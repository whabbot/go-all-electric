"""Value types shared by the maths core: ranges and confidence levels."""

from dataclasses import dataclass
from enum import StrEnum


class Confidence(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True)
class Range:
    """A central estimate with a low-high spread, all in the same unit."""

    low: float
    central: float
    high: float

    def __post_init__(self) -> None:
        if not self.low <= self.central <= self.high:
            raise ValueError(f"Range must satisfy low <= central <= high, got {self}")

    @classmethod
    def around(cls, central: float, minus: float, plus: float | None = None) -> Range:
        """Range spanning central * (1 - minus) to central * (1 + plus); plus defaults to minus."""
        plus = minus if plus is None else plus
        return cls(central * (1 - minus), central, central * (1 + plus))

    def scale(self, factor: float) -> Range:
        """Multiply every bound by a non-negative factor."""
        if factor < 0:
            raise ValueError("factor must be non-negative")
        return Range(self.low * factor, self.central * factor, self.high * factor)

    def contains(self, value: float) -> bool:
        return self.low <= value <= self.high


@dataclass(frozen=True)
class Exact:
    """A single value whose uncertainty is a confidence level rather than a spread."""

    value: float
    confidence: Confidence
