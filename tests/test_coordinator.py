"""Tests for coordinator helper functions."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from custom_components.tallinnavesi_water.api import SmartMeterReading
from custom_components.tallinnavesi_water.coordinator import (
    _calculate_daily_consumption,
    _pick_total_value,
)

_BASE_TIME = datetime(2024, 10, 1, 12, 0, 0, tzinfo=timezone.utc)


def _reading(total: float, hours_before: int = 0) -> SmartMeterReading:
    return SmartMeterReading(
        reading=total,
        reading_end=None,
        reading_date=_BASE_TIME - timedelta(hours=hours_before),
    )


def test_pick_total_value_prefers_reading_end() -> None:
    reading = SmartMeterReading(
        reading=10.0,
        reading_end=12.0,
        reading_date=_BASE_TIME,
    )
    assert _pick_total_value(reading) == 12.0


def test_pick_total_value_falls_back_to_reading() -> None:
    reading = SmartMeterReading(
        reading=15.0,
        reading_end=None,
        reading_date=_BASE_TIME,
    )
    assert _pick_total_value(reading) == 15.0


def test_calculate_daily_consumption_returns_delta() -> None:
    readings = [
        _reading(100.0, hours_before=30),
        _reading(110.0, hours_before=16),
        _reading(120.5, hours_before=2),
    ]
    latest_timestamp = readings[-1].reading_date

    result = _calculate_daily_consumption(readings, latest_timestamp)

    assert result is not None
    assert round(result, 3) == 10.5


def test_calculate_daily_consumption_handles_negative_delta() -> None:
    readings = [
        _reading(150.0, hours_before=20),
        _reading(140.0, hours_before=2),
    ]
    latest_timestamp = readings[-1].reading_date

    assert _calculate_daily_consumption(readings, latest_timestamp) is None


def test_calculate_daily_consumption_handles_missing_prior_total() -> None:
    readings = [_reading(50.0)]
    latest_timestamp = readings[-1].reading_date

    assert _calculate_daily_consumption(readings, latest_timestamp) is None


def test_calculate_daily_consumption_falls_back_to_same_day_baseline() -> None:
    midnight = _BASE_TIME.replace(hour=0)
    readings = [
        SmartMeterReading(
            reading=None,
            reading_end=200.0,
            reading_date=midnight + timedelta(hours=8),
        ),
        SmartMeterReading(
            reading=None,
            reading_end=200.25,
            reading_date=midnight + timedelta(hours=20),
        ),
    ]

    result = _calculate_daily_consumption(readings, readings[-1].reading_date)

    assert result == 0.25
