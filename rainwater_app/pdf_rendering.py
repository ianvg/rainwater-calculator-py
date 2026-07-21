"""Direct PDF report renderer with no Tkinter dependency."""

from __future__ import annotations

import math
from pathlib import Path

from pypdf import PdfWriter
from pypdf.annotations import Link
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from .reporting import (
    ReportModel,
    clip_pdf_text as _clip_pdf_text,
    pdf_escape as _pdf_escape,
    wrap_pdf_text as _wrap_pdf_text,
)


def render_pdf(pdf_path: Path, report: ReportModel) -> None:
    metadata = report["metadata"]
    report_title = "RWH Calculator Report - multi-tank" if report.get("include_multitank_charts") else "RWH Calculator Report"
    surface_rows = [
        (
            surface["name"],
            f"{surface['area']:,.2f}",
            f"{surface['runoff_coefficient']:.2f}",
        )
        for surface in report["surfaces"]
    ]
    if not surface_rows:
        surface_rows = [("No collection surfaces", "0.00", "0.000")]

    selected_reliability = "--"
    if report["selected_reliability"] is not None:
        selected_reliability = f"{report['selected_reliability']:.2f}%"

    pages: list[list[str]] = [[]]
    section_pages: dict[str, int] = {}
    toc_links: list[tuple[tuple[float, float, float, float], str]] = []
    section_titles = (
        "Design Recommendations",
        "Executive Summary",
        "Project Information",
        "Notes",
        "Surface Area Summary",
        "Tank Summary",
        "Candidate Performance",
        "Reconciled Water Balance",
        *(("System Visualization",) if report.get("include_system_visualization") else ()),
        "Demand Summary",
        "End-use Performance",
        "Financial Analysis",
        "Rainfall Quality and Completeness",
        "Yearly Rainfall Summary",
        "Rainfall-event Summary",
        "Analysis Provenance",
        "Reliability Curve",
        "Yearly Demand Reliability",
        "Tank Level Distribution",
    )
    y = 744.0

    def page() -> list[str]:
        return pages[-1]

    def add_page() -> None:
        nonlocal y
        pages.append([])
        y = 744.0

    def text(x: float, y_pos: float, value: object, size: int = 10, bold: bool = False) -> None:
        font = "F2" if bold else "F1"
        safe = _pdf_escape(value)
        page().append(f"BT /{font} {size} Tf 1 0 0 1 {x:.2f} {y_pos:.2f} Tm ({safe}) Tj ET")

    def line(x1: float, y1: float, x2: float, y2: float, width: float = 0.5) -> None:
        page().append(f"{width:.2f} w {x1:.2f} {y1:.2f} m {x2:.2f} {y2:.2f} l S")

    def circle(center_x: float, center_y: float, radius: float, width: float = 1.2) -> None:
        control = radius * 0.55228475
        page().append(
            f"{width:.2f} w {center_x + radius:.2f} {center_y:.2f} m "
            f"{center_x + radius:.2f} {center_y + control:.2f} {center_x + control:.2f} "
            f"{center_y + radius:.2f} {center_x:.2f} {center_y + radius:.2f} c "
            f"{center_x - control:.2f} {center_y + radius:.2f} {center_x - radius:.2f} "
            f"{center_y + control:.2f} {center_x - radius:.2f} {center_y:.2f} c "
            f"{center_x - radius:.2f} {center_y - control:.2f} {center_x - control:.2f} "
            f"{center_y - radius:.2f} {center_x:.2f} {center_y - radius:.2f} c "
            f"{center_x + control:.2f} {center_y - radius:.2f} {center_x + radius:.2f} "
            f"{center_y - control:.2f} {center_x + radius:.2f} {center_y:.2f} c S"
        )

    def filled_star(center_x: float, center_y: float, radius: float, color: str) -> None:
        rgb = {
            "blue": (0.08, 0.40, 0.75),
            "red": (0.84, 0.10, 0.13),
        }[color]
        points: list[tuple[float, float]] = []
        for index in range(10):
            point_radius = radius if index % 2 == 0 else radius * 0.42
            angle = -math.pi / 2.0 + index * math.pi / 5.0
            points.append((
                center_x + math.cos(angle) * point_radius,
                center_y + math.sin(angle) * point_radius,
            ))
        commands = [f"{rgb[0]:.2f} {rgb[1]:.2f} {rgb[2]:.2f} rg"]
        commands.append(f"{points[0][0]:.2f} {points[0][1]:.2f} m")
        commands.extend(f"{px:.2f} {py:.2f} l" for px, py in points[1:])
        commands.append("h f 0 0 0 rg")
        page().append(" ".join(commands))

    def add_wrapped(value: object, x: float = 54.0, size: int = 10, width: int = 90, indent: float = 0.0) -> None:
        nonlocal y
        for wrapped in _wrap_pdf_text(str(value), width):
            if y < 72:
                add_page()
            text(x + indent, y, wrapped, size=size)
            y -= size + 4

    def heading(value: str) -> None:
        nonlocal y
        if y < 112:
            add_page()
        section_pages[value] = len(pages) - 1
        y -= 10
        text(54, y, value, size=14, bold=True)
        y -= 18
        line(54, y + 8, 558, y + 8)

    text(54, y, report_title, size=20, bold=True)
    y -= 34
    if metadata.get("author_name", "").strip():
        text(54, y, f"Produced by: {metadata['author_name']}", size=10)
        y -= 22
    text(54, y, "Table of Contents", size=14, bold=True)
    y -= 24
    for title in section_titles:
        text(72, y, title, size=11)
        toc_links.append(((68.0, y - 4.0, 300.0, y + 12.0), title))
        y -= 24
    add_page()
    heading("Design Recommendations")
    assumptions = report.get("recommendation_assumptions", {})
    add_wrapped(
        f'Reliability target: {float(assumptions.get("reliability_target_percent", 90.0)):.1f}%. '
        f'Diminishing-return threshold: {float(assumptions.get("marginal_gain_threshold", 1.0)):.2f} '
        "reliability percentage points per 1,000 gallons."
    )
    add_wrapped(
        "Decision aids compare the simulated candidates under the stated assumptions; "
        "they are not a universal optimum."
    )
    for item in report.get("recommendations", []):
        add_wrapped(
            f'{item.get("role", "Recommendation")}: '
            f'{float(item.get("tank_size", 0.0)):,.0f} '
            f'{item.get("volume_unit", report["volume_unit"])} at '
            f'{float(item.get("reliability_percent", 0.0)):.1f}% reliability. '
            f'{item.get("detail", "")}',
            indent=10,
        )
    text(54, y, "Review conditions", size=11, bold=True)
    y -= 16
    warnings = list(report.get("review_warnings", [])) or [
        "No configured review conditions were triggered."
    ]
    for warning in warnings:
        add_wrapped(f"- {warning}", indent=10)
    y -= 4

    heading("Executive Summary")
    executive = report.get("executive_summary", {})
    financial = report.get("financial_summary", {})
    payback = executive.get("simple_payback_years")
    for label, value in (
        ("Selected reliability", selected_reliability),
        ("Average annual rainwater supply", f'{float(executive.get("average_annual_supply", 0.0)):,.0f} {report["volume_unit"]}/year'),
        ("Average annual municipal makeup", f'{float(executive.get("average_annual_municipal_makeup", 0.0)):,.0f} {report["volume_unit"]}/year'),
        ("Average annual overflow", f'{float(executive.get("average_annual_overflow", 0.0)):,.0f} {report["volume_unit"]}/year'),
        ("Net annual savings", f'{financial.get("currency", "USD")} {float(executive.get("net_annual_savings", 0.0)):,.2f}/year'),
        ("Simple payback", f"{float(payback):.1f} years" if payback is not None else "Not achieved"),
    ):
        add_wrapped(f"{label}: {value}")
    y -= 4

    heading("Project Information")
    for label, value in [
        ("Client name", metadata["client_name"]),
        ("Date", metadata["date"]),
        ("Location", metadata["location"]),
        ("Project name", metadata["project_name"]),
        ("End-uses of water", metadata["end_uses"]),
        (
            "Average annual precipitation",
            f"{float(report['average_annual_precipitation']):,.2f} {report['precipitation_unit']}",
        ),
        ("Precipitation basis", report["precipitation_basis"]),
        (
            "Selected tank size",
            f"{float(report['selected_tank_size']):,.0f} {report['volume_unit']}",
        ),
        ("Selected tank reliability", selected_reliability),
    ]:
        if y < 84:
            add_page()
        text(54, y, f"{label}:", size=10, bold=True)
        add_wrapped(value or "Not specified", x=190, size=10, width=58)
        y -= 2

    location_points: list[tuple[float, float, str, str]] = []
    if report.get("weather_station_latitude") is not None and report.get("weather_station_longitude") is not None:
        location_points.append((
            float(report["weather_station_latitude"]),
            float(report["weather_station_longitude"]),
            "red", "Weather station",
        ))
    if report.get("project_latitude") is not None and report.get("project_longitude") is not None:
        location_points.append((
            float(report["project_latitude"]),
            float(report["project_longitude"]),
            "blue", "Project location",
        ))
    if location_points:
        if y < 240:
            add_page()
        map_x, map_y, map_width, map_height = 54.0, y - 154.0, 504.0, 140.0
        text(map_x, y, "Project location map", size=11, bold=True)
        page().append(
            f"0.94 0.96 0.95 rg {map_x:.2f} {map_y:.2f} {map_width:.2f} {map_height:.2f} re f "
            f"0.55 G 0.8 w {map_x:.2f} {map_y:.2f} {map_width:.2f} {map_height:.2f} re S 0 G"
        )
        # Light road/grid context keeps the fallback PDF useful when raster tiles are unavailable.
        page().append("0.80 G 0.7 w")
        for fraction in (0.25, 0.5, 0.75):
            line(map_x + map_width * fraction, map_y, map_x + map_width * fraction, map_y + map_height)
            line(map_x, map_y + map_height * fraction, map_x + map_width, map_y + map_height * fraction)
        page().append("0 G")
        latitudes = [point[0] for point in location_points]
        longitudes = [point[1] for point in location_points]
        latitude_span = max(max(latitudes) - min(latitudes), 0.02)
        longitude_span = max(max(longitudes) - min(longitudes), 0.02)
        latitude_midpoint = (max(latitudes) + min(latitudes)) / 2.0
        longitude_midpoint = (max(longitudes) + min(longitudes)) / 2.0
        for latitude, longitude, color, label in location_points:
            marker_x = map_x + map_width * (
                0.5 + (longitude - longitude_midpoint) / (longitude_span * 1.4)
            )
            marker_y = map_y + map_height * (
                0.5 + (latitude - latitude_midpoint) / (latitude_span * 1.4)
            )
            filled_star(marker_x, marker_y, 8.0, color)
            text(marker_x + 11, marker_y - 3, label, size=8, bold=True)
        text(map_x + 5, map_y + 5, "Portable coordinate diagram; not a street map", size=7)
        y = map_y - 8

    heading("Notes")
    notes = str(report.get("notes", "")).strip() or "No notes provided."
    for paragraph_index, paragraph in enumerate(notes.splitlines() or [notes]):
        if paragraph_index and not paragraph:
            y -= 6
            continue
        add_wrapped(paragraph or " ", x=54, size=10, width=90)
    y -= 2

    heading("Surface Area Summary")
    text(54, y, "Surface", size=10, bold=True)
    text(330, y, f"Area ({report['area_unit']})", size=10, bold=True)
    text(450, y, "Runoff coeff.", size=10, bold=True)
    y -= 8
    line(54, y, 558, y)
    y -= 14
    for name, area_text, runoff in surface_rows:
        if y < 72:
            add_page()
        text(54, y, _clip_pdf_text(name, 46), size=9)
        text(330, y, area_text, size=9)
        text(450, y, runoff, size=9)
        y -= 14

    heading("Tank Summary")
    text(54, y, "Tank property", size=10, bold=True)
    text(330, y, "Value", size=10, bold=True)
    y -= 8
    line(54, y, 558, y)
    y -= 14
    text(54, y, "Size", size=9)
    text(330, y, f"{float(report['selected_tank_size']):,.0f} {report['volume_unit']}", size=9)
    y -= 14

    heading("Candidate Performance")
    candidates = list(report.get("candidate_performance", []))
    if not candidates:
        add_wrapped("No candidate results available.")
    for candidate in candidates:
        payback_value = candidate.get("SimplePaybackYears")
        add_wrapped(
            f'{float(candidate.get("tank_size", 0.0)):,.0f} {report["volume_unit"]}: '
            f'{float(candidate.get("reliability", 0.0)):.1f}% reliability; '
            f'{float(candidate.get("RainwaterSuppliedGallons") or 0.0):,.0f} supply/year; '
            f'{float(candidate.get("OverflowGallons") or 0.0):,.0f} overflow/year; '
            + (f"{float(payback_value):.1f} years payback" if payback_value is not None else "payback not achieved")
        )
    y -= 4

    heading("Reconciled Water Balance")
    balance = report.get("water_balance", {})
    for label, key in (
        ("Potential surface rainfall", "potential_surface_rainfall"),
        ("Gross runoff", "gross_runoff"),
        ("First-flush diversion", "first_flush_loss"),
        ("Net collected water", "net_collected"),
        ("Rainwater supplied", "rainwater_supplied"),
        ("Treatment loss", "treatment_loss"),
        ("Overflow", "overflow"),
        ("Final storage", "final_storage"),
        ("Storage residual", "storage_residual"),
    ):
        add_wrapped(f'{label}: {float(balance.get(key, 0.0)):,.1f} {report["volume_unit"]}')
    y -= 4

    if report.get("include_system_visualization"):
        heading("System Visualization")
        system_type = str(report.get("system_type", "Direct system"))
        text(54, y, system_type, size=11, bold=True)
        y -= 22
        tank_left, tank_bottom, tank_width, tank_height = 64.0, y - 105.0, 120.0, 92.0
        page().append(f"1.20 w {tank_left:.2f} {tank_bottom:.2f} {tank_width:.2f} {tank_height:.2f} re S")
        text(tank_left + 25, tank_bottom + 68, "Primary tank", size=9, bold=True)
        text(
            tank_left + 20,
            tank_bottom + 54,
            f"{float(report['selected_tank_size']):,.0f} {report['volume_unit']}",
            size=8,
        )
        wave_points = [
            (tank_left + offset, tank_bottom + 39 + (3 if (offset // 6) % 2 else -3))
            for offset in range(0, 121, 6)
        ]
        wave = [f"{wave_points[0][0]:.2f} {wave_points[0][1]:.2f} m"]
        wave.extend(f"{x_pos:.2f} {y_pos:.2f} l" for x_pos, y_pos in wave_points[1:])
        page().append(" ".join(wave) + " S")
        pipe_y = tank_bottom + 42
        if system_type == "Indirect system":
            line(tank_left + tank_width, pipe_y, 235, pipe_y, 1.2)
            circle(252, pipe_y, 17)
            text(220, pipe_y - 28, "Filtration pump", size=8)
            line(269, pipe_y, 310, pipe_y, 1.2)
            page().append(f"1.20 w 310 {pipe_y - 18:.2f} 80 36 re S")
            text(326, pipe_y - 3, "Filtration", size=8, bold=True)
            line(390, pipe_y, 430, pipe_y, 1.2)
            page().append(f"1.20 w 430 {tank_bottom + 10:.2f} 90 78 re S")
            text(444, tank_bottom + 65, "Buffer tank", size=8, bold=True)
            line(475, tank_bottom + 115, 475, tank_bottom + 88, 1.2)
            page().append(
                f"0 0 0 rg 475 {tank_bottom + 88:.2f} m 470 {tank_bottom + 98:.2f} l "
                f"480 {tank_bottom + 98:.2f} l f"
            )
            text(380, tank_bottom + 112, "Municipal water backup", size=7, bold=True)
            line(520, pipe_y, 526, pipe_y, 1.2)
            circle(538, pipe_y, 12)
            page().append(
                f"1.20 w 550 {pipe_y:.2f} m 532 {pipe_y + 10.39:.2f} l "
                f"532 {pipe_y - 10.39:.2f} l h S"
            )
            text(514, pipe_y - 24, "Booster pump", size=7)
            line(550, pipe_y, 580, pipe_y, 1.2)
        else:
            line(tank_left + tank_width, pipe_y, 250, pipe_y, 1.2)
            circle(267, pipe_y, 17)
            text(238, pipe_y - 28, "Distribution pump", size=8)
            line(284, pipe_y, 550, pipe_y, 1.2)
        arrow_x = 580 if system_type == "Indirect system" else 550
        page().append(
            f"0 0 0 rg {arrow_x} {pipe_y:.2f} m {arrow_x - 12} {pipe_y + 6:.2f} l "
            f"{arrow_x - 12} {pipe_y - 6:.2f} l f"
        )
        text(430, pipe_y + 14, "Flow to end-uses", size=8, bold=True)
        y = tank_bottom - 12

    heading("Demand Summary")
    column_x = (54.0, 100.0, 190.0, 310.0, 356.0, 446.0)
    headers = (
        "Month",
        f"{report['volume_unit']}/day",
        f"{report['volume_unit']}/month",
        "Month",
        f"{report['volume_unit']}/day",
        f"{report['volume_unit']}/month",
    )
    for x_pos, label in zip(column_x, headers):
        text(x_pos, y, label, size=9, bold=True)
    y -= 8
    line(54, y, 558, y)
    y -= 14
    for index in range(6):
        left_month = report["monthly_demand"][index]
        right_month = report["monthly_demand"][index + 6]
        text(column_x[0], y, left_month["month"], size=9)
        text(column_x[1], y, f"{float(left_month['demand_per_day']):,.0f}", size=9)
        text(column_x[2], y, f"{float(left_month['demand_per_month']):,.0f}", size=9)
        text(column_x[3], y, right_month["month"], size=9)
        text(column_x[4], y, f"{float(right_month['demand_per_day']):,.0f}", size=9)
        text(column_x[5], y, f"{float(right_month['demand_per_month']):,.0f}", size=9)
        y -= 14
    line(54, y + 5, 558, y + 5, width=0.4)
    line(54, y + 2, 558, y + 2, width=0.4)
    y -= 12
    text(320, y, "Total Annual Demand", size=9, bold=True)
    text(450, y, f"{float(report['total_annual_demand']):,.0f} {report['volume_unit']}", size=9, bold=True)
    y -= 14

    heading("End-use Performance")
    end_use_rows = list(report.get("end_use_rows", []))
    if not end_use_rows:
        add_wrapped("No demand objects available.")
    for row in end_use_rows:
        add_wrapped(
            f'{row.get("name", "Unnamed")}: {row.get("type", "unspecified")}; '
            f'{float(row.get("annual_demand", 0.0)):,.0f} demand/year; '
            f'{float(row.get("annual_supply", 0.0)):,.0f} supplied/year; '
            f'{float(row.get("demand_met_percent", 0.0)):.1f}% met'
        )
    y -= 4

    heading("Financial Analysis")
    financial = report.get("financial_summary", {})
    payback = financial.get("simple_payback_years")
    for label, value in (
        ("Configured", "Yes" if financial.get("configured") else "No"),
        ("Water tariff", f'{financial.get("currency", "USD")} {float(financial.get("water_rate", 0.0)):g} {financial.get("tariff_billing_unit", "")}'),
        ("Sewer tariff", f'{financial.get("currency", "USD")} {float(financial.get("sewer_rate", 0.0)):g} {financial.get("tariff_billing_unit", "")}'),
        ("Installed cost", f'{financial.get("currency", "USD")} {float(financial.get("installed_cost", 0.0)):,.2f}'),
        ("Net annual savings", f'{financial.get("currency", "USD")} {float(financial.get("net_annual_savings", 0.0)):,.2f}'),
        ("Simple payback", f"{float(payback):.1f} years" if payback is not None else "Not achieved"),
        ("Pump energy", f'{float(financial.get("average_annual_pump_energy_kwh", 0.0)):,.1f} kWh/year; {financial.get("currency", "USD")} {float(financial.get("annual_pump_energy_cost", 0.0)):,.2f}/year'),
        ("Discount rate", f'{float(financial.get("discount_rate_percent", 0.0)):g}%'),
        ("Lifecycle NPV", f'{financial.get("currency", "USD")} {float(financial.get("lifecycle_net_present_value", 0.0)):,.2f}'),
        ("IRR", f'{float(financial["internal_rate_of_return_percent"]):.2f}%' if financial.get("internal_rate_of_return_percent") is not None else "Not uniquely defined"),
        ("Discounted payback", f'{float(financial["discounted_payback_years"]):.1f} years' if financial.get("discounted_payback_years") is not None else "Not achieved"),
        ("Methodology", financial.get("methodology", "")),
    ):
        add_wrapped(f"{label}: {value}")
    cash_flows = [float(value) for value in financial.get("annual_cash_flows", [])]
    discount_rate = float(financial.get("discount_rate_percent", 0.0)) / 100.0
    cumulative_discounted = 0.0
    if cash_flows:
        add_wrapped("Annual lifecycle cash flow:", indent=10)
    for year, nominal in enumerate(cash_flows):
        discounted = nominal / ((1.0 + discount_rate) ** year)
        cumulative_discounted += discounted
        add_wrapped(
            f"Year {year}: nominal {financial.get('currency', 'USD')} {nominal:,.2f}; "
            f"discounted {financial.get('currency', 'USD')} {discounted:,.2f}; "
            f"cumulative discounted {financial.get('currency', 'USD')} "
            f"{cumulative_discounted:,.2f}",
            indent=10,
        )
    y -= 4

    heading("Rainfall Quality and Completeness")
    rainfall_quality = report.get("rainfall_quality", {})
    for label, value in (
        ("Completeness score", f'{float(rainfall_quality.get("completeness_percent", 0.0)):.2f}% ({rainfall_quality.get("completeness_rating", "Not rated")})'),
        ("Calendar-day coverage", f'{int(rainfall_quality.get("observed_days", 0)):,} observed of {int(rainfall_quality.get("expected_days", 0)):,} expected'),
        ("Missing days", f'{int(rainfall_quality.get("missing_days", 0)):,}'),
        ("Partial/incomplete years", ", ".join(str(value) for value in rainfall_quality.get("partial_years", [])) or "None"),
        ("Duplicate dates", f'{int(rainfall_quality.get("duplicate_dates", 0)):,}'),
    ):
        add_wrapped(f"{label}: {value}")
    missing_periods = list(rainfall_quality.get("missing_periods", []))[:20]
    if missing_periods:
        add_wrapped("Missing periods (up to 20):", indent=10)
        for row in missing_periods:
            add_wrapped(
                f'{row.get("start", "")} to {row.get("end", "")}: '
                f'{int(row.get("days", 0)):,} day(s)',
                indent=20,
            )
    y -= 4

    heading("Yearly Rainfall Summary")
    yearly_rainfall = list(report.get("yearly_rainfall_summary", []))
    if not yearly_rainfall:
        add_wrapped("No yearly rainfall summary is available.")
    for row in yearly_rainfall:
        add_wrapped(
            f'{int(row.get("year", 0))}: {int(row.get("observed_days", 0)):,} observed; '
            f'{int(row.get("missing_days", 0)):,} missing; '
            f'{float(row.get("completeness_percent", 0.0)):.2f}% complete; '
            f'{float(row.get("precipitation", 0.0)):,.2f} {report["precipitation_unit"]}; '
            f'{int(row.get("wet_days", 0)):,} wet day(s); '
            f'{"partial" if row.get("partial_year") else "complete"} year'
        )
    y -= 4

    heading("Rainfall-event Summary")
    event_summary = report.get("rainfall_event_summary", {})
    add_wrapped(
        f'{int(event_summary.get("event_count", 0)):,} event(s); '
        f'antecedent dry threshold {float(event_summary.get("antecedent_dry_days", 1.0)):g} day(s); '
        f'average depth {float(event_summary.get("average_event_precipitation", 0.0)):,.3f} '
        f'{report["precipitation_unit"]}; largest depth '
        f'{float(event_summary.get("largest_event_precipitation", 0.0)):,.3f} '
        f'{report["precipitation_unit"]}.'
    )
    for row in event_summary.get("largest_events", []):
        add_wrapped(
            f'Event {int(row.get("event_number", 0))}: {row.get("start", "")} to '
            f'{row.get("end", "")}; {int(row.get("duration_days", 0))} day(s); '
            f'{int(row.get("wet_days", 0))} wet day(s); '
            f'{float(row.get("precipitation", 0.0)):,.3f} {report["precipitation_unit"]}',
            indent=10,
        )
    y -= 4

    heading("Analysis Provenance")
    provenance = report.get("provenance", {})
    for label, value in (
        ("Rainfall source", provenance.get("rainfall_source", "Not available")),
        ("Rainfall data classification", provenance.get("rainfall_data_type", "Unclassified user-supplied data")),
        ("Rainfall record", f'{provenance.get("record_start", "Not available")} to {provenance.get("record_end", "Not available")}'),
        ("Missing calendar days", provenance.get("missing_calendar_days", 0)),
        ("Incomplete calendar years", provenance.get("incomplete_calendar_years", 0)),
        ("Rainfall resolution", provenance.get("rainfall_resolution", "Daily")),
        ("Rainfall source timezone", provenance.get("rainfall_timezone", "Unspecified")),
        ("Rainfall timing metadata", provenance.get("rainfall_timing_metadata", "Not specified")),
        ("Rainfall retrieved/imported", provenance.get("rainfall_retrieved_at", "Not recorded")),
        ("Simulation timestep", provenance.get("simulation_timestep", "Daily mass balance")),
        ("Application / algorithm", f'{provenance.get("application_version", "Unknown")} / {provenance.get("algorithm_version", "Unknown")}'),
        ("Report schema", provenance.get("report_schema_version", report["schema_version"])),
        ("Analysis signature", provenance.get("analysis_input_signature", "Not stored")),
        ("Generated", provenance.get("generated_at", "Not available")),
    ):
        add_wrapped(f"{label}: {value}")
    y -= 4

    heading("Reliability Curve")
    _draw_pdf_reliability_curve(page(), 78, max(120, y - 280), 456, 250, report)

    add_page()
    heading(
        f"Yearly Demand Reliability - {float(report['selected_tank_size']):,.0f} "
        f"{report['volume_unit']} tank"
    )
    _draw_pdf_yearly_demand_reliability(page(), 78, 400, 456, 250, report)

    add_page()
    heading("Tank Level Distribution")
    _draw_pdf_tank_level_distribution(page(), 78, 400, 456, 250, report)

    if report.get("include_multitank_charts"):
        for chart in report.get("multitank_charts", []):
            add_page()
            heading(str(chart["title"]))
            if chart.get("type") == "yearly_stacked":
                stacked_report = {
                    "yearly_reliability": chart["yearly_reliability"],
                    "selected_reliability": chart["selected_reliability"],
                }
                _draw_pdf_yearly_demand_reliability(page(), 78, 400, 456, 250, stacked_report)
            else:
                _draw_pdf_multiline_chart(page(), 78, 400, 456, 250, chart)

    _write_pdf_with_pypdf(pdf_path, pages, section_pages, toc_links)


def _draw_pdf_multiline_chart(
    commands: list[str],
    x: float,
    y: float,
    width: float,
    height: float,
    chart: dict[str, object],
) -> None:
    series_list = chart["series"]
    all_points = [point for series in series_list for point in series["points"]]
    if not all_points:
        return
    x_values = [float(point[0]) for point in all_points]
    y_values = [float(point[1]) for point in all_points]
    x_min, x_max = min(x_values), max(x_values)
    y_min, y_max = 0.0, max(max(y_values), 1.0)
    if x_min == x_max:
        x_max = x_min + 1.0

    def sx(value: float) -> float:
        return x + (value - x_min) / (x_max - x_min) * width

    def sy(value: float) -> float:
        return y + (value - y_min) / (y_max - y_min) * height

    commands.append("0.50 w 0.85 0.85 0.85 RG")
    for index in range(5):
        grid_y = y + height * index / 4
        commands.append(f"{x:.2f} {grid_y:.2f} m {x + width:.2f} {grid_y:.2f} l S")
    colors = ((0.04, 0.36, 0.67), (0.18, 0.55, 0.34), (0.79, 0.30, 0.30), (0.48, 0.29, 0.71))
    for series_index, series in enumerate(series_list):
        points = [(sx(float(px)), sy(float(py))) for px, py in series["points"]]
        if len(points) < 2:
            continue
        red, green, blue = colors[series_index % len(colors)]
        path = [f"{points[0][0]:.2f} {points[0][1]:.2f} m"]
        path.extend(f"{px:.2f} {py:.2f} l" for px, py in points[1:])
        commands.append(f"{red:.2f} {green:.2f} {blue:.2f} RG 1.5 w " + " ".join(path) + " S")
        legend_x = x + (series_index % 3) * 145
        legend_y = y + height + 18 - (series_index // 3) * 12
        commands.append(f"{legend_x:.2f} {legend_y:.2f} m {legend_x + 12:.2f} {legend_y:.2f} l S")
        commands.append(
            f"BT /F1 7 Tf 1 0 0 1 {legend_x + 16:.2f} {legend_y - 3:.2f} Tm ({_pdf_escape(series['label'])}) Tj ET"
        )
    commands.append("0 0 0 RG 0.75 w")
    commands.append(f"{x:.2f} {y:.2f} m {x:.2f} {y + height:.2f} l S")
    commands.append(f"{x:.2f} {y:.2f} m {x + width:.2f} {y:.2f} l S")
    commands.append(
        f"BT /F2 9 Tf 1 0 0 1 {x + width / 2 - 40:.2f} {y - 30:.2f} Tm ({_pdf_escape(chart['x_label'])}) Tj ET"
    )
    commands.append(
        f"BT /F2 9 Tf 0 1 -1 0 {x - 38:.2f} {y + height / 2 - 30:.2f} "
        f"Tm ({_pdf_escape(chart['y_label'])}) Tj ET"
    )


def _draw_pdf_yearly_demand_reliability(
    commands: list[str], x: float, y: float, width: float, height: float, report: dict[str, object]
) -> None:
    yearly = report["yearly_reliability"]
    if not yearly:
        return

    def yellow_circle(center_x: float, center_y: float, radius: float) -> None:
        control = radius * 0.55228475
        commands.append("0.95 0.79 0.30 rg 0.54 0.43 0.00 RG 0.75 w")
        commands.append(
            f"{center_x + radius:.2f} {center_y:.2f} m "
            f"{center_x + radius:.2f} {center_y + control:.2f} "
            f"{center_x + control:.2f} {center_y + radius:.2f} {center_x:.2f} {center_y + radius:.2f} c "
            f"{center_x - control:.2f} {center_y + radius:.2f} "
            f"{center_x - radius:.2f} {center_y + control:.2f} {center_x - radius:.2f} {center_y:.2f} c "
            f"{center_x - radius:.2f} {center_y - control:.2f} "
            f"{center_x - control:.2f} {center_y - radius:.2f} {center_x:.2f} {center_y - radius:.2f} c "
            f"{center_x + control:.2f} {center_y - radius:.2f} "
            f"{center_x + radius:.2f} {center_y - control:.2f} {center_x + radius:.2f} {center_y:.2f} c B"
        )

    commands.append("0.50 w 0.85 0.85 0.85 RG")
    for index in range(5):
        gy = y + height * index / 4
        commands.append(f"{x:.2f} {gy:.2f} m {x + width:.2f} {gy:.2f} l S")
        commands.append(
            f"BT /F1 8 Tf 1 0 0 1 {x - 28:.2f} {gy - 3:.2f} Tm ({index * 25}%) Tj ET"
        )
    commands.append("0 0 0 RG 0.75 w")
    commands.append(f"{x:.2f} {y:.2f} m {x:.2f} {y + height:.2f} l S")
    commands.append(f"{x:.2f} {y:.2f} m {x + width:.2f} {y:.2f} l S")
    slot_width = width / (len(yearly) + 1)
    label_step = max((len(yearly) + 9) // 10, 1)
    for index, row in enumerate(yearly):
        left = x + index * slot_width + max(slot_width * 0.15, 0.5)
        bar_width = max(slot_width * 0.7, 0.5)
        met_height = height * float(row["met_percent"]) / 100.0
        commands.append("0.18 0.55 0.34 rg")
        commands.append(f"{left:.2f} {y:.2f} {bar_width:.2f} {met_height:.2f} re f")
        commands.append("0.79 0.30 0.30 rg")
        commands.append(f"{left:.2f} {y + met_height:.2f} {bar_width:.2f} {height - met_height:.2f} re f")
        yellow_circle(left + bar_width / 2, y + met_height, 3.5)
        if index % label_step == 0 or index == len(yearly) - 1:
            commands.append(
                f"BT /F1 7 Tf 1 0 0 1 {left - 2:.2f} {y - 16:.2f} Tm ({int(row['year'])}) Tj ET"
            )
    average_reliability = float(report["selected_reliability"] or 0.0)
    average_x = x + (len(yearly) + 0.5) * slot_width
    average_y = y + height * average_reliability / 100.0
    yellow_circle(average_x, average_y, 4.5)
    commands.append(
        f"BT /F1 7 Tf 1 0 0 1 {average_x - 18:.2f} {y - 14:.2f} Tm (Average) Tj ET"
    )
    commands.append(
        f"BT /F1 6 Tf 1 0 0 1 {average_x - 20:.2f} {y - 24:.2f} Tm ({len(yearly)} years) Tj ET"
    )
    commands.append(f"BT /F2 9 Tf 1 0 0 1 {x + width / 2 - 12:.2f} {y - 34:.2f} Tm (Year) Tj ET")
    commands.append(f"BT /F2 9 Tf 0 1 -1 0 {x - 38:.2f} {y + height / 2 - 16:.2f} Tm (Days %) Tj ET")
    commands.append("0.18 0.55 0.34 rg 82 370 10 10 re f")
    commands.append("BT /F1 8 Tf 1 0 0 1 98 372 Tm (Demand met) Tj ET")
    commands.append("0.79 0.30 0.30 rg 176 370 10 10 re f")
    commands.append("BT /F1 8 Tf 1 0 0 1 192 372 Tm (Demand not met) Tj ET")
    yellow_circle(296, 375, 5)
    commands.append("BT /F1 8 Tf 1 0 0 1 306 372 Tm (Tank reliability) Tj ET")
    commands.append("0 0 0 rg 0 0 0 RG")


def _draw_pdf_tank_level_distribution(
    commands: list[str], x: float, y: float, width: float, height: float, report: dict[str, object]
) -> None:
    distribution = report["tank_level_distribution"]
    if not distribution:
        return
    max_count = max(int(row["count"]) for row in distribution) or 1
    commands.append("0.50 w 0.85 0.85 0.85 RG")
    for index in range(5):
        gy = y + height * index / 4
        commands.append(f"{x:.2f} {gy:.2f} m {x + width:.2f} {gy:.2f} l S")
        commands.append(
            f"BT /F1 8 Tf 1 0 0 1 {x - 28:.2f} {gy - 3:.2f} Tm ({max_count * index / 4:.0f}) Tj ET"
        )
    commands.append("0 0 0 RG 0.75 w")
    commands.append(f"{x:.2f} {y:.2f} m {x:.2f} {y + height:.2f} l S")
    commands.append(f"{x:.2f} {y:.2f} m {x + width:.2f} {y:.2f} l S")
    slot_width = width / len(distribution)
    for index, row in enumerate(distribution):
        left = x + index * slot_width + slot_width * 0.12
        bar_width = slot_width * 0.76
        bar_height = height * int(row["count"]) / max_count
        commands.append("0.18 0.55 0.34 rg")
        commands.append(f"{left:.2f} {y:.2f} {bar_width:.2f} {bar_height:.2f} re f")
        label = _pdf_escape(f"{float(row['low']):,.0f}-{float(row['high']):,.0f}")
        commands.append(
            f"BT /F1 7 Tf 1 0 0 1 {left:.2f} {y - 16:.2f} Tm ({label}) Tj ET"
        )
        commands.append(
            f"BT /F1 8 Tf 1 0 0 1 {left + bar_width / 2 - 4:.2f} {y + bar_height + 6:.2f} "
            f"Tm ({int(row['count'])}) Tj ET"
        )
    commands.append(
        f"BT /F2 9 Tf 1 0 0 1 {x + width / 2 - 58:.2f} {y - 34:.2f} "
        f"Tm (Tank level range ({_pdf_escape(report['volume_unit'])})) Tj ET"
    )
    commands.append(f"BT /F2 9 Tf 0 1 -1 0 {x - 38:.2f} {y + height / 2 - 12:.2f} Tm (Days) Tj ET")
    commands.append("0 0 0 rg 0 0 0 RG")


def _draw_pdf_reliability_curve(
    commands: list[str], x: float, y: float, width: float, height: float, report: dict[str, object]
) -> None:
    curve = report["curve"]
    if not curve:
        return
    values = [(float(point["tank_size"]), float(point["reliability"])) for point in curve]
    x_domain = [v[0] for v in values]
    if report["selected_reliability"] is not None:
        x_domain.append(float(report["selected_tank_size"]))
    x_min = min(x_domain)
    x_max = max(x_domain)
    if x_min == x_max:
        x_max = x_min + 1

    def sx(value: float) -> float:
        return x + ((value - x_min) / (x_max - x_min)) * width

    def sy(value: float) -> float:
        return y + (max(0.0, min(value, 100.0)) / 100.0) * height

    commands.append("0.50 w 0.85 0.85 0.85 RG")
    for i in range(6):
        gy = y + (height * i / 5)
        commands.append(f"{x:.2f} {gy:.2f} m {x + width:.2f} {gy:.2f} l S")
    commands.append("0 0 0 RG 0.75 w")
    commands.append(f"{x:.2f} {y:.2f} m {x:.2f} {y + height:.2f} l S")
    commands.append(f"{x:.2f} {y:.2f} m {x + width:.2f} {y:.2f} l S")
    for i in range(6):
        tick_y = y + (height * i / 5)
        label = _pdf_escape(f"{i * 20}")
        commands.append(f"BT /F1 8 Tf 1 0 0 1 {x - 24:.2f} {tick_y - 3:.2f} Tm ({label}) Tj ET")
    for i in range(5):
        value = x_min + ((x_max - x_min) * i / 4)
        tick_x = x + (width * i / 4)
        label = _pdf_escape(f"{value:.0f}")
        commands.append(f"BT /F1 8 Tf 1 0 0 1 {tick_x - 12:.2f} {y - 18:.2f} Tm ({label}) Tj ET")
    commands.append(f"BT /F2 10 Tf 1 0 0 1 {x + width / 2 - 56:.2f} {y + height + 18:.2f} Tm (Reliability Curve) Tj ET")
    commands.append(f"BT /F2 9 Tf 1 0 0 1 {x + width / 2 - 44:.2f} {y - 36:.2f} Tm (Tank size ({_pdf_escape(report['volume_unit'])})) Tj ET")
    commands.append(f"BT /F2 9 Tf 0 1 -1 0 {x - 38:.2f} {y + height / 2 - 28:.2f} Tm (Reliability %) Tj ET")
    points = [(sx(tank), sy(reliability)) for tank, reliability in values]
    if len(points) >= 2:
        path = [f"{points[0][0]:.2f} {points[0][1]:.2f} m"]
        path.extend(f"{px:.2f} {py:.2f} l" for px, py in points[1:])
        commands.append("0.04 0.36 0.67 RG 1.50 w " + " ".join(path) + " S")
    commands.append("0.04 0.36 0.67 rg")
    for px, py in points:
        commands.append(f"{px - 1.5:.2f} {py - 1.5:.2f} {3:.2f} {3:.2f} re f")
    if report["selected_reliability"] is not None:
        px = sx(float(report["selected_tank_size"]))
        py = sy(float(report["selected_reliability"]))
        radius = 6.0
        control = radius * 0.55228475
        commands.append(
            "0.84 0.05 0.08 RG 2.25 w "
            f"{px + radius:.2f} {py:.2f} m "
            f"{px + radius:.2f} {py + control:.2f} {px + control:.2f} {py + radius:.2f} {px:.2f} {py + radius:.2f} c "
            f"{px - control:.2f} {py + radius:.2f} {px - radius:.2f} {py + control:.2f} {px - radius:.2f} {py:.2f} c "
            f"{px - radius:.2f} {py - control:.2f} {px - control:.2f} {py - radius:.2f} {px:.2f} {py - radius:.2f} c "
            f"{px + control:.2f} {py - radius:.2f} {px + radius:.2f} {py - control:.2f} {px + radius:.2f} {py:.2f} c S"
        )
        legend_x = x + width - 128
        legend_y = y + height - 14
        legend_radius = 4.0
        legend_control = legend_radius * 0.55228475
        commands.append(
            "0.84 0.05 0.08 RG 1.50 w "
            f"{legend_x + legend_radius:.2f} {legend_y:.2f} m "
            f"{legend_x + legend_radius:.2f} {legend_y + legend_control:.2f} "
            f"{legend_x + legend_control:.2f} {legend_y + legend_radius:.2f} "
            f"{legend_x:.2f} {legend_y + legend_radius:.2f} c "
            f"{legend_x - legend_control:.2f} {legend_y + legend_radius:.2f} "
            f"{legend_x - legend_radius:.2f} {legend_y + legend_control:.2f} "
            f"{legend_x - legend_radius:.2f} {legend_y:.2f} c "
            f"{legend_x - legend_radius:.2f} {legend_y - legend_control:.2f} "
            f"{legend_x - legend_control:.2f} {legend_y - legend_radius:.2f} "
            f"{legend_x:.2f} {legend_y - legend_radius:.2f} c "
            f"{legend_x + legend_control:.2f} {legend_y - legend_radius:.2f} "
            f"{legend_x + legend_radius:.2f} {legend_y - legend_control:.2f} "
            f"{legend_x + legend_radius:.2f} {legend_y:.2f} c S"
        )
        commands.append(
            f"0 0 0 rg BT /F1 8 Tf 1 0 0 1 {legend_x + 9:.2f} {legend_y - 3:.2f} "
            "Tm (Primary tank size) Tj ET"
        )
    commands.append("0 0 0 rg 0 0 0 RG")


def _write_pdf_with_pypdf(
    pdf_path: Path,
    pages: list[list[str]],
    section_pages: dict[str, int] | None = None,
    toc_links: list[tuple[tuple[float, float, float, float], str]] | None = None,
) -> None:
    writer = PdfWriter()
    regular_font = writer._add_object(
        DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
    )
    bold_font = writer._add_object(
        DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica-Bold"),
            }
        )
    )
    resources = DictionaryObject(
        {
            NameObject("/Font"): DictionaryObject(
                {
                    NameObject("/F1"): regular_font,
                    NameObject("/F2"): bold_font,
                }
            )
        }
    )

    for page_commands in pages:
        page = writer.add_blank_page(width=612, height=792)
        page[NameObject("/Resources")] = resources
        content = DecodedStreamObject()
        content.set_data("\n".join(page_commands).encode("latin-1", errors="replace"))
        page[NameObject("/Contents")] = writer._add_object(content)

    for title, page_index in (section_pages or {}).items():
        writer.add_outline_item(title, page_index)
    for rect, title in toc_links or []:
        target_page = (section_pages or {}).get(title)
        if target_page is not None:
            writer.add_annotation(0, Link(rect=rect, target_page_index=target_page))

    with pdf_path.open("wb") as handle:
        writer.write(handle)
