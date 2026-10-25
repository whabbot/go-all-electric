from datetime import date, timedelta

import pytest

from gae.opendata.bill import measured_from_bill
from gae.opendata.usage import UsagePeriod, measured_from_periods, select_periods
from gae.opendata.weather import degree_days_from_daily


class SeasonalWeather:
    def __init__(self):
        self.calls = []

    def degree_days(self, postcode, start, end):
        self.calls.append((postcode, start, end))
        dates = [start + timedelta(days=i) for i in range((end - start).days + 1)]
        return degree_days_from_daily(
            postcode,
            start,
            end,
            {
                "time": [d.isoformat() for d in dates],
                "temperature_2m_mean": [18 if 6 <= d.month <= 8 else 5 for d in dates],
            },
        )


def p(start, end, kwh, entered=False):
    return UsagePeriod(
        date.fromisoformat(start),
        date.fromisoformat(end),
        kwh,
        "Entered period" if entered else "Bill photo",
        entered,
    )


def test_complete_year_retains_identical_result():
    weather = SeasonalWeather()
    period = p("2025-01-01", "2025-12-31", 12000)
    before = measured_from_bill(
        start=period.start,
        end=period.end,
        gas_kwh=12000,
        postcode="ZZ1 1ZZ",
        weather_client=weather,
    )
    after = measured_from_periods(
        periods=[period], shape=[], postcode="ZZ1 1ZZ", weather_client=weather
    )
    assert after.estimate == before.estimate
    assert after.annual_gas_kwh == 12000
    assert after.warning is None and not after.annualised


def test_disjoint_winter_periods_use_only_exact_weather_and_widen_range():
    weather = SeasonalWeather()
    periods = [p("2025-01-01", "2025-01-31", 2000), p("2025-11-01", "2025-11-30", 1800)]
    result = measured_from_periods(
        periods=periods, shape=[], postcode="ZZ1 1ZZ", weather_client=weather
    )
    assert result.estimate and result.annualised
    assert "61 days" in result.warning
    assert "01 Jan 2025" in result.warning and "01 Nov 2025" in result.warning
    assert [c[1:] for c in weather.calls[:2]] == [(p.start, p.end) for p in periods]
    assert len(weather.calls) == 3  # final call is annual costs weather, no gaps fetched
    assert 365 <= (weather.calls[-1][2] - weather.calls[-1][1]).days + 1 <= 366
    assert result.annual_gas_kwh > sum(p.kwh for p in periods)
    assert result.estimate.design_load_kw.high / result.estimate.design_load_kw.central > 1.4
    assert result.estimate.heating_gas_kwh.central < result.annual_gas_kwh


def test_contained_summer_readings_shape_year_without_double_counting():
    periods = [
        p("2025-01-01", "2025-12-31", 12000, True),
        p("2025-06-01", "2025-06-30", 300),
        p("2025-07-01", "2025-07-31", 310),
    ]
    chosen, notes = select_periods(periods)
    assert chosen == periods[:1] and len(notes) == 2
    result = measured_from_periods(
        periods=periods, shape=[], postcode="ZZ1 1ZZ", weather_client=SeasonalWeather()
    )
    assert result.annual_gas_kwh == 12000
    assert result.estimate.baseline_gas_kwh.central == pytest.approx(3650)
    assert "baseline_estimated" not in result.estimate.caveats
    assert not result.annualised


def test_entered_duplicate_wins_and_partial_overlap_keeps_longer():
    photo = p("2025-01-01", "2025-12-31", 10000)
    entered = p("2025-01-01", "2025-12-31", 12000, True)
    overlap = p("2025-12-01", "2026-01-31", 3000)
    chosen, notes = select_periods([photo, entered, overlap])
    assert chosen == [entered]
    assert any("shorter period set aside" in note for note in notes)


def test_summer_and_insufficient_degree_days_request_winter():
    for period in [p("2025-06-01", "2025-06-30", 200), p("2025-01-01", "2025-01-02", 50)]:
        result = measured_from_periods(
            periods=[period], shape=[], postcode="ZZ1 1ZZ", weather_client=SeasonalWeather()
        )
        assert result.estimate is None and "add a winter month" in result.reason
