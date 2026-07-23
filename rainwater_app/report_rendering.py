"""HTML and LaTeX report renderers with no UI-toolkit dependency."""

from __future__ import annotations

import html
import json
import math
import re

import pandas as pd

from .number_formatting import format_number
from .reporting import (
    REPORT_SECTION_DEFINITIONS,
    ReportModel,
    latex_escape as _latex_escape,
    latex_number as _latex_number,
    latex_row as _latex_row,
)


def _enabled_report_section_keys(report: ReportModel) -> set[str]:
    choices = report["report_sections"]
    return {key for key, enabled in choices.items() if enabled}


def _filter_latex_report_sections(document: str, report: ReportModel) -> str:
    enabled = _enabled_report_section_keys(report)
    for key, _label, _html_id, title in REPORT_SECTION_DEFINITIONS:
        if key in enabled:
            continue
        title_pattern = re.escape(title)
        if key == "yearly_demand_reliability":
            title_pattern += r"[^}]*"
        document = re.sub(
            rf"\n\\section\{{{title_pattern}\}}.*?(?=\n\\section\{{|\n\\end\{{document\}})",
            "",
            document,
            flags=re.DOTALL,
        )
    return document


def _filter_html_report_sections(document: str, report: ReportModel) -> str:
    enabled = _enabled_report_section_keys(report)
    for key, _label, html_id, _title in REPORT_SECTION_DEFINITIONS:
        if key in enabled:
            continue
        document = re.sub(
            rf'<section id="{re.escape(html_id)}"[^>]*>.*?</section>',
            "",
            document,
            flags=re.DOTALL,
        )
        document = re.sub(
            rf'<li><a href="#{re.escape(html_id)}">.*?</a></li>',
            "",
            document,
            flags=re.DOTALL,
        )
    return document


def render_latex(
    report: ReportModel | dict[str, object]
) -> str:
    report = ReportModel.from_payload(report)
    metadata = report["metadata"]
    area = report["area_unit"]
    volume = report["volume_unit"]
    report_title = "RWH Calculator Report - multi-tank" if report.get("include_multitank_charts") else "RWH Calculator Report"
    surface_rows = "\n".join(
        _latex_row(
            surface["name"],
            format_number(surface["area"]),
            format_number(surface["runoff_coefficient"]),
            format_number(surface.get("first_flush_depth", 0.0), max_decimal_places=3),
        )
        for surface in report["surfaces"]
    )
    if not surface_rows:
        surface_rows = _latex_row("No collection surfaces", "0.00", "0.000", "0.000")
    rainfall_volumes = report.get("average_annual_rainfall_volumes", {})
    rainfall_volume_rows_latex = "\n".join(
        _latex_row(label, f'{format_number(float(rainfall_volumes.get(key, 0.0)), max_decimal_places=0)} {volume}/year')
        for label, key in (
            ("Total average rain", "total_average_rain"),
            ("Average first-flush diversion", "average_first_flush_diversion"),
            ("Total usable average rain", "total_usable_average_rain"),
        )
    )
    demand_rows = "\n".join(
        _latex_row(
            report["monthly_demand"][index]["month"],
            format_number(report['monthly_demand'][index]['demand_per_day'], max_decimal_places=0),
            format_number(report['monthly_demand'][index]['demand_per_month'], max_decimal_places=0),
            report["monthly_demand"][index + 6]["month"],
            format_number(report['monthly_demand'][index + 6]['demand_per_day'], max_decimal_places=0),
            format_number(report['monthly_demand'][index + 6]['demand_per_month'], max_decimal_places=0),
        )
        for index in range(6)
    )
    recommendation_rows_latex = "\n".join(
        _latex_row(
            item.get("role", "Recommendation"),
            f'{format_number(float(item.get("tank_size", 0.0)), max_decimal_places=0)} {item.get("volume_unit", volume)}',
            f'{format_number(float(item.get("reliability_percent", 0.0)), max_decimal_places=1)}%',
            item.get("detail", ""),
        )
        for item in report.get("recommendations", [])
    )
    if not recommendation_rows_latex:
        recommendation_rows_latex = _latex_row(
            "No recommendation available", "--", "--", "Rerun the candidate analysis."
        )
    assumptions = report.get("recommendation_assumptions", {})
    recommendation_assumptions_latex = _latex_escape(
        f'Reliability target: {format_number(float(assumptions.get("reliability_target_percent", 90.0)), max_decimal_places=1)}%. '
        f'Diminishing-return threshold: {format_number(float(assumptions.get("marginal_gain_threshold", 1.0)))} '
        "reliability percentage points per 1,000 gallons."
    )
    warnings_latex = "\n".join(
        rf"\item {_latex_escape(warning)}" for warning in report.get("review_warnings", [])
    ) or r"\item No configured review conditions were triggered."
    executive = report.get("executive_summary", {})
    executive_rows_latex = "\n".join(
        _latex_row(label, value)
        for label, value in (
            (
                "Average annual precipitation",
                f'{format_number(float(report["average_annual_precipitation"]))} {report["precipitation_unit"]}',
            ),
            ("Precipitation basis", report["precipitation_basis"]),
            ("Selected tank", f'{format_number(float(report["selected_tank_size"]), max_decimal_places=0)} {volume}'),
            ("Selected reliability", f'{format_number(float(report.get("selected_reliability") or 0.0))}%'),
            ("Average annual rainwater supply", f'{format_number(float(executive.get("average_annual_supply", 0.0)), max_decimal_places=0)} {volume}/year'),
            ("Average annual municipal makeup", f'{format_number(float(executive.get("average_annual_municipal_makeup", 0.0)), max_decimal_places=0)} {volume}/year'),
            ("Average annual overflow", f'{format_number(float(executive.get("average_annual_overflow", 0.0)), max_decimal_places=0)} {volume}/year'),
            ("Net annual savings", f'{report.get("financial_summary", {}).get("currency", "USD")} {format_number(float(executive.get("net_annual_savings", 0.0)))}/year'),
            ("Simple payback", f'{format_number(float(executive["simple_payback_years"]), max_decimal_places=1)} years' if executive.get("simple_payback_years") is not None else "Not achieved"),
        )
    )
    candidate_rows_latex = "\n".join(
        _latex_row(
            format_number(float(row.get("tank_size", 0.0)), max_decimal_places=0),
            f'{format_number(float(row.get("reliability", 0.0)), max_decimal_places=1)}%',
            "--" if row.get("RainwaterSuppliedGallons") is None else format_number(float(row["RainwaterSuppliedGallons"]), max_decimal_places=0),
            "--" if row.get("OverflowGallons") is None else format_number(float(row["OverflowGallons"]), max_decimal_places=0),
            "--" if row.get("SimplePaybackYears") is None else f'{format_number(float(row["SimplePaybackYears"]), max_decimal_places=1)} years',
        )
        for row in report.get("candidate_performance", [])
    ) or _latex_row("No candidate results", "--", "--", "--", "--")
    balance = report.get("water_balance", {})
    balance_rows_latex = "\n".join(
        _latex_row(label, f'{format_number(float(balance.get(key, 0.0)), max_decimal_places=1)} {volume}')
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
        )
    )
    end_use_rows_latex = "\n".join(
        _latex_row(
            row.get("name", ""),
            row.get("type", ""),
            format_number(float(row.get("annual_demand", 0.0)), max_decimal_places=0),
            format_number(float(row.get("annual_supply", 0.0)), max_decimal_places=0),
            f'{format_number(float(row.get("demand_met_percent", 0.0)), max_decimal_places=1)}%',
        )
        for row in report.get("end_use_rows", [])
    ) or _latex_row("No demand objects", "--", "--", "--", "--")
    financial = report.get("financial_summary", {})
    financial_rows_latex = "\n".join(
        _latex_row(label, value)
        for label, value in (
            ("Configured", "Yes" if financial.get("configured") else "No"),
            ("Water tariff", f'{financial.get("currency", "USD")} {format_number(float(financial.get("water_rate", 0.0)), max_decimal_places=4)} {financial.get("tariff_billing_unit", "")}'),
            ("Sewer tariff", f'{financial.get("currency", "USD")} {format_number(float(financial.get("sewer_rate", 0.0)), max_decimal_places=4)} {financial.get("tariff_billing_unit", "")}'),
            ("Installed cost", f'{financial.get("currency", "USD")} {format_number(float(financial.get("installed_cost", 0.0)))}'),
            ("Net annual savings", f'{financial.get("currency", "USD")} {format_number(float(financial.get("net_annual_savings", 0.0)))}'),
            ("Simple payback", f'{format_number(float(financial["simple_payback_years"]), max_decimal_places=1)} years' if financial.get("simple_payback_years") is not None else "Not achieved"),
            ("Discount rate", f'{format_number(float(financial.get("discount_rate_percent", 0.0)))}%'),
            ("Lifecycle NPV", f'{financial.get("currency", "USD")} {format_number(float(financial.get("lifecycle_net_present_value", 0.0)))}'),
            ("IRR", f'{format_number(float(financial["internal_rate_of_return_percent"]))}%' if financial.get("internal_rate_of_return_percent") is not None else "Not uniquely defined"),
            ("Discounted payback", f'{format_number(float(financial["discounted_payback_years"]), max_decimal_places=1)} years' if financial.get("discounted_payback_years") is not None else "Not achieved"),
            ("Methodology", financial.get("methodology", "")),
        )
    )
    cash_flows = [float(value) for value in financial.get("annual_cash_flows", [])]
    discount_rate = float(financial.get("discount_rate_percent", 0.0)) / 100.0
    cumulative_discounted = 0.0
    cash_flow_rows_latex: list[str] = []
    for year, nominal in enumerate(cash_flows):
        discounted = nominal / ((1.0 + discount_rate) ** year)
        cumulative_discounted += discounted
        cash_flow_rows_latex.append(
            _latex_row(
                year,
                f'{financial.get("currency", "USD")} {format_number(nominal)}',
                f'{financial.get("currency", "USD")} {format_number(discounted)}',
                f'{financial.get("currency", "USD")} {format_number(cumulative_discounted)}',
            )
        )
    financial_cash_flow_rows_latex = "\n".join(cash_flow_rows_latex) or _latex_row(
        "No cash-flow schedule", "--", "--", "--"
    )
    provenance = report.get("provenance", {})
    rainfall_quality = report.get("rainfall_quality", {})
    rainfall_quality_rows_latex = "\n".join(
        _latex_row(label, value)
        for label, value in (
            ("Completeness score", f'{format_number(float(rainfall_quality.get("completeness_percent", 0.0)))}% ({rainfall_quality.get("completeness_rating", "Not rated")})'),
            ("Calendar-day coverage", f'{format_number(int(rainfall_quality.get("observed_days", 0)), max_decimal_places=0)} observed of {format_number(int(rainfall_quality.get("expected_days", 0)), max_decimal_places=0)} expected'),
            ("Missing days", format_number(int(rainfall_quality.get("missing_days", 0)), max_decimal_places=0)),
            ("Partial/incomplete years", ", ".join(str(value) for value in rainfall_quality.get("partial_years", [])) or "None"),
            ("Duplicate dates", f'{int(rainfall_quality.get("duplicate_dates", 0)):,}'),
            ("Invalid precipitation rows", f'{int(rainfall_quality.get("invalid_precipitation_rows", 0)):,}'),
        )
    )
    missing_period_rows_latex = "\n".join(
        _latex_row(row.get("start", ""), row.get("end", ""), row.get("days", 0))
        for row in rainfall_quality.get("missing_periods", [])[:20]
    ) or _latex_row("No missing periods", "--", "--")
    yearly_rainfall_rows_latex = "\n".join(
        _latex_row(
            row.get("year", ""),
            row.get("observed_days", 0),
            row.get("missing_days", 0),
            f'{format_number(float(row.get("completeness_percent", 0.0)))}%',
            format_number(float(row.get("precipitation", 0.0))),
            row.get("wet_days", 0),
            "Partial" if row.get("partial_year") else "Complete",
        )
        for row in report.get("yearly_rainfall_summary", [])
    ) or _latex_row("No yearly summary", "--", "--", "--", "--", "--", "--")
    event_summary = report.get("rainfall_event_summary", {})
    rainfall_event_rows_latex = "\n".join(
        _latex_row(
            row.get("event_number", ""),
            row.get("start", ""),
            row.get("end", ""),
            row.get("duration_days", 0),
            row.get("wet_days", 0),
            format_number(float(row.get("precipitation", 0.0)), max_decimal_places=3),
        )
        for row in event_summary.get("largest_events", [])
    ) or _latex_row("No wet-weather events", "--", "--", "--", "--", "--")
    first_flush_yearly_rows_latex = "\n".join(
        _latex_row(
            row.get("year", ""),
            row.get("event_count", 0),
            format_number(float(row.get("gross_runoff", 0.0))),
            format_number(float(row.get("first_flush_loss", 0.0))),
            format_number(float(row.get("net_collected", 0.0))),
            f'{format_number(float(row.get("diversion_percent", 0.0)))}%',
        )
        for row in report.get("first_flush_yearly_summary", [])
    ) or _latex_row("No yearly first-flush summary", "--", "--", "--", "--", "--")
    first_flush_event_rows_latex = "\n".join(
        _latex_row(
            row.get("event_id", ""),
            row.get("start", ""),
            row.get("end", ""),
            row.get("wet_timesteps", 0),
            format_number(float(row.get("gross_runoff", 0.0))),
            format_number(float(row.get("first_flush_loss", 0.0))),
            format_number(float(row.get("net_collected", 0.0))),
            f'{format_number(float(row.get("diversion_percent", 0.0)))}%',
        )
        for row in report.get("first_flush_event_summary", [])
    ) or _latex_row("No event-level first-flush summary", "--", "--", "--", "--", "--", "--", "--")
    provenance_rows_latex = "\n".join(
        _latex_row(label, value)
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
            ("Rainfall timing", provenance.get("rainfall_timing_assumption", "Not specified")),
            ("Demand timing", provenance.get("demand_timing_assumption", "Not specified")),
            ("Application / algorithm", f'{provenance.get("application_version", "Unknown")} / {provenance.get("algorithm_version", "Unknown")}'),
            ("Report schema", provenance.get("report_schema_version", report["schema_version"])),
            ("Analysis signature", provenance.get("analysis_input_signature", "Not stored")),
            ("Generated", provenance.get("generated_at", "Not available")),
        )
    )

    coordinates = "\n".join(
        f"({_latex_number(point['tank_size'])},{_latex_number(point['reliability'])})"
        for point in report["curve"]
    )
    project_coordinate_rows_latex = ""
    if report.get("project_latitude") is not None and report.get("project_longitude") is not None:
        project_coordinate_rows_latex += (
            r"\textbf{Project location coordinates} & "
            f"{float(report['project_latitude']):.6f}, "
            f"{float(report['project_longitude']):.6f} \\\\\n"
        )
    if report.get("weather_station_latitude") is not None and report.get("weather_station_longitude") is not None:
        project_coordinate_rows_latex += (
            r"\textbf{Weather station coordinates} & "
            f"{float(report['weather_station_latitude']):.6f}, "
            f"{float(report['weather_station_longitude']):.6f} \\\\\n"
        )
    author_line = ""
    if metadata.get("author_name", "").strip():
        author_line = rf"\noindent\textbf{{Produced by:}} {_latex_escape(metadata['author_name'])}\par\medskip"
    notes_latex = _latex_escape(report.get("notes", "").strip() or "No notes provided.")
    notes_latex = notes_latex.replace("\n\n", r"\par\medskip ").replace("\n", r"\par ")
    selected_marker = ""
    if report["selected_reliability"] is not None:
        selected_marker = rf"""
\addplot+[only marks, mark=o, red, mark size=7pt, very thick] coordinates {{
({_latex_number(report['selected_tank_size'])},{_latex_number(report['selected_reliability'])})
}};
\addlegendimage{{only marks, mark=o, red, mark size=5pt, very thick}}
\addlegendentry{{Primary tank size}}
"""
    yearly_met_coordinates = " ".join(
        f"({_latex_number(row['year'])},{_latex_number(row['met_percent'])})"
        for row in report["yearly_reliability"]
    )
    yearly_unmet_coordinates = " ".join(
        f"({_latex_number(row['year'])},{_latex_number(row['unmet_percent'])})"
        for row in report["yearly_reliability"]
    )
    yearly_average_label = "Average"
    yearly_average_reliability = float(report["selected_reliability"] or 0.0)
    yearly_marker_coordinates = " ".join(
        [
            *(
                f"({_latex_number(row['year'])},{_latex_number(row['met_percent'])})"
                for row in report["yearly_reliability"]
            ),
            f"({yearly_average_label},{_latex_number(yearly_average_reliability)})",
        ]
    )
    yearly_met_coordinates += f" ({yearly_average_label},0)"
    yearly_unmet_coordinates += f" ({yearly_average_label},0)"
    yearly_symbolic_coordinates = ",".join(
        [*(str(int(row["year"])) for row in report["yearly_reliability"]), yearly_average_label]
    )
    distribution_coordinates = " ".join(
        f"({_latex_number(index + 1)},{_latex_number(row['count'])})"
        for index, row in enumerate(report["tank_level_distribution"])
    )
    distribution_labels = ",".join(
        _latex_escape(f"{format_number(float(row['low']), max_decimal_places=0)}-{format_number(float(row['high']), max_decimal_places=0)}")
        for row in report["tank_level_distribution"]
    )
    multitank_latex = ""
    if report.get("include_multitank_charts"):
        for chart in report.get("multitank_charts", []):
            if chart.get("type") == "yearly_stacked":
                yearly_rows = chart["yearly_reliability"]
                symbolic = ",".join(
                    [*(str(int(row["year"])) for row in yearly_rows), "Average"]
                )
                met_points = " ".join(
                    [
                        *(f"({int(row['year'])},{_latex_number(row['met_percent'])})" for row in yearly_rows),
                        "(Average,0)",
                    ]
                )
                unmet_points = " ".join(
                    [
                        *(f"({int(row['year'])},{_latex_number(row['unmet_percent'])})" for row in yearly_rows),
                        "(Average,0)",
                    ]
                )
                marker_points = " ".join(
                    [
                        *(f"({int(row['year'])},{_latex_number(row['met_percent'])})" for row in yearly_rows),
                        f"(Average,{_latex_number(chart['selected_reliability'])})",
                    ]
                )
                multitank_latex += rf"""
\clearpage
\section{{{_latex_escape(chart['title'])}}}
\begin{{center}}
\begin{{tikzpicture}}
\begin{{axis}}[
width=6.6in,height=3.8in,ybar stacked,ymin=0,ymax=100,
ylabel={{Days (\%)}},xlabel={{Year}},symbolic x coords={{{symbolic}}},xtick=data,
label style={{font=\bfseries\normalsize}},
x tick label style={{rotate=45,anchor=east,font=\scriptsize}},
legend style={{at={{(0.5,-0.25)}},anchor=north,legend columns=3}},grid=major,
]
\addplot+[fill=green!65!black,draw=green!45!black] coordinates {{{met_points}}};
\addlegendentry{{Demand met}}
\addplot+[fill=red!65,draw=red!60!black] coordinates {{{unmet_points}}};
\addlegendentry{{Demand not met}}
\addplot+[only marks,mark=*,mark size=3pt,fill=yellow!80!orange,draw=yellow!40!black]
coordinates {{{marker_points}}};
\addlegendentry{{Tank reliability}}
\end{{axis}}
\end{{tikzpicture}}
\par\small The Average marker reports tank reliability across {len(yearly_rows)} analyzed years.
\end{{center}}
"""
                continue
            plots = []
            legends = []
            for series in chart["series"]:
                coordinates_text = " ".join(
                    f"({_latex_number(x_value)},{_latex_number(y_value)})"
                    for x_value, y_value in series["points"]
                )
                plots.append(rf"\addplot+[thick, no marks] coordinates {{{coordinates_text}}};")
                legends.append(_latex_escape(series["label"]))
            multitank_latex += rf"""
\clearpage
\section{{{_latex_escape(chart['title'])}}}
\begin{{center}}
\begin{{tikzpicture}}
\begin{{axis}}[
width=6.6in,
height=3.8in,
xlabel={{{_latex_escape(chart['x_label'])}}},
ylabel={{{_latex_escape(chart['y_label'])}}},
label style={{font=\bfseries\normalsize}},
ymin=0,
grid=major,
legend style={{at={{(0.5,-0.25)}}, anchor=north, legend columns=3}},
]
{chr(10).join(plots)}
\legend{{{','.join(legends)}}}
\end{{axis}}
\end{{tikzpicture}}
\end{{center}}
"""

    system_visualization_latex = ""
    if report.get("include_system_visualization"):
        system_type = _latex_escape(report.get("system_type", "Direct system"))
        if report.get("system_type") == "Indirect system":
            equipment = r"""
\draw (2.2,1.0) -- (2.9,1.0); \draw (3.25,1.0) circle (0.35);
\draw (3.60,1.0) -- (3.075,1.303) -- (3.075,0.697) -- cycle;
\node[below] at (3.25,0.55) {Transfer pump};
\draw (3.60,1.0) -- (4.2,1.0); \draw (4.2,0.7) rectangle (5.5,1.3);
\node at (4.85,1.0) {Filtration}; \draw (5.5,1.0) -- (6.1,1.0);
\draw (6.1,0.35) rectangle (7.7,1.65); \node at (6.9,1.4) {Buffer tank};
\draw[->,>=stealth] (6.9,2.45) -- (6.9,1.65); \node[left] at (6.85,2.1) {Municipal water backup};
\draw (7.7,1.0) -- (7.9,1.0); \draw (8.2,1.0) circle (0.3);
\draw (8.5,1.0) -- (8.05,1.26) -- (8.05,0.74) -- cycle;
\node[below] at (8.2,0.6) {Booster pump};
\draw[->,>=stealth] (8.5,1.0) -- (9.7,1.0); \node[above] at (9.1,1.0) {Flow to end-uses};
"""
        else:
            equipment = r"""
\draw (2.2,1.0) -- (3.2,1.0); \draw (3.55,1.0) circle (0.35);
\draw (3.90,1.0) -- (3.3,1.18) -- (3.3,0.82) -- cycle;
\node[below] at (3.55,0.55) {Distribution pump};
\draw[->,>=stealth] (3.90,1.0) -- (7.2,1.0); \node[above] at (5.55,1.0) {Flow directly to end-uses};
"""
        system_visualization_latex = rf"""
\section{{System Visualization - {system_type}}}
\begin{{center}}\begin{{tikzpicture}}[line width=1pt,font=\small]
\draw (0,0.25) rectangle (2.2,1.75); \node[font=\bfseries] at (1.1,1.48) {{Primary tank}};
\node at (1.1,1.22) {{{_latex_number(report['selected_tank_size'])} {_latex_escape(volume)}}};
\draw[domain=0:2.2,samples=45,smooth] plot (\x,{{0.92+0.05*sin(720*\x)}});
{equipment}\end{{tikzpicture}}\end{{center}}
"""

    document = rf"""\documentclass[11pt]{{article}}
\usepackage[margin=0.75in]{{geometry}}
\usepackage{{booktabs}}
\usepackage{{pgfplots}}
\usepackage{{longtable}}
\usepackage{{array}}
\usepackage[hidelinks]{{hyperref}}
\pgfplotsset{{compat=1.18}}

\title{{{_latex_escape(report_title)}}}
\date{{}}

\begin{{document}}
\maketitle
{author_line}
\tableofcontents
\newpage

\section{{Design Recommendations and Review Conditions}}
\noindent {recommendation_assumptions_latex}\par
\noindent These decision aids compare the simulated candidates under the stated assumptions; they are not a universal optimum.
\begin{{longtable}}{{@{{}}p{{1.55in}}rrp{{2.65in}}@{{}}}}
\toprule
Decision aid & Tank size & Reliability & Basis and tradeoff \\
\midrule
{recommendation_rows_latex}
\bottomrule
\end{{longtable}}
\subsection*{{Review conditions}}
\begin{{itemize}}
{warnings_latex}
\end{{itemize}}

\section{{Project Information}}
\begin{{tabular}}{{@{{}}p{{1.6in}}p{{4.8in}}@{{}}}}
\textbf{{Client name}} & {_latex_escape(metadata["client_name"])} \\
\textbf{{Date}} & {_latex_escape(metadata["date"])} \\
\textbf{{Location}} & {_latex_escape(metadata["location"])} \\
{project_coordinate_rows_latex}
\textbf{{Project name}} & {_latex_escape(metadata["project_name"])} \\
\textbf{{End-uses of water}} & {_latex_escape(metadata["end_uses"])} \\
\end{{tabular}}

\section{{Executive Summary}}
\begin{{longtable}}{{@{{}}p{{2.8in}}p{{3.5in}}@{{}}}}
\toprule
Metric & Result \\
\midrule
{executive_rows_latex}
\bottomrule
\end{{longtable}}

\section{{Notes}}
{notes_latex}

\section{{Surface Area Summary}}
\begin{{longtable}}{{@{{}}p{{2.4in}}rrr@{{}}}}
\toprule
Surface & Area ({_latex_escape(area)}) & Runoff coefficient & First flush ({_latex_escape(report['precipitation_unit'])}) \\
\midrule
{surface_rows}
\bottomrule
\end{{longtable}}

\noindent First-flush event dry-period threshold: {_latex_number(report.get('first_flush_antecedent_dry_value', report.get('first_flush_antecedent_dry_days', 1.0)))} {_latex_escape(str(report.get('first_flush_antecedent_dry_unit', 'days')))}. Events: {int(report.get('first_flush_event_count', 0))}. Diverted volume: {_latex_number(report.get('first_flush_loss', 0.0))} {_latex_escape(volume)}.

\section{{Rainfall Volume Summary}}
\begin{{longtable}}{{@{{}}p{{3.4in}}r@{{}}}}
\toprule
Average annual volume & Value \\
\midrule
{rainfall_volume_rows_latex}
\bottomrule
\end{{longtable}}

\noindent Total average rain is gross runoff after surface runoff coefficients and before first flush. Total usable average rain is the net collected volume after first-flush diversion.

\section{{Tank Summary}}
\begin{{tabular}}{{@{{}}lr@{{}}}}
\toprule
Tank property & Value \\
\midrule
Size & {_latex_number(report['selected_tank_size'])} {_latex_escape(volume)} \\
\bottomrule
\end{{tabular}}

\section{{Candidate Performance}}
\small
\begin{{longtable}}{{@{{}}rrrrr@{{}}}}
\toprule
Tank size ({_latex_escape(volume)}) & Reliability & Supply/year & Overflow/year & Payback \\
\midrule
{candidate_rows_latex}
\bottomrule
\end{{longtable}}
\normalsize

\section{{Reconciled Water Balance}}
\begin{{longtable}}{{@{{}}p{{3.2in}}r@{{}}}}
\toprule
Balance item & Volume \\
\midrule
{balance_rows_latex}
\bottomrule
\end{{longtable}}

{system_visualization_latex}

\section{{Demand Summary}}
\small
\begin{{tabular}}{{@{{}}lrrlrr@{{}}}}
\toprule
Month & Demand ({_latex_escape(volume)}/day) & Demand ({_latex_escape(volume)}/month) & Month & Demand ({_latex_escape(volume)}/day) & Demand ({_latex_escape(volume)}/month) \\
\midrule
{demand_rows}
\midrule
\addlinespace[1pt]
\midrule
\multicolumn{{5}}{{r}}{{\textbf{{Total Annual Demand}}}} & \textbf{{{_latex_escape(format_number(float(report['total_annual_demand']), max_decimal_places=0))} {_latex_escape(volume)}}} \\
\bottomrule
\end{{tabular}}
\normalsize

\section{{End-use Performance}}
\small
\begin{{longtable}}{{@{{}}p{{1.7in}}p{{1.0in}}rrr@{{}}}}
\toprule
End use & Type & Demand/year & Supply/year & Demand met \\
\midrule
{end_use_rows_latex}
\bottomrule
\end{{longtable}}
\normalsize

\section{{Financial Analysis}}
\begin{{longtable}}{{@{{}}p{{2.2in}}p{{4.0in}}@{{}}}}
\toprule
Assumption or result & Value \\
\midrule
{financial_rows_latex}
\bottomrule
\end{{longtable}}

\subsection*{{Annual lifecycle cash flow}}
\begin{{longtable}}{{@{{}}rrrr@{{}}}}
\toprule
Year & Nominal net cash flow & Discounted cash flow & Cumulative discounted cash flow \\
\midrule
{financial_cash_flow_rows_latex}
\bottomrule
\end{{longtable}}

\section{{Rainfall Quality and Completeness}}
\begin{{longtable}}{{@{{}}p{{2.5in}}p{{3.7in}}@{{}}}}
\toprule
Quality measure & Result \\
\midrule
{rainfall_quality_rows_latex}
\bottomrule
\end{{longtable}}
\subsection*{{Missing periods (up to 20)}}
\begin{{longtable}}{{@{{}}llr@{{}}}}
\toprule
Start & End & Days \\
\midrule
{missing_period_rows_latex}
\bottomrule
\end{{longtable}}

\section{{Yearly Rainfall Summary}}
\scriptsize
\begin{{longtable}}{{@{{}}rrrrrrl@{{}}}}
\toprule
Year & Observed & Missing & Complete & Precip. ({_latex_escape(report['precipitation_unit'])}) & Wet days & Status \\
\midrule
{yearly_rainfall_rows_latex}
\bottomrule
\end{{longtable}}
\normalsize

\section{{Rainfall-event Summary}}
\noindent {int(event_summary.get('event_count', 0))} event(s) were identified using an antecedent dry threshold of {_latex_number(event_summary.get('antecedent_dry_days', 1.0))} day(s). Average event precipitation: {_latex_number(event_summary.get('average_event_precipitation', 0.0))} {_latex_escape(report['precipitation_unit'])}; largest event: {_latex_number(event_summary.get('largest_event_precipitation', 0.0))} {_latex_escape(report['precipitation_unit'])}.
\scriptsize
\begin{{longtable}}{{@{{}}rllrrr@{{}}}}
\toprule
Event & Start & End & Duration & Wet days & Precip. \\
\midrule
{rainfall_event_rows_latex}
\bottomrule
\end{{longtable}}
\normalsize

\section{{First-flush Diversion Summary}}
\noindent Event counts are assigned to the calendar year in which each rainfall event starts. Volumes use the complete simulated record and reconcile gross runoff less first-flush diversion to net collected water.
\subsection*{{Yearly totals}}
\scriptsize
\begin{{longtable}}{{@{{}}rrrrrr@{{}}}}
\toprule
Year & Events & Gross ({_latex_escape(volume)}) & Diverted ({_latex_escape(volume)}) & Net ({_latex_escape(volume)}) & Diverted \% \\
\midrule
{first_flush_yearly_rows_latex}
\bottomrule
\end{{longtable}}
\subsection*{{Rainfall-event totals}}
\begin{{longtable}}{{@{{}}rllrrrrr@{{}}}}
\toprule
Event & Start & End & Wet steps & Gross & Diverted & Net & Diverted \% \\
\midrule
{first_flush_event_rows_latex}
\bottomrule
\end{{longtable}}
\normalsize

\section{{Analysis Provenance}}
\begin{{longtable}}{{@{{}}p{{2.2in}}p{{4.0in}}@{{}}}}
\toprule
Provenance item & Value \\
\midrule
{provenance_rows_latex}
\bottomrule
\end{{longtable}}

\section{{Reliability Curve}}
\begin{{center}}
\begin{{tikzpicture}}
\begin{{axis}}[
width=6.6in,
height=3.8in,
xlabel={{Tank size ({_latex_escape(volume)})}},
ylabel={{Reliability (\%)}},
label style={{font=\bfseries\normalsize}},
ymin=0,
ymax=100,
grid=major,
mark=*,
legend style={{at={{(0.5,-0.22)}}, anchor=north}},
]
\addplot+[blue, thick] coordinates {{
{coordinates}
}};
{selected_marker}
\end{{axis}}
\end{{tikzpicture}}
\end{{center}}

\section{{Yearly Demand Reliability - {_latex_number(report['selected_tank_size'])} {_latex_escape(volume)} tank}}
\begin{{center}}
\begin{{tikzpicture}}
\begin{{axis}}[
width=6.6in,
height=3.8in,
ybar stacked,
ymin=0,
ymax=100,
ylabel={{Days (\%)}},
xlabel={{Year}},
label style={{font=\bfseries\normalsize}},
symbolic x coords={{{yearly_symbolic_coordinates}}},
xtick=data,
x tick label style={{rotate=45, anchor=east, font=\scriptsize}},
legend style={{at={{(0.5,-0.25)}}, anchor=north, legend columns=3}},
grid=major,
]
\addplot+[fill=green!65!black, draw=green!45!black] coordinates {{{yearly_met_coordinates}}};
\addlegendentry{{Demand met}}
\addplot+[fill=red!65, draw=red!60!black] coordinates {{{yearly_unmet_coordinates}}};
\addlegendentry{{Demand not met}}
\addplot+[only marks, mark=*, mark size=3pt, fill=yellow!80!orange, draw=yellow!40!black]
coordinates {{{yearly_marker_coordinates}}};
\addlegendentry{{Tank reliability}}
\end{{axis}}
\end{{tikzpicture}}
\par\small The Average marker reports tank reliability across {len(report["yearly_reliability"])} analyzed years.
\end{{center}}

\section{{Tank Level Distribution}}
\begin{{center}}
\begin{{tikzpicture}}
\begin{{axis}}[
width=6.6in,
height=3.8in,
ybar,
ymin=0,
ylabel={{Days}},
xlabel={{Tank level range ({_latex_escape(volume)})}},
label style={{font=\bfseries\normalsize}},
xtick={{1,...,6}},
xticklabels={{{distribution_labels}}},
x tick label style={{rotate=30, anchor=east, font=\scriptsize}},
nodes near coords,
grid=major,
]
\addplot+[fill=green!65!black, draw=green!45!black] coordinates {{{distribution_coordinates}}};
\end{{axis}}
\end{{tikzpicture}}
\end{{center}}

{multitank_latex}
\end{{document}}
"""
    return _filter_latex_report_sections(document, report)


def _build_system_visualization_html(report: dict[str, object]) -> str:
    if not report.get("include_system_visualization"):
        return ""
    system_type = str(report.get("system_type", "Direct system"))
    size_label = html.escape(
        f"{format_number(float(report['selected_tank_size']), max_decimal_places=0)} {report['volume_unit']}", quote=True
    )
    if system_type == "Indirect system":
        equipment = """
<line x1="250" y1="130" x2="315" y2="130"/><circle cx="350" cy="130" r="35"/>
<polygon points="385,130 332.5,160.31 332.5,99.69"/><text x="350" y="185">Transfer pump</text>
<line x1="385" y1="130" x2="445" y2="130"/><rect x="445" y="100" width="130" height="60"/>
<text x="510" y="135">Filtration</text><line x1="575" y1="130" x2="640" y2="130"/>
<rect x="640" y="45" width="160" height="130"/><text x="720" y="72">Buffer tank</text>
<path d="M642 105 q7 -7 14 0 q7 7 14 0 q7 -7 14 0 q7 7 14 0 q7 -7 14 0 q7 7 14 0 q7 -7 14 0 q7 7 14 0 q7 -7 14 0 q7 7 14 0"/>
<line x1="720" y1="4" x2="720" y2="45"/><polygon points="720,45 711,30 729,30"/>
<text x="610" y="18">Municipal water backup</text>
<line x1="800" y1="130" x2="812" y2="130"/><circle cx="840" cy="130" r="28"/>
<polygon points="868,130 826,154.25 826,105.75"/><text x="840" y="190">Booster pump</text>
<line x1="868" y1="130" x2="970" y2="130"/><polygon points="990,130 970,119 970,141"/>
<text x="930" y="108">To end-uses</text>"""
    else:
        equipment = """
<line x1="250" y1="130" x2="385" y2="130"/><circle cx="420" cy="130" r="35"/>
<polygon points="455,130 390,148 390,112"/><text x="420" y="185">Distribution pump</text>
<line x1="455" y1="130" x2="720" y2="130"/><polygon points="740,130 720,119 720,141"/>
<text x="600" y="108">Flow directly to end-uses</text>"""
    return f'''<section id="system-visualization"><h2>System visualization - {html.escape(system_type)}</h2>
<div class="system-visualization"><svg viewBox="0 0 1000 220" role="img" aria-label="{html.escape(system_type)} schematic">
<g fill="none" stroke="#111" stroke-width="4" stroke-linecap="round" stroke-linejoin="round">
<rect x="30" y="25" width="220" height="150"/><path d="M32 105 q8 -7 16 0 q8 7 16 0 q8 -7 16 0 q8 7 16 0 q8 -7 16 0 q8 7 16 0 q8 -7 16 0 q8 7 16 0 q8 -7 16 0 q8 7 16 0 q8 -7 16 0 q8 7 16 0 q8 -7 16 0"/>{equipment}</g>
<g fill="#111" font-family="Arial,sans-serif" font-size="15" font-weight="700" text-anchor="middle">
<text x="140" y="52">Primary tank</text><text x="140" y="74" font-size="12" font-weight="400">Primary analysis size: {size_label}</text></g>
</svg></div></section>'''


def _web_mercator_pixel(
    latitude: float, longitude: float, zoom: int
) -> tuple[float, float]:
    """Project a coordinate to global Web Mercator pixels at a tile zoom level."""
    latitude = min(max(float(latitude), -85.05112878), 85.05112878)
    scale = 256.0 * (2 ** zoom)
    x = (float(longitude) + 180.0) / 360.0 * scale
    sine = math.sin(math.radians(latitude))
    y = (0.5 - math.log((1.0 + sine) / (1.0 - sine)) / (4.0 * math.pi)) * scale
    return x, y


def _build_static_location_map_html(
    report: ReportModel, map_points: list[dict[str, object]]
) -> str:
    """Build a static tile viewport without requiring a JavaScript map library."""
    if not map_points:
        return ""
    width, height = 800.0, 340.0
    selected_zoom = 2
    projected: list[tuple[float, float]] = []
    for zoom in range(16, 1, -1):
        candidate = [
            _web_mercator_pixel(point["latitude"], point["longitude"], zoom)
            for point in map_points
        ]
        x_span = max(value[0] for value in candidate) - min(value[0] for value in candidate)
        y_span = max(value[1] for value in candidate) - min(value[1] for value in candidate)
        if x_span <= width - 140.0 and y_span <= height - 110.0:
            selected_zoom = zoom
            projected = candidate
            break
    if not projected:
        projected = [
            _web_mercator_pixel(point["latitude"], point["longitude"], selected_zoom)
            for point in map_points
        ]
    center_x = (min(value[0] for value in projected) + max(value[0] for value in projected)) / 2.0
    center_y = (min(value[1] for value in projected) + max(value[1] for value in projected)) / 2.0
    viewport_left = center_x - width / 2.0
    viewport_top = center_y - height / 2.0
    tile_url = str(
        report.get("map_tile_url", "https://tile.openstreetmap.org/{z}/{x}/{y}.png")
    )
    tile_count = 2 ** selected_zoom
    tile_images: list[str] = []
    first_tile_x = math.floor(viewport_left / 256.0)
    last_tile_x = math.floor((viewport_left + width) / 256.0)
    first_tile_y = math.floor(viewport_top / 256.0)
    last_tile_y = math.floor((viewport_top + height) / 256.0)
    for tile_y in range(first_tile_y, last_tile_y + 1):
        if not 0 <= tile_y < tile_count:
            continue
        for tile_x in range(first_tile_x, last_tile_x + 1):
            source = (
                tile_url.replace("{z}", str(selected_zoom))
                .replace("{x}", str(tile_x % tile_count))
                .replace("{y}", str(tile_y))
                .replace("{s}", "a")
            )
            x = tile_x * 256.0 - viewport_left
            y = tile_y * 256.0 - viewport_top
            tile_images.append(
                f'<image href="{html.escape(source, quote=True)}" x="{x:.2f}" y="{y:.2f}" '
                'width="256" height="256" preserveAspectRatio="none"/>'
            )
    markers: list[str] = []
    for point, (projected_x, projected_y) in zip(map_points, projected):
        latitude = float(point["latitude"])
        longitude = float(point["longitude"])
        marker_x = projected_x - viewport_left
        marker_y = projected_y - viewport_top
        label = html.escape(str(point["label"]), quote=True)
        color = html.escape(str(point["color"]), quote=True)
        markers.append(
            f'<circle cx="{marker_x:.2f}" cy="{marker_y:.2f}" r="10" fill="{color}" '
            'stroke="#fff" stroke-width="3">'
            f'<title>{label}: {latitude:.6f}, {longitude:.6f}</title></circle>'
            f'<text class="map-marker-label" x="{marker_x + 15:.2f}" y="{marker_y + 5:.2f}">{label}</text>'
        )
    return (
        '<div id="project-location-map" class="location-map">'
        '<svg viewBox="0 0 800 340" role="img" aria-label="Static map of project and weather-station locations">'
        '<defs><clipPath id="location-map-clip"><rect width="800" height="340" rx="6"/></clipPath></defs>'
        '<g clip-path="url(#location-map-clip)">'
        '<rect width="800" height="340" fill="#e6ecef"/>'
        f'{"".join(tile_images)}'
        f'<g font-family="Arial,sans-serif" font-size="14" font-weight="700">{"".join(markers)}</g>'
        '</g></svg></div>'
        '<p class="map-note">Map data &copy; OpenStreetMap contributors. Static map tiles require an internet connection.</p>'
    )


def render_html(
    report: ReportModel | dict[str, object]
) -> str:
    report = ReportModel.from_payload(report)
    metadata = report["metadata"]
    surfaces = report["surfaces"]
    curve = report["curve"]
    escape = lambda value: html.escape(str(value), quote=True)
    report_title = "RWH Calculator Report - multi-tank" if report.get("include_multitank_charts") else "RWH Calculator Report"
    multitank_html = _build_multitank_report_html(report)
    system_visualization_html = _build_system_visualization_html(report)
    station_latitude = report.get("weather_station_latitude")
    station_longitude = report.get("weather_station_longitude")
    project_latitude = report.get("project_latitude")
    project_longitude = report.get("project_longitude")
    map_points: list[dict[str, object]] = []
    if station_latitude is not None and station_longitude is not None:
        map_points.append(
            {
                "latitude": float(station_latitude),
                "longitude": float(station_longitude),
                "color": "#d71920",
                "label": "Weather station",
            }
        )
    if project_latitude is not None and project_longitude is not None:
        map_points.append(
            {
                "latitude": float(project_latitude),
                "longitude": float(project_longitude),
                "color": "#1565c0",
                "label": "Project location",
            }
        )
    project_location_map_html = _build_static_location_map_html(report, map_points)
    multitank_toc_html = "".join(
        f'<li><a href="#multitank-chart-{index}">{escape(chart.get("title", f"Multitank chart {index}"))}</a></li>'
        for index, chart in enumerate(report.get("multitank_charts", []), start=1)
    ) if report.get("include_multitank_charts") else ""
    surface_rows = "".join(
        f"<tr><td>{escape(surface['name'])}</td><td>{format_number(surface['area'])}</td>"
        f"<td>{format_number(surface['runoff_coefficient'])}</td>"
        f"<td>{format_number(float(surface.get('first_flush_depth', 0.0)), max_decimal_places=3)}</td></tr>"
        for surface in surfaces
    ) or '<tr><td>No collection surfaces</td><td>0.00</td><td>0.000</td><td>0.000</td></tr>'
    demand_rows = "".join(
        f"<tr><td>{escape(report['monthly_demand'][index]['month'])}</td>"
        f"<td>{format_number(float(report['monthly_demand'][index]['demand_per_day']), max_decimal_places=0)}</td>"
        f"<td>{format_number(float(report['monthly_demand'][index]['demand_per_month']), max_decimal_places=0)}</td>"
        f"<td>{escape(report['monthly_demand'][index + 6]['month'])}</td>"
        f"<td>{format_number(float(report['monthly_demand'][index + 6]['demand_per_day']), max_decimal_places=0)}</td>"
        f"<td>{format_number(float(report['monthly_demand'][index + 6]['demand_per_month']), max_decimal_places=0)}</td></tr>"
        for index in range(6)
    )

    chart_width, chart_height = 900.0, 420.0
    left, right, top, bottom = 72.0, 24.0, 28.0, 62.0
    plot_width = chart_width - left - right
    plot_height = chart_height - top - bottom
    x_values = [float(point["tank_size"]) for point in curve]
    if report["selected_reliability"] is not None:
        x_values.append(float(report["selected_tank_size"]))
    x_min, x_max = min(x_values), max(x_values)
    if x_min == x_max:
        x_max = x_min + 1

    def chart_x(value: float) -> float:
        return left + ((value - x_min) / (x_max - x_min)) * plot_width

    def chart_y(value: float) -> float:
        return top + (1 - max(0.0, min(value, 100.0)) / 100.0) * plot_height

    polyline = " ".join(
        f"{chart_x(float(point['tank_size'])):.2f},{chart_y(float(point['reliability'])):.2f}"
        for point in curve
    )
    circles = "".join(
        f'<circle cx="{chart_x(float(point["tank_size"])):.2f}" cy="{chart_y(float(point["reliability"])):.2f}" r="4">'
        f'<title>{format_number(float(point["tank_size"]), max_decimal_places=0)} {escape(report["volume_unit"])}: '
        f'{format_number(float(point["reliability"]))}% reliability</title></circle>'
        for point in curve
    )
    selected_marker = ""
    if report["selected_reliability"] is not None:
        selected_x = chart_x(float(report["selected_tank_size"]))
        selected_y = chart_y(float(report["selected_reliability"]))
        selected_marker = (
            f'<circle class="selected-tank" cx="{selected_x:.2f}" cy="{selected_y:.2f}" r="10">'
            f'<title>Selected tank: {format_number(float(report["selected_tank_size"]), max_decimal_places=0)} '
            f'{escape(report["volume_unit"])} at {format_number(float(report["selected_reliability"]))}% reliability</title>'
            "</circle>"
        )
    y_grid = "".join(
        f'<line x1="{left}" y1="{chart_y(value):.2f}" x2="{left + plot_width}" y2="{chart_y(value):.2f}" />'
        f'<text x="{left - 14}" y="{chart_y(value) + 4:.2f}" text-anchor="end">{value}</text>'
        for value in range(0, 101, 20)
    )
    x_ticks = "".join(
        f'<line x1="{chart_x(value):.2f}" y1="{top}" x2="{chart_x(value):.2f}" y2="{top + plot_height}" />'
        f'<text x="{chart_x(value):.2f}" y="{top + plot_height + 26}" text-anchor="middle">{format_number(value, max_decimal_places=0)}</text>'
        for value in [x_min + (x_max - x_min) * index / 4 for index in range(5)]
    )
    selected = report["selected_reliability"]
    selected_text = "--" if selected is None else f"{format_number(selected)}%"
    author_html = ""
    if metadata.get("author_name", "").strip():
        author_html = f'<p class="author">Produced by {escape(metadata["author_name"])}</p>'
    info_rows = "".join(
        f'<div class="fact"><dt>{escape(label)}</dt><dd>{escape(value or "Not specified")}</dd></div>'
        for label, value in [
            ("Client name", metadata["client_name"]),
            ("Date", metadata["date"]),
            ("Location", metadata["location"]),
            (
                "Project location coordinates",
                f"{float(report['project_latitude']):.6f}, {float(report['project_longitude']):.6f}"
                if report.get("project_latitude") is not None and report.get("project_longitude") is not None
                else None,
            ),
            (
                "Weather station coordinates",
                f"{float(report['weather_station_latitude']):.6f}, {float(report['weather_station_longitude']):.6f}"
                if report.get("weather_station_latitude") is not None and report.get("weather_station_longitude") is not None
                else None,
            ),
            ("Project name", metadata["project_name"]),
            ("End-uses of water", metadata["end_uses"]),
        ]
        if value is not None
    )
    notes_html = escape(report.get("notes", "").strip() or "No notes provided.")
    summary = report.get("executive_summary", {})
    summary_payback = summary.get("simple_payback_years")
    summary_financial = (
        f'{escape(report.get("financial_summary", {}).get("currency", "USD"))} '
        f'{format_number(float(summary.get("net_annual_savings", 0.0)))}/year; '
        + (f'{format_number(float(summary_payback), max_decimal_places=1)} years payback' if summary_payback is not None else 'payback not achieved')
        if summary.get("financial_configured") else "Financial assumptions not configured"
    )
    executive_cards = "".join(
        f'<div class="metric"><span>{escape(label)}</span><strong>{escape(value)}</strong></div>'
        for label, value in (
            (
                "Average annual precipitation",
                f"{format_number(float(report['average_annual_precipitation']))} {report['precipitation_unit']}",
            ),
            ("Precipitation basis", report["precipitation_basis"]),
            ("Selected tank", f'{format_number(float(report["selected_tank_size"]), max_decimal_places=0)} {report["volume_unit"]}'),
            ("Reliability", selected_text),
            ("Average annual supply", f'{format_number(float(summary.get("average_annual_supply", 0.0)), max_decimal_places=0)} {report["volume_unit"]}/year'),
            ("Municipal makeup", f'{format_number(float(summary.get("average_annual_municipal_makeup", 0.0)), max_decimal_places=0)} {report["volume_unit"]}/year'),
            ("System unmet demand", f'{format_number(float(summary.get("average_annual_system_unmet", 0.0)), max_decimal_places=0)} {report["volume_unit"]}/year'),
            ("Overflow", f'{format_number(float(summary.get("average_annual_overflow", 0.0)), max_decimal_places=0)} {report["volume_unit"]}/year'),
            ("First-flush loss", f'{format_number(float(summary.get("average_annual_first_flush_loss", 0.0)), max_decimal_places=0)} {report["volume_unit"]}/year'),
            ("Treatment loss", f'{format_number(float(summary.get("average_annual_treatment_loss", 0.0)), max_decimal_places=0)} {report["volume_unit"]}/year'),
            ("Financial result", summary_financial),
        )
    )

    candidate_columns = (
        ("tank_size", "Tank size", "number"), ("reliability", "Reliability", "number"),
        ("RainwaterSuppliedGallons", "Supply/year", "number"),
        ("MunicipalMakeupGallons", "Municipal makeup/year", "number"),
        ("SystemUnmetDemandGallons", "System unmet/year", "number"),
        ("OverflowGallons", "Overflow/year", "number"),
        ("FirstFlushLossGallons", "First flush/year", "number"),
        ("TreatmentLossGallons", "Treatment loss/year", "number"),
        ("FinalStorageGallons", "Final storage", "number"),
        ("NetAnnualSavings", "Net savings/year", "number"),
        ("SimplePaybackYears", "Payback", "number"),
        ("LifecycleNPV", "Lifecycle NPV", "number"),
    )
    candidate_head = "".join(
        f'<th><button class="sort-button" type="button" data-column="{index}" data-sort="{kind}">{escape(label)}</button></th>'
        for index, (_key, label, kind) in enumerate(candidate_columns)
    )
    candidate_rows = ""
    currency = str(report.get("financial_summary", {}).get("currency", "USD"))
    for candidate in report.get("candidate_performance", []):
        cells: list[str] = []
        for key, _label, _kind in candidate_columns:
            value = candidate.get(key)
            if value is None:
                display, sort_value = "--", ""
            elif key == "reliability":
                display, sort_value = f"{format_number(float(value), max_decimal_places=1)}%", str(float(value))
            elif key in {"NetAnnualSavings", "LifecycleNPV"}:
                display, sort_value = f"{currency} {format_number(float(value))}", str(float(value))
            elif key == "SimplePaybackYears":
                display, sort_value = f"{format_number(float(value), max_decimal_places=1)} years", str(float(value))
            else:
                display, sort_value = format_number(float(value), max_decimal_places=0), str(float(value))
            cells.append(f'<td data-value="{escape(sort_value)}">{escape(display)}</td>')
        selected_class = ' class="selected-row"' if candidate.get("selected") else ""
        candidate_rows += f'<tr{selected_class}>{"".join(cells)}</tr>'
    candidate_rows = candidate_rows or f'<tr><td colspan="{len(candidate_columns)}">No candidate results available.</td></tr>'

    recommendation_rows = "".join(
        "<tr>"
        f'<td>{escape(item.get("role", "Recommendation"))}</td>'
        f'<td>{format_number(float(item.get("tank_size", 0.0)), max_decimal_places=0)} {escape(item.get("volume_unit", report["volume_unit"]))}</td>'
        f'<td>{format_number(float(item.get("reliability_percent", 0.0)), max_decimal_places=1)}%</td>'
        f'<td>{escape(item.get("detail", ""))}</td></tr>'
        for item in report.get("recommendations", [])
    ) or '<tr><td colspan="4">No design recommendation could be calculated from the available candidates.</td></tr>'
    assumptions = report.get("recommendation_assumptions", {})
    recommendation_assumptions = (
        f'Reliability target: {format_number(float(assumptions.get("reliability_target_percent", 90.0)), max_decimal_places=1)}%. '
        f'Diminishing-return threshold: {format_number(float(assumptions.get("marginal_gain_threshold", 1.0)))} '
        "reliability percentage points per 1,000 gallons."
    )
    warning_html = "".join(
        f'<li>{escape(warning)}</li>' for warning in report.get("review_warnings", [])
    )
    warnings_section = (
        f'<aside class="review-warning" role="note"><h3>Review conditions</h3><ul>{warning_html}</ul></aside>'
        if warning_html
        else '<p class="review-clear">No configured review conditions were triggered.</p>'
    )

    balance = report.get("water_balance", {})
    def balance_row(label: str, key: str) -> str:
        return f'<tr><td>{escape(label)}</td><td>{format_number(float(balance.get(key, 0.0)), max_decimal_places=1)} {escape(report["volume_unit"])}</td></tr>'
    collection_balance_rows = "".join((
        balance_row("Potential rainfall volume on collection surfaces", "potential_surface_rainfall"),
        balance_row("Less runoff-coefficient loss", "runoff_coefficient_loss"),
        balance_row("Gross runoff after runoff coefficients", "gross_runoff"),
        balance_row("Less first-flush diversion", "first_flush_loss"),
        balance_row("Net collected water", "net_collected"),
        balance_row("Reconciliation residual", "collection_residual"),
    ))
    storage_balance_rows = "".join((
        balance_row("Initial primary-tank storage", "initial_storage"),
        balance_row("Plus net collected water", "net_collected"),
        balance_row("Less rainwater supplied", "rainwater_supplied"),
        balance_row("Less treatment loss", "treatment_loss"),
        balance_row("Less overflow", "overflow"),
        balance_row("Final primary-tank storage", "final_storage"),
        balance_row("Reconciliation residual", "storage_residual"),
    ))

    end_use_rows = "".join(
        "<tr>"
        f'<td>{escape(row["name"])}</td><td>{escape(row["type"])}</td><td>{escape(row["schedule"])}</td>'
        f'<td>{escape(row["sewer_basis"])}</td><td>{format_number(float(row["annual_demand"]), max_decimal_places=0)}</td>'
        f'<td>{format_number(float(row["annual_supply"]), max_decimal_places=0)}</td><td>{format_number(float(row["demand_met_percent"]), max_decimal_places=1)}%</td>'
        f'<td>{escape(currency)} {format_number(float(row["water_savings"]))}</td>'
        f'<td>{escape(currency)} {format_number(float(row["sewer_savings"]))}</td></tr>'
        for row in report.get("end_use_rows", [])
    ) or '<tr><td colspan="9">No demand objects were reported.</td></tr>'

    financial = report.get("financial_summary", {})
    payback = financial.get("simple_payback_years")
    financial_rows = "".join(
        f'<tr><td>{escape(label)}</td><td>{escape(value)}</td></tr>'
        for label, value in (
            ("Water tariff", f'{currency} {format_number(float(financial.get("water_rate", 0.0)), max_decimal_places=4)} {financial.get("tariff_billing_unit", "") }'),
            ("Sewer tariff", f'{currency} {format_number(float(financial.get("sewer_rate", 0.0)), max_decimal_places=4)} {financial.get("tariff_billing_unit", "") }'),
            ("Legacy aggregate sewer eligibility", f'{format_number(float(financial.get("legacy_sewer_eligible_percent", 0.0)))}%'),
            ("Installed cost", f'{currency} {format_number(float(financial.get("installed_cost", 0.0)))}'),
            ("Incentives", f'{currency} {format_number(float(financial.get("incentives", 0.0)))}'),
            ("Annual maintenance", f'{currency} {format_number(float(financial.get("fixed_annual_maintenance", 0.0)))} + {format_number(float(financial.get("annual_maintenance_percent", 0.0)))}% of installed cost'),
            ("Average annual rainwater supplied", f'{format_number(float(financial.get("average_annual_supply", 0.0)), max_decimal_places=0)} {report["volume_unit"]}/year'),
            ("Average annual sewer-eligible supply", f'{format_number(float(financial.get("average_annual_sewer_eligible_supply", 0.0)), max_decimal_places=0)} {report["volume_unit"]}/year'),
            ("Municipal water savings", f'{currency} {format_number(float(financial.get("municipal_water_savings", 0.0)))}/year'),
            ("Sewer savings", f'{currency} {format_number(float(financial.get("sewer_savings", 0.0)))}/year'),
            ("Gross annual savings", f'{currency} {format_number(float(financial.get("gross_annual_savings", 0.0)))}/year'),
            ("Annual maintenance cost", f'{currency} {format_number(float(financial.get("annual_maintenance_cost", 0.0)))}/year'),
            ("Pump energy", f'{format_number(float(financial.get("average_annual_pump_energy_kwh", 0.0)), max_decimal_places=1)} kWh/year; {currency} {format_number(float(financial.get("annual_pump_energy_cost", 0.0)))}/year'),
            ("Net annual savings", f'{currency} {format_number(float(financial.get("net_annual_savings", 0.0)))}/year'),
            ("Net installed cost", f'{currency} {format_number(float(financial.get("net_installed_cost", 0.0)))}'),
            ("Simple payback", f'{format_number(float(payback), max_decimal_places=1)} years' if payback is not None else "Not achieved"),
            (f'{int(financial.get("analysis_period_years", 0))}-year net benefit', f'{currency} {format_number(float(financial.get("analysis_period_net_benefit", 0.0)))}'),
            ("Utility / maintenance / electricity / replacement escalation", f'{float(financial.get("utility_rate_escalation_percent", 0.0)):g}% / {float(financial.get("maintenance_escalation_percent", 0.0)):g}% / {float(financial.get("electricity_escalation_percent", 0.0)):g}% / {float(financial.get("equipment_replacement_escalation_percent", 0.0)):g}%'),
            ("Discount rate", f'{float(financial.get("discount_rate_percent", 0.0)):g}%'),
            ("Nominal replacement costs", f'{currency} {format_number(float(financial.get("total_replacement_cost", 0.0)))}'),
            ("Lifecycle net present value", f'{currency} {format_number(float(financial.get("lifecycle_net_present_value", 0.0)))}'),
            ("Internal rate of return", f'{format_number(float(financial["internal_rate_of_return_percent"]))}%' if financial.get("internal_rate_of_return_percent") is not None else "Not uniquely defined"),
            ("Discounted payback", f'{format_number(float(financial["discounted_payback_years"]), max_decimal_places=1)} years' if financial.get("discounted_payback_years") is not None else "Not achieved"),
        )
    )
    financial_notice = "" if financial.get("configured") else '<p class="notice">Financial inputs are not configured; zero-value outputs are shown for transparency.</p>'
    cash_flows = [float(value) for value in financial.get("annual_cash_flows", [])]
    discount_rate = float(financial.get("discount_rate_percent", 0.0)) / 100.0
    cumulative_discounted = 0.0
    cash_flow_rows: list[str] = []
    for year, nominal in enumerate(cash_flows):
        discounted = nominal / ((1.0 + discount_rate) ** year)
        cumulative_discounted += discounted
        cash_flow_rows.append(
            "<tr>"
            f"<td>{year}</td><td>{escape(currency)} {format_number(nominal)}</td>"
            f"<td>{escape(currency)} {format_number(discounted)}</td>"
            f"<td>{escape(currency)} {format_number(cumulative_discounted)}</td></tr>"
        )
    cash_flow_rows_html = "".join(cash_flow_rows) or (
        '<tr><td colspan="4">No lifecycle cash-flow schedule is available.</td></tr>'
    )

    rainfall_quality = report.get("rainfall_quality", {})
    rainfall_quality_rows = "".join(
        f'<div class="fact"><dt>{escape(label)}</dt><dd>{escape(value)}</dd></div>'
        for label, value in (
            (
                "Completeness score",
                f'{format_number(float(rainfall_quality.get("completeness_percent", 0.0)))}% '
                f'({rainfall_quality.get("completeness_rating", "Not rated")})',
            ),
            (
                "Calendar-day coverage",
                f'{format_number(int(rainfall_quality.get("observed_days", 0)), max_decimal_places=0)} observed of '
                f'{format_number(int(rainfall_quality.get("expected_days", 0)), max_decimal_places=0)} expected',
            ),
            ("Missing days", format_number(int(rainfall_quality.get("missing_days", 0)), max_decimal_places=0)),
            (
                "Partial/incomplete years",
                ", ".join(str(value) for value in rainfall_quality.get("partial_years", []))
                or "None",
            ),
            ("Duplicate dates", f'{int(rainfall_quality.get("duplicate_dates", 0)):,}'),
            (
                "Invalid precipitation rows",
                f'{int(rainfall_quality.get("invalid_precipitation_rows", 0)):,}',
            ),
        )
    )
    missing_period_rows = "".join(
        f'<tr><td>{escape(row.get("start", ""))}</td><td>{escape(row.get("end", ""))}</td>'
        f'<td>{int(row.get("days", 0)):,}</td></tr>'
        for row in rainfall_quality.get("missing_periods", [])[:20]
    ) or '<tr><td colspan="3">No missing periods.</td></tr>'
    yearly_rainfall_rows = "".join(
        f'<tr><td>{int(row.get("year", 0))}</td>'
        f'<td>{int(row.get("observed_days", 0)):,}</td>'
        f'<td>{int(row.get("missing_days", 0)):,}</td>'
        f'<td>{format_number(float(row.get("completeness_percent", 0.0)))}%</td>'
        f'<td>{format_number(float(row.get("precipitation", 0.0)))}</td>'
        f'<td>{int(row.get("wet_days", 0)):,}</td>'
        f'<td>{"Partial" if row.get("partial_year") else "Complete"}</td></tr>'
        for row in report.get("yearly_rainfall_summary", [])
    ) or '<tr><td colspan="7">No yearly rainfall summary is available.</td></tr>'
    event_summary = report.get("rainfall_event_summary", {})
    rainfall_event_rows = "".join(
        f'<tr><td>{int(row.get("event_number", 0))}</td>'
        f'<td>{escape(row.get("start", ""))}</td><td>{escape(row.get("end", ""))}</td>'
        f'<td>{int(row.get("duration_days", 0)):,}</td>'
        f'<td>{int(row.get("wet_days", 0)):,}</td>'
        f'<td>{format_number(float(row.get("precipitation", 0.0)), max_decimal_places=3)}</td></tr>'
        for row in event_summary.get("largest_events", [])
    ) or '<tr><td colspan="6">No wet-weather events were identified.</td></tr>'
    first_flush_yearly_rows = "".join(
        f'<tr><td>{int(row.get("year", 0))}</td>'
        f'<td>{int(row.get("event_count", 0)):,}</td>'
        f'<td>{format_number(float(row.get("gross_runoff", 0.0)))}</td>'
        f'<td>{format_number(float(row.get("first_flush_loss", 0.0)))}</td>'
        f'<td>{format_number(float(row.get("net_collected", 0.0)))}</td>'
        f'<td>{format_number(float(row.get("diversion_percent", 0.0)))}%</td></tr>'
        for row in report.get("first_flush_yearly_summary", [])
    ) or '<tr><td colspan="6">No yearly first-flush summary is available.</td></tr>'
    first_flush_event_rows = "".join(
        f'<tr><td>{escape(row.get("event_id", ""))}</td>'
        f'<td>{escape(row.get("start", ""))}</td><td>{escape(row.get("end", ""))}</td>'
        f'<td>{int(row.get("wet_timesteps", 0)):,}</td>'
        f'<td>{format_number(float(row.get("gross_runoff", 0.0)))}</td>'
        f'<td>{format_number(float(row.get("first_flush_loss", 0.0)))}</td>'
        f'<td>{format_number(float(row.get("net_collected", 0.0)))}</td>'
        f'<td>{format_number(float(row.get("diversion_percent", 0.0)))}%</td></tr>'
        for row in report.get("first_flush_event_summary", [])
    ) or '<tr><td colspan="8">No event-level first-flush summary is available.</td></tr>'

    provenance = report.get("provenance", {})
    provenance_rows = "".join(
        f'<div class="fact"><dt>{escape(label)}</dt><dd>{escape(value)}</dd></div>'
        for label, value in (
            ("Rainfall source", provenance.get("rainfall_source", "Not available")),
            ("Rainfall data classification", provenance.get("rainfall_data_type", "Unclassified user-supplied data")),
            ("Rainfall record", f'{provenance.get("record_start", "Not available")} to {provenance.get("record_end", "Not available")}'),
            ("Record coverage", f'{int(provenance.get("calendar_years", 0))} calendar years; {int(provenance.get("observations", 0)):,} observations; {int(provenance.get("missing_calendar_days", 0)):,} missing calendar days; {int(provenance.get("incomplete_calendar_years", 0)):,} incomplete calendar years'),
            ("Rainfall resolution", provenance.get("rainfall_resolution", "Daily")),
            ("Rainfall source timezone", provenance.get("rainfall_timezone", "Unspecified")),
            ("Rainfall timing metadata", provenance.get("rainfall_timing_metadata", "Not specified")),
            ("Rainfall retrieved/imported", provenance.get("rainfall_retrieved_at", "Not recorded")),
            ("Simulation timestep", provenance.get("simulation_timestep", "Daily mass balance")),
            ("Rainfall timing", provenance.get("rainfall_timing_assumption", "Not specified")),
            ("Demand timing", provenance.get("demand_timing_assumption", "Not specified")),
            ("System", f'{provenance.get("system_type", "Not specified")}; municipal backup {str(provenance.get("municipal_backup", "Not specified")).lower()}'),
            ("Initial tank fill", f'{float(provenance.get("initial_tank_fill_percent", 0.0)):g}%'),
            ("Filter recovery", f'{float(provenance.get("filter_recovery_percent", 100.0)):g}%'),
            (
                "Filtration system flow",
                "Infinite"
                if float(provenance.get("filtration_system_flow_gpm", 20.0)) == 0.0
                else f'{float(provenance.get("filtration_system_flow_gpm", 20.0)):g} GPM each',
            ),
            (
                "Filtration systems in parallel",
                str(int(provenance.get("filtration_system_count", 1))),
            ),
            ("Transfer pump type", str(provenance.get("transfer_pump_type", "External"))),
            ("Application / algorithm", f'{provenance.get("application_version", "Unknown")} / {provenance.get("algorithm_version", "Unknown")}'),
            ("Report schema", provenance.get("report_schema_version", report["schema_version"])),
            ("Analysis input signature", provenance.get("analysis_input_signature", "Not stored")),
            ("Generated", provenance.get("generated_at", "Not available")),
        )
    )
    yearly = report["yearly_reliability"]
    yearly_chart_width = max(900.0, 90.0 + (len(yearly) + 1) * 24.0)
    yearly_chart_height = 420.0
    yearly_left, yearly_right, yearly_top, yearly_bottom = 72.0, 24.0, 38.0, 62.0
    yearly_plot_width = yearly_chart_width - yearly_left - yearly_right
    yearly_plot_height = yearly_chart_height - yearly_top - yearly_bottom
    yearly_baseline = yearly_top + yearly_plot_height
    yearly_bars = ""
    yearly_labels = ""
    yearly_markers = ""
    if yearly:
        yearly_slot = yearly_plot_width / (len(yearly) + 1)
        yearly_label_step = max((len(yearly) + 9) // 10, 1)
        for index, row in enumerate(yearly):
            bar_x = yearly_left + index * yearly_slot + max(yearly_slot * 0.15, 1.0)
            bar_width = max(yearly_slot * 0.7, 1.0)
            met_height = yearly_plot_height * float(row["met_percent"]) / 100.0
            unmet_height = yearly_plot_height - met_height
            tooltip = (
                f"{int(row['year'])}: demand met {int(row['met_days'])} days "
                f"({format_number(float(row['met_percent']))}%); demand not met {format_number(int(row['unmet_days']), max_decimal_places=0)} days "
                f"({format_number(float(row['unmet_percent']))}%)"
            )
            yearly_bars += (
                f'<rect class="year-met" x="{bar_x:.2f}" y="{yearly_baseline - met_height:.2f}" '
                f'width="{bar_width:.2f}" height="{met_height:.2f}" data-tooltip="{escape(tooltip)}">'
                "</rect>"
                f'<rect class="year-unmet" x="{bar_x:.2f}" y="{yearly_top:.2f}" '
                f'width="{bar_width:.2f}" height="{unmet_height:.2f}" data-tooltip="{escape(tooltip)}">'
                "</rect>"
            )
            marker_x = bar_x + bar_width / 2
            marker_y = yearly_baseline - met_height
            yearly_markers += (
                f'<circle class="year-reliability" cx="{marker_x:.2f}" cy="{marker_y:.2f}" r="5" '
                f'data-tooltip="{int(row["year"])} tank reliability: {format_number(float(row["met_percent"]))}%"></circle>'
            )
            if index % yearly_label_step == 0 or index == len(yearly) - 1:
                yearly_labels += (
                    f'<text x="{bar_x + bar_width / 2:.2f}" y="{yearly_baseline + 22:.2f}" '
                    f'text-anchor="middle">{int(row["year"])}</text>'
                )
        average_reliability = float(report["selected_reliability"] or 0.0)
        average_x = yearly_left + (len(yearly) + 0.5) * yearly_slot
        average_y = yearly_baseline - yearly_plot_height * average_reliability / 100.0
        year_count = len(yearly)
        yearly_markers += (
            f'<circle class="year-reliability" cx="{average_x:.2f}" cy="{average_y:.2f}" r="6" '
            f'data-tooltip="Average tank reliability over {year_count} years: {format_number(average_reliability)}%"></circle>'
        )
        yearly_labels += (
            f'<text x="{average_x:.2f}" y="{yearly_baseline + 18:.2f}" text-anchor="middle">'
            f'<tspan x="{average_x:.2f}">Average</tspan>'
            f'<tspan x="{average_x:.2f}" dy="13">({year_count} years)</tspan></text>'
        )
    yearly_grid = "".join(
        f'<line x1="{yearly_left}" y1="{yearly_top + yearly_plot_height * (100 - value) / 100:.2f}" '
        f'x2="{yearly_left + yearly_plot_width}" y2="{yearly_top + yearly_plot_height * (100 - value) / 100:.2f}" />'
        f'<text x="{yearly_left - 12}" y="{yearly_top + yearly_plot_height * (100 - value) / 100 + 4:.2f}" '
        f'text-anchor="end">{value}%</text>'
        for value in range(0, 101, 25)
    )
    distribution = report["tank_level_distribution"]
    distribution_width, distribution_height = 900.0, 420.0
    distribution_left, distribution_right, distribution_top, distribution_bottom = 72.0, 24.0, 28.0, 72.0
    distribution_plot_width = distribution_width - distribution_left - distribution_right
    distribution_plot_height = distribution_height - distribution_top - distribution_bottom
    distribution_max = max((int(row["count"]) for row in distribution), default=1) or 1
    distribution_bars = ""
    if distribution:
        distribution_slot = distribution_plot_width / len(distribution)
        for index, row in enumerate(distribution):
            bar_x = distribution_left + index * distribution_slot + distribution_slot * 0.12
            bar_width = distribution_slot * 0.76
            bar_height = distribution_plot_height * int(row["count"]) / distribution_max
            bar_y = distribution_top + distribution_plot_height - bar_height
            range_label = f"{format_number(float(row['low']), max_decimal_places=0)}-{format_number(float(row['high']), max_decimal_places=0)}"
            distribution_bars += (
                f'<rect class="distribution-bar" x="{bar_x:.2f}" y="{bar_y:.2f}" width="{bar_width:.2f}" '
                f'height="{bar_height:.2f}"><title>{escape(range_label)} {escape(report["volume_unit"])}: '
                f'{int(row["count"])} days</title></rect>'
                f'<text x="{bar_x + bar_width / 2:.2f}" y="{distribution_top + distribution_plot_height + 22:.2f}" '
                f'text-anchor="middle">{escape(range_label)}</text>'
                f'<text x="{bar_x + bar_width / 2:.2f}" y="{max(bar_y - 7, distribution_top + 11):.2f}" '
                f'text-anchor="middle">{int(row["count"])}</text>'
            )
    distribution_grid = "".join(
        f'<line x1="{distribution_left}" y1="{distribution_top + distribution_plot_height * (4 - index) / 4:.2f}" '
        f'x2="{distribution_left + distribution_plot_width}" y2="{distribution_top + distribution_plot_height * (4 - index) / 4:.2f}" />'
        f'<text x="{distribution_left - 12}" y="{distribution_top + distribution_plot_height * (4 - index) / 4 + 4:.2f}" '
        f'text-anchor="end">{distribution_max * index / 4:.0f}</text>'
        for index in range(5)
    )
    reliability_data_rows = "".join(
        f'<tr><td>{format_number(float(point["tank_size"]), max_decimal_places=0)}</td>'
        f'<td>{format_number(float(point["reliability"]))}%</td></tr>'
        for point in curve
    )
    yearly_data_rows = "".join(
        f'<tr><td>{int(row["year"])}</td><td>{int(row["met_days"]):,}</td>'
        f'<td>{format_number(float(row["met_percent"]))}%</td><td>{format_number(int(row["unmet_days"]), max_decimal_places=0)}</td>'
        f'<td>{format_number(float(row["unmet_percent"]))}%</td></tr>'
        for row in yearly
    )
    distribution_data_rows = "".join(
        f'<tr><td>{format_number(float(row["low"]), max_decimal_places=0)}-{format_number(float(row["high"]), max_decimal_places=0)}</td>'
        f'<td>{int(row["count"]):,}</td></tr>'
        for row in distribution
    )
    rainfall_volumes = report.get("average_annual_rainfall_volumes", {})
    rainfall_volume_rows = "".join(
        f'<tr><td>{escape(label)}</td><td>{format_number(float(rainfall_volumes.get(key, 0.0)), max_decimal_places=0)} '
        f'{escape(report["volume_unit"])}/year</td></tr>'
        for label, key in (
            ("Total average rain", "total_average_rain"),
            ("Average first-flush diversion", "average_first_flush_diversion"),
            ("Total usable average rain", "total_usable_average_rain"),
        )
    )
    document = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(metadata['project_name'])} - {escape(report_title)}</title>
<style>
:root {{ color-scheme: light; --ink:#17242b; --muted:#64747c; --line:#dce5e8; --green:#18795b; --blue:#176b9c; --paper:#fff; --wash:#f2f6f5; }}
* {{ box-sizing:border-box; }} html {{ scroll-behavior:smooth; }} body {{ margin:0; background:var(--wash); color:var(--ink); font:15px/1.55 Arial,Helvetica,sans-serif; }}
.report-shell {{ display:grid; grid-template-columns:240px minmax(0,1040px); justify-content:center; gap:24px; width:min(1336px,calc(100% - 32px)); margin:32px auto; align-items:start; }}
main {{ width:100%; min-width:0; background:var(--paper); box-shadow:0 12px 36px rgba(23,36,43,.10); }}
header {{ padding:44px 52px 38px; border-top:6px solid var(--green); border-bottom:1px solid var(--line); }}
.eyebrow {{ color:var(--green); font-size:12px; font-weight:700; text-transform:uppercase; letter-spacing:.1em; }}
h1 {{ margin:8px 0 4px; font-size:34px; line-height:1.15; }} header p {{ margin:0; color:var(--muted); }}
main section {{ padding:34px 52px; border-bottom:1px solid var(--line); scroll-margin-top:20px; }} h2 {{ margin:0 0 20px; font-size:20px; }}
dl {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:0 40px; margin:0; }}
.fact {{ padding:11px 0; border-bottom:1px solid var(--line); }} dt {{ color:var(--muted); font-size:12px; font-weight:700; text-transform:uppercase; }} dd {{ margin:3px 0 0; }}
.location-map {{ height:230px; margin-top:20px; border:1px solid var(--line); border-radius:6px; }} .map-star {{ width:24px!important; height:24px!important; margin:-12px 0 0 -12px!important; background:transparent; border:0; font-size:25px; line-height:24px; text-align:center; text-shadow:0 1px 2px #fff,0 0 2px #fff; }} .map-legend {{ margin-top:7px; color:var(--muted); font-size:12px; }} .map-legend span {{ margin-left:12px; font-size:17px; }} .map-legend span:first-child {{ margin-left:0; }} .project-star {{ color:#1565c0; }} .station-star {{ color:#d71920; }}
.toc {{ position:sticky; top:20px; max-height:calc(100vh - 40px); overflow:auto; background:var(--paper); border-top:5px solid var(--green); box-shadow:0 8px 24px rgba(23,36,43,.09); }} .toc-toggle {{ display:block; width:100%; padding:9px 12px; border:0; border-bottom:1px solid var(--line); background:#edf6f2; color:var(--green); font:700 12px/1.2 Arial,Helvetica,sans-serif; text-align:left; cursor:pointer; }} .toc-toggle:hover {{ background:#e2f0ea; }} .toc-toggle:focus-visible {{ outline:2px solid var(--blue); outline-offset:-3px; }} .toc-inner {{ padding:16px 18px 20px; }} .toc h2 {{ margin:0 0 10px; font-size:16px; }} .toc ul {{ margin:0; padding:0; list-style:none; }} .toc li {{ border-bottom:1px solid var(--line); }} .toc a {{ display:block; padding:8px 4px; color:var(--blue); font-size:13px; font-weight:700; line-height:1.3; text-decoration:none; border-left:3px solid transparent; }} .toc a:hover,.toc a:focus-visible {{ color:var(--green); border-left-color:var(--green); padding-left:9px; }} .toc a.active {{ color:var(--green); border-left-color:var(--green); background:#edf6f2; padding-left:9px; }} .report-shell.toc-collapsed {{ grid-template-columns:44px minmax(0,1040px); }} .toc-collapsed .toc {{ overflow:hidden; }} .toc-collapsed .toc-inner {{ display:none; }} .toc-collapsed .toc-toggle {{ height:120px; padding:8px 5px; text-align:center; writing-mode:vertical-rl; transform:rotate(180deg); }} .notes-text {{ margin:0; white-space:pre-wrap; }}
table {{ width:100%; border-collapse:collapse; }} th {{ color:var(--muted); font-size:12px; text-align:left; text-transform:uppercase; }} th,td {{ padding:11px 12px; border-bottom:1px solid var(--line); }} th:nth-child(n+2),td:nth-child(n+2) {{ text-align:right; }}
.metric-grid {{ display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:12px; }} .metric {{ min-width:0; padding:16px; border:1px solid var(--line); border-radius:6px; background:#f8fbfa; }} .metric span {{ display:block; color:var(--muted); font-size:11px; font-weight:700; letter-spacing:.04em; text-transform:uppercase; }} .metric strong {{ display:block; margin-top:5px; font-size:17px; overflow-wrap:anywhere; }}
.table-scroll {{ overflow-x:auto; }} .table-scroll table {{ min-width:1040px; }} .selected-row {{ background:#e8f4ef; font-weight:700; }} .sort-button {{ width:100%; padding:0; border:0; background:transparent; color:inherit; font:inherit; text-align:inherit; text-transform:inherit; cursor:pointer; }} .sort-button::after {{ content:' \2195'; color:#93a1a7; }} .notice {{ padding:10px 12px; border-left:4px solid #d17a00; background:#fff7e8; }} .balance-grid {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:28px; }} .balance-grid h3 {{ margin:0 0 8px; font-size:16px; }}
.demand-rule td {{ height:5px; padding:0; border-top:1px solid var(--ink); border-bottom:1px solid var(--ink); }} .demand-total td {{ border-bottom:0; font-weight:700; }}
.location-map {{ height:auto; overflow:hidden; }} .location-map svg {{ min-width:0; background:#e6ecef; }} .map-marker-label {{ fill:#17242b; stroke:#fff; stroke-width:4px; paint-order:stroke; }} .map-note {{ color:var(--muted); font-size:12px; }}
.review-warning {{ margin-top:18px; padding:14px 18px; border-left:5px solid #b34b00; background:#fff1e5; }} .review-warning h3 {{ margin:0 0 6px; }} .review-warning ul {{ margin:0; padding-left:20px; }} .review-clear {{ color:#246b49; font-weight:700; }}
.chart-data {{ margin-top:14px; }} .chart-data caption {{ text-align:left; font-weight:700; padding:8px 0; }}
.chart {{ overflow-x:auto; }} svg {{ display:block; width:100%; min-width:620px; height:auto; }} .grid line {{ stroke:#dce5e8; }} .grid text {{ fill:#64747c; font-size:12px; }}
.curve {{ fill:none; stroke:var(--blue); stroke-width:3; }} circle {{ fill:var(--paper); stroke:var(--blue); stroke-width:3; }} circle:hover {{ fill:var(--blue); r:6; }}
.selected-tank {{ fill:none; stroke:#d71920; stroke-width:4; }} .selected-tank:hover {{ fill:none; r:11; }} .swatch.primary-tank {{ background:transparent; border:2px solid #d71920; border-radius:50%; }}
.year-met {{ fill:#2e8b57; }} .year-unmet {{ fill:#c94c4c; }} .year-met,.year-unmet,.year-reliability {{ cursor:pointer; transition:opacity .12s ease,stroke-width .12s ease; }} .year-met:hover,.year-unmet:hover {{ opacity:.78; stroke:#17242b; stroke-width:1.5; }} .year-reliability {{ fill:#f2c94c; stroke:#8a6d00; stroke-width:1.5; }} .year-reliability:hover {{ fill:#f2c94c; stroke-width:2.5; r:7; }} .chart-legend {{ display:flex; flex-wrap:wrap; gap:20px; margin:8px 0 0 72px; font-size:12px; color:var(--muted); }} .series-toggle {{ display:inline-flex; align-items:center; gap:5px; font-weight:700; cursor:pointer; }} .series-toggle input {{ accent-color:currentColor; }} .swatch {{ display:inline-block; width:11px; height:11px; margin-right:6px; vertical-align:-1px; }} .swatch.year-met {{ background:#2e8b57; }} .swatch.year-unmet {{ background:#c94c4c; }} .swatch.year-reliability {{ background:#f2c94c; border:1px solid #8a6d00; border-radius:50%; }} .chart-tooltip {{ position:fixed; display:none; z-index:1000; max-width:320px; padding:7px 9px; border:1px solid #526168; background:#fffff0; color:#17242b; font-size:12px; line-height:1.35; box-shadow:0 3px 10px rgba(0,0,0,.16); pointer-events:none; }}
.tank-history-point {{ fill:transparent; stroke:transparent; stroke-width:1; cursor:crosshair; }} .tank-history-point:hover {{ fill:#fff; stroke:currentColor; stroke-width:2; }}
.history-mode-controls,.history-controls,.history-range-controls {{ display:flex; align-items:center; justify-content:center; gap:10px; margin:8px 0; }} .history-mode-controls label {{ font-weight:700; }} .history-range-controls input[type=range] {{ width:min(280px,35vw); }}
.distribution-bar {{ fill:#2e8b57; stroke:#246b49; stroke-width:1; }}
.axis-label {{ fill:var(--muted); font-size:15px; font-weight:700; }} .history-controls {{ display:flex; align-items:center; justify-content:center; gap:10px; margin:-4px 0 8px; }} .history-controls button {{ width:30px; height:28px; border:1px solid #aab7bc; background:#fff; color:var(--ink); cursor:pointer; }} .history-controls button:disabled {{ color:#aab7bc; cursor:default; }} .history-controls strong {{ min-width:52px; text-align:center; }} footer {{ padding:20px 52px; color:var(--muted); font-size:12px; }}
@media (max-width:900px) {{ .report-shell,.report-shell.toc-collapsed {{ display:block; width:100%; margin:0; }} .toc {{ position:relative; top:auto; max-height:none; box-shadow:none; border-bottom:1px solid var(--line); }} .toc-inner {{ padding:18px 22px; }} .toc ul {{ columns:2; column-gap:28px; }} .toc-collapsed .toc-toggle {{ height:auto; writing-mode:horizontal-tb; transform:none; text-align:left; }} main {{ box-shadow:none; }} }}
@media (max-width:700px) {{ .toc ul {{ columns:1; }} header,main section {{ padding:28px 22px; }} dl {{ grid-template-columns:1fr; }} h1 {{ font-size:28px; }} .metric-grid,.balance-grid {{ grid-template-columns:1fr; }} }}
@media print {{ body {{ background:#fff; }} .report-shell {{ display:block; width:100%; margin:0; }} .toc {{ display:none; }} main {{ width:100%; margin:0; box-shadow:none; }} section {{ break-inside:avoid; }} }}
</style></head><body><div class="report-shell">
<nav class="toc" aria-label="Table of contents"><button id="toc-toggle" class="toc-toggle" type="button" aria-expanded="true" aria-controls="toc-links">Hide contents</button><div id="toc-links" class="toc-inner"><h2>Table of contents</h2><ul><li><a href="#project-information">Project information</a></li><li><a href="#executive-summary">Executive summary</a></li><li><a href="#notes">Notes</a></li><li><a href="#design-recommendations">Design recommendations</a></li><li><a href="#surface-area-summary">Surface area summary</a></li><li><a href="#rainfall-volume-summary">Rainfall volume summary</a></li><li><a href="#tank-summary">Tank summary</a></li><li><a href="#candidate-performance">Candidate performance</a></li><li><a href="#water-balance">Water balance</a></li>{'<li><a href="#system-visualization">System visualization</a></li>' if report.get('include_system_visualization') else ''}<li><a href="#demand-summary">Demand summary</a></li><li><a href="#end-use-performance">End-use performance</a></li><li><a href="#financial-analysis">Financial analysis</a></li><li><a href="#rainfall-quality">Rainfall quality</a></li><li><a href="#yearly-rainfall">Yearly rainfall</a></li><li><a href="#rainfall-events">Rainfall events</a></li><li><a href="#first-flush-summary">First-flush diversion</a></li><li><a href="#analysis-provenance">Analysis provenance</a></li><li><a href="#reliability-curve">Reliability curve</a></li><li><a href="#yearly-demand-reliability">Yearly demand reliability</a></li><li><a href="#tank-level-distribution">Tank level distribution</a></li>{multitank_toc_html}</ul></div></nav>
<main>
<header><div class="eyebrow">Rainwater harvesting analysis</div><h1>{escape(metadata['project_name'])}</h1><p>{escape(report_title)}</p>{author_html}</header>
<section id="project-information"><h2>Project information</h2><dl>{info_rows}</dl>{project_location_map_html}</section>
<section id="executive-summary"><h2>Executive design summary</h2><div class="metric-grid">{executive_cards}</div></section>
<section id="notes"><h2>Notes</h2><p class="notes-text">{notes_html}</p></section>
<section id="design-recommendations"><h2>Design recommendations and review conditions</h2><p>{escape(recommendation_assumptions)}</p><p>These are decision aids based on the simulated candidates and stated assumptions, not a universal optimum.</p><div class="table-scroll"><table><thead><tr><th>Decision aid</th><th>Tank size</th><th>Reliability</th><th>Basis and tradeoff</th></tr></thead><tbody>{recommendation_rows}</tbody></table></div>{warnings_section}</section>
<section id="surface-area-summary"><h2>Surface area summary</h2><table><thead><tr><th>Surface</th><th>Area ({escape(report['area_unit'])})</th><th>Runoff coefficient</th><th>First flush ({escape(report['precipitation_unit'])})</th></tr></thead><tbody>{surface_rows}</tbody></table><p>First-flush event dry-period threshold: {format_number(float(report.get('first_flush_antecedent_dry_value', report.get('first_flush_antecedent_dry_days', 1.0))))} {escape(str(report.get('first_flush_antecedent_dry_unit', 'days')))}. Events: {format_number(int(report.get('first_flush_event_count', 0)), max_decimal_places=0)}. Diverted volume: {format_number(float(report.get('first_flush_loss', 0.0)), max_decimal_places=1)} {escape(report['volume_unit'])}.</p></section>
<section id="rainfall-volume-summary"><h2>Rainfall volume summary</h2><p>Average annual volumes are calculated from the simulated calendar-year totals. Total average rain is gross runoff after surface runoff coefficients and before first flush. Total usable average rain is net collected volume after first-flush diversion.</p><table><thead><tr><th>Average annual volume</th><th>Value</th></tr></thead><tbody>{rainfall_volume_rows}</tbody></table></section>
<section id="tank-summary"><h2>Tank summary</h2><table><thead><tr><th>Tank property</th><th>Value</th></tr></thead><tbody><tr><td>Size</td><td>{format_number(float(report['selected_tank_size']), max_decimal_places=0)} {escape(report['volume_unit'])}</td></tr><tr><td>Minimum operating level</td><td>{format_number(float(report.get('minimum_operating_level_percent', 0.0)), max_decimal_places=1)}% of capacity</td></tr><tr><td>Minimum operating volume</td><td>{format_number(float(report.get('minimum_operating_volume', 0.0)), max_decimal_places=0)} {escape(report['volume_unit'])}</td></tr></tbody></table></section>
<section id="candidate-performance"><h2>Candidate tank performance</h2><p>Flow quantities are average annual values; final storage is the end-of-record value. Click a column heading to sort the HTML table. The selected primary tank is highlighted.</p><div class="table-scroll"><table data-sortable-table><thead><tr>{candidate_head}</tr></thead><tbody>{candidate_rows}</tbody></table></div></section>
<section id="water-balance"><h2>Reconciled water balance</h2><p>Runoff coefficients reduce rainfall-derived volume on every wet day. First flush is a separate event-based diversion applied after runoff coefficients. Values below cover the complete analysis period.</p><div class="balance-grid"><div><h3>Collection balance</h3><table><thead><tr><th>Component</th><th>Volume</th></tr></thead><tbody>{collection_balance_rows}</tbody></table></div><div><h3>Primary-storage balance</h3><table><thead><tr><th>Component</th><th>Volume</th></tr></thead><tbody>{storage_balance_rows}</tbody></table></div></div></section>
{system_visualization_html}
<section id="demand-summary"><h2>Demand summary</h2><table><thead><tr><th>Month</th><th>Demand ({escape(report['volume_unit'])}/day)</th><th>Demand ({escape(report['volume_unit'])}/month)</th><th>Month</th><th>Demand ({escape(report['volume_unit'])}/day)</th><th>Demand ({escape(report['volume_unit'])}/month)</th></tr></thead><tbody>{demand_rows}<tr class="demand-rule"><td colspan="6"></td></tr><tr class="demand-total"><td colspan="5">Total Annual Demand</td><td>{format_number(float(report['total_annual_demand']), max_decimal_places=0)} {escape(report['volume_unit'])}</td></tr></tbody></table></section>
<section id="end-use-performance"><h2>End-use demand and savings</h2><p>Rainwater supply is allocated proportionally among the demand objects active on each simulated day. Sewer savings follow each object's eligibility setting; migrated legacy objects use the legacy aggregate percentage.</p><div class="table-scroll"><table><thead><tr><th>End use</th><th>Type</th><th>Schedule</th><th>Sewer basis</th><th>Demand ({escape(report['volume_unit'])}/year)</th><th>Supply ({escape(report['volume_unit'])}/year)</th><th>Demand met</th><th>Water savings/year</th><th>Sewer savings/year</th></tr></thead><tbody>{end_use_rows}</tbody></table></div></section>
<section id="financial-analysis"><h2>Financial assumptions and results</h2>{financial_notice}<p>{escape(financial.get('methodology', 'Discounted lifecycle cash-flow estimate.'))}</p><table><thead><tr><th>Item</th><th>Value</th></tr></thead><tbody>{financial_rows}</tbody></table><h3>Annual lifecycle cash flow</h3><div class="table-scroll"><table><thead><tr><th>Year</th><th>Nominal net cash flow</th><th>Discounted cash flow</th><th>Cumulative discounted cash flow</th></tr></thead><tbody>{cash_flow_rows_html}</tbody></table></div></section>
<section id="rainfall-quality"><h2>Rainfall quality and completeness</h2><dl>{rainfall_quality_rows}</dl><h3>Missing periods</h3><p>Up to 20 missing periods are shown, including partial-year boundary periods.</p><table><thead><tr><th>Start</th><th>End</th><th>Days</th></tr></thead><tbody>{missing_period_rows}</tbody></table></section>
<section id="yearly-rainfall"><h2>Yearly rainfall summary</h2><div class="table-scroll"><table><thead><tr><th>Year</th><th>Observed days</th><th>Missing days</th><th>Completeness</th><th>Precipitation ({escape(report['precipitation_unit'])})</th><th>Wet days</th><th>Status</th></tr></thead><tbody>{yearly_rainfall_rows}</tbody></table></div></section>
<section id="rainfall-events"><h2>Rainfall-event summary</h2><p>{format_number(int(event_summary.get('event_count', 0)), max_decimal_places=0)} event(s) were identified using an antecedent dry threshold of {format_number(float(event_summary.get('antecedent_dry_days', 1.0)))} day(s). Average event precipitation: {format_number(float(event_summary.get('average_event_precipitation', 0.0)), max_decimal_places=3)} {escape(report['precipitation_unit'])}; largest event: {format_number(float(event_summary.get('largest_event_precipitation', 0.0)), max_decimal_places=3)} {escape(report['precipitation_unit'])}. The table lists up to the 10 largest events.</p><div class="table-scroll"><table><thead><tr><th>Event</th><th>Start</th><th>End</th><th>Duration (days)</th><th>Wet days</th><th>Precipitation ({escape(report['precipitation_unit'])})</th></tr></thead><tbody>{rainfall_event_rows}</tbody></table></div></section>
<section id="first-flush-summary"><h2>First-flush diversion summary</h2><p>Event counts are assigned to the calendar year in which each rainfall event starts. Volumes use the complete simulated record and reconcile gross runoff less first-flush diversion to net collected water.</p><h3>Yearly totals</h3><div class="table-scroll"><table><thead><tr><th>Year</th><th>Events started</th><th>Gross runoff ({escape(report['volume_unit'])})</th><th>First-flush diversion ({escape(report['volume_unit'])})</th><th>Net collected ({escape(report['volume_unit'])})</th><th>Diverted</th></tr></thead><tbody>{first_flush_yearly_rows}</tbody></table></div><h3>Rainfall-event totals</h3><div class="table-scroll"><table><thead><tr><th>Event</th><th>Start</th><th>End</th><th>Wet timesteps</th><th>Gross runoff ({escape(report['volume_unit'])})</th><th>First-flush diversion ({escape(report['volume_unit'])})</th><th>Net collected ({escape(report['volume_unit'])})</th><th>Diverted</th></tr></thead><tbody>{first_flush_event_rows}</tbody></table></div></section>
<section id="analysis-provenance"><h2>Analysis provenance and reproducibility</h2><dl>{provenance_rows}</dl></section>
<section id="reliability-curve"><h2>Reliability curve</h2><div class="chart"><svg viewBox="0 0 {chart_width:.0f} {chart_height:.0f}" role="img" aria-label="Reliability versus tank size chart">
<g class="grid">{y_grid}{x_ticks}</g><polyline class="curve" points="{polyline}"/>{circles}{selected_marker}
<text class="axis-label" x="{left + plot_width / 2:.2f}" y="{chart_height - 10:.2f}" text-anchor="middle">Tank size ({escape(report['volume_unit'])})</text>
<text class="axis-label" transform="translate(18 {top + plot_height / 2:.2f}) rotate(-90)" text-anchor="middle">Reliability (%)</text>
</svg></div><div class="chart-legend"><span><i class="swatch primary-tank"></i>Primary tank size</span></div><div class="table-scroll"><table class="chart-data"><caption>Reliability curve data</caption><thead><tr><th>Tank size ({escape(report['volume_unit'])})</th><th>Reliability</th></tr></thead><tbody>{reliability_data_rows}</tbody></table></div></section>
<section id="yearly-demand-reliability"><h2>Yearly demand reliability - {format_number(float(report['selected_tank_size']), max_decimal_places=0)} {escape(report['volume_unit'])} tank</h2><div class="chart"><svg viewBox="0 0 {yearly_chart_width:.0f} {yearly_chart_height:.0f}" role="img" aria-label="Yearly percentage of days demand was met or not met">
<g class="grid">{yearly_grid}{yearly_labels}</g>{yearly_bars}{yearly_markers}
<text class="axis-label" x="{yearly_left + yearly_plot_width / 2:.2f}" y="{yearly_chart_height - 10:.2f}" text-anchor="middle">Year</text>
<text class="axis-label" transform="translate(18 {yearly_top + yearly_plot_height / 2:.2f}) rotate(-90)" text-anchor="middle">Days (%)</text>
</svg></div><div class="chart-legend"><span><i class="swatch year-met"></i>Demand met</span><span><i class="swatch year-unmet"></i>Demand not met</span><span><i class="swatch year-reliability"></i>Tank reliability</span></div><div class="table-scroll"><table class="chart-data"><caption>Yearly demand reliability data</caption><thead><tr><th>Year</th><th>Days met</th><th>Met</th><th>Days not met</th><th>Not met</th></tr></thead><tbody>{yearly_data_rows}</tbody></table></div></section>
<section id="tank-level-distribution"><h2>Tank level distribution</h2><div class="chart"><svg viewBox="0 0 {distribution_width:.0f} {distribution_height:.0f}" role="img" aria-label="Distribution of days by tank level range">
<g class="grid">{distribution_grid}</g>{distribution_bars}
<text class="axis-label" x="{distribution_left + distribution_plot_width / 2:.2f}" y="{distribution_height - 10:.2f}" text-anchor="middle">Tank level range ({escape(report['volume_unit'])})</text>
<text class="axis-label" transform="translate(18 {distribution_top + distribution_plot_height / 2:.2f}) rotate(-90)" text-anchor="middle">Days</text>
</svg></div><div class="table-scroll"><table class="chart-data"><caption>Tank level distribution data</caption><thead><tr><th>Tank level range ({escape(report['volume_unit'])})</th><th>Days</th></tr></thead><tbody>{distribution_data_rows}</tbody></table></div></section>
{multitank_html}
<footer>Generated by RWH Calculator at {escape(provenance.get('generated_at', metadata.get('date', 'Not available')))}</footer>
</main></div><div id="chart-tooltip" class="chart-tooltip" role="tooltip"></div>
<script>
const reportShell=document.querySelector('.report-shell');
const tocToggle=document.getElementById('toc-toggle');
function setTocCollapsed(collapsed){{
  reportShell.classList.toggle('toc-collapsed',collapsed);
  tocToggle.setAttribute('aria-expanded',String(!collapsed));
  tocToggle.textContent=collapsed?'Show contents':'Hide contents';
  try{{sessionStorage.setItem('rwh-report-toc-collapsed',collapsed?'1':'0');}}catch(_error){{}}
}}
let storedTocState='0';try{{storedTocState=sessionStorage.getItem('rwh-report-toc-collapsed')||'0';}}catch(_error){{}}
setTocCollapsed(storedTocState==='1');
tocToggle.addEventListener('click',()=>setTocCollapsed(!reportShell.classList.contains('toc-collapsed')));
const tocLinks=[...document.querySelectorAll('.toc a[href^="#"]')];
const tocTargets=tocLinks.map((link)=>document.querySelector(link.getAttribute('href'))).filter(Boolean);
if('IntersectionObserver' in window){{
  const tocObserver=new IntersectionObserver((entries)=>{{
const visible=entries.filter((entry)=>entry.isIntersecting).sort((a,b)=>a.boundingClientRect.top-b.boundingClientRect.top);
if(!visible.length)return;
tocLinks.forEach((link)=>link.classList.toggle('active',link.getAttribute('href')==='#'+visible[0].target.id));
  }},{{rootMargin:'-10% 0px -75% 0px',threshold:0}});
  tocTargets.forEach((target)=>tocObserver.observe(target));
}}
const chartTooltip=document.getElementById('chart-tooltip');
const locationMapElement=null;
if(locationMapElement&&window.L){{
  const points=JSON.parse(locationMapElement.dataset.points);
  const map=L.map(locationMapElement,{{scrollWheelZoom:false}});
  const bounds=[];
  points.forEach((point)=>{{
const icon=L.divIcon({{className:'map-star',html:'<span style="color:'+point.color+'">★</span>',iconSize:[24,24],iconAnchor:[12,12]}});
L.marker([point.latitude,point.longitude],{{icon}}).addTo(map).bindTooltip(point.label);
bounds.push([point.latitude,point.longitude]);
  }});
  if(bounds.length>1)map.fitBounds(bounds,{{padding:[35,35],maxZoom:13}});else map.setView(bounds[0],10);
}}
document.querySelectorAll('[data-tooltip]').forEach((element)=>{{
  element.addEventListener('mouseenter',()=>{{chartTooltip.textContent=element.dataset.tooltip;chartTooltip.style.display='block';}});
  element.addEventListener('mousemove',(event)=>{{
const left=Math.min(event.clientX+12,window.innerWidth-chartTooltip.offsetWidth-8);
const top=Math.min(event.clientY+12,window.innerHeight-chartTooltip.offsetHeight-8);
chartTooltip.style.left=Math.max(8,left)+'px';chartTooltip.style.top=Math.max(8,top)+'px';
  }});
  element.addEventListener('mouseleave',()=>{{chartTooltip.style.display='none';}});
}});
document.querySelectorAll('[data-sortable-table] .sort-button').forEach((button)=>{{
  button.addEventListener('click',()=>{{
const table=button.closest('table');const body=table.querySelector('tbody');
const column=Number(button.dataset.column);const ascending=button.dataset.direction!=='asc';
const rows=[...body.querySelectorAll('tr')];
rows.sort((leftRow,rightRow)=>{{
  const left=leftRow.children[column]?.dataset.value||'';const right=rightRow.children[column]?.dataset.value||'';
  const leftNumber=Number(left),rightNumber=Number(right);
  const comparison=(left!==''&&right!==''&&!Number.isNaN(leftNumber)&&!Number.isNaN(rightNumber))
    ?leftNumber-rightNumber:left.localeCompare(right,undefined,{{numeric:true}});
  return ascending?comparison:-comparison;
}});
table.querySelectorAll('.sort-button').forEach((item)=>delete item.dataset.direction);
button.dataset.direction=ascending?'asc':'desc';rows.forEach((row)=>body.appendChild(row));
  }});
}});
function refreshTankHistory(sectionId){{
  const section=document.getElementById(sectionId);if(!section)return;
  const rangeMode=section.dataset.historyMode==='range';
  section.querySelector('[data-year-controls]').hidden=rangeMode;
  section.querySelector('[data-range-controls]').hidden=!rangeMode;
  section.querySelector('[data-year-groups]').style.display=rangeMode?'none':'';
  section.querySelector('[data-range-groups]').style.display=rangeMode?'':'none';
  if(rangeMode){{
const startControl=section.querySelector('[data-range-start]');
const endControl=section.querySelector('[data-range-end]');
let startMonth=Number(startControl.value),endMonth=Number(endControl.value);
if(startMonth>endMonth){{
  if(document.activeElement===startControl)endControl.value=String(startMonth);
  else startControl.value=String(endMonth);
  startMonth=Number(startControl.value);endMonth=Number(endControl.value);
}}
const monthDate=(value)=>new Date(Date.UTC(Math.floor(value/12),value%12,1));
const startDate=monthDate(startMonth);
const endDate=new Date(Date.UTC(Math.floor(endMonth/12),endMonth%12+1,1));
const formatMonth=(date)=>date.toLocaleDateString(undefined,{{month:'short',year:'numeric',timeZone:'UTC'}});
section.querySelector('[data-range-label]').textContent=formatMonth(startDate)+' to '+formatMonth(monthDate(endMonth));
const startMs=startDate.getTime(),endMs=endDate.getTime()-1,span=Math.max(endMs-startMs,1);
section.querySelectorAll('[data-history-range-series]').forEach((group)=>{{
  const toggle=section.querySelector('[data-history-series-toggle="'+group.dataset.historyRangeSeries+'"]');
  group.style.display=toggle&&toggle.checked?'':'none';
  const line=group.querySelector('polyline');
  const visiblePoints=JSON.parse(line.dataset.rangePoints).filter((point)=>point[0]>=startMs&&point[0]<=endMs);
  line.setAttribute('points',visiblePoints.map((point)=>{{
    const x=72+(point[0]-startMs)/span*804;
    const circle=group.querySelector('[data-range-date="'+point[0]+'"]');
    if(circle)circle.setAttribute('cx',x.toFixed(2));
    return x.toFixed(2)+','+(circle?circle.getAttribute('cy'):'0');
  }}).join(' '));
  group.querySelectorAll('[data-range-date]').forEach((point)=>{{
    const date=Number(point.dataset.rangeDate);
    point.style.display=date>=startMs&&date<=endMs?'':'none';
  }});
}});
return;
  }}
  const years=section.dataset.years.split(',');
  const index=Math.max(0,Math.min(Number(section.dataset.yearIndex)||0,years.length-1));
  section.dataset.yearIndex=String(index);
  section.querySelectorAll('[data-history-year]').forEach((group)=>{{group.style.display='none';}});
  const active=section.querySelector('[data-history-year="'+years[index]+'"]');
  if(active){{
active.style.display='';
active.querySelectorAll('[data-history-series]').forEach((line)=>{{
  const toggle=section.querySelector('[data-history-series-toggle="'+line.dataset.historySeries+'"]');
  line.style.display=toggle&&toggle.checked?'':'none';
}});
  }}
  section.querySelector('[data-history-year-label]').textContent=years[index];
  section.querySelector('[data-history-previous]').disabled=index===0;
  section.querySelector('[data-history-next]').disabled=index===years.length-1;
}}
function setTankHistoryMode(sectionId,mode){{
  const section=document.getElementById(sectionId);if(!section)return;
  section.dataset.historyMode=mode;refreshTankHistory(sectionId);
}}
function changeTankHistoryYear(sectionId,delta){{
  const section=document.getElementById(sectionId);if(!section)return;
  section.dataset.yearIndex=String((Number(section.dataset.yearIndex)||0)+delta);
  refreshTankHistory(sectionId);
}}
document.querySelectorAll('.tank-history').forEach((section)=>refreshTankHistory(section.id));
</script></body></html>"""
    return _filter_html_report_sections(document, report)


def _build_multitank_report_html(report: dict[str, object]) -> str:
    if not report.get("include_multitank_charts"):
        return ""
    colors = ("#0b5cab", "#2e8b57", "#c94c4c", "#7b4ab5", "#d17a00", "#00838f")
    sections = []
    for chart_index, chart in enumerate(report.get("multitank_charts", [])):
        if chart.get("type") == "yearly_stacked":
            sections.append(_build_stacked_yearly_report_html(chart, chart_index + 1))
            continue
        if chart.get("type") == "tank_history":
            sections.append(_build_tank_history_report_html(chart, chart_index + 1))
            continue
        series_list = chart["series"]
        all_points = [point for series in series_list for point in series["points"]]
        if not all_points:
            continue
        width, height = 900.0, 420.0
        left, right, top, bottom = 72.0, 24.0, 52.0, 62.0
        plot_width, plot_height = width - left - right, height - top - bottom
        x_values = [float(point[0]) for point in all_points]
        y_values = [float(point[1]) for point in all_points]
        x_min, x_max = min(x_values), max(x_values)
        y_max = max(max(y_values), 1.0)
        if x_min == x_max:
            x_max = x_min + 1.0

        def sx(value: float) -> float:
            return left + (value - x_min) / (x_max - x_min) * plot_width

        def sy(value: float) -> float:
            return top + (y_max - value) / y_max * plot_height

        grid = "".join(
            f'<line x1="{left}" y1="{top + plot_height * tick / 4:.2f}" x2="{left + plot_width}" y2="{top + plot_height * tick / 4:.2f}" />'
            f'<text x="{left - 12}" y="{top + plot_height * tick / 4 + 4:.2f}" text-anchor="end">{format_number(y_max * (4 - tick) / 4, max_decimal_places=0)}</text>'
            for tick in range(5)
        )
        polylines = []
        legends = []
        data_rows = []
        for series_index, series in enumerate(series_list):
            color = colors[series_index % len(colors)]
            points = " ".join(f"{sx(float(x)):.2f},{sy(float(y)):.2f}" for x, y in series["points"])
            label = html.escape(str(series["label"]))
            series_id = f"multitank-chart-{chart_index + 1}-series-{series_index + 1}"
            polylines.append(
                f'<polyline id="{series_id}" points="{points}" fill="none" stroke="{color}" '
                f'stroke-width="3"><title>{label}</title></polyline>'
            )
            if chart.get("interactive_series_toggle"):
                legends.append(
                    f'<label class="series-toggle" style="color:{color}"><input type="checkbox" checked '
                    f'onchange="document.getElementById(\'{series_id}\').style.display=this.checked?\'\':\'none\'">'
                    f'<span aria-hidden="true">&mdash;</span> {label}</label>'
                )
            else:
                legends.append(
                    f'<span style="color:{color};font-weight:700"><span aria-hidden="true">&mdash;</span> '
                    f'{label}</span>'
                )
            data_rows.extend(
                f'<tr><td>{label}</td><td>{format_number(float(x))}</td><td>{format_number(float(y))}</td></tr>'
                for x, y in series["points"]
            )
        section_id = f"multitank-chart-{chart_index + 1}"
        sections.append(
            f'<section id="{section_id}"><h2>{html.escape(str(chart["title"]))}</h2>'
            f'<div class="chart"><svg viewBox="0 0 {width:.0f} {height:.0f}" role="img">'
            f'<g class="grid">{grid}</g>{"".join(polylines)}'
            f'<text class="axis-label" x="{left + plot_width / 2:.2f}" y="{height - 10:.2f}" text-anchor="middle">{html.escape(str(chart["x_label"]))}</text>'
            f'<text class="axis-label" transform="translate(18 {top + plot_height / 2:.2f}) rotate(-90)" text-anchor="middle">{html.escape(str(chart["y_label"]))}</text>'
            f'</svg></div><div class="chart-legend">{"".join(legends)}</div>'
            f'<div class="table-scroll"><table class="chart-data"><caption>{html.escape(str(chart["title"]))} data</caption>'
            f'<thead><tr><th>Series</th><th>{html.escape(str(chart["x_label"]))}</th>'
            f'<th>{html.escape(str(chart["y_label"]))}</th></tr></thead>'
            f'<tbody>{"".join(data_rows)}</tbody></table></div></section>'
        )
    return "".join(sections)


def _build_stacked_yearly_report_html(chart: dict[str, object], chart_index: int) -> str:
    yearly = chart["yearly_reliability"]
    if not yearly:
        return ""
    escape = lambda value: html.escape(str(value), quote=True)
    width = max(900.0, 90.0 + (len(yearly) + 1) * 24.0)
    height = 420.0
    left, right, top, bottom = 72.0, 24.0, 38.0, 62.0
    plot_width, plot_height = width - left - right, height - top - bottom
    baseline = top + plot_height
    slot_width = plot_width / (len(yearly) + 1)
    label_step = max((len(yearly) + 9) // 10, 1)
    bars: list[str] = []
    labels: list[str] = []
    markers: list[str] = []
    for index, row in enumerate(yearly):
        bar_x = left + index * slot_width + max(slot_width * 0.15, 1.0)
        bar_width = max(slot_width * 0.7, 1.0)
        met_height = plot_height * float(row["met_percent"]) / 100.0
        unmet_height = plot_height - met_height
        marker_x = bar_x + bar_width / 2
        marker_y = baseline - met_height
        tooltip = (
            f"{int(row['year'])}: demand met {int(row['met_days'])} days "
            f"({format_number(float(row['met_percent']))}%); demand not met {format_number(int(row['unmet_days']), max_decimal_places=0)} days "
            f"({format_number(float(row['unmet_percent']))}%)"
        )
        bars.append(
            f'<rect class="year-met" x="{bar_x:.2f}" y="{marker_y:.2f}" width="{bar_width:.2f}" '
            f'height="{met_height:.2f}" data-tooltip="{escape(tooltip)}"></rect>'
            f'<rect class="year-unmet" x="{bar_x:.2f}" y="{top:.2f}" width="{bar_width:.2f}" '
            f'height="{unmet_height:.2f}" data-tooltip="{escape(tooltip)}"></rect>'
        )
        markers.append(
            f'<circle class="year-reliability" cx="{marker_x:.2f}" cy="{marker_y:.2f}" r="5" '
            f'data-tooltip="{int(row["year"])} tank reliability: {format_number(float(row["met_percent"]))}%"></circle>'
        )
        if index % label_step == 0 or index == len(yearly) - 1:
            labels.append(
                f'<text x="{marker_x:.2f}" y="{baseline + 22:.2f}" text-anchor="middle">'
                f'{int(row["year"])}</text>'
            )
    average = float(chart["selected_reliability"])
    year_count_text = f"{len(yearly)} {'year' if len(yearly) == 1 else 'years'}"
    average_x = left + (len(yearly) + 0.5) * slot_width
    average_y = baseline - plot_height * average / 100.0
    markers.append(
        f'<circle class="year-reliability" cx="{average_x:.2f}" cy="{average_y:.2f}" r="6" '
        f'data-tooltip="Average tank reliability over {year_count_text}: {format_number(average)}%"></circle>'
    )
    labels.append(
        f'<text x="{average_x:.2f}" y="{baseline + 18:.2f}" text-anchor="middle">'
        f'<tspan x="{average_x:.2f}">Average</tspan><tspan x="{average_x:.2f}" dy="13">'
        f'({year_count_text})</tspan></text>'
    )
    grid = "".join(
        f'<line x1="{left}" y1="{top + plot_height * (100 - value) / 100:.2f}" '
        f'x2="{left + plot_width}" y2="{top + plot_height * (100 - value) / 100:.2f}" />'
        f'<text x="{left - 12}" y="{top + plot_height * (100 - value) / 100 + 4:.2f}" '
        f'text-anchor="end">{value}%</text>'
        for value in range(0, 101, 25)
    )
    data_rows = "".join(
        f'<tr><td>{int(row["year"])}</td><td>{int(row["met_days"]):,}</td>'
        f'<td>{format_number(float(row["met_percent"]))}%</td><td>{format_number(int(row["unmet_days"]), max_decimal_places=0)}</td>'
        f'<td>{format_number(float(row["unmet_percent"]))}%</td></tr>'
        for row in yearly
    )
    return (
        f'<section id="multitank-chart-{chart_index}"><h2>{escape(chart["title"])}</h2>'
        f'<div class="chart"><svg viewBox="0 0 {width:.0f} {height:.0f}" role="img">'
        f'<g class="grid">{grid}{"".join(labels)}</g>{"".join(bars)}{"".join(markers)}'
        f'<text class="axis-label" x="{left + plot_width / 2:.2f}" y="{height - 10:.2f}" '
        f'text-anchor="middle">Year</text><text class="axis-label" '
        f'transform="translate(18 {top + plot_height / 2:.2f}) rotate(-90)" '
        f'text-anchor="middle">Days (%)</text></svg></div><div class="chart-legend">'
        f'<span><i class="swatch year-met"></i>Demand met</span>'
        f'<span><i class="swatch year-unmet"></i>Demand not met</span>'
        f'<span><i class="swatch year-reliability"></i>Tank reliability</span></div>'
        f'<div class="table-scroll"><table class="chart-data"><caption>{escape(chart["title"])} data</caption>'
        f'<thead><tr><th>Year</th><th>Days met</th><th>Met</th><th>Days not met</th>'
        f'<th>Not met</th></tr></thead><tbody>{data_rows}</tbody></table></div></section>'
    )


def _build_tank_history_report_html(chart: dict[str, object], chart_index: int) -> str:
    series_list = chart["series"]
    years = sorted(
        {
            int(year)
            for series in series_list
            for year in series.get("yearly_points", {})
        }
    )
    if not years:
        return ""
    dated_values = [
        (pd.Timestamp(date), float(level))
        for series in series_list
        for date, level in series.get("dated_points", [])
    ]
    if not dated_values:
        return ""
    first_month = min(date for date, _level in dated_values).to_period("M")
    last_month = max(date for date, _level in dated_values).to_period("M")
    first_month_index = first_month.year * 12 + first_month.month - 1
    last_month_index = last_month.year * 12 + last_month.month - 1
    colors = ("#0b5cab", "#2e8b57", "#c94c4c", "#7b4ab5", "#d17a00", "#00838f")
    section_id = f"multitank-chart-{chart_index}"
    width, height = 900.0, 420.0
    left, right, top, bottom = 72.0, 24.0, 38.0, 62.0
    plot_width, plot_height = width - left - right, height - top - bottom
    all_values = [
        float(point[1])
        for series in series_list
        for points in series.get("yearly_points", {}).values()
        for point in points
    ]
    y_max = max(max(all_values, default=0.0), 1.0)

    def sx(value: float) -> float:
        return left + (value - 1.0) / 365.0 * plot_width

    def sy(value: float) -> float:
        return top + (y_max - value) / y_max * plot_height

    grid = "".join(
        f'<line x1="{left}" y1="{top + plot_height * tick / 4:.2f}" '
        f'x2="{left + plot_width}" y2="{top + plot_height * tick / 4:.2f}" />'
        f'<text x="{left - 12}" y="{top + plot_height * tick / 4 + 4:.2f}" '
        f'text-anchor="end">{format_number(y_max * (4 - tick) / 4, max_decimal_places=0)}</text>'
        for tick in range(5)
    ) + "".join(
        f'<line x1="{sx(day):.2f}" y1="{top}" x2="{sx(day):.2f}" y2="{top + plot_height}" />'
        f'<text x="{sx(day):.2f}" y="{top + plot_height + 22:.2f}" text-anchor="middle">{day}</text>'
        for day in (1, 92, 183, 274, 366)
    )
    year_groups: list[str] = []
    for year_index, year in enumerate(years):
        lines: list[str] = []
        for series_index, series in enumerate(series_list):
            points = series.get("yearly_points", {}).get(str(year), [])
            if not points:
                continue
            color = colors[series_index % len(colors)]
            coordinates = " ".join(
                f"{sx(float(x_value)):.2f},{sy(float(y_value)):.2f}"
                for x_value, y_value in points
            )
            lines.append(
                f'<polyline data-history-series="{series_index}" points="{coordinates}" fill="none" '
                f'stroke="{color}" stroke-width="3"></polyline>'
                + "".join(
                    f'<circle class="tank-history-point" data-history-series="{series_index}" '
                    f'cx="{sx(float(day)):.2f}" cy="{sy(float(level)):.2f}" r="7" '
                    f'style="color:{color}" data-tooltip="{html.escape(str(series["label"]))}; '
                    f'{year}, day {format_number(float(day), max_decimal_places=0)}: {format_number(float(level))} '
                    f'{html.escape(str(chart["y_label"]))}"></circle>'
                    for day, level in points
                )
            )
        display = "" if year_index == 0 else "none"
        year_groups.append(
            f'<g data-history-year="{year}" style="display:{display}">{"".join(lines)}</g>'
        )
    range_series: list[str] = []
    range_span = max((last_month.end_time - first_month.start_time).total_seconds(), 1.0)
    for series_index, series in enumerate(series_list):
        color = colors[series_index % len(colors)]
        points = [(pd.Timestamp(date), float(level)) for date, level in series.get("dated_points", [])]
        coordinates = " ".join(
            f'{left + (date - first_month.start_time).total_seconds() / range_span * plot_width:.2f},'
            f'{sy(level):.2f}' for date, level in points
        )
        encoded_points = html.escape(json.dumps([[int(date.value // 1_000_000), level] for date, level in points]), quote=True)
        circles = "".join(
            f'<circle class="tank-history-point" data-history-series="{series_index}" '
            f'data-range-date="{int(date.value // 1_000_000)}" data-range-level="{level}" '
            f'cx="{left + (date - first_month.start_time).total_seconds() / range_span * plot_width:.2f}" '
            f'cy="{sy(level):.2f}" r="7" style="color:{color}" '
            f'data-tooltip="{html.escape(str(series["label"]))}; {date:%Y-%m-%d}: '
            f'{format_number(level)} {html.escape(str(chart["y_label"]))}"></circle>'
            for date, level in points
        )
        range_series.append(
            f'<g data-history-range-series="{series_index}"><polyline data-range-points="{encoded_points}" '
            f'points="{coordinates}" fill="none" stroke="{color}" stroke-width="3"></polyline>{circles}</g>'
        )
    toggles = "".join(
        f'<label class="series-toggle" style="color:{colors[index % len(colors)]}">'
        f'<input type="checkbox" checked data-history-series-toggle="{index}" '
        f'onchange="refreshTankHistory(\'{section_id}\')"><span aria-hidden="true">&mdash;</span> '
        f'{html.escape(str(series["label"]))}</label>'
        for index, series in enumerate(series_list)
    )
    data_rows = "".join(
        f'<tr><td>{html.escape(str(series["label"]))}</td><td>{html.escape(str(date))}</td>'
        f'<td>{format_number(float(level))}</td></tr>'
        for series in series_list
        for date, level in series.get("dated_points", [])
    )
    return (
        f'<section id="{section_id}" class="tank-history" data-years="{",".join(map(str, years))}" '
        f'data-year-index="0" data-history-mode="year"><h2>{html.escape(str(chart["title"]))}</h2>'
        f'<div class="history-mode-controls"><label><input type="radio" name="{section_id}-mode" checked '
        f'onchange="setTankHistoryMode(\'{section_id}\',\'year\')"> Single year</label>'
        f'<label><input type="radio" name="{section_id}-mode" '
        f'onchange="setTankHistoryMode(\'{section_id}\',\'range\')"> Custom range</label></div>'
        f'<div class="history-controls" data-year-controls><button type="button" data-history-previous '
        f'onclick="changeTankHistoryYear(\'{section_id}\',-1)" title="Previous year">&#9664;</button>'
        f'<strong data-history-year-label>{years[0]}</strong><button type="button" data-history-next '
        f'onclick="changeTankHistoryYear(\'{section_id}\',1)" title="Next year">&#9654;</button></div>'
        f'<div class="history-range-controls" data-range-controls hidden><strong data-range-label></strong>'
        f'<input type="range" min="{first_month_index}" max="{last_month_index}" value="{first_month_index}" '
        f'data-range-start oninput="refreshTankHistory(\'{section_id}\')">'
        f'<input type="range" min="{first_month_index}" max="{last_month_index}" value="{last_month_index}" '
        f'data-range-end oninput="refreshTankHistory(\'{section_id}\')"></div>'
        f'<div class="chart"><svg viewBox="0 0 {width:.0f} {height:.0f}" role="img">'
        f'<g class="grid">{grid}</g><g data-year-groups>{"".join(year_groups)}</g>'
        f'<g data-range-groups style="display:none">{"".join(range_series)}</g>'
        f'<text class="axis-label" x="{left + plot_width / 2:.2f}" y="{height - 10:.2f}" '
        f'text-anchor="middle">Day of year</text><text class="axis-label" '
        f'transform="translate(18 {top + plot_height / 2:.2f}) rotate(-90)" '
        f'text-anchor="middle">{html.escape(str(chart["y_label"]))}</text></svg></div>'
        f'<div class="chart-legend">{toggles}</div>'
        f'<div class="table-scroll"><table class="chart-data"><caption>{html.escape(str(chart["title"]))} data</caption>'
        f'<thead><tr><th>Series</th><th>Date</th><th>{html.escape(str(chart["y_label"]))}</th>'
        f'</tr></thead><tbody>{data_rows}</tbody></table></div></section>'
    )
