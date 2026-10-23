"""End-to-end analysis call with fakes only: Gemini, EPC, weather and the survey store.

Inputs are synthetic: an invented EPC record, invented readings and a constant-temperature
year of weather. No network, no keys, no Atlas.
"""

import json
from collections.abc import Callable
from contextlib import contextmanager
from datetime import date, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

from gae.db.models import SurveyInput
from gae.gemini.client import Call
from gae.gemini.router import get_gemini
from gae.gemini.schemas import (
    ArgonReview,
    FuseCutoutReading,
    OutdoorSpaceReading,
    RadiatorReading,
)
from gae.main import app
from gae.opendata.mapping import map_epc
from gae.opendata.weather import DegreeDays, degree_days_from_daily
from gae.survey.analysis import Services
from gae.survey.router import get_services
from tests.gemini.conftest import JPEG, PDF, SYNTHETIC_SHEETS, bill, boiler
from tests.gemini.conftest import InMemoryDatasheetLookup as Lookup

CERTIFICATE = "0000-1111-2222-3333-4444"
STREET = "1 Synthetic Street"
POSTCODE = "ZZ1 1ZZ"


def record(**overrides: Any) -> dict:
    """An invented semi-detached house, shaped like the EPC API's certificate data."""
    values = {
        "address_line_1": STREET,
        "postcode": POSTCODE,
        "uprn": 100000000001,
        "total_floor_area": 90,
        "dwelling_type": "Semi-detached house",
        "construction_age_band": "1930-1949",
        "walls": [{"description": "Cavity wall, as built, no insulation (assumed)"}],
        "roofs": [{"description": "Pitched, 100 mm loft insulation"}],
        "floors": [{"description": "Suspended, no insulation (assumed)"}],
        "windows": [{"description": "Fully double glazed"}],
        "main_heating": [{"description": "Boiler and radiators, mains gas"}],
        "current_energy_efficiency_band": "D",
    }
    return {**values, **overrides}


class FakeEpc:
    def __init__(self, data: dict):
        self.data = data
        self.calls: list[str] = []

    def __call__(self, certificate_id: str):
        self.calls.append(certificate_id)
        allowed = {k: v for k, v in self.data.items() if k != "uprn"}
        return allowed, map_epc(self.data)


class FakeSolar:
    def annual_kwh(self, outcode: str) -> float:
        return 3_500.0


class FakeWeather:
    """A constant 10.57C every day: about 1,800 degree days over a year at the 15.5C base."""

    def __init__(self):
        self.calls: list[tuple[str, date, date]] = []

    def degree_days(self, postcode: str, start: date, end: date) -> DegreeDays:
        self.calls.append((postcode, start, end))
        days = (end - start).days + 1
        daily = {
            "time": [(start + timedelta(days=i)).isoformat() for i in range(days)],
            "temperature_2m_mean": [15.5 - 1800 / days] * days,
        }
        return degree_days_from_daily(postcode, start, end, daily)


class ScriptedGemini:
    """Replies chosen by schema and by first read vs re-read, so concurrent reads are stable."""

    lead_model = "gemini-4-argon"
    fast_model = "gemini-3.8-flash"

    def __init__(self, replies: dict[str, list[BaseModel | Callable[[Call], BaseModel]]]):
        self.replies = replies
        self.calls: list[Call] = []

    def generate(self, *, model, input, schema, thinking_level, system_instruction=None, **_):
        call = Call(model, schema.__name__, thinking_level, list(input), system_instruction)
        self.calls.append(call)
        queue = self.replies[schema.__name__]
        reply = queue.pop(0) if len(queue) > 1 else queue[0]
        if callable(reply):
            reply = reply(call)
        return schema.model_validate_json(reply.model_dump_json())


def blurry_then_clear_radiator() -> list[RadiatorReading]:
    common = dict(confidence="medium", notes="", panels=2, fin_rows=2, room="Living room")
    return [
        RadiatorReading(
            legible=False, radiator_type="other", height_mm=None, width_mm=None, **common
        ),
        RadiatorReading(legible=True, radiator_type="K2", height_mm=600, width_mm=1200, **common),
    ]


def meter_twice() -> list[FuseCutoutReading]:
    return [
        FuseCutoutReading(
            legible=True, confidence="low", notes="", rating_a=None, looks_like="meter"
        )
    ]


def outdoor() -> list[OutdoorSpaceReading]:
    return [
        OutdoorSpaceReading(
            legible=True,
            confidence="medium",
            notes="",
            clear_width_m=1.6,
            clear_depth_m=1.0,
            surface="paved",
            obstructions=["drain"],
        )
    ]


def scripted(**extra) -> ScriptedGemini:
    return ScriptedGemini(
        {
            "BoilerPlateReading": [boiler()],
            "RadiatorReading": blurry_then_clear_radiator(),
            "FuseCutoutReading": meter_twice(),
            "OutdoorSpaceReading": outdoor(),
            "GasBillReading": [
                bill(
                    monthly=[
                        {"month": f"{2025 + (m < 10)}-{m:02d}", "kwh": kwh}
                        for m, kwh in [
                            (10, 900),
                            (11, 1600),
                            (12, 1990),
                            (1, 2050),
                            (2, 1800),
                            (3, 1400),
                            (4, 950),
                            (5, 500),
                            (6, 170),
                            (7, 150),
                            (8, 160),
                            (9, 330),
                        ]
                    ]
                )
            ],
            **extra,
        }
    )


@pytest.fixture
def harness():
    state: dict[str, Any] = {"saved": [], "epc": FakeEpc(record()), "weather": FakeWeather()}
    state["gemini"] = scripted()

    def save(survey: SurveyInput) -> str:
        state["saved"].append(survey)
        return "11111111-2222-4333-8444-555555555555"

    @contextmanager
    def factory():
        yield Services(
            gemini=state["gemini"],
            epc=state["epc"],
            weather=state["weather"],
            datasheets=Lookup(SYNTHETIC_SHEETS),
            save=state.get("save", save),
            solar=FakeSolar(),
        )

    app.dependency_overrides[get_services] = lambda: factory
    app.dependency_overrides[get_gemini] = lambda: state["gemini"]
    yield state
    app.dependency_overrides.clear()


client = TestClient(app)
ALL_PHOTOS = ["boiler_plate", "radiators", "fuse_cutout", "outdoor_space", "gas_bill"]


def analyse(kinds=ALL_PHOTOS, certificate=CERTIFICATE):
    files = [(k, (f"{k}.jpg", JPEG + k.encode(), "image/jpeg")) for k in kinds]
    response = client.post("/api/analysis", data={"certificate_id": certificate}, files=files)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")
    events = [json.loads(line) for line in response.text.splitlines()]
    return response.text, events


def result_of(events) -> dict:
    (result,) = [e["result"] for e in events if e["type"] == "result"]
    return result


def test_full_path_runs_epc_photos_bill_weather_maths_and_saves(harness) -> None:
    text, events = analyse()
    result = result_of(events)
    bundle = result["bundle"]

    assert harness["epc"].calls == [CERTIFICATE]
    ((postcode, start, end),) = harness["weather"].calls
    assert postcode == POSTCODE and (start, end) == (date(2025, 10, 1), date(2026, 9, 30))

    # Estimate B from the bill; Estimate A from the EPC; they disagree and the app says why.
    assert bundle["measured"]["design_load_kw"]["central"] == pytest.approx(4.6, abs=0.3)
    assert bundle["fabric"]["design_load_kw"]["central"] > 7
    assert bundle["cross_check"]["verdict"] == "fabric_higher"
    assert bundle["cross_check"]["reasons"]
    assert [c["design_flow_temp_c"] for c in bundle["costs_by_flow_temp"]] == [40, 45, 50, 55]
    assert result["size_basis"] == "measured"
    spec = bundle["target_spec"]
    assert spec["grant"]["amount_gbp"]["value"] == 7500
    (radiator,) = spec["radiators"]
    assert radiator["room"] == "Living room"
    names = {d["name"] for d in result["defaults"]}
    assert {"radiator_rating_from_photo", "photographed_room_share_of_heat_loss"} <= names
    assert "boiler_efficiency" in names

    # The live log carries the real fail -> re-read -> pass sequence for the blurry radiator.
    stream = [e["entry"] for e in events if e["type"] == "log"]
    radiator_log = [e for e in stream if e["input"] == "radiators"]
    steps = [(e["step"], e["passed"]) for e in radiator_log]
    first_fail = steps.index(("check", False))
    assert ("reread", True) in steps[first_fail:]
    assert steps[-1] == ("pass", True)
    assert radiator_log[first_fail]["action"] == "ask Gemini to look again"
    assert len({e["id"] for e in result["log"]}) == len(result["log"])
    assert {e["id"] for e in stream} == {e["id"] for e in result["log"]}
    assert [e["step"] for e in events if e["type"] == "step" and e["status"] == "done"]

    # Couldn't tell: a meter instead of the cutout is named, with what to photograph.
    fuse = next(r for r in result["readings"] if r["kind"] == "fuse_cutout")
    assert fuse["status"] == "couldnt_tell" and fuse["reading"] is None
    assert "sealed fuse carrier" in fuse["photograph_instead"]
    assert any(g["input"] == "fuse_cutout" for g in result["gaps"])

    # Timings per step for the PR, and the survey saved with the district only.
    assert {"epc", "read_gas_bill", "weather", "maths", "save", "total"} <= set(
        result["timings_ms"]
    )
    assert result["saved"] and result["postcode_district"] == "ZZ1"
    (survey,) = harness["saved"]
    stored = survey.model_dump_json()
    assert survey.postcode_district == "ZZ1"
    assert survey.extracted_readings["gas_bill_total_kwh"].value == 12000
    for private in (STREET, POSTCODE, "1ZZ", CERTIFICATE, "100000000001"):
        assert private not in stored
        assert private not in text
    assert "synthetic-not-a-real-photo" not in text  # photo bytes never come back


def test_reads_run_concurrently(harness) -> None:
    import threading

    barrier = threading.Barrier(3, timeout=5)
    base = harness["gemini"]

    def waits(reply):
        def call(_):
            barrier.wait()
            return reply

        return call

    harness["gemini"] = ScriptedGemini(
        {
            **base.replies,
            "BoilerPlateReading": [waits(boiler())],
            "OutdoorSpaceReading": [waits(outdoor()[0])],
            "GasBillReading": [waits(bill())],
        }
    )
    # Only passes if all three reads are in flight at once.
    _, events = analyse(["boiler_plate", "outdoor_space", "gas_bill"])
    assert result_of(events)["bundle"]["measured"] is not None


def test_no_bill_means_no_estimate_b_and_says_what_to_provide(harness) -> None:
    _, events = analyse(["boiler_plate", "outdoor_space"])
    result = result_of(events)
    bundle = result["bundle"]
    assert bundle["measured"] is None and bundle["cross_check"] is None
    assert bundle["costs_by_flow_temp"] == []
    assert result["size_basis"] == "fabric"
    gap = next(g for g in result["gaps"] if g["input"] == "gas_bill")
    assert "no Estimate B" in gap["message"] and "annual gas statement" in gap["provide"]
    assert any(d["name"] == "size_from_fabric_estimate" for d in result["defaults"])
    bill_reading = next(r for r in result["readings"] if r["kind"] == "gas_bill")
    assert bill_reading["status"] == "not_provided"
    assert harness["weather"].calls == []
    assert any(
        e["entry"]["check"].startswith("Estimate A vs B: no measured")
        for e in events
        if e["type"] == "log"
    )


def test_partial_year_bill_is_couldnt_tell_not_a_guess(harness) -> None:
    harness["gemini"].replies["GasBillReading"] = [
        bill(period_start="2026-01-01", period_end="2026-09-30", total_kwh=9000)
    ]
    _, events = analyse(["gas_bill"])
    result = result_of(events)
    assert result["bundle"]["measured"] is None
    gap = next(g for g in result["gaps"] if g["input"] == "gas_bill")
    assert "12-month" in gap["message"]
    # Skipped photos (the outdoor spot is optional) are never reported as gaps.
    assert {g["input"] for g in result["gaps"]} == {"gas_bill"}


def test_flats_are_refused_with_a_reason(harness) -> None:
    harness["epc"] = FakeEpc(record(dwelling_type="Mid-floor flat"))
    _, events = analyse(["boiler_plate"])
    (error,) = [e for e in events if e["type"] == "error"]
    assert error["status"] == 422 and "Couldn't tell" in error["message"]
    assert not harness["saved"]


def test_store_outage_still_returns_the_analysis(harness) -> None:
    def broken(_):
        raise RuntimeError("mongodb+srv://user:secret@example.invalid")

    harness["save"] = broken
    text, events = analyse(["gas_bill"])
    result = result_of(events)
    assert not result["saved"] and result["storage_note"].startswith("Not saved")
    assert "secret" not in text


def test_rejects_bad_certificate_ids_and_file_types(harness) -> None:
    assert client.post("/api/analysis", data={"certificate_id": "12 High St"}).status_code == 422
    response = client.post(
        "/api/analysis",
        data={"certificate_id": CERTIFICATE},
        files=[("gas_bill", ("bill.txt", b"hello", "text/plain"))],
    )
    assert response.status_code == 415


def test_review_gets_building_fields_only_and_quotes(harness) -> None:
    _, events = analyse()
    result = result_of(events)

    def reply(call: Call) -> ArgonReview:
        return ArgonReview(
            estimates_explanation="The fabric calc reads higher than your bills.",
            cited_reason_codes=[r["code"] for r in result["bundle"]["cross_check"]["reasons"]],
            quote_reviews=[{"quote_id": "Quote A", "flags": []}],
            questions_to_ask=["Can I see the room-by-room heat loss?"],
            summary="Your bills point lower than the fabric calc.",
        )

    harness["gemini"].replies["ArgonReview"] = [reply]
    readings = {r["kind"]: r["reading"] for r in result["readings"]}
    context = {
        "bundle": result["bundle"],
        "epc": result["epc"],
        "boiler": readings["boiler_plate"],
        "bill": readings["gas_bill"],
        "quotes": [{"quote_id": "Quote A", "reading": None}],
    }
    response = client.post(
        "/api/analysis/review",
        data={"context": json.dumps(context), "quote_index": ["0"]},
        files=[
            ("boiler_plate", ("plate.jpg", JPEG, "image/jpeg")),
            ("gas_bill", ("bill.jpg", JPEG, "image/jpeg")),
            ("quotes", ("quote.pdf", PDF, "application/pdf")),
        ],
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["review"]["quote_reviews"][0]["quote_id"] == "Quote A"
    assert body["stripped"] == []
    call = harness["gemini"].calls[-1]
    assert call.schema == "ArgonReview"
    assert call.media_types.count("image") == 2 and call.media_types.count("document") == 1
    for private in (STREET, POSTCODE, "ZZ1", CERTIFICATE, "100000000001"):
        assert private not in call.prompt
