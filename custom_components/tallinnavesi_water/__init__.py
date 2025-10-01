"""Tallinn Vesi water consumption integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType

from .api import TallinnVesiApiClient
from .const import (
    CONF_API_KEY,
    CONF_METER_NUMBER,
    DOMAIN,
    PLATFORMS,
)
from .coordinator import TallinnVesiDataUpdateCoordinator


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up via configuration.yaml is not supported."""

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Tallinn Vesi integration from a config entry."""

    hass.data.setdefault(DOMAIN, {})

    api_key: str = entry.data[CONF_API_KEY]
    meter_number: str = entry.data[CONF_METER_NUMBER]

    api_client = TallinnVesiApiClient.for_hass(hass, api_key)
    coordinator = TallinnVesiDataUpdateCoordinator(
        hass,
        entry=entry,
        api=api_client,
        meter_number=meter_number,
    )

    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload an integration entry."""

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle config entry updates by reloading the entry."""

    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)
