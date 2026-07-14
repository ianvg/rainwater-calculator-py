from __future__ import annotations

import csv
import datetime as dt
import html
import json
import shutil
import subprocess
import sys
import tkinter as tk
import tempfile
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

import pandas as pd
import pycountry
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from rainwater_app.acis import default_complete_calendar_range, fetch_daily_station_data, fetch_station_options
from rainwater_app.defaults import default_project_config, default_surface_runoff
from rainwater_app.eccc import fetch_canadian_daily_station_data, fetch_canadian_station_options
from rainwater_app.engine import reliability_curve, simulate_tank
from rainwater_app.models import MONTH_KEYS, ProjectConfig, Surface
from rainwater_app.rainfall import load_rainfall_csv
from rainwater_app.storage import SQLiteStore
from rainwater_app.units import (
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

APP_TITLE = "Rainwater Harvesting Calculator"
DEFAULT_WINDOW_WIDTH = 1200
DEFAULT_WINDOW_HEIGHT = 680
MINIMUM_WINDOW_WIDTH = 1000
GRAPH_AUTO_STEP_COUNT = 40
MAX_RECENT_PROJECTS = 8
ONLINE_HELP_URL = "https://ianvg.github.io/rainwater-calculator-py/"
ABOUT_TEXT = """RWH Calculator

Copyright (c) 2026 RWH Calculator contributors
All rights reserved except as granted by the open-source license below.

OPEN-SOURCE LICENSE:
RWH Calculator is open-source software released under the
Zero-Clause BSD (0BSD) license.

Permission to use, copy, modify, and/or distribute this software for any
purpose with or without fee is hereby granted.

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


def _help_index_path() -> Path | None:
    bundled_root = Path(getattr(sys, "_MEIPASS", _app_dir()))
    candidates = [bundled_root / "help" / "index.html", _app_dir() / "site" / "index.html"]
    return next((path for path in candidates if path.is_file()), None)


def _float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


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


class RainwaterTkApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.withdraw()
        self.title(APP_TITLE)
        self.active_project_name: str | None = None
        self.geometry(f"{DEFAULT_WINDOW_WIDTH}x{DEFAULT_WINDOW_HEIGHT}")
        self.minsize(MINIMUM_WINDOW_WIDTH, DEFAULT_WINDOW_HEIGHT)
        self.progress_style = ttk.Style(self)
        self.progress_style.configure("Analysis.Horizontal.TProgressbar")
        self.progress_style.configure("OpenProject.Horizontal.TProgressbar", background="#2e8b57")
        self.progress_style.configure("Invalid.TLabel", foreground="#c62828", font=("TkDefaultFont", 11, "bold"))

        self.project_file_path = _app_dir() / "rainwater_projects.db"
        self.store = SQLiteStore(str(self.project_file_path))
        self.recent_projects_path = _app_dir() / "recent_projects.json"
        self.recent_project_paths = self._load_recent_project_paths()
        self.config_model = default_project_config()
        self.rainfall_df = pd.DataFrame(columns=["Date", "Precipitation"])
        self.curve_df = pd.DataFrame()
        self.results_df = pd.DataFrame()
        self.station_options: list[dict] = []

        self.project_name_var = tk.StringVar(value=self.config_model.name)
        self.unit_var = tk.StringVar(value=self.config_model.unit_system)
        self.country_var = tk.StringVar(value=COUNTRY_LABEL_BY_CODE["USA"])
        self.saved_project_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Ready")
        self.simple_daily_var = tk.StringVar(value="0")
        self.flushes_var = tk.StringVar(value="0")
        self.toilet_flush_var = tk.StringVar(value="0")
        self.urinal_flush_var = tk.StringVar(value="0")
        self.graph_start_var = tk.StringVar(value=str(self.config_model.graph_start_gal))
        self.graph_end_var = tk.StringVar(value=str(self.config_model.graph_end_gal))
        self.graph_step_var = tk.StringVar(value=str(self.config_model.graph_step_gal))
        self.selected_tank_var = tk.StringVar(value=str(self.config_model.selected_tank_size_gal))
        self.selected_tank_warning_var = tk.StringVar()
        self.initial_fill_var = tk.StringVar(value=str(self.config_model.tank_parameters.initial_fill_percent))
        self.reserve_var = tk.StringVar(value=str(self.config_model.tank_parameters.reliable_fill_percent))
        self.simple_daily_unit_var = tk.StringVar()
        self.flush_count_unit_var = tk.StringVar(value="flushes/person")
        self.flush_volume_unit_var = tk.StringVar()
        self.tank_size_unit_var = tk.StringVar()
        self.percent_unit_var = tk.StringVar(value="%")
        self.reserve_unit_var = tk.StringVar(value="% of daily demand")
        self.rainfall_summary_var = tk.StringVar(value="No rainfall file loaded")
        self.reliability_var = tk.StringVar(value="Reliability: --")
        self.analysis_progress_var = tk.DoubleVar(value=0.0)
        self.show_tank_points_var = tk.BooleanVar(value=True)
        self.weather_state_var = tk.StringVar(value=STATE_PLACEHOLDER)
        self.weather_years_var = tk.StringVar(value="30")
        self.weather_filter_var = tk.StringVar(value="")
        self.station_var = tk.StringVar(value="")
        self.canadian_precip_var = tk.StringVar(value="Total precipitation")
        self.rainfall_source_label: str | None = None
        self.station_typeahead = ""
        self.station_typeahead_after_id: str | None = None
        self.state_typeahead = ""
        self.state_typeahead_after_id: str | None = None
        self.state_popdown_key_command: str | None = None
        self.country_typeahead = ""
        self.country_typeahead_after_id: str | None = None
        self.country_popdown_key_command: str | None = None
        self.results_chart_redraw_after_id: str | None = None

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
        self.rowconfigure(1, weight=1)
        self._build_menu()

        toolbar = ttk.Frame(self, padding=(10, 8))
        toolbar.grid(row=0, column=0, sticky="ew")
        toolbar.columnconfigure(2, weight=1)

        ttk.Label(toolbar, text="Project").grid(row=0, column=0, sticky="w")
        self.project_combo = ttk.Combobox(toolbar, textvariable=self.saved_project_var, width=24, state="readonly")
        self.project_combo.grid(row=0, column=1, padx=(6, 8), sticky="w")
        ttk.Button(toolbar, text="Run Analysis", command=self.run_analysis).grid(row=0, column=3, padx=(18, 2))
        ttk.Button(toolbar, text="Export Results", command=self.export_results).grid(row=0, column=4, padx=2)

        notebook = ttk.Notebook(self)
        notebook.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 6))

        self.inputs_tab = ttk.Frame(notebook, padding=10)
        self.import_tab = ttk.Frame(notebook, padding=10)
        self.demand_tab = ttk.Frame(notebook, padding=10)
        self.results_tab = ttk.Frame(notebook, padding=10)
        notebook.add(self.inputs_tab, text="Project Inputs")
        notebook.add(self.import_tab, text="Rainwater Data")
        notebook.add(self.demand_tab, text="Monthly Demand")
        notebook.add(self.results_tab, text="Results")

        self._build_inputs_tab()
        self._build_import_tab()
        self._build_demand_tab()
        self._build_results_tab()

        status_frame = ttk.Frame(self, padding=(10, 4))
        status_frame.grid(row=2, column=0, sticky="ew")
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

    def _build_menu(self) -> None:
        menubar = tk.Menu(self)
        file_menu = tk.Menu(menubar, tearoff=False)
        file_menu.add_command(label="Create new project", accelerator="Ctrl+N", command=self.new_project)
        file_menu.add_command(label="Save project", accelerator="Ctrl+S", command=self.save_project)
        file_menu.add_command(label="Save project as...", accelerator="Ctrl+Shift+S", command=self.save_project_as)
        file_menu.add_command(label="Open project...", accelerator="Ctrl+O", command=self.open_project_from)
        self.recent_menu = tk.Menu(file_menu, tearoff=False)
        file_menu.add_cascade(label="Open recent project", menu=self.recent_menu)
        file_menu.add_command(label="Run analysis", accelerator="Ctrl+R", command=self.run_analysis)
        file_menu.add_separator()
        file_menu.add_command(label="Close project", accelerator="Ctrl+W", command=self.close_project)
        file_menu.add_command(label="Exit", accelerator="Ctrl+Q", command=self.destroy)
        menubar.add_cascade(label="File", menu=file_menu)

        view_menu = tk.Menu(menubar, tearoff=False)
        view_menu.add_command(label="PDF report", command=self.generate_pdf_report)
        view_menu.add_command(label="HTML report", command=self.generate_html_report)
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
        self.bind_all("<Control-r>", self._shortcut_run_analysis)
        self.bind_all("<Control-w>", self._shortcut_close_project)
        self.bind_all("<Control-q>", self._shortcut_exit)

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

    def _shortcut_run_analysis(self, _event: tk.Event) -> str:
        self.run_analysis()
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
        self.inputs_tab.columnconfigure(1, weight=1)
        self.inputs_tab.rowconfigure(1, weight=1)

        project_frame = ttk.LabelFrame(self.inputs_tab, text="Project Settings", padding=10)
        project_frame.grid(row=0, column=0, columnspan=2, sticky="ew")
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

        surfaces_frame = ttk.LabelFrame(self.inputs_tab, text="Collection surfaces", padding=10)
        surfaces_frame.grid(row=1, column=0, sticky="nsew", pady=(10, 0), padx=(0, 5))
        surfaces_frame.rowconfigure(0, weight=1)
        surfaces_frame.columnconfigure(0, weight=1)
        self.surface_tree = ttk.Treeview(surfaces_frame, columns=("surface", "area", "runoff"), show="headings", height=12)
        self.surface_tree.heading("surface", text="Surface")
        self.surface_tree.heading("area", text="Area")
        self.surface_tree.heading("runoff", text="Runoff coeff.")
        self.surface_tree.column("surface", width=220)
        self.surface_tree.column("area", width=90, anchor="e")
        self.surface_tree.column("runoff", width=90, anchor="e")
        self.surface_tree.grid(row=0, column=0, sticky="nsew")
        self.surface_tree.bind("<Double-1>", self._edit_surface_from_event)
        self.surface_tree.bind("<Return>", self._edit_selected_surface_from_event)
        surface_buttons = ttk.Frame(surfaces_frame)
        surface_buttons.grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Button(surface_buttons, text="Add collection surface", command=self.add_surface).grid(row=0, column=0, padx=(0, 6))
        ttk.Button(surface_buttons, text="Edit selected surface", command=self.edit_surface).grid(row=0, column=1)

        right_frame = ttk.Frame(self.inputs_tab)
        right_frame.grid(row=1, column=1, sticky="nsew", pady=(10, 0), padx=(5, 0))
        right_frame.columnconfigure(0, weight=1)

        settings_frame = ttk.LabelFrame(right_frame, text="Demand and Analysis Settings", padding=10)
        settings_frame.grid(row=0, column=0, sticky="ew")
        settings_frame.columnconfigure(1, weight=1)

        self._labeled_entry(settings_frame, 0, "Simple daily demand", self.simple_daily_var, self.simple_daily_unit_var)
        self._labeled_entry(settings_frame, 1, "Average flushes", self.flushes_var, self.flush_count_unit_var)
        self._labeled_entry(settings_frame, 2, "Toilet volume", self.toilet_flush_var, self.flush_volume_unit_var)
        self._labeled_entry(settings_frame, 3, "Urinal volume", self.urinal_flush_var, self.flush_volume_unit_var)
        ttk.Separator(settings_frame).grid(row=4, column=0, columnspan=3, sticky="ew", pady=8)
        self._labeled_entry(settings_frame, 5, "Graph start tank size", self.graph_start_var, self.tank_size_unit_var)
        self._labeled_entry(settings_frame, 6, "Graph end tank size", self.graph_end_var, self.tank_size_unit_var)
        self._labeled_entry(settings_frame, 7, "Graph step", self.graph_step_var, self.tank_size_unit_var)
        ttk.Button(settings_frame, text="Auto", command=self.auto_set_graph_step).grid(row=7, column=3, sticky="w", padx=(8, 0), pady=2)
        self._labeled_entry(settings_frame, 8, "Selected tank size", self.selected_tank_var, self.tank_size_unit_var)
        ttk.Label(
            settings_frame,
            textvariable=self.selected_tank_warning_var,
            style="Invalid.TLabel",
        ).grid(row=8, column=3, sticky="w", padx=(8, 0), pady=2)
        self._labeled_entry(settings_frame, 9, "Initial fill", self.initial_fill_var, self.percent_unit_var)
        self._labeled_entry(settings_frame, 10, "Reserve threshold", self.reserve_var, self.reserve_unit_var)

    def _build_import_tab(self) -> None:
        self.import_tab.columnconfigure(0, weight=1)

        csv_frame = ttk.LabelFrame(self.import_tab, text="Rainfall CSV", padding=10)
        csv_frame.grid(row=0, column=0, sticky="ew")
        csv_frame.columnconfigure(0, weight=1)
        ttk.Label(csv_frame, textvariable=self.rainfall_summary_var).grid(row=0, column=0, sticky="w")
        ttk.Button(csv_frame, text="Load Rainfall CSV", command=self.load_rainfall_csv).grid(row=0, column=1, sticky="e", padx=(12, 0))

        self.weather_frame = ttk.LabelFrame(self.import_tab, text="ACIS Weather Import", padding=10)
        self.weather_frame.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        self.weather_frame.columnconfigure(1, weight=1)
        self.weather_location_label = ttk.Label(self.weather_frame, text="State")
        self.weather_location_label.grid(row=0, column=0, sticky="w", pady=2)
        self.state_combo = ttk.Combobox(
            self.weather_frame,
            textvariable=self.weather_state_var,
            values=[STATE_PLACEHOLDER, *STATE_LABELS],
            state="readonly",
        )
        self.state_combo.configure(postcommand=self._bind_state_combo_dropdown)
        self.state_combo.grid(row=0, column=1, sticky="ew", pady=2)
        self.state_combo.bind("<KeyPress>", self._select_state_by_first_letter)
        self._labeled_entry(self.weather_frame, 1, "Historical years", self.weather_years_var)
        self._labeled_entry(self.weather_frame, 2, "Station filter", self.weather_filter_var)
        self.canadian_precip_label = ttk.Label(self.weather_frame, text="Precipitation basis")
        self.canadian_precip_label.grid(row=3, column=0, sticky="w", pady=2)
        self.canadian_precip_combo = ttk.Combobox(
            self.weather_frame,
            textvariable=self.canadian_precip_var,
            values=list(CANADIAN_PRECIPITATION_OPTIONS),
            state="readonly",
        )
        self.canadian_precip_combo.grid(row=3, column=1, sticky="ew", pady=2)
        self.find_stations_button = ttk.Button(self.weather_frame, text="Find Stations", command=self.find_weather_stations)
        self.find_stations_button.grid(row=4, column=0, sticky="w", pady=(8, 2))
        self.station_combo = ttk.Combobox(self.weather_frame, textvariable=self.station_var, state="readonly")
        self.station_combo.configure(postcommand=self._bind_station_combo_dropdown)
        self.station_combo.grid(row=4, column=1, sticky="ew", padx=(8, 0), pady=(8, 2))
        self.station_combo.bind("<KeyPress>", self._select_station_by_typed_prefix)
        self.import_station_button = ttk.Button(
            self.weather_frame,
            text="Import Selected Station",
            command=self.import_selected_weather,
        )
        self.import_station_button.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(4, 0))

    def _build_demand_tab(self) -> None:
        self.demand_tab.columnconfigure(0, weight=1)
        self.demand_tab.rowconfigure(0, weight=1)
        columns = ["month"] + [field for field, _label in DEMAND_FIELDS]
        self.demand_tree = ttk.Treeview(self.demand_tab, columns=columns, show="headings", height=14)
        self.demand_tree.heading("month", text="Month")
        self.demand_tree.column("month", width=80, anchor="w")
        for field, _label in DEMAND_FIELDS:
            self.demand_tree.column(field, width=105, anchor="e")
        self._update_demand_headings()
        self.demand_tree.grid(row=0, column=0, sticky="nsew")
        self.demand_tree.bind("<Double-1>", self._edit_demand_month_from_event)
        scroll_x = ttk.Scrollbar(self.demand_tab, orient="horizontal", command=self.demand_tree.xview)
        scroll_x.grid(row=1, column=0, sticky="ew")
        self.demand_tree.configure(xscrollcommand=scroll_x.set)
        ttk.Button(self.demand_tab, text="Edit Selected Month", command=self.edit_demand_month).grid(row=2, column=0, sticky="w", pady=(8, 0))

    def _build_results_tab(self) -> None:
        self.results_tab.columnconfigure(0, weight=1)
        self.results_tab.columnconfigure(1, weight=1)
        self.results_tab.columnconfigure(2, weight=1)
        self.results_tab.rowconfigure(1, weight=1)
        self.results_tab.rowconfigure(2, weight=1)

        ttk.Label(self.results_tab, textvariable=self.reliability_var, font=("Segoe UI", 12, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Checkbutton(
            self.results_tab,
            text="Show tank chart points",
            variable=self.show_tank_points_var,
            command=self._draw_tank_chart,
        ).grid(row=0, column=1, columnspan=2, sticky="e")
        self.curve_canvas = tk.Canvas(self.results_tab, height=230, bg="white", highlightthickness=1, highlightbackground="#b7b7b7")
        self.curve_canvas.grid(row=1, column=0, sticky="nsew", pady=(8, 8), padx=(0, 5))
        self.tank_canvas = tk.Canvas(self.results_tab, height=230, bg="white", highlightthickness=1, highlightbackground="#b7b7b7")
        self.tank_canvas.grid(row=1, column=1, sticky="nsew", pady=(8, 8), padx=5)
        self.histogram_canvas = tk.Canvas(
            self.results_tab,
            height=230,
            bg="white",
            highlightthickness=1,
            highlightbackground="#b7b7b7",
        )
        self.histogram_canvas.grid(row=1, column=2, sticky="nsew", pady=(8, 8), padx=(5, 0))
        self.curve_canvas.bind("<Configure>", self._schedule_results_chart_redraw)
        self.tank_canvas.bind("<Configure>", self._schedule_results_chart_redraw)
        self.histogram_canvas.bind("<Configure>", self._schedule_results_chart_redraw)

        columns = ("date", "precip", "collected", "demand", "unmet", "tank")
        self.results_tree = ttk.Treeview(self.results_tab, columns=columns, show="headings", height=12)
        headings = {
            "date": "Date",
            "precip": "Precip.",
            "collected": "Collected",
            "demand": "Demand",
            "unmet": "Unmet",
            "tank": "Water in Tank",
        }
        for col, heading in headings.items():
            self.results_tree.heading(col, text=heading)
            self.results_tree.column(col, width=120, anchor="e" if col != "date" else "w")
        self.results_tree.grid(row=2, column=0, columnspan=3, sticky="nsew")
        results_scroll_y = ttk.Scrollbar(self.results_tab, orient="vertical", command=self.results_tree.yview)
        results_scroll_y.grid(row=2, column=3, sticky="ns")
        results_scroll_x = ttk.Scrollbar(self.results_tab, orient="horizontal", command=self.results_tree.xview)
        results_scroll_x.grid(row=3, column=0, columnspan=3, sticky="ew")
        self.results_tree.configure(yscrollcommand=results_scroll_y.set, xscrollcommand=results_scroll_x.set)

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

    def _select_station_by_char(self, char: str, listbox: tk.Listbox | None = None) -> str | None:
        key = char.casefold()
        if len(key) != 1 or not key.isalnum():
            return None

        if self.station_typeahead_after_id is not None:
            self.after_cancel(self.station_typeahead_after_id)

        self.station_typeahead += key
        if not self._select_station_by_prefix(self.station_typeahead, listbox):
            self.station_typeahead = key
            self._select_station_by_prefix(self.station_typeahead, listbox)

        self.station_typeahead_after_id = self.after(1000, self._reset_station_typeahead)
        return "break"

    def _select_station_by_prefix(self, prefix: str, listbox: tk.Listbox | None = None) -> bool:
        labels = list(self.station_combo["values"])
        for index, label in enumerate(labels):
            if str(label).casefold().startswith(prefix):
                self.station_combo.current(index)
                if listbox is not None:
                    listbox.selection_clear(0, tk.END)
                    listbox.selection_set(index)
                    listbox.activate(index)
                    listbox.see(index)
                return True
        return False

    def _reset_station_typeahead(self) -> None:
        self.station_typeahead = ""
        self.station_typeahead_after_id = None

    def _bind_station_combo_dropdown(self) -> None:
        self.after_idle(self._bind_station_combo_listbox)

    def _bind_station_combo_listbox(self) -> None:
        try:
            popdown = self.tk.eval(f"ttk::combobox::PopdownWindow {self.station_combo}")
            listbox = self.nametowidget(f"{popdown}.f.l")
        except (KeyError, tk.TclError):
            return
        listbox.bind("<KeyPress>", lambda event: self._select_station_by_char(str(event.char), listbox))

    def _load_project_list(self) -> None:
        projects = self.store.list_projects()
        self.project_combo["values"] = projects
        if self.saved_project_var.get() not in projects:
            self.saved_project_var.set("")
        if projects and not self.saved_project_var.get():
            self.saved_project_var.set(projects[0])

    def _populate_from_model(self) -> None:
        cfg = self.config_model
        self.project_name_var.set(cfg.name)
        self.unit_var.set(cfg.unit_system)
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
        self.flushes_var.set(f"{cfg.demand.avg_flush_per_person:.2f}")
        self.toilet_flush_var.set(f"{volume_to_display(cfg.demand.gallons_per_flush_toilet, cfg):.2f}")
        self.urinal_flush_var.set(f"{volume_to_display(cfg.demand.gallons_per_flush_urinal, cfg):.2f}")
        self.graph_start_var.set(f"{volume_to_display(cfg.graph_start_gal, cfg):.0f}")
        self.graph_end_var.set(f"{volume_to_display(cfg.graph_end_gal, cfg):.0f}")
        self.graph_step_var.set(f"{volume_to_display(cfg.graph_step_gal, cfg):.0f}")
        self.selected_tank_var.set(f"{volume_to_display(cfg.selected_tank_size_gal, cfg):.0f}")
        self.initial_fill_var.set(f"{cfg.tank_parameters.initial_fill_percent:.0f}")
        self.reserve_var.set(f"{cfg.tank_parameters.reliable_fill_percent:.0f}")
        self._update_setting_unit_labels()
        self._populate_surfaces()
        self._populate_demand()
        self._update_rainfall_summary()

    def _update_setting_unit_labels(self) -> None:
        unit = volume_unit(self.config_model)
        self.simple_daily_unit_var.set(f"{unit}/day")
        self.flush_volume_unit_var.set(f"{unit}/flush")
        self.tank_size_unit_var.set(unit)

    def _apply_form_to_model(self) -> bool:
        cfg = self.config_model
        cfg.name = self.project_name_var.get().strip() or "Unnamed Project"
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
        cfg.demand.avg_flush_per_person = _float(self.flushes_var.get())
        cfg.demand.gallons_per_flush_toilet = volume_to_internal(_float(self.toilet_flush_var.get()), cfg)
        cfg.demand.gallons_per_flush_urinal = volume_to_internal(_float(self.urinal_flush_var.get()), cfg)
        cfg.graph_start_gal = max(1, int(round(volume_to_internal(_float(self.graph_start_var.get(), 500), cfg))))
        cfg.graph_end_gal = max(2, int(round(volume_to_internal(_float(self.graph_end_var.get(), 20000), cfg))))
        cfg.graph_step_gal = max(1, int(round(volume_to_internal(_float(self.graph_step_var.get(), 500), cfg))))
        cfg.selected_tank_size_gal = max(0.0, volume_to_internal(_float(self.selected_tank_var.get(), 5000), cfg))
        cfg.tank_parameters.initial_fill_percent = min(max(_float(self.initial_fill_var.get(), 50), 0), 100)
        cfg.tank_parameters.reliable_fill_percent = min(max(_float(self.reserve_var.get(), 25), 0), 100)
        return True

    def _populate_surfaces(self) -> None:
        self.surface_tree.heading("area", text=f"Area ({area_unit(self.config_model)})")
        self.surface_tree.delete(*self.surface_tree.get_children())
        for i, surface in enumerate(self.config_model.surfaces):
            self.surface_tree.insert(
                "",
                "end",
                iid=str(i),
                values=(surface.name, f"{area_to_display(surface.area, self.config_model):.2f}", f"{surface.runoff_coefficient:.3f}"),
            )

    def _populate_demand(self) -> None:
        self._update_demand_headings()
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

    def _update_demand_headings(self) -> None:
        unit = volume_unit(self.config_model)
        for field, label in DEMAND_FIELDS:
            if field in {"male_occupancy", "female_occupancy"}:
                heading = f"{label} (people/day)"
            else:
                heading = f"{label} ({unit}/month)"
            self.demand_tree.heading(field, text=heading)

    def _update_rainfall_summary(self) -> None:
        if self.rainfall_df.empty:
            self.rainfall_summary_var.set("No rainfall file loaded")
            return
        start = pd.Timestamp(self.rainfall_df["Date"].min()).strftime("%Y-%m-%d")
        end = pd.Timestamp(self.rainfall_df["Date"].max()).strftime("%Y-%m-%d")
        source = f" from {self.rainfall_source_label}" if self.rainfall_source_label else ""
        self.rainfall_summary_var.set(f"{len(self.rainfall_df):,} rainfall rows loaded ({start} to {end}){source}")

    def _change_units(self) -> None:
        self.config_model.unit_system = self.unit_var.get()
        self._populate_from_model()

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
            self.weather_location_label.configure(text="State")
            self.state_combo.configure(values=[STATE_PLACEHOLDER, *STATE_LABELS], state="readonly")
            self.canadian_precip_label.grid()
            self.canadian_precip_combo.grid()
            enabled = True
        elif country == "CAN":
            self.weather_frame.configure(text="ECCC Canadian Climate Import")
            self.weather_location_label.configure(text="Province / territory")
            self.state_combo.configure(values=[PROVINCE_PLACEHOLDER, *PROVINCE_LABELS], state="readonly")
            self.canadian_precip_label.grid()
            self.canadian_precip_combo.grid()
            enabled = True
        else:
            self.weather_frame.configure(text="Weather Import")
            self.weather_location_label.configure(text="Region")
            self.state_combo.configure(values=["-- Weather import unavailable --"], state="disabled")
            self.weather_state_var.set("-- Weather import unavailable --")
            self.canadian_precip_label.grid_remove()
            self.canadian_precip_combo.grid_remove()
            enabled = False
        self.station_combo.configure(state="readonly" if enabled else "disabled")
        self.find_stations_button.configure(state="normal" if enabled else "disabled")
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

        step_gal = (end_gal - start_gal) / (GRAPH_AUTO_STEP_COUNT - 1)
        step_display = max(1.0, volume_to_display(step_gal, cfg))
        self.graph_step_var.set(f"{step_display:.0f}")
        self.status_var.set(f"Auto-set graph step to {step_display:.0f} {volume_unit(cfg)} for {GRAPH_AUTO_STEP_COUNT} graph points")

    def new_project(self) -> None:
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
        name = self.saved_project_var.get()
        if not name:
            messagebox.showinfo(APP_TITLE, "Select a saved project first.")
            return
        try:
            self.config_model, self.rainfall_df, self.curve_df, self.results_df = self.store.load_project_with_analysis(name)
            self.rainfall_source_label = self.config_model.rainfall_source_label
            self._clear_results()
            self._populate_from_model()
            self._reset_weather_selection()
            self._set_active_project(self.config_model.name)
            self._add_recent_project_path(self.project_file_path)
            if not self.results_df.empty and not self.curve_df.empty:
                reliability = float(self.results_df["ReliabilityPercent"].iloc[0])
                self.reliability_var.set(f"Reliability for selected tank: {reliability:.2f}%")
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
            initialdir=str(self.project_file_path.parent),
            filetypes=[("Rainwater project files", "*.db"), ("SQLite database files", "*.sqlite *.sqlite3"), ("All files", "*.*")],
        )
        if not path:
            return
        self._open_project_file(Path(path))

    def open_recent_project(self, path_text: str) -> None:
        self._open_project_file(Path(path_text))

    def clear_recent_projects(self) -> None:
        self.recent_project_paths = []
        self._save_recent_project_paths()
        self._refresh_recent_projects_menu()
        self.status_var.set("Cleared recent projects")

    def _open_project_file(self, selected_path: Path) -> None:
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
        self.config_model.name = name
        self.project_name_var.set(name)
        self._save_current_project()

    def _save_current_project(self) -> None:
        self.config_model.rainfall_source_label = self.rainfall_source_label
        try:
            self.store.save_project(self.config_model, self.rainfall_df, self.curve_df, self.results_df)
            self._load_project_list()
            self.saved_project_var.set(self.config_model.name)
            self._set_active_project(self.config_model.name)
            self._add_recent_project_path(self.project_file_path)
            self.status_var.set(f"Saved project '{self.config_model.name}' to {self.project_file_path}")
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(APP_TITLE, f"Could not save project:\n{exc}")

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
        state = _state_code(selected_state)
        query = self.weather_filter_var.get().strip().casefold()
        try:
            start_date, end_date = default_complete_calendar_range(years)
            stations = fetch_station_options(state, start_date, end_date)
            if query:
                stations = [
                    station
                    for station in stations
                    if query in station["name"].casefold() or query in station["sid"].casefold()
                ]
            self.station_options = stations
            labels = [self._station_label(station) for station in stations]
            self.station_combo["values"] = labels
            self.station_var.set(labels[0] if labels else "")
            self._reset_station_typeahead()
            self.status_var.set(f"Found {len(stations)} ACIS station(s)")
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(APP_TITLE, f"Could not fetch ACIS stations:\n{exc}")

    def find_weather_stations(self) -> None:
        country = self._selected_country_code()
        if country == "USA":
            self.find_acis_stations()
        elif country == "CAN":
            self.find_eccc_stations()

    def find_eccc_stations(self) -> None:
        years = max(30, int(_float(self.weather_years_var.get(), 30)))
        selected_province = self.weather_state_var.get()
        if selected_province == PROVINCE_PLACEHOLDER:
            messagebox.showwarning(APP_TITLE, "Select a province or territory before finding ECCC stations.")
            return
        province = _state_code(selected_province)
        query = self.weather_filter_var.get().strip().casefold()
        try:
            self.status_var.set("Finding ECCC climate stations...")
            self.update_idletasks()
            start_date, end_date = default_complete_calendar_range(years)
            stations = fetch_canadian_station_options(province, start_date, end_date)
            if query:
                stations = [
                    station
                    for station in stations
                    if query in station["name"].casefold() or query in station["sid"].casefold()
                ]
            self.station_options = stations
            labels = [self._station_label(station) for station in stations]
            self.station_combo["values"] = labels
            self.station_var.set(labels[0] if labels else "")
            self._reset_station_typeahead()
            self.status_var.set(f"Found {len(stations)} ECCC climate station(s)")
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(APP_TITLE, f"Could not fetch ECCC climate stations:\n{exc}")

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
            self.rainfall_source_label = f"{station['name']} ({station['sid']}) via ACIS, {basis_label}"
            self.config_model.rainfall_source_label = self.rainfall_source_label
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
            self.rainfall_source_label = f"{station['name']} ({station['sid']}) via ECCC, {basis_label}"
            self.config_model.rainfall_source_label = self.rainfall_source_label
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

    def _edit_demand_month_from_event(self, event: tk.Event) -> str:
        row_id = self.demand_tree.identify_row(event.y)
        if row_id:
            self.demand_tree.selection_set(row_id)
            self.demand_tree.focus(row_id)
            self.edit_demand_month()
        return "break"

    def run_analysis(self) -> None:
        self._apply_form_to_model()
        cfg = self.config_model
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
        try:
            tank_sizes = list(range(cfg.graph_start_gal, cfg.graph_end_gal + 1, cfg.graph_step_gal))
            total_parts = 2
            self.analysis_progress.configure(style="Analysis.Horizontal.TProgressbar")
            self.analysis_progress_var.set(0)
            self.status_var.set("Analysis running: Part A - reliability curve")
            self.update_idletasks()

            def update_curve_progress(index: int, total: int, _tank_size: float) -> None:
                part_progress = index / total if total else 1.0
                self.analysis_progress_var.set((part_progress / total_parts) * 100)
                self.status_var.set(f"Analysis running: Part A - reliability curve ({index}/{total})")
                self.update_idletasks()

            self.curve_df = reliability_curve(cfg, self.rainfall_df, tank_sizes, progress_callback=update_curve_progress)
            self.analysis_progress_var.set(50)
            self.status_var.set("Analysis running: Part B - selected tank simulation")
            self.update_idletasks()
            self.results_df = simulate_tank(cfg, self.rainfall_df, cfg.selected_tank_size_gal)
            self.analysis_progress_var.set(75)
            self.status_var.set("Analysis running: Part B - drawing results")
            self.update_idletasks()
            reliability = float(self.results_df["ReliabilityPercent"].iloc[0]) if not self.results_df.empty else 0.0
            self.reliability_var.set(f"Reliability for selected tank: {reliability:.2f}%")
            self._populate_results()
            self._draw_saved_analysis_charts()
            self.analysis_progress_var.set(100)
            self.status_var.set("Analysis complete")
        except Exception as exc:  # noqa: BLE001
            self.analysis_progress_var.set(0)
            self.status_var.set("Analysis failed")
            messagebox.showerror(APP_TITLE, f"Analysis failed:\n{exc}")

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

    def generate_pdf_report(self) -> None:
        self._apply_form_to_model()
        if self.curve_df.empty:
            messagebox.showinfo(APP_TITLE, "Run the analysis before generating a PDF report.")
            return

        dialog = ReportDialog(self, self._default_report_metadata())
        self.wait_window(dialog)
        if dialog.result is None:
            return

        path = filedialog.asksaveasfilename(
            title="Save PDF report",
            initialfile=_safe_project_file_name(self.config_model.name).replace(".db", "_report.pdf"),
            defaultextension=".pdf",
            filetypes=[("PDF files", "*.pdf")],
        )
        if not path:
            return

        pdf_path = Path(path)
        tex_path = pdf_path.with_suffix(".tex")
        try:
            report = self._build_report_content(dialog.result)
            latex = self._build_report_latex(report)
            tex_path.write_text(latex, encoding="utf-8")
            self._compile_latex_report(tex_path, pdf_path, report)
            self.status_var.set(f"Generated PDF report: {pdf_path.name}")
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(APP_TITLE, f"Could not generate PDF report:\n{exc}")

    def generate_html_report(self) -> None:
        self._apply_form_to_model()
        if self.curve_df.empty:
            messagebox.showinfo(APP_TITLE, "Run the analysis before generating an HTML report.")
            return

        dialog = ReportDialog(self, self._default_report_metadata())
        self.wait_window(dialog)
        if dialog.result is None:
            return

        path = filedialog.asksaveasfilename(
            title="Save HTML report",
            initialfile=_safe_project_file_name(self.config_model.name).replace(".db", "_report.html"),
            defaultextension=".html",
            filetypes=[("HTML files", "*.html;*.htm")],
        )
        if not path:
            return

        html_path = Path(path)
        try:
            report = self._build_report_content(dialog.result)
            html_path.write_text(self._build_report_html(report), encoding="utf-8")
            self.status_var.set(f"Generated HTML report: {html_path.name}")
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(APP_TITLE, f"Could not generate HTML report:\n{exc}")

    def _default_report_metadata(self) -> dict[str, str]:
        end_uses = self._default_end_uses_text()
        location = self.rainfall_source_label or self.config_model.rainfall_source_label or ""
        return {
            "client_name": "",
            "date": dt.date.today().isoformat(),
            "location": location,
            "project_name": self.project_name_var.get().strip() or self.config_model.name,
            "end_uses": end_uses,
        }

    def _default_end_uses_text(self) -> str:
        uses: list[str] = []
        if _float(self.simple_daily_var.get()) > 0:
            uses.append("Simple daily demand")
        if _float(self.flushes_var.get()) > 0 and (_float(self.toilet_flush_var.get()) > 0 or _float(self.urinal_flush_var.get()) > 0):
            uses.append("Toilet and urinal flushing")
        for field, label in DEMAND_FIELDS:
            if field in {"male_occupancy", "female_occupancy"}:
                continue
            monthly_values = getattr(self.config_model.demand, field)
            if any(float(value) > 0 for value in monthly_values.values()):
                uses.append(label)
        return ", ".join(dict.fromkeys(uses)) or "Not specified"

    def _build_report_content(self, metadata: dict[str, str]) -> dict[str, object]:
        cfg = self.config_model
        selected_reliability: float | None = None
        if not self.results_df.empty and "ReliabilityPercent" in self.results_df:
            selected_reliability = float(self.results_df["ReliabilityPercent"].iloc[0])
        return {
            "metadata": dict(metadata),
            "area_unit": area_unit(cfg),
            "volume_unit": volume_unit(cfg),
            "surfaces": [
                {
                    "name": surface.name,
                    "area": area_to_display(surface.area, cfg),
                    "runoff_coefficient": surface.runoff_coefficient,
                }
                for surface in cfg.surfaces
            ],
            "curve": [
                {
                    "tank_size": volume_to_display(row.TankSizeGallons, cfg),
                    "reliability": float(row.ReliabilityPercent),
                }
                for row in self.curve_df.itertuples(index=False)
            ],
            "selected_reliability": selected_reliability,
        }

    def _build_report_latex(self, report: dict[str, object]) -> str:
        metadata = report["metadata"]
        area = report["area_unit"]
        volume = report["volume_unit"]
        surface_rows = "\n".join(
            _latex_row(
                surface["name"],
                f"{surface['area']:,.2f}",
                f"{surface['runoff_coefficient']:.3f}",
            )
            for surface in report["surfaces"]
        )
        if not surface_rows:
            surface_rows = _latex_row("No collection surfaces", "0.00", "0.000")

        coordinates = "\n".join(
            f"({_latex_number(point['tank_size'])},{_latex_number(point['reliability'])})"
            for point in report["curve"]
        )
        selected_reliability = "--"
        if report["selected_reliability"] is not None:
            selected_reliability = f"{report['selected_reliability']:.2f}\\%"

        return rf"""\documentclass[11pt]{{article}}
\usepackage[margin=0.75in]{{geometry}}
\usepackage{{booktabs}}
\usepackage{{pgfplots}}
\usepackage{{longtable}}
\usepackage{{array}}
\pgfplotsset{{compat=1.18}}

\title{{RWH Calculator Report}}
\date{{}}

\begin{{document}}
\maketitle

\section*{{Project Information}}
\begin{{tabular}}{{@{{}}p{{1.6in}}p{{4.8in}}@{{}}}}
\textbf{{Client name}} & {_latex_escape(metadata["client_name"])} \\
\textbf{{Date}} & {_latex_escape(metadata["date"])} \\
\textbf{{Location}} & {_latex_escape(metadata["location"])} \\
\textbf{{Project name}} & {_latex_escape(metadata["project_name"])} \\
\textbf{{End-uses of water}} & {_latex_escape(metadata["end_uses"])} \\
\textbf{{Selected tank reliability}} & {selected_reliability} \\
\end{{tabular}}

\section*{{Surface Area Summary}}
\begin{{longtable}}{{@{{}}p{{2.8in}}rr@{{}}}}
\toprule
Surface & Area ({_latex_escape(area)}) & Runoff coefficient \\
\midrule
{surface_rows}
\bottomrule
\end{{longtable}}

\section*{{Reliability Curve}}
\begin{{center}}
\begin{{tikzpicture}}
\begin{{axis}}[
    width=6.6in,
    height=3.8in,
    xlabel={{Tank size ({_latex_escape(volume)})}},
    ylabel={{Reliability (\%)}},
    ymin=0,
    ymax=100,
    grid=major,
    mark=*,
]
\addplot+[blue, thick] coordinates {{
{coordinates}
}};
\end{{axis}}
\end{{tikzpicture}}
\end{{center}}

\end{{document}}
"""

    def _build_report_html(self, report: dict[str, object]) -> str:
        metadata = report["metadata"]
        surfaces = report["surfaces"]
        curve = report["curve"]
        escape = lambda value: html.escape(str(value), quote=True)
        surface_rows = "".join(
            f"<tr><td>{escape(surface['name'])}</td><td>{surface['area']:,.2f}</td>"
            f"<td>{surface['runoff_coefficient']:.3f}</td></tr>"
            for surface in surfaces
        ) or '<tr><td>No collection surfaces</td><td>0.00</td><td>0.000</td></tr>'

        chart_width, chart_height = 900.0, 420.0
        left, right, top, bottom = 72.0, 24.0, 28.0, 62.0
        plot_width = chart_width - left - right
        plot_height = chart_height - top - bottom
        x_values = [float(point["tank_size"]) for point in curve]
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
        info_rows = "".join(
            f'<div class="fact"><dt>{escape(label)}</dt><dd>{escape(value or "Not specified")}</dd></div>'
            for label, value in [
                ("Client name", metadata["client_name"]),
                ("Date", metadata["date"]),
                ("Location", metadata["location"]),
                ("Project name", metadata["project_name"]),
                ("End-uses of water", metadata["end_uses"]),
                ("Selected tank reliability", selected_text),
            ]
        )
        return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(metadata['project_name'])} - RWH Calculator Report</title>
<style>
:root {{ color-scheme: light; --ink:#17242b; --muted:#64747c; --line:#dce5e8; --green:#18795b; --blue:#176b9c; --paper:#fff; --wash:#f2f6f5; }}
* {{ box-sizing:border-box; }} body {{ margin:0; background:var(--wash); color:var(--ink); font:15px/1.55 Arial,Helvetica,sans-serif; }}
main {{ width:min(1040px,calc(100% - 32px)); margin:32px auto; background:var(--paper); box-shadow:0 12px 36px rgba(23,36,43,.10); }}
header {{ padding:44px 52px 38px; border-top:6px solid var(--green); border-bottom:1px solid var(--line); }}
.eyebrow {{ color:var(--green); font-size:12px; font-weight:700; text-transform:uppercase; letter-spacing:.1em; }}
h1 {{ margin:8px 0 4px; font-size:34px; line-height:1.15; }} header p {{ margin:0; color:var(--muted); }}
section {{ padding:34px 52px; border-bottom:1px solid var(--line); }} h2 {{ margin:0 0 20px; font-size:20px; }}
dl {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:0 40px; margin:0; }}
.fact {{ padding:11px 0; border-bottom:1px solid var(--line); }} dt {{ color:var(--muted); font-size:12px; font-weight:700; text-transform:uppercase; }} dd {{ margin:3px 0 0; }}
table {{ width:100%; border-collapse:collapse; }} th {{ color:var(--muted); font-size:12px; text-align:left; text-transform:uppercase; }} th,td {{ padding:11px 12px; border-bottom:1px solid var(--line); }} th:nth-child(n+2),td:nth-child(n+2) {{ text-align:right; }}
.chart {{ overflow-x:auto; }} svg {{ display:block; width:100%; min-width:620px; height:auto; }} .grid line {{ stroke:#dce5e8; }} .grid text {{ fill:#64747c; font-size:12px; }}
.curve {{ fill:none; stroke:var(--blue); stroke-width:3; }} circle {{ fill:var(--paper); stroke:var(--blue); stroke-width:3; }} circle:hover {{ fill:var(--blue); r:6; }}
.axis-label {{ fill:var(--muted); font-size:13px; font-weight:700; }} footer {{ padding:20px 52px; color:var(--muted); font-size:12px; }}
@media (max-width:700px) {{ main {{ width:100%; margin:0; }} header,section {{ padding:28px 22px; }} dl {{ grid-template-columns:1fr; }} h1 {{ font-size:28px; }} }}
@media print {{ body {{ background:#fff; }} main {{ width:100%; margin:0; box-shadow:none; }} section {{ break-inside:avoid; }} }}
</style></head><body><main>
<header><div class="eyebrow">Rainwater harvesting analysis</div><h1>{escape(metadata['project_name'])}</h1><p>RWH Calculator Report</p></header>
<section><h2>Project information</h2><dl>{info_rows}</dl></section>
<section><h2>Surface area summary</h2><table><thead><tr><th>Surface</th><th>Area ({escape(report['area_unit'])})</th><th>Runoff coefficient</th></tr></thead><tbody>{surface_rows}</tbody></table></section>
<section><h2>Reliability curve</h2><div class="chart"><svg viewBox="0 0 {chart_width:.0f} {chart_height:.0f}" role="img" aria-label="Reliability versus tank size chart">
<g class="grid">{y_grid}{x_ticks}</g><polyline class="curve" points="{polyline}"/>{circles}
<text class="axis-label" x="{left + plot_width / 2:.2f}" y="{chart_height - 10:.2f}" text-anchor="middle">Tank size ({escape(report['volume_unit'])})</text>
<text class="axis-label" transform="translate(18 {top + plot_height / 2:.2f}) rotate(-90)" text-anchor="middle">Reliability (%)</text>
</svg></div></section><footer>Generated by RWH Calculator on {escape(dt.date.today().isoformat())}</footer>
</main></body></html>"""

    def _compile_latex_report(self, tex_path: Path, pdf_path: Path, report: dict[str, object]) -> None:
        pdflatex = shutil.which("pdflatex")
        if pdflatex is None:
            self._write_fallback_pdf_report(pdf_path, report)
            return

        with tempfile.TemporaryDirectory() as temp_dir:
            work_dir = Path(temp_dir)
            work_tex = work_dir / tex_path.name
            work_tex.write_text(tex_path.read_text(encoding="utf-8"), encoding="utf-8")
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
        surface_rows = [
            (
                surface["name"],
                f"{surface['area']:,.2f}",
                f"{surface['runoff_coefficient']:.3f}",
            )
            for surface in report["surfaces"]
        ]
        if not surface_rows:
            surface_rows = [("No collection surfaces", "0.00", "0.000")]

        selected_reliability = "--"
        if report["selected_reliability"] is not None:
            selected_reliability = f"{report['selected_reliability']:.2f}%"

        pages: list[list[str]] = [[]]
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
            y -= 10
            text(54, y, value, size=14, bold=True)
            y -= 18
            line(54, y + 8, 558, y + 8)

        text(54, y, "RWH Calculator Report", size=20, bold=True)
        y -= 34
        heading("Project Information")
        for label, value in [
            ("Client name", metadata["client_name"]),
            ("Date", metadata["date"]),
            ("Location", metadata["location"]),
            ("Project name", metadata["project_name"]),
            ("End-uses of water", metadata["end_uses"]),
            ("Selected tank reliability", selected_reliability),
        ]:
            if y < 84:
                add_page()
            text(54, y, f"{label}:", size=10, bold=True)
            add_wrapped(value or "Not specified", x=190, size=10, width=58)
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

        heading("Reliability Curve")
        self._draw_pdf_reliability_curve(page(), 78, max(120, y - 280), 456, 250, report)

        self._write_pdf_with_pypdf(pdf_path, pages)

    def _draw_pdf_reliability_curve(
        self, commands: list[str], x: float, y: float, width: float, height: float, report: dict[str, object]
    ) -> None:
        curve = report["curve"]
        if not curve:
            return
        values = [(float(point["tank_size"]), float(point["reliability"])) for point in curve]
        x_min = min(v[0] for v in values)
        x_max = max(v[0] for v in values)
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
        commands.append(f"BT /F1 9 Tf 1 0 0 1 {x + width / 2 - 44:.2f} {y - 36:.2f} Tm (Tank size ({_pdf_escape(report['volume_unit'])})) Tj ET")
        commands.append(f"BT /F1 9 Tf 1 0 0 1 {x - 42:.2f} {y + height / 2:.2f} Tm (Reliability %) Tj ET")
        points = [(sx(tank), sy(reliability)) for tank, reliability in values]
        if len(points) >= 2:
            path = [f"{points[0][0]:.2f} {points[0][1]:.2f} m"]
            path.extend(f"{px:.2f} {py:.2f} l" for px, py in points[1:])
            commands.append("0.04 0.36 0.67 RG 1.50 w " + " ".join(path) + " S")
        commands.append("0.04 0.36 0.67 rg")
        for px, py in points:
            commands.append(f"{px - 1.5:.2f} {py - 1.5:.2f} {3:.2f} {3:.2f} re f")
        commands.append("0 0 0 rg 0 0 0 RG")

    def _write_pdf_with_pypdf(self, pdf_path: Path, pages: list[list[str]]) -> None:
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

        with pdf_path.open("wb") as handle:
            writer.write(handle)

    def _display_results_df(self) -> pd.DataFrame:
        cfg = self.config_model
        out = self.results_df.copy()
        out["Precipitation"] = out["Precipitation"].map(lambda v: precip_to_display(float(v), cfg))
        for col in ["CollectedGallons", "DemandGallons", "UnmetDemandGallons", "WaterInTankGallons"]:
            out[col] = out[col].map(lambda v: volume_to_display(float(v), cfg))
        return out.rename(
            columns={
                "Precipitation": f"Precipitation ({precip_unit(cfg)})",
                "CollectedGallons": f"Collected ({volume_unit(cfg)})",
                "DemandGallons": f"Demand ({volume_unit(cfg)}/day)",
                "UnmetDemandGallons": f"Unmet Demand ({volume_unit(cfg)}/day)",
                "WaterInTankGallons": f"Water in Tank ({volume_unit(cfg)})",
                "ReliabilityPercent": "Reliability (%)",
            }
        )

    @staticmethod
    def _station_label(station: dict) -> str:
        location = ""
        if station.get("latitude") is not None and station.get("longitude") is not None:
            location = f" ({station['latitude']:.3f}, {station['longitude']:.3f})"
        return f"{station['name']} - {station['sid']}{location}"

    def _populate_results(self) -> None:
        self.results_tree.heading("precip", text=f"Precip. ({precip_unit(self.config_model)})")
        self.results_tree.heading("collected", text=f"Collected ({volume_unit(self.config_model)})")
        self.results_tree.heading("demand", text=f"Demand ({volume_unit(self.config_model)})")
        self.results_tree.heading("unmet", text=f"Unmet ({volume_unit(self.config_model)})")
        self.results_tree.heading("tank", text=f"Water in Tank ({volume_unit(self.config_model)})")
        self.results_tree.delete(*self.results_tree.get_children())
        display = self._display_results_df().head(500)
        for _, row in display.iterrows():
            self.results_tree.insert(
                "",
                "end",
                values=(
                    pd.Timestamp(row["Date"]).strftime("%Y-%m-%d"),
                    f"{row[f'Precipitation ({precip_unit(self.config_model)})']:.3f}",
                    f"{row[f'Collected ({volume_unit(self.config_model)})']:.1f}",
                    f"{row[f'Demand ({volume_unit(self.config_model)}/day)']:.1f}",
                    f"{row[f'Unmet Demand ({volume_unit(self.config_model)}/day)']:.1f}",
                    f"{row[f'Water in Tank ({volume_unit(self.config_model)})']:.1f}",
                ),
            )

    def _clear_results(self) -> None:
        self.results_tree.delete(*self.results_tree.get_children())
        self.curve_canvas.delete("all")
        self.tank_canvas.delete("all")
        self.histogram_canvas.delete("all")
        self.curve_canvas.hover_points = []
        self.tank_canvas.hover_points = []
        self.histogram_canvas.hover_points = []

    def _draw_saved_analysis_charts(self) -> None:
        if not self.results_tab.winfo_ismapped():
            return
        self.update_idletasks()
        self._draw_curve()
        self._draw_tank_chart()
        self._draw_tank_level_histogram()

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
            hover_labels,
        )

    def _draw_tank_chart(self) -> None:
        if self.results_df.empty:
            return
        x = list(range(len(self.results_df)))
        y = [volume_to_display(v, self.config_model) for v in self.results_df["WaterInTankGallons"]]
        hover_labels = [
            f"Date: {pd.Timestamp(date).strftime('%Y-%m-%d')}\nWater in tank: {water:.1f} {volume_unit(self.config_model)}"
            for date, water in zip(self.results_df["Date"], y)
        ]
        self._draw_line_chart(
            self.tank_canvas,
            x,
            y,
            f"Tank Water Over Time ({volume_unit(self.config_model)})",
            volume_unit(self.config_model),
            hover_labels,
            show_points=self.show_tank_points_var.get(),
        )

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
        height = max(canvas.winfo_height(), 220)
        pad_left, pad_right, pad_top, pad_bottom = 48, 14, 32, 48
        plot_width = width - pad_left - pad_right
        plot_height = height - pad_top - pad_bottom
        max_count = max(counts) or 1
        canvas.create_text(width / 2, 16, text=f"Tank Level Distribution ({unit})", font=("Segoe UI", 10, "bold"))

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

    def _draw_line_chart(
        self,
        canvas: tk.Canvas,
        x_values: list[float],
        y_values: list[float],
        title: str,
        y_label: str,
        hover_labels: list[str] | None = None,
        show_points: bool = True,
    ) -> None:
        canvas.delete("all")
        canvas.hover_points = []
        width = max(canvas.winfo_width(), 300)
        height = max(canvas.winfo_height(), 220)
        pad_left, pad_right, pad_top, pad_bottom = 56, 18, 32, 42
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
            canvas.create_line(*points, fill="#0b5cab", width=2)
        if show_points:
            for px, py, _hover_label in canvas.hover_points:
                canvas.create_oval(px - 2, py - 2, px + 2, py + 2, fill="#0b5cab", outline="")
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
        text_x = min(max(px + 12, 72), max(canvas.winfo_width() - 96, 72))
        text_y = max(py - 30, 24)
        text_id = canvas.create_text(text_x, text_y, text=label, anchor="nw", font=("Segoe UI", 8), tags="hover")
        bbox = canvas.bbox(text_id)
        if bbox is None:
            return
        pad = 5
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
        self.runoff_var = tk.StringVar(value=f"{surface.runoff_coefficient:.3f}")
        body = ttk.Frame(self, padding=12)
        body.grid(sticky="nsew")
        ttk.Label(body, text="Surface").grid(row=0, column=0, sticky="w", pady=3)
        ttk.Entry(body, textvariable=self.name_var, width=36).grid(row=0, column=1, pady=3)
        ttk.Label(body, text=f"Area ({area_unit(config)})").grid(row=1, column=0, sticky="w", pady=3)
        ttk.Entry(body, textvariable=self.area_var, width=18).grid(row=1, column=1, sticky="w", pady=3)
        ttk.Label(body, text="Runoff coefficient").grid(row=2, column=0, sticky="w", pady=3)
        ttk.Entry(body, textvariable=self.runoff_var, width=18).grid(row=2, column=1, sticky="w", pady=3)
        default_runoff = default_surface_runoff(surface.name)
        tk.Label(
            body,
            text=f"Default runoff coefficient: {default_runoff:.3f}",
            fg="#777777",
        ).grid(row=3, column=1, sticky="w", pady=(0, 6))
        buttons = ttk.Frame(body)
        buttons.grid(row=4, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(buttons, text="Cancel", command=self.destroy).grid(row=0, column=0, padx=4)
        ttk.Button(buttons, text="Save", command=self._save).grid(row=0, column=1)
        self.transient(parent)
        self.grab_set()

    def _save(self) -> None:
        self.result = Surface(
            name=self.name_var.get().strip() or "Other",
            area=max(0.0, area_to_internal(_float(self.area_var.get()), self.config_model)),
            runoff_coefficient=min(max(_float(self.runoff_var.get(), 0.0), 0.0), 1.0),
        )
        self.destroy()


class ReportDialog(tk.Toplevel):
    def __init__(self, parent: RainwaterTkApp, defaults: dict[str, str]) -> None:
        super().__init__(parent)
        self.title("PDF Report")
        self.resizable(True, False)
        self.result: dict[str, str] | None = None
        self.vars = {
            "client_name": tk.StringVar(value=defaults["client_name"]),
            "date": tk.StringVar(value=defaults["date"]),
            "location": tk.StringVar(value=defaults["location"]),
            "project_name": tk.StringVar(value=defaults["project_name"]),
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
        self.end_uses_text.insert("1.0", defaults["end_uses"])

        buttons = ttk.Frame(body)
        buttons.grid(row=5, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(buttons, text="Cancel", command=self.destroy).grid(row=0, column=0, padx=4)
        ttk.Button(buttons, text="Continue", command=self._save).grid(row=0, column=1)

        self.transient(parent)
        self.grab_set()

    def _save(self) -> None:
        self.result = {key: var.get().strip() for key, var in self.vars.items()}
        self.result["end_uses"] = self.end_uses_text.get("1.0", "end").strip() or "Not specified"
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
            ttk.Entry(body, textvariable=var, width=18).grid(row=grid_row, column=1, sticky="w", pady=2)
            ttk.Label(body, text=unit).grid(row=grid_row, column=2, sticky="w", padx=(8, 0), pady=2)
        buttons = ttk.Frame(body)
        buttons.grid(row=len(DEMAND_FIELDS) + 1, column=0, columnspan=3, sticky="e", pady=(10, 0))
        ttk.Button(buttons, text="Cancel", command=self.destroy).grid(row=0, column=0, padx=4)
        ttk.Button(buttons, text="Save", command=self._save).grid(row=0, column=1)
        self.transient(parent)
        self.grab_set()

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
