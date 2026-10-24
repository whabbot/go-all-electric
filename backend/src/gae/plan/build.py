"""Build the sequenced all-electric plan from analysis outputs."""

from typing import Any

from gae.heatpump import constants as hc
from gae.plan import constants as pc
from gae.plan.schemas import (
    AllElectricPlan,
    PlanEv,
    PlanHeatPump,
    PlanSolar,
    PlanStep,
    PlanSupply,
)
from gae.plan.solar import SolarYieldProvider, payback_years
from gae.plan.supply import assess_supply
from gae.survey.fields import NamedDefault
from gae.survey.schemas import InputReading


def _fuse_rating_a(readings: list[InputReading]) -> int | None:
    for item in readings:
        if str(item.kind) != "fuse_cutout":
            continue
        if item.status not in ("verified", "verified_with_warnings", "entered") or not item.reading:
            return None
        raw = item.reading.get("rating_a")
        if isinstance(raw, int):
            return raw
        if isinstance(raw, float) and raw.is_integer():
            return int(raw)
        if isinstance(raw, str) and raw.isdigit():
            return int(raw)
        return None
    return None


def _target_spec(bundle: dict[str, Any]) -> dict[str, Any]:
    spec = bundle.get("target_spec")
    if not isinstance(spec, dict):
        raise ValueError("target_spec missing from bundle")
    return spec


def build_all_electric_plan(
    *,
    postcode_district: str | None,
    readings: list[InputReading],
    bundle: dict[str, Any],
    solar: SolarYieldProvider,
) -> AllElectricPlan:
    spec = _target_spec(bundle)
    size = spec["size_kw"]
    max_flow = spec["max_flow_temp_c"]
    grant = spec["grant"]

    size_low = float(size["low"])
    size_high = float(size["high"])
    flow_c = float(max_flow["value"])
    grant_gbp = float(grant["amount_gbp"]["value"])
    grant_note = str(grant.get("note", ""))

    thermal_kw = size_high
    fuse_a = _fuse_rating_a(readings)
    supply = assess_supply(fuse_a, heat_pump_thermal_kw=thermal_kw, design_flow_temp_c=flow_c)

    defaults: list[NamedDefault] = [
        NamedDefault(
            input="plan_supply",
            name="other_household_load_a",
            value=f"{pc.OTHER_HOUSEHOLD_LOAD_A:g} A",
            note=pc.OTHER_HOUSEHOLD_LOAD_NOTE,
            confidence="low",
        ),
        NamedDefault(
            input="plan_supply",
            name="hp_electrical_input_per_kw_thermal",
            value=f"{pc.HP_ELECTRICAL_INPUT_PER_KW_THERMAL:g}",
            note=pc.HP_ELECTRICAL_INPUT_NOTE,
            confidence="low",
        ),
        NamedDefault(
            input="plan_supply",
            name="hp_startup_allowance_a",
            value=f"{pc.HP_STARTUP_ALLOWANCE_A:g} A",
            note=pc.HP_STARTUP_NOTE,
            confidence="low",
        ),
        NamedDefault(
            input="plan_supply",
            name="ev_charger_kw",
            value=f"{pc.EV_CHARGER_KW:g} kW",
            note=pc.EV_CHARGER_NOTE,
            confidence="low",
        ),
    ]

    heat_pump = PlanHeatPump(
        size_kw_low=size_low,
        size_kw_high=size_high,
        max_flow_temp_c=flow_c,
        grant_gbp=grant_gbp,
        grant_note=grant_note,
        message=(
            f"Target {size_low:g}-{size_high:g} kW at up to {flow_c:g}C flow, "
            f"with a BUS grant of £{grant_gbp:,.0f} ({grant_note})."
        ),
    )

    annual_kwh: float | None = None
    payback: float | None = None
    solar_status: str = "couldnt_fetch"
    solar_message = "Couldn't fetch typical yield for your postcode district right now."
    if postcode_district:
        annual_kwh = solar.annual_kwh(postcode_district)
        if annual_kwh is not None:
            solar_status = "ok"
            payback = round(
                payback_years(annual_kwh, electricity_pence_per_kwh=hc.ELECTRICITY_PENCE_PER_KWH), 1
            )
            solar_message = (
                f"About {annual_kwh:,.0f} kWh/year from a {pc.DEFAULT_ARRAY_KWP:g} kWp "
                f"south-facing array at the {postcode_district} district centroid; "
                f"simple payback about {payback:g} years at today's electricity price "
                "(not a quote)."
            )
            defaults.extend(
                [
                    NamedDefault(
                        input="plan_solar",
                        name="default_array_kwp",
                        value=f"{pc.DEFAULT_ARRAY_KWP:g} kWp",
                        note=pc.DEFAULT_ARRAY_NOTE,
                        confidence="low",
                    ),
                    NamedDefault(
                        input="plan_solar",
                        name="array_cost_gbp_per_kwp",
                        value=f"£{pc.DEFAULT_ARRAY_COST_GBP_PER_KWP:,.0f}/kWp",
                        note=pc.DEFAULT_ARRAY_COST_NOTE,
                        confidence="low",
                    ),
                ]
            )
    plan_solar = PlanSolar(
        status=solar_status,
        annual_yield_kwh=annual_kwh,
        payback_years=payback,
        array_kwp=pc.DEFAULT_ARRAY_KWP,
        message=solar_message,
    )

    if supply.status == "couldnt_tell":
        ev_status = "couldnt_tell"
        ev_message = (
            "Can't judge charger headroom without the main fuse rating; "
            "photograph the fuse label first."
        )
    elif not supply.ev_fits_with_heat_pump:
        ev_status = "flagged"
        ev_message = (
            f"A {pc.EV_CHARGER_KW:g} kW home charger (~{supply.ev_draw_a:g} A) on the same fuse "
            "as the heat pump likely needs a supply upgrade; ask your network operator before "
            "booking the charger."
        )
    elif not supply.heat_pump_fits:
        ev_status = "flagged"
        ev_message = "Sort the main fuse headroom for the heat pump before planning a home charger."
    else:
        ev_status = "ok"
        ev_message = (
            f"After the heat pump, a {pc.EV_CHARGER_KW:g} kW home charger "
            f"(~{supply.ev_draw_a:g} A) looks feasible on the spare capacity we estimated; "
            "still confirm with your electrician."
        )

    steps = [
        PlanStep(
            id="supply",
            title="Electricity supply",
            order_reason=(
                "Heat pumps and EV chargers both draw on the same main fuse; check headroom first."
            ),
            status=supply.status,
            headline=supply.message,
            detail=(
                f"Heat pump ~{supply.heat_pump_running_a:g} A running "
                f"(+{pc.HP_STARTUP_ALLOWANCE_A:g} A start allowance) · "
                f"household ~{supply.household_a:g} A · "
                f"EV charger {supply.ev_charger_kw:g} kW (~{supply.ev_draw_a:g} A)"
                if supply.fuse_rating_a
                else None
            ),
        ),
        PlanStep(
            id="heat_pump",
            title="Heat pump + grant",
            order_reason=(
                "Size and flow temperature come from your house; "
                "the grant depends on your current fuel."
            ),
            status="info",
            headline=heat_pump.message,
        ),
        PlanStep(
            id="solar",
            title="Solar",
            order_reason="Once heating is sized, generation offsets the higher electricity bill.",
            status="ok" if plan_solar.status == "ok" else "couldnt_tell",
            headline=plan_solar.message,
        ),
        PlanStep(
            id="ev",
            title="EV charging",
            order_reason=(
                "A home charger comes last, only if the supply still has room after the heat pump."
            ),
            status=ev_status,
            headline=ev_message,
        ),
    ]

    return AllElectricPlan(
        steps=steps,
        supply=PlanSupply(
            status=supply.status,
            fuse_rating_a=supply.fuse_rating_a,
            heat_pump_thermal_kw=supply.heat_pump_thermal_kw,
            heat_pump_running_a=supply.heat_pump_running_a,
            heat_pump_peak_a=supply.heat_pump_peak_a,
            ev_charger_kw=supply.ev_charger_kw,
            ev_draw_a=supply.ev_draw_a,
            household_a=supply.household_a,
            headroom_a=supply.headroom_a,
            heat_pump_fits=supply.heat_pump_fits,
            ev_fits_with_heat_pump=supply.ev_fits_with_heat_pump,
            message=supply.message,
        ),
        heat_pump=heat_pump,
        solar=plan_solar,
        ev=PlanEv(status=ev_status, message=ev_message),
        defaults=defaults,
    )
