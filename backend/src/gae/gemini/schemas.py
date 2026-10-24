"""Gemini structured-output schemas and the API payloads built from them.

Field names follow `frontend/src/api/types.ts` (`PhotoCheckResult`, `VerificationLogEntry`,
`QuoteFlag`, `QuoteCheckResult`, `AnalysisBundle`) so the UI can switch off its mocks as-is.
Reading schemas carry no image data: photos and PDFs live only in request memory.
"""

import dataclasses
import json
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, JsonValue, WithJsonSchema

from gae.heatpump.costs import CostComparison
from gae.heatpump.crosscheck import CrossCheck, ReasonCode
from gae.heatpump.fabric import FabricEstimate
from gae.heatpump.measured import MeasuredEstimate
from gae.heatpump.ranges import Confidence, Range
from gae.heatpump.spec import TargetSpec


class PhotoKind(StrEnum):
    BOILER_PLATE = "boiler_plate"
    RADIATORS = "radiators"
    FUSE_CUTOUT = "fuse_cutout"
    OUTDOOR_SPACE = "outdoor_space"
    GAS_BILL = "gas_bill"
    LOFT = "loft"


# What the instant check may see instead of what was asked for.
DetectedKind = Literal[
    "boiler_plate",
    "radiators",
    "fuse_cutout",
    "outdoor_space",
    "gas_bill",
    "loft",
    "gas_meter",
    "consumer_unit",
    "other",
]


# --- Instant photo check ---------------------------------------------------------------------


class KeyField(BaseModel):
    name: str = Field(description="snake_case field name, e.g. make, model, output_kw, rating_a")
    value: str


class PhotoGlance(BaseModel):
    """Gemini schema for the instant check: a glance, not a full extraction."""

    detected_kind: DetectedKind
    legible: bool = Field(description="Can the key text or features be read reliably?")
    key_fields: list[KeyField] = Field(description="Only values clearly visible right now.")
    confidence: Confidence
    summary: str = Field(description="Under 8 words, e.g. 'legible, 24 kW Worcester'.")
    retake_hint: str | None = Field(
        description="One short instruction when not usable, e.g. 'too blurry, move closer'."
    )
    face_visible: bool
    number_plate_visible: bool
    house_or_street_visible: bool = Field(
        description="House number, door, or street name/sign visible."
    )
    mail_or_envelope_visible: bool = Field(description="Letter, envelope or postal item visible.")
    name_address_or_meter_visible: bool = Field(
        description="Personal name, home address, supplier account or meter number visible."
    )


class PhotoCheckResult(BaseModel):
    kind: DetectedKind
    expected_kind: PhotoKind
    matches_expected: bool
    legible: bool
    usable: bool
    summary: str
    key_fields: dict[str, str]
    confidence: Confidence
    retake_hint: str | None
    privacy_warning: str | None
    model: str
    elapsed_ms: int


# --- Extractions -----------------------------------------------------------------------------


class Reading(BaseModel):
    legible: bool = Field(description="False when the key values cannot be read reliably.")
    confidence: Confidence
    notes: str = Field(description="What was unclear or assumed; empty when nothing was.")


class BoilerPlateReading(Reading):
    make: str | None
    model: str | None = Field(description="Model name as printed, including output, e.g. '30i'.")
    gc_number: str | None = Field(description="Gas Council number, e.g. '47-406-48'.")
    heating_output_kw: float | None = Field(description="Max central-heating output, kW.")
    hot_water_output_kw: float | None = Field(description="Max hot-water output (combi), kW.")
    fuel: Literal["natural_gas", "lpg", "oil", "unknown"]


class RadiatorReading(Reading):
    radiator_type: Literal[
        "single_panel", "K1", "P+", "K2", "K3", "column", "towel_rail", "other"
    ] = Field(description="K1 = 1 panel + 1 fin row, P+ = 2 panels + 1, K2 = 2 + 2, K3 = 3 + 3.")
    height_mm: int | None = Field(description="Approximate height, mm.")
    width_mm: int | None = Field(description="Approximate width, mm.")
    panels: int | None
    fin_rows: int | None = Field(description="Convector fin rows between or behind panels.")
    room: str | None


class VideoRadiator(RadiatorReading):
    first_seen: str = Field(
        description="First-seen timestamp in M:SS or MM:SS format, e.g. '0:14'."
    )
    last_seen: str | None = Field(
        default=None,
        description="Last-seen timestamp in M:SS or MM:SS format, e.g. '0:19', or null.",
    )
    could_not_judge: list[str] = Field(
        default_factory=list,
        description="Anything about this radiator that could not be judged from the clip.",
    )


class RadiatorVideoReading(Reading):
    radiator_count: int = Field(
        description="Total number of distinct radiators seen in the video walkthrough."
    )
    radiators: list[VideoRadiator] = Field(
        description="One entry per distinct radiator, in order of first appearance."
    )
    could_not_judge: list[str] = Field(
        default_factory=list,
        description="Anything across the clip that could not be judged (e.g. dark hallway).",
    )


class FuseCutoutReading(Reading):
    rating_a: int | None = Field(description="Main service fuse rating in amps, e.g. 60, 80, 100.")
    looks_like: Literal["cutout", "meter", "consumer_unit", "other"]


class OutdoorSpaceReading(Reading):
    clear_width_m: float | None
    clear_depth_m: float | None
    surface: Literal["paved", "gravel", "grass", "soil", "decking", "other", "unknown"]
    obstructions: list[str] = Field(description="Drains, windows, fences, steps near the spot.")


LoftDepthBand = Literal["0mm", "25mm", "50mm", "100mm", "150mm", "200mm", "270mm"]


class LoftReading(Reading):
    insulation_visible: bool | None = Field(
        default=None, description="Is loft floor insulation clearly visible in the photo?"
    )
    depth_mm_band: LoftDepthBand | None = Field(
        default=None,
        description=(
            "Estimated loft insulation depth band from the closed set "
            "(0mm, 25mm, 50mm, 100mm, 150mm, 200mm, 270mm); 270mm covers 270 mm or deeper."
        ),
    )
    joists_visible_above_insulation: bool | None = Field(
        default=None,
        description=(
            "Are the tops of the ceiling joists visible above the insulation "
            "(typical joists are ~100 mm deep, so buried joists indicate >=150-270 mm)?"
        ),
    )
    ruler_or_tape_visible: bool | None = Field(
        default=None,
        description="Is a tape measure or ruler visible in the insulation to show depth?",
    )


class MonthlyKwh(BaseModel):
    month: str = Field(description="YYYY-MM")
    kwh: float


class GasBillReading(Reading):
    supplier: str | None
    period_start: date | None
    period_end: date | None
    total_kwh: float | None = Field(description="Gas kWh for the whole period (not £).")
    monthly: list[MonthlyKwh] = Field(description="Month-by-month kWh if the bill shows it.")
    estimated_reading: bool | None

    def kwh_by_calendar_month(self) -> dict[int, float]:
        """Month number -> kWh, the shape `estimate_measured(monthly_gas_kwh=...)` takes."""
        out: dict[int, float] = {}
        for row in self.monthly:
            month = int(row.month[5:7])
            out[month] = out.get(month, 0.0) + row.kwh
        return out


class QuoteLineItem(BaseModel):
    description: str
    amount_gbp: float = Field(description="Negative for discounts or grant deductions.")


class QuoteReading(Reading):
    heat_pump_make: str | None
    heat_pump_model: str | None
    heat_pump_kw: float | None = Field(description="Nominal output of the quoted heat pump.")
    design_flow_temp_c: float | None
    buffer_tank: bool | None
    cylinder: str | None = Field(description="Hot-water cylinder, e.g. '200 L unvented'.")
    line_items: list[QuoteLineItem]
    total_gbp: float | None = Field(description="Final amount the customer is asked to pay.")
    grant_deducted: bool | None = Field(description="Is the BUS grant already taken off?")
    grant_amount_gbp: float | None
    mcs_heat_loss_kw: float | None = Field(description="Design heat loss if the quote states it.")


# --- Verification log ------------------------------------------------------------------------


Step = Literal["read", "check", "reread", "pass", "fail"]


class VerificationLogEntry(BaseModel):
    id: str
    step: Step
    input: str
    model: str = Field(description="Gemini model id, or 'code' for a deterministic check.")
    check: str
    passed: bool
    action: str
    at: datetime


class VerificationLog(BaseModel):
    entries: list[VerificationLogEntry] = Field(default_factory=list)

    def add(
        self, step: Step, input: str, model: str, check: str, passed: bool, action: str
    ) -> None:
        self.entries.append(
            VerificationLogEntry(
                id=f"v{len(self.entries) + 1}",
                step=step,
                input=input,
                model=model,
                check=check,
                passed=passed,
                action=action,
                at=datetime.now(UTC),
            )
        )


class VerifiedReading[T: Reading](BaseModel):
    kind: str
    status: Literal["verified", "verified_with_warnings", "couldnt_tell"]
    reading: T | None = Field(description="None when the loop gave up: never show a guess.")
    attempts: int
    warnings: list[str]
    photograph_instead: str | None
    datasheet_id: str | None = None
    log: list[VerificationLogEntry]


UpsizeStatus = Literal["ok", "marginal", "upsize", "couldnt_tell"]


class VerifiedVideoRadiator(BaseModel):
    first_seen: str
    last_seen: str | None = None
    room: str | None = None
    status: Literal["verified", "verified_with_warnings", "couldnt_tell"]
    radiator_type: (
        Literal["single_panel", "K1", "P+", "K2", "K3", "column", "towel_rail", "other"] | None
    ) = None
    panels: int | None = None
    fin_rows: int | None = None
    width_mm: int | None = None
    height_mm: int | None = None
    confidence: Confidence
    could_not_judge: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    photo_request: str | None = None
    upsize_status: UpsizeStatus = "couldnt_tell"
    output_at_flow_temp_w: float | None = None
    heat_loss_w: float | None = None
    required_output_dt50_w: float | None = None
    min_flow_temp_c: float | None = None


class RadiatorVideoResult(BaseModel):
    status: Literal["verified", "verified_with_warnings", "couldnt_tell"]
    attempts: int
    model: str
    radiator_count: int
    radiators: list[VerifiedVideoRadiator]
    photo_requests: list[str] = Field(default_factory=list)
    could_not_judge: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    log: list[VerificationLogEntry]


# --- Quote checker (deterministic flags) -----------------------------------------------------


class QuoteFlag(BaseModel):
    severity: Literal["info", "amber", "red"]
    message: str
    evidence: str


class QuoteCheckResult(BaseModel):
    filename: str
    quoted_kw: float | None
    design_flow_temp_c: float | None
    flags: list[QuoteFlag]
    questions_to_ask: list[str]
    verified: VerifiedReading[QuoteReading]


# --- One-context review ----------------------------------------------------------------------


def _jsonable(value: Any) -> Any:
    return json.loads(json.dumps(dataclasses.asdict(value)))


class MathsBundle(BaseModel):
    """Maths-core outputs, shaped like the frontend's `AnalysisBundle`."""

    measured: dict[str, JsonValue]
    fabric: dict[str, JsonValue]
    cross_check: dict[str, JsonValue]
    costs_by_flow_temp: list[dict[str, JsonValue]]
    target_spec: dict[str, JsonValue]

    @classmethod
    def from_core(
        cls,
        measured: MeasuredEstimate,
        fabric: FabricEstimate,
        cross_check: CrossCheck,
        costs_by_flow_temp: list[CostComparison],
        target_spec: TargetSpec,
    ) -> MathsBundle:
        return cls(
            measured=_jsonable(measured),
            fabric=_jsonable(fabric),
            cross_check=_jsonable(cross_check),
            costs_by_flow_temp=[_jsonable(c) for c in costs_by_flow_temp],
            target_spec=_jsonable(target_spec),
        )

    def reason_codes(self) -> list[str]:
        reasons = self.cross_check.get("reasons") or []
        return [r["code"] for r in reasons if isinstance(r, dict) and isinstance(r["code"], str)]


class MediaInput(BaseModel):
    kind: PhotoKind | Literal["quote"]
    data_base64: str = Field(max_length=15_000_000)
    mime_type: str


class QuoteInput(BaseModel):
    quote_id: str = Field(description="Label used in flags, e.g. 'Quote A (9 kW)'.")
    document: MediaInput | None = None
    # Further pages of the same quote (photos or rendered PDF pages), after `document`.
    pages: list[MediaInput] = Field(default_factory=list, max_length=7)
    reading: QuoteReading | None = None


class ReviewRequest(BaseModel):
    photos: list[MediaInput] = Field(default_factory=list, max_length=16)
    bill: MediaInput | None = None
    epc_record: dict[str, JsonValue] = Field(default_factory=dict)
    boiler: BoilerPlateReading | None = None
    bill_reading: GasBillReading | None = None
    radiators: RadiatorReading | list[RadiatorReading] | None = None
    radiator_video: RadiatorVideoResult | RadiatorVideoReading | None = None
    fuse_cutout: FuseCutoutReading | None = None
    outdoor_space: OutdoorSpaceReading | None = None
    loft: LoftReading | None = None
    quotes: list[QuoteInput] = Field(default_factory=list, max_length=5)
    maths: MathsBundle


class ConflictField(StrEnum):
    """EPC building fields and fabric-model assumptions taken by `estimate_fabric`."""

    WALL_TYPE = "wall_type"
    LOFT_INSULATION_MM = "loft_insulation_mm"
    GLAZING = "glazing"
    FLOOR_INSULATED = "floor_insulated"
    AIR_CHANGE_RATE = "air_change_rate"
    PROPERTY_TYPE = "property_type"
    STOREYS = "storeys"


class EvidenceSource(StrEnum):
    """Survey inputs that may show an EPC field or fabric assumption is outdated."""

    BOILER_PLATE = "boiler_plate"
    GAS_BILL = "gas_bill"
    FUSE_CUTOUT = "fuse_cutout"
    RADIATORS = "radiators"
    RADIATOR_VIDEO = "radiator_video"
    OUTDOOR_SPACE = "outdoor_space"
    LOFT = "loft"
    QUOTE = "quote"
    EPC = "epc"


class ProposedValue(StrEnum):
    """Closed set of corrected values across all `ConflictField` options (never free numbers)."""

    # wall_type
    SOLID_BRICK = "solid_brick"
    CAVITY_UNFILLED = "cavity_unfilled"
    CAVITY_FILLED = "cavity_filled"
    SOLID_INSULATED = "solid_insulated"
    TIMBER_FRAME = "timber_frame"
    # loft_insulation_mm
    LOFT_0MM = "0mm"
    LOFT_25MM = "25mm"
    LOFT_50MM = "50mm"
    LOFT_100MM = "100mm"
    LOFT_150MM = "150mm"
    LOFT_200MM = "200mm"
    LOFT_270MM = "270mm"
    # glazing
    SINGLE = "single"
    DOUBLE_UNKNOWN_DATE = "double_unknown_date"
    DOUBLE_PRE_2003 = "double_pre_2003"
    DOUBLE_2003_ONWARDS = "double_2003_onwards"
    TRIPLE = "triple"
    # floor_insulated
    INSULATED = "insulated"
    UNINSULATED = "uninsulated"
    # air_change_rate
    ACH_1_0 = "1.0_ach"
    ACH_1_5 = "1.5_ach"
    # property_type
    DETACHED = "detached"
    SEMI_DETACHED = "semi_detached"
    END_TERRACE = "end_terrace"
    MID_TERRACE = "mid_terrace"
    BUNGALOW = "bungalow"
    # storeys
    STOREYS_1 = "1_storey"
    STOREYS_2 = "2_storeys"
    STOREYS_3 = "3_storeys"


ALLOWED_VALUES_BY_FIELD: dict[ConflictField, tuple[ProposedValue, ...]] = {
    ConflictField.WALL_TYPE: (
        ProposedValue.SOLID_BRICK,
        ProposedValue.CAVITY_UNFILLED,
        ProposedValue.CAVITY_FILLED,
        ProposedValue.SOLID_INSULATED,
        ProposedValue.TIMBER_FRAME,
    ),
    ConflictField.LOFT_INSULATION_MM: (
        ProposedValue.LOFT_0MM,
        ProposedValue.LOFT_25MM,
        ProposedValue.LOFT_50MM,
        ProposedValue.LOFT_100MM,
        ProposedValue.LOFT_150MM,
        ProposedValue.LOFT_200MM,
        ProposedValue.LOFT_270MM,
    ),
    ConflictField.GLAZING: (
        ProposedValue.SINGLE,
        ProposedValue.DOUBLE_UNKNOWN_DATE,
        ProposedValue.DOUBLE_PRE_2003,
        ProposedValue.DOUBLE_2003_ONWARDS,
        ProposedValue.TRIPLE,
    ),
    ConflictField.FLOOR_INSULATED: (
        ProposedValue.INSULATED,
        ProposedValue.UNINSULATED,
    ),
    ConflictField.AIR_CHANGE_RATE: (
        ProposedValue.ACH_1_0,
        ProposedValue.ACH_1_5,
    ),
    ConflictField.PROPERTY_TYPE: (
        ProposedValue.DETACHED,
        ProposedValue.SEMI_DETACHED,
        ProposedValue.END_TERRACE,
        ProposedValue.MID_TERRACE,
        ProposedValue.BUNGALOW,
    ),
    ConflictField.STOREYS: (
        ProposedValue.STOREYS_1,
        ProposedValue.STOREYS_2,
        ProposedValue.STOREYS_3,
    ),
}


class EstimateDirection(StrEnum):
    LOWER = "lower"
    HIGHER = "higher"


class ConflictStatus(StrEnum):
    NO_CONFLICT_FOUND = "no_conflict_found"
    CONFLICTS_FOUND = "conflicts_found"


_ConflictFieldSchema = Annotated[
    ConflictField | str,
    WithJsonSchema(
        {
            "type": "string",
            "enum": [f.value for f in ConflictField],
            "description": "EPC field or fabric-model assumption in doubt.",
        }
    ),
]
_EvidenceSourceSchema = Annotated[
    EvidenceSource | str,
    WithJsonSchema(
        {
            "type": "string",
            "enum": [s.value for s in EvidenceSource],
            "description": "Provided input or photo that shows the conflict.",
        }
    ),
]
_ProposedValueSchema = Annotated[
    ProposedValue | str,
    WithJsonSchema(
        {
            "type": "string",
            "enum": [v.value for v in ProposedValue],
            "description": "Corrected value from the closed set for that field.",
        }
    ),
]
_EstimateDirectionSchema = Annotated[
    EstimateDirection | str,
    WithJsonSchema(
        {
            "type": "string",
            "enum": [d.value for d in EstimateDirection],
            "description": "Which direction this correction should move Estimate A.",
        }
    ),
]
_ConflictStatusSchema = Annotated[
    ConflictStatus | str,
    WithJsonSchema(
        {
            "type": "string",
            "enum": [s.value for s in ConflictStatus],
            "description": "Whether any input conflict is suspected from the evidence.",
        }
    ),
]


class InputConflictProposal(BaseModel):
    """One suspected EPC or fabric-input conflict proposed by Argon for code to test."""

    field: _ConflictFieldSchema
    evidence_source: _EvidenceSourceSchema
    evidence_summary: str = Field(
        description="Plain English: what the evidence shows in words (no unverified numbers)."
    )
    proposed_value: _ProposedValueSchema
    expected_direction: _EstimateDirectionSchema


class RangePayload(BaseModel):
    low: float
    central: float
    high: float

    @classmethod
    def from_range(cls, r: Range) -> RangePayload:
        return cls(
            low=round(r.low, 2),
            central=round(r.central, 2),
            high=round(r.high, 2),
        )


class TestedConflict(BaseModel):
    """A proposal verified by code by re-running `estimate_fabric` with that single correction."""

    field: ConflictField
    evidence_source: EvidenceSource
    evidence_summary: str
    current_value: str
    proposed_value: ProposedValue
    expected_direction: EstimateDirection
    direction_matches: bool
    original_design_load_kw: RangePayload
    new_design_load_kw: RangePayload
    original_htc_w_per_k: float
    new_htc_w_per_k: float
    original_gap_kw: float | None = None
    new_gap_kw: float | None = None
    original_gap_w_per_k: float | None = None
    new_gap_w_per_k: float | None = None
    gap_change: Literal["shrinks", "grows", "unchanged"]


class ReviewFlag(BaseModel):
    severity: Literal["info", "amber", "red"]
    message: str
    evidence: str = Field(description="Which number or document line this rests on.")


class QuoteReview(BaseModel):
    quote_id: str
    flags: list[ReviewFlag]


class ArgonReview(BaseModel):
    """Gemini schema for the one-context review."""

    estimates_explanation: str = Field(
        description="Plain English: why Estimate A (fabric) and B (measured) differ."
    )
    cited_reason_codes: list[ReasonCode]
    conflict_status: _ConflictStatusSchema = ConflictStatus.NO_CONFLICT_FOUND
    input_conflicts: list[InputConflictProposal] = Field(
        default_factory=list,
        description="Suspected EPC or fabric-input conflicts supported by provided evidence.",
    )
    quote_reviews: list[QuoteReview]
    questions_to_ask: list[str]
    summary: str


class StrippedClaim(BaseModel):
    where: str
    text: str
    numbers: list[str]


class ReviewResult(BaseModel):
    review: ArgonReview
    tested_conflicts: list[TestedConflict] = Field(default_factory=list)
    stripped: list[StrippedClaim]
    datasheets_used: list[str]
    model: str
    log: list[VerificationLogEntry]
    disclaimer: str = (
        "A second opinion with confidence ranges, not financial advice. Nothing is sent to "
        "installers or network operators. It advises; you decide."
    )
