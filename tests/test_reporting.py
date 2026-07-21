import math

import pytest

import rainwater_app.reporting as reporting
from rainwater_app.report_service import ReportRenderingService
from rainwater_app.reporting import (
    REPORT_SCHEMA_VERSION,
    ReportModel,
    ReportValidationError,
    atomic_write_text,
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
