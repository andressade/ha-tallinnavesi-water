"""Tallinn Vesi API client helpers."""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, List, Mapping, Optional
from urllib.parse import urlparse

from aiohttp import ClientError, ClientSession, ClientTimeout
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util

from .const import (
    API_BASE_URL,
    LEGACY_API_BASE_URL,
    READINGS_OVERVIEW_ENDPOINT,
    SMART_METER_READINGS_ENDPOINT,
    SMART_METER_READINGS_PAGE_SIZE,
    SMART_METER_SUPPLY_POINTS_ENDPOINT,
)

DEFAULT_TIMEOUT: Final = ClientTimeout(total=30)
MAX_SMART_METER_READING_PAGES: Final = 10
SMART_METER_READINGS_ORDER_BY: Final = "ReadingDate DESC"
SENSITIVE_ERROR_PATTERNS: Final = (
    (
        re.compile(
            r"(?i)(authorization)(\s+)(bearer|basic)(\s+)([^\s\"',;]+)"
        ),
        r"\1\2\3\4<redacted>",
    ),
    (
        re.compile(r"(?i)(bearer)(\s+)([^\s\"',;]+)"),
        r"\1\2<redacted>",
    ),
    (
        re.compile(
            r"(?i)(x-api-key|api[_ -]?key|token|secret)"
            r"([\"'\s:=]+)([^\s\"',;]+)"
        ),
        r"\1\2<redacted>",
    ),
)
_LOGGER = logging.getLogger(__name__)


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
        self._base_url = API_BASE_URL

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

        readings: list[SmartMeterReading] = []
        from_datetime_utc = (
            dt_util.as_utc(from_datetime) if from_datetime is not None else None
        )
        meter_number_result: Optional[str] = None
        supply_point_id: Optional[str] = None
        errors: list[str] = []
        seen_pages: set[tuple[Any, ...]] = set()

        for page_no in range(1, MAX_SMART_METER_READING_PAGES + 1):
            params: dict[str, Any] = {
                "meterNr": meter_number,
                "pageNo": page_no,
                "pageSize": SMART_METER_READINGS_PAGE_SIZE,
                "orderBy": SMART_METER_READINGS_ORDER_BY,
            }

            payload = await self._request(
                "get", SMART_METER_READINGS_ENDPOINT, params=params
            )
            meter_number_result = meter_number_result or _multi_get(
                payload, "MeterNr", "meterNr"
            )
            supply_point_id = supply_point_id or _multi_get(
                payload, "SupplyPointId", "supplyPointId"
            )
            errors.extend(_multi_get(payload, "Errors", "errors") or [])

            readings_payload = _multi_get(payload, "Readings", "readings") or []
            if not readings_payload:
                break

            page_signature = tuple(
                (
                    _multi_get(item, "ReadingDate", "readingDate"),
                    _multi_get(item, "Reading", "reading"),
                    _multi_get(item, "ReadingEnd", "readingEnd"),
                )
                for item in readings_payload
            )
            if page_signature in seen_pages:
                break
            seen_pages.add(page_signature)

            page_readings: list[SmartMeterReading] = []
            for item in readings_payload:
                reading_date_raw = _multi_get(item, "ReadingDate", "readingDate")
                reading_date = dt_util.parse_datetime(reading_date_raw)
                if reading_date is None:
                    continue
                reading_date_utc = dt_util.as_utc(reading_date)
                page_readings.append(
                    SmartMeterReading(
                        reading=_coerce_float(_multi_get(item, "Reading", "reading")),
                        reading_end=_coerce_float(
                            _multi_get(item, "ReadingEnd", "readingEnd")
                        ),
                        reading_date=reading_date_utc,
                    )
                )

            readings.extend(
                reading
                for reading in page_readings
                if from_datetime_utc is None or reading.reading_date >= from_datetime_utc
            )

            if from_datetime_utc is None:
                break
            if len(readings_payload) < SMART_METER_READINGS_PAGE_SIZE:
                break
            if _page_crosses_from_datetime(page_readings, from_datetime_utc):
                break

        return SmartMeterReadingsResult(
            readings=readings,
            meter_number=meter_number_result,
            supply_point_id=supply_point_id,
            errors=errors,
        )

    async def _request(
        self,
        method: str,
        endpoint: str,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """Execute an HTTP request to the Tallinna Vesi API."""

        base_urls = [self._base_url]
        if self._base_url == API_BASE_URL:
            base_urls.append(LEGACY_API_BASE_URL)

        auth_error: TallinnVesiAuthError | None = None
        client_error: TallinnVesiApiError | None = None
        for base_url in base_urls:
            url = f"{base_url}{endpoint}"
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
                        host = urlparse(base_url).netloc or base_url
                        _LOGGER.warning(
                            "Tallinn Vesi request to %s failed: authentication status %s",
                            host,
                            response.status,
                        )
                        auth_error = TallinnVesiAuthError("Authentication failed")
                        continue
                    if response.status >= 400:
                        message = f"API request failed with status {response.status}"
                        detail = await _response_error_detail(response)
                        if detail:
                            message = f"{message}: {detail}"
                        host = urlparse(base_url).netloc or base_url
                        _LOGGER.warning(
                            "Tallinn Vesi request to %s failed: %s",
                            host,
                            message,
                        )
                        raise TallinnVesiApiError(message)
                    if response.content_type != "application/json":
                        host = urlparse(base_url).netloc or base_url
                        message = (
                            "API returned unexpected content type "
                            f"{response.content_type or 'unknown'}"
                        )
                        _LOGGER.warning(
                            "Tallinn Vesi request to %s failed: %s",
                            host,
                            message,
                        )
                        client_error = TallinnVesiApiError(message)
                        if auth_error is not None:
                            continue
                        if base_url == base_urls[-1]:
                            raise client_error
                        continue
                    payload = await response.json()
            except (ClientError, asyncio.TimeoutError) as err:
                host = urlparse(base_url).netloc or base_url
                error_detail = _redact_error_detail(str(err))[:300]
                client_error = TallinnVesiApiError(
                    "Error communicating with Tallinna Vesi API at "
                    f"{host}: {err.__class__.__name__}: {error_detail}"
                )
                _LOGGER.warning(
                    "Tallinn Vesi request to %s failed: %s: %s",
                    host,
                    err.__class__.__name__,
                    error_detail,
                )
                if base_url == base_urls[-1]:
                    raise client_error from err
                continue

            if base_url != self._base_url:
                _LOGGER.warning(
                    "Tallinn Vesi new API rejected the configured key; falling back to legacy endpoint"
                )
                self._base_url = base_url
            return payload

        if auth_error is not None:
            raise auth_error
        if client_error is not None:
            raise client_error
        raise TallinnVesiApiError("Error communicating with Tallinna Vesi API")

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


async def _response_error_detail(response: Any) -> str | None:
    """Extract a short non-secret error detail from an API response."""

    try:
        payload = await response.json(content_type=None)
    except (ClientError, ValueError, TypeError):
        try:
            text = await response.text()
        except (ClientError, UnicodeDecodeError):
            return None
        return _redact_error_detail(text)[:300] if text else None

    if isinstance(payload, Mapping):
        detail = _multi_get(payload, "message", "error", "status")
        if detail:
            return _redact_error_detail(str(detail))[:300]
    return None


def _redact_error_detail(detail: str) -> str:
    """Redact credential-like values from upstream error details."""

    redacted = detail
    for pattern, replacement in SENSITIVE_ERROR_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted


def _page_crosses_from_datetime(
    readings: list[SmartMeterReading], from_datetime: datetime
) -> bool:
    """Return true when a descending page has reached older readings."""

    if len(readings) < 2:
        return False

    first = readings[0].reading_date
    last = readings[-1].reading_date
    return first >= last and last < from_datetime


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
