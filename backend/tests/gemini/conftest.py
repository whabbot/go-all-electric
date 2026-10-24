"""Synthetic fixtures for the Gemini package. No network: Gemini is `FakeGemini` throughout."""

from typing import Any

import pytest

from gae.db.models import Datasheet
from gae.gemini.datasheets import InMemoryDatasheetLookup
from gae.gemini.schemas import (
    BoilerPlateReading,
    GasBillReading,
    LoftReading,
    MathsBundle,
    QuoteReading,
)
from gae.heatpump.constants import HeatingFuel
from gae.heatpump.costs import compare_running_costs
from gae.heatpump.crosscheck import cross_check
from gae.heatpump.fabric import FabricEstimate
from gae.heatpump.measured import MeasuredEstimate
from gae.heatpump.spec import target_spec
from tests.conftest import SAM_ANNUAL_GAS_KWH, SAM_BOILER_EFFICIENCY

# Invented makes and models: these are test fixtures, not manufacturer data.
SYNTHETIC_SHEETS = [
    Datasheet(
        id="synthetic-acme-combi-24i",
        make="Acme Heating",
        model="Comfort Combi 24i",
        kind="gas_combi",
        nominal_capacity_kw=24.0,
        heating_min_kw=4.0,
        heating_max_kw=20.0,
        source_url="https://example.invalid/acme-24i",
        notes="Synthetic test entry.",
        text="Acme Heating Comfort Combi 24i. Central heating output 4-20 kW. Hot water 24 kW.",
    ),
    Datasheet(
        id="synthetic-acme-system-18",
        make="Acme Heating",
        model="Comfort System 18",
        kind="gas_system",
        nominal_capacity_kw=18.0,
        heating_min_kw=4.0,
        heating_max_kw=18.0,
        source_url="https://example.invalid/acme-18",
        notes="Synthetic test entry.",
        text="Acme Heating Comfort System 18. Central heating output 4-18 kW.",
    ),
    Datasheet(
        id="synthetic-zephyr-airsource-6",
        make="Zephyr",
        model="AirSource 6",
        kind="heat_pump",
        nominal_capacity_kw=6.0,
        scop_35=4.4,
        scop_55=3.3,
        source_url="https://example.invalid/zephyr-6",
        notes="Synthetic test entry.",
        text="Zephyr AirSource 6 monobloc. Nominal 6 kW. SCOP 4.4 at 35C, 3.3 at 55C.",
    ),
    Datasheet(
        id="synthetic-zephyr-airsource-9",
        make="Zephyr",
        model="AirSource 9",
        kind="heat_pump",
        nominal_capacity_kw=9.0,
        scop_35=4.3,
        scop_55=3.2,
        source_url="https://example.invalid/zephyr-9",
        notes="Synthetic test entry.",
        text="Zephyr AirSource 9 monobloc. Nominal 9 kW. SCOP 4.3 at 35C, 3.2 at 55C.",
    ),
]


@pytest.fixture
def lookup() -> InMemoryDatasheetLookup:
    return InMemoryDatasheetLookup(SYNTHETIC_SHEETS)


@pytest.fixture
def sam_maths(sam_measured: MeasuredEstimate, sam_fabric: FabricEstimate) -> MathsBundle:
    costs = [
        compare_running_costs(
            annual_gas_kwh=SAM_ANNUAL_GAS_KWH,
            heating_gas_kwh=sam_measured.heating_gas_kwh.central,
            boiler_efficiency=SAM_BOILER_EFFICIENCY,
            design_flow_temp_c=flow,
        )
        for flow in (40, 55)
    ]
    return MathsBundle.from_core(
        sam_measured,
        sam_fabric,
        cross_check(sam_fabric, sam_measured),
        costs,
        target_spec(
            measured_design_load_kw=sam_measured.design_load_kw, current_fuel=HeatingFuel.GAS
        ),
    )


def boiler(**overrides: Any) -> BoilerPlateReading:
    values = dict(
        legible=True,
        confidence="high",
        notes="",
        make="Acme Heating",
        model="Comfort Combi 24i",
        gc_number="47-000-00",
        heating_output_kw=20.0,
        hot_water_output_kw=24.0,
        fuel="natural_gas",
    )
    return BoilerPlateReading(**{**values, **overrides})


def bill(**overrides: Any) -> GasBillReading:
    values = dict(
        legible=True,
        confidence="high",
        notes="",
        supplier="Example Energy",
        period_start="2025-10-01",
        period_end="2026-09-30",
        total_kwh=12_000,
        monthly=[],
        estimated_reading=False,
    )
    return GasBillReading(**{**values, **overrides})


def quote(**overrides: Any) -> QuoteReading:
    values = dict(
        legible=True,
        confidence="high",
        notes="",
        heat_pump_make="Zephyr",
        heat_pump_model="AirSource 9",
        heat_pump_kw=9.0,
        design_flow_temp_c=55,
        buffer_tank=True,
        cylinder="200 L unvented",
        line_items=[
            {"description": "Heat pump and controls", "amount_gbp": 8_000},
            {"description": "Cylinder", "amount_gbp": 2_000},
            {"description": "Installation and commissioning", "amount_gbp": 3_500},
        ],
        total_gbp=13_500,
        grant_deducted=False,
        grant_amount_gbp=None,
        mcs_heat_loss_kw=8.9,
    )
    return QuoteReading(**{**values, **overrides})


def loft(**overrides: Any) -> LoftReading:
    values = dict(
        legible=True,
        confidence="high",
        notes="",
        insulation_visible=True,
        depth_mm_band="270mm",
        joists_visible_above_insulation=False,
        ruler_or_tape_visible=True,
    )
    return LoftReading(**{**values, **overrides})


JPEG = b"\xff\xd8\xff\xe0synthetic-not-a-real-photo"
PDF = b"%PDF-1.7 synthetic quote"
