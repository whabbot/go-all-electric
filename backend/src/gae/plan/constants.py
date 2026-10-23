"""Named defaults for the all-electric closing plan (supply headroom and solar payback).

These are advisory second opinions with low confidence, not a DNO assessment.
"""

# UK nominal single-phase voltage for converting kW to amps (BS 7671 / typical supply).
UK_NOMINAL_VOLTAGE_V = 230.0

# Typical simultaneous household load on the main fuse (lighting, cooking, appliances).
# Source: project plan, Oct 2026 — order-of-magnitude diversity, not a load calculation.
OTHER_HOUSEHOLD_LOAD_A = 30.0
OTHER_HOUSEHOLD_LOAD_NOTE = (
    "Assumes other circuits may draw about 30 A while the heat pump runs; "
    "a proper load assessment could be lower with diversity."
)

# Electrical input per kW of heat output at design conditions (cold day, defrost).
# Source: project plan, Oct 2026 — installer rule of thumb before a DNO application.
HP_ELECTRICAL_INPUT_PER_KW_THERMAL = 0.50
HP_ELECTRICAL_INPUT_NOTE = (
    "Roughly 0.5 kW electrical per kW thermal at design output; "
    "actual peak depends on the unit and weather."
)

# Extra amps allowed for compressor start / defrost on top of running draw.
HP_STARTUP_ALLOWANCE_A = 15.0
HP_STARTUP_NOTE = "Short-lived extra draw on start-up and defrost; not a sustained load."

# Standard 7.4 kW (32 A) home charger used for headroom check only.
EV_CHARGER_KW = 7.4
EV_CHARGER_NOTE = "Typical 7.4 kW (32 A) smart charger; faster chargers need more headroom."

# Spare amps we want on the main fuse after household + heat pump running draw.
SUPPLY_HEADROOM_THRESHOLD_A = 18.0
SUPPLY_HEADROOM_NOTE = (
    "Below about 18 A spare after the heat pump and typical household load, "
    "a 7.4 kW charger may not fit without an upgrade."
)

# Default rooftop array for the demo plan (not a site survey).
DEFAULT_ARRAY_KWP = 3.5
DEFAULT_ARRAY_SLOPE_DEG = 35.0
DEFAULT_ARRAY_AZIMUTH_DEG = 0.0  # PVGIS: 0 = south
DEFAULT_ARRAY_NOTE = (
    "Assumes 3.5 kWp, south-facing, 35° slope at the postcode district centroid — "
    "not your roof."
)

# Installed cost for simple payback (hardware + labour, very rough).
DEFAULT_ARRAY_COST_GBP_PER_KWP = 1_400.0
DEFAULT_ARRAY_COST_NOTE = "Rough installed cost per kWp for payback only; quotes vary widely."

PVGIS_SYSTEM_LOSS_PCT = 14.0
PVGIS_SOURCE = "EU JRC PVGIS PVcalc v5.2 (SARAH2), no API key"
OUTCODE_GEO_SOURCE = "postcodes.io outward-code centroid only"
