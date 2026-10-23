"""Public datasheet lookup. Search queries must contain model text, never bill/address text.

Native $rankFusion combines Atlas ranked results. Python RRF supports older clusters;
responses explicitly identify the fusion implementation and any degraded search.
"""

import re
from typing import Literal, Protocol

from pymongo.collection import Collection
from pymongo.errors import OperationFailure

from gae.db.models import Datasheet, DatasheetIdentification, SearchMatch, SearchResults

TEXT_INDEX = "datasheets_text"
VECTOR_INDEX = "datasheets_semantic"
EMBEDDING_MODEL = "voyage-4-lite"


EquipmentKind = Literal["heat_pump", "gas_boiler"]


def infer_kind(text: str) -> EquipmentKind | None:
    """Only explicit equipment-family tokens justify narrowing the search.

    Conflicting tokens leave the search open. Whitespace inside aro THERM is
    accepted, as commonly extracted from equipment plates.
    """
    heat = re.search(r"\b(?:aro\s*therm|ecodan|altherma|heat[\s-]+pump)\b", text, re.I)
    gas = re.search(r"\b(?:combi|ecotec|greenstar)\b", text, re.I)
    if bool(heat) == bool(gas):
        return None
    return "heat_pump" if heat else "gas_boiler"


def kind_values(kind: EquipmentKind) -> list[str]:
    # The seed distinguishes combi and system boilers; the public filter groups both.
    if kind == "gas_boiler":
        return ["gas_combi", "gas_system"]
    if kind == "heat_pump":
        return ["heat_pump"]
    raise ValueError("Unsupported equipment kind")


def exact_model_match(query: str, sheet: Datasheet) -> bool:
    """Exact complete model (optionally prefixed by make), ignoring case/spacing.

    Keep punctuation and all model suffixes: fuzzy/family/capacity-only matches
    are related results, even when they lead the ranking. This is textual equality,
    not verification that the homeowner owns this equipment.
    """

    def normalize(value: str) -> str:
        return " ".join(value.casefold().split())

    return normalize(query) in {normalize(sheet.model), normalize(f"{sheet.make} {sheet.model}")}


class DatasheetLookup(Protocol):
    def find_by_make_model(
        self, text: str, limit: int = 5, kind: EquipmentKind | None = None
    ) -> list[DatasheetIdentification]: ...
    def get_full_datasheet_text(self, datasheet_id: str) -> str | None: ...
    def search_by_spec(
        self,
        *,
        min_kw: float | None = None,
        max_kw: float | None = None,
        kind: str = "heat_pump",
        limit: int = 10,
    ) -> list[Datasheet]: ...


def text_pipeline(query: str, limit: int, kind: EquipmentKind | None = None) -> list[dict]:
    clause = {
        "text": {
            "query": query,
            "path": ["make", "model", "text"],
            "fuzzy": {"maxEdits": 2, "prefixLength": 1, "maxExpansions": 50},
        }
    }
    if kind is not None:
        clause = {
            "compound": {
                "must": [clause],
                "filter": [{"in": {"path": "kind", "value": kind_values(kind)}}],
            }
        }
    return [{"$search": {"index": TEXT_INDEX, **clause}}, {"$limit": limit}]


def vector_pipeline(query: str, limit: int, kind: EquipmentKind | None = None) -> list[dict]:
    stage = {
        "index": VECTOR_INDEX,
        "path": "text",
        "query": query,
        "model": EMBEDDING_MODEL,
        "numCandidates": max(100, limit * 20),
        "limit": limit,
    }
    if kind is not None:
        stage["filter"] = {"kind": {"$in": kind_values(kind)}}
    return [{"$vectorSearch": stage}]


def hybrid_pipeline(
    query: str, candidates: int, limit: int, kind: EquipmentKind | None = None
) -> list[dict]:
    return [
        {
            "$rankFusion": {
                "input": {
                    "pipelines": {
                        "atlas_search": text_pipeline(query, candidates, kind),
                        "vector_search": vector_pipeline(query, candidates, kind),
                    }
                },
                "combination": {"weights": {"atlas_search": 1, "vector_search": 1}},
                "scoreDetails": True,
            }
        },
        {"$limit": limit},
        {"$addFields": {"fusion_details": {"$meta": "scoreDetails"}}},
    ]


def native_match(document: dict, query: str = "") -> SearchMatch:
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
        exact_model_match=exact_model_match(query, as_datasheet(document)),
        score=details["value"],
        produced_by=sorted(ranks),
        ranks=ranks,
    )


def as_datasheet(document: dict) -> Datasheet:
    return Datasheet.model_validate(
        {key: value for key, value in document.items() if key in Datasheet.model_fields}
    )


def fuse(channels: dict[str, list[dict]], limit: int, query: str = "") -> list[SearchMatch]:
    matches: dict[str, SearchMatch] = {}
    for channel, docs in channels.items():
        seen = set()
        for rank, doc in enumerate(docs, 1):
            sheet = as_datasheet(doc)
            if sheet.id in seen:
                continue
            seen.add(sheet.id)
            if sheet.id not in matches:
                matches[sheet.id] = SearchMatch(
                    datasheet=sheet,
                    exact_model_match=exact_model_match(query, sheet),
                    score=0,
                    produced_by=[],
                    ranks={},
                )
            result = matches[sheet.id]
            result.score += 1 / (60 + rank)
            result.produced_by.append(channel)
            result.ranks[channel] = rank
    return sorted(matches.values(), key=lambda m: (-m.score, m.datasheet.id))[:limit]


class AtlasDatasheetLookup:
    def __init__(self, collection: Collection):
        self.collection = collection

    def search(self, text: str, limit: int = 5, kind: EquipmentKind | None = None) -> SearchResults:
        kind = kind if kind is not None else infer_kind(text)
        if kind is not None:
            kind_values(kind)
        limit = max(1, min(limit, 20))
        candidates = max(20, limit * 3)
        try:
            documents = list(
                self.collection.aggregate(
                    hybrid_pipeline(text, candidates, limit, kind),
                    maxTimeMS=10000,
                )
            )
            return SearchResults(
                matches=[native_match(doc, text) for doc in documents],
                mode="hybrid",
                fusion="native_rank_fusion",
            )
        except OperationFailure as exc:
            # Only known unavailable stages/indexes enter compatibility handling. A bad
            # credential, timeout or unknown error must propagate to the API's generic 503.
            if exc.code not in {27, 59, 72, 115, 31082, 40324}:
                raise
        full_text = list(
            self.collection.aggregate(text_pipeline(text, candidates, kind), maxTimeMS=10000)
        )
        try:
            vector = list(
                self.collection.aggregate(vector_pipeline(text, candidates, kind), maxTimeMS=10000)
            )
        except OperationFailure as exc:
            # Only known missing-index / unsupported-feature failures degrade. Auth, network,
            # and other operational errors must not masquerade as successful semantic search.
            if exc.code not in {27, 59, 72, 115, 31082}:
                raise
            return SearchResults(
                matches=fuse({"atlas_search": full_text}, limit, text),
                mode="full_text",
                warnings=["Semantic index unavailable; fuzzy full-text results only."],
            )
        return SearchResults(
            matches=fuse({"atlas_search": full_text, "vector_search": vector}, limit, text),
            mode="hybrid",
            fusion="application_rrf",
            warnings=["Native fusion unavailable; application reciprocal-rank fusion used."],
        )

    def find_by_make_model(
        self, text: str, limit: int = 5, kind: EquipmentKind | None = None
    ) -> list[DatasheetIdentification]:
        return [
            DatasheetIdentification(
                **match.datasheet.model_dump(), exact_model_match=match.exact_model_match
            )
            for match in self.search(text, limit, kind).matches
        ]

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
