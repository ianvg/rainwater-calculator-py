"""UI-independent entry point for rendering validated reports."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .pdf_rendering import render_pdf
from .report_rendering import render_html, render_latex
from .reporting import ReportModel


@dataclass(frozen=True)
class ReportRenderingService:
    """Render one report model consistently across supported output formats."""

    def html(self, report: ReportModel | dict[str, object]) -> str:
        return render_html(report)

    def latex(self, report: ReportModel | dict[str, object]) -> str:
        return render_latex(report)

    def pdf(
        self, pdf_path: Path, report: ReportModel | dict[str, object]
    ) -> None:
        render_pdf(pdf_path, ReportModel.from_payload(report))
