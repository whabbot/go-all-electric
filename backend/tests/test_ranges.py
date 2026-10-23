import pytest

from gae.heatpump.ranges import Range


def test_range_validates_order() -> None:
    with pytest.raises(ValueError):
        Range(2, 1, 3)


def test_around_and_scale() -> None:
    r = Range.around(100, 0.2)
    assert (r.low, r.central, r.high) == pytest.approx((80, 100, 120))
    assert r.scale(0.5) == Range(40, 50, 60)
    assert Range.around(100, 0.1, 0.3).high == pytest.approx(130)
