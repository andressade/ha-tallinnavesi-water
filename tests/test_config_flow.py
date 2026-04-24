"""Tests for config-flow helper logic."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from homeassistant.helpers.typing import UNDEFINED

from custom_components.tallinnavesi_water.api import (
    ReadingOverview,
    SupplyPoint,
    TallinnVesiApiError,
    TallinnVesiAuthError,
    TallinnVesiApiClient,
)
from custom_components.tallinnavesi_water.config_flow import (
    TallinnVesiConfigFlow,
    _build_overview_by_meter,
    _build_supply_point_selections,
    _entry_unique_id,
    _has_supply_point_identity,
    _validate_reauth_api_key,
)
from custom_components.tallinnavesi_water.const import (
    CONF_ADDRESS,
    CONF_API_KEY,
    CONF_METER_NUMBER,
    CONF_SUPPLY_POINT_ID,
)


class _FakeFlowManager:
    def async_progress_by_handler(self, *args, **kwargs):
        return []

    def async_abort(self, flow_id):
        return None


class _FakeConfigEntries:
    def __init__(self, entry):
        self.entry = entry
        self.flow = _FakeFlowManager()
        self.reloads = []

    def async_get_entry(self, entry_id):
        if entry_id == self.entry.entry_id:
            return self.entry
        return None

    def async_entry_for_domain_unique_id(self, handler, unique_id):
        if unique_id == self.entry.unique_id:
            return self.entry
        return None

    def async_update_entry(
        self,
        *,
        entry,
        unique_id=UNDEFINED,
        title=UNDEFINED,
        data=UNDEFINED,
        options=UNDEFINED,
    ):
        changed = False
        if unique_id is not UNDEFINED and entry.unique_id != unique_id:
            entry.unique_id = unique_id
            changed = True
        if data is not UNDEFINED and entry.data != data:
            entry.data = data
            changed = True
        return changed

    def async_schedule_reload(self, entry_id):
        self.reloads.append(entry_id)


def _make_reauth_flow(entry):
    flow = TallinnVesiConfigFlow()
    flow.hass = SimpleNamespace(config_entries=_FakeConfigEntries(entry))
    flow.context = {"entry_id": entry.entry_id}
    return flow


def test_build_overview_by_meter_matches_supply_points_without_meter_type_filter() -> None:
    supply_points = [
        SupplyPoint(
            meter_number="07179527",
            supply_point_id="KP-001234",
            object_id="obj-1",
            address=None,
        )
    ]
    overview = [
        ReadingOverview(
            address="Pärnu mnt 10, Tallinn",
            meter_number="07179527",
            meter_type="Mechanical",
            last_reading=1234.56,
            last_reading_date=None,
        ),
        ReadingOverview(
            address="Manual meter",
            meter_number="555555",
            meter_type="Manual",
            last_reading=50.0,
            last_reading_date=None,
        ),
    ]

    overview_by_meter = _build_overview_by_meter(overview, supply_points)

    assert list(overview_by_meter) == ["07179527"]
    assert overview_by_meter["07179527"].meter_type == "Mechanical"


def test_build_supply_point_selections_uses_overview_address_fallback() -> None:
    supply_points = [
        SupplyPoint(
            meter_number="07179527",
            supply_point_id="KP-001234",
            object_id="obj-1",
            address=None,
        ),
        SupplyPoint(
            meter_number=None,
            supply_point_id="KP-missing-meter",
            object_id="obj-2",
            address="Should be skipped",
        ),
    ]
    overview_by_meter = {
        "07179527": ReadingOverview(
            address="Tedre tn 73, Tallinn",
            meter_number="07179527",
            meter_type="Mechanical",
            last_reading=1200.0,
            last_reading_date=None,
        )
    }

    selections = _build_supply_point_selections(supply_points, overview_by_meter)

    assert selections == [
        {
            CONF_METER_NUMBER: "07179527",
            CONF_SUPPLY_POINT_ID: "KP-001234",
            CONF_ADDRESS: "Tedre tn 73, Tallinn",
        }
    ]


def test_entry_unique_id_prefers_supply_point_id() -> None:
    assert (
        _entry_unique_id(
            {
                CONF_SUPPLY_POINT_ID: "KP-001234",
                CONF_METER_NUMBER: "07179527",
            }
        )
        == "KP-001234"
    )
    assert _entry_unique_id({CONF_METER_NUMBER: "07179527"}) == "07179527"


def test_has_supply_point_identity_matches_existing_entry() -> None:
    supply_points = [
        SupplyPoint(
            meter_number="07179527",
            supply_point_id="KP-001234",
            object_id="obj-1",
            address=None,
        )
    ]

    assert (
        _has_supply_point_identity(
            supply_points,
            supply_point_id="KP-001234",
            meter_number="999999",
        )
        is True
    )
    assert (
        _has_supply_point_identity(
            supply_points,
            supply_point_id="KP-wrong",
            meter_number="07179527",
        )
        is False
    )
    assert (
        _has_supply_point_identity(
            supply_points,
            supply_point_id=None,
            meter_number="07179527",
        )
        is True
    )
    assert (
        _has_supply_point_identity(
            supply_points,
            supply_point_id=None,
            meter_number="999999",
        )
        is False
    )
    assert (
        _has_supply_point_identity(
            supply_points,
            supply_point_id=None,
            meter_number=None,
        )
        is True
    )
    assert (
        _has_supply_point_identity([], supply_point_id=None, meter_number=None) is False
    )


@pytest.mark.asyncio
async def test_validate_reauth_api_key_accepts_existing_supply_point() -> None:
    client = AsyncMock()
    client.async_get_supply_points.return_value = [
        SupplyPoint(
            meter_number="07179527",
            supply_point_id="KP-001234",
            object_id="obj-1",
            address=None,
        )
    ]

    errors = await _validate_reauth_api_key(
        client,
        supply_point_id="KP-001234",
        meter_number="999999",
    )

    assert errors == {}


@pytest.mark.asyncio
async def test_validate_reauth_api_key_accepts_stored_meter_only_entry() -> None:
    client = AsyncMock()
    client.async_get_supply_points.return_value = [
        SupplyPoint(
            meter_number="07179527",
            supply_point_id="KP-001234",
            object_id="obj-1",
            address=None,
        )
    ]

    errors = await _validate_reauth_api_key(
        client,
        supply_point_id=None,
        meter_number="07179527",
    )

    assert errors == {}


@pytest.mark.asyncio
async def test_validate_reauth_api_key_rejects_wrong_supply_point() -> None:
    client = AsyncMock()
    client.async_get_supply_points.return_value = [
        SupplyPoint(
            meter_number="07179527",
            supply_point_id="KP-001234",
            object_id="obj-1",
            address=None,
        )
    ]

    errors = await _validate_reauth_api_key(
        client,
        supply_point_id="KP-wrong",
        meter_number="07179527",
    )

    assert errors == {"base": "no_supply_points"}


@pytest.mark.asyncio
async def test_validate_reauth_api_key_reports_invalid_auth() -> None:
    client = AsyncMock()
    client.async_get_supply_points.side_effect = TallinnVesiAuthError

    errors = await _validate_reauth_api_key(
        client,
        supply_point_id="KP-001234",
        meter_number="07179527",
    )

    assert errors == {"base": "invalid_auth"}


@pytest.mark.asyncio
async def test_validate_reauth_api_key_reports_connection_error() -> None:
    client = AsyncMock()
    client.async_get_supply_points.side_effect = TallinnVesiApiError

    errors = await _validate_reauth_api_key(
        client,
        supply_point_id="KP-001234",
        meter_number="07179527",
    )

    assert errors == {"base": "cannot_connect"}


@pytest.mark.asyncio
async def test_reauth_flow_updates_existing_entry_and_reloads(monkeypatch) -> None:
    entry = SimpleNamespace(
        entry_id="entry-1",
        unique_id="KP-001234",
        data={
            CONF_API_KEY: "old-key",
            CONF_METER_NUMBER: "07179527",
            CONF_SUPPLY_POINT_ID: "KP-001234",
            CONF_ADDRESS: "Tedre tn 73, Tallinn",
        },
    )
    flow = _make_reauth_flow(entry)
    client = AsyncMock()
    client.async_get_supply_points.return_value = [
        SupplyPoint(
            meter_number="07179527",
            supply_point_id="KP-001234",
            object_id="obj-1",
            address=None,
        )
    ]
    monkeypatch.setattr(TallinnVesiApiClient, "for_hass", Mock(return_value=client))

    form = await flow.async_step_reauth({})
    result = await flow.async_step_reauth_confirm({CONF_API_KEY: "new-key"})

    assert form["type"].value == "form"
    assert form["step_id"] == "reauth_confirm"
    assert result["type"].value == "abort"
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_API_KEY] == "new-key"
    assert entry.data[CONF_METER_NUMBER] == "07179527"
    assert entry.data[CONF_SUPPLY_POINT_ID] == "KP-001234"
    assert entry.unique_id == "KP-001234"
    assert flow.hass.config_entries.reloads == ["entry-1"]


@pytest.mark.asyncio
async def test_reauth_flow_rejects_key_for_different_supply_point(monkeypatch) -> None:
    entry = SimpleNamespace(
        entry_id="entry-1",
        unique_id="KP-001234",
        data={
            CONF_API_KEY: "old-key",
            CONF_METER_NUMBER: "07179527",
            CONF_SUPPLY_POINT_ID: "KP-001234",
        },
    )
    flow = _make_reauth_flow(entry)
    client = AsyncMock()
    client.async_get_supply_points.return_value = [
        SupplyPoint(
            meter_number="07179527",
            supply_point_id="KP-other",
            object_id="obj-1",
            address=None,
        )
    ]
    monkeypatch.setattr(TallinnVesiApiClient, "for_hass", Mock(return_value=client))

    await flow.async_step_reauth({})
    result = await flow.async_step_reauth_confirm({CONF_API_KEY: "wrong-key"})

    assert result["type"].value == "form"
    assert result["step_id"] == "reauth_confirm"
    assert result["errors"] == {"base": "no_supply_points"}
    assert entry.data[CONF_API_KEY] == "old-key"
    assert flow.hass.config_entries.reloads == []
