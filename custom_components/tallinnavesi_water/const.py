"""Constants for the Tallinn Vesi water integration."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.const import Platform

DOMAIN = "tallinnavesi_water"
PLATFORMS: list[Platform] = [Platform.SENSOR]
DEFAULT_UPDATE_INTERVAL = timedelta(hours=1)
CONF_SUPPLY_POINT_ID = "supply_point_id"
CONF_METER_NUMBER = "meter_number"
CONF_ADDRESS = "address"
CONF_API_KEY = "api_key"

API_BASE_URL = "https://klient.tallinnavesi.ee"
READINGS_OVERVIEW_ENDPOINT = "/api/Readings"
SMART_METER_READINGS_ENDPOINT = "/api/SmartMeter/GetSmartMeterReadings"
SMART_METER_SUPPLY_POINTS_ENDPOINT = "/api/SmartMeter/GetSupplyPointsWithSmartMeter"

SENSOR_KEY_TOTAL = "total"
SENSOR_KEY_DAILY = "daily"
