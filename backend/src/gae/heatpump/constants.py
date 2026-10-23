"""Every constant the maths core relies on, with its source and date.

Keep constants here, named, so the cross-check can point at the exact default an estimate used
and so a reviewer can audit one file. When a value changes (for example a new price cap),
update it here with the new source and date.
"""

from enum import StrEnum

# --- Energy prices -------------------------------------------------------------------------
# Source: Ofgem energy price cap, 1 Oct - 31 Dec 2026, typical direct-debit unit rates
# (project plan, Oct 2026). Unit rates only: standing charges are excluded from comparisons.
PRICE_CAP_PERIOD = "2026-10-01 to 2026-12-31"
ELECTRICITY_PENCE_PER_KWH = 26.32
GAS_PENCE_PER_KWH = 7.97

# --- Design conditions ---------------------------------------------------------------------
# Whole-house design internal temperature (MCS MIS 3005-D uses 21C for living spaces).
DESIGN_INDOOR_TEMP_C = 21.0
# External design temperature for London (CIBSE Guide A / MCS location data, ~-2C).
LONDON_DESIGN_OUTDOOR_TEMP_C = -2.0
# Heating degree days use a 15.5C base (UK convention, CIBSE TM41) which already allows for
# incidental gains from people, appliances and the sun.
DEGREE_DAY_BASE_TEMP_C = 15.5

# --- Measured (bill-based) method ----------------------------------------------------------
# Typical in-use seasonal efficiency of a modern condensing gas boiler. SEDBUK ratings are
# ~89-92% but field trials (Energy Saving Trust, 2009 condensing boiler trial) show in-use
# performance a few points lower.
DEFAULT_BOILER_EFFICIENCY = 0.85
# Share of annual gas use that is hot water and cooking rather than space heating, used when
# only an annual figure exists. Energy Saving Trust / BEIS (ECUK) put hot water at roughly
# 15-20% of household gas; the spread feeds the uncertainty below.
DEFAULT_BASELINE_FRACTION = 0.18
DEFAULT_BASELINE_FRACTION_LOW = 0.12
DEFAULT_BASELINE_FRACTION_HIGH = 0.25
# Months treated as heating-off when subtracting the summer baseline from monthly readings.
SUMMER_MONTHS = (6, 7, 8)
# Relative uncertainty of a bill-based heat transfer coefficient. Government-trialled measured
# methods (BEIS SMETER programme) carry roughly +/-20% error (project plan).
MEASURED_METHOD_UNCERTAINTY = 0.20
# Extra relative uncertainty when the boiler efficiency is a default rather than read from the
# data plate.
DEFAULTED_EFFICIENCY_UNCERTAINTY = 0.05
# Sunny or part-heated homes read low on bills; widen the top of the range by this much when
# either is flagged.
LOW_READING_UPLIFT = 0.15
# Specific heat loss (HTC per m2 floor area) below which a pre-2000 home is likely reading low
# because of solar gain or partial heating rather than genuinely low losses. Rule of thumb from
# typical UK HTCs (~2-3 W/K per m2 for pre-1980 semis).
LOW_SPECIFIC_HTC_W_PER_K_M2 = 1.6

# --- Fabric (installer-style) method -------------------------------------------------------
# U-values (W/m2K) below are the "as built" defaults an installer calc (RdSAP 10 tables /
# CIBSE Guide A) assumes when nothing better is known.


class WallType(StrEnum):
    SOLID_BRICK = "solid_brick"
    CAVITY_UNFILLED = "cavity_unfilled"
    CAVITY_FILLED = "cavity_filled"
    SOLID_INSULATED = "solid_insulated"
    TIMBER_FRAME = "timber_frame"


WALL_U_VALUES: dict[WallType, float] = {
    WallType.SOLID_BRICK: 2.1,  # CIBSE Guide A, 220mm solid brick, plastered
    WallType.CAVITY_UNFILLED: 1.5,  # RdSAP, cavity as built, pre-1976
    WallType.CAVITY_FILLED: 0.7,  # RdSAP, filled cavity
    WallType.SOLID_INSULATED: 0.6,  # RdSAP, solid wall with 50mm internal/external insulation
    WallType.TIMBER_FRAME: 0.8,  # RdSAP, timber frame as built, pre-1976
}


class Glazing(StrEnum):
    SINGLE = "single"
    # Double glazing of unknown date: installer calcs commonly default to U=2.8.
    DOUBLE_UNKNOWN_DATE = "double_unknown_date"
    DOUBLE_PRE_2003 = "double_pre_2003"
    # Building Regulations Part L (2002 edition, in force April 2002/2003) required U <= 2.2
    # for replacement windows.
    DOUBLE_2003_ONWARDS = "double_2003_onwards"
    TRIPLE = "triple"


SINGLE_GLAZING_U = 4.8  # RdSAP, single glazing, wood/PVC frame
DEFAULT_DOUBLE_GLAZING_U = 2.8  # Common installer/RdSAP default for double glazing, unknown date
DOUBLE_GLAZING_2003_U = 2.2  # Part L 2002 limit for replacement windows (brief: required 2003+)
TRIPLE_GLAZING_U = 1.6  # Typical modern triple glazing

GLAZING_U_VALUES: dict[Glazing, float] = {
    Glazing.SINGLE: SINGLE_GLAZING_U,
    Glazing.DOUBLE_UNKNOWN_DATE: DEFAULT_DOUBLE_GLAZING_U,
    Glazing.DOUBLE_PRE_2003: DEFAULT_DOUBLE_GLAZING_U,
    Glazing.DOUBLE_2003_ONWARDS: DOUBLE_GLAZING_2003_U,
    Glazing.TRIPLE: TRIPLE_GLAZING_U,
}

# Loft insulation thickness (mm) -> roof U-value, approximating the RdSAP default table for
# pitched roofs with insulation at the joists. Look-up takes the entry at or below the given
# thickness.
ROOF_U_BY_LOFT_INSULATION_MM: tuple[tuple[int, float], ...] = (
    (0, 2.3),
    (25, 1.0),
    (50, 0.68),
    (100, 0.4),
    (150, 0.3),
    (200, 0.21),
    (270, 0.16),
)
RECOMMENDED_LOFT_INSULATION_MM = 270  # Energy Saving Trust recommended depth

# Ground floor U-value for an uninsulated suspended timber or solid floor in a typical semi
# (BS EN ISO 13370 for perimeter/area ~0.5), and for insulated floors from 2003.
FLOOR_U_UNINSULATED = 0.7
FLOOR_U_INSULATED = 0.25

DOOR_U = 3.0  # RdSAP, solid timber door
DOOR_AREA_M2 = 1.85  # RdSAP default area per door
DOORS_PER_DWELLING = 2

# Geometry defaults when only a floor area is known.
# External wall height per storey including the floor zone (~2.5m room + ~0.2m floor).
STOREY_HEIGHT_M = 2.7
ROOM_HEIGHT_M = 2.5  # Internal room height for ventilation volume
WINDOW_TO_FLOOR_RATIO = 0.18  # RdSAP-style window area of ~18% of floor area for older houses
# Thermal bridging allowance y (W/m2K over exposed area), RdSAP default for pre-2003 dwellings.
THERMAL_BRIDGING_Y = 0.15

# Ventilation heat loss: 0.33 W/K per m3 per air change (air density x heat capacity / 3600).
AIR_HEAT_CAPACITY_WH_PER_M3K = 0.33
# Installer default air change rate for pre-2000 homes. CIBSE Guide A Table 4.21 room rates for
# older dwellings (living 1.5, kitchen 2.0, bathroom 3.0, bedrooms 1.0) average about 1.5 ACH;
# these are known to overestimate heat loss for most homes.
INSTALLER_DEFAULT_ACH_PRE_2000 = 1.5
INSTALLER_DEFAULT_ACH_2000_ONWARDS = 1.0
# Typical measured whole-house infiltration for UK pre-2000 homes at normal conditions
# (UK blower-door surveys of older housing typically imply ~0.5-0.8 ACH in normal conditions).
TYPICAL_MEASURED_ACH = 0.7

# Relative uncertainty of the simplified fabric calc (geometry and U-value defaults).
FABRIC_METHOD_UNCERTAINTY = 0.15

# --- Cross-check ---------------------------------------------------------------------------
# Fabric/measured ratio band treated as agreement given both methods' uncertainty.
AGREEMENT_RATIO_LOW = 0.8
AGREEMENT_RATIO_HIGH = 1.25

# --- Heat pump performance -----------------------------------------------------------------
# Approximate seasonal COP for a well-installed air source heat pump at a 40C design flow
# temperature. Consistent with the project plan ("SCOP 3.5 beats gas; a poorly set-up 2.5
# costs more") and MCS heat emitter guidance; field medians are lower when installs are poor.
REFERENCE_SCOP = 3.8
REFERENCE_FLOW_TEMP_C = 40.0
# Each extra degree of flow temperature costs roughly 3% efficiency (project plan; matches
# Carnot-based rules of thumb). Applied compounding per degree.
SCOP_LOSS_PER_DEGREE = 0.03
# Spread around the flow-temperature curve for installation quality (sizing, controls,
# commissioning).
SCOP_SPREAD = 0.5
# Hot water is heated to ~50-55C, so its seasonal COP is lower than space heating.
HOT_WATER_SCOP = 2.7
SCOP_MIN = 1.5
SCOP_MAX = 5.0

# --- Sizing and emitters -------------------------------------------------------------------
# Size range from the measured design load: no smaller than the central estimate, no more than
# this margin over the high end (oversized units cycle and lose efficiency).
SIZE_MARGIN_OVER_HIGH = 0.15
SIZE_ROUNDING_KW = 0.5
# Recommended maximum design flow temperature for good efficiency, and the hard ceiling.
TARGET_FLOW_TEMP_C = 45.0
MIN_FLOW_TEMP_C = 35.0
MAX_FLOW_TEMP_C = 55.0
# Heat pump systems run a ~5K flow/return difference, so mean water temp = flow - 2.5K.
HEAT_PUMP_FLOW_RETURN_DELTA_K = 5.0
# Radiator output scales with (Delta-T / 50)^n, n = 1.3 for panel radiators (BS EN 442).
RADIATOR_RATED_DELTA_T_K = 50.0
RADIATOR_EXPONENT = 1.3
# Room heat losses are themselves estimates; within this margin a radiator is "marginal".
RADIATOR_MARGIN = 0.10

# --- Boiler Upgrade Scheme -----------------------------------------------------------------
# Source: project plan, Oct 2026 (BUS grant towards an air or ground source heat pump).


class HeatingFuel(StrEnum):
    GAS = "gas"
    OIL = "oil"
    LPG = "lpg"
    ELECTRIC = "electric"
    OTHER = "other"


BUS_GRANT_GBP: dict[HeatingFuel, int] = {
    HeatingFuel.GAS: 7_500,
    HeatingFuel.OIL: 9_000,
    HeatingFuel.LPG: 9_000,
}
BUS_GRANT_SOURCE = "Boiler Upgrade Scheme rates per project plan, Oct 2026"
