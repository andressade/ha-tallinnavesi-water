"""Tests for the Tallinn Vesi API utilities."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from custom_components.tallinnavesi_water.api import TallinnVesiApiClient


def test_format_datetime_generates_zulu_timestamp() -> None:
    dt_value = datetime(2024, 9, 24, 15, 30, tzinfo=timezone.utc)

    formatted = TallinnVesiApiClient._format_datetime(dt_value)

    assert formatted == "2024-09-24T15:30:00Z"


@pytest.mark.asyncio
async def test_async_get_supply_points_accepts_lowercase_keys() -> None:
    client = TallinnVesiApiClient.__new__(TallinnVesiApiClient)
    client._session = None  # type: ignore[attr-defined]
    client._api_key = "secret"  # type: ignore[attr-defined]
    client._request = AsyncMock(  # type: ignore[attr-defined]
        return_value=[
            {
                "meterNr": "999999",
                "supplyPointId": "79029",
                "objectId": "O057213",
                "address": "Vihu 12, 13522 Tallinn",
            }
        ]
    )

    supply_points = await TallinnVesiApiClient.async_get_supply_points(client)

    assert len(supply_points) == 1
    sp = supply_points[0]
    assert sp.meter_number == "999999"
    assert sp.supply_point_id == "79029"
    assert sp.object_id == "O057213"
    assert sp.address == "Vihu 12, 13522 Tallinn"


@pytest.mark.asyncio
async def test_async_get_readings_accepts_lowercase_keys() -> None:
    payload = {
        "meterNr": "999999",
        "supplyPointId": "79029",
        "readings": [
            {
                "reading": 25.75,
                "readingEnd": 25.94,
                "readingDate": "2023-10-01T18:48:50+00:00",
            }
        ],
    }

    client = TallinnVesiApiClient.__new__(TallinnVesiApiClient)
    client._session = None  # type: ignore[attr-defined]
    client._api_key = "secret"  # type: ignore[attr-defined]
    client._request = AsyncMock(return_value=payload)  # type: ignore[attr-defined]

    response = await TallinnVesiApiClient.async_get_readings(client, "999999", None)

    assert response.meter_number == "999999"
    assert response.supply_point_id == "79029"
    assert response.errors == []
    assert len(response.readings) == 1
    reading = response.readings[0]
    assert reading.reading == pytest.approx(25.75)
    assert reading.reading_end == pytest.approx(25.94)
    assert str(reading.reading_date.tzinfo) == "UTC"


@pytest.mark.asyncio
async def test_async_get_overview_readings_parses_smart_meter_entries() -> None:
    payload = {
        "results": [
            {
                "address": "Vihu 12, 13522 Tallinn",
                "meterNr": "999999",
                "lastReading": 425,
                "lastReadingDate": "31.08.2025",
                "meterType": "smart",
            },
            {
                "address": "Manual meter",
                "meterNr": "555555",
                "lastReading": 50,
                "meterType": "manual",
            },
        ]
    }

    client = TallinnVesiApiClient.__new__(TallinnVesiApiClient)
    client._session = None  # type: ignore[attr-defined]
    client._api_key = "secret"  # type: ignore[attr-defined]
    client._request = AsyncMock(return_value=payload)  # type: ignore[attr-defined]

    overview = await TallinnVesiApiClient.async_get_overview_readings(client)

    assert len(overview) == 2
    smart_entry = overview[0]
    assert smart_entry.meter_number == "999999"
    assert smart_entry.meter_type == "smart"
    assert smart_entry.last_reading == pytest.approx(425)
    assert smart_entry.last_reading_date is not None
    assert smart_entry.last_reading_date.tzinfo is not None
