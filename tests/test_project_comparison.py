from __future__ import annotations

from dataclasses import replace
from html.parser import HTMLParser
from pathlib import Path

import pandas as pd
from pypdf import PdfReader
import pytest

from rainwater_app.defaults import default_project_config
from rainwater_app.models import METRIC_UNIT_SYSTEM
from rainwater_app.project_comparison import (
    ProjectComparisonRenderingService,
    ProjectComparisonSelection,
    ProjectComparisonService,
)


class FakeComparisonStore:
    def __init__(self, projects: dict[str, tuple[object, pd.DataFrame, pd.DataFrame, pd.DataFrame]]) -> None:
        self.projects = projects
        self.load_calls: list[str] = []

    def list_projects(self) -> list[str]:
        return list(self.projects)

    def load_project_with_analysis(self, name: str):
        self.load_calls.append(name)
        return self.projects[name]


def analyzed_project(
    name: str,
    *,
    reliability: float,
    tank_gallons: float,
    metric: bool = False,
) -> tuple[object, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    config = default_project_config()
    config.name = name
    config.selected_tank_size_gal = tank_gallons
    config.rainfall_source_label = f"Station for {name}"
    if metric:
        config.unit_system = METRIC_UNIT_SYSTEM
    dates = pd.to_datetime(["2023-01-01", "2023-01-02", "2024-01-01", "2024-01-02"])
    rainfall = pd.DataFrame({"Date": dates, "Precipitation": [1.0, 0.0, 2.0, 0.0]})
    curve = pd.DataFrame(
        {"TankSizeGallons": [tank_gallons], "ReliabilityPercent": [reliability]}
    )
    results = pd.DataFrame(
        {
            "Date": dates,
            "ReliabilityPercent": [reliability] * 4,
            "DemandGallons": [100.0, 200.0, 300.0, 500.0],
            "RainwaterSuppliedGallons": [80.0, 150.0, 250.0, 400.0],
            "MainsMakeupGallons": [20.0, 50.0, 50.0, 100.0],
            "SystemUnmetDemandGallons": [0.0, 0.0, 0.0, 0.0],
            "OverflowGallons": [10.0, 20.0, 30.0, 40.0],
        }
    )
    return config, rainfall, curve, results


def comparison_model(*, mixed_units: bool = False):
    store = FakeComparisonStore(
        {
            "Alpha & North": analyzed_project(
                "Alpha & North", reliability=80.0, tank_gallons=1_000.0
            ),
            "Beta <South>": analyzed_project(
                "Beta <South>", reliability=92.5, tank_gallons=2_000.0, metric=mixed_units
            ),
        }
    )
    return ProjectComparisonService(store).build(["Alpha & North", "Beta <South>"]), store


def test_service_builds_annualized_read_only_comparison() -> None:
    model, store = comparison_model()

    assert store.load_calls == ["Alpha & North", "Beta <South>"]
    assert model.display_volume_unit == "gal"
    assert model.rows[0].analysis_years == 2
    assert model.rows[0].annual_demand_gallons == pytest.approx(550.0)
    assert model.rows[0].annual_rainwater_supply_gallons == pytest.approx(440.0)
    assert model.rows[0].annual_municipal_makeup_gallons == pytest.approx(110.0)
    assert model.rows[0].annual_overflow_gallons == pytest.approx(50.0)
    assert model.rows[0].record_start == "2023-01-01"
    assert model.rows[0].record_end == "2024-01-02"


def test_service_rejects_too_few_unknown_and_unanalyzed_projects() -> None:
    project = analyzed_project("Alpha", reliability=80.0, tank_gallons=1_000.0)
    store = FakeComparisonStore({"Alpha": project, "Empty": (*project[:3], pd.DataFrame())})
    service = ProjectComparisonService(store)

    with pytest.raises(ValueError, match="at least two"):
        service.build(["Alpha"])
    with pytest.raises(ValueError, match="not found"):
        service.build(["Alpha", "Missing"])
    with pytest.raises(ValueError, match="no usable saved analysis"):
        service.build(["Alpha", "Empty"])


def test_mixed_units_are_explicitly_normalized_to_gallons() -> None:
    model, _store = comparison_model(mixed_units=True)

    assert model.has_mixed_unit_systems
    assert model.display_volume_unit == "gal"
    assert model.to_dict()["has_mixed_unit_systems"] is True


def test_all_metric_projects_render_in_liters() -> None:
    model, _store = comparison_model()
    metric_rows = tuple(replace(row, unit_system=METRIC_UNIT_SYSTEM) for row in model.rows)
    metric_model = replace(model, rows=metric_rows)

    assert metric_model.display_volume_unit == "L"
    assert metric_model.display_volume(1.0) == pytest.approx(3.78541)


def test_same_project_name_from_different_databases_is_disambiguated() -> None:
    first = FakeComparisonStore(
        {"Shared": analyzed_project("Shared", reliability=80.0, tank_gallons=1_000.0)}
    )
    second = FakeComparisonStore(
        {"Shared": analyzed_project("Shared", reliability=90.0, tank_gallons=2_000.0)}
    )
    model = ProjectComparisonService.build_selections(
        [
            ProjectComparisonSelection("first.db", "Shared", first),
            ProjectComparisonSelection("second.db", "Shared", second),
        ]
    )

    html = ProjectComparisonRenderingService().html(model)

    assert [row.source_name for row in model.rows] == ["first.db", "second.db"]
    assert "Shared (first.db)" in html
    assert "Shared (second.db)" in html


def test_different_rainfall_periods_remain_project_specific() -> None:
    first_project = analyzed_project("First", reliability=80.0, tank_gallons=1_000.0)
    second_config, second_rainfall, second_curve, second_results = analyzed_project(
        "Second", reliability=90.0, tank_gallons=2_000.0
    )
    shifted_dates = pd.to_datetime(
        ["2020-05-01", "2020-05-02", "2021-05-01", "2021-05-02"]
    )
    second_rainfall = second_rainfall.assign(Date=shifted_dates)
    second_results = second_results.assign(Date=shifted_dates)
    store = FakeComparisonStore(
        {
            "First": first_project,
            "Second": (second_config, second_rainfall, second_curve, second_results),
        }
    )

    model = ProjectComparisonService(store).build(["First", "Second"])

    assert (model.rows[0].record_start, model.rows[0].record_end) == (
        "2023-01-01",
        "2024-01-02",
    )
    assert (model.rows[1].record_start, model.rows[1].record_end) == (
        "2020-05-01",
        "2021-05-02",
    )


class TagCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags: list[tuple[str, dict[str, str]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append((tag, {key: value or "" for key, value in attrs}))


def test_html_renderer_escapes_names_and_includes_accessible_comparison() -> None:
    model, _store = comparison_model(mixed_units=True)
    html = ProjectComparisonRenderingService().html(model)
    parser = TagCollector()
    parser.feed(html)

    assert "Alpha &amp; North" in html
    assert "Beta &lt;South&gt;" in html
    assert "Mixed unit systems selected" in html
    assert any(tag == "main" for tag, _attrs in parser.tags)
    assert any(tag == "table" for tag, _attrs in parser.tags)
    assert any(
        tag == "svg" and attrs.get("role") == "img" and attrs.get("aria-labelledby")
        for tag, attrs in parser.tags
    )


def test_rendering_service_writes_valid_html_and_pdf(tmp_path: Path) -> None:
    model, _store = comparison_model()
    service = ProjectComparisonRenderingService()
    html_path = tmp_path / "comparison.html"
    pdf_path = tmp_path / "comparison.pdf"

    service.write_html(html_path, model)
    service.pdf(pdf_path, model)

    assert html_path.read_text(encoding="utf-8").startswith("<!doctype html>")
    reader = PdfReader(pdf_path)
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert "Multi-project comparison" in text
    assert "Alpha & North" in text
    assert "Average annual performance" in text
