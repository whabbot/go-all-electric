"""Main fuse headroom vs heat pump and EV charger — pure code, named defaults."""

from dataclasses import dataclass
from typing import Literal

from gae.plan import constants as pc


@dataclass(frozen=True)
class SupplyAssessment:
    status: Literal["ok", "flagged", "couldnt_tell"]
    fuse_rating_a: int | None
    heat_pump_thermal_kw: float
    heat_pump_running_a: float
    heat_pump_peak_a: float
    ev_charger_kw: float
    ev_draw_a: float
    household_a: float
    headroom_a: float | None
    message: str


def _amps_from_kw(power_kw: float) -> float:
    return power_kw * 1000.0 / pc.UK_NOMINAL_VOLTAGE_V


def assess_supply(
    fuse_rating_a: int | None,
    *,
    heat_pump_thermal_kw: float,
    design_flow_temp_c: float,
) -> SupplyAssessment:
    ev_draw = _amps_from_kw(pc.EV_CHARGER_KW)
    household = pc.OTHER_HOUSEHOLD_LOAD_A

    # Design-condition electrical input from thermal output (not seasonal average SCOP).
    _ = design_flow_temp_c  # flow temp is shown on the heat-pump step; supply uses sizing kW.
    running = _amps_from_kw(heat_pump_thermal_kw * pc.HP_ELECTRICAL_INPUT_PER_KW_THERMAL)
    peak = running + pc.HP_STARTUP_ALLOWANCE_A
    sustained = household + running

    if fuse_rating_a is None:
        return SupplyAssessment(
            status="couldnt_tell",
            fuse_rating_a=None,
            heat_pump_thermal_kw=heat_pump_thermal_kw,
            heat_pump_running_a=round(running, 1),
            heat_pump_peak_a=round(peak, 1),
            ev_charger_kw=pc.EV_CHARGER_KW,
            ev_draw_a=round(ev_draw, 1),
            household_a=household,
            headroom_a=None,
            message="Couldn't tell: photograph the main fuse label on the sealed cutout.",
        )

    headroom = fuse_rating_a - sustained
    needs_upgrade = headroom < pc.SUPPLY_HEADROOM_THRESHOLD_A or sustained + ev_draw > fuse_rating_a
    if needs_upgrade:
        message = (
            f"About {running:.0f} A for a {heat_pump_thermal_kw:.0f} kW heat pump plus "
            f"{household:.0f} A typical household load on a {fuse_rating_a} A fuse leaves "
            f"little room for a {pc.EV_CHARGER_KW} kW charger ({ev_draw:.0f} A). "
            "You may need a supply upgrade; ask your network operator before booking an install."
        )
        status = "flagged"
    else:
        message = (
            f"A {fuse_rating_a} A fuse looks workable for a {heat_pump_thermal_kw:.0f} kW "
            f"heat pump (~{running:.0f} A at design output plus ~{household:.0f} A household), "
            f"with headroom for a {pc.EV_CHARGER_KW} kW charger; "
            "still confirm with your electrician."
        )
        status = "ok"

    return SupplyAssessment(
        status=status,
        fuse_rating_a=fuse_rating_a,
        heat_pump_thermal_kw=heat_pump_thermal_kw,
        heat_pump_running_a=round(running, 1),
        heat_pump_peak_a=round(peak, 1),
        ev_charger_kw=pc.EV_CHARGER_KW,
        ev_draw_a=round(ev_draw, 1),
        household_a=household,
        headroom_a=round(headroom, 1),
        message=message,
    )
