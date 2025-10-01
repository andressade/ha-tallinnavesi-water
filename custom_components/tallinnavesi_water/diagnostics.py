"""Diagnostics support for Tallinn Vesi water integration."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import ConsumptionData, TallinnVesiDataUpdateCoordinator


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""

    coordinator: TallinnVesiDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    data: ConsumptionData | None = coordinator.data
    serialized_readings: list[dict[str, Any]] = []
    if data:
        serialized_readings = [
            {
                "reading": reading.reading,
                "reading_end": reading.reading_end,
                "reading_date": reading.reading_date.isoformat(),
            }
            for reading in data.readings[-50:]
        ]

    return {
        "meter_number": data.meter_number if data else None,
        "supply_point_id": data.supply_point_id if data else None,
        "latest_total": data.latest_total if data else None,
        "latest_timestamp": data.latest_timestamp.isoformat()
        if data and data.latest_timestamp
        else None,
        "daily_consumption": data.daily_consumption if data else None,
        "recent_readings": serialized_readings,
    }
