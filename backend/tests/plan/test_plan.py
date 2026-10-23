"""All-electric plan: supply headroom and solar lookups (faked HTTP, no network)."""

from typing import Any

import httpx

from gae.gemini.schemas import PhotoKind
from gae.plan.build import build_all_electric_plan
from gae.plan.solar import LiveSolarYield, outcode_centroid, pvgis_annual_kwh
from gae.plan.supply import assess_supply
from gae.survey.schemas import InputReading


class FakeSolar:
    def __init__(self, yield_kwh: float | None):
        self.outcodes: list[str] = []
        self._yield = yield_kwh

    def annual_kwh(self, outcode: str) -> float | None:
        self.outcodes.append(outcode)
        return self._yield


def _reading(status: str, rating_a: int | None) -> InputReading:
    reading = {"rating_a": rating_a, "legible": True, "confidence": "medium", "notes": ""}
    return InputReading(
        kind=PhotoKind.FUSE_CUTOUT,
        status=status,
        attempts=1,
        reading=reading if rating_a is not None else None,
        warnings=[],
        photograph_instead=None,
        used_for="test",
    )


def _bundle(size_high: float = 7.0) -> dict[str, Any]:
    return {
        "target_spec": {
            "size_kw": {"low": 5.0, "high": size_high, "central": 6.0},
            "max_flow_temp_c": {"value": 45.0, "confidence": "medium"},
            "grant": {
                "amount_gbp": {"value": 7500, "confidence": "high"},
                "fuel": "gas",
                "note": "Boiler Upgrade Scheme",
            },
        }
    }


def test_60a_fuse_flags_supply_100a_does_not() -> None:
    flagged = assess_supply(60, heat_pump_thermal_kw=7.0, design_flow_temp_c=45.0)
    assert flagged.status == "flagged"
    ok = assess_supply(100, heat_pump_thermal_kw=7.0, design_flow_temp_c=45.0)
    assert ok.status == "ok"


def test_no_fuse_gives_couldnt_tell() -> None:
    supply = assess_supply(None, heat_pump_thermal_kw=7.0, design_flow_temp_c=45.0)
    assert supply.status == "couldnt_tell"


def test_plan_supply_flagged_with_60a_fuse() -> None:
    readings = [_reading("verified", 60)]
    plan = build_all_electric_plan(
        postcode_district="ZZ1",
        readings=readings,
        bundle=_bundle(),
        solar=FakeSolar(3200.0),
    )
    assert plan.supply.status == "flagged"
    assert plan.steps[0].id == "supply" and plan.steps[0].status == "flagged"
    assert plan.ev.status == "flagged"


def test_pvgis_failure_shows_couldnt_fetch() -> None:
    plan = build_all_electric_plan(
        postcode_district="ZZ1",
        readings=[_reading("verified", 100)],
        bundle=_bundle(),
        solar=FakeSolar(None),
    )
    assert plan.solar.status == "couldnt_fetch"
    assert plan.solar.annual_yield_kwh is None


def test_only_outward_code_sent_to_geo_and_pvgis() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if "postcodes.io/outcodes/" in str(request.url):
            return httpx.Response(
                200,
                json={
                    "status": 200,
                    "result": {"latitude": 51.5, "longitude": -0.1, "outcode": "ZZ1"},
                },
            )
        if "re.jrc.ec.europa.eu" in str(request.url):
            return httpx.Response(
                200,
                json={"outputs": {"totals": {"fixed": {"E_y": 3000.0}}}},
            )
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as client:
        lat, lon = outcode_centroid(client, "ZZ1")
        assert lat == 51.5
        kwh = pvgis_annual_kwh(client, lat, lon)
        assert kwh == 3000.0
        live = LiveSolarYield(client)
        assert live.annual_kwh("ZZ1") == 3000.0

    assert all("ZZ1" in url and "ZZ1 1ZZ" not in url for url in calls if "postcodes.io" in url)
    assert not any("postcode=" in url.lower() and "1zz" in url.lower() for url in calls)
