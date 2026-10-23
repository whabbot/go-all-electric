"""Network-free driver mocks for persistence, retrieval and API failure boundaries."""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from pymongo.errors import OperationFailure, ServerSelectionTimeoutError

from gae.db.datasheets import (
    AtlasDatasheetLookup,
    exact_model_match,
    fuse,
    hybrid_pipeline,
    infer_kind,
    text_pipeline,
    vector_pipeline,
)
from gae.db.indexes import TEXT_DEFINITION, VECTOR_DEFINITION, ensure_indexes
from gae.db.models import SurveyInput
from gae.db.router import get_database
from gae.db.seed import load_seed, seed
from gae.db.surveys import SurveyRepository
from gae.main import app


def sheet(index=0):
    data = load_seed()[index].model_dump(mode="json")
    return {"_id": data["id"], **data}


def native_sheet():
    return {
        **sheet(),
        "fusion_details": {
            "value": 2 / 61,
            "details": [
                {"inputPipelineName": "atlas_search", "rank": 1},
                {"inputPipelineName": "vector_search", "rank": 1},
            ],
        },
    }


def test_seed_valid_unique_sourced_and_idempotent_upserts():
    rows = load_seed()
    assert 12 <= len(rows) <= 15
    assert {
        "Vaillant",
        "Mitsubishi Electric",
        "Daikin",
        "Samsung",
        "Worcester Bosch",
        "Baxi",
        "Ideal",
    } <= {row.make for row in rows}
    assert {5, 6, 7, 9, 12} <= {row.nominal_capacity_kw for row in rows if row.kind == "heat_pump"}
    assert len({row.id for row in rows}) == len(rows)
    assert all(row.source_url.startswith("https://") for row in rows)
    assert all(row.make in row.text and row.model in row.text for row in rows)
    collection = MagicMock()
    assert seed(collection) == len(rows)
    assert seed(collection) == len(rows)
    for call in collection.update_one.call_args_list:
        assert call.kwargs["upsert"] is True
        assert call.args[0]["_id"] == call.args[1]["$set"]["id"]
        assert "embedding" not in call.args[1]["$set"]  # Atlas-managed


def test_fusion_promotes_agreement_preserves_ranks_and_deduplicates():
    a, b = sheet(0), sheet(1)
    matches = fuse({"atlas_search": [a, b, b], "vector_search": [b]}, 5)
    assert [match.datasheet.id for match in matches] == [b["id"], a["id"]]
    assert matches[0].score == pytest.approx(1 / 62 + 1 / 61)
    assert matches[0].ranks == {"atlas_search": 2, "vector_search": 1}
    assert matches[0].produced_by == ["atlas_search", "vector_search"]


def test_search_executes_fuzzy_and_managed_voyage_pipelines():
    collection = MagicMock()
    collection.aggregate.return_value = [native_sheet()]
    result = AtlasDatasheetLookup(collection).search("Vailant aroterm", 2)
    assert result.mode == "hybrid"
    assert result.matches[0].produced_by == ["atlas_search", "vector_search"]
    calls = collection.aggregate.call_args_list
    assert result.fusion == "native_rank_fusion"
    assert len(calls) == 1
    assert calls[0].args[0] == hybrid_pipeline("Vailant aroterm", 20, 2)
    pipelines = calls[0].args[0][0]["$rankFusion"]["input"]["pipelines"]
    assert pipelines["atlas_search"] == text_pipeline("Vailant aroterm", 20)
    assert pipelines["vector_search"] == vector_pipeline("Vailant aroterm", 20)
    vector = pipelines["vector_search"][0]["$vectorSearch"]
    assert vector["model"] == VECTOR_DEFINITION["fields"][0]["model"]
    assert "queryVector" not in vector


def test_native_provenance_excludes_a_channel_that_did_not_match():
    collection = MagicMock()
    doc = native_sheet()
    doc["fusion_details"]["details"][1]["rank"] = "N/A"
    doc["fusion_details"]["value"] = 1 / 61
    collection.aggregate.return_value = [doc]
    result = AtlasDatasheetLookup(collection).search("aroTHERM")
    assert result.matches[0].ranks == {"atlas_search": 1}
    assert result.matches[0].produced_by == ["atlas_search"]
    assert result.matches[0].score == pytest.approx(1 / 61)


def test_native_stage_unavailable_falls_back_to_application_rrf():
    collection = MagicMock()
    collection.aggregate.side_effect = [
        OperationFailure("stage unavailable", code=40324),
        [sheet()],
        [sheet()],
    ]
    result = AtlasDatasheetLookup(collection).search("aroTHERM")
    assert result.mode == "hybrid" and result.fusion == "application_rrf"
    assert result.warnings
    assert result.matches[0].score == pytest.approx(2 / 61)
    assert result.matches[0].produced_by == ["atlas_search", "vector_search"]


def test_known_missing_semantic_index_degrades_honestly():
    collection = MagicMock()
    collection.aggregate.side_effect = [
        OperationFailure("unavailable", code=27),
        [sheet()],
        OperationFailure("unavailable", code=27),
    ]
    result = AtlasDatasheetLookup(collection).search("aroTHERM")
    assert result.mode == "full_text" and result.warnings
    assert result.matches[0].produced_by == ["atlas_search"]


def test_unknown_driver_failure_does_not_masquerade_as_fallback():
    collection = MagicMock()
    collection.aggregate.side_effect = [OperationFailure("auth", code=13)]
    with pytest.raises(OperationFailure):
        AtlasDatasheetLookup(collection).search("aroTHERM")


def test_datasheet_lookup_contract():
    collection = MagicMock()
    collection.find_one.return_value = sheet()
    lookup = AtlasDatasheetLookup(collection)
    assert lookup.get_full_datasheet_text(sheet()["id"]) == sheet()["text"]
    collection.find_one.return_value = None
    assert lookup.get_full_datasheet_text("missing") is None
    collection.find.return_value.sort.return_value.limit.return_value = [sheet()]
    assert len(lookup.search_by_spec(min_kw=3, max_kw=7)) == 1
    assert collection.find.call_args.args[0] == {
        "kind": "heat_pump",
        "nominal_capacity_kw": {"$gte": 3, "$lte": 7},
    }
    collection.aggregate.return_value = [native_sheet()]
    assert lookup.find_by_make_model("aroTHERM")[0].id == sheet()["id"]


def test_indexes_create_then_update_only_changed_definitions():
    db = MagicMock()
    collection = db["datasheets"]
    collection.list_search_indexes.return_value = []
    ensure_indexes(db)
    assert collection.create_search_index.call_count == 2
    collection.create_search_index.reset_mock()
    collection.list_search_indexes.return_value = [
        {"name": "datasheets_text", "latestDefinition": TEXT_DEFINITION},
        {"name": "datasheets_semantic", "latestDefinition": VECTOR_DEFINITION},
    ]
    ensure_indexes(db)
    collection.create_search_index.assert_not_called()
    collection.update_search_index.assert_not_called()
    collection.list_search_indexes.return_value[0]["latestDefinition"] = {}
    ensure_indexes(db)
    collection.update_search_index.assert_called_once_with("datasheets_text", TEXT_DEFINITION)


def test_survey_crud_preserves_id_creation_time_and_confidence():
    collection = MagicMock()
    repo = SurveyRepository(collection)
    value = SurveyInput(
        postcode="ZZ1 1ZZ",
        extracted_readings={
            "gas_kwh": {"value": 12000, "unit": "kWh", "confidence": "low"},
        },
    )
    created = repo.create(value)
    inserted = collection.insert_one.call_args.args[0]
    assert created.id == inserted["_id"]
    assert created.extracted_readings["gas_kwh"].confidence == "low"
    collection.find_one.return_value = inserted
    assert repo.get(created.id) == created
    collection.find_one_and_update.return_value = inserted
    assert repo.update(created.id, SurveyInput()) == created
    patch = collection.find_one_and_update.call_args.args[1]["$set"]
    assert "created_at" not in patch and "_id" not in patch
    collection.find.return_value.sort.return_value.limit.return_value = [inserted]
    assert repo.recent(500) == [created]
    collection.find.return_value.sort.return_value.limit.assert_called_with(100)
    collection.delete_one.return_value.deleted_count = 1
    assert repo.delete(created.id)
    collection.find_one.return_value = None
    collection.find_one_and_update.return_value = None
    assert repo.get("missing") is None and repo.update("missing", value) is None


@pytest.mark.parametrize(
    "payload",
    [
        {"images": ["private"]},
        {"epc_snapshot": {"image_bytes": "private"}},
        {"spec": {"$set": {}}},
        {"spec": {"a.b": 1}},
        {
            "extracted_readings": {
                "plate": {"value": "data:image/png;base64,private", "confidence": "low"}
            }
        },
        {"verification_log": [{"raw_bill": "private"}]},
        {"cost": {"value": float("nan")}},
    ],
)
def test_surveys_reject_images_unsafe_fields_and_nonfinite_values(payload):
    with pytest.raises(ValidationError):
        SurveyInput.model_validate(payload)


@pytest.fixture
def api():
    db = MagicMock()
    app.dependency_overrides[get_database] = lambda: db
    try:
        yield TestClient(app), db
    finally:
        app.dependency_overrides.clear()


def test_api_survey_lifecycle_and_validation(api):
    client, db = api
    response = client.post("/api/surveys", json={"postcode": "ZZ1 1ZZ"})
    assert response.status_code == 201
    survey = response.json()
    identifier = survey["id"]
    document = db["surveys"].insert_one.call_args.args[0]
    db["surveys"].find_one.return_value = document
    assert client.get(f"/api/surveys/{identifier}").json()["id"] == identifier
    db["surveys"].find_one_and_update.return_value = document
    assert client.put(f"/api/surveys/{identifier}", json={}).status_code == 200
    db["surveys"].find.return_value.sort.return_value.limit.return_value = [document]
    assert len(client.get("/api/surveys").json()) == 1
    db["surveys"].delete_one.return_value.deleted_count = 1
    assert client.delete(f"/api/surveys/{identifier}").status_code == 204
    db["surveys"].find_one.return_value = None
    assert client.get(f"/api/surveys/{identifier}").status_code == 404
    assert client.get("/api/surveys/not-a-uuid").status_code == 422
    assert client.get("/api/surveys?limit=101").status_code == 422
    assert client.post("/api/surveys", json={"photos": []}).status_code == 422


def test_api_search_scores_provenance_and_boundaries(api):
    client, db = api
    db["datasheets"].aggregate.return_value = [native_sheet()]
    response = client.get("/api/datasheets/search?q=Vailant")
    assert response.status_code == 200
    match = response.json()["matches"][0]
    assert match["score"] > 0 and match["produced_by"] == ["atlas_search", "vector_search"]
    assert client.get("/api/datasheets/search?q=x").status_code == 422
    assert client.get("/api/datasheets/search?q=%20%20").status_code == 422


def test_actual_database_dependency_sanitizes_errors(monkeypatch):
    from contextlib import contextmanager

    @contextmanager
    def failing_database():
        db = MagicMock()
        db["surveys"].insert_one.side_effect = ServerSelectionTimeoutError(
            "mongodb://private:secret@host"
        )
        yield db

    monkeypatch.setattr("gae.db.router.database", failing_database)
    client = TestClient(app)
    response = client.post("/api/surveys", json={})
    assert response.status_code == 503
    assert "secret" not in response.text and "private" not in response.text


@pytest.mark.parametrize(
    "query, expected",
    [
        ("Vaillant aro THERM plus 7kw", "heat_pump"),
        ("AROTHERM", "heat_pump"),
        ("Ecodan", "heat_pump"),
        ("Altherma", "heat_pump"),
        ("heat pump", "heat_pump"),
        ("combi", "gas_boiler"),
        ("ecoTEC", "gas_boiler"),
        ("Greenstar", "gas_boiler"),
        ("Greenstr 30i", None),
        ("Vaillant 7kw", None),
        ("notecotec", None),
        ("heat pump combi", None),
        ("", None),
    ],
)
def test_kind_inference_is_conservative(query, expected):
    assert infer_kind(query) == expected


@pytest.mark.parametrize(
    "kind, values",
    [
        ("heat_pump", ["heat_pump"]),
        ("gas_boiler", ["gas_combi", "gas_system"]),
    ],
)
def test_kind_prefilters_both_channels_and_indexes(kind, values):
    pipelines = hybrid_pipeline("Vaillant", 20, 5, kind)[0]["$rankFusion"]["input"]["pipelines"]
    search = pipelines["atlas_search"][0]["$search"]
    assert search["compound"]["filter"] == [{"in": {"path": "kind", "value": values}}]
    assert search["compound"]["must"][0]["text"]["query"] == "Vaillant"
    vector = pipelines["vector_search"][0]["$vectorSearch"]
    assert vector["filter"] == {"kind": {"$in": values}}
    assert TEXT_DEFINITION["mappings"]["fields"]["kind"] == {"type": "token"}
    assert {"type": "filter", "path": "kind"} in VECTOR_DEFINITION["fields"]


@pytest.mark.parametrize("failure", [None, 40324, 27])
def test_filters_and_match_flags_survive_native_and_fallback_paths(failure):
    collection = MagicMock()
    query = sheet()["model"]
    if failure is None:
        collection.aggregate.return_value = [native_sheet()]
    else:
        collection.aggregate.side_effect = [
            OperationFailure("unavailable", code=failure),
            [sheet()],
            [sheet()] if failure == 40324 else OperationFailure("missing", code=27),
        ]
    lookup = AtlasDatasheetLookup(collection)
    result = lookup.search(query, kind="gas_boiler")  # explicit overrides inferred heat pump
    assert result.matches[0].exact_model_match is True
    calls = collection.aggregate.call_args_list
    assert calls[0].args[0] == hybrid_pipeline(query, 20, 5, "gas_boiler")
    if failure:
        assert calls[1].args[0] == text_pipeline(query, 20, "gas_boiler")
        assert calls[2].args[0] == vector_pipeline(query, 20, "gas_boiler")


@pytest.mark.parametrize(
    "query, exact",
    [
        ("aroTHERM plus VWL 55/6 230V", True),
        (" vaillant  AROTHERM plus VWL 55/6 230V ", True),
        ("aroTHERM", False),
        ("aroTHERM plus VWL 55/6", False),
        ("Vaillant aro THERM plus 7kw", False),
        ("Greenstr 30i", False),
        ("aroTHERM plus VWL 55/6 230", False),
    ],
)
def test_exact_flag_requires_complete_model_text(query, exact):
    assert exact_model_match(query, load_seed()[0]) is exact
    collection = MagicMock()
    collection.aggregate.return_value = [native_sheet()]
    lookup = AtlasDatasheetLookup(collection)
    assert lookup.search(query).matches[0].exact_model_match is exact
    identified = lookup.find_by_make_model(query, 5, "heat_pump")[0]
    assert identified.id == sheet()["id"]
    assert identified.exact_model_match is exact


def test_api_kind_validation_and_exact_flag(api):
    client, db = api
    db["datasheets"].aggregate.return_value = [native_sheet()]
    response = client.get(
        "/api/datasheets/search",
        params={
            "q": sheet()["model"],
            "kind": "heat_pump",
        },
    )
    assert response.status_code == 200
    assert response.json()["matches"][0]["exact_model_match"] is True
    assert client.get("/api/datasheets/search?q=Vaillant&kind=oil_boiler").status_code == 422
    assert db["datasheets"].aggregate.call_count == 1


def test_search_infers_kind_but_leaves_ambiguous_queries_open():
    collection = MagicMock()
    collection.aggregate.return_value = []
    lookup = AtlasDatasheetLookup(collection)
    for query, kind in [("aro THERM", "heat_pump"), ("Greenstr 30i", None)]:
        lookup.search(query)
        assert collection.aggregate.call_args.args[0] == hybrid_pipeline(query, 20, 5, kind)
    with pytest.raises(ValueError):
        lookup.search("Vaillant", kind="oil_boiler")
