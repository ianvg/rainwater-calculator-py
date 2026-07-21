"""Deterministic decision support for candidate tank results."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math

import pandas as pd


@dataclass(frozen=True)
class TankRecommendation:
    role: str
    tank_size_gallons: float
    reliability_percent: float
    detail: str
    net_annual_savings: float | None = None
    simple_payback_years: float | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class RecommendationSet:
    reliability_target_percent: float
    marginal_gain_threshold: float
    recommendations: tuple[TankRecommendation, ...]
    alternatives: tuple[TankRecommendation, ...]


def _optional_finite(row: pd.Series, column: str) -> float | None:
    value = row.get(column)
    if value is None or pd.isna(value):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _choice(role: str, row: pd.Series, detail: str) -> TankRecommendation:
    return TankRecommendation(
        role=role,
        tank_size_gallons=float(row["TankSizeGallons"]),
        reliability_percent=float(row["ReliabilityPercent"]),
        detail=detail,
        net_annual_savings=_optional_finite(row, "NetAnnualSavings"),
        simple_payback_years=_optional_finite(row, "SimplePaybackYears"),
    )


def recommend_tank_sizes(
    candidate_data: pd.DataFrame,
    *,
    reliability_target_percent: float,
    marginal_gain_threshold: float,
    selected_tank_size_gallons: float | None = None,
) -> RecommendationSet:
    """Return auditable recommendations without claiming a universal optimum.

    ``marginal_gain_threshold`` is measured in reliability percentage points per
    additional 1,000 gallons.  The knee is the smaller candidate immediately
    before the first segment at or below that threshold.
    """
    target = min(max(float(reliability_target_percent), 0.0), 100.0)
    threshold = max(float(marginal_gain_threshold), 0.0)
    required = {"TankSizeGallons", "ReliabilityPercent"}
    if candidate_data.empty or not required.issubset(candidate_data.columns):
        return RecommendationSet(target, threshold, (), ())

    data = candidate_data.copy()
    for column in required:
        data[column] = pd.to_numeric(data[column], errors="coerce")
    data = data.dropna(subset=list(required))
    data = data[
        data["TankSizeGallons"].map(math.isfinite)
        & data["ReliabilityPercent"].map(math.isfinite)
        & (data["TankSizeGallons"] > 0.0)
    ]
    data = data.sort_values("TankSizeGallons").drop_duplicates(
        subset=["TankSizeGallons"], keep="last"
    ).reset_index(drop=True)
    if data.empty:
        return RecommendationSet(target, threshold, (), ())

    recommendations: list[TankRecommendation] = []
    target_rows = data[data["ReliabilityPercent"] >= target]
    if not target_rows.empty:
        row = target_rows.iloc[0]
        recommendations.append(
            _choice(
                "Smallest tank meeting reliability target",
                row,
                f"First simulated capacity at or above the {target:.1f}% target.",
            )
        )

    knee_index: int | None = None
    for index in range(1, len(data)):
        previous = data.iloc[index - 1]
        current = data.iloc[index]
        size_delta = float(current["TankSizeGallons"] - previous["TankSizeGallons"])
        if size_delta <= 0.0:
            continue
        gain = max(
            float(current["ReliabilityPercent"] - previous["ReliabilityPercent"]), 0.0
        ) / (size_delta / 1000.0)
        if gain <= threshold:
            knee_index = index - 1
            recommendations.append(
                _choice(
                    "Reliability-versus-capacity knee",
                    previous,
                    f"The next capacity gains {gain:.2f} reliability points per 1,000 gal, "
                    f"at or below the {threshold:.2f}-point threshold.",
                )
            )
            break

    if "SimplePaybackYears" in data:
        payback = pd.to_numeric(data["SimplePaybackYears"], errors="coerce")
        eligible = data[payback.map(lambda value: pd.notna(value) and math.isfinite(float(value)) and float(value) > 0.0)]
        if not eligible.empty:
            row = eligible.loc[pd.to_numeric(eligible["SimplePaybackYears"]).idxmin()]
            recommendations.append(
                _choice(
                    "Lowest-payback feasible candidate",
                    row,
                    "Lowest finite simple payback among the simulated candidate tanks.",
                )
            )

    anchor_index = knee_index
    if anchor_index is None and not target_rows.empty:
        anchor_size = float(target_rows.iloc[0]["TankSizeGallons"])
        anchor_index = int(data.index[data["TankSizeGallons"] == anchor_size][0])
    if anchor_index is None and selected_tank_size_gallons is not None:
        anchor_index = int(
            (data["TankSizeGallons"] - float(selected_tank_size_gallons)).abs().idxmin()
        )
    if anchor_index is None:
        anchor_index = min(len(data) // 2, len(data) - 1)

    recommended_sizes = {item.tank_size_gallons for item in recommendations}
    nearby_indices = [
        index
        for index in (anchor_index - 1, anchor_index, anchor_index + 1)
        if 0 <= index < len(data)
    ]
    alternatives: list[TankRecommendation] = []
    for index in nearby_indices:
        row = data.iloc[index]
        size = float(row["TankSizeGallons"])
        if size in recommended_sizes:
            continue
        relationship = "smaller" if index < anchor_index else "larger" if index > anchor_index else "at the comparison anchor"
        alternatives.append(
            _choice(
                "Nearby alternative",
                row,
                f"A {relationship} simulated option for comparing capacity, reliability, and economics.",
            )
        )

    return RecommendationSet(
        target,
        threshold,
        tuple(recommendations),
        tuple(alternatives),
    )


def selected_design_warnings(
    candidate_data: pd.DataFrame,
    *,
    selected_tank_size_gallons: float,
    reliability_target_percent: float,
    financial_configured: bool,
    missing_calendar_days: int = 0,
    incomplete_calendar_years: int = 0,
    completeness_percent: float | None = None,
    completeness_rating: str | None = None,
    partial_years: tuple[int, ...] = (),
    longest_missing_period: tuple[str, str, int] | None = None,
    rainfall_data_type: str | None = None,
    excessive_overflow_fraction: float = 0.25,
) -> list[str]:
    """Return deterministic review conditions for the selected design."""
    warnings: list[str] = []
    if candidate_data.empty or "TankSizeGallons" not in candidate_data:
        warnings.append("Candidate performance is unavailable; rerun the analysis.")
        return warnings
    sizes = pd.to_numeric(candidate_data["TankSizeGallons"], errors="coerce")
    valid = candidate_data[sizes.notna()]
    if valid.empty:
        warnings.append("Candidate performance is unavailable; rerun the analysis.")
        return warnings
    selected_index = (pd.to_numeric(valid["TankSizeGallons"]) - selected_tank_size_gallons).abs().idxmin()
    row = valid.loc[selected_index]
    reliability = _optional_finite(row, "ReliabilityPercent")
    if reliability is not None and reliability < reliability_target_percent:
        warnings.append(
            f"Selected-tank reliability is {reliability:.1f}%, below the "
            f"{reliability_target_percent:.1f}% review target."
        )

    overflow = _optional_finite(row, "OverflowGallons") or 0.0
    supply = _optional_finite(row, "RainwaterSuppliedGallons") or 0.0
    treatment = _optional_finite(row, "TreatmentLossGallons") or 0.0
    throughput = overflow + supply + treatment
    if throughput > 0.0 and overflow / throughput > excessive_overflow_fraction:
        warnings.append(
            f"Selected-tank overflow is {overflow / throughput:.0%} of simulated tank "
            f"throughput, above the {excessive_overflow_fraction:.0%} review threshold."
        )
    if missing_calendar_days > 0:
        warnings.append(
            f"The rainfall record has {missing_calendar_days:,} missing day(s) in its calendar coverage."
        )
    if longest_missing_period is not None:
        start, end, days = longest_missing_period
        warnings.append(
            f"The longest missing rainfall period is {days:,} day(s), from {start} to {end}."
        )
    if partial_years:
        years = ", ".join(str(year) for year in partial_years)
        warnings.append(f"Partial or incomplete rainfall year(s): {years}.")
    elif incomplete_calendar_years > 0:
        warnings.append(
            f"The rainfall record contains {incomplete_calendar_years:,} incomplete calendar year(s)."
        )
    if completeness_percent is not None and completeness_percent < 99.5:
        rating = f" ({completeness_rating})" if completeness_rating else ""
        warnings.append(
            f"Rainfall-record completeness is {completeness_percent:.2f}%{rating}; "
            "missing periods can bias reliability and storage results."
        )
    if rainfall_data_type == "unclassified":
        warnings.append(
            "Rainfall data is user-supplied but unclassified; identify whether it is "
            "observed, synthetic, interpolated, or gridded reanalysis data."
        )
    if not financial_configured:
        warnings.append(
            "Financial rates and costs are not configured; payback recommendations are unavailable."
        )
    return warnings
