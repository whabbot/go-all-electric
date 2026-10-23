"""Explicit, conservative EPC-to-fabric mapping. See MAPPING.md for the decision table."""

import math
import re
from dataclasses import dataclass
from typing import Any

from gae.heatpump.constants import Glazing, HeatingFuel, WallType
from gae.heatpump.fabric import FabricEstimate, PropertyType, estimate_fabric


@dataclass(frozen=True)
class FieldConfidence:
    confidence: str
    source: str
    note: str
    default: str | None = None


@dataclass(frozen=True)
class FabricMapping:
    fabric_inputs: dict[str, Any]
    confidence: dict[str, FieldConfidence]
    main_heating_fuel: HeatingFuel
    estimate: FabricEstimate | None
    reason: str | None


def descriptions(record: dict, key: str) -> list[str]:
    items = record.get(key, [])
    if isinstance(items, dict):
        items = [items]
    if not isinstance(items, list):
        return []
    result = []
    for item in items:
        value = item.get("description") if isinstance(item, dict) else item
        if isinstance(value, dict):
            # New RdSAP 21 descriptions wrap a value and language code. English only.
            value = value.get("value") if str(value.get("language", "1")) == "1" else None
        if isinstance(value, str) and value.strip():
            result.append(value.strip().lower())
    return result


def map_epc(record: dict, *, age_label: str | None = None) -> FabricMapping:
    inputs: dict[str, Any] = {}
    confidence: dict[str, FieldConfidence] = {}

    def put(field, value, source, note, *, default=None, level="medium"):
        inputs[field] = value
        confidence[field] = FieldConfidence("low" if default else level, source, note, default)

    area = record.get("total_floor_area")
    if isinstance(area, dict):
        area = area.get("value")
    try:
        area = float(area) if not isinstance(area, bool) else 0
        if not math.isfinite(area) or area <= 0:
            area = None
    except (TypeError, ValueError):
        area = None
    put(
        "floor_area_m2",
        area,
        "total_floor_area",
        "Reported EPC area; confirm at survey.",
        default="floor_area_unavailable" if area is None else None,
    )

    dwelling = str(record.get("dwelling_type", "")).lower()
    # Numeric property_type and built_form codes are schema-specific; never guess their meaning.
    built_form = record.get("built_form", "")
    property_label = record.get("property_type", "")
    if not dwelling and isinstance(built_form, str) and not built_form.isdigit():
        dwelling = f"{built_form} {property_label}".lower()
    prop = None
    unsupported = any(word in dwelling for word in ("flat", "maisonette", "park home"))
    if not unsupported:
        for label, value in (
            ("bungalow", PropertyType.BUNGALOW),
            ("semi-detached", PropertyType.SEMI_DETACHED),
            ("end-terrace", PropertyType.END_TERRACE),
            ("mid-terrace", PropertyType.MID_TERRACE),
            ("detached", PropertyType.DETACHED),
        ):
            if label in dwelling:
                prop = value
                break
    put(
        "property_type",
        prop or PropertyType.SEMI_DETACHED,
        "dwelling_type / built_form",
        "Flats/maisonettes are outside the house geometry model."
        if unsupported
        else "Dwelling form determines exposed perimeter; unknown form uses a semi assumption.",
        default="semi_detached_geometry" if prop is None else None,
    )
    put(
        "storeys",
        1 if prop == PropertyType.BUNGALOW else 2,
        "geometry assumption",
        "One storey for bungalows, two for houses; confirm at survey.",
        default="assumed_storeys",
    )

    label = age_label or record.get("construction_age_band", "")
    years = re.findall(r"\b(?:18|19|20)\d{2}\b", str(label))
    year = int(years[0]) if years else 1930
    put(
        "year_built",
        year,
        "construction_age_band",
        "Start of age band, not an exact build year.",
        default=None if years else "unknown_age_1930",
    )

    def one(key):
        values = descriptions(record, key)
        return values[0] if len(set(values)) == 1 else ""

    wall = one("walls")
    wall_type = None
    uninsulated = "no insulation" in wall or "uninsulated" in wall
    if "cavity" in wall:
        if "filled cavity" in wall or ("insulated" in wall and not uninsulated):
            wall_type = WallType.CAVITY_FILLED
        elif uninsulated:
            wall_type = WallType.CAVITY_UNFILLED
    elif "solid brick" in wall:
        wall_type = (
            WallType.SOLID_INSULATED
            if "insulat" in wall and not uninsulated
            else (WallType.SOLID_BRICK if uninsulated else None)
        )
    elif "timber frame" in wall:
        wall_type = WallType.TIMBER_FRAME
    put(
        "wall_type",
        wall_type or WallType.CAVITY_UNFILLED,
        "walls[].description",
        "Multiple differing walls or unknown insulation cannot be area weighted; confirm photos.",
        default="unknown_wall_cavity_unfilled" if wall_type is None else None,
    )

    glazing = one("window")
    glazed = {
        "fully double glazed": Glazing.DOUBLE_UNKNOWN_DATE,
        "fully triple glazed": Glazing.TRIPLE,
        "single glazed": Glazing.SINGLE,
        "fully single glazed": Glazing.SINGLE,
    }.get(glazing)
    put(
        "glazing",
        glazed or Glazing.DOUBLE_UNKNOWN_DATE,
        "window.description",
        "Double-glazing date is unknown; mixed glazing is not represented by this model.",
        default="unknown_glazing_double_u_2_8"
        if glazed in (None, Glazing.DOUBLE_UNKNOWN_DATE)
        else None,
    )

    roof = one("roofs")
    depth = re.search(r"(\d+)\s*mm\s+loft insulation", roof) if "pitched" in roof else None
    loft = int(depth[1]) if depth else 0
    known_roof = bool(depth) or ("pitched" in roof and "no insulation" in roof)
    put(
        "loft_insulation_mm",
        loft,
        "roofs[].description",
        "Only a uniform pitched loft maps to loft depth; flat/mixed/unknown roofs default to 0mm.",
        default=None if known_roof else "unknown_roof_zero_loft_depth",
    )

    floor = one("floors")
    insulated = None
    if "no insulation" in floor or "uninsulated" in floor:
        insulated = False
    elif "insulated" in floor:
        insulated = True
    put(
        "floor_insulated",
        insulated if insulated is not None else False,
        "floors[].description",
        "Mixed, other-premises-below or unknown floors default to uninsulated ground floor.",
        default="unknown_floor_uninsulated" if insulated is None else None,
    )
    put(
        "design_outdoor_temp_c",
        -2.0,
        "London default",
        "Not a local weather-derived design temperature.",
        default="london_design_minus_2c",
    )

    heating = one("main_heating")
    fuel = HeatingFuel.OTHER
    for phrase, value in (
        ("mains gas", HeatingFuel.GAS),
        ("lpg", HeatingFuel.LPG),
        ("oil", HeatingFuel.OIL),
        ("electric", HeatingFuel.ELECTRIC),
    ):
        # 'oil' must be a word, not the substring of 'boiler'.
        if re.search(r"\b" + phrase + r"\b", heating):
            fuel = value
            break
    confidence["main_heating_fuel"] = FieldConfidence(
        "low" if fuel == HeatingFuel.OTHER else "medium",
        "main_heating[].description",
        "Reported primary fuel; mixed or unmapped systems remain other.",
        "unknown_heating_fuel" if fuel == HeatingFuel.OTHER else None,
    )
    reason = None
    estimate = None
    if area is None:
        reason = "Couldn't tell: floor area is missing. Supply a measured floor area."
    elif unsupported:
        reason = "Couldn't tell: flats, maisonettes and park homes need a different geometry model."
    else:
        try:
            estimate = estimate_fabric(**inputs)
        except ValueError:
            reason = "Couldn't tell: EPC geometry is inconsistent. Confirm dimensions at survey."
    return FabricMapping(inputs, confidence, fuel, estimate, reason)
