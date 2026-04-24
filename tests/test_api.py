"""Tests for the Tallinn Vesi API utilities."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from unittest.mock import AsyncMock, call

import pytest
from aiohttp import ClientError

from custom_components.tallinnavesi_water.api import (
    TallinnVesiApiClient,
    TallinnVesiApiError,
    TallinnVesiAuthError,
)
from custom_components.tallinnavesi_water.const import (
    API_BASE_URL,
    LEGACY_API_BASE_URL,
    SMART_METER_READINGS_ENDPOINT,
    SMART_METER_READINGS_PAGE_SIZE,
)


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
async def test_async_get_readings_uses_salesforce_query_defaults() -> None:
    client = TallinnVesiApiClient.__new__(TallinnVesiApiClient)
    client._session = None  # type: ignore[attr-defined]
    client._api_key = "secret"  # type: ignore[attr-defined]
    client._request = AsyncMock(  # type: ignore[attr-defined]
        return_value={
            "readings": [
                {
                    "reading": 10.0,
                    "readingDate": "2026-01-14T23:59:59Z",
                },
                {
                    "reading": 11.0,
                    "readingDate": "2026-01-15T06:45:00Z",
                },
            ]
        }
    )

    from_dt = datetime(2026, 1, 15, 6, 45, tzinfo=timezone.utc)

    result = await TallinnVesiApiClient.async_get_readings(client, "999999", from_dt)

    client._request.assert_awaited_once_with(
        "get",
        SMART_METER_READINGS_ENDPOINT,
        params={
            "meterNr": "999999",
            "pageNo": 1,
            "pageSize": SMART_METER_READINGS_PAGE_SIZE,
            "orderBy": "ReadingDate DESC",
        },
    )
    assert [reading.reading for reading in result.readings] == [11.0]


@pytest.mark.asyncio
async def test_async_get_readings_paginates_until_from_datetime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "custom_components.tallinnavesi_water.api.SMART_METER_READINGS_PAGE_SIZE",
        2,
    )
    client = TallinnVesiApiClient.__new__(TallinnVesiApiClient)
    client._session = None  # type: ignore[attr-defined]
    client._api_key = "secret"  # type: ignore[attr-defined]
    client._request = AsyncMock(  # type: ignore[attr-defined]
        side_effect=[
            {
                "meterNr": "999999",
                "readings": [
                    {"reading": 13.0, "readingDate": "2026-01-17T00:00:00Z"},
                    {"reading": 12.0, "readingDate": "2026-01-16T00:00:00Z"},
                ],
            },
            {
                "meterNr": "999999",
                "readings": [
                    {"reading": 11.0, "readingDate": "2026-01-15T00:00:00Z"},
                    {"reading": 10.0, "readingDate": "2026-01-14T00:00:00Z"},
                ],
            },
        ]
    )

    from_dt = datetime(2026, 1, 15, tzinfo=timezone.utc)

    result = await TallinnVesiApiClient.async_get_readings(client, "999999", from_dt)

    assert client._request.await_args_list == [
        call(
            "get",
            SMART_METER_READINGS_ENDPOINT,
            params={
                "meterNr": "999999",
                "pageNo": 1,
                "pageSize": 2,
                "orderBy": "ReadingDate DESC",
            },
        ),
        call(
            "get",
            SMART_METER_READINGS_ENDPOINT,
            params={
                "meterNr": "999999",
                "pageNo": 2,
                "pageSize": 2,
                "orderBy": "ReadingDate DESC",
            },
        ),
    ]
    assert [reading.reading for reading in result.readings] == [13.0, 12.0, 11.0]


@pytest.mark.asyncio
async def test_async_get_readings_stops_on_duplicate_pages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "custom_components.tallinnavesi_water.api.SMART_METER_READINGS_PAGE_SIZE",
        1,
    )
    client = TallinnVesiApiClient.__new__(TallinnVesiApiClient)
    client._session = None  # type: ignore[attr-defined]
    client._api_key = "secret"  # type: ignore[attr-defined]
    page = {
        "meterNr": "999999",
        "readings": [{"reading": 13.0, "readingDate": "2026-01-17T00:00:00Z"}],
    }
    client._request = AsyncMock(side_effect=[page, page])  # type: ignore[attr-defined]

    from_dt = datetime(2026, 1, 15, tzinfo=timezone.utc)

    result = await TallinnVesiApiClient.async_get_readings(client, "999999", from_dt)

    assert client._request.await_count == 2
    assert [reading.reading for reading in result.readings] == [13.0]


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


class _MockResponse:
    def __init__(self, status: int, payload: object, text: str = "") -> None:
        self.status = status
        self._payload = payload
        self._text = text

    async def __aenter__(self) -> "_MockResponse":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def json(self, *args: object, **kwargs: object) -> object:
        return self._payload

    async def text(self) -> str:
        return self._text


class _MockSession:
    def __init__(self, request_callable) -> None:
        self._request_callable = request_callable

    def request(self, method: str, url: str, **kwargs: object) -> _MockResponse:
        return self._request_callable(method, url, **kwargs)


@pytest.mark.asyncio
async def test_request_falls_back_to_legacy_base_url_on_new_api_auth_failure() -> None:
    client = TallinnVesiApiClient.__new__(TallinnVesiApiClient)
    client._api_key = "secret"  # type: ignore[attr-defined]
    client._base_url = API_BASE_URL  # type: ignore[attr-defined]

    calls: list[str] = []

    def request(method: str, url: str, **kwargs: object) -> _MockResponse:
        calls.append(url)
        if url.startswith(API_BASE_URL):
            return _MockResponse(401, {"status": "error"})
        return _MockResponse(200, {"results": []})

    client._session = _MockSession(request)  # type: ignore[attr-defined]

    payload = await TallinnVesiApiClient._request(client, "get", "/api/Readings")

    assert payload == {"results": []}
    assert calls == [
        f"{API_BASE_URL}/api/Readings",
        f"{LEGACY_API_BASE_URL}/api/Readings",
    ]
    assert client._base_url == LEGACY_API_BASE_URL  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_request_raises_auth_error_when_all_base_urls_fail(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = TallinnVesiApiClient.__new__(TallinnVesiApiClient)
    client._api_key = "secret"  # type: ignore[attr-defined]
    client._base_url = API_BASE_URL  # type: ignore[attr-defined]

    def request(method: str, url: str, **kwargs: object) -> _MockResponse:
        return _MockResponse(401, {"status": "error"})

    client._session = _MockSession(request)  # type: ignore[attr-defined]

    caplog.set_level(logging.WARNING)

    with pytest.raises(TallinnVesiAuthError, match="Authentication failed"):
        await TallinnVesiApiClient._request(client, "get", "/api/Readings")
    assert "astv2.my.site.com" in caplog.text
    assert "klient.tallinnavesi.ee" in caplog.text
    assert "authentication status 401" in caplog.text


@pytest.mark.asyncio
async def test_request_includes_response_error_detail(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = TallinnVesiApiClient.__new__(TallinnVesiApiClient)
    client._api_key = "secret"  # type: ignore[attr-defined]
    client._base_url = LEGACY_API_BASE_URL  # type: ignore[attr-defined]

    def request(method: str, url: str, **kwargs: object) -> _MockResponse:
        return _MockResponse(
            500,
            {"message": "Internal server error", "status": "error"},
        )

    client._session = _MockSession(request)  # type: ignore[attr-defined]

    caplog.set_level(logging.WARNING)

    with pytest.raises(
        TallinnVesiApiError,
        match="API request failed with status 500: Internal server error",
    ):
        await TallinnVesiApiClient._request(
            client, "get", "/api/SmartMeter/GetSmartMeterReadings"
        )
    assert "klient.tallinnavesi.ee" in caplog.text
    assert "API request failed with status 500: Internal server error" in caplog.text


@pytest.mark.asyncio
async def test_request_redacts_sensitive_response_error_detail(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = TallinnVesiApiClient.__new__(TallinnVesiApiClient)
    client._api_key = "secret"  # type: ignore[attr-defined]
    client._base_url = LEGACY_API_BASE_URL  # type: ignore[attr-defined]

    def request(method: str, url: str, **kwargs: object) -> _MockResponse:
        return _MockResponse(
            500,
            {
                "message": (
                    "Rejected X-API-Key: live-secret-value and "
                    "Authorization Bearer live-token-value"
                )
            },
        )

    client._session = _MockSession(request)  # type: ignore[attr-defined]

    caplog.set_level(logging.WARNING)

    with pytest.raises(TallinnVesiApiError) as err:
        await TallinnVesiApiClient._request(client, "get", "/api/Readings")

    assert "live-secret-value" not in str(err.value)
    assert "live-token-value" not in str(err.value)
    assert "live-secret-value" not in caplog.text
    assert "live-token-value" not in caplog.text
    assert "X-API-Key: <redacted>" in caplog.text
    assert "Authorization Bearer <redacted>" in caplog.text


@pytest.mark.asyncio
async def test_request_falls_back_to_legacy_base_url_on_network_error() -> None:
    client = TallinnVesiApiClient.__new__(TallinnVesiApiClient)
    client._api_key = "secret"  # type: ignore[attr-defined]
    client._base_url = API_BASE_URL  # type: ignore[attr-defined]

    calls: list[str] = []

    def request(method: str, url: str, **kwargs: object) -> _MockResponse:
        calls.append(url)
        if url.startswith(API_BASE_URL):
            raise ClientError("boom")
        return _MockResponse(200, {"results": []})

    client._session = _MockSession(request)  # type: ignore[attr-defined]

    payload = await TallinnVesiApiClient._request(client, "get", "/api/Readings")

    assert payload == {"results": []}
    assert calls == [
        f"{API_BASE_URL}/api/Readings",
        f"{LEGACY_API_BASE_URL}/api/Readings",
    ]


@pytest.mark.asyncio
async def test_request_reports_network_error_host_and_type(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = TallinnVesiApiClient.__new__(TallinnVesiApiClient)
    client._api_key = "secret"  # type: ignore[attr-defined]
    client._base_url = LEGACY_API_BASE_URL  # type: ignore[attr-defined]

    def request(method: str, url: str, **kwargs: object) -> _MockResponse:
        raise ClientError("boom")

    client._session = _MockSession(request)  # type: ignore[attr-defined]

    caplog.set_level(logging.WARNING)

    with pytest.raises(
        TallinnVesiApiError,
        match=(
            "Error communicating with Tallinna Vesi API at "
            "klient.tallinnavesi.ee: ClientError: boom"
        ),
    ):
        await TallinnVesiApiClient._request(client, "get", "/api/Readings")
    assert "klient.tallinnavesi.ee" in caplog.text
    assert "ClientError: boom" in caplog.text


@pytest.mark.asyncio
async def test_request_reports_timeout_error_host_and_type(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = TallinnVesiApiClient.__new__(TallinnVesiApiClient)
    client._api_key = "secret"  # type: ignore[attr-defined]
    client._base_url = LEGACY_API_BASE_URL  # type: ignore[attr-defined]

    def request(method: str, url: str, **kwargs: object) -> _MockResponse:
        raise asyncio.TimeoutError

    client._session = _MockSession(request)  # type: ignore[attr-defined]

    caplog.set_level(logging.WARNING)

    with pytest.raises(
        TallinnVesiApiError,
        match=(
            "Error communicating with Tallinna Vesi API at "
            "klient.tallinnavesi.ee: TimeoutError"
        ),
    ):
        await TallinnVesiApiClient._request(client, "get", "/api/Readings")
    assert "klient.tallinnavesi.ee" in caplog.text
    assert "TimeoutError" in caplog.text
