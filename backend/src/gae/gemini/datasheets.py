"""Datasheet matching for the verification loop, over `gae.db.datasheets.DatasheetLookup`.

Atlas search is fuzzy, so it always returns *something*; `match_datasheet` decides in code
whether a candidate really is the model Gemini read. `InMemoryDatasheetLookup` serves tests and
local runs without Atlas, over any list of `Datasheet` (synthetic, or the public seed).
"""

import re
from collections.abc import Iterable, Sequence

from gae.db.datasheets import DatasheetLookup
from gae.db.models import Datasheet

_TOKEN = re.compile(r"[a-z0-9]+")
# Words that appear in many model names and prove nothing about a match.
_GENERIC = {"ng", "lpg", "combi", "system", "boiler", "heat", "pump", "kw", "the", "and", "class"}


def tokens(text: str | None) -> set[str]:
    return {t for t in _TOKEN.findall((text or "").lower()) if t not in _GENERIC}


def match_datasheet(
    lookup: DatasheetLookup,
    make: str | None,
    model: str | None,
    kinds: Iterable[str],
) -> Datasheet | None:
    """The library entry for a read make/model, or None when no candidate truly matches.

    A match needs the make to agree, every size or variant code in the catalogue model, and at
    least half of its distinctive tokens (e.g. "greenstar", "4000", "25kw") in what Gemini read.
    """
    if not model:
        return None
    query = f"{make or ''} {model}".strip()
    read = tokens(query)
    best: tuple[float, Datasheet] | None = None
    for sheet in lookup.find_by_make_model(query, limit=5):
        if sheet.kind not in set(kinds):
            continue
        if make and not tokens(sheet.make) & tokens(make):
            continue
        wanted = tokens(sheet.model)
        # Size and variant codes ("6", "25kw", "wz50vaa") must all be present.
        if not wanted or not {t for t in wanted if any(ch.isdigit() for ch in t)} <= read:
            continue
        score = len(wanted & read) / len(wanted)
        if score >= 0.5 and (best is None or score > best[0]):
            best = (score, sheet)
    return best[1] if best else None


class InMemoryDatasheetLookup:
    """`DatasheetLookup` over a fixed list, ranked by token overlap with the query."""

    def __init__(self, sheets: Sequence[Datasheet]):
        self.sheets = list(sheets)

    def find_by_make_model(self, text: str, limit: int = 5) -> list[Datasheet]:
        query = tokens(text)
        scored = [(len(query & tokens(f"{s.make} {s.model}")), s.id, s) for s in self.sheets]
        hits = sorted((item for item in scored if item[0] > 0), key=lambda i: (-i[0], i[1]))
        return [sheet for _, _, sheet in hits[:limit]]

    def get_full_datasheet_text(self, datasheet_id: str) -> str | None:
        return next((s.text for s in self.sheets if s.id == datasheet_id), None)

    def search_by_spec(
        self,
        *,
        min_kw: float | None = None,
        max_kw: float | None = None,
        kind: str = "heat_pump",
        limit: int = 10,
    ) -> list[Datasheet]:
        hits = [
            s
            for s in self.sheets
            if s.kind == kind
            and s.nominal_capacity_kw is not None
            and (min_kw is None or s.nominal_capacity_kw >= min_kw)
            and (max_kw is None or s.nominal_capacity_kw <= max_kw)
        ]
        return sorted(hits, key=lambda s: (s.nominal_capacity_kw, s.id))[:limit]
