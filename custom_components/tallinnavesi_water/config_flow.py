"""Config flow for the Tallinn Vesi water integration."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .api import (
    ReadingOverview,
    SupplyPoint,
    TallinnVesiApiClient,
    TallinnVesiApiError,
    TallinnVesiAuthError,
)
from .const import (
    CONF_ADDRESS,
    CONF_API_KEY,
    CONF_METER_NUMBER,
    CONF_SUPPLY_POINT_ID,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class TallinnVesiConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Tallinn Vesi water."""

    VERSION = 1

    _api_key: str | None = None
    _reauth_entry: config_entries.ConfigEntry | None = None
    _supply_points: list[dict[str, Any]] | None = None

    async def async_step_user(
        self, user_input: Mapping[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step where the user provides an API key."""

        errors: dict[str, str] = {}
        schema = vol.Schema({vol.Required(CONF_API_KEY): str})
        supply_points: list[SupplyPoint] = []
        overview_by_meter: dict[str, ReadingOverview] = {}

        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=schema)

        api_key = user_input[CONF_API_KEY].strip()
        client = TallinnVesiApiClient.for_hass(self.hass, api_key)

        try:
            supply_points = await client.async_get_supply_points()
        except TallinnVesiAuthError:
            errors["base"] = "invalid_auth"
        except TallinnVesiApiError:
            errors["base"] = "cannot_connect"
        else:
            self._supply_points = _build_supply_point_selections(supply_points)
            if not self._supply_points:
                errors["base"] = "no_supply_points"

        if not errors:
            try:
                overview = await client.async_get_overview_readings()
            except TallinnVesiApiError as err:
                _LOGGER.debug("Failed to fetch readings overview during setup: %s", err)
            else:
                overview_by_meter = _build_overview_by_meter(overview, supply_points)
                self._supply_points = _build_supply_point_selections(
                    supply_points, overview_by_meter
                )

        if errors:
            return self.async_show_form(
                step_id="user",
                data_schema=schema,
                errors=errors,
            )

        self._api_key = api_key
        assert self._supply_points is not None

        if len(self._supply_points) == 1:
            return await self._async_create_entry(self._supply_points[0])

        return await self.async_step_select_meter()

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> FlowResult:
        """Handle reauthentication when the stored API key stops working."""

        entry_id = self.context.get("entry_id")
        if entry_id is not None:
            self._reauth_entry = self.hass.config_entries.async_get_entry(entry_id)

        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: Mapping[str, Any] | None = None
    ) -> FlowResult:
        """Ask for and validate a replacement API key."""

        errors: dict[str, str] = {}
        schema = vol.Schema({vol.Required(CONF_API_KEY): str})

        if user_input is None:
            return self.async_show_form(
                step_id="reauth_confirm",
                data_schema=schema,
            )

        api_key = user_input[CONF_API_KEY].strip()
        if self._reauth_entry is None:
            return self.async_abort(reason="reauth_failed")

        client = TallinnVesiApiClient.for_hass(self.hass, api_key)
        expected_unique_id = _entry_unique_id(self._reauth_entry.data)
        errors = await _validate_reauth_api_key(
            client,
            supply_point_id=self._reauth_entry.data.get(CONF_SUPPLY_POINT_ID),
            meter_number=self._reauth_entry.data.get(CONF_METER_NUMBER),
        )

        if errors or not expected_unique_id:
            return self.async_show_form(
                step_id="reauth_confirm",
                data_schema=schema,
                errors=errors or {"base": "no_supply_points"},
            )

        matching_entry = await self.async_set_unique_id(
            expected_unique_id,
            raise_on_progress=False,
        )
        if (
            matching_entry is not None
            and matching_entry.entry_id != self._reauth_entry.entry_id
        ):
            return self.async_abort(reason="already_configured")

        if (
            self._reauth_entry.unique_id is not None
            and self._reauth_entry.unique_id != expected_unique_id
        ):
            return self.async_abort(reason="reauth_failed")

        return self.async_update_reload_and_abort(
            self._reauth_entry,
            unique_id=expected_unique_id,
            data={**self._reauth_entry.data, CONF_API_KEY: api_key},
        )

    async def async_step_select_meter(
        self, user_input: Mapping[str, Any] | None = None
    ) -> FlowResult:
        """Handle meter selection when multiple supply points exist."""

        assert self._supply_points is not None

        meter_map = {self._display_name(sp): sp for sp in self._supply_points}
        options = list(meter_map.keys())

        if user_input is not None:
            selected_display = user_input[CONF_METER_NUMBER]
            selected = meter_map.get(selected_display)
            if selected is not None:
                return await self._async_create_entry(selected)

        return self.async_show_form(
            step_id="select_meter",
            data_schema=vol.Schema({vol.Required(CONF_METER_NUMBER): vol.In(options)}),
        )

    async def _async_create_entry(self, selection: Mapping[str, Any]) -> FlowResult:
        """Create the config entry after validation."""

        assert self._api_key is not None

        meter_number = selection.get(CONF_METER_NUMBER)
        supply_point_id = selection.get(CONF_SUPPLY_POINT_ID)
        address = selection.get(CONF_ADDRESS)

        unique_id = supply_point_id or meter_number
        if unique_id:
            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured()

        data = {
            CONF_API_KEY: self._api_key,
            CONF_METER_NUMBER: meter_number,
        }
        if supply_point_id:
            data[CONF_SUPPLY_POINT_ID] = supply_point_id
        if address:
            data[CONF_ADDRESS] = address

        title = address or meter_number or "Tallinna Vesi"
        return self.async_create_entry(title=title, data=data)

    @staticmethod
    def _display_name(selection: Mapping[str, Any]) -> str:
        """Render a human-friendly display name for a supply point."""

        address = selection.get(CONF_ADDRESS)
        meter_nr = selection.get(CONF_METER_NUMBER)
        if address and meter_nr:
            return f"{address} ({meter_nr})"
        return address or meter_nr or "Smart meter"


def _build_overview_by_meter(
    overview: list[ReadingOverview], supply_points: list[SupplyPoint]
) -> dict[str, ReadingOverview]:
    """Keep only overview entries that match smart-meter supply points."""

    meter_numbers = {item.meter_number for item in supply_points if item.meter_number}
    return {
        item.meter_number: item
        for item in overview
        if item.meter_number and item.meter_number in meter_numbers
    }


def _build_supply_point_selections(
    supply_points: list[SupplyPoint],
    overview_by_meter: Mapping[str, ReadingOverview] | None = None,
) -> list[dict[str, str]]:
    """Build selectable smart-meter entries for the config flow."""

    selections: list[dict[str, str]] = []
    for supply_point in supply_points:
        if not supply_point.meter_number:
            continue

        overview = (
            overview_by_meter.get(supply_point.meter_number)
            if overview_by_meter is not None
            else None
        )
        address = supply_point.address or (overview.address if overview else None)

        selection = {CONF_METER_NUMBER: supply_point.meter_number}
        if supply_point.supply_point_id:
            selection[CONF_SUPPLY_POINT_ID] = supply_point.supply_point_id
        if address:
            selection[CONF_ADDRESS] = address
        selections.append(selection)

    return selections


def _entry_unique_id(entry_data: Mapping[str, Any]) -> str | None:
    """Return the unique ID used by stored entries."""

    return entry_data.get(CONF_SUPPLY_POINT_ID) or entry_data.get(CONF_METER_NUMBER)


def _has_supply_point_identity(
    supply_points: list[SupplyPoint],
    *,
    supply_point_id: str | None,
    meter_number: str | None,
) -> bool:
    """Return true when the replacement key can still access the configured entry."""

    if supply_point_id is not None:
        return any(
            supply_point.supply_point_id == supply_point_id
            for supply_point in supply_points
        )
    if meter_number is not None:
        return any(
            supply_point.meter_number == meter_number for supply_point in supply_points
        )
    if supply_point_id is None and meter_number is None:
        return bool(supply_points)
    return False


async def _validate_reauth_api_key(
    client: TallinnVesiApiClient,
    *,
    supply_point_id: str | None,
    meter_number: str | None,
) -> dict[str, str]:
    """Validate that a replacement key can access the configured entry."""

    try:
        supply_points = await client.async_get_supply_points()
    except TallinnVesiAuthError:
        return {"base": "invalid_auth"}
    except TallinnVesiApiError:
        return {"base": "cannot_connect"}

    if not _has_supply_point_identity(
        supply_points,
        supply_point_id=supply_point_id,
        meter_number=meter_number,
    ):
        return {"base": "no_supply_points"}

    return {}
