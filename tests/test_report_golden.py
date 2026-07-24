from __future__ import annotations

from html.parser import HTMLParser
import json
from pathlib import Path

from rainwater_app.report_service import ReportRenderingService
from rainwater_app.reporting import ReportModel


GOLDEN_DIR = Path(__file__).with_name("golden")
VOID_ELEMENTS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
    "meta", "param", "source", "track", "wbr",
}


def representative_report_payload() -> dict[str, object]:
    return {
        "metadata": {
            "client_name": "Example Client",
            "date": "2026-07-24",
            "location": "Lyon & Rh\u00f4ne",
            "project_name": "Golden Report <A>",
            "author_name": "QA Team",
            "end_uses": "Toilets and irrigation",
        },
        "notes": "Representative deterministic report fixture.",
        "area_unit": "sq ft",
        "volume_unit": "gal",
        "precipitation_unit": "in",
        "average_annual_precipitation": 40.25,
        "precipitation_basis": "Total precipitation",
        "surfaces": [
            {
                "name": "North roof & canopy",
                "area": 1200.0,
                "runoff_coefficient": 0.9,
                "first_flush_depth": 0.04,
            }
        ],
        "monthly_demand": [
            {
                "month": month,
                "demand_per_day": float(index * 10),
                "demand_per_month": float(index * 300),
            }
            for index, month in enumerate(
                ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"),
                start=1,
            )
        ],
        "total_annual_demand": 23_400.0,
        "curve": [
            {"tank_size": 1000.0, "reliability": 72.5},
            {"tank_size": 2000.0, "reliability": 88.0},
        ],
        "selected_tank_size": 2000.0,
        "selected_reliability": 88.0,
        "yearly_reliability": [
            {
                "year": 2024,
                "total_days": 366,
                "met_days": 322,
                "unmet_days": 44,
                "met_percent": 87.9781420765,
                "unmet_percent": 12.0218579235,
            }
        ],
        "tank_level_distribution": [
            {"low": 0.0, "high": 1000.0, "count": 120},
            {"low": 1000.0, "high": 2000.0, "count": 246},
        ],
        "rainfall_quality": {
            "completeness_percent": 99.7,
            "completeness_rating": "High",
            "expected_days": 366,
            "observed_days": 365,
            "missing_days": 1,
            "duplicate_dates": 0,
            "invalid_precipitation_rows": 0,
            "partial_years": [2024],
            "missing_periods": [{"start": "2024-02-29", "end": "2024-02-29", "days": 1}],
        },
        "yearly_rainfall_summary": [
            {
                "year": 2024,
                "observed_days": 365,
                "missing_days": 1,
                "completeness_percent": 99.7,
                "precipitation": 40.25,
                "wet_days": 104,
                "partial_year": True,
            }
        ],
        "rainfall_event_summary": {
            "event_count": 2,
            "average_event_precipitation": 0.75,
            "largest_event_precipitation": 1.0,
            "antecedent_dry_days": 1.0,
            "largest_events": [
                {
                    "event_number": 2,
                    "start": "2024-06-01",
                    "end": "2024-06-02",
                    "duration_days": 2,
                    "wet_days": 2,
                    "precipitation": 1.0,
                }
            ],
        },
        "first_flush_yearly_summary": [
            {
                "year": 2024,
                "event_count": 2,
                "gross_runoff": 1000.0,
                "first_flush_loss": 50.0,
                "net_collected": 950.0,
                "diversion_percent": 5.0,
            }
        ],
        "first_flush_event_summary": [
            {
                "event_id": 2,
                "start": "2024-06-01T00:00:00",
                "end": "2024-06-02T00:00:00",
                "wet_timesteps": 2,
                "gross_runoff": 200.0,
                "first_flush_loss": 10.0,
                "net_collected": 190.0,
                "diversion_percent": 5.0,
            }
        ],
        "provenance": {
            "rainfall_source": "Golden station",
            "record_start": "2024-01-01",
            "record_end": "2024-12-31",
            "generated_at": "2026-07-24T12:00:00+02:00",
        },
    }


class ReportHTMLInspector(HTMLParser):
    """Strict-enough offline checks for the deterministic generated report markup."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.errors: list[str] = []
        self.stack: list[str] = []
        self.ids: set[str] = set()
        self.internal_links: list[str] = []
        self.lang = ""
        self.title = ""
        self.h1: list[str] = []
        self.sections: list[dict[str, str]] = []
        self.toc_targets: list[str] = []
        self.tables: list[dict[str, object]] = []
        self.svg_labels: list[str] = []
        self.buttons: list[str] = []
        self.doctype_seen = False
        self.main_count = 0
        self.nav_count = 0
        self._head_depth = 0
        self._nav_depth = 0
        self._current_section = ""
        self._table_stack: list[dict[str, object]] = []
        self._captures: list[tuple[str, list[str]]] = []

    @staticmethod
    def _attrs(attributes: list[tuple[str, str | None]]) -> dict[str, str]:
        return {key: value or "" for key, value in attributes}

    def handle_decl(self, decl: str) -> None:
        if decl.casefold() == "doctype html":
            self.doctype_seen = True

    def handle_starttag(self, tag: str, attributes: list[tuple[str, str | None]]) -> None:
        attrs = self._attrs(attributes)
        if tag not in VOID_ELEMENTS:
            self.stack.append(tag)
        element_id = attrs.get("id")
        if element_id:
            if element_id in self.ids:
                self.errors.append(f"Duplicate id: {element_id}")
            self.ids.add(element_id)
        href = attrs.get("href", "")
        if href.startswith("#") and len(href) > 1:
            target = href[1:]
            self.internal_links.append(target)
            if self._nav_depth:
                self.toc_targets.append(target)
        if tag == "html":
            self.lang = attrs.get("lang", "")
        elif tag == "head":
            self._head_depth += 1
        elif tag == "main":
            self.main_count += 1
        elif tag == "nav":
            self.nav_count += 1
            self._nav_depth += 1
            if not attrs.get("aria-label"):
                self.errors.append("Navigation landmark lacks aria-label")
        elif tag == "section":
            self._current_section = attrs.get("id", "")
            if not self._current_section:
                self.errors.append("Section lacks id")
        elif tag == "table":
            table = {"section": self._current_section, "headers": []}
            self.tables.append(table)
            self._table_stack.append(table)
        elif tag == "svg":
            label = attrs.get("aria-label", "")
            self.svg_labels.append(label)
            if attrs.get("role") != "img" or not label:
                self.errors.append("Chart or diagram SVG lacks role=img and aria-label")
        elif tag == "img" and not attrs.get("alt"):
            self.errors.append("Image lacks alt text")

        if tag in {"h1", "h2", "th", "button"} or (
            tag == "title" and self._head_depth
        ):
            self._captures.append((tag, []))

    def handle_startendtag(self, tag: str, attributes: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attributes)
        if tag not in VOID_ELEMENTS and self.stack and self.stack[-1] == tag:
            self.stack.pop()

    def handle_data(self, data: str) -> None:
        for _tag, parts in self._captures:
            parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag not in VOID_ELEMENTS:
            if not self.stack:
                self.errors.append(f"Unexpected closing tag: {tag}")
            elif self.stack[-1] != tag:
                self.errors.append(
                    f"Mismatched closing tag: expected {self.stack[-1]}, received {tag}"
                )
                if tag in self.stack:
                    while self.stack and self.stack[-1] != tag:
                        self.stack.pop()
                    if self.stack:
                        self.stack.pop()
            else:
                self.stack.pop()

        for index in range(len(self._captures) - 1, -1, -1):
            capture_tag, parts = self._captures[index]
            if capture_tag != tag:
                continue
            text = " ".join("".join(parts).split())
            self._captures.pop(index)
            if tag == "title":
                self.title = text
            elif tag == "h1":
                self.h1.append(text)
            elif tag == "h2" and self._current_section:
                self.sections.append({"id": self._current_section, "heading": text})
            elif tag == "th" and self._table_stack:
                self._table_stack[-1]["headers"].append(text)
            elif tag == "button":
                self.buttons.append(text)
            break

        if tag == "table" and self._table_stack:
            self._table_stack.pop()
        elif tag == "head" and self._head_depth:
            self._head_depth -= 1
        elif tag == "section":
            self._current_section = ""
        elif tag == "nav" and self._nav_depth:
            self._nav_depth -= 1

    def finish(self) -> None:
        if self.stack:
            self.errors.append("Unclosed tags: " + ", ".join(self.stack))
        if not self.doctype_seen:
            self.errors.append("Missing HTML5 doctype")
        if not self.lang:
            self.errors.append("Document language is missing")
        if not self.title:
            self.errors.append("Document title is missing")
        if len(self.h1) != 1:
            self.errors.append(f"Expected one h1, found {len(self.h1)}")
        if self.main_count != 1:
            self.errors.append(f"Expected one main landmark, found {self.main_count}")
        if self.nav_count < 1:
            self.errors.append("Missing navigation landmark")
        for target in self.internal_links:
            if target not in self.ids:
                self.errors.append(f"Broken internal link: #{target}")
        for table in self.tables:
            if not table["headers"]:
                self.errors.append(
                    f'Table in section {table["section"] or "(none)"} has no headers'
                )
        if any(not button for button in self.buttons):
            self.errors.append("Button lacks accessible text")

    def semantic_snapshot(self) -> dict[str, object]:
        return {
            "document": {"lang": self.lang, "title": self.title, "h1": self.h1},
            "sections": [
                f'{section["id"]}: {section["heading"]}' for section in self.sections
            ],
            "toc_targets": self.toc_targets,
            "tables": [
                f'{table["section"]}: ' + " | ".join(table["headers"])
                for table in self.tables
            ],
            "svg_labels": self.svg_labels,
        }


def inspect_html(html: str) -> ReportHTMLInspector:
    inspector = ReportHTMLInspector()
    inspector.feed(html)
    inspector.close()
    inspector.finish()
    return inspector


def test_normalized_report_model_matches_golden_fixture() -> None:
    actual = json.dumps(
        ReportModel.from_payload(representative_report_payload()).to_dict(),
        indent=2,
        sort_keys=True,
        ensure_ascii=True,
    ) + "\n"

    assert actual == (GOLDEN_DIR / "report-model-v2.json").read_text(encoding="utf-8")


def test_representative_html_matches_semantic_golden_fixture() -> None:
    html = ReportRenderingService().html(representative_report_payload())
    inspector = inspect_html(html)
    actual = json.dumps(
        inspector.semantic_snapshot(), indent=2, sort_keys=True, ensure_ascii=True
    ) + "\n"

    assert actual == (GOLDEN_DIR / "report-html-semantics-v2.json").read_text(
        encoding="utf-8"
    )


def test_representative_html_is_structurally_valid_and_accessible() -> None:
    html = ReportRenderingService().html(representative_report_payload())
    inspector = inspect_html(html)

    assert inspector.errors == []
