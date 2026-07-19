from __future__ import annotations

import csv
import copy
import datetime as dt
import html
import http.server
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
import webbrowser
from dataclasses import asdict
from functools import partial
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from urllib.parse import parse_qs, quote, urlparse

import pandas as pd
import pycountry
from tkintermapview import TkinterMapView, decimal_to_osm
from pypdf import PdfWriter
from pypdf.annotations import Link
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from rainwater_app.acis import (
    default_complete_calendar_range,
    fetch_daily_station_data,
    fetch_station_by_id,
    fetch_station_options,
    fetch_station_options_bbox,
)
from rainwater_app.analysis_state import analysis_input_signature
from rainwater_app.defaults import default_project_config, default_surface_runoff
from rainwater_app.eccc import (
    fetch_canadian_station_by_id,
    fetch_canadian_daily_station_data,
    fetch_canadian_station_options,
    fetch_canadian_station_options_bbox,
)
from rainwater_app.engine import AnalysisCancelledError, reliability_curve, simulate_hourly_tank, simulate_tank
from rainwater_app.financial import (
    calculate_financial_results,
    calculate_financial_results_from_annual_supply,
)
from rainwater_app.geocoding import geocode_osm_address, reverse_geocode_osm
from rainwater_app.models import (
    DemandObject,
    MONTH_KEYS,
    ProjectConfig,
    Surface,
    SystemComponentParameters,
    TankParameters,
    WEEKDAY_KEYS,
    common_hourly_schedule_templates,
    default_sewer_eligible_for_object_type,
    default_hourly_weekly_fractions,
    migrate_legacy_demand_inputs,
)
from rainwater_app.rainfall import load_rainfall_csv
from rainwater_app.storage import SQLiteStore
from rainwater_app.system_model import compile_builder_system, validate_builder_system
from rainwater_app.stations import bounding_box, nearest_stations
from rainwater_app.units import (
    LITERS_PER_GALLON,
    area_to_display,
    area_to_internal,
    area_unit,
    precip_to_display,
    precip_to_internal,
    precip_unit,
    volume_to_display,
    volume_to_internal,
    volume_unit,
)
from rainwater_app.optimization import (
    BOOSTER_TANK_CATALOG,
    FILTRATION_PUMP_CATALOG,
    PRIMARY_TANK_CATALOG,
    optimize_indirect_system,
)

APP_TITLE = "Rainwater Harvesting Calculator"
SYSTEM_ANIMATION_FRAME_MS = 40
SYSTEM_ANIMATION_CYCLES_PER_SECOND = 0.6
DEMAND_FLOW_UNITS = ("gpm", "gal/hr", "lpm", "liter/hr")
DEFAULT_WINDOW_WIDTH = 1200
DEFAULT_WINDOW_HEIGHT = 680
MINIMUM_WINDOW_WIDTH = 1000
MAX_RECENT_PROJECTS = 8
ONLINE_HELP_URL = "https://ianvg.github.io/rainwater-calculator-py/"


def _demand_flow_to_gallons_per_minute(value: float, unit: str) -> float:
    if unit == "gpm":
        return value
    if unit == "gal/hr":
        return value / 60.0
    if unit == "lpm":
        return value / LITERS_PER_GALLON
    if unit == "liter/hr":
        return value / (LITERS_PER_GALLON * 60.0)
    raise ValueError(f"Unsupported demand flow unit: {unit}")


def _demand_flow_from_gallons_per_minute(value: float, unit: str) -> float:
    if unit == "gpm":
        return value
    if unit == "gal/hr":
        return value * 60.0
    if unit == "lpm":
        return value * LITERS_PER_GALLON
    if unit == "liter/hr":
        return value * LITERS_PER_GALLON * 60.0
    raise ValueError(f"Unsupported demand flow unit: {unit}")


def _normalized_demand_object_indices(value: object, demand_object_count: int) -> list[int]:
    if not isinstance(value, list):
        return []
    normalized: list[int] = []
    for raw_index in value:
        try:
            index = int(raw_index)
        except (TypeError, ValueError):
            continue
        if 0 <= index < demand_object_count and index not in normalized:
            normalized.append(index)
    return normalized


ACIS_SOURCE_URL = "https://www.rcc-acis.org/"
ECCC_SOURCE_URL = "https://climate.weather.gc.ca/"
OSM_TILE_URL = os.environ.get("RWH_OSM_TILE_URL", "https://tile.openstreetmap.org/{z}/{x}/{y}.png")
ABOUT_TEXT = """RWH Calculator

Copyright (c) 2026 RWH Calculator contributors
All rights reserved except as granted by the open-source license below.

OPEN-SOURCE LICENSE:
RWH Calculator is open-source software released under the
Zero-Clause BSD (0BSD) license.

Permission to use, copy, modify, and/or distribute this software for any
purpose with or without fee is hereby granted.

APPLICATION ICON:
The water-drop icon is adapted from the MIT-licensed Tabler Icons collection.
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


def _validated_schedule_library(payload: object) -> dict[str, dict[str, list[float]]]:
    if not isinstance(payload, dict):
        return {}
    library: dict[str, dict[str, list[float]]] = {}
    for raw_name, raw_schedule in payload.items():
        name = str(raw_name).strip()
        if not name or not isinstance(raw_schedule, dict):
            continue
        schedule: dict[str, list[float]] = {}
        valid = True
        for day in WEEKDAY_KEYS:
            raw_values = raw_schedule.get(day)
            if not isinstance(raw_values, list) or len(raw_values) != 24:
                valid = False
                break
            try:
                values = [min(max(float(value), 0.0), 1.0) for value in raw_values]
            except (TypeError, ValueError):
                valid = False
                break
            schedule[day] = values
        if valid:
            library[name] = schedule
    return library


def _common_demand_object_templates() -> dict[str, DemandObject]:
    monthly_types = (
        ("Ice making", "Ice making"), ("Cooling tower", "Cooling tower"),
        ("Ice skating", "Ice skating"), ("Other indoor", "Other indoor"),
        ("Spray irrigation", "Irrigation system"),
        ("Drip irrigation", "Irrigation system"),
        ("Vehicle washing", "Vehicle washing"), ("Other outdoor", "Other outdoor"),
    )
    templates = {
        "Simple recurring demand": DemandObject(
            "Simple recurring demand", "Other", demand_mode="recurring_daily"
        ),
        "Toilet": DemandObject("Toilet", "Toilet", 3.0),
        "Urinal": DemandObject("Urinal", "Urinal", 1.0),
    }
    templates.update({
        name: DemandObject(name, object_type, demand_mode="monthly_volume")
        for name, object_type in monthly_types
    })
    return templates


def _validated_demand_object_library(payload: object) -> dict[str, DemandObject]:
    if not isinstance(payload, dict):
        return {}
    library: dict[str, DemandObject] = {}
    for raw_name, raw_object in payload.items():
        name = str(raw_name).strip()
        if not name or not isinstance(raw_object, dict):
            continue
        try:
            flow = max(float(raw_object.get("instantaneous_demand_gallons_per_minute", 0.0)), 0.0)
        except (TypeError, ValueError):
            continue
        library[name] = DemandObject(
            name=name,
            object_type=str(raw_object.get("object_type", "Other")),
            instantaneous_demand_gallons_per_minute=flow,
            demand_mode=str(raw_object.get("demand_mode", "scheduled_flow")),
            recurring_daily_gallons=max(_float(raw_object.get("recurring_daily_gallons")), 0.0),
            operating_days_per_week=min(max(int(_float(raw_object.get("operating_days_per_week"), 7)), 0), 7),
            monthly_daily_demand_gallons={
                month: max(_float(dict(raw_object.get("monthly_daily_demand_gallons", {})).get(month)), 0.0)
                for month in MONTH_KEYS
            },
            monthly_demand_gallons={
                month: max(_float(dict(raw_object.get("monthly_demand_gallons", {})).get(month)), 0.0)
                for month in MONTH_KEYS
            },
            sewer_eligible=raw_object.get("sewer_eligible"),
        )
    return library


def _resource_path(relative_path: str) -> Path:
    bundled_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return bundled_root / relative_path


def _help_index_path() -> Path | None:
    bundled_root = Path(getattr(sys, "_MEIPASS", _app_dir()))
    candidates = [bundled_root / "help" / "index.html", _app_dir() / "site" / "index.html"]
    return next((path for path in candidates if path.is_file()), None)


def _float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_coordinates(latitude_text: str, longitude_text: str) -> tuple[float | None, float | None]:
    latitude_value = latitude_text.strip()
    longitude_value = longitude_text.strip()
    if not latitude_value and not longitude_value:
        return None, None
    if not latitude_value or not longitude_value:
        raise ValueError("Enter both latitude and longitude, or leave both fields blank.")
    try:
        latitude = float(latitude_value)
        longitude = float(longitude_value)
    except ValueError as exc:
        raise ValueError("Latitude and longitude must be numbers.") from exc
    if not -90 <= latitude <= 90:
        raise ValueError("Latitude must be between -90 and 90 degrees.")
    if not -180 <= longitude <= 180:
        raise ValueError("Longitude must be between -180 and 180 degrees.")
    return latitude, longitude


def _state_code(value: str) -> str:
    return value.split(" - ", 1)[0].strip().upper()


def _safe_project_file_name(name: str) -> str:
    safe = "".join(char if char.isalnum() or char in " ._-" else "_" for char in name).strip()
    return f"{safe or 'rainwater_project'}.db"


def _latex_escape(value: object) -> str:
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return "".join(replacements.get(char, char) for char in str(value))


def _latex_row(*values: object) -> str:
    return " & ".join(_latex_escape(value) for value in values) + r" \\"


def _latex_number(value: object) -> str:
    return f"{float(value):.6g}"


def _pdf_escape(value: object) -> str:
    text = str(value).replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    return text.encode("latin-1", errors="replace").decode("latin-1")


def _clip_pdf_text(value: object, max_chars: int) -> str:
    text = str(value)
    if len(text) <= max_chars:
        return text
    return text[: max(0, max_chars - 3)] + "..."


def _wrap_pdf_text(value: str, width: int) -> list[str]:
    words = value.split()
    if not words:
        return [""]
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        if len(current) + 1 + len(word) <= width:
            current = f"{current} {word}"
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def _report_surface_rows(config: ProjectConfig) -> list[dict[str, object]]:
    return [
        {
            "name": surface.name,
            "area": area_to_display(surface.area, config),
            "runoff_coefficient": surface.runoff_coefficient,
            "first_flush_depth": precip_to_display(surface.first_flush_depth_inches, config),
        }
        for surface in config.surfaces
        if surface.area > 0
    ]


def _report_demand_summary(results_df: pd.DataFrame, config: ProjectConfig) -> tuple[list[dict[str, object]], float]:
    if results_df.empty or not {"Date", "DemandGallons"}.issubset(results_df.columns):
        return (
            [
                {"month": MONTH_LABELS[key], "demand_per_day": 0.0, "demand_per_month": 0.0}
                for key in MONTH_KEYS
            ],
            0.0,
        )

    demand = results_df[["Date", "DemandGallons"]].copy()
    demand["Date"] = pd.to_datetime(demand["Date"], errors="coerce")
    demand["DemandGallons"] = pd.to_numeric(demand["DemandGallons"], errors="coerce").fillna(0.0)
    demand = demand.dropna(subset=["Date"])
    monthly_average = demand.groupby(demand["Date"].dt.month)["DemandGallons"].mean()
    monthly_totals = demand.groupby([demand["Date"].dt.year, demand["Date"].dt.month])["DemandGallons"].sum()
    mean_monthly_totals = monthly_totals.groupby(level=1).mean()
    annual_average = demand.groupby(demand["Date"].dt.year)["DemandGallons"].sum().mean()
    rows = [
        {
            "month": MONTH_LABELS[key],
            "demand_per_day": volume_to_display(float(monthly_average.get(index, 0.0)), config),
            "demand_per_month": volume_to_display(float(mean_monthly_totals.get(index, 0.0)), config),
        }
        for index, key in enumerate(MONTH_KEYS, start=1)
    ]
    return rows, volume_to_display(float(annual_average), config)


def _yearly_demand_reliability(results_df: pd.DataFrame) -> list[dict[str, float | int]]:
    if results_df.empty or not {"Date", "DemandMet"}.issubset(results_df.columns):
        return []
    values = results_df[["Date", "DemandMet"]].copy()
    values["Date"] = pd.to_datetime(values["Date"], errors="coerce")
    values = values.dropna(subset=["Date"])
    values["DemandMet"] = values["DemandMet"].fillna(False).astype(bool)
    rows: list[dict[str, float | int]] = []
    for year, group in values.groupby(values["Date"].dt.year, sort=True):
        total_days = len(group)
        met_days = int(group["DemandMet"].sum())
        met_percent = (met_days / total_days) * 100.0 if total_days else 0.0
        rows.append(
            {
                "year": int(year),
                "total_days": total_days,
                "met_days": met_days,
                "unmet_days": total_days - met_days,
                "met_percent": met_percent,
                "unmet_percent": 100.0 - met_percent,
            }
        )
    return rows


def _report_average_annual_precipitation(rainfall_df: pd.DataFrame, config: ProjectConfig) -> float:
    if rainfall_df.empty or not {"Date", "Precipitation"}.issubset(rainfall_df.columns):
        return 0.0
    rainfall = rainfall_df[["Date", "Precipitation"]].copy()
    rainfall["Date"] = pd.to_datetime(rainfall["Date"], errors="coerce")
    rainfall["Precipitation"] = pd.to_numeric(rainfall["Precipitation"], errors="coerce").fillna(0.0)
    rainfall = rainfall.dropna(subset=["Date"])
    annual_average = rainfall.groupby(rainfall["Date"].dt.year)["Precipitation"].sum().mean()
    return precip_to_display(float(annual_average), config)


def _report_tank_level_distribution(
    results_df: pd.DataFrame, config: ProjectConfig, bin_count: int = 6
) -> list[dict[str, float | int]]:
    if results_df.empty or "WaterInTankGallons" not in results_df.columns or bin_count <= 0:
        return []
    levels = [
        volume_to_display(max(float(value), 0.0), config)
        for value in pd.to_numeric(results_df["WaterInTankGallons"], errors="coerce").fillna(0.0)
    ]
    selected_capacity = volume_to_display(config.selected_tank_size_gal, config)
    upper = max(selected_capacity, max(levels, default=0.0), 1.0)
    bin_width = upper / bin_count
    counts = [0] * bin_count
    for level in levels:
        index = min(max(int(level / bin_width), 0), bin_count - 1)
        counts[index] += 1
    return [
        {
            "low": index * bin_width,
            "high": (index + 1) * bin_width,
            "count": count,
        }
        for index, count in enumerate(counts)
    ]


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
    """TkinterMapView variant that owns and cancels its recurring Tk callbacks."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        self._map_after_ids: set[str] = set()
        super().__init__(*args, **kwargs)

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
        self.running = False
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
        self.active_project_name: str | None = None
        self.geometry(f"{DEFAULT_WINDOW_WIDTH}x{DEFAULT_WINDOW_HEIGHT}")
        self.minsize(MINIMUM_WINDOW_WIDTH, DEFAULT_WINDOW_HEIGHT)
        self.progress_style = ttk.Style(self)
        self.progress_style.configure("Analysis.Horizontal.TProgressbar")
        self.progress_style.configure("OpenProject.Horizontal.TProgressbar", background="#2e8b57")
        self.progress_style.configure("SaveProject.Horizontal.TProgressbar", background="#2e8b57")
        self.progress_style.configure("Invalid.TLabel", foreground="#c62828", font=("TkDefaultFont", 11, "bold"))

        self.project_file_path = _app_dir() / "rainwater_projects.db"
        self.store = SQLiteStore(str(self.project_file_path))
        self.recent_projects_path = _app_dir() / "recent_projects.json"
        self.recent_project_paths = self._load_recent_project_paths()
        self.custom_schedule_library_path = _app_dir() / "schedule_library.json"
        self.custom_schedule_templates = self._load_custom_schedule_templates()
        self.custom_demand_object_library_path = _app_dir() / "demand_object_library.json"
        self.custom_demand_object_templates = self._load_custom_demand_object_templates()
        self.config_model = default_project_config()
        self.rainfall_df = pd.DataFrame(columns=["Date", "Precipitation"])
        self.curve_df = pd.DataFrame()
        self.results_df = pd.DataFrame()
        self.hourly_results_df = pd.DataFrame()
        self.comparison_results: dict[float, pd.DataFrame] = {}
        self.candidate_sort_column = "TankSizeGallons"
        self.candidate_sort_reverse = False
        self.candidate_tree_sizes: dict[str, float] = {}
        self.station_options: list[dict] = []
        self.station_map_markers: list[object] = []
        self.station_map_marker_by_label: dict[str, object] = {}
        self.station_map_rendered_zoom: int | None = None
        self.station_map_redraw_after_id: str | None = None
        self.station_map_selected_label = ""
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
        self.filter_recovery_var = tk.StringVar(value="100")
        self.booster_tank_size_var = tk.StringVar(value="0")
        self.booster_initial_fill_var = tk.StringVar(value="0")
        self.booster_refill_level_var = tk.StringVar(value="50")
        self.municipal_backup_enabled_var = tk.BooleanVar(value=True)
        self.pump_capacity_unit_var = tk.StringVar(value="gal/min")
        self.country_var = tk.StringVar(value=COUNTRY_LABEL_BY_CODE["USA"])
        self.saved_project_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Ready")
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
        self.comparison_tank_var = tk.StringVar()
        self.multitank_comparison_var = tk.BooleanVar(value=self.config_model.multitank_comparison_enabled)
        self.selected_tank_warning_var = tk.StringVar()
        self.initial_fill_var = tk.StringVar(value=str(self.config_model.tank_parameters.initial_fill_percent))
        self.reserve_var = tk.StringVar(
            value=str(self.config_model.tank_parameters.minimum_operating_volume_percent)
        )
        self.first_flush_antecedent_days_var = tk.StringVar(
            value=str(self.config_model.first_flush_antecedent_dry_days)
        )
        self.hourly_schedule_enabled_var = tk.BooleanVar(value=self.config_model.demand.hourly_schedule_enabled)
        self.hourly_schedule_summary_var = tk.StringVar(value="Even 24-hour demand profile")
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
        self.financial_status_var = tk.StringVar(value="Run a tank analysis to calculate financial results.")
        self.financial_result_vars = {key: tk.StringVar(value="--") for key in (
            "supplied", "sewer_eligible_supply", "water_savings", "sewer_savings", "gross",
            "maintenance", "net", "net_cost", "payback", "period_benefit"
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
        self.optimization_status_var = tk.StringVar(
            value="Uses 27 combinations from an illustrative built-in product catalog."
        )
        self.rainfall_summary_var = tk.StringVar(value="No rainfall file loaded")
        self.reliability_var = tk.StringVar(value="Reliability: --")
        self.average_annual_precipitation_var = tk.StringVar(value="Average annual precipitation: --")
        self.analysis_progress_var = tk.DoubleVar(value=0.0)
        self.analysis_running = False
        self.analysis_cancel_requested = False
        self.show_tank_points_var = tk.BooleanVar(value=True)
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
        self.rainfall_source_label: str | None = None
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
        self.optimization_result_queue: queue.Queue = queue.Queue()
        self.optimization_poll_after_id: str | None = None

        self._build_ui()
        self.selected_tank_var.trace_add("write", self._update_selected_tank_warning)
        self._update_selected_tank_warning()
        self._load_project_list()
        self._populate_from_model()
        self._center_main_window()
        self.deiconify()

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
        self.notebook.add(self.schedules_tab, text="Schedules")
        self.notebook.add(self.collection_tab, text="Collection surfaces")
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
        self.analysis_progress = ttk.Progressbar(
            status_frame,
            variable=self.analysis_progress_var,
            maximum=100,
            length=180,
            style="Analysis.Horizontal.TProgressbar",
        )
        self.analysis_progress.grid(row=0, column=1, sticky="e", padx=(12, 0))
        self.cancel_analysis_button = ttk.Button(
            status_frame, text="Cancel analysis", command=self.cancel_analysis, state="disabled"
        )
        self.cancel_analysis_button.grid(row=0, column=2, sticky="e", padx=(8, 0))

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
        file_menu.add_command(label="Save project", accelerator="Ctrl+S", command=self.save_project)
        file_menu.add_command(label="Save project as...", accelerator="Ctrl+Shift+S", command=self.save_project_as)
        file_menu.add_separator()
        file_menu.add_command(label="Close project", accelerator="Ctrl+W", command=self.close_project)
        file_menu.add_command(label="Exit", accelerator="Ctrl+Q", command=self.destroy)
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
        menubar.add_cascade(label="View", menu=view_menu)

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
        self.destroy()
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

    def _save_recent_project_paths(self) -> None:
        try:
            self.recent_projects_path.write_text(json.dumps(self.recent_project_paths, indent=2), encoding="utf-8")
        except OSError:
            pass

    def _load_custom_schedule_templates(self) -> dict[str, dict[str, list[float]]]:
        try:
            payload = json.loads(self.custom_schedule_library_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return _validated_schedule_library(payload)

    def _save_custom_schedule_templates(self) -> None:
        self.custom_schedule_library_path.write_text(
            json.dumps(self.custom_schedule_templates, indent=2),
            encoding="utf-8",
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
                "sewer_eligible": demand_object.sewer_eligible,
            }
            for name, demand_object in self.custom_demand_object_templates.items()
        }
        self.custom_demand_object_library_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

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
        self.update_idletasks()

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
        unit_combo = ttk.Combobox(project_frame, textvariable=self.unit_var, values=["Imperial", "Metric"], width=12, state="readonly")
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
        self.system_builder_scroll_canvas.itemconfigure(
            self.system_builder_scroll_window, width=event.width
        )

    def _update_system_builder_scroll_region(self, _event: tk.Event | None = None) -> None:
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
        self.system_builder_scroll_canvas.configure(yscrollcommand=system_builder_scrollbar.set)
        system_builder_content = ttk.Frame(self.system_builder_scroll_canvas)
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
        ttk.Label(
            zoom_bar, text="Shift+wheel: zoom  |  Middle-drag: pan", foreground="#667278"
        ).grid(row=0, column=3, sticky="w", padx=(12, 0))
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
        system_edit.columnconfigure(1, weight=1)
        self.system_component_name_var = tk.StringVar()
        ttk.Label(system_edit, text="Name").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=2)
        self.system_component_name_entry = ttk.Entry(system_edit, textvariable=self.system_component_name_var)
        self.system_component_name_entry.grid(row=0, column=1, sticky="ew", pady=2)
        self.system_component_name_entry.bind("<Return>", self._apply_system_component_name_from_event)
        self.apply_system_component_name_button = ttk.Button(
            system_edit, text="Apply", command=self.apply_system_component_name
        )
        self.apply_system_component_name_button.grid(row=1, column=0, columnspan=2, sticky="e", pady=(8, 0))
        self.system_component_edit_status_var = tk.StringVar(value="Select a system object to edit.")
        ttk.Label(
            system_edit,
            textvariable=self.system_component_edit_status_var,
            foreground="#667278",
            wraplength=220,
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(8, 0))
        self.system_component_parameters_editor = ttk.LabelFrame(
            system_edit, text="Object parameters", padding=6
        )
        self.system_component_parameters_editor.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        self.system_component_parameters_editor.columnconfigure(1, weight=1)
        self.system_parameter_frames: dict[str, ttk.Frame] = {}
        parameter_specs = {
            "primary_tank": [
                ("Primary tank size", self.selected_tank_var, self.tank_size_unit_var),
                ("Initial fill", self.initial_fill_var, self.percent_unit_var),
                ("Minimum operating level", self.reserve_var, self.reserve_unit_var),
                ("Graph start tank size", self.graph_start_var, self.tank_size_unit_var),
                ("Graph end tank size", self.graph_end_var, self.tank_size_unit_var),
                ("Graph step", self.graph_step_var, self.tank_size_unit_var),
            ],
            "filtration_pump": [
                ("Pump capacity (0 = unlimited)", self.filtration_pump_capacity_var, self.pump_capacity_unit_var),
            ],
            "filtration_system": [
                ("Filter recovery", self.filter_recovery_var, self.percent_unit_var),
            ],
            "booster_tank": [
                ("Tank size (0 = pass-through)", self.booster_tank_size_var, self.tank_size_unit_var),
                ("Initial fill", self.booster_initial_fill_var, self.percent_unit_var),
                ("Refill level", self.booster_refill_level_var, self.percent_unit_var),
            ],
            "booster_pump": [
                ("Pump capacity (0 = unlimited)", self.pump_capacity_var, self.pump_capacity_unit_var),
            ],
        }
        for component_type, specs in parameter_specs.items():
            frame = ttk.Frame(self.system_component_parameters_editor)
            frame.grid(row=0, column=0, sticky="ew")
            frame.columnconfigure(1, weight=1)
            for row, (label, variable, unit_variable) in enumerate(specs):
                self._labeled_entry(frame, row, label, variable, unit_variable)
            if component_type == "primary_tank":
                ttk.Button(frame, text="Auto graph step", command=self.auto_set_graph_step).grid(
                    row=len(specs), column=0, columnspan=3, sticky="w", pady=(6, 0)
                )
                ttk.Label(frame, text="Number of steps").grid(
                    row=len(specs) + 1, column=0, sticky="w", pady=2
                )
                ttk.Spinbox(
                    frame, from_=1, to=1000, increment=1,
                    textvariable=self.graph_auto_step_count_var, width=6,
                ).grid(row=len(specs) + 1, column=1, sticky="w", pady=2)
                ttk.Label(frame, textvariable=self.selected_tank_warning_var, style="Invalid.TLabel").grid(
                    row=len(specs) + 2, column=0, columnspan=3, sticky="w", pady=(4, 0)
                )
            self.system_parameter_frames[component_type] = frame
            frame.grid_remove()
        self.system_municipal_backup_editor = ttk.Frame(self.system_component_parameters_editor)
        self.system_municipal_backup_editor.grid(row=0, column=0, sticky="ew")
        ttk.Checkbutton(
            self.system_municipal_backup_editor,
            text="Municipal backup enabled",
            variable=self.municipal_backup_enabled_var,
            command=self._system_builder_backup_setting_changed,
        ).grid(row=0, column=0, sticky="w")
        self.system_municipal_backup_editor.grid_remove()
        self.system_end_uses_editor = ttk.LabelFrame(
            system_edit, text="Demand objects", padding=6
        )
        self.system_end_uses_editor.grid(row=4, column=0, columnspan=2, sticky="nsew", pady=(10, 0))
        self.system_end_uses_editor.columnconfigure(0, weight=1)
        ttk.Label(self.system_end_uses_editor, text="Available").grid(row=0, column=0, sticky="w")
        self.system_available_demands_list = tk.Listbox(
            self.system_end_uses_editor, height=4, exportselection=False
        )
        self.system_available_demands_list.grid(row=1, column=0, sticky="ew", pady=(2, 4))
        self.system_add_demand_button = ttk.Button(
            self.system_end_uses_editor,
            text="Add selected",
            command=self.add_demand_to_selected_end_uses,
        )
        self.system_add_demand_button.grid(row=2, column=0, sticky="ew")
        ttk.Label(self.system_end_uses_editor, text="Assigned").grid(row=3, column=0, sticky="w", pady=(8, 0))
        self.system_assigned_demands_list = tk.Listbox(
            self.system_end_uses_editor, height=4, exportselection=False
        )
        self.system_assigned_demands_list.grid(row=4, column=0, sticky="ew", pady=(2, 4))
        self.system_remove_demand_button = ttk.Button(
            self.system_end_uses_editor,
            text="Remove selected",
            command=self.remove_demand_from_selected_end_uses,
        )
        self.system_remove_demand_button.grid(row=5, column=0, sticky="ew")
        self.system_available_demands_list.bind(
            "<Double-1>", lambda _event: self.add_demand_to_selected_end_uses()
        )
        self.system_assigned_demands_list.bind(
            "<Double-1>", lambda _event: self.remove_demand_from_selected_end_uses()
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
            "filtration_pump": "Filtration pump",
            "filtration_system": "Filtration system",
            "booster_tank": "Buffer tank",
            "booster_pump": "Booster pump",
            "municipal_backup": "Municipal water backup",
            "end_uses": "End-uses",
            "first_flush_diversion": "First-flush diversion",
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
        selected_rainfall = self.rainfall_df.loc[dates == selected_date, ["Date", "Precipitation"]].head(1)
        if selected_rainfall.empty:
            messagebox.showerror(APP_TITLE, "The selected rainfall day is unavailable.", parent=self)
            return
        try:
            self.system_animation_results = simulate_hourly_tank(
                self.config_model, selected_rainfall,
                float(self.config_model.selected_tank_size_gal),
            )
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
            return float(row.get("CollectedGallons", 0.0)) > 1e-9
        if source_type == "municipal_backup":
            return float(row.get("MainsMakeupGallons", 0.0)) > 1e-9
        if target_type == "first_flush_diversion":
            return False
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
            f"rain {displayed_rain:.1f} {volume_unit(self.config_model)}  |  "
            f"demand {displayed_demand:.1f} {volume_unit(self.config_model)}"
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
            if self._system_animation_connection_active(
                str(source.get("component_type", "")), str(target.get("component_type", "")), row
            ):
                for offset in (0.0, 0.33, 0.66):
                    fraction = (self.system_animation_phase + offset) % 1.0
                    px, py = sx + (tx - sx) * fraction, sy + (ty - sy) * fraction
                    canvas.create_oval(px - 5, py - 5, px + 5, py + 5, fill="#1687d9", outline="")
        primary_begin = (
            self.config_model.selected_tank_size_gal * self.config_model.tank_parameters.initial_fill_percent / 100.0
            if hour == 0 else float(self.system_animation_results.iloc[hour - 1].get("WaterInTankGallons", 0.0))
        )
        booster_begin = (
            self.config_model.system_parameters.booster_tank_size_gallons
            * self.config_model.system_parameters.booster_initial_fill_percent / 100.0
            if hour == 0 else float(self.system_animation_results.iloc[hour - 1].get("BoosterTankGallons", 0.0))
        )
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
                volume = primary_begin if component_type == "primary_tank" else booster_begin
                fraction = min(max(volume / capacity, 0.0), 1.0) if capacity > 0 else 0.0
                inner_h = max(block_h - 6.0, 0.0) * fraction
                canvas.create_rectangle(x - block_w / 2 + 3, y + block_h / 2 - 3 - inner_h,
                                        x + block_w / 2 - 3, y + block_h / 2 - 3,
                                        fill="#70b7e6", outline="")
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
            cfg.system_layout = [copy.deepcopy(item) for item in layout if isinstance(item, dict)]
            cfg.system_connections = [
                {str(key): str(value) for key, value in item.items()}
                for item in connections if isinstance(item, dict)
            ]
            if isinstance(payload.get("system_parameters"), dict):
                cfg.system_parameters = SystemComponentParameters(**payload["system_parameters"])
            if isinstance(payload.get("tank_parameters"), dict):
                cfg.tank_parameters = TankParameters(**payload["tank_parameters"])
            if "selected_tank_size_gal" in payload:
                cfg.selected_tank_size_gal = float(payload["selected_tank_size_gal"])
            for field_name in ("graph_start_gal", "graph_end_gal", "graph_step_gal"):
                if field_name in payload:
                    setattr(cfg, field_name, int(float(payload[field_name])))
        except (TypeError, ValueError) as exc:
            messagebox.showerror(APP_TITLE, str(exc), parent=self)
            return
        self.system_builder_selected_id = None
        self.system_builder_selected_ids.clear()
        self.system_builder_selected_connection = None
        self.system_builder_pending_source = None
        self.system_builder_pending_target = None
        self.system_builder_pending_target_port = "in"
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
                ("rainwater_input", "Rainwater input", 90, 135),
                ("primary_tank", "Primary tank", 270, 135),
                ("booster_pump", "Distribution pump", 460, 135),
                ("end_uses", "End-uses", 650, 135),
                ("municipal_backup", "Municipal water backup", 460, 260),
            ]
            links = [(0, 1), (1, 2), (2, 3), (4, 3)]
        elif system_type == "Indirect system":
            components = [
                ("rainwater_input", "Rainwater input", 85, 100),
                ("primary_tank", "Primary tank", 235, 100),
                ("filtration_pump", "Filtration pump", 385, 100),
                ("filtration_system", "Filtration system", 535, 100),
                ("booster_tank", "Buffer tank", 685, 100),
                ("municipal_backup", "Municipal water backup", 535, 235),
                ("booster_pump", "Booster pump", 385, 320),
                ("end_uses", "End-uses", 650, 320),
            ]
            links = [(0, 1), (1, 2), (2, 3), (3, 4), (5, 4), (4, 6), (6, 7)]
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
            layout.append(item)
        self.config_model.system_layout = layout
        self.config_model.system_connections = [
            {
                "source_component": str(layout[source]["id"]),
                "target_component": str(layout[target]["id"]),
            }
            for source, target in links
        ]
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
        has_outlet = component_type not in {"end_uses", "first_flush_diversion"}
        return has_inlet, has_outlet

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
        if source_port == "out2":
            connection["source_port"] = "out2"
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
            if direction.startswith("out") and self.system_builder_pending_target is not None:
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
            elif direction.startswith("out"):
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
            start_x = x + half_width + 3.0 if direction.startswith("out") else x - half_width - 3.0
            start_y = y + (14.0 if direction == "in2" else (-14.0 if direction == "in" and item.get("extra_input_node") else 0.0))
            if direction.startswith("out") and item.get("extra_output_node"):
                start_y = y + (14.0 if direction == "out2" else -14.0)
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
                if origin_direction.startswith("out"):
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
        base_fill = "#1565c0" if direction.startswith("in") else "#c62828"
        for canvas_item in self.system_builder_canvas.find_withtag(
            f"port:{component_id}:{direction}"
        ):
            self.system_builder_canvas.itemconfigure(canvas_item, fill=base_fill)
        self.system_builder_hover_port = None

    def _update_system_port_drag_hover(
        self, x: float, y: float, origin_id: str, origin_direction: str
    ) -> None:
        self._clear_system_port_drag_hover()
        expected_direction = "in" if origin_direction.startswith("out") else "out"
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
                    or (expected_direction == "out" and not direction.startswith("out"))
                    or component_id == origin_id):
                continue
            hover_fill = "#90caf9" if direction.startswith("in") else "#ef9a9a"
            self.system_builder_canvas.itemconfigure(canvas_item, fill=hover_fill)
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
        return [
            item for item in connections
            if item.get("source_component") != component_id
            and item.get("target_component") != component_id
        ]

    def _start_system_connection_from_node(self, component_id: str, direction: str) -> None:
        self.system_builder_selected_id = component_id
        self.system_builder_selected_connection = None
        self.system_builder_port_drag = None
        if direction.startswith("out"):
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
            "out": "output node", "out2": "second output node", None: "object",
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
        node_key = "source_component" if direction.startswith("out") else "target_component"
        node_connections = sum(
            connection.get(node_key) == component_id
            and (
                (direction.startswith("out") and connection.get("source_port", "out") == direction)
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
        self.system_builder_selected_id = None
        self._render_system_builder()

    def _refresh_system_component_editor(self) -> None:
        if not hasattr(self, "system_component_name_entry"):
            return
        item = (
            self._system_layout_item(self.system_builder_selected_id)
            if self.system_builder_selected_id is not None
            else None
        )
        for frame in self.system_parameter_frames.values():
            frame.grid_remove()
        self.system_municipal_backup_editor.grid_remove()
        if item is None:
            self.system_component_name_var.set("")
            self.system_component_name_entry.state(["disabled"])
            self.apply_system_component_name_button.state(["disabled"])
            self.system_component_edit_status_var.set("Select a system object to edit.")
            self.system_component_parameters_editor.grid_remove()
            self.system_end_uses_editor.grid_remove()
            return
        self.system_component_name_var.set(str(item.get("name", "")))
        self.system_component_name_entry.state(["!disabled"])
        self.apply_system_component_name_button.state(["!disabled"])
        component_type_key = str(item.get("component_type", ""))
        component_type = self._system_component_templates().get(
            component_type_key, str(item.get("component_type", "System object"))
        )
        self.system_component_edit_status_var.set(f"Editing: {component_type}")
        parameter_frame = self.system_parameter_frames.get(component_type_key)
        if parameter_frame is not None:
            self.system_component_parameters_editor.grid()
            parameter_frame.grid()
        elif component_type_key == "municipal_backup":
            self.system_component_parameters_editor.grid()
            self.system_municipal_backup_editor.grid()
        else:
            self.system_component_parameters_editor.grid_remove()
        if component_type_key == "end_uses":
            self.system_end_uses_editor.grid()
            self._refresh_end_uses_demand_editor(item)
        else:
            self.system_end_uses_editor.grid_remove()

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
        name = self.system_component_name_var.get().strip()
        if not name:
            messagebox.showwarning(APP_TITLE, "System object name cannot be blank.", parent=self)
            self.system_component_name_entry.focus_set()
            return
        item["name"] = name
        self._render_system_builder()
        self.system_component_name_entry.focus_set()
        self.system_component_name_entry.selection_range(0, tk.END)

    def _apply_system_component_name_from_event(self, _event: tk.Event) -> str:
        self.apply_system_component_name()
        return "break"

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

    def _render_system_builder(self) -> None:
        if not hasattr(self, "system_builder_canvas"):
            return
        canvas = self.system_builder_canvas
        canvas.delete("all")
        self.system_builder_hover_port = None
        layout_by_id = {str(item.get("id")): item for item in self.config_model.system_layout}
        for index, connection in enumerate(self.config_model.system_connections):
            source = layout_by_id.get(connection.get("source_component", ""))
            target = layout_by_id.get(connection.get("target_component", ""))
            if source is None or target is None:
                continue
            source_x, source_y = float(source.get("x", 0.0)), float(source.get("y", 0.0))
            target_x, target_y = float(target.get("x", 0.0)), float(target.get("y", 0.0))
            if source.get("component_type") == "primary_tank" and source.get("extra_output_node"):
                source_y += 14.0 if connection.get("source_port") == "out2" else -14.0
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
            canvas.create_rectangle(
                x - half_width, y - half_height, x + half_width, y + half_height,
                fill=fill, outline=outline, width=3 if selected or geometry_selected else 2, tags=(tag,)
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
                outlet_y = y - 14.0 if extra_outlet else y
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
                    second_y = y + 14.0
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
        if self.system_builder_zoom != 1.0:
            canvas.scale("all", 0.0, 0.0, self.system_builder_zoom, self.system_builder_zoom)
        if self.system_builder_pan_x or self.system_builder_pan_y:
            canvas.move(
                "all",
                self.system_builder_pan_x * self.system_builder_zoom,
                self.system_builder_pan_y * self.system_builder_zoom,
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
            primary_size = float(self.selected_tank_var.get().replace(",", ""))
        except (ValueError, AttributeError):
            primary_size = volume_to_display(self.config_model.selected_tank_size_gal, self.config_model)
        canvas.create_text(
            150,
            80,
            text=f"Primary analysis size: {primary_size:,.0f} {volume_unit(self.config_model)}",
            font=("Segoe UI", 9),
        )
        canvas.create_line(*self._regular_wave_points(42, 258, 110, 8, 7), fill="black", width=4, smooth=True)
        canvas.create_line(260, 150, 330, 150, fill="black", width=4)
        canvas.create_oval(330, 115, 400, 185, outline="black", width=4)
        canvas.create_polygon(400, 150, 347.5, 180.31, 347.5, 119.69, outline="black", fill="", width=4)
        canvas.create_text(365, 210, text="Filtration pump", font=("Segoe UI", 11, "bold"))
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
        self.rainwater_data_notebook.add(self.daily_rainwater_tab, text="Daily data")
        self.rainwater_data_notebook.add(self.hourly_rainwater_tab, text="Hourly data")
        self.daily_rainwater_tab.columnconfigure(0, weight=1)
        self.daily_rainwater_tab.rowconfigure(0, weight=1)
        self.hourly_rainwater_tab.columnconfigure(0, weight=1)
        ttk.Label(
            self.hourly_rainwater_tab,
            text="Hourly rainwater data is a work in progress.",
            foreground="#667278",
        ).grid(row=0, column=0, sticky="nw")
        frame_background = ttk.Style(self).lookup("TFrame", "background") or "#f0f0f0"
        self.import_canvas = tk.Canvas(
            self.daily_rainwater_tab,
            highlightthickness=0,
            borderwidth=0,
            background=frame_background,
        )
        self.import_canvas.grid(row=0, column=0, sticky="nsew")
        import_scroll_y = ttk.Scrollbar(
            self.daily_rainwater_tab, orient="vertical", command=self.import_canvas.yview
        )
        import_scroll_y.grid(row=0, column=1, sticky="ns")
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
        ttk.Button(csv_frame, text="Load Rainfall CSV", command=self.load_rainfall_csv).grid(row=0, column=1, sticky="e", padx=(12, 0))

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
        self._labeled_entry(self.weather_frame, 3, "Station filter", self.weather_filter_var)
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
        self.station_map = _StationMapView(station_map_frame, width=800, height=440, corner_radius=0)
        self.station_map.set_tile_server(OSM_TILE_URL, max_zoom=19)
        self.station_map.set_position(39.5, -98.35)
        self.station_map.set_zoom(3)
        self.station_map.grid(row=0, column=0, sticky="nsew")
        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>", "<ButtonRelease-1>"):
            self.station_map.canvas.bind(sequence, self._station_map_view_changed, add="+")
        ttk.Label(
            station_map_frame,
            text="Map data © OpenStreetMap contributors",
            foreground="#5f6b70",
        ).grid(row=1, column=0, sticky="e", pady=(4, 0))

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
            columns=("surface", "area", "runoff", "first_flush"),
            show="headings",
            height=18,
        )
        self.surface_tree.heading("surface", text="Surface")
        self.surface_tree.heading("area", text="Area")
        self.surface_tree.heading("runoff", text="Runoff coeff.")
        self.surface_tree.heading("first_flush", text=f"First flush ({precip_unit(self.config_model)})")
        self.surface_tree.column("surface", width=420)
        self.surface_tree.column("area", width=160, anchor="e")
        self.surface_tree.column("runoff", width=140, anchor="e")
        self.surface_tree.column("first_flush", width=140, anchor="e")
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
        event_frame = ttk.LabelFrame(
            self.collection_tab, text="First-flush event definition", padding=10
        )
        event_frame.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        ttk.Label(event_frame, text="Antecedent dry period").grid(row=0, column=0, sticky="w")
        ttk.Entry(
            event_frame, textvariable=self.first_flush_antecedent_days_var, width=10
        ).grid(row=0, column=1, sticky="w", padx=(8, 4))
        ttk.Label(event_frame, text="days").grid(row=0, column=2, sticky="w")
        ttk.Label(
            event_frame,
            text="A wet day starts a new event after this many dry calendar days.",
            foreground="#667278",
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(4, 0))

    def _build_schedules_tab(self) -> None:
        self.schedules_tab.columnconfigure(1, weight=1)
        self.schedules_tab.columnconfigure(2, weight=1)
        self.schedules_tab.rowconfigure(1, weight=1)
        schedule_toolbar = ttk.Frame(self.schedules_tab)
        schedule_toolbar.grid(row=0, column=0, sticky="w", pady=(0, 6))
        self.schedule_add_icon = self._create_schedule_action_icon("#2e8b57", "+")
        self.schedule_duplicate_icon = self._create_schedule_action_icon("#1565c0", "x2")
        self.schedule_delete_icon = self._create_schedule_action_icon("#c62828", "x")
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
        self.common_schedule_templates = {**built_in_templates, **self.custom_schedule_templates}

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
        self.edit_schedule_button = ttk.Button(
            hourly_frame, text="Edit typical week...", command=self.edit_hourly_demand_schedule
        )
        self.edit_schedule_button.grid(row=1, column=0, columnspan=3, sticky="w", pady=(10, 0))
        self.save_schedule_to_library_button = ttk.Button(
            hourly_frame,
            text="Save selected to library",
            command=self.save_selected_schedule_to_library,
        )
        self.save_schedule_to_library_button.grid(row=2, column=0, columnspan=3, sticky="w", pady=(8, 0))
        ttk.Label(hourly_frame, textvariable=self.hourly_schedule_summary_var, foreground="#667278").grid(
            row=3, column=0, columnspan=3, sticky="w", pady=(6, 0)
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

    def _build_analysis_tab(self) -> None:
        self.analysis_tab.columnconfigure(0, weight=1)
        self.analysis_tab.rowconfigure(1, weight=1)

        hourly_analysis_frame = ttk.LabelFrame(self.analysis_tab, text="Hourly analysis", padding=10)
        hourly_analysis_frame.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        self.hourly_schedule_enabled_check = ttk.Checkbutton(
            hourly_analysis_frame,
            text="Enable hourly demand schedule",
            variable=self.hourly_schedule_enabled_var,
            command=self._hourly_schedule_enabled_changed,
        )
        self.hourly_schedule_enabled_check.grid(row=0, column=0, sticky="w")

        comparison_frame = ttk.LabelFrame(self.analysis_tab, text="Tank size comparison", padding=10)
        comparison_frame.grid(row=1, column=0, sticky="nsew")
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
        self.optimization_tab.rowconfigure(1, weight=1)
        assumptions = ttk.LabelFrame(self.optimization_tab, text="Optimization problem definition and assumptions", padding=10)
        assumptions.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        assumptions.columnconfigure(0, weight=1)
        ttk.Label(
            assumptions,
            text=("Design variables remain open to the optimizer. Fixed project inputs are read directly from "
                  "their source tabs so duplicate values cannot drift out of sync."),
            foreground="#667278", wraplength=1000,
        ).grid(row=0, column=0, sticky="ew", pady=(0, 6))
        self.optimization_assumptions_tree = ttk.Treeview(
            assumptions, columns=("classification", "item", "value", "source"), show="headings", height=8
        )
        for column, heading, width in (
            ("classification", "Classification", 125), ("item", "Variable / assumption", 235),
            ("value", "Value used", 360), ("source", "Source / edit location", 190),
        ):
            self.optimization_assumptions_tree.heading(column, text=heading)
            self.optimization_assumptions_tree.column(column, width=width, anchor="w")
        self.optimization_assumptions_tree.grid(row=1, column=0, sticky="ew")
        assumptions_scroll = ttk.Scrollbar(assumptions, orient="vertical", command=self.optimization_assumptions_tree.yview)
        assumptions_scroll.grid(row=1, column=1, sticky="ns")
        self.optimization_assumptions_tree.configure(yscrollcommand=assumptions_scroll.set)

        optimization_frame = ttk.LabelFrame(self.optimization_tab, text="Objectives, constraints, catalog, and results", padding=10)
        optimization_frame.grid(row=1, column=0, sticky="nsew")
        optimization_frame.columnconfigure(4, weight=1)
        ttk.Label(optimization_frame, text="Minimum rainwater reliability").grid(row=0, column=0, sticky="w")
        ttk.Entry(optimization_frame, textvariable=self.optimization_minimum_reliability_var, width=9).grid(
            row=0, column=1, sticky="w", padx=(8, 3)
        )
        ttk.Label(optimization_frame, text="%").grid(row=0, column=2, sticky="w", padx=(0, 16))
        ttk.Label(optimization_frame, text="Electricity price").grid(row=0, column=3, sticky="w")
        ttk.Entry(optimization_frame, textvariable=self.optimization_electricity_rate_var, width=9).grid(
            row=0, column=4, sticky="w", padx=(8, 3)
        )
        ttk.Label(optimization_frame, text="currency/kWh").grid(row=0, column=5, sticky="w", padx=(0, 16))
        ttk.Label(optimization_frame, text="Optimize for").grid(row=0, column=6, sticky="w")
        ttk.Combobox(
            optimization_frame, textvariable=self.optimization_objective_var,
            values=("Simple payback", "Net annual savings", "Rainwater reliability", "Analysis-period net benefit"),
            state="readonly", width=23,
        ).grid(row=0, column=7, sticky="w", padx=(8, 0))
        ttk.Label(optimization_frame, text="Maximum annual municipal makeup").grid(row=1, column=0, sticky="w")
        ttk.Entry(optimization_frame, textvariable=self.optimization_maximum_makeup_var, width=9).grid(
            row=1, column=1, sticky="w", padx=(8, 3)
        )
        ttk.Label(optimization_frame, textvariable=self.tank_size_unit_var).grid(row=1, column=2, sticky="w", padx=(0, 16))
        ttk.Label(optimization_frame, text="Maximum installed cost").grid(row=1, column=3, sticky="w")
        ttk.Entry(optimization_frame, textvariable=self.optimization_maximum_cost_var, width=9).grid(
            row=1, column=4, sticky="w", padx=(8, 3)
        )
        ttk.Label(optimization_frame, textvariable=self.financial_currency_var).grid(row=1, column=5, sticky="w", padx=(0, 16))
        ttk.Checkbutton(
            optimization_frame, text="Require positive net annual savings",
            variable=self.optimization_positive_savings_var,
        ).grid(row=1, column=6, columnspan=2, sticky="w")
        button_row = ttk.Frame(optimization_frame)
        button_row.grid(row=2, column=0, columnspan=8, sticky="ew", pady=(6, 0))
        ttk.Button(button_row, text="Edit sample catalog...", command=self.open_optimization_catalog).pack(side="left")
        ttk.Button(button_row, text="Run optimization", command=self.run_system_optimization).pack(side="right")
        ttk.Label(
            button_row, text="Leave maximum constraints blank for no limit.", foreground="#667278"
        ).pack(side="left", padx=(12, 0))
        ttk.Label(
            optimization_frame,
            text=("Evaluates the editable primary tank, filtration pump, and buffer tank catalog. "
                  "Catalog values are illustrative planning inputs, not vendor quotations."),
            foreground="#667278", wraplength=950,
        ).grid(row=3, column=0, columnspan=8, sticky="ew", pady=(6, 6))
        self.optimization_tree = ttk.Treeview(
            optimization_frame,
            columns=("rank", "tank", "pump", "booster", "reliability", "makeup", "energy", "cost", "savings", "payback"),
            show="headings", height=6,
        )
        headings = (
            ("rank", "Rank", 45), ("tank", "Primary tank", 100), ("pump", "Filter pump", 100),
            ("booster", "Buffer tank", 100), ("reliability", "Reliability", 85),
            ("makeup", "Municipal/year", 100),
            ("energy", "Energy/year", 90), ("cost", "Installed cost", 105),
            ("savings", "Net savings/year", 115), ("payback", "Simple payback", 100),
        )
        for column, label, width in headings:
            self.optimization_tree.heading(column, text=label)
            self.optimization_tree.column(column, width=width, anchor="e" if column not in {"tank", "pump", "booster"} else "w")
        self.optimization_tree.grid(row=4, column=0, columnspan=7, sticky="ew")
        optimization_scroll = ttk.Scrollbar(optimization_frame, orient="vertical", command=self.optimization_tree.yview)
        optimization_scroll.grid(row=4, column=7, sticky="ns")
        self.optimization_tree.configure(yscrollcommand=optimization_scroll.set)
        ttk.Label(optimization_frame, textvariable=self.optimization_status_var, foreground="#667278").grid(
            row=5, column=0, columnspan=8, sticky="w", pady=(6, 0)
        )

    @staticmethod
    def _default_optimization_catalog_rows() -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        rows.extend(
            {"category": "Primary tank", "name": item.name, "capacity": item.capacity_gallons,
             "cost": item.installed_cost, "power_kw": 0.0}
            for item in PRIMARY_TANK_CATALOG
        )
        rows.extend(
            {"category": "Filtration pump", "name": item.name,
             "capacity": item.capacity_gallons_per_hour, "cost": item.installed_cost,
             "power_kw": item.power_kw}
            for item in FILTRATION_PUMP_CATALOG
        )
        rows.extend(
            {"category": "Buffer tank", "name": item.name, "capacity": item.capacity_gallons,
             "cost": item.installed_cost, "power_kw": 0.0}
            for item in BOOSTER_TANK_CATALOG
        )
        return rows

    @staticmethod
    def _optimization_catalog_category(row: dict[str, object]) -> object:
        """Return the current display category while accepting saved legacy catalogs."""
        category = row.get("category")
        return "Buffer tank" if category == "Booster tank" else category

    def _refresh_optimization_assumptions(self) -> None:
        if not hasattr(self, "optimization_assumptions_tree"):
            return
        cfg = self.config_model
        optimization = cfg.optimization_parameters
        financial = cfg.financial_parameters
        system = cfg.system_parameters
        unit = volume_unit(cfg)
        catalog = optimization.catalog or self._default_optimization_catalog_rows()
        counts = {
            category: sum(self._optimization_catalog_category(row) == category for row in catalog)
            for category in ("Primary tank", "Filtration pump", "Buffer tank")
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
            else f"{volume_to_display(optimization.maximum_annual_municipal_makeup_gallons, cfg):,.0f} {unit}/year"
        )
        maximum_cost = (
            "No limit" if optimization.maximum_installed_cost is None
            else f"{financial.currency} {optimization.maximum_installed_cost:,.2f}"
        )
        rows = [
            ("Design variable", "Primary tank product", f"{counts['Primary tank']} catalog choices", "Optimization catalog"),
            ("Design variable", "Filtration pump product", f"{counts['Filtration pump']} catalog choices", "Optimization catalog"),
            ("Design variable", "Buffer tank product", f"{counts['Buffer tank']} catalog choices", "Optimization catalog"),
            ("Fixed input", "Rainfall record", rainfall_value, "Rainwater Data"),
            ("Fixed input", "Collection surfaces", f"{len(cfg.surfaces)} surfaces; {area_to_display(collection_area, cfg):,.0f} {area_unit(cfg)}", "Collection surfaces"),
            ("Fixed input", "Simple recurring demand", f"{volume_to_display(cfg.demand.simple_daily_demand_gallons, cfg):,.1f} {unit}/day; {cfg.demand.daily_demand_days_per_week} days/week", "Demand parameters"),
            ("Fixed input", "Demand objects", f"{len(cfg.demand.demand_objects)} objects", "Demand parameters / Schedules"),
            ("Model constant", "Simulation resolution", "Hourly; historical rainfall repeated only as supplied", "Hourly engine"),
            ("Model constant", "Daily rainfall timing", "Collected rainfall enters after that day's demand", "Hourly engine"),
            ("Fixed input", "Primary tank initial fill", f"{cfg.tank_parameters.initial_fill_percent:g}%", "System parameters / Edit"),
            ("Hard operating constraint", "Primary minimum operating level", f"{cfg.tank_parameters.minimum_operating_volume_percent:g}% of capacity", "System parameters / Edit"),
            ("Fixed input", "Filter recovery", f"{system.filter_recovery_percent:g}%", "System parameters / Edit"),
            ("Fixed input", "Buffer initial fill / refill level", f"{system.booster_initial_fill_percent:g}% / {system.booster_refill_level_percent:g}%", "System parameters / Edit"),
            ("Fixed input", "Municipal backup", "Enabled" if system.municipal_backup_enabled else "Disabled", "System parameters / Edit"),
            ("Objective", "Ranking objective", optimization.objective, "Optimization"),
            ("Constraint", "Minimum rainwater reliability", f"{optimization.minimum_reliability_percent:g}%", "Optimization"),
            ("Constraint", "Maximum annual municipal makeup", maximum_makeup, "Optimization"),
            ("Constraint", "Maximum installed cost", maximum_cost, "Optimization"),
            ("Constraint", "Positive net annual savings", "Required" if optimization.require_positive_net_savings else "Not required", "Optimization"),
            ("Economic input", "Water / sewer tariff", f"{financial.currency} {financial.water_rate:g} / {financial.sewer_rate:g} {financial.tariff_billing_unit}", "Financial analysis"),
            ("Economic input", "Legacy aggregate sewer eligibility", f"{financial.sewer_eligible_percent:g}%", "Financial analysis"),
            ("Economic input", "Base cost / incentives", f"{financial.currency} {financial.installed_cost:,.2f} / {financial.incentives:,.2f}", "Financial analysis"),
            ("Economic input", "Annual maintenance", f"{financial.currency} {financial.fixed_annual_maintenance:,.2f} + {financial.annual_maintenance_percent:g}% of installed cost", "Financial analysis"),
            ("Economic input", "Electricity price", f"{financial.currency} {optimization.electricity_rate_per_kwh:g}/kWh", "Optimization"),
            ("Economic input", "Analysis period", f"{financial.analysis_period_years} years; undiscounted", "Financial analysis"),
            ("Search method", "Candidate enumeration", f"Exhaustive deterministic search; {math.prod(counts.values())} combinations", "Optimization backend"),
            ("Performance method", "Candidate evaluation", "Aggregate hourly arrays; prepared inputs cached for 4 unchanged runs", "Optimization backend"),
        ]
        self.optimization_assumptions_tree.delete(*self.optimization_assumptions_tree.get_children())
        for row in rows:
            self.optimization_assumptions_tree.insert("", "end", values=row)

    def open_optimization_catalog(self) -> None:
        dialog = tk.Toplevel(self)
        dialog.title("Optimization equipment catalog")
        dialog.transient(self)
        dialog.geometry("820x480")
        dialog.columnconfigure(0, weight=1)
        dialog.rowconfigure(1, weight=1)
        ttk.Label(
            dialog,
            text=("Edit or paste comma-separated rows. Tank capacity is gallons; filtration-pump capacity "
                  "is gallons/hour. Power is used for filtration pumps. Prices use the selected currency."),
            wraplength=780, foreground="#667278", padding=10,
        ).grid(row=0, column=0, sticky="ew")
        editor = tk.Text(dialog, wrap="none", font=("Consolas", 10), undo=True)
        editor.grid(row=1, column=0, sticky="nsew", padx=10)
        scroll_y = ttk.Scrollbar(dialog, orient="vertical", command=editor.yview)
        scroll_y.grid(row=1, column=1, sticky="ns")
        editor.configure(yscrollcommand=scroll_y.set)

        def load_rows(rows: list[dict[str, object]]) -> None:
            editor.delete("1.0", tk.END)
            editor.insert("1.0", "Category,Name,Capacity,Installed cost,Power kW\n")
            for row in rows:
                editor.insert(
                    tk.END,
                    f"{self._optimization_catalog_category(row)},{row['name']},{float(row['capacity']):g},"
                    f"{float(row['cost']):g},{float(row.get('power_kw', 0.0)):g}\n",
                )

        load_rows(self.config_model.optimization_parameters.catalog or self._default_optimization_catalog_rows())

        def apply_catalog() -> None:
            lines = editor.get("1.0", "end-1c").splitlines()
            parsed: list[dict[str, object]] = []
            allowed = {"Primary tank", "Filtration pump", "Buffer tank"}
            try:
                for row_number, values in enumerate(csv.reader(lines[1:]), start=2):
                    if not values or not any(value.strip() for value in values):
                        continue
                    if len(values) != 5:
                        raise ValueError(f"Row {row_number} must contain exactly five columns.")
                    category, name = values[0].strip(), values[1].strip()
                    capacity, cost, power = map(float, (values[2], values[3], values[4]))
                    if category not in allowed:
                        raise ValueError(f"Row {row_number} has an unsupported category.")
                    if not name or capacity <= 0.0 or cost < 0.0 or power < 0.0:
                        raise ValueError(f"Row {row_number} requires a name, positive capacity, and non-negative cost and power.")
                    parsed.append({"category": category, "name": name, "capacity": capacity,
                                   "cost": cost, "power_kw": power})
                missing = allowed - {str(row["category"]) for row in parsed}
                if missing:
                    raise ValueError("Catalog requires at least one product in each category.")
            except ValueError as exc:
                messagebox.showwarning(APP_TITLE, str(exc), parent=dialog)
                return
            self.config_model.optimization_parameters.catalog = parsed
            combinations = math.prod(
                sum(row["category"] == category for row in parsed) for category in sorted(allowed)
            )
            self.optimization_status_var.set(
                f"Catalog saved with {len(parsed)} products and {combinations} combinations."
            )
            dialog.destroy()

        buttons = ttk.Frame(dialog, padding=10)
        buttons.grid(row=2, column=0, columnspan=2, sticky="ew")
        ttk.Button(buttons, text="Reset sample catalog", command=lambda: load_rows(self._default_optimization_catalog_rows())).pack(side="left")
        ttk.Button(buttons, text="Cancel", command=dialog.destroy).pack(side="right")
        ttk.Button(buttons, text="Apply catalog", command=apply_catalog).pack(side="right", padx=(0, 8))

    def run_system_optimization(self) -> None:
        if self.analysis_running:
            self.optimization_status_var.set("Wait for the current analysis to finish.")
            return
        self._apply_form_to_model()
        self._refresh_optimization_assumptions()
        self.optimization_tree.delete(*self.optimization_tree.get_children())
        catalog = self.config_model.optimization_parameters.catalog or self._default_optimization_catalog_rows()
        category_counts = [
            sum(self._optimization_catalog_category(row) == category for row in catalog)
            for category in ("Primary tank", "Filtration pump", "Buffer tank")
        ]
        combination_count = math.prod(category_counts)
        self.optimization_status_var.set(f"Evaluating {combination_count} product combinations...")
        self.analysis_progress_var.set(0.0)
        self.status_var.set("Optimization running: evaluating product combinations")
        self.config(cursor="watch")
        self.analysis_running = True
        config_snapshot = copy.deepcopy(self.config_model)
        rainfall_snapshot = self.rainfall_df.copy(deep=True)

        def worker() -> None:
            try:
                results = optimize_indirect_system(
                    config_snapshot,
                    rainfall_snapshot,
                    progress_callback=lambda current, total: self.optimization_result_queue.put(
                        ("progress", current, total)
                    ),
                )
                self.optimization_result_queue.put(("result", results, config_snapshot))
            except Exception as exc:
                self.optimization_result_queue.put(("error", str(exc)))

        threading.Thread(target=worker, daemon=True, name="optimization-worker").start()
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
                _kind, current, total = message
                self.optimization_status_var.set(f"Evaluating combination {current} of {total}...")
                self.analysis_progress_var.set(current / max(total, 1) * 100.0)
                self.status_var.set(f"Optimization running: combination {current} of {total}")
            elif kind == "result":
                _kind, results, config_snapshot = message
                self._display_optimization_results(results, config_snapshot)
                terminal_message = True
            else:
                _kind, error_message = message
                self.analysis_progress_var.set(0.0)
                self.status_var.set("Optimization failed")
                self.optimization_status_var.set(error_message)
                messagebox.showwarning(APP_TITLE, error_message, parent=self)
                terminal_message = True
        if terminal_message:
            self.analysis_running = False
            self.config(cursor="")
            self.optimization_poll_after_id = None
        elif self.analysis_running:
            self.optimization_poll_after_id = self.after(50, self._poll_optimization_results)

    def _display_optimization_results(self, results: list[object], run_config: ProjectConfig) -> None:
        currency = run_config.financial_parameters.currency
        feasible_count = sum(result.feasible for result in results)
        for index, result in enumerate(results):
            payback = (
                f"{result.simple_payback_years:.1f} years"
                if result.simple_payback_years is not None else "Not achieved"
            )
            self.optimization_tree.insert(
                "", "end", iid=str(index),
                values=(
                    result.rank if result.rank is not None else "Infeasible",
                    result.primary_tank.name,
                    result.filtration_pump.name,
                    result.booster_tank.name,
                    f"{result.reliability_percent:.1f}%",
                    f"{volume_to_display(result.average_annual_municipal_makeup_gallons, run_config):,.0f}",
                    f"{result.average_annual_energy_kwh:,.0f} kWh",
                    f"{currency} {result.total_installed_cost:,.0f}",
                    f"{currency} {result.net_annual_savings:,.0f}",
                    payback,
                ),
            )
        if feasible_count:
            best = next(result for result in results if result.feasible)
            objective = run_config.optimization_parameters.objective
            if objective == "Simple payback":
                best_value = f"{best.simple_payback_years:.1f} years" if best.simple_payback_years is not None else "not achieved"
            elif objective == "Net annual savings":
                best_value = f"{currency} {best.net_annual_savings:,.0f}/year"
            elif objective == "Rainwater reliability":
                best_value = f"{best.reliability_percent:.1f}%"
            else:
                best_value = f"{currency} {best.analysis_period_net_benefit:,.0f}"
            self.optimization_status_var.set(
                f"{feasible_count} of {len(results)} combinations meet all constraints. "
                f"Best: {best.primary_tank.name} + {best.filtration_pump.name} + "
                f"{best.booster_tank.name}; {objective.lower()} {best_value}."
            )
        else:
            self.optimization_status_var.set(
                f"None of the {len(results)} combinations meet the reliability target."
            )
        self.analysis_progress_var.set(100.0)
        self.status_var.set("Optimization complete")

    def _build_financial_tab(self) -> None:
        self.financial_tab.columnconfigure(0, weight=1)
        self.financial_tab.columnconfigure(1, weight=1)
        self.financial_tab.rowconfigure(1, weight=1)
        self.financial_tab.rowconfigure(2, weight=1)
        ttk.Label(
            self.financial_tab,
            text=(
                "This simple-rate estimate values only rainwater delivered to demand by the latest simulation. "
                "Overflow, unmet demand, municipal makeup, treatment loss, and water left in storage are excluded."
            ),
            foreground="#667278",
            wraplength=950,
        ).grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 10))

        inputs = ttk.LabelFrame(self.financial_tab, text="Financial assumptions", padding=12)
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
        ttk.Button(inputs, text="Update financial analysis", command=self.update_financial_analysis).grid(
            row=10, column=0, columnspan=3, sticky="ew", pady=(12, 0)
        )

        outputs = ttk.LabelFrame(self.financial_tab, text="Selected-tank financial results", padding=12)
        outputs.grid(row=1, column=1, sticky="nsew", padx=(6, 0))
        outputs.columnconfigure(1, weight=1)
        result_rows = (
            ("Average annual rainwater supplied", "supplied"),
            ("Annual sewer-eligible rainwater supplied", "sewer_eligible_supply"),
            ("Annual municipal water savings", "water_savings"),
            ("Annual sewer savings", "sewer_savings"),
            ("Gross annual utility savings", "gross"),
            ("Annual maintenance cost", "maintenance"),
            ("Net annual savings", "net"),
            ("Net installed cost after incentives", "net_cost"),
            ("Simple payback", "payback"),
            ("Net benefit over analysis period", "period_benefit"),
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
            self.financial_tab, text="Primary and comparison tank financial performance", padding=10
        )
        comparison.grid(row=2, column=0, columnspan=2, sticky="nsew", pady=(10, 0))
        comparison.columnconfigure(0, weight=1)
        comparison.rowconfigure(0, weight=1)
        columns = ("tank", "supplied", "gross", "net", "payback")
        self.financial_comparison_tree = ttk.Treeview(
            comparison, columns=columns, show="headings", height=6
        )
        headings = {
            "tank": "Tank size",
            "supplied": "Annual rainwater supplied",
            "gross": "Gross annual savings",
            "net": "Net annual savings",
            "payback": "Simple payback",
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
        if self.config_model.demand.hourly_schedule_enabled and not self.hourly_results_df.empty:
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
            results = calculate_financial_results(
                source,
                water_rate=params.water_rate,
                sewer_rate=params.sewer_rate,
                billing_unit=params.tariff_billing_unit,
                sewer_eligible_percent=params.sewer_eligible_percent,
                installed_cost=params.installed_cost,
                incentives=params.incentives,
                fixed_annual_maintenance=params.fixed_annual_maintenance,
                maintenance_percent=params.annual_maintenance_percent,
                analysis_period_years=params.analysis_period_years,
            )
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
        self.financial_result_vars["supplied"].set(f"{supplied_display:,.0f} {volume_label}/year")
        eligible_display = volume_to_display(
            results.average_annual_sewer_eligible_supplied_gallons, self.config_model
        )
        self.financial_result_vars["sewer_eligible_supply"].set(
            f"{eligible_display:,.0f} {volume_label}/year"
        )
        self.financial_result_vars["water_savings"].set(
            f"{currency} {results.annual_municipal_water_savings:,.2f}/year"
        )
        self.financial_result_vars["sewer_savings"].set(
            f"{currency} {results.annual_sewer_savings:,.2f}/year"
        )
        self.financial_result_vars["gross"].set(f"{currency} {results.gross_annual_savings:,.2f}/year")
        self.financial_result_vars["maintenance"].set(f"{currency} {results.annual_maintenance_cost:,.2f}/year")
        self.financial_result_vars["net"].set(f"{currency} {results.net_annual_savings:,.2f}/year")
        self.financial_result_vars["net_cost"].set(f"{currency} {results.net_installed_cost:,.2f}")
        self.financial_result_vars["payback"].set(
            f"{results.simple_payback_years:,.1f} years"
            if results.simple_payback_years is not None
            else "Not achieved"
        )
        self.financial_result_vars["period_benefit"].set(
            f"{currency} {results.analysis_period_net_benefit:,.2f}"
        )
        source_label = "hourly" if source is self.hourly_results_df else "daily"
        self.financial_status_var.set(
            f"Based on average annual delivered rainwater from the latest {source_label} simulation. "
            "This is a simple-rate, undiscounted estimate; tariff tiers, escalation, financing, energy, "
            "replacement costs, NPV, and IRR are not included."
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
                results = calculate_financial_results(
                    source,
                    water_rate=params.water_rate,
                    sewer_rate=params.sewer_rate,
                    billing_unit=params.tariff_billing_unit,
                    sewer_eligible_percent=params.sewer_eligible_percent,
                    installed_cost=params.installed_cost,
                    incentives=params.incentives,
                    fixed_annual_maintenance=params.fixed_annual_maintenance,
                    maintenance_percent=params.annual_maintenance_percent,
                    analysis_period_years=params.analysis_period_years,
                )
            except ValueError:
                continue
            tank_display = volume_to_display(tank_size, self.config_model)
            supplied_display = volume_to_display(
                results.average_annual_supplied_gallons, self.config_model
            )
            payback = (
                f"{results.simple_payback_years:,.1f} years"
                if results.simple_payback_years is not None
                else "Not achieved"
            )
            self.financial_comparison_tree.insert(
                "",
                "end",
                values=(
                    f"{tank_display:,.0f} {volume_unit(self.config_model)}",
                    f"{supplied_display:,.0f} {volume_unit(self.config_model)}/yr",
                    f"{params.currency} {results.gross_annual_savings:,.2f}",
                    f"{params.currency} {results.net_annual_savings:,.2f}",
                    payback,
                ),
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
        self.results_notebook.add(self.summary_results_tab, text="Single-tank summary")
        self.results_notebook.add(self.candidate_results_tab, text="Candidate performance")
        self.results_notebook.add(self.multitank_results_tab, text="Multitank summary")
        self.results_notebook.add(self.hourly_results_tab, text="Hourly results")
        self.results_notebook.bind("<<NotebookTabChanged>>", self._on_results_subtab_changed)

        summary = self.summary_results_tab
        summary.columnconfigure(0, weight=1)
        summary.columnconfigure(1, weight=1)
        summary.rowconfigure(1, weight=1)
        summary.rowconfigure(2, weight=1)
        summary.rowconfigure(3, weight=1)

        results_summary = ttk.Frame(summary)
        results_summary.grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(results_summary, textvariable=self.reliability_var, font=("Segoe UI", 12, "bold")).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(results_summary, textvariable=self.average_annual_precipitation_var).grid(
            row=1, column=0, sticky="w", pady=(2, 0)
        )
        self.curve_canvas = tk.Canvas(summary, height=170, bg="white", highlightthickness=1, highlightbackground="#b7b7b7")
        self.curve_canvas.grid(row=1, column=0, sticky="nsew", pady=(8, 8), padx=(0, 5))
        self.tank_canvas = tk.Canvas(summary, height=170, bg="white", highlightthickness=1, highlightbackground="#b7b7b7")
        self.tank_canvas.grid(row=1, column=1, sticky="nsew", pady=(8, 8), padx=(5, 0))
        self.tank_points_check = ttk.Checkbutton(
            self.tank_canvas,
            text="Show tank chart points",
            variable=self.show_tank_points_var,
            command=self._draw_tank_chart,
        )
        self.tank_points_check.place(x=58, rely=1, y=-4, anchor="sw")
        tank_year_controls = ttk.Frame(self.tank_canvas)
        tank_year_controls.place(relx=1, rely=1, x=-8, y=-4, anchor="se")
        ttk.Radiobutton(
            tank_year_controls, text="Single year", variable=self.tank_chart_range_mode_var,
            value="year", command=self._draw_tank_chart,
        ).grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Radiobutton(
            tank_year_controls, text="Custom range", variable=self.tank_chart_range_mode_var,
            value="range", command=self._draw_tank_chart,
        ).grid(row=0, column=2, columnspan=2, sticky="w")
        self.previous_tank_year_button = ttk.Button(
            tank_year_controls, text="<", width=3, command=lambda: self._change_tank_chart_year(-1)
        )
        self.previous_tank_year_button.grid(row=1, column=0)
        ttk.Label(tank_year_controls, text="Year").grid(row=1, column=1, padx=(4, 2))
        self.tank_chart_year_entry = ttk.Entry(
            tank_year_controls, textvariable=self.tank_chart_year_var, width=6, justify="center"
        )
        self.tank_chart_year_entry.grid(row=1, column=2, padx=(0, 4))
        self.tank_chart_year_entry.bind("<Return>", self._set_tank_chart_year_from_entry)
        self.next_tank_year_button = ttk.Button(
            tank_year_controls, text=">", width=3, command=lambda: self._change_tank_chart_year(1)
        )
        self.next_tank_year_button.grid(row=1, column=3)
        self.tank_range_controls = ttk.Frame(self.tank_canvas)
        self.tank_range_controls.place(x=58, rely=1, y=-30, anchor="sw")
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
            height=170,
            bg="white",
            highlightthickness=1,
            highlightbackground="#b7b7b7",
        )
        self.histogram_canvas.grid(row=2, column=0, sticky="nsew", pady=(0, 8), padx=(0, 5))
        self.yearly_reliability_canvas = tk.Canvas(
            summary,
            height=170,
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
        results_scroll_y = ttk.Scrollbar(summary, orient="vertical", command=self.results_tree.yview)
        results_scroll_y.grid(row=3, column=2, sticky="ns")
        results_scroll_x = ttk.Scrollbar(summary, orient="horizontal", command=self.results_tree.xview)
        results_scroll_x.grid(row=4, column=0, columnspan=2, sticky="ew")
        self.results_tree.configure(yscrollcommand=results_scroll_y.set, xscrollcommand=results_scroll_x.set)

        candidate = self.candidate_results_tab
        candidate.columnconfigure(0, weight=1)
        candidate.rowconfigure(1, weight=1)
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
        candidate_columns = (
            "TankSizeGallons", "ReliabilityPercent", "TotalDemandGallons",
            "RainwaterSuppliedGallons", "SewerEligibleRainwaterSuppliedGallons",
            "UnmetDemandGallons", "MunicipalMakeupGallons",
            "SystemUnmetDemandGallons", "OverflowGallons", "FirstFlushLossGallons",
            "TreatmentLossGallons", "FinalStorageGallons", "NetAnnualSavings",
            "SimplePaybackYears",
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
            "SimplePaybackYears": "Simple payback",
        }
        for column in candidate_columns:
            self.candidate_performance_tree.heading(
                column,
                text=candidate_headings[column],
                command=lambda selected=column: self._sort_candidate_performance(selected),
            )
            self.candidate_performance_tree.column(column, width=130, anchor="e", stretch=False)
        self.candidate_performance_tree.grid(row=1, column=0, sticky="nsew")
        candidate_scroll_y = ttk.Scrollbar(
            candidate, orient="vertical", command=self.candidate_performance_tree.yview
        )
        candidate_scroll_y.grid(row=1, column=1, sticky="ns")
        candidate_scroll_x = ttk.Scrollbar(
            candidate, orient="horizontal", command=self.candidate_performance_tree.xview
        )
        candidate_scroll_x.grid(row=2, column=0, sticky="ew")
        self.candidate_performance_tree.configure(
            yscrollcommand=candidate_scroll_y.set, xscrollcommand=candidate_scroll_x.set
        )
        self.candidate_performance_tree.bind("<Double-1>", self._use_candidate_as_primary_from_event)

        multitank = self.multitank_results_tab
        multitank.columnconfigure(0, weight=1)
        for row in range(3):
            multitank.rowconfigure(row, weight=1)
        self.multitank_tank_canvas = tk.Canvas(multitank, height=180, bg="white", highlightthickness=1, highlightbackground="#b7b7b7")
        self.multitank_distribution_canvas = tk.Canvas(multitank, height=180, bg="white", highlightthickness=1, highlightbackground="#b7b7b7")
        self.multitank_yearly_canvas = tk.Canvas(multitank, height=180, bg="white", highlightthickness=1, highlightbackground="#b7b7b7")
        self.multitank_tank_canvas.grid(row=0, column=0, sticky="nsew", pady=(0, 5))
        self.multitank_distribution_canvas.grid(row=1, column=0, sticky="nsew", pady=5)
        self.multitank_yearly_canvas.grid(row=2, column=0, sticky="nsew", pady=(5, 0))
        for canvas in (self.multitank_tank_canvas, self.multitank_distribution_canvas, self.multitank_yearly_canvas):
            canvas.bind("<Configure>", self._schedule_results_chart_redraw)

        hourly = self.hourly_results_tab
        hourly.columnconfigure(0, weight=1)
        hourly.rowconfigure(1, weight=1)
        hourly.rowconfigure(2, weight=1)
        hourly_controls = ttk.Frame(hourly)
        hourly_controls.grid(row=0, column=0, sticky="w", pady=(0, 6))
        ttk.Label(hourly_controls, text="Year").grid(row=0, column=0, padx=(0, 4))
        self.hourly_results_year_combo = ttk.Combobox(
            hourly_controls, textvariable=self.hourly_results_year_var, state="readonly", width=8
        )
        self.hourly_results_year_combo.grid(row=0, column=1)
        self.hourly_results_year_combo.bind("<<ComboboxSelected>>", lambda _event: self._refresh_hourly_results_view())
        self.hourly_tank_canvas = tk.Canvas(
            hourly, height=240, bg="white", highlightthickness=1, highlightbackground="#b7b7b7"
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
        self.selected_tank_var.set(f"{volume_to_display(tank_size, self.config_model):.0f}")

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
            reliability_text = "--" if reliability is None else f"{reliability:.1f}%"
            is_primary = abs(float(tank_size) - primary_tank_size) < 0.01
            item = f"comparison-{index}"
            self.comparison_tree.insert(
                "",
                "end",
                iid=item,
                values=(
                    f"{volume_to_display(tank_size, self.config_model):,.0f}",
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
            f"Reliability for {tank_size:,.0f} {volume_unit(self.config_model)} tank: {reliability:.2f}%"
        )
        average_precipitation = _report_average_annual_precipitation(self.rainfall_df, self.config_model)
        self.average_annual_precipitation_var.set(
            f"Average annual precipitation: {average_precipitation:,.2f} {precip_unit(self.config_model)}"
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
        self.unit_var.set(cfg.unit_system)
        self.system_type_var.set(
            cfg.system_type if cfg.system_type in {"Direct system", "Indirect system"} else "Direct system"
        )
        self.current_system_type_var.set(f"Current system type: {self.system_type_var.get()}")
        self.pump_capacity_var.set(
            f"{volume_to_display(cfg.system_parameters.pump_capacity_gallons_per_hour, cfg) / 60.0:.2f}"
        )
        self.filtration_pump_capacity_var.set(
            f"{volume_to_display(cfg.system_parameters.filtration_pump_capacity_gallons_per_hour, cfg) / 60.0:.2f}"
        )
        self.filter_recovery_var.set(f"{cfg.system_parameters.filter_recovery_percent:.2f}")
        self.booster_tank_size_var.set(
            f"{volume_to_display(cfg.system_parameters.booster_tank_size_gallons, cfg):.2f}"
        )
        self.booster_initial_fill_var.set(f"{cfg.system_parameters.booster_initial_fill_percent:.2f}")
        self.booster_refill_level_var.set(f"{cfg.system_parameters.booster_refill_level_percent:.2f}")
        self.municipal_backup_enabled_var.set(cfg.system_parameters.municipal_backup_enabled)
        financial = cfg.financial_parameters
        self.financial_currency_var.set(financial.currency)
        self.financial_water_rate_var.set(f"{financial.water_rate:g}")
        self.financial_sewer_rate_var.set(f"{financial.sewer_rate:g}")
        self.financial_tariff_unit_var.set(financial.tariff_billing_unit)
        self.financial_sewer_eligible_var.set(f"{financial.sewer_eligible_percent:g}")
        self.financial_installed_cost_var.set(f"{financial.installed_cost:g}")
        self.financial_incentives_var.set(f"{financial.incentives:g}")
        self.financial_fixed_maintenance_var.set(f"{financial.fixed_annual_maintenance:g}")
        self.financial_maintenance_percent_var.set(f"{financial.annual_maintenance_percent:g}")
        self.financial_analysis_period_var.set(str(financial.analysis_period_years))
        optimization = cfg.optimization_parameters
        self.optimization_minimum_reliability_var.set(f"{optimization.minimum_reliability_percent:g}")
        self.optimization_electricity_rate_var.set(f"{optimization.electricity_rate_per_kwh:g}")
        self.optimization_objective_var.set(optimization.objective)
        self.optimization_maximum_makeup_var.set(
            "" if optimization.maximum_annual_municipal_makeup_gallons is None
            else f"{volume_to_display(optimization.maximum_annual_municipal_makeup_gallons, cfg):g}"
        )
        self.optimization_maximum_cost_var.set(
            "" if optimization.maximum_installed_cost is None else f"{optimization.maximum_installed_cost:g}"
        )
        self.optimization_positive_savings_var.set(optimization.require_positive_net_savings)
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
        self.simple_daily_var.set(f"{volume_to_display(cfg.demand.simple_daily_demand_gallons, cfg):.2f}")
        self.daily_demand_days_var.set(str(min(max(int(cfg.demand.daily_demand_days_per_week), 0), 7)))
        self.hourly_schedule_enabled_var.set(bool(cfg.demand.hourly_schedule_enabled))
        self.hourly_schedule_summary_var.set(
            "Custom typical-week hourly profile" if cfg.demand.hourly_schedule_enabled else "Even 24-hour demand profile"
        )
        self._refresh_schedule_management()
        self.flushes_var.set(f"{cfg.demand.avg_flush_per_person:.2f}")
        self.toilet_flush_var.set(f"{volume_to_display(cfg.demand.gallons_per_flush_toilet, cfg):.2f}")
        self.urinal_flush_var.set(f"{volume_to_display(cfg.demand.gallons_per_flush_urinal, cfg):.2f}")
        self.graph_start_var.set(f"{volume_to_display(cfg.graph_start_gal, cfg):.0f}")
        self.graph_end_var.set(f"{volume_to_display(cfg.graph_end_gal, cfg):.0f}")
        self.graph_step_var.set(f"{volume_to_display(cfg.graph_step_gal, cfg):.0f}")
        self.graph_auto_step_count_var.set(str(cfg.graph_auto_step_count))
        self.selected_tank_var.set(f"{volume_to_display(cfg.selected_tank_size_gal, cfg):.0f}")
        self.multitank_comparison_var.set(cfg.multitank_comparison_enabled)
        self.initial_fill_var.set(f"{cfg.tank_parameters.initial_fill_percent:.0f}")
        self.reserve_var.set(f"{cfg.tank_parameters.minimum_operating_volume_percent:.0f}")
        self.first_flush_antecedent_days_var.set(
            f"{cfg.first_flush_antecedent_dry_days:g}"
        )
        self._update_setting_unit_labels()
        self._populate_surfaces()
        self._populate_demand()
        self._populate_comparison_tanks()
        self._update_multitank_comparison_state()
        self._update_rainfall_summary()
        self._refresh_system_animation_dates()
        self._refresh_optimization_assumptions()

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
        cfg.unit_system = self.unit_var.get() or "Imperial"
        if old_unit != cfg.unit_system:
            self._populate_from_model()
            return True

        cfg.demand.simple_daily_demand_gallons = volume_to_internal(_float(self.simple_daily_var.get()), cfg)
        cfg.demand.daily_demand_days_per_week = min(
            max(int(_float(self.daily_demand_days_var.get(), 7)), 0),
            7,
        )
        cfg.demand.hourly_schedule_enabled = bool(self.hourly_schedule_enabled_var.get())
        cfg.system_parameters.pump_capacity_gallons_per_hour = max(
            0.0, volume_to_internal(_float(self.pump_capacity_var.get(), 0.0) * 60.0, cfg)
        )
        cfg.system_parameters.filtration_pump_capacity_gallons_per_hour = max(
            0.0, volume_to_internal(_float(self.filtration_pump_capacity_var.get(), 20.0) * 60.0, cfg)
        )
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
        cfg.demand.avg_flush_per_person = _float(self.flushes_var.get())
        cfg.demand.gallons_per_flush_toilet = volume_to_internal(_float(self.toilet_flush_var.get()), cfg)
        cfg.demand.gallons_per_flush_urinal = volume_to_internal(_float(self.urinal_flush_var.get()), cfg)
        cfg.graph_start_gal = max(1, int(round(volume_to_internal(_float(self.graph_start_var.get(), 500), cfg))))
        cfg.graph_end_gal = max(2, int(round(volume_to_internal(_float(self.graph_end_var.get(), 20000), cfg))))
        cfg.graph_step_gal = max(1, int(round(volume_to_internal(_float(self.graph_step_var.get(), 500), cfg))))
        cfg.graph_auto_step_count = max(1, int(_float(self.graph_auto_step_count_var.get(), 20)))
        cfg.selected_tank_size_gal = max(0.0, volume_to_internal(_float(self.selected_tank_var.get(), 5000), cfg))
        cfg.multitank_comparison_enabled = bool(self.multitank_comparison_var.get())
        cfg.tank_parameters.initial_fill_percent = min(max(_float(self.initial_fill_var.get(), 50), 0), 100)
        cfg.tank_parameters.minimum_operating_volume_percent = min(
            max(_float(self.reserve_var.get(), 0), 0), 100
        )
        cfg.first_flush_antecedent_dry_days = max(
            _float(self.first_flush_antecedent_days_var.get(), 1.0), 0.0
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

    def _populate_surfaces(self) -> None:
        self.surface_tree.heading("area", text=f"Area ({area_unit(self.config_model)})")
        self.surface_tree.heading(
            "first_flush", text=f"First flush ({precip_unit(self.config_model)})"
        )
        self.surface_tree.delete(*self.surface_tree.get_children())
        for i, surface in enumerate(self.config_model.surfaces):
            self.surface_tree.insert(
                "",
                "end",
                iid=str(i),
                values=(
                    surface.name,
                    f"{area_to_display(surface.area, self.config_model):.2f}",
                    f"{surface.runoff_coefficient:.2f}",
                    f"{precip_to_display(surface.first_flush_depth_inches, self.config_model):.3f}",
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
                row.append(f"{value:.2f}")
            self.demand_tree.insert("", "end", iid=month, values=row)

    def _populate_demand_objects(self, select_index: int | None = None) -> None:
        if not hasattr(self, "demand_objects_tree"):
            return
        for tree in (self.demand_objects_tree,):
            tree.heading(
                "instantaneous_demand", text="Demand quantity"
            )
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
        if demand_object.demand_mode == "recurring_daily":
            values = demand_object.monthly_daily_demand_gallons.values()
            value = max(values, default=demand_object.recurring_daily_gallons)
            return f"up to {volume_to_display(value, self.config_model):.2f} {unit}/day"
        if demand_object.demand_mode == "monthly_volume":
            value = max(demand_object.monthly_demand_gallons.values(), default=0.0)
            return f"up to {volume_to_display(value, self.config_model):.2f} {unit}/month"
        value = volume_to_display(
            demand_object.instantaneous_demand_gallons_per_minute, self.config_model
        )
        return f"{value:.2f} {unit}/min"

    def _update_demand_headings(self) -> None:
        unit = volume_unit(self.config_model)
        demand_style = ttk.Style(self)
        demand_style.configure("MonthlyDemand.Treeview.Heading", padding=(4, 16))
        heading_font_name = demand_style.lookup("MonthlyDemand.Treeview.Heading", "font") or "TkHeadingFont"
        heading_font = tkfont.nametofont(str(heading_font_name))
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
            lines: list[str] = []
            current_line = ""
            for word in words:
                candidate = word if not current_line else f"{current_line} {word}"
                if current_line and heading_font.measure(candidate) + 18 > target_width:
                    lines.append(current_line)
                    current_line = word
                else:
                    current_line = candidate
            if current_line:
                lines.append(current_line)
            self.demand_tree.column(field, minwidth=minimum_width, width=target_width)
            self.demand_tree.heading(field, text="\n".join(lines))

    def _update_rainfall_summary(self) -> None:
        if self.rainfall_df.empty:
            self.rainfall_summary_var.set("No rainfall file loaded")
            self._refresh_system_animation_dates()
            return
        start = pd.Timestamp(self.rainfall_df["Date"].min()).strftime("%Y-%m-%d")
        end = pd.Timestamp(self.rainfall_df["Date"].max()).strftime("%Y-%m-%d")
        source = f" from {self.rainfall_source_label}" if self.rainfall_source_label else ""
        self.rainfall_summary_var.set(f"{len(self.rainfall_df):,} rainfall rows loaded ({start} to {end}){source}")
        self._refresh_system_animation_dates()

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
                self.pump_capacity_var,
                self.filtration_pump_capacity_var,
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
        self.import_station_button.configure(state="normal" if enabled else "disabled")

    def _set_active_project(self, project_name: str | None) -> None:
        self.active_project_name = project_name.strip() if project_name and project_name.strip() else None
        title = APP_TITLE if self.active_project_name is None else f"{APP_TITLE} - {self.active_project_name}"
        self.title(title)

    def auto_set_graph_step(self) -> None:
        self.config_model.unit_system = self.unit_var.get() or "Imperial"
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
        self.graph_step_var.set(f"{step_display:.0f}")
        self.status_var.set(
            f"Auto-set graph step to {step_display:.0f} {volume_unit(cfg)} for {step_count} steps"
        )

    def new_project(self) -> None:
        if self.analysis_running:
            messagebox.showinfo(APP_TITLE, "Wait for the active analysis or optimization to finish before replacing the project.")
            return
        self._set_active_project(None)
        self._reset_weather_selection()
        self.config_model = default_project_config()
        self.rainfall_df = pd.DataFrame(columns=["Date", "Precipitation"])
        self.rainfall_source_label = None
        self.config_model.rainfall_source_label = None
        self.results_df = pd.DataFrame()
        self.curve_df = pd.DataFrame()
        self.reliability_var.set("Reliability: --")
        self._clear_results()
        self._populate_from_model()
        self.status_var.set("Started a new project")

    def close_project(self) -> None:
        if self.analysis_running:
            messagebox.showinfo(APP_TITLE, "Wait for the active analysis or optimization to finish before closing the project.")
            return
        self._set_active_project(None)
        self._reset_weather_selection()
        self.config_model = default_project_config()
        self.project_name_var.set("")
        self.saved_project_var.set("")
        self.rainfall_df = pd.DataFrame(columns=["Date", "Precipitation"])
        self.rainfall_source_label = None
        self.config_model.rainfall_source_label = None
        self.results_df = pd.DataFrame()
        self.curve_df = pd.DataFrame()
        self.rainfall_summary_var.set("No rainfall file loaded")
        self.reliability_var.set("Reliability: --")
        self.analysis_progress_var.set(0)
        self._clear_results()
        self._populate_from_model()
        self.project_name_var.set("")
        self.saved_project_var.set("")
        self.status_var.set("Closed project")

    def load_selected_project(self) -> None:
        if self.analysis_running:
            messagebox.showinfo(APP_TITLE, "Wait for the active analysis or optimization to finish before loading another project.")
            return
        name = self.saved_project_var.get()
        if not name:
            messagebox.showinfo(APP_TITLE, "Select a saved project first.")
            return
        try:
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
        except Exception as exc:  # noqa: BLE001
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
        previous_path = self.project_file_path
        previous_store = self.store
        try:
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
            selected_store = SQLiteStore(str(selected_path))
            projects = selected_store.list_projects()
            if not projects:
                self.analysis_progress_var.set(0)
                messagebox.showinfo(APP_TITLE, "No saved projects were found in that file.")
                return

            self._set_progress(50, "Opening project: loading project data", "OpenProject.Horizontal.TProgressbar")
            self.project_file_path = selected_path
            self.store = selected_store
            self._refresh_system_template_library()
            self.saved_project_var.set(projects[0])
            self._load_project_list()
            self.load_selected_project()
            self._set_progress(85, "Opening project: refreshing views", "OpenProject.Horizontal.TProgressbar")
            self._add_recent_project_path(self.project_file_path)
            self._set_progress(100, f"Opened project '{self.config_model.name}' from {self.project_file_path}", "OpenProject.Horizontal.TProgressbar")
        except Exception as exc:  # noqa: BLE001
            self.project_file_path = previous_path
            self.store = previous_store
            self._load_project_list()
            self._refresh_system_template_library()
            self.analysis_progress_var.set(0)
            messagebox.showerror(APP_TITLE, f"Could not open project file:\n{exc}")

    def save_project(self) -> None:
        self._apply_form_to_model()
        self._save_current_project()

    def save_project_as(self) -> None:
        self._apply_form_to_model()
        path = filedialog.asksaveasfilename(
            title="Save project as...",
            initialdir=str(self.project_file_path.parent),
            initialfile=_safe_project_file_name(self.config_model.name),
            defaultextension=".db",
            filetypes=[("Rainwater project files", "*.db"), ("SQLite database files", "*.sqlite *.sqlite3"), ("All files", "*.*")],
        )
        if not path:
            return
        name = simpledialog.askstring(
            APP_TITLE,
            "Project name",
            initialvalue=self.config_model.name,
            parent=self,
        )
        if name is None:
            return
        name = name.strip()
        if not name:
            messagebox.showwarning(APP_TITLE, "Project name cannot be blank.")
            return
        self.project_file_path = Path(path)
        self.store = SQLiteStore(str(self.project_file_path))
        self._refresh_system_template_library()
        self.config_model.name = name
        self.project_name_var.set(name)
        self._save_current_project()

    def _save_current_project(self) -> None:
        self.config_model.rainfall_source_label = self.rainfall_source_label
        try:
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
        except Exception as exc:  # noqa: BLE001
            self.analysis_progress_var.set(0)
            self.status_var.set("Project save failed")
            messagebox.showerror(APP_TITLE, f"Could not save project:\n{exc}")

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

    def load_rainfall_csv(self) -> None:
        self._apply_form_to_model()
        path = filedialog.askopenfilename(
            title="Load rainfall CSV",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            raw = Path(path).read_bytes()
            rainfall = load_rainfall_csv(raw)
            rainfall["Precipitation"] = rainfall["Precipitation"].map(lambda v: precip_to_internal(float(v), self.config_model))
            self.rainfall_df = rainfall
            self.rainfall_source_label = None
            self.config_model.rainfall_source_label = None
            self.config_model.weather_station_latitude = None
            self.config_model.weather_station_longitude = None
            self.curve_df = pd.DataFrame()
            self.results_df = pd.DataFrame()
            self.reliability_var.set("Reliability: --")
            self._clear_results()
            self._reset_weather_selection()
            self._update_rainfall_summary()
            self.status_var.set(f"Loaded rainfall CSV: {Path(path).name}")
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(APP_TITLE, f"Could not load rainfall CSV:\n{exc}")

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
        for widget in (
            self.country_combo,
            self.state_combo,
            self.find_stations_button,
            self.find_nearest_stations_button,
            self.station_combo,
            self.import_station_button,
        ):
            widget.configure(state="disabled")
        self.analysis_progress.stop()
        self.analysis_progress.configure(mode="indeterminate", style="Analysis.Horizontal.TProgressbar")
        self.analysis_progress.start(12)
        self.status_var.set(f"Finding {provider} stations...")
        worker = threading.Thread(
            target=self._station_lookup_worker,
            args=(provider, region, start_date, end_date, query),
            name=f"rwh-{provider.casefold()}-station-lookup",
            daemon=True,
        )
        worker.start()
        self.station_lookup_poll_after_id = self.after(100, self._poll_station_lookup_results)

    def _start_nearest_station_lookup(
        self, provider: str, latitude: float, longitude: float, years: int
    ) -> None:
        start_date, end_date = default_complete_calendar_range(years)
        self.station_lookup_in_progress = True
        for widget in (
            self.country_combo,
            self.state_combo,
            self.find_stations_button,
            self.find_nearest_stations_button,
            self.station_combo,
            self.import_station_button,
        ):
            widget.configure(state="disabled")
        self.analysis_progress.stop()
        self.analysis_progress.configure(mode="indeterminate", style="Analysis.Horizontal.TProgressbar")
        self.analysis_progress.start(12)
        self.status_var.set(f"Finding nearest {provider} stations...")
        threading.Thread(
            target=self._nearest_station_lookup_worker,
            args=(provider, latitude, longitude, start_date, end_date),
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
    ) -> None:
        try:
            stations: list[dict] = []
            for radius_km in (50.0, 150.0, 400.0, 1000.0):
                west, south, east, north = bounding_box(latitude, longitude, radius_km)
                if provider == "ACIS":
                    stations = fetch_station_options_bbox(west, south, east, north, start_date, end_date)
                else:
                    stations = fetch_canadian_station_options_bbox(west, south, east, north, start_date, end_date)
                stations = nearest_stations(stations, latitude, longitude, limit=10)
                if len(stations) >= 10:
                    break
            self.station_lookup_queue.put(("success", provider, stations))
        except Exception as exc:  # noqa: BLE001
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
            if provider == "ACIS":
                stations = fetch_station_options(region, start_date, end_date)
            else:
                stations = fetch_canadian_station_options(region, start_date, end_date)
            if query:
                stations = [
                    station
                    for station in stations
                    if query in station["name"].casefold() or query in station["sid"].casefold()
                ]
            self.station_lookup_queue.put(("success", provider, stations))
        except Exception as exc:  # noqa: BLE001
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
        self.station_combo.configure(state="readonly")
        self.import_station_button.configure(state="normal")
        if result == "error":
            self.status_var.set(f"Could not fetch {provider} stations")
            messagebox.showerror(APP_TITLE, f"Could not fetch {provider} stations:\n{payload}")
            return

        self.station_options = payload
        labels = [self._station_label(station) for station in self.station_options]
        self.station_combo["values"] = labels
        self.station_var.set(labels[0] if labels else "")
        self._reset_station_typeahead()
        self._render_station_map(fit_bounds=True)
        descriptor = "ECCC climate station(s)" if provider == "ECCC" else "ACIS station(s)"
        nearest = bool(self.station_options and "distance_km" in self.station_options[0])
        qualifier = "nearest " if nearest else ""
        self.status_var.set(f"Found {len(self.station_options)} {qualifier}{descriptor}")

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
            start_date, end_date = default_complete_calendar_range(years)
            weather_df = fetch_daily_station_data(station["sid"], start_date, end_date, precipitation_field)
            self.rainfall_df = weather_df[["Date", "Precipitation"]].copy()
            station_region = self._station_region_suffix(station)
            self.rainfall_source_label = (
                f"{station['name']} ({station['sid']}){station_region} via ACIS, {basis_label}"
            )
            self.config_model.rainfall_source_label = self.rainfall_source_label
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
            if precipitation_field == "TOTAL_RAIN":
                excluded_days = int(weather_df.attrs.get("rain_only_excluded_days", 0))
                messagebox.showwarning(
                    APP_TITLE,
                    "ACIS does not provide a native rain-only field. "
                    f"Precipitation was excluded on {excluded_days:,} day(s) with reported snowfall. "
                    "Mixed rain and snow days may therefore undercount rain.",
                )
        except Exception as exc:  # noqa: BLE001
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
            self.status_var.set(f"Importing ECCC data for {station['name']}...")
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
            station_region = self._station_region_suffix(station)
            self.rainfall_source_label = (
                f"{station['name']} ({station['sid']}){station_region} via ECCC, {basis_label}"
            )
            self.config_model.rainfall_source_label = self.rainfall_source_label
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
            if missing_days:
                messagebox.showwarning(
                    APP_TITLE,
                    f"The ECCC record contained {missing_days:,} missing day(s). "
                    "They were treated as zero precipitation so daily demand remains continuous.",
                )
        except Exception as exc:  # noqa: BLE001
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
        dialog = SurfaceDialog(self, Surface("Custom surface", 0.0, Surface(name="Default").runoff_coefficient), self.config_model)
        self.wait_window(dialog)
        if dialog.result:
            self.config_model.surfaces.append(dialog.result)
            self._populate_surfaces()
            new_index = str(len(self.config_model.surfaces) - 1)
            self.surface_tree.selection_set(new_index)
            self.surface_tree.focus(new_index)

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
        dialog = HourlyDemandScheduleDialog(self, self.config_model)
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
        for demand_object in self.config_model.demand.demand_objects:
            if demand_object.schedule_name == selected_name:
                demand_object.schedule_name = new_name
        self._populate_demand_objects()
        self.config_model.demand.active_hourly_schedule_name = new_name
        self.hourly_schedule_summary_var.set(f"Renamed schedule to: {new_name}")
        self._refresh_schedule_management(select_name=new_name)

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

    def _save_library_changes(self, previous: dict[str, dict[str, list[float]]]) -> bool:
        try:
            self._save_custom_schedule_templates()
        except OSError as exc:
            self.custom_schedule_templates = previous
            self.common_schedule_templates = {
                **common_hourly_schedule_templates(),
                **self.custom_schedule_templates,
            }
            messagebox.showerror(APP_TITLE, f"Could not save the custom schedule library:\n{exc}", parent=self)
            return False
        self.common_schedule_templates = {
            **common_hourly_schedule_templates(),
            **self.custom_schedule_templates,
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
        dialog = HourlyDemandScheduleDialog(self, temporary_config)
        self.wait_window(dialog)
        if not dialog.saved:
            return
        previous = copy.deepcopy(self.custom_schedule_templates)
        self.custom_schedule_templates[name] = copy.deepcopy(temporary_config.demand.hourly_weekly_fractions)
        if self._save_library_changes(previous):
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
        self.custom_schedule_templates[name] = copy.deepcopy(source)
        if self._save_library_changes(previous):
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
        del self.custom_schedule_templates[name]
        if self._save_library_changes(previous):
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
        if existing_name is not None and existing_name != selected_name:
            del self.custom_schedule_templates[existing_name]
        schedule = copy.deepcopy(self.config_model.demand.hourly_schedule_library[selected_name])
        self.custom_schedule_templates[selected_name] = schedule
        if not self._save_library_changes(previous):
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
            "Delete the typical-week hourly demand schedule? Hourly analysis will be disabled.",
            parent=self,
        ):
            return
        del self.config_model.demand.hourly_schedule_library[selected_name]
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
            self.config_model.demand.active_hourly_schedule_name = name
        self.config_model.demand.hourly_schedule_enabled = bool(self.hourly_schedule_enabled_var.get())
        self._refresh_schedule_management()

    def _refresh_schedule_management(self, select_name: str | None = None) -> None:
        if not hasattr(self, "schedule_list"):
            return
        self.schedule_list.delete(0, tk.END)
        library = self.config_model.demand.hourly_schedule_library
        if self.hourly_schedule_enabled_var.get() and not library:
            active_name = self.config_model.demand.active_hourly_schedule_name
            library[active_name] = copy.deepcopy(self.config_model.demand.hourly_weekly_fractions)
        names = list(library)
        for name in names:
            self.schedule_list.insert(tk.END, name)
        target = select_name or self.config_model.demand.active_hourly_schedule_name
        if target in names:
            index = names.index(target)
            self.schedule_list.selection_set(index)
            self.schedule_list.see(index)
            self.schedule_name_var.set(target)
        else:
            self.schedule_name_var.set("")
        self._update_schedule_management_state()

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
            self.config_model.demand.active_hourly_schedule_name = selected_name
            self.config_model.demand.hourly_weekly_fractions = copy.deepcopy(
                self.config_model.demand.hourly_schedule_library[selected_name]
            )
            self.hourly_schedule_summary_var.set(f"Selected schedule: {selected_name}")
        self._update_schedule_management_state()

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
        self.analysis_running = True
        self.analysis_cancel_requested = False
        self.cancel_analysis_button.state(["!disabled"])
        try:
            tank_sizes = sorted(
                {
                    *(float(size) for size in range(cfg.graph_start_gal, cfg.graph_end_gal + 1, cfg.graph_step_gal)),
                    float(cfg.selected_tank_size_gal),
                    *(float(size) for size in cfg.comparison_tank_sizes_gal if include_comparisons),
                }
            )
            total_parts = 2
            self.analysis_progress.configure(style="Analysis.Horizontal.TProgressbar")
            self.analysis_progress_var.set(0)
            self.status_var.set(f"{analysis_label} running: Part A - reliability curve")
            self.update_idletasks()

            def update_curve_progress(index: int, total: int, _tank_size: float) -> None:
                part_progress = index / total if total else 1.0
                self.analysis_progress_var.set((part_progress / total_parts) * 100)
                self.status_var.set(f"{analysis_label} running: Part A - reliability curve ({index}/{total})")
                self.update()

            def cancellation_requested() -> bool:
                self.update()
                return self.analysis_cancel_requested

            curve_df = reliability_curve(
                cfg,
                self.rainfall_df,
                tank_sizes,
                progress_callback=update_curve_progress,
                cancel_callback=cancellation_requested,
            )
            self.analysis_progress_var.set(50)
            self.status_var.set(f"{analysis_label} running: Part B - selected tank simulation")
            self.update_idletasks()
            results_df = simulate_tank(
                cfg,
                self.rainfall_df,
                cfg.selected_tank_size_gal,
                cancel_callback=cancellation_requested,
            )
            hourly_results_df = (
                simulate_hourly_tank(
                    cfg,
                    self.rainfall_df,
                    cfg.selected_tank_size_gal,
                    cancel_callback=cancellation_requested,
                )
                if cfg.demand.hourly_schedule_enabled
                else pd.DataFrame()
            )
            comparison_results: dict[float, pd.DataFrame] = {}
            comparison_sizes = (
                sorted(set(float(size) for size in cfg.comparison_tank_sizes_gal))
                if include_comparisons
                else []
            )
            for index, tank_size in enumerate(comparison_sizes, start=1):
                self.status_var.set(
                    f"{analysis_label} running: Part B - comparison tank simulation "
                    f"({index}/{len(comparison_sizes)})"
                )
                self.update()
                if self.analysis_cancel_requested:
                    raise AnalysisCancelledError("Analysis cancelled by user.")
                if abs(tank_size - cfg.selected_tank_size_gal) < 0.01:
                    comparison_results[tank_size] = results_df.copy()
                else:
                    comparison_results[tank_size] = simulate_tank(
                        cfg,
                        self.rainfall_df,
                        tank_size,
                        cancel_callback=cancellation_requested,
                    )
            if self.analysis_cancel_requested:
                raise AnalysisCancelledError("Analysis cancelled by user.")
            self.curve_df = curve_df
            self.results_df = results_df
            self.hourly_results_df = hourly_results_df
            self.comparison_results = comparison_results
            self._populate_comparison_tanks()
            self.analysis_progress_var.set(75)
            self.status_var.set(f"{analysis_label} running: Part B - drawing results")
            self.update_idletasks()
            reliability = float(self.results_df["ReliabilityPercent"].iloc[0]) if not self.results_df.empty else 0.0
            self._set_selected_tank_reliability(reliability)
            self._populate_results()
            self.update_financial_analysis(show_errors=False)
            self._draw_saved_analysis_charts()
            cfg.analysis_input_signature = analysis_input_signature(cfg, self.rainfall_df)
            cfg.analysis_unit_system = cfg.unit_system
            self.last_analysis_warning_key = None
            self.analysis_progress_var.set(100)
            self.status_var.set(f"{analysis_label} complete")
        except AnalysisCancelledError:
            self.analysis_progress_var.set(0)
            self.status_var.set(f"{analysis_label} cancelled; previous completed results retained")
        except Exception as exc:  # noqa: BLE001
            self.analysis_progress_var.set(0)
            self.status_var.set(f"{analysis_label} failed")
            messagebox.showerror(APP_TITLE, f"{analysis_label} failed:\n{exc}")
        finally:
            self.analysis_running = False
            self.analysis_cancel_requested = False
            self.cancel_analysis_button.state(["disabled"])

    def cancel_analysis(self) -> None:
        if not self.analysis_running:
            return
        self.analysis_cancel_requested = True
        self.status_var.set("Cancelling analysis...")
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
            self._display_results_df().to_csv(path, index=False, quoting=csv.QUOTE_MINIMAL)
            self.status_var.set(f"Exported results to {Path(path).name}")
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(APP_TITLE, f"Could not export results:\n{exc}")

    def view_pdf_report(self) -> None:
        report = self._request_report_content("PDF")
        if report is None:
            return
        preview_dir = self._new_report_preview_directory()
        pdf_path = preview_dir / self._default_report_filename(".pdf")
        try:
            self._write_pdf_report(pdf_path, report)
            self._open_local_file(pdf_path)
            self.status_var.set(f"Opened PDF report preview: {pdf_path.name}")
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(APP_TITLE, f"Could not view PDF report:\n{exc}")

    def view_html_report(self) -> None:
        report = self._request_report_content("HTML")
        if report is None:
            return
        preview_dir = self._new_report_preview_directory()
        html_path = preview_dir / self._default_report_filename(".html")
        try:
            self._write_html_report(html_path, report)
            self._open_html_preview(html_path)
            self.status_var.set(f"Opened HTML report preview: {html_path.name}")
        except Exception as exc:  # noqa: BLE001
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
            self._write_pdf_report(pdf_path, report)
            self.status_var.set(f"Exported PDF report: {pdf_path.name}")
        except Exception as exc:  # noqa: BLE001
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
            self._write_html_report(html_path, report)
            self.status_var.set(f"Exported HTML report: {html_path.name}")
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(APP_TITLE, f"Could not export HTML report:\n{exc}")

    def _request_report_content(self, report_format: str) -> dict[str, object] | None:
        self._apply_form_to_model()
        if self.curve_df.empty:
            article = "an" if report_format == "HTML" else "a"
            messagebox.showinfo(APP_TITLE, f"Run the analysis before generating {article} {report_format} report.")
            return None

        dialog = ReportDialog(self, self._default_report_metadata())
        self.wait_window(dialog)
        if dialog.result is None:
            return None
        return self._build_report_content(dialog.result)

    def _default_report_filename(self, suffix: str) -> str:
        return _safe_project_file_name(self.config_model.name).replace(".db", f"_report{suffix}")

    def _write_pdf_report(self, pdf_path: Path, report: dict[str, object]) -> None:
        tex_path = pdf_path.with_suffix(".tex")
        latex = self._build_report_latex(report)
        tex_path.write_text(latex, encoding="utf-8")
        self._compile_latex_report(tex_path, pdf_path, report)

    def _write_html_report(self, html_path: Path, report: dict[str, object]) -> None:
        html_path.write_text(self._build_report_html(report), encoding="utf-8")

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
        for after_id_name in (
            "station_typeahead_after_id",
            "state_typeahead_after_id",
            "country_typeahead_after_id",
            "station_map_redraw_after_id",
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
            "multitank_available": bool(
                self.config_model.multitank_comparison_enabled and self.comparison_results
            ),
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
        if station is None:
            try:
                station = (
                    fetch_canadian_station_by_id(station_id)
                    if cfg.country_code == "CAN" or "ECCC" in source.upper()
                    else fetch_station_by_id(station_id)
                )
            except (OSError, TypeError, ValueError):
                station = None
        coordinates = self._station_coordinates(station) if station is not None else None
        if coordinates is None:
            return None, None
        cfg.weather_station_latitude, cfg.weather_station_longitude = coordinates
        return coordinates

    def _build_report_content(self, metadata: dict[str, object]) -> dict[str, object]:
        cfg = self.config_model
        station_latitude, station_longitude = self._report_weather_station_coordinates()
        monthly_demand, total_annual_demand = _report_demand_summary(self.results_df, cfg)
        precipitation_field = (
            cfg.canadian_precipitation_field if cfg.country_code == "CAN" else cfg.acis_precipitation_field
        )
        selected_reliability: float | None = None
        if not self.results_df.empty and "ReliabilityPercent" in self.results_df:
            selected_reliability = float(self.results_df["ReliabilityPercent"].iloc[0])
        return {
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
            "first_flush_antecedent_dry_days": cfg.first_flush_antecedent_dry_days,
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
            "include_multitank_charts": bool(metadata.get("include_multitank_charts", False)),
            "include_system_visualization": bool(metadata.get("include_system_visualization", False)),
            "system_type": cfg.system_type,
            "project_latitude": cfg.latitude,
            "project_longitude": cfg.longitude,
            "weather_station_latitude": station_latitude,
            "weather_station_longitude": station_longitude,
            "multitank_charts": self._multitank_report_chart_data(),
        }

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
            label = f"{volume_to_display(tank_size, self.config_model):,.0f} {unit}"
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

    def _build_report_latex(self, report: dict[str, object]) -> str:
        metadata = report["metadata"]
        area = report["area_unit"]
        volume = report["volume_unit"]
        report_title = "RWH Calculator Report - multi-tank" if report.get("include_multitank_charts") else "RWH Calculator Report"
        surface_rows = "\n".join(
            _latex_row(
                surface["name"],
                f"{surface['area']:,.2f}",
                f"{surface['runoff_coefficient']:.2f}",
                f"{surface.get('first_flush_depth', 0.0):.3f}",
            )
            for surface in report["surfaces"]
        )
        if not surface_rows:
            surface_rows = _latex_row("No collection surfaces", "0.00", "0.000", "0.000")
        demand_rows = "\n".join(
            _latex_row(
                report["monthly_demand"][index]["month"],
                f"{report['monthly_demand'][index]['demand_per_day']:,.0f}",
                f"{report['monthly_demand'][index]['demand_per_month']:,.0f}",
                report["monthly_demand"][index + 6]["month"],
                f"{report['monthly_demand'][index + 6]['demand_per_day']:,.0f}",
                f"{report['monthly_demand'][index + 6]['demand_per_month']:,.0f}",
            )
            for index in range(6)
        )

        coordinates = "\n".join(
            f"({_latex_number(point['tank_size'])},{_latex_number(point['reliability'])})"
            for point in report["curve"]
        )
        selected_reliability = "--"
        if report["selected_reliability"] is not None:
            selected_reliability = f"{report['selected_reliability']:.2f}\\%"
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
            _latex_escape(f"{float(row['low']):,.0f}-{float(row['high']):,.0f}")
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
\node[below] at (3.25,0.55) {Filtration pump};
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

        return rf"""\documentclass[11pt]{{article}}
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

\section{{Project Information}}
\begin{{tabular}}{{@{{}}p{{1.6in}}p{{4.8in}}@{{}}}}
\textbf{{Client name}} & {_latex_escape(metadata["client_name"])} \\
\textbf{{Date}} & {_latex_escape(metadata["date"])} \\
\textbf{{Location}} & {_latex_escape(metadata["location"])} \\
\textbf{{Project name}} & {_latex_escape(metadata["project_name"])} \\
\textbf{{End-uses of water}} & {_latex_escape(metadata["end_uses"])} \\
\textbf{{Average annual precipitation}} & {_latex_number(report['average_annual_precipitation'])} {_latex_escape(report['precipitation_unit'])} \\
\textbf{{Precipitation basis}} & {_latex_escape(report['precipitation_basis'])} \\
\textbf{{Selected tank size}} & {_latex_number(report['selected_tank_size'])} {_latex_escape(report['volume_unit'])} \\
\textbf{{Selected tank reliability}} & {selected_reliability} \\
\end{{tabular}}

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

\noindent First-flush event definition: {_latex_number(report.get('first_flush_antecedent_dry_days', 1.0))} antecedent dry days. Events: {int(report.get('first_flush_event_count', 0))}. Diverted volume: {_latex_number(report.get('first_flush_loss', 0.0))} {_latex_escape(volume)}.

\section{{Tank Summary}}
\begin{{tabular}}{{@{{}}lr@{{}}}}
\toprule
Tank property & Value \\
\midrule
Size & {_latex_number(report['selected_tank_size'])} {_latex_escape(volume)} \\
\bottomrule
\end{{tabular}}

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
\multicolumn{{5}}{{r}}{{\textbf{{Total Annual Demand}}}} & \textbf{{{_latex_escape(f"{float(report['total_annual_demand']):,.0f}")} {_latex_escape(volume)}}} \\
\bottomrule
\end{{tabular}}
\normalsize

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

    @staticmethod
    def _build_system_visualization_html(report: dict[str, object]) -> str:
        if not report.get("include_system_visualization"):
            return ""
        system_type = str(report.get("system_type", "Direct system"))
        size_label = html.escape(
            f"{float(report['selected_tank_size']):,.0f} {report['volume_unit']}", quote=True
        )
        if system_type == "Indirect system":
            equipment = """
<line x1="250" y1="130" x2="315" y2="130"/><circle cx="350" cy="130" r="35"/>
<polygon points="385,130 332.5,160.31 332.5,99.69"/><text x="350" y="185">Filtration pump</text>
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

    def _build_report_html(self, report: dict[str, object]) -> str:
        metadata = report["metadata"]
        surfaces = report["surfaces"]
        curve = report["curve"]
        escape = lambda value: html.escape(str(value), quote=True)
        report_title = "RWH Calculator Report - multi-tank" if report.get("include_multitank_charts") else "RWH Calculator Report"
        multitank_html = RainwaterTkApp._build_multitank_report_html(report)
        system_visualization_html = RainwaterTkApp._build_system_visualization_html(report)
        station_latitude = report.get("weather_station_latitude")
        station_longitude = report.get("weather_station_longitude")
        project_latitude = report.get("project_latitude")
        project_longitude = report.get("project_longitude")
        project_location_map_html = ""
        map_points: list[dict[str, object]] = []
        if station_latitude is not None and station_longitude is not None:
            map_points.append({
                    "latitude": float(station_latitude),
                    "longitude": float(station_longitude),
                    "color": "#d71920",
                    "label": "Weather station",
                })
        if project_latitude is not None and project_longitude is not None:
            map_points.append(
                {
                    "latitude": float(project_latitude),
                    "longitude": float(project_longitude),
                    "color": "#1565c0",
                    "label": "Project location",
                }
            )
        if map_points:
            project_legend = (
                '<span class="project-star">★</span> Project location '
                if project_latitude is not None and project_longitude is not None else ""
            )
            station_legend = (
                '<span class="station-star">★</span> Weather station'
                if station_latitude is not None and station_longitude is not None else ""
            )
            project_location_map_html = (
                '<div id="project-location-map" class="location-map" '
                f'data-points="{escape(json.dumps(map_points))}" '
                'aria-label="Project and weather-station location map"></div>'
                f'<div class="map-legend">{project_legend}{station_legend}</div>'
            )
        multitank_toc_html = "".join(
            f'<li><a href="#multitank-chart-{index}">{escape(chart.get("title", f"Multitank chart {index}"))}</a></li>'
            for index, chart in enumerate(report.get("multitank_charts", []), start=1)
        ) if report.get("include_multitank_charts") else ""
        surface_rows = "".join(
            f"<tr><td>{escape(surface['name'])}</td><td>{surface['area']:,.2f}</td>"
            f"<td>{surface['runoff_coefficient']:.2f}</td>"
            f"<td>{float(surface.get('first_flush_depth', 0.0)):.3f}</td></tr>"
            for surface in surfaces
        ) or '<tr><td>No collection surfaces</td><td>0.00</td><td>0.000</td><td>0.000</td></tr>'
        demand_rows = "".join(
            f"<tr><td>{escape(report['monthly_demand'][index]['month'])}</td>"
            f"<td>{float(report['monthly_demand'][index]['demand_per_day']):,.0f}</td>"
            f"<td>{float(report['monthly_demand'][index]['demand_per_month']):,.0f}</td>"
            f"<td>{escape(report['monthly_demand'][index + 6]['month'])}</td>"
            f"<td>{float(report['monthly_demand'][index + 6]['demand_per_day']):,.0f}</td>"
            f"<td>{float(report['monthly_demand'][index + 6]['demand_per_month']):,.0f}</td></tr>"
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
            f'<title>{float(point["tank_size"]):,.0f} {escape(report["volume_unit"])}: '
            f'{float(point["reliability"]):.2f}% reliability</title></circle>'
            for point in curve
        )
        selected_marker = ""
        if report["selected_reliability"] is not None:
            selected_x = chart_x(float(report["selected_tank_size"]))
            selected_y = chart_y(float(report["selected_reliability"]))
            selected_marker = (
                f'<circle class="selected-tank" cx="{selected_x:.2f}" cy="{selected_y:.2f}" r="10">'
                f'<title>Selected tank: {float(report["selected_tank_size"]):,.0f} '
                f'{escape(report["volume_unit"])} at {float(report["selected_reliability"]):.2f}% reliability</title>'
                "</circle>"
            )
        y_grid = "".join(
            f'<line x1="{left}" y1="{chart_y(value):.2f}" x2="{left + plot_width}" y2="{chart_y(value):.2f}" />'
            f'<text x="{left - 14}" y="{chart_y(value) + 4:.2f}" text-anchor="end">{value}</text>'
            for value in range(0, 101, 20)
        )
        x_ticks = "".join(
            f'<line x1="{chart_x(value):.2f}" y1="{top}" x2="{chart_x(value):.2f}" y2="{top + plot_height}" />'
            f'<text x="{chart_x(value):.2f}" y="{top + plot_height + 26}" text-anchor="middle">{value:,.0f}</text>'
            for value in [x_min + (x_max - x_min) * index / 4 for index in range(5)]
        )
        selected = report["selected_reliability"]
        selected_text = "--" if selected is None else f"{selected:.2f}%"
        author_html = ""
        if metadata.get("author_name", "").strip():
            author_html = f'<p class="author">Produced by {escape(metadata["author_name"])}</p>'
        info_rows = "".join(
            f'<div class="fact"><dt>{escape(label)}</dt><dd>{escape(value or "Not specified")}</dd></div>'
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
                ("Selected tank reliability", selected_text),
            ]
        )
        notes_html = escape(report.get("notes", "").strip() or "No notes provided.")
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
                    f"({float(row['met_percent']):.2f}%); demand not met {int(row['unmet_days'])} days "
                    f"({float(row['unmet_percent']):.2f}%)"
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
                    f'data-tooltip="{int(row["year"])} tank reliability: {float(row["met_percent"]):.2f}%"></circle>'
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
                f'data-tooltip="Average tank reliability over {year_count} years: {average_reliability:.2f}%"></circle>'
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
                range_label = f"{float(row['low']):,.0f}-{float(row['high']):,.0f}"
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
        return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
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
.demand-rule td {{ height:5px; padding:0; border-top:1px solid var(--ink); border-bottom:1px solid var(--ink); }} .demand-total td {{ border-bottom:0; font-weight:700; }}
.chart {{ overflow-x:auto; }} svg {{ display:block; width:100%; min-width:620px; height:auto; }} .grid line {{ stroke:#dce5e8; }} .grid text {{ fill:#64747c; font-size:12px; }}
.curve {{ fill:none; stroke:var(--blue); stroke-width:3; }} circle {{ fill:var(--paper); stroke:var(--blue); stroke-width:3; }} circle:hover {{ fill:var(--blue); r:6; }}
.selected-tank {{ fill:none; stroke:#d71920; stroke-width:4; }} .selected-tank:hover {{ fill:none; r:11; }} .swatch.primary-tank {{ background:transparent; border:2px solid #d71920; border-radius:50%; }}
.year-met {{ fill:#2e8b57; }} .year-unmet {{ fill:#c94c4c; }} .year-met,.year-unmet,.year-reliability {{ cursor:pointer; transition:opacity .12s ease,stroke-width .12s ease; }} .year-met:hover,.year-unmet:hover {{ opacity:.78; stroke:#17242b; stroke-width:1.5; }} .year-reliability {{ fill:#f2c94c; stroke:#8a6d00; stroke-width:1.5; }} .year-reliability:hover {{ fill:#f2c94c; stroke-width:2.5; r:7; }} .chart-legend {{ display:flex; flex-wrap:wrap; gap:20px; margin:8px 0 0 72px; font-size:12px; color:var(--muted); }} .series-toggle {{ display:inline-flex; align-items:center; gap:5px; font-weight:700; cursor:pointer; }} .series-toggle input {{ accent-color:currentColor; }} .swatch {{ display:inline-block; width:11px; height:11px; margin-right:6px; vertical-align:-1px; }} .swatch.year-met {{ background:#2e8b57; }} .swatch.year-unmet {{ background:#c94c4c; }} .swatch.year-reliability {{ background:#f2c94c; border:1px solid #8a6d00; border-radius:50%; }} .chart-tooltip {{ position:fixed; display:none; z-index:1000; max-width:320px; padding:7px 9px; border:1px solid #526168; background:#fffff0; color:#17242b; font-size:12px; line-height:1.35; box-shadow:0 3px 10px rgba(0,0,0,.16); pointer-events:none; }}
.tank-history-point {{ fill:transparent; stroke:transparent; stroke-width:1; cursor:crosshair; }} .tank-history-point:hover {{ fill:#fff; stroke:currentColor; stroke-width:2; }}
.history-mode-controls,.history-controls,.history-range-controls {{ display:flex; align-items:center; justify-content:center; gap:10px; margin:8px 0; }} .history-mode-controls label {{ font-weight:700; }} .history-range-controls input[type=range] {{ width:min(280px,35vw); }}
.distribution-bar {{ fill:#2e8b57; stroke:#246b49; stroke-width:1; }}
.axis-label {{ fill:var(--muted); font-size:15px; font-weight:700; }} .history-controls {{ display:flex; align-items:center; justify-content:center; gap:10px; margin:-4px 0 8px; }} .history-controls button {{ width:30px; height:28px; border:1px solid #aab7bc; background:#fff; color:var(--ink); cursor:pointer; }} .history-controls button:disabled {{ color:#aab7bc; cursor:default; }} .history-controls strong {{ min-width:52px; text-align:center; }} footer {{ padding:20px 52px; color:var(--muted); font-size:12px; }}
@media (max-width:900px) {{ .report-shell,.report-shell.toc-collapsed {{ display:block; width:100%; margin:0; }} .toc {{ position:relative; top:auto; max-height:none; box-shadow:none; border-bottom:1px solid var(--line); }} .toc-inner {{ padding:18px 22px; }} .toc ul {{ columns:2; column-gap:28px; }} .toc-collapsed .toc-toggle {{ height:auto; writing-mode:horizontal-tb; transform:none; text-align:left; }} main {{ box-shadow:none; }} }}
@media (max-width:700px) {{ .toc ul {{ columns:1; }} header,main section {{ padding:28px 22px; }} dl {{ grid-template-columns:1fr; }} h1 {{ font-size:28px; }} }}
@media print {{ body {{ background:#fff; }} .report-shell {{ display:block; width:100%; margin:0; }} .toc {{ display:none; }} main {{ width:100%; margin:0; box-shadow:none; }} section {{ break-inside:avoid; }} }}
</style></head><body><div class="report-shell">
<nav class="toc" aria-label="Table of contents"><button id="toc-toggle" class="toc-toggle" type="button" aria-expanded="true" aria-controls="toc-links">Hide contents</button><div id="toc-links" class="toc-inner"><h2>Table of contents</h2><ul><li><a href="#project-information">Project information</a></li><li><a href="#notes">Notes</a></li><li><a href="#surface-area-summary">Surface area summary</a></li><li><a href="#tank-summary">Tank summary</a></li>{'<li><a href="#system-visualization">System visualization</a></li>' if report.get('include_system_visualization') else ''}<li><a href="#demand-summary">Demand summary</a></li><li><a href="#reliability-curve">Reliability curve</a></li><li><a href="#yearly-demand-reliability">Yearly demand reliability</a></li><li><a href="#tank-level-distribution">Tank level distribution</a></li>{multitank_toc_html}</ul></div></nav>
<main>
<header><div class="eyebrow">Rainwater harvesting analysis</div><h1>{escape(metadata['project_name'])}</h1><p>{escape(report_title)}</p>{author_html}</header>
<section id="project-information"><h2>Project information</h2><dl>{info_rows}</dl>{project_location_map_html}</section>
<section id="notes"><h2>Notes</h2><p class="notes-text">{notes_html}</p></section>
<section id="surface-area-summary"><h2>Surface area summary</h2><table><thead><tr><th>Surface</th><th>Area ({escape(report['area_unit'])})</th><th>Runoff coefficient</th><th>First flush ({escape(report['precipitation_unit'])})</th></tr></thead><tbody>{surface_rows}</tbody></table><p>Rainfall-history event definition: {float(report.get('first_flush_antecedent_dry_days', 1.0)):g} antecedent dry days. Events: {int(report.get('first_flush_event_count', 0)):,}. Diverted volume: {float(report.get('first_flush_loss', 0.0)):,.1f} {escape(report['volume_unit'])}.</p></section>
<section id="tank-summary"><h2>Tank summary</h2><table><thead><tr><th>Tank property</th><th>Value</th></tr></thead><tbody><tr><td>Size</td><td>{float(report['selected_tank_size']):,.0f} {escape(report['volume_unit'])}</td></tr><tr><td>Minimum operating level</td><td>{float(report.get('minimum_operating_level_percent', 0.0)):,.1f}% of capacity</td></tr><tr><td>Minimum operating volume</td><td>{float(report.get('minimum_operating_volume', 0.0)):,.0f} {escape(report['volume_unit'])}</td></tr></tbody></table></section>
{system_visualization_html}
<section id="demand-summary"><h2>Demand summary</h2><table><thead><tr><th>Month</th><th>Demand ({escape(report['volume_unit'])}/day)</th><th>Demand ({escape(report['volume_unit'])}/month)</th><th>Month</th><th>Demand ({escape(report['volume_unit'])}/day)</th><th>Demand ({escape(report['volume_unit'])}/month)</th></tr></thead><tbody>{demand_rows}<tr class="demand-rule"><td colspan="6"></td></tr><tr class="demand-total"><td colspan="5">Total Annual Demand</td><td>{float(report['total_annual_demand']):,.0f} {escape(report['volume_unit'])}</td></tr></tbody></table></section>
<section id="reliability-curve"><h2>Reliability curve</h2><div class="chart"><svg viewBox="0 0 {chart_width:.0f} {chart_height:.0f}" role="img" aria-label="Reliability versus tank size chart">
<g class="grid">{y_grid}{x_ticks}</g><polyline class="curve" points="{polyline}"/>{circles}{selected_marker}
<text class="axis-label" x="{left + plot_width / 2:.2f}" y="{chart_height - 10:.2f}" text-anchor="middle">Tank size ({escape(report['volume_unit'])})</text>
<text class="axis-label" transform="translate(18 {top + plot_height / 2:.2f}) rotate(-90)" text-anchor="middle">Reliability (%)</text>
</svg></div><div class="chart-legend"><span><i class="swatch primary-tank"></i>Primary tank size</span></div></section>
<section id="yearly-demand-reliability"><h2>Yearly demand reliability - {float(report['selected_tank_size']):,.0f} {escape(report['volume_unit'])} tank</h2><div class="chart"><svg viewBox="0 0 {yearly_chart_width:.0f} {yearly_chart_height:.0f}" role="img" aria-label="Yearly percentage of days demand was met or not met">
<g class="grid">{yearly_grid}{yearly_labels}</g>{yearly_bars}{yearly_markers}
<text class="axis-label" x="{yearly_left + yearly_plot_width / 2:.2f}" y="{yearly_chart_height - 10:.2f}" text-anchor="middle">Year</text>
<text class="axis-label" transform="translate(18 {yearly_top + yearly_plot_height / 2:.2f}) rotate(-90)" text-anchor="middle">Days (%)</text>
</svg></div><div class="chart-legend"><span><i class="swatch year-met"></i>Demand met</span><span><i class="swatch year-unmet"></i>Demand not met</span><span><i class="swatch year-reliability"></i>Tank reliability</span></div></section>
<section id="tank-level-distribution"><h2>Tank level distribution</h2><div class="chart"><svg viewBox="0 0 {distribution_width:.0f} {distribution_height:.0f}" role="img" aria-label="Distribution of days by tank level range">
<g class="grid">{distribution_grid}</g>{distribution_bars}
<text class="axis-label" x="{distribution_left + distribution_plot_width / 2:.2f}" y="{distribution_height - 10:.2f}" text-anchor="middle">Tank level range ({escape(report['volume_unit'])})</text>
<text class="axis-label" transform="translate(18 {distribution_top + distribution_plot_height / 2:.2f}) rotate(-90)" text-anchor="middle">Days</text>
</svg></div></section>
{multitank_html}
<footer>Generated by RWH Calculator on {escape(dt.date.today().isoformat())}</footer>
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
const locationMapElement=document.getElementById('project-location-map');
if(locationMapElement&&window.L){{
  const points=JSON.parse(locationMapElement.dataset.points);
  const map=L.map(locationMapElement,{{scrollWheelZoom:false}});
  L.tileLayer({json.dumps(OSM_TILE_URL)},{{maxZoom:19,attribution:'&copy; OpenStreetMap contributors'}}).addTo(map);
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

    @staticmethod
    def _build_multitank_report_html(report: dict[str, object]) -> str:
        if not report.get("include_multitank_charts"):
            return ""
        colors = ("#0b5cab", "#2e8b57", "#c94c4c", "#7b4ab5", "#d17a00", "#00838f")
        sections = []
        for chart_index, chart in enumerate(report.get("multitank_charts", [])):
            if chart.get("type") == "yearly_stacked":
                sections.append(RainwaterTkApp._build_stacked_yearly_report_html(chart, chart_index + 1))
                continue
            if chart.get("type") == "tank_history":
                sections.append(RainwaterTkApp._build_tank_history_report_html(chart, chart_index + 1))
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
            y_min, y_max = 0.0, max(max(y_values), 1.0)
            if x_min == x_max:
                x_max = x_min + 1.0

            def sx(value: float) -> float:
                return left + (value - x_min) / (x_max - x_min) * plot_width

            def sy(value: float) -> float:
                return top + (y_max - value) / y_max * plot_height

            grid = "".join(
                f'<line x1="{left}" y1="{top + plot_height * tick / 4:.2f}" x2="{left + plot_width}" y2="{top + plot_height * tick / 4:.2f}" />'
                f'<text x="{left - 12}" y="{top + plot_height * tick / 4 + 4:.2f}" text-anchor="end">{y_max * (4 - tick) / 4:.0f}</text>'
                for tick in range(5)
            )
            polylines = []
            legends = []
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
            section_id = f"multitank-chart-{chart_index + 1}"
            sections.append(
                f'<section id="{section_id}"><h2>{html.escape(str(chart["title"]))}</h2>'
                f'<div class="chart"><svg viewBox="0 0 {width:.0f} {height:.0f}" role="img">'
                f'<g class="grid">{grid}</g>{"".join(polylines)}'
                f'<text class="axis-label" x="{left + plot_width / 2:.2f}" y="{height - 10:.2f}" text-anchor="middle">{html.escape(str(chart["x_label"]))}</text>'
                f'<text class="axis-label" transform="translate(18 {top + plot_height / 2:.2f}) rotate(-90)" text-anchor="middle">{html.escape(str(chart["y_label"]))}</text>'
                f'</svg></div><div class="chart-legend">{"".join(legends)}</div></section>'
            )
        return "".join(sections)

    @staticmethod
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
                f"({float(row['met_percent']):.2f}%); demand not met {int(row['unmet_days'])} days "
                f"({float(row['unmet_percent']):.2f}%)"
            )
            bars.append(
                f'<rect class="year-met" x="{bar_x:.2f}" y="{marker_y:.2f}" width="{bar_width:.2f}" '
                f'height="{met_height:.2f}" data-tooltip="{escape(tooltip)}"></rect>'
                f'<rect class="year-unmet" x="{bar_x:.2f}" y="{top:.2f}" width="{bar_width:.2f}" '
                f'height="{unmet_height:.2f}" data-tooltip="{escape(tooltip)}"></rect>'
            )
            markers.append(
                f'<circle class="year-reliability" cx="{marker_x:.2f}" cy="{marker_y:.2f}" r="5" '
                f'data-tooltip="{int(row["year"])} tank reliability: {float(row["met_percent"]):.2f}%"></circle>'
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
            f'data-tooltip="Average tank reliability over {year_count_text}: {average:.2f}%"></circle>'
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
            f'<span><i class="swatch year-reliability"></i>Tank reliability</span></div></section>'
        )

    @staticmethod
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
            f'text-anchor="end">{y_max * (4 - tick) / 4:.0f}</text>'
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
                        f'{year}, day {float(day):g}: {float(level):,.2f} '
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
                f'{level:,.2f} {html.escape(str(chart["y_label"]))}"></circle>'
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
            f'<div class="chart-legend">{toggles}</div></section>'
        )

    def _compile_latex_report(self, tex_path: Path, pdf_path: Path, report: dict[str, object]) -> None:
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

    def _write_fallback_pdf_report(self, pdf_path: Path, report: dict[str, object]) -> None:
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
            "Project Information",
            "Notes",
            "Surface Area Summary",
            "Tank Summary",
            *(("System Visualization",) if report.get("include_system_visualization") else ()),
            "Demand Summary",
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
            text(map_x + 5, map_y + 5, "Map data © OpenStreetMap contributors", size=7)
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

        heading("Reliability Curve")
        self._draw_pdf_reliability_curve(page(), 78, max(120, y - 280), 456, 250, report)

        add_page()
        heading(
            f"Yearly Demand Reliability - {float(report['selected_tank_size']):,.0f} "
            f"{report['volume_unit']} tank"
        )
        self._draw_pdf_yearly_demand_reliability(page(), 78, 400, 456, 250, report)

        add_page()
        heading("Tank Level Distribution")
        self._draw_pdf_tank_level_distribution(page(), 78, 400, 456, 250, report)

        if report.get("include_multitank_charts"):
            for chart in report.get("multitank_charts", []):
                add_page()
                heading(str(chart["title"]))
                if chart.get("type") == "yearly_stacked":
                    stacked_report = {
                        "yearly_reliability": chart["yearly_reliability"],
                        "selected_reliability": chart["selected_reliability"],
                    }
                    self._draw_pdf_yearly_demand_reliability(page(), 78, 400, 456, 250, stacked_report)
                else:
                    self._draw_pdf_multiline_chart(page(), 78, 400, 456, 250, chart)

        self._write_pdf_with_pypdf(pdf_path, pages, section_pages, toc_links)

    def _draw_pdf_multiline_chart(
        self,
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
        self, commands: list[str], x: float, y: float, width: float, height: float, report: dict[str, object]
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
        self, commands: list[str], x: float, y: float, width: float, height: float, report: dict[str, object]
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
        self, commands: list[str], x: float, y: float, width: float, height: float, report: dict[str, object]
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
        self,
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
        data = self.curve_df.copy()
        hydraulic_columns = (
            "TankSizeGallons", "ReliabilityPercent", "TotalDemandGallons",
            "RainwaterSuppliedGallons", "AverageAnnualRainwaterSuppliedGallons",
            "SewerEligibleRainwaterSuppliedGallons",
            "AverageAnnualSewerEligibleRainwaterSuppliedGallons",
            "UnmetDemandGallons", "MunicipalMakeupGallons", "SystemUnmetDemandGallons",
            "OverflowGallons", "FirstFlushLossGallons", "TreatmentLossGallons",
            "FinalStorageGallons",
        )
        for column in hydraulic_columns:
            if column not in data:
                data[column] = pd.NA
        data["NetAnnualSavings"] = pd.NA
        data["SimplePaybackYears"] = pd.NA
        params = self.config_model.financial_parameters
        configured = any(
            float(value) > 0.0
            for value in (
                params.water_rate, params.sewer_rate, params.installed_cost,
                params.incentives, params.fixed_annual_maintenance,
                params.annual_maintenance_percent,
            )
        )
        if configured:
            for index, supplied in data["AverageAnnualRainwaterSuppliedGallons"].items():
                if pd.isna(supplied):
                    continue
                try:
                    financial = calculate_financial_results_from_annual_supply(
                        float(supplied),
                        average_annual_sewer_eligible_supplied_gallons=(
                            None
                            if pd.isna(data.at[index, "AverageAnnualSewerEligibleRainwaterSuppliedGallons"])
                            else float(data.at[index, "AverageAnnualSewerEligibleRainwaterSuppliedGallons"])
                        ),
                        water_rate=params.water_rate,
                        sewer_rate=params.sewer_rate,
                        billing_unit=params.tariff_billing_unit,
                        sewer_eligible_percent=params.sewer_eligible_percent,
                        installed_cost=params.installed_cost,
                        incentives=params.incentives,
                        fixed_annual_maintenance=params.fixed_annual_maintenance,
                        maintenance_percent=params.annual_maintenance_percent,
                        analysis_period_years=params.analysis_period_years,
                    )
                except ValueError:
                    continue
                data.at[index, "NetAnnualSavings"] = financial.net_annual_savings
                data.at[index, "SimplePaybackYears"] = financial.simple_payback_years
        return data

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
            return
        if self.candidate_sort_column in data:
            data = data.sort_values(
                self.candidate_sort_column,
                ascending=not self.candidate_sort_reverse,
                na_position="last",
                kind="stable",
            )
        unit = volume_unit(self.config_model)
        currency = self.config_model.financial_parameters.currency
        volume_columns = (
            "TankSizeGallons", "TotalDemandGallons", "RainwaterSuppliedGallons",
            "SewerEligibleRainwaterSuppliedGallons",
            "UnmetDemandGallons", "MunicipalMakeupGallons", "SystemUnmetDemandGallons",
            "OverflowGallons", "FirstFlushLossGallons", "TreatmentLossGallons",
            "FinalStorageGallons",
        )
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
        }
        for column, label in heading_labels.items():
            tree.heading(column, text=label)
        for position, row in enumerate(data.itertuples(index=False), start=1):
            values_by_column = row._asdict()
            display_values: list[str] = []
            for column in tree["columns"]:
                value = values_by_column.get(column)
                if pd.isna(value):
                    display_values.append("--")
                elif column in volume_columns:
                    display_values.append(
                        f"{volume_to_display(float(value), self.config_model):,.0f}"
                    )
                elif column == "ReliabilityPercent":
                    display_values.append(f"{float(value):.1f}")
                elif column == "NetAnnualSavings":
                    display_values.append(f"{float(value):,.2f}")
                elif column == "SimplePaybackYears":
                    display_values.append(f"{float(value):.1f}")
                else:
                    display_values.append(str(value))
            item = f"candidate-{position}"
            tree.insert("", "end", iid=item, values=display_values)
            tank_size = values_by_column.get("TankSizeGallons")
            if not pd.isna(tank_size):
                self.candidate_tree_sizes[item] = float(tank_size)

    def use_candidate_as_primary(self) -> None:
        selected = self.candidate_performance_tree.selection()
        if len(selected) != 1 or selected[0] not in self.candidate_tree_sizes:
            messagebox.showinfo(APP_TITLE, "Select one candidate tank first.")
            return
        tank_size = self.candidate_tree_sizes[selected[0]]
        self.selected_tank_var.set(f"{volume_to_display(tank_size, self.config_model):.0f}")
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
            return
        export = data.copy()
        unit = volume_unit(self.config_model)
        volume_columns = [column for column in export.columns if column.endswith("Gallons")]
        for column in volume_columns:
            export[column] = pd.to_numeric(export[column], errors="coerce").map(
                lambda value: volume_to_display(float(value), self.config_model) if pd.notna(value) else value
            )
        export = export.rename(
            columns={column: column.replace("Gallons", f" ({unit})") for column in volume_columns}
        )
        export.to_csv(path, index=False, quoting=csv.QUOTE_MINIMAL)
        self.status_var.set(f"Exported candidate tank performance: {Path(path).name}")

    @staticmethod
    def _station_label(station: dict) -> str:
        location = ""
        if station.get("latitude") is not None and station.get("longitude") is not None:
            location = f" ({station['latitude']:.3f}, {station['longitude']:.3f})"
        distance = f" - {float(station['distance_km']):.1f} km" if station.get("distance_km") is not None else ""
        return f"{station['name']} - {station['sid']}{distance}{location}{RainwaterTkApp._station_region_suffix(station)}"

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
        self.results_tree.delete(*self.results_tree.get_children())
        display = self._display_results_df()
        overflow_column = f"Overflow ({volume_unit(self.config_model)}/day)"
        for _, row in display.iterrows():
            overflow_value = row.get(overflow_column)
            overflow_text = "" if pd.isna(overflow_value) else f"{overflow_value:.1f}"
            self.results_tree.insert(
                "",
                "end",
                values=(
                    pd.Timestamp(row["Date"]).strftime("%Y-%m-%d"),
                    f"{row[f'Precipitation ({precip_unit(self.config_model)})']:.3f}",
                    f"{row[f'Gross runoff ({volume_unit(self.config_model)})']:.1f}",
                    f"{row[f'First-flush loss ({volume_unit(self.config_model)})']:.1f}",
                    f"{row[f'Collected ({volume_unit(self.config_model)})']:.1f}",
                    overflow_text,
                    f"{row[f'Demand ({volume_unit(self.config_model)}/day)']:.1f}",
                    f"{row[f'Unmet Demand ({volume_unit(self.config_model)}/day)']:.1f}",
                    f"{row[f'Water in Tank ({volume_unit(self.config_model)})']:.1f}",
                ),
            )
        self._populate_hourly_results()
        self._populate_candidate_performance()

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
            label = self.hourly_results_tree.heading(column, "text").split(" (")[0]
            self.hourly_results_tree.heading(column, text=f"{label} ({unit})")
        for row in self._selected_hourly_results().itertuples(index=False):
            self.hourly_results_tree.insert(
                "", "end", values=(
                    pd.Timestamp(row.Date).strftime("%Y-%m-%d %H:00"),
                    f"{volume_to_display(row.GrossCollectedGallons, self.config_model):.2f}",
                    f"{volume_to_display(row.FirstFlushLossGallons, self.config_model):.2f}",
                    f"{volume_to_display(row.CollectedGallons, self.config_model):.2f}",
                    f"{volume_to_display(row.DemandGallons, self.config_model):.2f}",
                    f"{volume_to_display(row.PumpFlowGallons, self.config_model):.2f}",
                    f"{volume_to_display(row.FilterThroughputGallons, self.config_model):.2f}",
                    f"{volume_to_display(row.FilterLossGallons, self.config_model):.2f}",
                    f"{volume_to_display(row.BoosterTankGallons, self.config_model):.2f}",
                    f"{volume_to_display(row.MainsMakeupGallons, self.config_model):.2f}",
                    f"{volume_to_display(row.UnmetDemandGallons, self.config_model):.2f}",
                    f"{volume_to_display(row.SystemUnmetDemandGallons, self.config_model):.2f}",
                    f"{volume_to_display(row.OverflowGallons, self.config_model):.2f}",
                    f"{volume_to_display(row.WaterInTankGallons, self.config_model):.2f}",
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
            f"Hourly Tank Water Over Time ({self.hourly_results_year_var.get()}) - {volume_to_display(self.config_model.selected_tank_size_gal, self.config_model):,.0f} {volume_unit(self.config_model)} tank",
            volume_unit(self.config_model),
            "Simulation hour",
            [
                f"Date: {pd.Timestamp(dates[index]):%Y-%m-%d %H:00}\nWater in tank: {values[index]:.2f} {volume_unit(self.config_model)}"
                for index in indices
            ],
            show_points=False,
        )

    def _clear_results(self) -> None:
        self.comparison_results = {}
        self.tank_chart_year = None
        self.tank_chart_year_var.set("--")
        self.tank_chart_range_initialized = False
        self.average_annual_precipitation_var.set("Average annual precipitation: --")
        self.results_tree.delete(*self.results_tree.get_children())
        if hasattr(self, "hourly_results_tree"):
            self.hourly_results_tree.delete(*self.hourly_results_tree.get_children())
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
            f"Tank size: {tank_size:.0f} {volume_unit(self.config_model)}\nReliability: {reliability:.2f}%"
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
            f"Date: {pd.Timestamp(date).strftime('%Y-%m-%d')}\nWater in tank: {water:.1f} {volume_unit(self.config_model)}"
            for date, water in zip(chart_results["Date"], y)
        ]
        self._draw_line_chart(
            self.tank_canvas,
            x,
            y,
            f"Tank Water Over Time ({chart_title_period}) - "
            f"{volume_to_display(self.config_model.selected_tank_size_gal, self.config_model):,.0f} "
            f"{volume_unit(self.config_model)} tank",
            volume_unit(self.config_model),
            "Day in selected period",
            hover_labels,
            show_points=self.show_tank_points_var.get(),
            bottom_padding=78,
        )

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
            text=f"Tank Level Distribution - {selected_capacity:,.0f} {unit} tank",
            font=("Segoe UI", 10, "bold"),
        )

        for tick in range(5):
            y = pad_top + plot_height * tick / 4
            value = max_count * (4 - tick) / 4
            canvas.create_line(pad_left, y, width - pad_right, y, fill="#e6e6e6")
            canvas.create_text(pad_left - 7, y, text=f"{value:.0f}", anchor="e", font=("Segoe UI", 8))
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
            canvas.create_text((left + right) / 2, bottom + 15, text=f"{low:.0f}-{high:.0f}", font=("Segoe UI", 7))
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
            text=f"Yearly Demand Reliability - {selected_capacity:,.0f} {unit} tank",
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
                f"Demand met: {int(row['met_days'])} days ({float(row['met_percent']):.2f}%)\n"
                f"Demand not met: {int(row['unmet_days'])} days ({float(row['unmet_percent']):.2f}%)"
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
            (average_x, average_y, f"Overall tank reliability: {average_reliability:.2f}%")
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
            label = f"{display_size:,.0f} {unit}"
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
            canvas.create_text(pad_left - 7, y, text=f"{value:.0f}", anchor="e", font=("Segoe UI", 7))
            x = pad_left + plot_width * tick / 4
            x_value = x_min + (x_max - x_min) * tick / 4
            canvas.create_text(x, height - pad_bottom + 14, text=f"{x_value:.0f}", font=("Segoe UI", 7))
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
                canvas.hover_points.append((px, py, f"Tank: {label}\n{x_label}: {x_values[index]:.0f}\n{y_label}: {y_values[index]:.1f}"))
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
        hover_labels = hover_labels or [f"X: {x:.2f}\nY: {y:.2f}" for x, y in zip(x_values, y_values)]
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
            canvas.create_text(pad_left - 8, y, text=f"{value:.0f}", anchor="e", font=("Segoe UI", 8))
        for i in range(5):
            x = pad_left + (plot_w * i / 4)
            value = x_min + ((x_max - x_min) * i / 4)
            canvas.create_line(x, height - pad_bottom, x, height - pad_bottom + 5, fill="#555")
            canvas.create_text(x, height - pad_bottom + 17, text=f"{value:.0f}", font=("Segoe UI", 8))
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


class SurfaceDialog(tk.Toplevel):
    def __init__(self, parent: RainwaterTkApp, surface: Surface, config: ProjectConfig) -> None:
        super().__init__(parent)
        self.title("Edit Surface")
        self.resizable(False, False)
        self.result: Surface | None = None
        self.config_model = config
        self.name_var = tk.StringVar(value=surface.name)
        self.area_var = tk.StringVar(value=f"{area_to_display(surface.area, config):.2f}")
        self.runoff_var = tk.StringVar(value=f"{surface.runoff_coefficient:.2f}")
        self.first_flush_depth_var = tk.StringVar(
            value=f"{precip_to_display(surface.first_flush_depth_inches, config):.3f}"
        )
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
            text=f"Default runoff coefficient: {default_runoff:.2f}",
            fg="#777777",
        ).grid(row=3, column=1, sticky="w", pady=(0, 6))
        ttk.Label(body, text=f"First-flush depth ({precip_unit(config)})").grid(
            row=4, column=0, sticky="w", pady=3
        )
        ttk.Entry(body, textvariable=self.first_flush_depth_var, width=18).grid(
            row=4, column=1, sticky="w", pady=3
        )
        ttk.Label(
            body,
            text="Diverted once per rainfall event; 0 disables diversion for this surface.",
            foreground="#777777",
        ).grid(row=5, column=1, sticky="w", pady=(0, 6))
        buttons = ttk.Frame(body)
        buttons.grid(row=6, column=0, columnspan=2, sticky="e", pady=(10, 0))
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
            first_flush_depth_inches=max(
                precip_to_internal(_float(self.first_flush_depth_var.get()), self.config_model),
                0.0,
            ),
        )
        self.destroy()


class ReportDialog(tk.Toplevel):
    def __init__(self, parent: RainwaterTkApp, defaults: dict[str, object]) -> None:
        super().__init__(parent)
        self.title("PDF Report")
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

        self.include_multitank_var = tk.BooleanVar(value=False)
        self.multitank_check = ttk.Checkbutton(
            body,
            text="Include multi-tank sizing charts",
            variable=self.include_multitank_var,
        )
        self.multitank_check.grid(row=5, column=0, columnspan=2, sticky="w", pady=(8, 0))
        if not bool(defaults.get("multitank_available", False)):
            self.multitank_check.state(["disabled"])

        self.include_system_visualization_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            body,
            text="Include system-type visualization",
            variable=self.include_system_visualization_var,
        ).grid(row=6, column=0, columnspan=2, sticky="w", pady=(6, 0))

        buttons = ttk.Frame(body)
        buttons.grid(row=7, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(buttons, text="Cancel", command=self.destroy).grid(row=0, column=0, padx=4)
        ttk.Button(buttons, text="Continue", command=self._save).grid(row=0, column=1)

        self.transient(parent)
        self.grab_set()

    def _save(self) -> None:
        self.result = {key: var.get().strip() for key, var in self.vars.items()}
        self.result["author_name"] = self.author_name.strip()
        self.result["end_uses"] = self.end_uses_text.get("1.0", "end").strip() or "Not specified"
        self.result["include_multitank_charts"] = bool(self.include_multitank_var.get())
        self.result["include_system_visualization"] = bool(self.include_system_visualization_var.get())
        self.destroy()


class HourlyDemandScheduleDialog(tk.Toplevel):
    DAY_LABELS = dict(zip(WEEKDAY_KEYS, ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")))

    def __init__(self, parent: RainwaterTkApp, config: ProjectConfig) -> None:
        super().__init__(parent)
        self.title("Edit Typical Week Demand Schedule")
        self.transient(parent)
        self.grab_set()
        self.saved = False
        self.config_model = config
        self.vars: dict[tuple[str, int], tk.StringVar] = {}
        body = ttk.Frame(self, padding=10)
        body.grid(sticky="nsew")
        ttk.Label(
            body,
            text="Hourly multipliers range from 0 (off) to 1 (100% on). Active values distribute the daily demand.",
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
                variable = tk.StringVar(value=f"{min(max(float(value), 0.0), 1.0):.3f}")
                self.vars[(day, hour)] = variable
                ttk.Entry(body, textvariable=variable, width=8, justify="right").grid(
                    row=hour + 2, column=column, padx=2, pady=1
                )
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
            variable.set("1.000")

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
            if any(value < 0.0 or value > 1.0 for value in multipliers):
                messagebox.showwarning(
                    APP_TITLE,
                    f"Hourly multipliers for {self.DAY_LABELS[day]} must be between 0 and 1.",
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
        "Irrigation system", "Toilet", "Urinal", "Cooling tower", "Ice making",
        "Ice skating", "Other indoor", "Vehicle washing", "Other outdoor", "Other",
    )
    MODE_LABELS = {
        "Scheduled flow": "scheduled_flow",
        "Recurring daily volume": "recurring_daily",
        "Monthly volume": "monthly_volume",
    }

    def __init__(self, parent: RainwaterTkApp, config: ProjectConfig, demand_object: DemandObject) -> None:
        super().__init__(parent)
        self.title("Edit Demand Object")
        self.resizable(False, False)
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
        initial_flow_unit = "lpm" if config.unit_system == "Metric" else "gpm"
        self.instantaneous_demand_unit_var = tk.StringVar(value=initial_flow_unit)
        self._instantaneous_demand_unit = initial_flow_unit
        self.instantaneous_demand_var = tk.StringVar(
            value=f"{_demand_flow_from_gallons_per_minute(demand_object.instantaneous_demand_gallons_per_minute, initial_flow_unit):.8g}"
        )
        schedule_names = list(config.demand.hourly_schedule_library)
        selected_schedule = demand_object.schedule_name if demand_object.schedule_name in schedule_names else schedule_names[0]
        self.schedule_var = tk.StringVar(value=selected_schedule)
        mode_label = next(
            (label for label, value in self.MODE_LABELS.items() if value == demand_object.demand_mode),
            "Scheduled flow",
        )
        self.mode_var = tk.StringVar(value=mode_label)
        self.daily_volume_var = tk.StringVar(value=f"{volume_to_display(demand_object.recurring_daily_gallons, config):.8g}")
        self.operating_days_var = tk.StringVar(value=str(demand_object.operating_days_per_week))
        self.monthly_values = dict(
            demand_object.monthly_daily_demand_gallons
            if demand_object.demand_mode == "recurring_daily"
            else demand_object.monthly_demand_gallons
        )

        body = ttk.Frame(self, padding=12)
        body.grid(sticky="nsew")
        ttk.Label(body, text="Name").grid(row=0, column=0, sticky="w", pady=3)
        self.name_entry = ttk.Entry(body, textvariable=self.name_var, width=34)
        self.name_entry.grid(row=0, column=1, sticky="ew", pady=3)
        ttk.Label(body, text="Type").grid(row=1, column=0, sticky="w", pady=3)
        type_combo = ttk.Combobox(
            body,
            textvariable=self.type_var,
            values=self.OBJECT_TYPES,
            state="readonly",
            width=31,
        )
        type_combo.grid(row=1, column=1, sticky="ew", pady=3)
        type_combo.bind("<<ComboboxSelected>>", self._demand_type_changed)
        ttk.Label(body, text="Instantaneous demand").grid(row=2, column=0, sticky="w", pady=3)
        demand_row = ttk.Frame(body)
        demand_row.grid(row=2, column=1, sticky="ew", pady=3)
        demand_row.columnconfigure(0, weight=1)
        ttk.Entry(demand_row, textvariable=self.instantaneous_demand_var).grid(row=0, column=0, sticky="ew")
        demand_unit_combo = ttk.Combobox(
            demand_row,
            textvariable=self.instantaneous_demand_unit_var,
            values=DEMAND_FLOW_UNITS,
            state="readonly",
            width=9,
        )
        demand_unit_combo.grid(row=0, column=1, padx=(8, 0))
        demand_unit_combo.bind("<<ComboboxSelected>>", self._change_instantaneous_demand_unit)
        ttk.Label(body, text="Schedule").grid(row=3, column=0, sticky="w", pady=3)
        ttk.Combobox(
            body,
            textvariable=self.schedule_var,
            values=schedule_names,
            state="readonly",
            width=31,
        ).grid(row=3, column=1, sticky="ew", pady=3)
        ttk.Label(body, text="Demand mode").grid(row=4, column=0, sticky="w", pady=3)
        ttk.Combobox(
            body, textvariable=self.mode_var, values=tuple(self.MODE_LABELS),
            state="readonly", width=31,
        ).grid(row=4, column=1, sticky="ew", pady=3)
        ttk.Label(body, text=f"Recurring volume ({volume_unit(config)}/day)").grid(
            row=5, column=0, sticky="w", pady=3
        )
        ttk.Entry(body, textvariable=self.daily_volume_var).grid(row=5, column=1, sticky="ew", pady=3)
        ttk.Label(body, text="Operating days/week").grid(row=6, column=0, sticky="w", pady=3)
        ttk.Combobox(
            body, textvariable=self.operating_days_var,
            values=tuple(str(value) for value in range(8)), state="readonly", width=31,
        ).grid(row=6, column=1, sticky="ew", pady=3)
        ttk.Checkbutton(
            body,
            text="Eligible for sewer-charge savings",
            variable=self.sewer_eligible_var,
        ).grid(row=7, column=1, sticky="w", pady=3)
        ttk.Button(
            body, text="Edit January-December values...", command=self._edit_monthly_values
        ).grid(row=8, column=1, sticky="w", pady=3)
        buttons = ttk.Frame(body)
        buttons.grid(row=9, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(buttons, text="Cancel", command=self.destroy).grid(row=0, column=0, padx=(0, 6))
        ttk.Button(buttons, text="Save", command=self._save).grid(row=0, column=1)
        self.bind("<Escape>", lambda _event: self.destroy())
        self.bind("<Return>", lambda _event: self._save())
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

    def _edit_monthly_values(self) -> None:
        values = [
            volume_to_display(float(self.monthly_values.get(month, 0.0)), self.config_model)
            for month in MONTH_KEYS
        ]
        entered = simpledialog.askstring(
            APP_TITLE,
            "Enter Jan-Dec volumes separated by commas:\n" + ", ".join(MONTH_LABELS[month] for month in MONTH_KEYS),
            initialvalue=", ".join(f"{value:g}" for value in values),
            parent=self,
        )
        if entered is None:
            return
        parts = [part.strip() for part in entered.split(",")]
        if len(parts) != 12:
            messagebox.showwarning(APP_TITLE, "Enter exactly 12 comma-separated values.", parent=self)
            return
        try:
            converted = [volume_to_internal(max(float(part), 0.0), self.config_model) for part in parts]
        except ValueError:
            messagebox.showwarning(APP_TITLE, "Monthly values must be numeric.", parent=self)
            return
        self.monthly_values = dict(zip(MONTH_KEYS, converted))

    def _demand_type_changed(self, _event: tk.Event | None = None) -> None:
        self.sewer_eligible_var.set(
            default_sewer_eligible_for_object_type(self.type_var.get())
        )

    def _change_instantaneous_demand_unit(self, _event: tk.Event | None = None) -> None:
        new_unit = self.instantaneous_demand_unit_var.get()
        old_unit = self._instantaneous_demand_unit
        if new_unit == old_unit:
            return
        try:
            current_value = float(self.instantaneous_demand_var.get())
        except ValueError:
            self.instantaneous_demand_unit_var.set(old_unit)
            self.bell()
            return
        internal_flow = _demand_flow_to_gallons_per_minute(current_value, old_unit)
        converted = _demand_flow_from_gallons_per_minute(internal_flow, new_unit)
        self.instantaneous_demand_var.set(f"{converted:.8g}")
        self._instantaneous_demand_unit = new_unit

    def _save(self) -> None:
        name = self.name_var.get().strip()
        if not name:
            messagebox.showwarning(APP_TITLE, "Demand object name cannot be blank.", parent=self)
            return
        schedule_name = self.schedule_var.get()
        if schedule_name not in self.config_model.demand.hourly_schedule_library:
            messagebox.showwarning(APP_TITLE, "Select a schedule that is in the current project.", parent=self)
            return
        self.result = DemandObject(
            name=name,
            object_type=self.type_var.get() or "Other",
            instantaneous_demand_gallons_per_minute=_demand_flow_to_gallons_per_minute(
                max(_float(self.instantaneous_demand_var.get()), 0.0),
                self.instantaneous_demand_unit_var.get(),
            ),
            schedule_name=schedule_name,
            demand_mode=self.MODE_LABELS[self.mode_var.get()],
            recurring_daily_gallons=volume_to_internal(
                max(_float(self.daily_volume_var.get()), 0.0), self.config_model
            ),
            operating_days_per_week=min(max(int(_float(self.operating_days_var.get(), 7)), 0), 7),
            monthly_daily_demand_gallons=(
                dict(self.monthly_values)
                if self.MODE_LABELS[self.mode_var.get()] == "recurring_daily" else {}
            ),
            monthly_demand_gallons=(
                dict(self.monthly_values)
                if self.MODE_LABELS[self.mode_var.get()] == "monthly_volume" else {}
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
            var = tk.StringVar(value=f"{value:.2f}")
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
        store = SQLiteStore(str(_app_dir() / "rainwater_projects.db"))
        print(f"{APP_TITLE} smoke test OK; {len(store.list_projects())} saved project(s) visible.")
        raise SystemExit(0)
    app = RainwaterTkApp()
    app.mainloop()
