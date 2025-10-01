"""Tallinn Vesi API client helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, List, Mapping, Optional

from aiohttp import ClientError, ClientSession, ClientTimeout
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util

from .const import (
    API_BASE_URL,
    READINGS_OVERVIEW_ENDPOINT,
    SMART_METER_READINGS_ENDPOINT,
    SMART_METER_SUPPLY_POINTS_ENDPOINT,
)

DEFAULT_TIMEOUT: Final = ClientTimeout(total=30)


class TallinnVesiApiError(Exception):
    """Base error for Tallinn Vesi API."""


class TallinnVesiAuthError(TallinnVesiApiError):
    """Raised when authentication fails."""


@dataclass(slots=True)
class SupplyPoint:
    """Representation of a smart meter supply point."""

    meter_number: Optional[str]
    supply_point_id: Optional[str]
    object_id: Optional[str]
    address: Optional[str]


@dataclass(slots=True)
class SmartMeterReading:
    """Single smart meter reading data point."""

    reading: Optional[float]
    reading_end: Optional[float]
    reading_date: datetime


@dataclass(slots=True)
class SmartMeterReadingsResult:
    """Payload returned when requesting smart meter readings."""

    readings: List[SmartMeterReading]
    meter_number: Optional[str]
    supply_point_id: Optional[str]
    errors: list[str]


@dataclass(slots=True)
class ReadingOverview:
    """Overview item returned by the /api/Readings endpoint."""

    address: Optional[str]
    meter_number: Optional[str]
    meter_type: Optional[str]
    last_reading: Optional[float]
    last_reading_date: Optional[datetime]


class TallinnVesiApiClient:
    """Asynchronous API client for Tallinna Vesi."""

    def __init__(self, session: ClientSession, api_key: str) -> None:
        self._session = session
        self._api_key = api_key

    @classmethod
    def for_hass(cls, hass: HomeAssistant, api_key: str) -> "TallinnVesiApiClient":
        """Factory helper to build a client using Home Assistant's shared session."""

        session = async_get_clientsession(hass)
        return cls(session, api_key)

    async def async_get_supply_points(self) -> list[SupplyPoint]:
        """Fetch available supply points for the API key."""

        payload = await self._request("get", SMART_METER_SUPPLY_POINTS_ENDPOINT)
        supply_points: list[SupplyPoint] = []
        for item in payload or []:
            supply_points.append(
                SupplyPoint(
                    meter_number=_multi_get(item, "MeterNr", "meterNr"),
                    supply_point_id=_multi_get(item, "SupplyPointId", "supplyPointId"),
                    object_id=_multi_get(item, "ObjectId", "objectId"),
                    address=_multi_get(item, "Address", "address"),
                )
            )
        return supply_points

    async def async_get_overview_readings(self) -> list[ReadingOverview]:
        """Fetch reading overview entries (last manual/smart readings per meter)."""

        payload = await self._request("get", READINGS_OVERVIEW_ENDPOINT)
        results = _multi_get(payload, "Results", "results") or []

        overview: list[ReadingOverview] = []
        for item in results:
            overview.append(
                ReadingOverview(
                    address=_multi_get(item, "Address", "address"),
                    meter_number=_multi_get(item, "MeterNr", "meterNr"),
                    meter_type=_multi_get(item, "MeterType", "meterType"),
                    last_reading=_coerce_float(_multi_get(item, "LastReading", "lastReading")),
                    last_reading_date=_parse_overview_date(
                        _multi_get(item, "LastReadingDate", "lastReadingDate")
                    ),
                )
            )

        return overview

    async def async_get_readings(
        self, meter_number: str, from_datetime: datetime | None
    ) -> SmartMeterReadingsResult:
        """Fetch smart meter readings from optional start date."""

        params: dict[str, Any] = {"meterNr": meter_number}
        if from_datetime is not None:
            params["from"] = self._format_datetime(from_datetime)

        payload = await self._request("get", SMART_METER_READINGS_ENDPOINT, params=params)
        readings_payload = _multi_get(payload, "Readings", "readings") or []
        readings: list[SmartMeterReading] = []
        for item in readings_payload:
            reading_date_raw = _multi_get(item, "ReadingDate", "readingDate")
            reading_date = dt_util.parse_datetime(reading_date_raw)
            if reading_date is None:
                continue
            readings.append(
                SmartMeterReading(
                    reading=_coerce_float(_multi_get(item, "Reading", "reading")),
                    reading_end=_coerce_float(
                        _multi_get(item, "ReadingEnd", "readingEnd")
                    ),
                    reading_date=dt_util.as_utc(reading_date),
                )
            )

        return SmartMeterReadingsResult(
            readings=readings,
            meter_number=_multi_get(payload, "MeterNr", "meterNr"),
            supply_point_id=_multi_get(payload, "SupplyPointId", "supplyPointId"),
            errors=list(_multi_get(payload, "Errors", "errors") or []),
        )

    async def _request(
        self,
        method: str,
        endpoint: str,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """Execute an HTTP request to the Tallinna Vesi API."""

        url = f"{API_BASE_URL}{endpoint}"
        headers = {"X-API-Key": self._api_key}

        try:
            async with self._session.request(
                method,
                url,
                headers=headers,
                params=params,
                timeout=DEFAULT_TIMEOUT,
            ) as response:
                if response.status in (401, 403):
                    raise TallinnVesiAuthError("Authentication failed")
                if response.status >= 400:
                    raise TallinnVesiApiError(
                        f"API request failed with status {response.status}"
                    )
                return await response.json()
        except ClientError as err:
            raise TallinnVesiApiError("Error communicating with Tallinna Vesi API") from err

    @staticmethod
    def _format_datetime(value: datetime) -> str:
        """Format datetime for API query."""

        return dt_util.as_utc(value).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _coerce_float(value: Any) -> Optional[float]:
    """Convert API numeric value to float when possible."""

    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _multi_get(mapping: Mapping[str, Any], *keys: str) -> Any:
    """Try multiple key variants when reading API payloads."""

    for key in keys:
        if key in mapping:
            return mapping[key]
    return None


def _parse_overview_date(value: Any) -> Optional[datetime]:
    """Parse overview date strings that may not include time."""

    if value is None:
        return None

    if isinstance(value, datetime):
        return dt_util.as_utc(value)

    if isinstance(value, str):
        parsed = dt_util.parse_datetime(value)
        if parsed is not None:
            return dt_util.as_utc(parsed)
        # Handle "dd.mm.yyyy" format returned by the overview endpoint.
        try:
            parsed = datetime.strptime(value, "%d.%m.%Y")
        except ValueError:
            return None
        return dt_util.as_utc(parsed.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE))

    return None
