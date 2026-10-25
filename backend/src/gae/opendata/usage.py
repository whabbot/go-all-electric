"""Combine dated gas evidence without double counting; measure against exact-period weather."""

import math
from dataclasses import dataclass, replace
from datetime import date, timedelta

from gae.heatpump.measured import MeasuredCaveat, MeasuredEstimate, estimate_measured
from gae.heatpump.ranges import Range
from gae.opendata.bill import DegreeDayProvider, _validate_bill, measured_from_bill
from gae.opendata.http import DataUnavailable
from gae.opendata.weather import validate_period

# Below this there is too little heating weather to separate heating from hot water.
MIN_MEASURABLE_HDD = 100
# Up to 50 percentage points extra uncertainty when little of a typical year's HDD is covered.
SHORT_COVERAGE_UNCERTAINTY = 0.50


@dataclass(frozen=True)
class UsagePeriod:
    start: date
    end: date
    kwh: float
    source: str
    entered: bool = False

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1


@dataclass(frozen=True)
class UsageResult:
    estimate: MeasuredEstimate | None = None
    annual_gas_kwh: float | None = None
    warning: str | None = None
    reason: str | None = None
    annualised: bool = False


def select_periods(periods: list[UsagePeriod]) -> tuple[list[UsagePeriod], list[str]]:
    chosen: list[UsagePeriod] = []
    notes: list[str] = []
    for period in sorted(periods, key=lambda p: (-p.days, not p.entered)):
        overlaps = [p for p in chosen if p.start <= period.end and period.start <= p.end]
        if overlaps:
            container = overlaps[0]
            contained = container.start <= period.start and period.end <= container.end
            notes.append(
                f"{period.source} ({period.start:%d %b %Y} to {period.end:%d %b %Y}) "
                + ("is inside" if contained else "overlaps")
                + f" {container.source}: total counted once; "
                + (
                    "used for usage shape and cross-checks."
                    if contained
                    else "shorter period set aside."
                )
            )
        else:
            chosen.append(period)
    return sorted(chosen, key=lambda p: p.start), notes


def full_year(chosen: list[UsagePeriod]) -> bool:
    if not chosen or sum(p.days for p in chosen) != (chosen[-1].end - chosen[0].start).days + 1:
        return False
    try:
        _validate_bill(chosen[0].start, chosen[-1].end, sum(p.kwh for p in chosen), None)
        return True
    except ValueError:
        return False


def summer_daily(periods: list[UsagePeriod]) -> Range | None:
    # A broad annual statement cannot identify summer consumption. Use periods wholly in
    # June-August; prefer entered data on duplicate dates and avoid overlapping summer data.
    summer = [
        p for p in periods if p.start.year == p.end.year and 6 <= p.start.month <= p.end.month <= 8
    ]
    chosen, _ = select_periods(summer)
    if not chosen:
        return None
    rates = [p.kwh / p.days for p in chosen]
    return Range(min(rates), sum(p.kwh for p in chosen) / sum(p.days for p in chosen), max(rates))


def measured_from_periods(
    *,
    periods: list[UsagePeriod],
    shape: list[UsagePeriod],
    postcode: str,
    weather_client: DegreeDayProvider,
    monthly: dict[int, float] | None = None,
) -> UsageResult:
    chosen, _ = select_periods(periods)
    if not chosen:
        return UsageResult(reason="Couldn't tell: add gas kWh and dates, including a winter month.")
    complete = full_year(chosen)
    total = sum(p.kwh for p in chosen)
    baseline = summer_daily([*periods, *shape])
    # Keep the established full-year result bit-for-bit, including the twelve-month baseline.
    if complete and (monthly is not None or baseline is None):
        result = measured_from_bill(
            start=chosen[0].start,
            end=chosen[-1].end,
            gas_kwh=total,
            postcode=postcode,
            weather_client=weather_client,
            monthly_gas_kwh=monthly,
        )
        return UsageResult(
            estimate=result.estimate,
            annual_gas_kwh=total if result.estimate else None,
            reason=result.reason,
        )
    try:
        weather = []
        for period in chosen:
            validate_period(period.start, period.end)
            w = weather_client.degree_days(postcode, period.start, period.end)
            if (
                w.postcode != postcode
                or w.start != period.start
                or w.end != period.end
                or w.missing_day_count
                or w.days_covered != period.days
                or w.days_expected != period.days
                or w.base_temperature_c != 15.5
                or w.heating_degree_days is None
                or not math.isfinite(w.heating_degree_days)
                or w.heating_degree_days < 0
            ):
                raise ValueError("weather has missing days or does not match the usage dates")
            weather.append(w)
        hdd = sum(w.heating_degree_days for w in weather)
        if hdd < MIN_MEASURABLE_HDD or all(
            p.start.year == p.end.year and 6 <= p.start.month <= p.end.month <= 8 for p in chosen
        ):
            return UsageResult(
                reason="Couldn't tell: too little heating to measure; add a winter month."
            )
        days = sum(p.days for p in chosen)
        baseline_covered = baseline.scale(days) if baseline else None
        if baseline_covered and baseline_covered.high >= total:
            baseline_covered = None  # contradictory shape cannot erase measured winter usage
        # Annual weather is for the latest completed 12 months at this same location.
        end = date.today() - timedelta(days=1)
        try:
            start = (end + timedelta(days=1)).replace(year=date.today().year - 1)
        except ValueError:
            start = date(date.today().year - 1, 2, 28)
        annual_weather = None if complete else weather_client.degree_days(postcode, start, end)
        if annual_weather is not None and (
            annual_weather.postcode != postcode
            or annual_weather.start != start
            or annual_weather.end != end
            or annual_weather.missing_day_count
            or annual_weather.days_covered != (end - start).days + 1
            or annual_weather.days_expected != (end - start).days + 1
            or annual_weather.base_temperature_c != 15.5
            or annual_weather.heating_degree_days is None
            or not math.isfinite(annual_weather.heating_degree_days)
            or annual_weather.heating_degree_days <= 0
        ):
            raise ValueError("a complete recent year of weather is unavailable for annual costs")
        year_hdd = hdd if complete else annual_weather.heating_degree_days
        extra = 0 if complete else SHORT_COVERAGE_UNCERTAINTY * (1 - min(1, hdd / year_hdd))
        estimate = estimate_measured(
            annual_gas_kwh=total,
            heating_degree_days=hdd,
            baseline_gas_kwh=baseline_covered,
            extra_uncertainty=extra,
            design_outdoor_temp_c=weather[0].design_outdoor_temp_c,
        )
        annual = (
            total
            if complete
            else (
                estimate.baseline_gas_kwh.central / days * 365
                + estimate.heating_gas_kwh.central / hdd * year_hdd
            )
        )
        if not complete:
            estimate = replace(
                estimate,
                caveats=(*estimate.caveats, MeasuredCaveat.PARTIAL_COVERAGE),
                heating_gas_kwh=estimate.heating_gas_kwh.scale(year_hdd / hdd),
                baseline_gas_kwh=estimate.baseline_gas_kwh.scale(365 / days),
            )
        label = ", ".join(f"{p.start:%d %b %Y} to {p.end:%d %b %Y}" for p in chosen)
        warning = (
            None
            if complete
            else (
                f"Based on {days} days of usage: {label}. "
                "12 months in a row gives the best estimate. "
                "The range is wider; annual Costs are estimated."
            )
        )
        return UsageResult(estimate, annual, warning, annualised=not complete)
    except (ValueError, TypeError, DataUnavailable) as exc:
        return UsageResult(reason="Couldn't tell: " + str(exc))
