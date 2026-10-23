"""Target spec: what a good installation should look like for this home.

Heat pump size range from the measured design load, a recommended maximum flow temperature,
which radiators need upsizing at that flow temperature, and the Boiler Upgrade Scheme grant.
"""

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum

from gae.heatpump import constants as c
from gae.heatpump.constants import HeatingFuel
from gae.heatpump.ranges import Confidence, Exact, Range


@dataclass(frozen=True)
class Room:
    name: str
    # Design heat loss of the room in watts (itself an estimate).
    heat_loss_w: float
    # Combined rated output of the room's radiators at Delta-T 50, from the manufacturer's
    # tables or estimated from size and type.
    radiator_output_dt50_w: float
    temp_c: float = c.DESIGN_INDOOR_TEMP_C


class RadiatorStatus(StrEnum):
    OK = "ok"
    # Within the room heat-loss margin: likely fine, worth checking at survey.
    MARGINAL = "marginal"
    UPSIZE = "upsize"


@dataclass(frozen=True)
class RadiatorCheck:
    room: str
    flow_temp_c: float
    output_w: float
    heat_loss_w: float
    status: RadiatorStatus
    # Delta-T 50 rating needed to meet the room's heat loss at this flow temperature.
    required_output_dt50_w: float
    # Lowest flow temperature at which the existing radiators meet the room's heat loss.
    min_flow_temp_c: float


@dataclass(frozen=True)
class Grant:
    amount_gbp: Exact
    fuel: HeatingFuel
    note: str


@dataclass(frozen=True)
class TargetSpec:
    size_kw: Range
    # Recommended maximum design flow temperature; radiators are checked against it.
    max_flow_temp_c: Exact
    # Flow temperature the existing radiators need in the worst room (None without room data).
    flow_temp_needed_by_current_radiators_c: Exact | None
    radiators: tuple[RadiatorCheck, ...]
    grant: Grant


def size_range_kw(design_load_kw: Range) -> Range:
    """Heat pump size range: at least the central design load, at most a margin over the high.

    The central value covers the high end of the measured load, rounded up to the next step.
    """
    low = _round_to(design_load_kw.central, c.SIZE_ROUNDING_KW, math.ceil)
    high = _round_to(
        design_load_kw.high * (1 + c.SIZE_MARGIN_OVER_HIGH), c.SIZE_ROUNDING_KW, math.ceil
    )
    central = _round_to(design_load_kw.high, c.SIZE_ROUNDING_KW, math.ceil)
    return Range(low, min(max(central, low), high), high)


def radiator_output_w(rated_dt50_w: float, flow_temp_c: float, room_temp_c: float) -> float:
    """Radiator output at a heat pump flow temperature, from its Delta-T 50 rating (n = 1.3)."""
    mean_water = flow_temp_c - c.HEAT_PUMP_FLOW_RETURN_DELTA_K / 2
    delta_t = mean_water - room_temp_c
    if delta_t <= 0:
        return 0.0
    return rated_dt50_w * (delta_t / c.RADIATOR_RATED_DELTA_T_K) ** c.RADIATOR_EXPONENT


def min_flow_temp_c(rated_dt50_w: float, heat_loss_w: float, room_temp_c: float) -> float:
    """Lowest flow temperature at which radiators rated `rated_dt50_w` meet `heat_loss_w`."""
    if rated_dt50_w <= 0:
        return math.inf
    delta_t = c.RADIATOR_RATED_DELTA_T_K * (heat_loss_w / rated_dt50_w) ** (1 / c.RADIATOR_EXPONENT)
    return room_temp_c + delta_t + c.HEAT_PUMP_FLOW_RETURN_DELTA_K / 2


def check_radiator(room: Room, flow_temp_c: float) -> RadiatorCheck:
    if room.heat_loss_w < 0 or room.radiator_output_dt50_w < 0:
        raise ValueError(f"{room.name}: heat loss and radiator output cannot be negative")
    output = radiator_output_w(room.radiator_output_dt50_w, flow_temp_c, room.temp_c)
    factor = radiator_output_w(1.0, flow_temp_c, room.temp_c)
    required = math.inf if factor == 0 else room.heat_loss_w / factor
    if output >= room.heat_loss_w * (1 + c.RADIATOR_MARGIN):
        status = RadiatorStatus.OK
    elif output >= room.heat_loss_w * (1 - c.RADIATOR_MARGIN):
        status = RadiatorStatus.MARGINAL
    else:
        status = RadiatorStatus.UPSIZE
    return RadiatorCheck(
        room=room.name,
        flow_temp_c=flow_temp_c,
        output_w=output,
        heat_loss_w=room.heat_loss_w,
        status=status,
        required_output_dt50_w=required,
        min_flow_temp_c=min_flow_temp_c(room.radiator_output_dt50_w, room.heat_loss_w, room.temp_c),
    )


def bus_grant(fuel: HeatingFuel) -> Grant:
    amount = c.BUS_GRANT_GBP.get(fuel)
    if amount is None:
        return Grant(
            Exact(0, Confidence.LOW),
            fuel,
            f"No fixed grant for replacing {fuel} heating in our data; check eligibility "
            f"with an MCS installer. ({c.BUS_GRANT_SOURCE})",
        )
    return Grant(
        Exact(amount, Confidence.HIGH),
        fuel,
        f"Paid to the installer and deducted from the quote; subject to scheme eligibility. "
        f"({c.BUS_GRANT_SOURCE})",
    )


def target_spec(
    *,
    measured_design_load_kw: Range,
    current_fuel: HeatingFuel,
    rooms: Sequence[Room] = (),
    target_flow_temp_c: float = c.TARGET_FLOW_TEMP_C,
) -> TargetSpec:
    """Build the target spec from the measured design load and (optionally) room radiators."""
    if not c.MIN_FLOW_TEMP_C <= target_flow_temp_c <= c.MAX_FLOW_TEMP_C:
        raise ValueError(
            f"target_flow_temp_c must be between {c.MIN_FLOW_TEMP_C} and {c.MAX_FLOW_TEMP_C}"
        )
    checks = tuple(check_radiator(room, target_flow_temp_c) for room in rooms)
    needed = None
    if checks:
        worst = max(check.min_flow_temp_c for check in checks)
        needed = Exact(
            math.ceil(worst) if math.isfinite(worst) else worst,
            # Room heat losses are estimates, so the needed flow temperature is too.
            Confidence.MEDIUM,
        )
    return TargetSpec(
        size_kw=size_range_kw(measured_design_load_kw),
        max_flow_temp_c=Exact(target_flow_temp_c, Confidence.MEDIUM),
        flow_temp_needed_by_current_radiators_c=needed,
        radiators=checks,
        grant=bus_grant(current_fuel),
    )


def _round_to(value: float, step: float, rounding: Callable[[float], int]) -> float:
    return rounding(value / step) * step
