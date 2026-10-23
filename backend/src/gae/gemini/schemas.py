"""Gemini structured-output schemas and the API payloads built from them.

Field names follow `frontend/src/api/types.ts` (`PhotoCheckResult`, `VerificationLogEntry`,
`QuoteFlag`, `QuoteCheckResult`, `AnalysisBundle`) so the UI can switch off its mocks as-is.
Reading schemas carry no image data: photos and PDFs live only in request memory.
"""

import dataclasses
import json
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, JsonValue

from gae.heatpump.costs import CostComparison
from gae.heatpump.crosscheck import CrossCheck, ReasonCode
from gae.heatpump.fabric import FabricEstimate
from gae.heatpump.measured import MeasuredEstimate
from gae.heatpump.ranges import Confidence
from gae.heatpump.spec import TargetSpec


class PhotoKind(StrEnum):
    BOILER_PLATE = "boiler_plate"
    RADIATORS = "radiators"
    FUSE_CUTOUT = "fuse_cutout"
    OUTDOOR_SPACE = "outdoor_space"
    GAS_BILL = "gas_bill"


# What the instant check may see instead of what was asked for.
DetectedKind = Literal[
    "boiler_plate",
    "radiators",
    "fuse_cutout",
    "outdoor_space",
    "gas_bill",
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


class FuseCutoutReading(Reading):
    rating_a: int | None = Field(description="Main service fuse rating in amps, e.g. 60, 80, 100.")
    looks_like: Literal["cutout", "meter", "consumer_unit", "other"]


class OutdoorSpaceReading(Reading):
    clear_width_m: float | None
    clear_depth_m: float | None
    surface: Literal["paved", "gravel", "grass", "soil", "decking", "other", "unknown"]
    obstructions: list[str] = Field(description="Drains, windows, fences, steps near the spot.")


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
    ) -> "MathsBundle":
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
    photos: list[MediaInput] = Field(default_factory=list, max_length=12)
    bill: MediaInput | None = None
    epc_record: dict[str, JsonValue] = Field(default_factory=dict)
    boiler: BoilerPlateReading | None = None
    bill_reading: GasBillReading | None = None
    quotes: list[QuoteInput] = Field(default_factory=list, max_length=5)
    maths: MathsBundle


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
    quote_reviews: list[QuoteReview]
    questions_to_ask: list[str]
    summary: str


class StrippedClaim(BaseModel):
    where: str
    text: str
    numbers: list[str]


class ReviewResult(BaseModel):
    review: ArgonReview
    stripped: list[StrippedClaim]
    datasheets_used: list[str]
    model: str
    log: list[VerificationLogEntry]
    disclaimer: str = (
        "A second opinion with confidence ranges, not financial advice. Nothing is sent to "
        "installers or network operators. It advises; you decide."
    )
