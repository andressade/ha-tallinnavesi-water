"""Data coordinator for Tallinn Vesi water consumption."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    SmartMeterReading,
    TallinnVesiApiClient,
    TallinnVesiApiError,
    TallinnVesiAuthError,
)
from .const import DEFAULT_UPDATE_INTERVAL

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class ConsumptionData:
    """Container for processed consumption metrics."""

    meter_number: str
    supply_point_id: str | None
    latest_total: float | None
    latest_timestamp: datetime | None
    daily_consumption: float | None
    readings: list[SmartMeterReading]


class TallinnVesiDataUpdateCoordinator(DataUpdateCoordinator[ConsumptionData]):
    """Coordinator that periodically retrieves water consumption."""

    def __init__(
        self,
        hass: HomeAssistant,
        *,
        entry: ConfigEntry,
        api: TallinnVesiApiClient,
        meter_number: str,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name="Tallinn Vesi water",
            update_interval=DEFAULT_UPDATE_INTERVAL,
        )
        self._api = api
        self._entry = entry
        self._meter_number = meter_number

    async def _async_update_data(self) -> ConsumptionData:
        """Fetch the latest data from the API."""

        try:
            # Request a rolling 14-day window to compute daily deltas robustly.
            from_dt = dt_util.utcnow() - timedelta(days=14)
            result = await self._api.async_get_readings(self._meter_number, from_dt)
        except TallinnVesiAuthError as err:
            raise ConfigEntryAuthFailed from err
        except TallinnVesiApiError as err:
            raise UpdateFailed(err) from err

        if result.errors:
            _LOGGER.debug("Tallinn Vesi API reported errors: %s", result.errors)

        readings = sorted(result.readings, key=lambda item: item.reading_date)

        latest_total: float | None = None
        latest_timestamp: datetime | None = None
        if readings:
            latest_reading = readings[-1]
            latest_total = _pick_total_value(latest_reading)
            latest_timestamp = latest_reading.reading_date

        daily_consumption = _calculate_daily_consumption(readings, latest_timestamp)

        return ConsumptionData(
            meter_number=result.meter_number or self._meter_number,
            supply_point_id=result.supply_point_id,
            latest_total=latest_total,
            latest_timestamp=latest_timestamp,
            daily_consumption=daily_consumption,
            readings=readings,
        )


def _pick_total_value(reading: SmartMeterReading) -> float | None:
    """Pick the most appropriate total reading value."""

    if reading.reading_end is not None:
        return reading.reading_end
    return reading.reading


def _calculate_daily_consumption(
    readings: list[SmartMeterReading], latest_timestamp: datetime | None
) -> float | None:
    """Calculate daily consumption based on the most recent readings."""

    if not readings or latest_timestamp is None:
        return None

    latest_total = _pick_total_value(readings[-1])
    if latest_total is None:
        return None

    local_latest = dt_util.as_local(latest_timestamp)
    start_of_day_local = dt_util.start_of_local_day(local_latest)
    start_of_day_utc = dt_util.as_utc(start_of_day_local)

    prior_total: float | None = None
    for reading in reversed(readings):
        if reading.reading_date <= start_of_day_utc:
            prior_total = _pick_total_value(reading)
            if prior_total is not None:
                break

    if prior_total is None:
        return None

    consumption = latest_total - prior_total
    if consumption < 0:
        _LOGGER.debug(
            "Ignoring negative consumption derived from readings: %s", consumption
        )
        return None
    return consumption
