"""Cross-check: compare the fabric estimate (A) against the measured estimate (B).

Where they disagree, say why rather than smoothing it over: rank the likely reasons by how
much of the gap each could explain, and name the inputs that drive each one.
"""

from dataclasses import dataclass
from enum import StrEnum

from gae.heatpump import constants as c
from gae.heatpump.constants import Glazing, WallType
from gae.heatpump.fabric import FabricEstimate, roof_u_value
from gae.heatpump.measured import MeasuredCaveat, MeasuredEstimate
from gae.heatpump.ranges import Range


class Verdict(StrEnum):
    AGREE = "agree"
    FABRIC_HIGHER = "fabric_higher"
    MEASURED_HIGHER = "measured_higher"


class ReasonCode(StrEnum):
    # Fabric (A) reads high
    DEFAULT_AIR_CHANGE_RATE = "default_air_change_rate"
    DEFAULT_GLAZING_U = "default_glazing_u"
    MISSED_INSULATION = "missed_insulation"
    # Measured (B) reads low
    SUNNY_OR_PART_HEATED = "sunny_or_part_heated"
    # Measured (B) reads high
    BOILER_EFFICIENCY_OVERSTATED = "boiler_efficiency_overstated"
    HOME_KEPT_WARMER = "home_kept_warmer"
    # Fabric (A) reads low
    DRAUGHTIER_THAN_ASSUMED = "draughtier_than_assumed"
    INSULATION_OVERSTATED = "insulation_overstated"


@dataclass(frozen=True)
class Reason:
    code: ReasonCode
    explanation: str
    # Input names whose values drive this reason, so the UI can ask the right question.
    drivers: tuple[str, ...]
    # Rough size of the effect in W/K, and the share of the A-B gap it could explain.
    potential_w_per_k: float
    share_of_gap: float


@dataclass(frozen=True)
class CrossCheck:
    verdict: Verdict
    # Fabric / measured. Range spans fabric.low / measured.high to fabric.high / measured.low.
    ratio: Range
    gap_w_per_k: float
    reasons: tuple[Reason, ...]


# Rough sizes for effects the inputs cannot quantify directly, as fractions of measured HTC.
_BOILER_EFFICIENCY_SHORTFALL = 0.10  # in-use efficiency ten points below the plate
_WARMER_HOME_FRACTION = 0.10  # ~2C warmer than design over the heating season
_DRAUGHT_EXTRA_ACH = 0.5


def cross_check(fabric: FabricEstimate, measured: MeasuredEstimate) -> CrossCheck:
    a = fabric.htc_w_per_k
    b = measured.htc_w_per_k
    ratio = Range(a.low / b.high, a.central / b.central, a.high / b.low)
    gap = a.central - b.central

    if c.AGREEMENT_RATIO_LOW <= ratio.central <= c.AGREEMENT_RATIO_HIGH:
        return CrossCheck(Verdict.AGREE, ratio, gap, ())

    if gap > 0:
        verdict = Verdict.FABRIC_HIGHER
        candidates = _fabric_high_reasons(fabric, measured)
    else:
        verdict = Verdict.MEASURED_HIGHER
        candidates = _measured_high_reasons(fabric, measured)

    reasons = sorted(
        (
            Reason(code, text, drivers, w, min(1.0, w / abs(gap)))
            for code, text, drivers, w in candidates
            if w > 0
        ),
        key=lambda r: r.potential_w_per_k,
        reverse=True,
    )
    return CrossCheck(verdict, ratio, gap, tuple(reasons))


_Candidate = tuple[ReasonCode, str, tuple[str, ...], float]


def _fabric_high_reasons(fabric: FabricEstimate, measured: MeasuredEstimate) -> list[_Candidate]:
    out: list[_Candidate] = []

    if fabric.built_before_2000 and fabric.air_change_rate > c.TYPICAL_MEASURED_ACH:
        w = (
            c.AIR_HEAT_CAPACITY_WH_PER_M3K
            * (fabric.air_change_rate - c.TYPICAL_MEASURED_ACH)
            * fabric.volume_m3
        )
        out.append(
            (
                ReasonCode.DEFAULT_AIR_CHANGE_RATE,
                f"The fabric calc assumes {fabric.air_change_rate} air changes per hour, a "
                f"default that overestimates most pre-2000 homes; around "
                f"{c.TYPICAL_MEASURED_ACH} is typical when measured.",
                ("year_built", "air_change_rate"),
                w,
            )
        )

    if fabric.glazing is Glazing.DOUBLE_UNKNOWN_DATE:
        w = fabric.window_area_m2 * (c.DEFAULT_DOUBLE_GLAZING_U - c.DOUBLE_GLAZING_2003_U)
        out.append(
            (
                ReasonCode.DEFAULT_GLAZING_U,
                f"Double glazing of unknown date is assumed U={c.DEFAULT_DOUBLE_GLAZING_U}; "
                f"units fitted from 2003 must meet {c.DOUBLE_GLAZING_2003_U}.",
                ("glazing",),
                w,
            )
        )

    missed: list[tuple[str, float]] = []
    upgraded_wall = {
        WallType.CAVITY_UNFILLED: WallType.CAVITY_FILLED,
        WallType.SOLID_BRICK: WallType.SOLID_INSULATED,
    }.get(fabric.wall_type)
    if upgraded_wall is not None:
        missed.append(
            (
                "wall_type",
                fabric.net_wall_area_m2
                * (c.WALL_U_VALUES[fabric.wall_type] - c.WALL_U_VALUES[upgraded_wall]),
            )
        )
    if fabric.loft_insulation_mm < c.RECOMMENDED_LOFT_INSULATION_MM:
        missed.append(
            (
                "loft_insulation_mm",
                fabric.roof_area_m2
                * (
                    roof_u_value(fabric.loft_insulation_mm)
                    - roof_u_value(c.RECOMMENDED_LOFT_INSULATION_MM)
                ),
            )
        )
    if missed:
        out.append(
            (
                ReasonCode.MISSED_INSULATION,
                "Insulation may have been added since the EPC was lodged (cavity fill, loft "
                "top-up); the fabric calc only knows what the record says.",
                tuple(name for name, _ in missed),
                sum(w for _, w in missed),
            )
        )

    flagged = {
        MeasuredCaveat.POSSIBLY_SUNNY,
        MeasuredCaveat.POSSIBLY_PARTIALLY_HEATED,
    } & set(measured.caveats)
    # Always a candidate: bills read low for sunny or part-heated homes. Weighted up when the
    # measured estimate itself raised the flag.
    share = c.LOW_READING_UPLIFT * (2 if flagged else 1)
    out.append(
        (
            ReasonCode.SUNNY_OR_PART_HEATED,
            "Bills read low in sunny homes and where some rooms are left unheated, so the "
            "measured figure may understate the heat loss on a cold, dull day.",
            ("sunny", "partially_heated", "floor_area_m2"),
            measured.htc_w_per_k.central * share,
        )
    )
    return out


def _measured_high_reasons(fabric: FabricEstimate, measured: MeasuredEstimate) -> list[_Candidate]:
    b = measured.htc_w_per_k.central
    out: list[_Candidate] = [
        (
            ReasonCode.BOILER_EFFICIENCY_OVERSTATED,
            f"Measured heat assumes the boiler delivers {measured.boiler_efficiency:.0%} of the "
            "gas as heat; older or poorly set-up boilers deliver less, which inflates the "
            "measured figure.",
            ("boiler_efficiency",),
            b * _BOILER_EFFICIENCY_SHORTFALL,
        ),
        (
            ReasonCode.HOME_KEPT_WARMER,
            f"The home may be kept warmer than {measured.indoor_temp_c:g}C, which uses more gas "
            "than the design condition assumes.",
            ("indoor_temp_c",),
            b * _WARMER_HOME_FRACTION,
        ),
        (
            ReasonCode.DRAUGHTIER_THAN_ASSUMED,
            "The home may be draughtier than the fabric calc's air change rate assumes "
            "(open chimneys, gappy floorboards).",
            ("air_change_rate",),
            c.AIR_HEAT_CAPACITY_WH_PER_M3K * _DRAUGHT_EXTRA_ACH * fabric.volume_m3,
        ),
    ]
    if fabric.wall_type in (WallType.CAVITY_FILLED, WallType.SOLID_INSULATED):
        as_built = (
            WallType.CAVITY_UNFILLED
            if fabric.wall_type is WallType.CAVITY_FILLED
            else WallType.SOLID_BRICK
        )
        out.append(
            (
                ReasonCode.INSULATION_OVERSTATED,
                "The record says the walls are insulated; if the fill is patchy or missing, the "
                "fabric calc understates the heat loss.",
                ("wall_type",),
                fabric.net_wall_area_m2
                * (c.WALL_U_VALUES[as_built] - c.WALL_U_VALUES[fabric.wall_type]),
            )
        )
    return out
