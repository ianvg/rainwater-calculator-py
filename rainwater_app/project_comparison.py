"""Read-only multi-project comparison models, construction, and rendering."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from html import escape
import math
import os
from pathlib import Path
import tempfile
from typing import Protocol, Sequence

import pandas as pd

from .analysis_state import analysis_input_signature
from .financial_service import FinancialAnalysisService
from .models import METRIC_UNIT_SYSTEM, ProjectConfig, normalize_unit_system
from .number_formatting import format_number
from .pdf_rendering import _write_pdf_with_pypdf
from .reporting import atomic_write_text, pdf_escape, wrap_pdf_text
from .units import LITERS_PER_GALLON, MM_PER_INCH, SQFT_PER_SQM


COMPARISON_SCHEMA_VERSION = 1
_REQUIRED_RESULT_COLUMNS = {"ReliabilityPercent", "DemandGallons"}


class ComparisonStore(Protocol):
    def list_projects(self) -> list[str]: ...

    def load_project_with_analysis(
        self, name: str
    ) -> tuple[ProjectConfig, pd.DataFrame, pd.DataFrame, pd.DataFrame]: ...


@dataclass(frozen=True)
class ProjectComparisonSelection:
    source_name: str
    project_name: str
    store: ComparisonStore


@dataclass(frozen=True)
class ProjectComparisonRow:
    source_name: str
    project_name: str
    unit_system: str
    location: str
    rainfall_source: str
    record_start: str
    record_end: str
    analysis_years: int
    analysis_status: str
    collection_area_sqft: float
    weighted_runoff_coefficient: float
    average_annual_precipitation_inches: float
    selected_tank_gallons: float
    reliability_percent: float
    annual_demand_gallons: float
    annual_rainwater_supply_gallons: float
    annual_municipal_makeup_gallons: float
    annual_system_unmet_gallons: float
    annual_overflow_gallons: float
    annual_first_flush_gallons: float
    annual_treatment_loss_gallons: float
    currency: str
    installed_cost: float
    net_annual_savings: float | None
    simple_payback_years: float | None
    review_conditions: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.source_name.strip():
            raise ValueError("Comparison source names cannot be blank.")
        if not self.project_name.strip():
            raise ValueError("Comparison project names cannot be blank.")
        if self.analysis_years < 1:
            raise ValueError(f"Project '{self.project_name}' has no analyzed calendar year.")
        numeric_values = (
            self.collection_area_sqft,
            self.weighted_runoff_coefficient,
            self.average_annual_precipitation_inches,
            self.selected_tank_gallons,
            self.reliability_percent,
            self.annual_demand_gallons,
            self.annual_rainwater_supply_gallons,
            self.annual_municipal_makeup_gallons,
            self.annual_system_unmet_gallons,
            self.annual_overflow_gallons,
            self.annual_first_flush_gallons,
            self.annual_treatment_loss_gallons,
            self.installed_cost,
        )
        if not all(math.isfinite(value) and value >= 0.0 for value in numeric_values):
            raise ValueError(f"Project '{self.project_name}' contains invalid comparison values.")
        if self.reliability_percent > 100.0:
            raise ValueError(f"Project '{self.project_name}' has reliability above 100%.")
        if self.weighted_runoff_coefficient > 1.0:
            raise ValueError(f"Project '{self.project_name}' has an invalid runoff coefficient.")
        for value in (self.net_annual_savings, self.simple_payback_years):
            if value is not None and not math.isfinite(value):
                raise ValueError(f"Project '{self.project_name}' has invalid financial results.")


@dataclass(frozen=True)
class ProjectComparisonModel:
    rows: tuple[ProjectComparisonRow, ...]
    title: str = "Multi-project comparison"
    schema_version: int = COMPARISON_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != COMPARISON_SCHEMA_VERSION:
            raise ValueError(f"Unsupported comparison schema version {self.schema_version}.")
        if len(self.rows) < 2:
            raise ValueError("Select at least two analyzed projects to compare.")
        identities = [
            (row.source_name.casefold(), row.project_name.casefold()) for row in self.rows
        ]
        if len(identities) != len(set(identities)):
            raise ValueError("Each source project can appear only once in a comparison.")
        if not self.title.strip():
            raise ValueError("Comparison title cannot be blank.")

    @property
    def display_volume_unit(self) -> str:
        return (
            "L"
            if all(
                normalize_unit_system(row.unit_system) == METRIC_UNIT_SYSTEM
                for row in self.rows
            )
            else "gal"
        )

    @property
    def has_mixed_unit_systems(self) -> bool:
        return len({normalize_unit_system(row.unit_system) for row in self.rows}) > 1

    def display_volume(self, gallons: float) -> float:
        return gallons * LITERS_PER_GALLON if self.display_volume_unit == "L" else gallons

    @property
    def display_area_unit(self) -> str:
        return "m^2" if self.display_volume_unit == "L" else "sq ft"

    @property
    def display_precipitation_unit(self) -> str:
        return "mm" if self.display_volume_unit == "L" else "in"

    def display_area(self, square_feet: float) -> float:
        return square_feet / SQFT_PER_SQM if self.display_area_unit == "m^2" else square_feet

    def display_precipitation(self, inches: float) -> float:
        return inches * MM_PER_INCH if self.display_precipitation_unit == "mm" else inches

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "title": self.title,
            "display_volume_unit": self.display_volume_unit,
            "has_mixed_unit_systems": self.has_mixed_unit_systems,
            "rows": [asdict(row) for row in self.rows],
        }


def _date_series(frame: pd.DataFrame) -> pd.Series | None:
    if frame.empty or "Date" not in frame:
        return None
    dates = pd.to_datetime(frame["Date"], errors="coerce")
    return dates if dates.notna().any() else None


def _analysis_years(results: pd.DataFrame) -> int:
    dates = _date_series(results)
    return int(dates.dropna().dt.year.nunique()) if dates is not None else 1


def _annual_average(results: pd.DataFrame, column: str) -> float:
    if column not in results:
        return 0.0
    values = pd.to_numeric(results[column], errors="coerce").fillna(0.0).clip(lower=0.0)
    dates = _date_series(results)
    if dates is None:
        return float(values.sum())
    valid = dates.notna()
    if not valid.any():
        return float(values.sum())
    yearly = values.loc[valid].groupby(dates.loc[valid].dt.year).sum()
    return float(yearly.mean()) if not yearly.empty else 0.0


def _first_annual_average(results: pd.DataFrame, columns: Sequence[str]) -> float:
    return next((_annual_average(results, column) for column in columns if column in results), 0.0)


def _record_range(rainfall: pd.DataFrame, results: pd.DataFrame) -> tuple[str, str]:
    dates = _date_series(rainfall)
    if dates is None:
        dates = _date_series(results)
    if dates is None:
        return "Not available", "Not available"
    valid = dates.dropna()
    if valid.empty:
        return "Not available", "Not available"
    return valid.min().date().isoformat(), valid.max().date().isoformat()


def _average_annual_precipitation(rainfall: pd.DataFrame) -> float:
    if rainfall.empty or not {"Date", "Precipitation"}.issubset(rainfall.columns):
        return 0.0
    dates = pd.to_datetime(rainfall["Date"], errors="coerce")
    values = pd.to_numeric(rainfall["Precipitation"], errors="coerce").fillna(0.0)
    valid = dates.notna()
    annual = values.loc[valid].groupby(dates.loc[valid].dt.year).sum()
    return float(annual.mean()) if not annual.empty else 0.0


def _project_location(config: ProjectConfig) -> str:
    parts = (
        config.street_address,
        config.city,
        config.state_or_province,
        config.postal_code,
        config.country_code,
    )
    return ", ".join(str(part).strip() for part in parts if str(part).strip()) or "Not specified"


def _comparison_row(
    config: ProjectConfig,
    rainfall: pd.DataFrame,
    results: pd.DataFrame,
    *,
    source_name: str,
) -> ProjectComparisonRow:
    missing = _REQUIRED_RESULT_COLUMNS.difference(results.columns)
    if results.empty or missing:
        detail = ", ".join(sorted(missing)) if missing else "saved result rows"
        raise ValueError(
            f"Project '{config.name}' has no usable saved analysis ({detail} missing)."
        )
    reliability_values = pd.to_numeric(results["ReliabilityPercent"], errors="coerce").dropna()
    if reliability_values.empty:
        raise ValueError(f"Project '{config.name}' has no saved reliability result.")
    demand = _annual_average(results, "DemandGallons")
    rainwater_supply = _first_annual_average(results, ("RainwaterSuppliedGallons",))
    if "RainwaterSuppliedGallons" not in results:
        rainwater_supply = max(demand - _annual_average(results, "UnmetDemandGallons"), 0.0)
    record_start, record_end = _record_range(rainfall, results)
    collection_area = sum(max(float(surface.area), 0.0) for surface in config.surfaces)
    weighted_runoff = (
        sum(
            max(float(surface.area), 0.0) * float(surface.runoff_coefficient)
            for surface in config.surfaces
        )
        / collection_area
        if collection_area > 0.0
        else 0.0
    )
    if config.analysis_input_signature:
        analysis_status = (
            "Current"
            if config.analysis_input_signature == analysis_input_signature(config, rainfall)
            else "Stale - project inputs changed"
        )
    else:
        analysis_status = "Not verifiable - signature unavailable"
    financial_service = FinancialAnalysisService(config)
    financial_configured = financial_service.is_configured()
    financial_result = None
    financial_error = ""
    try:
        financial_result = financial_service.calculate_for_annual_supply(rainwater_supply)
    except ValueError as exc:
        financial_error = str(exc)
    annual_overflow = _annual_average(results, "OverflowGallons")
    annual_treatment = _first_annual_average(
        results, ("TreatmentLossGallons", "FilterLossGallons")
    )
    review_conditions: list[str] = []
    if analysis_status != "Current":
        review_conditions.append(analysis_status)
    reliability = float(reliability_values.iloc[0])
    if reliability < float(config.recommendation_reliability_target_percent):
        review_conditions.append(
            f"Reliability is below the {config.recommendation_reliability_target_percent:.1f}% target."
        )
    throughput = rainwater_supply + annual_overflow + annual_treatment
    if throughput > 0.0 and annual_overflow / throughput > 0.25:
        review_conditions.append("Overflow exceeds 25% of simulated tank throughput.")
    if str(config.rainfall_data_type).casefold() == "unclassified":
        review_conditions.append("Rainfall data type is unclassified.")
    if not financial_configured:
        review_conditions.append("Financial rates and costs are not configured.")
    if financial_error:
        review_conditions.append(f"Financial comparison unavailable: {financial_error}")
    return ProjectComparisonRow(
        source_name=source_name,
        project_name=config.name,
        unit_system=normalize_unit_system(config.unit_system),
        location=_project_location(config),
        rainfall_source=str(config.rainfall_source_label or "Not specified"),
        record_start=record_start,
        record_end=record_end,
        analysis_years=_analysis_years(results),
        analysis_status=analysis_status,
        collection_area_sqft=collection_area,
        weighted_runoff_coefficient=weighted_runoff,
        average_annual_precipitation_inches=_average_annual_precipitation(rainfall),
        selected_tank_gallons=max(float(config.selected_tank_size_gal), 0.0),
        reliability_percent=reliability,
        annual_demand_gallons=demand,
        annual_rainwater_supply_gallons=rainwater_supply,
        annual_municipal_makeup_gallons=_first_annual_average(
            results, ("MunicipalMakeupGallons", "MainsMakeupGallons")
        ),
        annual_system_unmet_gallons=_annual_average(results, "SystemUnmetDemandGallons"),
        annual_overflow_gallons=annual_overflow,
        annual_first_flush_gallons=_annual_average(results, "FirstFlushLossGallons"),
        annual_treatment_loss_gallons=annual_treatment,
        currency=str(config.financial_parameters.currency or ""),
        installed_cost=max(float(config.financial_parameters.installed_cost), 0.0),
        net_annual_savings=(
            financial_result.net_annual_savings if financial_result is not None else None
        ),
        simple_payback_years=(
            financial_result.simple_payback_years if financial_result is not None else None
        ),
        review_conditions=tuple(review_conditions),
    )


@dataclass(frozen=True)
class ProjectComparisonService:
    store: ComparisonStore

    def build(
        self, project_names: Sequence[str], *, title: str = "Multi-project comparison"
    ) -> ProjectComparisonModel:
        names = [str(name).strip() for name in project_names if str(name).strip()]
        if len(names) < 2:
            raise ValueError("Select at least two analyzed projects to compare.")
        if len({name.casefold() for name in names}) != len(names):
            raise ValueError("Each project can appear only once in a comparison.")
        available = {name.casefold(): name for name in self.store.list_projects()}
        unknown = [name for name in names if name.casefold() not in available]
        if unknown:
            raise ValueError("Project not found: " + ", ".join(unknown))
        source_name = Path(getattr(self.store, "db_path", "Current database")).name
        selections = [
            ProjectComparisonSelection(
                source_name=source_name,
                project_name=available[requested_name.casefold()],
                store=self.store,
            )
            for requested_name in names
        ]
        return self.build_selections(selections, title=title)

    @staticmethod
    def build_selections(
        selections: Sequence[ProjectComparisonSelection],
        *,
        title: str = "Multi-project comparison",
    ) -> ProjectComparisonModel:
        if len(selections) < 2:
            raise ValueError("Select at least two analyzed projects to compare.")
        identities = [
            (selection.source_name.casefold(), selection.project_name.casefold())
            for selection in selections
        ]
        if len(identities) != len(set(identities)):
            raise ValueError("Each source project can appear only once in a comparison.")
        rows: list[ProjectComparisonRow] = []
        for selection in selections:
            available = {
                name.casefold(): name for name in selection.store.list_projects()
            }
            stored_name = available.get(selection.project_name.casefold())
            if stored_name is None:
                raise ValueError(
                    f"Project not found in {selection.source_name}: {selection.project_name}"
                )
            config, rainfall, _curve, results = (
                selection.store.load_project_with_analysis(stored_name)
            )
            rows.append(
                _comparison_row(
                    config, rainfall, results, source_name=selection.source_name
                )
            )
        return ProjectComparisonModel(rows=tuple(rows), title=title.strip())


def _volume(model: ProjectComparisonModel, gallons: float) -> str:
    return format_number(model.display_volume(gallons), max_decimal_places=0)


def _row_label(model: ProjectComparisonModel, row: ProjectComparisonRow) -> str:
    duplicate_name = sum(
        candidate.project_name.casefold() == row.project_name.casefold()
        for candidate in model.rows
    ) > 1
    return f"{row.project_name} ({row.source_name})" if duplicate_name else row.project_name


def render_comparison_html(model: ProjectComparisonModel) -> str:
    unit = model.display_volume_unit
    area_unit = model.display_area_unit
    precip_unit = model.display_precipitation_unit
    assumption_rows = "".join(
        "<tr>"
        f"<th scope=\"row\">{escape(row.project_name)}</th>"
        f"<td>{escape(row.source_name)}</td>"
        f"<td>{escape(row.unit_system)}</td>"
        f"<td>{escape(row.location)}</td>"
        f"<td>{escape(row.rainfall_source)}</td>"
        f"<td>{escape(row.record_start)} to {escape(row.record_end)}</td>"
        f"<td>{row.analysis_years}</td>"
        f"<td>{escape(row.analysis_status)}</td>"
        f"<td>{format_number(model.display_area(row.collection_area_sqft), max_decimal_places=0)}</td>"
        f"<td>{format_number(model.display_precipitation(row.average_annual_precipitation_inches), max_decimal_places=1)}</td>"
        f"<td>{format_number(row.weighted_runoff_coefficient, max_decimal_places=2)}</td>"
        "</tr>"
        for row in model.rows
    )
    performance_rows = "".join(
        "<tr>"
        f"<th scope=\"row\">{escape(row.project_name)}</th>"
        f"<td>{_volume(model, row.selected_tank_gallons)}</td>"
        f"<td>{format_number(row.reliability_percent, max_decimal_places=1)}%</td>"
        f"<td>{_volume(model, row.annual_demand_gallons)}</td>"
        f"<td>{_volume(model, row.annual_rainwater_supply_gallons)}</td>"
        f"<td>{_volume(model, row.annual_municipal_makeup_gallons)}</td>"
        f"<td>{_volume(model, row.annual_system_unmet_gallons)}</td>"
        f"<td>{_volume(model, row.annual_overflow_gallons)}</td>"
        f"<td>{_volume(model, row.annual_first_flush_gallons)}</td>"
        f"<td>{_volume(model, row.annual_treatment_loss_gallons)}</td>"
        "</tr>"
        for row in model.rows
    )
    financial_rows = "".join(
        "<tr>"
        f"<th scope=\"row\">{escape(row.project_name)}</th>"
        f"<td>{escape(row.currency) or '--'} {format_number(row.installed_cost, max_decimal_places=0)}</td>"
        f"<td>{'--' if row.net_annual_savings is None else escape(row.currency) + ' ' + format_number(row.net_annual_savings, max_decimal_places=0)}</td>"
        f"<td>{'--' if row.simple_payback_years is None else format_number(row.simple_payback_years, max_decimal_places=1) + ' years'}</td>"
        "</tr>"
        for row in model.rows
    )
    review_rows = "".join(
        f"<section class=\"review-card\"><h3>{escape(row.project_name)}</h3><ul>"
        + "".join(f"<li>{escape(condition)}</li>" for condition in row.review_conditions)
        + ("<li>No comparison review conditions.</li>" if not row.review_conditions else "")
        + "</ul></section>"
        for row in model.rows
    )
    bar_width = 420.0
    chart_rows: list[str] = []
    for index, row in enumerate(model.rows):
        y = 34 + index * 42
        width = bar_width * row.reliability_percent / 100.0
        chart_rows.append(
            f'<text x="0" y="{y}" class="chart-label">{escape(_row_label(model, row))}</text>'
            f'<rect x="170" y="{y - 17}" width="{width:.2f}" height="22" rx="3" />'
            f'<text x="{180 + width:.2f}" y="{y}" class="chart-value">'
            f'{format_number(row.reliability_percent, max_decimal_places=1)}%</text>'
        )
    chart_height = 58 + len(model.rows) * 42
    mixed_note = (
        "<p class=\"notice\"><strong>Unit normalization:</strong> Mixed unit systems selected; "
        "all comparison volumes are shown in gallons.</p>"
        if model.has_mixed_unit_systems
        else ""
    )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(model.title)}</title>
<style>
:root {{ color-scheme: light; font-family: Arial, sans-serif; color: #17212b; }}
body {{ margin: 0; background: #eef3f6; }}
main {{ max-width: 1180px; margin: 24px auto; background: white; padding: 32px; box-shadow: 0 2px 12px #0002; }}
h1, h2 {{ color: #174f69; }}
.notice {{ background: #fff5d6; border-left: 4px solid #d29b14; padding: 12px; }}
.table-wrap {{ overflow-x: auto; }}
table {{ border-collapse: collapse; width: 100%; font-size: 0.88rem; }}
caption {{ text-align: left; font-weight: bold; margin-bottom: 8px; }}
th, td {{ border: 1px solid #aab7c0; padding: 7px; text-align: right; white-space: nowrap; }}
thead th, tbody th {{ background: #e7f1f5; color: #153f52; }}
thead th:first-child, tbody th {{ text-align: left; }}
svg {{ width: 100%; min-width: 650px; height: auto; }}
svg rect {{ fill: #277da1; }}
.chart-label {{ font-size: 13px; text-anchor: start; }}
.chart-value {{ font-size: 13px; font-weight: bold; }}
.method {{ color: #4d5961; font-size: 0.9rem; }}
.review-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 12px; }}
.review-card {{ border: 1px solid #c7d2d9; border-radius: 5px; padding: 0 14px; }}
@media print {{ body {{ background: white; }} main {{ margin: 0; box-shadow: none; padding: 0; }} }}
</style>
</head>
<body><main>
<h1>{escape(model.title)}</h1>
<p>Read-only comparison of {len(model.rows)} saved project analyses.</p>
{mixed_note}
<section aria-labelledby="reliability-heading">
<h2 id="reliability-heading">Selected-tank reliability</h2>
<div class="table-wrap">
<svg viewBox="0 0 700 {chart_height}" role="img" aria-labelledby="chart-title chart-desc">
<title id="chart-title">Selected-tank reliability by project</title>
<desc id="chart-desc">Horizontal bars compare reliability percentages from zero to one hundred.</desc>
{''.join(chart_rows)}
</svg>
</div>
</section>
<section aria-labelledby="comparison-heading">
<h2 id="comparison-heading">Project assumptions and provenance</h2>
<div class="table-wrap"><table>
<caption>Saved inputs and analysis provenance</caption>
<thead><tr><th scope="col">Project</th><th scope="col">Source database</th><th scope="col">Project units</th><th scope="col">Location</th><th scope="col">Rainfall source</th><th scope="col">Record</th><th scope="col">Years</th><th scope="col">Analysis status</th><th scope="col">Collection area ({area_unit})</th><th scope="col">Mean annual precipitation ({precip_unit})</th><th scope="col">Area-weighted runoff coefficient</th></tr></thead>
<tbody>{assumption_rows}</tbody>
</table></div>
</section>
<section aria-labelledby="performance-heading">
<h2 id="performance-heading">Selected-tank performance</h2>
<div class="table-wrap"><table>
<caption>Annual calendar-year averages in {unit}/year unless otherwise noted</caption>
<thead><tr><th scope="col">Project</th><th scope="col">Tank ({unit})</th><th scope="col">Reliability</th><th scope="col">Demand</th><th scope="col">Rainwater supply</th><th scope="col">Municipal</th><th scope="col">System unmet</th><th scope="col">Overflow</th><th scope="col">First flush</th><th scope="col">Treatment loss</th></tr></thead>
<tbody>{performance_rows}</tbody>
</table></div>
</section>
<section aria-labelledby="financial-heading">
<h2 id="financial-heading">Financial comparison</h2>
<div class="table-wrap"><table>
<caption>Project-specific currencies and saved financial assumptions</caption>
<thead><tr><th scope="col">Project</th><th scope="col">Installed cost</th><th scope="col">Net annual savings</th><th scope="col">Simple payback</th></tr></thead>
<tbody>{financial_rows}</tbody>
</table></div>
</section>
<section aria-labelledby="review-heading"><h2 id="review-heading">Review conditions</h2><div class="review-grid">{review_rows}</div></section>
<p class="method">Annual volumes are calendar-year averages from each project's saved result rows. This report does not rerun analyses or modify source projects.</p>
</main></body></html>
"""


def render_comparison_pdf(pdf_path: Path, model: ProjectComparisonModel) -> None:
    unit = model.display_volume_unit
    pages: list[list[str]] = [[]]
    y = 744.0

    def text(x: float, y_pos: float, value: object, *, size: int = 9, bold: bool = False) -> None:
        font = "F2" if bold else "F1"
        pages[-1].append(
            f"BT /{font} {size} Tf 1 0 0 1 {x:.2f} {y_pos:.2f} Tm ({pdf_escape(value)}) Tj ET"
        )

    def line(y_pos: float) -> None:
        pages[-1].append(f"0.5 w 48 {y_pos:.2f} m 564 {y_pos:.2f} l S")

    def new_page() -> None:
        nonlocal y
        pages.append([])
        y = 744.0

    def heading(value: str) -> None:
        nonlocal y
        if y < 100:
            new_page()
        text(48, y, value, size=14, bold=True)
        y -= 16
        line(y)
        y -= 18

    text(48, y, model.title, size=20, bold=True)
    y -= 30
    text(48, y, f"Read-only comparison of {len(model.rows)} saved project analyses.")
    y -= 24
    if model.has_mixed_unit_systems:
        text(48, y, "Mixed unit systems selected; all comparison volumes are shown in gallons.", bold=True)
        y -= 24

    heading("Selected-tank overview")
    overview_headers = ((48, "Project"), (230, "Record"), (390, f"Tank ({unit})"), (492, "Reliability"))
    for x, label in overview_headers:
        text(x, y, label, size=8, bold=True)
    y -= 13
    line(y)
    y -= 14
    for row in model.rows:
        if y < 70:
            new_page()
        text(48, y, _row_label(model, row)[:28], size=8)
        text(230, y, f"{row.record_start} to {row.record_end}", size=8)
        text(410, y, _volume(model, row.selected_tank_gallons), size=8)
        text(510, y, f"{format_number(row.reliability_percent, max_decimal_places=1)}%", size=8)
        y -= 18

    y -= 12
    heading("Project assumptions and provenance")
    for row in model.rows:
        if y < 118:
            new_page()
        text(48, y, _row_label(model, row), size=9, bold=True)
        y -= 14
        details = (
            f"Source: {row.source_name}; location: {row.location}; rainfall: "
            f"{row.rainfall_source}; status: {row.analysis_status}."
        )
        for detail_line in wrap_pdf_text(details, 94):
            text(58, y, detail_line, size=8)
            y -= 11
        text(
            58,
            y,
            f"Collection area: {format_number(model.display_area(row.collection_area_sqft), max_decimal_places=0)} "
            f"{model.display_area_unit}; mean annual precipitation: "
            f"{format_number(model.display_precipitation(row.average_annual_precipitation_inches), max_decimal_places=1)} "
            f"{model.display_precipitation_unit}; weighted runoff coefficient: "
            f"{format_number(row.weighted_runoff_coefficient, max_decimal_places=2)}.",
            size=8,
        )
        y -= 20

    y -= 6
    heading(f"Average annual performance ({unit}/year)")
    performance_headers = (
        (48, "Project"), (220, "Demand"), (285, "Supply"), (350, "Municipal"),
        (425, "Unmet"), (490, "Overflow"),
    )
    for x, label in performance_headers:
        text(x, y, label, size=8, bold=True)
    y -= 13
    line(y)
    y -= 14
    for row in model.rows:
        if y < 70:
            new_page()
        values = (
            _row_label(model, row)[:26],
            _volume(model, row.annual_demand_gallons),
            _volume(model, row.annual_rainwater_supply_gallons),
            _volume(model, row.annual_municipal_makeup_gallons),
            _volume(model, row.annual_system_unmet_gallons),
            _volume(model, row.annual_overflow_gallons),
        )
        for (x, _label), value in zip(performance_headers, values):
            text(x, y, value, size=8)
        y -= 18

    y -= 12
    heading(f"Annual losses ({unit}/year)")
    loss_headers = (
        (48, "Project"), (300, "First flush"), (420, "Treatment loss")
    )
    for x, label in loss_headers:
        text(x, y, label, size=8, bold=True)
    y -= 13
    line(y)
    y -= 14
    for row in model.rows:
        if y < 70:
            new_page()
        text(48, y, _row_label(model, row)[:36], size=8)
        text(300, y, _volume(model, row.annual_first_flush_gallons), size=8)
        text(420, y, _volume(model, row.annual_treatment_loss_gallons), size=8)
        y -= 18

    y -= 12
    heading("Financial comparison")
    for row in model.rows:
        if y < 82:
            new_page()
        payback = (
            "--"
            if row.simple_payback_years is None
            else f"{format_number(row.simple_payback_years, max_decimal_places=1)} years"
        )
        savings = (
            "--"
            if row.net_annual_savings is None
            else f"{row.currency} {format_number(row.net_annual_savings, max_decimal_places=0)}/year"
        )
        text(48, y, _row_label(model, row)[:32], size=8, bold=True)
        text(
            250,
            y,
            f"Installed: {row.currency} {format_number(row.installed_cost, max_decimal_places=0)}",
            size=8,
        )
        text(390, y, f"Net savings: {savings}; payback: {payback}", size=8)
        y -= 18

    y -= 12
    heading("Review conditions")
    for row in model.rows:
        if y < 90:
            new_page()
        text(48, y, _row_label(model, row), size=9, bold=True)
        y -= 14
        conditions = row.review_conditions or ("No comparison review conditions.",)
        for condition in conditions:
            for condition_line in wrap_pdf_text(f"- {condition}", 90):
                if y < 60:
                    new_page()
                text(58, y, condition_line, size=8)
                y -= 11
        y -= 6

    y -= 16
    heading("Method")
    method = (
        "Annual volumes are calendar-year averages from each project's saved result rows. "
        "The comparison uses the saved selected-tank analysis and does not rerun analyses "
        "or modify source projects."
    )
    for paragraph_line in wrap_pdf_text(method, 92):
        text(48, y, paragraph_line, size=9)
        y -= 13
    _write_pdf_with_pypdf(pdf_path, pages)


@dataclass(frozen=True)
class ProjectComparisonRenderingService:
    def html(self, model: ProjectComparisonModel) -> str:
        return render_comparison_html(model)

    def write_html(self, path: Path, model: ProjectComparisonModel) -> None:
        atomic_write_text(path, self.html(model))

    def pdf(self, path: Path, model: ProjectComparisonModel) -> None:
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                prefix=f".{path.name}.", suffix=".tmp.pdf", dir=path.parent, delete=False
            ) as handle:
                temporary = Path(handle.name)
            render_comparison_pdf(temporary, model)
            if temporary.stat().st_size < 5 or temporary.read_bytes()[:5] != b"%PDF-":
                raise ValueError("Generated comparison is not a valid PDF artifact.")
            os.replace(temporary, path)
            temporary = None
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
