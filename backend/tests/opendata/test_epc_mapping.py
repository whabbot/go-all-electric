"""Synthetic, identifying-field-free reproductions of the 2026 provider shapes."""

import copy
import json
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr

from gae.opendata.epc import EPCClient
from gae.opendata.mapping import map_epc

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return json.loads((FIXTURES / name).read_text())


def certificate_result(record=None, codes=None):
    record = record or fixture("certificate_nested.json")["data"]
    codes = codes or fixture("codes_nested.json")

    def handle(request):
        if request.url.path == "/api/certificate":
            return httpx.Response(200, json={"data": record})
        assert request.url.path == "/api/codes/info"
        assert request.url.params["schemaVersion"] == record["schema_type"]
        return httpx.Response(200, json=codes[request.url.params["code"]])

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        return EPCClient(client, SecretStr("synthetic")).certificate("0000-0000-0000-0000-0000")


def test_reported_nested_shape_decodes_flat_and_keeps_refusal():
    result = certificate_result()
    assert result["fabric_inputs"]["floor_area_m2"] == 63
    assert result["confidence"]["floor_area_m2"]["confidence"] == "medium"
    assert result["fabric_inputs"]["year_built"] == 1899
    assert "Pre-1900" in result["confidence"]["year_built"]["note"]
    assert result["confidence"]["year_built"]["value_range"] == (None, 1899)
    assert result["confidence"]["year_built"]["confidence"] == "low"
    assert result["confidence"]["glazing"]["confidence"] == "low"
    assert result["raw_summary"]["windows"] == [{"description": "Partial double glazing"}]
    assert result["estimate"] is None
    assert "geometry" in result["reason"]


def test_nested_house_certificate_produces_estimate_without_guessing_codes():
    record = fixture("certificate_nested.json")["data"]
    record["property_type"] = 0
    codes = fixture("codes_nested.json")
    codes["property_type"]["data"] = [
        {
            "key": "0",
            "values": [
                {"value": "House", "schemaVersion": "SAP-Schema-12.0", "assessmentType": "RdSAP"},
                {"value": "Flat", "schemaVersion": "SAP-Schema-12.0", "assessmentType": "SAP"},
            ],
        }
    ]
    result = certificate_result(record, codes)
    assert result["fabric_inputs"]["property_type"] == "detached"
    assert result["confidence"]["property_type"]["confidence"] == "medium"
    assert result["estimate"]["design_load_kw"]["central"] > 0


def test_code_table_failure_never_enables_numeric_geometry():
    result = certificate_result(codes={k: {"data": []} for k in fixture("codes_nested.json")})
    assert result["estimate"] is None
    assert result["confidence"]["year_built"]["default"] == "unknown_age_1930"


def test_assessment_is_required_and_must_match():
    record = fixture("certificate_nested.json")["data"]
    record["assessment_type"] = "SAP"
    assert "England and Wales" in certificate_result(record)["confidence"]["year_built"]["note"]
    record.pop("assessment_type")
    assert certificate_result(record)["confidence"]["year_built"]["default"] == "unknown_age_1930"


def area_record(parts):
    return {"dwelling_type": "Semi-detached house", "sap_building_parts": parts}


def part(number, *areas):
    return {
        "building_part_number": number,
        "sap_floor_dimensions": [
            {"floor": floor, "total_floor_area": area} for floor, area in enumerate(areas)
        ],
    }


def test_nested_area_sums_floors_and_extensions_once():
    main = part(1, 30, {"value": 30, "quantity": "square metres"})
    extension = part(2, 12)
    record = area_record([main, extension, copy.deepcopy(main)])
    result = map_epc(record)
    assert result.fabric_inputs["floor_area_m2"] == 72
    assert result.estimate is not None
    record["total_floor_area"] = {"value": 85}
    assert map_epc(record).fabric_inputs["floor_area_m2"] == 85


@pytest.mark.parametrize(
    "parts",
    [
        [],
        [part(1, None)],
        [part(1, 30), part(2, -1)],
        [part(1, 30), part(1, 35)],
        [{"sap_floor_dimensions": []}],
        [part(1, float("nan"))],
        [part(1, True)],
    ],
)
def test_absent_invalid_or_conflicting_area_refuses_partial_estimate(parts):
    result = map_epc(area_record(parts))
    assert result.estimate is None
    assert result.fabric_inputs["floor_area_m2"] is None


@pytest.mark.parametrize(
    "label, year, bounds",
    [
        ("England and Wales: before 1900", 1899, (None, 1899)),
        ("Pre-1900", 1899, (None, 1899)),
        ("2007 onwards", 2007, (2007, None)),
        ("after 2011", 2012, (2012, None)),
        ("1930-1949", 1930, (1930, 1949)),
    ],
)
def test_age_bands_are_ranges_not_exact_dates(label, year, bounds):
    result = map_epc({"total_floor_area": 63}, age_label=label)
    assert result.fabric_inputs["year_built"] == year
    assert result.confidence["year_built"].value_range == bounds
    if None in bounds:
        assert result.confidence["year_built"].confidence == "low"


@pytest.mark.parametrize(
    "description, expected, confidence",
    [
        ("Fully triple glazed", "triple", "medium"),
        ("Fully double glazed", "double_unknown_date", "low"),
        ("Partial double glazing", "double_unknown_date", "low"),
    ],
)
def test_plural_windows(description, expected, confidence):
    result = map_epc({"windows": [{"description": description}]})
    assert result.fabric_inputs["glazing"] == expected
    assert result.confidence["glazing"].confidence == confidence
