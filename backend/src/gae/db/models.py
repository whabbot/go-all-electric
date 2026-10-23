"""Extracted survey values only. Images and arbitrary document blobs are rejected."""

import json
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Reading(StrictModel):
    value: str | float | bool | None
    unit: str | None = None
    confidence: Literal["low", "medium", "high"]
    evidence: str = Field(default="", max_length=500)


class SurveyInput(StrictModel):
    # Location is the postcode district (outward code, e.g. "SW1A") only: never an address,
    # full postcode, UPRN or certificate number, so a stored survey cannot locate the house.
    postcode_district: str | None = Field(
        default=None, pattern=r"^(?:[A-Z]{1,2}[0-9][A-Z0-9]?|GIR)$"
    )
    epc_snapshot: dict[str, JsonValue] = Field(default_factory=dict)
    extracted_readings: dict[str, Reading] = Field(default_factory=dict)
    estimates: dict[str, JsonValue] = Field(default_factory=dict)
    cross_check: dict[str, JsonValue] = Field(default_factory=dict)
    cost: dict[str, JsonValue] = Field(default_factory=dict)
    spec: dict[str, JsonValue] = Field(default_factory=dict)
    quote_checks: list[dict[str, JsonValue]] = Field(default_factory=list)
    verification_log: list[dict[str, JsonValue]] = Field(default_factory=list)

    @model_validator(mode="after")
    def extracted_data_only(self) -> "SurveyInput":
        # Defense in depth for structured sections whose shape belongs to other workers.
        # This is not a face/plate detector: upstream must discard photos after extraction.
        forbidden = {
            "image",
            "images",
            "image_bytes",
            "photo",
            "photos",
            "base64",
            "raw_bill",
            "raw_quote",
            "face",
            "faces",
            "number_plate",
            "api_key",
            # Location identifiers: the district above is the only location kept.
            "postcode",
            "uprn",
            "certificate_id",
            "certificate_number",
            "lmk_key",
        }

        def check(value: JsonValue) -> None:
            if isinstance(value, dict):
                for key, child in value.items():
                    lowered = key.lower()
                    if (
                        lowered in forbidden
                        or lowered.startswith("address")
                        or key.startswith("$")
                        or "." in key
                    ):
                        raise ValueError("Store extracted values only; unsafe field name")
                    check(child)
            elif isinstance(value, list):
                for child in value:
                    check(child)
            elif isinstance(value, str) and (len(value) > 2000 or "data:image" in value.lower()):
                raise ValueError("Store short extracted values only; image payloads are forbidden")

        payload = self.model_dump(mode="json")
        check(payload)
        if len(json.dumps(payload)) > 100_000:
            raise ValueError("Survey exceeds extracted-data size limit")
        return self


class Survey(SurveyInput):
    id: str
    created_at: datetime
    updated_at: datetime


class Datasheet(StrictModel):
    id: str
    make: str
    model: str
    kind: Literal["heat_pump", "gas_combi", "gas_system"]
    nominal_capacity_kw: float | None = None
    heating_min_kw: float | None = None
    heating_max_kw: float | None = None
    scop_35: float | None = None
    scop_55: float | None = None
    sound_power_db_a: float | None = None
    refrigerant: str | None = None
    dimensions_h_w_d_mm: tuple[float, float, float] | None = None
    source_url: str
    notes: str
    text: str


class DatasheetIdentification(Datasheet):
    exact_model_match: bool = False


class SearchMatch(StrictModel):
    exact_model_match: bool = False
    datasheet: Datasheet
    score: float
    produced_by: list[str]
    ranks: dict[str, int]


class SearchResults(StrictModel):
    matches: list[SearchMatch]
    mode: Literal["hybrid", "full_text"]
    fusion: Literal["native_rank_fusion", "application_rrf", "none"] = "none"
    warnings: list[str] = Field(default_factory=list)
