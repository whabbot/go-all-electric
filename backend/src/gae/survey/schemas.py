"""Analysis payloads. Field names follow `frontend/src/api/types.ts` (`AnalysisResult` and friends).

Location is the postcode district only: no address, full postcode, UPRN or certificate number
appears in any response, stored survey or Gemini request built from these models.
"""

import dataclasses
import json
from typing import Any, Literal

from pydantic import BaseModel, Field, JsonValue

from gae.gemini.schemas import (
    BoilerPlateReading,
    GasBillReading,
    PhotoKind,
    QuoteReading,
    VerificationLogEntry,
)
from gae.plan.schemas import AllElectricPlan
from gae.survey.fields import NamedDefault


def jsonable(value: Any) -> Any:
    """Maths-core dataclass as plain JSON (enums become their string values)."""
    return json.loads(json.dumps(dataclasses.asdict(value)))


class AnalysisBundle(BaseModel):
    """`MathsBundle` shape; `measured` and `cross_check` are null when there is no usable bill."""

    measured: dict[str, JsonValue] | None
    fabric: dict[str, JsonValue]
    cross_check: dict[str, JsonValue] | None
    costs_by_flow_temp: list[dict[str, JsonValue]]
    target_spec: dict[str, JsonValue]


class EpcSummary(BaseModel):
    """The building from its EPC: what the maths used, never where it is."""

    property_type: str
    floor_area_m2: float | None
    age_band: str | None
    year_built: int
    wall_type: str
    glazing: str
    loft_insulation_mm: int
    floor_insulated: bool
    main_heating_fuel: str
    current_energy_efficiency_band: str | None
    walls: list[str]
    roofs: list[str]
    floors: list[str]
    windows: list[str]
    main_heating: list[str]


ReadingStatus = Literal["verified", "verified_with_warnings", "couldnt_tell", "not_provided"]


class InputReading(BaseModel):
    kind: PhotoKind
    status: ReadingStatus
    attempts: int
    # The typed reading as JSON (free-text notes blanked); null unless verified.
    reading: dict[str, JsonValue] | None
    warnings: list[str]
    photograph_instead: str | None
    used_for: str


class Gap(BaseModel):
    """Something we couldn't tell, what it means for the answer, and what to provide instead."""

    input: str
    message: str
    provide: str


class AnalysisResult(BaseModel):
    survey_id: str | None
    saved: bool
    storage_note: str | None
    postcode_district: str | None
    epc: EpcSummary
    bundle: AnalysisBundle
    size_basis: Literal["measured", "fabric"]
    readings: list[InputReading]
    gaps: list[Gap]
    defaults: list[NamedDefault]
    plan: AllElectricPlan
    log: list[VerificationLogEntry]
    timings_ms: dict[str, int]


class ReviewQuote(BaseModel):
    quote_id: str = Field(max_length=60)
    reading: QuoteReading | None = None


class ReviewContext(BaseModel):
    """What the browser sends back for the review: the bundle and readings, never images."""

    bundle: AnalysisBundle
    epc: EpcSummary
    boiler: BoilerPlateReading | None = None
    bill: GasBillReading | None = None
    quotes: list[ReviewQuote] = Field(default_factory=list, max_length=5)
