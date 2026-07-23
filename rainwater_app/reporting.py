"""Pure report data preparation and output-format helpers."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
import copy
from dataclasses import dataclass
import math
import os
from pathlib import Path
import tempfile

import pandas as pd

from rainwater_app.models import MONTH_KEYS, ProjectConfig
from rainwater_app.units import (
    area_to_display,
    precip_to_display,
    volume_to_display,
    volume_unit,
)

MONTH_LABELS = {
    "jan": "Jan",
    "feb": "Feb",
    "mar": "Mar",
    "apr": "Apr",
    "may": "May",
    "jun": "Jun",
    "jul": "Jul",
    "aug": "Aug",
    "sep": "Sep",
    "oct": "Oct",
    "nov": "Nov",
    "dec": "Dec",
}

REPORT_SCHEMA_VERSION = 2

REPORT_SECTION_DEFINITIONS = (
    ("design_recommendations", "Design recommendations", "design-recommendations", "Design Recommendations and Review Conditions"),
    ("project_information", "Project information", "project-information", "Project Information"),
    ("executive_summary", "Executive summary", "executive-summary", "Executive Summary"),
    ("notes", "Notes", "notes", "Notes"),
    ("surface_area_summary", "Surface area summary", "surface-area-summary", "Surface Area Summary"),
    ("rainfall_volume_summary", "Rainfall volume summary", "rainfall-volume-summary", "Rainfall Volume Summary"),
    ("tank_summary", "Tank summary", "tank-summary", "Tank Summary"),
    ("candidate_performance", "Candidate performance", "candidate-performance", "Candidate Performance"),
    ("water_balance", "Reconciled water balance", "water-balance", "Reconciled Water Balance"),
    ("demand_summary", "Demand summary", "demand-summary", "Demand Summary"),
    ("end_use_performance", "End-use performance", "end-use-performance", "End-use Performance"),
    ("financial_analysis", "Financial analysis", "financial-analysis", "Financial Analysis"),
    ("rainfall_quality", "Rainfall quality and completeness", "rainfall-quality", "Rainfall Quality and Completeness"),
    ("yearly_rainfall", "Yearly rainfall summary", "yearly-rainfall", "Yearly Rainfall Summary"),
    ("rainfall_events", "Rainfall-event summary", "rainfall-events", "Rainfall-event Summary"),
    ("first_flush_summary", "First-flush diversion summary", "first-flush-summary", "First-flush Diversion Summary"),
    ("analysis_provenance", "Analysis provenance", "analysis-provenance", "Analysis Provenance"),
    ("reliability_curve", "Reliability curve", "reliability-curve", "Reliability Curve"),
    ("yearly_demand_reliability", "Yearly demand reliability", "yearly-demand-reliability", "Yearly Demand Reliability"),
    ("tank_level_distribution", "Tank level distribution", "tank-level-distribution", "Tank Level Distribution"),
)
DEFAULT_REPORT_SECTIONS = {key: True for key, _label, _html_id, _title in REPORT_SECTION_DEFINITIONS}


def normalize_report_sections(value: object) -> dict[str, bool]:
    """Return a complete, forward-compatible set of report section choices."""
    supplied = value if isinstance(value, Mapping) else {}
    return {
        key: bool(supplied.get(key, default))
        for key, default in DEFAULT_REPORT_SECTIONS.items()
    }


class ReportValidationError(ValueError):
    """Raised when renderer input does not satisfy the report schema."""


def _validate_report_value(value: object, path: str = "report") -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ReportValidationError(f"{path} contains a non-finite number.")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ReportValidationError(f"{path} contains a non-string key.")
            _validate_report_value(item, f"{path}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _validate_report_value(item, f"{path}[{index}]")
        return
    raise ReportValidationError(f"{path} contains unsupported value type {type(value).__name__}.")


@dataclass(frozen=True)
class ReportModel(Mapping[str, object]):
    """Validated, versioned renderer input shared by every report format."""

    schema_version: int
    _payload: dict[str, object]

    @classmethod
    def from_payload(cls, payload: Mapping[str, object] | "ReportModel") -> "ReportModel":
        if isinstance(payload, cls):
            return payload
        normalized = copy.deepcopy(dict(payload))
        version = int(normalized.pop("schema_version", REPORT_SCHEMA_VERSION))
        if version != REPORT_SCHEMA_VERSION:
            raise ReportValidationError(
                f"Unsupported report schema version {version}; expected {REPORT_SCHEMA_VERSION}."
            )
        required = {
            "metadata",
            "area_unit",
            "volume_unit",
            "precipitation_unit",
            "surfaces",
            "monthly_demand",
            "curve",
            "selected_tank_size",
            "selected_reliability",
        }
        missing = sorted(required.difference(normalized))
        if missing:
            raise ReportValidationError("Missing report field(s): " + ", ".join(missing) + ".")
        if not isinstance(normalized["metadata"], Mapping):
            raise ReportValidationError("report.metadata must be a mapping.")
        if not isinstance(normalized["surfaces"], list):
            raise ReportValidationError("report.surfaces must be a list.")
        if not isinstance(normalized["monthly_demand"], list) or len(normalized["monthly_demand"]) != 12:
            raise ReportValidationError("report.monthly_demand must contain 12 months.")
        if not isinstance(normalized["curve"], list) or not normalized["curve"]:
            raise ReportValidationError("report.curve must contain at least one point.")
        for index, point in enumerate(normalized["curve"]):
            if not isinstance(point, Mapping) or not {"tank_size", "reliability"}.issubset(point):
                raise ReportValidationError(
                    f"report.curve[{index}] must contain tank_size and reliability."
                )
        normalized.setdefault("recommendations", [])
        normalized.setdefault("review_warnings", [])
        normalized.setdefault("rainfall_quality", {})
        normalized.setdefault("yearly_rainfall_summary", [])
        normalized.setdefault("rainfall_event_summary", {})
        normalized.setdefault("first_flush_event_summary", [])
        normalized.setdefault("first_flush_yearly_summary", [])
        normalized.setdefault("average_annual_rainfall_volumes", {})
        normalized["report_sections"] = normalize_report_sections(
            normalized.get("report_sections")
        )
        _validate_report_value(normalized)
        return cls(version, normalized)

    def __getitem__(self, key: str) -> object:
        if key == "schema_version":
            return self.schema_version
        return self._payload[key]

    def __iter__(self) -> Iterator[str]:
        yield "schema_version"
        yield from self._payload

    def __len__(self) -> int:
        return len(self._payload) + 1

    def to_dict(self) -> dict[str, object]:
        return {"schema_version": self.schema_version, **copy.deepcopy(self._payload)}


def atomic_write_text(path: Path, content: str) -> None:
    """Validate and atomically replace a UTF-8 text artifact."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            prefix=f".{target.name}.",
            suffix=".tmp",
            dir=target.parent,
            delete=False,
        ) as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
            temporary_path = Path(handle.name)
        if temporary_path.stat().st_size == 0:
            raise ValueError("Refusing to replace an artifact with an empty file.")
        os.replace(temporary_path, target)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def latex_escape(value: object) -> str:
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return "".join(replacements.get(char, char) for char in str(value))


def latex_row(*values: object) -> str:
    return " & ".join(latex_escape(value) for value in values) + r" \\"


def latex_number(value: object) -> str:
    return f"{float(value):.6g}"


def pdf_escape(value: object) -> str:
    text = str(value).replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    return text.encode("latin-1", errors="replace").decode("latin-1")


def clip_pdf_text(value: object, max_chars: int) -> str:
    text = str(value)
    if len(text) <= max_chars:
        return text
    return text[: max(0, max_chars - 3)] + "..."


def wrap_pdf_text(value: str, width: int) -> list[str]:
    words = value.split()
    if not words:
        return [""]
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        if len(current) + 1 + len(word) <= width:
            current = f"{current} {word}"
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def report_surface_rows(config: ProjectConfig) -> list[dict[str, object]]:
    return [
        {
            "name": surface.name,
            "area": area_to_display(surface.area, config),
            "runoff_coefficient": surface.runoff_coefficient,
            "first_flush_depth": precip_to_display(
                surface.first_flush_depth_inches, config
            ),
        }
        for surface in config.surfaces
        if surface.area > 0
    ]


def report_average_annual_rainfall_volumes(
    results: pd.DataFrame, config: ProjectConfig
) -> dict[str, float]:
    """Summarize gross rain, first flush, and usable rain as mean annual volumes."""
    columns = {
        "total_average_rain": "GrossCollectedGallons",
        "average_first_flush_diversion": "FirstFlushLossGallons",
        "total_usable_average_rain": "CollectedGallons",
    }
    if results.empty or "Date" not in results:
        return {key: 0.0 for key in columns}
    values = pd.DataFrame({"Date": pd.to_datetime(results["Date"], errors="coerce")})
    for key, column in columns.items():
        values[key] = pd.to_numeric(
            results.get(column, pd.Series(0.0, index=results.index)), errors="coerce"
        ).fillna(0.0)
    values = values.dropna(subset=["Date"])
    if values.empty:
        return {key: 0.0 for key in columns}
    annual = values.groupby(values["Date"].dt.year)[list(columns)].sum()
    return {
        key: volume_to_display(float(annual[key].mean()), config)
        for key in columns
    }


def report_first_flush_summaries(
    results: pd.DataFrame, config: ProjectConfig
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Aggregate first-flush volumes by rainfall event and calendar year.

    Event rows include only timesteps carrying a rainfall event identifier. Yearly
    rows retain all simulated volumes, including legacy results that predate event
    identifiers. An event is counted in the year in which it starts, even when it
    crosses a calendar-year boundary.
    """
    if results.empty or "Date" not in results:
        return [], []

    values = pd.DataFrame({"date": pd.to_datetime(results["Date"], errors="coerce")})
    for output, source in (
        ("gross_runoff", "GrossCollectedGallons"),
        ("first_flush_loss", "FirstFlushLossGallons"),
        ("net_collected", "CollectedGallons"),
    ):
        values[output] = pd.to_numeric(
            results.get(source, pd.Series(0.0, index=results.index)), errors="coerce"
        ).fillna(0.0).clip(lower=0.0)
    values["event_id"] = results.get(
        "RainfallEventId", pd.Series(pd.NA, index=results.index, dtype="object")
    )
    supplied_starts = results.get("RainfallEventStart")
    if supplied_starts is None:
        values["event_start"] = values["event_id"].notna() & ~values["event_id"].duplicated()
    else:
        values["event_start"] = supplied_starts.fillna(False).astype(bool)
    values = values.dropna(subset=["date"])
    if values.empty:
        return [], []

    def displayed_volume(value: object) -> float:
        return volume_to_display(float(value), config)

    def diversion_percent(group: pd.DataFrame) -> float:
        gross = float(group["gross_runoff"].sum())
        diverted = float(group["first_flush_loss"].sum())
        return diverted / gross * 100.0 if gross > 0.0 else 0.0

    event_rows: list[dict[str, object]] = []
    event_values = values.dropna(subset=["event_id"])
    for event_id, group in event_values.groupby("event_id", sort=False):
        normalized_id: object = event_id
        try:
            numeric_id = float(event_id)
            normalized_id = int(numeric_id) if numeric_id.is_integer() else numeric_id
        except (TypeError, ValueError):
            normalized_id = str(event_id)
        event_rows.append(
            {
                "event_id": normalized_id,
                "start": group["date"].min().isoformat(),
                "end": group["date"].max().isoformat(),
                "wet_timesteps": len(group),
                "gross_runoff": displayed_volume(group["gross_runoff"].sum()),
                "first_flush_loss": displayed_volume(group["first_flush_loss"].sum()),
                "net_collected": displayed_volume(group["net_collected"].sum()),
                "diversion_percent": diversion_percent(group),
            }
        )

    yearly_rows: list[dict[str, object]] = []
    for year, group in values.groupby(values["date"].dt.year, sort=True):
        yearly_rows.append(
            {
                "year": int(year),
                "event_count": int(group["event_start"].sum()),
                "gross_runoff": displayed_volume(group["gross_runoff"].sum()),
                "first_flush_loss": displayed_volume(group["first_flush_loss"].sum()),
                "net_collected": displayed_volume(group["net_collected"].sum()),
                "diversion_percent": diversion_percent(group),
            }
        )
    return event_rows, yearly_rows


def report_demand_summary(
    results_df: pd.DataFrame, config: ProjectConfig
) -> tuple[list[dict[str, object]], float]:
    if results_df.empty or not {"Date", "DemandGallons"}.issubset(results_df.columns):
        return (
            [
                {
                    "month": MONTH_LABELS[key],
                    "demand_per_day": 0.0,
                    "demand_per_month": 0.0,
                }
                for key in MONTH_KEYS
            ],
            0.0,
        )

    demand = results_df[["Date", "DemandGallons"]].copy()
    demand["Date"] = pd.to_datetime(demand["Date"], errors="coerce")
    demand["DemandGallons"] = pd.to_numeric(
        demand["DemandGallons"], errors="coerce"
    ).fillna(0.0)
    demand = demand.dropna(subset=["Date"])
    monthly_average = demand.groupby(demand["Date"].dt.month)["DemandGallons"].mean()
    monthly_totals = demand.groupby(
        [demand["Date"].dt.year, demand["Date"].dt.month]
    )["DemandGallons"].sum()
    mean_monthly_totals = monthly_totals.groupby(level=1).mean()
    annual_average = demand.groupby(demand["Date"].dt.year)["DemandGallons"].sum().mean()
    rows = [
        {
            "month": MONTH_LABELS[key],
            "demand_per_day": volume_to_display(
                float(monthly_average.get(index, 0.0)), config
            ),
            "demand_per_month": volume_to_display(
                float(mean_monthly_totals.get(index, 0.0)), config
            ),
        }
        for index, key in enumerate(MONTH_KEYS, start=1)
    ]
    return rows, volume_to_display(float(annual_average), config)


def yearly_demand_reliability(
    results_df: pd.DataFrame,
) -> list[dict[str, float | int]]:
    if results_df.empty or not {"Date", "DemandMet"}.issubset(results_df.columns):
        return []
    values = results_df[["Date", "DemandMet"]].copy()
    values["Date"] = pd.to_datetime(values["Date"], errors="coerce")
    values = values.dropna(subset=["Date"])
    values["DemandMet"] = values["DemandMet"].fillna(False).astype(bool)
    rows: list[dict[str, float | int]] = []
    for year, group in values.groupby(values["Date"].dt.year, sort=True):
        total_days = len(group)
        met_days = int(group["DemandMet"].sum())
        met_percent = (met_days / total_days) * 100.0 if total_days else 0.0
        rows.append(
            {
                "year": int(year),
                "total_days": total_days,
                "met_days": met_days,
                "unmet_days": total_days - met_days,
                "met_percent": met_percent,
                "unmet_percent": 100.0 - met_percent,
            }
        )
    return rows


def report_average_annual_precipitation(
    rainfall_df: pd.DataFrame, config: ProjectConfig
) -> float:
    if rainfall_df.empty or not {"Date", "Precipitation"}.issubset(rainfall_df.columns):
        return 0.0
    rainfall = rainfall_df[["Date", "Precipitation"]].copy()
    rainfall["Date"] = pd.to_datetime(rainfall["Date"], errors="coerce")
    rainfall["Precipitation"] = pd.to_numeric(
        rainfall["Precipitation"], errors="coerce"
    ).fillna(0.0)
    rainfall = rainfall.dropna(subset=["Date"])
    annual_average = rainfall.groupby(rainfall["Date"].dt.year)["Precipitation"].sum().mean()
    return precip_to_display(float(annual_average), config)


def report_tank_level_distribution(
    results_df: pd.DataFrame, config: ProjectConfig, bin_count: int = 6
) -> list[dict[str, float | int]]:
    if results_df.empty or "WaterInTankGallons" not in results_df.columns or bin_count <= 0:
        return []
    levels = [
        volume_to_display(max(float(value), 0.0), config)
        for value in pd.to_numeric(
            results_df["WaterInTankGallons"], errors="coerce"
        ).fillna(0.0)
    ]
    selected_capacity = volume_to_display(config.selected_tank_size_gal, config)
    upper = max(selected_capacity, max(levels, default=0.0), 1.0)
    bin_width = upper / bin_count
    counts = [0] * bin_count
    for level in levels:
        index = min(max(int(level / bin_width), 0), bin_count - 1)
        counts[index] += 1
    return [
        {"low": index * bin_width, "high": (index + 1) * bin_width, "count": count}
        for index, count in enumerate(counts)
    ]


def tank_volume_capacity_label(
    current_gallons: float, capacity_gallons: float, config: ProjectConfig
) -> str:
    """Format the animated tank's current volume and capacity in project units."""
    current = volume_to_display(max(float(current_gallons), 0.0), config)
    capacity = volume_to_display(max(float(capacity_gallons), 0.0), config)
    unit = volume_unit(config)
    return f"{current:,.0f} {unit} / {capacity:,.0f} {unit}"
