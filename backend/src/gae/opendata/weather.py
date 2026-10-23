"""Postcode centroid weather, inclusive civil dates, UK 15.5C heating degree days."""

import math
import re
from dataclasses import dataclass
from datetime import date

import httpx

from gae.heatpump.constants import DEGREE_DAY_BASE_TEMP_C, LONDON_DESIGN_OUTDOOR_TEMP_C
from gae.opendata.http import DataUnavailable, get_json


def normalise_postcode(postcode: str) -> str:
    compact = re.sub(r"\s+", "", postcode.upper())
    if not re.fullmatch(r"(?:[A-Z]{1,2}[0-9][A-Z0-9]?|GIR)[0-9][A-Z]{2}", compact):
        raise ValueError("Enter a full UK postcode.")
    return compact[:-3] + " " + compact[-3:]


def validate_period(start: date, end: date) -> None:
    if start > end:
        raise ValueError("start must be on or before end (both dates are inclusive).")
    if start < date(1940, 1, 1) or end >= date.today():
        raise ValueError("Historical weather dates must be from 1940 through yesterday.")
    if (end - start).days > 731:
        raise ValueError("Request at most two years of daily weather.")


@dataclass(frozen=True)
class DegreeDays:
    postcode: str
    start: date
    end: date
    heating_degree_days: float | None
    observed_degree_days: float
    days_expected: int
    days_covered: int
    missing_day_count: int
    base_temperature_c: float = DEGREE_DAY_BASE_TEMP_C
    base_reason: str = "15.5C UK convention allows for incidental internal and solar gains."
    confidence: str = "medium"
    source: str = "Open-Meteo historical reanalysis at postcodes.io postcode centroid"
    design_outdoor_temp_c: float = LONDON_DESIGN_OUTDOOR_TEMP_C
    design_temperature_confidence: str = "low"
    design_temperature_note: str = "Named London -2C default; not a local design temperature."


def degree_days_from_daily(postcode: str, start: date, end: date, daily: dict) -> DegreeDays:
    """Pure aggregation; missing, duplicate, non-finite or nonnumeric days are not imputed."""
    validate_period(start, end)
    times = daily.get("time", [])
    temperatures = daily.get("temperature_2m_mean", [])
    if not isinstance(times, list) or not isinstance(temperatures, list):
        raise DataUnavailable("Couldn't read daily weather observations.")
    values: dict[date, float] = {}
    invalid: set[date] = set()
    for stamp, temperature in zip(times, temperatures, strict=False):
        try:
            day = date.fromisoformat(stamp)
        except TypeError, ValueError:
            continue
        if not start <= day <= end:
            continue
        if day in values or day in invalid:
            invalid.add(day)
            values.pop(day, None)
            continue
        if (
            isinstance(temperature, bool)
            or not isinstance(temperature, (int, float))
            or not math.isfinite(temperature)
            or not -90 <= temperature <= 60
        ):
            invalid.add(day)
            continue
        values[day] = max(0, DEGREE_DAY_BASE_TEMP_C - temperature)
    count = (end - start).days + 1
    observed = sum(values.values())
    missing = count - len(values)
    return DegreeDays(
        postcode=normalise_postcode(postcode),
        start=start,
        end=end,
        heating_degree_days=observed if missing == 0 else None,
        observed_degree_days=observed,
        days_expected=count,
        days_covered=len(values),
        missing_day_count=missing,
        confidence="low" if missing else "medium",
    )


class WeatherClient:
    def __init__(self, client: httpx.Client):
        self.client = client

    def degree_days(self, postcode: str, start: date, end: date) -> DegreeDays:
        validate_period(start, end)
        postcode = normalise_postcode(postcode)
        geo = get_json(self.client, "https://api.postcodes.io/postcodes/" + postcode)
        result = geo.get("result")
        if not isinstance(result, dict):
            raise DataUnavailable("Couldn't locate that postcode centroid.", 404)
        lat, lon = result.get("latitude"), result.get("longitude")
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in (lat, lon)):
            raise DataUnavailable("Couldn't locate that postcode centroid.")
        if (
            not math.isfinite(lat)
            or not math.isfinite(lon)
            or not (-90 <= lat <= 90 and -180 <= lon <= 180)
        ):
            raise DataUnavailable("Couldn't locate that postcode centroid.")
        # Only centroid coordinates are sent, kept in local variables, never persisted/returned.
        weather = get_json(
            self.client,
            "https://archive-api.open-meteo.com/v1/archive",
            params={
                "latitude": lat,
                "longitude": lon,
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "daily": "temperature_2m_mean",
                "timezone": "Europe/London",
                "temperature_unit": "celsius",
            },
        )
        daily = weather.get("daily")
        if not isinstance(daily, dict):
            raise DataUnavailable("Couldn't read daily weather observations.")
        return degree_days_from_daily(postcode, start, end, daily)
