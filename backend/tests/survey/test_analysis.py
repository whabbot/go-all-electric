"""End-to-end analysis call with fakes only: Gemini, EPC, weather and the survey store.

Inputs are synthetic: an invented EPC record, invented readings and a constant-temperature
year of weather. No network, no keys, no Atlas.
"""

import json
from collections.abc import Callable
from contextlib import contextmanager
from datetime import date, timedelta
from threading import Lock
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel, SecretStr

from gae.db.models import SurveyInput
from gae.gemini.client import Call
from gae.gemini.router import get_gemini
from gae.gemini.schemas import (
    ArgonReview,
    FuseCutoutReading,
    OutdoorSpaceReading,
    RadiatorReading,
    RadiatorVideoReading,
    VideoRadiator,
)
from gae.main import app
from gae.opendata.epc import EPCClient
from gae.opendata.mapping import map_epc
from gae.opendata.weather import DegreeDays, degree_days_from_daily
from gae.survey.analysis import Services
from gae.survey.router import get_services
from tests.gemini.conftest import JPEG, PDF, SYNTHETIC_SHEETS, bill, boiler, loft
from tests.gemini.conftest import InMemoryDatasheetLookup as Lookup
from tests.gemini.test_gemini_video import _synthetic_mp4

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
        self._lock = Lock()

    def generate(self, *, model, input, schema, thinking_level, system_instruction=None, **_):
        call = Call(model, schema.__name__, thinking_level, list(input), system_instruction)
        with self._lock:
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
            "LoftReading": [loft()],
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
ALL_PHOTOS = ["boiler_plate", "radiators", "fuse_cutout", "outdoor_space", "gas_bill", "loft"]


def analyse(kinds=ALL_PHOTOS, certificate=CERTIFICATE, **form):
    files = [(k, (f"{k}.jpg", JPEG + k.encode(), "image/jpeg")) for k in kinds]
    data = {"certificate_id": certificate, **form}
    response = client.post("/api/analysis", data=data, files=files)
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
    # Named by number, never by a room name: labels stay in the browser.
    assert radiator["room"] == "Radiator 1"
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
    assert survey.extracted_readings["loft_depth_mm_band"].value == "270mm"
    assert survey.extracted_readings["loft_insulation_visible"].value is True
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
    assert "winter month" in gap["message"] and "gas kWh" in gap["provide"]
    assert any(d["name"] == "size_from_fabric_estimate" for d in result["defaults"])
    bill_reading = next(r for r in result["readings"] if r["kind"] == "gas_bill")
    assert bill_reading["status"] == "not_provided"
    assert harness["weather"].calls == []
    assert any(
        e["entry"]["check"].startswith("Estimate A vs B: no measured")
        for e in events
        if e["type"] == "log"
    )


def test_house_with_unrecorded_form_renders_estimate_a_without_photos(harness) -> None:
    # Synthetic reproduction of the refusal path: a decoded House with no
    # attachment form, fetched through the real EPC client and analysis route.
    data = record(
        dwelling_type=None,
        property_type=0,
        built_form=0,
        schema_type="SAP-Schema-12.0",
        assessment_type="RdSAP",
    )

    def handle(request):
        if request.url.path == "/api/certificate":
            return httpx.Response(200, json={"data": data})
        name = request.url.params["code"]
        label = {"property_type": "House", "built_form": "Not Recorded"}[name]
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "key": "0",
                        "values": [
                            {
                                "value": label,
                                "schemaVersion": data["schema_type"],
                                "assessmentType": "RdSAP",
                            }
                        ],
                    }
                ]
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handle)) as http:
        harness["epc"] = EPCClient(http, SecretStr("synthetic")).mapped
        _, events = analyse([])
        no_photos = result_of(events)
        assert no_photos["bundle"]["fabric"]["design_load_kw"]["central"] > 0
        assert no_photos["bundle"]["measured"] is None
        assert all(r["status"] == "not_provided" for r in no_photos["readings"])
        assert harness["gemini"].calls == []
        assert harness["weather"].calls == []
        geometry = next(d for d in no_photos["defaults"] if d["name"] == "semi_detached_geometry")
        assert geometry["confidence"] == "low"
        assert "assume semi-detached" in geometry["note"]

        # Uploading a boiler photo or one/multiple radiator photos cannot change
        # the EPC-derived Estimate A or turn this geometry refusal on/off.
        for photos, index in (
            (["boiler_plate"], []),
            (["radiators"], []),
            (["radiators", "radiators"], ["0", "1"]),
        ):
            _, events = analyse(photos, radiator_index=index)
            assert result_of(events)["bundle"]["fabric"] == no_photos["bundle"]["fabric"]


def test_partial_year_bill_has_warning_and_estimated_costs(harness) -> None:
    harness["gemini"].replies["GasBillReading"] = [
        bill(period_start="2026-01-01", period_end="2026-09-30", total_kwh=9000)
    ]
    _, events = analyse(["gas_bill"])
    result = result_of(events)
    assert result["bundle"]["measured"] is not None
    assert "12 months in a row" in result["bill_warning"]
    assert result["costs_annualised"]
    assert result["bundle"]["costs_by_flow_temp"]
    assert not result["gaps"]


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
            conflict_status="conflicts_found",
            input_conflicts=[
                {
                    "field": "wall_type",
                    "evidence_source": "outdoor_space",
                    "evidence_summary": "The outdoor wall photo shows retrofit cavity fill.",
                    "proposed_value": "cavity_filled",
                    "expected_direction": "lower",
                },
                {
                    "field": "loft_insulation_mm",
                    "evidence_source": "loft",
                    "evidence_summary": (
                        "The loft photo shows deep mineral wool burying the joists."
                    ),
                    "proposed_value": "270mm",
                    "expected_direction": "lower",
                },
            ],
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
        "radiators": readings["radiators"],
        "fuse_cutout": readings["fuse_cutout"],
        "outdoor_space": readings["outdoor_space"],
        "loft": readings["loft"],
        "quotes": [{"quote_id": "Quote A", "reading": None}],
    }
    response = client.post(
        "/api/analysis/review",
        data={"context": json.dumps(context), "quote_index": ["0"]},
        files=[
            ("boiler_plate", ("plate.jpg", JPEG, "image/jpeg")),
            ("gas_bill", ("bill.jpg", JPEG, "image/jpeg")),
            ("loft", ("loft.jpg", JPEG, "image/jpeg")),
            ("quotes", ("quote.pdf", PDF, "application/pdf")),
        ],
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["review"]["quote_reviews"][0]["quote_id"] == "Quote A"
    assert len(body["tested_conflicts"]) == 2
    assert body["tested_conflicts"][0]["field"] == "wall_type"
    assert body["tested_conflicts"][0]["proposed_value"] == "cavity_filled"
    assert body["tested_conflicts"][0]["gap_change"] == "shrinks"
    assert body["tested_conflicts"][1]["field"] == "loft_insulation_mm"
    assert body["tested_conflicts"][1]["evidence_source"] == "loft"
    assert body["tested_conflicts"][1]["proposed_value"] == "270mm"
    assert body["tested_conflicts"][1]["gap_change"] == "shrinks"
    assert body["stripped"] == []
    call = harness["gemini"].calls[-1]
    assert call.schema == "ArgonReview"
    assert '"outdoor_space":' in call.prompt and '"radiators":' in call.prompt
    assert '"loft":' in call.prompt
    assert call.media_types.count("image") == 3 and call.media_types.count("document") == 1
    for private in (STREET, POSTCODE, "ZZ1", CERTIFICATE, "100000000001"):
        assert private not in call.prompt


def test_analysis_with_radiator_video_feeds_spec_check_and_gaps(harness) -> None:
    harness["gemini"].replies["RadiatorVideoReading"] = [
        RadiatorVideoReading(
            legible=True,
            confidence="high",
            notes="",
            radiator_count=2,
            radiators=[
                VideoRadiator(
                    legible=True,
                    confidence="high",
                    notes="",
                    first_seen="0:03",
                    last_seen="0:07",
                    room="Dining room",
                    radiator_type="K2",
                    panels=2,
                    fin_rows=2,
                    height_mm=600,
                    width_mm=2000,
                    could_not_judge=[],
                ),
                VideoRadiator(
                    legible=True,
                    confidence="low",
                    notes="",
                    first_seen="0:14",
                    last_seen="0:17",
                    room="Box room",
                    radiator_type="single_panel",
                    panels=1,
                    fin_rows=0,
                    height_mm=500,
                    width_mm=600,
                    could_not_judge=["behind desk; fin rows unclear"],
                ),
            ],
            could_not_judge=[],
        )
    ]
    files = [
        ("boiler_plate", ("boiler.jpg", JPEG, "image/jpeg")),
        ("gas_bill", ("bill.jpg", JPEG, "image/jpeg")),
        ("radiator_video", ("walkthrough.mp4", _synthetic_mp4(), "video/mp4")),
    ]
    response = client.post("/api/analysis", data={"certificate_id": CERTIFICATE}, files=files)
    assert response.status_code == 200
    events = [json.loads(line) for line in response.text.splitlines()]
    result = result_of(events)

    video = result["radiator_video"]
    assert video is not None
    assert video["status"] == "verified_with_warnings"
    assert video["radiator_count"] == 2
    assert video["radiators"][0]["room"] == "Dining room"
    assert video["radiators"][0]["upsize_status"] == "ok"
    assert video["radiators"][1]["upsize_status"] == "couldnt_tell"
    assert video["photo_requests"] == ["couldn't tell: photograph the radiator seen at 0:14"]

    spec_radiators = result["bundle"]["target_spec"]["radiators"]
    assert [r["room"] for r in spec_radiators] == ["Dining room"]
    assert any(g["input"] == "radiators" and "0:14" in g["message"] for g in result["gaps"])
    assert any(d["name"] == "radiator_rating_from_video" for d in result["defaults"])


def _radiator(**overrides) -> RadiatorReading:
    values = dict(
        legible=True,
        confidence="high",
        notes="",
        radiator_type="K2",
        height_mm=600,
        width_mm=2000,
        panels=2,
        fin_rows=2,
        room="Living room",
    )
    return RadiatorReading(**{**values, **overrides})


def _rad_files(*names: str) -> list[tuple[str, tuple[str, bytes, str]]]:
    return [("radiators", (n, JPEG + n.encode(), "image/jpeg")) for n in names]


def _post(files, **form) -> dict:
    data = {"certificate_id": CERTIFICATE, **form}
    response = client.post("/api/analysis", data=data, files=files)
    assert response.status_code == 200, response.text
    return result_of([json.loads(line) for line in response.text.splitlines()])


def test_two_photos_of_one_radiator_are_one_radiator(harness) -> None:
    harness["gemini"].replies["RadiatorReading"] = [
        _radiator(),
        _radiator(radiator_type="K1", width_mm=900, panels=1, fin_rows=1, room="Bedroom 1"),
    ]
    files = [
        ("boiler_plate", ("boiler.jpg", JPEG, "image/jpeg")),
        ("gas_bill", ("bill.jpg", JPEG, "image/jpeg")),
        *_rad_files("rad1-front.jpg", "rad1-end.jpg", "rad2.jpg"),
    ]
    result = _post(files, radiator_index=["0", "0", "1"])

    rad_readings = [r for r in result["readings"] if r["kind"] == "radiators"]
    assert [r["index"] for r in rad_readings] == [0, 1]
    assert [r["status"] for r in rad_readings] == ["verified", "verified"]
    rad_calls = [c for c in harness["gemini"].calls if c.schema == "RadiatorReading"]
    # One Gemini read per radiator; radiator 1's two photos go in the same request.
    assert sorted(c.media_types.count("image") for c in rad_calls) == [1, 2]
    two_photo_call = next(c for c in rad_calls if c.media_types.count("image") == 2)
    assert "same single radiator" in two_photo_call.prompt

    spec_radiators = result["bundle"]["target_spec"]["radiators"]
    assert sorted(r["room"] for r in spec_radiators) == ["Radiator 1", "Radiator 2"]
    (survey,) = harness["saved"]
    assert {"radiators_room", "radiators_2_room"} <= set(survey.extracted_readings)

    harness["gemini"].replies["ArgonReview"] = [
        ArgonReview(
            estimates_explanation="The fabric calc reads higher than your bills.",
            cited_reason_codes=[],
            conflict_status="no_conflict_found",
            input_conflicts=[],
            quote_reviews=[],
            questions_to_ask=[],
            summary="Two radiators checked.",
        )
    ]
    context = {
        "bundle": result["bundle"],
        "epc": result["epc"],
        "radiators": [r["reading"] for r in rad_readings],
    }
    rev_response = client.post(
        "/api/analysis/review",
        data={"context": json.dumps(context), "radiator_index": ["0", "0", "1"]},
        files=_rad_files("rad1-front.jpg", "rad1-end.jpg", "rad2.jpg"),
    )
    assert rev_response.status_code == 200, rev_response.text
    call = harness["gemini"].calls[-1]
    assert call.schema == "ArgonReview"
    assert '"radiator": 1' in call.prompt and '"radiator": 2' in call.prompt
    assert call.prompt.count("radiators (radiator 1)") == 2
    assert call.prompt.count("radiators (radiator 2)") == 1
    assert call.media_types.count("image") == 3


def test_entered_values_win_and_disagreements_are_shown(harness) -> None:
    harness["gemini"].replies["RadiatorReading"] = [_radiator(width_mm=1400)]
    known = {
        "radiators": [{"width_mm": 1200, "height_mm": 590}],
        "boiler": {"make": "Acme Heating Ltd", "heating_output_kw": 30},
        "fuse_cutout": {"rating_a": 100},
    }
    files = [
        ("boiler_plate", ("boiler.jpg", JPEG, "image/jpeg")),
        ("gas_bill", ("bill.jpg", JPEG, "image/jpeg")),
        *_rad_files("rad1.jpg"),
    ]
    result = _post(files, radiator_index=["0"], known=json.dumps(known))
    by_kind = {r["kind"]: r for r in result["readings"]}

    rad = by_kind["radiators"]
    assert rad["status"] == "verified"
    assert rad["reading"]["width_mm"] == 1200 and rad["reading"]["height_mm"] == 590
    assert rad["entered"] == {"width_mm": 1200, "height_mm": 590}
    # 1,400 vs 1,200 mm is a disagreement; 600 vs 590 mm is within the photo's tolerance.
    assert rad["disagreements"] == [{"field": "width_mm", "entered": 1200, "read": 1400}]
    rating = next(d for d in result["defaults"] if d["name"].startswith("radiator_rating"))
    assert rating["name"] == "radiator_rating" and "as you measured them" in rating["note"]

    boiler = by_kind["boiler_plate"]
    assert boiler["reading"]["make"] == "Acme Heating Ltd"  # the photo's "Acme Heating" agrees
    assert boiler["reading"]["heating_output_kw"] == 30
    assert boiler["disagreements"] == [{"field": "heating_output_kw", "entered": 30, "read": 20}]

    # No fuse photo: the entered rating still counts and feeds the supply check.
    fuse = by_kind["fuse_cutout"]
    assert fuse["status"] == "entered" and fuse["reading"]["rating_a"] == 100
    assert result["plan"]["supply"]["fuse_rating_a"] == 100
    assert not any(c.schema == "FuseCutoutReading" for c in harness["gemini"].calls)


def test_details_only_radiator_counts_without_a_gemini_call(harness) -> None:
    known = {
        "radiators": [
            {},
            {"radiator_type": "K2", "width_mm": 1000, "height_mm": 600},
            {"radiator_type": "K1"},
        ]
    }
    result = _post([("gas_bill", ("bill.jpg", JPEG, "image/jpeg"))], known=json.dumps(known))

    rad_readings = [r for r in result["readings"] if r["kind"] == "radiators"]
    # The empty first card counts for nothing; the others keep their radiator numbers.
    assert [(r["index"], r["status"]) for r in rad_readings] == [(1, "entered"), (2, "entered")]
    assert rad_readings[0]["reading"]["width_mm"] == 1000
    assert not any(c.schema == "RadiatorReading" for c in harness["gemini"].calls)
    (radiator,) = result["bundle"]["target_spec"]["radiators"]
    assert radiator["room"] == "Radiator 2"
    assert not any(g["input"] == "radiators" for g in result["gaps"])


def test_couldnt_tell_photo_falls_back_to_entered_values(harness) -> None:
    blurry = _radiator(legible=False, height_mm=None, width_mm=None, radiator_type="other")
    harness["gemini"].replies["RadiatorReading"] = [blurry]
    known = {"radiators": [{"radiator_type": "K1", "width_mm": 800, "height_mm": 600}]}
    result = _post(_rad_files("rad1.jpg"), radiator_index=["0"], known=json.dumps(known))

    (rad,) = [r for r in result["readings"] if r["kind"] == "radiators"]
    assert rad["status"] == "entered" and rad["attempts"] == 2
    assert rad["reading"]["radiator_type"] == "K1"
    assert not any(g["input"] == "radiators" for g in result["gaps"])


def test_entered_details_are_validated_and_labels_are_refused(harness) -> None:
    for known, detail in (
        ({"radiators": [{"width_mm": 50}]}, "radiators.0.width_mm"),
        ({"radiators": [{"radiator_type": "K2", "panels": 1}]}, "2 panel(s)"),
        ({"fuse_cutout": {"rating_a": 70}}, "Main fuse ratings"),
        ({"boiler": {"heating_output_kw": 500}}, "boiler.heating_output_kw"),
        ({"boiler": {"make": "Worcester ZZ1 1ZZ"}}, "make or model only"),
        # Labels are display-only in the browser: the API has nowhere to put one.
        ({"radiators": [{"label": "Jamie's room"}]}, "radiators.0.label"),
        ({"radiators": [{}] * 9}, "radiators"),
    ):
        response = client.post(
            "/api/analysis", data={"certificate_id": CERTIFICATE, "known": json.dumps(known)}
        )
        assert response.status_code == 422, known
        assert detail in response.json()["detail"]
        assert "Jamie" not in response.text and "ZZ1" not in response.text
    assert harness["gemini"].calls == []


def test_review_sees_entered_values_and_photo_disagreements(harness) -> None:
    harness["gemini"].replies["RadiatorReading"] = [_radiator(width_mm=1400)]
    known = {"radiators": [{"width_mm": 1200}]}
    result = _post(_rad_files("rad1.jpg"), radiator_index=["0"], known=json.dumps(known))
    (rad,) = [r for r in result["readings"] if r["kind"] == "radiators"]
    harness["gemini"].replies["ArgonReview"] = [
        ArgonReview(
            estimates_explanation="No bill to compare against.",
            cited_reason_codes=[],
            conflict_status="no_conflict_found",
            input_conflicts=[],
            quote_reviews=[],
            questions_to_ask=[],
            summary="Your measured width differs from the photo.",
        )
    ]
    context = {
        "bundle": {**result["bundle"], "measured": None, "cross_check": None},
        "epc": result["epc"],
        "radiators": [rad["reading"]],
        "entered": [
            {
                "input": "radiators",
                "radiator": 1,
                "field": "width_mm",
                "entered": 1200,
                "photo_read": 1400,
            }
        ],
    }
    response = client.post(
        "/api/analysis/review",
        data={"context": json.dumps(context), "radiator_index": ["0"]},
        files=_rad_files("rad1.jpg"),
    )
    assert response.status_code == 200, response.text
    call = harness["gemini"].calls[-1]
    assert '"homeowner_entered"' in call.prompt
    assert '"photo_read": 1400' in call.prompt and '"entered": 1200' in call.prompt

    labelled = {**context, "entered": [{**context["entered"][0], "label": "Jamie's room"}]}
    response = client.post("/api/analysis/review", data={"context": json.dumps(labelled)})
    assert response.status_code == 422


def test_rejects_more_than_max_radiators_or_photos(harness) -> None:
    nine = _rad_files(*(f"rad-{i}.jpg" for i in range(9)))
    response = client.post(
        "/api/analysis",
        data={"certificate_id": CERTIFICATE, "radiator_index": [str(i) for i in range(9)]},
        files=nine,
    )
    assert response.status_code == 422
    assert "at most 8 radiators" in response.json()["detail"]

    four = _rad_files(*(f"rad-{i}.jpg" for i in range(4)))
    response = client.post(
        "/api/analysis",
        data={"certificate_id": CERTIFICATE, "radiator_index": ["0"] * 4},
        files=four,
    )
    assert response.status_code == 422
    assert "at most 3 photos per radiator" in response.json()["detail"]

    # Several photos with no radiator_index can't be told apart into radiators.
    response = client.post(
        "/api/analysis", data={"certificate_id": CERTIFICATE}, files=_rad_files("a.jpg", "b.jpg")
    )
    assert response.status_code == 422
    assert "radiator_index" in response.json()["detail"]


def _known_bill(periods):
    return json.dumps({"gas_bill": {"periods": periods}})


def test_entered_annual_bill_without_photo_drives_all_maths(harness):
    _, events = analyse(
        [], known=_known_bill([{"kwh": 14000, "start": "2025-01-01", "end": "2025-12-31"}])
    )
    result = result_of(events)
    assert result["bundle"]["measured"] is not None
    assert result["bundle"]["cross_check"] is not None
    assert result["bundle"]["costs_by_flow_temp"]
    assert "baseline_estimated" in result["bundle"]["measured"]["caveats"]
    assert not harness["gemini"].calls
    assert any(e["check"] == "Entered by you" and e["input"] == "gas_bill" for e in result["log"])
    item = next(r for r in result["readings"] if r["kind"] == "gas_bill")
    assert item["status"] == "entered" and item["reading"]["total_kwh"] == 14000


def test_entered_months_sorted_and_summer_baseline_used(harness):
    from calendar import monthrange

    periods = [
        {
            "kwh": 300 if m in (6, 7, 8) else 1500,
            "start": f"2025-{m:02d}-01",
            "end": f"2025-{m:02d}-{monthrange(2025, m)[1]}",
        }
        for m in range(1, 13)
    ]
    _, events = analyse([], known=_known_bill(list(reversed(periods))))
    result = result_of(events)
    assert "baseline_estimated" not in result["bundle"]["measured"]["caveats"]
    assert result["bundle"]["cross_check"] is not None
    assert result["bundle"]["costs_by_flow_temp"]
    item = next(r for r in result["readings"] if r["kind"] == "gas_bill")
    assert len(item["reading"]["monthly"]) == 12


@pytest.mark.parametrize(
    ("periods", "message"),
    [
        ([{"kwh": 12000, "start": "2025-01-01", "end": "2025-11-30"}], "12 months"),
        (
            [
                {"kwh": 6000, "start": "2025-01-01", "end": "2025-06-30"},
                {"kwh": 6000, "start": "2025-06-30", "end": "2025-12-31"},
            ],
            "overlap",
        ),
        (
            [
                {"kwh": 6000, "start": "2025-01-01", "end": "2025-06-30"},
                {"kwh": 6000, "start": "2025-08-01", "end": "2025-12-31"},
            ],
            "gap",
        ),
    ],
)
def test_partial_gapped_and_overlapping_bill_still_measures(harness, periods, message):
    _, events = analyse([], known=_known_bill(periods))
    result = result_of(events)
    assert result["bundle"]["measured"] is not None
    assert result["bundle"]["costs_by_flow_temp"]
    assert result["costs_annualised"]
    assert "12 months in a row" in result["bill_warning"]
    if message == "overlap":
        assert any("overlap" in note for note in result["bill_notes"])


def test_entered_bill_wins_over_photo_and_lists_disagreement(harness):
    harness["gemini"].replies["GasBillReading"] = [
        bill(period_start="2025-01-01", period_end="2025-12-31", total_kwh=12000)
    ]
    _, events = analyse(
        ["gas_bill"],
        known=_known_bill([{"kwh": 20000, "start": "2025-01-01", "end": "2025-12-31"}]),
    )
    result = result_of(events)
    item = next(r for r in result["readings"] if r["kind"] == "gas_bill")
    assert item["reading"]["total_kwh"] == 20000
    assert {d["field"] for d in item["disagreements"]} == {"total_kwh"}
    assert item["reading"]["monthly"] == []
    assert harness["weather"].calls[0][1:] == (date(2025, 1, 1), date(2025, 12, 31))


@pytest.mark.parametrize(
    "periods",
    [
        [{"kwh": 0, "start": "2025-01-01", "end": "2025-12-31"}],
        [{"kwh": 40001, "start": "2025-01-01", "end": "2025-12-31"}],
        [{"kwh": 100, "start": "2025-01-01", "end": "2025-12-31"}],
        [{"kwh": 12000, "start": "2025-02-30", "end": "2025-12-31"}],
        [{"kwh": 12000, "start": "2025-12-31", "end": "2025-01-01"}],
        [{"kwh": 12000, "start": "2025-01-01", "end": "2025-12-31", "account": "refused"}],
        [{"kwh": 1000, "start": "2025-01-01", "end": "2025-01-31"}] * 14,
    ],
)
def test_entered_bill_rejects_bad_values_with_422(harness, periods):
    response = client.post(
        "/api/analysis", data={"certificate_id": CERTIFICATE, "known": _known_bill(periods)}
    )
    assert response.status_code == 422


def test_yearly_entry_plus_two_contained_photos_uses_total_once(harness):
    harness["gemini"].replies["GasBillReading"] = [
        bill(period_start="2025-06-01", period_end="2025-06-30", total_kwh=250),
        bill(period_start="2025-07-01", period_end="2025-07-31", total_kwh=200),
    ]
    result = _post(
        [
            ("gas_bill", ("june.jpg", JPEG, "image/jpeg")),
            ("gas_bill", ("july.jpg", JPEG, "image/jpeg")),
        ],
        known=_known_bill([{"kwh": 12000, "start": "2025-01-01", "end": "2025-12-31"}]),
    )
    item = next(r for r in result["readings"] if r["kind"] == "gas_bill")
    assert item["reading"]["total_kwh"] == 12000
    assert len(result["bill_notes"]) == 2
    assert "baseline_estimated" not in result["bundle"]["measured"]["caveats"]
    assert not result["bill_warning"] and not result["costs_annualised"]


def test_summer_only_requests_winter_month(harness):
    _, events = analyse(
        [], known=_known_bill([{"kwh": 300, "start": "2025-06-01", "end": "2025-06-30"}])
    )
    result = result_of(events)
    assert result["bundle"]["measured"] is None
    assert not result["bundle"]["costs_by_flow_temp"]
    assert "add a winter month" in next(
        g["message"] for g in result["gaps"] if g["input"] == "gas_bill"
    )
