"""Installer-draft request and response.

The request carries numbers, verified quote fields and the quote checker's own flags only. It
has no field for an address, name, account or meter number, and unknown fields are rejected, so
nothing identifying can ride along. Quotes are named by label ("Quote C (12 kW)"), never by file
name, and free text that looks like a postcode or an email address is refused.
"""

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from gae.gemini.review import POSTCODE
from gae.gemini.schemas import QuoteFlag, StrippedClaim, VerificationLogEntry

EMAIL = re.compile(r"\S+@\S+\.\S+")
QUOTE_LABEL = r"^Quote [A-E]( \(\d{1,2}(\.\d{1,2})? kW\))?$"


def _anonymous(value: str) -> str:
    if POSTCODE.search(value) or EMAIL.search(value):
        raise ValueError("looks like a postcode or email address; leave personal details out")
    return value


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Range(Strict):
    low: float
    central: float
    high: float


class PackBundle(Strict):
    """From the maths core: what a right-sized installation looks like for this home."""

    size_kw: Range
    max_flow_temp_c: float
    measured_design_load_kw: Range | None = None
    htc_w_per_k: Range | None = None
    grant_gbp: float | None = None


class QuoteSummary(Strict):
    """The verified quote reading, minus notes and line items (they can carry an address)."""

    heat_pump_make: str | None = Field(default=None, max_length=60)
    heat_pump_model: str | None = Field(default=None, max_length=80)
    heat_pump_kw: float | None = None
    design_flow_temp_c: float | None = None
    buffer_tank: bool | None = None
    total_gbp: float | None = None
    grant_deducted: bool | None = None
    grant_amount_gbp: float | None = None
    mcs_heat_loss_kw: float | None = None

    @field_validator("heat_pump_make", "heat_pump_model")
    @classmethod
    def _no_personal_details(cls, value: str | None) -> str | None:
        return _anonymous(value) if value else value


class PackFlag(QuoteFlag):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(max_length=300)
    evidence: str = Field(max_length=300)

    @field_validator("message", "evidence")
    @classmethod
    def _no_personal_details(cls, value: str) -> str:
        return _anonymous(value)


class PackQuote(Strict):
    label: str = Field(pattern=QUOTE_LABEL, description="e.g. 'Quote C (12 kW)'")
    reading: QuoteSummary | None = None
    flags: list[PackFlag] = Field(default_factory=list, max_length=12)
    questions: list[str] = Field(default_factory=list, max_length=12)

    @field_validator("questions")
    @classmethod
    def _questions(cls, value: list[str]) -> list[str]:
        if any(len(q) > 300 for q in value):
            raise ValueError("questions are 300 characters at most")
        return [_anonymous(q) for q in value]


class InstallerDraftsRequest(Strict):
    bundle: PackBundle
    quotes: list[PackQuote] = Field(min_length=1, max_length=5)
    fuse_rating_a: int | None = Field(default=None, ge=0, le=200)


class SuggestedModel(BaseModel):
    """A right-sized heat pump from our public datasheet library."""

    datasheet_id: str
    make: str
    model: str
    nominal_capacity_kw: float
    scop_35: float | None
    source_url: str


class ArgonEmail(BaseModel):
    """Gemini schema for one installer email."""

    subject: str
    body: str = Field(description="Plain-text email body, short paragraphs, no numbered lists.")
    requested_model_ids: list[str] = Field(
        description="datasheet_id of each RIGHT_SIZED_MODELS entry the email asks a re-quote on."
    )


class InstallerDraft(BaseModel):
    quote_label: str
    source: Literal["argon", "template"]
    subject: str
    text: str
    stripped: list[StrippedClaim]
    models: list[SuggestedModel]
    fallback_reason: str | None = None
    elapsed_ms: int
    log: list[VerificationLogEntry]


class InstallerDraftsResult(BaseModel):
    drafts: list[InstallerDraft]
    model: str
    disclaimer: str = (
        "Drafts only. Nothing is sent to installers: review, edit and copy them yourself. "
        "It advises; you decide."
    )
