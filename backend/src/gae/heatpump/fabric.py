"""Estimate A: simplified installer-style fabric heat loss from EPC-like inputs.

Sums U x A for walls, windows, doors, roof and floor, adds a thermal bridging allowance and
ventilation loss (0.33 x ACH x volume), all using the defaults an installer calc would assume.
Each default used is recorded as a named assumption so the cross-check can point at it.
"""

import math
from dataclasses import dataclass
from enum import StrEnum

from gae.heatpump import constants as c
from gae.heatpump.constants import Glazing, WallType
from gae.heatpump.ranges import Range


class PropertyType(StrEnum):
    DETACHED = "detached"
    SEMI_DETACHED = "semi_detached"
    END_TERRACE = "end_terrace"
    MID_TERRACE = "mid_terrace"
    BUNGALOW = "bungalow"


# Share of the footprint perimeter that is exposed external wall (the rest is party wall).
EXPOSED_WALL_FRACTION: dict[PropertyType, float] = {
    PropertyType.DETACHED: 1.0,
    PropertyType.SEMI_DETACHED: 0.75,
    PropertyType.END_TERRACE: 0.75,
    PropertyType.MID_TERRACE: 0.5,
    PropertyType.BUNGALOW: 1.0,
}


class Element(StrEnum):
    WALLS = "walls"
    WINDOWS = "windows"
    DOORS = "doors"
    ROOF = "roof"
    FLOOR = "floor"
    THERMAL_BRIDGING = "thermal_bridging"
    VENTILATION = "ventilation"


class Default(StrEnum):
    """Named defaults the fabric calc can rely on; the cross-check refers to these."""

    INSTALLER_AIR_CHANGE_RATE = "installer_air_change_rate"
    DOUBLE_GLAZING_U_2_8 = "double_glazing_u_2_8"
    WALL_U_AS_BUILT = "wall_u_as_built"
    ROOF_U_FROM_LOFT_DEPTH = "roof_u_from_loft_depth"
    FLOOR_U = "floor_u"
    GEOMETRY_FROM_FLOOR_AREA = "geometry_from_floor_area"


@dataclass(frozen=True)
class Assumption:
    default: Default
    value: float
    unit: str
    note: str


@dataclass(frozen=True)
class FabricEstimate:
    # Heat loss per element in W/K, so callers can see where the total comes from.
    element_w_per_k: dict[Element, float]
    htc_w_per_k: Range
    design_load_kw: Range
    assumptions: tuple[Assumption, ...]
    # Inputs the cross-check needs to size its explanations.
    wall_type: WallType
    glazing: Glazing
    loft_insulation_mm: int
    net_wall_area_m2: float
    window_area_m2: float
    roof_area_m2: float
    volume_m3: float
    air_change_rate: float
    built_before_2000: bool


def estimate_fabric(
    *,
    floor_area_m2: float,
    property_type: PropertyType,
    year_built: int,
    wall_type: WallType,
    glazing: Glazing,
    loft_insulation_mm: int,
    storeys: int | None = None,
    floor_insulated: bool | None = None,
    indoor_temp_c: float = c.DESIGN_INDOOR_TEMP_C,
    design_outdoor_temp_c: float = c.LONDON_DESIGN_OUTDOOR_TEMP_C,
) -> FabricEstimate:
    """Installer-style whole-house heat loss.

    `year_built` can be the start of an EPC age band (e.g. 1930 for "1930-1949").
    `storeys` defaults to 1 for bungalows and 2 otherwise. `floor_insulated` defaults to
    whether the house was built from 2003, when Part L made floor insulation routine.
    """
    if floor_area_m2 <= 0:
        raise ValueError("floor_area_m2 must be positive")
    if loft_insulation_mm < 0:
        raise ValueError("loft_insulation_mm cannot be negative")
    if indoor_temp_c <= design_outdoor_temp_c:
        raise ValueError("indoor_temp_c must be above design_outdoor_temp_c")
    if storeys is None:
        storeys = 1 if property_type is PropertyType.BUNGALOW else 2
    if storeys < 1:
        raise ValueError("storeys must be at least 1")
    if floor_insulated is None:
        floor_insulated = year_built >= 2003

    assumptions: list[Assumption] = []

    # Geometry: square footprint, exposed perimeter by property type.
    footprint = floor_area_m2 / storeys
    exposed_perimeter = 4 * math.sqrt(footprint) * EXPOSED_WALL_FRACTION[property_type]
    gross_wall = exposed_perimeter * c.STOREY_HEIGHT_M * storeys
    window_area = floor_area_m2 * c.WINDOW_TO_FLOOR_RATIO
    door_area = c.DOOR_AREA_M2 * c.DOORS_PER_DWELLING
    net_wall = gross_wall - window_area - door_area
    if net_wall <= 0:
        raise ValueError("window and door area exceed the estimated wall area")
    volume = floor_area_m2 * c.ROOM_HEIGHT_M
    assumptions.append(
        Assumption(
            Default.GEOMETRY_FROM_FLOOR_AREA,
            c.WINDOW_TO_FLOOR_RATIO,
            "window/floor ratio",
            f"Square footprint, {c.STOREY_HEIGHT_M}m storeys, windows "
            f"{c.WINDOW_TO_FLOOR_RATIO:.0%} of floor area",
        )
    )

    wall_u = c.WALL_U_VALUES[wall_type]
    assumptions.append(
        Assumption(Default.WALL_U_AS_BUILT, wall_u, "W/m2K", f"As-built U-value for {wall_type}")
    )
    window_u = c.GLAZING_U_VALUES[glazing]
    if window_u == c.DEFAULT_DOUBLE_GLAZING_U:
        assumptions.append(
            Assumption(
                Default.DOUBLE_GLAZING_U_2_8,
                window_u,
                "W/m2K",
                "Double glazing of unknown date assumed U=2.8; units from 2003 must meet 2.2",
            )
        )
    roof_u = roof_u_value(loft_insulation_mm)
    assumptions.append(
        Assumption(
            Default.ROOF_U_FROM_LOFT_DEPTH,
            roof_u,
            "W/m2K",
            f"{loft_insulation_mm}mm loft insulation",
        )
    )
    floor_u = c.FLOOR_U_INSULATED if floor_insulated else c.FLOOR_U_UNINSULATED
    assumptions.append(
        Assumption(
            Default.FLOOR_U,
            floor_u,
            "W/m2K",
            "Insulated ground floor" if floor_insulated else "Uninsulated ground floor",
        )
    )

    built_before_2000 = year_built < 2000
    ach = (
        c.INSTALLER_DEFAULT_ACH_PRE_2000
        if built_before_2000
        else c.INSTALLER_DEFAULT_ACH_2000_ONWARDS
    )
    assumptions.append(
        Assumption(
            Default.INSTALLER_AIR_CHANGE_RATE,
            ach,
            "ACH",
            "CIBSE-style default air change rate for a "
            + ("pre-2000" if built_before_2000 else "post-2000")
            + " home",
        )
    )

    exposed_area = gross_wall + footprint * 2  # walls (incl. openings) + roof + floor
    elements = {
        Element.WALLS: net_wall * wall_u,
        Element.WINDOWS: window_area * window_u,
        Element.DOORS: door_area * c.DOOR_U,
        Element.ROOF: footprint * roof_u,
        Element.FLOOR: footprint * floor_u,
        Element.THERMAL_BRIDGING: exposed_area * c.THERMAL_BRIDGING_Y,
        Element.VENTILATION: c.AIR_HEAT_CAPACITY_WH_PER_M3K * ach * volume,
    }
    htc = Range.around(sum(elements.values()), c.FABRIC_METHOD_UNCERTAINTY)
    delta_t = indoor_temp_c - design_outdoor_temp_c

    return FabricEstimate(
        element_w_per_k=elements,
        htc_w_per_k=htc,
        design_load_kw=htc.scale(delta_t / 1000),
        assumptions=tuple(assumptions),
        wall_type=wall_type,
        glazing=glazing,
        loft_insulation_mm=loft_insulation_mm,
        net_wall_area_m2=net_wall,
        window_area_m2=window_area,
        roof_area_m2=footprint,
        volume_m3=volume,
        air_change_rate=ach,
        built_before_2000=built_before_2000,
    )


def roof_u_value(loft_insulation_mm: int) -> float:
    """Roof U-value for a loft insulation depth, taking the table entry at or below it."""
    u = c.ROOF_U_BY_LOFT_INSULATION_MM[0][1]
    for depth, value in c.ROOF_U_BY_LOFT_INSULATION_MM:
        if loft_insulation_mm >= depth:
            u = value
    return u
