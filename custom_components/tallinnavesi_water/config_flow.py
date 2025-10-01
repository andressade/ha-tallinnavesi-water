"""Config flow for the Tallinn Vesi water integration."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .api import (
    ReadingOverview,
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


class TallinnVesiConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Tallinn Vesi water."""

    VERSION = 1

    _api_key: str | None = None
    _supply_points: list[dict[str, Any]] | None = None
    _overview_by_meter: dict[str, ReadingOverview] | None = None

    async def async_step_user(
        self, user_input: Mapping[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step where the user provides an API key."""

        errors: dict[str, str] = {}
        schema = vol.Schema({vol.Required(CONF_API_KEY): str})
        smart_overview: list[ReadingOverview] = []

        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=schema)

        api_key = user_input[CONF_API_KEY].strip()
        client = TallinnVesiApiClient.for_hass(self.hass, api_key)

        try:
            overview = await client.async_get_overview_readings()
        except TallinnVesiAuthError:
            errors["base"] = "invalid_auth"
        except TallinnVesiApiError:
            errors["base"] = "cannot_connect"
        else:
            smart_overview = [
                item
                for item in overview
                if (item.meter_type or "").lower() == "smart"
            ]
            if not smart_overview:
                errors["base"] = "no_smart_meter"

        supply_points: list[Any] | None = None
        if not errors:
            try:
                supply_points = await client.async_get_supply_points()
            except TallinnVesiApiError:
                errors["base"] = "cannot_connect"
            else:
                if not supply_points:
                    errors["base"] = "no_supply_points"

        if errors:
            return self.async_show_form(
                step_id="user",
                data_schema=schema,
                errors=errors,
            )

        self._api_key = api_key
        overview_map = {
            item.meter_number: item for item in smart_overview if item.meter_number
        }
        self._overview_by_meter = overview_map or None

        supply_points = supply_points or []

        if overview_map:
            self._supply_points = [
                {
                    CONF_SUPPLY_POINT_ID: sp.supply_point_id,
                    CONF_METER_NUMBER: sp.meter_number,
                    CONF_ADDRESS: sp.address
                    or overview_map[sp.meter_number].address,
                }
                for sp in supply_points
                if sp.meter_number in overview_map
            ]
        else:
            self._supply_points = [
                {
                    CONF_SUPPLY_POINT_ID: sp.supply_point_id,
                    CONF_METER_NUMBER: sp.meter_number,
                    CONF_ADDRESS: sp.address,
                }
                for sp in supply_points
            ]

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
