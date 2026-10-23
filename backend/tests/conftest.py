import pytest

from gae.heatpump.constants import Glazing, WallType
from gae.heatpump.fabric import FabricEstimate, PropertyType, estimate_fabric
from gae.heatpump.measured import MeasuredEstimate, estimate_measured

# Sam: 1930s semi in London, gas combi, ~12,000 kWh/yr of gas. Illustrative persona data only.
SAM_MONTHLY_GAS_KWH = {
    1: 2050,
    2: 1800,
    3: 1400,
    4: 950,
    5: 500,
    6: 170,
    7: 150,
    8: 160,
    9: 330,
    10: 900,
    11: 1600,
    12: 1990,
}
SAM_ANNUAL_GAS_KWH = sum(SAM_MONTHLY_GAS_KWH.values())
# London heating degree days, 15.5C base, for a recent typical year.
SAM_DEGREE_DAYS = 1800
# Condensing combi; data plate efficiency less a few points for in-use performance.
SAM_BOILER_EFFICIENCY = 0.88
SAM_FLOOR_AREA_M2 = 90


@pytest.fixture
def sam_measured() -> MeasuredEstimate:
    return estimate_measured(
        annual_gas_kwh=SAM_ANNUAL_GAS_KWH,
        heating_degree_days=SAM_DEGREE_DAYS,
        monthly_gas_kwh=SAM_MONTHLY_GAS_KWH,
        boiler_efficiency=SAM_BOILER_EFFICIENCY,
        floor_area_m2=SAM_FLOOR_AREA_M2,
    )


@pytest.fixture
def sam_fabric() -> FabricEstimate:
    return estimate_fabric(
        floor_area_m2=SAM_FLOOR_AREA_M2,
        property_type=PropertyType.SEMI_DETACHED,
        year_built=1930,
        wall_type=WallType.CAVITY_UNFILLED,
        glazing=Glazing.DOUBLE_UNKNOWN_DATE,
        loft_insulation_mm=100,
    )
