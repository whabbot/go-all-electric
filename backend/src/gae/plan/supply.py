"""Main fuse headroom vs heat pump and EV charger — pure code, named defaults."""

from dataclasses import dataclass
from typing import Literal

from gae.plan import constants as pc

DNO_HEAT_PUMP_NOTIFY = (
    "Your installer must notify the network operator of a heat pump install; "
    "this app does not contact them."
)


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
    heat_pump_fits: bool
    ev_fits_with_heat_pump: bool
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
            heat_pump_fits=False,
            ev_fits_with_heat_pump=False,
            message="Couldn't tell: photograph the main fuse label on the sealed cutout.",
        )

    headroom = fuse_rating_a - sustained
    heat_pump_fits = sustained <= fuse_rating_a
    ev_fits = sustained + ev_draw <= fuse_rating_a

    if not heat_pump_fits:
        message = (
            f"About {running:.0f} A for a {heat_pump_thermal_kw:.0f} kW heat pump plus "
            f"{household:.0f} A typical household load may be too much for a {fuse_rating_a} A "
            f"fuse. Ask your network operator before booking an install. {DNO_HEAT_PUMP_NOTIFY}"
        )
        status = "flagged"
    elif not ev_fits:
        message = (
            f"A {fuse_rating_a} A fuse is usually enough for a {heat_pump_thermal_kw:.0f} kW "
            f"heat pump (~{running:.0f} A plus ~{household:.0f} A household), "
            f"but a {pc.EV_CHARGER_KW:g} "
            f"kW EV charger (~{ev_draw:.0f} A) on the same fuse likely needs a supply upgrade. "
            f"Ask your network operator before booking the charger. {DNO_HEAT_PUMP_NOTIFY}"
        )
        status = "flagged"
    else:
        message = (
            f"A {fuse_rating_a} A fuse looks workable for a {heat_pump_thermal_kw:.0f} kW "
            f"heat pump "
            f"(~{running:.0f} A) and a {pc.EV_CHARGER_KW:g} kW charger (~{ev_draw:.0f} A) with "
            f"typical household load. {DNO_HEAT_PUMP_NOTIFY}"
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
        heat_pump_fits=heat_pump_fits,
        ev_fits_with_heat_pump=ev_fits,
        message=message,
    )
