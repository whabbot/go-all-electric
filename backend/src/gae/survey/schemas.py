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
    EnteredValue,
    FuseCutoutReading,
    GasBillReading,
    LoftReading,
    OutdoorSpaceReading,
    PhotoKind,
    QuoteReading,
    RadiatorReading,
    RadiatorVideoReading,
    RadiatorVideoResult,
    VerificationLogEntry,
)
from gae.plan.schemas import AllElectricPlan
from gae.survey.fields import NamedDefault
from gae.survey.known import Disagreement


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
    storeys: int = 2
    age_band: str | None
    year_built: int
    wall_type: str
    glazing: str
    loft_insulation_mm: int
    floor_insulated: bool
    design_outdoor_temp_c: float = -2.0
    main_heating_fuel: str
    current_energy_efficiency_band: str | None
    walls: list[str]
    roofs: list[str]
    floors: list[str]
    windows: list[str]
    main_heating: list[str]


# "entered": no photo was read (or it couldn't be), only what the homeowner typed in.
ReadingStatus = Literal[
    "verified", "verified_with_warnings", "couldnt_tell", "not_provided", "entered"
]


class InputReading(BaseModel):
    kind: PhotoKind
    status: ReadingStatus
    attempts: int
    # The typed reading as JSON (free-text notes blanked); null unless verified.
    reading: dict[str, JsonValue] | None
    warnings: list[str]
    photograph_instead: str | None
    used_for: str
    # Radiators only: which radiator this is (0 = radiator 1), however many photos it had.
    index: int | None = None
    # Values the homeowner entered; they are already applied to `reading`.
    entered: dict[str, JsonValue] = Field(default_factory=dict)
    # Where the photo reading differs from an entered value (the entered value is used).
    disagreements: list[Disagreement] = Field(default_factory=list)


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
    radiator_video: RadiatorVideoResult | None = None
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
    # One entry per radiator by position (radiator 1 first); null where nothing was read.
    radiators: RadiatorReading | list[RadiatorReading | None] | None = None
    radiator_video: RadiatorVideoResult | RadiatorVideoReading | None = None
    fuse_cutout: FuseCutoutReading | None = None
    outdoor_space: OutdoorSpaceReading | None = None
    loft: LoftReading | None = None
    quotes: list[ReviewQuote] = Field(default_factory=list, max_length=5)
    # Values the homeowner entered (already applied to the readings above), with any
    # photo reading that disagreed, so the review sees both.
    entered: list[EnteredValue] = Field(default_factory=list, max_length=60)
