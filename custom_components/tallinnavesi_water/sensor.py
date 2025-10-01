"""Sensor platform for Tallinn Vesi water usage."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_ADDRESS,
    CONF_METER_NUMBER,
    CONF_SUPPLY_POINT_ID,
    DOMAIN,
    SENSOR_KEY_DAILY,
    SENSOR_KEY_TOTAL,
)
from .coordinator import ConsumptionData, TallinnVesiDataUpdateCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Tallinn Vesi sensors based on a config entry."""

    coordinator: TallinnVesiDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    sensors = [
        TallinnVesiTotalSensor(coordinator, entry),
        TallinnVesiDailySensor(coordinator, entry),
    ]

    async_add_entities(sensors)


class TallinnVesiBaseSensor(CoordinatorEntity[TallinnVesiDataUpdateCoordinator], SensorEntity):
    """Base entity shared behaviour."""

    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.WATER
    _attr_native_unit_of_measurement = UnitOfVolume.CUBIC_METERS

    def __init__(self, coordinator: TallinnVesiDataUpdateCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._meter_number = entry.data.get(CONF_METER_NUMBER)
        self._supply_point_id = entry.data.get(CONF_SUPPLY_POINT_ID)
        self._address = entry.data.get(CONF_ADDRESS)

    @property
    def device_info(self) -> DeviceInfo:
        identifiers = {(DOMAIN, self._supply_point_id or self._meter_number)}
        device_name = self._address or "Tallinn Vesi smart meter"
        return DeviceInfo(
            identifiers=identifiers,
            name=device_name,
            manufacturer="Tallinna Vesi",
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data
        if not data:
            return {}
        attributes: dict[str, Any] = {
            "meter_number": data.meter_number,
            "supply_point_id": data.supply_point_id,
        }
        if data.latest_timestamp is not None:
            attributes["last_updated"] = data.latest_timestamp.isoformat()
        return attributes


class TallinnVesiTotalSensor(TallinnVesiBaseSensor):
    """Cumulative meter reading sensor."""

    _attr_translation_key = "total_water_consumption"
    _attr_unique_id_suffix = SENSOR_KEY_TOTAL
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    @property
    def unique_id(self) -> str | None:
        base = self._supply_point_id or self._meter_number
        if base is None:
            return None
        return f"{base}_{self._attr_unique_id_suffix}"

    @property
    def native_value(self) -> float | None:
        data: ConsumptionData | None = self.coordinator.data
        return data.latest_total if data else None


class TallinnVesiDailySensor(TallinnVesiBaseSensor):
    """Daily water consumption sensor based on delta."""

    _attr_translation_key = "daily_water_usage"
    _attr_unique_id_suffix = SENSOR_KEY_DAILY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_device_class = None

    @property
    def device_class(self) -> SensorDeviceClass | None:
        """Daily usage is a consumptive delta, so omit device class."""

        return None

    @property
    def unique_id(self) -> str | None:
        base = self._supply_point_id or self._meter_number
        if base is None:
            return None
        return f"{base}_{self._attr_unique_id_suffix}"

    @property
    def native_value(self) -> float | None:
        data: ConsumptionData | None = self.coordinator.data
        return data.daily_consumption if data else None

    @property
    def suggested_unit_of_measurement(self) -> str | None:
        return UnitOfVolume.CUBIC_METERS
