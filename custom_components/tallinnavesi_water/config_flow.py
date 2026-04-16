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
