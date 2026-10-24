"""Details the homeowner already knows, entered by hand instead of (or as well as) a photo.

An entered value wins over the Gemini reading for that field. When a photo reading disagrees,
the disagreement is kept and shown rather than one value being picked silently.

Radiator labels (room names) are display-only in the browser and are never sent here: the
models forbid unknown fields, so a label cannot reach a Gemini request through this path.
"""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

from gae.gemini.checks import RADIATOR_SHAPES, STANDARD_FUSE_RATINGS_A
from gae.gemini.review import CERTIFICATE_ID, POSTCODE
from gae.gemini.schemas import PhotoKind

MAX_RADIATORS = 8

RadiatorType = Literal["single_panel", "K1", "P+", "K2", "K3", "column", "towel_rail", "other"]


class _Known(BaseModel):
    model_config = ConfigDict(extra="forbid")

    def values(self) -> dict[str, JsonValue]:
        """Entered fields only, in the reading schema's field names."""
        return self.model_dump(mode="json", exclude_none=True)


class KnownRadiator(_Known):
    radiator_type: RadiatorType | None = None
    panels: int | None = Field(default=None, ge=1, le=3)
    fin_rows: int | None = Field(default=None, ge=0, le=3)
    width_mm: int | None = Field(default=None, ge=300, le=3000)
    height_mm: int | None = Field(default=None, ge=250, le=2000)

    @model_validator(mode="after")
    def _shape_matches_type(self) -> Self:
        shape = RADIATOR_SHAPES.get(self.radiator_type or "")
        if shape is None:
            return self
        panels, fins = shape
        if (self.panels is not None and self.panels != panels) or (
            self.fin_rows is not None and self.fin_rows != fins
        ):
            raise ValueError(
                f"A {self.radiator_type} radiator has {panels} panel(s) and {fins} fin row(s)"
            )
        return self


class KnownBoiler(_Known):
    make: str | None = Field(default=None, max_length=40)
    model: str | None = Field(default=None, max_length=60)
    heating_output_kw: float | None = Field(default=None, ge=3, le=70)
    hot_water_output_kw: float | None = Field(default=None, ge=3, le=70)

    @field_validator("make", "model")
    @classmethod
    def _plain_text(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        value = " ".join(value.split())
        if POSTCODE.search(value) or CERTIFICATE_ID.search(value):
            raise ValueError("Enter the boiler make or model only")
        return value


class KnownFuse(_Known):
    rating_a: int | None = None

    @field_validator("rating_a")
    @classmethod
    def _standard_rating(cls, value: int | None) -> int | None:
        if value is not None and value not in STANDARD_FUSE_RATINGS_A:
            allowed = ", ".join(str(a) for a in sorted(STANDARD_FUSE_RATINGS_A))
            raise ValueError(f"Main fuse ratings are {allowed} A")
        return value


class KnownDetails(_Known):
    """Everything entered by hand, radiators keyed by position (radiator 1 is index 0)."""

    radiators: list[KnownRadiator] = Field(default_factory=list, max_length=MAX_RADIATORS)
    boiler: KnownBoiler | None = None
    fuse_cutout: KnownFuse | None = None


class Disagreement(BaseModel):
    """A photo reading that differs from what the homeowner entered; the entered value is used."""

    model_config = ConfigDict(extra="forbid")

    field: str = Field(max_length=40)
    entered: float | int | str
    read: float | int | str

    @field_validator("entered", "read")
    @classmethod
    def _short(cls, value: float | int | str) -> float | int | str:
        if isinstance(value, str) and len(value) > 60:
            raise ValueError("too long")
        return value


# Numbers within this relative tolerance of the entered value count as agreeing: photo
# readings of size and output are approximate, counts and fuse ratings are not.
_TOLERANCE = {
    "width_mm": 0.1,
    "height_mm": 0.1,
    "heating_output_kw": 0.05,
    "hot_water_output_kw": 0.05,
}


def _agrees(field: str, entered: JsonValue, read: JsonValue) -> bool:
    if isinstance(entered, str) and isinstance(read, str):
        a, b = (" ".join(v.casefold().replace("-", " ").split()) for v in (entered, read))
        # "Worcester" vs "Worcester Bosch": one naming the other is not a disagreement.
        return a in b or b in a if field in ("make", "model") else a == b
    if isinstance(entered, int | float) and isinstance(read, int | float):
        tolerance = _TOLERANCE.get(field, 0.0)
        return abs(entered - read) <= tolerance * abs(entered)
    return entered == read


def apply_entered(
    reading: dict[str, JsonValue] | None, entered: dict[str, JsonValue]
) -> tuple[dict[str, JsonValue] | None, list[Disagreement]]:
    """The photo reading with every entered field taking its place, plus the disagreements."""
    if reading is None:
        return None, []
    disagreements = [
        Disagreement(field=field, entered=value, read=reading[field])
        for field, value in entered.items()
        if reading.get(field) is not None and not _agrees(field, value, reading[field])
    ]
    return {**reading, **entered}, disagreements


def entered_for(known: KnownDetails | None, kind: PhotoKind) -> dict[str, JsonValue]:
    if known is None:
        return {}
    item = {PhotoKind.BOILER_PLATE: known.boiler, PhotoKind.FUSE_CUTOUT: known.fuse_cutout}.get(
        kind
    )
    return item.values() if item is not None else {}
