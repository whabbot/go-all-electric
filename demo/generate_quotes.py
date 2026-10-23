"""Generate explicitly fictional quotes, using only models in the public datasheet seed."""

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen.canvas import Canvas

ROOT = Path(__file__).resolve().parent
SAMPLE_MARK = "SAMPLE - not a real quote"


@dataclass(frozen=True)
class Quote:
    letter: str
    model: dict
    flow_c: int
    heat_loss_kw: float
    buffer: bool
    grant_deducted: bool
    items: tuple[tuple[str, int], ...]

    @property
    def total_gbp(self) -> int:
        return sum(amount for _, amount in self.items)

    @property
    def filename(self) -> str:
        return f"sample-quote-{self.letter.lower()}.pdf"


def build_quotes(low: float = 5, high: float = 7, load: float = 4.7) -> list[Quote]:
    if not all(math.isfinite(n) and n > 0 for n in (low, high, load)) or low > high:
        raise ValueError("Use positive finite numbers and size-low <= size-high.")
    seed = json.loads((ROOT.parent / "backend/src/gae/db/datasheets.json").read_text())
    models = [m for m in seed if m["kind"] == "heat_pump"]

    def nearest(candidates: list[dict], target: float) -> dict:
        if not candidates:
            raise ValueError(
                "Seed cannot supply an in-range A and two larger, distinct B/C models. "
                "Choose a supported range; no unseeded model will be invented."
            )
        return min(
            candidates,
            key=lambda m: (
                abs(m["nominal_capacity_kw"] - target),
                m["nominal_capacity_kw"],
            ),
        )

    a = nearest([m for m in models if low <= m["nominal_capacity_kw"] <= high], (low + high) / 2)
    c = nearest([m for m in models if m["nominal_capacity_kw"] > high], high * 2)
    b = nearest(
        [m for m in models if high < m["nominal_capacity_kw"] < c["nominal_capacity_kw"]],
        high * 1.5,
    )
    quotes = []
    for letter, model, flow, loss, buffer, grant in (
        ("A", a, 45, load, False, True),
        ("B", b, 50, load, False, True),
        ("C", c, 55, round(max(load * 1.8, high * 1.25), 1), True, False),
    ):
        kw = model["nominal_capacity_kw"]
        items = [
            ("Air-source heat pump supply", 4000 + int(kw * 300)),
            ("200 L unvented hot-water cylinder", 1800),
            ("Installation, electrical work and commissioning", 3200),
            ("Radiator upgrades and system flush", 1200),
        ]
        if buffer:
            items.append(("50 L buffer tank supply and installation", 650))
        if grant:
            items.append(("Boiler Upgrade Scheme grant deducted", -7500))
        quotes.append(Quote(letter, model, flow, loss, buffer, grant, tuple(items)))
    return quotes


def money(amount: int) -> str:
    return f"{'-' if amount < 0 else ''}GBP {abs(amount):,}.00"


def write_quote(quote: Quote, destination: Path) -> None:
    pdf = Canvas(str(destination), pagesize=A4, invariant=1)
    pdf.setTitle(f"Sample quote {quote.letter} - fictional installer")
    pdf.setAuthor("Go All-Electric demo")
    width, height = A4

    def text(y: float, value: str, size: int = 11, bold: bool = False) -> None:
        pdf.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        pdf.setFillColor(colors.HexColor("#173740"))
        pdf.drawString(48, y, value)

    def frame(page: int, heading: str) -> None:
        pdf.setFillColor(colors.HexColor("#fff0cb"))
        pdf.rect(0, height - 56, width, 56, fill=1, stroke=0)
        text(height - 35, SAMPLE_MARK, 16, True)
        text(
            746,
            f"Imaginary Installer {quote.letter} - fictional demo business",
            15,
            True,
        )
        text(724, "000 Example Lane, Imaginary Town (fictional; no postcode)", 10)
        text(
            690,
            f"Quote {quote.letter} | 23 October 2026 | Prepared for Sam (fictional)",
        )
        text(651, heading, 21, True)
        pdf.setStrokeColor(colors.HexColor("#c6d5d4"))
        pdf.line(48, 630, width - 48, 630)
        text(
            53,
            "Synthetic demo document. No real customer, installer or site survey.",
            10,
        )
        text(35, f"{SAMPLE_MARK} | Quote {quote.letter} | Page {page} of 2", 10, True)

    frame(1, "Installation proposal")
    text(598, "Proposed air-source heat pump", 13, True)
    text(571, quote.model["make"], 13)
    text(548, quote.model["model"], 11)
    text(
        505,
        f"Nominal heat pump output: {quote.model['nominal_capacity_kw']:g} kW",
        14,
        True,
    )
    text(476, f"Design flow temperature: {quote.flow_c} C", 13)
    text(447, f"Stated design heat loss: {quote.heat_loss_kw:g} kW at -2 C outdoors", 12)
    text(405, "Included equipment", 13, True)
    text(376, "Hot-water cylinder: 200 L unvented")
    text(350, "Buffer tank: 50 L included" if quote.buffer else "Buffer tank: none")
    text(306, "Scope", 13, True)
    text(279, "Replace the existing gas boiler; connect the heating and hot water.")
    text(254, "Allow for radiator upgrades, electrical work and commissioning.")
    text(
        211,
        "All specifications and prices are invented for the hackathon demo.",
        11,
        True,
    )
    text(
        185,
        "Equipment names match the project's public manufacturer datasheet seed.",
        10,
    )
    text(150, "Price breakdown and grant treatment follow on page 2.")
    pdf.showPage()

    frame(2, "Price and grant")
    text(598, "Line item", 12, True)
    pdf.setFont("Helvetica-Bold", 12)
    pdf.drawRightString(width - 48, 598, "Amount")
    y = 561
    for description, amount in quote.items:
        text(y, description, 10)
        pdf.setFont("Helvetica", 11)
        pdf.drawRightString(width - 48, y, money(amount))
        y -= 33
    pdf.line(48, y + 12, width - 48, y + 12)
    text(y - 15, "TOTAL CUSTOMER PAYS", 12, True)
    pdf.setFont("Helvetica-Bold", 15)
    pdf.drawRightString(width - 48, y - 15, money(quote.total_gbp))
    text(260, "All amounts shown are final, including any applicable VAT.", 10)
    text(222, "Boiler Upgrade Scheme (BUS)", 13, True)
    if quote.grant_deducted:
        text(195, "GBP 7,500 grant already deducted in the line items above.")
        text(
            171,
            "Subject to eligibility; installer would apply on the customer's behalf.",
            10,
        )
    else:
        text(195, "GBP 7,500 grant NOT deducted from the total customer pays.", 11, True)
        text(171, "No grant discount has been applied to this quote.", 10)
    text(
        128,
        "Demo only: this document is not an offer or a scheme eligibility decision.",
        10,
    )
    pdf.showPage()
    pdf.save()


def generate(output: Path, low: float = 5, high: float = 7, load: float = 4.7) -> list[Quote]:
    quotes = build_quotes(low, high, load)
    output.mkdir(parents=True, exist_ok=True)
    for quote in quotes:
        write_quote(quote, output / quote.filename)
    return quotes


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--size-low-kw", type=float, default=5)
    parser.add_argument("--size-high-kw", type=float, default=7)
    parser.add_argument("--design-load-kw", type=float, default=4.7)
    parser.add_argument("--output", type=Path, default=ROOT / "quotes")
    args = parser.parse_args()
    try:
        results = generate(args.output, args.size_low_kw, args.size_high_kw, args.design_load_kw)
    except ValueError as exc:
        parser.error(str(exc))
    for result in results:
        print(
            f"{result.filename}: {result.model['nominal_capacity_kw']:g} kW, "
            f"{result.flow_c} C, customer pays {money(result.total_gbp)}"
        )
