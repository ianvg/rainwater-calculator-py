"""WeasyPrint-backed HTML-to-PDF report rendering."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from .report_rendering import render_html
from .reporting import ReportModel


def render_html_pdf(
    pdf_path: Path, report: ReportModel | dict[str, object]
) -> None:
    """Render the validated HTML report to an atomically replaced PDF."""
    pdf_path = Path(pdf_path)
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    document = render_html(ReportModel.from_payload(report))
    temporary_pdf: Path | None = None
    temporary_html: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{pdf_path.name}.",
            suffix=".tmp.pdf",
            dir=pdf_path.parent,
            delete=False,
        ) as handle:
            temporary_pdf = Path(handle.name)
        executable = _weasyprint_executable()
        if executable is not None:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                prefix=f".{pdf_path.name}.",
                suffix=".tmp.html",
                dir=pdf_path.parent,
                delete=False,
            ) as handle:
                temporary_html = Path(handle.name)
                handle.write(document)
            result = subprocess.run(
                [str(executable), str(temporary_html), str(temporary_pdf)],
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
            if result.returncode != 0:
                details = (result.stdout + "\n" + result.stderr).strip()
                raise RuntimeError(f"WeasyPrint failed to generate the PDF.\n\n{details[-2000:]}")
        else:
            try:
                from weasyprint import HTML
            except (ImportError, OSError) as exc:
                raise RuntimeError(
                    "WeasyPrint is unavailable. Install its native dependencies, set "
                    "RWH_WEASYPRINT_EXECUTABLE, or use the Legacy PDF report option."
                ) from exc
            HTML(string=document, base_url=pdf_path.parent.resolve().as_uri()).write_pdf(
                target=temporary_pdf
            )
        if temporary_pdf.stat().st_size < 5 or temporary_pdf.read_bytes()[:5] != b"%PDF-":
            raise ValueError("WeasyPrint did not generate a valid PDF artifact.")
        os.replace(temporary_pdf, pdf_path)
    finally:
        if temporary_html is not None and temporary_html.exists():
            temporary_html.unlink()
        if temporary_pdf is not None and temporary_pdf.exists():
            temporary_pdf.unlink()


def _weasyprint_executable() -> Path | None:
    """Return an available standalone WeasyPrint executable, if any."""
    configured = os.environ.get("RWH_WEASYPRINT_EXECUTABLE", "").strip()
    candidates: list[Path] = []
    if configured:
        candidates.append(Path(configured).expanduser())
    if getattr(sys, "frozen", False):
        bundle_root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        candidates.append(bundle_root / "weasyprint" / "weasyprint.exe")
    repository_build = Path(__file__).resolve().parents[1] / "build" / "weasyprint"
    candidates.append(repository_build / "weasyprint.exe")
    discovered = shutil.which("weasyprint")
    if discovered:
        candidates.append(Path(discovered))
    return next((candidate.resolve() for candidate in candidates if candidate.is_file()), None)
