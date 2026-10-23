"""Opt-in real mongot integration; CI skips by default.

ATLAS_LOCAL_URI=mongodb://127.0.0.1:27028/?directConnection=true \
    uv run pytest -m atlas_local -o addopts='' tests/test_db_atlas_local.py

Only a unique synthetic collection is written/deleted. No cloud model is called: toy vectors
exercise the actual vector index and hybrid fusion; managed Voyage needs a separate Atlas smoke.
"""

import os
import time
from uuid import uuid4

import pytest
from pymongo import MongoClient
from pymongo.operations import SearchIndexModel

from gae.db.datasheets import TEXT_INDEX, VECTOR_INDEX, AtlasDatasheetLookup
from gae.db.indexes import TEXT_DEFINITION
from gae.db.seed import load_seed

pytestmark = pytest.mark.atlas_local


def test_real_fuzzy_vector_and_hybrid_search(monkeypatch):
    uri = os.environ.get("ATLAS_LOCAL_URI")
    if not uri:
        pytest.skip("Set ATLAS_LOCAL_URI to an Atlas Local Docker instance")
    with MongoClient(uri, serverSelectionTimeoutMS=5000) as client:
        # Never permit the opt-in test to accidentally write into a hosted Atlas cluster.
        client.admin.command("ping")
        if any(host not in {"localhost", "127.0.0.1", "::1"} for host, _ in client.nodes):
            pytest.fail("ATLAS_LOCAL_URI must point to a loopback Atlas Local instance")
        collection = client["go_all_electric_test"][f"datasheets_{uuid4().hex}"]
        try:
            docs = [
                row.model_dump(mode="json")
                for row in [
                    *load_seed()[:2],
                    next(
                        row
                        for row in load_seed()
                        if row.kind == "gas_combi" and row.make == "Vaillant"
                    ),
                ]
            ]
            for index, doc in enumerate(docs):
                doc["_id"] = doc["id"]
                doc["test_vector"] = [1.0, float(index), 0.0]
            collection.insert_many(docs)
            collection.create_search_index(
                SearchIndexModel(
                    name=TEXT_INDEX,
                    definition=TEXT_DEFINITION,
                )
            )
            collection.create_search_index(
                SearchIndexModel(
                    name=VECTOR_INDEX,
                    type="vectorSearch",
                    definition={
                        "fields": [
                            {
                                "type": "vector",
                                "path": "test_vector",
                                "numDimensions": 3,
                                "similarity": "cosine",
                            },
                            {"type": "filter", "path": "kind"},
                        ]
                    },
                )
            )
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                indexes = list(collection.list_search_indexes())
                if len(indexes) == 2 and all(item.get("queryable") for item in indexes):
                    break
                time.sleep(1)
            else:
                pytest.fail("Atlas Local search indexes did not become queryable in 120s")

            def local_vector(query, limit, kind=None):
                from gae.db.datasheets import kind_values

                return [
                    {
                        "$vectorSearch": {
                            "index": VECTOR_INDEX,
                            "path": "test_vector",
                            "queryVector": [1.0, 0.0, 0.0],
                            "numCandidates": 100,
                            "limit": limit,
                            **({"filter": {"kind": {"$in": kind_values(kind)}}} if kind else {}),
                        }
                    }
                ]

            monkeypatch.setattr("gae.db.datasheets.vector_pipeline", local_vector)
            result = AtlasDatasheetLookup(collection).search("Vailant aroTHERM")
            assert result.mode == "hybrid"
            assert result.fusion == "native_rank_fusion"
            assert len(result.matches) == 2
            assert all(
                match.produced_by == ["atlas_search", "vector_search"] for match in result.matches
            )
            assert result.matches[0].datasheet.id == docs[0]["id"]
            assert result.matches[0].score > 0
            assert all(match.datasheet.kind == "heat_pump" for match in result.matches)
            for query, kind, expected in [
                ("Vaillant", None, 3),
                ("Vaillant", "heat_pump", 2),
                ("Vaillant", "gas_boiler", 1),
            ]:
                filtered = AtlasDatasheetLookup(collection).search(query, kind=kind)
                assert filtered.fusion == "native_rank_fusion"
                assert len(filtered.matches) == expected
                assert all(len(match.produced_by) == 2 for match in filtered.matches)
                if kind == "gas_boiler":
                    assert filtered.matches[0].datasheet.kind == "gas_combi"

        finally:
            collection.drop()
