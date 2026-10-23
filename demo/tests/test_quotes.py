import re
import sys
from pathlib import Path

import pytest
from pypdf import PdfReader

DEMO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DEMO))
from generate_quotes import SAMPLE_MARK, build_quotes, generate  # noqa: E402


def assert_pdf_matches(quote, path):
    reader = PdfReader(path)
    assert len(reader.pages) == 2
    for page in reader.pages:
        assert SAMPLE_MARK in page.extract_text()
    pricing = reader.pages[1].extract_text()
    # Read the rendered amounts, including the final total, independently of the data model.
    amounts = re.findall(r"(-?)GBP ([\d,]+)\.00", pricing.split("All amounts shown")[0])
    values = [int(number.replace(",", "")) * (-1 if sign else 1) for sign, number in amounts]
    assert values[:-1] == [amount for _, amount in quote.items]
    assert sum(values[:-1]) == values[-1] == quote.total_gbp
    assert quote.model["model"] in reader.pages[0].extract_text()


def test_committed_default_pdfs():
    quotes = build_quotes()
    assert [q.model["nominal_capacity_kw"] for q in quotes] == [6, 9, 12]
    assert [q.total_gbp for q in quotes] == [4500, 5400, 14450]
    assert [q.flow_c for q in quotes] == [45, 50, 55]
    assert [q.grant_deducted for q in quotes] == [True, True, False]
    assert quotes[2].buffer and quotes[2].heat_loss_kw > 7
    for quote in quotes:
        assert_pdf_matches(quote, DEMO / "quotes" / quote.filename)


@pytest.mark.parametrize("low,high,load", [(5, 7, 4.7), (6, 8, 5.8), (5, 6, 4.2)])
def test_regenerate_for_house(tmp_path, low, high, load):
    quotes = generate(tmp_path, low, high, load)
    a, b, c = quotes
    assert low <= a.model["nominal_capacity_kw"] <= high
    assert high < b.model["nominal_capacity_kw"] < c.model["nominal_capacity_kw"]
    assert a.heat_loss_kw == b.heat_loss_kw == load
    assert c.heat_loss_kw > max(load, high)
    for quote in quotes:
        assert_pdf_matches(quote, tmp_path / quote.filename)


@pytest.mark.parametrize(
    "numbers",
    [
        (0, 7, 4.7),
        (7, 5, 4.7),
        (5, float("nan"), 4.7),
        (5, 7, float("inf")),
        (20, 30, 18),
    ],
)
def test_invalid_or_unsupported_range(numbers):
    with pytest.raises(ValueError):
        build_quotes(*numbers)


def test_generation_is_reproducible(tmp_path):
    for quote in generate(tmp_path):
        assert (tmp_path / quote.filename).read_bytes() == (
            DEMO / "quotes" / quote.filename
        ).read_bytes()
