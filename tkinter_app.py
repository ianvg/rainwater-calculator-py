from __future__ import annotations

import csv
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import pandas as pd

from rainwater_app.acis import default_complete_calendar_range, fetch_daily_station_data, fetch_station_options
from rainwater_app.defaults import default_project_config
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


def _app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _state_code(value: str) -> str:
    return value.split(" - ", 1)[0].strip().upper()


class RainwaterTkApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1200x760")
        self.minsize(1000, 680)

        self.store = SQLiteStore(str(_app_dir() / "rainwater_projects.db"))
        self.config_model = default_project_config()
        self.rainfall_df = pd.DataFrame(columns=["Date", "Precipitation"])
        self.curve_df = pd.DataFrame()
        self.results_df = pd.DataFrame()
        self.station_options: list[dict] = []

        self.project_name_var = tk.StringVar(value=self.config_model.name)
        self.unit_var = tk.StringVar(value=self.config_model.unit_system)
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
        self.initial_fill_var = tk.StringVar(value=str(self.config_model.tank_parameters.initial_fill_percent))
        self.reserve_var = tk.StringVar(value=str(self.config_model.tank_parameters.reliable_fill_percent))
        self.rainfall_summary_var = tk.StringVar(value="No rainfall file loaded")
        self.reliability_var = tk.StringVar(value="Reliability: --")
        self.weather_state_var = tk.StringVar(value="NY - New York")
        self.weather_years_var = tk.StringVar(value="30")
        self.weather_filter_var = tk.StringVar(value="")
        self.station_var = tk.StringVar(value="")

        self._build_ui()
        self._load_project_list()
        self._populate_from_model()

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        toolbar = ttk.Frame(self, padding=(10, 8))
        toolbar.grid(row=0, column=0, sticky="ew")
        toolbar.columnconfigure(4, weight=1)

        ttk.Label(toolbar, text="Project").grid(row=0, column=0, sticky="w")
        self.project_combo = ttk.Combobox(toolbar, textvariable=self.saved_project_var, width=24, state="readonly")
        self.project_combo.grid(row=0, column=1, padx=(6, 8), sticky="w")
        ttk.Button(toolbar, text="New", command=self.new_project).grid(row=0, column=2, padx=2)
        ttk.Button(toolbar, text="Save", command=self.save_project).grid(row=0, column=3, padx=2)
        ttk.Button(toolbar, text="Load", command=self.load_selected_project).grid(row=0, column=4, sticky="w", padx=2)
        ttk.Button(toolbar, text="Run Analysis", command=self.run_analysis).grid(row=0, column=5, padx=(18, 2))
        ttk.Button(toolbar, text="Export Results", command=self.export_results).grid(row=0, column=6, padx=2)

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

        status = ttk.Label(self, textvariable=self.status_var, anchor="w", padding=(10, 4))
        status.grid(row=2, column=0, sticky="ew")

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
        unit_combo.grid(row=0, column=3, padx=(8, 0))
        unit_combo.bind("<<ComboboxSelected>>", lambda _event: self._change_units())

        surfaces_frame = ttk.LabelFrame(self.inputs_tab, text="Collection Surfaces", padding=10)
        surfaces_frame.grid(row=1, column=0, sticky="nsew", pady=(10, 0), padx=(0, 5))
        surfaces_frame.rowconfigure(0, weight=1)
        surfaces_frame.columnconfigure(0, weight=1)
        self.surface_tree = ttk.Treeview(surfaces_frame, columns=("surface", "area", "runoff"), show="headings", height=12)
        self.surface_tree.heading("surface", text="Surface")
        self.surface_tree.heading("area", text="Area")
        self.surface_tree.heading("runoff", text="Runoff Coeff.")
        self.surface_tree.column("surface", width=220)
        self.surface_tree.column("area", width=90, anchor="e")
        self.surface_tree.column("runoff", width=90, anchor="e")
        self.surface_tree.grid(row=0, column=0, sticky="nsew")
        ttk.Button(surfaces_frame, text="Edit Selected Surface", command=self.edit_surface).grid(row=1, column=0, sticky="w", pady=(8, 0))

        right_frame = ttk.Frame(self.inputs_tab)
        right_frame.grid(row=1, column=1, sticky="nsew", pady=(10, 0), padx=(5, 0))
        right_frame.columnconfigure(0, weight=1)

        settings_frame = ttk.LabelFrame(right_frame, text="Demand and Analysis Settings", padding=10)
        settings_frame.grid(row=0, column=0, sticky="ew")
        for i in range(2):
            settings_frame.columnconfigure(i, weight=1)

        self._labeled_entry(settings_frame, 0, "Simple daily demand", self.simple_daily_var)
        self._labeled_entry(settings_frame, 1, "Average flushes/person", self.flushes_var)
        self._labeled_entry(settings_frame, 2, "Toilet volume/flush", self.toilet_flush_var)
        self._labeled_entry(settings_frame, 3, "Urinal volume/flush", self.urinal_flush_var)
        ttk.Separator(settings_frame).grid(row=4, column=0, columnspan=2, sticky="ew", pady=8)
        self._labeled_entry(settings_frame, 5, "Graph start tank size", self.graph_start_var)
        self._labeled_entry(settings_frame, 6, "Graph end tank size", self.graph_end_var)
        self._labeled_entry(settings_frame, 7, "Graph step", self.graph_step_var)
        self._labeled_entry(settings_frame, 8, "Selected tank size", self.selected_tank_var)
        self._labeled_entry(settings_frame, 9, "Initial fill %", self.initial_fill_var)
        self._labeled_entry(settings_frame, 10, "Reserve threshold %", self.reserve_var)

    def _build_import_tab(self) -> None:
        self.import_tab.columnconfigure(0, weight=1)

        csv_frame = ttk.LabelFrame(self.import_tab, text="Rainfall CSV", padding=10)
        csv_frame.grid(row=0, column=0, sticky="ew")
        csv_frame.columnconfigure(0, weight=1)
        ttk.Label(csv_frame, textvariable=self.rainfall_summary_var).grid(row=0, column=0, sticky="w")
        ttk.Button(csv_frame, text="Load Rainfall CSV", command=self.load_rainfall_csv).grid(row=0, column=1, sticky="e", padx=(12, 0))

        weather_frame = ttk.LabelFrame(self.import_tab, text="ACIS Weather Import", padding=10)
        weather_frame.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        weather_frame.columnconfigure(1, weight=1)
        ttk.Label(weather_frame, text="State").grid(row=0, column=0, sticky="w", pady=2)
        state_combo = ttk.Combobox(weather_frame, textvariable=self.weather_state_var, values=STATE_LABELS, state="readonly")
        state_combo.grid(row=0, column=1, sticky="ew", pady=2)
        self._labeled_entry(weather_frame, 1, "Historical years", self.weather_years_var)
        self._labeled_entry(weather_frame, 2, "Station filter", self.weather_filter_var)
        ttk.Button(weather_frame, text="Find Stations", command=self.find_acis_stations).grid(row=3, column=0, sticky="w", pady=(8, 2))
        self.station_combo = ttk.Combobox(weather_frame, textvariable=self.station_var, state="readonly")
        self.station_combo.grid(row=3, column=1, sticky="ew", padx=(8, 0), pady=(8, 2))
        ttk.Button(weather_frame, text="Import Selected Station", command=self.import_acis_weather).grid(row=4, column=0, columnspan=2, sticky="ew", pady=(4, 0))

    def _build_demand_tab(self) -> None:
        self.demand_tab.columnconfigure(0, weight=1)
        self.demand_tab.rowconfigure(0, weight=1)
        columns = ["month"] + [field for field, _label in DEMAND_FIELDS]
        self.demand_tree = ttk.Treeview(self.demand_tab, columns=columns, show="headings", height=14)
        self.demand_tree.heading("month", text="Month")
        self.demand_tree.column("month", width=80, anchor="w")
        for field, label in DEMAND_FIELDS:
            self.demand_tree.heading(field, text=label)
            self.demand_tree.column(field, width=105, anchor="e")
        self.demand_tree.grid(row=0, column=0, sticky="nsew")
        scroll_x = ttk.Scrollbar(self.demand_tab, orient="horizontal", command=self.demand_tree.xview)
        scroll_x.grid(row=1, column=0, sticky="ew")
        self.demand_tree.configure(xscrollcommand=scroll_x.set)
        ttk.Button(self.demand_tab, text="Edit Selected Month", command=self.edit_demand_month).grid(row=2, column=0, sticky="w", pady=(8, 0))

    def _build_results_tab(self) -> None:
        self.results_tab.columnconfigure(0, weight=1)
        self.results_tab.columnconfigure(1, weight=1)
        self.results_tab.rowconfigure(1, weight=1)

        ttk.Label(self.results_tab, textvariable=self.reliability_var, font=("Segoe UI", 12, "bold")).grid(row=0, column=0, columnspan=2, sticky="w")
        self.curve_canvas = tk.Canvas(self.results_tab, height=230, bg="white", highlightthickness=1, highlightbackground="#b7b7b7")
        self.curve_canvas.grid(row=1, column=0, sticky="nsew", pady=(8, 8), padx=(0, 5))
        self.tank_canvas = tk.Canvas(self.results_tab, height=230, bg="white", highlightthickness=1, highlightbackground="#b7b7b7")
        self.tank_canvas.grid(row=1, column=1, sticky="nsew", pady=(8, 8), padx=(5, 0))

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
        self.results_tree.grid(row=2, column=0, columnspan=2, sticky="nsew")

    def _labeled_entry(self, parent: ttk.Frame, row: int, label: str, variable: tk.StringVar) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=2)
        ttk.Entry(parent, textvariable=variable, width=18).grid(row=row, column=1, sticky="ew", pady=2)

    def _load_project_list(self) -> None:
        projects = self.store.list_projects()
        self.project_combo["values"] = projects
        if projects and not self.saved_project_var.get():
            self.saved_project_var.set(projects[0])

    def _populate_from_model(self) -> None:
        cfg = self.config_model
        self.project_name_var.set(cfg.name)
        self.unit_var.set(cfg.unit_system)
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
        self._populate_surfaces()
        self._populate_demand()
        self._update_rainfall_summary()

    def _apply_form_to_model(self) -> bool:
        cfg = self.config_model
        cfg.name = self.project_name_var.get().strip() or "Unnamed Project"
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
        cfg.selected_tank_size_gal = max(1.0, volume_to_internal(_float(self.selected_tank_var.get(), 5000), cfg))
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

    def _update_rainfall_summary(self) -> None:
        if self.rainfall_df.empty:
            self.rainfall_summary_var.set("No rainfall file loaded")
            return
        start = pd.Timestamp(self.rainfall_df["Date"].min()).strftime("%Y-%m-%d")
        end = pd.Timestamp(self.rainfall_df["Date"].max()).strftime("%Y-%m-%d")
        self.rainfall_summary_var.set(f"{len(self.rainfall_df):,} rainfall rows loaded ({start} to {end})")

    def _change_units(self) -> None:
        self.config_model.unit_system = self.unit_var.get()
        self._populate_from_model()

    def new_project(self) -> None:
        self.config_model = default_project_config()
        self.rainfall_df = pd.DataFrame(columns=["Date", "Precipitation"])
        self.results_df = pd.DataFrame()
        self.curve_df = pd.DataFrame()
        self.reliability_var.set("Reliability: --")
        self._clear_results()
        self._populate_from_model()
        self.status_var.set("Started a new project")

    def load_selected_project(self) -> None:
        name = self.saved_project_var.get()
        if not name:
            messagebox.showinfo(APP_TITLE, "Select a saved project first.")
            return
        try:
            self.config_model, self.rainfall_df = self.store.load_project(name)
            self.results_df = pd.DataFrame()
            self.curve_df = pd.DataFrame()
            self._clear_results()
            self._populate_from_model()
            self.status_var.set(f"Loaded project '{name}'")
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(APP_TITLE, f"Could not load project:\n{exc}")

    def save_project(self) -> None:
        self._apply_form_to_model()
        try:
            self.store.save_project(self.config_model, self.rainfall_df)
            self._load_project_list()
            self.saved_project_var.set(self.config_model.name)
            self.status_var.set(f"Saved project '{self.config_model.name}'")
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
            self._update_rainfall_summary()
            self.status_var.set(f"Loaded rainfall CSV: {Path(path).name}")
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(APP_TITLE, f"Could not load rainfall CSV:\n{exc}")

    def find_acis_stations(self) -> None:
        years = max(30, int(_float(self.weather_years_var.get(), 30)))
        state = _state_code(self.weather_state_var.get())
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
            self.status_var.set(f"Found {len(stations)} ACIS station(s)")
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(APP_TITLE, f"Could not fetch ACIS stations:\n{exc}")

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
        try:
            start_date, end_date = default_complete_calendar_range(years)
            weather_df = fetch_daily_station_data(station["sid"], start_date, end_date)
            self.rainfall_df = weather_df[["Date", "Precipitation"]].copy()
            self._update_rainfall_summary()
            self.status_var.set(f"Imported {len(self.rainfall_df):,} rows from {station['name']}")
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(APP_TITLE, f"Could not import ACIS weather:\n{exc}")

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

    def run_analysis(self) -> None:
        self._apply_form_to_model()
        cfg = self.config_model
        if self.rainfall_df.empty:
            messagebox.showwarning(APP_TITLE, "Load rainfall data before running the analysis.")
            return
        if cfg.graph_end_gal <= cfg.graph_start_gal:
            messagebox.showwarning(APP_TITLE, "Graph end tank size must be greater than graph start tank size.")
            return
        try:
            tank_sizes = range(cfg.graph_start_gal, cfg.graph_end_gal + 1, cfg.graph_step_gal)
            self.curve_df = reliability_curve(cfg, self.rainfall_df, tank_sizes)
            self.results_df = simulate_tank(cfg, self.rainfall_df, cfg.selected_tank_size_gal)
            reliability = float(self.results_df["ReliabilityPercent"].iloc[0]) if not self.results_df.empty else 0.0
            self.reliability_var.set(f"Reliability for selected tank: {reliability:.2f}%")
            self._populate_results()
            self._draw_curve()
            self._draw_tank_chart()
            self.status_var.set("Analysis complete")
        except Exception as exc:  # noqa: BLE001
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

    def _draw_curve(self) -> None:
        if self.curve_df.empty:
            return
        x = [volume_to_display(v, self.config_model) for v in self.curve_df["TankSizeGallons"]]
        y = list(self.curve_df["ReliabilityPercent"])
        self._draw_line_chart(self.curve_canvas, x, y, f"Reliability vs Tank Size ({volume_unit(self.config_model)})", "Reliability %")

    def _draw_tank_chart(self) -> None:
        if self.results_df.empty:
            return
        x = list(range(len(self.results_df)))
        y = [volume_to_display(v, self.config_model) for v in self.results_df["WaterInTankGallons"]]
        self._draw_line_chart(self.tank_canvas, x, y, f"Tank Water Over Time ({volume_unit(self.config_model)})", volume_unit(self.config_model))

    def _draw_line_chart(self, canvas: tk.Canvas, x_values: list[float], y_values: list[float], title: str, y_label: str) -> None:
        canvas.delete("all")
        width = max(canvas.winfo_width(), 420)
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
        for x, y in zip(x_values, y_values):
            px = pad_left + ((x - x_min) / (x_max - x_min)) * plot_w
            py = height - pad_bottom - ((y - y_min) / (y_max - y_min)) * plot_h
            points.extend([px, py])
        if len(points) >= 4:
            canvas.create_line(*points, fill="#0b5cab", width=2)
        for i in range(5):
            y = pad_top + (plot_h * i / 4)
            value = y_max - ((y_max - y_min) * i / 4)
            canvas.create_line(pad_left - 4, y, width - pad_right, y, fill="#e6e6e6")
            canvas.create_text(pad_left - 8, y, text=f"{value:.0f}", anchor="e", font=("Segoe UI", 8))
        canvas.create_text(width / 2, height - 14, text=f"{x_min:.0f} to {x_max:.0f}", font=("Segoe UI", 8))
        canvas.create_text(14, height / 2, text=y_label, angle=90, font=("Segoe UI", 8))


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
        buttons = ttk.Frame(body)
        buttons.grid(row=3, column=0, columnspan=2, sticky="e", pady=(10, 0))
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
        for row, (field, label) in enumerate(DEMAND_FIELDS):
            value = getattr(config.demand, field)[month]
            if field not in {"male_occupancy", "female_occupancy"}:
                label = f"{label} ({volume_unit(config)}/month)"
                value = volume_to_display(value, config)
            var = tk.StringVar(value=f"{value:.2f}")
            self.vars[field] = var
            ttk.Label(body, text=label).grid(row=row, column=0, sticky="w", pady=2)
            ttk.Entry(body, textvariable=var, width=18).grid(row=row, column=1, sticky="w", pady=2)
        buttons = ttk.Frame(body)
        buttons.grid(row=len(DEMAND_FIELDS), column=0, columnspan=2, sticky="e", pady=(10, 0))
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
