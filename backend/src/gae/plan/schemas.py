"""All-electric plan payload — mirrors `frontend/src/api/types.ts`."""

from typing import Literal

from pydantic import BaseModel

from gae.survey.fields import NamedDefault

PlanStepStatus = Literal["ok", "flagged", "couldnt_tell", "info"]
SupplyStatus = Literal["ok", "flagged", "couldnt_tell"]
SolarStatus = Literal["ok", "couldnt_fetch"]


class PlanSupply(BaseModel):
    status: SupplyStatus
    fuse_rating_a: int | None
    heat_pump_thermal_kw: float
    heat_pump_running_a: float
    heat_pump_peak_a: float
    ev_charger_kw: float
    ev_draw_a: float
    household_a: float
    headroom_a: float | None
    message: str


class PlanHeatPump(BaseModel):
    size_kw_low: float
    size_kw_high: float
    max_flow_temp_c: float
    grant_gbp: float
    grant_note: str
    message: str


class PlanSolar(BaseModel):
    status: SolarStatus
    annual_yield_kwh: float | None
    payback_years: float | None
    array_kwp: float
    message: str


class PlanEv(BaseModel):
    status: PlanStepStatus
    message: str


class PlanStep(BaseModel):
    id: Literal["supply", "heat_pump", "solar", "ev"]
    title: str
    order_reason: str
    status: PlanStepStatus
    headline: str
    detail: str | None = None


class AllElectricPlan(BaseModel):
    steps: list[PlanStep]
    supply: PlanSupply
    heat_pump: PlanHeatPump
    solar: PlanSolar
    ev: PlanEv
    defaults: list[NamedDefault]
