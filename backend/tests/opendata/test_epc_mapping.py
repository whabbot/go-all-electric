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


@pytest.mark.parametrize(
    "label, expected",
    [
        ("Detached", "detached"),
        ("Semi-Detached", "semi_detached"),
        ("Semi Detached", "semi_detached"),
        ("End-Terrace", "end_terrace"),
        ("Mid-Terrace", "mid_terrace"),
        ("Enclosed End-Terrace", "end_terrace"),
        ("Enclosed Mid-Terrace", "mid_terrace"),
        ("Not Recorded", "semi_detached"),
    ],
)
def test_decoded_house_forms(label, expected):
    result = map_epc(
        {"total_floor_area": 90, "property_type": 0, "built_form": 1},
        property_label="House",
        built_form_label=label,
    )
    assert result.estimate is not None
    assert result.fabric_inputs["property_type"] == expected
    # Exercise the provider's numeric-code path as well as direct label mapping.
    record = fixture("certificate_nested.json")["data"]
    record["property_type"] = 0
    codes = fixture("codes_nested.json")
    codes["property_type"]["data"][0]["key"] = "0"
    for value in codes["property_type"]["data"][0]["values"]:
        if value["schemaVersion"] == record["schema_type"]:
            value["value"] = "House"
    for value in codes["built_form"]["data"][0]["values"]:
        if value["schemaVersion"] == record["schema_type"]:
            value["value"] = label
    decoded = certificate_result(record, codes)
    assert decoded["estimate"] is not None
    assert decoded["fabric_inputs"]["property_type"] == expected
    confidence = result.confidence["property_type"]
    if label.startswith("Enclosed") or label == "Not Recorded":
        assert confidence.confidence == "low"
        assert confidence.default is not None
        assert "assum" in confidence.note.lower()
    else:
        assert confidence.confidence == "medium"
        assert confidence.default is None


@pytest.mark.parametrize(
    "dwelling, expected",
    [
        ("Semi Detached house", "semi_detached"),
        ("  SEMI\u2013DETACHED   HOUSE ", "semi_detached"),
        ("End terrace house", "end_terrace"),
        ("Mid terrace house", "mid_terrace"),
        ("Enclosed Mid-Terrace house", "mid_terrace"),
        ("Enclosed End-Terrace house", "end_terrace"),
        ("Semi-detached bungalow", "bungalow"),
        ("Detached bungalow", "bungalow"),
    ],
)
@pytest.mark.parametrize("wrapped", [False, True])
def test_dwelling_text_and_english_value_objects(dwelling, expected, wrapped):
    value = {"value": dwelling, "language": "1"} if wrapped else dwelling
    result = map_epc({"total_floor_area": 90, "dwelling_type": value})
    assert result.estimate is not None
    assert result.fabric_inputs["property_type"] == expected
    assert result.fabric_inputs["storeys"] == (1 if expected == "bungalow" else 2)


@pytest.mark.parametrize("form", [None, "", "Not Recorded", 99, "Unspecified"])
def test_known_house_with_unknown_form_uses_named_low_confidence_assumption(form):
    result = map_epc(
        {"total_floor_area": 90, "property_type": "House", "built_form": form},
        property_label="House",
    )
    assert result.reason is None
    assert result.estimate is not None
    assert result.fabric_inputs["property_type"] == "semi_detached"
    confidence = result.confidence["property_type"]
    assert confidence.confidence == "low"
    assert confidence.default == "semi_detached_geometry"
    assert "assum" in confidence.note.lower()
    assert "survey" in confidence.note.lower()


def test_generic_dwelling_does_not_mask_decoded_form():
    result = map_epc(
        {"total_floor_area": 90, "dwelling_type": "House", "built_form": 4},
        built_form_label="Mid-Terrace",
    )
    assert result.estimate is not None
    assert result.fabric_inputs["property_type"] == "mid_terrace"


@pytest.mark.parametrize(
    "label",
    [
        "Ground-floor flat",
        "Mid-floor flat",
        "Top-floor flat",
        "Ground-floor maisonette",
        "Top-floor maisonette",
        "Park home",
        "Park-Home",
    ],
)
@pytest.mark.parametrize("field", ["dwelling_type", "property_type"])
def test_non_house_types_refuse_even_with_a_house_form(label, field):
    record = {"total_floor_area": 90, "built_form": "Semi Detached", field: label}
    assert map_epc(record).estimate is None
    record[field] = {"value": label, "language": "1"}
    assert map_epc(record).estimate is None


def test_decoded_flat_cannot_be_masked_by_house_dwelling_text():
    result = map_epc(
        {"total_floor_area": 90, "dwelling_type": "Detached house", "property_type": 2},
        property_label="Flat",
    )
    assert result.estimate is None


def test_house_dwelling_does_not_mask_bungalow_property_type():
    result = map_epc(
        {"total_floor_area": 90, "dwelling_type": "Detached", "property_type": 1},
        property_label="Bungalow",
    )
    assert result.fabric_inputs["property_type"] == "bungalow"
    assert result.fabric_inputs["storeys"] == 1


def test_known_house_with_missing_form_through_client():
    record = fixture("certificate_nested.json")["data"]
    record["dwelling_type"] = "House"
    record["property_type"] = 0
    codes = fixture("codes_nested.json")
    codes["property_type"]["data"][0]["key"] = "0"
    for value in codes["property_type"]["data"][0]["values"]:
        if value["schemaVersion"] == record["schema_type"]:
            value["value"] = "House"
    record["built_form"] = 99  # Unknown even in the static table.
    codes["built_form"] = {"data": []}
    result = certificate_result(record, codes)
    assert result["estimate"] is not None
    assert result["confidence"]["property_type"]["confidence"] == "low"


def test_client_resolves_form_despite_generic_dwelling_text():
    record = fixture("certificate_nested.json")["data"]
    record["dwelling_type"] = "House"
    record["property_type"] = 0
    codes = fixture("codes_nested.json")
    codes["property_type"] = {"data": []}
    result = certificate_result(record, codes)
    assert result["estimate"] is not None
    assert result["fabric_inputs"]["property_type"] == "detached"


@pytest.mark.parametrize(
    "property_code,expected", [(0, "detached"), (1, "bungalow"), (2, None), (3, None), (4, None)]
)
def test_static_codes_when_endpoint_fails(property_code, expected, monkeypatch, caplog):
    from gae.opendata.http import DataUnavailable

    data = fixture("certificate_nested.json")["data"]
    data["property_type"] = property_code

    def get(self, path, params):
        if path == "/api/certificate":
            return {"data": data}
        raise DataUnavailable("Codes service unavailable")

    monkeypatch.setattr(EPCClient, "_get", get)
    with caplog.at_level("INFO"), httpx.Client() as client:
        result = EPCClient(client, SecretStr("synthetic")).certificate("0000-0000-0000-0000-0000")
    assert (result["estimate"] is not None) == (expected is not None)
    if expected:
        assert result["fabric_inputs"]["property_type"] == expected
    assert "static_code_fallback" in caplog.text
    assert "0000-0000-0000-0000-0000" not in caplog.text
    assert "address" not in caplog.text


@pytest.mark.parametrize(
    "code,label",
    [
        ("1", "detached"),
        ("2", "semi_detached"),
        ("3", "end_terrace"),
        ("4", "mid_terrace"),
        ("5", "end_terrace"),
        ("6", "mid_terrace"),
        ("NR", "semi_detached"),
    ],
)
def test_verified_static_built_forms(code, label):
    result = map_epc({"total_floor_area": 90, "property_type": 0, "built_form": code})
    assert result.estimate is not None
    assert result.fabric_inputs["property_type"] == label


@pytest.mark.parametrize(
    "label,expected",
    [
        ("Not Recorded", "semi_detached"),
        ("Mid-terrace", "mid_terrace"),
        ("Unspecified", "semi_detached"),
    ],
)
def test_dwelling_label_without_word_house(label, expected):
    result = map_epc({"total_floor_area": 90, "dwelling_type": label})
    assert result.estimate is not None
    assert result.fabric_inputs["property_type"] == expected
    if expected == "semi_detached":
        assert result.confidence["property_type"].confidence == "low"
        assert "Confirm at survey" in result.confidence["property_type"].note


@pytest.mark.parametrize("code", [2, 3, 4, "2", "3", "4"])
def test_static_non_house_code_overrules_house_text(code):
    result = map_epc(
        {"total_floor_area": 90, "property_type": code, "dwelling_type": "Detached house"}
    )
    assert result.estimate is None
    assert not result.house_model_supported
