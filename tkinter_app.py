from __future__ import annotations

import csv
import copy
import datetime as dt
import http.server
import io
import importlib.metadata as importlib_metadata
import itertools
import json
import math
import os
import queue
import re
import shutil
import subprocess
import sys
import tkinter as tk
import tkinter.font as tkfont
import tempfile
import threading
import time
import webbrowser
import weakref
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from functools import partial
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from urllib.parse import parse_qs, quote, urlparse

import pandas as pd
import pycountry
import resvg_py
from PIL import Image, ImageDraw, ImageTk
from tkintermapview import TkinterMapView, decimal_to_osm

from rainwater_app.acis import (
    default_complete_calendar_range,
    fetch_daily_station_data,
    fetch_station_options,
    fetch_station_options_bbox,
)
from rainwater_app.analysis_state import ANALYSIS_ALGORITHM_VERSION, analysis_input_signature
from rainwater_app.analysis_service import (
    AnalysisOutcome,
    AnalysisProgressEvent,
    AnalysisService,
)
from rainwater_app.aviation import (
    acis_aviation_identifiers,
    verified_airport_weather_stations,
)
from rainwater_app.app_paths import (
    migrate_legacy_application_data,
    project_backup_dir,
    user_data_dir,
)
from rainwater_app.climate_normals import (
    ClimateNormalRequestCancelled,
    NCEI_CLIMATE_NORMALS_URL,
    NCEI_BULK_ARCHIVE_SIZE_BYTES,
    PRECIPITATION_NORMAL_RECORD_KEYS,
    cancel_annual_precipitation_normal_request,
    climate_normals_bulk_archive_installed,
    climate_normals_bulk_archive_path,
    download_climate_normals_bulk_archive,
    fetch_annual_precipitation_normal,
    fetch_us_annual_precipitation_normal_catalog,
    filter_climate_normal_stations,
    remove_climate_normals_bulk_archive,
)
from rainwater_app.defaults import DEFAULT_SURFACES, default_project_config, default_surface_runoff
from rainwater_app.eccc import (
    fetch_canadian_daily_station_data,
    fetch_canadian_station_options,
    fetch_canadian_station_options_bbox,
)
from rainwater_app.engine import (
    AnalysisCancelledError,
    demand_object_daily_value_for_date,
    demand_object_sewer_eligible_fraction,
    simulate_hourly_tank,
)
from rainwater_app.equipment_catalog import (
    CANDIDATE_DISPOSITIONS,
    EQUIPMENT_CATEGORIES,
    built_in_equipment_library,
    candidate_from_product,
    default_project_candidates,
    effective_candidate_product,
    evaluate_combination_compatibility,
    evaluate_product_eligibility,
    load_equipment_library,
    normalize_product,
    normalized_constraints,
    save_equipment_library,
    update_candidate_snapshot,
)
from rainwater_app.execution_log import (
    DETAIL_LEVELS,
    ExecutionLogEntry,
    ExecutionLogger,
    normalize_log_detail,
)
from rainwater_app.example_projects import EXAMPLE_PROJECT_LABELS, build_completed_example
from rainwater_app.financial import tariff_rate_per_gallon
from rainwater_app.financial_service import FinancialAnalysisService
from rainwater_app.candidate_service import CandidateAnalysisService
from rainwater_app.first_flush import (
    CODE_MINIMUM_PRESET,
    DESIGN_PRESET_LABELS,
    GUIDED_SIZING_METHOD,
    MANUAL_SIZING_METHOD,
    SIZING_METHOD_LABELS,
    first_flush_guidance,
    normalize_first_flush_design_preset,
    normalize_first_flush_sizing_method,
)
from rainwater_app.geocoding import geocode_osm_address, reverse_geocode_osm
from rainwater_app.map_tiles import TileLoadTask, shared_tile_loader
from rainwater_app.models import (
    DEFAULT_TOILET_FLUSHES_PER_PERSON_PER_DAY,
    DEFAULT_TOILET_VOLUME_GALLONS_PER_FLUSH,
    FRACTIONAL_SCHEDULE_TYPE,
    FILTRATION_SYSTEM_FLOW_RATES_GPM,
    OCCUPANCY_SCHEDULE_TYPE,
    TRANSFER_PUMP_TYPES,
    UNIT_SYSTEMS,
    DemandObject,
    MONTH_KEYS,
    ProjectConfig,
    Surface,
    SystemComponentParameters,
    TankParameters,
    WEEKDAY_KEYS,
    common_hourly_schedule_templates,
    common_hourly_schedule_template_types,
    default_sewer_eligible_for_object_type,
    default_hourly_weekly_fractions,
    fixture_daily_demand_gallons,
    migrate_legacy_demand_inputs,
    normalized_schedule_months,
    normalize_schedule_type,
    normalize_filtration_system_flow_gpm,
    normalize_unit_system,
    purge_unused_hourly_schedules,
    schedule_months_for,
    unused_hourly_schedule_names,
)
from rainwater_app.number_formatting import (
    EUROPEAN_NUMBER_FORMAT,
    NUMBER_FORMATS,
    US_NUMBER_FORMAT,
    format_number,
    normalize_number_format,
    parse_number,
    set_active_number_format,
)
from rainwater_app.rainfall import (
    HOURLY_PRECIPITATION_COLUMNS,
    disaggregate_daily_rainfall_hyetos,
    has_hourly_rainfall,
    load_rainfall_csv,
    load_hourly_rainfall_csv,
    remove_hourly_rainfall,
)
from rainwater_app.rainfall_quality import (
    RAINFALL_DATA_TYPE_LABELS,
    RainfallQualityAssessment,
    assess_rainfall_record,
    rainfall_data_type_label,
)
from rainwater_app.recommendations import (
    RecommendationSet,
    recommend_tank_sizes,
    selected_design_warnings,
)
from rainwater_app.reporting import (
    DEFAULT_REPORT_SECTIONS,
    REPORT_SECTION_DEFINITIONS,
    REPORT_SCHEMA_VERSION,
    ReportModel,
    atomic_write_text,
    report_average_annual_precipitation as _report_average_annual_precipitation,
    report_average_annual_rainfall_volumes as _report_average_annual_rainfall_volumes,
    report_demand_summary as _report_demand_summary,
    report_first_flush_summaries as _report_first_flush_summaries,
    report_surface_rows as _report_surface_rows,
    report_tank_level_distribution as _report_tank_level_distribution,
    normalize_report_sections,
    tank_volume_capacity_label as _tank_volume_capacity_label,
    yearly_demand_reliability as _yearly_demand_reliability,
)
from rainwater_app.report_service import ReportRenderingService
from rainwater_app.pdf_rendering import (
    _draw_pdf_reliability_curve as draw_pdf_reliability_curve,
    _draw_pdf_tank_level_distribution as draw_pdf_tank_level_distribution,
    _draw_pdf_yearly_demand_reliability as draw_pdf_yearly_demand_reliability,
    _write_pdf_with_pypdf as write_pdf_with_pypdf,
)
from rainwater_app.project_state import WorkingDraftStore, project_state_fingerprint
from rainwater_app.storage import SQLiteStore
from rainwater_app.system_model import (
    compile_builder_system,
    ensure_primary_overflow_paths,
    validate_builder_system,
)
from rainwater_app.stations import bounding_box, filter_stations, nearest_stations
from rainwater_app.ui_logic import (
    antecedent_dry_period_from_days as _antecedent_dry_period_from_days,
    antecedent_dry_period_to_days as _antecedent_dry_period_to_days,
    common_demand_object_templates as _common_demand_object_templates,
    demand_flow_from_gallons_per_minute as _demand_flow_from_gallons_per_minute,
    demand_flow_to_gallons_per_minute as _demand_flow_to_gallons_per_minute,
    graph_step_count as _graph_step_count,
    normalized_demand_object_indices as _normalized_demand_object_indices,
    parse_coordinates as _parse_coordinates,
    safe_project_file_name as _safe_project_file_name,
    state_code as _state_code,
    system_object_editor_validation as _system_object_editor_validation,
    validated_demand_object_library as _validated_demand_object_library,
    validated_schedule_library as _validated_schedule_library,
)
from rainwater_app.units import (
    LITERS_PER_GALLON,
    area_to_display,
    area_to_internal,
    area_unit,
    is_metric,
    precip_to_display,
    precip_to_internal,
    precip_unit,
    volume_to_display,
    volume_to_internal,
    volume_unit,
)
from rainwater_app.optimization import optimize_indirect_system

APP_TITLE = "Rainwater Harvesting Calculator"
SYSTEM_ANIMATION_FRAME_MS = 40
SYSTEM_ANIMATION_CYCLES_PER_SECOND = 0.6
DEMAND_FLOW_UNITS = ("gpm", "gal/hr", "lpm", "liter/hr")
DEFAULT_WINDOW_WIDTH = 1200
DEFAULT_WINDOW_HEIGHT = 680
MINIMUM_WINDOW_WIDTH = 750
RESULTS_CHART_HEIGHT = 340
RESULTS_MULTITANK_CHART_HEIGHT = 360
RESULTS_HOURLY_CHART_HEIGHT = 480
RESULTS_PLOT_STACK_BREAKPOINT = 900
MAX_RECENT_PROJECTS = 8
MAX_RECENT_RAINFALL_CSVS = 8
MAX_PINNED_RAINFALL_CSVS = 1_000
PINNED_RAINFALL_MENU_GROUP_SIZE = 50
TEXT_SCALE_PERCENTAGES = (80, 90, 100, 110, 125, 150)
DEFAULT_TEXT_SCALE_PERCENT = 100
PROJECT_STATE_POLL_MS = 1_000
WORKING_DRAFT_SAVE_MS = 10_000
ONLINE_HELP_URL = "https://ianvg.github.io/rainwater-calculator-py/"
RAINFALL_DATA_TYPE_BY_LABEL = {
    label: key for key, label in RAINFALL_DATA_TYPE_LABELS.items()
}
RAINFALL_RESOLUTION_LABELS = {
    "daily": "Daily",
    "hourly": "Hourly",
    "subhourly": "Subhourly",
    "monthly": "Monthly",
    "unknown": "Unknown",
}
SCHEDULE_TYPE_LABELS = {
    FRACTIONAL_SCHEDULE_TYPE: "Fractional multiplier",
    OCCUPANCY_SCHEDULE_TYPE: "Occupancy (binary)",
}
SCHEDULE_TYPE_BY_LABEL = {
    label: schedule_type for schedule_type, label in SCHEDULE_TYPE_LABELS.items()
}


def _constraint_display_value(value: object) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    return str(value)


def _normalize_text_scale_percent(value: object) -> int:
    """Return the closest supported application text scale."""
    if isinstance(value, bool):
        return DEFAULT_TEXT_SCALE_PERCENT
    try:
        requested = int(value)
    except (TypeError, ValueError):
        return DEFAULT_TEXT_SCALE_PERCENT
    return min(TEXT_SCALE_PERCENTAGES, key=lambda option: abs(option - requested))


def _two_line_heading_text(
    text: str,
    column_width: int,
    measure: Callable[[str], int],
    *,
    horizontal_padding: int = 18,
) -> str:
    """Wrap a table heading at a word boundary, using no more than two lines."""
    normalized = " ".join(str(text).split())
    if not normalized or measure(normalized) + horizontal_padding <= column_width:
        return normalized
    words = normalized.split()
    if len(words) < 2:
        return normalized
    split_at = min(
        range(1, len(words)),
        key=lambda index: (
            max(measure(" ".join(words[:index])), measure(" ".join(words[index:]))),
            abs(measure(" ".join(words[:index])) - measure(" ".join(words[index:]))),
        ),
    )
    return f"{' '.join(words[:split_at])}\n{' '.join(words[split_at:])}"

PROJECT_FORM_VARIABLES = (
    "project_name_var", "author_name_var", "street_address_var", "city_var",
    "state_or_province_var", "postal_code_var", "latitude_var", "longitude_var",
    "unit_var", "country_var", "canadian_precip_var", "system_type_var",
    "simple_daily_var", "daily_demand_days_var", "hourly_schedule_enabled_var",
    "use_synthetic_hourly_rainfall_var", "rainfall_data_type_var",
    "rainfall_resolution_var", "rainfall_timezone_var", "rainfall_timing_var",
    "pump_capacity_var", "filtration_pump_capacity_var", "filter_recovery_var",
    "filtration_system_count_var",
    "booster_tank_size_var", "booster_initial_fill_var", "booster_refill_level_var",
    "municipal_backup_enabled_var", "flushes_var", "toilet_flush_var",
    "urinal_flush_var", "graph_start_var", "graph_end_var", "graph_step_var",
    "graph_auto_step_count_var", "selected_tank_var",
    "recommendation_reliability_target_var", "recommendation_marginal_gain_var",
    "multitank_comparison_var", "initial_fill_var", "reserve_var",
    "first_flush_sizing_method_var", "first_flush_design_preset_var",
    "first_flush_antecedent_unit_var", "first_flush_antecedent_var",
    "financial_currency_var", "financial_water_rate_var", "financial_sewer_rate_var",
    "financial_tariff_unit_var", "financial_sewer_eligible_var",
    "financial_installed_cost_var", "financial_incentives_var",
    "financial_fixed_maintenance_var", "financial_maintenance_percent_var",
    "financial_analysis_period_var", "financial_discount_rate_var",
    "financial_utility_escalation_var", "financial_maintenance_escalation_var",
    "financial_electricity_escalation_var", "financial_pump_power_var",
    "financial_pump_flow_rate_var", "financial_replacement_cost_var",
    "financial_replacement_interval_var", "financial_replacement_escalation_var",
    "optimization_minimum_reliability_var", "optimization_electricity_rate_var",
    "optimization_objective_var", "optimization_maximum_makeup_var",
    "optimization_maximum_cost_var", "optimization_positive_savings_var",
)


ACIS_SOURCE_URL = "https://www.rcc-acis.org/"
ECCC_SOURCE_URL = "https://climate.weather.gc.ca/"
OSM_TILE_URL = os.environ.get("RWH_OSM_TILE_URL", "https://tile.openstreetmap.org/{z}/{x}/{y}.png")
OPTIMIZATION_SECTION_HELP = {
    "Problem assumptions": (
        "Design variables remain open to the optimizer. Fixed project inputs are read directly from their "
        "source tabs so duplicate values cannot drift out of sync."
    ),
    "Objectives": (
        "The objective defines what should be made best. It ranks the designs that satisfy every active "
        "constraint. Only one objective is used for each optimization run."
    ),
    "Constraints": (
        "Constraints define the limits that every feasible design must satisfy. Minimum rainwater reliability "
        "is always active. Maximum annual municipal makeup, maximum installed cost, and positive net annual "
        "savings are optional constraints."
    ),
    "Catalog": (
        "The shared library supplies reusable primary tanks, transfer pumps, filtration systems, and buffer "
        "tanks. Applying a product creates a project snapshot. Project eligibility and compatibility determine "
        "which combinations the optimizer may evaluate. Starter values are illustrative, not vendor quotations."
    ),
    "Results": (
        "Results show the catalog combinations evaluated by the optimizer. Feasible designs are ranked by the "
        "selected objective; designs that do not satisfy every active constraint remain unranked."
    ),
}
ABOUT_TEXT = """RWH Calculator

Copyright (c) 2026 RWH Calculator contributors
All rights reserved except as granted by the open-source license below.

OPEN-SOURCE LICENSE:
RWH Calculator is open-source software released under the
Zero-Clause BSD (0BSD) license.

Permission to use, copy, modify, and/or distribute this software for any
purpose with or without fee is hereby granted.

APPLICATION ICONS:
The water-drop application icon and selected interface icons, including the
trash and player controls, are adapted from the MIT-licensed Tabler Icons collection.
Copyright (c) 2020-2026 Paweł Kuna. https://github.com/tabler/tabler-icons

MAP AND ADDRESS DATA:
Map and reverse-geocoding data are provided by OpenStreetMap contributors
under the Open Data Commons Open Database License (ODbL).

NOTICE:
This software is provided to assist with rainwater harvesting calculations.
Users are responsible for verifying inputs, assumptions, local codes, design
criteria, rainfall data, and results before using them for planning,
engineering, permitting, construction, or operational decisions.

DISCLAIMER OF WARRANTY AND LIMITATION OF LIABILITY:
THIS SOFTWARE IS PROVIDED "AS IS" WITHOUT WARRANTY OF ANY KIND. NEITHER THE
RWH CALCULATOR CONTRIBUTORS, THEIR LICENSORS, OR ANY PERSON OR ORGANIZATION
ACTING ON BEHALF OF ANY OF THEM:

A.  MAKE ANY WARRANTY OR REPRESENTATION WHATSOEVER, EXPRESS OR IMPLIED, WITH
RESPECT TO RWH CALCULATOR OR ANY DERIVATIVE WORKS THEREOF, INCLUDING WITHOUT
LIMITATION WARRANTIES OF MERCHANTABILITY, WARRANTIES OF FITNESS FOR A
PARTICULAR PURPOSE, OR WARRANTIES OR REPRESENTATIONS REGARDING THE USE, OR
THE RESULTS OF THE USE OF RWH CALCULATOR OR DERIVATIVE WORKS THEREOF IN
TERMS OF CORRECTNESS, ACCURACY, RELIABILITY, CURRENTNESS, OR OTHERWISE. THE
ENTIRE RISK AS TO THE RESULTS AND PERFORMANCE OF THE SOFTWARE IS ASSUMED BY
THE USER.

B.  MAKE ANY REPRESENTATION OR WARRANTY THAT RWH CALCULATOR OR DERIVATIVE
WORKS THEREOF WILL NOT INFRINGE ANY COPYRIGHT OR OTHER PROPRIETARY RIGHT.

C.  ASSUME ANY LIABILITY WHATSOEVER WITH RESPECT TO ANY USE OF RWH
CALCULATOR, DERIVATIVE WORKS THEREOF, OR ANY PORTION THEREOF OR WITH RESPECT
TO ANY DAMAGES WHICH MAY RESULT FROM SUCH USE.

DISCLAIMER OF ENDORSEMENT:
Reference herein to any specific commercial products, processes, services,
data sources, trade names, trademarks, manufacturers, or otherwise, does not
necessarily constitute or imply endorsement, recommendation, or favoring by
the RWH Calculator contributors or any government entity.
"""
MONTH_LABELS = {
    "jan": "Jan",
    "feb": "Feb",
    "mar": "Mar",
    "apr": "Apr",
    "may": "May",
    "jun": "Jun",
    "jul": "Jul",
    "aug": "Aug",
    "sep": "Sep",
    "oct": "Oct",
    "nov": "Nov",
    "dec": "Dec",
}
DEMAND_FIELDS = [
    ("male_occupancy", "Male Occ."),
    ("female_occupancy", "Female Occ."),
    ("ice_making", "Ice Making"),
    ("cooling_tower", "Cooling Tower"),
    ("ice_skating", "Ice Skating"),
    ("other_indoor", "Other Indoor"),
    ("spray_irrigation", "Spray Irrig."),
    ("drip_irrigation", "Drip Irrig."),
    ("vehicular_washing", "Vehicle Wash"),
    ("other_outdoor", "Other Outdoor"),
]
STATE_OPTIONS = [
    ("AL", "Alabama"),
    ("AK", "Alaska"),
    ("AZ", "Arizona"),
    ("AR", "Arkansas"),
    ("CA", "California"),
    ("CO", "Colorado"),
    ("CT", "Connecticut"),
    ("DE", "Delaware"),
    ("DC", "District of Columbia"),
    ("FL", "Florida"),
    ("GA", "Georgia"),
    ("HI", "Hawaii"),
    ("ID", "Idaho"),
    ("IL", "Illinois"),
    ("IN", "Indiana"),
    ("IA", "Iowa"),
    ("KS", "Kansas"),
    ("KY", "Kentucky"),
    ("LA", "Louisiana"),
    ("ME", "Maine"),
    ("MD", "Maryland"),
    ("MA", "Massachusetts"),
    ("MI", "Michigan"),
    ("MN", "Minnesota"),
    ("MS", "Mississippi"),
    ("MO", "Missouri"),
    ("MT", "Montana"),
    ("NE", "Nebraska"),
    ("NV", "Nevada"),
    ("NH", "New Hampshire"),
    ("NJ", "New Jersey"),
    ("NM", "New Mexico"),
    ("NY", "New York"),
    ("NC", "North Carolina"),
    ("ND", "North Dakota"),
    ("OH", "Ohio"),
    ("OK", "Oklahoma"),
    ("OR", "Oregon"),
    ("PA", "Pennsylvania"),
    ("RI", "Rhode Island"),
    ("SC", "South Carolina"),
    ("SD", "South Dakota"),
    ("TN", "Tennessee"),
    ("TX", "Texas"),
    ("UT", "Utah"),
    ("VT", "Vermont"),
    ("VA", "Virginia"),
    ("WA", "Washington"),
    ("WV", "West Virginia"),
    ("WI", "Wisconsin"),
    ("WY", "Wyoming"),
]
STATE_LABELS = [f"{code} - {name}" for code, name in STATE_OPTIONS]
STATE_NAME_BY_CODE = dict(STATE_OPTIONS)
STATE_PLACEHOLDER = "-- Select state --"
PROVINCE_OPTIONS = [
    ("AB", "Alberta"),
    ("BC", "British Columbia"),
    ("MB", "Manitoba"),
    ("NB", "New Brunswick"),
    ("NL", "Newfoundland and Labrador"),
    ("NS", "Nova Scotia"),
    ("NT", "Northwest Territories"),
    ("NU", "Nunavut"),
    ("ON", "Ontario"),
    ("PE", "Prince Edward Island"),
    ("QC", "Quebec"),
    ("SK", "Saskatchewan"),
    ("YT", "Yukon"),
]
PROVINCE_LABELS = [f"{code} - {name}" for code, name in PROVINCE_OPTIONS]
PROVINCE_NAME_BY_CODE = dict(PROVINCE_OPTIONS)
PROVINCE_PLACEHOLDER = "-- Select province / territory --"
CANADIAN_PRECIPITATION_OPTIONS = {
    "Total precipitation": "TOTAL_PRECIPITATION",
    "Rain only": "TOTAL_RAIN",
}
CANADIAN_PRECIPITATION_LABELS = {value: label for label, value in CANADIAN_PRECIPITATION_OPTIONS.items()}
COUNTRY_OPTIONS = sorted(
    ((country.alpha_3, country.name) for country in pycountry.countries),
    key=lambda item: item[1],
)
COUNTRY_LABELS = [f"{code} - {name}" for code, name in COUNTRY_OPTIONS]
COUNTRY_LABEL_BY_CODE = {code: f"{code} - {name}" for code, name in COUNTRY_OPTIONS}


def _app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _resource_path(relative_path: str) -> Path:
    bundled_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return bundled_root / relative_path


def _help_index_path() -> Path | None:
    bundled_root = Path(getattr(sys, "_MEIPASS", _app_dir()))
    candidates = [bundled_root / "help" / "index.html", _app_dir() / "site" / "index.html"]
    return next((path for path in candidates if path.is_file()), None)


def _float(value: object, default: float = 0.0) -> float:
    return parse_number(value, default)


class _ScaledCanvasProxy:
    """Create Canvas items directly in screen coordinates for a model-space scene."""

    def __init__(
        self,
        canvas: tk.Canvas,
        zoom: float,
        pan_x: float,
        pan_y: float,
    ) -> None:
        self.canvas = canvas
        self.zoom = max(float(zoom), 0.01)
        self.pan_x = float(pan_x)
        self.pan_y = float(pan_y)

    def _coordinates(self, coordinates: tuple[object, ...]) -> tuple[object, ...]:
        transformed: list[object] = []
        for index, value in enumerate(coordinates):
            if isinstance(value, (int, float)):
                offset = self.pan_x if index % 2 == 0 else self.pan_y
                screen_coordinate = (float(value) + offset) * self.zoom
                transformed.append(round(screen_coordinate * 2.0) / 2.0)
            else:
                transformed.append(value)
        return tuple(transformed)

    def _options(self, options: dict[str, object], *, scale_font: bool = False) -> dict[str, object]:
        scaled = dict(options)
        if isinstance(scaled.get("width"), (int, float)):
            scaled["width"] = max(float(scaled["width"]) * self.zoom, 1.0)
        if isinstance(scaled.get("arrowshape"), (tuple, list)):
            scaled["arrowshape"] = tuple(
                max(float(value) * self.zoom, 1.0) for value in scaled["arrowshape"]
            )
        if isinstance(scaled.get("dash"), (tuple, list)):
            scaled["dash"] = tuple(
                max(round(float(value) * self.zoom), 1) for value in scaled["dash"]
            )
        if scale_font and isinstance(scaled.get("font"), (tuple, list)):
            font = list(scaled["font"])
            if len(font) >= 2 and isinstance(font[1], (int, float)):
                font[1] = max(round(float(font[1]) * self.zoom), 6)
                scaled["font"] = tuple(font)
        return scaled

    def create_line(self, *coordinates: object, **options: object) -> int:
        return self.canvas.create_line(
            *self._coordinates(coordinates), **self._options(options)
        )

    def create_oval(self, *coordinates: object, **options: object) -> int:
        return self.canvas.create_oval(
            *self._coordinates(coordinates), **self._options(options)
        )

    def create_rectangle(self, *coordinates: object, **options: object) -> int:
        return self.canvas.create_rectangle(
            *self._coordinates(coordinates), **self._options(options)
        )

    def create_arc(self, *coordinates: object, **options: object) -> int:
        return self.canvas.create_arc(
            *self._coordinates(coordinates), **self._options(options)
        )

    def create_polygon(self, *coordinates: object, **options: object) -> int:
        return self.canvas.create_polygon(
            *self._coordinates(coordinates), **self._options(options)
        )

    def create_text(self, *coordinates: object, **options: object) -> int:
        scaled = self._options(options, scale_font=True)
        if isinstance(options.get("width"), (int, float)):
            scaled["width"] = max(float(options["width"]) * self.zoom, 1.0)
        return self.canvas.create_text(*self._coordinates(coordinates), **scaled)

    def create_image(self, *coordinates: object, **options: object) -> int:
        return self.canvas.create_image(*self._coordinates(coordinates), **options)


class _QuietReportHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, _format: str, *args: object) -> None:
        pass


class _MapSelectionHandler(http.server.BaseHTTPRequestHandler):
    def __init__(
        self,
        *args: object,
        page_html: str,
        selection_queue: queue.Queue,
        **kwargs: object,
    ) -> None:
        self.page_html = page_html
        self.selection_queue = selection_queue
        super().__init__(*args, **kwargs)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._send(200, "text/html; charset=utf-8", self.page_html.encode("utf-8"))
            return
        if parsed.path == "/select":
            try:
                values = parse_qs(parsed.query)
                latitude = float(values["lat"][0])
                longitude = float(values["lon"][0])
                if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
                    raise ValueError
            except (KeyError, IndexError, TypeError, ValueError):
                self._send(400, "text/plain; charset=utf-8", b"Invalid coordinates")
                return
            self.selection_queue.put(("selected", latitude, longitude))
            self._send(200, "application/json", b'{"accepted":true}')
            return
        self._send(404, "text/plain; charset=utf-8", b"Not found")

    def _send(self, status: int, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *args: object) -> None:
        pass


def _build_osm_picker_html(latitude: float, longitude: float, zoom: int, show_marker: bool) -> str:
    template = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Select project location</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<style>
html,body,#map { height:100%; margin:0; } body { font-family:Arial,sans-serif; }
#map { cursor:crosshair; }
.action { position:fixed; z-index:1000; left:50%; bottom:24px; transform:translateX(-50%); display:flex; gap:10px; align-items:center; padding:10px; background:#fff; border:1px solid #c9d4d8; box-shadow:0 4px 18px rgba(0,0,0,.18); }
button { border:0; padding:10px 16px; background:#176b9c; color:#fff; font-weight:700; cursor:pointer; }
button:disabled { background:#87959b; cursor:default; }
#coordinates { min-width:210px; color:#26383f; font-variant-numeric:tabular-nums; }
</style></head><body><div id="map"></div><div class="action"><span id="coordinates">No location selected</span><button id="use" disabled>Use selected location</button></div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script><script>
const map=L.map('map').setView([__LAT__,__LON__],__ZOOM__);
L.tileLayer(__TILE_URL__,{maxZoom:19,attribution:'&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a>'}).addTo(map);
let marker=null; let selected=null;
if (__SHOW_MARKER__) { selected={lat:__LAT__,lng:__LON__}; marker=L.marker(selected).addTo(map); document.getElementById('coordinates').textContent=`${selected.lat.toFixed(6)}, ${selected.lng.toFixed(6)}`; document.getElementById('use').disabled=false; }
map.on('click',event=>{selected=event.latlng;if(marker){marker.setLatLng(selected);}else{marker=L.marker(selected).addTo(map);}document.getElementById('coordinates').textContent=`${selected.lat.toFixed(6)}, ${selected.lng.toFixed(6)}`;document.getElementById('use').disabled=false;});
document.getElementById('use').addEventListener('click',async()=>{if(!selected)return;const button=document.getElementById('use');button.disabled=true;const response=await fetch(`/select?lat=${encodeURIComponent(selected.lat)}&lon=${encodeURIComponent(selected.lng)}`);if(!response.ok){button.disabled=false;return;}button.textContent='Location selected';window.opener=null;window.open('','_self');window.close();});
</script></body></html>"""
    return (
        template.replace("__LAT__", f"{latitude:.8f}")
        .replace("__LON__", f"{longitude:.8f}")
        .replace("__ZOOM__", str(zoom))
        .replace("__SHOW_MARKER__", "true" if show_marker else "false")
        .replace("__TILE_URL__", json.dumps(OSM_TILE_URL))
    )


class _StationMapView(TkinterMapView):
    """TkinterMapView with retained zoom tiles and a shared, cached loader."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        self._map_after_ids: set[str] = set()
        self._tile_generation = 0
        self._tile_result_queue: queue.Queue[
            tuple[int, int, int, int, object, bytes | None]
        ] = queue.Queue()
        self._pending_tile_requests: set[tuple[int, int, int, int, int]] = set()
        self._pil_tile_cache: dict[tuple[int, int, int], Image.Image] = {}
        self._tile_loader = shared_tile_loader()
        super().__init__(*args, **kwargs)

    @staticmethod
    def _tile_cache_key(zoom: int, x: int, y: int) -> str:
        return f"{zoom}:{x}:{y}"

    def get_tile_image_from_cache(self, zoom: int, x: int, y: int) -> object:  # type: ignore[override]
        return self.tile_image_cache.get(self._tile_cache_key(zoom, x, y), False)

    def pre_cache(self) -> None:
        """Disable tkintermapview's radius-8 speculative download loop."""

    def load_images_background(self) -> None:
        """Disable tkintermapview's per-widget pool; the shared pool is used instead."""

    def set_tile_server(
        self, tile_server: str, tile_size: int = 256, max_zoom: int = 19
    ) -> None:
        self._tile_generation += 1
        self._pending_tile_requests.clear()
        self._pil_tile_cache.clear()
        super().set_tile_server(tile_server, tile_size=tile_size, max_zoom=max_zoom)

    def _fallback_tile_image(self, zoom: int, x: int, y: int) -> Image.Image | None:
        tile_size = self.tile_size
        for difference in range(1, 4):
            ancestor_zoom = zoom - difference
            if ancestor_zoom < 0:
                break
            divisor = 2**difference
            ancestor = self._pil_tile_cache.get(
                (ancestor_zoom, x // divisor, y // divisor)
            )
            if ancestor is None:
                continue
            source_width, source_height = ancestor.size
            left = (x % divisor) * source_width // divisor
            top = (y % divisor) * source_height // divisor
            right = ((x % divisor) + 1) * source_width // divisor
            bottom = ((y % divisor) + 1) * source_height // divisor
            return ancestor.crop((left, top, right, bottom)).resize(
                (tile_size, tile_size), Image.Resampling.BILINEAR
            )

        children = [
            self._pil_tile_cache.get((zoom + 1, x * 2 + child_x, y * 2 + child_y))
            for child_y in range(2)
            for child_x in range(2)
        ]
        if any(child is None for child in children):
            return None
        composite = Image.new("RGB", (tile_size * 2, tile_size * 2))
        for index, child in enumerate(children):
            assert child is not None
            child_image = child.convert("RGB").resize(
                (tile_size, tile_size), Image.Resampling.BILINEAR
            )
            composite.paste(child_image, ((index % 2) * tile_size, (index // 2) * tile_size))
        return composite.resize((tile_size, tile_size), Image.Resampling.BILINEAR)

    def _display_fallback(self, canvas_tile: object, zoom: int, x: int, y: int) -> None:
        fallback = self._fallback_tile_image(zoom, x, y)
        if fallback is not None:
            canvas_tile.set_image(ImageTk.PhotoImage(fallback))  # type: ignore[attr-defined]

    def draw_zoom(self) -> None:
        if not self.canvas_tile_array:
            return
        self._tile_generation += 1
        self._pending_tile_requests.clear()
        self.image_load_queue_tasks = []
        upper_left_x = math.floor(self.upper_left_tile_pos[0])
        upper_left_y = math.floor(self.upper_left_tile_pos[1])
        zoom = round(self.zoom)

        for x_position, column in enumerate(self.canvas_tile_array):
            for y_position, canvas_tile in enumerate(column):
                tile_position = (upper_left_x + x_position, upper_left_y + y_position)
                image = self.get_tile_image_from_cache(zoom, *tile_position)
                if image is False:
                    fallback = self._fallback_tile_image(zoom, *tile_position)
                    image = ImageTk.PhotoImage(fallback) if fallback is not None else self.not_loaded_tile_image
                    self.image_load_queue_tasks.append(
                        ((zoom, *tile_position), canvas_tile)
                    )
                canvas_tile.set_image_and_position(image, tile_position)

        self.pre_cache_position = (
            round((self.upper_left_tile_pos[0] + self.lower_right_tile_pos[0]) / 2),
            round((self.upper_left_tile_pos[1] + self.lower_right_tile_pos[1]) / 2),
        )
        self.draw_move(called_after_zoom=True)

    def _dispatch_tile_requests(self) -> None:
        generation = self._tile_generation
        zoom_now = round(self.zoom)
        center_x = (self.upper_left_tile_pos[0] + self.lower_right_tile_pos[0]) / 2
        center_y = (self.upper_left_tile_pos[1] + self.lower_right_tile_pos[1]) / 2
        widget_reference = weakref.ref(self)

        while self.image_load_queue_tasks:
            (zoom, x, y), canvas_tile = self.image_load_queue_tasks.pop()
            if zoom != zoom_now:
                continue
            request_key = (generation, zoom, x, y, id(canvas_tile))
            if request_key in self._pending_tile_requests:
                continue
            self._display_fallback(canvas_tile, zoom, x, y)
            self._pending_tile_requests.add(request_key)
            url = (
                self.tile_server.replace("{x}", str(x))
                .replace("{y}", str(y))
                .replace("{z}", str(zoom))
            )

            def cancelled(
                reference: weakref.ReferenceType[_StationMapView] = widget_reference,
                expected_generation: int = generation,
            ) -> bool:
                widget = reference()
                return (
                    widget is None
                    or not widget.running
                    or widget._tile_generation != expected_generation
                )

            def deliver(
                payload: bytes | None,
                reference: weakref.ReferenceType[_StationMapView] = widget_reference,
                result: tuple[int, int, int, int, object] = (
                    generation,
                    zoom,
                    x,
                    y,
                    canvas_tile,
                ),
            ) -> None:
                widget = reference()
                if widget is not None:
                    widget._tile_result_queue.put((*result, payload))

            priority = (x + 0.5 - center_x) ** 2 + (y + 0.5 - center_y) ** 2
            self._tile_loader.submit(
                TileLoadTask(url=url, cancelled=cancelled, deliver=deliver),
                priority=priority,
            )

    def update_canvas_tile_images(self) -> None:
        self._dispatch_tile_requests()
        while self.running:
            try:
                generation, zoom, x, y, canvas_tile, payload = (
                    self._tile_result_queue.get_nowait()
                )
            except queue.Empty:
                break
            self._pending_tile_requests.discard((generation, zoom, x, y, id(canvas_tile)))
            if (
                payload is None
                or generation != self._tile_generation
                or zoom != round(self.zoom)
                or getattr(canvas_tile, "tile_name_position", None) != (x, y)
                or not any(
                    canvas_tile is current_tile
                    for column in self.canvas_tile_array
                    for current_tile in column
                )
            ):
                continue
            try:
                pil_image = Image.open(io.BytesIO(payload)).convert("RGB")
                pil_image.load()
            except (OSError, ValueError):
                continue
            photo_image = ImageTk.PhotoImage(pil_image)
            self._pil_tile_cache[(zoom, x, y)] = pil_image
            self.tile_image_cache[self._tile_cache_key(zoom, x, y)] = photo_image
            canvas_tile.set_image(photo_image)
        if self.running:
            self.after(10, self.update_canvas_tile_images)

    def after(self, ms: int, func: object = None, *args: object) -> str:  # type: ignore[override]
        if func is None:
            return super().after(ms)
        callback_id: list[str] = []

        def run_tracked_callback() -> None:
            if callback_id:
                self._map_after_ids.discard(callback_id[0])
            func(*args)  # type: ignore[operator]

        after_id = super().after(ms, run_tracked_callback)
        callback_id.append(after_id)
        self._map_after_ids.add(after_id)
        return after_id

    def after_cancel(self, after_id: str) -> None:
        self._map_after_ids.discard(after_id)
        super().after_cancel(after_id)

    def destroy(self) -> None:
        self.analysis_cancel_requested = True
        self.running = False
        self._tile_generation += 1
        for after_id in tuple(self._map_after_ids):
            try:
                super().after_cancel(after_id)
            except tk.TclError:
                pass
        self._map_after_ids.clear()
        super().destroy()


class ProjectLocationPickerDialog(tk.Toplevel):
    def __init__(
        self,
        parent: "RainwaterTkApp",
        latitude: float,
        longitude: float,
        zoom: int,
        show_marker: bool,
    ) -> None:
        super().__init__(parent)
        self.title("Find project location on OpenStreetMap")
        self.transient(parent)
        self.result: tuple[float, float] | None = None
        self.selected_coordinates: tuple[float, float] | None = None
        self.marker: object | None = None
        self.geometry("900x620")
        self.minsize(680, 460)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        self.map = _StationMapView(self, width=880, height=540, corner_radius=0)
        self.map.set_tile_server(OSM_TILE_URL, max_zoom=19)
        self.map.set_position(latitude, longitude)
        self.map.set_zoom(zoom)
        self.map.add_left_click_map_command(self._map_clicked)
        self.map.grid(row=0, column=0, sticky="nsew", padx=10, pady=(10, 0))

        action_row = ttk.Frame(self, padding=10)
        action_row.grid(row=1, column=0, sticky="ew")
        action_row.columnconfigure(0, weight=1)
        self.coordinates_var = tk.StringVar(value="Select a point on the map")
        ttk.Label(action_row, textvariable=self.coordinates_var).grid(row=0, column=0, sticky="w")
        ttk.Label(
            action_row,
            text="Map data © OpenStreetMap contributors",
            foreground="#5f6b70",
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))
        ttk.Button(action_row, text="Cancel", command=self._cancel).grid(row=0, column=1, rowspan=2, padx=(8, 4))
        self.select_button = ttk.Button(
            action_row,
            text="Use selected location",
            command=self._accept,
            state="disabled",
        )
        self.select_button.grid(row=0, column=2, rowspan=2)

        if show_marker:
            self._set_selection(latitude, longitude)
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.bind("<Escape>", lambda _event: self._cancel())
        self.bind("<Return>", self._accept_from_event)
        self.update_idletasks()
        x = parent.winfo_rootx() + max((parent.winfo_width() - self.winfo_width()) // 2, 0)
        y = parent.winfo_rooty() + max((parent.winfo_height() - self.winfo_height()) // 2, 0)
        self.geometry(f"+{x}+{y}")
        self.grab_set()
        self.focus_force()

    def _map_clicked(self, coordinates: tuple[float, float]) -> None:
        self._set_selection(float(coordinates[0]), float(coordinates[1]))

    def _set_selection(self, latitude: float, longitude: float) -> None:
        self.selected_coordinates = (latitude, longitude)
        self.coordinates_var.set(f"Selected coordinates: {latitude:.6f}, {longitude:.6f}")
        if self.marker is None:
            self.marker = self.map.set_marker(latitude, longitude, text="Project location")
        else:
            self.marker.set_position(latitude, longitude)  # type: ignore[attr-defined]
        self.select_button.state(["!disabled"])

    def _accept(self) -> None:
        if self.selected_coordinates is None:
            return
        self.result = self.selected_coordinates
        self.destroy()

    def _accept_from_event(self, _event: tk.Event) -> str:
        self._accept()
        return "break"

    def _cancel(self) -> None:
        self.destroy()


class UnsavedChangesDialog(tk.Toplevel):
    def __init__(self, parent: "RainwaterTkApp", project_name: str, action: str) -> None:
        super().__init__(parent)
        self.title("Unsaved changes")
        self.transient(parent)
        self.resizable(False, False)
        self.result: str | None = None

        body = ttk.Frame(self, padding=18)
        body.grid(row=0, column=0, sticky="nsew")
        ttk.Label(
            body,
            text=f"Save changes to {project_name} before {action}?",
            font=("TkDefaultFont", 11, "bold"),
            wraplength=430,
        ).grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(
            body,
            text="Your changes will be lost if you don't save them.",
            wraplength=430,
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(8, 18))

        save_button = ttk.Button(body, text="Save", command=lambda: self._choose("save"))
        save_button.grid(row=2, column=0, padx=(0, 8))
        ttk.Button(
            body, text="Don't Save", command=lambda: self._choose("discard")
        ).grid(row=2, column=1, padx=8)
        ttk.Button(body, text="Cancel", command=self._cancel).grid(
            row=2, column=2, padx=(8, 0)
        )

        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.bind("<Escape>", lambda _event: self._cancel())
        self.bind("<Return>", lambda _event: self._choose("save"))
        self.update_idletasks()
        x = parent.winfo_rootx() + max((parent.winfo_width() - self.winfo_width()) // 2, 0)
        y = parent.winfo_rooty() + max((parent.winfo_height() - self.winfo_height()) // 2, 0)
        self.geometry(f"+{x}+{y}")
        self.grab_set()
        save_button.focus_set()

    def _choose(self, result: str) -> None:
        self.result = result
        self.destroy()

    def _cancel(self) -> None:
        self.result = "cancel"
        self.destroy()


class RainwaterTkApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.withdraw()
        self.title(APP_TITLE)
        icon_path = _resource_path("assets/app_icon.png")
        self.app_icon = tk.PhotoImage(file=icon_path) if icon_path.is_file() else None
        if self.app_icon is not None:
            self.iconphoto(True, self.app_icon)
        self.system_weather_images: dict[str, tk.PhotoImage] = {}
        self.system_weather_assets_loaded = False
        self.system_builder_node_images: dict[tuple[object, ...], ImageTk.PhotoImage] = {}
        self.active_project_name: str | None = None
        self.geometry(f"{DEFAULT_WINDOW_WIDTH}x{DEFAULT_WINDOW_HEIGHT}")
        self.minsize(MINIMUM_WINDOW_WIDTH, DEFAULT_WINDOW_HEIGHT)
        self._default_tk_scaling = float(self.tk.call("tk", "scaling"))

        self.application_data_dir = user_data_dir()
        try:
            self.migrated_legacy_files = migrate_legacy_application_data(
                _app_dir(), self.application_data_dir
            )
        except OSError:
            self.application_data_dir = Path(tempfile.gettempdir()) / "RWH Calculator"
            self.application_data_dir.mkdir(parents=True, exist_ok=True)
            self.migrated_legacy_files = ()
        self.project_file_path = self.application_data_dir / "rainwater_projects.db"
        self.store = SQLiteStore(
            str(self.project_file_path),
            backup_dir=project_backup_dir(
                self.project_file_path, data_dir=self.application_data_dir
            ),
        )
        self.recent_projects_path = self.application_data_dir / "recent_projects.json"
        self.recent_project_paths = self._load_recent_project_paths()
        self.working_draft_store = WorkingDraftStore(
            self.application_data_dir / "recovery"
        )
        application_state_dir = self.application_data_dir
        self.app_preferences_path = application_state_dir / "app_preferences.json"
        self.app_preferences = self._load_app_preferences()
        self.number_format_var = tk.StringVar(
            value=set_active_number_format(
                self.app_preferences.get("number_format", US_NUMBER_FORMAT)
            )
        )
        self.recent_rainfall_csv_paths = self._preference_path_list(
            "recent_rainfall_csv_paths", MAX_RECENT_RAINFALL_CSVS
        )
        self.pinned_rainfall_csv_paths = self._preference_path_list(
            "pinned_rainfall_csv_paths", MAX_PINNED_RAINFALL_CSVS
        )
        self.current_rainfall_csv_path: str | None = None
        self.text_scale_var = tk.IntVar(
            value=_normalize_text_scale_percent(
                self.app_preferences.get("text_scale_percent", DEFAULT_TEXT_SCALE_PERCENT)
            )
        )
        self._apply_tk_text_scale(self.text_scale_var.get())
        self.progress_style = ttk.Style(self)
        self.progress_style.configure("Analysis.Horizontal.TProgressbar")
        self.progress_style.configure("OpenProject.Horizontal.TProgressbar", background="#2e8b57")
        self.progress_style.configure("SaveProject.Horizontal.TProgressbar", background="#2e8b57")
        self.progress_style.configure("Invalid.TLabel", foreground="#c62828", font=("TkDefaultFont", 11, "bold"))
        self.progress_style.configure("Treeview.Heading", padding=(4, 8))
        self.progress_style.configure("MonthlyDemand.Treeview.Heading", padding=(4, 8))
        self.bind_class("Treeview", "<Map>", self._wrap_mapped_treeview_headings, add="+")
        try:
            self.execution_log = ExecutionLogger(application_state_dir / "logs")
        except OSError:
            self.execution_log = ExecutionLogger(Path(tempfile.gettempdir()) / "RWH Calculator" / "logs")
        self.execution_log_window: tk.Toplevel | None = None
        self.execution_log_text: tk.Text | None = None
        self.execution_log_poll_after_id: str | None = None
        self.execution_log_auto_scroll_var = tk.BooleanVar(value=True)
        self.execution_log_pause_var = tk.BooleanVar(value=False)
        self.execution_log_visible_var = tk.BooleanVar(
            value=bool(self.app_preferences.get("show_execution_log", False))
        )
        self.execution_log_detail_var = tk.StringVar(
            value=normalize_log_detail(self.app_preferences.get("execution_log_detail", "Normal"))
        )
        self.custom_schedule_library_path = application_state_dir / "schedule_library.json"
        self.custom_schedule_template_types: dict[str, str] = {}
        self.custom_schedule_template_months: dict[str, list[int]] = {}
        self.custom_schedule_templates = self._load_custom_schedule_templates()
        self.custom_demand_object_library_path = application_state_dir / "demand_object_library.json"
        self.custom_demand_object_templates = self._load_custom_demand_object_templates()
        self.equipment_library_path = application_state_dir / "equipment_library.json"
        self.equipment_library = load_equipment_library(self.equipment_library_path)
        self.config_model = default_project_config()
        self.config_model.optimization_parameters.equipment_candidates = default_project_candidates(
            self.equipment_library
        )
        self.rainfall_df = pd.DataFrame(columns=["Date", "Precipitation"])
        self.curve_df = pd.DataFrame()
        self.results_df = pd.DataFrame()
        self.hourly_results_df = pd.DataFrame()
        self.comparison_results: dict[float, pd.DataFrame] = {}
        self.candidate_sort_column = "TankSizeGallons"
        self.candidate_sort_reverse = False
        self.candidate_tree_sizes: dict[str, float] = {}
        self.station_options: list[dict] = []
        self.climate_normal_search_results: list[dict[str, object]] = []
        self.climate_normal_catalog: list[dict[str, object]] = []
        self.climate_normal_comparison_rows: dict[str, dict[str, object]] = {}
        self.climate_normal_sort_column = "annual"
        self.climate_normal_sort_descending = True
        self.climate_normal_map_markers: list[object] = []
        self.climate_normal_map_marker_by_station_id: dict[str, object] = {}
        self.climate_normal_map_rendered_zoom: int | None = None
        self.climate_normal_map_redraw_after_id: str | None = None
        self.climate_normal_map_fit_on_redraw = False
        self.climate_normal_map_records: list[dict[str, object]] = []
        self.climate_normal_map_selected_station_id = ""
        self.station_map_markers: list[object] = []
        self.station_map_marker_by_label: dict[str, object] = {}
        self.station_map_rendered_zoom: int | None = None
        self.station_map_redraw_after_id: str | None = None
        self.station_map_selected_label = ""
        self.station_map_embedded: _StationMapView | None = None
        self.station_map_fullscreen_window: tk.Toplevel | None = None
        self.system_multi_select_var = tk.BooleanVar(value=False)
        self.system_geometry_status_var = tk.StringVar(value="Turn on multi-select, then choose two or more objects.")
        self.system_builder_selected_ids: set[str] = set()
        self.system_builder_resize_state: tuple[object, ...] | None = None

        self.project_name_var = tk.StringVar(value=self.config_model.name)
        self.author_name_var = tk.StringVar(value=self.config_model.author_name)
        self.street_address_var = tk.StringVar(value=self.config_model.street_address)
        self.city_var = tk.StringVar(value=self.config_model.city)
        self.state_or_province_var = tk.StringVar(value=self.config_model.state_or_province)
        self.postal_code_var = tk.StringVar(value=self.config_model.postal_code)
        self.latitude_var = tk.StringVar()
        self.longitude_var = tk.StringVar()
        self.coordinates_var = tk.StringVar(value="Coordinates: not selected")
        self.unit_var = tk.StringVar(value=self.config_model.unit_system)
        self.system_type_var = tk.StringVar(value=self.config_model.system_type)
        self.current_system_type_var = tk.StringVar(value=f"Current system type: {self.config_model.system_type}")
        self.pump_capacity_var = tk.StringVar(value="0")
        self.filtration_pump_capacity_var = tk.StringVar(value="20")
        self.filtration_system_flow_gpm_var = tk.StringVar(value="20")
        self.filtration_system_count_var = tk.StringVar(value="1")
        self.transfer_pump_type_var = tk.StringVar(value="External")
        self.filter_recovery_var = tk.StringVar(value="100")
        self.booster_tank_size_var = tk.StringVar(value="0")
        self.booster_initial_fill_var = tk.StringVar(value="0")
        self.booster_refill_level_var = tk.StringVar(value="50")
        self.municipal_backup_enabled_var = tk.BooleanVar(value=True)
        self.pump_capacity_unit_var = tk.StringVar(value="gal/min")
        self.country_var = tk.StringVar(value=COUNTRY_LABEL_BY_CODE["USA"])
        self.saved_project_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Ready")
        self.project_state_var = tk.StringVar(value="All changes saved")
        self.simple_daily_var = tk.StringVar(value="0")
        self.daily_demand_days_var = tk.StringVar(value="7")
        self.flushes_var = tk.StringVar(value="0")
        self.toilet_flush_var = tk.StringVar(value="0")
        self.urinal_flush_var = tk.StringVar(value="0")
        self.graph_start_var = tk.StringVar(value=str(self.config_model.graph_start_gal))
        self.graph_end_var = tk.StringVar(value=str(self.config_model.graph_end_gal))
        self.graph_step_var = tk.StringVar(value=str(self.config_model.graph_step_gal))
        self.graph_auto_step_count_var = tk.StringVar(value=str(self.config_model.graph_auto_step_count))
        self.selected_tank_var = tk.StringVar(value=str(self.config_model.selected_tank_size_gal))
        self.recommendation_reliability_target_var = tk.StringVar(
            value=str(self.config_model.recommendation_reliability_target_percent)
        )
        self.recommendation_marginal_gain_var = tk.StringVar(
            value=str(self.config_model.recommendation_marginal_gain_threshold)
        )
        self.design_recommendations_var = tk.StringVar(
            value="Run an analysis to generate design recommendations."
        )
        self.design_warnings_var = tk.StringVar(value="")
        self.comparison_tank_var = tk.StringVar()
        self.multitank_comparison_var = tk.BooleanVar(value=self.config_model.multitank_comparison_enabled)
        self.selected_tank_warning_var = tk.StringVar()
        self.initial_fill_var = tk.StringVar(value=str(self.config_model.tank_parameters.initial_fill_percent))
        self.reserve_var = tk.StringVar(
            value=str(self.config_model.tank_parameters.minimum_operating_volume_percent)
        )
        sizing_method = normalize_first_flush_sizing_method(
            self.config_model.first_flush_sizing_method
        )
        design_preset = normalize_first_flush_design_preset(
            self.config_model.first_flush_design_preset
        )
        self.first_flush_sizing_method_var = tk.StringVar(
            value=SIZING_METHOD_LABELS[sizing_method]
        )
        self.first_flush_design_preset_var = tk.StringVar(
            value=DESIGN_PRESET_LABELS[design_preset]
        )
        self.first_flush_guidance_summary_var = tk.StringVar()
        self.country_var.trace_add("write", lambda *_args: self._refresh_first_flush_guidance())
        self.state_or_province_var.trace_add(
            "write", lambda *_args: self._refresh_first_flush_guidance()
        )
        self.first_flush_antecedent_unit_var = tk.StringVar(
            value=self.config_model.first_flush_antecedent_dry_unit
        )
        self.first_flush_antecedent_display_unit = self.first_flush_antecedent_unit_var.get()
        first_flush_antecedent_display_value = _antecedent_dry_period_from_days(
            self.config_model.first_flush_antecedent_dry_days,
            self.first_flush_antecedent_display_unit,
        )
        self.first_flush_antecedent_var = tk.StringVar(
            value=f"{first_flush_antecedent_display_value:g}"
        )
        self.hourly_schedule_enabled_var = tk.BooleanVar(value=self.config_model.demand.hourly_schedule_enabled)
        self.hourly_schedule_summary_var = tk.StringVar(value="Even 24-hour demand profile")
        self.use_synthetic_hourly_rainfall_var = tk.BooleanVar(
            value=self.config_model.use_synthetic_hourly_rainfall
        )
        self.synthetic_hourly_rainfall_status_var = tk.StringVar()
        self.applied_analysis_resolution_var = tk.StringVar()
        self.applied_rainfall_source_var = tk.StringVar()
        self.applied_demand_timing_var = tk.StringVar()
        self.applied_rainfall_timing_var = tk.StringVar()
        self.hourly_demand_schedule_selection_var = tk.StringVar()
        self.hourly_profile_reference_var = tk.StringVar(
            value="Hourly profile: Not generated - manage in Hourly rainfall."
        )
        self.hourly_profile_preview_var = tk.StringVar(
            value="Generate a profile to preview its distribution by hour."
        )
        self.hourly_results_year_var = tk.StringVar(value="--")
        self.simple_daily_unit_var = tk.StringVar()
        self.flush_count_unit_var = tk.StringVar(value="flushes/person")
        self.flush_volume_unit_var = tk.StringVar()
        self.tank_size_unit_var = tk.StringVar()
        self.percent_unit_var = tk.StringVar(value="%")
        self.reserve_unit_var = tk.StringVar(value="% of tank capacity")
        financial = self.config_model.financial_parameters
        self.financial_currency_var = tk.StringVar(value=financial.currency)
        self.financial_water_rate_var = tk.StringVar(value=str(financial.water_rate))
        self.financial_sewer_rate_var = tk.StringVar(value=str(financial.sewer_rate))
        self.financial_tariff_unit_var = tk.StringVar(value=financial.tariff_billing_unit)
        self.financial_sewer_eligible_var = tk.StringVar(value=str(financial.sewer_eligible_percent))
        self.financial_installed_cost_var = tk.StringVar(value=str(financial.installed_cost))
        self.financial_incentives_var = tk.StringVar(value=str(financial.incentives))
        self.financial_fixed_maintenance_var = tk.StringVar(value=str(financial.fixed_annual_maintenance))
        self.financial_maintenance_percent_var = tk.StringVar(value=str(financial.annual_maintenance_percent))
        self.financial_analysis_period_var = tk.StringVar(value=str(financial.analysis_period_years))
        self.financial_discount_rate_var = tk.StringVar(value=str(financial.discount_rate_percent))
        self.financial_utility_escalation_var = tk.StringVar(
            value=str(financial.utility_rate_escalation_percent)
        )
        self.financial_maintenance_escalation_var = tk.StringVar(
            value=str(financial.maintenance_escalation_percent)
        )
        self.financial_electricity_escalation_var = tk.StringVar(
            value=str(financial.electricity_escalation_percent)
        )
        self.financial_pump_power_var = tk.StringVar(value=str(financial.pump_power_kw))
        self.financial_pump_flow_rate_var = tk.StringVar(
            value=str(financial.pump_flow_rate_gallons_per_hour)
        )
        self.financial_replacement_cost_var = tk.StringVar(
            value=str(financial.equipment_replacement_cost)
        )
        self.financial_replacement_interval_var = tk.StringVar(
            value=str(financial.equipment_replacement_interval_years)
        )
        self.financial_replacement_escalation_var = tk.StringVar(
            value=str(financial.equipment_replacement_escalation_percent)
        )
        self.financial_power_unit_var = tk.StringVar(value="kW")
        self.financial_pump_flow_unit_var = tk.StringVar(
            value=f"{volume_unit(self.config_model)}/hour"
        )
        self.financial_electricity_unit_var = tk.StringVar(value="currency/kWh")
        self.financial_replacement_interval_unit_var = tk.StringVar(
            value="years; 0 disables"
        )
        self.financial_status_var = tk.StringVar(value="Run a tank analysis to calculate financial results.")
        self.financial_result_vars = {key: tk.StringVar(value="--") for key in (
            "supplied", "sewer_eligible_supply", "water_savings", "sewer_savings", "gross",
            "maintenance", "energy", "net", "net_cost", "payback", "discounted_payback",
            "period_benefit", "replacement", "npv", "irr"
        )}
        optimization = self.config_model.optimization_parameters
        self.optimization_minimum_reliability_var = tk.StringVar(
            value=str(optimization.minimum_reliability_percent)
        )
        self.optimization_electricity_rate_var = tk.StringVar(
            value=str(optimization.electricity_rate_per_kwh)
        )
        self.optimization_objective_var = tk.StringVar(value=optimization.objective)
        self.optimization_maximum_makeup_var = tk.StringVar(
            value="" if optimization.maximum_annual_municipal_makeup_gallons is None
            else str(optimization.maximum_annual_municipal_makeup_gallons)
        )
        self.optimization_maximum_cost_var = tk.StringVar(
            value="" if optimization.maximum_installed_cost is None else str(optimization.maximum_installed_cost)
        )
        self.optimization_positive_savings_var = tk.BooleanVar(value=optimization.require_positive_net_savings)
        equipment_constraints = normalized_constraints(optimization.equipment_constraints)
        self.equipment_library_search_var = tk.StringVar()
        self.equipment_library_category_var = tk.StringVar(value="All categories")
        self.equipment_require_values_var = tk.BooleanVar(
            value=bool(equipment_constraints["require_constraint_values"])
        )
        self.equipment_flow_compatibility_var = tk.BooleanVar(value=True)
        self.equipment_constraint_vars = {
            key: tk.StringVar(value=_constraint_display_value(equipment_constraints.get(key)))
            for key in (
                "approved_vendors", "required_tags", "required_standards", "required_voltage", "required_phase",
                "required_pressure_class", "required_connection_size", "maximum_length",
                "maximum_width", "maximum_height", "maximum_footprint",
                "minimum_access_clearance", "project_standards",
            )
        }
        self.optimization_status_var = tk.StringVar(
            value="Review the project equipment candidates before running optimization."
        )
        self.rainfall_summary_var = tk.StringVar(value="No rainfall file loaded")
        self.rainfall_quality_var = tk.StringVar(value="Quality assessment unavailable")
        self.rainfall_data_type_var = tk.StringVar(value="--")
        self.rainfall_resolution_var = tk.StringVar(value="--")
        self.rainfall_timezone_var = tk.StringVar(value="--")
        self.rainfall_timing_var = tk.StringVar(value="--")
        self.reliability_var = tk.StringVar(value="Reliability: --")
        self.average_annual_precipitation_var = tk.StringVar(value="Average annual precipitation: --")
        self.analysis_progress_var = tk.DoubleVar(value=0.0)
        self.analysis_running = False
        self.analysis_cancel_requested = False
        self.analysis_thread: threading.Thread | None = None
        self.analysis_result_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self.analysis_poll_after_id: str | None = None
        self.analysis_active_label = "Analysis"
        self.analysis_started_at = 0.0
        self.analysis_started_signature: str | None = None
        self.analysis_started_unit_system: str | None = None
        self.show_tank_points_var = tk.BooleanVar(value=True)
        initial_report_sections = normalize_report_sections(
            self.config_model.report_sections
        )
        self.report_section_vars = {
            key: tk.BooleanVar(value=initial_report_sections[key])
            for key, _label, _html_id, _title in REPORT_SECTION_DEFINITIONS
        }
        self.report_include_system_visualization_var = tk.BooleanVar(
            value=self.config_model.report_include_system_visualization
        )
        self.report_include_multitank_charts_var = tk.BooleanVar(
            value=self.config_model.report_include_multitank_charts
        )
        self.tank_chart_year_var = tk.StringVar(value="--")
        self.tank_chart_year: int | None = None
        self.tank_chart_range_mode_var = tk.StringVar(value="year")
        self.tank_chart_range_start_var = tk.DoubleVar(value=0)
        self.tank_chart_range_end_var = tk.DoubleVar(value=0)
        self.tank_chart_range_label_var = tk.StringVar(value="")
        self.tank_chart_range_initialized = False
        self.weather_state_var = tk.StringVar(value=STATE_PLACEHOLDER)
        self.weather_years_var = tk.StringVar(value="30")
        self.weather_filter_var = tk.StringVar(value="")
        self.station_var = tk.StringVar(value="")
        self.canadian_precip_var = tk.StringVar(value="Total precipitation")
        self.weather_source_note_var = tk.StringVar()
        self.weather_source_link_var = tk.StringVar()
        self.weather_source_url = ACIS_SOURCE_URL
        self.climate_normal_query_var = tk.StringVar(value="Find station by name")
        self.climate_normal_station_var = tk.StringVar()
        self.climate_normal_status_var = tk.StringVar(
            value="Open this tab to load NOAA 1991-2020 Climate Normals stations."
        )
        self.climate_normal_archive_status_var = tk.StringVar()
        self.climate_normal_archive_progress_var = tk.DoubleVar(value=0.0)
        self.climate_normal_archive_in_progress = False
        self.climate_normal_search_placeholder_active = True
        self.rainfall_source_label: str | None = None
        self.active_example_id: str | None = None
        self.station_typeahead = ""
        self.station_typeahead_after_id: str | None = None
        self.station_popdown_key_command: str | None = None
        self.state_typeahead = ""
        self.state_typeahead_after_id: str | None = None
        self.state_popdown_key_command: str | None = None
        self.country_typeahead = ""
        self.country_typeahead_after_id: str | None = None
        self.country_popdown_key_command: str | None = None
        self.results_chart_redraw_after_id: str | None = None
        self.last_analysis_warning_key: str | None = None
        self.last_unit_conversion_notice: str | None = None
        self.unit_conversion_form_snapshot: tuple[str, ...] | None = None
        self.report_preview_directories: list[tempfile.TemporaryDirectory] = []
        self.report_preview_servers: list[http.server.ThreadingHTTPServer] = []
        self.location_result_queue: queue.Queue = queue.Queue()
        self.location_poll_after_id: str | None = None
        self.station_lookup_queue: queue.Queue = queue.Queue()
        self.station_lookup_poll_after_id: str | None = None
        self.station_lookup_in_progress = False
        self.station_lookup_airport_only = False
        self.climate_normal_queue: queue.Queue = queue.Queue()
        self.climate_normal_poll_after_id: str | None = None
        self.climate_normal_lookup_in_progress = False
        self.climate_normal_detail_queue: queue.Queue = queue.Queue()
        self.climate_normal_detail_poll_after_id: str | None = None
        self.climate_normal_detail_request_station_id = ""
        self.climate_normal_detail_request_id: int | None = None
        self.climate_normal_detail_request_serial = 0
        self.climate_normal_detail_cancel_event: threading.Event | None = None
        self.climate_normal_detail_in_flight = 0
        self.climate_normal_detail_in_flight_ids: set[str] = set()
        self.climate_normal_detail_requests: dict[
            int, tuple[str, threading.Event]
        ] = {}
        self.climate_normal_detail_request_by_station: dict[str, int] = {}
        self.climate_normal_detail_executor = ThreadPoolExecutor(
            max_workers=4,
            thread_name_prefix="rwh-climate-normal",
        )
        self.climate_normal_archive_queue: queue.Queue = queue.Queue()
        self.climate_normal_archive_poll_after_id: str | None = None
        self.optimization_result_queue: queue.Queue = queue.Queue()
        self.optimization_poll_after_id: str | None = None
        self.project_state_poll_after_id: str | None = None
        self.working_draft_after_id: str | None = None
        self._saved_state_fingerprint = ""
        self._last_draft_fingerprint = ""
        self._project_dirty = False

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self.request_exit)
        self.execution_log.info("Application", "Application started")
        self.execution_log_poll_after_id = self.after(75, self._poll_execution_log)
        if self.execution_log_visible_var.get():
            self.after_idle(self.show_execution_log)
        self.selected_tank_var.trace_add("write", self._update_selected_tank_warning)
        self._update_selected_tank_warning()
        self._load_project_list()
        self._populate_from_model()
        self._accept_current_project_state(clear_draft=False)
        self.project_state_poll_after_id = self.after(
            PROJECT_STATE_POLL_MS, self._poll_project_state
        )
        self.working_draft_after_id = self.after(
            WORKING_DRAFT_SAVE_MS, self._autosave_working_draft
        )
        self._center_main_window()
        self.deiconify()
        if self.migrated_legacy_files:
            migrated_names = ", ".join(path.name for path in self.migrated_legacy_files)
            self.after_idle(
                lambda: messagebox.showinfo(
                    APP_TITLE,
                    "Copied legacy application data into the per-user data directory:\n"
                    f"{self.application_data_dir}\n\nFiles: {migrated_names}\n\n"
                    "The original files were retained.",
                    parent=self,
                )
            )
        if self.store.recovery_notice:
            recovery_notice = self.store.recovery_notice
            self.after_idle(
                lambda: messagebox.showwarning(
                    APP_TITLE, recovery_notice, parent=self
                )
            )
        if self.working_draft_store.exists():
            self.after_idle(self._offer_working_draft_recovery)

    def _wrap_mapped_treeview_headings(self, event: tk.Event) -> None:
        """Give every displayed data table up to two lines for its headings."""
        tree = event.widget
        if isinstance(tree, ttk.Treeview):
            self.after_idle(lambda: self._wrap_treeview_headings(tree))

    def _wrap_treeview_headings(self, tree: ttk.Treeview) -> None:
        if not isinstance(tree, ttk.Treeview):
            return
        try:
            style_name = str(tree.cget("style") or "Treeview")
            heading_style = f"{style_name}.Heading"
            heading_font_name = ttk.Style(self).lookup(heading_style, "font") or "TkHeadingFont"
            heading_font = tkfont.Font(root=self, font=heading_font_name)
            for column in tree["columns"]:
                text = str(tree.heading(column, "text"))
                width = int(tree.column(column, "width"))
                tree.heading(
                    column,
                    text=_two_line_heading_text(text, width, heading_font.measure),
                )
        except tk.TclError:
            # A short-lived dialog can be destroyed before its idle callback runs.
            return

    def _center_main_window(self) -> None:
        self.update_idletasks()
        work_x, work_y, work_width, work_height = self._screen_work_area()
        x = work_x + max((work_width - DEFAULT_WINDOW_WIDTH) // 2, 0)
        y = work_y + max((work_height - DEFAULT_WINDOW_HEIGHT) // 2, 0)
        self.geometry(f"{DEFAULT_WINDOW_WIDTH}x{DEFAULT_WINDOW_HEIGHT}+{x}+{y}")

    def _screen_work_area(self) -> tuple[int, int, int, int]:
        if sys.platform == "win32":
            try:
                import ctypes

                class Rect(ctypes.Structure):
                    _fields_ = [
                        ("left", ctypes.c_long),
                        ("top", ctypes.c_long),
                        ("right", ctypes.c_long),
                        ("bottom", ctypes.c_long),
                    ]

                rect = Rect()
                if ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):
                    return rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top
            except (AttributeError, OSError):
                pass
        return self.winfo_vrootx(), self.winfo_vrooty(), self.winfo_vrootwidth(), self.winfo_vrootheight()

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self._build_menu()

        self.notebook = ttk.Notebook(self, takefocus=False)
        self.notebook.grid(row=0, column=0, sticky="nsew", padx=10, pady=(8, 6))

        self.inputs_tab = ttk.Frame(self.notebook, padding=10)
        self.schedules_tab = ttk.Frame(self.notebook, padding=10)
        self.system_parameters_tab = ttk.Frame(self.notebook, padding=10)
        self.import_tab = ttk.Frame(self.notebook, padding=10)
        self.collection_tab = ttk.Frame(self.notebook, padding=10)
        self.demand_tab = ttk.Frame(self.notebook, padding=10)
        self.analysis_tab = ttk.Frame(self.notebook, padding=10)
        self.optimization_tab = ttk.Frame(self.notebook, padding=10)
        self.results_tab = ttk.Frame(self.notebook, padding=10)
        self.financial_tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(self.inputs_tab, text="Project Inputs")
        self.notebook.add(self.import_tab, text="Rainwater Data")
        self.notebook.add(self.collection_tab, text="Collection surfaces")
        self.notebook.add(self.schedules_tab, text="Schedules")
        self.notebook.add(self.demand_tab, text="Demand parameters")
        self.notebook.add(self.system_parameters_tab, text="System parameters")
        self.notebook.add(self.analysis_tab, text="Analysis settings")
        self.notebook.add(self.financial_tab, text="Financial analysis")
        self.notebook.add(self.optimization_tab, text="Optimization")
        self.notebook.add(self.results_tab, text="Results")
        self.notebook.bind("<<NotebookTabChanged>>", self._on_notebook_tab_changed)
        self.notebook.bind("<ButtonRelease-1>", self._clear_top_level_tab_focus, add="+")
        self.bind("<Left>", lambda event: self._navigate_top_level_tabs(event, -1), add="+")
        self.bind("<Right>", lambda event: self._navigate_top_level_tabs(event, 1), add="+")
        self.bind("<Control-Tab>", lambda event: self._navigate_top_level_tabs(event, 1, anywhere=True), add="+")
        self.bind("<Control-Shift-Tab>", lambda event: self._navigate_top_level_tabs(event, -1, anywhere=True), add="+")

        self._build_inputs_tab()
        self._build_schedules_tab()
        self._build_system_parameters_tab()
        self._build_import_tab()
        self._build_collection_tab()
        self._build_demand_tab()
        self._build_analysis_tab()
        self._build_financial_tab()
        self._build_results_tab()

        status_frame = ttk.Frame(self, padding=(10, 4))
        status_frame.grid(row=1, column=0, sticky="ew")
        status_frame.columnconfigure(0, weight=1)
        ttk.Label(status_frame, textvariable=self.status_var, anchor="w").grid(row=0, column=0, sticky="ew")
        ttk.Label(
            status_frame,
            textvariable=self.project_state_var,
            anchor="e",
        ).grid(row=0, column=1, sticky="e", padx=(12, 0))
        self.analysis_progress = ttk.Progressbar(
            status_frame,
            variable=self.analysis_progress_var,
            maximum=100,
            length=180,
            style="Analysis.Horizontal.TProgressbar",
        )
        self.analysis_progress.grid(row=0, column=2, sticky="e", padx=(12, 0))
        self.cancel_analysis_button = ttk.Button(
            status_frame, text="Cancel analysis", command=self.cancel_analysis, state="disabled"
        )
        self.cancel_analysis_button.grid(row=0, column=3, sticky="e", padx=(8, 0))

    def _clear_top_level_tab_focus(self, _event: tk.Event) -> None:
        """Keep mouse-selected main tabs from retaining the native dotted focus ring."""
        self.after_idle(self.focus_set)

    def _navigate_top_level_tabs(
        self, _event: tk.Event, direction: int, *, anywhere: bool = False
    ) -> str | None:
        if not anywhere and self.focus_get() is not self:
            return None
        tabs = self.notebook.tabs()
        if not tabs:
            return "break"
        current = self.notebook.index(self.notebook.select())
        self.notebook.select(tabs[(current + direction) % len(tabs)])
        self.focus_set()
        return "break"

    def _build_menu(self) -> None:
        menubar = tk.Menu(self)
        file_menu = tk.Menu(menubar, tearoff=False)
        file_menu.add_command(label="Create new project", accelerator="Ctrl+N", command=self.new_project)
        file_menu.add_command(label="Open project...", accelerator="Ctrl+O", command=self.open_project_from)
        file_menu.add_command(
            label="Open most recent project",
            accelerator="Ctrl+Alt+O",
            command=self.open_most_recent_project,
        )
        self.recent_menu = tk.Menu(file_menu, tearoff=False)
        file_menu.add_cascade(label="Open recent project", menu=self.recent_menu)
        examples_menu = tk.Menu(file_menu, tearoff=False)
        for example_id, label in EXAMPLE_PROJECT_LABELS.items():
            examples_menu.add_command(
                label=label,
                command=lambda value=example_id: self.load_example_project(value),
            )
        file_menu.add_cascade(label="Examples", menu=examples_menu)
        file_menu.add_command(label="Save project", accelerator="Ctrl+S", command=self.save_project)
        file_menu.add_command(label="Save project as...", accelerator="Ctrl+Shift+S", command=self.save_project_as)
        file_menu.add_separator()
        file_menu.add_command(label="Close project", accelerator="Ctrl+W", command=self.close_project)
        file_menu.add_command(label="Exit", accelerator="Ctrl+Q", command=self.request_exit)
        menubar.add_cascade(label="File", menu=file_menu)

        analysis_menu = tk.Menu(menubar, tearoff=False)
        analysis_menu.add_command(
            label="Run single-tank analysis",
            accelerator="Ctrl+R",
            command=self.run_single_tank_analysis,
        )
        analysis_menu.add_command(
            label="Run multi-tank analysis",
            accelerator="Ctrl+Alt+R",
            command=self.run_multitank_analysis,
        )
        menubar.add_cascade(label="Run analysis", menu=analysis_menu)

        export_menu = tk.Menu(menubar, tearoff=False)
        export_menu.add_command(label="Export results...", command=self.export_results)
        export_menu.add_command(label="Export PDF report...", command=self.export_pdf_report)
        export_menu.add_command(label="Export HTML report...", command=self.export_html_report)
        menubar.add_cascade(label="Export", menu=export_menu)

        view_menu = tk.Menu(menubar, tearoff=False)
        view_menu.add_command(label="View PDF report", command=self.view_pdf_report)
        view_menu.add_command(label="View HTML report", command=self.view_html_report)
        view_menu.add_separator()
        view_menu.add_command(label="Execution log", command=self.show_execution_log)
        menubar.add_cascade(label="View", menu=view_menu)

        settings_menu = tk.Menu(menubar, tearoff=False)
        number_format_menu = tk.Menu(settings_menu, tearoff=False)
        number_format_labels = {
            US_NUMBER_FORMAT: "1,000.00 (U.S.)",
            EUROPEAN_NUMBER_FORMAT: "1.000,00 (France/Europe)",
        }
        for number_format in NUMBER_FORMATS:
            number_format_menu.add_radiobutton(
                label=number_format_labels[number_format],
                value=number_format,
                variable=self.number_format_var,
                command=self._number_format_changed,
            )
        settings_menu.add_cascade(label="Number format", menu=number_format_menu)
        settings_menu.add_separator()
        text_size_menu = tk.Menu(settings_menu, tearoff=False)
        for percentage in TEXT_SCALE_PERCENTAGES:
            text_size_menu.add_radiobutton(
                label=f"{percentage}%",
                value=percentage,
                variable=self.text_scale_var,
                command=self._text_scale_changed,
            )
        settings_menu.add_cascade(label="Text size", menu=text_size_menu)
        settings_menu.add_separator()
        settings_menu.add_checkbutton(
            label="Show execution log",
            variable=self.execution_log_visible_var,
            command=self._execution_log_visibility_changed,
        )
        detail_menu = tk.Menu(settings_menu, tearoff=False)
        for detail in DETAIL_LEVELS:
            detail_menu.add_radiobutton(
                label=detail,
                value=detail,
                variable=self.execution_log_detail_var,
                command=self._execution_log_detail_changed,
            )
        settings_menu.add_cascade(label="Log detail", menu=detail_menu)
        menubar.add_cascade(label="Settings", menu=settings_menu)

        help_menu = tk.Menu(menubar, tearoff=False)
        help_menu.add_command(label="User guide", command=self.open_user_guide)
        help_menu.add_command(label="Online documentation", command=self.open_online_documentation)
        help_menu.add_separator()
        help_menu.add_command(label="About RWH Calculator", command=self._show_about_dialog)
        menubar.add_cascade(label="Help", menu=help_menu)
        self.config(menu=menubar)
        self._refresh_recent_projects_menu()

        self.bind_all("<Control-n>", self._shortcut_create_new_project)
        self.bind_all("<Control-s>", self._shortcut_save_project)
        self.bind_all("<Control-Shift-S>", self._shortcut_save_project_as)
        self.bind_all("<Control-Shift-s>", self._shortcut_save_project_as)
        self.bind_all("<Control-o>", self._shortcut_open_project_from)
        self.bind_all("<Control-Alt-o>", self._shortcut_open_most_recent_project)
        self.bind_all("<Control-Alt-O>", self._shortcut_open_most_recent_project)
        self.bind_all("<Control-r>", self._shortcut_run_analysis)
        self.bind_all("<Control-Alt-r>", self._shortcut_run_multitank_analysis)
        self.bind_all("<Control-Alt-R>", self._shortcut_run_multitank_analysis)
        self.bind_all("<Control-w>", self._shortcut_close_project)
        self.bind_all("<Control-q>", self._shortcut_exit)

    def _on_notebook_tab_changed(self, _event: tk.Event) -> None:
        if self.notebook.select() == str(self.optimization_tab):
            self._apply_form_to_model()
            self._refresh_optimization_assumptions()
            self.last_analysis_warning_key = None
            self.last_unit_conversion_notice = None
            return
        if self.notebook.select() == str(self.financial_tab):
            self.update_financial_analysis(show_errors=False)
            self.last_analysis_warning_key = None
            self.last_unit_conversion_notice = None
            return
        if self.notebook.select() != str(self.results_tab):
            self.last_analysis_warning_key = None
            self.last_unit_conversion_notice = None
            return
        if not self.results_df.empty or not self.curve_df.empty:
            self.after_idle(self._draw_saved_analysis_charts)
        previous_signature = self.config_model.analysis_input_signature
        if not previous_signature:
            return
        current_form_snapshot = self._calculation_form_snapshot()
        if self.unit_conversion_form_snapshot != current_form_snapshot:
            self._apply_form_to_model()
        current_signature = analysis_input_signature(self.config_model, self.rainfall_df)
        if current_signature != previous_signature:
            warning_key = f"{previous_signature}:{current_signature}"
            if self.last_analysis_warning_key == warning_key:
                return
            self.last_analysis_warning_key = warning_key
            messagebox.showwarning(
                APP_TITLE,
                "Simulation parameters have changed. The analysis needs to be re-run.",
            )
            return
        analysis_units = self.config_model.analysis_unit_system
        current_units = self.config_model.unit_system
        if analysis_units and analysis_units != current_units:
            notice_key = f"{analysis_units}:{current_units}:{previous_signature}"
            if self.last_unit_conversion_notice != notice_key:
                self.last_unit_conversion_notice = notice_key
                messagebox.showinfo(
                    APP_TITLE,
                    f"The unit system changed from {analysis_units} to {current_units}. "
                    "The saved analysis remains valid; charts and result values were converted without rerunning it.",
                )

    def _on_results_subtab_changed(self, _event: tk.Event) -> None:
        self.after_idle(self._draw_saved_analysis_charts)

    def open_user_guide(self) -> None:
        index_path = _help_index_path()
        if index_path is None:
            messagebox.showinfo(
                APP_TITLE,
                "The local user guide has not been built yet.\n\n"
                "Run '.\\.venv\\Scripts\\python.exe -m mkdocs build' or use Help > Online documentation.",
            )
            return
        webbrowser.open(index_path.resolve().as_uri())

    def open_online_documentation(self) -> None:
        webbrowser.open(ONLINE_HELP_URL)

    def _shortcut_create_new_project(self, _event: tk.Event) -> str:
        self.new_project()
        return "break"

    def _shortcut_save_project(self, _event: tk.Event) -> str:
        self.save_project()
        return "break"

    def _shortcut_save_project_as(self, _event: tk.Event) -> str:
        self.save_project_as()
        return "break"

    def _shortcut_open_project_from(self, _event: tk.Event) -> str:
        self.open_project_from()
        return "break"

    def _shortcut_open_most_recent_project(self, _event: tk.Event) -> str:
        self.open_most_recent_project()
        return "break"

    def _shortcut_run_analysis(self, _event: tk.Event) -> str:
        self.run_single_tank_analysis()
        return "break"

    def _shortcut_run_multitank_analysis(self, _event: tk.Event) -> str:
        self.run_multitank_analysis()
        return "break"

    def _shortcut_close_project(self, _event: tk.Event) -> str:
        self.close_project()
        return "break"

    def _shortcut_exit(self, _event: tk.Event) -> str:
        self.request_exit()
        return "break"

    def _load_recent_project_paths(self) -> list[str]:
        try:
            payload = json.loads(self.recent_projects_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        if not isinstance(payload, list):
            return []
        paths: list[str] = []
        for item in payload:
            if isinstance(item, str) and item.strip() and item not in paths:
                paths.append(item)
        return paths[:MAX_RECENT_PROJECTS]

    def _load_app_preferences(self) -> dict[str, object]:
        try:
            payload = json.loads(self.app_preferences_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def _save_app_preferences(self) -> None:
        self.app_preferences.update({
            "show_execution_log": bool(self.execution_log_visible_var.get()),
            "execution_log_detail": normalize_log_detail(self.execution_log_detail_var.get()),
            "text_scale_percent": _normalize_text_scale_percent(self.text_scale_var.get()),
            "number_format": normalize_number_format(self.number_format_var.get()),
            "recent_rainfall_csv_paths": self.recent_rainfall_csv_paths,
            "pinned_rainfall_csv_paths": self.pinned_rainfall_csv_paths,
        })
        try:
            self.app_preferences_path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_text(
                self.app_preferences_path, json.dumps(self.app_preferences, indent=2)
            )
        except OSError as exc:
            self.execution_log.warning(
                "Settings", "Could not save application preferences", details=str(exc)
            )

    def _preference_path_list(self, key: str, limit: int) -> list[str]:
        raw_paths = self.app_preferences.get(key, [])
        if not isinstance(raw_paths, list):
            return []
        paths: list[str] = []
        seen: set[str] = set()
        for item in raw_paths:
            if not isinstance(item, str) or not item.strip():
                continue
            path_text = str(Path(item).expanduser().resolve(strict=False))
            identity = path_text.casefold()
            if identity in seen:
                continue
            seen.add(identity)
            paths.append(path_text)
            if len(paths) >= limit:
                break
        return paths

    def _apply_tk_text_scale(self, percentage: int) -> None:
        self.tk.call(
            "tk", "scaling", self._default_tk_scaling * percentage / 100.0
        )

    def _refresh_scaled_widget_fonts(self, widget: tk.Misc) -> None:
        """Notify existing widgets that point-sized fonts have new pixel metrics."""
        try:
            if "font" in widget.keys():
                current_font = widget.cget("font")
                if current_font:
                    widget.configure(font=current_font)
        except (AttributeError, tk.TclError):
            pass
        if isinstance(widget, tk.Canvas):
            for item in widget.find_all():
                if widget.type(item) == "text":
                    current_font = widget.itemcget(item, "font")
                    if current_font:
                        widget.itemconfigure(item, font=current_font)
        for child in widget.winfo_children():
            self._refresh_scaled_widget_fonts(child)

    def _text_scale_changed(self) -> None:
        percentage = _normalize_text_scale_percent(self.text_scale_var.get())
        self.text_scale_var.set(percentage)
        self._apply_tk_text_scale(percentage)
        for font_name in tkfont.names(self):
            named_font = tkfont.nametofont(font_name, root=self)
            named_font.configure(size=named_font.cget("size"))
        self._refresh_scaled_widget_fonts(self)
        self.update_idletasks()
        self._save_app_preferences()
        self.execution_log.info("Settings", f"Text size set to {percentage}%")

    def _number_format_changed(self) -> None:
        self._apply_form_to_model()
        number_format = set_active_number_format(self.number_format_var.get())
        self.number_format_var.set(number_format)
        self._save_app_preferences()
        self._populate_from_model()
        if not self.results_df.empty:
            self._populate_results()
        self.status_var.set(f"Number format set to {number_format}")
        self.execution_log.info("Settings", f"Number format set to {number_format}")

    def _save_recent_project_paths(self) -> None:
        try:
            atomic_write_text(
                self.recent_projects_path,
                json.dumps(self.recent_project_paths, indent=2),
            )
        except OSError:
            pass

    def _load_custom_schedule_templates(self) -> dict[str, dict[str, list[float]]]:
        self.__dict__.setdefault("custom_schedule_template_months", {})
        try:
            payload = json.loads(self.custom_schedule_library_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        schedule_payload: dict[str, object] = {}
        for raw_name, raw_value in payload.items() if isinstance(payload, dict) else ():
            name = str(raw_name)
            if (
                isinstance(raw_value, dict)
                and isinstance(raw_value.get("values"), dict)
            ):
                schedule_payload[name] = raw_value["values"]
                self.custom_schedule_template_types[name] = normalize_schedule_type(
                    raw_value.get("schedule_type")
                )
                self.custom_schedule_template_months[name] = normalized_schedule_months(
                    raw_value.get("months", list(range(1, 13)))
                )
            else:
                schedule_payload[name] = raw_value
                self.custom_schedule_template_types[name] = FRACTIONAL_SCHEDULE_TYPE
                self.custom_schedule_template_months[name] = list(range(1, 13))
        schedules = _validated_schedule_library(schedule_payload)
        self.custom_schedule_template_types = {
            name: self.custom_schedule_template_types.get(
                name, FRACTIONAL_SCHEDULE_TYPE
            )
            for name in schedules
        }
        self.custom_schedule_template_months = {
            name: self.custom_schedule_template_months.get(name, list(range(1, 13)))
            for name in schedules
        }
        return schedules

    def _save_custom_schedule_templates(self) -> None:
        template_months = self.__dict__.get("custom_schedule_template_months", {})
        payload = {
            name: {
                "schedule_type": self.custom_schedule_template_types.get(
                    name, FRACTIONAL_SCHEDULE_TYPE
                ),
                "months": template_months.get(
                    name, list(range(1, 13))
                ),
                "values": schedule,
            }
            for name, schedule in self.custom_schedule_templates.items()
        }
        atomic_write_text(
            self.custom_schedule_library_path,
            json.dumps(payload, indent=2),
        )

    def _load_custom_demand_object_templates(self) -> dict[str, DemandObject]:
        try:
            payload = json.loads(self.custom_demand_object_library_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return _validated_demand_object_library(payload)

    def _save_custom_demand_object_templates(self) -> None:
        payload = {
            name: {
                "object_type": demand_object.object_type,
                "instantaneous_demand_gallons_per_minute": demand_object.instantaneous_demand_gallons_per_minute,
                "demand_mode": demand_object.demand_mode,
                "recurring_daily_gallons": demand_object.recurring_daily_gallons,
                "operating_days_per_week": demand_object.operating_days_per_week,
                "operating_weekdays": demand_object.operating_weekdays,
                "monthly_daily_demand_gallons": demand_object.monthly_daily_demand_gallons,
                "monthly_demand_gallons": demand_object.monthly_demand_gallons,
                "sewer_eligible": demand_object.sewer_eligible,
            }
            for name, demand_object in self.custom_demand_object_templates.items()
        }
        atomic_write_text(
            self.custom_demand_object_library_path, json.dumps(payload, indent=2)
        )

    def _add_recent_project_path(self, path: Path) -> None:
        recent_path = str(path.expanduser().resolve(strict=False))
        self.recent_project_paths = [
            existing for existing in self.recent_project_paths if existing.casefold() != recent_path.casefold()
        ]
        self.recent_project_paths.insert(0, recent_path)
        self.recent_project_paths = self.recent_project_paths[:MAX_RECENT_PROJECTS]
        self._save_recent_project_paths()
        self._refresh_recent_projects_menu()

    def _refresh_recent_projects_menu(self) -> None:
        self.recent_menu.delete(0, tk.END)
        if not self.recent_project_paths:
            self.recent_menu.add_command(label="No recent projects", state="disabled")
            return
        for index, path_text in enumerate(self.recent_project_paths, start=1):
            path = Path(path_text)
            label = f"{index}. {path.name} ({path.parent})"
            self.recent_menu.add_command(label=label, command=lambda value=path_text: self.open_recent_project(value))
        self.recent_menu.add_separator()
        self.recent_menu.add_command(label="Clear recent projects", command=self.clear_recent_projects)

    def _set_progress(self, value: float, status: str, style: str = "Analysis.Horizontal.TProgressbar") -> None:
        self.analysis_progress.configure(style=style)
        self.analysis_progress_var.set(value)
        self.status_var.set(status)
        self.execution_log.debug("Progress", status)
        self._drain_execution_log_to_window()
        self.update_idletasks()

    def _execution_log_visibility_changed(self) -> None:
        if self.execution_log_visible_var.get():
            self.show_execution_log()
        else:
            self.hide_execution_log()

    def _execution_log_detail_changed(self, _event: tk.Event | None = None) -> None:
        detail = normalize_log_detail(self.execution_log_detail_var.get())
        self.execution_log_detail_var.set(detail)
        self._save_app_preferences()
        self._refresh_execution_log_text()
        self.execution_log.info("Settings", f"Execution log detail set to {detail}")

    def show_execution_log(self) -> None:
        if self.execution_log_window is None or not self.execution_log_window.winfo_exists():
            self._build_execution_log_window()
        assert self.execution_log_window is not None
        self.execution_log_visible_var.set(True)
        self.execution_log_window.deiconify()
        self.execution_log_window.lift()
        self._refresh_execution_log_text()
        self._save_app_preferences()

    def hide_execution_log(self) -> None:
        if self.execution_log_window is not None and self.execution_log_window.winfo_exists():
            self.execution_log_window.withdraw()
        self.execution_log_visible_var.set(False)
        self._save_app_preferences()

    def _build_execution_log_window(self) -> None:
        window = tk.Toplevel(self)
        window.title("Execution log")
        window.geometry("900x440")
        window.minsize(620, 280)
        window.protocol("WM_DELETE_WINDOW", self.hide_execution_log)
        window.columnconfigure(0, weight=1)
        window.rowconfigure(1, weight=1)
        self.execution_log_window = window

        controls = ttk.Frame(window, padding=(10, 8))
        controls.grid(row=0, column=0, sticky="ew")
        controls.columnconfigure(7, weight=1)
        ttk.Label(controls, text="Detail").grid(row=0, column=0, sticky="w")
        detail_combo = ttk.Combobox(
            controls,
            textvariable=self.execution_log_detail_var,
            values=tuple(DETAIL_LEVELS),
            state="readonly",
            width=11,
        )
        detail_combo.grid(row=0, column=1, sticky="w", padx=(6, 14))
        detail_combo.bind("<<ComboboxSelected>>", self._execution_log_detail_changed)
        ttk.Checkbutton(
            controls,
            text="Auto-scroll",
            variable=self.execution_log_auto_scroll_var,
        ).grid(row=0, column=2, sticky="w", padx=(0, 12))
        ttk.Checkbutton(
            controls,
            text="Pause display",
            variable=self.execution_log_pause_var,
            command=self._execution_log_pause_changed,
        ).grid(row=0, column=3, sticky="w", padx=(0, 12))
        ttk.Button(controls, text="Clear", command=self._clear_execution_log).grid(
            row=0, column=4, padx=(0, 6)
        )
        ttk.Button(controls, text="Copy", command=self._copy_execution_log).grid(
            row=0, column=5, padx=(0, 6)
        )
        ttk.Button(controls, text="Save log...", command=self._save_execution_log).grid(
            row=0, column=6, padx=(0, 6)
        )
        ttk.Button(controls, text="Open log folder", command=self._open_execution_log_folder).grid(
            row=0, column=8, sticky="e"
        )

        text_frame = ttk.Frame(window, padding=(10, 0, 10, 10))
        text_frame.grid(row=1, column=0, sticky="nsew")
        text_frame.columnconfigure(0, weight=1)
        text_frame.rowconfigure(0, weight=1)
        text_widget = tk.Text(
            text_frame,
            wrap="none",
            font=("TkFixedFont", 9),
            state="disabled",
            background="#101417",
            foreground="#e6edf3",
            insertbackground="#e6edf3",
        )
        text_widget.grid(row=0, column=0, sticky="nsew")
        scroll_y = ttk.Scrollbar(text_frame, orient="vertical", command=text_widget.yview)
        scroll_y.grid(row=0, column=1, sticky="ns")
        scroll_x = ttk.Scrollbar(text_frame, orient="horizontal", command=text_widget.xview)
        scroll_x.grid(row=1, column=0, sticky="ew")
        text_widget.configure(yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set)
        for tag, color in {
            "DIAGNOSTIC": "#8b949e",
            "DEBUG": "#79c0ff",
            "INFO": "#7ee787",
            "WARNING": "#e3b341",
            "ERROR": "#ff7b72",
        }.items():
            text_widget.tag_configure(tag, foreground=color)
        self.execution_log_text = text_widget

    def _execution_log_pause_changed(self) -> None:
        if not self.execution_log_pause_var.get():
            self._refresh_execution_log_text()

    def _execution_log_entry_visible(self, entry: ExecutionLogEntry) -> bool:
        threshold = DETAIL_LEVELS[normalize_log_detail(self.execution_log_detail_var.get())]
        return entry.level >= threshold

    def _append_execution_log_entries(self, entries: list[ExecutionLogEntry]) -> None:
        text_widget = self.execution_log_text
        if text_widget is None or not text_widget.winfo_exists():
            return
        visible = [entry for entry in entries if self._execution_log_entry_visible(entry)]
        if not visible:
            return
        include_details = normalize_log_detail(self.execution_log_detail_var.get()) == "Diagnostic"
        text_widget.configure(state="normal")
        for entry in visible:
            text_widget.insert(
                tk.END,
                entry.display_text(include_details=include_details),
                (entry.level_name,),
            )
        text_widget.configure(state="disabled")
        if self.execution_log_auto_scroll_var.get():
            text_widget.see(tk.END)

    def _refresh_execution_log_text(self) -> None:
        text_widget = self.execution_log_text
        if text_widget is None or not text_widget.winfo_exists():
            return
        self.execution_log.drain(maximum=100_000)
        text_widget.configure(state="normal")
        text_widget.delete("1.0", tk.END)
        text_widget.configure(state="disabled")
        self._append_execution_log_entries(self.execution_log.history())

    def _drain_execution_log_to_window(self) -> None:
        entries = self.execution_log.drain(maximum=500)
        if (
            entries
            and not self.execution_log_pause_var.get()
            and self.execution_log_window is not None
            and self.execution_log_window.winfo_exists()
            and self.execution_log_window.state() != "withdrawn"
        ):
            self._append_execution_log_entries(entries)

    def _poll_execution_log(self) -> None:
        self.execution_log_poll_after_id = None
        self._drain_execution_log_to_window()
        self.execution_log_poll_after_id = self.after(75, self._poll_execution_log)

    def _clear_execution_log(self) -> None:
        self.execution_log.clear()
        self._refresh_execution_log_text()

    def _execution_log_export_text(self) -> str:
        self.execution_log.drain(maximum=100_000)
        detail = normalize_log_detail(self.execution_log_detail_var.get())
        include_details = detail == "Diagnostic"
        return "".join(
            entry.display_text(include_details=include_details)
            for entry in self.execution_log.history()
            if self._execution_log_entry_visible(entry)
        )

    def _copy_execution_log(self) -> None:
        self.clipboard_clear()
        self.clipboard_append(self._execution_log_export_text())

    def _save_execution_log(self) -> None:
        path = filedialog.asksaveasfilename(
            title="Save execution log",
            initialfile="rainwater_execution_log.txt",
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("Log files", "*.log"), ("All files", "*.*")],
            parent=self.execution_log_window or self,
        )
        if not path:
            return
        try:
            Path(path).write_text(self._execution_log_export_text(), encoding="utf-8")
            self.execution_log.info("Log", f"Saved displayed log to {Path(path).name}")
        except OSError as exc:
            self.execution_log.error("Log", "Could not save displayed log", exception=exc)
            messagebox.showerror(APP_TITLE, f"Could not save execution log:\n{exc}", parent=self)

    def _open_execution_log_folder(self) -> None:
        try:
            self._open_local_file(self.execution_log.log_directory)
        except OSError as exc:
            self.execution_log.error("Log", "Could not open log folder", exception=exc)
            messagebox.showerror(APP_TITLE, f"Could not open log folder:\n{exc}", parent=self)

    def _show_about_dialog(self) -> None:
        dialog = tk.Toplevel(self)
        dialog.title("About RWH Calculator")
        dialog.transient(self)
        dialog.geometry("720x560")
        dialog.minsize(560, 360)
        dialog.columnconfigure(0, weight=1)
        dialog.rowconfigure(0, weight=1)

        text_frame = ttk.Frame(dialog, padding=(10, 10, 10, 0))
        text_frame.grid(row=0, column=0, sticky="nsew")
        text_frame.columnconfigure(0, weight=1)
        text_frame.rowconfigure(0, weight=1)

        text = tk.Text(text_frame, wrap="word", height=24, width=84)
        text.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(text_frame, orient="vertical", command=text.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        text.configure(yscrollcommand=scrollbar.set)
        text.insert("1.0", ABOUT_TEXT)
        text.configure(state="disabled")

        button_frame = ttk.Frame(dialog, padding=10)
        button_frame.grid(row=1, column=0, sticky="e")
        ttk.Button(button_frame, text="Close", command=dialog.destroy).grid(row=0, column=0)
        dialog.bind("<Escape>", lambda _event: dialog.destroy())
        dialog.focus_set()

    def _build_inputs_tab(self) -> None:
        self.inputs_tab.columnconfigure(0, weight=1)
        project_frame = ttk.LabelFrame(self.inputs_tab, text="Project Settings", padding=10)
        project_frame.grid(row=0, column=0, sticky="ew")
        project_frame.columnconfigure(1, weight=1)
        ttk.Label(project_frame, text="Project name").grid(row=0, column=0, sticky="w")
        ttk.Entry(project_frame, textvariable=self.project_name_var).grid(row=0, column=1, sticky="ew", padx=(8, 20))
        ttk.Label(project_frame, text="Units").grid(row=0, column=2, sticky="w")
        unit_combo = ttk.Combobox(
            project_frame,
            textvariable=self.unit_var,
            values=UNIT_SYSTEMS,
            width=15,
            state="readonly",
        )
        unit_combo.grid(row=0, column=3, padx=(8, 20))
        unit_combo.bind("<<ComboboxSelected>>", lambda _event: self._change_units())
        ttk.Label(project_frame, text="Country").grid(row=0, column=4, sticky="w")
        self.country_combo = ttk.Combobox(
            project_frame,
            textvariable=self.country_var,
            values=COUNTRY_LABELS,
            width=30,
            state="readonly",
        )
        self.country_combo.grid(row=0, column=5, padx=(8, 0))
        self.country_combo.configure(postcommand=self._bind_country_combo_dropdown)
        self.country_combo.bind("<KeyPress>", self._select_country_by_typed_prefix)
        self.country_combo.bind("<<ComboboxSelected>>", self._country_changed)
        ttk.Label(project_frame, text="Produced by / author").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(project_frame, textvariable=self.author_name_var).grid(
            row=1, column=1, columnspan=5, sticky="ew", padx=(8, 0), pady=(8, 0)
        )

        notes_frame = ttk.LabelFrame(self.inputs_tab, text="Notes", padding=10)
        notes_frame.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        notes_frame.columnconfigure(0, weight=1)
        self.project_notes_text = tk.Text(notes_frame, height=3, wrap="word", undo=True)
        self.project_notes_text.grid(row=0, column=0, sticky="ew")
        notes_scroll = ttk.Scrollbar(notes_frame, orient="vertical", command=self.project_notes_text.yview)
        notes_scroll.grid(row=0, column=1, sticky="ns")
        self.project_notes_text.configure(yscrollcommand=notes_scroll.set)

        location_frame = ttk.LabelFrame(self.inputs_tab, text="Project Location", padding=10)
        location_frame.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        location_frame.columnconfigure(1, weight=1)
        location_frame.columnconfigure(3, weight=1)
        location_frame.columnconfigure(5, weight=1)
        location_buttons = ttk.Frame(location_frame)
        location_buttons.grid(row=0, column=0, columnspan=6, sticky="w")
        ttk.Button(location_buttons, text="Find on OpenStreetMap...", command=self.find_project_location).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Button(
            location_buttons,
            text="Find nearest OSM address",
            command=self.find_address_for_coordinates,
        ).grid(row=0, column=1, sticky="w", padx=(8, 0))
        ttk.Button(
            location_buttons,
            text="Find nearest coordinates from OSM",
            command=self.find_coordinates_for_address,
        ).grid(row=0, column=2, sticky="w", padx=(8, 0))
        ttk.Label(location_frame, text="Street address").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(location_frame, textvariable=self.street_address_var).grid(
            row=1,
            column=1,
            columnspan=5,
            sticky="ew",
            padx=(8, 0),
            pady=(8, 0),
        )
        ttk.Label(location_frame, text="City").grid(row=2, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(location_frame, textvariable=self.city_var).grid(
            row=2, column=1, sticky="ew", padx=(8, 20), pady=(8, 0)
        )
        ttk.Label(location_frame, text="State / province / region").grid(row=2, column=2, sticky="w", pady=(8, 0))
        ttk.Entry(location_frame, textvariable=self.state_or_province_var, width=18).grid(
            row=2, column=3, sticky="ew", padx=(8, 20), pady=(8, 0)
        )
        ttk.Label(location_frame, text="Postal code").grid(row=2, column=4, sticky="w", pady=(8, 0))
        ttk.Entry(location_frame, textvariable=self.postal_code_var, width=14).grid(
            row=2, column=5, sticky="ew", padx=(8, 0), pady=(8, 0)
        )
        ttk.Label(location_frame, text="Latitude").grid(row=3, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(location_frame, textvariable=self.latitude_var, width=18).grid(
            row=3, column=1, sticky="w", padx=(8, 20), pady=(8, 0)
        )
        ttk.Label(location_frame, text="Longitude").grid(row=3, column=2, sticky="w", pady=(8, 0))
        ttk.Entry(location_frame, textvariable=self.longitude_var, width=18).grid(
            row=3, column=3, sticky="w", padx=(8, 20), pady=(8, 0)
        )
        ttk.Label(location_frame, textvariable=self.coordinates_var, foreground="#5f6b70").grid(
            row=4, column=1, columnspan=5, sticky="w", pady=(6, 0)
        )

    def _show_collection_surface_tip(self) -> None:
        messagebox.showinfo(
            "Collection surfaces",
            "Enter the gross horizontal roof area projected over the ground. "
            "For a sloped roof, use its plan-view footprint rather than the larger sloped surface area.",
            parent=self,
        )

    def _show_weather_source_tip(self) -> None:
        if self._selected_country_code() == "CAN":
            detail = (
                "Canadian imports use Environment and Climate Change Canada (ECCC) daily station observations. "
                "Records contain a date and precipitation measured in millimetres; the selected precipitation "
                "basis determines whether total precipitation or rain only is imported."
            )
        else:
            detail = (
                "United States imports use daily station records from the NOAA Regional Climate Centers' "
                "Applied Climate Information System (ACIS). Records contain a date and precipitation measured "
                "in inches. ACIS rain-only imports exclude precipitation on reported snowfall days."
            )
        messagebox.showinfo("Rainfall data source", detail, parent=self)

    def _show_rainfall_csv_format_tip(self) -> None:
        unit = precip_unit(self.config_model)
        messagebox.showinfo(
            "Daily rainfall CSV format",
            "The CSV must contain columns named Date and Precipitation. "
            "Header capitalization and surrounding spaces are ignored; additional columns are allowed.\n\n"
            "Use one row per day. Dates should preferably use the unambiguous YYYY-MM-DD format. "
            f"Precipitation must be numeric and expressed in {unit}, matching the current project units. "
            "Blank or nonnumeric precipitation values are treated as zero.\n\n"
            "Example:\n"
            "Date,Precipitation\n"
            "2025-01-01,0.00\n"
            "2025-01-02,0.37\n"
            "2025-01-03,0.00",
            parent=self,
        )

    def _show_multi_site_comparison_info(self) -> None:
        existing = self.__dict__.get("multi_site_info_window")
        if existing is not None and existing.winfo_exists():
            self._refresh_climate_normal_archive_status()
            existing.deiconify()
            existing.lift()
            existing.focus_force()
            return

        dialog = tk.Toplevel(self)
        self.multi_site_info_window = dialog
        dialog.title("About multi-site comparison")
        dialog.transient(self)
        dialog.resizable(True, True)
        dialog.columnconfigure(0, weight=1)

        body = ttk.Frame(dialog, padding=14)
        body.grid(row=0, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)

        overview = ttk.LabelFrame(body, text="Purpose", padding=10)
        overview.grid(row=0, column=0, sticky="ew")
        overview.columnconfigure(0, weight=1)
        ttk.Label(
            overview,
            text=(
                "Compare NOAA 1991-2020 annual and seasonal precipitation normals for "
                "multiple U.S. locations without changing the rainfall data assigned to "
                "this project."
            ),
            foreground="#5f6b70",
            wraplength=720,
            justify="left",
        ).grid(row=0, column=0, sticky="ew")

        disclaimer = ttk.LabelFrame(body, text="Planning-data disclaimer", padding=10)
        disclaimer.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        disclaimer.columnconfigure(0, weight=1)
        ttk.Label(
            disclaimer,
            text=(
                "Precipitation is shown in the project's current units as water equivalent "
                "and includes the liquid-water equivalent of frozen precipitation. These "
                "NOAA Climate Normals use a different source and fixed 1991-2020 period from "
                "project simulation rainfall. A simulation's average annual precipitation "
                "may differ because its station, period, precipitation basis, completeness, "
                "or provider processing may differ."
            ),
            foreground="#7a4e00",
            wraplength=720,
            justify="left",
        ).grid(row=0, column=0, sticky="ew")
        source_link = ttk.Label(
            disclaimer,
            text="Open NOAA U.S. Climate Normals Quick Access",
            foreground="#0563c1",
            cursor="hand2",
            font=("Segoe UI", 9, "underline"),
        )
        source_link.grid(row=1, column=0, sticky="w", pady=(6, 0))
        source_link.bind(
            "<Button-1>", lambda _event: webbrowser.open(NCEI_CLIMATE_NORMALS_URL)
        )

        archive_frame = ttk.LabelFrame(
            body, text="Optional offline Climate Normals archive", padding=10
        )
        archive_frame.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        archive_frame.columnconfigure(0, weight=1)
        ttk.Label(
            archive_frame,
            textvariable=self.climate_normal_archive_status_var,
            foreground="#5f6b70",
            wraplength=560,
            justify="left",
        ).grid(row=0, column=0, sticky="ew")
        archive_actions = ttk.Frame(archive_frame)
        archive_actions.grid(row=0, column=1, rowspan=2, sticky="e", padx=(12, 0))
        self.download_climate_normal_archive_button = ttk.Button(
            archive_actions,
            text="Download archive",
            command=self.download_climate_normal_archive,
        )
        self.download_climate_normal_archive_button.pack(side="left")
        self.remove_climate_normal_archive_button = ttk.Button(
            archive_actions,
            text="Remove archive",
            command=self.remove_climate_normal_archive,
        )
        self.remove_climate_normal_archive_button.pack(side="left", padx=(8, 0))
        self.climate_normal_archive_progress = ttk.Progressbar(
            archive_frame,
            variable=self.climate_normal_archive_progress_var,
            maximum=100.0,
        )
        self.climate_normal_archive_progress.grid(
            row=1, column=0, sticky="ew", pady=(7, 0)
        )
        self.climate_normal_archive_progress.grid_remove()
        self._refresh_climate_normal_archive_status()

        ttk.Button(body, text="Close", command=dialog.withdraw).grid(
            row=3, column=0, sticky="e", pady=(12, 0)
        )
        dialog.protocol("WM_DELETE_WINDOW", dialog.withdraw)
        dialog.bind("<Escape>", lambda _event: dialog.withdraw())
        dialog.update_idletasks()
        width = max(dialog.winfo_reqwidth(), 760)
        height = dialog.winfo_reqheight()
        x = self.winfo_rootx() + max((self.winfo_width() - width) // 2, 0)
        y = self.winfo_rooty() + max((self.winfo_height() - height) // 2, 0)
        dialog.geometry(f"{width}x{height}+{x}+{y}")
        dialog.lift()
        dialog.focus_force()

    def _rainwater_data_notebook_clicked(self, event: tk.Event) -> str | None:
        try:
            tab_index = self.rainwater_data_notebook.index(f"@{event.x},{event.y}")
        except tk.TclError:
            return None
        if tab_index != self.rainwater_data_notebook.index(
            self.multi_site_rainwater_tab
        ):
            return None
        tab_right = event.x
        for probe_x in range(event.x, self.rainwater_data_notebook.winfo_width()):
            try:
                probe_index = self.rainwater_data_notebook.index(
                    f"@{probe_x},{event.y}"
                )
            except tk.TclError:
                break
            if probe_index != tab_index:
                break
            tab_right = probe_x + 1
        if event.x < tab_right - 28:
            return None
        self.after_idle(self._show_multi_site_comparison_info)
        return "break"

    def _create_info_icon(self, size: int = 20) -> tk.PhotoImage:
        image = tk.PhotoImage(master=self, width=size, height=size)
        center = (size - 1) / 2.0
        radius = size / 2.0 - 1.0
        for y in range(size):
            for x in range(size):
                if (x - center) ** 2 + (y - center) ** 2 <= radius ** 2:
                    image.put("#176b9c", (x, y))
        center_x = int(round(center))
        for y in range(8, 15):
            image.put("#ffffff", (center_x, y))
            image.put("#ffffff", (center_x - 1, y))
        for x in range(center_x - 2, center_x + 2):
            image.put("#ffffff", (x, 14))
        for y in (5, 6):
            image.put("#ffffff", (center_x, y))
            image.put("#ffffff", (center_x - 1, y))
        return image

    def _info_button(self, parent: tk.Misc, command) -> tk.Button:
        if not hasattr(self, "info_icon_image"):
            self.info_icon_image = self._create_info_icon()
        background = ttk.Style(self).lookup("TFrame", "background") or "#f0f0f0"
        button = tk.Button(
            parent,
            image=self.info_icon_image,
            command=command,
            background=background,
            activebackground=background,
            relief=tk.FLAT,
            overrelief=tk.FLAT,
            borderwidth=0,
            highlightthickness=0,
            takefocus=0,
            cursor="hand2",
            padx=0,
            pady=0,
        )
        button.bind("<ButtonRelease-1>", lambda _event: self.after_idle(self.focus_set), add="+")
        return button

    def _open_weather_source(self, _event: tk.Event | None = None) -> None:
        webbrowser.open(self.weather_source_url)

    def _resize_system_parameters_content(self, event: tk.Event) -> None:
        self.system_parameters_canvas.itemconfigure(self.system_parameters_canvas_window, width=event.width)

    def _resize_import_content(self, event: tk.Event) -> None:
        self.import_canvas.itemconfigure(self.import_canvas_window, width=event.width)

    def _resize_multi_site_content(self, event: tk.Event) -> None:
        self.multi_site_canvas.itemconfigure(
            self.multi_site_canvas_window, width=event.width
        )

    def _update_multi_site_scroll_region(
        self, _event: tk.Event | None = None
    ) -> None:
        self.multi_site_canvas.configure(
            scrollregion=self.multi_site_canvas.bbox("all")
        )

    def _scroll_import_mousewheel(self, event: tk.Event) -> str | None:
        if self.notebook.select() != str(self.import_tab):
            return None
        if self.rainwater_data_notebook.select() != str(self.daily_rainwater_tab):
            return None
        pointer_x, pointer_y = self.winfo_pointerxy()
        if hasattr(self, "station_map") and self.station_map.winfo_exists():
            map_x = self.station_map.winfo_rootx()
            map_y = self.station_map.winfo_rooty()
            if (
                map_x <= pointer_x < map_x + self.station_map.winfo_width()
                and map_y <= pointer_y < map_y + self.station_map.winfo_height()
            ):
                return None
        canvas_x = self.import_canvas.winfo_rootx()
        canvas_y = self.import_canvas.winfo_rooty()
        if not (
            canvas_x <= pointer_x < canvas_x + self.import_canvas.winfo_width()
            and canvas_y <= pointer_y < canvas_y + self.import_canvas.winfo_height()
        ):
            return None
        if getattr(event, "num", None) == 4:
            direction = -1
        elif getattr(event, "num", None) == 5:
            direction = 1
        else:
            direction = -1 if event.delta > 0 else 1
        self.import_canvas.yview_scroll(direction, "units")
        return "break"

    def _scroll_multi_site_mousewheel(self, event: tk.Event) -> str | None:
        if self.notebook.select() != str(self.import_tab):
            return None
        if self.rainwater_data_notebook.select() != str(self.multi_site_rainwater_tab):
            return None
        pointer_x, pointer_y = self.winfo_pointerxy()
        independently_scrollable = (
            self.climate_normal_map,
            self.climate_normal_state_list,
            self.climate_normal_station_list,
            self.climate_normal_tree,
        )
        for widget in independently_scrollable:
            widget_x = widget.winfo_rootx()
            widget_y = widget.winfo_rooty()
            if (
                widget_x <= pointer_x < widget_x + widget.winfo_width()
                and widget_y <= pointer_y < widget_y + widget.winfo_height()
            ):
                return None
        canvas_x = self.multi_site_canvas.winfo_rootx()
        canvas_y = self.multi_site_canvas.winfo_rooty()
        if not (
            canvas_x <= pointer_x < canvas_x + self.multi_site_canvas.winfo_width()
            and canvas_y <= pointer_y < canvas_y + self.multi_site_canvas.winfo_height()
        ):
            return None
        if getattr(event, "num", None) == 4:
            direction = -1
        elif getattr(event, "num", None) == 5:
            direction = 1
        else:
            direction = -1 if event.delta > 0 else 1
        self.multi_site_canvas.yview_scroll(direction, "units")
        return "break"

    def _scroll_system_parameters_mousewheel(self, event: tk.Event) -> str | None:
        if not hasattr(self, "system_builder_scroll_canvas"):
            return None
        if self.notebook.select() != str(self.system_parameters_tab):
            return None
        if self.system_parameters_notebook.select() != str(self.system_builder_page):
            return None
        pointer_x, pointer_y = self.winfo_pointerxy()
        builder_canvas = self.system_builder_canvas
        builder_x, builder_y = builder_canvas.winfo_rootx(), builder_canvas.winfo_rooty()
        over_builder_canvas = (
            builder_x <= pointer_x < builder_x + builder_canvas.winfo_width()
            and builder_y <= pointer_y < builder_y + builder_canvas.winfo_height()
        )
        if over_builder_canvas and (int(getattr(event, "state", 0)) & 0x0001):
            if getattr(event, "num", None) == 4:
                zoom_delta = 0.1
            elif getattr(event, "num", None) == 5:
                zoom_delta = -0.1
            else:
                zoom_delta = 0.1 if event.delta > 0 else -0.1
            self._change_system_builder_zoom(zoom_delta)
            self.status_var.set(f"System builder zoom: {self.system_builder_zoom_var.get()}")
            return "break"
        canvas = self.system_builder_scroll_canvas
        canvas_x, canvas_y = canvas.winfo_rootx(), canvas.winfo_rooty()
        if not (
            canvas_x <= pointer_x < canvas_x + canvas.winfo_width()
            and canvas_y <= pointer_y < canvas_y + canvas.winfo_height()
        ):
            return None
        if getattr(event, "num", None) == 4:
            direction = -1
        elif getattr(event, "num", None) == 5:
            direction = 1
        else:
            direction = -1 if event.delta > 0 else 1
        canvas.yview_scroll(direction, "units")
        return "break"

    def _resize_system_builder_scroll_content(self, event: tk.Event) -> None:
        requested_width = self.system_builder_scroll_content.winfo_reqwidth()
        self.system_builder_scroll_canvas.itemconfigure(
            self.system_builder_scroll_window, width=max(event.width, requested_width)
        )

    def _update_system_builder_scroll_region(self, _event: tk.Event | None = None) -> None:
        if hasattr(self, "system_builder_scroll_content"):
            content_width = max(
                self.system_builder_scroll_canvas.winfo_width(),
                self.system_builder_scroll_content.winfo_reqwidth(),
            )
            self.system_builder_scroll_canvas.itemconfigure(
                self.system_builder_scroll_window, width=content_width
            )
        self.system_builder_scroll_canvas.configure(
            scrollregion=self.system_builder_scroll_canvas.bbox("all")
        )

    def _build_system_parameters_tab(self) -> None:
        self.system_parameters_tab.columnconfigure(0, weight=1)
        self.system_parameters_tab.rowconfigure(0, weight=1)
        self.system_parameters_notebook = ttk.Notebook(self.system_parameters_tab)
        self.system_parameters_notebook.grid(row=0, column=0, sticky="nsew")
        system_builder_page = ttk.Frame(self.system_parameters_notebook)
        system_animation_page = ttk.Frame(self.system_parameters_notebook)
        system_builder_page.columnconfigure(0, weight=1)
        system_builder_page.rowconfigure(0, weight=1)
        self.system_parameters_notebook.add(system_builder_page, text="Builder")
        self.system_parameters_notebook.add(system_animation_page, text="Animation")
        self.system_builder_page = system_builder_page
        self.system_animation_page = system_animation_page
        self.system_builder_scroll_canvas = tk.Canvas(
            system_builder_page, highlightthickness=0, borderwidth=0
        )
        self.system_builder_scroll_canvas.grid(row=0, column=0, sticky="nsew")
        system_builder_scrollbar = ttk.Scrollbar(
            system_builder_page, orient="vertical",
            command=self.system_builder_scroll_canvas.yview,
        )
        system_builder_scrollbar.grid(row=0, column=1, sticky="ns")
        system_builder_horizontal_scrollbar = ttk.Scrollbar(
            system_builder_page, orient="horizontal",
            command=self.system_builder_scroll_canvas.xview,
        )
        system_builder_horizontal_scrollbar.grid(row=1, column=0, sticky="ew")
        self.system_builder_scroll_canvas.configure(
            xscrollcommand=system_builder_horizontal_scrollbar.set,
            yscrollcommand=system_builder_scrollbar.set,
        )
        system_builder_content = ttk.Frame(self.system_builder_scroll_canvas)
        self.system_builder_scroll_content = system_builder_content
        self.system_builder_scroll_window = self.system_builder_scroll_canvas.create_window(
            (0, 0), window=system_builder_content, anchor="nw"
        )
        system_builder_content.columnconfigure(0, weight=1)
        system_builder_content.bind("<Configure>", self._update_system_builder_scroll_region)
        self.system_builder_scroll_canvas.bind(
            "<Configure>", self._resize_system_builder_scroll_content
        )
        self.bind_all("<MouseWheel>", self._scroll_system_parameters_mousewheel, add="+")
        self.bind_all("<Button-4>", self._scroll_system_parameters_mousewheel, add="+")
        self.bind_all("<Button-5>", self._scroll_system_parameters_mousewheel, add="+")
        self.indirect_system_diagram_frame = ttk.LabelFrame(
            system_builder_content, text="System builder", padding=10
        )
        self.indirect_system_diagram_frame.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        self.indirect_system_diagram_frame.columnconfigure(0, weight=1)
        self.system_builder_zoom = 1.0
        self.system_builder_pan_x = 0.0
        self.system_builder_pan_y = 0.0
        self.system_builder_pan_state: tuple[float, float, float, float] | None = None
        self.system_builder_zoom_var = tk.StringVar(value="100%")
        self.system_builder_view_var = tk.StringVar(value="icon-graph")
        canvas_column = ttk.Frame(self.indirect_system_diagram_frame)
        canvas_column.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        canvas_column.columnconfigure(0, weight=1)
        canvas_column.rowconfigure(1, weight=1)
        zoom_bar = ttk.Frame(canvas_column)
        zoom_bar.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        ttk.Button(
            zoom_bar, text="Zoom out 10%", command=lambda: self._change_system_builder_zoom(-0.1)
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(zoom_bar, textvariable=self.system_builder_zoom_var, width=6, anchor="center").grid(
            row=0, column=1, padx=6
        )
        ttk.Button(
            zoom_bar, text="Zoom in 10%", command=lambda: self._change_system_builder_zoom(0.1)
        ).grid(row=0, column=2, sticky="w")
        view_switch = ttk.Frame(zoom_bar)
        view_switch.grid(row=0, column=3, sticky="w", padx=(14, 0))
        ttk.Radiobutton(
            view_switch,
            text="Block graph",
            value="block-graph",
            variable=self.system_builder_view_var,
            command=self._system_builder_view_changed,
        ).grid(row=0, column=0, sticky="w")
        ttk.Radiobutton(
            view_switch,
            text="Icon graph",
            value="icon-graph",
            variable=self.system_builder_view_var,
            command=self._system_builder_view_changed,
        ).grid(row=0, column=1, sticky="w", padx=(8, 0))
        ttk.Label(
            zoom_bar, text="Shift+wheel: zoom  |  Middle-drag: pan", foreground="#667278"
        ).grid(row=0, column=4, sticky="w", padx=(12, 0))
        self.system_builder_canvas = tk.Canvas(
            canvas_column,
            width=760,
            height=420,
            background="white",
            highlightthickness=1,
            highlightbackground="#b7b7b7",
        )
        self.system_builder_canvas.grid(row=1, column=0, sticky="nsew")
        self.system_builder_canvas.bind("<ButtonPress-1>", self._system_canvas_press)
        self.system_builder_canvas.bind("<B1-Motion>", self._system_canvas_drag)
        self.system_builder_canvas.bind("<ButtonRelease-1>", self._system_canvas_release)
        self.system_builder_canvas.bind("<ButtonPress-2>", self._system_canvas_pan_start)
        self.system_builder_canvas.bind("<B2-Motion>", self._system_canvas_pan_drag)
        self.system_builder_canvas.bind("<ButtonRelease-2>", self._system_canvas_pan_end)
        self.system_builder_canvas.bind("<Configure>", self._system_builder_canvas_resized)
        self.system_builder_canvas.bind("<Button-3>", self._system_node_context_menu)
        self.system_builder_canvas.bind("<Delete>", lambda _event: self.delete_selected_system_component())
        self.system_builder_canvas.bind("<Escape>", self._cancel_system_link)
        self.system_builder_side_tabs = ttk.Notebook(self.indirect_system_diagram_frame)
        self.system_builder_side_tabs.grid(row=0, column=1, sticky="nsew")
        system_library = ttk.Frame(self.system_builder_side_tabs, padding=8)
        system_templates = ttk.Frame(self.system_builder_side_tabs, padding=8)
        system_edit = ttk.Frame(self.system_builder_side_tabs, padding=8)
        system_geometry = ttk.Frame(self.system_builder_side_tabs, padding=8)
        self.system_component_edit_tab = system_edit
        self.system_builder_side_tabs.add(system_library, text="System object library")
        self.system_builder_side_tabs.add(system_templates, text="System templates")
        self.system_builder_side_tabs.add(system_edit, text="Edit")
        self.system_builder_side_tabs.add(system_geometry, text="Geometry")
        system_library.columnconfigure(0, weight=1)
        system_library.rowconfigure(0, weight=1)
        self.system_component_library = ttk.Treeview(system_library, show="tree", height=15, selectmode="browse")
        self.system_component_library.grid(row=0, column=0, sticky="nsew")
        for component_type, label in self._system_component_templates().items():
            self.system_component_library.insert("", "end", iid=component_type, text=label)
        self.system_component_library.bind("<Double-1>", self._add_system_library_component_from_event)
        self.system_component_library.bind("<Return>", self._add_system_library_component_from_event)
        self.system_component_library.bind("<ButtonPress-1>", self._system_library_drag_start)
        self.system_component_library.bind("<ButtonRelease-1>", self._system_library_drop)
        ttk.Button(system_library, text="Add selected", command=self.add_selected_system_component).grid(
            row=1, column=0, sticky="ew", pady=(8, 0)
        )
        ttk.Button(system_library, text="Delete selected", command=self.delete_selected_system_component).grid(
            row=2, column=0, sticky="ew", pady=(6, 0)
        )
        system_templates.columnconfigure(0, weight=1)
        system_templates.rowconfigure(1, weight=1)
        ttk.Label(
            system_templates,
            text="Apply a built-in design or save the current canvas for later use.",
            foreground="#667278",
            wraplength=230,
        ).grid(row=0, column=0, sticky="ew", pady=(0, 10))
        self.system_template_library = ttk.Treeview(
            system_templates, show="tree", height=10, selectmode="browse"
        )
        self.system_template_library.grid(row=1, column=0, sticky="nsew")
        self.system_template_library.bind("<Double-1>", self._apply_selected_system_template_event)
        self.system_template_library.bind("<Return>", self._apply_selected_system_template_event)
        ttk.Button(
            system_templates, text="Apply selected", command=self.apply_selected_system_template
        ).grid(row=2, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(
            system_templates, text="Save current as custom", command=self.save_custom_system_template
        ).grid(row=3, column=0, sticky="ew", pady=(6, 0))
        custom_actions = ttk.Frame(system_templates)
        custom_actions.grid(row=4, column=0, sticky="ew", pady=(6, 0))
        custom_actions.columnconfigure((0, 1), weight=1)
        ttk.Button(
            custom_actions, text="Rename", command=self.rename_custom_system_template
        ).grid(row=0, column=0, sticky="ew", padx=(0, 3))
        ttk.Button(
            custom_actions, text="Delete", command=self.delete_custom_system_template
        ).grid(row=0, column=1, sticky="ew", padx=(3, 0))
        ttk.Label(
            system_templates,
            text="Applying a template replaces the objects and links currently on the canvas.",
            foreground="#667278",
            wraplength=230,
        ).grid(row=5, column=0, sticky="ew", pady=(10, 0))
        self._refresh_system_template_library()
        system_geometry.columnconfigure(0, weight=1)
        ttk.Checkbutton(
            system_geometry,
            text="Select multiple objects",
            variable=self.system_multi_select_var,
            command=self._system_multi_select_changed,
        ).grid(row=0, column=0, sticky="w")
        ttk.Button(
            system_geometry,
            text="Align selected horizontally",
            command=self.align_selected_system_objects_horizontally,
        ).grid(row=1, column=0, sticky="ew", pady=(10, 0))
        ttk.Button(
            system_geometry,
            text="Clear selection",
            command=self.clear_system_geometry_selection,
        ).grid(row=2, column=0, sticky="ew", pady=(6, 0))
        ttk.Label(
            system_geometry,
            textvariable=self.system_geometry_status_var,
            foreground="#667278",
            wraplength=230,
        ).grid(row=3, column=0, sticky="ew", pady=(10, 0))
        system_edit.columnconfigure(0, weight=1)
        self.system_component_edit_status_var = tk.StringVar(value="Select a system object to edit.")
        ttk.Label(
            system_edit,
            textvariable=self.system_component_edit_status_var,
            foreground="#667278",
            wraplength=220,
        ).grid(row=0, column=0, sticky="w")
        self.system_component_parameters_editor = ttk.LabelFrame(
            system_edit, text="Object parameters", padding=6
        )
        self.system_component_parameters_editor.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        self.system_component_parameters_editor.columnconfigure(1, weight=1)
        self.system_component_name_var = tk.StringVar()
        ttk.Label(self.system_component_parameters_editor, text="Name").grid(
            row=0, column=0, sticky="w", padx=(0, 8), pady=2
        )
        self.system_component_name_entry = ttk.Entry(
            self.system_component_parameters_editor, textvariable=self.system_component_name_var
        )
        self.system_component_name_entry.grid(row=0, column=1, sticky="ew", pady=2)
        self.system_component_name_entry.bind("<Return>", self._apply_system_component_name_from_event)
        self.system_component_parameter_vars: dict[str, tk.Variable] = {
            "selected_tank_size": tk.StringVar(),
            "initial_fill": tk.StringVar(),
            "reserve": tk.StringVar(),
            "graph_start": tk.StringVar(),
            "graph_end": tk.StringVar(),
            "graph_step": tk.StringVar(),
            "graph_auto_step_count": tk.StringVar(),
            "filtration_system_flow_gpm": tk.StringVar(),
            "filtration_system_count": tk.StringVar(),
            "transfer_pump_type": tk.StringVar(),
            "filter_recovery": tk.StringVar(),
            "booster_tank_size": tk.StringVar(),
            "booster_initial_fill": tk.StringVar(),
            "booster_refill_level": tk.StringVar(),
            "pump_capacity": tk.StringVar(),
            "municipal_backup_enabled": tk.BooleanVar(),
            "first_flush_sizing_method": self.first_flush_sizing_method_var,
            "first_flush_design_preset": self.first_flush_design_preset_var,
            "first_flush_antecedent": self.first_flush_antecedent_var,
            "first_flush_antecedent_unit": self.first_flush_antecedent_unit_var,
        }
        self.system_component_editor_loaded_id: str | None = None
        self.system_component_editor_baseline: dict[str, object] = {}
        self.system_component_editor_drafts: dict[str, dict[str, object]] = {}
        self.system_component_editor_loading = False
        self.system_component_graph_step_autosizing = False
        self.system_component_editor_model = self.config_model
        self.system_component_validation_var = tk.StringVar()
        self.apply_system_component_name_button = ttk.Button(
            self.system_component_parameters_editor,
            text="Apply changes",
            command=self.apply_system_component_name,
        )
        self.system_parameter_frames: dict[str, ttk.Frame] = {}
        editor_vars = self.system_component_parameter_vars
        parameter_specs = {
            "primary_tank": [
                ("Primary tank size", editor_vars["selected_tank_size"], self.tank_size_unit_var),
                ("Initial fill", editor_vars["initial_fill"], self.percent_unit_var),
                ("Minimum operating level", editor_vars["reserve"], self.reserve_unit_var),
                ("Graph start tank size", editor_vars["graph_start"], self.tank_size_unit_var),
                ("Graph end tank size", editor_vars["graph_end"], self.tank_size_unit_var),
                ("Graph step", editor_vars["graph_step"], self.tank_size_unit_var),
            ],
            "filtration_system": [
                ("Number in parallel", editor_vars["filtration_system_count"], None),
                ("Filter recovery", editor_vars["filter_recovery"], self.percent_unit_var),
            ],
            "booster_tank": [
                ("Tank size (0 = pass-through)", editor_vars["booster_tank_size"], self.tank_size_unit_var),
                ("Initial fill", editor_vars["booster_initial_fill"], self.percent_unit_var),
                ("Refill level", editor_vars["booster_refill_level"], self.percent_unit_var),
            ],
            "booster_pump": [
                ("Pump capacity (0 = unlimited)", editor_vars["pump_capacity"], self.pump_capacity_unit_var),
            ],
        }
        for component_type, specs in parameter_specs.items():
            frame = ttk.Frame(self.system_component_parameters_editor)
            frame.grid(row=1, column=0, columnspan=2, sticky="ew")
            frame.columnconfigure(1, weight=1)
            for row, (label, variable, unit_variable) in enumerate(specs):
                self._labeled_entry(frame, row, label, variable, unit_variable)
            if component_type == "primary_tank":
                ttk.Button(
                    frame, text="Auto graph step", command=self._auto_set_system_component_graph_step
                ).grid(
                    row=len(specs), column=0, columnspan=3, sticky="w", pady=(6, 0)
                )
                ttk.Label(frame, text="Number of steps").grid(
                    row=len(specs) + 1, column=0, sticky="w", pady=2
                )
                ttk.Spinbox(
                    frame, from_=1, to=1000, increment=1,
                    textvariable=editor_vars["graph_auto_step_count"], width=6,
                ).grid(row=len(specs) + 1, column=1, sticky="w", pady=2)
            self.system_parameter_frames[component_type] = frame
            frame.grid_remove()
        transfer_pump_frame = ttk.Frame(self.system_component_parameters_editor)
        transfer_pump_frame.grid(row=1, column=0, columnspan=2, sticky="ew")
        transfer_pump_frame.columnconfigure(1, weight=1)
        ttk.Label(transfer_pump_frame, text="Pump type").grid(row=0, column=0, sticky="w", pady=2)
        ttk.Combobox(
            transfer_pump_frame, textvariable=editor_vars["transfer_pump_type"],
            values=TRANSFER_PUMP_TYPES, state="readonly", width=14,
        ).grid(row=0, column=1, sticky="ew", pady=2)
        ttk.Label(transfer_pump_frame, text="Linked total flow").grid(row=1, column=0, sticky="w", pady=2)
        ttk.Label(
            transfer_pump_frame, textvariable=editor_vars["filtration_system_flow_gpm"]
        ).grid(row=1, column=1, sticky="w", pady=2)
        ttk.Label(transfer_pump_frame, text="GPM").grid(row=1, column=2, sticky="w", pady=2)
        self.system_parameter_frames["filtration_pump"] = transfer_pump_frame
        transfer_pump_frame.grid_remove()
        filtration_frame = self.system_parameter_frames["filtration_system"]
        for child in filtration_frame.grid_slaves():
            child.grid_configure(row=int(child.grid_info()["row"]) + 1)
        ttk.Label(filtration_frame, text="Nominal skid flow").grid(row=0, column=0, sticky="w", pady=2)
        ttk.Combobox(
            filtration_frame, textvariable=editor_vars["filtration_system_flow_gpm"],
            values=("Infinite", *(str(value) for value in FILTRATION_SYSTEM_FLOW_RATES_GPM)),
            state="readonly", width=8,
        ).grid(row=0, column=1, sticky="ew", pady=2)
        ttk.Label(filtration_frame, text="GPM").grid(row=0, column=2, sticky="w", pady=2)
        self.system_municipal_backup_editor = ttk.Frame(self.system_component_parameters_editor)
        self.system_municipal_backup_editor.grid(row=1, column=0, columnspan=2, sticky="ew")
        ttk.Checkbutton(
            self.system_municipal_backup_editor,
            text="Municipal backup enabled",
            variable=editor_vars["municipal_backup_enabled"],
        ).grid(row=0, column=0, sticky="w")
        self.system_municipal_backup_editor.grid_remove()
        first_flush_frame = ttk.Frame(self.system_component_parameters_editor)
        first_flush_frame.grid(row=1, column=0, columnspan=2, sticky="ew")
        first_flush_frame.columnconfigure(1, weight=1)
        self.first_flush_surface_selection_var = tk.StringVar()
        self.first_flush_surface_depth_var = tk.StringVar()
        self.first_flush_surface_depth_unit_var = tk.StringVar(
            value=precip_unit(self.config_model)
        )
        ttk.Label(first_flush_frame, text="Sizing method").grid(row=0, column=0, sticky="w", pady=2)
        first_flush_sizing_method_combo = ttk.Combobox(
            first_flush_frame,
            textvariable=self.first_flush_sizing_method_var,
            values=tuple(SIZING_METHOD_LABELS.values()),
            state="readonly",
        )
        first_flush_sizing_method_combo.grid(
            row=0, column=1, columnspan=2, sticky="ew", pady=2
        )
        first_flush_sizing_method_combo.bind(
            "<<ComboboxSelected>>", self._first_flush_guidance_changed
        )
        ttk.Label(first_flush_frame, text="Design preset").grid(row=1, column=0, sticky="w", pady=2)
        self.first_flush_design_preset_combo = ttk.Combobox(
            first_flush_frame,
            textvariable=self.first_flush_design_preset_var,
            values=tuple(DESIGN_PRESET_LABELS.values()),
            state="readonly",
        )
        self.first_flush_design_preset_combo.grid(row=1, column=1, columnspan=2, sticky="ew", pady=2)
        self.first_flush_design_preset_combo.bind(
            "<<ComboboxSelected>>", self._first_flush_guidance_changed
        )
        ttk.Label(first_flush_frame, text="Antecedent dry period").grid(
            row=2, column=0, sticky="w", pady=2
        )
        ttk.Entry(first_flush_frame, textvariable=self.first_flush_antecedent_var, width=9).grid(
            row=2, column=1, sticky="ew", pady=2
        )
        antecedent_combo = ttk.Combobox(
            first_flush_frame,
            textvariable=self.first_flush_antecedent_unit_var,
            values=("days", "hours"),
            state="readonly",
            width=7,
        )
        antecedent_combo.grid(row=2, column=2, sticky="w", pady=2)
        antecedent_combo.bind(
            "<<ComboboxSelected>>", self._first_flush_antecedent_unit_changed
        )
        ttk.Label(first_flush_frame, text="Collection surface").grid(
            row=3, column=0, sticky="w", pady=2
        )
        self.first_flush_surface_combo = ttk.Combobox(
            first_flush_frame,
            textvariable=self.first_flush_surface_selection_var,
            state="readonly",
        )
        self.first_flush_surface_combo.grid(
            row=3, column=1, columnspan=2, sticky="ew", pady=2
        )
        self.first_flush_surface_combo.bind(
            "<<ComboboxSelected>>", self._first_flush_surface_changed
        )
        ttk.Label(first_flush_frame, text="Diversion depth").grid(
            row=4, column=0, sticky="w", pady=2
        )
        ttk.Entry(
            first_flush_frame, textvariable=self.first_flush_surface_depth_var, width=9
        ).grid(row=4, column=1, sticky="ew", pady=2)
        ttk.Label(first_flush_frame, textvariable=self.first_flush_surface_depth_unit_var).grid(
            row=4, column=2, sticky="w", pady=2
        )
        ttk.Button(
            first_flush_frame,
            text="Apply surface depth",
            command=self._apply_first_flush_surface_depth,
        ).grid(row=5, column=0, columnspan=3, sticky="ew", pady=(4, 0))
        ttk.Label(
            first_flush_frame,
            textvariable=self.first_flush_guidance_summary_var,
            foreground="#667278",
            wraplength=220,
            justify="left",
        ).grid(row=6, column=0, columnspan=3, sticky="ew", pady=(5, 0))
        self.apply_first_flush_guidance_button = ttk.Button(
            first_flush_frame,
            text="Apply guided floor to surfaces",
            command=self._apply_first_flush_guidance,
        )
        self.apply_first_flush_guidance_button.grid(
            row=7, column=0, columnspan=3, sticky="ew", pady=(6, 0)
        )
        self.system_parameter_frames["first_flush_diversion"] = first_flush_frame
        first_flush_frame.grid_remove()
        ttk.Label(
            self.system_component_parameters_editor,
            textvariable=self.system_component_validation_var,
            style="Invalid.TLabel",
            wraplength=220,
            justify="left",
        ).grid(row=2, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        self.apply_system_component_name_button.grid(
            row=3, column=0, columnspan=2, sticky="e", pady=(8, 0)
        )
        self.system_end_uses_editor = ttk.LabelFrame(
            system_edit, text="Demand objects", padding=6
        )
        self.system_end_uses_editor.grid(row=2, column=0, sticky="nsew", pady=(10, 0))
        self.system_end_uses_editor.columnconfigure(0, weight=1)
        ttk.Label(
            self.system_end_uses_editor,
            text="Demand assignments apply immediately.",
            foreground="#667278",
            wraplength=220,
        ).grid(row=0, column=0, sticky="w", pady=(0, 6))
        ttk.Label(self.system_end_uses_editor, text="Available").grid(row=1, column=0, sticky="w")
        self.system_available_demands_list = tk.Listbox(
            self.system_end_uses_editor, height=4, exportselection=False
        )
        self.system_available_demands_list.grid(row=2, column=0, sticky="ew", pady=(2, 4))
        self.system_add_demand_button = ttk.Button(
            self.system_end_uses_editor,
            text="Add selected",
            command=self.add_demand_to_selected_end_uses,
        )
        self.system_add_demand_button.grid(row=3, column=0, sticky="ew")
        ttk.Label(self.system_end_uses_editor, text="Assigned").grid(row=4, column=0, sticky="w", pady=(8, 0))
        self.system_assigned_demands_list = tk.Listbox(
            self.system_end_uses_editor, height=4, exportselection=False
        )
        self.system_assigned_demands_list.grid(row=5, column=0, sticky="ew", pady=(2, 4))
        self.system_remove_demand_button = ttk.Button(
            self.system_end_uses_editor,
            text="Remove selected",
            command=self.remove_demand_from_selected_end_uses,
        )
        self.system_remove_demand_button.grid(row=6, column=0, sticky="ew")
        self.system_available_demands_list.bind(
            "<Double-1>", lambda _event: self.add_demand_to_selected_end_uses()
        )
        self.system_assigned_demands_list.bind(
            "<Double-1>", lambda _event: self.remove_demand_from_selected_end_uses()
        )
        for variable in (self.system_component_name_var, *editor_vars.values()):
            variable.trace_add("write", self._system_component_editor_field_changed)
        editor_vars["graph_step"].trace_add(
            "write", self._system_component_graph_step_changed
        )
        ttk.Label(
            self.indirect_system_diagram_frame,
            text=("Link objects by selecting either an output or input node, then the opposite node. "
                  "You can also drag between nodes. Select a link and press Delete to remove it."),
            foreground="#667278",
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(8, 0))
        ttk.Label(
            self.indirect_system_diagram_frame,
            text="The previous indirect-system schematic is preserved in assets/indirect_system.svg.",
            foreground="#667278",
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(3, 0))
        self.system_builder_warning_var = tk.StringVar()
        self.system_builder_warning_label = ttk.Label(
            self.indirect_system_diagram_frame,
            textvariable=self.system_builder_warning_var,
            style="Invalid.TLabel", wraplength=980, justify="left",
        )
        self.system_builder_warning_label.grid(
            row=3, column=0, columnspan=2, sticky="ew", pady=(8, 0)
        )
        self.system_builder_selected_id: str | None = None
        self.system_builder_selected_connection: dict[str, str] | None = None
        self.system_builder_pending_source: str | None = None
        self.system_builder_pending_source_port = "out"
        self.system_builder_pending_target: str | None = None
        self.system_builder_pending_target_port = "in"
        self.system_builder_port_drag: tuple[str, str] | None = None
        self.system_builder_hover_port: tuple[str, str] | None = None
        self.system_builder_drag_offset = (0.0, 0.0)
        self.system_library_drag_type: str | None = None
        self._build_system_animation_tab(system_animation_page)
        self._refresh_system_component_editor()
        self._render_system_builder()

    @staticmethod
    def _system_component_templates() -> dict[str, str]:
        return {
            "rainwater_input": "Rainwater input",
            "primary_tank": "Primary tank",
            "filtration_pump": "Transfer pump",
            "filtration_system": "Filtration system",
            "booster_tank": "Buffer tank",
            "booster_pump": "Booster pump",
            "municipal_backup": "Municipal water backup",
            "end_uses": "End-uses",
            "first_flush_diversion": "First-flush device",
            "overflow_pipe": "Overflow pipe",
        }

    def _new_system_component_id(self, component_type: str) -> str:
        existing = {str(item.get("id", "")) for item in self.config_model.system_layout}
        index = 1
        while f"{component_type}_{index}" in existing:
            index += 1
        return f"{component_type}_{index}"

    def _refresh_system_template_library(self, select_name: str | None = None) -> None:
        if not hasattr(self, "system_template_library"):
            return
        tree = self.system_template_library
        tree.delete(*tree.get_children())
        builtins = tree.insert("", "end", iid="template-builtins", text="Built-in templates", open=True)
        tree.insert(builtins, "end", iid="builtin:Direct system", text="Direct system")
        tree.insert(builtins, "end", iid="builtin:Indirect system", text="Indirect system")
        custom_root = tree.insert("", "end", iid="template-custom", text="Custom templates", open=True)
        self.system_custom_template_iids: dict[str, str] = {}
        for index, name in enumerate(self.store.list_system_templates()):
            iid = f"custom:{index}"
            self.system_custom_template_iids[iid] = name
            tree.insert(custom_root, "end", iid=iid, text=name)
            if name == select_name:
                tree.selection_set(iid)
                tree.focus(iid)

    def _selected_custom_system_template_name(self) -> str | None:
        selected = self.system_template_library.selection()
        if not selected:
            return None
        return self.system_custom_template_iids.get(selected[0])

    def _system_template_payload(self) -> dict[str, object]:
        self._apply_form_to_model()
        cfg = self.config_model
        return {
            "version": 1,
            "system_type": cfg.system_type,
            "system_layout": copy.deepcopy(cfg.system_layout),
            "system_connections": copy.deepcopy(cfg.system_connections),
            "system_parameters": asdict(cfg.system_parameters),
            "tank_parameters": asdict(cfg.tank_parameters),
            "selected_tank_size_gal": cfg.selected_tank_size_gal,
            "graph_start_gal": cfg.graph_start_gal,
            "graph_end_gal": cfg.graph_end_gal,
            "graph_step_gal": cfg.graph_step_gal,
            "first_flush_sizing_method": cfg.first_flush_sizing_method,
            "first_flush_design_preset": cfg.first_flush_design_preset,
            "first_flush_antecedent_dry_days": cfg.first_flush_antecedent_dry_days,
            "first_flush_antecedent_dry_unit": cfg.first_flush_antecedent_dry_unit,
        }

    def _create_media_control(
        self, parent: tk.Misc, icon: str, tooltip_text: str, command, *, primary: bool = False,
        icon_font_size: int = 15,
    ) -> tuple[tk.Canvas, int]:
        frame = ttk.Frame(parent)
        canvas = tk.Canvas(
            frame, width=46, height=46, highlightthickness=0,
            background=ttk.Style(self).lookup("TFrame", "background") or "#f0f0f0",
            cursor="hand2", takefocus=True,
        )
        canvas.grid(row=0, column=0)
        canvas_background = str(canvas.cget("background"))
        foreground = "#1565c0" if primary else "#263238"
        rounded_rectangle = canvas.create_polygon(
            12, 3, 34, 3, 43, 3, 43, 12,
            43, 34, 43, 43, 34, 43, 12, 43,
            3, 43, 3, 34, 3, 12, 3, 3, 12, 3,
            smooth=True, splinesteps=24,
            fill=canvas_background, outline=canvas_background, width=1,
        )
        text_item = canvas.create_text(
            23, 23, text=icon, fill=foreground,
            font=("Segoe UI Symbol", icon_font_size, "bold"),
        )
        icon_bounds = canvas.bbox(text_item)
        if icon_bounds is not None:
            icon_center_x = (icon_bounds[0] + icon_bounds[2]) / 2.0
            icon_center_y = (icon_bounds[1] + icon_bounds[3]) / 2.0
            canvas.move(text_item, 23.0 - icon_center_x, 23.0 - icon_center_y)
        canvas.bind("<Button-1>", lambda _event: command())
        canvas.bind("<Return>", lambda _event: command())
        canvas.bind("<space>", lambda _event: command())
        hover = "#e2e5e7"
        canvas.bind(
            "<Enter>",
            lambda _event: canvas.itemconfigure(
                rounded_rectangle, fill=hover, outline=hover
            ),
        )
        canvas.bind(
            "<Leave>",
            lambda _event: canvas.itemconfigure(
                rounded_rectangle, fill=canvas_background, outline=canvas_background
            ),
        )
        canvas.bind(
            "<FocusIn>",
            lambda _event: canvas.itemconfigure(
                rounded_rectangle, outline="#1565c0", width=2
            ),
        )
        canvas.bind(
            "<FocusOut>",
            lambda _event: canvas.itemconfigure(
                rounded_rectangle, outline=canvas_background, width=1
            ),
        )
        canvas._media_background = rounded_rectangle  # type: ignore[attr-defined]
        canvas._media_default_fill = canvas_background  # type: ignore[attr-defined]
        canvas._media_hover_fill = hover  # type: ignore[attr-defined]
        self._attach_media_control_tooltip(canvas, tooltip_text)
        return canvas, text_item

    @staticmethod
    def _set_media_control_icon(canvas: tk.Canvas, text_item: int, icon: str) -> None:
        canvas.itemconfigure(text_item, text="")
        RainwaterTkApp._draw_tabler_player_icon(
            canvas, "pause" if icon == "⏸" else "play", color="#1565c0"
        )

    @staticmethod
    def _draw_tabler_player_icon(
        canvas: tk.Canvas, icon: str, *, color: str = "#263238"
    ) -> None:
        """Draw the approved Tabler filled player icons on the 24px source grid."""
        canvas.delete("tabler-player-icon")
        scale, offset = 1.05, 10.4

        def point(px: float, py: float) -> tuple[float, float]:
            return offset + px * scale, offset + py * scale

        def polygon(values: tuple[float, ...]) -> None:
            coordinates: list[float] = []
            for index in range(0, len(values), 2):
                coordinates.extend(point(values[index], values[index + 1]))
            canvas.create_polygon(
                *coordinates, fill=color, outline=color, tags=("tabler-player-icon",)
            )

        if icon == "play":
            polygon((6, 4, 21, 12, 6, 20))
        elif icon == "pause":
            for left, right in ((5, 11), (13, 19)):
                x1, y1 = point(left, 4); x2, y2 = point(right, 20)
                canvas.create_rectangle(
                    x1, y1, x2, y2, fill=color, outline=color,
                    tags=("tabler-player-icon",),
                )
        elif icon in {"skip-back", "skip-forward"}:
            if icon == "skip-back":
                polygon((20, 4, 7, 12, 20, 20))
                x1, y1 = point(3, 4); x2, y2 = point(5, 20)
            else:
                polygon((4, 4, 17, 12, 4, 20))
                x1, y1 = point(19, 4); x2, y2 = point(21, 20)
            canvas.create_rectangle(
                x1, y1, x2, y2, fill=color, outline=color,
                tags=("tabler-player-icon",),
            )
        elif icon in {"track-prev", "track-next"}:
            if icon == "track-prev":
                polygon((21, 4, 12, 12, 21, 20))
                polygon((10, 4, 1, 12, 10, 20))
            else:
                polygon((3, 4, 12, 12, 3, 20))
                polygon((14, 4, 23, 12, 14, 20))

    def _attach_media_control_tooltip(self, canvas: tk.Canvas, text: str) -> None:
        canvas._media_tooltip_text = text  # type: ignore[attr-defined]
        canvas._media_tooltip_window = None  # type: ignore[attr-defined]
        canvas._media_tooltip_canvas = None  # type: ignore[attr-defined]
        canvas._media_tooltip_text_item = None  # type: ignore[attr-defined]
        canvas.bind("<Enter>", lambda _event: self._show_media_control_tooltip(canvas), add="+")
        canvas.bind("<Leave>", lambda _event: self._hide_media_control_tooltip(canvas), add="+")
        canvas.bind("<Destroy>", lambda _event: self._hide_media_control_tooltip(canvas), add="+")

    def _show_media_control_tooltip(self, canvas: tk.Canvas) -> None:
        self._hide_media_control_tooltip(canvas)
        tooltip = tk.Toplevel(self)
        tooltip.overrideredirect(True)
        tooltip.attributes("-topmost", True)
        transparent_color = "#ff00ff"
        tooltip.configure(background=transparent_color)
        try:
            tooltip.attributes("-transparentcolor", transparent_color)
        except tk.TclError:
            pass
        message = str(canvas._media_tooltip_text)  # type: ignore[attr-defined]
        tooltip_fill = "#d4d8da"
        tooltip_canvas = tk.Canvas(
            tooltip, width=82, height=28, highlightthickness=0,
            background=transparent_color,
        )
        tooltip_canvas.pack()
        tooltip_canvas.create_polygon(
            8, 1, 74, 1, 81, 8, 81, 20, 74, 27, 8, 27, 1, 20, 1, 8,
            smooth=True, splinesteps=24, fill=tooltip_fill, outline="#59666c",
        )
        text_item = tooltip_canvas.create_text(
            41, 14, text=message, fill="#17242b", font=("Segoe UI", 9)
        )
        tooltip.update_idletasks()
        x = canvas.winfo_rootx() + (canvas.winfo_width() - tooltip.winfo_reqwidth()) // 2
        y = canvas.winfo_rooty() - tooltip.winfo_reqheight() - 6
        tooltip.geometry(f"+{x}+{y}")
        canvas._media_tooltip_window = tooltip  # type: ignore[attr-defined]
        canvas._media_tooltip_canvas = tooltip_canvas  # type: ignore[attr-defined]
        canvas._media_tooltip_text_item = text_item  # type: ignore[attr-defined]

    @staticmethod
    def _hide_media_control_tooltip(canvas: tk.Canvas) -> None:
        tooltip = getattr(canvas, "_media_tooltip_window", None)
        if tooltip is not None:
            tooltip.destroy()
            canvas._media_tooltip_window = None  # type: ignore[attr-defined]
            canvas._media_tooltip_canvas = None  # type: ignore[attr-defined]
            canvas._media_tooltip_text_item = None  # type: ignore[attr-defined]

    @staticmethod
    def _set_media_control_tooltip(canvas: tk.Canvas, text: str) -> None:
        canvas._media_tooltip_text = text  # type: ignore[attr-defined]
        tooltip_canvas = getattr(canvas, "_media_tooltip_canvas", None)
        text_item = getattr(canvas, "_media_tooltip_text_item", None)
        if tooltip_canvas is not None and text_item is not None:
            tooltip_canvas.itemconfigure(text_item, text=text)

    def _build_system_animation_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)
        controls = ttk.Frame(parent, padding=8)
        controls.grid(row=0, column=0, sticky="ew")
        ttk.Label(controls, text="Simulation day").grid(row=0, column=0, sticky="w")
        self.system_animation_date_var = tk.StringVar()
        self.system_animation_date_combo = ttk.Combobox(
            controls, textvariable=self.system_animation_date_var,
            state="readonly", width=13,
        )
        self.system_animation_date_combo.grid(row=0, column=1, padx=(6, 10))
        ttk.Button(
            controls, text="Simulate day", command=self.simulate_system_animation_day
        ).grid(row=0, column=2, padx=(0, 12))
        self.system_animation_hour_var = tk.StringVar(value="Run a one-day simulation to begin.")
        ttk.Label(controls, textvariable=self.system_animation_hour_var).grid(
            row=0, column=3, sticky="w", padx=(10, 0)
        )
        player = ttk.LabelFrame(parent, text="Animation player", padding=(12, 8))
        player.grid(row=2, column=0, sticky="ew", padx=8, pady=(0, 8))
        player.columnconfigure(5, weight=1)
        transport = ttk.Frame(player)
        transport.grid(row=0, column=0, columnspan=7)
        previous_day, _previous_day_text = self._create_media_control(
            transport, "", "Previous day", lambda: self._step_system_animation_day(-1),
            icon_font_size=11,
        )
        self._draw_tabler_player_icon(previous_day, "skip-back")
        previous_day.master.grid(row=0, column=0, padx=0)
        previous_hour, _previous_hour_text = self._create_media_control(
            transport, "", "Previous hour", lambda: self._step_system_animation(-1),
            icon_font_size=11,
        )
        self._draw_tabler_player_icon(previous_hour, "track-prev")
        previous_hour.master.grid(row=0, column=1, padx=0)
        self.system_animation_play_button, self.system_animation_play_icon = self._create_media_control(
            transport, "", "Play (K)", self._toggle_system_animation, primary=True
        )
        self._draw_tabler_player_icon(
            self.system_animation_play_button, "play", color="#1565c0"
        )
        self.system_animation_play_button.master.grid(row=0, column=2, padx=0)
        next_hour, _next_hour_text = self._create_media_control(
            transport, "", "Next hour", lambda: self._step_system_animation(1),
            icon_font_size=11,
        )
        self._draw_tabler_player_icon(next_hour, "track-next")
        next_hour.master.grid(row=0, column=3, padx=0)
        next_day, _next_day_text = self._create_media_control(
            transport, "", "Next day", lambda: self._step_system_animation_day(1),
            icon_font_size=11,
        )
        self._draw_tabler_player_icon(next_day, "skip-forward")
        next_day.master.grid(row=0, column=4, padx=0)
        self.system_animation_seek_var = tk.DoubleVar(value=0.0)
        self.system_animation_seek = ttk.Scale(
            player, from_=0.0, to=23.0, variable=self.system_animation_seek_var,
            command=self._seek_system_animation_hour,
        )
        self.system_animation_seek.grid(row=1, column=0, columnspan=6, sticky="ew", pady=(10, 0))
        self.system_animation_progress_var = tk.StringVar(value="00:00 / 24:00")
        ttk.Label(player, textvariable=self.system_animation_progress_var, width=14, anchor="e").grid(
            row=1, column=6, padx=(10, 0), pady=(10, 0)
        )
        player_options = ttk.Frame(player)
        player_options.grid(row=2, column=0, columnspan=7, pady=(7, 0))
        self.system_animation_auto_next_day_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            player_options, text="Auto-play next day",
            variable=self.system_animation_auto_next_day_var,
        ).grid(row=0, column=0, sticky="w", padx=(0, 14))
        ttk.Label(player_options, text="After one hour").grid(
            row=0, column=1, sticky="e", padx=(0, 4)
        )
        self.system_animation_hour_end_var = tk.StringVar(value="Advance to next hour")
        ttk.Combobox(
            player_options, textvariable=self.system_animation_hour_end_var,
            values=("Advance to next hour", "Loop current hour"),
            state="readonly", width=20,
        ).grid(row=0, column=2, sticky="w")
        settings = ttk.LabelFrame(controls, text="Playback settings", padding=(10, 6))
        settings.grid(row=2, column=0, columnspan=9, sticky="ew", pady=(8, 0))
        ttk.Label(settings, text="Seconds per hour").grid(row=0, column=0, sticky="w")
        self.system_animation_seconds_per_hour_var = tk.StringVar(value="1.0")
        ttk.Spinbox(
            settings, from_=0.1, to=60.0, increment=0.1,
            textvariable=self.system_animation_seconds_per_hour_var, width=7,
        ).grid(row=0, column=1, sticky="w", padx=(6, 14))
        self.system_animation_auto_replay_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            settings, text="Repeat day",
            variable=self.system_animation_auto_replay_var,
        ).grid(row=0, column=2, sticky="w", padx=(0, 14))
        self.system_animation_show_pipe_flow_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            settings,
            text="Show instantaneous pipe flow",
            variable=self.system_animation_show_pipe_flow_var,
            command=self._draw_system_animation,
        ).grid(row=0, column=3, sticky="w")
        self.system_animation_canvas = tk.Canvas(
            parent, background="white", highlightthickness=1,
            highlightbackground="#b7b7b7", width=980, height=500,
        )
        self.system_animation_canvas.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))
        self.system_animation_canvas.bind("<Configure>", lambda _event: self._draw_system_animation())
        self.system_animation_canvas.bind("<ButtonPress-1>", self._system_animation_drag_start)
        self.system_animation_canvas.bind("<B1-Motion>", self._system_animation_drag_motion)
        self.system_animation_canvas.bind("<ButtonRelease-1>", self._system_animation_drag_end)
        self.bind_all("<KeyPress-k>", self._shortcut_toggle_system_animation, add="+")
        self.bind_all("<KeyPress-K>", self._shortcut_toggle_system_animation, add="+")
        self.system_animation_results = pd.DataFrame()
        self.system_animation_hour = 0
        self.system_animation_phase = 0.0
        self.system_animation_frame = 0
        self.system_animation_playing = False
        self.system_animation_play_mode = "day"
        self.system_animation_after_id: str | None = None
        self.system_animation_drag_state: tuple[str, float, float, float, float, float] | None = None

    def _refresh_system_animation_dates(self) -> None:
        if not hasattr(self, "system_animation_date_combo"):
            return
        values = [pd.Timestamp(value).strftime("%Y-%m-%d") for value in self.rainfall_df.get("Date", [])]
        values = list(dict.fromkeys(values))
        self.system_animation_date_combo.configure(values=values)
        if values and self.system_animation_date_var.get() not in values:
            self.system_animation_date_var.set(values[0])
        elif not values:
            self.system_animation_date_var.set("")

    def simulate_system_animation_day(self) -> None:
        self._refresh_system_animation_dates()
        date_text = self.system_animation_date_var.get()
        if not date_text:
            messagebox.showinfo(APP_TITLE, "Import rainfall data before simulating a day.", parent=self)
            return
        self._apply_form_to_model()
        compiled_system = compile_builder_system(
            self.config_model.system_type,
            self.config_model.system_layout,
            self.config_model.system_connections,
        )
        warnings = self._refresh_system_builder_warnings()
        if compiled_system.uses_builder_graph and warnings:
            messagebox.showwarning(
                APP_TITLE,
                "Correct the system builder configuration before simulating animation:\n\n"
                + "\n".join(f"- {warning}" for warning in warnings[:6]),
                parent=self,
            )
            self.status_var.set("Animation simulation blocked by system builder warnings")
            return
        selected_date = pd.Timestamp(date_text).normalize()
        dates = pd.to_datetime(self.rainfall_df["Date"]).dt.normalize()
        selected_rainfall = self.rainfall_df.loc[dates == selected_date].head(1).copy()
        if selected_rainfall.empty:
            messagebox.showerror(APP_TITLE, "The selected rainfall day is unavailable.", parent=self)
            return
        try:
            current_signature = analysis_input_signature(
                self.config_model, self.rainfall_df
            )
            cached_dates = pd.to_datetime(
                self.hourly_results_df.get("Date", pd.Series(dtype="datetime64[ns]")),
                errors="coerce",
            )
            cached_day = self.hourly_results_df.loc[
                cached_dates.dt.normalize() == selected_date
            ].copy()
            cache_is_current = (
                self.config_model.analysis_input_signature == current_signature
                and len(cached_day) == 24
                and "PrimaryTankBeginningGallons" in cached_day.columns
                and "CumulativeOverflowGallons" in cached_day.columns
            )
            if cache_is_current:
                self.system_animation_results = cached_day.reset_index(drop=True)
            else:
                history = self.rainfall_df.loc[dates <= selected_date].copy()
                self.system_animation_results = simulate_hourly_tank(
                    self.config_model,
                    history,
                    float(self.config_model.selected_tank_size_gal),
                    result_start_date=selected_date,
                ).reset_index(drop=True)
        except (TypeError, ValueError) as exc:
            messagebox.showerror(APP_TITLE, f"Could not simulate the selected day:\n{exc}", parent=self)
            return
        self._stop_system_animation()
        self.system_animation_hour = 0
        self.system_animation_phase = 0.0
        self.system_animation_frame = 0
        self._draw_system_animation()
        self.status_var.set(f"Simulated system animation for {date_text}")

    def _toggle_system_animation(self) -> None:
        if self.system_animation_results.empty:
            self.simulate_system_animation_day()
            if self.system_animation_results.empty:
                return
        if self.system_animation_playing:
            self._stop_system_animation("Day animation paused")
        else:
            duration = self._system_animation_seconds_per_hour()
            self.system_animation_seconds_per_hour_var.set(f"{duration:.1f}")
            if self.system_animation_hour >= 23:
                self.system_animation_hour = 0
                self.system_animation_phase = 0.0
                self.system_animation_frame = 0
            self.system_animation_playing = True
            self.system_animation_play_mode = "day"
            self._set_media_control_icon(
                self.system_animation_play_button, self.system_animation_play_icon, "⏸"
            )
            self._set_media_control_tooltip(
                self.system_animation_play_button, "Pause (K)"
            )
            self.status_var.set(
                f"Playing whole-day animation from hour {self.system_animation_hour:02d}:00"
            )
            self._animate_system_frame()

    def _shortcut_toggle_system_animation(self, event: tk.Event) -> str | None:
        """Use K as play/pause only while the system Animation sub-tab is visible."""
        if self.notebook.select() != str(self.system_parameters_tab):
            return None
        if self.system_parameters_notebook.select() != str(self.system_animation_page):
            return None
        if isinstance(
            event.widget,
            (tk.Entry, tk.Text, ttk.Entry, ttk.Spinbox, ttk.Combobox),
        ):
            return None
        self._toggle_system_animation()
        return "break"

    def _toggle_single_hour_animation(self) -> None:
        if self.system_animation_results.empty:
            self.simulate_system_animation_day()
            if self.system_animation_results.empty:
                return
        if self.system_animation_playing:
            self._stop_system_animation("One-hour animation paused")
            return
        duration = self._system_animation_seconds_per_hour()
        self.system_animation_seconds_per_hour_var.set(f"{duration:.1f}")
        self.system_animation_phase = 0.0
        self.system_animation_frame = 0
        self.system_animation_playing = True
        self.system_animation_play_mode = "hour"
        self._set_media_control_icon(
            self.system_animation_play_hour_button, self.system_animation_play_hour_icon, "⏸"
        )
        self.status_var.set(
            f"Playing animation for hour {self.system_animation_hour:02d}:00"
        )
        self._animate_system_frame()

    def _stop_system_animation(self, status_message: str | None = None) -> None:
        self.system_animation_playing = False
        if hasattr(self, "system_animation_play_button"):
            self._set_media_control_icon(
                self.system_animation_play_button, self.system_animation_play_icon, "▶"
            )
            self._set_media_control_tooltip(
                self.system_animation_play_button, "Play (K)"
            )
        if hasattr(self, "system_animation_play_hour_button"):
            self._set_media_control_icon(
                self.system_animation_play_hour_button, self.system_animation_play_hour_icon, "▶"
            )
        if self.system_animation_after_id is not None:
            self.after_cancel(self.system_animation_after_id)
            self.system_animation_after_id = None
        if status_message:
            self.status_var.set(status_message)

    def _stop_system_animation_playback(self) -> None:
        self._stop_system_animation("Animation stopped")
        self.system_animation_phase = 0.0
        self.system_animation_frame = 0
        self._draw_system_animation()

    def _step_system_animation(self, delta: int) -> None:
        if self.system_animation_results.empty:
            return
        self._stop_system_animation()
        self.system_animation_hour = min(max(self.system_animation_hour + delta, 0), 23)
        self.system_animation_phase = 0.0
        self.system_animation_frame = 0
        self._draw_system_animation()
        direction = "next" if delta > 0 else "previous"
        self.status_var.set(
            f"Selected {direction} animation hour: {self.system_animation_hour:02d}:00"
        )

    def _step_system_animation_day(self, delta: int) -> None:
        raw_values = self.system_animation_date_combo.cget("values")
        values = tuple(
            str(value) for value in (
                self.tk.splitlist(raw_values) if isinstance(raw_values, str) else raw_values
            )
        )
        target = self._adjacent_system_animation_date(
            values, self.system_animation_date_var.get(), delta
        )
        if target is None:
            direction = "previous" if delta < 0 else "next"
            self.status_var.set(f"No {direction} simulation day is available")
            return
        self.system_animation_date_var.set(target)
        self.simulate_system_animation_day()
        if not self.system_animation_results.empty:
            direction = "previous" if delta < 0 else "next"
            self.status_var.set(f"Simulated {direction} day: {target}")

    def _seek_system_animation_hour(self, value: str) -> None:
        if self.system_animation_results.empty:
            return
        selected_hour = min(max(int(round(float(value))), 0), 23)
        if selected_hour == self.system_animation_hour and self.system_animation_playing:
            return
        self._stop_system_animation()
        self.system_animation_hour = selected_hour
        self.system_animation_phase = 0.0
        self.system_animation_frame = 0
        self._draw_system_animation()
        self.status_var.set(f"Sought animation to hour {selected_hour:02d}:00")

    def _animate_system_frame(self) -> None:
        if not self.system_animation_playing:
            return
        self.system_animation_after_id = None
        self.system_animation_phase = (
            self.system_animation_phase
            + SYSTEM_ANIMATION_CYCLES_PER_SECOND * SYSTEM_ANIMATION_FRAME_MS / 1000.0
        ) % 1.0
        self.system_animation_frame += 1
        frames_per_hour = self._system_animation_frames_per_hour(
            self._system_animation_seconds_per_hour()
        )
        if self.system_animation_frame >= frames_per_hour:
            self.system_animation_frame = 0
            if self.system_animation_play_mode == "hour":
                next_hour, should_stop = self._single_hour_animation_completion(
                    self.system_animation_hour, self.system_animation_hour_end_var.get()
                )
                self.system_animation_hour = next_hour
                if not should_stop:
                    self.system_animation_phase = 0.0
                else:
                    self._stop_system_animation(
                        f"One-hour animation completed; selected hour "
                        f"{self.system_animation_hour:02d}:00"
                    )
            elif self.system_animation_hour >= 23:
                advanced_day = (
                    self.system_animation_auto_next_day_var.get()
                    and self._auto_play_next_system_animation_day()
                )
                if advanced_day:
                    pass
                elif self.system_animation_auto_replay_var.get():
                    self.system_animation_hour = 0
                    self.system_animation_phase = 0.0
                else:
                    self._stop_system_animation("Whole-day animation completed")
            else:
                self.system_animation_hour += 1
        self._draw_system_animation()
        if self.system_animation_playing:
            self.system_animation_after_id = self.after(
                SYSTEM_ANIMATION_FRAME_MS, self._animate_system_frame
            )

    @staticmethod
    def _adjacent_system_animation_date(
        values: list[str] | tuple[str, ...], current: str, delta: int
    ) -> str | None:
        if not values:
            return None
        try:
            index = list(values).index(current)
        except ValueError:
            return values[0]
        target_index = index + (-1 if delta < 0 else 1)
        if 0 <= target_index < len(values):
            return values[target_index]
        return None

    @staticmethod
    def _next_system_animation_date(
        values: list[str] | tuple[str, ...], current: str
    ) -> str | None:
        return RainwaterTkApp._adjacent_system_animation_date(values, current, 1)

    def _auto_play_next_system_animation_day(self) -> bool:
        raw_values = self.system_animation_date_combo.cget("values")
        values = tuple(
            str(value) for value in (
                self.tk.splitlist(raw_values) if isinstance(raw_values, str) else raw_values
            )
        )
        next_date = self._next_system_animation_date(
            values, self.system_animation_date_var.get()
        )
        if next_date is None:
            return False
        self.system_animation_date_var.set(next_date)
        self.simulate_system_animation_day()
        if self.system_animation_results.empty:
            return False
        self.system_animation_playing = True
        self.system_animation_play_mode = "day"
        self._set_media_control_icon(
            self.system_animation_play_button, self.system_animation_play_icon, "⏸"
        )
        self._set_media_control_tooltip(
            self.system_animation_play_button, "Pause (K)"
        )
        self.status_var.set(f"Auto-playing system animation for {next_date}")
        return True

    def _system_animation_seconds_per_hour(self) -> float:
        return self._bounded_system_animation_seconds(
            _float(self.system_animation_seconds_per_hour_var.get(), 1.0)
        )

    @staticmethod
    def _system_animation_drag_delta(
        screen_dx: float, screen_dy: float, scale: float
    ) -> tuple[float, float]:
        safe_scale = max(float(scale), 0.001)
        return float(screen_dx) / safe_scale, float(screen_dy) / safe_scale

    def _system_animation_drag_start(self, event: tk.Event) -> str | None:
        overlapping = self.system_animation_canvas.find_overlapping(
            event.x - 1, event.y - 1, event.x + 1, event.y + 1
        )
        component_id: str | None = None
        for canvas_item in reversed(overlapping):
            component_tag = next(
                (
                    tag for tag in self.system_animation_canvas.gettags(canvas_item)
                    if tag.startswith("animation-component:")
                ),
                None,
            )
            if component_tag:
                component_id = component_tag.split(":", 1)[1]
                break
        if component_id is None:
            return None
        item = self._system_layout_item(component_id)
        if item is None:
            return None
        self.system_animation_drag_state = (
            component_id, float(event.x), float(event.y),
            float(item.get("x", 0.0)), float(item.get("y", 0.0)),
            max(float(getattr(self, "system_animation_render_scale", 1.0)), 0.001),
        )
        self.system_animation_canvas.configure(cursor="fleur")
        return "break"

    def _system_animation_drag_motion(self, event: tk.Event) -> str | None:
        if self.system_animation_drag_state is None:
            return None
        component_id, start_x, start_y, original_x, original_y, scale = self.system_animation_drag_state
        item = self._system_layout_item(component_id)
        if item is None:
            return "break"
        dx, dy = self._system_animation_drag_delta(event.x - start_x, event.y - start_y, scale)
        proposed_x, proposed_y = original_x + dx, original_y + dy
        item_width = max(float(item.get("width", 124.0)), 80.0)
        item_height = max(float(item.get("height", 60.0)), 44.0)
        workspace_width, workspace_height = self._system_canvas_dimensions()
        proposed_x = min(max(proposed_x, item_width / 2.0 + 3.0), workspace_width - item_width / 2.0 - 3.0)
        proposed_y = min(max(proposed_y, item_height / 2.0 + 3.0), workspace_height - item_height / 2.0 - 3.0)
        if not self._system_position_overlaps(
            proposed_x, proposed_y, width=item_width, height=item_height,
            exclude_id=component_id,
        ):
            item["x"], item["y"] = proposed_x, proposed_y
            self._draw_system_animation()
        return "break"

    def _system_animation_drag_end(self, _event: tk.Event) -> str | None:
        if self.system_animation_drag_state is None:
            return None
        component_id = self.system_animation_drag_state[0]
        self.system_animation_drag_state = None
        self.system_animation_canvas.configure(cursor="")
        self._render_system_builder()
        self.status_var.set(f"Moved system object in animation view: {component_id}")
        return "break"

    @staticmethod
    def _bounded_system_animation_seconds(value: float) -> float:
        return min(max(float(value), 0.1), 60.0)

    @staticmethod
    def _system_animation_frames_per_hour(seconds_per_hour: float) -> int:
        bounded = RainwaterTkApp._bounded_system_animation_seconds(seconds_per_hour)
        return max(round(bounded * 1000.0 / SYSTEM_ANIMATION_FRAME_MS), 1)

    @staticmethod
    def _single_hour_animation_completion(hour: int, behavior: str) -> tuple[int, bool]:
        bounded_hour = min(max(int(hour), 0), 23)
        if behavior == "Loop current hour":
            return bounded_hour, False
        return min(bounded_hour + 1, 23), True

    @staticmethod
    def _system_animation_connection_active(
        source_type: str, target_type: str, row: pd.Series
    ) -> bool:
        if source_type == "rainwater_input":
            field = (
                "GrossCollectedGallons"
                if target_type == "first_flush_diversion"
                else "CollectedGallons"
            )
            return float(row.get(field, 0.0)) > 1e-9
        if source_type == "first_flush_diversion":
            return float(row.get("CollectedGallons", 0.0)) > 1e-9
        if source_type == "municipal_backup":
            return float(row.get("MainsMakeupGallons", 0.0)) > 1e-9
        if target_type == "overflow_pipe":
            return float(row.get("OverflowGallons", 0.0)) > 1e-9
        if source_type in {"primary_tank", "filtration_pump"}:
            return float(row.get("PumpFlowGallons", 0.0)) > 1e-9
        if source_type == "filtration_system":
            return float(row.get("FilterThroughputGallons", 0.0)) > 1e-9
        if source_type in {"booster_tank", "booster_pump"}:
            supplied = float(row.get("DemandGallons", 0.0)) - float(
                row.get("SystemUnmetDemandGallons", 0.0)
            )
            return supplied > 1e-9
        return False

    def _build_project_candidates_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        self.project_candidates_tree = ttk.Treeview(
            parent, columns=("state", "category", "product", "eligibility", "reason"),
            show="headings", height=5, selectmode="extended",
        )
        for column, label, width in (
            ("state", "Use", 75), ("category", "Category", 120), ("product", "Product", 150),
            ("eligibility", "Eligibility", 105), ("reason", "Reason / warning", 430),
        ):
            self.project_candidates_tree.heading(column, text=label)
            self.project_candidates_tree.column(column, width=width, anchor="w")
        self.project_candidates_tree.grid(row=0, column=0, sticky="ew")
        scroll = ttk.Scrollbar(parent, orient="vertical", command=self.project_candidates_tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.project_candidates_tree.configure(yscrollcommand=scroll.set)
        buttons = ttk.Frame(parent)
        buttons.grid(row=1, column=0, sticky="ew", pady=(5, 0))
        for label, state in (("Use as candidate", "Candidate"), ("Fix selection", "Fixed"), ("Exclude", "Excluded")):
            ttk.Button(buttons, text=label, command=lambda value=state: self._set_candidate_disposition(value)).pack(side="left", padx=(0, 6))
        ttk.Button(buttons, text="Remove from project", command=self._remove_project_candidates).pack(side="left", padx=(0, 6))
        ttk.Button(buttons, text="Edit project copy", command=self._load_candidate_into_editor).pack(side="left", padx=(0, 6))
        ttk.Button(buttons, text="Update from library", command=self._update_candidates_from_library).pack(side="left")
        ttk.Label(buttons, text="Project overrides remain after a library update.", foreground="#667278").pack(side="right")
        editor = ttk.Frame(parent)
        editor.grid(row=2, column=0, sticky="ew", pady=(5, 0))
        self.candidate_override_vars = {key: tk.StringVar() for key in ("model", "capacity", "installed_cost", "power_kw", "exclusion_reason")}
        for index, (key, label) in enumerate((
            ("model", "Project name"), ("capacity", "Capacity"),
            ("installed_cost", "Installed cost"), ("power_kw", "Power kW"),
        )):
            ttk.Label(editor, text=label).grid(row=0, column=index * 2, sticky="w", padx=(0 if index == 0 else 8, 3))
            ttk.Entry(editor, textvariable=self.candidate_override_vars[key], width=15).grid(row=0, column=index * 2 + 1, sticky="w")
        ttk.Button(editor, text="Save project override", command=self._save_candidate_override).grid(row=0, column=8, padx=(10, 0))
        ttk.Button(editor, text="Clear overrides", command=self._clear_candidate_overrides).grid(row=0, column=9, padx=(6, 0))
        ttk.Label(editor, text="Exclusion reason").grid(row=1, column=0, sticky="w", pady=(4, 0))
        ttk.Entry(editor, textvariable=self.candidate_override_vars["exclusion_reason"], width=55).grid(
            row=1, column=1, columnspan=5, sticky="ew", pady=(4, 0)
        )

    def _build_equipment_library_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        toolbar = ttk.Frame(parent)
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        ttk.Label(toolbar, text="Search").pack(side="left")
        search = ttk.Entry(toolbar, textvariable=self.equipment_library_search_var, width=24)
        search.pack(side="left", padx=(5, 10))
        search.bind("<KeyRelease>", lambda _event: self._refresh_equipment_library_tree())
        category = ttk.Combobox(
            toolbar, textvariable=self.equipment_library_category_var,
            values=("All categories", *EQUIPMENT_CATEGORIES), state="readonly", width=18,
        )
        category.pack(side="left")
        category.bind("<<ComboboxSelected>>", lambda _event: self._refresh_equipment_library_tree())
        ttk.Button(toolbar, text="Apply selected to project", command=self._apply_library_selection).pack(side="right")
        self.equipment_library_tree = ttk.Treeview(
            parent, columns=("category", "manufacturer", "model", "capacity", "cost"),
            show="headings", height=4, selectmode="extended",
        )
        for column, label, width in (
            ("category", "Category", 125), ("manufacturer", "Manufacturer", 130),
            ("model", "Model", 150), ("capacity", "Capacity", 100), ("cost", "Installed cost", 105),
        ):
            self.equipment_library_tree.heading(column, text=label)
            self.equipment_library_tree.column(column, width=width, anchor="w")
        self.equipment_library_tree.grid(row=1, column=0, sticky="ew")
        self.equipment_library_tree.bind("<<TreeviewSelect>>", lambda _event: self._load_library_editor())
        self.library_editor_vars = {key: tk.StringVar() for key in (
            "id", "category", "manufacturer", "model", "capacity", "installed_cost", "power_kw",
            "rated_flow_gpm", "pump_type", "minimum_flow_gpm", "maximum_flow_gpm",
            "voltage", "phase", "pressure_class",
            "connection_size", "length", "width", "height", "access_clearance", "tags",
            "required_companion_categories", "standards",
        )}
        editor = ttk.Frame(parent)
        editor.grid(row=2, column=0, sticky="ew", pady=(5, 0))
        fields = (
            ("id", "Stable ID"), ("category", "Category"), ("manufacturer", "Manufacturer"),
            ("model", "Model"), ("capacity", "Capacity"), ("installed_cost", "Cost"),
            ("power_kw", "Power kW"), ("rated_flow_gpm", "Rated flow GPM"),
            ("pump_type", "Pump type"), ("minimum_flow_gpm", "Min flow GPM"),
            ("maximum_flow_gpm", "Max flow GPM"), ("voltage", "Voltage"), ("phase", "Phase"),
            ("pressure_class", "Pressure class"), ("connection_size", "Connection size"),
            ("length", "Length (in)"), ("width", "Width (in)"), ("height", "Height (in)"),
            ("access_clearance", "Access clearance (in)"), ("tags", "Tags"),
            ("required_companion_categories", "Required companions"),
            ("standards", "Standards"),
        )
        for index, (key, label) in enumerate(fields):
            row, column = divmod(index, 7)
            ttk.Label(editor, text=label).grid(row=row * 2, column=column, sticky="w", padx=(0, 6))
            if key == "category":
                widget = ttk.Combobox(editor, textvariable=self.library_editor_vars[key], values=EQUIPMENT_CATEGORIES, state="readonly", width=15)
            else:
                widget = ttk.Entry(editor, textvariable=self.library_editor_vars[key], width=16)
            widget.grid(row=row * 2 + 1, column=column, sticky="w", padx=(0, 6))
        actions = ttk.Frame(parent)
        actions.grid(row=3, column=0, sticky="ew", pady=(5, 0))
        ttk.Button(actions, text="New product", command=self._new_library_product).pack(side="left", padx=(0, 6))
        ttk.Button(actions, text="Save product", command=self._save_library_product).pack(side="left", padx=(0, 6))
        ttk.Button(actions, text="Delete product", command=self._delete_library_product).pack(side="left", padx=(0, 6))
        ttk.Button(actions, text="Add/update starter products", command=self._update_shared_library).pack(side="left")

    def _build_equipment_constraints_tab(self, parent: ttk.Frame) -> None:
        ttk.Checkbutton(
            parent, text="Transfer-pump and filtration-system flows must match",
            variable=self.equipment_flow_compatibility_var, state="disabled",
        ).grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Checkbutton(
            parent,
            text="Require values for active constraints (otherwise missing values pass with a warning)",
            variable=self.equipment_require_values_var,
        ).grid(row=1, column=0, columnspan=4, sticky="w")
        fields = (
            ("approved_vendors", "Approved vendors (comma-separated)"),
            ("required_tags", "Required tags (comma-separated)"),
            ("required_standards", "Required standards (comma-separated)"),
            ("required_voltage", "Voltage"), ("required_phase", "Phase"),
            ("required_pressure_class", "Pressure class"),
            ("required_connection_size", "Connection size"),
            ("maximum_length", "Maximum length (in)"), ("maximum_width", "Maximum width (in)"),
            ("maximum_height", "Maximum height (in)"), ("maximum_footprint", "Maximum footprint (in²)"),
            ("minimum_access_clearance", "Minimum access clearance (in)"),
            ("project_standards", "Project standards / notes"),
        )
        for index, (key, label) in enumerate(fields):
            row, pair = divmod(index, 3)
            column = pair * 2
            ttk.Label(parent, text=label).grid(row=row + 2, column=column, sticky="w", padx=(0 if pair == 0 else 12, 4), pady=2)
            ttk.Entry(parent, textvariable=self.equipment_constraint_vars[key], width=24).grid(row=row + 2, column=column + 1, sticky="w", pady=2)
        ttk.Button(parent, text="Apply project constraints", command=self._apply_equipment_constraints).grid(
            row=7, column=0, sticky="w", pady=(6, 0)
        )

    def _build_compatibility_review_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        self.compatibility_summary_var = tk.StringVar(value="Compatibility has not been reviewed.")
        ttk.Label(parent, textvariable=self.compatibility_summary_var, foreground="#667278").grid(row=0, column=0, sticky="w", pady=(0, 4))
        self.compatibility_review_tree = ttk.Treeview(
            parent, columns=("scope", "items", "status", "reason"), show="headings", height=6,
        )
        for column, label, width in (
            ("scope", "Review", 100), ("items", "Equipment", 300),
            ("status", "Status", 95), ("reason", "Reason / warning", 450),
        ):
            self.compatibility_review_tree.heading(column, text=label)
            self.compatibility_review_tree.column(column, width=width, anchor="w")
        self.compatibility_review_tree.grid(row=1, column=0, sticky="ew")
        ttk.Button(parent, text="Refresh review", command=self._refresh_equipment_catalog_views).grid(row=2, column=0, sticky="w", pady=(5, 0))

    def _show_equipment_candidates(self) -> None:
        self.optimization_catalog_notebook.select(1)
        self._refresh_equipment_catalog_views()

    def _project_candidates(self) -> list[dict[str, object]]:
        settings = self.config_model.optimization_parameters
        if not settings.equipment_candidates:
            if settings.catalog:
                from rainwater_app.equipment_catalog import migrate_legacy_catalog
                settings.equipment_candidates = migrate_legacy_catalog(settings.catalog)
            else:
                settings.equipment_candidates = default_project_candidates(self.equipment_library)
        return settings.equipment_candidates

    def _selected_candidate_indices(self) -> list[int]:
        return [int(item) for item in self.project_candidates_tree.selection()]

    def _set_candidate_disposition(self, disposition: str) -> None:
        candidates = self._project_candidates()
        for index in self._selected_candidate_indices():
            if disposition == "Fixed":
                category = effective_candidate_product(candidates[index])["category"]
                for other_index, other in enumerate(candidates):
                    if other_index != index and effective_candidate_product(other)["category"] == category and other.get("disposition") == "Fixed":
                        other["disposition"] = "Candidate"
            candidates[index]["disposition"] = disposition
            if disposition != "Excluded":
                candidates[index]["exclusion_reason"] = ""
        self._refresh_equipment_catalog_views()

    def _remove_project_candidates(self) -> None:
        candidates = self._project_candidates()
        for index in sorted(self._selected_candidate_indices(), reverse=True):
            candidates.pop(index)
        self._refresh_equipment_catalog_views()

    def _load_candidate_into_editor(self) -> None:
        selected = self._selected_candidate_indices()
        if len(selected) != 1:
            return
        product = effective_candidate_product(self._project_candidates()[selected[0]])
        for key in ("model", "capacity", "installed_cost"):
            self.candidate_override_vars[key].set(str(product.get(key, "")))
        self.candidate_override_vars["power_kw"].set(str(product["properties"].get("power_kw", "")))
        self.candidate_override_vars["exclusion_reason"].set(
            str(self._project_candidates()[selected[0]].get("exclusion_reason", ""))
        )

    def _save_candidate_override(self) -> None:
        selected = self._selected_candidate_indices()
        if len(selected) != 1:
            messagebox.showinfo(APP_TITLE, "Select one project candidate to override.", parent=self)
            return
        try:
            overrides = {
                "model": self.candidate_override_vars["model"].get().strip(),
                "capacity": parse_number(self.candidate_override_vars["capacity"].get()),
                "installed_cost": parse_number(self.candidate_override_vars["installed_cost"].get()),
                "properties": {"power_kw": parse_number(self.candidate_override_vars["power_kw"].get() or 0)},
            }
            if not overrides["model"] or overrides["capacity"] <= 0 or overrides["installed_cost"] < 0:
                raise ValueError
        except ValueError:
            messagebox.showwarning(APP_TITLE, "Enter a name, positive capacity, non-negative cost and power.", parent=self)
            return
        self._project_candidates()[selected[0]]["project_overrides"] = overrides
        self._project_candidates()[selected[0]]["exclusion_reason"] = (
            self.candidate_override_vars["exclusion_reason"].get().strip()
        )
        self._refresh_equipment_catalog_views()

    def _clear_candidate_overrides(self) -> None:
        for index in self._selected_candidate_indices():
            self._project_candidates()[index]["project_overrides"] = {}
        self._refresh_equipment_catalog_views()

    def _update_candidates_from_library(self) -> None:
        by_id = {str(item["id"]): item for item in self.equipment_library}
        updated = 0
        for index in self._selected_candidate_indices():
            candidate = self._project_candidates()[index]
            product = by_id.get(str(candidate.get("product_id")))
            if product:
                self._project_candidates()[index] = update_candidate_snapshot(candidate, product)
                updated += 1
        self.optimization_status_var.set(f"Updated {updated} project snapshot(s); project overrides were preserved.")
        self._refresh_equipment_catalog_views()

    def _refresh_equipment_library_tree(self) -> None:
        if not hasattr(self, "equipment_library_tree"):
            return
        query = self.equipment_library_search_var.get().strip().casefold()
        category = self.equipment_library_category_var.get()
        self.equipment_library_tree.delete(*self.equipment_library_tree.get_children())
        for item in self.equipment_library:
            haystack = " ".join((str(item["manufacturer"]), str(item["model"]), str(item["category"]))).casefold()
            if query and query not in haystack:
                continue
            if category != "All categories" and item["category"] != category:
                continue
            self.equipment_library_tree.insert("", "end", iid=str(item["id"]), values=(
                item["category"], item["manufacturer"], item["model"], f"{float(item['capacity']):g}",
                format_number(float(item["installed_cost"]), self.config_model),
            ))

    def _load_library_editor(self) -> None:
        selection = self.equipment_library_tree.selection()
        if len(selection) != 1:
            return
        item = next(product for product in self.equipment_library if str(product["id"]) == selection[0])
        props, dimensions = item["properties"], item["dimensions"]
        values = {**item, **props, **dimensions}
        values["tags"] = ", ".join(item["tags"])
        values["standards"] = ", ".join(item["standards"])
        values["required_companion_categories"] = ", ".join(props.get("required_companion_categories", []))
        for key, variable in self.library_editor_vars.items():
            variable.set(_constraint_display_value(values.get(key)))

    def _new_library_product(self) -> None:
        for variable in self.library_editor_vars.values():
            variable.set("")
        self.library_editor_vars["category"].set(EQUIPMENT_CATEGORIES[0])

    @staticmethod
    def _optional_editor_number(value: str) -> float | None:
        return None if not value.strip() else float(value)

    def _library_product_from_editor(self) -> dict[str, object]:
        product_id = self.library_editor_vars["id"].get().strip()
        if not product_id:
            raise ValueError("Enter a stable product ID.")
        properties = {
            key: self._optional_editor_number(self.library_editor_vars[key].get())
            for key in ("power_kw", "rated_flow_gpm", "minimum_flow_gpm", "maximum_flow_gpm")
        }
        properties.update({key: self.library_editor_vars[key].get().strip() for key in (
            "pump_type", "voltage", "phase", "pressure_class", "connection_size",
        )})
        properties["required_companion_categories"] = [
            value.strip() for value in self.library_editor_vars["required_companion_categories"].get().split(",") if value.strip()
        ]
        dimensions = {
            key: self._optional_editor_number(self.library_editor_vars[key].get())
            for key in ("length", "width", "height", "access_clearance")
        }
        return normalize_product({
            "id": product_id, "category": self.library_editor_vars["category"].get(),
            "manufacturer": self.library_editor_vars["manufacturer"].get(),
            "model": self.library_editor_vars["model"].get(),
            "capacity": float(self.library_editor_vars["capacity"].get()),
            "installed_cost": float(self.library_editor_vars["installed_cost"].get()),
            "properties": {key: value for key, value in properties.items() if value not in (None, "")},
            "dimensions": {key: value for key, value in dimensions.items() if value is not None},
            "tags": [value.strip() for value in self.library_editor_vars["tags"].get().split(",") if value.strip()],
            "standards": [value.strip() for value in self.library_editor_vars["standards"].get().split(",") if value.strip()],
            "active": True,
        })

    def _save_library_product(self) -> None:
        try:
            product = self._library_product_from_editor()
            existing = next((index for index, item in enumerate(self.equipment_library) if item["id"] == product["id"]), None)
            proposed = list(self.equipment_library)
            if existing is None:
                proposed.append(product)
            else:
                proposed[existing] = product
            save_equipment_library(self.equipment_library_path, proposed)
        except (ValueError, OSError) as exc:
            messagebox.showwarning(APP_TITLE, str(exc), parent=self)
            return
        self.equipment_library = proposed
        self._refresh_equipment_library_tree()
        self.optimization_status_var.set("Shared equipment library saved. Project snapshots were not changed.")

    def _delete_library_product(self) -> None:
        selected = set(self.equipment_library_tree.selection())
        if not selected:
            return
        self.equipment_library = [item for item in self.equipment_library if str(item["id"]) not in selected]
        save_equipment_library(self.equipment_library_path, self.equipment_library)
        self._refresh_equipment_library_tree()
        self.optimization_status_var.set("Library product removed; existing project snapshots were retained.")

    def _update_shared_library(self) -> None:
        by_id = {str(item["id"]): item for item in self.equipment_library}
        added = 0
        updated = 0
        for product in built_in_equipment_library():
            if str(product["id"]) in by_id:
                index = self.equipment_library.index(by_id[str(product["id"])])
                self.equipment_library[index] = product
                updated += 1
            else:
                self.equipment_library.append(product)
                added += 1
        save_equipment_library(self.equipment_library_path, self.equipment_library)
        self._refresh_equipment_library_tree()
        self.optimization_status_var.set(f"Shared library updated: {added} added, {updated} starter products refreshed. Projects unchanged.")

    def _apply_library_selection(self) -> None:
        existing = {str(item.get("product_id")) for item in self._project_candidates()}
        by_id = {str(item["id"]): item for item in self.equipment_library}
        added = 0
        for product_id in self.equipment_library_tree.selection():
            if product_id not in existing:
                self._project_candidates().append(candidate_from_product(by_id[product_id]))
                added += 1
        self.optimization_status_var.set(f"Applied {added} library product(s) to this project.")
        self._refresh_equipment_catalog_views()

    def _apply_equipment_constraints(self) -> None:
        constraints = {
            "enforce_flow_compatibility": self.equipment_flow_compatibility_var.get(),
            "require_constraint_values": self.equipment_require_values_var.get(),
            "approved_vendors": [value.strip() for value in self.equipment_constraint_vars["approved_vendors"].get().split(",") if value.strip()],
            "required_tags": [value.strip() for value in self.equipment_constraint_vars["required_tags"].get().split(",") if value.strip()],
            "required_standards": [value.strip() for value in self.equipment_constraint_vars["required_standards"].get().split(",") if value.strip()],
        }
        for key in ("required_voltage", "required_phase", "required_pressure_class", "required_connection_size", "project_standards"):
            constraints[key] = self.equipment_constraint_vars[key].get().strip()
        try:
            for key in ("maximum_length", "maximum_width", "maximum_height", "maximum_footprint", "minimum_access_clearance"):
                constraints[key] = self._optional_editor_number(self.equipment_constraint_vars[key].get())
        except ValueError:
            messagebox.showwarning(APP_TITLE, "Dimensional constraints must be numeric or blank.", parent=self)
            return
        self.config_model.optimization_parameters.equipment_constraints = normalized_constraints(constraints)
        self._refresh_equipment_catalog_views()

    def _refresh_equipment_catalog_views(self) -> None:
        if not hasattr(self, "project_candidates_tree"):
            return
        candidates = self._project_candidates()
        constraints = self.config_model.optimization_parameters.equipment_constraints
        self.project_candidates_tree.delete(*self.project_candidates_tree.get_children())
        self.compatibility_review_tree.delete(*self.compatibility_review_tree.get_children())
        eligible_by_category: dict[str, list[dict[str, object]]] = {category: [] for category in EQUIPMENT_CATEGORIES}
        warnings = 0
        for index, candidate in enumerate(candidates):
            product = effective_candidate_product(candidate)
            disposition = str(candidate.get("disposition", "Candidate"))
            eligible, reasons = evaluate_product_eligibility(product, constraints)
            if disposition == "Excluded":
                status = "Excluded"
                reason = str(candidate.get("exclusion_reason") or "Excluded from this project")
            else:
                status = "Eligible" if eligible else "Ineligible"
                reason = "; ".join(reasons)
                if eligible:
                    eligible_by_category.setdefault(str(product["category"]), []).append(product)
            if reasons:
                warnings += 1
            self.project_candidates_tree.insert("", "end", iid=str(index), values=(
                disposition, product["category"], product["model"], status, reason,
            ))
            if reasons or not eligible:
                self.compatibility_review_tree.insert("", "end", values=(
                    "Product", product["model"], "Pass with warning" if eligible else "Ineligible", reason,
                ))
        fixed_categories = {
            str(effective_candidate_product(candidate)["category"])
            for candidate in candidates if candidate.get("disposition") == "Fixed"
        }
        for category in fixed_categories:
            fixed_ids = {
                str(candidate.get("product_id")) for candidate in candidates
                if candidate.get("disposition") == "Fixed"
            }
            eligible_by_category[category] = [
                product for product in eligible_by_category.get(category, [])
                if str(product["id"]) in fixed_ids
            ]
        combinations = list(itertools.product(*(eligible_by_category[category] for category in EQUIPMENT_CATEGORIES)))
        compatible = 0
        rejected = 0
        for combination in combinations:
            allowed, reasons = evaluate_combination_compatibility(combination, constraints)
            if allowed:
                compatible += 1
            else:
                rejected += 1
                self.compatibility_review_tree.insert("", "end", values=(
                    "Combination", " + ".join(str(item["model"]) for item in combination),
                    "Rejected", "; ".join(reasons),
                ))
        self.compatibility_summary_var.set(
            f"{len(candidates)} applied products · {compatible} compatible combinations · "
            f"{rejected} rejected combinations · {warnings} product warnings"
        )
        self._refresh_equipment_library_tree()

    @staticmethod
    def _system_animation_connection_flow_gallons(
        source_type: str, target_type: str, row: pd.Series
    ) -> float:
        """Return the volume crossing a builder connection during this hour."""
        if target_type == "overflow_pipe":
            return max(float(row.get("OverflowGallons", 0.0)), 0.0)
        if source_type == "rainwater_input":
            field = (
                "GrossCollectedGallons"
                if target_type == "first_flush_diversion"
                else "CollectedGallons"
            )
            return max(float(row.get(field, 0.0)), 0.0)
        if source_type == "first_flush_diversion":
            return max(float(row.get("CollectedGallons", 0.0)), 0.0)
        if source_type == "municipal_backup":
            return max(float(row.get("MainsMakeupGallons", 0.0)), 0.0)
        if source_type in {"primary_tank", "filtration_pump"}:
            return max(float(row.get("PumpFlowGallons", 0.0)), 0.0)
        if source_type == "filtration_system":
            return max(float(row.get("FilterThroughputGallons", 0.0)), 0.0)
        if source_type in {"booster_tank", "booster_pump"}:
            return max(
                float(row.get("DemandGallons", 0.0))
                - float(row.get("SystemUnmetDemandGallons", 0.0)),
                0.0,
            )
        return 0.0

    @staticmethod
    def _system_animation_pipe_flow_label(
        hourly_gallons: float, config: ProjectConfig
    ) -> str:
        flow = max(float(hourly_gallons), 0.0) / 60.0
        if is_metric(config):
            return f"{format_number(flow * LITERS_PER_GALLON, config, max_decimal_places=1)} LPM"
        return f"{format_number(flow, config, max_decimal_places=1)} GPM"

    @staticmethod
    def _system_animation_rain_active(row: pd.Series) -> bool:
        """Return whether collected rainwater enters the configured system this hour."""
        return float(row.get("CollectedGallons", 0.0)) > 1e-9

    def _load_system_weather_images(self) -> bool:
        """Load and retain the optional CC0 weather artwork for canvas animation."""
        if self.system_weather_assets_loaded:
            return bool(self.system_weather_images)
        self.system_weather_assets_loaded = True
        root = _resource_path("assets/third_party/weather")
        paths = {
            "sunny": root / "weather-icon-set" / "sunnyWeather.png",
        }
        paths.update(
            {
                f"rain_drop_{index}": root / "rain-drop-animation" / f"rain_drop_{index}.png"
                for index in range(5)
            }
        )
        try:
            loaded = {name: tk.PhotoImage(file=path) for name, path in paths.items()}
        except (tk.TclError, OSError):
            self.system_weather_images.clear()
            return False

        # The weather icons are 100 px square; halve them to fit inside a block.
        loaded["sunny"] = loaded["sunny"].subsample(2, 2)
        # Enlarge the 10 px particle frames enough to remain visible after packaging.
        for index in range(5):
            key = f"rain_drop_{index}"
            loaded[key] = loaded[key].zoom(2, 2)
        self.system_weather_images = loaded
        return True

    def _draw_weather_asset_animation(
        self, canvas: tk.Canvas, x: float, y: float, phase: float, raining: bool
    ) -> bool:
        """Draw cached weather assets, returning False when fallback art is needed."""
        if not self._load_system_weather_images():
            return False
        if not raining:
            canvas.create_image(x, y, image=self.system_weather_images["sunny"])
            return True

        frame = min(int((phase % 1.0) * 5.0), 4)
        particle = self.system_weather_images[f"rain_drop_{frame}"]
        # Three particles fill the block while remaining inside its 124 x 60 bounds.
        canvas.create_image(x - 30, y, image=particle)
        canvas.create_image(x, y, image=particle)
        canvas.create_image(x + 30, y, image=particle)
        return True

    def _system_animation_irrigation_active(
        self, item: dict[str, object], timestamp: pd.Timestamp
    ) -> bool:
        assigned = _normalized_demand_object_indices(
            item.get("demand_object_indices"),
            len(self.config_model.demand.demand_objects),
        )
        day_key = WEEKDAY_KEYS[timestamp.weekday()]
        for index in assigned:
            demand_object = self.config_model.demand.demand_objects[index]
            if demand_object.object_type.casefold() != "irrigation system":
                continue
            schedule = self.config_model.demand.hourly_schedule_library.get(
                demand_object.schedule_name
            )
            if schedule is None:
                continue
            if timestamp.month not in schedule_months_for(
                self.config_model.demand, demand_object.schedule_name
            ):
                continue
            values = schedule.get(day_key, [])
            if timestamp.hour < len(values) and float(values[timestamp.hour]) > 0.0:
                return True
        return False

    @staticmethod
    def _draw_pixel_irrigation_animation(
        canvas: tk.Canvas, x: float, y: float, width: float, height: float, phase: float
    ) -> None:
        """Draw a tiny original pixel-art gardener, hose, flower and water spray."""
        pixel = max(min(int(min(width / 34.0, height / 18.0)), 4), 1)
        scene_w, scene_h = 34 * pixel, 18 * pixel
        left, top = x - scene_w / 2.0, y - scene_h / 2.0
        def rect(px: int, py: int, pw: int, ph: int, color: str) -> None:
            canvas.create_rectangle(
                left + px * pixel, top + py * pixel,
                left + (px + pw) * pixel, top + (py + ph) * pixel,
                fill=color, outline="",
            )
        # Grass and flower.
        rect(0, 15, 34, 3, "#55a630")
        for blade in (1, 5, 9, 20, 24, 30):
            rect(blade, 13 + blade % 2, 1, 2, "#2f7d32")
        rect(27, 10, 1, 5, "#2f7d32")
        rect(25, 8, 2, 2, "#ff70a6"); rect(28, 8, 2, 2, "#ff70a6")
        rect(27, 7, 1, 1, "#ffd166"); rect(27, 9, 1, 1, "#ffd166")
        # Gardener: hat, head, shirt, trousers and boots.
        rect(5, 3, 6, 1, "#f4a261"); rect(7, 2, 4, 1, "#e76f51")
        rect(7, 4, 4, 4, "#f2c6a0"); rect(10, 5, 1, 1, "#263238")
        rect(6, 8, 6, 5, "#4361ee"); rect(6, 13, 2, 3, "#37474f")
        rect(10, 13, 2, 3, "#37474f"); rect(5, 16, 4, 1, "#6d4c41")
        rect(10, 16, 4, 1, "#6d4c41")
        # Arm, hose handle and a slightly wiggly green hose.
        rect(11, 9, 4, 2, "#f2c6a0"); rect(14, 10, 4, 1, "#455a64")
        hose_y = 13 + (1 if phase >= 0.5 else 0)
        rect(15, 12, 1, hose_y - 11, "#2d6a4f")
        rect(15, hose_y, 8, 1, "#2d6a4f"); rect(22, 12, 1, 2, "#2d6a4f")
        # Three looping droplets travel toward the flower.
        for index in range(3):
            progress = (phase + index / 3.0) % 1.0
            drop_x = 18 + int(progress * 8)
            arc = int(3.0 * (4.0 * progress * (1.0 - progress)))
            drop_y = 9 - arc + (index % 2)
            rect(drop_x, drop_y, 1, 1, "#29b6f6")

    @staticmethod
    def _draw_pixel_weather_animation(
        canvas: tk.Canvas, x: float, y: float, width: float, height: float,
        phase: float, raining: bool,
    ) -> None:
        """Draw an original animated pixel sun or drifting rain cloud."""
        pixel = max(min(int(min(width / 30.0, height / 16.0)), 4), 1)
        scene_w, scene_h = 30 * pixel, 16 * pixel
        left, top = x - scene_w / 2.0, y - scene_h / 2.0

        def rect(px: int, py: int, pw: int, ph: int, color: str) -> None:
            canvas.create_rectangle(
                left + px * pixel, top + py * pixel,
                left + (px + pw) * pixel, top + (py + ph) * pixel,
                fill=color, outline="",
            )

        if not raining:
            pulse = 1 if phase >= 0.5 else 0
            rect(12, 4, 6, 6, "#ffd43b"); rect(10, 6, 10, 2, "#ffd43b")
            ray_color = "#ffb703" if pulse else "#ffc300"
            for ray in (
                (14, 1 - pulse), (14, 12 + pulse),
                (7 - pulse, 6), (21 + pulse, 6),
                (9 - pulse, 2 - pulse), (19 + pulse, 2 - pulse),
                (9 - pulse, 10 + pulse), (19 + pulse, 10 + pulse),
            ):
                rect(ray[0], ray[1], 2, 2, ray_color)
            return

        cloud_shift = 1 if phase >= 0.5 else 0
        rect(5 + cloud_shift, 4, 20, 5, "#90a4ae")
        rect(8 + cloud_shift, 2, 7, 4, "#b0bec5")
        rect(15 + cloud_shift, 3, 7, 4, "#c5d0d5")
        rect(7 + cloud_shift, 8, 16, 2, "#78909c")
        rain_step = int(phase * 4.0) % 4
        for index, drop_x in enumerate((7, 12, 17, 22)):
            rect(drop_x, 10 + ((rain_step + index * 2) % 4), 1, 2, "#29b6f6")

    def _draw_system_animation(self) -> None:
        if not hasattr(self, "system_animation_canvas"):
            return
        canvas = self.system_animation_canvas
        canvas.delete("all")
        if self.system_animation_results.empty:
            if hasattr(self, "system_animation_seek_var"):
                self.system_animation_seek_var.set(0.0)
                self.system_animation_progress_var.set("00:00 / 24:00")
            canvas.create_text(
                max(canvas.winfo_width(), 300) / 2, max(canvas.winfo_height(), 200) / 2,
                text="Select a rainfall day and choose Simulate day.", fill="#667278",
                font=("Segoe UI", 12),
            )
            return
        hour = min(max(self.system_animation_hour, 0), len(self.system_animation_results) - 1)
        row = self.system_animation_results.iloc[hour]
        frames_per_hour = self._system_animation_frames_per_hour(
            self._system_animation_seconds_per_hour()
        )
        hour_progress = min(self.system_animation_frame / max(frames_per_hour, 1), 0.999)
        timeline_hour = hour + hour_progress
        self.system_animation_seek_var.set(timeline_hour)
        progress_minutes = min(int(timeline_hour * 60.0), 24 * 60)
        self.system_animation_progress_var.set(
            f"{progress_minutes // 60:02d}:{progress_minutes % 60:02d} / 24:00"
        )
        animation_timestamp = pd.Timestamp(row.get("Date"))
        displayed_rain = volume_to_display(float(row.get("CollectedGallons", 0.0)), self.config_model)
        displayed_demand = volume_to_display(float(row.get("DemandGallons", 0.0)), self.config_model)
        self.system_animation_hour_var.set(
            f"Hour {hour:02d}:00-{hour:02d}:59  |  "
            f"rain {format_number(displayed_rain, self.config_model, max_decimal_places=1)} {volume_unit(self.config_model)}  |  "
            f"demand {format_number(displayed_demand, self.config_model, max_decimal_places=1)} {volume_unit(self.config_model)}"
        )
        layout = self.config_model.system_layout
        if not layout:
            canvas.create_text(30, 30, anchor="nw", text="Apply or build a system first.")
            return
        width, height = max(canvas.winfo_width(), 200), max(canvas.winfo_height(), 160)
        xs = [float(item.get("x", 0.0)) for item in layout]
        ys = [float(item.get("y", 0.0)) for item in layout]
        min_x, max_x = min(xs) - 80.0, max(xs) + 80.0
        min_y, max_y = min(ys) - 60.0, max(ys) + 60.0
        scale = min((width - 30.0) / max(max_x - min_x, 1.0), (height - 30.0) / max(max_y - min_y, 1.0))
        self.system_animation_render_scale = scale
        def point(item: dict[str, object]) -> tuple[float, float]:
            return (15.0 + (float(item.get("x", 0.0)) - min_x) * scale,
                    15.0 + (float(item.get("y", 0.0)) - min_y) * scale)
        by_id = {str(item.get("id")): item for item in layout}
        for connection in self.config_model.system_connections:
            source, target = by_id.get(connection.get("source_component", "")), by_id.get(connection.get("target_component", ""))
            if source is None or target is None:
                continue
            sx, sy = point(source); tx, ty = point(target)
            canvas.create_line(sx, sy, tx, ty, fill="#7b878d", width=3, arrow=tk.LAST)
            source_type = str(source.get("component_type", ""))
            target_type = str(target.get("component_type", ""))
            if self._system_animation_connection_active(source_type, target_type, row):
                for offset in (0.0, 0.33, 0.66):
                    fraction = (self.system_animation_phase + offset) % 1.0
                    px, py = sx + (tx - sx) * fraction, sy + (ty - sy) * fraction
                    canvas.create_oval(px - 5, py - 5, px + 5, py + 5, fill="#1687d9", outline="")
            if self.system_animation_show_pipe_flow_var.get():
                flow_volume = self._system_animation_connection_flow_gallons(
                    source_type, target_type, row
                )
                label_id = canvas.create_text(
                    (sx + tx) / 2.0,
                    (sy + ty) / 2.0 - 9.0,
                    text=self._system_animation_pipe_flow_label(
                        flow_volume, self.config_model
                    ),
                    fill="#263238",
                    font=("Segoe UI", 8, "bold"),
                )
                bounds = canvas.bbox(label_id)
                if bounds is not None:
                    background_id = canvas.create_rectangle(
                        bounds[0] - 3, bounds[1] - 1,
                        bounds[2] + 3, bounds[3] + 1,
                        fill="white", outline="#c5cdd1",
                    )
                    canvas.tag_lower(background_id, label_id)
        primary_begin = float(row.get(
            "PrimaryTankBeginningGallons",
            self.config_model.selected_tank_size_gal
            * self.config_model.tank_parameters.initial_fill_percent / 100.0
            if hour == 0
            else self.system_animation_results.iloc[hour - 1].get("WaterInTankGallons", 0.0),
        ))
        booster_begin = float(row.get(
            "BoosterTankBeginningGallons",
            self.config_model.system_parameters.booster_tank_size_gallons
            * self.config_model.system_parameters.booster_initial_fill_percent / 100.0
            if hour == 0
            else self.system_animation_results.iloc[hour - 1].get("BoosterTankGallons", 0.0),
        ))
        for item in layout:
            x, y = point(item); component_type = str(item.get("component_type", ""))
            component_id = str(item.get("id", ""))
            component_tag = f"animation-component:{component_id}"
            block_w, block_h = 124.0 * scale, 60.0 * scale
            canvas.create_rectangle(x - block_w / 2, y - block_h / 2, x + block_w / 2, y + block_h / 2,
                                    fill="#f7f9fa", outline="#30363a", width=2,
                                    tags=(component_tag,))
            if component_type in {"primary_tank", "booster_tank"}:
                capacity = (self.config_model.selected_tank_size_gal if component_type == "primary_tank"
                            else self.config_model.system_parameters.booster_tank_size_gallons)
                beginning_volume = primary_begin if component_type == "primary_tank" else booster_begin
                result_column = (
                    "WaterInTankGallons"
                    if component_type == "primary_tank"
                    else "BoosterTankGallons"
                )
                ending_volume = float(row.get(result_column, beginning_volume))
                volume = beginning_volume + (ending_volume - beginning_volume) * hour_progress
                volume = min(max(volume, 0.0), max(capacity, 0.0))
                fraction = min(max(volume / capacity, 0.0), 1.0) if capacity > 0 else 0.0
                inner_h = max(block_h - 6.0, 0.0) * fraction
                canvas.create_rectangle(x - block_w / 2 + 3, y + block_h / 2 - 3 - inner_h,
                                        x + block_w / 2 - 3, y + block_h / 2 - 3,
                                        fill="#70b7e6", outline="")
                canvas.create_text(
                    x,
                    y,
                    text=_tank_volume_capacity_label(volume, capacity, self.config_model),
                    fill="#172026",
                    font=("Segoe UI", 7, "bold"),
                    width=max(block_w - 8.0, 20.0),
                    justify="center",
                    tags=(component_tag,),
                )
            if component_type in {"filtration_pump", "booster_pump"}:
                running = (float(row.get("PumpFlowGallons", 0.0)) > 1e-9 if component_type == "filtration_pump"
                           else float(row.get("DemandGallons", 0.0)) - float(row.get("SystemUnmetDemandGallons", 0.0)) > 1e-9)
                angle = self.system_animation_phase * math.tau if running else 0.0
                radius = min(block_w, block_h) * 0.23
                canvas.create_oval(x - radius, y - radius, x + radius, y + radius, outline="#455a64", width=2)
                for spoke in range(6):
                    theta = angle + spoke * math.tau / 6.0
                    canvas.create_line(x, y, x + math.cos(theta) * radius, y + math.sin(theta) * radius,
                                       fill="#455a64", width=2)
            if component_type == "rainwater_input":
                raining = self._system_animation_rain_active(row)
                if not self._draw_weather_asset_animation(
                    canvas, x, y, self.system_animation_phase, raining
                ):
                    self._draw_pixel_weather_animation(
                        canvas, x, y, max(block_w - 6.0, 1.0), max(block_h - 6.0, 1.0),
                        self.system_animation_phase, raining,
                    )
            if component_type == "overflow_pipe":
                overflow_start = float(
                    row.get("OverflowBeginningCumulativeGallons", 0.0)
                )
                overflow_end = float(
                    row.get("CumulativeOverflowGallons", overflow_start)
                )
                overflow_total = overflow_start + (
                    overflow_end - overflow_start
                ) * hour_progress
                canvas.create_text(
                    x, y,
                    text=(
                        "Cumulative overflow\n"
                        f"{format_number(volume_to_display(overflow_total, self.config_model), self.config_model, max_decimal_places=1)} "
                        f"{volume_unit(self.config_model)}"
                    ),
                    fill="#a84300", font=("Segoe UI", 7, "bold"),
                    width=max(block_w - 8.0, 20.0), justify="center",
                    tags=(component_tag,),
                )
            if (
                component_type == "end_uses"
                and self._system_animation_irrigation_active(item, animation_timestamp)
                and float(row.get("DemandGallons", 0.0)) > 1e-9
            ):
                self._draw_pixel_irrigation_animation(
                    canvas, x, y, max(block_w - 6.0, 1.0), max(block_h - 6.0, 1.0),
                    self.system_animation_phase,
                )
            canvas.create_text(x, y + block_h / 2 + 11, text=str(item.get("name", component_type)),
                               font=("Segoe UI", 8, "bold"), tags=(component_tag,))

    def save_custom_system_template(self) -> None:
        if not self.config_model.system_layout:
            messagebox.showwarning(APP_TITLE, "Add system objects before saving a template.", parent=self)
            return
        name = simpledialog.askstring(APP_TITLE, "Custom template name:", parent=self)
        if name is None:
            return
        try:
            self.store.save_system_template(name, self._system_template_payload())
        except ValueError as exc:
            messagebox.showerror(APP_TITLE, str(exc), parent=self)
            return
        clean_name = name.strip()
        self._refresh_system_template_library(select_name=clean_name)
        self.status_var.set(f"Saved custom system template: {clean_name}")

    def apply_selected_system_template(self) -> None:
        selected = self.system_template_library.selection()
        if not selected:
            return
        iid = selected[0]
        if iid.startswith("builtin:"):
            self.apply_system_template(iid.split(":", 1)[1])
            return
        name = self.system_custom_template_iids.get(iid)
        if name is None:
            return
        try:
            payload = self.store.load_system_template(name)
            layout = payload.get("system_layout", [])
            connections = payload.get("system_connections", [])
            if not isinstance(layout, list) or not isinstance(connections, list):
                raise ValueError(f"System template '{name}' is invalid.")
            cfg = self.config_model
            cfg.system_type = (
                payload.get("system_type")
                if payload.get("system_type") in {"Direct system", "Indirect system"}
                else "Direct system"
            )
            loaded_layout = [copy.deepcopy(item) for item in layout if isinstance(item, dict)]
            loaded_connections = [
                {str(key): str(value) for key, value in item.items()}
                for item in connections if isinstance(item, dict)
            ]
            cfg.system_layout, cfg.system_connections = ensure_primary_overflow_paths(
                loaded_layout, loaded_connections
            )
            if isinstance(payload.get("system_parameters"), dict):
                system_payload = dict(payload["system_parameters"])
                if "filtration_system_flow_gpm" not in system_payload:
                    legacy_capacity = float(
                        system_payload.get("filtration_pump_capacity_gallons_per_hour", 1200.0)
                    )
                    system_payload["filtration_system_flow_gpm"] = (
                        normalize_filtration_system_flow_gpm(legacy_capacity / 60.0)
                    )
                cfg.system_parameters = SystemComponentParameters(**system_payload)
                cfg.system_parameters.synchronize_filtration_flow()
            if isinstance(payload.get("tank_parameters"), dict):
                cfg.tank_parameters = TankParameters(**payload["tank_parameters"])
            if "selected_tank_size_gal" in payload:
                cfg.selected_tank_size_gal = float(payload["selected_tank_size_gal"])
            for field_name in ("graph_start_gal", "graph_end_gal", "graph_step_gal"):
                if field_name in payload:
                    setattr(cfg, field_name, int(float(payload[field_name])))
            cfg.first_flush_sizing_method = normalize_first_flush_sizing_method(
                payload.get("first_flush_sizing_method", cfg.first_flush_sizing_method)
            )
            cfg.first_flush_design_preset = normalize_first_flush_design_preset(
                payload.get("first_flush_design_preset", cfg.first_flush_design_preset)
            )
            cfg.first_flush_antecedent_dry_days = max(
                float(payload.get(
                    "first_flush_antecedent_dry_days",
                    cfg.first_flush_antecedent_dry_days,
                )),
                0.0,
            )
            unit = str(payload.get(
                "first_flush_antecedent_dry_unit",
                cfg.first_flush_antecedent_dry_unit,
            )).casefold()
            cfg.first_flush_antecedent_dry_unit = unit if unit in {"days", "hours"} else "days"
        except (TypeError, ValueError) as exc:
            messagebox.showerror(APP_TITLE, str(exc), parent=self)
            return
        self.system_builder_selected_id = None
        self.system_builder_selected_ids.clear()
        self.system_builder_selected_connection = None
        self.system_builder_pending_source = None
        self.system_builder_pending_target = None
        self.system_builder_pending_target_port = "in"
        self.system_component_editor_drafts.clear()
        self.system_component_editor_loaded_id = None
        self._populate_from_model()
        self._render_system_builder()
        self.status_var.set(f"Applied custom system template: {name}")

    def _apply_selected_system_template_event(self, _event: tk.Event) -> str:
        self.apply_selected_system_template()
        return "break"

    def rename_custom_system_template(self) -> None:
        old_name = self._selected_custom_system_template_name()
        if old_name is None:
            messagebox.showinfo(APP_TITLE, "Select a custom template to rename.", parent=self)
            return
        new_name = simpledialog.askstring(
            APP_TITLE, "New custom template name:", initialvalue=old_name, parent=self
        )
        if new_name is None:
            return
        try:
            self.store.rename_system_template(old_name, new_name)
        except ValueError as exc:
            messagebox.showerror(APP_TITLE, str(exc), parent=self)
            return
        clean_name = new_name.strip()
        self._refresh_system_template_library(select_name=clean_name)
        self.status_var.set(f"Renamed custom system template to: {clean_name}")

    def delete_custom_system_template(self) -> None:
        name = self._selected_custom_system_template_name()
        if name is None:
            messagebox.showinfo(APP_TITLE, "Select a custom template to delete.", parent=self)
            return
        if not messagebox.askyesno(
            APP_TITLE, f"Delete custom system template '{name}'?", parent=self
        ):
            return
        self.store.delete_system_template(name)
        self._refresh_system_template_library()
        self.status_var.set(f"Deleted custom system template: {name}")

    def apply_system_template(self, system_type: str) -> None:
        if system_type == "Direct system":
            components = [
                ("rainwater_input", "Rainwater input", 65, 135),
                ("first_flush_diversion", "First-flush device", 205, 135),
                ("primary_tank", "Primary tank", 345, 135),
                ("booster_pump", "Distribution pump", 500, 135),
                ("end_uses", "End-uses", 665, 135),
                ("municipal_backup", "Municipal water backup", 460, 260),
                ("overflow_pipe", "Overflow pipe", 460, 40),
            ]
            links = [(0, 1), (1, 2), (2, 3), (3, 4), (5, 4)]
        elif system_type == "Indirect system":
            components = [
                ("rainwater_input", "Rainwater input", 65, 100),
                ("first_flush_diversion", "First-flush device", 195, 100),
                ("primary_tank", "Primary tank", 325, 100),
                ("filtration_pump", "Transfer pump", 455, 100),
                ("filtration_system", "Filtration system", 585, 100),
                ("booster_tank", "Buffer tank", 715, 100),
                ("municipal_backup", "Municipal water backup", 535, 235),
                ("booster_pump", "Booster pump", 385, 320),
                ("end_uses", "End-uses", 650, 320),
                ("overflow_pipe", "Overflow pipe", 385, 20),
            ]
            links = [(0, 1), (1, 2), (2, 3), (3, 4), (4, 5), (6, 5), (5, 7), (7, 8)]
        else:
            return
        layout: list[dict[str, object]] = []
        for index, (component_type, name, x, y) in enumerate(components, start=1):
            item: dict[str, object] = {
                "id": f"{component_type}_{index}",
                "component_type": component_type,
                "name": name,
                "x": x,
                "y": y,
            }
            if component_type == "end_uses":
                item["demand_object_indices"] = list(
                    range(len(self.config_model.demand.demand_objects))
                )
            elif component_type == "first_flush_diversion":
                item.update({
                    "sizing_method": self.config_model.first_flush_sizing_method,
                    "design_preset": self.config_model.first_flush_design_preset,
                    "antecedent_dry_days": self.config_model.first_flush_antecedent_dry_days,
                    "antecedent_dry_unit": self.config_model.first_flush_antecedent_dry_unit,
                })
            layout.append(item)
        self.config_model.system_layout = layout
        self.config_model.system_connections = [
            {
                "source_component": str(layout[source]["id"]),
                "target_component": str(layout[target]["id"]),
            }
            for source, target in links
        ]
        primary_id = next(
            str(item["id"]) for item in layout if item["component_type"] == "primary_tank"
        )
        overflow_id = next(
            str(item["id"]) for item in layout if item["component_type"] == "overflow_pipe"
        )
        self.config_model.system_connections.append({
            "source_component": primary_id,
            "source_port": "overflow",
            "target_component": overflow_id,
        })
        self.config_model.system_type = system_type
        self.system_type_var.set(system_type)
        self.current_system_type_var.set(f"Current system type: {system_type}")
        self.system_builder_selected_id = None
        self.system_builder_selected_ids.clear()
        self.system_builder_selected_connection = None
        self.system_builder_pending_source = None
        self.system_builder_pending_target = None
        self.system_builder_pending_target_port = "in"
        self.system_builder_port_drag = None
        self.system_component_editor_drafts.clear()
        self.system_component_editor_loaded_id = None
        self._render_system_builder()
        self.status_var.set(f"Applied {system_type.lower()} template")

    def _add_system_component(self, component_type: str, x: float, y: float) -> None:
        label = self._system_component_templates().get(component_type)
        if label is None:
            return
        component_id = self._new_system_component_id(component_type)
        position = self._nearest_available_system_position(x, y)
        if position is None:
            self.status_var.set("No open space is available for another system object")
            return
        x, y = position
        item: dict[str, object] = {
            "id": component_id, "component_type": component_type,
            "name": label, "x": x, "y": y,
        }
        if component_type == "end_uses":
            item["demand_object_indices"] = list(
                range(len(self.config_model.demand.demand_objects))
            )
        elif component_type == "first_flush_diversion":
            item.update({
                "sizing_method": self.config_model.first_flush_sizing_method,
                "design_preset": self.config_model.first_flush_design_preset,
                "antecedent_dry_days": self.config_model.first_flush_antecedent_dry_days,
                "antecedent_dry_unit": self.config_model.first_flush_antecedent_dry_unit,
            })
        self.config_model.system_layout.append(item)
        self.system_builder_selected_id = component_id
        self._render_system_builder()

    def add_selected_system_component(self) -> None:
        selected = self.system_component_library.selection()
        if not selected:
            return
        count = len(self.config_model.system_layout)
        self._add_system_component(selected[0], 110 + (count % 4) * 165, 80 + (count // 4) * 110)

    def _add_system_library_component_from_event(self, event: tk.Event) -> str:
        row_id = self.system_component_library.identify_row(getattr(event, "y", 0))
        if row_id:
            self.system_component_library.selection_set(row_id)
        self.add_selected_system_component()
        return "break"

    def _system_library_drag_start(self, event: tk.Event) -> None:
        row_id = self.system_component_library.identify_row(event.y)
        self.system_library_drag_type = row_id if row_id in self._system_component_templates() else None

    def _system_library_drop(self, _event: tk.Event) -> None:
        if self.system_library_drag_type is None:
            return
        pointer_x, pointer_y = self.winfo_pointerxy()
        canvas_x = pointer_x - self.system_builder_canvas.winfo_rootx()
        canvas_y = pointer_y - self.system_builder_canvas.winfo_rooty()
        if 0 <= canvas_x <= self.system_builder_canvas.winfo_width() and 0 <= canvas_y <= self.system_builder_canvas.winfo_height():
            model_x, model_y = self._system_model_point(canvas_x, canvas_y)
            self._add_system_component(self.system_library_drag_type, model_x, model_y)
        self.system_library_drag_type = None

    def _system_layout_item(self, component_id: str) -> dict[str, object] | None:
        return next(
            (item for item in self.config_model.system_layout if str(item.get("id")) == component_id),
            None,
        )

    @staticmethod
    def _system_blocks_overlap(
        first_x: float, first_y: float, second_x: float, second_y: float
    ) -> bool:
        """Treat system blocks as solid rectangles with a small visual gap."""
        return RainwaterTkApp._system_rectangles_overlap(
            first_x, first_y, 124.0, 60.0, second_x, second_y, 124.0, 60.0
        )

    @staticmethod
    def _system_rectangles_overlap(
        first_x: float,
        first_y: float,
        first_width: float,
        first_height: float,
        second_x: float,
        second_y: float,
        second_width: float,
        second_height: float,
    ) -> bool:
        return (
            abs(first_x - second_x) < (first_width + second_width) / 2.0 + 8.0
            and abs(first_y - second_y) < (first_height + second_height) / 2.0 + 8.0
        )

    def _system_position_overlaps(
        self,
        x: float,
        y: float,
        *,
        width: float = 124.0,
        height: float = 60.0,
        exclude_id: str | None = None,
    ) -> bool:
        for item in self.config_model.system_layout:
            if exclude_id is not None and str(item.get("id")) == exclude_id:
                continue
            try:
                other_x, other_y = float(item["x"]), float(item["y"])
            except (KeyError, TypeError, ValueError):
                continue
            other_width = max(float(item.get("width", 124.0)), 80.0)
            other_height = max(float(item.get("height", 60.0)), 44.0)
            if self._system_rectangles_overlap(
                x, y, width, height, other_x, other_y, other_width, other_height
            ):
                return True
        return False

    def _system_canvas_dimensions(self) -> tuple[float, float]:
        maximum_zoom_out = 0.7
        width = max(
            float(self.system_builder_canvas.winfo_width()),
            float(self.system_builder_canvas.cget("width")),
        ) / maximum_zoom_out
        height = max(
            float(self.system_builder_canvas.winfo_height()),
            float(self.system_builder_canvas.cget("height")),
        ) / maximum_zoom_out
        return width, height

    @staticmethod
    def _required_system_builder_canvas_size(
        layout: list[dict[str, object]],
        minimum_width: float = 760.0,
        minimum_height: float = 420.0,
    ) -> tuple[int, int]:
        """Return a canvas size that contains every system object and its ports."""
        right_edge = float(minimum_width)
        bottom_edge = float(minimum_height)
        for item in layout:
            try:
                x = float(item.get("x", 0.0))
                y = float(item.get("y", 0.0))
                width = max(float(item.get("width", 124.0)), 80.0)
                height = max(float(item.get("height", 60.0)), 44.0)
            except (TypeError, ValueError):
                continue
            # Leave room for inlet/outlet circles, their +/- affordances, and the
            # canvas highlight so edge objects are never visually clipped.
            right_edge = max(right_edge, x + width / 2.0 + 32.0)
            bottom_edge = max(bottom_edge, y + height / 2.0 + 16.0)
        return math.ceil(right_edge), math.ceil(bottom_edge)

    def _resize_system_builder_canvas_to_objects(self) -> None:
        canvas = self.system_builder_canvas
        width, height = self._required_system_builder_canvas_size(
            self.config_model.system_layout
        )
        if int(float(canvas.cget("width"))) != width or int(float(canvas.cget("height"))) != height:
            canvas.configure(width=width, height=height)
            if hasattr(self, "system_builder_scroll_canvas"):
                self.after_idle(self._update_system_builder_scroll_region)

    def _change_system_builder_zoom(self, delta: float) -> None:
        self.system_builder_zoom = self._bounded_system_builder_zoom(
            self.system_builder_zoom, delta
        )
        self._clamp_system_builder_pan()
        new_steps = round(self.system_builder_zoom * 10)
        self.system_builder_zoom_var.set(f"{new_steps * 10}%")
        self._render_system_builder()

    @staticmethod
    def _bounded_system_builder_zoom(current: float, delta: float) -> float:
        current_steps = round(float(current) * 10)
        delta_steps = 1 if delta > 0 else -1
        return min(max(current_steps + delta_steps, 7), 13) / 10.0

    def _system_model_point(self, x: float, y: float) -> tuple[float, float]:
        zoom = max(float(getattr(self, "system_builder_zoom", 1.0)), 0.01)
        return (
            float(x) / zoom - self.system_builder_pan_x,
            float(y) / zoom - self.system_builder_pan_y,
        )

    @staticmethod
    def _bounded_system_builder_pan(
        canvas_width: float, canvas_height: float, zoom: float,
        pan_x: float, pan_y: float,
    ) -> tuple[float, float]:
        zoom = min(max(float(zoom), 0.7), 1.3)
        world_width = float(canvas_width) / 0.7
        world_height = float(canvas_height) / 0.7
        minimum_x = min(float(canvas_width) / zoom - world_width, 0.0)
        minimum_y = min(float(canvas_height) / zoom - world_height, 0.0)
        return (
            min(max(float(pan_x), minimum_x), 0.0),
            min(max(float(pan_y), minimum_y), 0.0),
        )

    def _clamp_system_builder_pan(self) -> None:
        canvas = self.system_builder_canvas
        self.system_builder_pan_x, self.system_builder_pan_y = self._bounded_system_builder_pan(
            max(float(canvas.winfo_width()), float(canvas.cget("width"))),
            max(float(canvas.winfo_height()), float(canvas.cget("height"))),
            self.system_builder_zoom,
            self.system_builder_pan_x,
            self.system_builder_pan_y,
        )

    def _system_canvas_pan_start(self, event: tk.Event) -> str:
        self.system_builder_pan_state = (
            float(event.x), float(event.y),
            self.system_builder_pan_x, self.system_builder_pan_y,
        )
        self.system_builder_canvas.configure(cursor="fleur")
        return "break"

    def _system_canvas_pan_drag(self, event: tk.Event) -> str:
        if self.system_builder_pan_state is None:
            return "break"
        start_x, start_y, original_pan_x, original_pan_y = self.system_builder_pan_state
        zoom = max(self.system_builder_zoom, 0.01)
        self.system_builder_pan_x = original_pan_x + (float(event.x) - start_x) / zoom
        self.system_builder_pan_y = original_pan_y + (float(event.y) - start_y) / zoom
        self._clamp_system_builder_pan()
        self._render_system_builder()
        return "break"

    def _system_canvas_pan_end(self, _event: tk.Event) -> str:
        self.system_builder_pan_state = None
        self.system_builder_canvas.configure(cursor="")
        self.status_var.set("System builder view panned")
        return "break"

    def _system_builder_canvas_resized(self, _event: tk.Event) -> None:
        self._clamp_system_builder_pan()
        self._render_system_builder()

    def _nearest_available_system_position(self, x: float, y: float) -> tuple[float, float] | None:
        width, height = self._system_canvas_dimensions()
        requested = (
            min(max(float(x), 65.0), max(width - 65.0, 65.0)),
            min(max(float(y), 35.0), max(height - 35.0, 35.0)),
        )
        if not self._system_position_overlaps(*requested):
            return requested
        candidates = [
            (candidate_x, candidate_y)
            for candidate_y in self._float_range(35.0, max(height - 35.0, 35.0), 68.0)
            for candidate_x in self._float_range(65.0, max(width - 65.0, 65.0), 132.0)
            if not self._system_position_overlaps(candidate_x, candidate_y)
        ]
        if not candidates:
            return None
        return min(
            candidates,
            key=lambda point: (point[0] - requested[0]) ** 2 + (point[1] - requested[1]) ** 2,
        )

    @staticmethod
    def _float_range(start: float, stop: float, step: float) -> list[float]:
        values: list[float] = []
        value = start
        while value <= stop + 0.001:
            values.append(value)
            value += step
        return values

    @staticmethod
    def _system_component_ports(component_type: str) -> tuple[bool, bool]:
        has_inlet = component_type not in {"rainwater_input", "municipal_backup"}
        has_outlet = component_type not in {"end_uses", "overflow_pipe"}
        return has_inlet, has_outlet

    @staticmethod
    def _primary_tank_outlet_offset(
        item: dict[str, object], source_port: str
    ) -> float:
        """Return the vertical offset for a primary tank's distinct outlets."""
        has_optional_outlet = bool(item.get("extra_output_node"))
        if source_port == "overflow":
            return 20.0 if has_optional_outlet else 14.0
        if source_port == "out2":
            return 0.0
        return -20.0 if has_optional_outlet else -14.0

    @staticmethod
    def _system_port_is_output(direction: str) -> bool:
        return direction.startswith("out") or direction == "overflow"

    def _connect_system_components(
        self, source_id: str, target_id: str, target_port: str = "in",
        source_port: str = "out",
    ) -> None:
        if source_id == target_id:
            self.system_builder_pending_source = None
            self.system_builder_pending_target = None
            self._render_system_builder()
            return
        connection = {"source_component": source_id, "target_component": target_id}
        if source_port in {"out2", "overflow"}:
            connection["source_port"] = source_port
        if target_port == "in2":
            connection["target_port"] = "in2"
        if connection not in self.config_model.system_connections:
            self.config_model.system_connections.append(connection)
        self.system_builder_pending_source = None
        self.system_builder_pending_target = None
        self.system_builder_selected_connection = connection
        self.system_builder_selected_id = None
        self._render_system_builder()

    def _system_canvas_press(self, event: tk.Event) -> None:
        model_x, model_y = self._system_model_point(event.x, event.y)
        current = self.system_builder_canvas.find_withtag("current")
        tags = self.system_builder_canvas.gettags(current[0]) if current else ()
        port_tag = next((tag for tag in tags if tag.startswith("port:")), None)
        add_inlet_tag = next((tag for tag in tags if tag.startswith("add-inlet:")), None)
        remove_inlet_tag = next((tag for tag in tags if tag.startswith("remove-inlet:")), None)
        add_outlet_tag = next((tag for tag in tags if tag.startswith("add-outlet:")), None)
        remove_outlet_tag = next((tag for tag in tags if tag.startswith("remove-outlet:")), None)
        if remove_outlet_tag is not None:
            component_id = remove_outlet_tag.split(":", 1)[1]
            item = self._system_layout_item(component_id)
            if item is not None and item.get("component_type") == "primary_tank":
                linked = any(
                    connection.get("source_component") == component_id
                    and connection.get("source_port", "out") == "out2"
                    for connection in self.config_model.system_connections
                )
                if linked:
                    self.status_var.set(
                        "Disconnect the second primary-tank output before removing it"
                    )
                    return
                item.pop("extra_output_node", None)
                self.system_builder_pending_source = None
                self.system_builder_pending_source_port = "out"
                self.system_builder_port_drag = None
                self.system_builder_selected_id = component_id
                self.status_var.set("Removed the second primary-tank output node")
                self._render_system_builder()
            return
        if add_outlet_tag is not None:
            component_id = add_outlet_tag.split(":", 1)[1]
            item = self._system_layout_item(component_id)
            if item is not None and item.get("component_type") == "primary_tank":
                item["extra_output_node"] = True
                self.system_builder_selected_id = component_id
                self.status_var.set("Added a second primary-tank output node")
                self._render_system_builder()
            return
        if remove_inlet_tag is not None:
            component_id = remove_inlet_tag.split(":", 1)[1]
            item = self._system_layout_item(component_id)
            if item is not None and item.get("component_type") == "booster_tank":
                linked = any(
                    connection.get("target_component") == component_id
                    and connection.get("target_port", "in") == "in2"
                    for connection in self.config_model.system_connections
                )
                if linked:
                    self.status_var.set(
                        "Disconnect the second buffer-tank input before removing it"
                    )
                    return
                before = len(self.config_model.system_connections)
                self.config_model.system_connections = self._connections_after_node_disconnect(
                    self.config_model.system_connections, component_id, "in2"
                )
                item.pop("extra_input_node", None)
                removed = before - len(self.config_model.system_connections)
                self.system_builder_pending_target = None
                self.system_builder_pending_target_port = "in"
                self.system_builder_port_drag = None
                self.system_builder_selected_id = component_id
                self.status_var.set(
                    f"Removed the second buffer-tank input node and {removed} connection(s)"
                )
                self._render_system_builder()
            return
        if add_inlet_tag is not None:
            component_id = add_inlet_tag.split(":", 1)[1]
            item = self._system_layout_item(component_id)
            if item is not None and item.get("component_type") == "booster_tank":
                item["extra_input_node"] = True
                self.system_builder_selected_id = component_id
                self.status_var.set("Added a second buffer-tank input node")
                self._render_system_builder()
            return
        if port_tag is not None:
            _prefix, component_id, direction = port_tag.split(":", 2)
            if self._system_port_is_output(direction) and self.system_builder_pending_target is not None:
                self._connect_system_components(
                    component_id, self.system_builder_pending_target,
                    self.system_builder_pending_target_port, direction,
                )
                self.system_builder_port_drag = None
            elif direction.startswith("in") and self.system_builder_pending_source is not None:
                self._connect_system_components(
                    self.system_builder_pending_source, component_id, direction,
                    self.system_builder_pending_source_port,
                )
                self.system_builder_port_drag = None
            elif self._system_port_is_output(direction):
                self.system_builder_pending_source = component_id
                self.system_builder_pending_source_port = direction
                self.system_builder_pending_target = None
                self.system_builder_selected_id = component_id
                self.system_builder_selected_connection = None
                self._render_system_builder()
                self.system_builder_port_drag = (component_id, direction)
            else:
                self.system_builder_pending_target = component_id
                self.system_builder_pending_target_port = direction
                self.system_builder_pending_source = None
                self.system_builder_selected_id = component_id
                self.system_builder_selected_connection = None
                self._render_system_builder()
                self.system_builder_port_drag = (component_id, direction)
            self.system_builder_canvas.focus_set()
            return
        connection_tag = next((tag for tag in tags if tag.startswith("connection:")), None)
        if connection_tag is not None:
            index = int(connection_tag.split(":", 1)[1])
            if 0 <= index < len(self.config_model.system_connections):
                self.system_builder_selected_connection = self.config_model.system_connections[index]
                self.system_builder_selected_id = None
                self.system_builder_pending_source = None
                self.system_builder_pending_target = None
                self.system_builder_canvas.focus_set()
                self._render_system_builder()
            return
        component_tag = next((tag for tag in tags if tag.startswith("component:")), None)
        clicked_id = component_tag.split(":", 1)[1] if component_tag else None
        if (
            clicked_id is not None
            and clicked_id == self.system_builder_selected_id
            and not self.system_multi_select_var.get()
        ):
            item = self._system_layout_item(clicked_id)
            if item is not None:
                x, y = float(item.get("x", 0.0)), float(item.get("y", 0.0))
                item_width = float(item.get("width", 124.0))
                item_height = float(item.get("height", 60.0))
                horizontal = "w" if model_x < x else "e"
                vertical = "n" if model_y < y else "s"
                corner_x = x - item_width / 2.0 if horizontal == "w" else x + item_width / 2.0
                corner_y = y - item_height / 2.0 if vertical == "n" else y + item_height / 2.0
                if abs(model_x - corner_x) <= 10.0 and abs(model_y - corner_y) <= 10.0:
                    self.system_builder_resize_state = (
                        clicked_id, vertical + horizontal, x, y, item_width, item_height,
                        model_x, model_y,
                    )
                    return
        if self.system_multi_select_var.get():
            if clicked_id is not None:
                if clicked_id in self.system_builder_selected_ids:
                    self.system_builder_selected_ids.remove(clicked_id)
                else:
                    self.system_builder_selected_ids.add(clicked_id)
            self.system_builder_selected_id = None
            self.system_geometry_status_var.set(
                f"{len(self.system_builder_selected_ids)} object(s) selected."
            )
            self.system_builder_canvas.focus_set()
            self._render_system_builder()
            return
        self.system_builder_selected_ids.clear()
        self.system_builder_selected_id = clicked_id
        self.system_builder_selected_connection = None
        self.system_builder_pending_source = None
        self.system_builder_pending_target = None
        if self.system_builder_selected_id:
            item = self._system_layout_item(self.system_builder_selected_id)
            if item is not None:
                self.system_builder_drag_offset = (
                    model_x - float(item["x"]), model_y - float(item["y"])
                )
            self.system_builder_side_tabs.select(self.system_component_edit_tab)
        self.system_builder_canvas.focus_set()
        self._render_system_builder()

    def _system_canvas_drag(self, event: tk.Event) -> None:
        if self.system_builder_port_drag is not None:
            component_id, direction = self.system_builder_port_drag
            item = self._system_layout_item(component_id)
            if item is None:
                return
            x, y = float(item.get("x", 0.0)), float(item.get("y", 0.0))
            half_width = max(float(item.get("width", 124.0)), 80.0) / 2.0
            output_port = self._system_port_is_output(direction)
            start_x = x + half_width + 3.0 if output_port else x - half_width - 3.0
            start_y = y + (14.0 if direction == "in2" else (-14.0 if direction == "in" and item.get("extra_input_node") else 0.0))
            if output_port and item.get("component_type") == "primary_tank":
                start_y = y + self._primary_tank_outlet_offset(item, direction)
            self.system_builder_canvas.delete("pending-link-preview")
            zoom = self.system_builder_zoom
            self.system_builder_canvas.create_line(
                (start_x + self.system_builder_pan_x) * zoom,
                (start_y + self.system_builder_pan_y) * zoom,
                event.x, event.y,
                fill="#9aa4a9", width=2, dash=(5, 3), arrow=tk.LAST,
                tags=("pending-link-preview",),
            )
            self._update_system_port_drag_hover(event.x, event.y, component_id, direction)
            return
        if self.system_builder_resize_state is not None:
            self._resize_selected_system_object(event)
            return
        if self.system_builder_selected_id is None:
            return
        item = self._system_layout_item(self.system_builder_selected_id)
        if item is None:
            return
        offset_x, offset_y = self.system_builder_drag_offset
        model_x, model_y = self._system_model_point(event.x, event.y)
        item_width = max(float(item.get("width", 124.0)), 80.0)
        item_height = max(float(item.get("height", 60.0)), 44.0)
        width, height = self._system_canvas_dimensions()
        proposed_x = min(max(model_x - offset_x, item_width / 2.0 + 3.0), max(width - item_width / 2.0 - 3.0, item_width / 2.0 + 3.0))
        proposed_y = min(max(model_y - offset_y, item_height / 2.0 + 3.0), max(height - item_height / 2.0 - 3.0, item_height / 2.0 + 3.0))
        current_x, current_y = float(item["x"]), float(item["y"])
        if not self._system_position_overlaps(
            proposed_x, proposed_y, width=item_width, height=item_height,
            exclude_id=self.system_builder_selected_id
        ):
            item["x"], item["y"] = proposed_x, proposed_y
        elif not self._system_position_overlaps(
            proposed_x, current_y, width=item_width, height=item_height,
            exclude_id=self.system_builder_selected_id
        ):
            item["x"] = proposed_x
        elif not self._system_position_overlaps(
            current_x, proposed_y, width=item_width, height=item_height,
            exclude_id=self.system_builder_selected_id
        ):
            item["y"] = proposed_y
        self._render_system_builder()

    def _system_canvas_release(self, event: tk.Event) -> None:
        if self.system_builder_port_drag is not None:
            origin_id, origin_direction = self.system_builder_port_drag
            overlapping = self.system_builder_canvas.find_overlapping(
                event.x - 2, event.y - 2, event.x + 2, event.y + 2
            )
            target_port: tuple[str, str] | None = None
            for canvas_item in reversed(overlapping):
                port_tag = next(
                    (tag for tag in self.system_builder_canvas.gettags(canvas_item) if tag.startswith("port:")),
                    None,
                )
                if port_tag:
                    _prefix, component_id, direction = port_tag.split(":", 2)
                    target_port = (component_id, direction)
                    break
            self.system_builder_port_drag = None
            self._clear_system_port_drag_hover()
            self.system_builder_canvas.delete("pending-link-preview")
            if target_port is not None and target_port[1] != origin_direction:
                if self._system_port_is_output(origin_direction):
                    self._connect_system_components(
                        origin_id, target_port[0], target_port[1], origin_direction
                    )
                else:
                    self._connect_system_components(
                        target_port[0], origin_id, origin_direction, target_port[1]
                    )
                return
        self.system_builder_drag_offset = (0.0, 0.0)
        self.system_builder_resize_state = None

    def _clear_system_port_drag_hover(self) -> None:
        if self.system_builder_hover_port is None:
            return
        component_id, direction = self.system_builder_hover_port
        base_fill = (
            "#1565c0" if direction.startswith("in")
            else "#ef6c00" if direction == "overflow"
            else "#c62828"
        )
        for canvas_item in self.system_builder_canvas.find_withtag(
            f"port:{component_id}:{direction}"
        ):
            if self.system_builder_canvas.type(canvas_item) == "oval":
                self.system_builder_canvas.itemconfigure(canvas_item, fill=base_fill)
        self.system_builder_hover_port = None

    def _update_system_port_drag_hover(
        self, x: float, y: float, origin_id: str, origin_direction: str
    ) -> None:
        self._clear_system_port_drag_hover()
        expected_direction = "in" if self._system_port_is_output(origin_direction) else "out"
        overlapping = self.system_builder_canvas.find_overlapping(x - 2, y - 2, x + 2, y + 2)
        for canvas_item in reversed(overlapping):
            port_tag = next(
                (tag for tag in self.system_builder_canvas.gettags(canvas_item) if tag.startswith("port:")),
                None,
            )
            if not port_tag:
                continue
            _prefix, component_id, direction = port_tag.split(":", 2)
            if ((expected_direction == "in" and not direction.startswith("in"))
                    or (expected_direction == "out" and not self._system_port_is_output(direction))
                    or component_id == origin_id):
                continue
            hover_fill = (
                "#90caf9" if direction.startswith("in")
                else "#ffcc80" if direction == "overflow"
                else "#ef9a9a"
            )
            for port_item in self.system_builder_canvas.find_withtag(
                f"port:{component_id}:{direction}"
            ):
                if self.system_builder_canvas.type(port_item) == "oval":
                    self.system_builder_canvas.itemconfigure(port_item, fill=hover_fill)
            self.system_builder_hover_port = (component_id, direction)
            break

    def _resize_selected_system_object(self, event: tk.Event) -> None:
        state = self.system_builder_resize_state
        if state is None:
            return
        component_id, corner, original_x, original_y, original_width, original_height, press_x, press_y = state
        item = self._system_layout_item(str(component_id))
        if item is None:
            return
        model_x, model_y = self._system_model_point(event.x, event.y)
        dx, dy = model_x - float(press_x), model_y - float(press_y)
        left = float(original_x) - float(original_width) / 2.0
        right = float(original_x) + float(original_width) / 2.0
        top = float(original_y) - float(original_height) / 2.0
        bottom = float(original_y) + float(original_height) / 2.0
        if "w" in str(corner):
            left = min(left + dx, right - 80.0)
        else:
            right = max(right + dx, left + 80.0)
        if "n" in str(corner):
            top = min(top + dy, bottom - 44.0)
        else:
            bottom = max(bottom + dy, top + 44.0)
        width, height = self._system_canvas_dimensions()
        if left < 3.0 or right > width - 3.0 or top < 3.0 or bottom > height - 3.0:
            return
        new_width, new_height = right - left, bottom - top
        new_x, new_y = (left + right) / 2.0, (top + bottom) / 2.0
        if self._system_position_overlaps(
            new_x,
            new_y,
            width=new_width,
            height=new_height,
            exclude_id=str(component_id),
        ):
            return
        item.update({"x": new_x, "y": new_y, "width": new_width, "height": new_height})
        self._render_system_builder()

    @staticmethod
    def _connections_after_node_disconnect(
        connections: list[dict[str, str]], component_id: str, direction: str | None
    ) -> list[dict[str, str]]:
        if direction == "in":
            return [
                item for item in connections
                if item.get("target_component") != component_id
                or item.get("target_port", "in") != "in"
            ]
        if direction == "in2":
            return [
                item for item in connections
                if item.get("target_component") != component_id
                or item.get("target_port", "in") != "in2"
            ]
        if direction == "out":
            return [
                item for item in connections
                if item.get("source_component") != component_id
                or item.get("source_port", "out") != "out"
            ]
        if direction == "out2":
            return [
                item for item in connections
                if item.get("source_component") != component_id
                or item.get("source_port", "out") != "out2"
            ]
        if direction == "overflow":
            return [
                item for item in connections
                if item.get("source_component") != component_id
                or item.get("source_port", "out") != "overflow"
            ]
        return [
            item for item in connections
            if item.get("source_component") != component_id
            and item.get("target_component") != component_id
        ]

    def _start_system_connection_from_node(self, component_id: str, direction: str) -> None:
        self.system_builder_selected_id = component_id
        self.system_builder_selected_connection = None
        self.system_builder_port_drag = None
        if self._system_port_is_output(direction):
            self.system_builder_pending_source = component_id
            self.system_builder_pending_source_port = direction
            self.system_builder_pending_target = None
        else:
            self.system_builder_pending_target = component_id
            self.system_builder_pending_target_port = direction
            self.system_builder_pending_source = None
        self._render_system_builder()

    def _disconnect_system_node(self, component_id: str, direction: str | None) -> None:
        before = len(self.config_model.system_connections)
        self.config_model.system_connections = self._connections_after_node_disconnect(
            self.config_model.system_connections, component_id, direction
        )
        removed = before - len(self.config_model.system_connections)
        self.system_builder_selected_connection = None
        self.system_builder_pending_source = None
        self.system_builder_pending_target = None
        self.system_builder_port_drag = None
        self._clear_system_port_drag_hover()
        node_label = {
            "in": "input node", "in2": "second input node",
            "out": "output node", "out2": "second output node",
            "overflow": "overflow outlet", None: "object",
        }[direction]
        self.status_var.set(f"Disconnected {removed} connection(s) from the {node_label}")
        self._render_system_builder()

    def _system_node_context_menu(self, event: tk.Event) -> str | None:
        overlapping = self.system_builder_canvas.find_overlapping(
            event.x - 2, event.y - 2, event.x + 2, event.y + 2
        )
        port: tuple[str, str] | None = None
        for canvas_item in reversed(overlapping):
            port_tag = next(
                (tag for tag in self.system_builder_canvas.gettags(canvas_item) if tag.startswith("port:")),
                None,
            )
            if port_tag:
                _prefix, component_id, direction = port_tag.split(":", 2)
                port = (component_id, direction)
                break
        if port is None:
            return None
        component_id, direction = port
        output_port = self._system_port_is_output(direction)
        node_key = "source_component" if output_port else "target_component"
        node_connections = sum(
            connection.get(node_key) == component_id
            and (
                (output_port and connection.get("source_port", "out") == direction)
                or (direction.startswith("in") and connection.get("target_port", "in") == direction)
            )
            for connection in self.config_model.system_connections
        )
        object_connections = sum(
            connection.get("source_component") == component_id
            or connection.get("target_component") == component_id
            for connection in self.config_model.system_connections
        )
        menu = tk.Menu(self, tearoff=False)
        menu.add_command(
            label="Start connection from this node",
            command=lambda: self._start_system_connection_from_node(component_id, direction),
        )
        menu.add_separator()
        menu.add_command(
            label=f"Disconnect this node ({node_connections})",
            state=tk.NORMAL if node_connections else tk.DISABLED,
            command=lambda: self._disconnect_system_node(component_id, direction),
        )
        menu.add_command(
            label=f"Disconnect all object connections ({object_connections})",
            state=tk.NORMAL if object_connections else tk.DISABLED,
            command=lambda: self._disconnect_system_node(component_id, None),
        )
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()
        return "break"

    def _system_multi_select_changed(self) -> None:
        if not self.system_multi_select_var.get():
            self.system_builder_selected_ids.clear()
            self.system_geometry_status_var.set("Turn on multi-select, then choose two or more objects.")
        else:
            self.system_builder_selected_id = None
            self.system_geometry_status_var.set("Click objects on the canvas to add or remove them.")
        self._render_system_builder()

    def clear_system_geometry_selection(self) -> None:
        self.system_builder_selected_ids.clear()
        self.system_geometry_status_var.set("0 objects selected.")
        self._render_system_builder()

    def align_selected_system_objects_horizontally(self) -> None:
        items = [
            item for item in self.config_model.system_layout
            if str(item.get("id")) in self.system_builder_selected_ids
        ]
        if len(items) < 2:
            self.system_geometry_status_var.set("Select at least two objects to align.")
            return
        items.sort(key=lambda item: float(item.get("x", 0.0)))
        canvas_width, canvas_height = self._system_canvas_dimensions()
        target_y = sum(float(item.get("y", 0.0)) for item in items) / len(items)
        max_height = max(float(item.get("height", 60.0)) for item in items)
        target_y = min(max(target_y, max_height / 2.0 + 3.0), canvas_height - max_height / 2.0 - 3.0)
        widths = [float(item.get("width", 124.0)) for item in items]
        planned_x = [float(items[0].get("x", 0.0))]
        for index in range(1, len(items)):
            minimum_x = planned_x[-1] + widths[index - 1] / 2.0 + widths[index] / 2.0 + 8.0
            planned_x.append(max(float(items[index].get("x", 0.0)), minimum_x))
        left_edge = planned_x[0] - widths[0] / 2.0
        right_edge = planned_x[-1] + widths[-1] / 2.0
        shift = 0.0
        if left_edge < 3.0:
            shift = 3.0 - left_edge
        if right_edge + shift > canvas_width - 3.0:
            shift += canvas_width - 3.0 - (right_edge + shift)
        planned_x = [value + shift for value in planned_x]
        if planned_x[0] - widths[0] / 2.0 < 3.0:
            self.system_geometry_status_var.set("The selected objects do not fit horizontally on the canvas.")
            return
        selected_ids = {str(item.get("id")) for item in items}
        for item, x, item_width in zip(items, planned_x, widths):
            item_height = float(item.get("height", 60.0))
            for other in self.config_model.system_layout:
                if str(other.get("id")) in selected_ids:
                    continue
                if self._system_rectangles_overlap(
                    x, target_y, item_width, item_height,
                    float(other.get("x", 0.0)), float(other.get("y", 0.0)),
                    float(other.get("width", 124.0)), float(other.get("height", 60.0)),
                ):
                    self.system_geometry_status_var.set(
                        "Alignment is blocked by an unselected object; move it or include it in the selection."
                    )
                    return
        for item, x in zip(items, planned_x):
            item["x"], item["y"] = x, target_y
        self.system_geometry_status_var.set(f"Aligned {len(items)} objects horizontally.")
        self._render_system_builder()

    def _cancel_system_link(self, _event: tk.Event | None = None) -> str:
        self.system_builder_pending_source = None
        self.system_builder_pending_target = None
        self.system_builder_port_drag = None
        self._render_system_builder()
        return "break"

    def delete_selected_system_component(self) -> None:
        if self.system_builder_selected_connection is not None:
            selected = self.system_builder_selected_connection
            self.config_model.system_connections = [
                connection for connection in self.config_model.system_connections if connection is not selected
            ]
            self.system_builder_selected_connection = None
            self._render_system_builder()
            return
        if self.system_builder_selected_id is None:
            return
        removed_id = self.system_builder_selected_id
        self.config_model.system_layout = [
            item for item in self.config_model.system_layout
            if str(item.get("id")) != removed_id
        ]
        self.config_model.system_connections = [
            connection for connection in self.config_model.system_connections
            if connection.get("source_component") != removed_id
            and connection.get("target_component") != removed_id
        ]
        self.system_component_editor_drafts.pop(removed_id, None)
        self.system_builder_selected_id = None
        self._render_system_builder()

    @staticmethod
    def _system_component_editor_field_names(component_type: str) -> tuple[str, ...]:
        return {
            "primary_tank": (
                "selected_tank_size", "initial_fill", "reserve", "graph_start",
                "graph_end", "graph_step", "graph_auto_step_count",
            ),
            "filtration_pump": ("transfer_pump_type", "filtration_system_flow_gpm"),
            "filtration_system": (
                "filtration_system_flow_gpm", "filtration_system_count", "filter_recovery"
            ),
            "booster_tank": (
                "booster_tank_size", "booster_initial_fill", "booster_refill_level",
            ),
            "booster_pump": ("pump_capacity",),
            "municipal_backup": ("municipal_backup_enabled",),
            "first_flush_diversion": (
                "first_flush_sizing_method", "first_flush_design_preset",
                "first_flush_antecedent", "first_flush_antecedent_unit",
            ),
        }.get(component_type, ())

    def _system_component_editor_snapshot(
        self, item: dict[str, object]
    ) -> dict[str, object]:
        component_type = str(item.get("component_type", ""))
        values: dict[str, object] = {"name": self.system_component_name_var.get()}
        for field in self._system_component_editor_field_names(component_type):
            values[field] = self.system_component_parameter_vars[field].get()
        return values

    def _system_component_model_snapshot(
        self, item: dict[str, object]
    ) -> dict[str, object]:
        cfg = self.config_model
        component_type = str(item.get("component_type", ""))
        values: dict[str, object] = {"name": str(item.get("name", ""))}
        if component_type == "primary_tank":
            values.update({
                "selected_tank_size": format_number(volume_to_display(cfg.selected_tank_size_gal, cfg), cfg, max_decimal_places=0),
                "initial_fill": format_number(cfg.tank_parameters.initial_fill_percent, cfg),
                "reserve": format_number(cfg.tank_parameters.minimum_operating_volume_percent, cfg),
                "graph_start": format_number(volume_to_display(cfg.graph_start_gal, cfg), cfg, max_decimal_places=0),
                "graph_end": format_number(volume_to_display(cfg.graph_end_gal, cfg), cfg, max_decimal_places=0),
                "graph_step": format_number(volume_to_display(cfg.graph_step_gal, cfg), cfg, max_decimal_places=0),
                "graph_auto_step_count": format_number(cfg.graph_auto_step_count, cfg, max_decimal_places=0),
            })
        elif component_type == "filtration_pump":
            values["transfer_pump_type"] = cfg.system_parameters.transfer_pump_type
            values["filtration_system_flow_gpm"] = (
                "Infinite" if cfg.system_parameters.filtration_system_flow_gpm == 0
                else str(
                    cfg.system_parameters.filtration_system_flow_gpm
                    * cfg.system_parameters.filtration_system_count
                )
            )
        elif component_type == "filtration_system":
            values["filtration_system_flow_gpm"] = (
                "Infinite" if cfg.system_parameters.filtration_system_flow_gpm == 0
                else str(cfg.system_parameters.filtration_system_flow_gpm)
            )
            values["filtration_system_count"] = str(
                cfg.system_parameters.filtration_system_count
            )
            values["filter_recovery"] = format_number(cfg.system_parameters.filter_recovery_percent, cfg)
        elif component_type == "booster_tank":
            values.update({
                "booster_tank_size": format_number(volume_to_display(cfg.system_parameters.booster_tank_size_gallons, cfg), cfg),
                "booster_initial_fill": format_number(cfg.system_parameters.booster_initial_fill_percent, cfg),
                "booster_refill_level": format_number(cfg.system_parameters.booster_refill_level_percent, cfg),
            })
        elif component_type == "booster_pump":
            values["pump_capacity"] = (
                format_number(volume_to_display(cfg.system_parameters.pump_capacity_gallons_per_hour, cfg) / 60.0, cfg)
            )
        elif component_type == "municipal_backup":
            values["municipal_backup_enabled"] = bool(
                cfg.system_parameters.municipal_backup_enabled
            )
        elif component_type == "first_flush_diversion":
            sizing_method = normalize_first_flush_sizing_method(
                item.get("sizing_method", cfg.first_flush_sizing_method)
            )
            design_preset = normalize_first_flush_design_preset(
                item.get("design_preset", cfg.first_flush_design_preset)
            )
            antecedent_days = max(float(item.get(
                "antecedent_dry_days", cfg.first_flush_antecedent_dry_days
            )), 0.0)
            antecedent_unit = str(item.get(
                "antecedent_dry_unit", cfg.first_flush_antecedent_dry_unit
            )).casefold()
            if antecedent_unit not in {"days", "hours"}:
                antecedent_unit = "days"
            values.update({
                "first_flush_sizing_method": SIZING_METHOD_LABELS[
                    sizing_method
                ],
                "first_flush_design_preset": DESIGN_PRESET_LABELS[
                    design_preset
                ],
                "first_flush_antecedent": f"{_antecedent_dry_period_from_days(antecedent_days, antecedent_unit):g}",
                "first_flush_antecedent_unit": antecedent_unit,
            })
        return values

    def _load_system_component_editor_values(
        self, item: dict[str, object], values: dict[str, object]
    ) -> None:
        self.system_component_editor_loading = True
        try:
            self.system_component_name_var.set(str(values.get("name", "")))
            component_type = str(item.get("component_type", ""))
            for field in self._system_component_editor_field_names(component_type):
                variable = self.system_component_parameter_vars[field]
                value = values.get(field, False if isinstance(variable, tk.BooleanVar) else "")
                variable.set(value)
        finally:
            self.system_component_editor_loading = False

    def _update_system_component_editor_state(self, *, restored: bool = False) -> None:
        item = self._system_layout_item(self.system_component_editor_loaded_id or "")
        if item is None:
            self.apply_system_component_name_button.state(["disabled"])
            self.system_component_validation_var.set("")
            return
        values = self._system_component_editor_snapshot(item)
        dirty = values != self.system_component_editor_baseline
        component_id = str(item.get("id", ""))
        if dirty:
            self.system_component_editor_drafts[component_id] = values
        else:
            self.system_component_editor_drafts.pop(component_id, None)
        component_type_key = str(item.get("component_type", ""))
        errors = _system_object_editor_validation(component_type_key, values)
        self.system_component_validation_var.set("\n".join(errors))
        self.apply_system_component_name_button.state(
            ["!disabled"] if dirty and not errors else ["disabled"]
        )
        component_type = self._system_component_templates().get(
            component_type_key, component_type_key or "System object"
        )
        if errors:
            suffix = " — fix the validation message below."
        elif dirty:
            suffix = " — unapplied changes restored." if restored else " — unapplied changes."
        else:
            suffix = ""
        self.system_component_edit_status_var.set(f"Object type: {component_type}{suffix}")

    def _system_component_editor_field_changed(self, *_args: object) -> None:
        if self.system_component_editor_loading or self.system_component_editor_loaded_id is None:
            return
        self._update_system_component_editor_state()

    def _system_component_graph_step_changed(self, *_args: object) -> None:
        if (
            self.system_component_editor_loading
            or self.system_component_editor_loaded_id is None
            or getattr(self, "system_component_graph_step_autosizing", False)
        ):
            return
        item = self._system_layout_item(self.system_component_editor_loaded_id)
        if item is None or str(item.get("component_type")) != "primary_tank":
            return
        values = self._system_component_editor_snapshot(item)
        try:
            start = float(str(values["graph_start"]).replace(",", ""))
            end = float(str(values["graph_end"]).replace(",", ""))
            step = float(str(values["graph_step"]).replace(",", ""))
        except ValueError:
            return
        step_count = _graph_step_count(start, end, step)
        if step_count is None:
            return
        step_count_var = self.system_component_parameter_vars["graph_auto_step_count"]
        if step_count_var.get() != str(step_count):
            step_count_var.set(str(step_count))

    def _refresh_system_component_editor(self, *, force_reload: bool = False) -> None:
        if not hasattr(self, "system_component_name_entry"):
            return
        if self.system_component_editor_model is not self.config_model:
            self.system_component_editor_model = self.config_model
            self.system_component_editor_drafts.clear()
            self.system_component_editor_loaded_id = None
        item = (
            self._system_layout_item(self.system_builder_selected_id)
            if self.system_builder_selected_id is not None
            else None
        )
        for frame in self.system_parameter_frames.values():
            frame.grid_remove()
        self.system_municipal_backup_editor.grid_remove()
        if item is None:
            self.system_component_editor_loaded_id = None
            self.system_component_editor_baseline = {}
            self.system_component_editor_loading = True
            self.system_component_name_var.set("")
            self.system_component_editor_loading = False
            self.system_component_name_entry.state(["disabled"])
            self.apply_system_component_name_button.state(["disabled"])
            self.system_component_edit_status_var.set("Select a system object to edit.")
            self.system_component_validation_var.set("")
            self.system_component_parameters_editor.grid_remove()
            self.system_end_uses_editor.grid_remove()
            return
        component_id = str(item.get("id", ""))
        restored = False
        if force_reload or component_id != self.system_component_editor_loaded_id:
            model_values = self._system_component_model_snapshot(item)
            values = self.system_component_editor_drafts.get(component_id, model_values)
            restored = component_id in self.system_component_editor_drafts
            self.system_component_editor_loaded_id = component_id
            self.system_component_editor_baseline = model_values
            self._load_system_component_editor_values(item, values)
        self.system_component_name_entry.state(["!disabled"])
        component_type_key = str(item.get("component_type", ""))
        self.system_component_parameters_editor.grid()
        parameter_frame = self.system_parameter_frames.get(component_type_key)
        if parameter_frame is not None:
            parameter_frame.grid()
            if component_type_key == "first_flush_diversion":
                self._refresh_first_flush_guidance()
                self._refresh_first_flush_surface_editor()
        elif component_type_key == "municipal_backup":
            self.system_municipal_backup_editor.grid()
        if component_type_key == "end_uses":
            self.system_end_uses_editor.grid()
            self._refresh_end_uses_demand_editor(item)
        else:
            self.system_end_uses_editor.grid_remove()
        self._update_system_component_editor_state(restored=restored)

    def _refresh_first_flush_surface_editor(self) -> None:
        if not hasattr(self, "first_flush_surface_combo"):
            return
        names = [
            f"{index + 1}. {surface.name}"
            for index, surface in enumerate(self.config_model.surfaces)
        ]
        self._first_flush_surface_indices = {
            label: index for index, label in enumerate(names)
        }
        self.first_flush_surface_combo.configure(values=names)
        selected = self.first_flush_surface_selection_var.get()
        if selected not in names:
            selected = names[0] if names else ""
            self.first_flush_surface_selection_var.set(selected)
        self.first_flush_surface_depth_unit_var.set(precip_unit(self.config_model))
        self._first_flush_surface_changed()

    def _first_flush_surface_changed(self, _event: tk.Event | None = None) -> None:
        selected = self.first_flush_surface_selection_var.get()
        index = getattr(self, "_first_flush_surface_indices", {}).get(selected)
        surface = (
            self.config_model.surfaces[index]
            if index is not None and 0 <= index < len(self.config_model.surfaces)
            else None
        )
        self.first_flush_surface_depth_var.set(
            "" if surface is None else format_number(
                precip_to_display(surface.first_flush_depth_inches, self.config_model),
                self.config_model,
                max_decimal_places=3,
            )
        )

    def _apply_first_flush_surface_depth(self) -> None:
        selected = self.first_flush_surface_selection_var.get()
        index = getattr(self, "_first_flush_surface_indices", {}).get(selected)
        surface = (
            self.config_model.surfaces[index]
            if index is not None and 0 <= index < len(self.config_model.surfaces)
            else None
        )
        if surface is None:
            return
        try:
            displayed_depth = parse_number(self.first_flush_surface_depth_var.get())
        except ValueError:
            self.status_var.set("Enter a valid first-flush diversion depth")
            return
        surface.first_flush_depth_inches = max(
            precip_to_internal(displayed_depth, self.config_model), 0.0
        )
        self._populate_surfaces()
        self._refresh_project_dirty_state()
        self.status_var.set(f"Updated first-flush depth for {surface.name}")

    def _refresh_end_uses_demand_editor(self, item: dict[str, object]) -> None:
        demand_objects = self.config_model.demand.demand_objects
        assigned = _normalized_demand_object_indices(
            item.get("demand_object_indices"), len(demand_objects)
        )
        item["demand_object_indices"] = assigned
        self._system_available_demand_indices = [
            index for index in range(len(demand_objects)) if index not in assigned
        ]
        self._system_assigned_demand_indices = assigned
        self.system_available_demands_list.delete(0, tk.END)
        self.system_assigned_demands_list.delete(0, tk.END)
        for index in self._system_available_demand_indices:
            self.system_available_demands_list.insert(tk.END, demand_objects[index].name)
        for index in self._system_assigned_demand_indices:
            self.system_assigned_demands_list.insert(tk.END, demand_objects[index].name)
        self.system_add_demand_button.state(
            ["!disabled"] if self._system_available_demand_indices else ["disabled"]
        )
        self.system_remove_demand_button.state(
            ["!disabled"] if self._system_assigned_demand_indices else ["disabled"]
        )

    def add_demand_to_selected_end_uses(self) -> None:
        item = self._system_layout_item(self.system_builder_selected_id or "")
        selected = self.system_available_demands_list.curselection()
        if item is None or str(item.get("component_type")) != "end_uses" or not selected:
            return
        demand_index = self._system_available_demand_indices[selected[0]]
        assigned = _normalized_demand_object_indices(
            item.get("demand_object_indices"), len(self.config_model.demand.demand_objects)
        )
        if demand_index not in assigned:
            assigned.append(demand_index)
        item["demand_object_indices"] = assigned
        self._render_system_builder()

    def remove_demand_from_selected_end_uses(self) -> None:
        item = self._system_layout_item(self.system_builder_selected_id or "")
        selected = self.system_assigned_demands_list.curselection()
        if item is None or str(item.get("component_type")) != "end_uses" or not selected:
            return
        demand_index = self._system_assigned_demand_indices[selected[0]]
        item["demand_object_indices"] = [
            index
            for index in _normalized_demand_object_indices(
                item.get("demand_object_indices"), len(self.config_model.demand.demand_objects)
            )
            if index != demand_index
        ]
        self._render_system_builder()

    def apply_system_component_name(self) -> None:
        if self.system_builder_selected_id is None:
            return
        item = self._system_layout_item(self.system_builder_selected_id)
        if item is None:
            return
        values = self._system_component_editor_snapshot(item)
        component_type = str(item.get("component_type", ""))
        errors = _system_object_editor_validation(component_type, values)
        if errors:
            self.system_component_validation_var.set("\n".join(errors))
            return
        if values == self.system_component_editor_baseline:
            return
        number = lambda field: float(str(values[field]).strip().replace(",", ""))
        cfg = self.config_model
        cfg.unit_system = normalize_unit_system(self.unit_var.get())
        item["name"] = str(values["name"]).strip()
        if component_type == "primary_tank":
            cfg.selected_tank_size_gal = volume_to_internal(number("selected_tank_size"), cfg)
            cfg.tank_parameters.initial_fill_percent = number("initial_fill")
            cfg.tank_parameters.minimum_operating_volume_percent = number("reserve")
            cfg.graph_start_gal = max(1, int(round(volume_to_internal(number("graph_start"), cfg))))
            cfg.graph_end_gal = max(2, int(round(volume_to_internal(number("graph_end"), cfg))))
            cfg.graph_step_gal = max(1, int(round(volume_to_internal(number("graph_step"), cfg))))
            cfg.graph_auto_step_count = int(number("graph_auto_step_count"))
            self.selected_tank_var.set(str(values["selected_tank_size"]))
            self.initial_fill_var.set(str(values["initial_fill"]))
            self.reserve_var.set(str(values["reserve"]))
            self.graph_start_var.set(str(values["graph_start"]))
            self.graph_end_var.set(str(values["graph_end"]))
            self.graph_step_var.set(str(values["graph_step"]))
            self.graph_auto_step_count_var.set(str(values["graph_auto_step_count"]))
        elif component_type == "filtration_pump":
            cfg.system_parameters.transfer_pump_type = str(values["transfer_pump_type"])
            cfg.system_parameters.synchronize_filtration_flow()
            self.transfer_pump_type_var.set(cfg.system_parameters.transfer_pump_type)
        elif component_type == "filtration_system":
            cfg.system_parameters.filtration_system_flow_gpm = (
                normalize_filtration_system_flow_gpm(values["filtration_system_flow_gpm"])
            )
            cfg.system_parameters.filtration_system_count = int(
                number("filtration_system_count")
            )
            cfg.system_parameters.synchronize_filtration_flow()
            flow_label = (
                "Infinite" if cfg.system_parameters.filtration_system_flow_gpm == 0
                else str(cfg.system_parameters.filtration_system_flow_gpm)
            )
            self.filtration_system_flow_gpm_var.set(flow_label)
            self.filtration_pump_capacity_var.set(flow_label)
            self.filtration_system_count_var.set(
                str(cfg.system_parameters.filtration_system_count)
            )
            cfg.system_parameters.filter_recovery_percent = number("filter_recovery")
            self.filter_recovery_var.set(str(values["filter_recovery"]))
        elif component_type == "booster_tank":
            cfg.system_parameters.booster_tank_size_gallons = volume_to_internal(
                number("booster_tank_size"), cfg
            )
            cfg.system_parameters.booster_initial_fill_percent = number("booster_initial_fill")
            cfg.system_parameters.booster_refill_level_percent = number("booster_refill_level")
            self.booster_tank_size_var.set(str(values["booster_tank_size"]))
            self.booster_initial_fill_var.set(str(values["booster_initial_fill"]))
            self.booster_refill_level_var.set(str(values["booster_refill_level"]))
        elif component_type == "booster_pump":
            cfg.system_parameters.pump_capacity_gallons_per_hour = volume_to_internal(
                number("pump_capacity") * 60.0, cfg
            )
            self.pump_capacity_var.set(str(values["pump_capacity"]))
        elif component_type == "municipal_backup":
            enabled = bool(values["municipal_backup_enabled"])
            cfg.system_parameters.municipal_backup_enabled = enabled
            self.municipal_backup_enabled_var.set(enabled)
        elif component_type == "first_flush_diversion":
            cfg.first_flush_sizing_method = self._selected_first_flush_sizing_method()
            cfg.first_flush_design_preset = self._selected_first_flush_design_preset()
            unit = str(values["first_flush_antecedent_unit"]).casefold()
            cfg.first_flush_antecedent_dry_unit = unit
            cfg.first_flush_antecedent_dry_days = max(
                _antecedent_dry_period_to_days(number("first_flush_antecedent"), unit),
                0.0,
            )
            item.update({
                "sizing_method": cfg.first_flush_sizing_method,
                "design_preset": cfg.first_flush_design_preset,
                "antecedent_dry_days": cfg.first_flush_antecedent_dry_days,
                "antecedent_dry_unit": cfg.first_flush_antecedent_dry_unit,
            })

        component_id = str(item.get("id", ""))
        self.system_component_editor_drafts.pop(component_id, None)
        self.system_component_editor_baseline = dict(values)
        self.apply_system_component_name_button.state(["disabled"])
        self.system_component_validation_var.set("")
        self._render_system_builder()
        component_label = self._system_component_templates().get(component_type, component_type)
        self.system_component_edit_status_var.set(
            f"Object type: {component_label} - changes applied."
        )
        self.status_var.set(f"Applied changes to {item['name']}")

    def _system_builder_view_changed(self) -> None:
        view = self._normalized_system_builder_view(self.system_builder_view_var.get())
        self.system_builder_view_var.set(view)
        self._render_system_builder()
        self.status_var.set(
            "System builder view: " + ("icon graph" if view == "icon-graph" else "block graph")
        )

    @staticmethod
    def _normalized_system_builder_view(value: object) -> str:
        """Return a supported builder presentation without affecting project data."""
        return "block-graph" if str(value) == "block-graph" else "icon-graph"
    def _apply_system_component_name_from_event(self, _event: tk.Event) -> str:
        self.apply_system_component_name()
        return "break"

    def _auto_set_system_component_graph_step(self) -> None:
        item = self._system_layout_item(self.system_builder_selected_id or "")
        if item is None or str(item.get("component_type")) != "primary_tank":
            return
        values = self._system_component_editor_snapshot(item)
        try:
            start = float(str(values["graph_start"]).replace(",", ""))
            end = float(str(values["graph_end"]).replace(",", ""))
            step_count_value = float(str(values["graph_auto_step_count"]).replace(",", ""))
        except ValueError:
            self._update_system_component_editor_state()
            return
        if not step_count_value.is_integer() or step_count_value < 1 or end <= start:
            self._update_system_component_editor_state()
            return
        step = max((end - start) / int(step_count_value), 1.0)
        self.system_component_graph_step_autosizing = True
        try:
            self.system_component_parameter_vars["graph_step"].set(
                format_number(step, max_decimal_places=0)
            )
        finally:
            self.system_component_graph_step_autosizing = False

    @staticmethod
    def _system_connection_points(
        source_x: float,
        source_y: float,
        target_x: float,
        target_y: float,
        canvas_height: float,
        source_width: float = 124.0,
        target_width: float = 124.0,
        source_height: float = 60.0,
        target_height: float = 60.0,
    ) -> tuple[float, ...]:
        """Route a connection to the target's left port without crossing either object."""
        # Use the centers of the visible port circles. Keeping the former extra
        # six-pixel extension made normally adjacent ports geometrically cross,
        # which incorrectly selected the backward/U-shaped route.
        start_x = source_x + source_width / 2.0 + 3.0
        end_x = target_x - target_width / 2.0 - 3.0
        if target_x > source_x:
            if abs(target_y - source_y) < 0.001:
                return (start_x, source_y, end_x, target_y)
            midpoint = (start_x + end_x) / 2.0
            return (start_x, source_y, midpoint, source_y, midpoint, target_y, end_x, target_y)

        source_rail_x = start_x + 24.0
        target_rail_x = end_x - 24.0
        if abs(target_y - source_y) >= (source_height + target_height) / 2.0 + 24.0:
            # When the blocks have a clear vertical gap, route through that gap. For a
            # source above its target this reads naturally as right, down, left, down,
            # then right into the target's inlet instead of looping over both blocks.
            corridor_y = (source_y + target_y) / 2.0
        else:
            corridor_offset = max(source_height, target_height) / 2.0 + 22.0
            upper_corridor = min(source_y, target_y) - corridor_offset
            lower_corridor = max(source_y, target_y) + corridor_offset
            if upper_corridor >= 10.0:
                corridor_y = upper_corridor
            elif lower_corridor <= max(canvas_height - 10.0, 10.0):
                corridor_y = lower_corridor
            else:
                corridor_y = upper_corridor
        return (
            start_x,
            source_y,
            source_rail_x,
            source_y,
            source_rail_x,
            corridor_y,
            target_rail_x,
            corridor_y,
            target_rail_x,
            target_y,
            end_x,
            target_y,
        )

    @staticmethod
    def _system_builder_icon_assets() -> dict[str, str]:
        return {
            "rainwater_input": "assets/bootstrap-icons/cloud-rain.svg",
            "primary_tank": "assets/tabler-icons/cylinder.svg",
            "filtration_pump": "assets/bootstrap-icons/arrow-right-circle-fill.svg",
            "filtration_system": "assets/bootstrap-icons/filter-square.svg",
            "booster_tank": "assets/tabler-icons/cylinder.svg",
            "booster_pump": "assets/bootstrap-icons/speedometer2.svg",
            "municipal_backup": "assets/bootstrap-icons/buildings-fill.svg",
            "end_uses": "assets/bootstrap-icons/house-door-fill.svg",
            "first_flush_diversion": "assets/bootstrap-icons/funnel-fill.svg",
            "overflow_pipe": "assets/bootstrap-icons/box-arrow-down-right.svg",
        }

    def _system_builder_node_image(
        self,
        component_type: str,
        width: float,
        height: float,
        *,
        fill: str,
        outline: str,
        line_width: int,
    ) -> ImageTk.PhotoImage:
        zoom = max(float(self.system_builder_zoom), 0.01)
        target_width = max(round(float(width) * zoom), 1)
        target_height = max(round(float(height) * zoom), 1)
        cache_key = (
            component_type, target_width, target_height, fill, outline, line_width
        )
        cached = self.system_builder_node_images.get(cache_key)
        if cached is not None:
            return cached
        if len(self.system_builder_node_images) >= 256:
            self.system_builder_node_images.clear()

        supersample = 4
        render_width = target_width * supersample
        render_height = target_height * supersample
        image = Image.new("RGBA", (render_width, render_height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        stroke_width = max(round(line_width * zoom * supersample), 1)
        inset = stroke_width / 2.0
        radius = min(
            12.0 * zoom * supersample,
            render_width / 5.0,
            render_height / 4.0,
        )
        draw.rounded_rectangle(
            (inset, inset, render_width - inset - 1, render_height - inset - 1),
            radius=radius,
            fill=fill,
            outline=outline,
            width=stroke_width,
        )

        asset_relative_path = self._system_builder_icon_assets().get(component_type)
        if asset_relative_path is not None:
            asset_path = _resource_path(asset_relative_path)
            if asset_path.is_file():
                svg = asset_path.read_text(encoding="utf-8").replace("currentColor", outline)
                icon_size = max(round(28.0 * zoom * supersample), 4)
                icon_png = resvg_py.svg_to_bytes(
                    svg_string=svg,
                    width=icon_size,
                    height=icon_size,
                    skip_system_fonts=True,
                )
                with Image.open(io.BytesIO(icon_png)) as icon_source:
                    icon = icon_source.convert("RGBA")
                center_y = render_height / 2.0 - 10.0 * zoom * supersample
                icon_left = round((render_width - icon.width) / 2.0)
                icon_top = round(center_y - icon.height / 2.0)
                image.alpha_composite(icon, (icon_left, icon_top))

        if supersample > 1:
            image = image.resize(
                (target_width, target_height), Image.Resampling.LANCZOS
            )
        photo = ImageTk.PhotoImage(image, master=self)
        self.system_builder_node_images[cache_key] = photo
        return photo

    def _render_system_builder(self) -> None:
        if not hasattr(self, "system_builder_canvas"):
            return
        self._resize_system_builder_canvas_to_objects()
        raw_canvas = self.system_builder_canvas
        raw_canvas.delete("all")
        canvas = _ScaledCanvasProxy(
            raw_canvas,
            self.system_builder_zoom,
            self.system_builder_pan_x,
            self.system_builder_pan_y,
        )
        self.system_builder_hover_port = None
        layout_by_id = {str(item.get("id")): item for item in self.config_model.system_layout}
        view_mode = self._normalized_system_builder_view(
            self.system_builder_view_var.get() if hasattr(self, "system_builder_view_var") else None
        )
        for index, connection in enumerate(self.config_model.system_connections):
            source = layout_by_id.get(connection.get("source_component", ""))
            target = layout_by_id.get(connection.get("target_component", ""))
            if source is None or target is None:
                continue
            source_x, source_y = float(source.get("x", 0.0)), float(source.get("y", 0.0))
            target_x, target_y = float(target.get("x", 0.0)), float(target.get("y", 0.0))
            if source.get("component_type") == "primary_tank":
                source_y += self._primary_tank_outlet_offset(
                    source, str(connection.get("source_port", "out"))
                )
            if target.get("component_type") == "booster_tank" and target.get("extra_input_node"):
                target_y += 14.0 if connection.get("target_port") == "in2" else -14.0
            selected = connection is self.system_builder_selected_connection
            canvas.create_line(
                *self._system_connection_points(
                    source_x,
                    source_y,
                    target_x,
                    target_y,
                    self._system_canvas_dimensions()[1],
                    float(source.get("width", 124.0)),
                    float(target.get("width", 124.0)),
                    float(source.get("height", 60.0)),
                    float(target.get("height", 60.0)),
                ),
                fill="#1565c0" if selected else "#58656b",
                width=4 if selected else 3,
                arrow=tk.LAST,
                arrowshape=(10, 12, 5),
                tags=(f"connection:{index}",),
            )
        for item in self.config_model.system_layout:
            try:
                component_id = str(item["id"])
                component_type = str(item["component_type"])
                x, y = float(item["x"]), float(item["y"])
                object_width = max(float(item.get("width", 124.0)), 80.0)
                object_height = max(float(item.get("height", 60.0)), 44.0)
            except (KeyError, TypeError, ValueError):
                continue
            label = str(item.get("name") or self._system_component_templates().get(component_type, component_type))
            if component_type == "end_uses":
                assigned_count = len(
                    _normalized_demand_object_indices(
                        item.get("demand_object_indices"),
                        len(self.config_model.demand.demand_objects),
                    )
                )
                if assigned_count:
                    label = f"{label}\n({assigned_count} demand{'s' if assigned_count != 1 else ''})"
            selected = component_id == self.system_builder_selected_id
            geometry_selected = component_id in self.system_builder_selected_ids
            outline = "#1565c0" if selected or geometry_selected else "#30363a"
            fill = "#e8f1fb" if selected or geometry_selected else "#f7f9fa"
            tag = f"component:{component_id}"
            half_width, half_height = object_width / 2.0, object_height / 2.0
            if view_mode == "icon-graph":
                node_image = self._system_builder_node_image(
                    component_type, object_width, object_height,
                    fill=fill, outline=outline,
                    line_width=3 if selected or geometry_selected else 2,
                )
                canvas.create_image(x, y, image=node_image, tags=(tag,))
                canvas.create_text(
                    x, y + 17, text=label, width=max(object_width - 10.0, 70.0),
                    justify="center", font=("Segoe UI", 8, "bold"), tags=(tag,)
                )
            else:
                canvas.create_rectangle(
                    x - half_width, y - half_height, x + half_width, y + half_height,
                    fill=fill, outline=outline,
                    width=3 if selected or geometry_selected else 2, tags=(tag,)
                )
                canvas.create_text(
                    x, y, text=label, width=max(object_width - 12.0, 68.0),
                    justify="center", font=("Segoe UI", 9, "bold"), tags=(tag,)
                )
            has_inlet, has_outlet = self._system_component_ports(component_type)
            if has_inlet:
                extra_inlet = component_type == "booster_tank" and bool(item.get("extra_input_node"))
                inlet_y = y - 14.0 if extra_inlet else y
                pending = (
                    component_id == self.system_builder_pending_target
                    and self.system_builder_pending_target_port == "in"
                )
                canvas.create_oval(
                    x - half_width - 10, inlet_y - 7, x - half_width + 4, inlet_y + 7,
                    fill="#90caf9" if pending else "#1565c0",
                    outline="#0d47a1", width=3 if pending else 2,
                    tags=(f"port:{component_id}:in",),
                )
                if component_type == "booster_tank":
                    second_y = y + 14.0
                    if extra_inlet:
                        second_pending = (
                            component_id == self.system_builder_pending_target
                            and self.system_builder_pending_target_port == "in2"
                        )
                        canvas.create_oval(
                            x - half_width - 10, second_y - 7,
                            x - half_width + 4, second_y + 7,
                            fill="#90caf9" if second_pending else "#1565c0",
                            outline="#0d47a1", width=3 if second_pending else 2,
                            tags=(f"port:{component_id}:in2",),
                        )
                        second_inlet_linked = any(
                            connection.get("target_component") == component_id
                            and connection.get("target_port", "in") == "in2"
                            for connection in self.config_model.system_connections
                        )
                        if not second_inlet_linked:
                            remove_tag = f"remove-inlet:{component_id}"
                            canvas.create_text(
                                x - half_width - 19, second_y, text="−",
                                fill="#c62828", font=("Segoe UI", 12, "bold"),
                                tags=(remove_tag,),
                            )
                    else:
                        affordance_tag = f"add-inlet:{component_id}"
                        canvas.create_oval(
                            x - half_width - 10, second_y - 7,
                            x - half_width + 4, second_y + 7,
                            fill="#dceaf5", outline="#6f9fbe", width=2,
                            dash=(3, 2), tags=(affordance_tag,),
                        )
                        canvas.create_text(
                            x - half_width - 19, second_y, text="+",
                            fill="#6f9fbe", font=("Segoe UI", 11, "bold"),
                            tags=(affordance_tag,),
                        )
            if has_outlet:
                extra_outlet = component_type == "primary_tank" and bool(item.get("extra_output_node"))
                outlet_y = (
                    y + self._primary_tank_outlet_offset(item, "out")
                    if component_type == "primary_tank" else y
                )
                pending = (
                    component_id == self.system_builder_pending_source
                    and self.system_builder_pending_source_port == "out"
                )
                canvas.create_oval(
                    x + half_width - 4, outlet_y - 7, x + half_width + 10, outlet_y + 7,
                    fill="#ef9a9a" if pending else "#c62828",
                    outline="#8e0000",
                    width=3 if pending else 2,
                    tags=(f"port:{component_id}:out",),
                )
                if component_type == "primary_tank":
                    second_y = y + self._primary_tank_outlet_offset(item, "out2")
                    if extra_outlet:
                        second_pending = (
                            component_id == self.system_builder_pending_source
                            and self.system_builder_pending_source_port == "out2"
                        )
                        canvas.create_oval(
                            x + half_width - 4, second_y - 7,
                            x + half_width + 10, second_y + 7,
                            fill="#ef9a9a" if second_pending else "#c62828",
                            outline="#8e0000", width=3 if second_pending else 2,
                            tags=(f"port:{component_id}:out2",),
                        )
                        second_outlet_linked = any(
                            connection.get("source_component") == component_id
                            and connection.get("source_port", "out") == "out2"
                            for connection in self.config_model.system_connections
                        )
                        if not second_outlet_linked:
                            remove_tag = f"remove-outlet:{component_id}"
                            canvas.create_text(
                                x + half_width + 19, second_y, text="-",
                                fill="#c62828", font=("Segoe UI", 12, "bold"),
                                tags=(remove_tag,),
                            )
                    else:
                        affordance_tag = f"add-outlet:{component_id}"
                        canvas.create_oval(
                            x + half_width - 4, second_y - 7,
                            x + half_width + 10, second_y + 7,
                            fill="#f5dede", outline="#b86f6f", width=2,
                            dash=(3, 2), tags=(affordance_tag,),
                        )
                        canvas.create_text(
                            x + half_width + 19, second_y, text="+",
                            fill="#b86f6f", font=("Segoe UI", 11, "bold"),
                            tags=(affordance_tag,),
                        )
                    overflow_y = y + self._primary_tank_outlet_offset(item, "overflow")
                    overflow_pending = (
                        component_id == self.system_builder_pending_source
                        and self.system_builder_pending_source_port == "overflow"
                    )
                    canvas.create_oval(
                        x + half_width - 4, overflow_y - 7,
                        x + half_width + 10, overflow_y + 7,
                        fill="#ffcc80" if overflow_pending else "#ef6c00",
                        outline="#a84300", width=3 if overflow_pending else 2,
                        tags=(f"port:{component_id}:overflow",),
                    )
                    canvas.create_text(
                        x + half_width + 22, overflow_y,
                        text="OF", fill="#a84300", font=("Segoe UI", 6, "bold"),
                        tags=(f"port:{component_id}:overflow",),
                    )
        self._refresh_system_component_editor()
        self._refresh_system_builder_warnings()

    def _refresh_system_builder_warnings(self) -> list[str]:
        warnings = validate_builder_system(
            self.config_model.system_layout,
            self.config_model.system_connections,
            municipal_backup_enabled=self.config_model.system_parameters.municipal_backup_enabled,
            demand_object_count=len(self.config_model.demand.demand_objects),
        )
        if hasattr(self, "system_builder_warning_var"):
            if warnings:
                visible = warnings[:4]
                suffix = f"\n...and {len(warnings) - 4} more warning(s)." if len(warnings) > 4 else ""
                self.system_builder_warning_var.set(
                    "System warnings:\n" + "\n".join(f"- {warning}" for warning in visible) + suffix
                )
            else:
                self.system_builder_warning_var.set("System configuration is ready for simulation.")
            if hasattr(self, "system_builder_scroll_canvas"):
                self.after_idle(self._update_system_builder_scroll_region)
        return warnings

    def _system_builder_backup_setting_changed(self) -> None:
        self.config_model.system_parameters.municipal_backup_enabled = bool(
            self.municipal_backup_enabled_var.get()
        )
        self._refresh_system_builder_warnings()

    def _show_indirect_system_schematic(self) -> None:
        dialog = tk.Toplevel(self)
        dialog.title("Indirect system schematic")
        dialog.transient(self)
        dialog.resizable(True, False)
        body = ttk.Frame(dialog, padding=12)
        body.grid(sticky="nsew")
        body.columnconfigure(0, weight=1)
        canvas = tk.Canvas(
            body,
            width=1060,
            height=250,
            background="white",
            highlightthickness=1,
            highlightbackground="#b7b7b7",
        )
        canvas.grid(row=0, column=0, sticky="ew")
        self._draw_indirect_system_diagram(canvas)
        ttk.Label(
            body,
            text="Preserved source: assets/indirect_system.svg",
            foreground="#667278",
        ).grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Button(body, text="Close", command=dialog.destroy).grid(row=2, column=0, sticky="e", pady=(10, 0))
        dialog.bind("<Escape>", lambda _event: dialog.destroy())
        dialog.update_idletasks()
        self.update_idletasks()
        x = self.winfo_rootx() + max((self.winfo_width() - dialog.winfo_reqwidth()) // 2, 0)
        y = self.winfo_rooty() + max((self.winfo_height() - dialog.winfo_reqheight()) // 2, 0)
        dialog.geometry(f"+{x}+{y}")
        dialog.lift()
        dialog.focus_force()

    def _draw_indirect_system_diagram(self, target_canvas: tk.Canvas | None = None) -> None:
        canvas = target_canvas or self.indirect_system_canvas
        canvas.delete("all")
        canvas.create_rectangle(40, 30, 260, 190, outline="black", width=4)
        canvas.create_text(150, 57, text="Primary tank", font=("Segoe UI", 13, "bold"))
        try:
            primary_size = parse_number(self.selected_tank_var.get())
        except (ValueError, AttributeError):
            primary_size = volume_to_display(self.config_model.selected_tank_size_gal, self.config_model)
        canvas.create_text(
            150,
            80,
            text=f"Primary analysis size: {format_number(primary_size, self.config_model, max_decimal_places=0)} {volume_unit(self.config_model)}",
            font=("Segoe UI", 9),
        )
        canvas.create_line(*self._regular_wave_points(42, 258, 110, 8, 7), fill="black", width=4, smooth=True)
        canvas.create_line(260, 150, 330, 150, fill="black", width=4)
        canvas.create_oval(330, 115, 400, 185, outline="black", width=4)
        canvas.create_polygon(400, 150, 347.5, 180.31, 347.5, 119.69, outline="black", fill="", width=4)
        canvas.create_text(365, 210, text="Transfer pump", font=("Segoe UI", 11, "bold"))
        canvas.create_line(400, 150, 460, 150, fill="black", width=4)
        canvas.create_rectangle(460, 120, 600, 180, outline="black", width=4)
        canvas.create_text(530, 150, text="Filtration", font=("Segoe UI", 11, "bold"))
        canvas.create_line(600, 150, 680, 150, fill="black", width=4)
        canvas.create_rectangle(680, 50, 850, 190, outline="black", width=4)
        canvas.create_text(765, 80, text="Buffer tank", font=("Segoe UI", 13, "bold"))
        canvas.create_line(*self._regular_wave_points(682, 848, 120, 7, 6), fill="black", width=4, smooth=True)
        canvas.create_line(765, 4, 765, 50, fill="black", width=4, arrow=tk.LAST, arrowshape=(14, 16, 7))
        canvas.create_text(660, 16, text="Municipal water backup", font=("Segoe UI", 10, "bold"))
        canvas.create_line(850, 150, 872, 150, fill="black", width=4)
        canvas.create_oval(872, 122, 928, 178, outline="black", width=4)
        canvas.create_polygon(928, 150, 886, 174.25, 886, 125.75, outline="black", fill="", width=4)
        canvas.create_text(900, 210, text="Booster pump", font=("Segoe UI", 11, "bold"))
        canvas.create_line(928, 150, 1030, 150, fill="black", width=4, arrow=tk.LAST, arrowshape=(18, 20, 8))
        canvas.create_text(980, 126, text="To end-uses", font=("Segoe UI", 10, "bold"))

    @staticmethod
    def _regular_wave_points(start_x: int, end_x: int, center_y: int, half_step: int, amplitude: int) -> list[int]:
        points = [start_x, center_y]
        x = start_x + half_step
        direction = -1
        while x < end_x:
            points.extend((x, center_y + direction * amplitude))
            direction *= -1
            x += half_step
        points.extend((end_x, center_y))
        return points

    def _build_import_tab(self) -> None:
        self.import_tab.columnconfigure(0, weight=1)
        self.import_tab.rowconfigure(0, weight=1)
        self.rainwater_data_notebook = ttk.Notebook(self.import_tab)
        self.rainwater_data_notebook.grid(row=0, column=0, sticky="nsew")
        self.daily_rainwater_tab = ttk.Frame(self.rainwater_data_notebook, padding=8)
        self.hourly_rainwater_tab = ttk.Frame(self.rainwater_data_notebook, padding=16)
        self.multi_site_rainwater_tab = ttk.Frame(self.rainwater_data_notebook, padding=16)
        self.rainwater_data_notebook.add(self.daily_rainwater_tab, text="Daily data")
        self.rainwater_data_notebook.add(
            self.hourly_rainwater_tab, text="Hourly rainfall"
        )
        if not hasattr(self, "info_icon_image"):
            self.info_icon_image = self._create_info_icon()
        self.rainwater_data_notebook.add(
            self.multi_site_rainwater_tab,
            text="Multi-site comparison",
            image=self.info_icon_image,
            compound="right",
        )
        self.rainwater_data_notebook.bind(
            "<Button-1>", self._rainwater_data_notebook_clicked, add="+"
        )
        self.daily_rainwater_tab.columnconfigure(0, weight=1)
        self.daily_rainwater_tab.rowconfigure(1, weight=1)
        self.hourly_rainwater_tab.columnconfigure(0, weight=1)
        self.hourly_rainwater_tab.rowconfigure(3, weight=1)
        self._build_multi_site_comparison_tab()
        ttk.Label(
            self.hourly_rainwater_tab,
            text=(
                "Load observed hourly rainfall or generate a derived hourly profile from "
                "daily rainfall."
            ),
            foreground="#667278",
            wraplength=980,
            justify="left",
        ).grid(row=0, column=0, sticky="ew", pady=(0, 10))

        hourly_profile_frame = ttk.LabelFrame(
            self.hourly_rainwater_tab, text="Synthetic hourly profile", padding=10
        )
        hourly_profile_frame.grid(row=1, column=0, sticky="ew")
        hourly_profile_frame.columnconfigure(0, weight=1)
        ttk.Label(
            hourly_profile_frame,
            textvariable=self.rainfall_summary_var,
            wraplength=820,
            justify="left",
        ).grid(row=0, column=0, columnspan=2, sticky="ew")
        ttk.Label(
            hourly_profile_frame,
            textvariable=self.synthetic_hourly_rainfall_status_var,
            foreground="#667278",
            wraplength=820,
            justify="left",
        ).grid(row=1, column=0, columnspan=2, sticky="ew", pady=(5, 8))
        hourly_actions = ttk.Frame(hourly_profile_frame)
        hourly_actions.grid(row=2, column=0, columnspan=2, sticky="w")
        ttk.Button(
            hourly_actions,
            text="Load Hourly Rainfall CSV",
            command=self.load_hourly_rainfall_csv,
        ).pack(side="left")
        self.generate_hourly_rainfall_button = ttk.Button(
            hourly_actions,
            text="Generate Synthetic Hourly Rainfall...",
            command=self.generate_hourly_rainfall,
        )
        self.generate_hourly_rainfall_button.pack(side="left", padx=(8, 0))
        self.remove_hourly_rainfall_button = ttk.Button(
            hourly_actions,
            text="Remove Generated Profile",
            command=self.remove_generated_hourly_rainfall,
        )
        self.remove_hourly_rainfall_button.pack(side="left", padx=(8, 0))

        assumptions_frame = ttk.LabelFrame(
            self.hourly_rainwater_tab, text="Distribution assumptions", padding=10
        )
        assumptions_frame.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        assumptions_frame.columnconfigure(0, weight=1)
        ttk.Label(
            assumptions_frame,
            text=(
                "Hyetos-style Bartlett-Lewis rectangular pulses generate candidate within-day "
                "profiles. A repetition step selects a plausible wet-hour pattern, and an "
                "adjusting step makes the 24 hourly depths sum exactly to each daily total. "
                "The random seed makes regeneration reproducible. The built-in stochastic "
                "parameters are general-purpose defaults, not a local calibration."
            ),
            wraplength=980,
            justify="left",
        ).grid(row=0, column=0, sticky="ew")

        preview_frame = ttk.LabelFrame(
            self.hourly_rainwater_tab, text="Hourly distribution preview", padding=10
        )
        preview_frame.grid(row=3, column=0, sticky="nsew", pady=(10, 0))
        preview_frame.columnconfigure(0, weight=1)
        preview_frame.rowconfigure(1, weight=1)
        ttk.Label(
            preview_frame,
            textvariable=self.hourly_profile_preview_var,
            foreground="#667278",
            wraplength=960,
            justify="left",
        ).grid(row=0, column=0, sticky="ew", pady=(0, 6))
        self.hourly_profile_tree = ttk.Treeview(
            preview_frame,
            columns=("Hour", "Precipitation", "Share"),
            show="headings",
            height=8,
        )
        self.hourly_profile_tree.heading("Hour", text="Hour")
        self.hourly_profile_tree.heading("Precipitation", text="Record precipitation")
        self.hourly_profile_tree.heading("Share", text="Share of generated total (%)")
        self.hourly_profile_tree.column("Hour", width=150, anchor="center")
        self.hourly_profile_tree.column("Precipitation", width=220, anchor="e")
        self.hourly_profile_tree.column("Share", width=220, anchor="e")
        self.hourly_profile_tree.grid(row=1, column=0, sticky="nsew")
        hourly_preview_scroll = ttk.Scrollbar(
            preview_frame, orient="vertical", command=self.hourly_profile_tree.yview
        )
        hourly_preview_scroll.grid(row=1, column=1, sticky="ns")
        self.hourly_profile_tree.configure(yscrollcommand=hourly_preview_scroll.set)
        daily_hourly_reference = ttk.Frame(self.daily_rainwater_tab, padding=(0, 0, 0, 8))
        daily_hourly_reference.grid(row=0, column=0, columnspan=2, sticky="ew")
        daily_hourly_reference.columnconfigure(0, weight=1)
        ttk.Label(
            daily_hourly_reference,
            textvariable=self.hourly_profile_reference_var,
            foreground="#667278",
            justify="left",
        ).grid(row=0, column=0, sticky="w")
        ttk.Button(
            daily_hourly_reference,
            text="Open Hourly Data",
            command=self.open_hourly_rainwater_tab,
        ).grid(row=0, column=1, sticky="e", padx=(12, 0))
        frame_background = ttk.Style(self).lookup("TFrame", "background") or "#f0f0f0"
        self.import_canvas = tk.Canvas(
            self.daily_rainwater_tab,
            highlightthickness=0,
            borderwidth=0,
            background=frame_background,
        )
        self.import_canvas.grid(row=1, column=0, sticky="nsew")
        import_scroll_y = ttk.Scrollbar(
            self.daily_rainwater_tab, orient="vertical", command=self.import_canvas.yview
        )
        import_scroll_y.grid(row=1, column=1, sticky="ns")
        self.import_canvas.configure(yscrollcommand=import_scroll_y.set)
        import_content = ttk.Frame(self.import_canvas, padding=(0, 0, 8, 8))
        self.import_canvas_window = self.import_canvas.create_window(
            (0, 0), window=import_content, anchor="nw"
        )
        import_content.columnconfigure(0, weight=1)
        import_content.bind(
            "<Configure>",
            lambda _event: self.import_canvas.configure(scrollregion=self.import_canvas.bbox("all")),
        )
        self.import_canvas.bind("<Configure>", self._resize_import_content)
        self.bind_all("<MouseWheel>", self._scroll_import_mousewheel, add="+")
        self.bind_all("<Button-4>", self._scroll_import_mousewheel, add="+")
        self.bind_all("<Button-5>", self._scroll_import_mousewheel, add="+")

        csv_title = ttk.Frame(import_content)
        ttk.Label(csv_title, text="Rainfall CSV").grid(row=0, column=0, sticky="w")
        self._info_button(csv_title, self._show_rainfall_csv_format_tip).grid(
            row=0, column=1, padx=(5, 0)
        )
        csv_frame = ttk.LabelFrame(import_content, labelwidget=csv_title, padding=10)
        csv_frame.grid(row=0, column=0, sticky="ew")
        csv_frame.columnconfigure(0, weight=1)
        ttk.Label(csv_frame, textvariable=self.rainfall_summary_var).grid(row=0, column=0, sticky="w")
        ttk.Button(csv_frame, text="Load Rainfall CSV", command=self.load_rainfall_csv).grid(
            row=0, column=1, sticky="e", padx=(12, 0)
        )
        self.rainfall_quick_access_button = ttk.Menubutton(
            csv_frame, text="Quick Access \N{BLACK DOWN-POINTING SMALL TRIANGLE}"
        )
        self.rainfall_quick_access_button.grid(row=0, column=2, sticky="e", padx=(6, 0))
        self.rainfall_quick_access_menu = tk.Menu(
            self.rainfall_quick_access_button, tearoff=False
        )
        self.rainfall_quick_access_button.configure(menu=self.rainfall_quick_access_menu)
        self.rainfall_quick_access_button.bind(
            "<Enter>", self._open_rainfall_quick_access_on_hover, add="+"
        )
        self.save_rainfall_csv_button = ttk.Button(
            csv_frame,
            text="Save Rainfall CSV...",
            command=self.save_rainfall_csv,
            state="disabled",
        )
        self.save_rainfall_csv_button.grid(row=0, column=3, sticky="e", padx=(6, 0))
        self._refresh_rainfall_quick_access_menu()
        provenance_frame = ttk.LabelFrame(
            csv_frame, text="Quality and provenance", padding=8
        )
        provenance_frame.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(10, 0))
        provenance_frame.columnconfigure(1, weight=1)
        ttk.Label(
            provenance_frame,
            textvariable=self.rainfall_quality_var,
            wraplength=760,
            justify="left",
        ).grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        ttk.Label(provenance_frame, text="Data classification").grid(
            row=1, column=0, sticky="w", pady=2
        )
        ttk.Label(
            provenance_frame,
            textvariable=self.rainfall_data_type_var,
            foreground="#5f6b70",
        ).grid(row=1, column=1, sticky="ew", pady=2)
        ttk.Label(provenance_frame, text="Temporal resolution").grid(
            row=2, column=0, sticky="w", pady=2
        )
        ttk.Label(
            provenance_frame,
            textvariable=self.rainfall_resolution_var,
            foreground="#5f6b70",
        ).grid(row=2, column=1, sticky="ew", pady=2)
        ttk.Label(provenance_frame, text="Source timezone").grid(
            row=3, column=0, sticky="w", pady=2
        )
        ttk.Label(
            provenance_frame,
            textvariable=self.rainfall_timezone_var,
            foreground="#5f6b70",
        ).grid(row=3, column=1, sticky="ew", pady=2)
        ttk.Label(provenance_frame, text="Timing metadata").grid(
            row=4, column=0, sticky="nw", pady=2
        )
        ttk.Label(
            provenance_frame,
            textvariable=self.rainfall_timing_var,
            wraplength=570,
            justify="left",
            foreground="#5f6b70",
        ).grid(row=4, column=1, sticky="ew", pady=2)
        self._refresh_synthetic_hourly_rainfall_status()

        self.weather_frame = ttk.LabelFrame(import_content, text="ACIS Weather Import", padding=10)
        self.weather_frame.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        self.weather_frame.columnconfigure(1, weight=1)
        source_row = ttk.Frame(self.weather_frame)
        source_row.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        source_row.columnconfigure(1, weight=1)
        self._info_button(source_row, self._show_weather_source_tip).grid(
            row=0, column=0, sticky="nw", padx=(0, 6)
        )
        ttk.Label(
            source_row,
            textvariable=self.weather_source_note_var,
            foreground="#5f6b70",
            wraplength=680,
            justify="left",
        ).grid(row=0, column=1, sticky="ew")
        self.weather_source_link = ttk.Label(
            source_row,
            textvariable=self.weather_source_link_var,
            foreground="#0563c1",
            cursor="hand2",
            font=("Segoe UI", 9, "underline"),
        )
        self.weather_source_link.grid(row=1, column=1, sticky="w", pady=(3, 0))
        self.weather_source_link.bind("<Button-1>", self._open_weather_source)
        self.weather_location_label = ttk.Label(self.weather_frame, text="State")
        self.weather_location_label.grid(row=1, column=0, sticky="w", pady=2)
        self.state_combo = ttk.Combobox(
            self.weather_frame,
            textvariable=self.weather_state_var,
            values=[STATE_PLACEHOLDER, *STATE_LABELS],
            state="readonly",
        )
        self.state_combo.configure(postcommand=self._bind_state_combo_dropdown)
        self.state_combo.grid(row=1, column=1, sticky="ew", pady=2)
        self.state_combo.bind("<KeyPress>", self._select_state_by_first_letter)
        self._labeled_entry(self.weather_frame, 2, "Historical years", self.weather_years_var)
        self._labeled_entry(
            self.weather_frame,
            3,
            "Station filter(s), separated by ;",
            self.weather_filter_var,
        )
        self.canadian_precip_label = ttk.Label(self.weather_frame, text="Precipitation basis")
        self.canadian_precip_label.grid(row=4, column=0, sticky="w", pady=2)
        self.canadian_precip_combo = ttk.Combobox(
            self.weather_frame,
            textvariable=self.canadian_precip_var,
            values=list(CANADIAN_PRECIPITATION_OPTIONS),
            state="readonly",
        )
        self.canadian_precip_combo.grid(row=4, column=1, sticky="ew", pady=2)
        station_search_buttons = ttk.Frame(self.weather_frame)
        station_search_buttons.grid(row=5, column=0, sticky="w", pady=(8, 2))
        self.find_stations_button = ttk.Button(
            station_search_buttons, text="Find Stations", command=self.find_weather_stations
        )
        self.find_stations_button.grid(row=0, column=0, sticky="w")
        self.find_nearest_stations_button = ttk.Button(
            station_search_buttons,
            text="Find Nearest 10",
            command=self.find_nearest_weather_stations,
        )
        self.find_nearest_stations_button.grid(row=0, column=1, sticky="w", padx=(6, 0))
        self.find_nearest_airport_stations_button = ttk.Button(
            station_search_buttons,
            text="Find Nearest 5 Airports",
            command=self.find_nearest_airport_weather_stations,
        )
        self.find_nearest_airport_stations_button.grid(
            row=0, column=2, sticky="w", padx=(6, 0)
        )
        self.station_combo = ttk.Combobox(self.weather_frame, textvariable=self.station_var, state="readonly")
        self.station_combo.configure(postcommand=self._bind_station_combo_dropdown)
        self.station_combo.grid(row=5, column=1, sticky="ew", padx=(8, 0), pady=(8, 2))
        self.station_combo.bind("<KeyPress>", self._select_station_by_typed_prefix)
        self.station_combo.bind("<<ComboboxSelected>>", self._station_selection_changed)
        self.import_station_button = ttk.Button(
            self.weather_frame,
            text="Import Selected Station",
            command=self.import_selected_weather,
        )
        self.import_station_button.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(4, 0))

        station_map_frame = ttk.LabelFrame(import_content, text="Weather stations", padding=6)
        station_map_frame.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        station_map_frame.columnconfigure(0, weight=1)
        station_map_frame.rowconfigure(1, weight=1)
        map_toolbar = ttk.Frame(station_map_frame)
        map_toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        map_toolbar.columnconfigure(0, weight=1)
        ttk.Label(
            map_toolbar,
            text="Select a station marker or expand the map for a larger view.",
            foreground="#5f6b70",
        ).grid(row=0, column=0, sticky="w")
        ttk.Button(
            map_toolbar,
            text="Full screen",
            command=self._open_station_map_fullscreen,
        ).grid(row=0, column=1, sticky="e", padx=(12, 0))
        self.station_map = _StationMapView(station_map_frame, width=800, height=560, corner_radius=0)
        self.station_map_embedded = self.station_map
        self.station_map.set_tile_server(OSM_TILE_URL, max_zoom=19)
        self.station_map.set_position(39.5, -98.35)
        self.station_map.set_zoom(3)
        self.station_map.grid(row=1, column=0, sticky="nsew")
        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>", "<ButtonRelease-1>"):
            self.station_map.canvas.bind(sequence, self._station_map_view_changed, add="+")
        ttk.Label(
            station_map_frame,
            text="Map data © OpenStreetMap contributors",
            foreground="#5f6b70",
        ).grid(row=2, column=0, sticky="e", pady=(4, 0))

    def _build_multi_site_comparison_tab(self) -> None:
        tab = self.multi_site_rainwater_tab
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(0, weight=1)
        tab.bind("<Map>", self._multi_site_tab_mapped, add="+")

        frame_background = ttk.Style(self).lookup("TFrame", "background") or "#f0f0f0"
        self.multi_site_canvas = tk.Canvas(
            tab,
            highlightthickness=0,
            borderwidth=0,
            background=frame_background,
        )
        self.multi_site_canvas.grid(row=0, column=0, sticky="nsew")
        multi_site_scroll_y = ttk.Scrollbar(
            tab, orient="vertical", command=self.multi_site_canvas.yview
        )
        multi_site_scroll_y.grid(row=0, column=1, sticky="ns")
        self.multi_site_canvas.configure(yscrollcommand=multi_site_scroll_y.set)
        content = ttk.Frame(self.multi_site_canvas, padding=(0, 0, 8, 8))
        self.multi_site_canvas_window = self.multi_site_canvas.create_window(
            (0, 0), window=content, anchor="nw"
        )
        content.columnconfigure(0, weight=1)
        content.bind("<Configure>", self._update_multi_site_scroll_region)
        self.multi_site_canvas.bind("<Configure>", self._resize_multi_site_content)
        self.bind_all("<MouseWheel>", self._scroll_multi_site_mousewheel, add="+")
        self.bind_all("<Button-4>", self._scroll_multi_site_mousewheel, add="+")
        self.bind_all("<Button-5>", self._scroll_multi_site_mousewheel, add="+")

        search_frame = ttk.LabelFrame(
            content, text="Find a Climate Normals station", padding=10
        )
        search_frame.grid(row=0, column=0, sticky="ew")
        search_frame.columnconfigure(0, weight=1)

        browser_columns = ttk.Frame(search_frame)
        browser_columns.grid(row=0, column=0, sticky="ew")
        browser_columns.columnconfigure(0, weight=2, uniform="station-browser")
        browser_columns.columnconfigure(1, weight=3, uniform="station-browser")
        browser_columns.rowconfigure(0, weight=1)

        state_column = ttk.Frame(browser_columns)
        state_column.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        state_column.columnconfigure(0, weight=1)
        state_column.rowconfigure(2, weight=1)
        self.climate_normal_search_entry = tk.Entry(
            state_column,
            textvariable=self.climate_normal_query_var,
            foreground="#7a858a",
            relief="solid",
            borderwidth=1,
        )
        self.climate_normal_search_entry.grid(row=0, column=0, sticky="ew")
        self.climate_normal_search_entry.bind(
            "<FocusIn>", self._climate_normal_search_focus_in
        )
        self.climate_normal_search_entry.bind(
            "<FocusOut>", self._climate_normal_search_focus_out
        )
        self.climate_normal_search_entry.bind(
            "<KeyRelease>", self._climate_normal_search_changed
        )
        ttk.Label(
            state_column,
            text="US States",
            font=("Segoe UI", 9, "bold italic"),
            anchor="w",
        ).grid(row=1, column=0, sticky="ew", pady=(6, 2))
        state_list_frame = ttk.Frame(state_column)
        state_list_frame.grid(row=2, column=0, sticky="nsew")
        state_list_frame.columnconfigure(0, weight=1)
        self.climate_normal_state_list = tk.Listbox(
            state_list_frame,
            height=len(DEFAULT_SURFACES),
            exportselection=False,
            activestyle="dotbox",
            disabledforeground="#90999d",
        )
        self.climate_normal_state_list.grid(row=0, column=0, sticky="nsew")
        climate_state_scroll = ttk.Scrollbar(
            state_list_frame,
            orient="vertical",
            command=self.climate_normal_state_list.yview,
        )
        climate_state_scroll.grid(row=0, column=1, sticky="ns")
        self.climate_normal_state_list.configure(yscrollcommand=climate_state_scroll.set)
        for _state_code_value, state_name in STATE_OPTIONS:
            self.climate_normal_state_list.insert(tk.END, f"    {state_name}")
        self.climate_normal_state_list.bind(
            "<<ListboxSelect>>", self._climate_normal_state_selected
        )

        station_list_frame = ttk.Frame(browser_columns)
        station_list_frame.grid(row=0, column=1, sticky="nsew")
        station_list_frame.columnconfigure(0, weight=1)
        station_list_frame.rowconfigure(0, weight=1)
        self.climate_normal_station_list = tk.Listbox(
            station_list_frame,
            height=10,
            exportselection=False,
            activestyle="dotbox",
        )
        self.climate_normal_station_list.grid(row=0, column=0, sticky="nsew")
        climate_station_scroll = ttk.Scrollbar(
            station_list_frame,
            orient="vertical",
            command=self.climate_normal_station_list.yview,
        )
        climate_station_scroll.grid(row=0, column=1, sticky="ns")
        self.climate_normal_station_list.configure(
            yscrollcommand=climate_station_scroll.set
        )
        self.climate_normal_station_list.bind(
            "<<ListboxSelect>>", self._climate_normal_station_selected
        )
        self.climate_normal_station_list.bind(
            "<Double-1>", lambda _event: self.add_selected_climate_normal()
        )

        station_actions = ttk.Frame(search_frame)
        station_actions.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        station_actions.columnconfigure(0, weight=1)
        self.cancel_climate_normal_search_button = ttk.Button(
            station_actions,
            text="Cancel data search",
            command=self.cancel_climate_normal_data_search,
            state="disabled",
        )
        self.cancel_climate_normal_search_button.grid(
            row=0, column=1, sticky="e", padx=(8, 0)
        )
        self.add_climate_normal_button = ttk.Button(
            station_actions,
            text="Add to comparison",
            command=self.add_selected_climate_normal,
            state="disabled",
        )
        self.add_climate_normal_button.grid(row=0, column=2, sticky="e", padx=(8, 0))
        ttk.Label(
            station_actions,
            textvariable=self.climate_normal_status_var,
            foreground="#5f6b70",
            wraplength=820,
            justify="left",
        ).grid(row=0, column=0, sticky="ew")

        climate_map_frame = ttk.LabelFrame(
            content, text="Climate Normals stations", padding=6
        )
        climate_map_frame.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        climate_map_frame.columnconfigure(0, weight=1)
        self.climate_normal_map = _StationMapView(
            climate_map_frame, width=800, height=240, corner_radius=0
        )
        self.climate_normal_map.set_tile_server(OSM_TILE_URL, max_zoom=19)
        self.climate_normal_map.set_position(39.5, -98.35)
        self.climate_normal_map.set_zoom(3)
        self.climate_normal_map.grid(row=0, column=0, sticky="nsew")
        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>", "<ButtonRelease-1>"):
            self.climate_normal_map.canvas.bind(
                sequence, self._climate_normal_map_view_changed, add="+"
            )
        ttk.Label(
            climate_map_frame,
            text="Map data © OpenStreetMap contributors",
            foreground="#5f6b70",
        ).grid(row=1, column=0, sticky="e", pady=(4, 0))

        comparison_frame = ttk.LabelFrame(
            content, text="Precipitation normals", padding=10
        )
        self.climate_normal_comparison_frame = comparison_frame
        comparison_frame.grid(row=2, column=0, sticky="nsew", pady=(10, 0))
        comparison_frame.columnconfigure(0, weight=1)
        comparison_frame.rowconfigure(0, weight=1)
        self.climate_normal_tree = ttk.Treeview(
            comparison_frame,
            columns=("station", "annual", "winter", "spring", "summer", "autumn"),
            show="headings",
            height=6,
        )
        headings = {
            "station": "Station",
            "annual": "Annual",
            "winter": "Winter",
            "spring": "Spring",
            "summer": "Summer",
            "autumn": "Autumn",
        }
        for column, heading in headings.items():
            heading_options: dict[str, object] = {
                "text": heading,
                "command": (
                    lambda selected_column=column: self._sort_climate_normal_comparison(
                        selected_column
                    )
                )
            }
            self.climate_normal_tree.heading(column, **heading_options)
        self.climate_normal_tree.column("station", width=330)
        for column in ("annual", "winter", "spring", "summer", "autumn"):
            self.climate_normal_tree.column(column, width=115, anchor="e")
        self.climate_normal_tree.grid(row=0, column=0, sticky="nsew")
        comparison_scroll = ttk.Scrollbar(
            comparison_frame, orient="vertical", command=self.climate_normal_tree.yview
        )
        comparison_scroll.grid(row=0, column=1, sticky="ns")
        comparison_scroll_x = ttk.Scrollbar(
            comparison_frame,
            orient="horizontal",
            command=self.climate_normal_tree.xview,
        )
        comparison_scroll_x.grid(row=1, column=0, sticky="ew")
        self.climate_normal_tree.configure(
            yscrollcommand=comparison_scroll.set,
            xscrollcommand=comparison_scroll_x.set,
        )

        self.climate_normal_season_note = ttk.Label(
            comparison_frame,
            foreground="#5f6b70",
            text=(
                "Meteorological seasons: Winter Dec-Feb; Spring Mar-May; "
                "Summer Jun-Aug; Autumn Sep-Nov."
            ),
        )
        self.climate_normal_season_note.grid(
            row=2, column=0, columnspan=2, sticky="w", pady=(6, 0)
        )

        comparison_actions = ttk.Frame(comparison_frame)
        comparison_actions.grid(row=3, column=0, columnspan=2, sticky="w", pady=(8, 0))
        ttk.Button(
            comparison_actions,
            text="Remove selected",
            command=self.remove_selected_climate_normal,
        ).pack(side="left")
        ttk.Button(
            comparison_actions,
            text="Clear comparison",
            command=self.clear_climate_normal_comparison,
        ).pack(side="left", padx=(8, 0))
        ttk.Button(
            comparison_actions,
            text="Export CSV...",
            command=self.export_climate_normal_comparison,
        ).pack(side="left", padx=(8, 0))

    def _build_collection_tab(self) -> None:
        self.collection_tab.columnconfigure(0, weight=1)
        self.collection_tab.rowconfigure(0, weight=1)
        surface_title = ttk.Frame(self.collection_tab)
        ttk.Label(surface_title, text="Collection surfaces").grid(row=0, column=0, sticky="w")
        self._info_button(surface_title, self._show_collection_surface_tip).grid(
            row=0, column=1, padx=(4, 0)
        )
        surfaces_frame = ttk.LabelFrame(self.collection_tab, labelwidget=surface_title, padding=10)
        surfaces_frame.grid(row=0, column=0, sticky="nsew")
        surfaces_frame.rowconfigure(0, weight=1)
        surfaces_frame.columnconfigure(0, weight=1)
        self.surface_tree = ttk.Treeview(
            surfaces_frame,
            columns=("surface", "area", "runoff"),
            show="headings",
            height=18,
        )
        self.surface_tree.heading("surface", text="Surface")
        self.surface_tree.heading("area", text="Area")
        self.surface_tree.heading("runoff", text="Runoff coeff.")
        self.surface_tree.column("surface", width=420)
        self.surface_tree.column("area", width=160, anchor="e")
        self.surface_tree.column("runoff", width=140, anchor="e")
        self.surface_tree.grid(row=0, column=0, sticky="nsew")
        surface_scroll_y = ttk.Scrollbar(surfaces_frame, orient="vertical", command=self.surface_tree.yview)
        surface_scroll_y.grid(row=0, column=1, sticky="ns")
        self.surface_tree.configure(yscrollcommand=surface_scroll_y.set)
        self.surface_tree.bind("<Double-1>", self._edit_surface_from_event)
        self.surface_tree.bind("<Return>", self._edit_selected_surface_from_event)
        surface_buttons = ttk.Frame(surfaces_frame)
        surface_buttons.grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Button(surface_buttons, text="Add collection surface", command=self.add_surface).grid(
            row=0, column=0, padx=(0, 6)
        )
        ttk.Button(surface_buttons, text="Edit selected surface", command=self.edit_surface).grid(row=0, column=1)
        self._refresh_first_flush_guidance()

    def _selected_first_flush_sizing_method(self) -> str:
        label = self.first_flush_sizing_method_var.get()
        return next(
            (code for code, value in SIZING_METHOD_LABELS.items() if value == label),
            MANUAL_SIZING_METHOD,
        )

    def _selected_first_flush_design_preset(self) -> str:
        label = self.first_flush_design_preset_var.get()
        return next(
            (code for code, value in DESIGN_PRESET_LABELS.items() if value == label),
            CODE_MINIMUM_PRESET,
        )

    def _first_flush_guidance_changed(self, _event: tk.Event | None = None) -> None:
        self._refresh_first_flush_guidance()

    def _refresh_first_flush_guidance(self) -> None:
        if not hasattr(self, "first_flush_design_preset_combo"):
            return
        method = self._selected_first_flush_sizing_method()
        guided = method == GUIDED_SIZING_METHOD
        self.first_flush_design_preset_combo.configure(
            state="readonly" if guided else "disabled"
        )
        self.apply_first_flush_guidance_button.configure(
            state="normal" if guided else "disabled"
        )
        if not guided:
            self.first_flush_guidance_summary_var.set(
                "Legacy behavior: each surface's stored first-flush depth is used without a guided floor."
            )
            return

        country_code = self.country_var.get().split(" - ", 1)[0].strip() or "USA"
        guidance = first_flush_guidance(
            country_code,
            self.state_or_province_var.get(),
            self._selected_first_flush_design_preset(),
        )
        target = guidance.automatic_target_mm
        target_text = f"{target:.3f} mm ({target / 25.4:.4f} in)"
        self.first_flush_guidance_summary_var.set(
            f"Location layer: {guidance.baseline.label}, {guidance.baseline.depth_mm:g} mm. "
            f"Guided floor: {target_text}. Applying raises lower active-surface depths and "
            f"retains larger site-specific values. {guidance.baseline.source}."
        )

    def _apply_first_flush_guidance(self) -> None:
        if self._selected_first_flush_sizing_method() != GUIDED_SIZING_METHOD:
            return
        country_code = self.country_var.get().split(" - ", 1)[0].strip() or "USA"
        guidance = first_flush_guidance(
            country_code,
            self.state_or_province_var.get(),
            self._selected_first_flush_design_preset(),
        )
        target_inches = guidance.automatic_target_mm / 25.4
        active_surfaces = [surface for surface in self.config_model.surfaces if surface.area > 0.0]
        if not active_surfaces:
            messagebox.showinfo(
                APP_TITLE,
                "Add an active collection surface with an area before applying guided sizing.",
                parent=self,
            )
            return
        if target_inches <= 0.0:
            messagebox.showinfo(
                APP_TITLE,
                "No built-in regulatory floor was identified for this location. Verify local "
                "requirements and enter a custom or site-tested depth on each surface.",
                parent=self,
            )
            return
        for surface in active_surfaces:
            surface.first_flush_depth_inches = max(
                float(surface.first_flush_depth_inches), target_inches
            )
        self.config_model.first_flush_sizing_method = GUIDED_SIZING_METHOD
        self.config_model.first_flush_design_preset = self._selected_first_flush_design_preset()
        item = self._system_layout_item(self.system_builder_selected_id or "")
        if item is not None and item.get("component_type") == "first_flush_diversion":
            item["sizing_method"] = self.config_model.first_flush_sizing_method
            item["design_preset"] = self.config_model.first_flush_design_preset
        self._populate_surfaces()
        self._refresh_first_flush_surface_editor()
        self._refresh_project_dirty_state()

    def _first_flush_antecedent_unit_changed(self, _event: tk.Event | None = None) -> None:
        new_unit = self.first_flush_antecedent_unit_var.get().casefold()
        if new_unit not in {"days", "hours"}:
            new_unit = "days"
            self.first_flush_antecedent_unit_var.set(new_unit)
        old_unit = self.first_flush_antecedent_display_unit
        try:
            displayed_value = parse_number(self.first_flush_antecedent_var.get())
            if not math.isfinite(displayed_value):
                raise ValueError
            duration_days = _antecedent_dry_period_to_days(displayed_value, old_unit)
        except ValueError:
            duration_days = self.config_model.first_flush_antecedent_dry_days
        converted = _antecedent_dry_period_from_days(duration_days, new_unit)
        self.first_flush_antecedent_display_unit = new_unit
        self.first_flush_antecedent_var.set(f"{converted:g}")

    def _build_schedules_tab(self) -> None:
        self.schedules_tab.columnconfigure(1, weight=1)
        self.schedules_tab.columnconfigure(2, weight=1)
        self.schedules_tab.rowconfigure(1, weight=1)
        schedule_toolbar = ttk.Frame(self.schedules_tab)
        schedule_toolbar.grid(row=0, column=0, sticky="w", pady=(0, 6))
        self.schedule_add_icon = self._create_schedule_action_icon("#2e8b57", "+")
        self.schedule_duplicate_icon = self._create_schedule_action_icon("#1565c0", "x2")
        self.schedule_delete_icon = self._create_schedule_action_icon("#c62828", "x")
        self.schedule_purge_icon = self._create_tabler_trash_icon()
        self.schedule_add_button = ttk.Button(
            schedule_toolbar, image=self.schedule_add_icon, command=self.create_hourly_demand_schedule, takefocus=True
        )
        self.schedule_add_button.grid(row=0, column=0)
        self.schedule_duplicate_button = ttk.Button(
            schedule_toolbar,
            image=self.schedule_duplicate_icon,
            command=self.duplicate_hourly_demand_schedule,
            takefocus=True,
        )
        self.schedule_duplicate_button.grid(row=0, column=1, padx=(2, 0))
        self.schedule_delete_button = ttk.Button(
            schedule_toolbar,
            image=self.schedule_delete_icon,
            command=self.delete_hourly_demand_schedule,
            takefocus=True,
        )
        self.schedule_delete_button.grid(row=0, column=2, padx=(2, 0))
        self.schedule_purge_button = ttk.Button(
            schedule_toolbar,
            image=self.schedule_purge_icon,
            text="Purge unused objects",
            compound=tk.NONE,
            command=self.purge_unused_schedule_objects,
            takefocus=True,
        )
        self.schedule_purge_button.grid(row=0, column=3, padx=(8, 0))
        self.schedule_list = tk.Listbox(self.schedules_tab, width=28, exportselection=False)
        self.schedule_list.grid(row=1, column=0, sticky="nsew", padx=(0, 10))
        self.schedule_list.bind("<<ListboxSelect>>", self._schedule_selection_changed)
        self.schedule_list.bind("<F2>", self._focus_schedule_name_from_event)

        built_in_templates = common_hourly_schedule_templates()
        built_in_names = {name.casefold() for name in built_in_templates}
        self.custom_schedule_templates = {
            name: schedule
            for name, schedule in self.custom_schedule_templates.items()
            if name.casefold() not in built_in_names
        }
        self.custom_schedule_template_types = {
            name: self.custom_schedule_template_types.get(
                name, FRACTIONAL_SCHEDULE_TYPE
            )
            for name in self.custom_schedule_templates
        }
        self.custom_schedule_template_months = {
            name: self.custom_schedule_template_months.get(name, list(range(1, 13)))
            for name in self.custom_schedule_templates
        }
        self.common_schedule_templates = {**built_in_templates, **self.custom_schedule_templates}
        self.common_schedule_template_types = {
            **common_hourly_schedule_template_types(),
            **self.custom_schedule_template_types,
        }
        self.common_schedule_template_months = {
            **{name: list(range(1, 13)) for name in built_in_templates},
            **self.custom_schedule_template_months,
        }

        hourly_frame = ttk.LabelFrame(self.schedules_tab, text="Schedule properties", padding=12)
        hourly_frame.grid(row=0, column=1, rowspan=2, sticky="nsew", padx=(0, 10))
        hourly_frame.columnconfigure(1, weight=1)
        self.schedule_name_var = tk.StringVar()
        ttk.Label(hourly_frame, text="Schedule name").grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.schedule_name_entry = ttk.Entry(hourly_frame, textvariable=self.schedule_name_var)
        self.schedule_name_entry.grid(row=0, column=1, sticky="ew")
        self.schedule_name_entry.bind("<Return>", self._rename_schedule_from_event)
        self.rename_schedule_button = ttk.Button(
            hourly_frame, text="Rename", command=self.rename_hourly_demand_schedule
        )
        self.rename_schedule_button.grid(row=0, column=2, sticky="w", padx=(8, 0))
        ttk.Label(hourly_frame, text="Schedule type").grid(
            row=1, column=0, sticky="w", padx=(0, 8), pady=(10, 0)
        )
        self.schedule_type_var = tk.StringVar()
        self.schedule_type_combo = ttk.Combobox(
            hourly_frame,
            textvariable=self.schedule_type_var,
            values=tuple(SCHEDULE_TYPE_BY_LABEL),
            state="readonly",
        )
        self.schedule_type_combo.grid(
            row=1, column=1, columnspan=2, sticky="ew", pady=(10, 0)
        )
        self.schedule_type_combo.bind(
            "<<ComboboxSelected>>", self._schedule_type_changed
        )
        months_frame = ttk.LabelFrame(hourly_frame, text="Active months", padding=8)
        months_frame.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(10, 0))
        self.schedule_month_vars = {
            month_number: tk.BooleanVar(value=True)
            for month_number in range(1, 13)
        }
        self.schedule_month_checkbuttons: list[ttk.Checkbutton] = []
        for index, (month_number, month_key) in enumerate(
            zip(range(1, 13), MONTH_KEYS, strict=True)
        ):
            checkbox = ttk.Checkbutton(
                months_frame,
                text=month_key.title(),
                variable=self.schedule_month_vars[month_number],
                command=self._schedule_months_changed,
            )
            checkbox.grid(
                row=index // 6,
                column=index % 6,
                sticky="w",
                padx=(0, 10),
                pady=2,
            )
            self.schedule_month_checkbuttons.append(checkbox)
        self.edit_schedule_button = ttk.Button(
            hourly_frame, text="Edit typical week...", command=self.edit_hourly_demand_schedule
        )
        self.edit_schedule_button.grid(row=3, column=0, columnspan=3, sticky="w", pady=(10, 0))
        self.save_schedule_to_library_button = ttk.Button(
            hourly_frame,
            text="Save selected to library",
            command=self.save_selected_schedule_to_library,
        )
        self.save_schedule_to_library_button.grid(row=4, column=0, columnspan=3, sticky="w", pady=(8, 0))
        ttk.Label(hourly_frame, textvariable=self.hourly_schedule_summary_var, foreground="#667278").grid(
            row=5, column=0, columnspan=3, sticky="w", pady=(6, 0)
        )

        library_frame = ttk.LabelFrame(self.schedules_tab, text="Schedule library", padding=10)
        library_frame.grid(row=0, column=2, rowspan=2, sticky="nsew")
        library_frame.columnconfigure(0, weight=1)
        library_frame.rowconfigure(1, weight=1)
        library_toolbar = ttk.Frame(library_frame)
        library_toolbar.grid(row=0, column=0, sticky="w", pady=(0, 6))
        self.library_add_button = ttk.Button(
            library_toolbar,
            image=self.schedule_add_icon,
            command=self.create_custom_library_schedule,
            takefocus=True,
        )
        self.library_add_button.grid(row=0, column=0)
        self.library_duplicate_button = ttk.Button(
            library_toolbar,
            image=self.schedule_duplicate_icon,
            command=self.duplicate_library_schedule,
            takefocus=True,
        )
        self.library_duplicate_button.grid(row=0, column=1, padx=(2, 0))
        self.library_delete_button = ttk.Button(
            library_toolbar,
            image=self.schedule_delete_icon,
            command=self.delete_custom_library_schedule,
            takefocus=True,
        )
        self.library_delete_button.grid(row=0, column=2, padx=(2, 0))
        self.library_tree = ttk.Treeview(library_frame, show="tree", selectmode="browse", height=16)
        self.library_tree.grid(row=1, column=0, sticky="nsew")
        library_scroll = ttk.Scrollbar(library_frame, orient="vertical", command=self.library_tree.yview)
        library_scroll.grid(row=1, column=1, sticky="ns")
        self.library_tree.configure(yscrollcommand=library_scroll.set)
        self.library_tree.tag_configure("group", font=("Segoe UI", 9, "bold"))
        self.library_tree.bind("<<TreeviewSelect>>", self._library_selection_changed)
        self.library_tree.bind("<Double-1>", self._add_library_schedule_from_event)
        self.library_tree.bind("<Return>", self._add_library_schedule_from_event)
        self.add_library_schedule_to_project_button = ttk.Button(
            library_frame,
            text="Add selected to project",
            command=self.add_common_hourly_schedule,
        )
        self.add_library_schedule_to_project_button.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        self._refresh_schedule_library()
        self._refresh_schedule_management()

    def _create_schedule_action_icon(self, color: str, symbol: str, size: int = 26) -> tk.PhotoImage:
        image = tk.PhotoImage(master=self, width=size, height=size)
        center = (size - 1) / 2
        radius = size / 2 - 1
        for y in range(size):
            for x in range(size):
                if (x - center) ** 2 + (y - center) ** 2 <= radius ** 2:
                    image.put(color, (x, y))
        for offset in range(-6, 7):
            if symbol == "+":
                for thickness in (-1, 0, 1):
                    image.put("#ffffff", (int(center + offset), int(center + thickness)))
                    image.put("#ffffff", (int(center + thickness), int(center + offset)))
            elif symbol == "x" and -5 <= offset <= 5:
                for thickness in (-1, 0, 1):
                    image.put("#ffffff", (int(center + offset), int(center + offset + thickness)))
                    image.put("#ffffff", (int(center + offset), int(center - offset + thickness)))
        if symbol == "x2":
            for offset in range(-4, 5):
                for thickness in (-1, 0, 1):
                    image.put("#ffffff", (int(center - 4 + offset), int(center + offset + thickness)))
                    image.put("#ffffff", (int(center - 4 + offset), int(center - offset + thickness)))
            for x in range(15, 21):
                for thickness in (-1, 0, 1):
                    image.put("#ffffff", (x, 7 + thickness))
                    image.put("#ffffff", (x, 12 + thickness))
                    image.put("#ffffff", (x, 18 + thickness))
            for y in range(8, 12):
                for thickness in (-1, 0, 1):
                    image.put("#ffffff", (20 + thickness, y))
            for y in range(13, 18):
                for thickness in (-1, 0, 1):
                    image.put("#ffffff", (15 + thickness, y))
        return image

    def _create_tabler_trash_icon(
        self, color: str = "#c62828", size: int = 26
    ) -> tk.PhotoImage:
        """Rasterize the MIT-licensed Tabler outline trash icon for Tk buttons."""
        image = tk.PhotoImage(master=self, width=size, height=size)
        scale = (size - 2) / 24.0

        def point(x: float, y: float) -> tuple[int, int]:
            return round(1 + x * scale), round(1 + y * scale)

        def line(start: tuple[float, float], end: tuple[float, float]) -> None:
            x1, y1 = point(*start)
            x2, y2 = point(*end)
            steps = max(abs(x2 - x1), abs(y2 - y1), 1)
            for index in range(steps + 1):
                x = round(x1 + (x2 - x1) * index / steps)
                y = round(y1 + (y2 - y1) * index / steps)
                for offset_x, offset_y in ((0, 0), (1, 0), (0, 1)):
                    target_x, target_y = x + offset_x, y + offset_y
                    if 0 <= target_x < size and 0 <= target_y < size:
                        image.put(color, (target_x, target_y))

        # Tabler "trash" icon geometry on its native 24 x 24 grid.
        for start, end in (
            ((4, 7), (20, 7)),
            ((10, 11), (10, 17)),
            ((14, 11), (14, 17)),
            ((5, 7), (6, 19)),
            ((6, 19), (8, 21)),
            ((8, 21), (16, 21)),
            ((16, 21), (18, 19)),
            ((18, 19), (19, 7)),
            ((9, 7), (9, 4)),
            ((9, 4), (10, 3)),
            ((10, 3), (14, 3)),
            ((14, 3), (15, 4)),
            ((15, 4), (15, 7)),
        ):
            line(start, end)
        return image

    def _build_demand_tab(self) -> None:
        self.demand_tab.columnconfigure(0, weight=1)
        self.demand_tab.rowconfigure(0, weight=1)
        self.demand_settings_notebook = ttk.Notebook(self.demand_tab)
        self.demand_settings_notebook.grid(row=0, column=0, sticky="nsew")
        self.overall_demand_settings_tab = ttk.Frame(self.demand_settings_notebook, padding=10)
        self.demand_settings_notebook.add(self.overall_demand_settings_tab, text="Overall demand settings")

        overall = self.overall_demand_settings_tab
        overall.columnconfigure(0, weight=1)
        overall.rowconfigure(1, weight=1)
        overall.rowconfigure(2, weight=1)
        settings_frame = ttk.LabelFrame(overall, text="Simple demand settings", padding=10)
        settings_frame.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        settings_frame.columnconfigure(1, weight=1)
        self._labeled_entry(settings_frame, 0, "Simple daily demand", self.simple_daily_var, self.simple_daily_unit_var)
        ttk.Label(settings_frame, text="Daily demand schedule").grid(row=1, column=0, sticky="w", pady=2)
        self.daily_demand_days_combo = ttk.Combobox(
            settings_frame,
            textvariable=self.daily_demand_days_var,
            values=[str(value) for value in range(8)],
            width=8,
            state="readonly",
        )
        self.daily_demand_days_combo.grid(row=1, column=1, sticky="ew", pady=2)
        ttk.Label(settings_frame, text="days/week").grid(row=1, column=2, sticky="w", padx=(8, 0), pady=2)
        self._labeled_entry(settings_frame, 2, "Average flushes", self.flushes_var, self.flush_count_unit_var)
        self._labeled_entry(settings_frame, 3, "Toilet volume", self.toilet_flush_var, self.flush_volume_unit_var)
        self._labeled_entry(settings_frame, 4, "Urinal volume", self.urinal_flush_var, self.flush_volume_unit_var)

        monthly_frame = ttk.LabelFrame(overall, text="Monthly demand", padding=8)
        monthly_frame.grid(row=1, column=0, sticky="nsew")
        monthly_frame.columnconfigure(0, weight=1)
        monthly_frame.rowconfigure(0, weight=1)
        columns = ["month"] + [field for field, _label in DEMAND_FIELDS]
        self.demand_tree = ttk.Treeview(
            monthly_frame, columns=columns, show="headings", height=12, style="MonthlyDemand.Treeview"
        )
        self.demand_tree.heading("month", text="Month")
        self.demand_tree.column("month", width=80, anchor="w")
        for field, _label in DEMAND_FIELDS:
            self.demand_tree.column(field, width=105, anchor="e")
        self._update_demand_headings()
        self.demand_tree.grid(row=0, column=0, sticky="nsew")
        self.demand_tree.bind("<Double-1>", self._edit_demand_month_from_event)
        scroll_x = ttk.Scrollbar(monthly_frame, orient="horizontal", command=self.demand_tree.xview)
        scroll_x.grid(row=1, column=0, sticky="ew")
        self.demand_tree.configure(xscrollcommand=scroll_x.set)
        ttk.Button(monthly_frame, text="Edit Selected Month", command=self.edit_demand_month).grid(
            row=2, column=0, sticky="w", pady=(8, 0)
        )
        # Aggregate inputs remain instantiated for backward-compatible form/model
        # plumbing, but migrated projects are edited exclusively as demand objects.
        settings_frame.grid_remove()
        monthly_frame.grid_remove()
        overall.rowconfigure(0, weight=1)
        overall.rowconfigure(1, weight=0)
        overall.rowconfigure(2, weight=0)

        demand_objects_workspace = ttk.LabelFrame(
            overall, text="Demand objects and library", padding=8
        )
        demand_objects_workspace.grid(row=0, column=0, sticky="nsew")
        self._build_demand_objects_workspace(demand_objects_workspace, "overall")
        self.demand_objects_tree = self.overall_demand_objects_tree
        self.demand_library_tree = self.overall_demand_library_tree
        self._refresh_demand_object_library()

    def _build_demand_objects_workspace(self, parent: ttk.Frame, prefix: str) -> None:
        parent.columnconfigure(0, weight=2)
        parent.columnconfigure(1, weight=1)
        parent.rowconfigure(0, weight=1)
        demand_objects_frame = ttk.LabelFrame(parent, text="Demand objects", padding=8)
        demand_objects_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        demand_objects_frame.columnconfigure(0, weight=1)
        demand_objects_frame.rowconfigure(0, weight=1)
        objects_tree = ttk.Treeview(
            demand_objects_frame,
            columns=("name", "type", "instantaneous_demand", "schedule", "sewer"),
            show="headings",
            height=12,
            selectmode="browse",
        )
        objects_tree.heading("name", text="Name")
        objects_tree.heading("type", text="Type")
        objects_tree.heading("instantaneous_demand", text="Demand")
        objects_tree.heading("schedule", text="Schedule")
        objects_tree.heading("sewer", text="Sewer savings")
        objects_tree.column("name", width=190)
        objects_tree.column("type", width=140)
        objects_tree.column("instantaneous_demand", width=165, anchor="e")
        objects_tree.column("schedule", width=190)
        objects_tree.column("sewer", width=105, anchor="center")
        objects_tree.grid(row=0, column=0, sticky="nsew")
        demand_object_scroll = ttk.Scrollbar(
            demand_objects_frame, orient="vertical", command=objects_tree.yview
        )
        demand_object_scroll.grid(row=0, column=1, sticky="ns")
        objects_tree.configure(yscrollcommand=demand_object_scroll.set)
        objects_tree.bind("<Double-1>", self._edit_demand_object_from_event)
        objects_tree.bind("<Return>", self._edit_selected_demand_object_from_event)
        setattr(self, f"{prefix}_demand_objects_tree", objects_tree)
        object_buttons = ttk.Frame(demand_objects_frame)
        object_buttons.grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Button(object_buttons, text="Add demand object", command=self.add_demand_object).grid(row=0, column=0)
        ttk.Button(object_buttons, text="Edit selected", command=self.edit_demand_object).grid(
            row=0, column=1, padx=(6, 0)
        )
        ttk.Button(object_buttons, text="Delete selected", command=self.delete_demand_object).grid(
            row=0, column=2, padx=(6, 0)
        )
        ttk.Button(object_buttons, text="Save selected to library", command=self.save_selected_demand_object_to_library).grid(
            row=0, column=3, padx=(6, 0)
        )

        demand_library_frame = ttk.LabelFrame(parent, text="Demand object library", padding=8)
        demand_library_frame.grid(row=0, column=1, sticky="nsew")
        demand_library_frame.columnconfigure(0, weight=1)
        demand_library_frame.rowconfigure(1, weight=1)
        demand_library_toolbar = ttk.Frame(demand_library_frame)
        demand_library_toolbar.grid(row=0, column=0, sticky="w", pady=(0, 6))
        demand_library_add_button = ttk.Button(
            demand_library_toolbar, image=self.schedule_add_icon, command=self.create_custom_demand_object_template
        )
        demand_library_add_button.grid(row=0, column=0)
        demand_library_duplicate_button = ttk.Button(
            demand_library_toolbar, image=self.schedule_duplicate_icon, command=self.duplicate_demand_object_template
        )
        demand_library_duplicate_button.grid(row=0, column=1, padx=(2, 0))
        demand_library_delete_button = ttk.Button(
            demand_library_toolbar, image=self.schedule_delete_icon, command=self.delete_custom_demand_object_template
        )
        demand_library_delete_button.grid(row=0, column=2, padx=(2, 0))
        library_tree = ttk.Treeview(demand_library_frame, show="tree", selectmode="browse", height=12)
        library_tree.grid(row=1, column=0, sticky="nsew")
        demand_library_scroll = ttk.Scrollbar(
            demand_library_frame, orient="vertical", command=library_tree.yview
        )
        demand_library_scroll.grid(row=1, column=1, sticky="ns")
        library_tree.configure(yscrollcommand=demand_library_scroll.set)
        library_tree.tag_configure("group", font=("Segoe UI", 9, "bold"))
        library_tree.bind("<<TreeviewSelect>>", self._demand_library_selection_changed)
        library_tree.bind("<Double-1>", self._add_demand_library_object_from_event)
        library_tree.bind("<Return>", self._add_demand_library_object_from_event)
        add_library_button = ttk.Button(
            demand_library_frame, text="Add selected to project", command=self.add_demand_object_from_library
        )
        add_library_button.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        setattr(self, f"{prefix}_demand_library_tree", library_tree)
        setattr(self, f"{prefix}_demand_library_duplicate_button", demand_library_duplicate_button)
        setattr(self, f"{prefix}_demand_library_delete_button", demand_library_delete_button)
        setattr(self, f"{prefix}_add_demand_library_to_project_button", add_library_button)

    def _scroll_analysis_mousewheel(self, event: tk.Event) -> str | None:
        if not hasattr(self, "analysis_scroll_canvas"):
            return None
        if self.notebook.select() != str(self.analysis_tab):
            return None
        pointer_x, pointer_y = self.winfo_pointerxy()
        canvas = self.analysis_scroll_canvas
        canvas_x, canvas_y = canvas.winfo_rootx(), canvas.winfo_rooty()
        if not (
            canvas_x <= pointer_x < canvas_x + canvas.winfo_width()
            and canvas_y <= pointer_y < canvas_y + canvas.winfo_height()
        ):
            return None
        if getattr(event, "num", None) == 4:
            direction = -1
        elif getattr(event, "num", None) == 5:
            direction = 1
        else:
            direction = -1 if event.delta > 0 else 1
        canvas.yview_scroll(direction, "units")
        return "break"

    def _resize_analysis_scroll_content(self, event: tk.Event) -> None:
        self.analysis_scroll_canvas.itemconfigure(
            self.analysis_scroll_window, width=event.width
        )

    def _update_analysis_scroll_region(self, _event: tk.Event | None = None) -> None:
        self.analysis_scroll_canvas.configure(
            scrollregion=self.analysis_scroll_canvas.bbox("all")
        )

    def _build_analysis_tab(self) -> None:
        self.analysis_tab.columnconfigure(0, weight=1)
        self.analysis_tab.rowconfigure(0, weight=1)
        self.analysis_scroll_canvas = tk.Canvas(
            self.analysis_tab, highlightthickness=0, borderwidth=0
        )
        self.analysis_scroll_canvas.grid(row=0, column=0, sticky="nsew")
        self.analysis_scrollbar = ttk.Scrollbar(
            self.analysis_tab,
            orient="vertical",
            command=self.analysis_scroll_canvas.yview,
        )
        self.analysis_scrollbar.grid(row=0, column=1, sticky="ns")
        self.analysis_scroll_canvas.configure(
            yscrollcommand=self.analysis_scrollbar.set
        )
        analysis_content = ttk.Frame(self.analysis_scroll_canvas, padding=(0, 0, 8, 0))
        self.analysis_scroll_content = analysis_content
        self.analysis_scroll_window = self.analysis_scroll_canvas.create_window(
            (0, 0), window=analysis_content, anchor="nw"
        )
        analysis_content.columnconfigure(0, weight=1)
        analysis_content.rowconfigure(3, weight=1)
        analysis_content.bind("<Configure>", self._update_analysis_scroll_region)
        self.analysis_scroll_canvas.bind(
            "<Configure>", self._resize_analysis_scroll_content
        )
        self.bind_all("<MouseWheel>", self._scroll_analysis_mousewheel, add="+")
        self.bind_all("<Button-4>", self._scroll_analysis_mousewheel, add="+")
        self.bind_all("<Button-5>", self._scroll_analysis_mousewheel, add="+")

        resolution_frame = ttk.LabelFrame(
            analysis_content, text="Analysis resolution", padding=10
        )
        resolution_frame.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        resolution_frame.columnconfigure(0, weight=1)
        ttk.Label(
            resolution_frame,
            textvariable=self.applied_analysis_resolution_var,
            foreground="#33444c",
            wraplength=900,
            justify="left",
        ).grid(row=0, column=0, sticky="ew")
        ttk.Label(
            resolution_frame,
            text=(
                "Read-only. The daily mass balance is retained for the sizing curve, and the "
                "hourly timing simulation uses the rainfall and demand modes below."
            ),
            foreground="#667278",
            wraplength=900,
            justify="left",
        ).grid(row=1, column=0, sticky="ew", pady=(5, 0))

        hourly_analysis_frame = ttk.LabelFrame(
            analysis_content, text="Timing assumptions", padding=10
        )
        hourly_analysis_frame.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        hourly_analysis_frame.columnconfigure(0, weight=1)

        rainfall_timing_frame = ttk.LabelFrame(
            hourly_analysis_frame, text="Rainfall timing", padding=8
        )
        rainfall_timing_frame.grid(row=0, column=0, sticky="ew")
        rainfall_timing_frame.columnconfigure(1, weight=1)
        self.daily_rainfall_timing_radio = ttk.Radiobutton(
            rainfall_timing_frame,
            text="Daily total at end of day",
            variable=self.use_synthetic_hourly_rainfall_var,
            value=False,
            command=self._synthetic_hourly_rainfall_setting_changed,
        )
        self.daily_rainfall_timing_radio.grid(row=0, column=0, sticky="nw")
        ttk.Label(
            rainfall_timing_frame,
            text="Uses the source daily totals; rainfall is applied at 23:00.",
            foreground="#667278",
        ).grid(row=0, column=1, columnspan=2, sticky="nw", padx=(16, 0))
        self.synthetic_hourly_rainfall_radio = ttk.Radiobutton(
            rainfall_timing_frame,
            text="Synthetic hourly timing",
            variable=self.use_synthetic_hourly_rainfall_var,
            value=True,
            command=self._synthetic_hourly_rainfall_setting_changed,
        )
        self.synthetic_hourly_rainfall_radio.grid(row=1, column=0, sticky="nw", pady=(7, 0))
        ttk.Label(
            rainfall_timing_frame,
            text=(
                "Distributes each daily total using a generated profile. The timing is "
                "synthetic, not observed hourly rainfall."
            ),
            foreground="#667278",
            wraplength=610,
            justify="left",
        ).grid(row=1, column=1, sticky="nw", padx=(16, 0), pady=(7, 0))
        self.analysis_generate_hourly_rainfall_button = ttk.Button(
            rainfall_timing_frame,
            text="Generate hourly profile...",
            command=self.generate_hourly_rainfall,
        )
        self.analysis_generate_hourly_rainfall_button.grid(
            row=1, column=2, sticky="ne", padx=(12, 0), pady=(7, 0)
        )
        ttk.Label(
            rainfall_timing_frame,
            textvariable=self.synthetic_hourly_rainfall_status_var,
            foreground="#667278",
            wraplength=930,
            justify="left",
        ).grid(row=2, column=0, columnspan=3, sticky="ew", pady=(7, 0))

        demand_timing_frame = ttk.LabelFrame(
            hourly_analysis_frame, text="Demand timing", padding=8
        )
        demand_timing_frame.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        demand_timing_frame.columnconfigure(1, weight=1)
        self.daily_demand_timing_radio = ttk.Radiobutton(
            demand_timing_frame,
            text="Daily",
            variable=self.hourly_schedule_enabled_var,
            value=False,
            command=self._hourly_schedule_enabled_changed,
        )
        self.daily_demand_timing_radio.grid(row=0, column=0, sticky="nw")
        ttk.Label(
            demand_timing_frame,
            text=(
                "Runs the daily mass balance only. The hourly demand profile remains saved, "
                "but no full hourly result is generated."
            ),
            foreground="#667278",
            wraplength=760,
            justify="left",
        ).grid(row=0, column=1, columnspan=2, sticky="nw", padx=(16, 0))
        self.hourly_demand_timing_radio = ttk.Radiobutton(
            demand_timing_frame,
            text="Hourly",
            variable=self.hourly_schedule_enabled_var,
            value=True,
            command=self._hourly_schedule_enabled_changed,
        )
        self.hourly_demand_timing_radio.grid(row=1, column=0, sticky="nw", pady=(7, 0))
        ttk.Label(demand_timing_frame, text="Schedule:").grid(
            row=1, column=1, sticky="w", padx=(16, 8), pady=(7, 0)
        )
        ttk.Label(
            demand_timing_frame,
            textvariable=self.hourly_demand_schedule_selection_var,
        ).grid(row=1, column=2, sticky="w", pady=(7, 0))
        self.hourly_schedule_change_button = ttk.Button(
            demand_timing_frame,
            text="Change...",
            command=lambda: self.notebook.select(self.schedules_tab),
        )
        self.hourly_schedule_change_button.grid(row=1, column=3, sticky="e", padx=(12, 0), pady=(7, 0))
        ttk.Label(
            demand_timing_frame,
            text="Applies the preserved demand profile hour by hour and generates full hourly results.",
            foreground="#667278",
        ).grid(row=2, column=1, columnspan=3, sticky="w", padx=(16, 0), pady=(5, 0))

        applied_settings_frame = ttk.LabelFrame(
            analysis_content, text="Applied analysis settings (read-only)", padding=10
        )
        applied_settings_frame.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        applied_settings_frame.columnconfigure(1, weight=1)
        applied_settings = (
            ("Analysis resolution", self.applied_analysis_resolution_var),
            ("Rainfall source", self.applied_rainfall_source_var),
            ("Rainfall timing", self.applied_rainfall_timing_var),
            ("Demand timing", self.applied_demand_timing_var),
        )
        for row, (label, variable) in enumerate(applied_settings):
            ttk.Label(applied_settings_frame, text=label).grid(
                row=row, column=0, sticky="nw", padx=(0, 16), pady=2
            )
            ttk.Label(
                applied_settings_frame,
                textvariable=variable,
                foreground="#33444c",
                wraplength=780,
                justify="left",
            ).grid(row=row, column=1, sticky="ew", pady=2)

        self._refresh_synthetic_hourly_rainfall_status()

        comparison_frame = ttk.LabelFrame(
            analysis_content, text="Tank size comparison", padding=10
        )
        comparison_frame.grid(row=3, column=0, sticky="nsew")
        self.comparison_frame = comparison_frame
        comparison_frame.columnconfigure(0, weight=1)
        comparison_frame.rowconfigure(2, weight=1)
        self.multitank_comparison_check = ttk.Checkbutton(
            comparison_frame,
            text="Multi-tank comparison",
            variable=self.multitank_comparison_var,
            command=self._toggle_multitank_comparison,
        )
        self.multitank_comparison_check.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
        add_row = ttk.Frame(comparison_frame)
        add_row.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        add_row.columnconfigure(1, weight=1)
        ttk.Label(add_row, text="Tank size").grid(row=0, column=0, sticky="w")
        self.comparison_tank_entry = ttk.Entry(add_row, textvariable=self.comparison_tank_var, width=16)
        self.comparison_tank_entry.grid(row=0, column=1, sticky="ew", padx=(8, 8))
        self.comparison_tank_entry.bind("<Return>", self._add_comparison_tank_from_entry)
        ttk.Label(add_row, textvariable=self.tank_size_unit_var).grid(row=0, column=2, sticky="w")
        ttk.Button(add_row, text="Add", command=self.add_comparison_tank).grid(row=0, column=3, padx=(8, 0))

        self.comparison_tree = ttk.Treeview(
            comparison_frame,
            columns=("size", "reliability", "status"),
            show="headings",
            height=12,
            selectmode="extended",
        )
        self.comparison_tree.heading("size", text="Tank size")
        self.comparison_tree.heading("reliability", text="Reliability")
        self.comparison_tree.heading("status", text="")
        self.comparison_tree.column("size", width=150, anchor="e")
        self.comparison_tree.column("reliability", width=130, anchor="e")
        self.comparison_tree.column("status", width=72, minwidth=72, anchor="w", stretch=False)
        self.comparison_tree.tag_configure("primary", foreground="#0563c1", font=("Segoe UI", 9, "bold"))
        self.comparison_tree.grid(row=2, column=0, sticky="nsew")
        comparison_scroll = ttk.Scrollbar(comparison_frame, orient="vertical", command=self.comparison_tree.yview)
        comparison_scroll.grid(row=2, column=1, sticky="ns")
        self.comparison_tree.configure(yscrollcommand=comparison_scroll.set)
        self.comparison_tree.bind("<Double-1>", self._use_comparison_as_primary_from_event)

        comparison_buttons = ttk.Frame(comparison_frame)
        comparison_buttons.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(comparison_buttons, text="Remove selected", command=self.remove_comparison_tanks).grid(
            row=0, column=0, padx=(0, 8)
        )
        ttk.Button(comparison_buttons, text="Use as primary", command=self.use_comparison_as_primary).grid(
            row=0, column=1
        )
        self._update_multitank_comparison_state()

        self.optimization_tab.columnconfigure(0, weight=1)
        self.optimization_tab.rowconfigure(0, weight=1)
        assumptions = ttk.Frame(self.optimization_tab)
        assumptions.grid(row=0, column=0, sticky="nsew", pady=(0, 10))
        assumptions.columnconfigure(0, weight=1)
        assumptions.columnconfigure(1, weight=0)
        assumptions.rowconfigure(0, weight=1)
        self._info_button(
            assumptions,
            lambda: messagebox.showinfo(
                "Optimization problem definition and assumptions",
                OPTIMIZATION_SECTION_HELP["Problem assumptions"],
                parent=self,
            ),
        ).grid(row=0, column=1, sticky="ne", padx=(6, 0), pady=(1, 0))
        self.optimization_catalog_notebook = ttk.Notebook(assumptions)
        self.optimization_catalog_notebook.grid(row=0, column=0, sticky="nsew")
        assumptions_tab = ttk.Frame(self.optimization_catalog_notebook, padding=6)
        candidates_tab = ttk.Frame(self.optimization_catalog_notebook, padding=6)
        library_tab = ttk.Frame(self.optimization_catalog_notebook, padding=6)
        constraints_tab = ttk.Frame(self.optimization_catalog_notebook, padding=6)
        compatibility_tab = ttk.Frame(self.optimization_catalog_notebook, padding=6)
        self.optimization_catalog_notebook.add(assumptions_tab, text="Problem assumptions")
        self.optimization_catalog_notebook.add(candidates_tab, text="Project candidates")
        self.optimization_catalog_notebook.add(library_tab, text="Equipment library")
        self.optimization_catalog_notebook.add(constraints_tab, text="Project constraints")
        self.optimization_catalog_notebook.add(compatibility_tab, text="Compatibility review")
        optimization_results_tab = ttk.Frame(self.optimization_catalog_notebook, padding=10)
        self.optimization_catalog_notebook.add(optimization_results_tab, text="Optimization setup and results")
        assumptions_tab.columnconfigure(0, weight=1)
        assumptions_tab.rowconfigure(0, weight=1)
        self.optimization_assumptions_tree = ttk.Treeview(
            assumptions_tab, columns=("classification", "item", "value", "source"), show="headings", height=6
        )
        for column, heading, width in (
            ("classification", "Classification", 125), ("item", "Variable / assumption", 235),
            ("value", "Value used", 360), ("source", "Source / edit location", 190),
        ):
            self.optimization_assumptions_tree.heading(column, text=heading)
            self.optimization_assumptions_tree.column(column, width=width, anchor="w")
        self.optimization_assumptions_tree.grid(row=0, column=0, sticky="nsew")
        assumptions_scroll = ttk.Scrollbar(assumptions_tab, orient="vertical", command=self.optimization_assumptions_tree.yview)
        assumptions_scroll.grid(row=0, column=1, sticky="ns")
        self.optimization_assumptions_tree.configure(yscrollcommand=assumptions_scroll.set)
        self._build_project_candidates_tab(candidates_tab)
        self._build_equipment_library_tab(library_tab)
        self._build_equipment_constraints_tab(constraints_tab)
        self._build_compatibility_review_tab(compatibility_tab)

        optimization_frame = optimization_results_tab
        optimization_frame.columnconfigure(0, weight=1)
        optimization_frame.rowconfigure(6, weight=1)

        objective_row = ttk.Frame(optimization_frame)
        objective_row.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        ttk.Label(objective_row, text="Objectives", font=("Segoe UI", 9, "bold")).pack(side="left")
        ttk.Button(
            objective_row, text="ⓘ", width=2,
            command=lambda: messagebox.showinfo(
                "Objectives", OPTIMIZATION_SECTION_HELP["Objectives"], parent=self
            ),
        ).pack(side="left", padx=(5, 0))
        ttk.Label(objective_row, text="Optimize for").pack(side="left", padx=(12, 0))
        ttk.Combobox(
            objective_row, textvariable=self.optimization_objective_var,
            values=("Simple payback", "Net annual savings", "Rainwater reliability", "Analysis-period net benefit", "Lifecycle NPV"),
            state="readonly", width=23,
        ).pack(side="left", padx=(8, 16))
        ttk.Separator(objective_row, orient="vertical").pack(side="left", fill="y", padx=(0, 16))
        ttk.Label(objective_row, text="Fixed assumption:", font=("Segoe UI", 9, "bold")).pack(side="left")
        ttk.Label(objective_row, text="Electricity price").pack(side="left", padx=(6, 0))
        ttk.Entry(objective_row, textvariable=self.optimization_electricity_rate_var, width=9).pack(
            side="left", padx=(8, 3)
        )
        ttk.Label(objective_row, text="currency/kWh").pack(side="left")

        constraints_heading = ttk.Frame(optimization_frame)
        constraints_heading.grid(row=1, column=0, sticky="w", pady=(2, 4))
        ttk.Label(constraints_heading, text="Constraints", font=("Segoe UI", 9, "bold")).pack(side="left")
        ttk.Button(
            constraints_heading, text="ⓘ", width=2,
            command=lambda: messagebox.showinfo(
                "Constraints", OPTIMIZATION_SECTION_HELP["Constraints"], parent=self
            ),
        ).pack(side="left", padx=(5, 0))
        constraint_fields = ttk.Frame(optimization_frame)
        constraint_fields.grid(row=2, column=0, sticky="ew")
        ttk.Label(constraint_fields, text="Minimum rainwater reliability").pack(side="left")
        ttk.Entry(constraint_fields, textvariable=self.optimization_minimum_reliability_var, width=7).pack(
            side="left", padx=(8, 3)
        )
        ttk.Label(constraint_fields, text="%").pack(side="left", padx=(0, 14))
        ttk.Label(constraint_fields, text="Maximum annual municipal makeup").pack(side="left")
        ttk.Entry(constraint_fields, textvariable=self.optimization_maximum_makeup_var, width=7).pack(
            side="left", padx=(8, 3)
        )
        ttk.Label(constraint_fields, textvariable=self.tank_size_unit_var).pack(side="left", padx=(0, 14))

        secondary_constraint_fields = ttk.Frame(optimization_frame)
        secondary_constraint_fields.grid(row=3, column=0, sticky="ew", pady=(4, 0))
        ttk.Label(secondary_constraint_fields, text="Maximum installed cost").pack(side="left")
        ttk.Entry(secondary_constraint_fields, textvariable=self.optimization_maximum_cost_var, width=7).pack(
            side="left", padx=(8, 3)
        )
        ttk.Label(secondary_constraint_fields, textvariable=self.financial_currency_var).pack(
            side="left", padx=(0, 14)
        )
        ttk.Checkbutton(
            secondary_constraint_fields, text="Require positive net annual savings",
            variable=self.optimization_positive_savings_var,
        ).pack(side="left")

        catalog_row = ttk.Frame(optimization_frame)
        catalog_row.grid(row=4, column=0, sticky="ew", pady=(8, 6))
        ttk.Label(catalog_row, text="Catalog", font=("Segoe UI", 9, "bold")).pack(side="left")
        ttk.Button(
            catalog_row, text="ⓘ", width=2,
            command=lambda: messagebox.showinfo(
                "Catalog", OPTIMIZATION_SECTION_HELP["Catalog"], parent=self
            ),
        ).pack(side="left", padx=(5, 0))
        ttk.Button(catalog_row, text="Equipment candidates...", command=self._show_equipment_candidates).pack(
            side="left", padx=(12, 0)
        )
        ttk.Label(
            catalog_row,
            text=("Shared library products are applied as project snapshots; eligibility and compatibility "
                  "are reviewed before optimization."),
            foreground="#667278",
        ).pack(side="left", padx=(12, 0))
        ttk.Button(catalog_row, text="Run optimization", command=self.run_system_optimization).pack(side="right")

        results_heading = ttk.Frame(optimization_frame)
        results_heading.grid(row=5, column=0, sticky="w", pady=(0, 4))
        ttk.Label(results_heading, text="Results", font=("Segoe UI", 9, "bold")).pack(side="left")
        ttk.Button(
            results_heading, text="ⓘ", width=2,
            command=lambda: messagebox.showinfo(
                "Results", OPTIMIZATION_SECTION_HELP["Results"], parent=self
            ),
        ).pack(side="left", padx=(5, 0))
        self.optimization_tree = ttk.Treeview(
            optimization_frame,
            columns=("rank", "tank", "pump", "filter", "booster", "reliability", "makeup", "energy", "cost", "savings", "payback", "npv"),
            show="headings", height=4,
        )
        headings = (
            ("rank", "Rank", 45), ("tank", "Primary tank", 100), ("pump", "Transfer pump", 100),
            ("filter", "Filtration system", 105),
            ("booster", "Buffer tank", 100), ("reliability", "Reliability", 85),
            ("makeup", "Municipal/year", 100),
            ("energy", "Energy/year", 90), ("cost", "Installed cost", 105),
            ("savings", "Net savings/year", 115), ("payback", "Simple payback", 100),
            ("npv", "Lifecycle NPV", 110),
        )
        for column, label, width in headings:
            self.optimization_tree.heading(column, text=label)
            self.optimization_tree.column(column, width=width, anchor="e" if column not in {"tank", "pump", "filter", "booster"} else "w")
        self.optimization_tree.grid(row=6, column=0, sticky="nsew")
        optimization_scroll = ttk.Scrollbar(optimization_frame, orient="vertical", command=self.optimization_tree.yview)
        optimization_scroll.grid(row=6, column=1, sticky="ns")
        self.optimization_tree.configure(yscrollcommand=optimization_scroll.set)
        ttk.Label(optimization_frame, textvariable=self.optimization_status_var, foreground="#667278").grid(
            row=7, column=0, columnspan=2, sticky="w", pady=(6, 0)
        )

    def _refresh_optimization_assumptions(self) -> None:
        if not hasattr(self, "optimization_assumptions_tree"):
            return
        cfg = self.config_model
        optimization = cfg.optimization_parameters
        financial = cfg.financial_parameters
        system = cfg.system_parameters
        unit = volume_unit(cfg)
        candidates = self._project_candidates()
        counts = {
            category: sum(
                effective_candidate_product(row)["category"] == category
                and row.get("disposition", "Candidate") != "Excluded"
                for row in candidates
            ) for category in EQUIPMENT_CATEGORIES
        }
        if self.rainfall_df.empty:
            rainfall_value = "Not loaded"
        else:
            rainfall_value = (
                f"{len(self.rainfall_df):,} daily rows, "
                f"{pd.Timestamp(self.rainfall_df['Date'].min()).date()} to "
                f"{pd.Timestamp(self.rainfall_df['Date'].max()).date()}"
            )
        collection_area = sum(max(float(surface.area), 0.0) for surface in cfg.surfaces)
        maximum_makeup = (
            "No limit" if optimization.maximum_annual_municipal_makeup_gallons is None
            else f"{format_number(volume_to_display(optimization.maximum_annual_municipal_makeup_gallons, cfg), cfg, max_decimal_places=0)} {unit}/year"
        )
        maximum_cost = (
            "No limit" if optimization.maximum_installed_cost is None
            else f"{financial.currency} {format_number(optimization.maximum_installed_cost, cfg)}"
        )
        rows = [
            ("Design variable", "Primary tank product", f"{counts['Primary tank']} catalog choices", "Optimization catalog"),
            ("Design variable", "Transfer pump product", f"{counts['Transfer pump']} catalog choices", "Optimization catalog"),
            ("Design variable", "Filtration system product", f"{counts['Filtration system']} catalog choices", "Optimization catalog"),
            ("Design variable", "Buffer tank product", f"{counts['Buffer tank']} catalog choices", "Optimization catalog"),
            ("Fixed input", "Rainfall record", rainfall_value, "Rainwater Data"),
            ("Fixed input", "Collection surfaces", f"{len(cfg.surfaces)} surfaces; {format_number(area_to_display(collection_area, cfg), cfg, max_decimal_places=0)} {area_unit(cfg)}", "Collection surfaces"),
            ("Fixed input", "Simple recurring demand", f"{format_number(volume_to_display(cfg.demand.simple_daily_demand_gallons, cfg), cfg, max_decimal_places=1)} {unit}/day; {cfg.demand.daily_demand_days_per_week} days/week", "Demand parameters"),
            ("Fixed input", "Demand objects", f"{len(cfg.demand.demand_objects)} objects", "Demand parameters / Schedules"),
            ("Model constant", "Simulation resolution", "Hourly; historical rainfall repeated only as supplied", "Hourly engine"),
            ("Model constant", "Daily rainfall timing", "Collected rainfall enters after that day's demand", "Hourly engine"),
            ("Fixed input", "Primary tank initial fill", f"{format_number(cfg.tank_parameters.initial_fill_percent, cfg)}%", "System parameters / Edit"),
            ("Hard operating constraint", "Primary minimum operating level", f"{format_number(cfg.tank_parameters.minimum_operating_volume_percent, cfg)}% of capacity", "System parameters / Edit"),
            ("Fixed input", "Filter recovery", f"{format_number(system.filter_recovery_percent, cfg)}%", "System parameters / Edit"),
            ("Fixed input", "Buffer initial fill / refill level", f"{format_number(system.booster_initial_fill_percent, cfg)}% / {format_number(system.booster_refill_level_percent, cfg)}%", "System parameters / Edit"),
            ("Fixed input", "Municipal backup", "Enabled" if system.municipal_backup_enabled else "Disabled", "System parameters / Edit"),
            ("Objective", "Ranking objective", optimization.objective, "Optimization"),
            ("Constraint", "Minimum rainwater reliability", f"{format_number(optimization.minimum_reliability_percent, cfg)}%", "Optimization"),
            ("Constraint", "Maximum annual municipal makeup", maximum_makeup, "Optimization"),
            ("Constraint", "Maximum installed cost", maximum_cost, "Optimization"),
            ("Constraint", "Positive net annual savings", "Required" if optimization.require_positive_net_savings else "Not required", "Optimization"),
            ("Economic input", "Water / sewer tariff", f"{financial.currency} {financial.water_rate:g} / {financial.sewer_rate:g} {financial.tariff_billing_unit}", "Financial analysis"),
            ("Economic input", "Legacy aggregate sewer eligibility", f"{financial.sewer_eligible_percent:g}%", "Financial analysis"),
            ("Economic input", "Base cost / incentives", f"{financial.currency} {format_number(financial.installed_cost, cfg)} / {format_number(financial.incentives, cfg)}", "Financial analysis"),
            ("Economic input", "Annual maintenance", f"{financial.currency} {format_number(financial.fixed_annual_maintenance, cfg)} + {format_number(financial.annual_maintenance_percent, cfg)}% of installed cost", "Financial analysis"),
            ("Economic input", "Electricity price", f"{financial.currency} {optimization.electricity_rate_per_kwh:g}/kWh", "Optimization"),
            ("Economic input", "Analysis period / discount rate", f"{financial.analysis_period_years} years / {financial.discount_rate_percent:g}%", "Financial analysis"),
            ("Economic input", "Utility / maintenance escalation", f"{financial.utility_rate_escalation_percent:g}% / {financial.maintenance_escalation_percent:g}%", "Financial analysis"),
            ("Economic input", "Electricity / replacement escalation", f"{financial.electricity_escalation_percent:g}% / {financial.equipment_replacement_escalation_percent:g}%", "Financial analysis"),
            ("Economic input", "Recurring replacement", f"{financial.currency} {format_number(financial.equipment_replacement_cost, cfg)} every {financial.equipment_replacement_interval_years} year(s)", "Financial analysis"),
            ("Search method", "Candidate enumeration", f"Up to {math.prod(counts.values())} combinations before compatibility filtering", "Optimization backend"),
            ("Performance method", "Candidate evaluation", "Aggregate hourly arrays; prepared inputs and bounded candidate results cached for unchanged runs", "Optimization backend"),
        ]
        self.optimization_assumptions_tree.delete(*self.optimization_assumptions_tree.get_children())
        for row in rows:
            self.optimization_assumptions_tree.insert("", "end", values=row)
        self._refresh_equipment_catalog_views()

    def run_system_optimization(self) -> None:
        if self.analysis_running:
            self.optimization_status_var.set("Wait for the current analysis to finish.")
            return
        self._apply_form_to_model()
        self._refresh_optimization_assumptions()
        candidates = self._project_candidates()
        category_counts = [
            sum(
                effective_candidate_product(row)["category"] == category
                and row.get("disposition", "Candidate") != "Excluded"
                for row in candidates
            ) for category in EQUIPMENT_CATEGORIES
        ]
        combination_count = math.prod(category_counts)
        self.execution_log.info(
            "Optimization", f"System optimization started for up to {combination_count} combinations"
        )
        self.execution_log.diagnostic(
            "Optimization", "Optimization catalog prepared", details=f"category_counts={category_counts}"
        )
        self.optimization_status_var.set(f"Preparing up to {combination_count} eligible product combinations...")
        self.analysis_progress_var.set(0.0)
        self.status_var.set("Optimization running: evaluating product combinations")
        self.config(cursor="watch")
        self.analysis_running = True
        self.analysis_cancel_requested = False
        self.analysis_active_label = "System optimization"
        self.cancel_analysis_button.configure(text="Cancel optimization")
        self.cancel_analysis_button.state(["!disabled"])
        config_snapshot = copy.deepcopy(self.config_model)
        rainfall_snapshot = self.rainfall_df.copy(deep=True)

        def worker() -> None:
            cache_hits = 0

            def record_cache_event(hit: bool) -> None:
                nonlocal cache_hits
                cache_hits += int(hit)

            try:
                self.execution_log.debug("Optimization", "Optimization worker started")
                results = optimize_indirect_system(
                    config_snapshot,
                    rainfall_snapshot,
                    progress_callback=lambda current, total: self.optimization_result_queue.put(
                        ("progress", current, total, cache_hits)
                    ),
                    cancel_callback=lambda: self.analysis_cancel_requested,
                    cache_callback=record_cache_event,
                )
                self.optimization_result_queue.put(
                    ("result", results, config_snapshot, cache_hits)
                )
            except AnalysisCancelledError:
                self.optimization_result_queue.put(("cancelled",))
            except Exception as exc:
                self.execution_log.error("Optimization", "Optimization worker failed", exception=exc)
                self.optimization_result_queue.put(("error", str(exc)))

        self.analysis_thread = threading.Thread(
            target=worker, daemon=True, name="optimization-worker"
        )
        self.analysis_thread.start()
        self.optimization_poll_after_id = self.after(50, self._poll_optimization_results)

    def _poll_optimization_results(self) -> None:
        terminal_message = False
        while True:
            try:
                message = self.optimization_result_queue.get_nowait()
            except queue.Empty:
                break
            kind = message[0]
            if kind == "progress":
                _kind, current, total, cache_hits = message
                reused = f"; {cache_hits} reused from cache" if cache_hits else ""
                self.optimization_status_var.set(
                    f"Evaluating combination {current} of {total}{reused}..."
                )
                self.analysis_progress_var.set(current / max(total, 1) * 100.0)
                self.status_var.set(
                    f"Optimization running: combination {current} of {total}{reused}"
                )
                self.execution_log.debug(
                    "Optimization", f"Evaluating combination {current} of {total}"
                )
            elif kind == "result":
                _kind, results, config_snapshot, cache_hits = message
                self._display_optimization_results(
                    results, config_snapshot, cache_hits=cache_hits
                )
                terminal_message = True
            elif kind == "cancelled":
                self.analysis_progress_var.set(0.0)
                self.status_var.set(
                    "System optimization cancelled; previous completed results retained"
                )
                self.optimization_status_var.set(
                    "Optimization cancelled; previous completed results were retained."
                )
                self.execution_log.warning("Optimization", "System optimization cancelled")
                terminal_message = True
            else:
                _kind, error_message = message
                self.analysis_progress_var.set(0.0)
                self.status_var.set("Optimization failed")
                self.optimization_status_var.set(error_message)
                self.execution_log.error("Optimization", f"Optimization failed: {error_message}")
                messagebox.showwarning(APP_TITLE, error_message, parent=self)
                terminal_message = True
        if terminal_message:
            self._finish_analysis_run()
            self.cancel_analysis_button.configure(text="Cancel analysis")
            self.config(cursor="")
            self.optimization_poll_after_id = None
        elif self.analysis_running:
            self.optimization_poll_after_id = self.after(50, self._poll_optimization_results)

    def _display_optimization_results(
        self,
        results: list[object],
        run_config: ProjectConfig,
        *,
        cache_hits: int = 0,
    ) -> None:
        self.optimization_tree.delete(*self.optimization_tree.get_children())
        currency = run_config.financial_parameters.currency
        feasible_count = sum(result.feasible for result in results)
        for index, result in enumerate(results):
            payback = (
                f"{format_number(result.simple_payback_years, run_config, max_decimal_places=1)} years"
                if result.simple_payback_years is not None else "Not achieved"
            )
            self.optimization_tree.insert(
                "", "end", iid=str(index),
                values=(
                    result.rank if result.rank is not None else "Infeasible",
                    result.primary_tank.name,
                    result.filtration_pump.name,
                    result.filtration_unit.name,
                    result.booster_tank.name,
                    f"{format_number(result.reliability_percent, run_config, max_decimal_places=1)}%",
                    format_number(volume_to_display(result.average_annual_municipal_makeup_gallons, run_config), run_config, max_decimal_places=0),
                    f"{format_number(result.average_annual_energy_kwh, run_config, max_decimal_places=0)} kWh",
                    f"{currency} {format_number(result.total_installed_cost, run_config, max_decimal_places=0)}",
                    f"{currency} {format_number(result.net_annual_savings, run_config, max_decimal_places=0)}",
                    payback,
                    f"{currency} {format_number(result.lifecycle_net_present_value, run_config, max_decimal_places=0)}",
                ),
            )
        if feasible_count:
            best = next(result for result in results if result.feasible)
            objective = run_config.optimization_parameters.objective
            if objective == "Simple payback":
                best_value = f"{format_number(best.simple_payback_years, run_config, max_decimal_places=1)} years" if best.simple_payback_years is not None else "not achieved"
            elif objective == "Net annual savings":
                best_value = f"{currency} {format_number(best.net_annual_savings, run_config, max_decimal_places=0)}/year"
            elif objective == "Rainwater reliability":
                best_value = f"{format_number(best.reliability_percent, run_config, max_decimal_places=1)}%"
            elif objective == "Lifecycle NPV":
                best_value = f"{currency} {format_number(best.lifecycle_net_present_value, run_config, max_decimal_places=0)}"
            else:
                best_value = f"{currency} {format_number(best.analysis_period_net_benefit, run_config, max_decimal_places=0)}"
            self.optimization_status_var.set(
                f"{feasible_count} of {len(results)} combinations meet all constraints. "
                f"Best: {best.primary_tank.name} + {best.filtration_pump.name} + "
                f"{best.filtration_unit.name} + {best.booster_tank.name}; {objective.lower()} {best_value}. "
                f"Reused {cache_hits} cached candidate result(s)."
            )
        else:
            self.optimization_status_var.set(
                f"None of the {len(results)} combinations meet the reliability target. "
                f"Reused {cache_hits} cached candidate result(s)."
            )
        self.analysis_progress_var.set(100.0)
        self.status_var.set("Optimization complete")
        self.execution_log.info(
            "Optimization",
            f"Optimization completed with {len(results)} evaluated combinations, "
            f"{feasible_count} feasible results, and {cache_hits} cache hits",
        )

    def _build_financial_tab(self) -> None:
        self.financial_tab.columnconfigure(0, weight=1)
        self.financial_tab.rowconfigure(0, weight=1)
        financial_canvas = tk.Canvas(self.financial_tab, highlightthickness=0)
        financial_scrollbar = ttk.Scrollbar(
            self.financial_tab, orient="vertical", command=financial_canvas.yview
        )
        financial_canvas.configure(yscrollcommand=financial_scrollbar.set)
        financial_canvas.grid(row=0, column=0, sticky="nsew")
        financial_scrollbar.grid(row=0, column=1, sticky="ns")
        content = ttk.Frame(financial_canvas)
        content_window = financial_canvas.create_window(
            (0, 0), window=content, anchor="nw"
        )
        content.columnconfigure(0, weight=1)
        content.columnconfigure(1, weight=1)
        content.rowconfigure(1, weight=1)
        content.rowconfigure(2, weight=1)
        content.bind(
            "<Configure>",
            lambda _event: financial_canvas.configure(
                scrollregion=financial_canvas.bbox("all")
            ),
        )
        financial_canvas.bind(
            "<Configure>",
            lambda event: financial_canvas.itemconfigure(
                content_window, width=event.width
            ),
        )
        ttk.Label(
            content,
            text=(
                "Lifecycle cash flow values rainwater delivered to demand by the latest simulation. "
                "It includes escalation, pump electricity, recurring equipment replacement, discounting, NPV, "
                "and IRR. Tariff tiers are excluded because billing-period tier rules are not configured."
            ),
            foreground="#667278",
            wraplength=950,
        ).grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 10))

        inputs = ttk.LabelFrame(content, text="Financial assumptions", padding=12)
        inputs.grid(row=1, column=0, sticky="nsew", padx=(0, 6))
        inputs.columnconfigure(1, weight=1)
        ttk.Label(inputs, text="Currency").grid(row=0, column=0, sticky="w", pady=3)
        ttk.Combobox(
            inputs,
            textvariable=self.financial_currency_var,
            values=("USD", "CAD", "EUR", "GBP", "AUD", "Other"),
            state="readonly",
            width=14,
        ).grid(row=0, column=1, sticky="ew", pady=3)
        ttk.Label(inputs, text="Tariff billing unit").grid(row=1, column=0, sticky="w", pady=3)
        ttk.Combobox(
            inputs,
            textvariable=self.financial_tariff_unit_var,
            values=("per 1,000 gal", "per m³"),
            state="readonly",
            width=14,
        ).grid(row=1, column=1, sticky="ew", pady=3)
        self._labeled_entry(inputs, 2, "Water rate", self.financial_water_rate_var, self.financial_tariff_unit_var)
        self._labeled_entry(inputs, 3, "Sewer rate", self.financial_sewer_rate_var, self.financial_tariff_unit_var)
        self._labeled_entry(
            inputs, 4, "Legacy aggregate demand eligible for sewer savings",
            self.financial_sewer_eligible_var, self.percent_unit_var,
        )
        self._labeled_entry(inputs, 5, "Installed system cost", self.financial_installed_cost_var, self.financial_currency_var)
        self._labeled_entry(inputs, 6, "Incentives or rebates", self.financial_incentives_var, self.financial_currency_var)
        self._labeled_entry(inputs, 7, "Fixed annual maintenance", self.financial_fixed_maintenance_var, self.financial_currency_var)
        self._labeled_entry(inputs, 8, "Annual maintenance", self.financial_maintenance_percent_var, self.percent_unit_var)
        ttk.Label(inputs, text="Analysis period").grid(row=9, column=0, sticky="w", pady=3)
        ttk.Spinbox(
            inputs, from_=1, to=100, increment=1,
            textvariable=self.financial_analysis_period_var, width=10,
        ).grid(row=9, column=1, sticky="w", pady=3)
        ttk.Label(inputs, text="years").grid(row=9, column=2, sticky="w", padx=(6, 0), pady=3)
        self._labeled_entry(inputs, 10, "Discount rate", self.financial_discount_rate_var, self.percent_unit_var)
        self._labeled_entry(inputs, 11, "Utility-rate escalation", self.financial_utility_escalation_var, self.percent_unit_var)
        self._labeled_entry(inputs, 12, "Electricity price", self.optimization_electricity_rate_var, self.financial_electricity_unit_var)
        self._labeled_entry(inputs, 13, "Electricity-price escalation", self.financial_electricity_escalation_var, self.percent_unit_var)
        self._labeled_entry(inputs, 14, "Maintenance-cost escalation", self.financial_maintenance_escalation_var, self.percent_unit_var)
        self._labeled_entry(inputs, 15, "Pump rated power", self.financial_pump_power_var, self.financial_power_unit_var)
        self._labeled_entry(inputs, 16, "Pump rated flow", self.financial_pump_flow_rate_var, self.financial_pump_flow_unit_var)
        self._labeled_entry(inputs, 17, "Recurring equipment replacement", self.financial_replacement_cost_var, self.financial_currency_var)
        self._labeled_entry(inputs, 18, "Replacement interval", self.financial_replacement_interval_var, self.financial_replacement_interval_unit_var)
        self._labeled_entry(inputs, 19, "Replacement-cost escalation", self.financial_replacement_escalation_var, self.percent_unit_var)
        ttk.Button(inputs, text="Update financial analysis", command=self.update_financial_analysis).grid(
            row=20, column=0, columnspan=3, sticky="ew", pady=(12, 0)
        )

        outputs = ttk.LabelFrame(content, text="Selected-tank financial results", padding=12)
        outputs.grid(row=1, column=1, sticky="nsew", padx=(6, 0))
        outputs.columnconfigure(1, weight=1)
        result_rows = (
            ("Average annual rainwater supplied", "supplied"),
            ("Annual sewer-eligible rainwater supplied", "sewer_eligible_supply"),
            ("Annual municipal water savings", "water_savings"),
            ("Annual sewer savings", "sewer_savings"),
            ("Gross annual utility savings", "gross"),
            ("Annual maintenance cost", "maintenance"),
            ("Annual pump electricity", "energy"),
            ("Net annual savings", "net"),
            ("Net installed cost after incentives", "net_cost"),
            ("Simple payback", "payback"),
            ("Discounted payback", "discounted_payback"),
            ("Net benefit over analysis period", "period_benefit"),
            ("Nominal replacement costs", "replacement"),
            ("Lifecycle net present value", "npv"),
            ("Internal rate of return", "irr"),
        )
        for row, (label, key) in enumerate(result_rows):
            ttk.Label(outputs, text=label).grid(row=row, column=0, sticky="w", pady=5)
            ttk.Label(
                outputs,
                textvariable=self.financial_result_vars[key],
                font=("Segoe UI", 10, "bold"),
                anchor="e",
            ).grid(row=row, column=1, sticky="e", padx=(12, 0), pady=5)
        ttk.Separator(outputs).grid(row=len(result_rows), column=0, columnspan=2, sticky="ew", pady=8)
        ttk.Label(
            outputs,
            textvariable=self.financial_status_var,
            foreground="#667278",
            wraplength=400,
        ).grid(row=len(result_rows) + 1, column=0, columnspan=2, sticky="ew")

        comparison = ttk.LabelFrame(
            content, text="Primary and comparison tank financial performance", padding=10
        )
        comparison.grid(row=2, column=0, columnspan=2, sticky="nsew", pady=(10, 0))
        comparison.columnconfigure(0, weight=1)
        comparison.rowconfigure(0, weight=1)
        columns = ("tank", "supplied", "gross", "net", "payback", "npv")
        self.financial_comparison_tree = ttk.Treeview(
            comparison, columns=columns, show="headings", height=6
        )
        headings = {
            "tank": "Tank size",
            "supplied": "Annual rainwater supplied",
            "gross": "Gross annual savings",
            "net": "Net annual savings",
            "payback": "Simple payback",
            "npv": "Lifecycle NPV",
        }
        for column, heading in headings.items():
            self.financial_comparison_tree.heading(column, text=heading)
            self.financial_comparison_tree.column(column, width=165, anchor="e")
        self.financial_comparison_tree.grid(row=0, column=0, sticky="nsew")
        financial_scroll = ttk.Scrollbar(
            comparison, orient="vertical", command=self.financial_comparison_tree.yview
        )
        financial_scroll.grid(row=0, column=1, sticky="ns")
        self.financial_comparison_tree.configure(yscrollcommand=financial_scroll.set)

    def _financial_results_source(self) -> pd.DataFrame:
        if not self.hourly_results_df.empty:
            return self.hourly_results_df
        return self.results_df

    def update_financial_analysis(self, *, show_errors: bool = True) -> None:
        self._apply_financial_form_to_model()
        source = self._financial_results_source()
        if source.empty:
            self.financial_status_var.set("Run a tank analysis to calculate financial results.")
            for variable in self.financial_result_vars.values():
                variable.set("--")
            self.financial_comparison_tree.delete(*self.financial_comparison_tree.get_children())
            self._populate_candidate_performance()
            return
        params = self.config_model.financial_parameters
        try:
            results = FinancialAnalysisService(self.config_model).calculate(source)
        except ValueError as exc:
            self.financial_status_var.set(str(exc))
            for variable in self.financial_result_vars.values():
                variable.set("--")
            self.financial_comparison_tree.delete(*self.financial_comparison_tree.get_children())
            if show_errors:
                messagebox.showwarning(APP_TITLE, str(exc), parent=self)
            self._populate_candidate_performance()
            return
        currency = params.currency
        volume_label = volume_unit(self.config_model)
        supplied_display = volume_to_display(results.average_annual_supplied_gallons, self.config_model)
        self.financial_result_vars["supplied"].set(f"{format_number(supplied_display, self.config_model, max_decimal_places=0)} {volume_label}/year")
        eligible_display = volume_to_display(
            results.average_annual_sewer_eligible_supplied_gallons, self.config_model
        )
        self.financial_result_vars["sewer_eligible_supply"].set(
            f"{format_number(eligible_display, self.config_model, max_decimal_places=0)} {volume_label}/year"
        )
        self.financial_result_vars["water_savings"].set(
            f"{currency} {format_number(results.annual_municipal_water_savings, self.config_model)}/year"
        )
        self.financial_result_vars["sewer_savings"].set(
            f"{currency} {format_number(results.annual_sewer_savings, self.config_model)}/year"
        )
        self.financial_result_vars["gross"].set(f"{currency} {format_number(results.gross_annual_savings, self.config_model)}/year")
        self.financial_result_vars["maintenance"].set(f"{currency} {format_number(results.annual_maintenance_cost, self.config_model)}/year")
        self.financial_result_vars["energy"].set(
            f"{format_number(results.average_annual_pump_energy_kwh, self.config_model, max_decimal_places=1)} kWh; "
            f"{currency} {format_number(results.annual_pump_energy_cost, self.config_model)}/year"
        )
        self.financial_result_vars["net"].set(f"{currency} {format_number(results.net_annual_savings, self.config_model)}/year")
        self.financial_result_vars["net_cost"].set(f"{currency} {format_number(results.net_installed_cost, self.config_model)}")
        self.financial_result_vars["payback"].set(
            f"{format_number(results.simple_payback_years, self.config_model, max_decimal_places=1)} years"
            if results.simple_payback_years is not None
            else "Not achieved"
        )
        self.financial_result_vars["discounted_payback"].set(
            f"{format_number(results.discounted_payback_years, self.config_model, max_decimal_places=1)} years"
            if results.discounted_payback_years is not None
            else "Not achieved"
        )
        self.financial_result_vars["period_benefit"].set(
            f"{currency} {format_number(results.analysis_period_net_benefit, self.config_model)}"
        )
        self.financial_result_vars["replacement"].set(
            f"{currency} {format_number(results.total_replacement_cost, self.config_model)}"
        )
        self.financial_result_vars["npv"].set(
            f"{currency} {format_number(results.lifecycle_net_present_value, self.config_model)}"
        )
        self.financial_result_vars["irr"].set(
            f"{format_number(results.internal_rate_of_return_percent, self.config_model)}%"
            if results.internal_rate_of_return_percent is not None
            else "Not uniquely defined"
        )
        source_label = "hourly" if source is self.hourly_results_df else "daily"
        self.financial_status_var.set(
            f"Based on average annual delivered rainwater from the latest {source_label} simulation. "
            "Year 0 contains net installed cost; operating cash flows occur at each year end. "
            "IRR is withheld for non-conventional cash flows with multiple sign changes."
        )
        self._populate_financial_comparison()
        self._populate_candidate_performance()

    def _populate_financial_comparison(self) -> None:
        self.financial_comparison_tree.delete(*self.financial_comparison_tree.get_children())
        params = self.config_model.financial_parameters
        candidates: list[tuple[float, pd.DataFrame]] = [
            (float(self.config_model.selected_tank_size_gal), self._financial_results_source())
        ]
        candidates.extend(sorted(self.comparison_results.items()))
        seen: set[float] = set()
        for tank_size, source in candidates:
            rounded_size = round(float(tank_size), 6)
            if rounded_size in seen or source.empty:
                continue
            seen.add(rounded_size)
            try:
                results = FinancialAnalysisService(self.config_model).calculate(source)
            except ValueError:
                continue
            tank_display = volume_to_display(tank_size, self.config_model)
            supplied_display = volume_to_display(
                results.average_annual_supplied_gallons, self.config_model
            )
            payback = (
                f"{format_number(results.simple_payback_years, self.config_model, max_decimal_places=1)} years"
                if results.simple_payback_years is not None
                else "Not achieved"
            )
            self.financial_comparison_tree.insert(
                "",
                "end",
                values=(
                    f"{format_number(tank_display, self.config_model, max_decimal_places=0)} {volume_unit(self.config_model)}",
                    f"{format_number(supplied_display, self.config_model, max_decimal_places=0)} {volume_unit(self.config_model)}/yr",
                    f"{params.currency} {format_number(results.gross_annual_savings, self.config_model)}",
                    f"{params.currency} {format_number(results.net_annual_savings, self.config_model)}",
                    payback,
                    f"{params.currency} {format_number(results.lifecycle_net_present_value, self.config_model)}",
                ),
            )

    def _build_report_generation_tab(self) -> None:
        report_tab = self.report_generation_tab
        report_tab.columnconfigure(0, weight=1)

        ttk.Label(
            report_tab,
            text="Choose which sections are included in generated HTML and PDF reports.",
            font=("Segoe UI", 12, "bold"),
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            report_tab,
            text=(
                "These choices are saved with the project. The report cover and table of "
                "contents are generated automatically."
            ),
            foreground="#667278",
        ).grid(row=1, column=0, sticky="w", pady=(2, 12))

        toolbar = ttk.Frame(report_tab)
        toolbar.grid(row=2, column=0, sticky="w", pady=(0, 10))
        ttk.Button(
            toolbar, text="Select all", command=lambda: self._set_report_sections(True)
        ).grid(row=0, column=0)
        ttk.Button(
            toolbar, text="Clear all", command=lambda: self._set_report_sections(False)
        ).grid(row=0, column=1, padx=(8, 0))
        ttk.Button(
            toolbar, text="Restore defaults", command=self._restore_default_report_sections
        ).grid(row=0, column=2, padx=(8, 0))

        sections = ttk.LabelFrame(report_tab, text="Report sections", padding=12)
        sections.grid(row=3, column=0, sticky="ew")
        sections.columnconfigure(0, weight=1)
        sections.columnconfigure(1, weight=1)
        split_at = (len(REPORT_SECTION_DEFINITIONS) + 1) // 2
        for index, (key, label, _html_id, _title) in enumerate(REPORT_SECTION_DEFINITIONS):
            column = 0 if index < split_at else 1
            row = index if column == 0 else index - split_at
            ttk.Checkbutton(
                sections,
                text=label,
                variable=self.report_section_vars[key],
                command=self._apply_report_options_to_model,
            ).grid(row=row, column=column, sticky="w", padx=(0, 30), pady=3)

        supplemental = ttk.LabelFrame(report_tab, text="Supplemental visuals", padding=12)
        supplemental.grid(row=4, column=0, sticky="ew", pady=(12, 0))
        ttk.Checkbutton(
            supplemental,
            text="Include system-type visualization",
            variable=self.report_include_system_visualization_var,
            command=self._apply_report_options_to_model,
        ).grid(row=0, column=0, sticky="w")
        ttk.Checkbutton(
            supplemental,
            text="Include multi-tank comparison charts when comparison results are available",
            variable=self.report_include_multitank_charts_var,
            command=self._apply_report_options_to_model,
        ).grid(row=1, column=0, sticky="w", pady=(6, 0))

        actions = ttk.Frame(report_tab)
        actions.grid(row=5, column=0, sticky="w", pady=(16, 0))
        ttk.Button(actions, text="View PDF report", command=self.view_pdf_report).grid(row=0, column=0)
        ttk.Button(actions, text="View HTML report", command=self.view_html_report).grid(row=0, column=1, padx=(8, 0))
        ttk.Button(actions, text="Export PDF...", command=self.export_pdf_report).grid(row=0, column=2, padx=(18, 0))
        ttk.Button(actions, text="Export HTML...", command=self.export_html_report).grid(row=0, column=3, padx=(8, 0))

    def _set_report_sections(self, selected: bool) -> None:
        for variable in self.report_section_vars.values():
            variable.set(selected)
        self._apply_report_options_to_model()

    def _restore_default_report_sections(self) -> None:
        for key, variable in self.report_section_vars.items():
            variable.set(DEFAULT_REPORT_SECTIONS[key])
        self._apply_report_options_to_model()

    def _apply_report_options_to_model(self) -> None:
        self.config_model.report_sections = {
            key: bool(variable.get()) for key, variable in self.report_section_vars.items()
        }
        self.config_model.report_include_system_visualization = bool(
            self.report_include_system_visualization_var.get()
        )
        self.config_model.report_include_multitank_charts = bool(
            self.report_include_multitank_charts_var.get()
        )

    def _build_results_tab(self) -> None:
        self.results_tab.columnconfigure(0, weight=1)
        self.results_tab.rowconfigure(0, weight=1)
        self.results_notebook = ttk.Notebook(self.results_tab)
        self.results_notebook.grid(row=0, column=0, sticky="nsew")
        self.summary_results_tab = ttk.Frame(self.results_notebook, padding=8)
        self.candidate_results_tab = ttk.Frame(self.results_notebook, padding=8)
        self.multitank_results_tab = ttk.Frame(self.results_notebook, padding=8)
        self.hourly_results_tab = ttk.Frame(self.results_notebook, padding=8)
        self.first_flush_results_tab = ttk.Frame(self.results_notebook, padding=8)
        self.report_generation_tab = ttk.Frame(self.results_notebook, padding=12)
        self.results_notebook.add(self.summary_results_tab, text="Single-tank summary")
        self.results_notebook.add(self.candidate_results_tab, text="Candidate performance")
        self.results_notebook.add(self.multitank_results_tab, text="Multitank summary")
        self.results_notebook.add(self.hourly_results_tab, text="Hourly results")
        self.results_notebook.add(self.first_flush_results_tab, text="First-flush summaries")
        self.results_notebook.add(self.report_generation_tab, text="Report generation")
        self.results_notebook.bind("<<NotebookTabChanged>>", self._on_results_subtab_changed)

        self._build_report_generation_tab()

        self.summary_results_tab.columnconfigure(0, weight=1)
        self.summary_results_tab.rowconfigure(0, weight=1)
        self.summary_scroll_canvas = tk.Canvas(
            self.summary_results_tab,
            highlightthickness=0,
            borderwidth=0,
        )
        self.summary_scroll_canvas.grid(row=0, column=0, sticky="nsew")
        summary_scrollbar = ttk.Scrollbar(
            self.summary_results_tab,
            orient="vertical",
            command=self.summary_scroll_canvas.yview,
        )
        summary_scrollbar.grid(row=0, column=1, sticky="ns")
        self.summary_scroll_canvas.configure(yscrollcommand=summary_scrollbar.set)

        summary = ttk.Frame(self.summary_scroll_canvas)
        self.summary_results_content = summary
        self.summary_scroll_window = self.summary_scroll_canvas.create_window(
            (0, 0), window=summary, anchor="nw"
        )
        self._summary_results_stacked: bool | None = None
        summary.bind(
            "<Configure>",
            lambda _event: self.summary_scroll_canvas.configure(
                scrollregion=self.summary_scroll_canvas.bbox("all")
            ),
        )
        self.summary_scroll_canvas.bind("<Configure>", self._on_summary_results_resize)
        summary.columnconfigure(0, weight=1)
        summary.columnconfigure(1, weight=1)

        results_summary = ttk.Frame(summary)
        results_summary.grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(results_summary, textvariable=self.reliability_var, font=("Segoe UI", 12, "bold")).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(results_summary, textvariable=self.average_annual_precipitation_var).grid(
            row=1, column=0, sticky="w", pady=(2, 0)
        )
        self.curve_canvas = tk.Canvas(
            summary, height=RESULTS_CHART_HEIGHT, bg="white",
            highlightthickness=1, highlightbackground="#b7b7b7"
        )
        self.curve_canvas.grid(row=1, column=0, sticky="nsew", pady=(8, 8), padx=(0, 5))
        self.tank_canvas = tk.Canvas(
            summary, height=RESULTS_CHART_HEIGHT, bg="white",
            highlightthickness=1, highlightbackground="#b7b7b7"
        )
        self.tank_canvas.grid(row=1, column=1, sticky="nsew", pady=(8, 8), padx=(5, 0))
        self.tank_points_check = ttk.Checkbutton(
            self.tank_canvas,
            text="Show tank chart points",
            variable=self.show_tank_points_var,
            command=self._draw_tank_chart,
        )
        self.tank_year_controls = ttk.Frame(self.tank_canvas)
        ttk.Radiobutton(
            self.tank_year_controls, text="Single year", variable=self.tank_chart_range_mode_var,
            value="year", command=self._draw_tank_chart,
        ).grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Radiobutton(
            self.tank_year_controls, text="Custom range", variable=self.tank_chart_range_mode_var,
            value="range", command=self._draw_tank_chart,
        ).grid(row=0, column=2, columnspan=2, sticky="w")
        self.previous_tank_year_button = ttk.Button(
            self.tank_year_controls, text="<", width=3, command=lambda: self._change_tank_chart_year(-1)
        )
        self.previous_tank_year_button.grid(row=1, column=0)
        ttk.Label(self.tank_year_controls, text="Year").grid(row=1, column=1, padx=(4, 2))
        self.tank_chart_year_entry = ttk.Entry(
            self.tank_year_controls, textvariable=self.tank_chart_year_var, width=6, justify="center"
        )
        self.tank_chart_year_entry.grid(row=1, column=2, padx=(0, 4))
        self.tank_chart_year_entry.bind("<Return>", self._set_tank_chart_year_from_entry)
        self.next_tank_year_button = ttk.Button(
            self.tank_year_controls, text=">", width=3, command=lambda: self._change_tank_chart_year(1)
        )
        self.next_tank_year_button.grid(row=1, column=3)
        self.tank_range_controls = ttk.Frame(self.tank_canvas)
        ttk.Label(self.tank_range_controls, textvariable=self.tank_chart_range_label_var).grid(
            row=0, column=0, columnspan=2, sticky="w"
        )
        self.tank_range_start_scale = ttk.Scale(
            self.tank_range_controls, from_=0, to=0, variable=self.tank_chart_range_start_var,
            command=lambda _value: self._tank_range_slider_changed("start"), length=115,
        )
        self.tank_range_start_scale.grid(row=1, column=0)
        self.tank_range_end_scale = ttk.Scale(
            self.tank_range_controls, from_=0, to=0, variable=self.tank_chart_range_end_var,
            command=lambda _value: self._tank_range_slider_changed("end"), length=115,
        )
        self.tank_range_end_scale.grid(row=1, column=1, padx=(4, 0))
        self.histogram_canvas = tk.Canvas(
            summary,
            height=RESULTS_CHART_HEIGHT,
            bg="white",
            highlightthickness=1,
            highlightbackground="#b7b7b7",
        )
        self.histogram_canvas.grid(row=2, column=0, sticky="nsew", pady=(0, 8), padx=(0, 5))
        self.yearly_reliability_canvas = tk.Canvas(
            summary,
            height=RESULTS_CHART_HEIGHT,
            bg="white",
            highlightthickness=1,
            highlightbackground="#b7b7b7",
        )
        self.yearly_reliability_canvas.grid(row=2, column=1, sticky="nsew", pady=(0, 8), padx=(5, 0))
        self.curve_canvas.bind("<Configure>", self._schedule_results_chart_redraw)
        self.tank_canvas.bind("<Configure>", self._schedule_results_chart_redraw)
        self.histogram_canvas.bind("<Configure>", self._schedule_results_chart_redraw)
        self.yearly_reliability_canvas.bind("<Configure>", self._schedule_results_chart_redraw)

        columns = (
            "date", "precip", "gross", "first_flush", "collected", "overflow",
            "demand", "unmet", "tank",
        )
        self.results_tree = ttk.Treeview(summary, columns=columns, show="headings", height=7)
        headings = {
            "date": "Date",
            "precip": "Precip.",
            "gross": "Gross runoff",
            "first_flush": "First-flush loss",
            "collected": "Collected",
            "overflow": "Overflow",
            "demand": "Demand",
            "unmet": "Unmet",
            "tank": "Water in Tank",
        }
        for col, heading in headings.items():
            self.results_tree.heading(col, text=heading)
            self.results_tree.column(col, width=120, anchor="e" if col != "date" else "w")
        self.results_tree.grid(row=3, column=0, columnspan=2, sticky="nsew")
        self.results_scroll_y = ttk.Scrollbar(
            summary, orient="vertical", command=self.results_tree.yview
        )
        self.results_scroll_y.grid(row=3, column=2, sticky="ns")
        self.results_scroll_x = ttk.Scrollbar(
            summary, orient="horizontal", command=self.results_tree.xview
        )
        self.results_scroll_x.grid(row=4, column=0, columnspan=2, sticky="ew")
        self.results_tree.configure(
            yscrollcommand=self.results_scroll_y.set,
            xscrollcommand=self.results_scroll_x.set,
        )

        candidate = self.candidate_results_tab
        candidate.columnconfigure(0, weight=1)
        candidate.rowconfigure(2, weight=1)
        candidate_toolbar = ttk.Frame(candidate)
        candidate_toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ttk.Label(
            candidate_toolbar,
            text="Each row aggregates the same daily mass-balance simulation used by the reliability curve.",
            foreground="#667278",
        ).pack(side="left")
        ttk.Button(
            candidate_toolbar, text="Use selected as primary", command=self.use_candidate_as_primary
        ).pack(side="right")
        ttk.Button(
            candidate_toolbar, text="Export CSV...", command=self.export_candidate_performance
        ).pack(side="right", padx=(0, 8))
        recommendation_frame = ttk.LabelFrame(
            candidate, text="Design recommendations", padding=(10, 8)
        )
        recommendation_frame.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        recommendation_frame.columnconfigure(7, weight=1)
        ttk.Label(recommendation_frame, text="Reliability target").grid(
            row=0, column=0, sticky="w"
        )
        target_entry = ttk.Entry(
            recommendation_frame,
            textvariable=self.recommendation_reliability_target_var,
            width=7,
        )
        target_entry.grid(row=0, column=1, padx=(5, 2))
        ttk.Label(recommendation_frame, text="%").grid(row=0, column=2, sticky="w")
        ttk.Label(recommendation_frame, text="Diminishing-return threshold").grid(
            row=0, column=3, sticky="w", padx=(18, 0)
        )
        gain_entry = ttk.Entry(
            recommendation_frame,
            textvariable=self.recommendation_marginal_gain_var,
            width=7,
        )
        gain_entry.grid(row=0, column=4, padx=(5, 2))
        ttk.Label(recommendation_frame, text="reliability points / 1,000 gal").grid(
            row=0, column=5, sticky="w"
        )
        ttk.Button(
            recommendation_frame,
            text="Refresh",
            command=self._refresh_design_recommendations,
        ).grid(row=0, column=6, padx=(18, 0))
        ttk.Label(
            recommendation_frame,
            textvariable=self.design_recommendations_var,
            justify="left",
            wraplength=1080,
        ).grid(row=1, column=0, columnspan=8, sticky="ew", pady=(8, 0))
        ttk.Label(
            recommendation_frame,
            textvariable=self.design_warnings_var,
            foreground="#a33a00",
            justify="left",
            wraplength=1080,
        ).grid(row=2, column=0, columnspan=8, sticky="ew", pady=(4, 0))
        for entry in (target_entry, gain_entry):
            entry.bind("<Return>", lambda _event: self._refresh_design_recommendations())
            entry.bind("<FocusOut>", lambda _event: self._refresh_design_recommendations())
        candidate_columns = (
            "TankSizeGallons", "ReliabilityPercent", "TotalDemandGallons",
            "RainwaterSuppliedGallons", "SewerEligibleRainwaterSuppliedGallons",
            "UnmetDemandGallons", "MunicipalMakeupGallons",
            "SystemUnmetDemandGallons", "OverflowGallons", "FirstFlushLossGallons",
            "TreatmentLossGallons", "FinalStorageGallons", "NetAnnualSavings",
            "SimplePaybackYears", "LifecycleNPV",
        )
        self.candidate_performance_tree = ttk.Treeview(
            candidate, columns=candidate_columns, show="headings", height=18, selectmode="browse"
        )
        candidate_headings = {
            "TankSizeGallons": "Tank size", "ReliabilityPercent": "Reliability",
            "TotalDemandGallons": "Total demand", "RainwaterSuppliedGallons": "Rainwater supplied",
            "SewerEligibleRainwaterSuppliedGallons": "Sewer-eligible supply",
            "UnmetDemandGallons": "Rainwater shortfall", "MunicipalMakeupGallons": "Municipal makeup",
            "SystemUnmetDemandGallons": "System unmet", "OverflowGallons": "Overflow",
            "FirstFlushLossGallons": "First-flush loss", "TreatmentLossGallons": "Treatment loss",
            "FinalStorageGallons": "Final storage", "NetAnnualSavings": "Net savings/year",
            "SimplePaybackYears": "Simple payback", "LifecycleNPV": "Lifecycle NPV",
        }
        for column in candidate_columns:
            self.candidate_performance_tree.heading(
                column,
                text=candidate_headings[column],
                command=lambda selected=column: self._sort_candidate_performance(selected),
            )
            self.candidate_performance_tree.column(column, width=130, anchor="e", stretch=False)
        self.candidate_performance_tree.grid(row=2, column=0, sticky="nsew")
        candidate_scroll_y = ttk.Scrollbar(
            candidate, orient="vertical", command=self.candidate_performance_tree.yview
        )
        candidate_scroll_y.grid(row=2, column=1, sticky="ns")
        candidate_scroll_x = ttk.Scrollbar(
            candidate, orient="horizontal", command=self.candidate_performance_tree.xview
        )
        candidate_scroll_x.grid(row=3, column=0, sticky="ew")
        self.candidate_performance_tree.configure(
            yscrollcommand=candidate_scroll_y.set, xscrollcommand=candidate_scroll_x.set
        )
        self.candidate_performance_tree.bind("<Double-1>", self._use_candidate_as_primary_from_event)

        multitank = self._create_results_scroll_content(self.multitank_results_tab)
        multitank.columnconfigure(0, weight=1)
        self.multitank_tank_canvas = tk.Canvas(
            multitank, height=RESULTS_MULTITANK_CHART_HEIGHT, bg="white",
            highlightthickness=1, highlightbackground="#b7b7b7",
        )
        self.multitank_distribution_canvas = tk.Canvas(
            multitank, height=RESULTS_MULTITANK_CHART_HEIGHT, bg="white",
            highlightthickness=1, highlightbackground="#b7b7b7",
        )
        self.multitank_yearly_canvas = tk.Canvas(
            multitank, height=RESULTS_MULTITANK_CHART_HEIGHT, bg="white",
            highlightthickness=1, highlightbackground="#b7b7b7",
        )
        self.multitank_tank_canvas.grid(row=0, column=0, sticky="nsew", pady=(0, 5))
        self.multitank_distribution_canvas.grid(row=1, column=0, sticky="nsew", pady=5)
        self.multitank_yearly_canvas.grid(row=2, column=0, sticky="nsew", pady=(5, 0))
        for canvas in (self.multitank_tank_canvas, self.multitank_distribution_canvas, self.multitank_yearly_canvas):
            canvas.bind("<Configure>", self._schedule_results_chart_redraw)

        hourly = self._create_results_scroll_content(self.hourly_results_tab)
        hourly.columnconfigure(0, weight=1)
        hourly_controls = ttk.Frame(hourly)
        hourly_controls.grid(row=0, column=0, sticky="w", pady=(0, 6))
        ttk.Label(hourly_controls, text="Year").grid(row=0, column=0, padx=(0, 4))
        self.hourly_results_year_combo = ttk.Combobox(
            hourly_controls, textvariable=self.hourly_results_year_var, state="readonly", width=8
        )
        self.hourly_results_year_combo.grid(row=0, column=1)
        self.hourly_results_year_combo.bind("<<ComboboxSelected>>", lambda _event: self._refresh_hourly_results_view())
        self.hourly_tank_canvas = tk.Canvas(
            hourly, height=RESULTS_HOURLY_CHART_HEIGHT, bg="white",
            highlightthickness=1, highlightbackground="#b7b7b7",
        )
        self.hourly_tank_canvas.grid(row=1, column=0, sticky="nsew", pady=(0, 8))
        self.hourly_tank_canvas.bind("<Configure>", self._schedule_results_chart_redraw)
        hourly_columns = (
            "datetime", "gross", "first_flush", "collected", "demand", "pump", "filter", "filter_loss", "booster",
            "mains", "shortfall", "system_unmet", "overflow", "tank"
        )
        self.hourly_results_tree = ttk.Treeview(hourly, columns=hourly_columns, show="headings", height=12)
        for column, label in {
            "datetime": "Date and hour", "gross": "Gross runoff", "first_flush": "First-flush loss",
            "collected": "Collected", "demand": "Demand",
            "pump": "Pump flow", "filter": "Filter throughput", "filter_loss": "Filter loss",
            "booster": "Buffer tank", "mains": "Mains makeup", "shortfall": "Rainwater shortfall",
            "system_unmet": "System unmet", "overflow": "Overflow", "tank": "Primary tank",
        }.items():
            self.hourly_results_tree.heading(column, text=label)
            self.hourly_results_tree.column(column, width=145, anchor="w" if column == "datetime" else "e")
        self.hourly_results_tree.grid(row=2, column=0, sticky="nsew")
        hourly_scroll = ttk.Scrollbar(hourly, orient="vertical", command=self.hourly_results_tree.yview)
        hourly_scroll.grid(row=2, column=1, sticky="ns")
        hourly_scroll_x = ttk.Scrollbar(hourly, orient="horizontal", command=self.hourly_results_tree.xview)
        hourly_scroll_x.grid(row=3, column=0, sticky="ew")
        self.hourly_results_tree.configure(yscrollcommand=hourly_scroll.set, xscrollcommand=hourly_scroll_x.set)

        first_flush = self._create_results_scroll_content(self.first_flush_results_tab)
        first_flush.columnconfigure(0, weight=1)
        ttk.Label(
            first_flush,
            text=(
                "Event totals follow the saved rainfall event identifiers. Yearly totals include "
                "all simulated first-flush diversion, including legacy results without event IDs."
            ),
            foreground="#667278",
            wraplength=1050,
            justify="left",
        ).grid(row=0, column=0, sticky="ew", pady=(0, 8))

        yearly_frame = ttk.LabelFrame(first_flush, text="Yearly first-flush summary", padding=8)
        yearly_frame.grid(row=1, column=0, sticky="nsew", pady=(0, 10))
        yearly_frame.columnconfigure(0, weight=1)
        yearly_columns = ("year", "events", "gross", "diverted", "collected", "percent")
        self.first_flush_yearly_tree = ttk.Treeview(
            yearly_frame, columns=yearly_columns, show="headings", height=7
        )
        for column, label in {
            "year": "Year",
            "events": "Events started",
            "gross": "Gross runoff",
            "diverted": "First-flush diversion",
            "collected": "Net collected",
            "percent": "Diverted",
        }.items():
            self.first_flush_yearly_tree.heading(column, text=label)
            self.first_flush_yearly_tree.column(column, width=150, anchor="e", stretch=False)
        self.first_flush_yearly_tree.grid(row=0, column=0, sticky="nsew")
        yearly_scroll = ttk.Scrollbar(
            yearly_frame, orient="vertical", command=self.first_flush_yearly_tree.yview
        )
        yearly_scroll.grid(row=0, column=1, sticky="ns")
        self.first_flush_yearly_tree.configure(yscrollcommand=yearly_scroll.set)

        event_frame = ttk.LabelFrame(first_flush, text="Rainfall-event first-flush summary", padding=8)
        event_frame.grid(row=2, column=0, sticky="nsew")
        event_frame.columnconfigure(0, weight=1)
        event_columns = (
            "event", "start", "end", "timesteps", "gross", "diverted", "collected", "percent"
        )
        self.first_flush_event_tree = ttk.Treeview(
            event_frame, columns=event_columns, show="headings", height=12
        )
        for column, label in {
            "event": "Event",
            "start": "Start",
            "end": "End",
            "timesteps": "Wet timesteps",
            "gross": "Gross runoff",
            "diverted": "First-flush diversion",
            "collected": "Net collected",
            "percent": "Diverted",
        }.items():
            self.first_flush_event_tree.heading(column, text=label)
            self.first_flush_event_tree.column(
                column,
                width=155,
                anchor="w" if column in {"event", "start", "end"} else "e",
                stretch=False,
            )
        self.first_flush_event_tree.grid(row=0, column=0, sticky="nsew")
        event_scroll_y = ttk.Scrollbar(
            event_frame, orient="vertical", command=self.first_flush_event_tree.yview
        )
        event_scroll_y.grid(row=0, column=1, sticky="ns")
        event_scroll_x = ttk.Scrollbar(
            event_frame, orient="horizontal", command=self.first_flush_event_tree.xview
        )
        event_scroll_x.grid(row=1, column=0, sticky="ew")
        self.first_flush_event_tree.configure(
            yscrollcommand=event_scroll_y.set, xscrollcommand=event_scroll_x.set
        )

    @staticmethod
    def _create_results_scroll_content(parent: ttk.Frame) -> ttk.Frame:
        """Create full-width, vertically scrollable content for a results subtab."""
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)
        viewport = tk.Canvas(parent, highlightthickness=0, borderwidth=0)
        viewport.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=viewport.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        viewport.configure(yscrollcommand=scrollbar.set)

        content = ttk.Frame(viewport)
        content_window = viewport.create_window((0, 0), window=content, anchor="nw")
        content.bind(
            "<Configure>",
            lambda _event: viewport.configure(scrollregion=viewport.bbox("all")),
        )
        viewport.bind(
            "<Configure>",
            lambda event: viewport.itemconfigure(
                content_window, width=max(int(event.width), 1)
            ),
        )
        return content

    def _on_summary_results_resize(self, event: tk.Event) -> None:
        """Keep summary content full-width and stack plot pairs when space is tight."""
        width = max(int(event.width), 1)
        self.summary_scroll_canvas.itemconfigure(self.summary_scroll_window, width=width)
        stacked = width < RESULTS_PLOT_STACK_BREAKPOINT
        if self._summary_results_stacked == stacked:
            return
        self._summary_results_stacked = stacked

        for widget in (
            self.curve_canvas,
            self.tank_canvas,
            self.histogram_canvas,
            self.yearly_reliability_canvas,
            self.results_tree,
            self.results_scroll_y,
            self.results_scroll_x,
        ):
            widget.grid_forget()

        if stacked:
            plot_layout = (
                (self.curve_canvas, 1, (8, 8)),
                (self.tank_canvas, 2, (0, 8)),
                (self.histogram_canvas, 3, (0, 8)),
                (self.yearly_reliability_canvas, 4, (0, 8)),
            )
            for canvas, row, pady in plot_layout:
                canvas.grid(
                    row=row, column=0, columnspan=2, sticky="ew", pady=pady
                )
            results_row = 5
        else:
            self.curve_canvas.grid(
                row=1, column=0, sticky="ew", pady=(8, 8), padx=(0, 5)
            )
            self.tank_canvas.grid(
                row=1, column=1, sticky="ew", pady=(8, 8), padx=(5, 0)
            )
            self.histogram_canvas.grid(
                row=2, column=0, sticky="ew", pady=(0, 8), padx=(0, 5)
            )
            self.yearly_reliability_canvas.grid(
                row=2, column=1, sticky="ew", pady=(0, 8), padx=(5, 0)
            )
            results_row = 3

        self.results_tree.grid(
            row=results_row, column=0, columnspan=2, sticky="ew"
        )
        self.results_scroll_y.grid(row=results_row, column=2, sticky="ns")
        self.results_scroll_x.grid(
            row=results_row + 1, column=0, columnspan=2, sticky="ew"
        )
        self.after_idle(
            lambda: self.summary_scroll_canvas.configure(
                scrollregion=self.summary_scroll_canvas.bbox("all")
            )
        )

    def _set_tank_chart_controls_visible(self, visible: bool) -> None:
        if visible:
            self.tank_points_check.place(x=58, rely=1, y=-4, anchor="sw")
            self.tank_year_controls.place(
                relx=1, rely=1, x=-8, y=-4, anchor="se"
            )
            self.tank_range_controls.place(x=58, rely=1, y=-30, anchor="sw")
            return
        self.tank_points_check.place_forget()
        self.tank_year_controls.place_forget()
        self.tank_range_controls.place_forget()

    def _labeled_entry(self, parent: ttk.Frame, row: int, label: str, variable: tk.StringVar, unit_var: tk.StringVar | None = None) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=2)
        ttk.Entry(parent, textvariable=variable, width=18).grid(row=row, column=1, sticky="ew", pady=2)
        if unit_var is not None:
            ttk.Label(parent, textvariable=unit_var).grid(row=row, column=2, sticky="w", padx=(8, 0), pady=2)

    def _update_selected_tank_warning(self, *_args: object) -> None:
        value = self.selected_tank_var.get().strip()
        try:
            show_warning = bool(value) and float(value) <= 0
        except ValueError:
            show_warning = False
        self.selected_tank_warning_var.set("!" if show_warning else "")
        if hasattr(self, "indirect_system_canvas"):
            self._draw_indirect_system_diagram()
        if hasattr(self, "comparison_tree"):
            self._populate_comparison_tanks()

    def add_comparison_tank(self) -> None:
        if not self.multitank_comparison_var.get():
            return
        display_value = _float(self.comparison_tank_var.get(), -1.0)
        tank_size = volume_to_internal(display_value, self.config_model)
        if tank_size <= 0:
            messagebox.showwarning(APP_TITLE, "Comparison tank size must be greater than zero.")
            return
        if not any(abs(existing - tank_size) < 0.01 for existing in self.config_model.comparison_tank_sizes_gal):
            self.config_model.comparison_tank_sizes_gal.append(tank_size)
            self.config_model.comparison_tank_sizes_gal.sort()
        self.comparison_tank_var.set("")
        self._populate_comparison_tanks()

    def _add_comparison_tank_from_entry(self, _event: tk.Event) -> str:
        self.add_comparison_tank()
        return "break"

    def remove_comparison_tanks(self) -> None:
        if not self.multitank_comparison_var.get():
            return
        selected_sizes = {
            self.comparison_tree_sizes[item]
            for item in self.comparison_tree.selection()
            if item in self.comparison_tree_sizes
        }
        if not selected_sizes:
            return
        self.config_model.comparison_tank_sizes_gal = [
            size for size in self.config_model.comparison_tank_sizes_gal if size not in selected_sizes
        ]
        self._populate_comparison_tanks()

    def use_comparison_as_primary(self) -> None:
        if not self.multitank_comparison_var.get():
            return
        selected = self.comparison_tree.selection()
        if len(selected) != 1 or selected[0] not in self.comparison_tree_sizes:
            messagebox.showinfo(APP_TITLE, "Select one comparison tank first.")
            return
        tank_size = self.comparison_tree_sizes[selected[0]]
        self.selected_tank_var.set(
            format_number(volume_to_display(tank_size, self.config_model), self.config_model, max_decimal_places=0)
        )

    def _use_comparison_as_primary_from_event(self, event: tk.Event) -> str:
        row_id = self.comparison_tree.identify_row(event.y)
        if row_id:
            self.comparison_tree.selection_set(row_id)
            self.use_comparison_as_primary()
        return "break"

    def _populate_comparison_tanks(self) -> None:
        if not hasattr(self, "comparison_tree"):
            return
        self.comparison_tree.delete(*self.comparison_tree.get_children())
        self.comparison_tree_sizes: dict[str, float] = {}
        unit = volume_unit(self.config_model)
        self.comparison_tree.heading("size", text=f"Tank size ({unit})")
        self._wrap_treeview_headings(self.comparison_tree)
        reliability_by_size = {
            round(float(row.TankSizeGallons), 6): float(row.ReliabilityPercent)
            for row in self.curve_df.itertuples(index=False)
        } if not self.curve_df.empty else {}
        primary_tank_size = volume_to_internal(
            _float(
                self.selected_tank_var.get(),
                volume_to_display(self.config_model.selected_tank_size_gal, self.config_model),
            ),
            self.config_model,
        )
        for index, tank_size in enumerate(sorted(set(self.config_model.comparison_tank_sizes_gal))):
            reliability = reliability_by_size.get(round(float(tank_size), 6))
            reliability_text = "--" if reliability is None else f"{format_number(reliability, self.config_model, max_decimal_places=1)}%"
            is_primary = abs(float(tank_size) - primary_tank_size) < 0.01
            item = f"comparison-{index}"
            self.comparison_tree.insert(
                "",
                "end",
                iid=item,
                values=(
                    format_number(volume_to_display(tank_size, self.config_model), self.config_model, max_decimal_places=0),
                    reliability_text,
                    "Primary" if is_primary else "",
                ),
                tags=("primary",) if is_primary else (),
            )
            self.comparison_tree_sizes[item] = tank_size

    def _toggle_multitank_comparison(self) -> None:
        self.config_model.multitank_comparison_enabled = bool(self.multitank_comparison_var.get())
        self._update_multitank_comparison_state()
        self._draw_multitank_summary()

    def _update_multitank_comparison_state(self) -> None:
        if not hasattr(self, "comparison_frame"):
            return
        disabled = not self.multitank_comparison_var.get()
        for widget in self._widget_descendants(self.comparison_frame):
            if widget is self.multitank_comparison_check:
                continue
            try:
                widget.state(["disabled"] if disabled else ["!disabled"])
            except (AttributeError, tk.TclError):
                pass

    @staticmethod
    def _widget_descendants(parent: tk.Misc) -> list[tk.Misc]:
        descendants: list[tk.Misc] = []
        for child in parent.winfo_children():
            descendants.append(child)
            descendants.extend(RainwaterTkApp._widget_descendants(child))
        return descendants

    def _set_selected_tank_reliability(self, reliability: float) -> None:
        tank_size = volume_to_display(self.config_model.selected_tank_size_gal, self.config_model)
        self.reliability_var.set(
            f"Reliability for {format_number(tank_size, self.config_model, max_decimal_places=0)} "
            f"{volume_unit(self.config_model)} tank: {format_number(reliability, self.config_model)}%"
        )
        average_precipitation = _report_average_annual_precipitation(self.rainfall_df, self.config_model)
        self.average_annual_precipitation_var.set(
            f"Average annual precipitation: {format_number(average_precipitation, self.config_model)} "
            f"{precip_unit(self.config_model)}"
        )

    def _select_state_by_first_letter(self, event: tk.Event) -> str | None:
        return self._select_state_by_char(str(event.char))

    def _select_state_by_char(self, char: str, listbox: tk.Listbox | str | None = None) -> str | None:
        key = char.casefold()
        if len(key) != 1 or not key.isalpha():
            return None

        if self.state_typeahead_after_id is not None:
            self.after_cancel(self.state_typeahead_after_id)

        self.state_typeahead += key
        if not self._select_state_by_prefix(self.state_typeahead, listbox):
            self.state_typeahead = key
            self._select_state_by_prefix(self.state_typeahead, listbox)

        self.state_typeahead_after_id = self.after(1000, self._reset_state_typeahead)
        return "break"

    def _select_state_by_prefix(self, prefix: str, listbox: tk.Listbox | str | None = None) -> bool:
        for index, (code, name) in enumerate(self._weather_location_options()):
            if code.casefold().startswith(prefix) or name.casefold().startswith(prefix):
                combo_index = index + 1
                self.state_combo.current(combo_index)
                if listbox is not None:
                    if isinstance(listbox, str):
                        self.tk.call(listbox, "selection", "clear", 0, "end")
                        self.tk.call(listbox, "selection", "set", combo_index)
                        self.tk.call(listbox, "activate", combo_index)
                        self.tk.call(listbox, "see", combo_index)
                    else:
                        listbox.selection_clear(0, tk.END)
                        listbox.selection_set(combo_index)
                        listbox.activate(combo_index)
                        listbox.see(combo_index)
                return True
        return False

    def _reset_state_typeahead(self) -> None:
        self.state_typeahead = ""
        self.state_typeahead_after_id = None

    def _select_country_by_typed_prefix(self, event: tk.Event) -> str | None:
        return self._select_country_by_char(str(event.char))

    def _select_country_by_char(self, char: str, listbox_path: str | None = None) -> str | None:
        key = char.casefold()
        if len(key) != 1 or not key.isalpha():
            return None

        if self.country_typeahead_after_id is not None:
            self.after_cancel(self.country_typeahead_after_id)
            self.country_typeahead_after_id = None
        if len(self.country_typeahead) >= 3:
            self.country_typeahead = ""

        self.country_typeahead += key
        if not self._select_country_by_prefix(self.country_typeahead, listbox_path):
            self.country_typeahead = key
            self._select_country_by_prefix(self.country_typeahead, listbox_path)

        if len(self.country_typeahead) >= 3:
            self._reset_country_typeahead()
        else:
            self.country_typeahead_after_id = self.after(1000, self._reset_country_typeahead)
        return "break"

    def _select_country_by_prefix(self, prefix: str, listbox_path: str | None = None) -> bool:
        for index, (code, name) in enumerate(COUNTRY_OPTIONS):
            if code.casefold().startswith(prefix) or name.casefold().startswith(prefix):
                self.country_combo.current(index)
                if listbox_path is not None:
                    self.tk.call(listbox_path, "selection", "clear", 0, "end")
                    self.tk.call(listbox_path, "selection", "set", index)
                    self.tk.call(listbox_path, "activate", index)
                    self.tk.call(listbox_path, "see", index)
                self._update_weather_import_provider()
                return True
        return False

    def _reset_country_typeahead(self) -> None:
        self.country_typeahead = ""
        self.country_typeahead_after_id = None

    def _select_country_in_expanded_dropdown(self, char: str) -> bool:
        try:
            popdown = self.tk.eval(f"ttk::combobox::PopdownWindow {self.country_combo}")
            return self._select_country_by_char(char, f"{popdown}.f.l") == "break"
        except tk.TclError:
            return False

    def _bind_country_combo_dropdown(self) -> None:
        self.after_idle(self._bind_country_combo_listbox)

    def _bind_country_combo_listbox(self) -> None:
        try:
            popdown = self.tk.eval(f"ttk::combobox::PopdownWindow {self.country_combo}")
            listbox_path = f"{popdown}.f.l"
            if self.country_popdown_key_command is None:
                self.country_popdown_key_command = self.register(self._select_country_in_expanded_dropdown)
            binding = f"if {{[{self.country_popdown_key_command} %K]}} {{break}}"
            self.tk.call("bind", listbox_path, "<KeyPress>", binding)
        except tk.TclError:
            return

    def _select_state_in_expanded_dropdown(self, char: str) -> bool:
        try:
            popdown = self.tk.eval(f"ttk::combobox::PopdownWindow {self.state_combo}")
            listbox_path = f"{popdown}.f.l"
            return self._select_state_by_char(char, listbox_path) == "break"
        except tk.TclError:
            return False

    def _bind_state_combo_dropdown(self) -> None:
        self.after_idle(self._bind_state_combo_listbox)

    def _bind_state_combo_listbox(self) -> None:
        try:
            popdown = self.tk.eval(f"ttk::combobox::PopdownWindow {self.state_combo}")
            listbox_path = f"{popdown}.f.l"
            if self.state_popdown_key_command is None:
                self.state_popdown_key_command = self.register(self._select_state_in_expanded_dropdown)
            binding = f"if {{[{self.state_popdown_key_command} %K]}} {{break}}"
            self.tk.call("bind", listbox_path, "<KeyPress>", binding)
        except tk.TclError:
            return

    def _select_station_by_typed_prefix(self, event: tk.Event) -> str | None:
        return self._select_station_by_char(str(event.char))

    def _select_station_by_char(self, char: str, listbox: tk.Listbox | str | None = None) -> str | None:
        key = char.casefold()
        if len(key) != 1 or not key.isalnum():
            return None

        if self.station_typeahead_after_id is not None:
            self.after_cancel(self.station_typeahead_after_id)
            self.station_typeahead_after_id = None

        max_characters = 4 if self._selected_country_code() == "CAN" else None
        if max_characters is not None and len(self.station_typeahead) >= max_characters:
            self.station_typeahead = ""

        self.station_typeahead += key
        if not self._select_station_by_prefix(self.station_typeahead, listbox):
            self.station_typeahead = key
            self._select_station_by_prefix(self.station_typeahead, listbox)

        if max_characters is not None and len(self.station_typeahead) >= max_characters:
            self._reset_station_typeahead()
        else:
            self.station_typeahead_after_id = self.after(1000, self._reset_station_typeahead)
        return "break"

    def _select_station_by_prefix(self, prefix: str, listbox: tk.Listbox | str | None = None) -> bool:
        labels = list(self.station_combo["values"])
        for index, label in enumerate(labels):
            if str(label).casefold().startswith(prefix):
                self.station_combo.current(index)
                self._update_station_marker_selection()
                if listbox is not None:
                    if isinstance(listbox, str):
                        self.tk.call(listbox, "selection", "clear", 0, "end")
                        self.tk.call(listbox, "selection", "set", index)
                        self.tk.call(listbox, "activate", index)
                        self.tk.call(listbox, "see", index)
                    else:
                        listbox.selection_clear(0, tk.END)
                        listbox.selection_set(index)
                        listbox.activate(index)
                        listbox.see(index)
                return True
        return False

    def _reset_station_typeahead(self) -> None:
        self.station_typeahead = ""
        self.station_typeahead_after_id = None

    @staticmethod
    def _station_coordinates(station: dict) -> tuple[float, float] | None:
        try:
            latitude = float(station["latitude"])
            longitude = float(station["longitude"])
        except (KeyError, TypeError, ValueError):
            return None
        if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
            return None
        return latitude, longitude

    def _open_station_map_fullscreen(self) -> None:
        existing = self.station_map_fullscreen_window
        if existing is not None and existing.winfo_exists():
            existing.lift()
            existing.focus_force()
            return
        if self.station_map_embedded is None or not self.station_map_embedded.winfo_exists():
            return

        if self.station_map_redraw_after_id is not None:
            self.after_cancel(self.station_map_redraw_after_id)
            self.station_map_redraw_after_id = None
        center = self.station_map_embedded.get_position()
        zoom = round(self.station_map_embedded.zoom)
        self._clear_station_map_markers()

        window = tk.Toplevel(self)
        self.station_map_fullscreen_window = window
        window.title("Daily rainfall weather-station map")
        window.columnconfigure(0, weight=1)
        window.rowconfigure(1, weight=1)
        toolbar = ttk.Frame(window, padding=(10, 8))
        toolbar.grid(row=0, column=0, sticky="ew")
        toolbar.columnconfigure(0, weight=1)
        ttk.Label(
            toolbar,
            text="Daily rainfall weather stations",
            font=("Segoe UI", 11, "bold"),
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            toolbar,
            text="Press Esc to return",
            foreground="#5f6b70",
        ).grid(row=0, column=1, sticky="e", padx=(12, 8))
        ttk.Button(
            toolbar,
            text="Exit full screen",
            command=self._close_station_map_fullscreen,
        ).grid(row=0, column=2, sticky="e")

        fullscreen_map = _StationMapView(window, width=1200, height=760, corner_radius=0)
        fullscreen_map.set_tile_server(OSM_TILE_URL, max_zoom=19)
        fullscreen_map.set_position(*center)
        fullscreen_map.set_zoom(zoom)
        fullscreen_map.grid(row=1, column=0, sticky="nsew")
        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>", "<ButtonRelease-1>"):
            fullscreen_map.canvas.bind(sequence, self._station_map_view_changed, add="+")
        ttk.Label(
            window,
            text="Map data © OpenStreetMap contributors",
            foreground="#5f6b70",
            padding=(8, 4),
        ).grid(row=2, column=0, sticky="e")

        self.station_map = fullscreen_map
        self.station_map_rendered_zoom = None
        self._render_station_map(fit_bounds=False)
        window.protocol("WM_DELETE_WINDOW", self._close_station_map_fullscreen)
        window.bind("<Escape>", lambda _event: self._close_station_map_fullscreen())
        window.attributes("-fullscreen", True)
        window.lift()
        fullscreen_map.focus_set()

    def _close_station_map_fullscreen(self) -> None:
        window = self.station_map_fullscreen_window
        embedded = self.station_map_embedded
        if window is None or embedded is None:
            return
        if self.station_map_redraw_after_id is not None:
            self.after_cancel(self.station_map_redraw_after_id)
            self.station_map_redraw_after_id = None
        try:
            center = self.station_map.get_position()
            zoom = round(self.station_map.zoom)
        except tk.TclError:
            center = embedded.get_position()
            zoom = round(embedded.zoom)
        self._clear_station_map_markers()
        self.station_map = embedded
        if embedded.winfo_exists():
            embedded.set_position(*center)
            embedded.set_zoom(zoom)
        self.station_map_fullscreen_window = None
        window.destroy()
        self.station_map_rendered_zoom = None
        if embedded.winfo_exists():
            self._render_station_map(fit_bounds=False)

    def _station_selection_changed(self, _event: tk.Event | None = None) -> None:
        self._reset_station_typeahead()
        self._update_station_marker_selection()

    def _station_marker_clicked(self, marker: object) -> None:
        marker_data = getattr(marker, "data", {})
        labels_in_marker = marker_data.get("labels", []) if isinstance(marker_data, dict) else []
        if len(labels_in_marker) > 1:
            latitude, longitude = getattr(marker, "position")
            self.station_map.set_position(latitude, longitude)
            self.station_map.set_zoom(min(round(self.station_map.zoom) + 2, self.station_map.max_zoom))
            self._schedule_station_map_redraw()
            return
        label = str(labels_in_marker[0]) if labels_in_marker else ""
        labels = list(self.station_combo["values"])
        if label not in labels:
            return
        self.station_combo.current(labels.index(label))
        self.station_combo.focus_set()
        self._station_selection_changed()

    @classmethod
    def _cluster_stations(cls, stations: list[dict], zoom: int, cluster_pixels: int = 70) -> list[list[dict]]:
        clusters: dict[tuple[int, int], list[dict]] = {}
        for station in stations:
            coordinates = cls._station_coordinates(station)
            if coordinates is None:
                continue
            tile_x, tile_y = decimal_to_osm(*coordinates, zoom)
            key = (int(tile_x * 256 // cluster_pixels), int(tile_y * 256 // cluster_pixels))
            clusters.setdefault(key, []).append(station)
        return list(clusters.values())

    def _clear_station_map_markers(self) -> None:
        markers = tuple(self.station_map_markers)
        self.station_map_markers = []
        self.station_map_marker_by_label = {}
        for marker in markers:
            try:
                marker.delete()
            except (IndexError, tk.TclError):
                pass

    def _render_station_map(self, *, fit_bounds: bool) -> None:
        if not hasattr(self, "station_map") or not self.station_map.winfo_exists():
            return
        self._clear_station_map_markers()
        selected_label = self.station_var.get()
        self.station_map_selected_label = selected_label
        valid_stations = [station for station in self.station_options if self._station_coordinates(station) is not None]
        positions = [self._station_coordinates(station) for station in valid_stations]
        zoom = max(round(self.station_map.zoom), 1)
        self.station_map_rendered_zoom = zoom
        for cluster in self._cluster_stations(valid_stations, zoom):
            cluster_positions = [self._station_coordinates(station) for station in cluster]
            latitude = sum(position[0] for position in cluster_positions if position is not None) / len(cluster_positions)
            longitude = sum(position[1] for position in cluster_positions if position is not None) / len(cluster_positions)
            labels = [self._station_label(station) for station in cluster]
            selected = selected_label in labels
            marker_text = labels[0] if selected and len(labels) == 1 else f"{len(labels)} stations" if len(labels) > 1 else None
            marker = self.station_map.set_marker(
                latitude,
                longitude,
                text=marker_text,
                command=self._station_marker_clicked,
                data={"labels": labels},
                marker_color_circle="#b71c1c" if selected else "#1565c0",
                marker_color_outside="#d32f2f" if selected else "#1976d2",
            )
            self.station_map_markers.append(marker)
            for label in labels:
                self.station_map_marker_by_label[label] = marker
        if not fit_bounds or not positions:
            return
        if len(positions) == 1:
            self.station_map.set_position(*positions[0])
            self.station_map.set_zoom(10)
            self._schedule_station_map_redraw()
            return
        latitudes = [position[0] for position in positions]
        longitudes = [position[1] for position in positions]
        latitude_padding = max((max(latitudes) - min(latitudes)) * 0.06, 0.05)
        longitude_padding = max((max(longitudes) - min(longitudes)) * 0.06, 0.05)
        self.station_map.fit_bounding_box(
            (max(latitudes) + latitude_padding, min(longitudes) - longitude_padding),
            (min(latitudes) - latitude_padding, max(longitudes) + longitude_padding),
        )
        self._schedule_station_map_redraw()

    def _update_station_marker_selection(self) -> None:
        selected_label = self.station_var.get()
        markers_to_update = {
            marker
            for label in (self.station_map_selected_label, selected_label)
            if (marker := self.station_map_marker_by_label.get(label)) is not None
        }
        self.station_map_selected_label = selected_label
        for marker in markers_to_update:
            marker_data = getattr(marker, "data", {})
            labels = marker_data.get("labels", []) if isinstance(marker_data, dict) else []
            selected = selected_label in labels
            marker.marker_color_circle = "#b71c1c" if selected else "#1565c0"
            marker.marker_color_outside = "#d32f2f" if selected else "#1976d2"
            text = labels[0] if selected and len(labels) == 1 else f"{len(labels)} stations" if len(labels) > 1 else None
            marker.set_text(text)

    def _station_map_view_changed(self, _event: tk.Event | None = None) -> None:
        self._schedule_station_map_redraw()

    def _schedule_station_map_redraw(self) -> None:
        if self.station_map_redraw_after_id is not None:
            self.after_cancel(self.station_map_redraw_after_id)
        self.station_map_redraw_after_id = self.after(250, self._redraw_station_map_for_zoom)

    def _redraw_station_map_for_zoom(self) -> None:
        self.station_map_redraw_after_id = None
        if not hasattr(self, "station_map") or not self.station_map.winfo_exists():
            return
        if round(self.station_map.zoom) != self.station_map_rendered_zoom:
            self._render_station_map(fit_bounds=False)

    def _bind_station_combo_dropdown(self) -> None:
        self.after_idle(self._bind_station_combo_listbox)

    def _select_station_in_expanded_dropdown(self, char: str) -> bool:
        try:
            popdown = self.tk.eval(f"ttk::combobox::PopdownWindow {self.station_combo}")
            listbox_path = f"{popdown}.f.l"
            return self._select_station_by_char(char, listbox_path) == "break"
        except tk.TclError:
            return False

    def _bind_station_combo_listbox(self) -> None:
        try:
            popdown = self.tk.eval(f"ttk::combobox::PopdownWindow {self.station_combo}")
            listbox_path = f"{popdown}.f.l"
            if self.station_popdown_key_command is None:
                self.station_popdown_key_command = self.register(self._select_station_in_expanded_dropdown)
            binding = f"if {{[{self.station_popdown_key_command} %K]}} {{break}}"
            self.tk.call("bind", listbox_path, "<KeyPress>", binding)
        except tk.TclError:
            return

    def _load_project_list(self) -> None:
        projects = self.store.list_projects()
        if self.saved_project_var.get() not in projects:
            self.saved_project_var.set("")
        if projects and not self.saved_project_var.get():
            self.saved_project_var.set(projects[0])

    def _populate_from_model(self) -> None:
        if hasattr(self, "system_animation_results"):
            self._stop_system_animation()
            self.system_animation_results = pd.DataFrame()
            self.system_animation_hour_var.set("Run a one-day simulation to begin.")
            self._draw_system_animation()
        cfg = self.config_model
        migrated_indices = migrate_legacy_demand_inputs(cfg.demand)
        for index in migrated_indices:
            self._assign_demand_object_to_end_uses(index)
        self.project_name_var.set(cfg.name)
        self.author_name_var.set(cfg.author_name)
        self.project_notes_text.delete("1.0", tk.END)
        self.project_notes_text.insert("1.0", cfg.notes)
        self.street_address_var.set(cfg.street_address)
        self.city_var.set(cfg.city)
        self.state_or_province_var.set(cfg.state_or_province)
        self.postal_code_var.set(cfg.postal_code)
        self.latitude_var.set("" if cfg.latitude is None else f"{cfg.latitude:.8f}")
        self.longitude_var.set("" if cfg.longitude is None else f"{cfg.longitude:.8f}")
        self._update_coordinates_label()
        cfg.unit_system = normalize_unit_system(cfg.unit_system)
        self.unit_var.set(cfg.unit_system)
        self.system_type_var.set(
            cfg.system_type if cfg.system_type in {"Direct system", "Indirect system"} else "Direct system"
        )
        self.current_system_type_var.set(f"Current system type: {self.system_type_var.get()}")
        self.pump_capacity_var.set(
            format_number(volume_to_display(cfg.system_parameters.pump_capacity_gallons_per_hour, cfg) / 60.0, cfg)
        )
        filtration_flow_label = (
            "Infinite" if cfg.system_parameters.filtration_system_flow_gpm == 0
            else str(cfg.system_parameters.filtration_system_flow_gpm)
        )
        self.filtration_pump_capacity_var.set(filtration_flow_label)
        self.filtration_system_flow_gpm_var.set(filtration_flow_label)
        self.filtration_system_count_var.set(str(cfg.system_parameters.filtration_system_count))
        self.transfer_pump_type_var.set(cfg.system_parameters.transfer_pump_type)
        self.filter_recovery_var.set(format_number(cfg.system_parameters.filter_recovery_percent, cfg))
        self.booster_tank_size_var.set(
            format_number(volume_to_display(cfg.system_parameters.booster_tank_size_gallons, cfg), cfg)
        )
        self.booster_initial_fill_var.set(format_number(cfg.system_parameters.booster_initial_fill_percent, cfg))
        self.booster_refill_level_var.set(format_number(cfg.system_parameters.booster_refill_level_percent, cfg))
        self.municipal_backup_enabled_var.set(cfg.system_parameters.municipal_backup_enabled)
        financial = cfg.financial_parameters
        self.financial_currency_var.set(financial.currency)
        self.financial_water_rate_var.set(format_number(financial.water_rate, cfg, max_decimal_places=4))
        self.financial_sewer_rate_var.set(format_number(financial.sewer_rate, cfg, max_decimal_places=4))
        self.financial_tariff_unit_var.set(financial.tariff_billing_unit)
        self.financial_sewer_eligible_var.set(format_number(financial.sewer_eligible_percent, cfg))
        self.financial_installed_cost_var.set(format_number(financial.installed_cost, cfg))
        self.financial_incentives_var.set(format_number(financial.incentives, cfg))
        self.financial_fixed_maintenance_var.set(format_number(financial.fixed_annual_maintenance, cfg))
        self.financial_maintenance_percent_var.set(format_number(financial.annual_maintenance_percent, cfg))
        self.financial_analysis_period_var.set(format_number(financial.analysis_period_years, cfg, max_decimal_places=0))
        self.financial_discount_rate_var.set(format_number(financial.discount_rate_percent, cfg))
        self.financial_utility_escalation_var.set(
            format_number(financial.utility_rate_escalation_percent, cfg)
        )
        self.financial_maintenance_escalation_var.set(
            format_number(financial.maintenance_escalation_percent, cfg)
        )
        self.financial_electricity_escalation_var.set(
            format_number(financial.electricity_escalation_percent, cfg)
        )
        self.financial_pump_power_var.set(format_number(financial.pump_power_kw, cfg))
        self.financial_pump_flow_rate_var.set(
            format_number(volume_to_display(financial.pump_flow_rate_gallons_per_hour, cfg), cfg)
        )
        self.financial_pump_flow_unit_var.set(f"{volume_unit(cfg)}/hour")
        self.financial_replacement_cost_var.set(
            format_number(financial.equipment_replacement_cost, cfg)
        )
        self.financial_replacement_interval_var.set(
            format_number(financial.equipment_replacement_interval_years, cfg, max_decimal_places=0)
        )
        self.financial_replacement_escalation_var.set(
            format_number(financial.equipment_replacement_escalation_percent, cfg)
        )
        optimization = cfg.optimization_parameters
        self.optimization_minimum_reliability_var.set(format_number(optimization.minimum_reliability_percent, cfg))
        self.optimization_electricity_rate_var.set(format_number(optimization.electricity_rate_per_kwh, cfg, max_decimal_places=4))
        self.optimization_objective_var.set(optimization.objective)
        self.optimization_maximum_makeup_var.set(
            "" if optimization.maximum_annual_municipal_makeup_gallons is None
            else format_number(volume_to_display(optimization.maximum_annual_municipal_makeup_gallons, cfg), cfg)
        )
        self.optimization_maximum_cost_var.set(
            "" if optimization.maximum_installed_cost is None else format_number(optimization.maximum_installed_cost, cfg)
        )
        self.optimization_positive_savings_var.set(optimization.require_positive_net_savings)
        equipment_constraints = normalized_constraints(optimization.equipment_constraints)
        self.equipment_require_values_var.set(bool(equipment_constraints["require_constraint_values"]))
        self.equipment_flow_compatibility_var.set(True)
        for key, variable in self.equipment_constraint_vars.items():
            variable.set(_constraint_display_value(equipment_constraints.get(key)))
        self._render_system_builder()
        self.country_var.set(COUNTRY_LABEL_BY_CODE.get(cfg.country_code, COUNTRY_LABEL_BY_CODE["USA"]))
        precipitation_field = (
            cfg.canadian_precipitation_field if cfg.country_code == "CAN" else cfg.acis_precipitation_field
        )
        self.canadian_precip_var.set(
            CANADIAN_PRECIPITATION_LABELS.get(precipitation_field, "Total precipitation")
        )
        if hasattr(self, "weather_frame"):
            self._update_weather_import_provider()
        self.simple_daily_var.set(format_number(volume_to_display(cfg.demand.simple_daily_demand_gallons, cfg), cfg))
        self.daily_demand_days_var.set(str(min(max(int(cfg.demand.daily_demand_days_per_week), 0), 7)))
        self.hourly_schedule_enabled_var.set(bool(cfg.demand.hourly_schedule_enabled))
        self.use_synthetic_hourly_rainfall_var.set(
            bool(cfg.use_synthetic_hourly_rainfall)
        )
        if self.rainfall_df.empty:
            self.rainfall_data_type_var.set("--")
            self.rainfall_resolution_var.set("--")
            self.rainfall_timezone_var.set("--")
            self.rainfall_timing_var.set("--")
        else:
            self.rainfall_data_type_var.set(rainfall_data_type_label(cfg.rainfall_data_type))
            self.rainfall_resolution_var.set(
                RAINFALL_RESOLUTION_LABELS.get(cfg.rainfall_temporal_resolution, "Unknown")
            )
            self.rainfall_timezone_var.set(cfg.rainfall_timezone or "Unspecified")
            self.rainfall_timing_var.set(cfg.rainfall_timing_type)
        self.hourly_schedule_summary_var.set(
            (
                f"Active hourly profile: {cfg.demand.active_hourly_schedule_name}"
                if cfg.demand.hourly_schedule_library
                else "Even 24-hour demand profile"
            )
        )
        self._refresh_schedule_management()
        self.flushes_var.set(format_number(cfg.demand.avg_flush_per_person, cfg))
        self.toilet_flush_var.set(format_number(volume_to_display(cfg.demand.gallons_per_flush_toilet, cfg), cfg))
        self.urinal_flush_var.set(format_number(volume_to_display(cfg.demand.gallons_per_flush_urinal, cfg), cfg))
        self.graph_start_var.set(format_number(volume_to_display(cfg.graph_start_gal, cfg), cfg, max_decimal_places=0))
        self.graph_end_var.set(format_number(volume_to_display(cfg.graph_end_gal, cfg), cfg, max_decimal_places=0))
        self.graph_step_var.set(format_number(volume_to_display(cfg.graph_step_gal, cfg), cfg, max_decimal_places=0))
        self.graph_auto_step_count_var.set(format_number(cfg.graph_auto_step_count, cfg, max_decimal_places=0))
        self.selected_tank_var.set(format_number(volume_to_display(cfg.selected_tank_size_gal, cfg), cfg, max_decimal_places=0))
        self.recommendation_reliability_target_var.set(
            format_number(cfg.recommendation_reliability_target_percent, cfg)
        )
        self.recommendation_marginal_gain_var.set(
            format_number(cfg.recommendation_marginal_gain_threshold, cfg)
        )
        self.multitank_comparison_var.set(cfg.multitank_comparison_enabled)
        report_sections = normalize_report_sections(cfg.report_sections)
        for key, variable in self.report_section_vars.items():
            variable.set(report_sections[key])
        self.report_include_system_visualization_var.set(
            cfg.report_include_system_visualization
        )
        self.report_include_multitank_charts_var.set(
            cfg.report_include_multitank_charts
        )
        self.initial_fill_var.set(format_number(cfg.tank_parameters.initial_fill_percent, cfg))
        self.reserve_var.set(format_number(cfg.tank_parameters.minimum_operating_volume_percent, cfg))
        prior_component_editor_loading = getattr(
            self, "system_component_editor_loading", False
        )
        self.system_component_editor_loading = True
        sizing_method = normalize_first_flush_sizing_method(cfg.first_flush_sizing_method)
        design_preset = normalize_first_flush_design_preset(cfg.first_flush_design_preset)
        try:
            self.first_flush_sizing_method_var.set(SIZING_METHOD_LABELS[sizing_method])
            self.first_flush_design_preset_var.set(DESIGN_PRESET_LABELS[design_preset])
            self._refresh_first_flush_guidance()
            antecedent_unit = (
                cfg.first_flush_antecedent_dry_unit
                if cfg.first_flush_antecedent_dry_unit in {"days", "hours"}
                else "days"
            )
            self.first_flush_antecedent_display_unit = antecedent_unit
            self.first_flush_antecedent_unit_var.set(antecedent_unit)
            antecedent_display_value = _antecedent_dry_period_from_days(
                cfg.first_flush_antecedent_dry_days, antecedent_unit
            )
            self.first_flush_antecedent_var.set(
                format_number(antecedent_display_value, cfg)
            )
        finally:
            self.system_component_editor_loading = prior_component_editor_loading
        self._update_setting_unit_labels()
        self._populate_surfaces()
        self._populate_demand()
        self._populate_comparison_tanks()
        self._update_multitank_comparison_state()
        self._update_rainfall_summary()
        self._refresh_synthetic_hourly_rainfall_status()
        self._refresh_system_animation_dates()
        self._refresh_optimization_assumptions()
        self._refresh_design_recommendations()
        if hasattr(self, "climate_normal_tree"):
            self._refresh_climate_normal_comparison()

    def _update_setting_unit_labels(self) -> None:
        unit = volume_unit(self.config_model)
        self.simple_daily_unit_var.set(f"{unit}/day")
        self.flush_volume_unit_var.set(f"{unit}/flush")
        self.tank_size_unit_var.set(unit)
        self.pump_capacity_unit_var.set(f"{unit}/min")

    def _apply_form_to_model(self) -> bool:
        cfg = self.config_model
        cfg.name = self.project_name_var.get().strip() or "Unnamed Project"
        cfg.author_name = self.author_name_var.get().strip()
        cfg.notes = self.project_notes_text.get("1.0", "end-1c").strip()
        cfg.street_address = self.street_address_var.get().strip()
        cfg.city = self.city_var.get().strip()
        cfg.state_or_province = self.state_or_province_var.get().strip()
        cfg.postal_code = self.postal_code_var.get().strip()
        try:
            cfg.latitude, cfg.longitude = _parse_coordinates(self.latitude_var.get(), self.longitude_var.get())
            self._update_coordinates_label()
        except ValueError:
            pass
        cfg.country_code = self.country_var.get().split(" - ", 1)[0].strip() or "USA"
        precipitation_field = CANADIAN_PRECIPITATION_OPTIONS.get(self.canadian_precip_var.get(), "TOTAL_PRECIPITATION")
        if cfg.country_code == "CAN":
            cfg.canadian_precipitation_field = precipitation_field
        else:
            cfg.acis_precipitation_field = precipitation_field
        old_unit = cfg.unit_system
        cfg.unit_system = normalize_unit_system(self.unit_var.get())
        if old_unit != cfg.unit_system:
            self._populate_from_model()
            return True

        cfg.demand.simple_daily_demand_gallons = volume_to_internal(_float(self.simple_daily_var.get()), cfg)
        cfg.demand.daily_demand_days_per_week = min(
            max(int(_float(self.daily_demand_days_var.get(), 7)), 0),
            7,
        )
        cfg.demand.hourly_schedule_enabled = bool(self.hourly_schedule_enabled_var.get())
        cfg.use_synthetic_hourly_rainfall = bool(
            self.use_synthetic_hourly_rainfall_var.get()
        )
        cfg.rainfall_data_type = RAINFALL_DATA_TYPE_BY_LABEL.get(
            self.rainfall_data_type_var.get(), "unclassified"
        )
        cfg.rainfall_temporal_resolution = next(
            (
                key
                for key, label in RAINFALL_RESOLUTION_LABELS.items()
                if label == self.rainfall_resolution_var.get()
            ),
            "unknown",
        )
        cfg.rainfall_timezone = self.rainfall_timezone_var.get().strip() or "Unspecified"
        cfg.system_parameters.pump_capacity_gallons_per_hour = max(
            0.0, volume_to_internal(_float(self.pump_capacity_var.get(), 0.0) * 60.0, cfg)
        )
        cfg.system_parameters.filtration_system_flow_gpm = (
            normalize_filtration_system_flow_gpm(self.filtration_system_flow_gpm_var.get())
        )
        cfg.system_parameters.filtration_system_count = max(
            int(_float(self.filtration_system_count_var.get(), 1.0)), 1
        )
        cfg.system_parameters.transfer_pump_type = self.transfer_pump_type_var.get()
        cfg.system_parameters.synchronize_filtration_flow()
        cfg.system_parameters.filter_recovery_percent = min(
            max(_float(self.filter_recovery_var.get(), 100.0), 0.0), 100.0
        )
        cfg.system_parameters.booster_tank_size_gallons = max(
            0.0, volume_to_internal(_float(self.booster_tank_size_var.get(), 0.0), cfg)
        )
        cfg.system_parameters.booster_initial_fill_percent = min(
            max(_float(self.booster_initial_fill_var.get(), 0.0), 0.0), 100.0
        )
        cfg.system_parameters.booster_refill_level_percent = min(
            max(_float(self.booster_refill_level_var.get(), 50.0), 0.0), 100.0
        )
        cfg.system_parameters.municipal_backup_enabled = bool(self.municipal_backup_enabled_var.get())
        self._apply_financial_form_to_model()
        cfg.optimization_parameters.minimum_reliability_percent = _float(
            self.optimization_minimum_reliability_var.get(), 80.0
        )
        cfg.optimization_parameters.electricity_rate_per_kwh = _float(
            self.optimization_electricity_rate_var.get(), 0.15
        )
        cfg.optimization_parameters.objective = self.optimization_objective_var.get() or "Simple payback"
        maximum_makeup = self.optimization_maximum_makeup_var.get().strip()
        cfg.optimization_parameters.maximum_annual_municipal_makeup_gallons = (
            volume_to_internal(_float(maximum_makeup, 0.0), cfg) if maximum_makeup else None
        )
        maximum_cost = self.optimization_maximum_cost_var.get().strip()
        cfg.optimization_parameters.maximum_installed_cost = _float(maximum_cost, 0.0) if maximum_cost else None
        cfg.optimization_parameters.require_positive_net_savings = bool(
            self.optimization_positive_savings_var.get()
        )
        current_constraints = normalized_constraints(cfg.optimization_parameters.equipment_constraints)
        current_constraints["require_constraint_values"] = self.equipment_require_values_var.get()
        current_constraints["enforce_flow_compatibility"] = True
        current_constraints["approved_vendors"] = [
            value.strip() for value in self.equipment_constraint_vars["approved_vendors"].get().split(",") if value.strip()
        ]
        current_constraints["required_tags"] = [
            value.strip() for value in self.equipment_constraint_vars["required_tags"].get().split(",") if value.strip()
        ]
        current_constraints["required_standards"] = [
            value.strip() for value in self.equipment_constraint_vars["required_standards"].get().split(",") if value.strip()
        ]
        for key in ("required_voltage", "required_phase", "required_pressure_class", "required_connection_size", "project_standards"):
            current_constraints[key] = self.equipment_constraint_vars[key].get().strip()
        for key in ("maximum_length", "maximum_width", "maximum_height", "maximum_footprint", "minimum_access_clearance"):
            raw_value = self.equipment_constraint_vars[key].get().strip()
            current_constraints[key] = _float(raw_value) if raw_value else None
        cfg.optimization_parameters.equipment_constraints = current_constraints
        cfg.demand.avg_flush_per_person = _float(self.flushes_var.get())
        cfg.demand.gallons_per_flush_toilet = volume_to_internal(_float(self.toilet_flush_var.get()), cfg)
        cfg.demand.gallons_per_flush_urinal = volume_to_internal(_float(self.urinal_flush_var.get()), cfg)
        cfg.graph_start_gal = max(1, int(round(volume_to_internal(_float(self.graph_start_var.get(), 500), cfg))))
        cfg.graph_end_gal = max(2, int(round(volume_to_internal(_float(self.graph_end_var.get(), 20000), cfg))))
        cfg.graph_step_gal = max(1, int(round(volume_to_internal(_float(self.graph_step_var.get(), 500), cfg))))
        cfg.graph_auto_step_count = max(1, int(_float(self.graph_auto_step_count_var.get(), 20)))
        cfg.selected_tank_size_gal = max(0.0, volume_to_internal(_float(self.selected_tank_var.get(), 5000), cfg))
        cfg.recommendation_reliability_target_percent = min(
            max(_float(self.recommendation_reliability_target_var.get(), 90.0), 0.0),
            100.0,
        )
        cfg.recommendation_marginal_gain_threshold = max(
            _float(self.recommendation_marginal_gain_var.get(), 1.0), 0.0
        )
        cfg.multitank_comparison_enabled = bool(self.multitank_comparison_var.get())
        self._apply_report_options_to_model()
        cfg.tank_parameters.initial_fill_percent = min(max(_float(self.initial_fill_var.get(), 50), 0), 100)
        cfg.tank_parameters.minimum_operating_volume_percent = min(
            max(_float(self.reserve_var.get(), 0), 0), 100
        )
        cfg.first_flush_sizing_method = self._selected_first_flush_sizing_method()
        cfg.first_flush_design_preset = self._selected_first_flush_design_preset()
        antecedent_unit = self.first_flush_antecedent_unit_var.get().casefold()
        if antecedent_unit not in {"days", "hours"}:
            antecedent_unit = "days"
        cfg.first_flush_antecedent_dry_unit = antecedent_unit
        antecedent_default = _antecedent_dry_period_from_days(
            cfg.first_flush_antecedent_dry_days, antecedent_unit
        )
        cfg.first_flush_antecedent_dry_days = max(
            _antecedent_dry_period_to_days(
                _float(self.first_flush_antecedent_var.get(), antecedent_default),
                antecedent_unit,
            ),
            0.0,
        )
        return True

    def _apply_financial_form_to_model(self) -> None:
        params = self.config_model.financial_parameters
        params.currency = self.financial_currency_var.get().strip() or "USD"
        params.water_rate = _float(self.financial_water_rate_var.get(), 0.0)
        params.sewer_rate = _float(self.financial_sewer_rate_var.get(), 0.0)
        params.tariff_billing_unit = self.financial_tariff_unit_var.get().strip() or "per 1,000 gal"
        params.sewer_eligible_percent = _float(self.financial_sewer_eligible_var.get(), 100.0)
        params.installed_cost = _float(self.financial_installed_cost_var.get(), 0.0)
        params.incentives = _float(self.financial_incentives_var.get(), 0.0)
        params.fixed_annual_maintenance = _float(self.financial_fixed_maintenance_var.get(), 0.0)
        params.annual_maintenance_percent = _float(
            self.financial_maintenance_percent_var.get(), 0.0
        )
        params.analysis_period_years = int(_float(self.financial_analysis_period_var.get(), 20.0))
        params.discount_rate_percent = _float(self.financial_discount_rate_var.get(), 5.0)
        params.utility_rate_escalation_percent = _float(
            self.financial_utility_escalation_var.get(), 0.0
        )
        params.maintenance_escalation_percent = _float(
            self.financial_maintenance_escalation_var.get(), 0.0
        )
        params.electricity_escalation_percent = _float(
            self.financial_electricity_escalation_var.get(), 0.0
        )
        params.pump_power_kw = _float(self.financial_pump_power_var.get(), 0.0)
        params.pump_flow_rate_gallons_per_hour = volume_to_internal(
            _float(self.financial_pump_flow_rate_var.get(), 0.0), self.config_model
        )
        params.equipment_replacement_cost = _float(
            self.financial_replacement_cost_var.get(), 0.0
        )
        params.equipment_replacement_interval_years = int(
            _float(self.financial_replacement_interval_var.get(), 0.0)
        )
        params.equipment_replacement_escalation_percent = _float(
            self.financial_replacement_escalation_var.get(), 0.0
        )
        self.config_model.optimization_parameters.electricity_rate_per_kwh = _float(
            self.optimization_electricity_rate_var.get(), 0.15
        )

    def _populate_surfaces(self) -> None:
        self.surface_tree.heading("area", text=f"Area ({area_unit(self.config_model)})")
        self._wrap_treeview_headings(self.surface_tree)
        self.surface_tree.delete(*self.surface_tree.get_children())
        for i, surface in enumerate(self.config_model.surfaces):
            template = DEFAULT_SURFACES[i] if i < len(DEFAULT_SURFACES) else None
            is_untouched_template = (
                template is not None
                and surface.area <= 0.0
                and surface.name.casefold() == template.name.casefold()
                and surface.runoff_coefficient == template.runoff_coefficient
                and surface.first_flush_depth_inches == template.first_flush_depth_inches
            )
            if is_untouched_template:
                continue
            self.surface_tree.insert(
                "",
                "end",
                iid=str(i),
                values=(
                    surface.name,
                    format_number(area_to_display(surface.area, self.config_model), self.config_model),
                    format_number(surface.runoff_coefficient, self.config_model),
                ),
            )

    def _populate_demand(self) -> None:
        self._update_demand_headings()
        self._populate_demand_objects()
        self.demand_tree.delete(*self.demand_tree.get_children())
        monthly_volume_fields = {field for field, _label in DEMAND_FIELDS if field not in {"male_occupancy", "female_occupancy"}}
        for month in MONTH_KEYS:
            row = [MONTH_LABELS[month]]
            for field, _label in DEMAND_FIELDS:
                value = getattr(self.config_model.demand, field)[month]
                if field in monthly_volume_fields:
                    value = volume_to_display(value, self.config_model)
                row.append(format_number(value, self.config_model))
            self.demand_tree.insert("", "end", iid=month, values=row)

    def _populate_demand_objects(self, select_index: int | None = None) -> None:
        if not hasattr(self, "demand_objects_tree"):
            return
        for tree in (self.demand_objects_tree,):
            tree.heading(
                "instantaneous_demand", text="Demand quantity"
            )
            self._wrap_treeview_headings(tree)
            tree.delete(*tree.get_children())
            for index, demand_object in enumerate(self.config_model.demand.demand_objects):
                tree.insert(
                    "", "end", iid=str(index),
                    values=(
                        demand_object.name,
                        demand_object.object_type,
                        self._demand_object_quantity_summary(demand_object),
                        demand_object.schedule_name,
                        (
                            f"Legacy {self.config_model.financial_parameters.sewer_eligible_percent:g}%"
                            if demand_object.uses_legacy_sewer_eligibility
                            else ("Eligible" if demand_object.sewer_eligible else "Exempt")
                        ),
                    ),
                )
            if select_index is not None and 0 <= select_index < len(self.config_model.demand.demand_objects):
                iid = str(select_index)
                tree.selection_set(iid)
                tree.focus(iid)
                tree.see(iid)
        self._render_system_builder()

    def _demand_object_quantity_summary(self, demand_object: DemandObject) -> str:
        unit = volume_unit(self.config_model)
        if demand_object.demand_mode == "fixture_usage":
            daily = fixture_daily_demand_gallons(demand_object)
            return (
                f"{format_number(volume_to_display(daily, self.config_model), self.config_model)} "
                f"{unit}/active day "
                f"({format_number(demand_object.fixture_people, self.config_model)} people)"
            )
        if demand_object.demand_mode == "recurring_daily":
            return (
                f"{format_number(volume_to_display(demand_object.recurring_daily_gallons, self.config_model), self.config_model)} "
                f"{unit}/occupied day"
            )
        if demand_object.demand_mode == "monthly_volume":
            value = max(demand_object.monthly_demand_gallons.values(), default=0.0)
            return (
                f"up to {format_number(volume_to_display(value, self.config_model), self.config_model)} "
                f"{unit}/month"
            )
        value = volume_to_display(
            demand_object.instantaneous_demand_gallons_per_minute, self.config_model
        )
        return f"{format_number(value, self.config_model)} {unit}/min"

    def _update_demand_headings(self) -> None:
        unit = volume_unit(self.config_model)
        demand_style = ttk.Style(self)
        heading_font_name = demand_style.lookup("MonthlyDemand.Treeview.Heading", "font") or "TkHeadingFont"
        heading_font = tkfont.Font(root=self, font=heading_font_name)
        month_minimum_width = heading_font.measure("Month") + 18
        self.demand_tree.column("month", minwidth=month_minimum_width, width=max(80, month_minimum_width))
        for field, label in DEMAND_FIELDS:
            if field in {"male_occupancy", "female_occupancy"}:
                heading = f"{label} (people/day)"
            else:
                heading = f"{label} ({unit}/month)"
            words = heading.split()
            minimum_width = max(heading_font.measure(word) for word in words) + 18
            target_width = max(105, minimum_width)
            self.demand_tree.column(field, minwidth=minimum_width, width=target_width)
            self.demand_tree.heading(field, text=heading)
        self._wrap_treeview_headings(self.demand_tree)

    def _update_rainfall_summary(self) -> None:
        if self.rainfall_df.empty:
            self.rainfall_summary_var.set("No rainfall file loaded")
            self.rainfall_quality_var.set("Quality assessment unavailable")
            save_button = self.__dict__.get("save_rainfall_csv_button")
            if save_button is not None:
                save_button.state(["disabled"])
            self._refresh_system_animation_dates()
            self._refresh_synthetic_hourly_rainfall_status()
            return
        save_button = self.__dict__.get("save_rainfall_csv_button")
        if save_button is not None:
            save_button.state(["!disabled"])
        start = pd.Timestamp(self.rainfall_df["Date"].min()).strftime("%Y-%m-%d")
        end = pd.Timestamp(self.rainfall_df["Date"].max()).strftime("%Y-%m-%d")
        source = f" from {self.rainfall_source_label}" if self.rainfall_source_label else ""
        hourly = "; Hyetos-style hourly profiles generated" if has_hourly_rainfall(self.rainfall_df) else ""
        self.rainfall_summary_var.set(
            f"{len(self.rainfall_df):,} rainfall rows loaded ({start} to {end}){source}{hourly}"
        )
        quality = self._rainfall_quality_assessment()
        partial_years = ", ".join(str(year) for year in quality.partial_years)
        quality_parts = [
            f"Completeness: {format_number(quality.completeness_percent, self.config_model)}% ({quality.completeness_rating}); "
            f"{quality.observed_days:,} of {quality.expected_days:,} calendar days observed",
            f"{quality.missing_days:,} missing day(s) in {len(quality.missing_periods):,} period(s)",
        ]
        if partial_years:
            quality_parts.append(f"partial/incomplete year(s): {partial_years}")
        if quality.duplicate_dates:
            quality_parts.append(f"{quality.duplicate_dates:,} duplicate date(s)")
        self.rainfall_quality_var.set("; ".join(quality_parts) + ".")
        self._refresh_system_animation_dates()
        self._refresh_synthetic_hourly_rainfall_status()

    def _rainfall_quality_assessment(self) -> RainfallQualityAssessment:
        return assess_rainfall_record(
            self.rainfall_df,
            known_missing_dates=self.config_model.rainfall_known_missing_dates,
            antecedent_dry_days=self.config_model.first_flush_antecedent_dry_days,
        )

    def _rainfall_provenance_changed(self, _event: tk.Event | None = None) -> None:
        cfg = self.config_model
        cfg.rainfall_data_type = RAINFALL_DATA_TYPE_BY_LABEL.get(
            self.rainfall_data_type_var.get(), "unclassified"
        )
        cfg.rainfall_temporal_resolution = next(
            (
                key
                for key, label in RAINFALL_RESOLUTION_LABELS.items()
                if label == self.rainfall_resolution_var.get()
            ),
            "unknown",
        )
        cfg.rainfall_timezone = self.rainfall_timezone_var.get().strip() or "Unspecified"
        self._update_rainfall_summary()

    def _change_units(self) -> None:
        new_unit = self.unit_var.get()
        old_unit = self.config_model.unit_system
        self.unit_var.set(old_unit)
        self._apply_form_to_model()
        self.unit_var.set(new_unit)
        self.config_model.unit_system = new_unit
        self._populate_from_model()
        if not self.results_df.empty:
            reliability = float(self.results_df["ReliabilityPercent"].iloc[0])
            self._set_selected_tank_reliability(reliability)
        self.unit_conversion_form_snapshot = self._calculation_form_snapshot()

    def _calculation_form_snapshot(self) -> tuple[str, ...]:
        return tuple(
            str(variable.get())
            for variable in (
                self.simple_daily_var,
                self.daily_demand_days_var,
                self.hourly_schedule_enabled_var,
                self.flushes_var,
                self.toilet_flush_var,
                self.urinal_flush_var,
                self.graph_start_var,
                self.graph_end_var,
                self.graph_step_var,
                self.selected_tank_var,
                self.initial_fill_var,
                self.reserve_var,
                self.first_flush_sizing_method_var,
                self.first_flush_design_preset_var,
                self.first_flush_antecedent_var,
                self.first_flush_antecedent_unit_var,
                self.pump_capacity_var,
                self.filtration_pump_capacity_var,
                self.filtration_system_flow_gpm_var,
                self.filtration_system_count_var,
                self.transfer_pump_type_var,
                self.filter_recovery_var,
                self.booster_tank_size_var,
                self.booster_initial_fill_var,
                self.booster_refill_level_var,
                self.municipal_backup_enabled_var,
                self.system_type_var,
            )
        )

    def _country_changed(self, _event: tk.Event | None = None) -> None:
        self.config_model.country_code = self._selected_country_code()
        precipitation_field = (
            self.config_model.canadian_precipitation_field
            if self.config_model.country_code == "CAN"
            else self.config_model.acis_precipitation_field
        )
        self.canadian_precip_var.set(
            CANADIAN_PRECIPITATION_LABELS.get(precipitation_field, "Total precipitation")
        )
        self._update_weather_import_provider()

    def _update_coordinates_label(self) -> None:
        latitude = self.config_model.latitude
        longitude = self.config_model.longitude
        if latitude is None or longitude is None:
            self.coordinates_var.set("Coordinates: not selected")
        else:
            self.coordinates_var.set(f"Coordinates: {latitude:.6f}, {longitude:.6f}")

    def _coordinates_from_form(self, *, require_coordinates: bool) -> tuple[float | None, float | None] | None:
        try:
            latitude, longitude = _parse_coordinates(self.latitude_var.get(), self.longitude_var.get())
        except ValueError as exc:
            messagebox.showwarning(APP_TITLE, str(exc))
            return None
        if require_coordinates and (latitude is None or longitude is None):
            messagebox.showinfo(APP_TITLE, "Enter latitude and longitude first.")
            return None
        self.config_model.latitude = latitude
        self.config_model.longitude = longitude
        self._update_coordinates_label()
        return latitude, longitude

    def find_project_location(self) -> None:
        coordinates = self._coordinates_from_form(require_coordinates=False)
        if coordinates is None:
            return
        latitude, longitude = coordinates
        has_location = latitude is not None and longitude is not None
        if not has_location:
            country = self._selected_country_code()
            if country == "CAN":
                latitude, longitude, initial_zoom = 56.1304, -106.3468, 3
            elif country == "USA":
                latitude, longitude, initial_zoom = 39.5, -98.35, 3
            else:
                latitude, longitude, initial_zoom = 20.0, 0.0, 2
        else:
            initial_zoom = 16
        dialog = ProjectLocationPickerDialog(
            self,
            float(latitude),
            float(longitude),
            initial_zoom,
            has_location,
        )
        self.status_var.set("OpenStreetMap location picker opened")
        self.wait_window(dialog)
        if dialog.result is None:
            self.status_var.set("OpenStreetMap location selection cancelled")
            self._focus_main_window()
            return
        selected_latitude, selected_longitude = dialog.result
        self.config_model.latitude = selected_latitude
        self.config_model.longitude = selected_longitude
        self.latitude_var.set(f"{selected_latitude:.8f}")
        self.longitude_var.set(f"{selected_longitude:.8f}")
        self._update_coordinates_label()
        self.status_var.set("Finding the nearest OpenStreetMap address...")
        threading.Thread(
            target=self._reverse_geocode_project_location,
            args=(selected_latitude, selected_longitude),
            name="rwh-reverse-geocode",
            daemon=True,
        ).start()
        if self.location_poll_after_id is None:
            self.location_poll_after_id = self.after(100, self._poll_location_results)
        self._focus_main_window()

    def find_address_for_coordinates(self) -> None:
        coordinates = self._coordinates_from_form(require_coordinates=True)
        if coordinates is None:
            return
        latitude, longitude = coordinates
        assert latitude is not None and longitude is not None
        self.status_var.set("Finding the nearest OpenStreetMap address...")
        threading.Thread(
            target=self._reverse_geocode_project_location,
            args=(latitude, longitude),
            name="rwh-reverse-geocode",
            daemon=True,
        ).start()
        if self.location_poll_after_id is None:
            self.location_poll_after_id = self.after(100, self._poll_location_results)

    def find_coordinates_for_address(self) -> None:
        address_parts = [
            self.street_address_var.get().strip(),
            self.city_var.get().strip(),
            self.state_or_province_var.get().strip(),
            self.postal_code_var.get().strip(),
        ]
        country = pycountry.countries.get(alpha_3=self._selected_country_code())
        country_name = country.name if country is not None else ""
        address_text = ", ".join(part for part in [*address_parts, country_name] if part)
        address_fields = {
            "street": address_parts[0],
            "city": address_parts[1],
            "state": address_parts[2],
            "postalcode": address_parts[3],
            "country": country_name,
        }
        if not any(address_parts):
            messagebox.showinfo(APP_TITLE, "Enter a project address before searching for coordinates.")
            return
        self.status_var.set("Finding the nearest OpenStreetMap coordinates...")
        threading.Thread(
            target=self._forward_geocode_project_location,
            args=(address_text, country.alpha_2 if country is not None else "", address_fields),
            name="rwh-forward-geocode",
            daemon=True,
        ).start()
        if self.location_poll_after_id is None:
            self.location_poll_after_id = self.after(100, self._poll_location_results)

    def _poll_location_results(self) -> None:
        self.location_poll_after_id = None
        try:
            while True:
                result = self.location_result_queue.get_nowait()
                kind = result[0]
                if kind == "selected":
                    latitude, longitude = float(result[1]), float(result[2])
                    self.config_model.latitude = latitude
                    self.config_model.longitude = longitude
                    self.latitude_var.set(f"{latitude:.8f}")
                    self.longitude_var.set(f"{longitude:.8f}")
                    self._update_coordinates_label()
                    self.after(150, self._focus_main_window)
                    self.status_var.set("Finding the nearest OpenStreetMap address...")
                    threading.Thread(
                        target=self._reverse_geocode_project_location,
                        args=(latitude, longitude),
                        name="rwh-reverse-geocode",
                        daemon=True,
                    ).start()
                elif kind == "address":
                    self._apply_reverse_geocode_result(result[1])
                elif kind == "coordinates":
                    self._apply_forward_geocode_result(result[1])
                elif kind == "geocode_error":
                    self.status_var.set("OpenStreetMap coordinate lookup failed")
                    messagebox.showwarning(
                        APP_TITLE,
                        f"Coordinates could not be found for the entered address:\n{result[1]}",
                    )
                elif kind == "error":
                    self.status_var.set("OpenStreetMap address lookup failed")
                    messagebox.showwarning(
                        APP_TITLE,
                        f"The coordinates were saved, but the nearest address could not be found:\n{result[1]}",
                    )
        except queue.Empty:
            pass
        self.location_poll_after_id = self.after(100, self._poll_location_results)

    def _focus_main_window(self) -> None:
        if self.state() == "iconic":
            self.deiconify()
        self.lift()
        self.attributes("-topmost", True)
        self.focus_force()
        self.after(100, lambda: self.attributes("-topmost", False))

    def _reverse_geocode_project_location(self, latitude: float, longitude: float) -> None:
        try:
            address = reverse_geocode_osm(latitude, longitude)
            self.location_result_queue.put(("address", address))
        except Exception as exc:  # noqa: BLE001
            self.location_result_queue.put(("error", str(exc)))

    def _forward_geocode_project_location(
        self, address_text: str, country_code_alpha2: str, address_fields: dict[str, str]
    ) -> None:
        try:
            coordinates = geocode_osm_address(address_text, country_code_alpha2, address_fields)
            self.location_result_queue.put(("coordinates", coordinates))
        except Exception as exc:  # noqa: BLE001
            self.location_result_queue.put(("geocode_error", str(exc)))

    def _apply_forward_geocode_result(self, coordinates: dict[str, object]) -> None:
        latitude = float(coordinates["latitude"])
        longitude = float(coordinates["longitude"])
        self.config_model.latitude = latitude
        self.config_model.longitude = longitude
        self.latitude_var.set(f"{latitude:.8f}")
        self.longitude_var.set(f"{longitude:.8f}")
        self._update_coordinates_label()
        self.status_var.set("Nearest OpenStreetMap coordinates applied to the project location")
        self._focus_main_window()

    def _apply_reverse_geocode_result(self, address: dict[str, str]) -> None:
        self.street_address_var.set(address.get("street_address", ""))
        self.city_var.set(address.get("city", ""))
        self.state_or_province_var.set(address.get("state_or_province", ""))
        self.postal_code_var.set(address.get("postal_code", ""))
        country = pycountry.countries.get(alpha_2=address.get("country_code_alpha2", ""))
        if country is not None:
            self.country_var.set(COUNTRY_LABEL_BY_CODE.get(country.alpha_3, self.country_var.get()))
            self.config_model.country_code = country.alpha_3
            self._update_weather_import_provider()
        self._apply_form_to_model()
        self.status_var.set("Project location and nearest OpenStreetMap address selected")

    def _selected_country_code(self) -> str:
        return self.country_var.get().split(" - ", 1)[0].strip() or "USA"

    def _weather_location_options(self) -> list[tuple[str, str]]:
        return PROVINCE_OPTIONS if self._selected_country_code() == "CAN" else STATE_OPTIONS

    def _update_weather_import_provider(self) -> None:
        if not hasattr(self, "weather_frame"):
            return
        country = self._selected_country_code()
        self._reset_weather_selection()
        if country == "USA":
            self.weather_frame.configure(text="ACIS Weather Import")
            self.weather_source_note_var.set(
                "Daily station precipitation from the NOAA Regional Climate Centers' ACIS service (inches)."
            )
            self.weather_source_link_var.set("View the ACIS data source")
            self.weather_source_url = ACIS_SOURCE_URL
            self.weather_source_link.grid()
            self.weather_location_label.configure(text="State")
            self.state_combo.configure(values=[STATE_PLACEHOLDER, *STATE_LABELS], state="readonly")
            self.canadian_precip_label.grid()
            self.canadian_precip_combo.grid()
            enabled = True
        elif country == "CAN":
            self.weather_frame.configure(text="ECCC Canadian Climate Import")
            self.weather_source_note_var.set(
                "Daily station precipitation from Environment and Climate Change Canada (millimetres)."
            )
            self.weather_source_link_var.set("View ECCC Historical Climate Data")
            self.weather_source_url = ECCC_SOURCE_URL
            self.weather_source_link.grid()
            self.weather_location_label.configure(text="Province / territory")
            self.state_combo.configure(values=[PROVINCE_PLACEHOLDER, *PROVINCE_LABELS], state="readonly")
            self.canadian_precip_label.grid()
            self.canadian_precip_combo.grid()
            enabled = True
        else:
            self.weather_frame.configure(text="Weather Import")
            self.weather_source_note_var.set("Automatic weather-data import is currently available for the USA and Canada.")
            self.weather_source_link_var.set("")
            self.weather_source_link.grid_remove()
            self.weather_location_label.configure(text="Region")
            self.state_combo.configure(values=["-- Weather import unavailable --"], state="disabled")
            self.weather_state_var.set("-- Weather import unavailable --")
            self.canadian_precip_label.grid_remove()
            self.canadian_precip_combo.grid_remove()
            enabled = False
        self.station_combo.configure(state="readonly" if enabled else "disabled")
        self.find_stations_button.configure(state="normal" if enabled else "disabled")
        self.find_nearest_stations_button.configure(state="normal" if enabled else "disabled")
        self.find_nearest_airport_stations_button.configure(
            state="normal" if enabled else "disabled"
        )
        self.import_station_button.configure(state="normal" if enabled else "disabled")

    def _project_form_values(self) -> dict[str, object]:
        values: dict[str, object] = {}
        for attribute_name in PROJECT_FORM_VARIABLES:
            variable = getattr(self, attribute_name, None)
            if isinstance(variable, tk.Variable):
                values[attribute_name] = variable.get()
        return values

    def _restore_project_form_values(self, values: dict[str, object], notes: str) -> None:
        for attribute_name, value in values.items():
            variable = getattr(self, attribute_name, None)
            if isinstance(variable, tk.Variable):
                variable.set(value)
        self.project_notes_text.delete("1.0", tk.END)
        self.project_notes_text.insert("1.0", notes)

    def _current_project_fingerprint(self) -> str:
        return project_state_fingerprint(
            self.config_model,
            self.rainfall_df,
            self.curve_df,
            self.results_df,
            self._comparison_results_to_frame(),
            self.hourly_results_df,
            form_values=self._project_form_values(),
            notes=self.project_notes_text.get("1.0", "end-1c"),
        )

    def _update_project_state_display(self) -> None:
        project_name = self.active_project_name or self.project_name_var.get().strip()
        title = APP_TITLE if not project_name else f"{APP_TITLE} - {project_name}"
        if self._project_dirty:
            title = f"{title} *"
            self.project_state_var.set("Unsaved changes")
        else:
            self.project_state_var.set("All changes saved")
        self.title(title)

    def _refresh_project_dirty_state(self) -> bool:
        self._project_dirty = (
            self._current_project_fingerprint() != self._saved_state_fingerprint
        )
        self._update_project_state_display()
        return self._project_dirty

    def _poll_project_state(self) -> None:
        self.project_state_poll_after_id = None
        try:
            self._refresh_project_dirty_state()
        finally:
            if self.winfo_exists():
                self.project_state_poll_after_id = self.after(
                    PROJECT_STATE_POLL_MS, self._poll_project_state
                )

    def _accept_current_project_state(self, *, clear_draft: bool = True) -> None:
        self._saved_state_fingerprint = self._current_project_fingerprint()
        self._last_draft_fingerprint = ""
        self._project_dirty = False
        self._update_project_state_display()
        if clear_draft:
            self.working_draft_store.clear()

    def _confirm_project_replacement(self, action: str) -> bool:
        if not self._refresh_project_dirty_state():
            return True
        choice = self._ask_unsaved_changes(action)
        if choice == "cancel":
            return False
        if choice == "save":
            return self.save_project()
        self.working_draft_store.clear()
        return True

    def _ask_unsaved_changes(self, action: str) -> str:
        project_name = (
            self.project_name_var.get().strip()
            or self.active_project_name
            or "this project"
        )
        dialog = UnsavedChangesDialog(self, project_name, action)
        self.wait_window(dialog)
        return dialog.result or "cancel"

    def _autosave_working_draft(self) -> None:
        self.working_draft_after_id = None
        try:
            if self.analysis_running or not self._refresh_project_dirty_state():
                return
            fingerprint = self._current_project_fingerprint()
            if fingerprint == self._last_draft_fingerprint:
                return
            form_values = self._project_form_values()
            notes = self.project_notes_text.get("1.0", "end-1c")
            comparison_results = self._comparison_results_to_frame()
            self.working_draft_store.save(
                self.config_model,
                self.rainfall_df,
                self.curve_df,
                self.results_df,
                comparison_results,
                self.hourly_results_df,
                project_file_path=self.project_file_path,
                baseline_fingerprint=self._saved_state_fingerprint,
                form_values=form_values,
                notes=notes,
            )
            self._last_draft_fingerprint = self._current_project_fingerprint()
        except Exception as exc:  # noqa: BLE001
            self.execution_log.warning(
                "Project",
                "Could not update the working recovery draft",
                details=str(exc),
            )
        finally:
            if self.winfo_exists():
                self.working_draft_after_id = self.after(
                    WORKING_DRAFT_SAVE_MS, self._autosave_working_draft
                )

    def _offer_working_draft_recovery(self) -> None:
        restore = messagebox.askyesno(
            APP_TITLE,
            "Unsaved work was found from an interrupted session.\n\n"
            "Restore the working draft? Choose No to discard it.",
            parent=self,
        )

        if not restore:
            self.working_draft_store.clear()
            return
        try:
            draft = self.working_draft_store.load()
            source_path = Path(draft.metadata.project_file_path)
            if source_path.is_file():
                self.project_file_path = source_path
                self.store = SQLiteStore(
                    str(source_path),
                    backup_dir=project_backup_dir(
                        source_path, data_dir=self.application_data_dir
                    ),
                )
                self._load_project_list()
                self._refresh_system_template_library()
            self.config_model = draft.config
            self.rainfall_df = draft.rainfall_df
            self.curve_df = draft.curve_df
            self.results_df = draft.results_df
            self.hourly_results_df = draft.hourly_results_df
            self.comparison_results = self._comparison_results_from_frame(
                draft.comparison_results_df
            )
            self.current_rainfall_csv_path = None
            self.rainfall_source_label = self.config_model.rainfall_source_label
            self._clear_results()
            self._populate_from_model()
            self._restore_project_form_values(
                draft.metadata.form_values, draft.metadata.notes
            )
            self._set_active_project(self.config_model.name)
            if not self.results_df.empty and not self.curve_df.empty:
                self._populate_results()
                self.after_idle(self._draw_saved_analysis_charts)
            self._saved_state_fingerprint = (
                draft.metadata.baseline_fingerprint or "pre-recovery-state"
            )
            if self._current_project_fingerprint() == self._saved_state_fingerprint:
                self._saved_state_fingerprint = "pre-recovery-state"
            self._last_draft_fingerprint = self._current_project_fingerprint()
            self._refresh_project_dirty_state()
            self.status_var.set("Recovered unsaved work from the interrupted session")
            self.execution_log.info("Project", "Recovered unsaved working draft")
        except Exception as exc:  # noqa: BLE001
            self.working_draft_store.clear()
            self.execution_log.error(
                "Project", "Could not recover the working draft", exception=exc
            )
            messagebox.showwarning(
                APP_TITLE,
                f"The unsaved working draft could not be recovered and was discarded:\n{exc}",
                parent=self,
            )

    def request_exit(self) -> None:
        if self.analysis_running:
            messagebox.showinfo(
                APP_TITLE,
                "Wait for the active analysis or optimization to finish before exiting.",
                parent=self,
            )
            return
        if not self._confirm_project_replacement("exiting"):
            return
        self.working_draft_store.clear()
        if self.project_state_poll_after_id is not None:
            self.after_cancel(self.project_state_poll_after_id)
        if self.working_draft_after_id is not None:
            self.after_cancel(self.working_draft_after_id)
        self.destroy()

    def _set_active_project(self, project_name: str | None) -> None:
        self.active_example_id = None
        self.active_project_name = project_name.strip() if project_name and project_name.strip() else None
        self._update_project_state_display()

    def auto_set_graph_step(self) -> None:
        self.config_model.unit_system = normalize_unit_system(self.unit_var.get())
        cfg = self.config_model
        start_gal = volume_to_internal(_float(self.graph_start_var.get(), 500), cfg)
        end_gal = volume_to_internal(_float(self.graph_end_var.get(), 20000), cfg)
        if end_gal <= start_gal:
            messagebox.showwarning(APP_TITLE, "Graph end tank size must be greater than graph start tank size.")
            return

        step_count = int(_float(self.graph_auto_step_count_var.get(), 20))
        if step_count < 1:
            messagebox.showwarning(APP_TITLE, "Number of graph steps must be at least 1.")
            return
        self.graph_auto_step_count_var.set(str(step_count))
        cfg.graph_auto_step_count = step_count
        step_gal = (end_gal - start_gal) / step_count
        step_display = max(1.0, volume_to_display(step_gal, cfg))
        self.graph_step_var.set(format_number(step_display, cfg, max_decimal_places=0))
        self.status_var.set(
            f"Auto-set graph step to {format_number(step_display, cfg, max_decimal_places=0)} "
            f"{volume_unit(cfg)} for {format_number(step_count, cfg, max_decimal_places=0)} steps"
        )

    def new_project(self) -> None:
        if self.analysis_running:
            messagebox.showinfo(APP_TITLE, "Wait for the active analysis or optimization to finish before replacing the project.")
            return
        if not self._confirm_project_replacement("creating a new project"):
            return
        self.execution_log.info("Project", "Creating a new project")
        self._set_active_project(None)
        self._reset_weather_selection()
        self.config_model = default_project_config()
        self.rainfall_df = pd.DataFrame(columns=["Date", "Precipitation"])
        self.current_rainfall_csv_path = None
        self.rainfall_source_label = None
        self.config_model.rainfall_source_label = None
        self.results_df = pd.DataFrame()
        self.curve_df = pd.DataFrame()
        self.hourly_results_df = pd.DataFrame()
        self.comparison_results = {}
        self.reliability_var.set("Reliability: --")
        self._clear_results()
        self._populate_from_model()
        self._accept_current_project_state()
        self.status_var.set("Started a new project")
        self.execution_log.info("Project", "New project ready")

    def load_example_project(self, example_id: str) -> None:
        """Open a fresh built-in example with a completed analysis."""
        if self.analysis_running:
            messagebox.showinfo(
                APP_TITLE,
                "Wait for the active analysis or optimization to finish before loading an example.",
            )
            return
        if not self._confirm_project_replacement("loading an example project"):
            return
        label = EXAMPLE_PROJECT_LABELS.get(example_id, example_id)
        try:
            self._set_progress(
                15,
                f"Loading example: {label}",
                "OpenProject.Horizontal.TProgressbar",
            )
            example = build_completed_example(example_id)
            self.config_model = example.config
            self.rainfall_df = example.rainfall
            self.curve_df = example.outcome.curve
            self.results_df = example.outcome.selected_tank
            self.hourly_results_df = example.outcome.hourly_selected_tank
            self.comparison_results = example.outcome.comparison_tanks
            self.current_rainfall_csv_path = None
            self.rainfall_source_label = self.config_model.rainfall_source_label
            self._clear_results()
            self._populate_from_model()
            self._reset_weather_selection()
            self._set_active_project(None)
            self.active_example_id = example_id
            reliability = float(self.results_df["ReliabilityPercent"].iloc[0])
            self._set_selected_tank_reliability(reliability)
            self._populate_results()
            self.after_idle(self._draw_saved_analysis_charts)
            self._accept_current_project_state()
            self._set_progress(
                100,
                f"Loaded example '{label}' with completed simulation",
                "OpenProject.Horizontal.TProgressbar",
            )
            self.execution_log.info(
                "Project", f"Loaded built-in example '{label}' with completed simulation"
            )
        except Exception as exc:  # noqa: BLE001
            self.analysis_progress_var.set(0)
            self.status_var.set("Could not load example")
            self.execution_log.error("Project", "Could not load example", exception=exc)
            messagebox.showerror(APP_TITLE, f"Could not load the example project:\n{exc}")

    def close_project(self) -> None:
        if self.analysis_running:
            messagebox.showinfo(APP_TITLE, "Wait for the active analysis or optimization to finish before closing the project.")
            return
        if not self._confirm_project_replacement("closing the project"):
            return
        self.execution_log.info("Project", "Closing the current project")
        self._set_active_project(None)
        self._reset_weather_selection()
        self.config_model = default_project_config()
        self.project_name_var.set("")
        self.saved_project_var.set("")
        self.rainfall_df = pd.DataFrame(columns=["Date", "Precipitation"])
        self.current_rainfall_csv_path = None
        self.rainfall_source_label = None
        self.config_model.rainfall_source_label = None
        self.results_df = pd.DataFrame()
        self.curve_df = pd.DataFrame()
        self.hourly_results_df = pd.DataFrame()
        self.comparison_results = {}
        self.rainfall_summary_var.set("No rainfall file loaded")
        self.reliability_var.set("Reliability: --")
        self.analysis_progress_var.set(0)
        self._clear_results()
        self._populate_from_model()
        self.project_name_var.set("")
        self.saved_project_var.set("")
        self._accept_current_project_state()
        self.status_var.set("Closed project")
        self.execution_log.info("Project", "Project closed")

    def load_selected_project(self, *, confirm_unsaved: bool = True) -> None:
        if self.analysis_running:
            messagebox.showinfo(APP_TITLE, "Wait for the active analysis or optimization to finish before loading another project.")
            return
        name = self.saved_project_var.get()
        if not name:
            messagebox.showinfo(APP_TITLE, "Select a saved project first.")
            return
        if confirm_unsaved and not self._confirm_project_replacement(
            "loading another project"
        ):
            return
        try:
            self.execution_log.info("Project", "Loading selected project")
            self.config_model, self.rainfall_df, self.curve_df, self.results_df = self.store.load_project_with_analysis(name)
            if (
                not self.results_df.empty
                and not self.curve_df.empty
                and not self.config_model.analysis_input_signature
            ):
                self.config_model.analysis_input_signature = analysis_input_signature(
                    self.config_model, self.rainfall_df
                )
            if not self.results_df.empty and not self.config_model.analysis_unit_system:
                self.config_model.analysis_unit_system = self.config_model.unit_system
            self.current_rainfall_csv_path = None
            self.rainfall_source_label = self.config_model.rainfall_source_label
            self._clear_results()
            self.hourly_results_df = self.store.load_hourly_results(name)
            comparison_frame = self.store.load_comparison_results(name)
            self.comparison_results = self._comparison_results_from_frame(comparison_frame)
            self._populate_from_model()
            self._reset_weather_selection()
            self._set_active_project(self.config_model.name)
            self._add_recent_project_path(self.project_file_path)
            if not self.results_df.empty and not self.curve_df.empty:
                reliability = float(self.results_df["ReliabilityPercent"].iloc[0])
                self._set_selected_tank_reliability(reliability)
                self._populate_results()
                self.after_idle(self._draw_saved_analysis_charts)
                self.status_var.set(f"Loaded project '{name}' with saved analysis")
            else:
                self.reliability_var.set("Reliability: --")
                self.status_var.set(f"Loaded project '{name}'")
            self._accept_current_project_state()
            self.execution_log.info(
                "Project", f"Project loaded with {len(self.rainfall_df):,} rainfall rows"
            )
        except Exception as exc:  # noqa: BLE001
            self.execution_log.error("Project", "Could not load selected project", exception=exc)
            messagebox.showerror(APP_TITLE, f"Could not load project:\n{exc}")

    def open_project_from(self) -> None:
        path = filedialog.askopenfilename(
            title="Open project...",
            initialdir=str(Path.home()),
            filetypes=[("Rainwater project files", "*.db"), ("SQLite database files", "*.sqlite *.sqlite3"), ("All files", "*.*")],
        )
        if not path:
            return
        self._open_project_file(Path(path))

    def open_recent_project(self, path_text: str) -> None:
        self._open_project_file(Path(path_text))

    def open_most_recent_project(self) -> None:
        missing_paths: list[str] = []
        for path_text in self.recent_project_paths:
            if Path(path_text).is_file():
                if missing_paths:
                    self.recent_project_paths = [
                        path for path in self.recent_project_paths if path not in missing_paths
                    ]
                    self._save_recent_project_paths()
                    self._refresh_recent_projects_menu()
                self.open_recent_project(path_text)
                return
            missing_paths.append(path_text)
        if missing_paths:
            self.recent_project_paths = []
            self._save_recent_project_paths()
            self._refresh_recent_projects_menu()
        messagebox.showinfo(APP_TITLE, "No recently opened project is available.")

    def clear_recent_projects(self) -> None:
        self.recent_project_paths = []
        self._save_recent_project_paths()
        self._refresh_recent_projects_menu()
        self.status_var.set("Cleared recent projects")

    def _open_project_file(self, selected_path: Path) -> None:
        if self.analysis_running:
            messagebox.showinfo(APP_TITLE, "Wait for the active analysis or optimization to finish before opening another project.")
            return
        if not self._confirm_project_replacement("opening another project file"):
            return
        previous_path = self.project_file_path
        previous_store = self.store
        try:
            self.execution_log.info("Project", f"Opening project file {selected_path.name}")
            self._set_progress(5, "Opening project: checking file", "OpenProject.Horizontal.TProgressbar")
            if not selected_path.exists():
                self.analysis_progress_var.set(0)
                messagebox.showinfo(APP_TITLE, "That project file no longer exists.")
                self.recent_project_paths = [
                    existing for existing in self.recent_project_paths if existing.casefold() != str(selected_path).casefold()
                ]
                self._save_recent_project_paths()
                self._refresh_recent_projects_menu()
                return
            self._set_progress(25, "Opening project: reading project file", "OpenProject.Horizontal.TProgressbar")
            selected_store = SQLiteStore(
                str(selected_path),
                backup_dir=project_backup_dir(
                    selected_path, data_dir=self.application_data_dir
                ),
            )
            projects = selected_store.list_projects()
            if not projects:
                self.analysis_progress_var.set(0)
                messagebox.showinfo(APP_TITLE, "No saved projects were found in that file.")
                return

            self._set_progress(50, "Opening project: loading project data", "OpenProject.Horizontal.TProgressbar")
            self.project_file_path = selected_path
            self.store = selected_store
            if selected_store.recovery_notice:
                messagebox.showwarning(
                    APP_TITLE, selected_store.recovery_notice, parent=self
                )
            self._refresh_system_template_library()
            self.saved_project_var.set(projects[0])
            self._load_project_list()
            self.load_selected_project(confirm_unsaved=False)
            self._set_progress(85, "Opening project: refreshing views", "OpenProject.Horizontal.TProgressbar")
            self._add_recent_project_path(self.project_file_path)
            self._set_progress(100, f"Opened project '{self.config_model.name}' from {self.project_file_path}", "OpenProject.Horizontal.TProgressbar")
            self.execution_log.info("Project", f"Opened project file {selected_path.name}")
        except Exception as exc:  # noqa: BLE001
            self.project_file_path = previous_path
            self.store = previous_store
            self._load_project_list()
            self._refresh_system_template_library()
            self.analysis_progress_var.set(0)
            self.execution_log.error("Project", "Could not open project file", exception=exc)
            messagebox.showerror(APP_TITLE, f"Could not open project file:\n{exc}")

    def save_project(self) -> bool:
        if self.active_example_id is not None:
            return self.save_project_as()
        self._apply_form_to_model()
        return self._save_current_project()

    def save_project_as(self) -> bool:
        self._apply_form_to_model()
        path = filedialog.asksaveasfilename(
            title="Save project as...",
            initialdir=str(self.project_file_path.parent),
            initialfile=_safe_project_file_name(self.config_model.name),
            defaultextension=".db",
            filetypes=[("Rainwater project files", "*.db"), ("SQLite database files", "*.sqlite *.sqlite3"), ("All files", "*.*")],
        )
        if not path:
            return False
        name = simpledialog.askstring(
            APP_TITLE,
            "Project name",
            initialvalue=self.config_model.name,
            parent=self,
        )
        if name is None:
            return False
        name = name.strip()
        if not name:
            messagebox.showwarning(APP_TITLE, "Project name cannot be blank.")
            return False
        self.project_file_path = Path(path)
        self.store = SQLiteStore(
            str(self.project_file_path),
            backup_dir=project_backup_dir(
                self.project_file_path, data_dir=self.application_data_dir
            ),
        )
        self._refresh_system_template_library()
        self.config_model.name = name
        self.project_name_var.set(name)
        return self._save_current_project()

    def _save_current_project(self) -> bool:
        self.config_model.rainfall_source_label = self.rainfall_source_label
        try:
            self.execution_log.info("Project", "Saving current project")
            self._set_progress(15, "Saving project: preparing data", "SaveProject.Horizontal.TProgressbar")
            comparison_results = self._comparison_results_to_frame()
            self._set_progress(45, "Saving project: writing project file", "SaveProject.Horizontal.TProgressbar")
            self.store.save_project(
                self.config_model,
                self.rainfall_df,
                self.curve_df,
                self.results_df,
                comparison_results,
                self.hourly_results_df,
            )
            self._set_progress(85, "Saving project: refreshing project information", "SaveProject.Horizontal.TProgressbar")
            self._load_project_list()
            self.saved_project_var.set(self.config_model.name)
            self._set_active_project(self.config_model.name)
            self._add_recent_project_path(self.project_file_path)
            self._set_progress(
                100,
                f"Saved project '{self.config_model.name}' to {self.project_file_path}",
                "SaveProject.Horizontal.TProgressbar",
            )
            self.execution_log.info("Project", f"Saved project file {self.project_file_path.name}")
            self._accept_current_project_state()
            if self.store.last_backup_error:
                self.execution_log.warning(
                    "Project",
                    "Project saved, but the automatic backup failed",
                    details=self.store.last_backup_error,
                )
                messagebox.showwarning(
                    APP_TITLE,
                    "The project was saved, but its automatic backup failed:\n"
                    f"{self.store.last_backup_error}",
                    parent=self,
                )
            return True
        except Exception as exc:  # noqa: BLE001
            self.analysis_progress_var.set(0)
            self.status_var.set("Project save failed")
            self.execution_log.error("Project", "Project save failed", exception=exc)
            messagebox.showerror(APP_TITLE, f"Could not save project:\n{exc}")
            return False

    def _comparison_results_to_frame(self) -> pd.DataFrame:
        frames = []
        for tank_size, results in sorted(self.comparison_results.items()):
            if results.empty:
                continue
            frame = results.copy()
            frame["ComparisonTankSizeGallons"] = float(tank_size)
            frames.append(frame)
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    @staticmethod
    def _comparison_results_from_frame(frame: pd.DataFrame) -> dict[float, pd.DataFrame]:
        if frame.empty or "ComparisonTankSizeGallons" not in frame:
            return {}
        return {
            float(tank_size): rows.drop(columns=["ComparisonTankSizeGallons"]).reset_index(drop=True)
            for tank_size, rows in frame.groupby("ComparisonTankSizeGallons", sort=True)
        }

    def _set_rainfall_provenance(
        self,
        *,
        data_type: str,
        temporal_resolution: str,
        timezone: str,
        timing_type: str,
        known_missing_dates: object = (),
    ) -> None:
        cfg = self.config_model
        cfg.rainfall_data_type = data_type
        cfg.rainfall_temporal_resolution = temporal_resolution
        cfg.rainfall_timezone = timezone
        cfg.rainfall_timing_type = timing_type
        cfg.rainfall_retrieved_at = dt.datetime.now().astimezone().isoformat(
            timespec="seconds"
        )
        cfg.rainfall_known_missing_dates = [
            str(value) for value in (known_missing_dates or [])
        ]
        self.rainfall_data_type_var.set(rainfall_data_type_label(data_type))
        self.rainfall_resolution_var.set(
            RAINFALL_RESOLUTION_LABELS.get(temporal_resolution, "Unknown")
        )
        self.rainfall_timezone_var.set(timezone)
        self.rainfall_timing_var.set(timing_type)

    @staticmethod
    def _rainfall_quick_access_label(path_text: str) -> str:
        path = Path(path_text)
        return f"{path.name}  —  {path.parent}"

    def _refresh_rainfall_quick_access_menu(self) -> None:
        menu = self.rainfall_quick_access_menu
        menu.delete(0, tk.END)

        menu.add_command(label="Recent daily rainfall CSVs", state="disabled")
        if self.recent_rainfall_csv_paths:
            for path_text in self.recent_rainfall_csv_paths:
                menu.add_command(
                    label=self._rainfall_quick_access_label(path_text),
                    command=lambda value=path_text: self._load_rainfall_csv_path(value),
                )
        else:
            menu.add_command(label="No recent files", state="disabled")

        menu.add_separator()
        pinned_menu = tk.Menu(menu, tearoff=False)
        if not self.pinned_rainfall_csv_paths:
            pinned_menu.add_command(label="No pinned files", state="disabled")
        elif len(self.pinned_rainfall_csv_paths) <= PINNED_RAINFALL_MENU_GROUP_SIZE:
            self._add_rainfall_paths_to_menu(
                pinned_menu, self.pinned_rainfall_csv_paths
            )
        else:
            for start in range(
                0, len(self.pinned_rainfall_csv_paths), PINNED_RAINFALL_MENU_GROUP_SIZE
            ):
                group = self.pinned_rainfall_csv_paths[
                    start : start + PINNED_RAINFALL_MENU_GROUP_SIZE
                ]
                group_menu = tk.Menu(pinned_menu, tearoff=False)
                self._add_rainfall_paths_to_menu(group_menu, group)
                pinned_menu.add_cascade(
                    label=f"Files {start + 1}–{start + len(group)}", menu=group_menu
                )
        menu.add_cascade(
            label=f"Pinned files ({len(self.pinned_rainfall_csv_paths):,}/"
            f"{MAX_PINNED_RAINFALL_CSVS:,})",
            menu=pinned_menu,
        )
        menu.add_separator()
        menu.add_command(label="Pin CSV files...", command=self.pin_rainfall_csv_files)
        current_is_pinned = self._rainfall_path_is_pinned(
            self.current_rainfall_csv_path
        )
        if current_is_pinned:
            menu.add_command(
                label="Unpin current CSV", command=self.unpin_current_rainfall_csv
            )
        else:
            menu.add_command(
                label="Pin current CSV",
                command=self.pin_current_rainfall_csv,
                state="normal" if self.current_rainfall_csv_path else "disabled",
            )
        menu.add_command(
            label="Manage pinned files...", command=self.manage_pinned_rainfall_csvs
        )
        menu.add_command(
            label="Remove missing entries", command=self.remove_missing_rainfall_csv_entries
        )
        menu.add_command(label="Clear recent files", command=self.clear_recent_rainfall_csvs)

    def _add_rainfall_paths_to_menu(
        self, menu: tk.Menu, paths: list[str]
    ) -> None:
        for path_text in paths:
            menu.add_command(
                label=self._rainfall_quick_access_label(path_text),
                command=lambda value=path_text: self._load_rainfall_csv_path(value),
            )

    def _open_rainfall_quick_access_on_hover(self, _event: tk.Event) -> None:
        self._refresh_rainfall_quick_access_menu()
        button = self.rainfall_quick_access_button
        try:
            self.rainfall_quick_access_menu.post(
                button.winfo_rootx(), button.winfo_rooty() + button.winfo_height()
            )
        except tk.TclError:
            pass

    def _rainfall_path_is_pinned(self, path_text: str | None) -> bool:
        if not path_text:
            return False
        identity = path_text.casefold()
        return any(path.casefold() == identity for path in self.pinned_rainfall_csv_paths)

    def _remember_recent_rainfall_csv(self, path: Path) -> None:
        path_text = str(path.expanduser().resolve(strict=False))
        identity = path_text.casefold()
        self.recent_rainfall_csv_paths = [
            item for item in self.recent_rainfall_csv_paths
            if item.casefold() != identity
        ]
        self.recent_rainfall_csv_paths.insert(0, path_text)
        self.recent_rainfall_csv_paths = self.recent_rainfall_csv_paths[
            :MAX_RECENT_RAINFALL_CSVS
        ]
        self._save_app_preferences()
        self._refresh_rainfall_quick_access_menu()

    def pin_rainfall_csv_files(self) -> None:
        paths = filedialog.askopenfilenames(
            title="Pin rainfall CSV files",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if not paths:
            return
        added = 0
        skipped = 0
        for raw_path in paths:
            if len(self.pinned_rainfall_csv_paths) >= MAX_PINNED_RAINFALL_CSVS:
                skipped += 1
                continue
            path = Path(raw_path).expanduser().resolve(strict=False)
            if path.suffix.casefold() != ".csv" or not path.is_file():
                skipped += 1
                continue
            path_text = str(path)
            if self._rainfall_path_is_pinned(path_text):
                skipped += 1
                continue
            self.pinned_rainfall_csv_paths.append(path_text)
            added += 1
        self._save_app_preferences()
        self._refresh_rainfall_quick_access_menu()
        self.status_var.set(f"Pinned {added:,} rainfall CSV file(s)")
        if skipped:
            messagebox.showinfo(
                APP_TITLE,
                f"Pinned {added:,} file(s). Skipped {skipped:,} duplicate, invalid, "
                f"or over-limit file(s).",
                parent=self,
            )

    def pin_current_rainfall_csv(self) -> None:
        if not self.current_rainfall_csv_path:
            return
        if len(self.pinned_rainfall_csv_paths) >= MAX_PINNED_RAINFALL_CSVS:
            messagebox.showinfo(
                APP_TITLE,
                f"Quick Access already contains the maximum of "
                f"{MAX_PINNED_RAINFALL_CSVS:,} pinned files.",
                parent=self,
            )
            return
        if not self._rainfall_path_is_pinned(self.current_rainfall_csv_path):
            self.pinned_rainfall_csv_paths.append(self.current_rainfall_csv_path)
            self._save_app_preferences()
            self._refresh_rainfall_quick_access_menu()
            self.status_var.set(f"Pinned rainfall CSV: {Path(self.current_rainfall_csv_path).name}")

    def unpin_current_rainfall_csv(self) -> None:
        if not self.current_rainfall_csv_path:
            return
        identity = self.current_rainfall_csv_path.casefold()
        self.pinned_rainfall_csv_paths = [
            item for item in self.pinned_rainfall_csv_paths
            if item.casefold() != identity
        ]
        self._save_app_preferences()
        self._refresh_rainfall_quick_access_menu()

    def clear_recent_rainfall_csvs(self) -> None:
        self.recent_rainfall_csv_paths = []
        self._save_app_preferences()
        self._refresh_rainfall_quick_access_menu()
        self.status_var.set("Cleared recent rainfall CSV files")

    def remove_missing_rainfall_csv_entries(self) -> None:
        recent_before = len(self.recent_rainfall_csv_paths)
        pinned_before = len(self.pinned_rainfall_csv_paths)
        self.recent_rainfall_csv_paths = [
            path for path in self.recent_rainfall_csv_paths if Path(path).is_file()
        ]
        self.pinned_rainfall_csv_paths = [
            path for path in self.pinned_rainfall_csv_paths if Path(path).is_file()
        ]
        removed = (
            recent_before - len(self.recent_rainfall_csv_paths)
            + pinned_before - len(self.pinned_rainfall_csv_paths)
        )
        self._save_app_preferences()
        self._refresh_rainfall_quick_access_menu()
        self.status_var.set(f"Removed {removed:,} missing Quick Access entry/entries")

    def manage_pinned_rainfall_csvs(self) -> None:
        window = tk.Toplevel(self)
        window.title("Manage pinned rainfall CSV files")
        window.geometry("820x480")
        window.minsize(560, 300)
        window.transient(self)
        window.columnconfigure(0, weight=1)
        window.rowconfigure(1, weight=1)
        pinned_count_var = tk.StringVar()
        ttk.Label(
            window,
            textvariable=pinned_count_var,
            padding=(10, 10, 10, 6),
        ).grid(row=0, column=0, sticky="w")
        list_frame = ttk.Frame(window, padding=(10, 0))
        list_frame.grid(row=1, column=0, sticky="nsew")
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)
        file_list = tk.Listbox(list_frame, selectmode=tk.EXTENDED)
        file_list.grid(row=0, column=0, sticky="nsew")
        y_scroll = ttk.Scrollbar(list_frame, orient="vertical", command=file_list.yview)
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll = ttk.Scrollbar(list_frame, orient="horizontal", command=file_list.xview)
        x_scroll.grid(row=1, column=0, sticky="ew")
        file_list.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)
        def refresh_file_list() -> None:
            file_list.delete(0, tk.END)
            for path_text in self.pinned_rainfall_csv_paths:
                file_list.insert(tk.END, path_text)
            pinned_count_var.set(
                f"Pinned files ({len(self.pinned_rainfall_csv_paths):,}/"
                f"{MAX_PINNED_RAINFALL_CSVS:,})"
            )

        refresh_file_list()

        def remove_selected() -> None:
            selected = list(file_list.curselection())
            if not selected:
                return
            for index in reversed(selected):
                del self.pinned_rainfall_csv_paths[index]
            self._save_app_preferences()
            self._refresh_rainfall_quick_access_menu()
            refresh_file_list()

        def load_selected() -> None:
            selected = file_list.curselection()
            if not selected:
                return
            path_text = self.pinned_rainfall_csv_paths[selected[0]]
            window.destroy()
            self._load_rainfall_csv_path(path_text)

        def add_files() -> None:
            self.pin_rainfall_csv_files()
            refresh_file_list()

        controls = ttk.Frame(window, padding=10)
        controls.grid(row=2, column=0, sticky="ew")
        ttk.Button(controls, text="Load selected", command=load_selected).pack(side="left")
        ttk.Button(controls, text="Remove selected", command=remove_selected).pack(
            side="left", padx=(6, 0)
        )
        ttk.Button(controls, text="Add files...", command=add_files).pack(
            side="left", padx=(6, 0)
        )
        ttk.Button(controls, text="Close", command=window.destroy).pack(side="right")

    def save_rainfall_csv(self) -> None:
        if self.rainfall_df.empty:
            messagebox.showinfo(
                APP_TITLE, "Load or import precipitation data before saving a CSV.", parent=self
            )
            return
        self._apply_form_to_model()
        source_stem = (
            Path(self.current_rainfall_csv_path).stem
            if self.current_rainfall_csv_path
            else _safe_project_file_name(self.config_model.name).replace(".db", "")
        )
        path = filedialog.asksaveasfilename(
            title="Save daily rainfall CSV",
            initialfile=f"{source_stem}_rainfall.csv",
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            export = self.rainfall_df[["Date", "Precipitation"]].copy()
            export["Date"] = pd.to_datetime(export["Date"]).dt.strftime("%Y-%m-%d")
            export["Precipitation"] = export["Precipitation"].map(
                lambda value: precip_to_display(float(value), self.config_model)
            )
            export.to_csv(path, index=False, quoting=csv.QUOTE_MINIMAL)
            self.status_var.set(
                f"Saved rainfall CSV ({precip_unit(self.config_model)}): {Path(path).name}"
            )
            self.execution_log.info(
                "Rainfall", f"Saved {len(export):,} daily rainfall rows to {Path(path).name}"
            )
        except Exception as exc:  # noqa: BLE001
            self.execution_log.error("Rainfall", "Could not save rainfall CSV", exception=exc)
            messagebox.showerror(
                APP_TITLE, f"Could not save rainfall CSV:\n{exc}", parent=self
            )

    def load_rainfall_csv(self) -> None:
        self._apply_form_to_model()
        path = filedialog.askopenfilename(
            title="Load rainfall CSV",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if not path:
            return
        self._load_rainfall_csv_path(path)

    def _load_rainfall_csv_path(self, path: str | Path) -> None:
        self._apply_form_to_model()
        csv_path = Path(path).expanduser().resolve(strict=False)
        try:
            self.execution_log.info("Rainfall", f"Loading rainfall CSV {csv_path.name}")
            raw = csv_path.read_bytes()
            rainfall = load_rainfall_csv(raw)
            rainfall["Precipitation"] = rainfall["Precipitation"].map(lambda v: precip_to_internal(float(v), self.config_model))
            self.rainfall_df = rainfall
            self.use_synthetic_hourly_rainfall_var.set(False)
            self.config_model.use_synthetic_hourly_rainfall = False
            self.current_rainfall_csv_path = str(csv_path)
            self._remember_recent_rainfall_csv(csv_path)
            self.rainfall_source_label = f"CSV file: {csv_path.name}"
            self.config_model.rainfall_source_label = self.rainfall_source_label
            self._set_rainfall_provenance(
                data_type="unclassified",
                temporal_resolution="daily",
                timezone="Unspecified",
                timing_type="Daily totals; within-day timing not observed",
                known_missing_dates=rainfall.attrs.get("known_missing_dates", []),
            )
            self.config_model.weather_station_latitude = None
            self.config_model.weather_station_longitude = None
            self.curve_df = pd.DataFrame()
            self.results_df = pd.DataFrame()
            self.reliability_var.set("Reliability: --")
            self._clear_results()
            self._reset_weather_selection()
            self._update_rainfall_summary()
            self.status_var.set(f"Loaded rainfall CSV: {csv_path.name}")
            self.execution_log.info(
                "Rainfall", f"Loaded {len(self.rainfall_df):,} rainfall rows from CSV"
            )
        except Exception as exc:  # noqa: BLE001
            self.execution_log.error("Rainfall", "Could not load rainfall CSV", exception=exc)
            messagebox.showerror(APP_TITLE, f"Could not load rainfall CSV:\n{exc}")

    def load_hourly_rainfall_csv(self) -> None:
        """Load observed hourly rainfall and retain its within-day timing."""
        self._apply_form_to_model()
        path = filedialog.askopenfilename(
            title="Load hourly rainfall CSV",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            self.execution_log.info("Rainfall", f"Loading hourly rainfall CSV {Path(path).name}")
            rainfall = load_hourly_rainfall_csv(Path(path).read_bytes())
            rainfall["Precipitation"] = rainfall["Precipitation"].map(
                lambda value: precip_to_internal(float(value), self.config_model)
            )
            for column in HOURLY_PRECIPITATION_COLUMNS:
                rainfall[column] = rainfall[column].map(
                    lambda value: precip_to_internal(float(value), self.config_model)
                )
            self.rainfall_df = rainfall
            self.use_synthetic_hourly_rainfall_var.set(False)
            self.config_model.use_synthetic_hourly_rainfall = False
            self.current_rainfall_csv_path = None
            self.rainfall_source_label = f"Hourly CSV file: {Path(path).name}"
            self.config_model.rainfall_source_label = self.rainfall_source_label
            self._set_rainfall_provenance(
                data_type="unclassified",
                temporal_resolution="hourly",
                timezone="Unspecified",
                timing_type="Observed hourly rainfall",
                known_missing_dates=rainfall.attrs.get("known_missing_dates", []),
            )
            self.config_model.weather_station_latitude = None
            self.config_model.weather_station_longitude = None
            self.curve_df = pd.DataFrame()
            self.results_df = pd.DataFrame()
            self.reliability_var.set("Reliability: --")
            self._clear_results()
            self._reset_weather_selection()
            self._update_rainfall_summary()
            self.status_var.set(f"Loaded hourly rainfall CSV: {Path(path).name}")
            self.execution_log.info(
                "Rainfall", f"Loaded {len(self.rainfall_df):,} daily rainfall rows from hourly CSV"
            )
        except Exception as exc:  # noqa: BLE001
            self.execution_log.error("Rainfall", "Could not load hourly rainfall CSV", exception=exc)
            messagebox.showerror(APP_TITLE, f"Could not load hourly rainfall CSV:\n{exc}")

    def generate_hourly_rainfall(self) -> None:
        """Generate reproducible hourly hyetographs from the loaded daily record."""
        if self.rainfall_df.empty:
            messagebox.showinfo(
                APP_TITLE, "Load or import daily rainfall before generating hourly data."
            )
            return
        previous_seed = re.search(
            r"\(seed (\d+)\)", self.config_model.rainfall_timing_type
        )
        seed = simpledialog.askinteger(
            APP_TITLE,
            "Random seed for reproducible Hyetos-style hourly rainfall:",
            initialvalue=int(previous_seed.group(1)) if previous_seed else 1,
            minvalue=0,
            parent=self,
        )
        if seed is None:
            return
        try:
            self.rainfall_df = disaggregate_daily_rainfall_hyetos(
                self.rainfall_df, seed=seed
            )
            self.use_synthetic_hourly_rainfall_var.set(True)
            self.config_model.use_synthetic_hourly_rainfall = True
            self.config_model.rainfall_timing_type = (
                "Synthetic hourly timing derived from daily totals using a "
                f"Hyetos-style profile (seed {seed})"
            )
            self.rainfall_timing_var.set(self.config_model.rainfall_timing_type)
            self.curve_df = pd.DataFrame()
            self.results_df = pd.DataFrame()
            self.reliability_var.set("Reliability: --")
            self._clear_results()
            self._update_rainfall_summary()
            self.status_var.set(
                f"Generated Hyetos-style hourly rainfall using random seed {seed}"
            )
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(APP_TITLE, f"Could not generate hourly rainfall:\n{exc}")

    def open_hourly_rainwater_tab(self) -> None:
        self.rainwater_data_notebook.select(self.hourly_rainwater_tab)

    def remove_generated_hourly_rainfall(self) -> None:
        if not has_hourly_rainfall(self.rainfall_df):
            return
        if not messagebox.askyesno(
            APP_TITLE,
            "Remove the generated hourly profile?\n\n"
            "The imported daily rainfall totals will be retained.",
            parent=self,
        ):
            return
        self.rainfall_df = remove_hourly_rainfall(self.rainfall_df)
        self.use_synthetic_hourly_rainfall_var.set(False)
        self.config_model.use_synthetic_hourly_rainfall = False
        self.config_model.rainfall_timing_type = (
            "Observed daily totals; within-day timing not observed"
            if self.config_model.rainfall_data_type == "observed"
            else "Daily totals; within-day timing not observed"
        )
        self.rainfall_timing_var.set(self.config_model.rainfall_timing_type)
        self.curve_df = pd.DataFrame()
        self.results_df = pd.DataFrame()
        self.hourly_results_df = pd.DataFrame()
        self.reliability_var.set("Reliability: --")
        self._clear_results()
        self._update_rainfall_summary()
        self.status_var.set(
            "Removed the generated hourly profile; daily rainfall was retained"
        )

    def _refresh_hourly_profile_preview(self) -> None:
        if not hasattr(self, "hourly_profile_tree"):
            return
        tree = self.hourly_profile_tree
        tree.delete(*tree.get_children())
        tree.heading(
            "Precipitation",
            text=f"Record precipitation ({precip_unit(self.config_model)})",
        )
        self._wrap_treeview_headings(tree)
        if not has_hourly_rainfall(self.rainfall_df):
            self.hourly_profile_preview_var.set(
                "Generate a profile to preview its distribution by hour."
            )
            return
        hourly_totals = (
            self.rainfall_df.loc[:, HOURLY_PRECIPITATION_COLUMNS]
            .apply(pd.to_numeric, errors="coerce")
            .fillna(0.0)
            .clip(lower=0.0)
            .sum(axis=0)
        )
        record_total = float(hourly_totals.sum())
        for hour, column in enumerate(HOURLY_PRECIPITATION_COLUMNS):
            total = float(hourly_totals[column])
            share = 100.0 * total / record_total if record_total > 0.0 else 0.0
            tree.insert(
                "",
                "end",
                values=(
                    f"{hour:02d}:00-{(hour + 1) % 24:02d}:00",
                    format_number(precip_to_display(total, self.config_model), self.config_model, max_decimal_places=3),
                    format_number(share, self.config_model),
                ),
            )
        wet_hours = int((hourly_totals > 0.0).sum())
        self.hourly_profile_preview_var.set(
            f"Record-wide distribution across 24 clock hours; {wet_hours} hour bin(s) "
            "contain generated rainfall. Daily totals are conserved exactly."
        )

    def _multi_site_tab_mapped(self, _event: tk.Event | None = None) -> None:
        self.after_idle(self._start_climate_normal_catalog_load)

    def _refresh_climate_normal_archive_status(self) -> None:
        if not hasattr(self, "climate_normal_archive_status_var"):
            return
        archive_path = climate_normals_bulk_archive_path()
        installed = climate_normals_bulk_archive_installed()
        archive_size_mb = NCEI_BULK_ARCHIVE_SIZE_BYTES / 1_000_000
        if installed:
            self.climate_normal_archive_status_var.set(
                f"Installed ({format_number(archive_size_mb, self.config_model, max_decimal_places=1)} MB) as an offline fallback at "
                f"{archive_path}. Normal lookups use NOAA's per-station mirrors first."
            )
        else:
            self.climate_normal_archive_status_var.set(
                f"Not installed. Download the {format_number(archive_size_mb, self.config_model, max_decimal_places=1)} MB official NOAA "
                "1991-2020 annual/seasonal archive only if an offline fallback is needed."
            )
        if hasattr(self, "download_climate_normal_archive_button"):
            self.download_climate_normal_archive_button.configure(
                state="disabled" if installed or self.climate_normal_archive_in_progress else "normal"
            )
            self.remove_climate_normal_archive_button.configure(
                state="normal" if installed and not self.climate_normal_archive_in_progress else "disabled"
            )

    def download_climate_normal_archive(self) -> None:
        if self.climate_normal_archive_in_progress:
            return
        self.climate_normal_archive_in_progress = True
        self.climate_normal_archive_progress_var.set(0.0)
        self.climate_normal_archive_progress.grid()
        self.download_climate_normal_archive_button.configure(state="disabled")
        self.remove_climate_normal_archive_button.configure(state="disabled")
        self.climate_normal_archive_status_var.set(
            "Connecting to NOAA's public AWS archive mirror..."
        )
        threading.Thread(
            target=self._climate_normal_archive_download_worker,
            name="rwh-climate-normal-archive-download",
            daemon=True,
        ).start()
        self.climate_normal_archive_poll_after_id = self.after(
            100, self._poll_climate_normal_archive_download
        )

    def _climate_normal_archive_download_worker(self) -> None:
        def report_progress(downloaded: int, total: int) -> None:
            self.climate_normal_archive_queue.put(
                ("progress", downloaded, total)
            )

        try:
            path = download_climate_normals_bulk_archive(
                progress_callback=report_progress
            )
            self.climate_normal_archive_queue.put(("success", path))
        except Exception as exc:  # noqa: BLE001
            self.climate_normal_archive_queue.put(("error", str(exc)))

    def _poll_climate_normal_archive_download(self) -> None:
        self.climate_normal_archive_poll_after_id = None
        try:
            result = self.climate_normal_archive_queue.get_nowait()
        except queue.Empty:
            self.climate_normal_archive_poll_after_id = self.after(
                100, self._poll_climate_normal_archive_download
            )
            return
        while True:
            try:
                result = self.climate_normal_archive_queue.get_nowait()
            except queue.Empty:
                break

        if result[0] == "progress":
            downloaded, total = int(result[1]), max(int(result[2]), 1)
            percent = min(downloaded / total * 100.0, 100.0)
            self.climate_normal_archive_progress_var.set(percent)
            self.climate_normal_archive_status_var.set(
                f"Downloading NOAA archive: {format_number(downloaded / 1_000_000, self.config_model, max_decimal_places=1)} of "
                f"{format_number(total / 1_000_000, self.config_model, max_decimal_places=1)} MB ({format_number(percent, self.config_model, max_decimal_places=0)}%)."
            )
            self.climate_normal_archive_poll_after_id = self.after(
                100, self._poll_climate_normal_archive_download
            )
            return

        self.climate_normal_archive_in_progress = False
        self.climate_normal_archive_progress.grid_remove()
        if result[0] == "success":
            self.execution_log.info(
                "Climate normals", f"Installed NOAA bulk archive at {result[1]}."
            )
            self._refresh_climate_normal_archive_status()
            messagebox.showinfo(
                APP_TITLE,
                "The NOAA 1991-2020 Climate Normals archive is installed. "
                "It will be used only as an offline fallback after the direct "
                "per-station mirrors are unavailable.",
                parent=self,
            )
        else:
            self.execution_log.error(
                "Climate normals", f"Could not install the NOAA bulk archive: {result[1]}"
            )
            self._refresh_climate_normal_archive_status()
            messagebox.showerror(
                APP_TITLE,
                f"Could not download the NOAA Climate Normals archive:\n{result[1]}",
                parent=self,
            )

    def remove_climate_normal_archive(self) -> None:
        archive_path = climate_normals_bulk_archive_path()
        if not climate_normals_bulk_archive_installed():
            self._refresh_climate_normal_archive_status()
            return
        if not messagebox.askyesno(
            APP_TITLE,
            "Remove the optional NOAA Climate Normals bulk archive?\n\n"
            f"{archive_path}\n\n"
            "Previously cached individual station values will be retained. Future uncached "
            "lookups will use the online data source.",
            parent=self,
        ):
            return
        try:
            removed = remove_climate_normals_bulk_archive()
        except OSError as exc:
            messagebox.showerror(
                APP_TITLE, f"Could not remove the NOAA archive:\n{exc}", parent=self
            )
            return
        if removed:
            self.execution_log.info(
                "Climate normals", f"Removed NOAA bulk archive from {archive_path}."
            )
        self._refresh_climate_normal_archive_status()

    def _start_climate_normal_catalog_load(self) -> None:
        if self.climate_normal_catalog or self.climate_normal_lookup_in_progress:
            return
        self.climate_normal_lookup_in_progress = True
        self.climate_normal_status_var.set(
            "Loading NOAA 1991-2020 Climate Normals stations..."
        )
        threading.Thread(
            target=self._climate_normal_catalog_worker,
            name="rwh-climate-normal-catalog",
            daemon=True,
        ).start()
        self.climate_normal_poll_after_id = self.after(
            100, self._poll_climate_normal_catalog
        )

    def _climate_normal_catalog_worker(self) -> None:
        try:
            records = fetch_us_annual_precipitation_normal_catalog()
            self.climate_normal_queue.put(("success", records))
        except Exception as exc:  # noqa: BLE001
            self.climate_normal_queue.put(("error", str(exc)))

    def _poll_climate_normal_catalog(self) -> None:
        self.climate_normal_poll_after_id = None
        try:
            result, payload = self.climate_normal_queue.get_nowait()
        except queue.Empty:
            self.climate_normal_poll_after_id = self.after(
                100, self._poll_climate_normal_catalog
            )
            return

        self.climate_normal_lookup_in_progress = False
        if result == "error":
            self.climate_normal_status_var.set("Climate Normals station loading failed.")
            self.execution_log.error(
                "Climate normals", f"Could not load the station catalog: {payload}"
            )
            messagebox.showerror(
                APP_TITLE,
                f"Could not load NOAA Climate Normals stations:\n{payload}",
                parent=self,
            )
            return

        self.climate_normal_catalog = [dict(item) for item in payload]
        self.execution_log.info(
            "Climate normals",
            f"Loaded {len(self.climate_normal_catalog)} precipitation-normal stations.",
        )
        self._apply_climate_normal_station_filter(fit_map=False)

    def _climate_normal_search_focus_in(self, _event: tk.Event | None = None) -> None:
        if not self.climate_normal_search_placeholder_active:
            return
        self.climate_normal_search_placeholder_active = False
        self.climate_normal_query_var.set("")
        self.climate_normal_search_entry.configure(foreground="#1f2d33")

    def _climate_normal_search_focus_out(self, _event: tk.Event | None = None) -> None:
        if self.climate_normal_query_var.get().strip():
            return
        self.climate_normal_search_placeholder_active = True
        self.climate_normal_query_var.set("Find station by name")
        self.climate_normal_search_entry.configure(foreground="#7a858a")
        self._apply_climate_normal_station_filter(fit_map=False)

    def _climate_normal_search_changed(self, _event: tk.Event | None = None) -> None:
        if self.climate_normal_search_placeholder_active:
            return
        query = self.climate_normal_query_var.get().strip()
        if query:
            self.climate_normal_state_list.selection_clear(0, tk.END)
            self.climate_normal_state_list.configure(state=tk.DISABLED)
        else:
            self.climate_normal_state_list.configure(state=tk.NORMAL)
        self._apply_climate_normal_station_filter(fit_map=bool(query))

    def _climate_normal_state_selected(self, _event: tk.Event | None = None) -> None:
        if str(self.climate_normal_state_list.cget("state")) == str(tk.DISABLED):
            return
        self._apply_climate_normal_station_filter(fit_map=True)

    def _selected_climate_normal_state_code(self) -> str:
        selection = self.climate_normal_state_list.curselection()
        if not selection:
            return ""
        index = int(selection[0])
        return STATE_OPTIONS[index][0] if 0 <= index < len(STATE_OPTIONS) else ""

    def _climate_normal_name_query(self) -> str:
        if self.climate_normal_search_placeholder_active:
            return ""
        return self.climate_normal_query_var.get().strip()

    def _apply_climate_normal_station_filter(self, *, fit_map: bool) -> None:
        if not hasattr(self, "climate_normal_station_list"):
            return
        query = self._climate_normal_name_query()
        state_code = "" if query else self._selected_climate_normal_state_code()
        self.climate_normal_search_results = filter_climate_normal_stations(
            self.climate_normal_catalog,
            name_query=query,
            state_code=state_code,
        ) if (query or state_code) else []
        self.climate_normal_station_list.delete(0, tk.END)
        for record in self.climate_normal_search_results:
            self.climate_normal_station_list.insert(
                tk.END, self._climate_normal_station_label(record)
            )
        self.climate_normal_station_var.set("")
        self.add_climate_normal_button.configure(state="disabled")
        self.cancel_climate_normal_search_button.configure(state="disabled")
        if query:
            context = f'name containing "{query}" nationwide'
        elif state_code:
            context = STATE_NAME_BY_CODE.get(state_code, state_code)
        else:
            context = "the United States"
        count = len(self.climate_normal_search_results)
        self.climate_normal_status_var.set(
            f"{count} station(s) shown for {context}."
            if (query or state_code)
            else f"Loaded {len(self.climate_normal_catalog)} U.S. station(s). Select a state or search by name."
        )
        self.climate_normal_map_records = (
            list(self.climate_normal_search_results)
            if (query or state_code)
            else list(self.climate_normal_catalog)
        )
        self._schedule_climate_normal_map_redraw(fit_bounds=fit_map and bool(self.climate_normal_map_records))

    @staticmethod
    def _climate_normal_station_label(record: dict[str, object]) -> str:
        return f"{record.get('name', 'Unnamed station')} [{record.get('station_id', '')}]"

    def _climate_normal_station_selected(self, _event: tk.Event | None = None) -> None:
        selection = self.climate_normal_station_list.curselection()
        if not selection:
            self.climate_normal_station_var.set("")
            self.add_climate_normal_button.configure(state="disabled")
            self.cancel_climate_normal_search_button.configure(state="disabled")
            self._update_climate_normal_map_selection()
            return
        index = int(selection[0])
        if not 0 <= index < len(self.climate_normal_search_results):
            return
        station_id = str(self.climate_normal_search_results[index]["station_id"])
        self.climate_normal_station_var.set(station_id)
        self._update_climate_normal_map_selection()
        record = self.climate_normal_search_results[index]
        request_by_station = self.__dict__.get(
            "climate_normal_detail_request_by_station", {}
        )
        if station_id in request_by_station:
            self.add_climate_normal_button.configure(state="disabled")
            self.cancel_climate_normal_search_button.configure(state="normal")
            self.climate_normal_status_var.set(
                f"The precipitation normals for {record['name']} are loading."
            )
            return
        self.cancel_climate_normal_search_button.configure(state="disabled")
        if all(key in record for key in PRECIPITATION_NORMAL_RECORD_KEYS):
            self.add_climate_normal_button.configure(state="normal")
            self.climate_normal_status_var.set(
                f"Selected {record['name']}: "
                f"{format_number(float(record['annual_precipitation_inches']), self.config_model)} in annually."
            )
            return
        self.add_climate_normal_button.configure(state="normal")
        self.climate_normal_status_var.set(
            f"Selected {record['name']}. Choose Add to comparison to load its "
            "annual and seasonal precipitation normals."
        )

    def _start_climate_normal_detail_search(self, record: dict[str, object]) -> None:
        station_id = str(record.get("station_id", ""))
        if station_id in self.climate_normal_detail_request_by_station:
            self.climate_normal_status_var.set(
                f"The precipitation normals for {record['name']} are already loading."
            )
            return
        if len(self.climate_normal_detail_requests) >= 4:
            self.climate_normal_status_var.set(
                "Four Climate Normals data searches are already running. "
                "Wait for one to finish before starting another."
            )
            return
        self.climate_normal_detail_request_serial += 1
        request_id = self.climate_normal_detail_request_serial
        cancel_event = threading.Event()
        self.climate_normal_detail_requests[request_id] = (station_id, cancel_event)
        self.climate_normal_detail_request_by_station[station_id] = request_id
        self.climate_normal_detail_request_id = request_id
        self.climate_normal_detail_request_station_id = station_id
        self.climate_normal_detail_cancel_event = cancel_event
        self.climate_normal_detail_in_flight_ids.add(station_id)
        self.climate_normal_detail_in_flight = len(self.climate_normal_detail_requests)
        self.add_climate_normal_button.configure(state="disabled")
        self.cancel_climate_normal_search_button.configure(state="normal")
        self.climate_normal_status_var.set(
            f"Loading annual and seasonal precipitation normals for {record['name']}..."
        )
        self.climate_normal_detail_executor.submit(
            self._climate_normal_detail_worker,
            dict(record),
            request_id,
            cancel_event,
        )
        if self.climate_normal_detail_poll_after_id is None:
            self.climate_normal_detail_poll_after_id = self.after(
                100, self._poll_climate_normal_detail
            )

    def _climate_normal_detail_worker(
        self,
        station: dict[str, object],
        request_id: int,
        cancel_event: threading.Event,
    ) -> None:
        station_id = str(station.get("station_id", ""))

        def report_progress(message: str) -> None:
            if not cancel_event.is_set():
                self.climate_normal_detail_queue.put(
                    ("progress", request_id, station_id, message)
                )

        try:
            record = fetch_annual_precipitation_normal(
                station,
                progress_callback=report_progress,
                cancel_event=cancel_event,
            )
            if not cancel_event.is_set():
                self.climate_normal_detail_queue.put(
                    ("success", request_id, station_id, record)
                )
        except ClimateNormalRequestCancelled:
            self.climate_normal_detail_queue.put(
                ("cancelled", request_id, station_id, "Data search canceled.")
            )
        except Exception as exc:  # noqa: BLE001
            if not cancel_event.is_set():
                self.climate_normal_detail_queue.put(
                    ("error", request_id, station_id, str(exc))
                )

    def cancel_climate_normal_data_search(self) -> None:
        station_id = self.climate_normal_station_var.get()
        request_id = self.climate_normal_detail_request_by_station.get(station_id)
        request_details = self.climate_normal_detail_requests.get(request_id or -1)
        if request_id is None or request_details is None:
            return
        _request_station_id, cancel_event = request_details
        cancel_event.set()
        if len(self.climate_normal_detail_requests) == 1:
            cancel_annual_precipitation_normal_request()
        self._finish_climate_normal_detail_request(request_id, station_id)
        selected_station_id = self.climate_normal_station_var.get()
        self.add_climate_normal_button.configure(
            state="normal" if selected_station_id else "disabled"
        )
        station = next(
            (
                item
                for item in self.climate_normal_catalog
                if str(item.get("station_id", "")) == station_id
            ),
            None,
        )
        station_name = str(station.get("name", station_id)) if station else station_id
        self.climate_normal_status_var.set(f"Canceled data search for {station_name}.")

    def _finish_climate_normal_detail_request(
        self, request_id: int, station_id: str
    ) -> None:
        if request_id not in self.climate_normal_detail_requests:
            return
        self.climate_normal_detail_requests.pop(request_id, None)
        self.climate_normal_detail_request_by_station.pop(station_id, None)
        self.climate_normal_detail_in_flight_ids.discard(station_id)
        self.climate_normal_detail_in_flight = len(self.climate_normal_detail_requests)
        if self.climate_normal_detail_requests:
            latest_id = max(self.climate_normal_detail_requests)
            latest_station_id, latest_event = self.climate_normal_detail_requests[latest_id]
            self.climate_normal_detail_request_id = latest_id
            self.climate_normal_detail_request_station_id = latest_station_id
            self.climate_normal_detail_cancel_event = latest_event
        else:
            self.climate_normal_detail_request_id = None
            self.climate_normal_detail_request_station_id = ""
            self.climate_normal_detail_cancel_event = None
        selected_station_id = self.climate_normal_station_var.get()
        self.cancel_climate_normal_search_button.configure(
            state=(
                "normal"
                if selected_station_id in self.climate_normal_detail_request_by_station
                else "disabled"
            )
        )

    def _poll_climate_normal_detail(self) -> None:
        self.climate_normal_detail_poll_after_id = None
        try:
            result, request_id, station_id, payload = (
                self.climate_normal_detail_queue.get_nowait()
            )
        except queue.Empty:
            if self.climate_normal_detail_requests:
                self.climate_normal_detail_poll_after_id = self.after(
                    100, self._poll_climate_normal_detail
                )
            return

        if request_id not in self.climate_normal_detail_requests:
            if self.climate_normal_detail_requests or not self.climate_normal_detail_queue.empty():
                self.climate_normal_detail_poll_after_id = self.after(
                    0, self._poll_climate_normal_detail
                )
            return
        if result == "progress":
            if self.climate_normal_station_var.get() == station_id:
                self.climate_normal_status_var.set(str(payload))
            self.climate_normal_detail_poll_after_id = self.after(
                100, self._poll_climate_normal_detail
            )
            return

        self._finish_climate_normal_detail_request(request_id, station_id)
        if result == "success":
            updated_record = dict(payload)
            for collection in (
                self.climate_normal_catalog,
                self.climate_normal_search_results,
            ):
                for index, record in enumerate(collection):
                    if str(record.get("station_id", "")) == station_id:
                        collection[index] = dict(updated_record)
            self._add_climate_normal_record(updated_record)
            selected_station_id = self.climate_normal_station_var.get()
            self.add_climate_normal_button.configure(
                state=(
                    "normal"
                    if selected_station_id
                    and selected_station_id
                    not in self.climate_normal_detail_request_by_station
                    else "disabled"
                )
            )
        elif result == "error":
            selected_station_id = self.climate_normal_station_var.get()
            self.add_climate_normal_button.configure(
                state=(
                    "normal"
                    if selected_station_id
                    and selected_station_id
                    not in self.climate_normal_detail_request_by_station
                    else "disabled"
                )
            )
            if selected_station_id == station_id:
                self.climate_normal_status_var.set(str(payload))
        if self.climate_normal_detail_requests or not self.climate_normal_detail_queue.empty():
            self.climate_normal_detail_poll_after_id = self.after(
                100, self._poll_climate_normal_detail
            )

    def add_selected_climate_normal(self) -> None:
        selection = self.climate_normal_station_list.curselection()
        index = int(selection[0]) if selection else -1
        if index < 0 or index >= len(self.climate_normal_search_results):
            messagebox.showinfo(
                APP_TITLE, "Find and select a NOAA Climate Normals station first.", parent=self
            )
            return
        record = dict(self.climate_normal_search_results[index])
        if not all(key in record for key in PRECIPITATION_NORMAL_RECORD_KEYS):
            query = self._climate_normal_name_query()
            state_code = self._selected_climate_normal_state_code()
            record["searched_location"] = (
                query or STATE_NAME_BY_CODE.get(state_code, "United States")
            )
            self._start_climate_normal_detail_search(record)
            return
        query = self._climate_normal_name_query()
        state_code = self._selected_climate_normal_state_code()
        record["searched_location"] = (
            query or STATE_NAME_BY_CODE.get(state_code, "United States")
        )
        self._add_climate_normal_record(record)

    def _add_climate_normal_record(self, record: dict[str, object]) -> None:
        station_id = str(record["station_id"])
        self.climate_normal_comparison_rows[station_id] = record
        self._refresh_climate_normal_comparison()
        self.climate_normal_status_var.set(
            f"Added {record['name']} to the precipitation comparison."
        )

    def _climate_normal_map_marker_clicked(self, marker: object) -> None:
        marker_data = getattr(marker, "data", {})
        station_ids = (
            marker_data.get("station_ids", []) if isinstance(marker_data, dict) else []
        )
        if len(station_ids) > 1:
            latitude, longitude = getattr(marker, "position")
            self.climate_normal_map.set_position(latitude, longitude)
            self.climate_normal_map.set_zoom(
                min(round(self.climate_normal_map.zoom) + 2, self.climate_normal_map.max_zoom)
            )
            self._schedule_climate_normal_map_redraw()
            return
        if not station_ids:
            return
        station_id = str(station_ids[0])
        visible_ids = [str(item.get("station_id", "")) for item in self.climate_normal_search_results]
        if station_id not in visible_ids:
            record = next(
                (
                    item
                    for item in self.climate_normal_catalog
                    if str(item.get("station_id", "")) == station_id
                ),
                None,
            )
            if record is None:
                return
            self.climate_normal_search_placeholder_active = False
            self.climate_normal_query_var.set(str(record.get("name", "")))
            self.climate_normal_search_entry.configure(foreground="#1f2d33")
            self.climate_normal_state_list.selection_clear(0, tk.END)
            self.climate_normal_state_list.configure(state=tk.DISABLED)
            self._apply_climate_normal_station_filter(fit_map=True)
            visible_ids = [
                str(item.get("station_id", "")) for item in self.climate_normal_search_results
            ]
        if station_id not in visible_ids:
            return
        index = visible_ids.index(station_id)
        self.climate_normal_station_list.selection_clear(0, tk.END)
        self.climate_normal_station_list.selection_set(index)
        self.climate_normal_station_list.activate(index)
        self.climate_normal_station_list.see(index)
        self._climate_normal_station_selected()

    def _clear_climate_normal_map_markers(self) -> None:
        markers = tuple(self.climate_normal_map_markers)
        self.climate_normal_map_markers = []
        self.climate_normal_map_marker_by_station_id = {}
        for marker in markers:
            try:
                marker.delete()
            except (IndexError, tk.TclError):
                pass

    def _render_climate_normal_map(self, *, fit_bounds: bool) -> None:
        if not hasattr(self, "climate_normal_map") or not self.climate_normal_map.winfo_exists():
            return
        self._clear_climate_normal_map_markers()
        selected_station_id = self.climate_normal_station_var.get()
        self.climate_normal_map_selected_station_id = selected_station_id
        valid_stations = [
            station
            for station in self.climate_normal_map_records
            if self._station_coordinates(station) is not None
        ]
        positions = [self._station_coordinates(station) for station in valid_stations]
        zoom = max(round(self.climate_normal_map.zoom), 1)
        self.climate_normal_map_rendered_zoom = zoom
        for cluster in self._cluster_stations(valid_stations, zoom):
            cluster_positions = [self._station_coordinates(station) for station in cluster]
            latitude = sum(
                position[0] for position in cluster_positions if position is not None
            ) / len(cluster_positions)
            longitude = sum(
                position[1] for position in cluster_positions if position is not None
            ) / len(cluster_positions)
            station_ids = [str(station.get("station_id", "")) for station in cluster]
            selected = selected_station_id in station_ids
            selected_record = next(
                (
                    station
                    for station in cluster
                    if str(station.get("station_id", "")) == selected_station_id
                ),
                None,
            )
            marker_text = (
                str(selected_record.get("name", ""))
                if selected_record is not None and len(cluster) == 1
                else f"{len(cluster)} stations"
                if len(cluster) > 1
                else None
            )
            marker = self.climate_normal_map.set_marker(
                latitude,
                longitude,
                text=marker_text,
                command=self._climate_normal_map_marker_clicked,
                data={"station_ids": station_ids},
                marker_color_circle="#b71c1c" if selected else "#1565c0",
                marker_color_outside="#d32f2f" if selected else "#1976d2",
            )
            self.climate_normal_map_markers.append(marker)
            for station_id in station_ids:
                self.climate_normal_map_marker_by_station_id[station_id] = marker
        valid_positions = [position for position in positions if position is not None]
        if not fit_bounds or not valid_positions:
            return
        if len(valid_positions) == 1:
            self.climate_normal_map.set_position(*valid_positions[0])
            self.climate_normal_map.set_zoom(10)
            self._schedule_climate_normal_map_redraw()
            return
        latitudes = [position[0] for position in valid_positions]
        longitudes = [position[1] for position in valid_positions]
        latitude_padding = max((max(latitudes) - min(latitudes)) * 0.06, 0.05)
        longitude_padding = max((max(longitudes) - min(longitudes)) * 0.06, 0.05)
        self.climate_normal_map.fit_bounding_box(
            (max(latitudes) + latitude_padding, min(longitudes) - longitude_padding),
            (min(latitudes) - latitude_padding, max(longitudes) + longitude_padding),
        )
        self._schedule_climate_normal_map_redraw()

    def _update_climate_normal_map_selection(self) -> None:
        selected_station_id = self.climate_normal_station_var.get()
        markers_to_update = {
            marker
            for station_id in (
                self.climate_normal_map_selected_station_id,
                selected_station_id,
            )
            if (
                marker := self.climate_normal_map_marker_by_station_id.get(station_id)
            ) is not None
        }
        self.climate_normal_map_selected_station_id = selected_station_id
        for marker in markers_to_update:
            marker_data = getattr(marker, "data", {})
            station_ids = (
                marker_data.get("station_ids", [])
                if isinstance(marker_data, dict)
                else []
            )
            selected = selected_station_id in station_ids
            marker.marker_color_circle = "#b71c1c" if selected else "#1565c0"
            marker.marker_color_outside = "#d32f2f" if selected else "#1976d2"
            if selected and len(station_ids) == 1:
                record = next(
                    (
                        item
                        for item in self.climate_normal_catalog
                        if str(item.get("station_id", "")) == selected_station_id
                    ),
                    None,
                )
                marker.set_text(str(record.get("name", "")) if record else None)
            else:
                marker.set_text(f"{len(station_ids)} stations" if len(station_ids) > 1 else None)

    def _climate_normal_map_view_changed(self, _event: tk.Event | None = None) -> None:
        self._schedule_climate_normal_map_redraw()

    def _schedule_climate_normal_map_redraw(self, *, fit_bounds: bool = False) -> None:
        self.climate_normal_map_fit_on_redraw = (
            self.climate_normal_map_fit_on_redraw or fit_bounds
        )
        if self.climate_normal_map_redraw_after_id is not None:
            self.after_cancel(self.climate_normal_map_redraw_after_id)
        self.climate_normal_map_redraw_after_id = self.after(
            200, self._redraw_climate_normal_map
        )

    def _redraw_climate_normal_map(self) -> None:
        self.climate_normal_map_redraw_after_id = None
        fit_bounds = self.climate_normal_map_fit_on_redraw
        self.climate_normal_map_fit_on_redraw = False
        if not hasattr(self, "climate_normal_map") or not self.climate_normal_map.winfo_exists():
            return
        if fit_bounds or round(self.climate_normal_map.zoom) != self.climate_normal_map_rendered_zoom:
            self._render_climate_normal_map(fit_bounds=fit_bounds)

    def _ranked_climate_normal_rows(self) -> list[dict[str, object]]:
        sort_keys = dict(
            zip(
                ("annual", "winter", "spring", "summer", "autumn"),
                PRECIPITATION_NORMAL_RECORD_KEYS,
                strict=True,
            )
        )
        sort_column = self.__dict__.get("climate_normal_sort_column", "annual")
        descending = self.__dict__.get("climate_normal_sort_descending", True)
        if sort_column == "station":
            return sorted(
                self.climate_normal_comparison_rows.values(),
                key=lambda item: (
                    str(item["name"]).casefold(),
                    str(item.get("station_id", "")).casefold(),
                ),
                reverse=descending,
            )
        record_key = sort_keys.get(sort_column, sort_keys["annual"])
        return sorted(
            self.climate_normal_comparison_rows.values(),
            key=lambda item: (
                (-1.0 if descending else 1.0) * float(item[record_key]),
                str(item["name"]).casefold(),
            ),
        )

    def _sort_climate_normal_comparison(self, column: str) -> None:
        sortable_columns = {
            "station",
            "annual",
            "winter",
            "spring",
            "summer",
            "autumn",
        }
        if column not in sortable_columns:
            return
        if column == self.__dict__.get("climate_normal_sort_column", "annual"):
            self.climate_normal_sort_descending = not self.__dict__.get(
                "climate_normal_sort_descending", True
            )
        else:
            self.climate_normal_sort_column = column
            self.climate_normal_sort_descending = column != "station"
        self._refresh_climate_normal_comparison()

    def _refresh_climate_normal_sort_headings(self) -> None:
        if not hasattr(self.climate_normal_tree, "heading"):
            return
        labels = {
            "station": "Station",
            "annual": "Annual",
            "winter": "Winter",
            "spring": "Spring",
            "summer": "Summer",
            "autumn": "Autumn",
        }
        active_column = self.__dict__.get("climate_normal_sort_column", "annual")
        descending = self.__dict__.get("climate_normal_sort_descending", True)
        for column, label in labels.items():
            indicator = " ▼" if descending else " ▲"
            self.climate_normal_tree.heading(
                column,
                text=f"{label}{indicator}" if column == active_column else label,
            )
        self._wrap_treeview_headings(self.climate_normal_tree)

    def _refresh_climate_normal_comparison(self) -> None:
        unit = precip_unit(self.config_model)
        comparison_frame = self.__dict__.get("climate_normal_comparison_frame")
        if comparison_frame is not None:
            comparison_frame.configure(text=f"Precipitation normals ({unit})")
        self._refresh_climate_normal_sort_headings()
        self.climate_normal_tree.delete(*self.climate_normal_tree.get_children())
        for record in self._ranked_climate_normal_rows():
            self.climate_normal_tree.insert(
                "",
                "end",
                iid=str(record["station_id"]),
                values=(
                    f"{record.get('name', '')} [{record.get('station_id', '')}]",
                    *(
                        format_number(precip_to_display(float(record[key]), self.config_model), self.config_model)
                        for key in PRECIPITATION_NORMAL_RECORD_KEYS
                    ),
                ),
            )

    def remove_selected_climate_normal(self) -> None:
        for station_id in self.climate_normal_tree.selection():
            self.climate_normal_comparison_rows.pop(station_id, None)
        self._refresh_climate_normal_comparison()

    def clear_climate_normal_comparison(self) -> None:
        self.climate_normal_comparison_rows.clear()
        self._refresh_climate_normal_comparison()

    def export_climate_normal_comparison(self) -> None:
        rows = self._ranked_climate_normal_rows()
        if not rows:
            messagebox.showinfo(
                APP_TITLE, "Add at least one station before exporting.", parent=self
            )
            return
        path = filedialog.asksaveasfilename(
            title="Export multi-site weather comparison",
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            unit = precip_unit(self.config_model)
            with Path(path).open("w", encoding="utf-8", newline="") as output:
                writer = csv.writer(output)
                writer.writerow(
                    [
                        "Rank",
                        "Searched location",
                        "NOAA station",
                        "Station ID",
                        f"Annual precipitation normal ({unit} water equivalent)",
                        f"Winter precipitation normal ({unit} water equivalent)",
                        f"Spring precipitation normal ({unit} water equivalent)",
                        f"Summer precipitation normal ({unit} water equivalent)",
                        f"Autumn precipitation normal ({unit} water equivalent)",
                        "Normal period",
                        "Latitude",
                        "Longitude",
                        "Source",
                    ]
                )
                for rank, record in enumerate(rows, start=1):
                    writer.writerow(
                        [
                            rank,
                            record.get("searched_location", record.get("name", "")),
                            record.get("name", ""),
                            record.get("station_id", ""),
                            *(
                                format_number(precip_to_display(float(record[key]), self.config_model), self.config_model)
                                for key in PRECIPITATION_NORMAL_RECORD_KEYS
                            ),
                            record.get("period", "1991-2020"),
                            record.get("latitude", ""),
                            record.get("longitude", ""),
                            record.get("provider", "NOAA NCEI U.S. Climate Normals"),
                        ]
                    )
        except OSError as exc:
            self.climate_normal_status_var.set("Could not export the comparison.")
            messagebox.showerror("Export failed", str(exc), parent=self)
            return
        self.climate_normal_status_var.set(
            f"Exported comparison to {Path(path).name}."
        )

    def find_acis_stations(self) -> None:
        years = max(30, int(_float(self.weather_years_var.get(), 30)))
        selected_state = self.weather_state_var.get()
        if selected_state == STATE_PLACEHOLDER:
            messagebox.showwarning(APP_TITLE, "Select a state before finding ACIS stations.")
            return
        self._start_station_lookup("ACIS", _state_code(selected_state), years)

    def find_weather_stations(self) -> None:
        if self.station_lookup_in_progress:
            return
        country = self._selected_country_code()
        if country == "USA":
            self.find_acis_stations()
        elif country == "CAN":
            self.find_eccc_stations()

    def find_nearest_weather_stations(self) -> None:
        if self.station_lookup_in_progress:
            return
        coordinates = self._coordinates_from_form(require_coordinates=True)
        if coordinates is None:
            return
        latitude, longitude = coordinates
        assert latitude is not None and longitude is not None
        country = self._selected_country_code()
        if country not in {"USA", "CAN"}:
            messagebox.showinfo(APP_TITLE, "Nearest-station search is currently available for the USA and Canada.")
            return
        years = max(30, int(_float(self.weather_years_var.get(), 30)))
        self._start_nearest_station_lookup(
            "ACIS" if country == "USA" else "ECCC",
            latitude,
            longitude,
            years,
        )

    def find_nearest_airport_weather_stations(self) -> None:
        if self.station_lookup_in_progress:
            return
        coordinates = self._coordinates_from_form(require_coordinates=True)
        if coordinates is None:
            return
        latitude, longitude = coordinates
        assert latitude is not None and longitude is not None
        country = self._selected_country_code()
        if country not in {"USA", "CAN"}:
            messagebox.showinfo(
                APP_TITLE,
                "Airport-station search is currently available for the USA and Canada.",
            )
            return
        years = max(30, int(_float(self.weather_years_var.get(), 30)))
        self._start_nearest_station_lookup(
            "ACIS" if country == "USA" else "ECCC",
            latitude,
            longitude,
            years,
            airport_only=True,
        )

    def find_eccc_stations(self) -> None:
        years = max(30, int(_float(self.weather_years_var.get(), 30)))
        selected_province = self.weather_state_var.get()
        if selected_province == PROVINCE_PLACEHOLDER:
            messagebox.showwarning(APP_TITLE, "Select a province or territory before finding ECCC stations.")
            return
        self._start_station_lookup("ECCC", _state_code(selected_province), years)

    def _start_station_lookup(self, provider: str, region: str, years: int) -> None:
        if self.station_lookup_in_progress:
            return
        start_date, end_date = default_complete_calendar_range(years)
        query = self.weather_filter_var.get().strip().casefold()
        self.station_lookup_in_progress = True
        self.station_lookup_airport_only = False
        for widget in (
            self.country_combo,
            self.state_combo,
            self.find_stations_button,
            self.find_nearest_stations_button,
            self.find_nearest_airport_stations_button,
            self.station_combo,
            self.import_station_button,
        ):
            widget.configure(state="disabled")
        self.analysis_progress.stop()
        self.analysis_progress.configure(mode="indeterminate", style="Analysis.Horizontal.TProgressbar")
        self.analysis_progress.start(12)
        self.status_var.set(f"Finding {provider} stations...")
        self.execution_log.info("Weather", f"Searching {provider} stations in the selected region")
        self.execution_log.diagnostic(
            "Weather",
            "Station search parameters prepared",
            details=f"years={years}; query_set={bool(query)}",
        )
        worker = threading.Thread(
            target=self._station_lookup_worker,
            args=(provider, region, start_date, end_date, query),
            name=f"rwh-{provider.casefold()}-station-lookup",
            daemon=True,
        )
        worker.start()
        self.station_lookup_poll_after_id = self.after(100, self._poll_station_lookup_results)

    def _start_nearest_station_lookup(
        self,
        provider: str,
        latitude: float,
        longitude: float,
        years: int,
        *,
        airport_only: bool = False,
    ) -> None:
        start_date, end_date = default_complete_calendar_range(years)
        self.station_lookup_in_progress = True
        self.station_lookup_airport_only = airport_only
        for widget in (
            self.country_combo,
            self.state_combo,
            self.find_stations_button,
            self.find_nearest_stations_button,
            self.find_nearest_airport_stations_button,
            self.station_combo,
            self.import_station_button,
        ):
            widget.configure(state="disabled")
        self.analysis_progress.stop()
        self.analysis_progress.configure(mode="indeterminate", style="Analysis.Horizontal.TProgressbar")
        self.analysis_progress.start(12)
        station_kind = "airport weather stations" if airport_only else f"{provider} stations"
        self.status_var.set(f"Finding nearest {station_kind}...")
        self.execution_log.info("Weather", f"Searching for nearest {station_kind}")
        threading.Thread(
            target=self._nearest_station_lookup_worker,
            args=(provider, latitude, longitude, start_date, end_date, airport_only),
            name=f"rwh-{provider.casefold()}-nearest-stations",
            daemon=True,
        ).start()
        self.station_lookup_poll_after_id = self.after(100, self._poll_station_lookup_results)

    def _nearest_station_lookup_worker(
        self,
        provider: str,
        latitude: float,
        longitude: float,
        start_date: dt.date,
        end_date: dt.date,
        airport_only: bool = False,
    ) -> None:
        try:
            stations: list[dict] = []
            limit = 5 if airport_only else 10
            search_radii = (
                (150.0, 400.0, 1000.0)
                if airport_only and provider == "ACIS"
                else (50.0, 150.0, 400.0, 1000.0)
            )
            for radius_index, radius_km in enumerate(search_radii):
                self.execution_log.diagnostic(
                    "Weather", f"Searching within a {radius_km:g} km radius"
                )
                west, south, east, north = bounding_box(latitude, longitude, radius_km)
                if provider == "ACIS":
                    stations = fetch_station_options_bbox(west, south, east, north, start_date, end_date)
                else:
                    stations = fetch_canadian_station_options_bbox(west, south, east, north, start_date, end_date)
                if airport_only and provider == "ACIS":
                    structured_candidates = [
                        station for station in stations if acis_aviation_identifiers(station)
                    ]
                    verification_window = (10, 20, 40)[radius_index]
                    structured_candidates = nearest_stations(
                        structured_candidates,
                        latitude,
                        longitude,
                        limit=verification_window,
                    )
                    stations = verified_airport_weather_stations(
                        structured_candidates, provider
                    )
                elif airport_only:
                    stations = verified_airport_weather_stations(stations, provider)
                stations = nearest_stations(stations, latitude, longitude, limit=limit)
                if len(stations) >= limit:
                    break
            self.station_lookup_queue.put(("success", provider, stations))
        except Exception as exc:  # noqa: BLE001
            self.execution_log.error("Weather", "Nearest-station search failed", exception=exc)
            self.station_lookup_queue.put(("error", provider, str(exc)))

    def _station_lookup_worker(
        self,
        provider: str,
        region: str,
        start_date: dt.date,
        end_date: dt.date,
        query: str,
    ) -> None:
        try:
            self.execution_log.debug("Weather", f"{provider} station-search worker started")
            if provider == "ACIS":
                stations = fetch_station_options(region, start_date, end_date)
            else:
                stations = fetch_canadian_station_options(region, start_date, end_date)
            stations = filter_stations(stations, query)
            self.station_lookup_queue.put(("success", provider, stations))
        except Exception as exc:  # noqa: BLE001
            self.execution_log.error("Weather", f"{provider} station search failed", exception=exc)
            self.station_lookup_queue.put(("error", provider, str(exc)))

    def _poll_station_lookup_results(self) -> None:
        self.station_lookup_poll_after_id = None
        try:
            result, provider, payload = self.station_lookup_queue.get_nowait()
        except queue.Empty:
            self.station_lookup_poll_after_id = self.after(100, self._poll_station_lookup_results)
            return

        self.analysis_progress.stop()
        self.analysis_progress.configure(mode="determinate")
        self.analysis_progress_var.set(0)
        self.station_lookup_in_progress = False
        self.country_combo.configure(state="readonly")
        self.state_combo.configure(state="readonly")
        self.find_stations_button.configure(state="normal")
        self.find_nearest_stations_button.configure(state="normal")
        self.find_nearest_airport_stations_button.configure(state="normal")
        self.station_combo.configure(state="readonly")
        self.import_station_button.configure(state="normal")
        if result == "error":
            station_kind = "airport weather stations" if self.station_lookup_airport_only else f"{provider} stations"
            self.status_var.set(f"Could not fetch {station_kind}")
            self.execution_log.error("Weather", f"Could not fetch {provider} stations: {payload}")
            messagebox.showerror(APP_TITLE, f"Could not fetch {station_kind}:\n{payload}")
            return

        self.station_options = payload
        labels = [self._station_label(station) for station in self.station_options]
        self.station_combo["values"] = labels
        self.station_var.set(labels[0] if labels else "")
        self._reset_station_typeahead()
        self._render_station_map(fit_bounds=True)
        descriptor = (
            "airport weather station(s)"
            if self.station_lookup_airport_only
            else "ECCC climate station(s)" if provider == "ECCC" else "ACIS station(s)"
        )
        nearest = bool(self.station_options and "distance_km" in self.station_options[0])
        qualifier = "nearest " if nearest else ""
        self.status_var.set(f"Found {len(self.station_options)} {qualifier}{descriptor}")
        self.execution_log.info(
            "Weather", f"Found {len(self.station_options)} {provider} station options"
        )

    def _reset_weather_selection(self) -> None:
        if self.state_typeahead_after_id is not None:
            self.after_cancel(self.state_typeahead_after_id)
        self._reset_state_typeahead()
        country = self._selected_country_code()
        if country == "CAN":
            self.weather_state_var.set(PROVINCE_PLACEHOLDER)
        elif country == "USA":
            self.weather_state_var.set(STATE_PLACEHOLDER)
        self.weather_filter_var.set("")
        self.station_var.set("")
        self.station_options = []
        if hasattr(self, "station_combo"):
            self.station_combo["values"] = []
        if hasattr(self, "station_map"):
            self._clear_station_map_markers()
        self._reset_station_typeahead()

    def import_acis_weather(self) -> None:
        selected = self.station_var.get()
        if not selected:
            messagebox.showinfo(APP_TITLE, "Find and select an ACIS station first.")
            return
        station = next((item for item in self.station_options if self._station_label(item) == selected), None)
        if station is None:
            messagebox.showinfo(APP_TITLE, "Select an ACIS station first.")
            return
        years = max(30, int(_float(self.weather_years_var.get(), 30)))
        basis_label = self.canadian_precip_var.get()
        precipitation_field = CANADIAN_PRECIPITATION_OPTIONS.get(basis_label, "TOTAL_PRECIPITATION")
        try:
            self.status_var.set(f"Importing station {station['name']} ({station['sid']})...")
            self.execution_log.info("Weather", "Importing ACIS rainfall data")
            self.execution_log.diagnostic(
                "Weather", "ACIS import configured", details=f"years={years}; basis={basis_label}"
            )
            self._drain_execution_log_to_window()
            self.update_idletasks()
            start_date, end_date = default_complete_calendar_range(years)
            weather_df = fetch_daily_station_data(station["sid"], start_date, end_date, precipitation_field)
            self.rainfall_df = weather_df[["Date", "Precipitation"]].copy()
            self.use_synthetic_hourly_rainfall_var.set(False)
            self.config_model.use_synthetic_hourly_rainfall = False
            self.current_rainfall_csv_path = None
            station_region = self._station_region_suffix(station)
            self.rainfall_source_label = (
                f"{station['name']} ({station['sid']}){station_region} via ACIS, {basis_label}"
            )
            self.config_model.rainfall_source_label = self.rainfall_source_label
            self._set_rainfall_provenance(
                data_type="observed",
                temporal_resolution="daily",
                timezone="Station local time; UTC offset not supplied by ACIS import",
                timing_type="Observed daily totals; within-day timing not observed",
                known_missing_dates=weather_df.attrs.get("known_missing_dates", []),
            )
            self.config_model.weather_station_latitude = None
            self.config_model.weather_station_longitude = None
            station_coordinates = self._station_coordinates(station)
            if station_coordinates is not None:
                (
                    self.config_model.weather_station_latitude,
                    self.config_model.weather_station_longitude,
                ) = station_coordinates
            self.config_model.country_code = "USA"
            self.config_model.acis_precipitation_field = precipitation_field
            self.curve_df = pd.DataFrame()
            self.results_df = pd.DataFrame()
            self.reliability_var.set("Reliability: --")
            self._clear_results()
            self._update_rainfall_summary()
            self.status_var.set(f"Imported {len(self.rainfall_df):,} rows from {station['name']} ({station['sid']})")
            self.execution_log.info(
                "Weather", f"Imported {len(self.rainfall_df):,} daily ACIS rainfall rows"
            )
            if precipitation_field == "TOTAL_RAIN":
                excluded_days = int(weather_df.attrs.get("rain_only_excluded_days", 0))
                messagebox.showwarning(
                    APP_TITLE,
                    "ACIS does not provide a native rain-only field. "
                    f"Precipitation was excluded on {excluded_days:,} day(s) with reported snowfall. "
                    "Mixed rain and snow days may therefore undercount rain.",
                )
        except Exception as exc:  # noqa: BLE001
            self.execution_log.error("Weather", "ACIS rainfall import failed", exception=exc)
            messagebox.showerror(APP_TITLE, f"Could not import ACIS weather:\n{exc}")

    def import_selected_weather(self) -> None:
        country = self._selected_country_code()
        if country == "USA":
            self.import_acis_weather()
        elif country == "CAN":
            self.import_eccc_weather()

    def import_eccc_weather(self) -> None:
        selected = self.station_var.get()
        if not selected:
            messagebox.showinfo(APP_TITLE, "Find and select an ECCC climate station first.")
            return
        station = next((item for item in self.station_options if self._station_label(item) == selected), None)
        if station is None:
            messagebox.showinfo(APP_TITLE, "Select an ECCC climate station first.")
            return

        years = max(30, int(_float(self.weather_years_var.get(), 30)))
        basis_label = self.canadian_precip_var.get()
        precipitation_field = CANADIAN_PRECIPITATION_OPTIONS.get(basis_label, "TOTAL_PRECIPITATION")
        try:
            self.status_var.set(f"Importing station {station['name']} ({station['sid']})...")
            self.execution_log.info("Weather", "Importing ECCC rainfall data")
            self.execution_log.diagnostic(
                "Weather", "ECCC import configured", details=f"years={years}; basis={basis_label}"
            )
            self._drain_execution_log_to_window()
            self.update_idletasks()
            start_date, end_date = default_complete_calendar_range(years)
            weather_df = fetch_canadian_daily_station_data(
                station["sid"],
                start_date,
                end_date,
                precipitation_field,
            )
            missing_days = int(weather_df.attrs.get("missing_days", 0))
            self.rainfall_df = weather_df[["Date", "Precipitation"]].copy()
            self.use_synthetic_hourly_rainfall_var.set(False)
            self.config_model.use_synthetic_hourly_rainfall = False
            self.current_rainfall_csv_path = None
            station_region = self._station_region_suffix(station)
            self.rainfall_source_label = (
                f"{station['name']} ({station['sid']}){station_region} via ECCC, {basis_label}"
            )
            self.config_model.rainfall_source_label = self.rainfall_source_label
            self._set_rainfall_provenance(
                data_type="observed",
                temporal_resolution="daily",
                timezone="Station local time; UTC offset not supplied by ECCC import",
                timing_type="Observed daily totals; within-day timing not observed",
                known_missing_dates=weather_df.attrs.get("known_missing_dates", []),
            )
            self.config_model.weather_station_latitude = None
            self.config_model.weather_station_longitude = None
            station_coordinates = self._station_coordinates(station)
            if station_coordinates is not None:
                (
                    self.config_model.weather_station_latitude,
                    self.config_model.weather_station_longitude,
                ) = station_coordinates
            self.config_model.country_code = "CAN"
            self.config_model.canadian_precipitation_field = precipitation_field
            self.curve_df = pd.DataFrame()
            self.results_df = pd.DataFrame()
            self.reliability_var.set("Reliability: --")
            self._clear_results()
            self._update_rainfall_summary()
            self.status_var.set(f"Imported {len(self.rainfall_df):,} rows from {station['name']} ({station['sid']})")
            self.execution_log.info(
                "Weather", f"Imported {len(self.rainfall_df):,} daily ECCC rainfall rows"
            )
            if missing_days:
                messagebox.showwarning(
                    APP_TITLE,
                    f"The ECCC record contained {missing_days:,} missing day(s). "
                    "They were treated as zero precipitation so daily demand remains continuous.",
                )
        except Exception as exc:  # noqa: BLE001
            self.execution_log.error("Weather", "ECCC rainfall import failed", exception=exc)
            messagebox.showerror(APP_TITLE, f"Could not import ECCC climate data:\n{exc}")

    def edit_surface(self) -> None:
        selected = self.surface_tree.selection()
        if not selected:
            messagebox.showinfo(APP_TITLE, "Select a surface row first.")
            return
        index = int(selected[0])
        surface = self.config_model.surfaces[index]
        dialog = SurfaceDialog(self, surface, self.config_model)
        self.wait_window(dialog)
        if dialog.result:
            self.config_model.surfaces[index] = dialog.result
            self._populate_surfaces()

    def add_surface(self) -> None:
        library_dialog = SurfaceLibraryDialog(self)
        self.wait_window(library_dialog)
        if library_dialog.result is None:
            return

        dialog = SurfaceDialog(self, library_dialog.result, self.config_model)
        self.wait_window(dialog)
        if dialog.result:
            self.config_model.surfaces.append(dialog.result)
            selected_index = len(self.config_model.surfaces) - 1
            self._populate_surfaces()
            item_id = str(selected_index)
            self.surface_tree.selection_set(item_id)
            self.surface_tree.focus(item_id)
            self.surface_tree.see(item_id)

    def _edit_surface_from_event(self, event: tk.Event) -> str:
        row_id = self.surface_tree.identify_row(event.y)
        if row_id:
            self.surface_tree.selection_set(row_id)
            self.surface_tree.focus(row_id)
            self.edit_surface()
        return "break"

    def _edit_selected_surface_from_event(self, _event: tk.Event) -> str:
        if self.surface_tree.selection():
            self.edit_surface()
        return "break"

    def edit_demand_month(self) -> None:
        selected = self.demand_tree.selection()
        if not selected:
            messagebox.showinfo(APP_TITLE, "Select a month row first.")
            return
        month = selected[0]
        dialog = DemandDialog(self, self.config_model, month)
        self.wait_window(dialog)
        if dialog.saved:
            self._populate_demand()

    def add_demand_object(self) -> None:
        if not self.config_model.demand.hourly_schedule_library:
            messagebox.showinfo(APP_TITLE, "Add a schedule to the project before creating a demand object.", parent=self)
            return
        demand_object = DemandObject(
            name="New demand object",
            schedule_name=next(iter(self.config_model.demand.hourly_schedule_library)),
        )
        dialog = DemandObjectDialog(self, self.config_model, demand_object)
        self.wait_window(dialog)
        if dialog.result is not None:
            self.config_model.demand.demand_objects.append(dialog.result)
            new_index = len(self.config_model.demand.demand_objects) - 1
            self._assign_demand_object_to_end_uses(new_index)
            self._populate_demand_objects(select_index=new_index)

    def _assign_demand_object_to_end_uses(self, demand_object_index: int) -> None:
        demand_count = len(self.config_model.demand.demand_objects)
        if not 0 <= demand_object_index < demand_count:
            return
        for item in self.config_model.system_layout:
            if str(item.get("component_type", "")) != "end_uses":
                continue
            assigned = _normalized_demand_object_indices(
                item.get("demand_object_indices"), demand_count
            )
            if demand_object_index not in assigned:
                assigned.append(demand_object_index)
            item["demand_object_indices"] = assigned

    def _all_demand_object_templates(self) -> dict[str, DemandObject]:
        return {**_common_demand_object_templates(), **self.custom_demand_object_templates}

    def _active_demand_objects_tree(self) -> ttk.Treeview:
        return self.demand_objects_tree

    def _active_demand_library_tree(self) -> ttk.Treeview:
        return self.demand_library_tree

    def _selected_demand_library_object(self) -> tuple[str, str] | None:
        selected = self._active_demand_library_tree().selection()
        if not selected:
            return None
        return self.demand_library_item_map.get(selected[0])

    def _refresh_demand_object_library(self, select_name: str | None = None) -> None:
        self.demand_library_item_map: dict[str, tuple[str, str]] = {}
        for tree in (self.demand_library_tree,):
            tree.delete(*tree.get_children())
            template_group = tree.insert(
                "", "end", iid="demand_library_templates", text="Templates", open=True, tags=("group",)
            )
            custom_group = tree.insert(
                "", "end", iid="demand_library_custom", text="Custom", open=True, tags=("group",)
            )
            selected_iid: str | None = None
            for kind, parent, templates in (
                ("template", template_group, _common_demand_object_templates()),
                ("custom", custom_group, self.custom_demand_object_templates),
            ):
                for index, name in enumerate(templates):
                    iid = f"demand_library_{kind}_{index}"
                    tree.insert(parent, "end", iid=iid, text=name)
                    self.demand_library_item_map[iid] = (kind, name)
                    if name == select_name:
                        selected_iid = iid
            if selected_iid is not None:
                tree.selection_set(selected_iid)
                tree.focus(selected_iid)
                tree.see(selected_iid)
        self._update_demand_library_state()

    def _demand_library_selection_changed(self, _event: tk.Event | None = None) -> None:
        self._update_demand_library_state()

    def _update_demand_library_state(self) -> None:
        for prefix in ("overall",):
            tree = getattr(self, f"{prefix}_demand_library_tree")
            selected_rows = tree.selection()
            selected = self.demand_library_item_map.get(selected_rows[0]) if selected_rows else None
            getattr(self, f"{prefix}_demand_library_duplicate_button").state(
                ["!disabled"] if selected else ["disabled"]
            )
            getattr(self, f"{prefix}_demand_library_delete_button").state(
                ["!disabled"] if selected and selected[0] == "custom" else ["disabled"]
            )
            getattr(self, f"{prefix}_add_demand_library_to_project_button").state(
                ["!disabled"] if selected else ["disabled"]
            )

    def _unique_demand_library_name(self, base_name: str) -> str:
        existing = {name.casefold() for name in self._all_demand_object_templates()}
        if base_name.casefold() not in existing:
            return base_name
        suffix = 2
        while f"{base_name} {suffix}".casefold() in existing:
            suffix += 1
        return f"{base_name} {suffix}"

    def _save_demand_library_changes(self, previous: dict[str, DemandObject]) -> bool:
        try:
            self._save_custom_demand_object_templates()
        except OSError as exc:
            self.custom_demand_object_templates = previous
            messagebox.showerror(APP_TITLE, f"Could not save the demand object library:\n{exc}", parent=self)
            return False
        return True

    def _edit_demand_library_template(self, demand_object: DemandObject) -> DemandObject | None:
        if not self.config_model.demand.hourly_schedule_library:
            messagebox.showinfo(APP_TITLE, "Add a schedule to the project before editing a demand object.", parent=self)
            return None
        demand_object.schedule_name = next(iter(self.config_model.demand.hourly_schedule_library))
        dialog = DemandObjectDialog(self, self.config_model, demand_object)
        self.wait_window(dialog)
        return dialog.result

    def create_custom_demand_object_template(self) -> None:
        name = self._unique_demand_library_name("Custom demand object")
        result = self._edit_demand_library_template(DemandObject(name=name))
        if result is None:
            return
        result.schedule_name = ""
        previous = copy.deepcopy(self.custom_demand_object_templates)
        self.custom_demand_object_templates[result.name] = result
        if self._save_demand_library_changes(previous):
            self._refresh_demand_object_library(select_name=result.name)

    def duplicate_demand_object_template(self) -> None:
        selected = self._selected_demand_library_object()
        if selected is None:
            return
        source = copy.deepcopy(self._all_demand_object_templates()[selected[1]])
        source.name = self._unique_demand_library_name(f"{source.name} copy")
        previous = copy.deepcopy(self.custom_demand_object_templates)
        self.custom_demand_object_templates[source.name] = source
        if self._save_demand_library_changes(previous):
            self._refresh_demand_object_library(select_name=source.name)

    def delete_custom_demand_object_template(self) -> None:
        selected = self._selected_demand_library_object()
        if selected is None or selected[0] != "custom":
            return
        name = selected[1]
        if not messagebox.askyesno(APP_TITLE, f"Delete custom demand object '{name}'?", parent=self):
            return
        previous = copy.deepcopy(self.custom_demand_object_templates)
        del self.custom_demand_object_templates[name]
        if self._save_demand_library_changes(previous):
            self._refresh_demand_object_library()

    def add_demand_object_from_library(self) -> None:
        selected = self._selected_demand_library_object()
        if selected is None:
            return
        result = self._edit_demand_library_template(copy.deepcopy(self._all_demand_object_templates()[selected[1]]))
        if result is not None:
            self.config_model.demand.demand_objects.append(result)
            new_index = len(self.config_model.demand.demand_objects) - 1
            self._assign_demand_object_to_end_uses(new_index)
            self._populate_demand_objects(select_index=new_index)

    def _add_demand_library_object_from_event(self, event: tk.Event) -> str:
        tree = event.widget
        if getattr(event, "y", None) is not None:
            row_id = tree.identify_row(event.y)
            if row_id in self.demand_library_item_map:
                tree.selection_set(row_id)
                tree.focus(row_id)
        if self._selected_demand_library_object() is not None:
            self.add_demand_object_from_library()
        return "break"

    def save_selected_demand_object_to_library(self) -> None:
        selected = self._active_demand_objects_tree().selection()
        if not selected:
            messagebox.showinfo(APP_TITLE, "Select a demand object first.", parent=self)
            return
        source = copy.deepcopy(self.config_model.demand.demand_objects[int(selected[0])])
        source.name = self._unique_demand_library_name(source.name)
        source.schedule_name = ""
        previous = copy.deepcopy(self.custom_demand_object_templates)
        self.custom_demand_object_templates[source.name] = source
        if self._save_demand_library_changes(previous):
            self._refresh_demand_object_library(select_name=source.name)

    def edit_demand_object(self) -> None:
        selected = self._active_demand_objects_tree().selection()
        if not selected:
            messagebox.showinfo(APP_TITLE, "Select a demand object first.", parent=self)
            return
        index = int(selected[0])
        dialog = DemandObjectDialog(
            self, self.config_model, copy.deepcopy(self.config_model.demand.demand_objects[index])
        )
        self.wait_window(dialog)
        if dialog.result is not None:
            self.config_model.demand.demand_objects[index] = dialog.result
            self._populate_demand_objects(select_index=index)

    def delete_demand_object(self) -> None:
        selected = self._active_demand_objects_tree().selection()
        if not selected:
            return
        index = int(selected[0])
        demand_object = self.config_model.demand.demand_objects[index]
        if not messagebox.askyesno(APP_TITLE, f"Delete demand object '{demand_object.name}'?", parent=self):
            return
        del self.config_model.demand.demand_objects[index]
        for item in self.config_model.system_layout:
            assigned = _normalized_demand_object_indices(
                item.get("demand_object_indices"), len(self.config_model.demand.demand_objects) + 1
            )
            item["demand_object_indices"] = [
                assigned_index - 1 if assigned_index > index else assigned_index
                for assigned_index in assigned
                if assigned_index != index
            ]
        self._populate_demand_objects()
        self._render_system_builder()

    def _edit_demand_object_from_event(self, event: tk.Event) -> str:
        tree = event.widget
        row_id = tree.identify_row(event.y)
        if row_id:
            tree.selection_set(row_id)
            tree.focus(row_id)
            self.edit_demand_object()
        return "break"

    def _edit_selected_demand_object_from_event(self, event: tk.Event) -> str:
        if event.widget.selection():
            self.edit_demand_object()
        return "break"

    def edit_hourly_demand_schedule(self) -> None:
        selected_name = self._selected_schedule_name()
        if selected_name is None:
            return
        self.config_model.demand.active_hourly_schedule_name = selected_name
        self.config_model.demand.hourly_weekly_fractions = copy.deepcopy(
            self.config_model.demand.hourly_schedule_library[selected_name]
        )
        schedule_type = self.config_model.demand.hourly_schedule_types.get(
            selected_name, FRACTIONAL_SCHEDULE_TYPE
        )
        dialog = HourlyDemandScheduleDialog(
            self, self.config_model, schedule_type=schedule_type
        )
        self.wait_window(dialog)
        if dialog.saved:
            self.hourly_schedule_enabled_var.set(True)
            self.config_model.demand.hourly_schedule_library[selected_name] = copy.deepcopy(
                self.config_model.demand.hourly_weekly_fractions
            )
            self.hourly_schedule_summary_var.set("Custom typical-week hourly profile")
            self._refresh_schedule_management()

    def create_hourly_demand_schedule(self) -> None:
        library = self.config_model.demand.hourly_schedule_library
        name = self._unique_schedule_name("Typical week demand")
        library[name] = default_hourly_weekly_fractions()
        self.config_model.demand.hourly_schedule_types[name] = (
            FRACTIONAL_SCHEDULE_TYPE
        )
        self.config_model.demand.hourly_schedule_months[name] = list(range(1, 13))
        self.config_model.demand.active_hourly_schedule_name = name
        self.config_model.demand.hourly_schedule_enabled = True
        self.hourly_schedule_enabled_var.set(True)
        self.hourly_schedule_summary_var.set("New even 24-hour demand profile")
        self._refresh_schedule_management(select_name=name)
        self.after_idle(self.edit_hourly_demand_schedule)

    def duplicate_hourly_demand_schedule(self) -> None:
        source_name = self._selected_schedule_name()
        if source_name is None:
            return
        name = self._unique_schedule_name(f"{source_name} copy")
        self.config_model.demand.hourly_schedule_library[name] = copy.deepcopy(
            self.config_model.demand.hourly_schedule_library[source_name]
        )
        self.config_model.demand.hourly_schedule_types[name] = (
            self.config_model.demand.hourly_schedule_types.get(
                source_name, FRACTIONAL_SCHEDULE_TYPE
            )
        )
        self.config_model.demand.hourly_schedule_months[name] = schedule_months_for(
            self.config_model.demand, source_name
        )
        self.config_model.demand.active_hourly_schedule_name = name
        self.config_model.demand.hourly_schedule_enabled = True
        self.hourly_schedule_enabled_var.set(True)
        self.hourly_schedule_summary_var.set(f"Duplicate of {source_name}")
        self._refresh_schedule_management(select_name=name)

    def rename_hourly_demand_schedule(self) -> None:
        selected_name = self._selected_schedule_name()
        if selected_name is None:
            return
        new_name = self.schedule_name_var.get().strip()
        if not new_name:
            messagebox.showwarning(APP_TITLE, "Schedule name cannot be blank.", parent=self)
            self.schedule_name_entry.focus_set()
            return
        library = self.config_model.demand.hourly_schedule_library
        if new_name != selected_name and any(
            name.casefold() == new_name.casefold() for name in library if name != selected_name
        ):
            messagebox.showwarning(APP_TITLE, f"A schedule named '{new_name}' already exists.", parent=self)
            self.schedule_name_entry.focus_set()
            return
        if new_name == selected_name:
            return
        renamed_items = [
            (new_name if name == selected_name else name, schedule)
            for name, schedule in library.items()
        ]
        library.clear()
        library.update(renamed_items)
        schedule_types = self.config_model.demand.hourly_schedule_types
        selected_type = schedule_types.pop(
            selected_name, FRACTIONAL_SCHEDULE_TYPE
        )
        schedule_types[new_name] = selected_type
        schedule_months = self.config_model.demand.hourly_schedule_months
        if selected_name in schedule_months:
            schedule_months[new_name] = schedule_months.pop(selected_name)
        for demand_object in self.config_model.demand.demand_objects:
            if demand_object.schedule_name == selected_name:
                demand_object.schedule_name = new_name
        self._populate_demand_objects()
        self.config_model.demand.active_hourly_schedule_name = new_name
        self.hourly_schedule_summary_var.set(f"Renamed schedule to: {new_name}")
        self._refresh_schedule_management(select_name=new_name)

    def _schedule_type_changed(self, _event: tk.Event | None = None) -> None:
        selected_name = self._selected_schedule_name()
        if selected_name is None:
            return
        schedule_type = SCHEDULE_TYPE_BY_LABEL.get(
            self.schedule_type_var.get(), FRACTIONAL_SCHEDULE_TYPE
        )
        fixture_users = [
            demand_object.name
            for demand_object in self.config_model.demand.demand_objects
            if demand_object.demand_mode == "fixture_usage"
            and demand_object.schedule_name == selected_name
        ]
        if schedule_type != OCCUPANCY_SCHEDULE_TYPE and fixture_users:
            messagebox.showwarning(
                APP_TITLE,
                f"Schedule '{selected_name}' is used by fixture demand object(s): "
                f"{', '.join(fixture_users)}. Assign an occupancy schedule before changing its type.",
                parent=self,
            )
            self.schedule_type_var.set(
                SCHEDULE_TYPE_LABELS[OCCUPANCY_SCHEDULE_TYPE]
            )
            return
        self.config_model.demand.hourly_schedule_types[selected_name] = schedule_type
        if schedule_type == OCCUPANCY_SCHEDULE_TYPE:
            schedule = self.config_model.demand.hourly_schedule_library[selected_name]
            for day in WEEKDAY_KEYS:
                schedule[day] = [
                    1.0 if float(value) > 0.0 else 0.0
                    for value in schedule.get(day, [])[:24]
                ]
                schedule[day].extend([0.0] * (24 - len(schedule[day])))
            if (
                self.config_model.demand.active_hourly_schedule_name
                == selected_name
            ):
                self.config_model.demand.hourly_weekly_fractions = copy.deepcopy(
                    schedule
                )
        self.hourly_schedule_summary_var.set(
            f"Schedule type: {SCHEDULE_TYPE_LABELS[schedule_type]}"
        )

    def _schedule_months_changed(self) -> None:
        selected_name = self._selected_schedule_name()
        if selected_name is None:
            return
        months = [
            month
            for month, variable in self.schedule_month_vars.items()
            if variable.get()
        ]
        self.config_model.demand.hourly_schedule_months[selected_name] = months
        label = "All months" if len(months) == 12 else (
            ", ".join(MONTH_KEYS[month - 1].title() for month in months)
            if months
            else "No active months"
        )
        self.hourly_schedule_summary_var.set(f"Active months: {label}")

    def _rename_schedule_from_event(self, _event: tk.Event) -> str:
        self.rename_hourly_demand_schedule()
        return "break"

    def _focus_schedule_name_from_event(self, _event: tk.Event) -> str:
        if self._selected_schedule_name() is not None:
            self.schedule_name_entry.focus_set()
            self.schedule_name_entry.selection_range(0, tk.END)
        return "break"

    def _selected_library_schedule(self) -> tuple[str, str] | None:
        if not hasattr(self, "library_tree"):
            return None
        selected = self.library_tree.selection()
        if not selected:
            return None
        return self.library_tree_item_map.get(selected[0])

    def _refresh_schedule_library(self, select_name: str | None = None) -> None:
        self.library_tree.delete(*self.library_tree.get_children())
        self.library_tree_item_map: dict[str, tuple[str, str]] = {}
        template_group = self.library_tree.insert("", "end", iid="library_templates", text="Templates", open=True, tags=("group",))
        custom_group = self.library_tree.insert("", "end", iid="library_custom", text="Custom", open=True, tags=("group",))
        selected_iid: str | None = None
        for index, name in enumerate(common_hourly_schedule_templates()):
            iid = f"library_template_{index}"
            self.library_tree.insert(template_group, "end", iid=iid, text=name)
            self.library_tree_item_map[iid] = ("template", name)
            if name == select_name:
                selected_iid = iid
        for index, name in enumerate(self.custom_schedule_templates):
            iid = f"library_custom_{index}"
            self.library_tree.insert(custom_group, "end", iid=iid, text=name)
            self.library_tree_item_map[iid] = ("custom", name)
            if name == select_name:
                selected_iid = iid
        if selected_iid is not None:
            self.library_tree.selection_set(selected_iid)
            self.library_tree.focus(selected_iid)
            self.library_tree.see(selected_iid)
        self._update_library_management_state()

    def _unique_library_name(self, base_name: str) -> str:
        existing = {name.casefold() for name in self.common_schedule_templates}
        if base_name.casefold() not in existing:
            return base_name
        suffix = 2
        while f"{base_name} {suffix}".casefold() in existing:
            suffix += 1
        return f"{base_name} {suffix}"

    def _save_library_changes(
        self,
        previous: dict[str, dict[str, list[float]]],
        previous_types: dict[str, str] | None = None,
        previous_months: dict[str, list[int]] | None = None,
    ) -> bool:
        try:
            self._save_custom_schedule_templates()
        except OSError as exc:
            self.custom_schedule_templates = previous
            if previous_types is not None:
                self.custom_schedule_template_types = previous_types
            if previous_months is not None:
                self.custom_schedule_template_months = previous_months
            self.common_schedule_templates = {
                **common_hourly_schedule_templates(),
                **self.custom_schedule_templates,
            }
            self.common_schedule_template_types = {
                **common_hourly_schedule_template_types(),
                **self.custom_schedule_template_types,
            }
            self.common_schedule_template_months = {
                **{
                    name: list(range(1, 13))
                    for name in common_hourly_schedule_templates()
                },
                **self.custom_schedule_template_months,
            }
            messagebox.showerror(APP_TITLE, f"Could not save the custom schedule library:\n{exc}", parent=self)
            return False
        self.common_schedule_templates = {
            **common_hourly_schedule_templates(),
            **self.custom_schedule_templates,
        }
        self.common_schedule_template_types = {
            **common_hourly_schedule_template_types(),
            **self.custom_schedule_template_types,
        }
        self.common_schedule_template_months = {
            **{
                name: list(range(1, 13))
                for name in common_hourly_schedule_templates()
            },
            **self.custom_schedule_template_months,
        }
        return True

    def create_custom_library_schedule(self) -> None:
        default_name = self._unique_library_name("Custom schedule")
        name = simpledialog.askstring(
            "Add custom library schedule",
            "Schedule name:",
            initialvalue=default_name,
            parent=self,
        )
        if name is None:
            return
        name = name.strip()
        if not name:
            messagebox.showwarning(APP_TITLE, "Schedule name cannot be blank.", parent=self)
            return
        if any(existing.casefold() == name.casefold() for existing in self.common_schedule_templates):
            messagebox.showwarning(APP_TITLE, f"A library schedule named '{name}' already exists.", parent=self)
            return
        temporary_config = default_project_config("Schedule library")
        temporary_config.demand.hourly_weekly_fractions = default_hourly_weekly_fractions()
        dialog = HourlyDemandScheduleDialog(
            self, temporary_config, schedule_type=FRACTIONAL_SCHEDULE_TYPE
        )
        self.wait_window(dialog)
        if not dialog.saved:
            return
        previous = copy.deepcopy(self.custom_schedule_templates)
        previous_types = dict(self.custom_schedule_template_types)
        previous_months = copy.deepcopy(self.custom_schedule_template_months)
        self.custom_schedule_templates[name] = copy.deepcopy(temporary_config.demand.hourly_weekly_fractions)
        self.custom_schedule_template_types[name] = FRACTIONAL_SCHEDULE_TYPE
        self.custom_schedule_template_months[name] = list(range(1, 13))
        if self._save_library_changes(previous, previous_types, previous_months):
            self._refresh_schedule_library(select_name=name)
            self.status_var.set(f"Added '{name}' to the custom schedule library")

    def duplicate_library_schedule(self) -> None:
        selected = self._selected_library_schedule()
        if selected is None:
            return
        _kind, source_name = selected
        source = self.common_schedule_templates[source_name]
        name = self._unique_library_name(f"{source_name} copy")
        previous = copy.deepcopy(self.custom_schedule_templates)
        previous_types = dict(self.custom_schedule_template_types)
        previous_months = copy.deepcopy(self.custom_schedule_template_months)
        self.custom_schedule_templates[name] = copy.deepcopy(source)
        self.custom_schedule_template_types[name] = (
            self.common_schedule_template_types.get(
                source_name, FRACTIONAL_SCHEDULE_TYPE
            )
        )
        self.custom_schedule_template_months[name] = list(
            self.common_schedule_template_months.get(source_name, range(1, 13))
        )
        if self._save_library_changes(previous, previous_types, previous_months):
            self._refresh_schedule_library(select_name=name)
            self.status_var.set(f"Duplicated '{source_name}' in the custom schedule library")

    def delete_custom_library_schedule(self) -> None:
        selected = self._selected_library_schedule()
        if selected is None or selected[0] != "custom":
            return
        name = selected[1]
        if not messagebox.askyesno(
            APP_TITLE,
            f"Delete custom library schedule '{name}'?",
            parent=self,
        ):
            return
        previous = copy.deepcopy(self.custom_schedule_templates)
        previous_types = dict(self.custom_schedule_template_types)
        previous_months = copy.deepcopy(self.custom_schedule_template_months)
        del self.custom_schedule_templates[name]
        self.custom_schedule_template_types.pop(name, None)
        self.custom_schedule_template_months.pop(name, None)
        if self._save_library_changes(previous, previous_types, previous_months):
            self._refresh_schedule_library()
            self.status_var.set(f"Deleted '{name}' from the custom schedule library")

    def _library_selection_changed(self, _event: tk.Event | None = None) -> None:
        self._update_library_management_state()

    def _update_library_management_state(self) -> None:
        selected = self._selected_library_schedule()
        has_schedule = selected is not None
        is_custom = has_schedule and selected[0] == "custom"
        if hasattr(self, "library_duplicate_button"):
            self.library_duplicate_button.state(["!disabled"] if has_schedule else ["disabled"])
        if hasattr(self, "library_delete_button"):
            self.library_delete_button.state(["!disabled"] if is_custom else ["disabled"])
        if hasattr(self, "add_library_schedule_to_project_button"):
            self.add_library_schedule_to_project_button.state(["!disabled"] if has_schedule else ["disabled"])

    def add_common_hourly_schedule(self) -> None:
        selected = self._selected_library_schedule()
        if selected is None:
            return
        _kind, template_name = selected
        template = self.common_schedule_templates.get(template_name)
        if template is None:
            return
        name = self._unique_schedule_name(template_name)
        self.config_model.demand.hourly_schedule_library[name] = copy.deepcopy(template)
        self.config_model.demand.hourly_schedule_types[name] = (
            self.common_schedule_template_types.get(
                template_name, FRACTIONAL_SCHEDULE_TYPE
            )
        )
        self.config_model.demand.hourly_schedule_months[name] = list(
            self.common_schedule_template_months.get(template_name, range(1, 13))
        )
        self.config_model.demand.active_hourly_schedule_name = name
        self.config_model.demand.hourly_weekly_fractions = copy.deepcopy(template)
        self.config_model.demand.hourly_schedule_enabled = True
        self.hourly_schedule_enabled_var.set(True)
        self.hourly_schedule_summary_var.set(f"Added common schedule: {template_name}")
        self._refresh_schedule_management(select_name=name)

    def _add_library_schedule_from_event(self, event: tk.Event) -> str:
        if getattr(event, "y", None) is not None:
            row_id = self.library_tree.identify_row(event.y)
            if row_id in self.library_tree_item_map:
                self.library_tree.selection_set(row_id)
                self.library_tree.focus(row_id)
        if self._selected_library_schedule() is not None:
            self.add_common_hourly_schedule()
        return "break"

    def save_selected_schedule_to_library(self) -> None:
        selected_name = self._selected_schedule_name()
        if selected_name is None:
            return
        built_in_names = common_hourly_schedule_templates()
        if any(name.casefold() == selected_name.casefold() for name in built_in_names):
            messagebox.showwarning(
                APP_TITLE,
                "Built-in schedule names are reserved. Rename the project schedule before adding it to the library.",
                parent=self,
            )
            return
        existing_name = next(
            (name for name in self.custom_schedule_templates if name.casefold() == selected_name.casefold()),
            None,
        )
        if existing_name is not None and not messagebox.askyesno(
            APP_TITLE,
            f"Replace the custom library schedule '{existing_name}'?",
            parent=self,
        ):
            return
        previous = copy.deepcopy(self.custom_schedule_templates)
        previous_types = dict(self.custom_schedule_template_types)
        previous_months = copy.deepcopy(self.custom_schedule_template_months)
        if existing_name is not None and existing_name != selected_name:
            del self.custom_schedule_templates[existing_name]
            self.custom_schedule_template_types.pop(existing_name, None)
            self.custom_schedule_template_months.pop(existing_name, None)
        schedule = copy.deepcopy(self.config_model.demand.hourly_schedule_library[selected_name])
        self.custom_schedule_templates[selected_name] = schedule
        self.custom_schedule_template_types[selected_name] = (
            self.config_model.demand.hourly_schedule_types.get(
                selected_name, FRACTIONAL_SCHEDULE_TYPE
            )
        )
        self.custom_schedule_template_months[selected_name] = schedule_months_for(
            self.config_model.demand, selected_name
        )
        if not self._save_library_changes(previous, previous_types, previous_months):
            return
        self._refresh_schedule_library(select_name=selected_name)
        self.hourly_schedule_summary_var.set(f"Saved to common schedule library: {selected_name}")
        self.status_var.set(f"Added '{selected_name}' to the common schedule library")

    def delete_hourly_demand_schedule(self) -> None:
        selected_name = self._selected_schedule_name()
        if selected_name is None:
            return
        users = [
            demand_object.name
            for demand_object in self.config_model.demand.demand_objects
            if demand_object.schedule_name == selected_name
        ]
        if users:
            messagebox.showwarning(
                APP_TITLE,
                f"Schedule '{selected_name}' is used by demand object(s): {', '.join(users)}. "
                "Assign another schedule before deleting it.",
                parent=self,
            )
            return
        if not messagebox.askyesno(
            APP_TITLE,
            "Delete the typical-week hourly demand schedule? Demand timing will switch to Daily.",
            parent=self,
        ):
            return
        del self.config_model.demand.hourly_schedule_library[selected_name]
        self.config_model.demand.hourly_schedule_types.pop(selected_name, None)
        self.config_model.demand.hourly_schedule_months.pop(selected_name, None)
        library = self.config_model.demand.hourly_schedule_library
        if library:
            active_name = next(iter(library))
            self.config_model.demand.active_hourly_schedule_name = active_name
            self.config_model.demand.hourly_weekly_fractions = copy.deepcopy(library[active_name])
        else:
            self.config_model.demand.hourly_schedule_enabled = False
            self.hourly_schedule_enabled_var.set(False)
            self.config_model.demand.hourly_weekly_fractions = default_hourly_weekly_fractions()
            self.hourly_schedule_summary_var.set("No hourly demand schedule")
        self._refresh_schedule_management()

    def _hourly_schedule_enabled_changed(self) -> None:
        if self.hourly_schedule_enabled_var.get() and not self.config_model.demand.hourly_schedule_library:
            name = "Typical week demand"
            self.config_model.demand.hourly_schedule_library[name] = copy.deepcopy(
                self.config_model.demand.hourly_weekly_fractions
            )
            self.config_model.demand.hourly_schedule_types[name] = (
                FRACTIONAL_SCHEDULE_TYPE
            )
            self.config_model.demand.hourly_schedule_months[name] = list(range(1, 13))
            self.config_model.demand.active_hourly_schedule_name = name
        self.config_model.demand.hourly_schedule_enabled = bool(self.hourly_schedule_enabled_var.get())
        self.curve_df = pd.DataFrame()
        self.results_df = pd.DataFrame()
        self.hourly_results_df = pd.DataFrame()
        self.reliability_var.set("Reliability: --")
        self._clear_results()
        self._refresh_schedule_management()

    def purge_unused_schedule_objects(self) -> None:
        demand = self.config_model.demand
        unused_names = unused_hourly_schedule_names(demand)
        if not unused_names:
            messagebox.showinfo(
                APP_TITLE,
                "No unused project schedule objects were found.",
                parent=self,
            )
            return
        schedule_list = "\n".join(f"- {name}" for name in unused_names)
        if not messagebox.askyesno(
            APP_TITLE,
            f"Purge {len(unused_names)} unused project schedule object(s)?\n\n"
            f"{schedule_list}\n\nThis cannot be undone after the project is saved.",
            parent=self,
        ):
            return
        removed = purge_unused_hourly_schedules(demand)
        self.hourly_schedule_summary_var.set(
            f"Purged {len(removed)} unused schedule object(s)"
        )
        self.status_var.set(
            f"Purged {len(removed)} unused project schedule object(s)"
        )
        self._refresh_schedule_management(
            select_name=demand.active_hourly_schedule_name
        )

    def _synthetic_hourly_rainfall_setting_changed(self) -> None:
        self.config_model.use_synthetic_hourly_rainfall = bool(
            self.use_synthetic_hourly_rainfall_var.get()
        )
        self.curve_df = pd.DataFrame()
        self.results_df = pd.DataFrame()
        self.reliability_var.set("Reliability: --")
        self._clear_results()
        self._refresh_synthetic_hourly_rainfall_status()

    def _refresh_synthetic_hourly_rainfall_status(self) -> None:
        if not hasattr(self, "synthetic_hourly_rainfall_status_var"):
            return
        enabled = bool(self.use_synthetic_hourly_rainfall_var.get())
        available = has_hourly_rainfall(self.rainfall_df)
        if enabled and available:
            message = (
                "Synthetic hourly profiles will be used for hourly collection and first-flush timing. "
                "The daily mass balance continues to use the source daily totals."
            )
        elif enabled:
            message = (
                "Synthetic hourly rainfall is selected, but no generated profiles are available. "
                "Generate them under Rainwater Data > Hourly rainfall before running analysis."
            )
        elif available:
            message = (
                "A synthetic hourly profile is available but not selected. The hourly simulation "
                "applies each daily rainfall total at 23:00."
            )
        else:
            message = (
                "Synthetic hourly rainfall is not used. Each daily rainfall total is applied at "
                "23:00 during hourly analysis."
            )
        self.synthetic_hourly_rainfall_status_var.set(message)
        if hasattr(self, "hourly_profile_reference_var"):
            reference = (
                "Hourly profile: Synthetic profile generated - manage in Hourly rainfall."
                if available
                else "Hourly profile: Not generated - manage in Hourly rainfall."
            )
            self.hourly_profile_reference_var.set(reference)
        if hasattr(self, "generate_hourly_rainfall_button"):
            self.generate_hourly_rainfall_button.configure(
                text=(
                    "Regenerate Synthetic Hourly Rainfall..."
                    if available
                    else "Generate Synthetic Hourly Rainfall..."
                ),
                state="normal" if not self.rainfall_df.empty else "disabled",
            )
        if hasattr(self, "remove_hourly_rainfall_button"):
            self.remove_hourly_rainfall_button.configure(
                state="normal" if available else "disabled"
            )
        if hasattr(self, "analysis_generate_hourly_rainfall_button"):
            self.analysis_generate_hourly_rainfall_button.configure(
                text=(
                    "Regenerate hourly profile..."
                    if available
                    else "Generate hourly profile..."
                )
            )
        self._refresh_applied_analysis_settings()
        self._refresh_hourly_profile_preview()

    def _refresh_applied_analysis_settings(self) -> None:
        """Summarize the timing assumptions currently applied by analysis."""
        required_variables = (
            "applied_analysis_resolution_var",
            "applied_rainfall_source_var",
            "applied_demand_timing_var",
            "applied_rainfall_timing_var",
        )
        if not all(hasattr(self, name) for name in required_variables):
            return

        hourly_enabled = bool(self.hourly_schedule_enabled_var.get())
        available = has_hourly_rainfall(self.rainfall_df)
        active_name = self.config_model.demand.active_hourly_schedule_name
        schedule_selection_var = self.__dict__.get(
            "hourly_demand_schedule_selection_var"
        )
        if schedule_selection_var is not None:
            schedule_selection_var.set(active_name)
        resolution = (
            "Daily mass balance for sizing + full hourly selected-tank simulation"
            if hourly_enabled
            else "Daily mass balance only"
        )
        demand_timing = (
            f"Hourly profile applied hour by hour (schedule: {active_name})"
            if hourly_enabled
            else "Daily demand totals; hourly profile is preserved but not simulated"
        )
        if not hourly_enabled:
            rainfall_timing = "Hourly rainfall timing is not simulated; daily source totals are used"
        elif bool(self.use_synthetic_hourly_rainfall_var.get()):
            if available:
                seed_match = re.search(
                    r"\(seed (\d+)\)", self.config_model.rainfall_timing_type
                )
                seed_suffix = f" (seed {seed_match.group(1)})" if seed_match else ""
                rainfall_timing = (
                    "Synthetic hourly profile derived from each daily rainfall total"
                    + seed_suffix
                )
            else:
                rainfall_timing = (
                    "Synthetic hourly timing selected, but no profile has been generated"
                )
        else:
            rainfall_timing = "Each daily rainfall total is applied at 23:00"

        self.applied_analysis_resolution_var.set(resolution)
        rainfall_source = (
            "Not loaded"
            if self.rainfall_df.empty
            else self.config_model.rainfall_source_label or "Loaded daily rainfall record"
        )
        self.applied_rainfall_source_var.set(rainfall_source)
        self.applied_demand_timing_var.set(demand_timing)
        self.applied_rainfall_timing_var.set(rainfall_timing)

        enabled_state = ["!disabled"] if hourly_enabled else ["disabled"]
        hourly_schedule_change_button = self.__dict__.get(
            "hourly_schedule_change_button"
        )
        if hourly_schedule_change_button is not None:
            hourly_schedule_change_button.state(enabled_state)
        daily_rainfall_timing_radio = self.__dict__.get(
            "daily_rainfall_timing_radio"
        )
        if daily_rainfall_timing_radio is not None:
            daily_rainfall_timing_radio.state(["!disabled"])
        synthetic_hourly_rainfall_radio = self.__dict__.get(
            "synthetic_hourly_rainfall_radio"
        )
        if synthetic_hourly_rainfall_radio is not None:
            synthetic_hourly_rainfall_radio.state(
                ["!disabled"] if available else ["disabled"]
            )
        analysis_generate_hourly_rainfall_button = self.__dict__.get(
            "analysis_generate_hourly_rainfall_button"
        )
        if analysis_generate_hourly_rainfall_button is not None:
            analysis_generate_hourly_rainfall_button.state(
                ["!disabled"]
                if not self.rainfall_df.empty
                else ["disabled"]
            )

    def _refresh_schedule_management(self, select_name: str | None = None) -> None:
        if not hasattr(self, "schedule_list"):
            self._refresh_applied_analysis_settings()
            return
        self.schedule_list.delete(0, tk.END)
        library = self.config_model.demand.hourly_schedule_library
        if self.hourly_schedule_enabled_var.get() and not library:
            active_name = self.config_model.demand.active_hourly_schedule_name
            library[active_name] = copy.deepcopy(self.config_model.demand.hourly_weekly_fractions)
            self.config_model.demand.hourly_schedule_types[active_name] = (
                FRACTIONAL_SCHEDULE_TYPE
            )
            self.config_model.demand.hourly_schedule_months.setdefault(
                active_name, list(range(1, 13))
            )
        names = list(library)
        for name in names:
            self.schedule_list.insert(tk.END, name)
        target = select_name or self.config_model.demand.active_hourly_schedule_name
        if target in names:
            index = names.index(target)
            self.schedule_list.selection_set(index)
            self.schedule_list.see(index)
            self.schedule_name_var.set(target)
            self.schedule_type_var.set(
                SCHEDULE_TYPE_LABELS[
                    self.config_model.demand.hourly_schedule_types.get(
                        target, FRACTIONAL_SCHEDULE_TYPE
                    )
                ]
            )
            active_months = set(schedule_months_for(self.config_model.demand, target))
            for month, variable in self.schedule_month_vars.items():
                variable.set(month in active_months)
        else:
            self.schedule_name_var.set("")
            self.schedule_type_var.set("")
            for variable in self.schedule_month_vars.values():
                variable.set(False)
        self._update_schedule_management_state()
        self._refresh_applied_analysis_settings()

    def _selected_schedule_name(self) -> str | None:
        selected = self.schedule_list.curselection() if hasattr(self, "schedule_list") else ()
        return str(self.schedule_list.get(selected[0])) if selected else None

    def _unique_schedule_name(self, base_name: str) -> str:
        library = self.config_model.demand.hourly_schedule_library
        if base_name not in library:
            return base_name
        suffix = 2
        while f"{base_name} {suffix}" in library:
            suffix += 1
        return f"{base_name} {suffix}"

    def _schedule_selection_changed(self, _event: tk.Event | None = None) -> None:
        selected_name = self._selected_schedule_name()
        if selected_name is not None:
            self.schedule_name_var.set(selected_name)
            self.schedule_type_var.set(
                SCHEDULE_TYPE_LABELS[
                    self.config_model.demand.hourly_schedule_types.get(
                        selected_name, FRACTIONAL_SCHEDULE_TYPE
                    )
                ]
            )
            self.config_model.demand.active_hourly_schedule_name = selected_name
            self.config_model.demand.hourly_weekly_fractions = copy.deepcopy(
                self.config_model.demand.hourly_schedule_library[selected_name]
            )
            active_months = set(
                schedule_months_for(self.config_model.demand, selected_name)
            )
            for month, variable in self.schedule_month_vars.items():
                variable.set(month in active_months)
            self.hourly_schedule_summary_var.set(f"Selected schedule: {selected_name}")
        self._update_schedule_management_state()
        self._refresh_applied_analysis_settings()

    def _update_schedule_management_state(self) -> None:
        has_schedule = bool(self.schedule_list.curselection()) if hasattr(self, "schedule_list") else False
        if hasattr(self, "schedule_delete_button"):
            self.schedule_delete_button.state(["!disabled"] if has_schedule else ["disabled"])
        if hasattr(self, "schedule_duplicate_button"):
            self.schedule_duplicate_button.state(["!disabled"] if has_schedule else ["disabled"])
        if hasattr(self, "edit_schedule_button"):
            self.edit_schedule_button.state(["!disabled"] if has_schedule else ["disabled"])
        if hasattr(self, "rename_schedule_button"):
            self.rename_schedule_button.state(["!disabled"] if has_schedule else ["disabled"])
        if hasattr(self, "schedule_name_entry"):
            self.schedule_name_entry.state(["!disabled"] if has_schedule else ["disabled"])
        if hasattr(self, "save_schedule_to_library_button"):
            self.save_schedule_to_library_button.state(["!disabled"] if has_schedule else ["disabled"])
        if hasattr(self, "schedule_type_combo"):
            self.schedule_type_combo.configure(
                state="readonly" if has_schedule else "disabled"
            )
        for checkbox in getattr(self, "schedule_month_checkbuttons", []):
            checkbox.state(["!disabled"] if has_schedule else ["disabled"])

    def _edit_demand_month_from_event(self, event: tk.Event) -> str:
        row_id = self.demand_tree.identify_row(event.y)
        if row_id:
            self.demand_tree.selection_set(row_id)
            self.demand_tree.focus(row_id)
            self.edit_demand_month()
        return "break"

    def run_single_tank_analysis(self) -> None:
        self.run_analysis(include_comparisons=False)

    def run_multitank_analysis(self) -> None:
        self.run_analysis(include_comparisons=True)

    def run_analysis(self, *, include_comparisons: bool = False) -> None:
        if self.analysis_running:
            self.status_var.set("An analysis is already running")
            return
        self._apply_form_to_model()
        cfg = self.config_model
        compiled_system = compile_builder_system(
            cfg.system_type, cfg.system_layout, cfg.system_connections
        )
        warnings = self._refresh_system_builder_warnings()
        if compiled_system.uses_builder_graph and warnings:
            messagebox.showwarning(
                APP_TITLE,
                "Correct the system builder configuration before running analysis:\n\n"
                + "\n".join(f"- {warning}" for warning in warnings[:6]),
            )
            return
        if self.rainfall_df.empty:
            messagebox.showwarning(APP_TITLE, "Load rainfall data before running the analysis.")
            return
        if (
            cfg.demand.hourly_schedule_enabled
            and cfg.use_synthetic_hourly_rainfall
            and not has_hourly_rainfall(self.rainfall_df)
        ):
            messagebox.showwarning(
                APP_TITLE,
                "Synthetic hourly rainfall is selected, but no generated profiles are available. "
                "Generate them on the Rainfall Data tab or turn the option off in Analysis settings.",
            )
            return
        if cfg.graph_end_gal <= cfg.graph_start_gal:
            messagebox.showwarning(APP_TITLE, "Graph end tank size must be greater than graph start tank size.")
            return
        if cfg.selected_tank_size_gal <= 0:
            messagebox.showwarning(APP_TITLE, "Selected tank size must be greater than zero.")
            return
        if cfg.selected_tank_size_gal > cfg.graph_end_gal:
            messagebox.showwarning(APP_TITLE, "Selected tank size cannot be greater than the graph end tank size.")
            return
        if include_comparisons and not cfg.multitank_comparison_enabled:
            messagebox.showwarning(
                APP_TITLE,
                "Enable Multi-tank comparison in Analysis settings before running a multi-tank analysis.",
            )
            return
        if include_comparisons and not cfg.comparison_tank_sizes_gal:
            messagebox.showwarning(APP_TITLE, "Add at least one comparison tank size before running a multi-tank analysis.")
            return
        oversized_comparisons = [
            size for size in cfg.comparison_tank_sizes_gal
            if include_comparisons and size > cfg.graph_end_gal
        ]
        if oversized_comparisons:
            messagebox.showwarning(APP_TITLE, "Comparison tank sizes cannot be greater than the graph end tank size.")
            return
        analysis_label = "Multi-tank analysis" if include_comparisons else "Single-tank analysis"
        analysis_started = time.perf_counter()
        self.execution_log.info("Analysis", f"{analysis_label} started")
        self.execution_log.diagnostic(
            "Analysis",
            "Prepared analysis inputs",
            details=(
                f"rainfall_rows={len(self.rainfall_df):,}; surfaces={len(cfg.surfaces)}; "
                f"selected_tank={cfg.selected_tank_size_gal:g}; "
                f"demand_timing={'hourly' if cfg.demand.hourly_schedule_enabled else 'daily'}"
            ),
        )
        self.analysis_running = True
        self.analysis_cancel_requested = False
        self.cancel_analysis_button.state(["!disabled"])
        self.analysis_progress.configure(style="Analysis.Horizontal.TProgressbar")
        self.analysis_progress_var.set(0)
        self.status_var.set(f"{analysis_label} running: preparing inputs")
        analysis_config = copy.deepcopy(cfg)
        analysis_rainfall = self.rainfall_df.copy(deep=True)
        self.analysis_active_label = analysis_label
        self.analysis_started_at = analysis_started
        self.analysis_started_signature = analysis_input_signature(
            analysis_config, analysis_rainfall
        )
        self.analysis_started_unit_system = analysis_config.unit_system
        self.analysis_result_queue = queue.Queue()

        def run_in_background() -> None:
            try:
                outcome = AnalysisService().run(
                    analysis_config,
                    analysis_rainfall,
                    include_comparisons=include_comparisons,
                    progress_callback=lambda event: self.analysis_result_queue.put(
                        ("progress", event)
                    ),
                    cancel_callback=lambda: self.analysis_cancel_requested,
                )
            except AnalysisCancelledError as exc:
                self.analysis_result_queue.put(("cancelled", exc))
            except Exception as exc:  # noqa: BLE001
                self.analysis_result_queue.put(("error", exc))
            else:
                self.analysis_result_queue.put(("complete", outcome))

        self.analysis_thread = threading.Thread(
            target=run_in_background,
            name="rainwater-analysis",
            daemon=True,
        )
        self.analysis_thread.start()
        self.analysis_poll_after_id = self.after(50, self._poll_analysis_results)

    def _apply_analysis_progress(self, event: AnalysisProgressEvent) -> None:
        analysis_label = self.analysis_active_label
        if event.phase == "reliability_curve":
            part_progress = event.current / event.total if event.total else 1.0
            self.analysis_progress_var.set(part_progress * 50.0)
            self.status_var.set(
                f"{analysis_label} running: Part A - reliability curve "
                f"({event.current}/{event.total})"
            )
        elif event.phase == "selected_tank":
            self.analysis_progress_var.set(50)
            self.status_var.set(
                f"{analysis_label} running: Part B - selected tank simulation"
            )
            self.execution_log.info("Analysis", "Simulating the selected tank")
        else:
            self.status_var.set(
                f"{analysis_label} running: Part B - comparison tank simulation "
                f"({event.current}/{event.total})"
            )

    def _poll_analysis_results(self) -> None:
        self.analysis_poll_after_id = None
        terminal: tuple[str, object] | None = None
        while True:
            try:
                kind, payload = self.analysis_result_queue.get_nowait()
            except queue.Empty:
                break
            if kind == "progress":
                self._apply_analysis_progress(payload)  # type: ignore[arg-type]
            else:
                terminal = (kind, payload)
        if terminal is None:
            if self.analysis_running:
                self.analysis_poll_after_id = self.after(
                    50, self._poll_analysis_results
                )
            return
        kind, payload = terminal
        if kind == "complete":
            try:
                self._complete_analysis(payload)  # type: ignore[arg-type]
            except Exception as exc:  # noqa: BLE001
                self.analysis_progress_var.set(0)
                self.status_var.set(f"{self.analysis_active_label} failed")
                self.execution_log.error(
                    "Analysis",
                    f"{self.analysis_active_label} failed while drawing results",
                    exception=exc,
                )
                messagebox.showerror(
                    APP_TITLE, f"{self.analysis_active_label} failed:\n{exc}"
                )
                self._finish_analysis_run()
        elif kind == "cancelled":
            self.analysis_progress_var.set(0)
            self.status_var.set(
                f"{self.analysis_active_label} cancelled; previous completed results retained"
            )
            self.execution_log.warning(
                "Analysis", f"{self.analysis_active_label} cancelled"
            )
            self._finish_analysis_run()
        else:
            exc = payload
            self.analysis_progress_var.set(0)
            self.status_var.set(f"{self.analysis_active_label} failed")
            self.execution_log.error(
                "Analysis", f"{self.analysis_active_label} failed", exception=exc
            )
            messagebox.showerror(
                APP_TITLE, f"{self.analysis_active_label} failed:\n{exc}"
            )
            self._finish_analysis_run()

    def _complete_analysis(self, outcome: AnalysisOutcome) -> None:
        self.curve_df = outcome.curve
        self.results_df = outcome.selected_tank
        self.hourly_results_df = outcome.hourly_selected_tank
        self.comparison_results = outcome.comparison_tanks
        self._populate_comparison_tanks()
        self.analysis_progress_var.set(75)
        self.status_var.set(
            f"{self.analysis_active_label} running: drawing results"
        )
        self.execution_log.info("Analysis", "Rendering analysis results")
        self.update_idletasks()
        reliability = (
            float(self.results_df["ReliabilityPercent"].iloc[0])
            if not self.results_df.empty
            else 0.0
        )
        self._set_selected_tank_reliability(reliability)
        self._populate_results()
        self.update_financial_analysis(show_errors=False)
        self._draw_saved_analysis_charts()
        self.config_model.analysis_input_signature = self.analysis_started_signature
        self.config_model.analysis_unit_system = self.analysis_started_unit_system
        self.last_analysis_warning_key = None
        self.analysis_progress_var.set(100)
        self.status_var.set(f"{self.analysis_active_label} complete")
        self.execution_log.info(
            "Analysis",
            f"{self.analysis_active_label} completed in "
            f"{time.perf_counter() - self.analysis_started_at:.2f} seconds",
        )
        self._finish_analysis_run()

    def _finish_analysis_run(self) -> None:
        self.analysis_running = False
        self.analysis_cancel_requested = False
        self.analysis_thread = None
        self.cancel_analysis_button.state(["disabled"])

    def cancel_analysis(self) -> None:
        if not self.analysis_running:
            return
        self.analysis_cancel_requested = True
        self.status_var.set(f"Cancelling {self.analysis_active_label.lower()}...")
        self.cancel_analysis_button.state(["disabled"])

    def export_results(self) -> None:
        if self.results_df.empty:
            messagebox.showinfo(APP_TITLE, "Run the analysis before exporting results.")
            return
        path = filedialog.asksaveasfilename(
            title="Export results",
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv")],
        )
        if not path:
            return
        try:
            self.execution_log.info("Export", "Exporting analysis results")
            self._display_results_df().to_csv(path, index=False, quoting=csv.QUOTE_MINIMAL)
            self.status_var.set(f"Exported results to {Path(path).name}")
            self.execution_log.info("Export", f"Exported results to {Path(path).name}")
        except Exception as exc:  # noqa: BLE001
            self.execution_log.error("Export", "Could not export results", exception=exc)
            messagebox.showerror(APP_TITLE, f"Could not export results:\n{exc}")

    def view_pdf_report(self) -> None:
        report = self._request_report_content("PDF")
        if report is None:
            return
        preview_dir = self._new_report_preview_directory()
        pdf_path = preview_dir / self._default_report_filename(".pdf")
        try:
            self.execution_log.info("Report", "Generating PDF report preview")
            self._drain_execution_log_to_window()
            self.update_idletasks()
            self._write_pdf_report(pdf_path, report)
            self._open_local_file(pdf_path)
            self.status_var.set(f"Opened PDF report preview: {pdf_path.name}")
            self.execution_log.info("Report", "PDF report preview opened")
        except Exception as exc:  # noqa: BLE001
            self.execution_log.error("Report", "Could not view PDF report", exception=exc)
            messagebox.showerror(APP_TITLE, f"Could not view PDF report:\n{exc}")

    def view_html_report(self) -> None:
        report = self._request_report_content("HTML")
        if report is None:
            return
        preview_dir = self._new_report_preview_directory()
        html_path = preview_dir / self._default_report_filename(".html")
        try:
            self.execution_log.info("Report", "Generating HTML report preview")
            self._drain_execution_log_to_window()
            self.update_idletasks()
            self._write_html_report(html_path, report)
            self._open_html_preview(html_path)
            self.status_var.set(f"Opened HTML report preview: {html_path.name}")
            self.execution_log.info("Report", "HTML report preview opened")
        except Exception as exc:  # noqa: BLE001
            self.execution_log.error("Report", "Could not view HTML report", exception=exc)
            messagebox.showerror(APP_TITLE, f"Could not view HTML report:\n{exc}")

    def export_pdf_report(self) -> None:
        report = self._request_report_content("PDF")
        if report is None:
            return
        path = filedialog.asksaveasfilename(
            title="Export PDF report",
            initialfile=self._default_report_filename(".pdf"),
            defaultextension=".pdf",
            filetypes=[("PDF files", "*.pdf")],
        )
        if not path:
            return
        pdf_path = Path(path)
        try:
            self.execution_log.info("Report", "Exporting PDF report")
            self._drain_execution_log_to_window()
            self.update_idletasks()
            self._write_pdf_report(pdf_path, report)
            self.status_var.set(f"Exported PDF report: {pdf_path.name}")
            self.execution_log.info("Report", f"Exported PDF report {pdf_path.name}")
        except Exception as exc:  # noqa: BLE001
            self.execution_log.error("Report", "Could not export PDF report", exception=exc)
            messagebox.showerror(APP_TITLE, f"Could not export PDF report:\n{exc}")

    def export_html_report(self) -> None:
        report = self._request_report_content("HTML")
        if report is None:
            return
        path = filedialog.asksaveasfilename(
            title="Export HTML report",
            initialfile=self._default_report_filename(".html"),
            defaultextension=".html",
            filetypes=[("HTML files", "*.html;*.htm")],
        )
        if not path:
            return
        html_path = Path(path)
        try:
            self.execution_log.info("Report", "Exporting HTML report")
            self._drain_execution_log_to_window()
            self.update_idletasks()
            self._write_html_report(html_path, report)
            self.status_var.set(f"Exported HTML report: {html_path.name}")
            self.execution_log.info("Report", f"Exported HTML report {html_path.name}")
        except Exception as exc:  # noqa: BLE001
            self.execution_log.error("Report", "Could not export HTML report", exception=exc)
            messagebox.showerror(APP_TITLE, f"Could not export HTML report:\n{exc}")

    def _request_report_content(self, report_format: str) -> ReportModel | None:
        self._apply_form_to_model()
        self.execution_log.debug("Report", f"Preparing {report_format} report content")
        if self.curve_df.empty:
            article = "an" if report_format == "HTML" else "a"
            messagebox.showinfo(APP_TITLE, f"Run the analysis before generating {article} {report_format} report.")
            return None

        dialog = ReportDialog(self, self._default_report_metadata())
        self.wait_window(dialog)
        if dialog.result is None:
            self.execution_log.info("Report", f"{report_format} report generation cancelled")
            return None
        content = self._build_report_content(dialog.result)
        self.execution_log.debug("Report", f"Prepared {report_format} report content")
        return content

    def _default_report_filename(self, suffix: str) -> str:
        return _safe_project_file_name(self.config_model.name).replace(".db", f"_report{suffix}")

    def _write_pdf_report(
        self, pdf_path: Path, report: ReportModel | dict[str, object]
    ) -> None:
        report = ReportModel.from_payload(report)
        self.execution_log.debug("Report", "Building LaTeX report source")
        tex_path = pdf_path.with_suffix(".tex")
        latex = self._build_report_latex(report)
        atomic_write_text(tex_path, latex)
        temporary_pdf: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                prefix=f".{pdf_path.name}.",
                suffix=".tmp.pdf",
                dir=pdf_path.parent,
                delete=False,
            ) as handle:
                temporary_pdf = Path(handle.name)
            self._compile_latex_report(tex_path, temporary_pdf, report)
            if temporary_pdf.stat().st_size < 5 or temporary_pdf.read_bytes()[:5] != b"%PDF-":
                raise ValueError("Generated report is not a valid PDF artifact.")
            os.replace(temporary_pdf, pdf_path)
        finally:
            if temporary_pdf is not None and temporary_pdf.exists():
                temporary_pdf.unlink()

    def _write_html_report(
        self, html_path: Path, report: ReportModel | dict[str, object]
    ) -> None:
        report = ReportModel.from_payload(report)
        self.execution_log.debug("Report", "Building HTML report document")
        document = self._build_report_html(report)
        if "<!doctype html>" not in document.casefold():
            raise ValueError("Generated HTML report is missing its document declaration.")
        atomic_write_text(html_path, document)

    def _new_report_preview_directory(self) -> Path:
        preview = tempfile.TemporaryDirectory(prefix="rwh-calculator-report-")
        self.report_preview_directories.append(preview)
        return Path(preview.name)

    @staticmethod
    def _open_local_file(path: Path) -> None:
        resolved = path.resolve()
        if sys.platform == "win32":
            os.startfile(resolved)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(resolved)])
        else:
            subprocess.Popen(["xdg-open", str(resolved)])

    def _open_html_preview(self, html_path: Path) -> None:
        handler = partial(_QuietReportHandler, directory=str(html_path.parent))
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, name="rwh-report-preview", daemon=True)
        thread.start()
        self.report_preview_servers.append(server)
        port = server.server_address[1]
        webbrowser.open(f"http://127.0.0.1:{port}/{quote(html_path.name)}")

    def destroy(self) -> None:
        if getattr(self, "execution_log_poll_after_id", None) is not None:
            try:
                self.after_cancel(self.execution_log_poll_after_id)
            except tk.TclError:
                pass
            self.execution_log_poll_after_id = None
        if hasattr(self, "execution_log"):
            self.execution_log.info("Application", "Application closing")
            self.execution_log.close()
        for after_id_name in (
            "station_typeahead_after_id",
            "state_typeahead_after_id",
            "country_typeahead_after_id",
            "station_map_redraw_after_id",
            "climate_normal_archive_poll_after_id",
            "analysis_poll_after_id",
        ):
            after_id = getattr(self, after_id_name, None)
            if after_id is not None:
                try:
                    self.after_cancel(after_id)
                except tk.TclError:
                    pass
                setattr(self, after_id_name, None)
        if self.station_lookup_poll_after_id is not None:
            self.after_cancel(self.station_lookup_poll_after_id)
            self.station_lookup_poll_after_id = None
        if self.location_poll_after_id is not None:
            self.after_cancel(self.location_poll_after_id)
            self.location_poll_after_id = None
        for server in self.report_preview_servers:
            server.shutdown()
            server.server_close()
        self.report_preview_servers.clear()
        for preview in self.report_preview_directories:
            preview.cleanup()
        self.report_preview_directories.clear()
        climate_normal_executor = getattr(self, "climate_normal_detail_executor", None)
        if climate_normal_executor is not None:
            climate_normal_executor.shutdown(wait=False, cancel_futures=True)
        if hasattr(self, "station_map") and self.station_map.winfo_exists():
            self.station_map.destroy()
        super().destroy()

    def _default_report_metadata(self) -> dict[str, object]:
        end_uses = self._default_end_uses_text()
        address_parts = [
            self.street_address_var.get().strip(),
            self.city_var.get().strip(),
            self.state_or_province_var.get().strip(),
            self.postal_code_var.get().strip(),
        ]
        location = ", ".join(part for part in address_parts if part)
        if location:
            country = self.country_var.get().split(" - ", 1)[-1].strip()
            location = f"{location}, {country}" if country else location
        if not location:
            location = self.rainfall_source_label or self.config_model.rainfall_source_label or ""
        return {
            "client_name": "",
            "date": dt.date.today().isoformat(),
            "location": location,
            "project_name": self.project_name_var.get().strip() or self.config_model.name,
            "author_name": self.author_name_var.get().strip(),
            "end_uses": end_uses,
        }

    def _default_end_uses_text(self) -> str:
        uses = [
            demand_object.object_type or demand_object.name
            for demand_object in self.config_model.demand.demand_objects
        ]
        return ", ".join(dict.fromkeys(uses)) or "Not specified"

    def _report_weather_station_coordinates(self) -> tuple[float | None, float | None]:
        cfg = self.config_model
        if cfg.weather_station_latitude is not None and cfg.weather_station_longitude is not None:
            return cfg.weather_station_latitude, cfg.weather_station_longitude
        source = self.rainfall_source_label or cfg.rainfall_source_label or ""
        identifiers = re.findall(r"\(([^()]+)\)", source)
        if not identifiers:
            return None, None
        station_id = identifiers[-1].strip()
        station = next(
            (item for item in self.station_options if str(item.get("sid", "")) == station_id),
            None,
        )
        coordinates = self._station_coordinates(station) if station is not None else None
        return coordinates if coordinates is not None else (None, None)

    @staticmethod
    def _average_annual_result_total(results: pd.DataFrame, column: str) -> float:
        if results.empty or "Date" not in results or column not in results:
            return 0.0
        values = results[["Date", column]].copy()
        values["Date"] = pd.to_datetime(values["Date"], errors="coerce")
        values[column] = pd.to_numeric(values[column], errors="coerce").fillna(0.0)
        values = values.dropna(subset=["Date"])
        annual = values.groupby(values["Date"].dt.year)[column].sum()
        return float(annual.mean()) if not annual.empty else 0.0

    def _report_end_use_rows(self) -> list[dict[str, object]]:
        cfg = self.config_model
        if self.results_df.empty or "Date" not in self.results_df:
            return []
        dates = pd.to_datetime(self.results_df["Date"], errors="coerce")
        total_demand = pd.to_numeric(
            self.results_df.get("DemandGallons", pd.Series(0.0, index=self.results_df.index)),
            errors="coerce",
        ).fillna(0.0)
        supplied = pd.to_numeric(
            self.results_df.get("RainwaterSuppliedGallons", pd.Series(0.0, index=self.results_df.index)),
            errors="coerce",
        ).fillna(0.0)
        water_rate = tariff_rate_per_gallon(
            cfg.financial_parameters.water_rate, cfg.financial_parameters.tariff_billing_unit
        )
        sewer_rate = tariff_rate_per_gallon(
            cfg.financial_parameters.sewer_rate, cfg.financial_parameters.tariff_billing_unit
        )
        rows: list[dict[str, object]] = []
        assigned_demand = pd.Series(0.0, index=self.results_df.index)
        assigned_supply = pd.Series(0.0, index=self.results_df.index)

        def annual_average(values: pd.Series) -> float:
            frame = pd.DataFrame({"Date": dates, "Value": values}).dropna(subset=["Date"])
            annual = frame.groupby(frame["Date"].dt.year)["Value"].sum()
            return float(annual.mean()) if not annual.empty else 0.0

        for demand_object in cfg.demand.demand_objects:
            object_demand = pd.Series(
                [
                    0.0 if pd.isna(date) else demand_object_daily_value_for_date(
                        cfg.demand, demand_object, pd.Timestamp(date)
                    )
                    for date in dates
                ],
                index=self.results_df.index,
                dtype=float,
            )
            object_supply = supplied * object_demand.div(total_demand.where(total_demand > 0.0, 1.0))
            object_supply = object_supply.where(total_demand > 0.0, 0.0)
            sewer_fraction = demand_object_sewer_eligible_fraction(
                demand_object, cfg.financial_parameters.sewer_eligible_percent
            )
            annual_demand = annual_average(object_demand)
            annual_supply = annual_average(object_supply)
            sewer_supply = annual_supply * sewer_fraction
            mode = getattr(demand_object, "demand_mode", "scheduled_flow")
            if mode == "monthly_volume":
                schedule = "Monthly volume profile"
            elif mode in {"recurring_daily", "fixture_usage"}:
                labels = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
                occupancy_schedule = cfg.demand.hourly_schedule_library.get(
                    demand_object.schedule_name, {}
                )
                days = [
                    index
                    for index, day in enumerate(WEEKDAY_KEYS)
                    if any(
                        float(value) > 0.0
                        for value in occupancy_schedule.get(day, [])[:24]
                    )
                ]
                schedule = ", ".join(labels[int(day)] for day in days if 0 <= int(day) <= 6) or "No operating days"
                if mode == "fixture_usage":
                    fixture_volume = volume_to_display(
                        demand_object.fixture_volume_gallons_per_use, cfg
                    )
                    schedule = (
                        f"{schedule}; {demand_object.fixture_people:g} people x "
                        f"{demand_object.fixture_uses_per_person_per_day:g} uses/person/day x "
                        f"{fixture_volume:g} {volume_unit(cfg)}/use"
                    )
            else:
                schedule = demand_object.schedule_name or "Schedule not specified"
            sewer_basis = (
                f"Legacy aggregate ({sewer_fraction * 100.0:g}%)"
                if getattr(demand_object, "uses_legacy_sewer_eligibility", False)
                else ("Eligible" if sewer_fraction > 0.0 else "Exempt")
            )
            rows.append({
                "name": demand_object.name,
                "type": demand_object.object_type,
                "schedule": schedule,
                "sewer_basis": sewer_basis,
                "annual_demand": volume_to_display(annual_demand, cfg),
                "annual_supply": volume_to_display(annual_supply, cfg),
                "demand_met_percent": annual_supply / annual_demand * 100.0 if annual_demand > 0.0 else 0.0,
                "water_savings": annual_supply * water_rate,
                "sewer_savings": sewer_supply * sewer_rate,
            })
            assigned_demand += object_demand
            assigned_supply += object_supply

        legacy_demand = (total_demand - assigned_demand).clip(lower=0.0)
        if float(legacy_demand.sum()) > 1e-6:
            legacy_supply = (supplied - assigned_supply).clip(lower=0.0)
            annual_demand = annual_average(legacy_demand)
            annual_supply = annual_average(legacy_supply)
            sewer_fraction = min(max(cfg.financial_parameters.sewer_eligible_percent, 0.0), 100.0) / 100.0
            rows.append({
                "name": "Legacy aggregate demand",
                "type": "Legacy project inputs",
                "schedule": cfg.demand.active_hourly_schedule_name or "Project demand schedule",
                "sewer_basis": f"Legacy aggregate ({sewer_fraction * 100.0:g}%)",
                "annual_demand": volume_to_display(annual_demand, cfg),
                "annual_supply": volume_to_display(annual_supply, cfg),
                "demand_met_percent": annual_supply / annual_demand * 100.0 if annual_demand > 0.0 else 0.0,
                "water_savings": annual_supply * water_rate,
                "sewer_savings": annual_supply * sewer_fraction * sewer_rate,
            })
        return rows

    def _report_candidate_rows(self) -> list[dict[str, object]]:
        cfg = self.config_model
        data = self._candidate_performance_data()
        if data.empty:
            return []
        dates = pd.to_datetime(self.results_df.get("Date", pd.Series(dtype="datetime64[ns]")), errors="coerce")
        year_count = max(int(dates.dropna().dt.year.nunique()), 1)
        annual_columns = (
            "RainwaterSuppliedGallons", "MunicipalMakeupGallons", "SystemUnmetDemandGallons",
            "OverflowGallons", "FirstFlushLossGallons", "TreatmentLossGallons",
        )
        rows: list[dict[str, object]] = []
        for row in data.to_dict("records"):
            output: dict[str, object] = {
                "selected": abs(float(row["TankSizeGallons"]) - cfg.selected_tank_size_gal) < 0.01,
                "tank_size": volume_to_display(float(row["TankSizeGallons"]), cfg),
                "reliability": float(row["ReliabilityPercent"]),
            }
            for column in annual_columns:
                value = row.get(column)
                output[column] = None if pd.isna(value) else volume_to_display(float(value) / year_count, cfg)
            final_storage = row.get("FinalStorageGallons")
            output["FinalStorageGallons"] = (
                None if pd.isna(final_storage) else volume_to_display(float(final_storage), cfg)
            )
            output["NetAnnualSavings"] = None if pd.isna(row.get("NetAnnualSavings")) else float(row["NetAnnualSavings"])
            output["SimplePaybackYears"] = None if pd.isna(row.get("SimplePaybackYears")) else float(row["SimplePaybackYears"])
            output["LifecycleNPV"] = (
                None if pd.isna(row.get("LifecycleNPV")) else float(row["LifecycleNPV"])
            )
            rows.append(output)
        return rows

    def _report_water_balance(self) -> dict[str, float]:
        cfg = self.config_model
        results = self.results_df
        total_area_sqft = sum(max(float(surface.area), 0.0) for surface in cfg.surfaces)
        rainfall_inches = pd.to_numeric(
            self.rainfall_df.get("Precipitation", pd.Series(dtype=float)), errors="coerce"
        ).fillna(0.0).clip(lower=0.0).sum()
        potential = float(rainfall_inches) * total_area_sqft / 12.0 * 7.48051948
        total = lambda column: float(pd.to_numeric(results.get(column, pd.Series(dtype=float)), errors="coerce").fillna(0.0).sum())
        gross = total("GrossCollectedGallons")
        first_flush = total("FirstFlushLossGallons")
        collected = total("CollectedGallons")
        supplied = total("RainwaterSuppliedGallons")
        treatment = total("FilterLossGallons")
        overflow = total("OverflowGallons")
        initial = cfg.selected_tank_size_gal * min(max(cfg.tank_parameters.initial_fill_percent, 0.0), 100.0) / 100.0
        final = (
            float(pd.to_numeric(results["WaterInTankGallons"], errors="coerce").fillna(0.0).iloc[-1])
            if not results.empty and "WaterInTankGallons" in results else 0.0
        )
        return {
            key: volume_to_display(value, cfg)
            for key, value in {
                "potential_surface_rainfall": potential,
                "runoff_coefficient_loss": max(potential - gross, 0.0),
                "gross_runoff": gross,
                "first_flush_loss": first_flush,
                "net_collected": collected,
                "initial_storage": initial,
                "rainwater_supplied": supplied,
                "treatment_loss": treatment,
                "overflow": overflow,
                "final_storage": final,
                "collection_residual": potential - max(potential - gross, 0.0) - first_flush - collected,
                "storage_residual": initial + collected - supplied - treatment - overflow - final,
            }.items()
        }

    def _build_report_content(self, metadata: dict[str, object]) -> ReportModel:
        cfg = self.config_model
        station_latitude, station_longitude = self._report_weather_station_coordinates()
        monthly_demand, total_annual_demand = _report_demand_summary(self.results_df, cfg)
        precipitation_field = (
            cfg.canadian_precipitation_field if cfg.country_code == "CAN" else cfg.acis_precipitation_field
        )
        selected_reliability: float | None = None
        if not self.results_df.empty and "ReliabilityPercent" in self.results_df:
            selected_reliability = float(self.results_df["ReliabilityPercent"].iloc[0])
        params = cfg.financial_parameters
        financial_results = FinancialAnalysisService(cfg).calculate(self.results_df)
        financial_configured = self._financial_inputs_configured()
        result_dates = pd.to_datetime(self.results_df.get("Date", pd.Series(dtype="datetime64[ns]")), errors="coerce").dropna()
        rainfall_dates = pd.to_datetime(self.rainfall_df.get("Date", pd.Series(dtype="datetime64[ns]")), errors="coerce").dropna()
        record_start = rainfall_dates.min().date().isoformat() if not rainfall_dates.empty else "Not available"
        record_end = rainfall_dates.max().date().isoformat() if not rainfall_dates.empty else "Not available"
        rainfall_quality = self._rainfall_quality_assessment()
        yearly_rainfall = []
        for summary in rainfall_quality.yearly_summaries:
            row = summary.to_dict()
            row["precipitation"] = precip_to_display(summary.precipitation, cfg)
            yearly_rainfall.append(row)
        rainfall_events = []
        for summary in sorted(
            rainfall_quality.event_summaries,
            key=lambda item: (-item.precipitation, item.start),
        )[:10]:
            row = summary.to_dict()
            row["precipitation"] = precip_to_display(summary.precipitation, cfg)
            rainfall_events.append(row)
        event_depths = [item.precipitation for item in rainfall_quality.event_summaries]
        first_flush_events, first_flush_years = _report_first_flush_summaries(
            self.results_df, cfg
        )
        try:
            application_version = importlib_metadata.version("rainwater-calculator-standalone")
        except importlib_metadata.PackageNotFoundError:
            application_version = "development build"
        return ReportModel.from_payload({
            "metadata": dict(metadata),
            "notes": cfg.notes,
            "area_unit": area_unit(cfg),
            "volume_unit": volume_unit(cfg),
            "precipitation_unit": precip_unit(cfg),
            "average_annual_precipitation": _report_average_annual_precipitation(self.rainfall_df, cfg),
            "precipitation_basis": CANADIAN_PRECIPITATION_LABELS.get(
                precipitation_field, "Total precipitation"
            ),
            "surfaces": _report_surface_rows(cfg),
            "average_annual_rainfall_volumes": _report_average_annual_rainfall_volumes(
                self.results_df, cfg
            ),
            "first_flush_antecedent_dry_days": cfg.first_flush_antecedent_dry_days,
            "first_flush_antecedent_dry_value": _antecedent_dry_period_from_days(
                cfg.first_flush_antecedent_dry_days,
                cfg.first_flush_antecedent_dry_unit,
            ),
            "first_flush_antecedent_dry_unit": cfg.first_flush_antecedent_dry_unit,
            "first_flush_event_count": int(
                self.results_df.get("RainfallEventStart", pd.Series(dtype=bool)).fillna(False).sum()
            ),
            "first_flush_loss": volume_to_display(
                float(self.results_df.get("FirstFlushLossGallons", pd.Series(dtype=float)).sum()),
                cfg,
            ),
            "monthly_demand": monthly_demand,
            "total_annual_demand": total_annual_demand,
            "yearly_reliability": _yearly_demand_reliability(self.results_df),
            "tank_level_distribution": _report_tank_level_distribution(self.results_df, cfg),
            "curve": [
                {
                    "tank_size": volume_to_display(row.TankSizeGallons, cfg),
                    "reliability": float(row.ReliabilityPercent),
                }
                for row in self.curve_df.itertuples(index=False)
            ],
            "selected_tank_size": volume_to_display(cfg.selected_tank_size_gal, cfg),
            "minimum_operating_level_percent": cfg.tank_parameters.minimum_operating_volume_percent,
            "minimum_operating_volume": volume_to_display(
                cfg.selected_tank_size_gal
                * cfg.tank_parameters.minimum_operating_volume_percent
                / 100.0,
                cfg,
            ),
            "selected_reliability": selected_reliability,
            "executive_summary": {
                "average_annual_supply": volume_to_display(
                    self._average_annual_result_total(self.results_df, "RainwaterSuppliedGallons"), cfg
                ),
                "average_annual_municipal_makeup": volume_to_display(
                    self._average_annual_result_total(self.results_df, "MainsMakeupGallons"), cfg
                ),
                "average_annual_system_unmet": volume_to_display(
                    self._average_annual_result_total(self.results_df, "SystemUnmetDemandGallons"), cfg
                ),
                "average_annual_overflow": volume_to_display(
                    self._average_annual_result_total(self.results_df, "OverflowGallons"), cfg
                ),
                "average_annual_first_flush_loss": volume_to_display(
                    self._average_annual_result_total(self.results_df, "FirstFlushLossGallons"), cfg
                ),
                "average_annual_treatment_loss": volume_to_display(
                    self._average_annual_result_total(self.results_df, "FilterLossGallons"), cfg
                ),
                "net_annual_savings": financial_results.net_annual_savings,
                "simple_payback_years": financial_results.simple_payback_years,
                "lifecycle_net_present_value": financial_results.lifecycle_net_present_value,
                "internal_rate_of_return_percent": financial_results.internal_rate_of_return_percent,
                "financial_configured": financial_configured,
            },
            "candidate_performance": self._report_candidate_rows(),
            "recommendation_assumptions": {
                "reliability_target_percent": cfg.recommendation_reliability_target_percent,
                "marginal_gain_threshold": cfg.recommendation_marginal_gain_threshold,
                "marginal_gain_unit": "reliability percentage points per 1,000 gal",
            },
            "recommendations": self._recommendation_report_rows(),
            "review_warnings": self._design_review_warnings(),
            "rainfall_quality": {
                "completeness_percent": rainfall_quality.completeness_percent,
                "completeness_rating": rainfall_quality.completeness_rating,
                "expected_days": rainfall_quality.expected_days,
                "observed_days": rainfall_quality.observed_days,
                "missing_days": rainfall_quality.missing_days,
                "duplicate_dates": rainfall_quality.duplicate_dates,
                "invalid_precipitation_rows": rainfall_quality.invalid_precipitation_rows,
                "partial_years": list(rainfall_quality.partial_years),
                "missing_periods": [
                    period.to_dict() for period in rainfall_quality.missing_periods
                ],
            },
            "yearly_rainfall_summary": yearly_rainfall,
            "rainfall_event_summary": {
                "event_count": rainfall_quality.event_count,
                "average_event_precipitation": precip_to_display(
                    sum(event_depths) / len(event_depths) if event_depths else 0.0, cfg
                ),
                "largest_event_precipitation": precip_to_display(
                    max(event_depths, default=0.0), cfg
                ),
                "largest_events": rainfall_events,
                "antecedent_dry_days": cfg.first_flush_antecedent_dry_days,
            },
            "first_flush_event_summary": first_flush_events,
            "first_flush_yearly_summary": first_flush_years,
            "water_balance": self._report_water_balance(),
            "end_use_rows": self._report_end_use_rows(),
            "financial_summary": {
                "configured": financial_configured,
                "currency": params.currency,
                "water_rate": params.water_rate,
                "sewer_rate": params.sewer_rate,
                "tariff_billing_unit": params.tariff_billing_unit,
                "legacy_sewer_eligible_percent": params.sewer_eligible_percent,
                "installed_cost": params.installed_cost,
                "incentives": params.incentives,
                "fixed_annual_maintenance": params.fixed_annual_maintenance,
                "annual_maintenance_percent": params.annual_maintenance_percent,
                "analysis_period_years": params.analysis_period_years,
                "discount_rate_percent": params.discount_rate_percent,
                "utility_rate_escalation_percent": params.utility_rate_escalation_percent,
                "maintenance_escalation_percent": params.maintenance_escalation_percent,
                "electricity_rate_per_kwh": cfg.optimization_parameters.electricity_rate_per_kwh,
                "electricity_escalation_percent": params.electricity_escalation_percent,
                "pump_power_kw": params.pump_power_kw,
                "pump_flow_rate": volume_to_display(
                    params.pump_flow_rate_gallons_per_hour, cfg
                ),
                "equipment_replacement_cost": params.equipment_replacement_cost,
                "equipment_replacement_interval_years": params.equipment_replacement_interval_years,
                "equipment_replacement_escalation_percent": (
                    params.equipment_replacement_escalation_percent
                ),
                "average_annual_supply": volume_to_display(financial_results.average_annual_supplied_gallons, cfg),
                "average_annual_sewer_eligible_supply": volume_to_display(
                    financial_results.average_annual_sewer_eligible_supplied_gallons, cfg
                ),
                "municipal_water_savings": financial_results.annual_municipal_water_savings,
                "sewer_savings": financial_results.annual_sewer_savings,
                "gross_annual_savings": financial_results.gross_annual_savings,
                "annual_maintenance_cost": financial_results.annual_maintenance_cost,
                "average_annual_pump_energy_kwh": financial_results.average_annual_pump_energy_kwh,
                "annual_pump_energy_cost": financial_results.annual_pump_energy_cost,
                "net_annual_savings": financial_results.net_annual_savings,
                "net_installed_cost": financial_results.net_installed_cost,
                "simple_payback_years": financial_results.simple_payback_years,
                "analysis_period_net_benefit": financial_results.analysis_period_net_benefit,
                "total_replacement_cost": financial_results.total_replacement_cost,
                "lifecycle_net_present_value": financial_results.lifecycle_net_present_value,
                "internal_rate_of_return_percent": financial_results.internal_rate_of_return_percent,
                "discounted_payback_years": financial_results.discounted_payback_years,
                "annual_cash_flows": list(financial_results.annual_cash_flows),
                "methodology": (
                    "Year-end discounted cash flow based on simulated rainwater delivered to demand, "
                    "with configured utility, maintenance, and electricity escalation plus recurring "
                    "equipment replacement. Tariff tiers and financing are excluded."
                ),
            },
            "provenance": {
                "rainfall_source": self.rainfall_source_label or cfg.rainfall_source_label or "Imported rainfall data",
                "record_start": record_start,
                "record_end": record_end,
                "calendar_years": len(rainfall_quality.yearly_summaries),
                "observations": rainfall_quality.observed_days,
                "missing_calendar_days": rainfall_quality.missing_days,
                "incomplete_calendar_years": len(rainfall_quality.partial_years),
                "rainfall_completeness_percent": rainfall_quality.completeness_percent,
                "rainfall_completeness_rating": rainfall_quality.completeness_rating,
                "rainfall_data_type": rainfall_data_type_label(cfg.rainfall_data_type),
                "rainfall_data_type_code": cfg.rainfall_data_type,
                "rainfall_resolution": RAINFALL_RESOLUTION_LABELS.get(
                    cfg.rainfall_temporal_resolution, "Unknown"
                ),
                "rainfall_timezone": cfg.rainfall_timezone,
                "rainfall_timing_metadata": cfg.rainfall_timing_type,
                "rainfall_retrieved_at": cfg.rainfall_retrieved_at or "Not recorded",
                "simulation_timestep": (
                    "Daily mass balance for sizing; hourly timing simulation for detailed results"
                ),
                "rainfall_timing_assumption": (
                    "Synthetic hourly timing is used for hourly analysis."
                    if cfg.use_synthetic_hourly_rainfall and has_hourly_rainfall(self.rainfall_df)
                    else "Each daily rainfall total is applied within that simulated day; "
                    "hourly demand analysis places it after hour 23."
                ),
                "demand_timing_assumption": (
                    f"Hourly demand profile applied hour by hour (schedule: "
                    f"{cfg.demand.active_hourly_schedule_name})."
                    if cfg.demand.hourly_schedule_enabled
                    else "Hourly demand values are summed for each calendar day and the total "
                    "is applied once at 12:00 noon; the hourly profile is preserved."
                ),
                "initial_tank_fill_percent": cfg.tank_parameters.initial_fill_percent,
                "municipal_backup": "Enabled" if cfg.system_parameters.municipal_backup_enabled else "Disabled",
                "filter_recovery_percent": cfg.system_parameters.filter_recovery_percent,
                "filtration_system_flow_gpm": cfg.system_parameters.filtration_system_flow_gpm,
                "filtration_system_count": cfg.system_parameters.filtration_system_count,
                "transfer_pump_type": cfg.system_parameters.transfer_pump_type,
                "system_type": cfg.system_type,
                "application_version": application_version,
                "algorithm_version": ANALYSIS_ALGORITHM_VERSION,
                "report_schema_version": REPORT_SCHEMA_VERSION,
                "analysis_input_signature": cfg.analysis_input_signature or "Not stored",
                "generated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
                "result_years": int(result_dates.dt.year.nunique()) if not result_dates.empty else 0,
            },
            "report_sections": normalize_report_sections(cfg.report_sections),
            "include_multitank_charts": bool(
                cfg.report_include_multitank_charts
                and cfg.multitank_comparison_enabled
                and self.comparison_results
            ),
            "include_system_visualization": bool(
                cfg.report_include_system_visualization
            ),
            "system_type": cfg.system_type,
            "project_latitude": cfg.latitude,
            "project_longitude": cfg.longitude,
            "weather_station_latitude": station_latitude,
            "weather_station_longitude": station_longitude,
            "map_tile_url": OSM_TILE_URL,
            "multitank_charts": self._multitank_report_chart_data(),
        })

    def _multitank_report_chart_data(self) -> list[dict[str, object]]:
        if not self.config_model.multitank_comparison_enabled:
            return []
        unit = volume_unit(self.config_model)
        tank_series: list[dict[str, object]] = []
        distribution_series: list[dict[str, object]] = []
        yearly_series: list[dict[str, object]] = []
        yearly_stacked_charts: list[dict[str, object]] = []
        for tank_size, results in sorted(self.comparison_results.items()):
            if results.empty:
                continue
            label = f"{format_number(volume_to_display(tank_size, self.config_model), self.config_model, max_decimal_places=0)} {unit}"
            levels = [float(value) for value in results["WaterInTankGallons"]]
            render_indices = self._chart_render_indices(levels, 800)
            result_dates = pd.to_datetime(results["Date"], errors="coerce")
            yearly_points: dict[str, list[tuple[float, float]]] = {}
            for year in sorted(int(value) for value in result_dates.dropna().dt.year.unique()):
                year_mask = result_dates.dt.year == year
                year_levels = [
                    volume_to_display(float(value), self.config_model)
                    for value in results.loc[year_mask, "WaterInTankGallons"]
                ]
                year_indices = self._chart_render_indices(year_levels, 400)
                yearly_points[str(year)] = [
                    (float(index + 1), year_levels[index]) for index in year_indices
                ]
            tank_series.append(
                {
                    "label": label,
                    "points": [
                        (float(index), volume_to_display(levels[index], self.config_model))
                        for index in render_indices
                    ],
                    "yearly_points": yearly_points,
                    "dated_points": [
                        (
                            pd.Timestamp(result_dates.iloc[index]).strftime("%Y-%m-%d"),
                            volume_to_display(levels[index], self.config_model),
                        )
                        for index in render_indices
                        if not pd.isna(result_dates.iloc[index])
                    ],
                }
            )
            counts = [0] * 6
            for value in levels:
                percentage = min(max(value / tank_size * 100.0, 0.0), 100.0)
                counts[min(int(percentage / (100.0 / 6)), 5)] += 1
            total = len(levels) or 1
            distribution_series.append(
                {
                    "label": label,
                    "points": [
                        ((index + 0.5) * (100.0 / 6), count / total * 100.0)
                        for index, count in enumerate(counts)
                    ],
                }
            )
            yearly = _yearly_demand_reliability(results)
            yearly_series.append(
                {
                    "label": label,
                    "points": [
                        (float(row["year"]), float(row["met_percent"]))
                        for row in yearly
                    ],
                }
            )
            yearly_stacked_charts.append(
                {
                    "type": "yearly_stacked",
                    "title": f"Yearly Demand Reliability - {label} tank",
                    "yearly_reliability": yearly,
                    "selected_reliability": float(results["ReliabilityPercent"].iloc[0]),
                }
            )
        return [
            {
                "title": "Tank level distribution - multitank",
                "x_label": "Tank level (% of capacity)",
                "y_label": "Days (%)",
                "series": distribution_series,
            },
            {
                "title": "Yearly demand reliability - multitank",
                "x_label": "Year",
                "y_label": "Demand met (%)",
                "series": yearly_series,
                "interactive_series_toggle": True,
            },
            *yearly_stacked_charts,
            {
                "type": "tank_history",
                "title": f"Tank Water Over Time ({unit})",
                "x_label": "Day of year",
                "y_label": unit,
                "series": tank_series,
            },
        ]

    def _build_report_latex(
        self, report: ReportModel | dict[str, object]
    ) -> str:
        return ReportRenderingService().latex(report)

    def _build_report_html(
        self, report: ReportModel | dict[str, object]
    ) -> str:
        return ReportRenderingService().html(report)

    def _compile_latex_report(
        self, tex_path: Path, pdf_path: Path, report: ReportModel
    ) -> None:
        pdflatex = shutil.which("pdflatex")
        if pdflatex is None:
            self._write_fallback_pdf_report(pdf_path, report)
            return

        with tempfile.TemporaryDirectory() as temp_dir:
            work_dir = Path(temp_dir)
            work_tex = work_dir / tex_path.name
            work_tex.write_text(tex_path.read_text(encoding="utf-8"), encoding="utf-8")
            for _pass in range(2):
                result = subprocess.run(
                    [pdflatex, "-interaction=nonstopmode", "-halt-on-error", work_tex.name],
                    cwd=work_dir,
                    capture_output=True,
                    text=True,
                    timeout=60,
                    check=False,
                )
                if result.returncode != 0:
                    log = (result.stdout + "\n" + result.stderr).strip()
                    raise RuntimeError(f"LaTeX failed. Source saved to {tex_path}.\n\n{log[-2000:]}")
            compiled_pdf = work_dir / work_tex.with_suffix(".pdf").name
            if not compiled_pdf.exists():
                raise RuntimeError(f"LaTeX did not create a PDF. Source saved to {tex_path}.")
            shutil.copyfile(compiled_pdf, pdf_path)

    def _write_fallback_pdf_report(
        self, pdf_path: Path, report: ReportModel | dict[str, object]
    ) -> None:
        ReportRenderingService().pdf(pdf_path, report)

    def _draw_pdf_yearly_demand_reliability(
        self, commands: list[str], x: float, y: float, width: float, height: float,
        report: ReportModel | dict[str, object],
    ) -> None:
        draw_pdf_yearly_demand_reliability(commands, x, y, width, height, report)

    def _draw_pdf_tank_level_distribution(
        self, commands: list[str], x: float, y: float, width: float, height: float,
        report: ReportModel | dict[str, object],
    ) -> None:
        draw_pdf_tank_level_distribution(commands, x, y, width, height, report)

    def _draw_pdf_reliability_curve(
        self, commands: list[str], x: float, y: float, width: float, height: float,
        report: ReportModel | dict[str, object],
    ) -> None:
        draw_pdf_reliability_curve(commands, x, y, width, height, report)

    def _write_pdf_with_pypdf(
        self,
        pdf_path: Path,
        pages: list[list[str]],
        section_pages: dict[str, int] | None = None,
        toc_links: list[tuple[tuple[float, float, float, float], str]] | None = None,
    ) -> None:
        write_pdf_with_pypdf(pdf_path, pages, section_pages, toc_links)

    def _display_results_df(self) -> pd.DataFrame:
        cfg = self.config_model
        out = self.results_df.copy()
        out["Precipitation"] = out["Precipitation"].map(lambda v: precip_to_display(float(v), cfg))
        for col in [
            "GrossCollectedGallons", "FirstFlushLossGallons", "CollectedGallons",
            "OverflowGallons", "DemandGallons", "SewerEligibleDemandGallons",
            "RainwaterSuppliedGallons", "SewerEligibleRainwaterSuppliedGallons",
            "UnmetDemandGallons", "MainsMakeupGallons", "SystemUnmetDemandGallons",
            "FilterLossGallons", "WaterInTankGallons",
        ]:
            if col in out:
                out[col] = out[col].map(lambda v: volume_to_display(float(v), cfg))
        return out.rename(
            columns={
                "Precipitation": f"Precipitation ({precip_unit(cfg)})",
                "GrossCollectedGallons": f"Gross runoff ({volume_unit(cfg)})",
                "FirstFlushLossGallons": f"First-flush loss ({volume_unit(cfg)})",
                "CollectedGallons": f"Collected ({volume_unit(cfg)})",
                "OverflowGallons": f"Overflow ({volume_unit(cfg)}/day)",
                "DemandGallons": f"Demand ({volume_unit(cfg)}/day)",
                "SewerEligibleDemandGallons": f"Sewer-eligible demand ({volume_unit(cfg)}/day)",
                "RainwaterSuppliedGallons": f"Rainwater supplied ({volume_unit(cfg)}/day)",
                "SewerEligibleRainwaterSuppliedGallons": f"Sewer-eligible rainwater supplied ({volume_unit(cfg)}/day)",
                "UnmetDemandGallons": f"Unmet Demand ({volume_unit(cfg)}/day)",
                "MainsMakeupGallons": f"Municipal makeup ({volume_unit(cfg)}/day)",
                "SystemUnmetDemandGallons": f"System unmet demand ({volume_unit(cfg)}/day)",
                "FilterLossGallons": f"Treatment loss ({volume_unit(cfg)}/day)",
                "WaterInTankGallons": f"Water in Tank ({volume_unit(cfg)})",
                "ReliabilityPercent": "Reliability (%)",
            }
        )

    def _candidate_performance_data(self) -> pd.DataFrame:
        return CandidateAnalysisService(self.config_model).build(self.curve_df)

    def _financial_inputs_configured(self) -> bool:
        return FinancialAnalysisService(self.config_model).is_configured()

    def _rainfall_record_quality(self) -> tuple[int, int]:
        quality = self._rainfall_quality_assessment()
        return quality.missing_days, len(quality.partial_years)

    def _design_recommendation_set(self) -> RecommendationSet:
        cfg = self.config_model
        return recommend_tank_sizes(
            self._candidate_performance_data(),
            reliability_target_percent=cfg.recommendation_reliability_target_percent,
            marginal_gain_threshold=cfg.recommendation_marginal_gain_threshold,
            selected_tank_size_gallons=cfg.selected_tank_size_gal,
        )

    def _design_review_warnings(self) -> list[str]:
        quality = self._rainfall_quality_assessment()
        longest_period = max(quality.missing_periods, key=lambda item: item.days, default=None)
        warnings = selected_design_warnings(
            self._candidate_performance_data(),
            selected_tank_size_gallons=self.config_model.selected_tank_size_gal,
            reliability_target_percent=self.config_model.recommendation_reliability_target_percent,
            financial_configured=self._financial_inputs_configured(),
            missing_calendar_days=quality.missing_days,
            incomplete_calendar_years=len(quality.partial_years),
            completeness_percent=quality.completeness_percent,
            completeness_rating=quality.completeness_rating,
            partial_years=quality.partial_years,
            longest_missing_period=(
                (longest_period.start, longest_period.end, longest_period.days)
                if longest_period is not None
                else None
            ),
            rainfall_data_type=self.config_model.rainfall_data_type,
        )
        if self.config_model.rainfall_temporal_resolution != "daily":
            warnings.append(
                "The current calculation engine expects daily rainfall totals, but the "
                f"record is labeled {self.config_model.rainfall_temporal_resolution}."
            )
        if self.config_model.rainfall_timezone.strip().casefold() in {
            "",
            "unknown",
            "unspecified",
        }:
            warnings.append(
                "Rainfall source timezone is not recorded; subdaily temporal alignment "
                "cannot be verified."
            )
        return warnings

    def _recommendation_report_rows(self) -> list[dict[str, object]]:
        cfg = self.config_model
        recommendations = self._design_recommendation_set()
        rows: list[dict[str, object]] = []
        for item in (*recommendations.recommendations, *recommendations.alternatives):
            row = item.to_dict()
            row["tank_size"] = volume_to_display(item.tank_size_gallons, cfg)
            row["volume_unit"] = volume_unit(cfg)
            rows.append(row)
        return rows

    def _refresh_design_recommendations(self) -> None:
        if not hasattr(self, "design_recommendations_var"):
            return
        cfg = self.config_model
        cfg.recommendation_reliability_target_percent = min(
            max(_float(self.recommendation_reliability_target_var.get(), 90.0), 0.0),
            100.0,
        )
        cfg.recommendation_marginal_gain_threshold = max(
            _float(self.recommendation_marginal_gain_var.get(), 1.0), 0.0
        )
        self.recommendation_reliability_target_var.set(
            f"{cfg.recommendation_reliability_target_percent:g}"
        )
        self.recommendation_marginal_gain_var.set(
            f"{cfg.recommendation_marginal_gain_threshold:g}"
        )
        recommendation_set = self._design_recommendation_set()
        items = (*recommendation_set.recommendations, *recommendation_set.alternatives)
        if not items:
            self.design_recommendations_var.set(
                "Run an analysis to generate design recommendations."
            )
        else:
            unit = volume_unit(cfg)
            currency = cfg.financial_parameters.currency
            lines: list[str] = []
            for item in items:
                economics = ""
                if item.simple_payback_years is not None:
                    economics = f"; payback {format_number(item.simple_payback_years, cfg, max_decimal_places=1)} years"
                elif item.net_annual_savings is not None:
                    economics = f"; net savings {currency} {format_number(item.net_annual_savings, cfg)}/year"
                lines.append(
                    f"- {item.role}: {format_number(volume_to_display(item.tank_size_gallons, cfg), cfg, max_decimal_places=0)} "
                    f"{unit} at {format_number(item.reliability_percent, cfg, max_decimal_places=1)}% reliability{economics}. {item.detail}"
                )
            self.design_recommendations_var.set("\n".join(lines))
        warnings = self._design_review_warnings()
        self.design_warnings_var.set(
            "Review: " + " ".join(warnings) if warnings else "No configured review conditions were triggered."
        )

    def _sort_candidate_performance(self, column: str) -> None:
        if self.candidate_sort_column == column:
            self.candidate_sort_reverse = not self.candidate_sort_reverse
        else:
            self.candidate_sort_column = column
            self.candidate_sort_reverse = False
        self._populate_candidate_performance()

    def _populate_candidate_performance(self) -> None:
        if not hasattr(self, "candidate_performance_tree"):
            return
        tree = self.candidate_performance_tree
        tree.delete(*tree.get_children())
        self.candidate_tree_sizes = {}
        data = self._candidate_performance_data()
        if data.empty:
            self._refresh_design_recommendations()
            return
        candidate_service = CandidateAnalysisService(self.config_model)
        data = candidate_service.sorted_data(
            data, self.candidate_sort_column, self.candidate_sort_reverse
        )
        unit = volume_unit(self.config_model)
        currency = self.config_model.financial_parameters.currency
        heading_labels = {
            "TankSizeGallons": f"Tank size ({unit})", "ReliabilityPercent": "Reliability (%)",
            "TotalDemandGallons": f"Total demand ({unit})",
            "RainwaterSuppliedGallons": f"Rainwater supplied ({unit})",
            "SewerEligibleRainwaterSuppliedGallons": f"Sewer-eligible supply ({unit})",
            "UnmetDemandGallons": f"Rainwater shortfall ({unit})",
            "MunicipalMakeupGallons": f"Municipal makeup ({unit})",
            "SystemUnmetDemandGallons": f"System unmet ({unit})",
            "OverflowGallons": f"Overflow ({unit})", "FirstFlushLossGallons": f"First-flush loss ({unit})",
            "TreatmentLossGallons": f"Treatment loss ({unit})", "FinalStorageGallons": f"Final storage ({unit})",
            "NetAnnualSavings": f"Net savings/year ({currency})", "SimplePaybackYears": "Simple payback (years)",
            "LifecycleNPV": f"Lifecycle NPV ({currency})",
        }
        for column, label in heading_labels.items():
            tree.heading(column, text=label)
        self._wrap_treeview_headings(tree)
        columns = tuple(str(column) for column in tree["columns"])
        display_rows = candidate_service.display_rows(data, columns)
        for position, (values_by_column, display_values) in enumerate(
            zip(data.to_dict("records"), display_rows), start=1
        ):
            item = f"candidate-{position}"
            tree.insert("", "end", iid=item, values=display_values)
            tank_size = values_by_column.get("TankSizeGallons")
            if not pd.isna(tank_size):
                self.candidate_tree_sizes[item] = float(tank_size)
        self._refresh_design_recommendations()

    def use_candidate_as_primary(self) -> None:
        selected = self.candidate_performance_tree.selection()
        if len(selected) != 1 or selected[0] not in self.candidate_tree_sizes:
            messagebox.showinfo(APP_TITLE, "Select one candidate tank first.")
            return
        tank_size = self.candidate_tree_sizes[selected[0]]
        self.selected_tank_var.set(
            format_number(volume_to_display(tank_size, self.config_model), self.config_model, max_decimal_places=0)
        )
        self.status_var.set("Candidate set as the primary tank size; rerun the analysis to refresh detailed results.")

    def _use_candidate_as_primary_from_event(self, event: tk.Event) -> str:
        row_id = self.candidate_performance_tree.identify_row(event.y)
        if row_id:
            self.candidate_performance_tree.selection_set(row_id)
            self.use_candidate_as_primary()
        return "break"

    def export_candidate_performance(self) -> None:
        data = self._candidate_performance_data()
        if data.empty:
            messagebox.showinfo(APP_TITLE, "Run the analysis before exporting candidate performance.")
            return
        path = filedialog.asksaveasfilename(
            title="Export candidate tank performance",
            initialfile=f"{_safe_project_file_name(self.config_model.name).replace('.db', '')}_candidate_tanks.csv",
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if not path:
            return False
        export = CandidateAnalysisService(self.config_model).export_data(data)
        export.to_csv(path, index=False, quoting=csv.QUOTE_MINIMAL)
        self.status_var.set(f"Exported candidate tank performance: {Path(path).name}")

    @staticmethod
    def _station_label(station: dict) -> str:
        location = ""
        if station.get("latitude") is not None and station.get("longitude") is not None:
            location = f" ({station['latitude']:.3f}, {station['longitude']:.3f})"
        distance = f" - {format_number(float(station['distance_km']), self.config_model, max_decimal_places=1)} km" if station.get("distance_km") is not None else ""
        airport_id = str(
            station.get("airport_icao")
            or station.get("airport_faa")
            or station.get("tc_identifier")
            or ""
        ).strip()
        airport = f" [Airport {airport_id}]" if station.get("airport_verified") and airport_id else ""
        return (
            f"{station['name']} - {station['sid']}{airport}{distance}{location}"
            f"{RainwaterTkApp._station_region_suffix(station)}"
        )

    @staticmethod
    def _station_region_suffix(station: dict) -> str:
        code = str(station.get("state", "")).strip().upper()
        provider = str(station.get("provider", "")).strip().upper()
        names = PROVINCE_NAME_BY_CODE if provider == "ECCC" else STATE_NAME_BY_CODE
        region_name = names.get(code)
        return f" in {region_name}" if region_name else ""

    def _populate_results(self) -> None:
        self.results_tree.heading("precip", text=f"Precip. ({precip_unit(self.config_model)})")
        self.results_tree.heading("gross", text=f"Gross runoff ({volume_unit(self.config_model)})")
        self.results_tree.heading("first_flush", text=f"First flush ({volume_unit(self.config_model)})")
        self.results_tree.heading("collected", text=f"Collected ({volume_unit(self.config_model)})")
        self.results_tree.heading("overflow", text=f"Overflow ({volume_unit(self.config_model)})")
        self.results_tree.heading("demand", text=f"Demand ({volume_unit(self.config_model)})")
        self.results_tree.heading("unmet", text=f"Unmet ({volume_unit(self.config_model)})")
        self.results_tree.heading("tank", text=f"Water in Tank ({volume_unit(self.config_model)})")
        self._wrap_treeview_headings(self.results_tree)
        self.results_tree.delete(*self.results_tree.get_children())
        display = self._display_results_df()
        overflow_column = f"Overflow ({volume_unit(self.config_model)}/day)"
        for _, row in display.iterrows():
            overflow_value = row.get(overflow_column)
            overflow_text = "" if pd.isna(overflow_value) else format_number(overflow_value, self.config_model, max_decimal_places=1)
            self.results_tree.insert(
                "",
                "end",
                values=(
                    pd.Timestamp(row["Date"]).strftime("%Y-%m-%d"),
                    format_number(row[f'Precipitation ({precip_unit(self.config_model)})'], self.config_model, max_decimal_places=3),
                    format_number(row[f'Gross runoff ({volume_unit(self.config_model)})'], self.config_model, max_decimal_places=1),
                    format_number(row[f'First-flush loss ({volume_unit(self.config_model)})'], self.config_model, max_decimal_places=1),
                    format_number(row[f'Collected ({volume_unit(self.config_model)})'], self.config_model, max_decimal_places=1),
                    overflow_text,
                    format_number(row[f'Demand ({volume_unit(self.config_model)}/day)'], self.config_model, max_decimal_places=1),
                    format_number(row[f'Unmet Demand ({volume_unit(self.config_model)}/day)'], self.config_model, max_decimal_places=1),
                    format_number(row[f'Water in Tank ({volume_unit(self.config_model)})'], self.config_model, max_decimal_places=1),
                ),
            )
        self._populate_hourly_results()
        self._populate_first_flush_summaries()
        self._populate_candidate_performance()

    def _populate_first_flush_summaries(self) -> None:
        event_rows, yearly_rows = _report_first_flush_summaries(
            self.results_df, self.config_model
        )
        unit = volume_unit(self.config_model)
        for tree in (self.first_flush_yearly_tree, self.first_flush_event_tree):
            tree.delete(*tree.get_children())
            for column, label in (
                ("gross", "Gross runoff"),
                ("diverted", "First-flush diversion"),
                ("collected", "Net collected"),
            ):
                tree.heading(column, text=f"{label} ({unit})")
            tree.heading("percent", text="Diverted (%)")
            self._wrap_treeview_headings(tree)
        for row in yearly_rows:
            self.first_flush_yearly_tree.insert(
                "",
                "end",
                values=(
                    int(row["year"]),
                    int(row["event_count"]),
                    format_number(float(row["gross_runoff"]), self.config_model),
                    format_number(float(row["first_flush_loss"]), self.config_model),
                    format_number(float(row["net_collected"]), self.config_model),
                    format_number(float(row["diversion_percent"]), self.config_model),
                ),
            )
        for row in event_rows:
            start = str(row["start"]).replace("T00:00:00", "")
            end = str(row["end"]).replace("T00:00:00", "")
            self.first_flush_event_tree.insert(
                "",
                "end",
                values=(
                    row["event_id"],
                    start,
                    end,
                    int(row["wet_timesteps"]),
                    format_number(float(row["gross_runoff"]), self.config_model),
                    format_number(float(row["first_flush_loss"]), self.config_model),
                    format_number(float(row["net_collected"]), self.config_model),
                    format_number(float(row["diversion_percent"]), self.config_model),
                ),
            )

    def _populate_hourly_results(self) -> None:
        self.hourly_results_tree.delete(*self.hourly_results_tree.get_children())
        dates = pd.to_datetime(self.hourly_results_df.get("Date", pd.Series(dtype="datetime64[ns]")), errors="coerce")
        years = sorted(str(int(year)) for year in dates.dropna().dt.year.unique())
        self.hourly_results_year_combo.configure(values=years)
        if self.hourly_results_year_var.get() not in years:
            self.hourly_results_year_var.set(years[0] if years else "--")
        unit = volume_unit(self.config_model)
        for column in (
            "gross", "first_flush", "collected", "demand", "pump", "filter", "filter_loss", "booster", "mains",
            "shortfall", "system_unmet", "overflow", "tank",
        ):
            label = re.split(r"\s+\(", self.hourly_results_tree.heading(column, "text"), maxsplit=1)[0]
            self.hourly_results_tree.heading(column, text=f"{label} ({unit})")
        self._wrap_treeview_headings(self.hourly_results_tree)
        for row in self._selected_hourly_results().itertuples(index=False):
            self.hourly_results_tree.insert(
                "", "end", values=(
                    pd.Timestamp(row.Date).strftime("%Y-%m-%d %H:00"),
                    format_number(volume_to_display(row.GrossCollectedGallons, self.config_model), self.config_model),
                    format_number(volume_to_display(row.FirstFlushLossGallons, self.config_model), self.config_model),
                    format_number(volume_to_display(row.CollectedGallons, self.config_model), self.config_model),
                    format_number(volume_to_display(row.DemandGallons, self.config_model), self.config_model),
                    format_number(volume_to_display(row.PumpFlowGallons, self.config_model), self.config_model),
                    format_number(volume_to_display(row.FilterThroughputGallons, self.config_model), self.config_model),
                    format_number(volume_to_display(row.FilterLossGallons, self.config_model), self.config_model),
                    format_number(volume_to_display(row.BoosterTankGallons, self.config_model), self.config_model),
                    format_number(volume_to_display(row.MainsMakeupGallons, self.config_model), self.config_model),
                    format_number(volume_to_display(row.UnmetDemandGallons, self.config_model), self.config_model),
                    format_number(volume_to_display(row.SystemUnmetDemandGallons, self.config_model), self.config_model),
                    format_number(volume_to_display(row.OverflowGallons, self.config_model), self.config_model),
                    format_number(volume_to_display(row.WaterInTankGallons, self.config_model), self.config_model),
                )
            )

    def _selected_hourly_results(self) -> pd.DataFrame:
        if self.hourly_results_df.empty:
            return self.hourly_results_df
        try:
            year = int(self.hourly_results_year_var.get())
        except ValueError:
            return self.hourly_results_df.iloc[0:0]
        dates = pd.to_datetime(self.hourly_results_df["Date"], errors="coerce")
        return self.hourly_results_df.loc[dates.dt.year == year]

    def _refresh_hourly_results_view(self) -> None:
        self._populate_hourly_results()
        self._draw_hourly_results()

    def _draw_hourly_results(self) -> None:
        self.hourly_tank_canvas.delete("all")
        self.hourly_tank_canvas.hover_points = []
        selected_results = self._selected_hourly_results()
        if selected_results.empty:
            self.hourly_tank_canvas.create_text(
                max(self.hourly_tank_canvas.winfo_width(), 300) / 2,
                max(self.hourly_tank_canvas.winfo_height(), 160) / 2,
                text="Enable an hourly demand schedule and run the analysis to view hourly results.",
            )
            return
        values = [volume_to_display(value, self.config_model) for value in selected_results["WaterInTankGallons"]]
        indices = self._chart_render_indices(values, 1200)
        dates = list(selected_results["Date"])
        self._draw_line_chart(
            self.hourly_tank_canvas,
            [float(index) for index in indices],
            [values[index] for index in indices],
            f"Hourly Tank Water Over Time ({self.hourly_results_year_var.get()}) - {format_number(volume_to_display(self.config_model.selected_tank_size_gal, self.config_model), self.config_model, max_decimal_places=0)} {volume_unit(self.config_model)} tank",
            volume_unit(self.config_model),
            "Simulation hour",
            [
                f"Date: {pd.Timestamp(dates[index]):%Y-%m-%d %H:00}\nWater in tank: {format_number(values[index], self.config_model)} {volume_unit(self.config_model)}"
                for index in indices
            ],
            show_points=False,
        )

    def _clear_results(self) -> None:
        self.comparison_results = {}
        self._set_tank_chart_controls_visible(False)
        self.tank_chart_year = None
        self.tank_chart_year_var.set("--")
        self.tank_chart_range_initialized = False
        self.average_annual_precipitation_var.set("Average annual precipitation: --")
        self.results_tree.delete(*self.results_tree.get_children())
        if hasattr(self, "hourly_results_tree"):
            self.hourly_results_tree.delete(*self.hourly_results_tree.get_children())
        if hasattr(self, "first_flush_event_tree"):
            self.first_flush_event_tree.delete(*self.first_flush_event_tree.get_children())
            self.first_flush_yearly_tree.delete(*self.first_flush_yearly_tree.get_children())
        if hasattr(self, "candidate_performance_tree"):
            self.candidate_performance_tree.delete(*self.candidate_performance_tree.get_children())
            self.candidate_tree_sizes = {}
        self._populate_comparison_tanks()
        self.curve_canvas.delete("all")
        self.tank_canvas.delete("all")
        self.histogram_canvas.delete("all")
        self.yearly_reliability_canvas.delete("all")
        self.hourly_results_df = pd.DataFrame()
        if hasattr(self, "hourly_tank_canvas"):
            self.hourly_tank_canvas.delete("all")
        if hasattr(self, "multitank_tank_canvas"):
            self.multitank_tank_canvas.delete("all")
            self.multitank_distribution_canvas.delete("all")
            self.multitank_yearly_canvas.delete("all")
        self.curve_canvas.hover_points = []
        self.tank_canvas.hover_points = []
        self.histogram_canvas.hover_points = []
        self.yearly_reliability_canvas.hover_points = []

    def _draw_saved_analysis_charts(self) -> None:
        if not self.results_tab.winfo_ismapped():
            return
        self.update_idletasks()
        self._draw_curve()
        self._draw_tank_chart()
        self._draw_tank_level_histogram()
        self._draw_yearly_demand_reliability()
        self._draw_multitank_summary()
        self._draw_hourly_results()

    def _schedule_results_chart_redraw(self, _event: tk.Event | None = None) -> None:
        if self.results_df.empty and self.curve_df.empty:
            return
        if self.results_chart_redraw_after_id is not None:
            self.after_cancel(self.results_chart_redraw_after_id)
        self.results_chart_redraw_after_id = self.after(100, self._redraw_results_charts_after_resize)

    def _redraw_results_charts_after_resize(self) -> None:
        self.results_chart_redraw_after_id = None
        self._draw_saved_analysis_charts()

    def _draw_curve(self) -> None:
        if self.curve_df.empty:
            return
        x = [volume_to_display(v, self.config_model) for v in self.curve_df["TankSizeGallons"]]
        y = list(self.curve_df["ReliabilityPercent"])
        hover_labels = [
            f"Tank size: {format_number(tank_size, self.config_model, max_decimal_places=0)} {volume_unit(self.config_model)}\nReliability: {format_number(reliability, self.config_model)}%"
            for tank_size, reliability in zip(x, y)
        ]
        self._draw_line_chart(
            self.curve_canvas,
            x,
            y,
            f"Reliability vs Tank Size ({volume_unit(self.config_model)})",
            "Reliability %",
            f"Tank size ({volume_unit(self.config_model)})",
            hover_labels,
        )

    def _draw_tank_chart(self) -> None:
        self._set_tank_chart_controls_visible(False)
        if self.results_df.empty:
            return
        dates = pd.to_datetime(self.results_df["Date"], errors="coerce")
        valid_dates = dates.dropna()
        if valid_dates.empty:
            return
        months = pd.period_range(valid_dates.min().to_period("M"), valid_dates.max().to_period("M"), freq="M")
        max_month_index = max(len(months) - 1, 0)
        self.tank_range_start_scale.configure(to=max_month_index)
        self.tank_range_end_scale.configure(to=max_month_index)
        if not self.tank_chart_range_initialized:
            self.tank_chart_range_start_var.set(0)
            self.tank_chart_range_end_var.set(max_month_index)
            self.tank_chart_range_initialized = True
        elif self.tank_chart_range_end_var.get() > max_month_index:
            self.tank_chart_range_end_var.set(max_month_index)
        available_years = sorted(int(year) for year in dates.dropna().dt.year.unique())
        if not available_years:
            return
        if self.tank_chart_year not in available_years:
            self.tank_chart_year = available_years[0]
        year_index = available_years.index(self.tank_chart_year)
        self.tank_chart_year_var.set(str(self.tank_chart_year))
        self.previous_tank_year_button.state(["disabled"] if year_index == 0 else ["!disabled"])
        self.next_tank_year_button.state(
            ["disabled"] if year_index == len(available_years) - 1 else ["!disabled"]
        )
        range_mode = self.tank_chart_range_mode_var.get() == "range"
        if range_mode:
            start_index = min(max(int(round(self.tank_chart_range_start_var.get())), 0), max_month_index)
            end_index = min(max(int(round(self.tank_chart_range_end_var.get())), start_index), max_month_index)
            self.tank_chart_range_start_var.set(start_index)
            self.tank_chart_range_end_var.set(end_index)
            start_date = months[start_index].start_time
            end_date = months[end_index].end_time
            chart_results = self.results_df.loc[dates.between(start_date, end_date)]
            self.tank_chart_range_label_var.set(f"{months[start_index]} to {months[end_index]}")
            chart_title_period = f"{months[start_index]} to {months[end_index]}"
        else:
            chart_results = self.results_df.loc[dates.dt.year == self.tank_chart_year]
            self.tank_chart_range_label_var.set("Range rounded to whole months")
            chart_title_period = str(self.tank_chart_year)
        self.tank_chart_year_entry.state(["disabled"] if range_mode else ["!disabled"])
        if range_mode:
            self.previous_tank_year_button.state(["disabled"])
            self.next_tank_year_button.state(["disabled"])
        for widget in (self.tank_range_start_scale, self.tank_range_end_scale):
            widget.state(["!disabled"] if range_mode else ["disabled"])
        x = list(range(1, len(chart_results) + 1))
        y = [volume_to_display(v, self.config_model) for v in chart_results["WaterInTankGallons"]]
        hover_labels = [
            f"Date: {pd.Timestamp(date).strftime('%Y-%m-%d')}\nWater in tank: {format_number(water, self.config_model, max_decimal_places=1)} {volume_unit(self.config_model)}"
            for date, water in zip(chart_results["Date"], y)
        ]
        self._draw_line_chart(
            self.tank_canvas,
            x,
            y,
            f"Tank Water Over Time ({chart_title_period}) - "
            f"{format_number(volume_to_display(self.config_model.selected_tank_size_gal, self.config_model), self.config_model, max_decimal_places=0)} "
            f"{volume_unit(self.config_model)} tank",
            volume_unit(self.config_model),
            "Day in selected period",
            hover_labels,
            show_points=self.show_tank_points_var.get(),
            bottom_padding=78,
        )
        self._set_tank_chart_controls_visible(bool(x and y))

    def _tank_range_slider_changed(self, changed: str) -> None:
        if self.tank_chart_range_mode_var.get() != "range":
            return
        start_index = int(round(self.tank_chart_range_start_var.get()))
        end_index = int(round(self.tank_chart_range_end_var.get()))
        if changed == "start" and start_index > end_index:
            self.tank_chart_range_end_var.set(start_index)
        elif changed == "end" and end_index < start_index:
            self.tank_chart_range_start_var.set(end_index)
        self._draw_tank_chart()

    def _change_tank_chart_year(self, direction: int) -> None:
        if self.results_df.empty:
            return
        dates = pd.to_datetime(self.results_df["Date"], errors="coerce")
        available_years = sorted(int(year) for year in dates.dropna().dt.year.unique())
        if not available_years:
            return
        current_index = available_years.index(self.tank_chart_year) if self.tank_chart_year in available_years else 0
        new_index = min(max(current_index + direction, 0), len(available_years) - 1)
        self.tank_chart_year = available_years[new_index]
        self._draw_tank_chart()

    def _set_tank_chart_year_from_entry(self, _event: tk.Event | None = None) -> str:
        dates = pd.to_datetime(self.results_df.get("Date", pd.Series(dtype="datetime64[ns]")), errors="coerce")
        available_years = sorted(int(year) for year in dates.dropna().dt.year.unique())
        try:
            requested_year = int(self.tank_chart_year_var.get().strip())
        except ValueError:
            requested_year = -1
        if requested_year not in available_years:
            self.tank_chart_year_var.set(str(self.tank_chart_year) if self.tank_chart_year is not None else "--")
            if available_years:
                messagebox.showwarning(
                    APP_TITLE,
                    f"No analyzed tank data is available for {requested_year if requested_year >= 0 else 'that year'}. "
                    f"Enter a year from {available_years[0]} through {available_years[-1]}.",
                    parent=self,
                )
            return "break"
        self.tank_chart_year = requested_year
        self._draw_tank_chart()
        return "break"

    def _draw_tank_level_histogram(self) -> None:
        canvas = self.histogram_canvas
        canvas.delete("all")
        canvas.hover_points = []
        if self.results_df.empty:
            return

        bin_count = 6
        unit = volume_unit(self.config_model)
        levels = [volume_to_display(value, self.config_model) for value in self.results_df["WaterInTankGallons"]]
        selected_capacity = volume_to_display(self.config_model.selected_tank_size_gal, self.config_model)
        upper = max(selected_capacity, max(levels, default=0.0), 1.0)
        bin_width = upper / bin_count
        counts = [0] * bin_count
        for level in levels:
            index = min(max(int(max(level, 0.0) / bin_width), 0), bin_count - 1)
            counts[index] += 1

        width = max(canvas.winfo_width(), 300)
        height = max(canvas.winfo_height(), 160)
        pad_left, pad_right, pad_top, pad_bottom = 48, 14, 32, 64
        plot_width = width - pad_left - pad_right
        plot_height = height - pad_top - pad_bottom
        max_count = max(counts) or 1
        canvas.create_text(
            width / 2,
            16,
            text=f"Tank Level Distribution - {format_number(selected_capacity, self.config_model, max_decimal_places=0)} {unit} tank",
            font=("Segoe UI", 10, "bold"),
        )

        for tick in range(5):
            y = pad_top + plot_height * tick / 4
            value = max_count * (4 - tick) / 4
            canvas.create_line(pad_left, y, width - pad_right, y, fill="#e6e6e6")
            canvas.create_text(pad_left - 7, y, text=format_number(value, self.config_model, max_decimal_places=0), anchor="e", font=("Segoe UI", 8))
        canvas.create_line(pad_left, pad_top, pad_left, height - pad_bottom, fill="#555")
        canvas.create_line(pad_left, height - pad_bottom, width - pad_right, height - pad_bottom, fill="#555")

        slot_width = plot_width / bin_count
        for index, count in enumerate(counts):
            left = pad_left + index * slot_width + 3
            right = pad_left + (index + 1) * slot_width - 3
            top = height - pad_bottom - (count / max_count) * plot_height
            bottom = height - pad_bottom
            canvas.create_rectangle(left, top, right, bottom, fill="#2e8b57", outline="#246b49")
            low = index * bin_width
            high = (index + 1) * bin_width
            canvas.create_text((left + right) / 2, bottom + 15, text=f"{format_number(low, self.config_model, max_decimal_places=0)}-{format_number(high, self.config_model, max_decimal_places=0)}", font=("Segoe UI", 7))
            canvas.create_text((left + right) / 2, max(top - 9, pad_top + 7), text=str(count), font=("Segoe UI", 8))
        canvas.create_text(13, height / 2, text="Days", angle=90, font=("Segoe UI", 8))
        canvas.create_text(
            pad_left + plot_width / 2,
            ((height - pad_bottom + 15) + height) / 2,
            text=f"Tank level range ({unit})",
            font=("Segoe UI", 8),
        )

    def _draw_yearly_demand_reliability(self) -> None:
        canvas = self.yearly_reliability_canvas
        canvas.delete("all")
        canvas.hover_points = []
        yearly = _yearly_demand_reliability(self.results_df)
        width = max(canvas.winfo_width(), 300)
        height = max(canvas.winfo_height(), 160)
        pad_left, pad_right, pad_top, pad_bottom = 50, 14, 46, 44
        plot_width = width - pad_left - pad_right
        plot_height = height - pad_top - pad_bottom
        selected_capacity = volume_to_display(self.config_model.selected_tank_size_gal, self.config_model)
        unit = volume_unit(self.config_model)
        canvas.create_text(
            width / 2,
            14,
            text=f"Yearly Demand Reliability - {format_number(selected_capacity, self.config_model, max_decimal_places=0)} {unit} tank",
            font=("Segoe UI", 10, "bold"),
        )
        canvas.create_rectangle(16, 27, 26, 35, fill="#2e8b57", outline="")
        canvas.create_text(31, 31, text="Demand met", anchor="w", font=("Segoe UI", 7))
        canvas.create_rectangle(112, 27, 122, 35, fill="#c94c4c", outline="")
        canvas.create_text(127, 31, text="Demand not met", anchor="w", font=("Segoe UI", 7))
        canvas.create_oval(224, 27, 232, 35, fill="#f2c94c", outline="#8a6d00")
        canvas.create_text(237, 31, text="Tank reliability", anchor="w", font=("Segoe UI", 7))
        for tick in range(5):
            value = 100 - tick * 25
            y = pad_top + plot_height * tick / 4
            canvas.create_line(pad_left, y, width - pad_right, y, fill="#e6e6e6")
            canvas.create_text(pad_left - 7, y, text=f"{value}%", anchor="e", font=("Segoe UI", 7))
        canvas.create_line(pad_left, pad_top, pad_left, height - pad_bottom, fill="#555")
        canvas.create_line(pad_left, height - pad_bottom, width - pad_right, height - pad_bottom, fill="#555")
        if not yearly:
            canvas.create_text(width / 2, height / 2, text="No data")
            return

        slot_width = plot_width / (len(yearly) + 1)
        label_step = max((len(yearly) + 7) // 8, 1)
        baseline = height - pad_bottom
        for index, row in enumerate(yearly):
            left = pad_left + index * slot_width + max(slot_width * 0.15, 1.0)
            right = pad_left + (index + 1) * slot_width - max(slot_width * 0.15, 1.0)
            met_height = plot_height * float(row["met_percent"]) / 100.0
            boundary = baseline - met_height
            canvas.create_rectangle(left, boundary, right, baseline, fill="#2e8b57", outline="#246b49")
            canvas.create_rectangle(left, pad_top, right, boundary, fill="#c94c4c", outline="#9e3737")
            center_x = (left + right) / 2
            canvas.create_oval(
                center_x - 4,
                boundary - 4,
                center_x + 4,
                boundary + 4,
                fill="#f2c94c",
                outline="#8a6d00",
                width=1,
            )
            label = (
                f"Year: {int(row['year'])}\n"
                f"Demand met: {format_number(int(row['met_days']), self.config_model, max_decimal_places=0)} days ({format_number(float(row['met_percent']), self.config_model)}%)\n"
                f"Demand not met: {format_number(int(row['unmet_days']), self.config_model, max_decimal_places=0)} days ({format_number(float(row['unmet_percent']), self.config_model)}%)"
            )
            if met_height > 0:
                canvas.hover_points.append((center_x, boundary + met_height / 2, label))
            unmet_height = plot_height - met_height
            if unmet_height > 0:
                canvas.hover_points.append((center_x, pad_top + unmet_height / 2, label))
            if index % label_step == 0 or index == len(yearly) - 1:
                canvas.create_text(center_x, baseline + 13, text=str(int(row["year"])), font=("Segoe UI", 7))
        average_reliability = float(self.results_df["ReliabilityPercent"].iloc[0])
        average_x = pad_left + (len(yearly) + 0.5) * slot_width
        average_y = baseline - plot_height * average_reliability / 100.0
        canvas.create_oval(
            average_x - 5,
            average_y - 5,
            average_x + 5,
            average_y + 5,
            fill="#f2c94c",
            outline="#8a6d00",
            width=1,
        )
        canvas.create_text(average_x, baseline + 13, text="Average", font=("Segoe UI", 7))
        canvas.hover_points.append(
            (average_x, average_y, f"Overall tank reliability: {format_number(average_reliability, self.config_model)}%")
        )
        canvas.create_text(12, pad_top + plot_height / 2, text="Days (%)", angle=90, font=("Segoe UI", 8))
        canvas.create_text(
            pad_left + plot_width / 2,
            ((baseline + 13) + height) / 2,
            text="Year",
            font=("Segoe UI", 8),
        )
        canvas.bind("<Motion>", self._show_chart_hover)
        canvas.bind("<Leave>", self._hide_chart_hover)

    def _draw_multitank_summary(self) -> None:
        unit = volume_unit(self.config_model)
        tank_series: list[tuple[str, list[float], list[float]]] = []
        distribution_series: list[tuple[str, list[float], list[float]]] = []
        yearly_series: list[tuple[str, list[float], list[float]]] = []
        for tank_size, results in sorted(self.comparison_results.items()):
            if results.empty:
                continue
            display_size = volume_to_display(tank_size, self.config_model)
            label = f"{format_number(display_size, self.config_model, max_decimal_places=0)} {unit}"
            tank_series.append(
                (
                    label,
                    [float(index) for index in range(len(results))],
                    [volume_to_display(value, self.config_model) for value in results["WaterInTankGallons"]],
                )
            )

            percentages = [
                min(max(float(value) / tank_size * 100.0, 0.0), 100.0)
                for value in results["WaterInTankGallons"]
            ]
            counts = [0] * 6
            for percentage in percentages:
                counts[min(int(percentage / (100.0 / 6)), 5)] += 1
            total = len(percentages) or 1
            distribution_series.append(
                (
                    label,
                    [(index + 0.5) * (100.0 / 6) for index in range(6)],
                    [count / total * 100.0 for count in counts],
                )
            )

            yearly = _yearly_demand_reliability(results)
            yearly_series.append(
                (
                    label,
                    [float(row["year"]) for row in yearly],
                    [float(row["met_percent"]) for row in yearly],
                )
            )

        self._draw_multiline_chart(
            self.multitank_tank_canvas,
            tank_series,
            f"Tank Water Over Time ({unit})",
            unit,
            "Day of record",
        )
        self._draw_multiline_chart(
            self.multitank_distribution_canvas,
            distribution_series,
            "Tank Level Distribution",
            "Days (%)",
            "Tank level (% of capacity)",
            y_bounds=(0.0, 100.0),
        )
        self._draw_multiline_chart(
            self.multitank_yearly_canvas,
            yearly_series,
            "Yearly Demand Reliability",
            "Demand met (%)",
            "Year",
            y_bounds=(0.0, 100.0),
        )

    def _draw_multiline_chart(
        self,
        canvas: tk.Canvas,
        series: list[tuple[str, list[float], list[float]]],
        title: str,
        y_label: str,
        x_label: str,
        y_bounds: tuple[float, float] | None = None,
    ) -> None:
        canvas.delete("all")
        canvas.hover_points = []
        width = max(canvas.winfo_width(), 400)
        height = max(canvas.winfo_height(), 170)
        pad_left, pad_right, pad_top, pad_bottom = 58, 18, 48, 48
        plot_width = width - pad_left - pad_right
        plot_height = height - pad_top - pad_bottom
        canvas.create_text(width / 2, 14, text=title, font=("Segoe UI", 10, "bold"))
        if not series:
            canvas.create_text(width / 2, height / 2, text="Add comparison tank sizes and run the analysis")
            return
        all_x = [value for _label, x_values, _y_values in series for value in x_values]
        all_y = [value for _label, _x_values, y_values in series for value in y_values]
        if not all_x or not all_y:
            canvas.create_text(width / 2, height / 2, text="No comparison data")
            return
        x_min, x_max = min(all_x), max(all_x)
        y_min, y_max = y_bounds if y_bounds is not None else (min(all_y), max(all_y))
        if x_min == x_max:
            x_max = x_min + 1.0
        if y_min == y_max:
            y_max = y_min + 1.0
        colors = ("#0b5cab", "#2e8b57", "#c94c4c", "#7b4ab5", "#d17a00", "#00838f", "#6d4c41")
        for tick in range(5):
            y = pad_top + plot_height * tick / 4
            value = y_max - (y_max - y_min) * tick / 4
            canvas.create_line(pad_left, y, width - pad_right, y, fill="#e6e6e6")
            canvas.create_text(pad_left - 7, y, text=format_number(value, self.config_model, max_decimal_places=0), anchor="e", font=("Segoe UI", 7))
            x = pad_left + plot_width * tick / 4
            x_value = x_min + (x_max - x_min) * tick / 4
            canvas.create_text(x, height - pad_bottom + 14, text=format_number(x_value, self.config_model, max_decimal_places=0), font=("Segoe UI", 7))
        canvas.create_line(pad_left, pad_top, pad_left, height - pad_bottom, fill="#555")
        canvas.create_line(pad_left, height - pad_bottom, width - pad_right, height - pad_bottom, fill="#555")
        for series_index, (label, x_values, y_values) in enumerate(series):
            color = colors[series_index % len(colors)]
            render_indices = self._chart_render_indices(y_values, max(int(plot_width * 1.5), 300))
            points: list[float] = []
            for index in render_indices:
                px = pad_left + (x_values[index] - x_min) / (x_max - x_min) * plot_width
                py = height - pad_bottom - (y_values[index] - y_min) / (y_max - y_min) * plot_height
                points.extend((px, py))
                canvas.hover_points.append((px, py, f"Tank: {label}\n{x_label}: {format_number(x_values[index], self.config_model, max_decimal_places=0)}\n{y_label}: {format_number(y_values[index], self.config_model, max_decimal_places=1)}"))
            if len(points) >= 4:
                canvas.create_line(*points, fill=color, width=2)
            legend_x = pad_left + series_index * max(plot_width / max(len(series), 1), 85)
            canvas.create_line(legend_x, 31, legend_x + 14, 31, fill=color, width=3)
            canvas.create_text(legend_x + 18, 31, text=label, anchor="w", font=("Segoe UI", 7))
        canvas.create_text(13, pad_top + plot_height / 2, text=y_label, angle=90, font=("Segoe UI", 8))
        canvas.create_text(pad_left + plot_width / 2, height - 8, text=x_label, font=("Segoe UI", 8))
        canvas.bind("<Motion>", self._show_chart_hover)
        canvas.bind("<Leave>", self._hide_chart_hover)

    def _draw_line_chart(
        self,
        canvas: tk.Canvas,
        x_values: list[float],
        y_values: list[float],
        title: str,
        y_label: str,
        x_label: str,
        hover_labels: list[str] | None = None,
        show_points: bool = True,
        bottom_padding: int = 58,
    ) -> None:
        canvas.delete("all")
        canvas.hover_points = []
        width = max(canvas.winfo_width(), 300)
        height = max(canvas.winfo_height(), 160)
        pad_left, pad_right, pad_top, pad_bottom = 56, 18, 32, bottom_padding
        plot_w = width - pad_left - pad_right
        plot_h = height - pad_top - pad_bottom
        canvas.create_text(width / 2, 16, text=title, font=("Segoe UI", 10, "bold"))
        canvas.create_line(pad_left, pad_top, pad_left, height - pad_bottom, fill="#555")
        canvas.create_line(pad_left, height - pad_bottom, width - pad_right, height - pad_bottom, fill="#555")
        if not x_values or not y_values:
            canvas.create_text(width / 2, height / 2, text="No data")
            return
        x_min, x_max = min(x_values), max(x_values)
        y_min, y_max = min(y_values), max(y_values)
        if x_min == x_max:
            x_max = x_min + 1
        if y_min == y_max:
            y_max = y_min + 1
        points: list[float] = []
        hover_labels = hover_labels or [f"X: {format_number(x, self.config_model)}\nY: {format_number(y, self.config_model)}" for x, y in zip(x_values, y_values)]
        render_indices = self._chart_render_indices(y_values, max(int(plot_w * 2), 300))
        for index in render_indices:
            x = x_values[index]
            y = y_values[index]
            hover_label = hover_labels[index]
            px = pad_left + ((x - x_min) / (x_max - x_min)) * plot_w
            py = height - pad_bottom - ((y - y_min) / (y_max - y_min)) * plot_h
            points.extend([px, py])
            canvas.hover_points.append((px, py, hover_label))
        if len(points) >= 4:
            canvas.create_line(*points, fill="#0b5cab", width=2, tags=("chart-data",))
        if show_points:
            for px, py, _hover_label in canvas.hover_points:
                canvas.create_oval(
                    px - 2,
                    py - 2,
                    px + 2,
                    py + 2,
                    fill="#0b5cab",
                    outline="",
                    tags=("chart-data",),
                )
        for i in range(5):
            y = pad_top + (plot_h * i / 4)
            value = y_max - ((y_max - y_min) * i / 4)
            canvas.create_line(pad_left, y, width - pad_right, y, fill="#e6e6e6")
            canvas.create_line(pad_left - 5, y, pad_left, y, fill="#555")
            canvas.create_text(pad_left - 8, y, text=format_number(value, self.config_model, max_decimal_places=0), anchor="e", font=("Segoe UI", 8))
        for i in range(5):
            x = pad_left + (plot_w * i / 4)
            value = x_min + ((x_max - x_min) * i / 4)
            canvas.create_line(x, height - pad_bottom, x, height - pad_bottom + 5, fill="#555")
            canvas.create_text(x, height - pad_bottom + 17, text=format_number(value, self.config_model, max_decimal_places=0), font=("Segoe UI", 8))
        canvas.create_text(14, height / 2, text=y_label, angle=90, font=("Segoe UI", 8))
        canvas.create_text(
            pad_left + plot_w / 2,
            ((height - pad_bottom + 17) + height) / 2,
            text=x_label,
            font=("Segoe UI", 8),
        )
        canvas.tag_raise("chart-data")
        canvas.bind("<Motion>", self._show_chart_hover)
        canvas.bind("<Leave>", self._hide_chart_hover)

    @staticmethod
    def _chart_render_indices(y_values: list[float], max_points: int) -> list[int]:
        point_count = len(y_values)
        if point_count <= max_points:
            return list(range(point_count))

        bucket_count = max((max_points - 2) // 2, 1)
        interior_count = point_count - 2
        bucket_size = max((interior_count + bucket_count - 1) // bucket_count, 1)
        indices = [0]
        for start in range(1, point_count - 1, bucket_size):
            stop = min(start + bucket_size, point_count - 1)
            bucket = range(start, stop)
            low = min(bucket, key=y_values.__getitem__)
            high = max(bucket, key=y_values.__getitem__)
            indices.extend(sorted({low, high}))
        indices.append(point_count - 1)
        return indices

    def _show_chart_hover(self, event: tk.Event) -> None:
        canvas = event.widget
        points = getattr(canvas, "hover_points", [])
        if not points:
            return
        nearest = min(points, key=lambda point: (point[0] - event.x) ** 2 + (point[1] - event.y) ** 2)
        distance_squared = (nearest[0] - event.x) ** 2 + (nearest[1] - event.y) ** 2
        if distance_squared > 225:
            self._hide_chart_hover(event)
            return

        canvas.delete("hover")
        px, py, label = nearest
        canvas.create_oval(px - 5, py - 5, px + 5, py + 5, outline="#c2410c", width=2, tags="hover")
        canvas_width = max(canvas.winfo_width(), 1)
        canvas_height = max(canvas.winfo_height(), 1)
        margin = 8
        pad = 5
        text_width = max(min(canvas_width - 2 * (margin + pad), 240), 80)
        text_id = canvas.create_text(
            px + 12,
            py - 30,
            text=label,
            anchor="nw",
            width=text_width,
            font=("Segoe UI", 8),
            tags="hover",
        )
        bbox = canvas.bbox(text_id)
        if bbox is None:
            return
        shift_x = 0
        shift_y = 0
        if bbox[2] + pad > canvas_width - margin:
            shift_x = canvas_width - margin - pad - bbox[2]
        if bbox[0] + shift_x - pad < margin:
            shift_x += margin + pad - (bbox[0] + shift_x)
        if bbox[3] + pad > canvas_height - margin:
            shift_y = canvas_height - margin - pad - bbox[3]
        if bbox[1] + shift_y - pad < margin:
            shift_y += margin + pad - (bbox[1] + shift_y)
        if shift_x or shift_y:
            canvas.move(text_id, shift_x, shift_y)
            bbox = canvas.bbox(text_id)
            if bbox is None:
                return
        rect_id = canvas.create_rectangle(
            bbox[0] - pad,
            bbox[1] - pad,
            bbox[2] + pad,
            bbox[3] + pad,
            fill="#fffff0",
            outline="#666",
            tags="hover",
        )
        canvas.tag_lower(rect_id, text_id)

    def _hide_chart_hover(self, event: tk.Event) -> None:
        event.widget.delete("hover")


class SurfaceLibraryDialog(tk.Toplevel):
    """Offer the built-in collection surfaces only when a user asks to add one."""

    COMPACT_ROW_COUNT = 7
    SCREEN_MARGIN = 24

    def __init__(self, parent: RainwaterTkApp) -> None:
        super().__init__(parent)
        self.title("Add collection surface")
        self.resizable(False, False)
        self.result: Surface | None = None

        body = ttk.Frame(self, padding=12)
        body.grid(sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.rowconfigure(2, weight=1)
        ttk.Label(
            body,
            text="Collection surface library",
            font=("TkDefaultFont", 10, "bold"),
        ).grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(
            body,
            text="Choose a common surface, then enter its area and other details.",
            foreground="#667278",
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(2, 8))

        self.surface_tree = ttk.Treeview(
            body,
            columns=("surface", "runoff"),
            show="headings",
            height=max(self.COMPACT_ROW_COUNT, len(DEFAULT_SURFACES)),
            selectmode="browse",
        )
        self.surface_tree.heading("surface", text="Surface")
        self.surface_tree.heading("runoff", text="Default runoff coeff.")
        self.surface_tree.column("surface", width=280)
        self.surface_tree.column("runoff", width=150, anchor="e")
        self.surface_tree.grid(row=2, column=0, sticky="nsew")
        surface_scroll = ttk.Scrollbar(body, orient="vertical", command=self.surface_tree.yview)
        surface_scroll.grid(row=2, column=1, sticky="ns")
        self.surface_tree.configure(yscrollcommand=surface_scroll.set)
        for index, surface in enumerate(DEFAULT_SURFACES):
            self.surface_tree.insert(
                "",
                "end",
                iid=str(index),
                values=(surface.name, format_number(surface.runoff_coefficient)),
            )
        if DEFAULT_SURFACES:
            self.surface_tree.selection_set("0")
            self.surface_tree.focus("0")

        buttons = ttk.Frame(body)
        buttons.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        ttk.Button(
            buttons, text="Custom surface...", command=self._choose_custom
        ).pack(side="left")
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(
            side="right", padx=(6, 0)
        )
        ttk.Button(buttons, text="Add selected", command=self._choose_selected).pack(
            side="right"
        )

        self.transient(parent)
        self.grab_set()
        self.bind("<Escape>", lambda _event: self.destroy())
        self.surface_tree.bind("<Double-1>", self._choose_selected)
        self.surface_tree.bind("<Return>", self._choose_selected)
        self.after_idle(self._focus_dialog)

    @staticmethod
    def _copy_surface(surface: Surface) -> Surface:
        return Surface(
            surface.name,
            surface.area,
            surface.runoff_coefficient,
            surface.first_flush_depth_inches,
        )

    def _choose_selected(self, _event: tk.Event | None = None) -> None:
        selected = self.surface_tree.selection()
        if not selected:
            return
        self.result = self._copy_surface(DEFAULT_SURFACES[int(selected[0])])
        self.destroy()

    def _choose_custom(self) -> None:
        self.result = Surface(
            "Custom surface",
            0.0,
            Surface(name="Default").runoff_coefficient,
        )
        self.destroy()

    def _focus_dialog(self) -> None:
        self.update_idletasks()
        parent = self.master
        work_x, work_y, work_width, work_height = parent._screen_work_area()
        maximum_height = max(work_height - (self.SCREEN_MARGIN * 2), 1)
        if self.winfo_reqheight() > maximum_height:
            self.surface_tree.configure(
                height=min(self.COMPACT_ROW_COUNT, len(DEFAULT_SURFACES))
            )
            self.update_idletasks()
        width = self.winfo_reqwidth()
        height = self.winfo_reqheight()
        centered_x = parent.winfo_rootx() + (parent.winfo_width() - width) // 2
        centered_y = parent.winfo_rooty() + (parent.winfo_height() - height) // 2
        x = min(max(centered_x, work_x + self.SCREEN_MARGIN), work_x + work_width - width - self.SCREEN_MARGIN)
        y = min(max(centered_y, work_y + self.SCREEN_MARGIN), work_y + work_height - height - self.SCREEN_MARGIN)
        self.geometry(f"{width}x{height}{x:+d}{y:+d}")
        self.deiconify()
        self.lift()
        self.surface_tree.focus_set()


class SurfaceDialog(tk.Toplevel):
    def __init__(self, parent: RainwaterTkApp, surface: Surface, config: ProjectConfig) -> None:
        super().__init__(parent)
        self.title("Edit Surface")
        self.resizable(False, False)
        self.result: Surface | None = None
        self.config_model = config
        self.name_var = tk.StringVar(value=surface.name)
        self.area_var = tk.StringVar(value=format_number(area_to_display(surface.area, config), config))
        self.runoff_var = tk.StringVar(value=format_number(surface.runoff_coefficient, config))
        self.first_flush_depth_inches = surface.first_flush_depth_inches
        body = ttk.Frame(self, padding=12)
        body.grid(sticky="nsew")
        ttk.Label(body, text="Surface").grid(row=0, column=0, sticky="w", pady=3)
        self.name_entry = ttk.Entry(body, textvariable=self.name_var, width=36)
        self.name_entry.grid(row=0, column=1, pady=3)
        ttk.Label(body, text=f"Area ({area_unit(config)})").grid(row=1, column=0, sticky="w", pady=3)
        ttk.Entry(body, textvariable=self.area_var, width=18).grid(row=1, column=1, sticky="w", pady=3)
        ttk.Label(body, text="Runoff coefficient").grid(row=2, column=0, sticky="w", pady=3)
        ttk.Entry(body, textvariable=self.runoff_var, width=18).grid(row=2, column=1, sticky="w", pady=3)
        default_runoff = default_surface_runoff(surface.name)
        tk.Label(
            body,
            text=f"Default runoff coefficient: {format_number(default_runoff, config)}",
            fg="#777777",
        ).grid(row=3, column=1, sticky="w", pady=(0, 6))
        buttons = ttk.Frame(body)
        buttons.grid(row=4, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(buttons, text="Cancel", command=self.destroy).grid(row=0, column=0, padx=4)
        ttk.Button(buttons, text="Save", command=self._save).grid(row=0, column=1)
        self.transient(parent)
        self.grab_set()
        self.bind("<Escape>", lambda _event: self.destroy())
        self.after_idle(self._focus_dialog)

    def _focus_dialog(self) -> None:
        self.update_idletasks()
        parent = self.master
        dialog_width = self.winfo_reqwidth()
        dialog_height = self.winfo_reqheight()
        target_root_x = parent.winfo_rootx() + (parent.winfo_width() - dialog_width) // 2
        target_root_y = parent.winfo_rooty() + (parent.winfo_height() - dialog_height) // 2
        x = self.winfo_x() + target_root_x - self.winfo_rootx()
        y = self.winfo_y() + target_root_y - self.winfo_rooty()
        self.geometry(f"{dialog_width}x{dialog_height}{x:+d}{y:+d}")
        self.deiconify()
        self.lift()
        self.attributes("-topmost", True)
        self.after(10, self._center_mapped_dialog)
        self.after(50, lambda: self.attributes("-topmost", False) if self.winfo_exists() else None)
        self.name_entry.focus_force()
        self.name_entry.selection_range(0, tk.END)

    def _center_mapped_dialog(self) -> None:
        self.update_idletasks()
        parent = self.master
        target_root_x = parent.winfo_rootx() + (parent.winfo_width() - self.winfo_width()) // 2
        target_root_y = parent.winfo_rooty() + (parent.winfo_height() - self.winfo_height()) // 2
        x = self.winfo_x() + target_root_x - self.winfo_rootx()
        y = self.winfo_y() + target_root_y - self.winfo_rooty()
        self.geometry(f"{self.winfo_width()}x{self.winfo_height()}{x:+d}{y:+d}")

    def _save(self) -> None:
        self.result = Surface(
            name=self.name_var.get().strip() or "Other",
            area=max(0.0, area_to_internal(_float(self.area_var.get()), self.config_model)),
            runoff_coefficient=min(max(_float(self.runoff_var.get(), 0.0), 0.0), 1.0),
            first_flush_depth_inches=self.first_flush_depth_inches,
        )
        self.destroy()


class ReportDialog(tk.Toplevel):
    def __init__(self, parent: RainwaterTkApp, defaults: dict[str, object]) -> None:
        super().__init__(parent)
        self.title("Report details")
        self.resizable(True, False)
        self.result: dict[str, object] | None = None
        self.author_name = str(defaults.get("author_name", ""))
        self.vars = {
            "client_name": tk.StringVar(value=str(defaults["client_name"])),
            "date": tk.StringVar(value=str(defaults["date"])),
            "location": tk.StringVar(value=str(defaults["location"])),
            "project_name": tk.StringVar(value=str(defaults["project_name"])),
        }

        body = ttk.Frame(self, padding=12)
        body.grid(sticky="nsew")
        body.columnconfigure(1, weight=1)

        fields = [
            ("client_name", "Client name"),
            ("date", "Date"),
            ("location", "Location"),
            ("project_name", "Project name"),
        ]
        for row, (key, label) in enumerate(fields):
            ttk.Label(body, text=label).grid(row=row, column=0, sticky="w", pady=3)
            ttk.Entry(body, textvariable=self.vars[key], width=52).grid(row=row, column=1, sticky="ew", pady=3)

        ttk.Label(body, text="End-uses of water").grid(row=4, column=0, sticky="nw", pady=3)
        self.end_uses_text = tk.Text(body, width=52, height=4, wrap="word")
        self.end_uses_text.grid(row=4, column=1, sticky="ew", pady=3)
        self.end_uses_text.insert("1.0", str(defaults["end_uses"]))

        buttons = ttk.Frame(body)
        buttons.grid(row=5, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(buttons, text="Cancel", command=self.destroy).grid(row=0, column=0, padx=4)
        ttk.Button(buttons, text="Continue", command=self._save).grid(row=0, column=1)

        self.transient(parent)
        self.grab_set()

    def _save(self) -> None:
        self.result = {key: var.get().strip() for key, var in self.vars.items()}
        self.result["author_name"] = self.author_name.strip()
        self.result["end_uses"] = self.end_uses_text.get("1.0", "end").strip() or "Not specified"
        self.destroy()


class HourlyDemandScheduleDialog(tk.Toplevel):
    DAY_LABELS = dict(zip(WEEKDAY_KEYS, ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")))
    FRACTIONAL_MIN_VALUE = 0.0
    FRACTIONAL_MAX_VALUE = 1.0
    FRACTIONAL_INCREMENT = 0.01
    FRACTIONAL_FORMAT = "%.2f"

    def __init__(
        self,
        parent: RainwaterTkApp,
        config: ProjectConfig,
        *,
        schedule_type: str = FRACTIONAL_SCHEDULE_TYPE,
    ) -> None:
        super().__init__(parent)
        self.title("Edit Typical Week Demand Schedule")
        self.transient(parent)
        self.grab_set()
        self.saved = False
        self.config_model = config
        self.schedule_type = normalize_schedule_type(schedule_type)
        self.vars: dict[tuple[str, int], tk.StringVar] = {}
        body = ttk.Frame(self, padding=10)
        body.grid(sticky="nsew")
        ttk.Label(
            body,
            text=(
                "Binary occupancy schedule: choose 1 when occupied and 0 when unoccupied."
                if self.schedule_type == OCCUPANCY_SCHEDULE_TYPE
                else "Fractional schedule: values from 0 to 1 multiply flow or weight fixed demand."
            ),
            foreground="#5f6b70",
        ).grid(row=0, column=0, columnspan=8, sticky="w", pady=(0, 8))
        ttk.Label(body, text="Hour").grid(row=1, column=0, padx=3)
        for column, day in enumerate(WEEKDAY_KEYS, start=1):
            ttk.Label(body, text=self.DAY_LABELS[day]).grid(row=1, column=column, padx=3)
        for hour in range(24):
            ttk.Label(body, text=f"{hour:02d}:00-{(hour + 1) % 24:02d}:00").grid(
                row=hour + 2, column=0, sticky="e", padx=(0, 5), pady=1
            )
            for column, day in enumerate(WEEKDAY_KEYS, start=1):
                fractions = config.demand.hourly_weekly_fractions.get(day, [1.0] * 24)
                value = fractions[hour] if hour < len(fractions) else 0.0
                normalized_value = min(
                    max(float(value), self.FRACTIONAL_MIN_VALUE),
                    self.FRACTIONAL_MAX_VALUE,
                )
                variable = tk.StringVar(
                    value=(
                        str(int(normalized_value > 0.0))
                        if self.schedule_type == OCCUPANCY_SCHEDULE_TYPE
                        else self.FRACTIONAL_FORMAT % normalized_value
                    )
                )
                self.vars[(day, hour)] = variable
                if self.schedule_type == OCCUPANCY_SCHEDULE_TYPE:
                    ttk.Combobox(
                        body,
                        textvariable=variable,
                        values=("0", "1"),
                        state="readonly",
                        width=6,
                        justify="right",
                    ).grid(row=hour + 2, column=column, padx=2, pady=1)
                else:
                    ttk.Spinbox(
                        body,
                        textvariable=variable,
                        from_=self.FRACTIONAL_MIN_VALUE,
                        to=self.FRACTIONAL_MAX_VALUE,
                        increment=self.FRACTIONAL_INCREMENT,
                        format=self.FRACTIONAL_FORMAT,
                        width=8,
                        justify="right",
                    ).grid(row=hour + 2, column=column, padx=2, pady=1)
        actions = ttk.Frame(body)
        actions.grid(row=26, column=0, columnspan=8, sticky="ew", pady=(10, 0))
        ttk.Button(actions, text="Set all on", command=self._set_even).grid(row=0, column=0)
        ttk.Button(actions, text="Copy Monday to weekdays", command=self._copy_monday_to_weekdays).grid(
            row=0, column=1, padx=(8, 0)
        )
        ttk.Button(actions, text="Copy Monday to all days", command=self._copy_monday_to_all).grid(
            row=0, column=2, padx=(8, 0)
        )
        ttk.Button(actions, text="Cancel", command=self.destroy).grid(row=0, column=3, padx=(24, 4))
        ttk.Button(actions, text="Save", command=self._save).grid(row=0, column=4)
        self.bind("<Escape>", lambda _event: self.destroy())
        self.update_idletasks()
        parent.update_idletasks()
        x = parent.winfo_rootx() + max((parent.winfo_width() - self.winfo_reqwidth()) // 2, 0)
        y = parent.winfo_rooty() + max((parent.winfo_height() - self.winfo_reqheight()) // 2, 0)
        self.geometry(f"+{x}+{y}")
        self.focus_force()

    def _set_even(self) -> None:
        for variable in self.vars.values():
            variable.set(
                "1"
                if self.schedule_type == OCCUPANCY_SCHEDULE_TYPE
                else self.FRACTIONAL_FORMAT % self.FRACTIONAL_MAX_VALUE
            )

    def _copy_day(self, source: str, targets: list[str]) -> None:
        for target in targets:
            for hour in range(24):
                self.vars[(target, hour)].set(self.vars[(source, hour)].get())

    def _copy_monday_to_weekdays(self) -> None:
        self._copy_day("mon", ["tue", "wed", "thu", "fri"])

    def _copy_monday_to_all(self) -> None:
        self._copy_day("mon", WEEKDAY_KEYS[1:])

    def _save(self) -> None:
        schedule: dict[str, list[float]] = {}
        for day in WEEKDAY_KEYS:
            try:
                multipliers = [float(self.vars[(day, hour)].get()) for hour in range(24)]
            except ValueError:
                messagebox.showwarning(APP_TITLE, f"Enter numeric hourly multipliers for {self.DAY_LABELS[day]}.", parent=self)
                return
            if any(
                value < self.FRACTIONAL_MIN_VALUE
                or value > self.FRACTIONAL_MAX_VALUE
                for value in multipliers
            ):
                messagebox.showwarning(
                    APP_TITLE,
                    f"Hourly multipliers for {self.DAY_LABELS[day]} must be between 0 and 1.",
                    parent=self,
                )
                return
            if (
                self.schedule_type == OCCUPANCY_SCHEDULE_TYPE
                and any(value not in {0.0, 1.0} for value in multipliers)
            ):
                messagebox.showwarning(
                    APP_TITLE,
                    f"Occupancy values for {self.DAY_LABELS[day]} must be 0 or 1.",
                    parent=self,
                )
                return
            schedule[day] = multipliers
        self.config_model.demand.hourly_weekly_fractions = schedule
        self.config_model.demand.hourly_schedule_enabled = True
        self.saved = True
        self.destroy()


class DemandObjectDialog(tk.Toplevel):
    OBJECT_TYPES = (
        "Irrigation system", "Toilet", "Sink", "Urinal", "Cooling tower", "Ice making",
        "Ice skating", "Other indoor", "Vehicle washing", "Other outdoor", "Other",
    )
    MODE_LABELS = {
        "Scheduled flow": "scheduled_flow",
        "Occupational - Fixture use (people x uses)": "fixture_usage",
        "Occupational - Recurring daily volume": "recurring_daily",
        "Occupational - Monthly volume": "monthly_volume",
    }
    OCCUPATIONAL_MODES = {"fixture_usage", "recurring_daily", "monthly_volume"}
    DAY_LABELS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")

    def __init__(self, parent: RainwaterTkApp, config: ProjectConfig, demand_object: DemandObject) -> None:
        super().__init__(parent)
        self.title("Edit Demand Object")
        self.resizable(False, True)
        self.transient(parent)
        self.grab_set()
        self.config_model = config
        self.result: DemandObject | None = None
        self.original = copy.deepcopy(demand_object)
        self.name_var = tk.StringVar(value=demand_object.name)
        self.type_var = tk.StringVar(
            value=demand_object.object_type if demand_object.object_type in self.OBJECT_TYPES else "Other"
        )
        self.sewer_eligible_var = tk.BooleanVar(value=bool(demand_object.sewer_eligible))
        initial_flow_unit = "lpm" if is_metric(config) else "gpm"
        self.instantaneous_demand_unit_var = tk.StringVar(value=initial_flow_unit)
        self._instantaneous_demand_unit = initial_flow_unit
        self.instantaneous_demand_var = tk.StringVar(
            value=format_number(
                _demand_flow_from_gallons_per_minute(
                    demand_object.instantaneous_demand_gallons_per_minute,
                    initial_flow_unit,
                ),
                config,
                max_decimal_places=8,
            )
        )
        self.project_schedule_names = list(config.demand.hourly_schedule_library)
        mode_label = next(
            (label for label, value in self.MODE_LABELS.items() if value == demand_object.demand_mode),
            "Scheduled flow",
        )
        initial_mode = self.MODE_LABELS[mode_label]
        schedule_names = self._compatible_schedule_names(initial_mode)
        selected_schedule = (
            demand_object.schedule_name
            if demand_object.schedule_name in schedule_names
            else (schedule_names[0] if schedule_names else "")
        )
        self.schedule_var = tk.StringVar(value=selected_schedule)
        self.mode_var = tk.StringVar(value=mode_label)
        self.daily_volume_var = tk.StringVar(
            value=format_number(
                volume_to_display(demand_object.recurring_daily_gallons, config),
                config,
                max_decimal_places=8,
            )
        )
        default_fixture_uses = (
            DEFAULT_TOILET_FLUSHES_PER_PERSON_PER_DAY
            if demand_object.object_type == "Toilet"
            else 1.0
        )
        default_fixture_volume = (
            DEFAULT_TOILET_VOLUME_GALLONS_PER_FLUSH
            if demand_object.object_type == "Toilet"
            else 0.0
        )
        self.fixture_people_var = tk.StringVar(
            value=format_number(
                demand_object.fixture_people or 1.0, config, max_decimal_places=8
            )
        )
        self.fixture_uses_var = tk.StringVar(
            value=format_number(
                demand_object.fixture_uses_per_person_per_day or default_fixture_uses,
                config,
                max_decimal_places=8,
            )
        )
        fixture_volume = (
            demand_object.fixture_volume_gallons_per_use
            or default_fixture_volume
        )
        self.fixture_volume_var = tk.StringVar(
            value=format_number(
                volume_to_display(fixture_volume, config),
                config,
                max_decimal_places=8,
            )
        )
        self.fixture_uses_label_var = tk.StringVar()
        self.fixture_volume_label_var = tk.StringVar()
        self.fixture_guidance_var = tk.StringVar()
        existing_monthly_values = dict(
            demand_object.monthly_demand_gallons
            if demand_object.demand_mode == "monthly_volume"
            else {}
        )
        self.monthly_vars = {
            month: tk.StringVar(
                value=format_number(
                    volume_to_display(
                        float(existing_monthly_values.get(month, 0.0)), config
                    ),
                    config,
                    max_decimal_places=8,
                )
            )
            for month in MONTH_KEYS
        }
        self.identity_error_var = tk.StringVar()
        self.demand_error_var = tk.StringVar()
        self.schedule_help_var = tk.StringVar()
        self.summary_var = tk.StringVar()

        body = ttk.Frame(self, padding=8)
        body.grid(sticky="nsew")
        body.columnconfigure(0, weight=1)

        identity = ttk.LabelFrame(body, text="Identity", padding=8)
        identity.grid(row=0, column=0, sticky="ew")
        identity.columnconfigure(1, weight=1)
        ttk.Label(identity, text="Name").grid(row=0, column=0, sticky="w", pady=3, padx=(0, 8))
        self.name_entry = ttk.Entry(identity, textvariable=self.name_var, width=42)
        self.name_entry.grid(row=0, column=1, sticky="ew", pady=3)
        ttk.Label(identity, text="Type").grid(row=1, column=0, sticky="w", pady=3, padx=(0, 8))
        type_combo = ttk.Combobox(
            identity,
            textvariable=self.type_var,
            values=self.OBJECT_TYPES,
            state="readonly",
            width=39,
        )
        type_combo.grid(row=1, column=1, sticky="ew", pady=3)
        type_combo.bind("<<ComboboxSelected>>", self._demand_type_changed)
        ttk.Label(identity, text="Demand mode").grid(row=2, column=0, sticky="w", pady=3, padx=(0, 8))
        mode_combo = ttk.Combobox(
            identity, textvariable=self.mode_var, values=tuple(self.MODE_LABELS),
            state="readonly", width=39,
        )
        mode_combo.grid(row=2, column=1, sticky="ew", pady=3)
        mode_combo.bind("<<ComboboxSelected>>", self._mode_changed)
        ttk.Label(identity, textvariable=self.identity_error_var, foreground="#c62828").grid(
            row=3, column=1, sticky="w", pady=(2, 0)
        )

        demand = ttk.LabelFrame(body, text="Demand calculation", padding=8)
        demand.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        demand.columnconfigure(1, weight=1)
        ttk.Label(demand, text="Schedule").grid(row=0, column=0, sticky="w", pady=3, padx=(0, 8))
        schedule_values = schedule_names
        self.schedule_combo = ttk.Combobox(
            demand, textvariable=self.schedule_var, values=schedule_values,
            state="readonly" if schedule_values else "disabled", width=39,
        )
        self.schedule_combo.grid(row=0, column=1, sticky="ew", pady=3)
        self.schedule_combo.bind("<<ComboboxSelected>>", lambda _event: self._refresh_dialog_state())
        ttk.Label(
            demand, textvariable=self.schedule_help_var, foreground="#667278",
            wraplength=560, justify="left",
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(2, 7))

        self.scheduled_frame = ttk.Frame(demand)
        self.scheduled_frame.grid(row=2, column=0, columnspan=2, sticky="ew")
        self.scheduled_frame.columnconfigure(1, weight=1)
        ttk.Label(self.scheduled_frame, text="Instantaneous demand").grid(
            row=0, column=0, sticky="w", pady=3, padx=(0, 8)
        )
        flow_row = ttk.Frame(self.scheduled_frame)
        flow_row.grid(row=0, column=1, sticky="ew", pady=3)
        flow_row.columnconfigure(0, weight=1)
        ttk.Entry(flow_row, textvariable=self.instantaneous_demand_var).grid(row=0, column=0, sticky="ew")
        demand_unit_combo = ttk.Combobox(
            flow_row,
            textvariable=self.instantaneous_demand_unit_var,
            values=DEMAND_FLOW_UNITS,
            state="readonly",
            width=9,
        )
        demand_unit_combo.grid(row=0, column=1, padx=(8, 0))
        demand_unit_combo.bind("<<ComboboxSelected>>", self._change_instantaneous_demand_unit)

        self.fixture_frame = ttk.Frame(demand)
        self.fixture_frame.grid(row=2, column=0, columnspan=2, sticky="ew")
        self.fixture_frame.columnconfigure(1, weight=1)
        ttk.Label(self.fixture_frame, text="Number of people").grid(
            row=0, column=0, sticky="w", pady=3, padx=(0, 8)
        )
        ttk.Entry(self.fixture_frame, textvariable=self.fixture_people_var).grid(
            row=0, column=1, sticky="ew", pady=3
        )
        ttk.Label(self.fixture_frame, textvariable=self.fixture_uses_label_var).grid(
            row=1, column=0, sticky="w", pady=3, padx=(0, 8)
        )
        ttk.Entry(self.fixture_frame, textvariable=self.fixture_uses_var).grid(
            row=1, column=1, sticky="ew", pady=3
        )
        ttk.Label(self.fixture_frame, textvariable=self.fixture_volume_label_var).grid(
            row=2, column=0, sticky="w", pady=3, padx=(0, 8)
        )
        fixture_volume_row = ttk.Frame(self.fixture_frame)
        fixture_volume_row.grid(row=2, column=1, sticky="ew", pady=3)
        fixture_volume_row.columnconfigure(0, weight=1)
        ttk.Entry(fixture_volume_row, textvariable=self.fixture_volume_var).grid(
            row=0, column=0, sticky="ew"
        )
        ttk.Label(fixture_volume_row, text=volume_unit(config)).grid(
            row=0, column=1, padx=(8, 0)
        )
        ttk.Label(
            self.fixture_frame,
            textvariable=self.fixture_guidance_var,
            foreground="#667278",
            wraplength=560,
            justify="left",
        ).grid(row=3, column=0, columnspan=2, sticky="w", pady=(4, 7))
        self.recurring_frame = ttk.Frame(demand)
        self.recurring_frame.grid(row=2, column=0, columnspan=2, sticky="ew")
        self.recurring_frame.columnconfigure(1, weight=1)
        ttk.Label(self.recurring_frame, text=f"Recurring volume ({volume_unit(config)}/day)").grid(
            row=0, column=0, sticky="w", pady=3, padx=(0, 8)
        )
        ttk.Entry(self.recurring_frame, textvariable=self.daily_volume_var).grid(
            row=0, column=1, sticky="ew", pady=3
        )

        self.monthly_mode_frame = ttk.Frame(demand)
        self.monthly_mode_frame.grid(row=2, column=0, columnspan=2, sticky="ew")
        ttk.Label(
            self.monthly_mode_frame,
            text="Enter the total demand volume for each month.",
            foreground="#667278",
        ).grid(row=0, column=0, sticky="w")

        self.monthly_table_frame = ttk.LabelFrame(
            demand, text=f"January-December values ({volume_unit(config)})", padding=8
        )
        self.monthly_table_frame.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(7, 0))
        for offset, month in enumerate(MONTH_KEYS):
            group = 0 if offset < 6 else 1
            row = offset if offset < 6 else offset - 6
            column = group * 2
            ttk.Label(self.monthly_table_frame, text=MONTH_LABELS[month]).grid(
                row=row, column=column, sticky="w", padx=(0 if group == 0 else 18, 6), pady=2
            )
            ttk.Entry(
                self.monthly_table_frame, textvariable=self.monthly_vars[month], width=13,
            ).grid(row=row, column=column + 1, sticky="ew", pady=2)
        ttk.Label(demand, textvariable=self.demand_error_var, foreground="#c62828").grid(
            row=4, column=0, columnspan=2, sticky="w", pady=(6, 0)
        )

        billing = ttk.LabelFrame(body, text="Billing", padding=8)
        billing.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        ttk.Checkbutton(
            billing, text="Eligible for sewer-charge savings",
            variable=self.sewer_eligible_var, command=self._refresh_dialog_state,
        ).grid(row=0, column=0, sticky="w")
        self.billing_help_var = tk.StringVar()
        ttk.Label(
            billing, textvariable=self.billing_help_var, foreground="#667278",
            wraplength=560, justify="left",
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))

        summary = ttk.LabelFrame(body, text="Calculated summary", padding=8)
        summary.grid(row=3, column=0, sticky="ew", pady=(6, 0))
        ttk.Label(summary, textvariable=self.summary_var, justify="left").grid(
            row=0, column=0, sticky="w"
        )

        buttons = ttk.Frame(body)
        buttons.grid(row=4, column=0, sticky="e", pady=(6, 0))
        ttk.Button(buttons, text="Cancel", command=self.destroy).grid(row=0, column=0, padx=(0, 6))
        self.save_button = ttk.Button(buttons, text="Save", command=self._save)
        self.save_button.grid(row=0, column=1)
        self.bind("<Escape>", lambda _event: self.destroy())
        self.bind("<Return>", lambda _event: self._save())
        for variable in (
            self.name_var, self.mode_var, self.schedule_var, self.instantaneous_demand_var,
            self.daily_volume_var, self.fixture_people_var, self.fixture_uses_var,
            self.fixture_volume_var, self.sewer_eligible_var,
            *self.monthly_vars.values(),
        ):
            variable.trace_add("write", lambda *_args: self._refresh_dialog_state())
        self._refresh_dialog_state()
        self.after_idle(self._focus_dialog)

    def _focus_dialog(self) -> None:
        self.update_idletasks()
        parent = self.master
        x = parent.winfo_rootx() + max((parent.winfo_width() - self.winfo_reqwidth()) // 2, 0)
        y = parent.winfo_rooty() + max((parent.winfo_height() - self.winfo_reqheight()) // 2, 0)
        self.geometry(f"+{x}+{y}")
        self.lift()
        self.focus_force()
        self.name_entry.focus_set()
        self.name_entry.selection_range(0, tk.END)

    def _demand_type_changed(self, _event: tk.Event | None = None) -> None:
        self.sewer_eligible_var.set(
            default_sewer_eligible_for_object_type(self.type_var.get())
        )
        if (
            self.type_var.get() in {"Toilet", "Sink"}
            and self.original.name == "New demand object"
            and self.MODE_LABELS.get(self.mode_var.get()) == "scheduled_flow"
        ):
            self.mode_var.set("Occupational - Fixture use (people x uses)")
            if self.name_var.get().strip() == "New demand object":
                self.name_var.set(self.type_var.get())
        self._mode_changed()

    def _mode_changed(self, _event: tk.Event | None = None) -> None:
        mode = self.MODE_LABELS.get(self.mode_var.get(), "scheduled_flow")
        compatible_names = self._compatible_schedule_names(mode)
        self.schedule_combo.configure(
            values=compatible_names,
            state="readonly" if compatible_names else "disabled",
        )
        if self.schedule_var.get() not in compatible_names:
            self.schedule_var.set(compatible_names[0] if compatible_names else "")
        self._refresh_dialog_state()

    def _compatible_schedule_names(self, mode: str) -> list[str]:
        if mode not in self.OCCUPATIONAL_MODES:
            return list(self.project_schedule_names)
        return [
            name
            for name in self.project_schedule_names
            if self.config_model.demand.hourly_schedule_types.get(
                name, FRACTIONAL_SCHEDULE_TYPE
            )
            == OCCUPANCY_SCHEDULE_TYPE
        ]

    def _parsed_nonnegative(self, variable: tk.StringVar) -> float | None:
        try:
            value = parse_number(variable.get(), float("nan"))
        except ValueError:
            return None
        return value if math.isfinite(value) and value >= 0.0 else None

    def _monthly_display_values(self) -> dict[str, float] | None:
        values: dict[str, float] = {}
        for month, variable in self.monthly_vars.items():
            value = self._parsed_nonnegative(variable)
            if value is None:
                return None
            values[month] = value
        return values

    def _refresh_dialog_state(self) -> None:
        mode = self.MODE_LABELS.get(self.mode_var.get(), "scheduled_flow")
        for frame in (
            self.scheduled_frame,
            self.fixture_frame,
            self.recurring_frame,
            self.monthly_mode_frame,
        ):
            frame.grid_remove()
        if mode == "scheduled_flow":
            self.scheduled_frame.grid()
            self.monthly_table_frame.grid_remove()
            self.schedule_help_var.set(
                "Schedule values multiply the instantaneous flow in each hour."
            )
        elif mode == "fixture_usage":
            self.fixture_frame.grid()
            self.monthly_table_frame.grid_remove()
            is_toilet = self.type_var.get() == "Toilet"
            self.fixture_uses_label_var.set(
                "Flushes per person per day" if is_toilet else "Uses per person per day"
            )
            self.fixture_volume_label_var.set(
                "Volume per flush" if is_toilet else "Volume per use"
            )
            self.fixture_guidance_var.set(
                "Planning default: 3.0 flushes/person/day. EPA commercial guidance uses "
                "3 toilet flushes/day for female occupants and 1 for male occupants; the EPA "
                "residential calculator uses 5.05. Adjust for the population. The 1.28 gal "
                "fixture default is the WaterSense toilet limit."
                if is_toilet
                else (
                    "Enter the average sink volume per use. If flow and duration are known, "
                    "volume/use = flow rate x minutes/use. No sink volume is assumed."
                    if self.type_var.get() == "Sink"
                    else "Daily demand equals people x uses/person/day x volume/use. Adjust "
                    "each assumption for the fixture and population."
                )
            )
            self.schedule_help_var.set(
                "The schedule controls both active days and hourly timing. On each day with "
                "occupied hours, the calculated daily fixture volume is distributed evenly "
                "across those hours; an all-zero day has no fixture demand."
            )
        elif mode == "recurring_daily":
            self.recurring_frame.grid()
            self.monthly_table_frame.grid_remove()
            self.schedule_help_var.set(
                "The daily volume is applied on each day with occupied hours and distributed "
                "evenly across those hours. The occupancy schedule controls both active days "
                "and hourly timing."
            )
        else:
            self.monthly_mode_frame.grid()
            self.monthly_table_frame.grid()
            self.monthly_table_frame.configure(
                text=f"January-December monthly volumes ({volume_unit(self.config_model)}/month)"
            )
            self.schedule_help_var.set(
                "Each monthly total is divided across calendar days, then distributed "
                "across the selected occupancy schedule's occupied hours."
            )

        self.billing_help_var.set(
            "This type normally avoids both water and sewer charges. Confirm the local utility tariff."
            if self.sewer_eligible_var.get()
            else "This type normally avoids water charges only. Irrigation defaults to sewer-exempt; confirm the local utility tariff."
        )
        identity_error = "" if self.name_var.get().strip() else "Enter a demand object name."
        if mode in self.OCCUPATIONAL_MODES and not self._compatible_schedule_names(mode):
            demand_error = (
                "Add an Occupancy (binary) schedule to the project before saving."
            )
        elif (
            mode in self.OCCUPATIONAL_MODES
            and self.schedule_var.get() not in self._compatible_schedule_names(mode)
        ):
            demand_error = "Select an Occupancy (binary) schedule."
        elif (
            not self.schedule_var.get()
            or self.schedule_var.get()
            not in self.config_model.demand.hourly_schedule_library
        ):
            demand_error = (
                "Select an Occupancy (binary) schedule."
                if mode in self.OCCUPATIONAL_MODES
                else "Add or select a project schedule before saving."
            )
        elif mode == "scheduled_flow":
            flow = self._parsed_nonnegative(self.instantaneous_demand_var)
            demand_error = (
                "Instantaneous demand must be a non-negative number."
                if flow is None else ("Enter an instantaneous demand greater than zero." if flow == 0.0 else "")
            )
        elif mode == "fixture_usage":
            people = self._parsed_nonnegative(self.fixture_people_var)
            uses = self._parsed_nonnegative(self.fixture_uses_var)
            volume = self._parsed_nonnegative(self.fixture_volume_var)
            fixture_schedule = self.config_model.demand.hourly_schedule_library.get(
                self.schedule_var.get(), {}
            )
            schedule_has_active_day = any(
                any(float(value) > 0.0 for value in fixture_schedule.get(day, [])[:24])
                for day in WEEKDAY_KEYS
            )
            if people is None or uses is None or volume is None:
                demand_error = "People, uses, and volume per use must be non-negative numbers."
            elif not schedule_has_active_day:
                demand_error = "Select a schedule with at least one active day."
            elif people == 0.0:
                demand_error = "Enter at least one person."
            elif uses == 0.0:
                demand_error = "Enter at least one use per person per day."
            elif volume == 0.0:
                demand_error = (
                    "Enter the sink volume per use."
                    if self.type_var.get() == "Sink"
                    else "Enter a fixture volume greater than zero."
                )
            else:
                demand_error = ""
        elif mode == "recurring_daily":
            daily = self._parsed_nonnegative(self.daily_volume_var)
            recurring_schedule = self.config_model.demand.hourly_schedule_library.get(
                self.schedule_var.get(), {}
            )
            schedule_has_active_day = any(
                any(float(value) > 0.0 for value in recurring_schedule.get(day, [])[:24])
                for day in WEEKDAY_KEYS
            )
            if daily is None:
                demand_error = "Recurring volume must be a non-negative number."
            elif not schedule_has_active_day:
                demand_error = "Select a schedule with at least one occupied day."
            elif daily == 0.0:
                demand_error = "Enter a recurring volume greater than zero."
            else:
                demand_error = ""
        else:
            monthly = self._monthly_display_values()
            if monthly is None:
                demand_error = "Monthly values must be non-negative numbers."
            elif not any(monthly.values()):
                demand_error = "Enter at least one monthly volume greater than zero."
            else:
                demand_error = ""
        self.identity_error_var.set(identity_error)
        self.demand_error_var.set(demand_error)
        self.save_button.state(["disabled"] if identity_error or demand_error else ["!disabled"])
        self._update_calculated_summary()

    def _update_calculated_summary(self) -> None:
        mode = self.MODE_LABELS.get(self.mode_var.get(), "scheduled_flow")
        schedule = self.config_model.demand.hourly_schedule_library.get(self.schedule_var.get(), {})
        typical_day = 0.0
        typical_week = 0.0
        average_monthly = 0.0
        daily_summary_label = "Typical weekday"
        if mode == "scheduled_flow":
            display_flow = self._parsed_nonnegative(self.instantaneous_demand_var) or 0.0
            flow = _demand_flow_to_gallons_per_minute(
                display_flow, self.instantaneous_demand_unit_var.get()
            )
            daily_values = [
                flow * 60.0 * sum(float(value) for value in schedule.get(day, [])[:24])
                for day in WEEKDAY_KEYS
            ]
            typical_day = sum(daily_values[:5]) / 5.0
            typical_week = sum(daily_values)
            average_monthly = typical_week * 365.0 / (7.0 * 12.0)
        elif mode == "fixture_usage":
            daily_summary_label = "Active-day demand"
            people = self._parsed_nonnegative(self.fixture_people_var) or 0.0
            uses = self._parsed_nonnegative(self.fixture_uses_var) or 0.0
            volume = volume_to_internal(
                self._parsed_nonnegative(self.fixture_volume_var) or 0.0,
                self.config_model,
            )
            selected_days = sum(
                any(float(value) > 0.0 for value in schedule.get(day, [])[:24])
                for day in WEEKDAY_KEYS
            )
            typical_day = people * uses * volume
            typical_week = typical_day * selected_days
            average_monthly = typical_week * 365.0 / (7.0 * 12.0)
        elif mode == "recurring_daily":
            daily = volume_to_internal(
                self._parsed_nonnegative(self.daily_volume_var) or 0.0, self.config_model
            )
            selected_days = sum(
                any(float(value) > 0.0 for value in schedule.get(day, [])[:24])
                for day in WEEKDAY_KEYS
            )
            typical_day = daily
            typical_week = daily * selected_days
            average_monthly = typical_week * 365.0 / (7.0 * 12.0)
        else:
            monthly = self._monthly_display_values() or {}
            annual = sum(
                volume_to_internal(monthly.get(month, 0.0), self.config_model)
                for month in MONTH_KEYS
            )
            average_monthly = annual / 12.0
            typical_day = annual / 365.0
            typical_week = typical_day * 7.0
        unit = volume_unit(self.config_model)
        eligibility = "Yes" if self.sewer_eligible_var.get() else "No"
        self.summary_var.set(
            f"{daily_summary_label}: {format_number(volume_to_display(typical_day, self.config_model), self.config_model, max_decimal_places=1)} {unit}    |    "
            f"Typical week: {format_number(volume_to_display(typical_week, self.config_model), self.config_model, max_decimal_places=1)} {unit}\n"
            f"Average monthly estimate: {format_number(volume_to_display(average_monthly, self.config_model), self.config_model, max_decimal_places=1)} {unit}    |    "
            f"Sewer-charge eligible: {eligibility}"
        )

    def _change_instantaneous_demand_unit(self, _event: tk.Event | None = None) -> None:
        new_unit = self.instantaneous_demand_unit_var.get()
        old_unit = self._instantaneous_demand_unit
        if new_unit == old_unit:
            return
        try:
            current_value = parse_number(
                self.instantaneous_demand_var.get(), float("nan")
            )
            if not math.isfinite(current_value):
                raise ValueError
        except ValueError:
            self.instantaneous_demand_unit_var.set(old_unit)
            self.bell()
            return
        internal_flow = _demand_flow_to_gallons_per_minute(current_value, old_unit)
        converted = _demand_flow_from_gallons_per_minute(internal_flow, new_unit)
        self.instantaneous_demand_var.set(
            format_number(converted, self.config_model, max_decimal_places=8)
        )
        self._instantaneous_demand_unit = new_unit
        self._refresh_dialog_state()

    def _save(self) -> None:
        self._refresh_dialog_state()
        if "disabled" in self.save_button.state():
            self.bell()
            return
        name = self.name_var.get().strip()
        schedule_name = self.schedule_var.get()
        mode = self.MODE_LABELS[self.mode_var.get()]
        monthly_display = self._monthly_display_values() or {}
        monthly_internal = {
            month: volume_to_internal(value, self.config_model)
            for month, value in monthly_display.items()
        }
        operating_weekdays = (
            [
                index
                for index, day in enumerate(WEEKDAY_KEYS)
                if any(
                    float(value) > 0.0
                    for value in self.config_model.demand.hourly_schedule_library.get(
                        schedule_name, {}
                    ).get(day, [])[:24]
                )
            ]
            if mode in self.OCCUPATIONAL_MODES
            else [
                index for index in range(7)
            ]
        )
        self.result = DemandObject(
            name=name,
            object_type=self.type_var.get() or "Other",
            instantaneous_demand_gallons_per_minute=_demand_flow_to_gallons_per_minute(
                max(_float(self.instantaneous_demand_var.get()), 0.0),
                self.instantaneous_demand_unit_var.get(),
            ),
            schedule_name=schedule_name,
            demand_mode=mode,
            recurring_daily_gallons=volume_to_internal(
                max(_float(self.daily_volume_var.get()), 0.0), self.config_model
            ),
            fixture_people=max(_float(self.fixture_people_var.get()), 0.0),
            fixture_uses_per_person_per_day=max(
                _float(self.fixture_uses_var.get()), 0.0
            ),
            fixture_volume_gallons_per_use=volume_to_internal(
                max(_float(self.fixture_volume_var.get()), 0.0), self.config_model
            ),
            operating_days_per_week=len(operating_weekdays),
            operating_weekdays=operating_weekdays,
            monthly_daily_demand_gallons={},
            monthly_demand_gallons=(
                monthly_internal if mode == "monthly_volume" else {}
            ),
            sewer_eligible=bool(self.sewer_eligible_var.get()),
        )
        self.destroy()


class DemandDialog(tk.Toplevel):
    def __init__(self, parent: RainwaterTkApp, config: ProjectConfig, month: str) -> None:
        super().__init__(parent)
        self.title(f"Edit Demand - {MONTH_LABELS[month]}")
        self.resizable(False, False)
        self.saved = False
        self.config_model = config
        self.month = month
        self.vars: dict[str, tk.StringVar] = {}
        body = ttk.Frame(self, padding=12)
        body.grid(sticky="nsew")
        ttk.Label(body, text="Field").grid(row=0, column=0, sticky="w", pady=(0, 6))
        ttk.Label(body, text="Value").grid(row=0, column=1, sticky="w", pady=(0, 6))
        ttk.Label(body, text="Unit").grid(row=0, column=2, sticky="w", pady=(0, 6), padx=(8, 0))
        self.first_entry: ttk.Entry | None = None
        for row, (field, label) in enumerate(DEMAND_FIELDS):
            value = getattr(config.demand, field)[month]
            if field in {"male_occupancy", "female_occupancy"}:
                unit = "people/day"
            else:
                unit = f"{volume_unit(config)}/month"
                value = volume_to_display(value, config)
            var = tk.StringVar(value=format_number(value, self.config_model))
            self.vars[field] = var
            grid_row = row + 1
            ttk.Label(body, text=label).grid(row=grid_row, column=0, sticky="w", pady=2)
            entry = ttk.Entry(body, textvariable=var, width=18)
            entry.grid(row=grid_row, column=1, sticky="w", pady=2)
            if self.first_entry is None:
                self.first_entry = entry
            ttk.Label(body, text=unit).grid(row=grid_row, column=2, sticky="w", padx=(8, 0), pady=2)
        buttons = ttk.Frame(body)
        buttons.grid(row=len(DEMAND_FIELDS) + 1, column=0, columnspan=3, sticky="e", pady=(10, 0))
        ttk.Button(buttons, text="Cancel", command=self.destroy).grid(row=0, column=0, padx=4)
        ttk.Button(buttons, text="Save", command=self._save).grid(row=0, column=1)
        self.transient(parent)
        self.grab_set()
        self.bind("<Escape>", lambda _event: self.destroy())
        self.after_idle(self._focus_dialog)

    def _focus_dialog(self) -> None:
        self.update_idletasks()
        parent = self.master
        dialog_width = self.winfo_reqwidth()
        dialog_height = self.winfo_reqheight()
        target_root_x = parent.winfo_rootx() + (parent.winfo_width() - dialog_width) // 2
        target_root_y = parent.winfo_rooty() + (parent.winfo_height() - dialog_height) // 2
        x = self.winfo_x() + target_root_x - self.winfo_rootx()
        y = self.winfo_y() + target_root_y - self.winfo_rooty()
        self.geometry(f"{dialog_width}x{dialog_height}{x:+d}{y:+d}")
        self.deiconify()
        self.lift()
        self.attributes("-topmost", True)
        self.after(10, self._center_mapped_dialog)
        self.after(50, lambda: self.attributes("-topmost", False) if self.winfo_exists() else None)
        if self.first_entry is not None:
            self.first_entry.focus_force()
            self.first_entry.selection_range(0, tk.END)

    def _center_mapped_dialog(self) -> None:
        self.update_idletasks()
        parent = self.master
        target_root_x = parent.winfo_rootx() + (parent.winfo_width() - self.winfo_width()) // 2
        target_root_y = parent.winfo_rooty() + (parent.winfo_height() - self.winfo_height()) // 2
        x = self.winfo_x() + target_root_x - self.winfo_rootx()
        y = self.winfo_y() + target_root_y - self.winfo_rooty()
        self.geometry(f"{self.winfo_width()}x{self.winfo_height()}{x:+d}{y:+d}")

    def _save(self) -> None:
        for field, _label in DEMAND_FIELDS:
            value = max(0.0, _float(self.vars[field].get()))
            if field not in {"male_occupancy", "female_occupancy"}:
                value = volume_to_internal(value, self.config_model)
            getattr(self.config_model.demand, field)[self.month] = value
        self.saved = True
        self.destroy()


if __name__ == "__main__":
    if "--smoke-test" in sys.argv:
        smoke_data_dir = user_data_dir()
        smoke_data_dir.mkdir(parents=True, exist_ok=True)
        smoke_project_path = smoke_data_dir / "rainwater_projects.db"
        store = SQLiteStore(
            str(smoke_project_path),
            backup_dir=project_backup_dir(
                smoke_project_path, data_dir=smoke_data_dir
            ),
        )
        print(f"{APP_TITLE} smoke test OK; {len(store.list_projects())} saved project(s) visible.")
        raise SystemExit(0)
    app = RainwaterTkApp()
    app.mainloop()
