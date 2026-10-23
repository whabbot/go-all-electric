"""Explicit, conservative EPC-to-fabric mapping. See MAPPING.md for the decision table."""

import math
import re
from dataclasses import dataclass, replace
from typing import Any

from gae.heatpump.constants import Glazing, HeatingFuel, WallType
from gae.heatpump.fabric import FabricEstimate, PropertyType, estimate_fabric


@dataclass(frozen=True)
class FieldConfidence:
    confidence: str
    source: str
    note: str
    default: str | None = None
    value_range: tuple[int | None, int | None] | None = None


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


def positive_area(value: Any) -> float | None:
    if isinstance(value, dict):
        value = value.get("value")
    try:
        area = float(value) if not isinstance(value, bool) else 0
        return area if math.isfinite(area) and area > 0 else None
    except (TypeError, ValueError):
        return None


def floor_area(record: dict) -> tuple[float | None, str]:
    """Prefer a whole-dwelling total; otherwise sum distinct part/floor entries only.

    Repeated part/floor identities must agree. Never sum a partial set of dimensions
    or multiply a floor area by the assumed storey count.
    """
    if "total_floor_area" in record:
        return positive_area(record["total_floor_area"]), "total_floor_area"
    source = "sap_building_parts[].sap_floor_dimensions[].total_floor_area"
    parts = record.get("sap_building_parts")
    if not isinstance(parts, list) or not parts:
        return None, source
    areas = {}
    for part_index, part in enumerate(parts):
        if not isinstance(part, dict):
            return None, source
        dimensions = part.get("sap_floor_dimensions")
        if not isinstance(dimensions, list) or not dimensions:
            return None, source
        part_id = (
            ("number", str(part["building_part_number"]))
            if part.get("building_part_number") is not None
            else ("index", part_index)
        )
        for floor_index, dimension in enumerate(dimensions):
            if not isinstance(dimension, dict):
                return None, source
            area = positive_area(dimension.get("total_floor_area"))
            if area is None:
                return None, source
            floor_id = (
                ("floor", str(dimension["floor"]))
                if dimension.get("floor") is not None
                else ("index", floor_index)
            )
            identity = (part_id, floor_id)
            if identity in areas and areas[identity] != area:
                return None, source
            areas[identity] = area
    total = sum(areas.values())
    return (total if math.isfinite(total) else None), source


def map_epc(
    record: dict,
    *,
    age_label: str | None = None,
    property_label: str | None = None,
    built_form_label: str | None = None,
) -> FabricMapping:
    inputs: dict[str, Any] = {}
    confidence: dict[str, FieldConfidence] = {}

    def put(field, value, source, note, *, default=None, level="medium"):
        inputs[field] = value
        confidence[field] = FieldConfidence("low" if default else level, source, note, default)

    area, area_source = floor_area(record)
    put(
        "floor_area_m2",
        area,
        area_source,
        "Reported EPC area; confirm at survey.",
        default="floor_area_unavailable" if area is None else None,
    )

    dwelling = str(record.get("dwelling_type", "")).lower()
    # Labels are resolved by the client using schema AND actual assessment type.
    built_form = built_form_label or record.get("built_form", "")
    property_value = property_label or record.get("property_type", "")
    unresolved_codes = any(
        isinstance(value, (int, float)) or (isinstance(value, str) and value.isdigit())
        for value in (built_form, property_value)
    )
    if not dwelling:
        dwelling = f"{built_form} {property_value}".lower()
    prop = None
    unsupported = any(word in dwelling for word in ("flat", "maisonette", "park home"))
    unsupported = unsupported or (unresolved_codes and not record.get("dwelling_type"))
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
    if (property_label or built_form_label) and prop is None:
        unsupported = True
    put(
        "property_type",
        prop or PropertyType.SEMI_DETACHED,
        "dwelling_type / built_form / property_type (schema and assessment labels)",
        "Unsupported or unresolved form cannot use the house geometry model."
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
    years = [int(y) for y in re.findall(r"\b(?:1[6-9]|20)\d{2}\b", str(label))]
    text = str(label).lower()
    age_range = None
    open_ended = False
    if years and any(word in text for word in ("before", "pre-", "prior to")):
        age_range = (None, years[0] - 1)
        year = years[0] - 1
        open_ended = True
    elif years and any(word in text for word in ("after", "onwards", "onward", " or later")):
        year = years[0] + (1 if "after" in text else 0)
        age_range = (year, None)
        open_ended = True
    else:
        year = years[0] if years else 1930
        if len(years) == 2:
            age_range = (years[0], years[1])
    put(
        "year_built",
        year,
        "construction_age_band",
        f"Reported band: {label}. Representative year for maths only; not an exact build year."
        if years
        else "Unknown build age; 1930 assumption.",
        default="open_ended_age_band" if open_ended else (None if years else "unknown_age_1930"),
    )
    confidence["year_built"] = replace(confidence["year_built"], value_range=age_range)

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

    glazing = one("windows" if "windows" in record else "window")
    glazed = {
        "fully double glazed": Glazing.DOUBLE_UNKNOWN_DATE,
        "fully triple glazed": Glazing.TRIPLE,
        "single glazed": Glazing.SINGLE,
        "fully single glazed": Glazing.SINGLE,
    }.get(glazing)
    put(
        "glazing",
        glazed or Glazing.DOUBLE_UNKNOWN_DATE,
        "windows[].description / window.description",
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
        reason = (
            "Couldn't tell: unsupported or unresolved dwelling geometry; "
            "confirm property type at survey."
        )
    else:
        try:
            estimate = estimate_fabric(**inputs)
        except ValueError:
            reason = "Couldn't tell: EPC geometry is inconsistent. Confirm dimensions at survey."
    return FabricMapping(inputs, confidence, fuel, estimate, reason)
