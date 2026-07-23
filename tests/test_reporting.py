import math

import pytest
import pandas as pd
from pypdf import PdfReader

import rainwater_app.reporting as reporting
from rainwater_app.report_service import ReportRenderingService
from rainwater_app.defaults import default_project_config
from rainwater_app.reporting import (
    REPORT_SCHEMA_VERSION,
    ReportModel,
    ReportValidationError,
    atomic_write_text,
    report_average_annual_rainfall_volumes,
    report_first_flush_summaries,
)


def _minimal_report() -> dict[str, object]:
    return {
        "metadata": {"project_name": "Test"},
        "area_unit": "sq ft",
        "volume_unit": "gal",
        "precipitation_unit": "in",
        "surfaces": [],
        "monthly_demand": [
            {"month": str(index), "demand_per_day": 0.0, "demand_per_month": 0.0}
            for index in range(12)
        ],
        "curve": [{"tank_size": 1000.0, "reliability": 80.0}],
        "selected_tank_size": 1000.0,
        "selected_reliability": 80.0,
    }


def _renderable_report() -> dict[str, object]:
    report = _minimal_report()
    report.update(
        metadata={
            "client_name": "Client",
            "date": "2026-07-21",
            "location": "Test location",
            "project_name": "Test",
            "author_name": "",
            "end_uses": "Testing",
        },
        average_annual_precipitation=40.0,
        precipitation_basis="Rain only",
        total_annual_demand=0.0,
        yearly_reliability=[],
        tank_level_distribution=[],
    )
    return report


def test_report_model_normalizes_legacy_payload_and_is_versioned() -> None:
    model = ReportModel.from_payload(_minimal_report())

    assert model.schema_version == REPORT_SCHEMA_VERSION
    assert model["schema_version"] == REPORT_SCHEMA_VERSION
    assert model["recommendations"] == []
    assert all(model["report_sections"].values())
    assert model.to_dict()["metadata"] == {"project_name": "Test"}


def test_report_rendering_service_renders_validated_html_and_latex() -> None:
    service = ReportRenderingService()

    html = service.html(_renderable_report())
    latex = service.latex(_renderable_report())

    assert "<!doctype html>" in html
    assert "Test" in html
    assert "\\documentclass" in latex
    assert "Test" in latex


def test_report_rendering_service_writes_pdf(tmp_path) -> None:
    target = tmp_path / "report.pdf"

    ReportRenderingService().pdf(target, _renderable_report())

    assert target.read_bytes().startswith(b"%PDF")


def test_average_annual_rainfall_volumes_reconcile_gross_first_flush_and_usable() -> None:
    results = pd.DataFrame(
        {
            "Date": ["2024-01-01", "2024-02-01", "2025-01-01"],
            "GrossCollectedGallons": [100.0, 200.0, 500.0],
            "FirstFlushLossGallons": [10.0, 20.0, 50.0],
            "CollectedGallons": [90.0, 180.0, 450.0],
        }
    )

    summary = report_average_annual_rainfall_volumes(
        results, default_project_config()
    )

    assert summary == {
        "total_average_rain": 400.0,
        "average_first_flush_diversion": 40.0,
        "total_usable_average_rain": 360.0,
    }


def test_first_flush_summaries_reconcile_events_and_years() -> None:
    results = pd.DataFrame(
        {
            "Date": ["2024-12-31", "2025-01-01", "2025-01-10", "2025-01-11"],
            "RainfallEventId": [1, 1, 2, pd.NA],
            "RainfallEventStart": [True, False, True, False],
            "GrossCollectedGallons": [100.0, 50.0, 200.0, 0.0],
            "FirstFlushLossGallons": [10.0, 0.0, 20.0, 0.0],
            "CollectedGallons": [90.0, 50.0, 180.0, 0.0],
        }
    )

    events, years = report_first_flush_summaries(results, default_project_config())

    assert events == [
        {
            "event_id": 1,
            "start": "2024-12-31T00:00:00",
            "end": "2025-01-01T00:00:00",
            "wet_timesteps": 2,
            "gross_runoff": 150.0,
            "first_flush_loss": 10.0,
            "net_collected": 140.0,
            "diversion_percent": pytest.approx(10.0 / 150.0 * 100.0),
        },
        {
            "event_id": 2,
            "start": "2025-01-10T00:00:00",
            "end": "2025-01-10T00:00:00",
            "wet_timesteps": 1,
            "gross_runoff": 200.0,
            "first_flush_loss": 20.0,
            "net_collected": 180.0,
            "diversion_percent": 10.0,
        },
    ]
    assert years == [
        {
            "year": 2024,
            "event_count": 1,
            "gross_runoff": 100.0,
            "first_flush_loss": 10.0,
            "net_collected": 90.0,
            "diversion_percent": 10.0,
        },
        {
            "year": 2025,
            "event_count": 1,
            "gross_runoff": 250.0,
            "first_flush_loss": 20.0,
            "net_collected": 230.0,
            "diversion_percent": 8.0,
        },
    ]


def test_first_flush_yearly_summary_supports_legacy_results_without_event_ids() -> None:
    results = pd.DataFrame(
        {
            "Date": ["2024-01-01"],
            "GrossCollectedGallons": [100.0],
            "FirstFlushLossGallons": [10.0],
            "CollectedGallons": [90.0],
        }
    )

    events, years = report_first_flush_summaries(results, default_project_config())

    assert events == []
    assert years[0]["event_count"] == 0
    assert years[0]["first_flush_loss"] == 10.0


def test_rainfall_volume_summary_is_grouped_in_every_report_format(tmp_path) -> None:
    report = _renderable_report()
    report["average_annual_rainfall_volumes"] = {
        "total_average_rain": 12_500.0,
        "average_first_flush_diversion": 750.0,
        "total_usable_average_rain": 11_750.0,
    }
    service = ReportRenderingService()

    html = service.html(report)
    latex = service.latex(report)
    target = tmp_path / "rainfall-volumes.pdf"
    service.pdf(target, report)
    pdf_text = "\n".join(page.extract_text() or "" for page in PdfReader(target).pages)

    assert 'id="rainfall-volume-summary"' in html
    assert "12,500 gal/year" in html
    assert "11,750 gal/year" in html
    assert r"\section{Rainfall Volume Summary}" in latex
    assert "12,500 gal/year" in latex
    assert "Rainfall Volume Summary" in pdf_text
    assert "Total average rain: 12,500 gal/year" in pdf_text
    assert "Total usable average rain: 11,750 gal/year" in pdf_text


def test_first_flush_summaries_are_rendered_in_every_report_format(tmp_path) -> None:
    report = _renderable_report()
    report["first_flush_yearly_summary"] = [
        {
            "year": 2025,
            "event_count": 2,
            "gross_runoff": 350.0,
            "first_flush_loss": 30.0,
            "net_collected": 320.0,
            "diversion_percent": 30.0 / 350.0 * 100.0,
        }
    ]
    report["first_flush_event_summary"] = [
        {
            "event_id": 7,
            "start": "2025-01-10T00:00:00",
            "end": "2025-01-11T00:00:00",
            "wet_timesteps": 2,
            "gross_runoff": 150.0,
            "first_flush_loss": 10.0,
            "net_collected": 140.0,
            "diversion_percent": 10.0 / 150.0 * 100.0,
        }
    ]
    service = ReportRenderingService()

    html = service.html(report)
    latex = service.latex(report)
    target = tmp_path / "first-flush-summaries.pdf"
    service.pdf(target, report)
    pdf_text = "\n".join(page.extract_text() or "" for page in PdfReader(target).pages)

    assert 'id="first-flush-summary"' in html
    assert "350" in html
    assert "2025-01-10T00:00:00" in html
    assert r"\section{First-flush Diversion Summary}" in latex
    assert "2025-01-10T00:00:00" in latex
    assert "First-flush Diversion Summary" in pdf_text
    assert "Event 7" in pdf_text
    assert "diverted 10 gal" in pdf_text


def test_report_section_choices_apply_to_html_latex_and_pdf(tmp_path) -> None:
    report = _renderable_report()
    report["report_sections"] = {
        "executive_summary": True,
        "candidate_performance": False,
        "financial_analysis": False,
    }
    service = ReportRenderingService()

    html = service.html(report)
    latex = service.latex(report)
    target = tmp_path / "selected-sections.pdf"
    service.pdf(target, report)
    pdf_text = "\n".join(page.extract_text() or "" for page in PdfReader(target).pages)

    assert 'id="executive-summary"' in html
    assert 'id="candidate-performance"' not in html
    assert 'href="#candidate-performance"' not in html
    assert r"\section{Executive Summary}" in latex
    assert r"\section{Candidate Performance}" not in latex
    assert "Executive Summary" in pdf_text
    assert "Candidate Performance" not in pdf_text
    assert "Financial Analysis" not in pdf_text


def test_project_information_precedes_executive_summary_in_all_formats(tmp_path) -> None:
    report = _renderable_report()
    service = ReportRenderingService()

    html = service.html(report)
    latex = service.latex(report)
    target = tmp_path / "section-order.pdf"
    service.pdf(target, report)
    pdf_text = "\n".join(page.extract_text() or "" for page in PdfReader(target).pages)

    assert html.index('<section id="project-information">') < html.index(
        '<section id="executive-summary">'
    )
    assert latex.index(r"\section{Project Information}") < latex.index(
        r"\section{Executive Summary}"
    )
    assert pdf_text.index("Project Information") < pdf_text.index("Executive Summary")


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload.pop("curve"),
        lambda payload: payload.update(schema_version=999),
        lambda payload: payload.update(selected_tank_size=math.inf),
    ],
)
def test_report_model_rejects_invalid_renderer_input(mutation) -> None:
    payload = _minimal_report()
    mutation(payload)

    with pytest.raises(ReportValidationError):
        ReportModel.from_payload(payload)


def test_atomic_write_text_replaces_complete_file(tmp_path) -> None:
    target = tmp_path / "report.html"
    target.write_text("old", encoding="utf-8")

    atomic_write_text(target, "new report")

    assert target.read_text(encoding="utf-8") == "new report"
    assert not list(tmp_path.glob(".report.html.*.tmp"))


def test_atomic_write_text_preserves_existing_file_when_replace_fails(tmp_path, monkeypatch) -> None:
    target = tmp_path / "report.html"
    target.write_text("old", encoding="utf-8")

    def fail_replace(_source, _target) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(reporting.os, "replace", fail_replace)
    with pytest.raises(OSError, match="replace failed"):
        atomic_write_text(target, "new report")

    assert target.read_text(encoding="utf-8") == "old"
    assert not list(tmp_path.glob(".report.html.*.tmp"))
