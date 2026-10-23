"""Postcode-district centroid and PVGIS yield — outward code only, never a full postcode."""

from typing import Any, Protocol

import httpx

from gae.opendata.http import DataUnavailable, get_json
from gae.plan import constants as pc

PVGIS_URL = "https://re.jrc.ec.europa.eu/api/v5_2/PVcalc"
OUTCODE_URL = "https://api.postcodes.io/outcodes/"


class SolarYieldProvider(Protocol):
    def annual_kwh(self, outcode: str) -> float | None: ...


def _parse_outcode(payload: dict[str, Any]) -> tuple[float, float]:
    result = payload.get("result")
    if not isinstance(result, dict):
        raise DataUnavailable("Couldn't locate that outward code.")
    lat = result.get("latitude")
    lon = result.get("longitude")
    if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
        raise DataUnavailable("Couldn't locate that outward code.")
    return float(lat), float(lon)


def outcode_centroid(client: httpx.Client, outcode: str) -> tuple[float, float]:
    """Latitude and longitude for a UK outward code (e.g. N10), not a full postcode."""
    compact = outcode.strip().upper().replace(" ", "")
    if not compact or len(compact) > 4:
        raise ValueError("Outward code must look like N10 or SW1A.")
    payload = get_json(client, OUTCODE_URL + compact)
    return _parse_outcode(payload)


def pvgis_annual_kwh(
    client: httpx.Client,
    lat: float,
    lon: float,
    *,
    peak_kw: float = pc.DEFAULT_ARRAY_KWP,
    slope_deg: float = pc.DEFAULT_ARRAY_SLOPE_DEG,
    azimuth_deg: float = pc.DEFAULT_ARRAY_AZIMUTH_DEG,
) -> float:
    params = {
        "lat": lat,
        "lon": lon,
        "peakpower": peak_kw,
        "loss": pc.PVGIS_SYSTEM_LOSS_PCT,
        "angle": slope_deg,
        "aspect": azimuth_deg,
        "outputformat": "json",
    }
    payload = get_json(client, PVGIS_URL, params=params)
    outputs = payload.get("outputs")
    if not isinstance(outputs, dict):
        raise DataUnavailable("Couldn't fetch solar yield.")
    totals = outputs.get("totals")
    if not isinstance(totals, dict):
        raise DataUnavailable("Couldn't fetch solar yield.")
    fixed = totals.get("fixed")
    if not isinstance(fixed, dict):
        raise DataUnavailable("Couldn't fetch solar yield.")
    annual = fixed.get("E_y")
    if not isinstance(annual, (int, float)) or annual <= 0:
        raise DataUnavailable("Couldn't fetch solar yield.")
    return float(annual)


class LiveSolarYield:
    def __init__(self, client: httpx.Client):
        self._client = client

    def annual_kwh(self, outcode: str) -> float | None:
        try:
            lat, lon = outcode_centroid(self._client, outcode)
            return pvgis_annual_kwh(self._client, lat, lon)
        except DataUnavailable:
            return None


def payback_years(annual_kwh: float, *, electricity_pence_per_kwh: float) -> float:
    cost = pc.DEFAULT_ARRAY_KWP * pc.DEFAULT_ARRAY_COST_GBP_PER_KWP
    annual_value = annual_kwh * electricity_pence_per_kwh / 100.0
    if annual_value <= 0:
        return float("inf")
    return cost / annual_value
