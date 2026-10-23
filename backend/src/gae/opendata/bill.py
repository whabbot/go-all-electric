"""Measured bill adapter with injected weather I/O and a separate pure calculation."""

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Protocol

from gae.heatpump.constants import DEGREE_DAY_BASE_TEMP_C
from gae.heatpump.measured import MeasuredEstimate, estimate_measured
from gae.opendata.http import DataUnavailable
from gae.opendata.weather import DegreeDays, normalise_postcode, validate_period


class DegreeDayProvider(Protocol):
    def degree_days(self, postcode: str, start: date, end: date) -> DegreeDays: ...


@dataclass(frozen=True)
class BillResult:
    status: str
    reason: str | None = None
    weather: DegreeDays | None = None
    estimate: MeasuredEstimate | None = None


def _validate_bill(start, end, gas_kwh, monthly_gas_kwh):
    validate_period(start, end)
    # Inclusive bill dates must span an exact calendar year, including leap-day windows.
    after_end = end + timedelta(days=1)
    try:
        anniversary = start.replace(year=start.year + 1)
    except ValueError:  # 29 February -> 28 February the next year
        anniversary = date(start.year + 1, 2, 28)
    if after_end != anniversary:
        raise ValueError("Supply a complete 12-month bill period with inclusive start/end dates.")
    if isinstance(gas_kwh, bool) or not math.isfinite(gas_kwh) or gas_kwh <= 0:
        raise ValueError(
            "Supply positive finite gas consumption in kWh, not pounds or meter units."
        )
    if monthly_gas_kwh:
        if start.day != 1:
            raise ValueError(
                "Monthly figures need whole calendar months; omit them for mid-month bills."
            )
        if set(monthly_gas_kwh) != set(range(1, 13)):
            raise ValueError("Monthly figures must cover all 12 months of this bill period.")
        if any(
            isinstance(v, bool) or not math.isfinite(v) or v < 0 for v in monthly_gas_kwh.values()
        ):
            raise ValueError("Monthly gas kWh must be finite and nonnegative.")
        if not math.isclose(sum(monthly_gas_kwh.values()), gas_kwh, rel_tol=0.01):
            raise ValueError("Monthly gas figures must total the bill kWh (within 1%).")


def measured_from_degree_days(
    *,
    start: date,
    end: date,
    gas_kwh: float,
    weather: DegreeDays,
    monthly_gas_kwh: Mapping[int, float] | None = None,
    boiler_efficiency: float | None = None,
) -> BillResult:
    """Pure calculation from supplied weather; no network or silent weather fallback."""
    try:
        _validate_bill(start, end, gas_kwh, monthly_gas_kwh)
        if weather.start != start or weather.end != end:
            raise ValueError("Weather must cover the exact bill dates.")
        expected = (end - start).days + 1
        if weather.base_temperature_c != DEGREE_DAY_BASE_TEMP_C:
            raise ValueError("Weather degree-day base must be 15.5C for this method.")
        if (
            weather.missing_day_count
            or weather.heating_degree_days is None
            or weather.days_expected != expected
            or weather.days_covered != expected
        ):
            return BillResult("couldnt_tell", "Couldn't tell: weather has missing days.", weather)
        if not math.isfinite(weather.heating_degree_days) or weather.heating_degree_days <= 0:
            raise ValueError("Weather must contain positive finite heating degree days.")
        estimate = estimate_measured(
            annual_gas_kwh=gas_kwh,
            heating_degree_days=weather.heating_degree_days,
            monthly_gas_kwh=monthly_gas_kwh,
            boiler_efficiency=boiler_efficiency,
            design_outdoor_temp_c=weather.design_outdoor_temp_c,
        )
        return BillResult("ok", weather=weather, estimate=estimate)
    except (ValueError, TypeError) as exc:
        return BillResult("couldnt_tell", "Couldn't tell: " + str(exc), weather)


def measured_from_bill(
    *,
    start: date,
    end: date,
    gas_kwh: float,
    postcode: str,
    weather_client: DegreeDayProvider,
    monthly_gas_kwh: Mapping[int, float] | None = None,
    boiler_efficiency: float | None = None,
) -> BillResult:
    """Fetch exact-period weather through a small Protocol; calculation itself is pure above.

    Network fetching cannot itself be pure. Inject WeatherClient in production and a fake in tests.
    Optional monthly figures are month-of-year kWh for the same complete calendar months.
    """
    try:
        _validate_bill(start, end, gas_kwh, monthly_gas_kwh)
        postcode = normalise_postcode(postcode)
        weather = weather_client.degree_days(postcode, start, end)
        if weather.postcode != postcode:
            raise ValueError("Weather postcode must match the bill postcode.")
    except (DataUnavailable, ValueError, TypeError) as exc:
        return BillResult("couldnt_tell", "Couldn't tell: " + str(exc))
    return measured_from_degree_days(
        start=start,
        end=end,
        gas_kwh=gas_kwh,
        weather=weather,
        monthly_gas_kwh=monthly_gas_kwh,
        boiler_efficiency=boiler_efficiency,
    )
