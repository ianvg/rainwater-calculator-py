"""WeasyPrint-backed HTML-to-PDF report rendering."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from .report_rendering import render_html
from .reporting import ReportModel


def render_html_pdf(
    pdf_path: Path, report: ReportModel | dict[str, object]
) -> None:
    """Render the validated HTML report to an atomically replaced PDF."""
    try:
        from weasyprint import HTML
    except (ImportError, OSError) as exc:
        raise RuntimeError(
            "WeasyPrint is unavailable. Install the application PDF dependencies "
            "or use the Legacy PDF report option."
        ) from exc

    pdf_path = Path(pdf_path)
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    document = render_html(ReportModel.from_payload(report))
    temporary_pdf: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{pdf_path.name}.",
            suffix=".tmp.pdf",
            dir=pdf_path.parent,
            delete=False,
        ) as handle:
            temporary_pdf = Path(handle.name)
        HTML(string=document, base_url=pdf_path.parent.resolve().as_uri()).write_pdf(
            target=temporary_pdf
        )
        if temporary_pdf.stat().st_size < 5 or temporary_pdf.read_bytes()[:5] != b"%PDF-":
            raise ValueError("WeasyPrint did not generate a valid PDF artifact.")
        os.replace(temporary_pdf, pdf_path)
    finally:
        if temporary_pdf is not None and temporary_pdf.exists():
            temporary_pdf.unlink()
