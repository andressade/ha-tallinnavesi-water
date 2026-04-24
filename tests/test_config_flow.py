"""Tests for config-flow helper logic."""

from __future__ import annotations

from custom_components.tallinnavesi_water.api import ReadingOverview, SupplyPoint
from custom_components.tallinnavesi_water.config_flow import (
    _build_overview_by_meter,
    _build_supply_point_selections,
)
from custom_components.tallinnavesi_water.const import (
    CONF_ADDRESS,
    CONF_METER_NUMBER,
    CONF_SUPPLY_POINT_ID,
)


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
