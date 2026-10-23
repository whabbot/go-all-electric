"""Public datasheet lookup. Search queries must contain model text, never bill/address text.

Native $rankFusion combines Atlas ranked results. Python RRF supports older clusters;
responses explicitly identify the fusion implementation and any degraded search.
"""

from typing import Protocol

from pymongo.collection import Collection
from pymongo.errors import OperationFailure

from gae.db.models import Datasheet, SearchMatch, SearchResults

TEXT_INDEX = "datasheets_text"
VECTOR_INDEX = "datasheets_semantic"
EMBEDDING_MODEL = "voyage-4-lite"


class DatasheetLookup(Protocol):
    def find_by_make_model(self, text: str, limit: int = 5) -> list[Datasheet]: ...
    def get_full_datasheet_text(self, datasheet_id: str) -> str | None: ...
    def search_by_spec(
        self,
        *,
        min_kw: float | None = None,
        max_kw: float | None = None,
        kind: str = "heat_pump",
        limit: int = 10,
    ) -> list[Datasheet]: ...


def text_pipeline(query: str, limit: int) -> list[dict]:
    return [
        {
            "$search": {
                "index": TEXT_INDEX,
                "text": {
                    "query": query,
                    "path": ["make", "model", "text"],
                    "fuzzy": {"maxEdits": 2, "prefixLength": 1, "maxExpansions": 50},
                },
            }
        },
        {"$limit": limit},
    ]


def vector_pipeline(query: str, limit: int) -> list[dict]:
    return [
        {
            "$vectorSearch": {
                "index": VECTOR_INDEX,
                "path": "text",
                "query": query,
                "model": EMBEDDING_MODEL,
                "numCandidates": max(100, limit * 20),
                "limit": limit,
            }
        }
    ]


def hybrid_pipeline(query: str, candidates: int, limit: int) -> list[dict]:
    return [
        {
            "$rankFusion": {
                "input": {
                    "pipelines": {
                        "atlas_search": text_pipeline(query, candidates),
                        "vector_search": vector_pipeline(query, candidates),
                    }
                },
                "combination": {"weights": {"atlas_search": 1, "vector_search": 1}},
                "scoreDetails": True,
            }
        },
        {"$limit": limit},
        {"$addFields": {"fusion_details": {"$meta": "scoreDetails"}}},
    ]


def native_match(document: dict) -> SearchMatch:
    details = document["fusion_details"]
    ranks = {
        item["inputPipelineName"]: item["rank"]
        for item in details["details"]
        if item.get("inputPipelineName") in {"atlas_search", "vector_search"}
        and isinstance(item.get("rank"), int)
        and item["rank"] > 0
    }
    return SearchMatch(
        datasheet=as_datasheet(document),
        score=details["value"],
        produced_by=sorted(ranks),
        ranks=ranks,
    )


def as_datasheet(document: dict) -> Datasheet:
    return Datasheet.model_validate(
        {key: value for key, value in document.items() if key in Datasheet.model_fields}
    )


def fuse(channels: dict[str, list[dict]], limit: int) -> list[SearchMatch]:
    matches: dict[str, SearchMatch] = {}
    for channel, docs in channels.items():
        seen = set()
        for rank, doc in enumerate(docs, 1):
            sheet = as_datasheet(doc)
            if sheet.id in seen:
                continue
            seen.add(sheet.id)
            if sheet.id not in matches:
                matches[sheet.id] = SearchMatch(datasheet=sheet, score=0, produced_by=[], ranks={})
            result = matches[sheet.id]
            result.score += 1 / (60 + rank)
            result.produced_by.append(channel)
            result.ranks[channel] = rank
    return sorted(matches.values(), key=lambda m: (-m.score, m.datasheet.id))[:limit]


class AtlasDatasheetLookup:
    def __init__(self, collection: Collection):
        self.collection = collection

    def search(self, text: str, limit: int = 5) -> SearchResults:
        limit = max(1, min(limit, 20))
        candidates = max(20, limit * 3)
        try:
            documents = list(
                self.collection.aggregate(
                    hybrid_pipeline(text, candidates, limit),
                    maxTimeMS=10000,
                )
            )
            return SearchResults(
                matches=[native_match(doc) for doc in documents],
                mode="hybrid",
                fusion="native_rank_fusion",
            )
        except OperationFailure as exc:
            # Only known unavailable stages/indexes enter compatibility handling. A bad
            # credential, timeout or unknown error must propagate to the API's generic 503.
            if exc.code not in {27, 59, 72, 115, 31082, 40324}:
                raise
        full_text = list(
            self.collection.aggregate(text_pipeline(text, candidates), maxTimeMS=10000)
        )
        try:
            vector = list(
                self.collection.aggregate(vector_pipeline(text, candidates), maxTimeMS=10000)
            )
        except OperationFailure as exc:
            # Only known missing-index / unsupported-feature failures degrade. Auth, network,
            # and other operational errors must not masquerade as successful semantic search.
            if exc.code not in {27, 59, 72, 115, 31082}:
                raise
            return SearchResults(
                matches=fuse({"atlas_search": full_text}, limit),
                mode="full_text",
                warnings=["Semantic index unavailable; fuzzy full-text results only."],
            )
        return SearchResults(
            matches=fuse({"atlas_search": full_text, "vector_search": vector}, limit),
            mode="hybrid",
            fusion="application_rrf",
            warnings=["Native fusion unavailable; application reciprocal-rank fusion used."],
        )

    def find_by_make_model(self, text: str, limit: int = 5) -> list[Datasheet]:
        return [match.datasheet for match in self.search(text, limit).matches]

    def get_full_datasheet_text(self, datasheet_id: str) -> str | None:
        doc = self.collection.find_one({"_id": datasheet_id})
        return as_datasheet(doc).text if doc else None

    def search_by_spec(
        self,
        *,
        min_kw: float | None = None,
        max_kw: float | None = None,
        kind: str = "heat_pump",
        limit: int = 10,
    ) -> list[Datasheet]:
        query: dict = {"kind": kind}
        bounds = {}
        if min_kw is not None:
            bounds["$gte"] = min_kw
        if max_kw is not None:
            bounds["$lte"] = max_kw
        if bounds:
            query["nominal_capacity_kw"] = bounds
        return [
            as_datasheet(doc)
            for doc in self.collection.find(query)
            .sort([("nominal_capacity_kw", 1), ("_id", 1)])
            .limit(max(1, min(limit, 20)))
        ]
