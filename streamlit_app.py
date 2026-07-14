from __future__ import annotations

import pandas as pd
import streamlit as st

from rainwater_app.acis import default_complete_calendar_range, fetch_daily_station_data, fetch_station_options
from rainwater_app.defaults import default_project_config
from rainwater_app.engine import reliability_curve, simulate_tank
from rainwater_app.models import MONTH_KEYS, ProjectConfig, Surface
from rainwater_app.rainfall import load_rainfall_csv
from rainwater_app.storage import SQLiteStore

st.set_page_config(page_title="Rainwater Calculator", layout="wide")

store = SQLiteStore()

SQFT_PER_SQM = 10.7639
LITERS_PER_GALLON = 3.78541
MM_PER_INCH = 25.4
US_STATE_CODES = (
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "HI", "ID", "IL", "IN", "IA",
    "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM",
    "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA",
    "WV", "WI", "WY",
)


def _is_metric(config: ProjectConfig) -> bool:
    return config.unit_system == "Metric"


def _area_unit(config: ProjectConfig) -> str:
    return "m^2" if _is_metric(config) else "sq ft"


def _volume_unit(config: ProjectConfig) -> str:
    return "L" if _is_metric(config) else "gal"


def _precip_unit(config: ProjectConfig) -> str:
    return "mm" if _is_metric(config) else "in"


def _area_to_display(value_sqft: float, config: ProjectConfig) -> float:
    return value_sqft / SQFT_PER_SQM if _is_metric(config) else value_sqft


def _area_to_internal(value: float, config: ProjectConfig) -> float:
    return value * SQFT_PER_SQM if _is_metric(config) else value


def _volume_to_display(value_gallons: float, config: ProjectConfig) -> float:
    return value_gallons * LITERS_PER_GALLON if _is_metric(config) else value_gallons


def _volume_to_internal(value: float, config: ProjectConfig) -> float:
    return value / LITERS_PER_GALLON if _is_metric(config) else value


def _precip_to_display(value_inches: float, config: ProjectConfig) -> float:
    return value_inches * MM_PER_INCH if _is_metric(config) else value_inches


def _precip_to_internal(value: float, config: ProjectConfig) -> float:
    return value / MM_PER_INCH if _is_metric(config) else value


def _temperature_to_display(value_f: float, config: ProjectConfig) -> float:
    return (value_f - 32.0) * 5.0 / 9.0 if _is_metric(config) else value_f


def _temperature_unit(config: ProjectConfig) -> str:
    return "C" if _is_metric(config) else "F"


def _ensure_session_state() -> None:
    if "config" not in st.session_state:
        st.session_state.config = default_project_config()
    _migrate_config(st.session_state.config)
    if "rainfall_df" not in st.session_state:
        st.session_state.rainfall_df = pd.DataFrame(columns=["Date", "Precipitation"])
    if "rainfall_source_label" not in st.session_state:
        st.session_state.rainfall_source_label = None
    if "curve_df" not in st.session_state:
        st.session_state.curve_df = pd.DataFrame()
    if "results_df" not in st.session_state:
        st.session_state.results_df = pd.DataFrame()


def _migrate_config(config: ProjectConfig) -> None:
    if not hasattr(config.demand, "simple_daily_demand_gallons"):
        config.demand.simple_daily_demand_gallons = 0.0
    if not hasattr(config, "rainfall_source_label"):
        config.rainfall_source_label = None


def _surfaces_df(config: ProjectConfig) -> pd.DataFrame:
    area_label = f"Area ({_area_unit(config)})"
    return pd.DataFrame([
        {"Surface": s.name, area_label: _area_to_display(s.area, config), "Runoff coefficient": s.runoff_coefficient}
        for s in config.surfaces
    ])


def _month_name(m: str) -> str:
    names = {
        "jan": "Jan", "feb": "Feb", "mar": "Mar", "apr": "Apr", "may": "May", "jun": "Jun",
        "jul": "Jul", "aug": "Aug", "sep": "Sep", "oct": "Oct", "nov": "Nov", "dec": "Dec",
    }
    return names[m]


def _demand_df(config: ProjectConfig) -> pd.DataFrame:
    d = config.demand
    volume_unit = _volume_unit(config)
    rows = []
    for m in MONTH_KEYS:
        rows.append(
            {
                "Month": _month_name(m),
                "Male Occupancy (people/day)": d.male_occupancy[m],
                "Female Occupancy (people/day)": d.female_occupancy[m],
                f"Ice Making ({volume_unit}/month)": _volume_to_display(d.ice_making[m], config),
                f"Cooling Tower ({volume_unit}/month)": _volume_to_display(d.cooling_tower[m], config),
                f"Ice Skating ({volume_unit}/month)": _volume_to_display(d.ice_skating[m], config),
                f"Other Indoor ({volume_unit}/month)": _volume_to_display(d.other_indoor[m], config),
                f"Spray Irrigation ({volume_unit}/month)": _volume_to_display(d.spray_irrigation[m], config),
                f"Drip Irrigation ({volume_unit}/month)": _volume_to_display(d.drip_irrigation[m], config),
                f"Vehicular Washing ({volume_unit}/month)": _volume_to_display(d.vehicular_washing[m], config),
                f"Other Outdoor ({volume_unit}/month)": _volume_to_display(d.other_outdoor[m], config),
            }
        )
    return pd.DataFrame(rows)


def _apply_surfaces(config: ProjectConfig, edited: pd.DataFrame) -> None:
    surfaces: list[Surface] = []
    area_label = f"Area ({_area_unit(config)})"
    for _, row in edited.iterrows():
        surfaces.append(
            Surface(
                name=str(row.get("Surface", "Other")),
                area=_area_to_internal(float(row.get(area_label, 0.0) or 0.0), config),
                runoff_coefficient=float(row.get("Runoff coefficient", 0.0) or 0.0),
            )
        )
    config.surfaces = surfaces


def _apply_demand(config: ProjectConfig, edited: pd.DataFrame) -> None:
    d = config.demand
    volume_unit = _volume_unit(config)
    for i, m in enumerate(MONTH_KEYS):
        row = edited.iloc[i]
        d.male_occupancy[m] = float(row.get("Male Occupancy (people/day)", 0.0) or 0.0)
        d.female_occupancy[m] = float(row.get("Female Occupancy (people/day)", 0.0) or 0.0)
        d.ice_making[m] = _volume_to_internal(float(row.get(f"Ice Making ({volume_unit}/month)", 0.0) or 0.0), config)
        d.cooling_tower[m] = _volume_to_internal(float(row.get(f"Cooling Tower ({volume_unit}/month)", 0.0) or 0.0), config)
        d.ice_skating[m] = _volume_to_internal(float(row.get(f"Ice Skating ({volume_unit}/month)", 0.0) or 0.0), config)
        d.other_indoor[m] = _volume_to_internal(float(row.get(f"Other Indoor ({volume_unit}/month)", 0.0) or 0.0), config)
        d.spray_irrigation[m] = _volume_to_internal(float(row.get(f"Spray Irrigation ({volume_unit}/month)", 0.0) or 0.0), config)
        d.drip_irrigation[m] = _volume_to_internal(float(row.get(f"Drip Irrigation ({volume_unit}/month)", 0.0) or 0.0), config)
        d.vehicular_washing[m] = _volume_to_internal(float(row.get(f"Vehicular Washing ({volume_unit}/month)", 0.0) or 0.0), config)
        d.other_outdoor[m] = _volume_to_internal(float(row.get(f"Other Outdoor ({volume_unit}/month)", 0.0) or 0.0), config)


def _rainfall_to_display_df(rainfall_df: pd.DataFrame, config: ProjectConfig) -> pd.DataFrame:
    display = rainfall_df.copy()
    display = display.rename(columns={"Precipitation": f"Precipitation ({_precip_unit(config)})"})
    precip_col = f"Precipitation ({_precip_unit(config)})"
    if precip_col in display:
        display[precip_col] = display[precip_col].map(lambda v: _precip_to_display(float(v), config))
    return display


def _rainfall_to_internal_df(rainfall_df: pd.DataFrame, config: ProjectConfig) -> pd.DataFrame:
    internal = rainfall_df.copy()
    internal["Precipitation"] = internal["Precipitation"].map(lambda v: _precip_to_internal(float(v), config))
    return internal


def _rainfall_summary(rainfall_df: pd.DataFrame, source_label: str | None = None) -> str:
    if rainfall_df.empty:
        return "No rainfall data loaded."
    start = pd.Timestamp(rainfall_df["Date"].min()).strftime("%Y-%m-%d")
    end = pd.Timestamp(rainfall_df["Date"].max()).strftime("%Y-%m-%d")
    source = f" from {source_label}" if source_label else ""
    return f"{len(rainfall_df):,} rainfall rows loaded ({start} to {end}){source}"


def _station_label(station: dict) -> str:
    location = ""
    if station.get("latitude") is not None and station.get("longitude") is not None:
        location = f" ({station['latitude']:.3f}, {station['longitude']:.3f})"
    return f"{station['name']} - {station['sid']}{location}"


def _curve_to_display_df(curve: pd.DataFrame, config: ProjectConfig) -> pd.DataFrame:
    tank_col = f"Tank Size ({_volume_unit(config)})"
    display = curve.rename(columns={"TankSizeGallons": tank_col, "ReliabilityPercent": "Reliability (%)"}).copy()
    display[tank_col] = display[tank_col].map(lambda v: _volume_to_display(float(v), config))
    return display


def _results_to_display_df(results: pd.DataFrame, config: ProjectConfig) -> pd.DataFrame:
    volume_unit = _volume_unit(config)
    display = results.rename(
        columns={
            "Precipitation": f"Precipitation ({_precip_unit(config)})",
            "CollectedGallons": f"Collected ({volume_unit})",
            "DemandGallons": f"Demand ({volume_unit}/day)",
            "UnmetDemandGallons": f"Unmet Demand ({volume_unit}/day)",
            "WaterInTankGallons": f"Water in Tank ({volume_unit})",
            "ReliabilityPercent": "Reliability (%)",
            "DemandMet": "Demand Met",
            "ReliabilityTargetMet": "Reliability Target Met",
        }
    ).copy()
    for column in [f"Collected ({volume_unit})", f"Demand ({volume_unit}/day)", f"Unmet Demand ({volume_unit}/day)", f"Water in Tank ({volume_unit})"]:
        if column in display:
            display[column] = display[column].map(lambda v: _volume_to_display(float(v), config))
    precip_col = f"Precipitation ({_precip_unit(config)})"
    if precip_col in display:
        display[precip_col] = display[precip_col].map(lambda v: _precip_to_display(float(v), config))
    return display


def _sidebar() -> None:
    st.sidebar.header("Project")
    projects = store.list_projects()
    selected = st.sidebar.selectbox("Saved projects", options=["(none)"] + projects)

    col_new, col_save, col_load = st.sidebar.columns(3)
    if col_new.button("New"):
        st.session_state.config = default_project_config()
        st.session_state.rainfall_df = pd.DataFrame(columns=["Date", "Precipitation"])
        st.session_state.rainfall_source_label = None
        st.session_state.config.rainfall_source_label = None
        st.session_state.curve_df = pd.DataFrame()
        st.session_state.results_df = pd.DataFrame()
        st.rerun()

    if col_load.button("Load") and selected != "(none)":
        config, rainfall_df, curve_df, results_df = store.load_project_with_analysis(selected)
        _migrate_config(config)
        st.session_state.config = config
        st.session_state.rainfall_df = rainfall_df
        st.session_state.rainfall_source_label = config.rainfall_source_label
        st.session_state.curve_df = curve_df
        st.session_state.results_df = results_df
        st.rerun()

    if col_save.button("Save"):
        config = st.session_state.config
        rainfall_df = st.session_state.rainfall_df
        config.rainfall_source_label = st.session_state.get("rainfall_source_label")
        store.save_project(config, rainfall_df, st.session_state.curve_df, st.session_state.results_df)
        st.sidebar.success("Project saved.")


_ensure_session_state()

config: ProjectConfig = st.session_state.config
rainfall_df: pd.DataFrame = st.session_state.rainfall_df

st.title("Rainwater Harvesting Calculator")
st.caption("Standalone local app. Inputs and projects are saved to a local SQLite file.")

col_a, col_b = st.columns(2)
config.name = col_a.text_input("Project name", value=config.name)
config.unit_system = col_b.selectbox("Unit system", options=["Imperial", "Metric"], index=0 if config.unit_system == "Imperial" else 1)

st.subheader("Collection surfaces")
surfaces_edited = st.data_editor(
    _surfaces_df(config),
    num_rows="dynamic",
    width="stretch",
    key=f"surfaces_editor_{config.unit_system}",
)

st.subheader("Demand Inputs")
col1, col2, col3, col4 = st.columns(4)
simple_daily_demand = col1.number_input(
    f"Simple daily demand ({_volume_unit(config)}/day)",
    min_value=0.0,
    value=float(_volume_to_display(config.demand.simple_daily_demand_gallons, config)),
    step=10.0,
)
config.demand.simple_daily_demand_gallons = _volume_to_internal(simple_daily_demand, config)
config.demand.avg_flush_per_person = col2.number_input("Average flushes per person", min_value=0.0, value=float(config.demand.avg_flush_per_person), step=0.1)
toilet_flush = col3.number_input(
    f"Volume per flush - toilet ({_volume_unit(config)}/flush)",
    min_value=0.0,
    value=float(_volume_to_display(config.demand.gallons_per_flush_toilet, config)),
    step=0.1,
)
urinal_flush = col4.number_input(
    f"Volume per flush - urinal ({_volume_unit(config)}/flush)",
    min_value=0.0,
    value=float(_volume_to_display(config.demand.gallons_per_flush_urinal, config)),
    step=0.1,
)
config.demand.gallons_per_flush_toilet = _volume_to_internal(toilet_flush, config)
config.demand.gallons_per_flush_urinal = _volume_to_internal(urinal_flush, config)

demand_edited = st.data_editor(
    _demand_df(config),
    width="stretch",
    key=f"demand_editor_{config.unit_system}",
)

st.subheader("Rainfall Data")
w1, w2, w3 = st.columns(3)
weather_state = w1.selectbox("Weather station state", options=US_STATE_CODES, index=US_STATE_CODES.index("NY"))
weather_years = int(w2.number_input("Historical period (years)", min_value=30, value=30, step=1))
weather_query = w3.text_input("Filter stations", value="")

start_date, end_date = default_complete_calendar_range(weather_years)
st.caption(
    f"ACIS import uses complete calendar years from {start_date:%Y-%m-%d} to {end_date:%Y-%m-%d}. "
    "Precipitation is loaded from ACIS `pcpn`; snowfall, min temperature, and max temperature are cached for review but snowfall is not added to precipitation."
)

station_options: list[dict] = []
if st.button("Find ACIS stations", width="stretch"):
    try:
        station_options = fetch_station_options(weather_state, start_date, end_date)
        if weather_query:
            query = weather_query.casefold()
            station_options = [s for s in station_options if query in s["name"].casefold() or query in s["sid"].casefold()]
        st.session_state.acis_station_options = station_options
        st.success(f"Found {len(station_options)} station options.")
    except Exception as exc:  # noqa: BLE001
        st.error(f"Could not fetch ACIS stations: {exc}")

station_options = st.session_state.get("acis_station_options", [])
if station_options:
    selected_station = st.selectbox("ACIS weather station", options=station_options, format_func=_station_label)
    if st.button("Import ACIS daily weather", width="stretch"):
        try:
            weather_df = fetch_daily_station_data(selected_station["sid"], start_date, end_date)
            st.session_state.weather_source_df = weather_df
            st.session_state.rainfall_df = weather_df[["Date", "Precipitation"]].copy()
            rainfall_df = st.session_state.rainfall_df
            source_label = f"{selected_station['name']} ({selected_station['sid']})"
            st.session_state.rainfall_source_label = source_label
            st.session_state.config.rainfall_source_label = source_label
            st.session_state.curve_df = pd.DataFrame()
            st.session_state.results_df = pd.DataFrame()
            st.success(_rainfall_summary(rainfall_df, source_label))
        except Exception as exc:  # noqa: BLE001
            st.error(f"Could not import ACIS weather data: {exc}")

if "weather_source_df" in st.session_state and not st.session_state.weather_source_df.empty:
    weather_preview = st.session_state.weather_source_df.rename(
        columns={
            "MaxTemperature": f"Max Temperature ({_temperature_unit(config)})",
            "MinTemperature": f"Min Temperature ({_temperature_unit(config)})",
            "Precipitation": f"Precipitation ({_precip_unit(config)})",
            "Snowfall": f"Snowfall ({_precip_unit(config)})",
        }
    ).copy()
    for column in [f"Max Temperature ({_temperature_unit(config)})", f"Min Temperature ({_temperature_unit(config)})"]:
        weather_preview[column] = weather_preview[column].map(lambda v: _temperature_to_display(float(v), config))
    for column in [f"Precipitation ({_precip_unit(config)})", f"Snowfall ({_precip_unit(config)})"]:
        weather_preview[column] = weather_preview[column].map(lambda v: _precip_to_display(float(v), config))
    st.dataframe(weather_preview.head(20), width="stretch")

uploaded = st.file_uploader(f"Upload CSV with Date and Precipitation columns; precipitation is read as {_precip_unit(config)}", type=["csv"])
if uploaded is not None:
    try:
        st.session_state.rainfall_df = _rainfall_to_internal_df(load_rainfall_csv(uploaded.getvalue()), config)
        rainfall_df = st.session_state.rainfall_df
        st.session_state.rainfall_source_label = None
        st.session_state.config.rainfall_source_label = None
        st.session_state.curve_df = pd.DataFrame()
        st.session_state.results_df = pd.DataFrame()
        st.success(f"Loaded {len(rainfall_df)} rainfall rows.")
    except Exception as exc:  # noqa: BLE001
        st.error(str(exc))

if not rainfall_df.empty:
    st.caption(_rainfall_summary(rainfall_df, st.session_state.get("rainfall_source_label")))
    st.dataframe(_rainfall_to_display_df(rainfall_df.head(20), config), width="stretch")

st.subheader("Analysis Settings")
g1, g2, g3 = st.columns(3)
graph_start = g1.number_input(
    f"Graph start tank size ({_volume_unit(config)})",
    min_value=1.0,
    value=float(_volume_to_display(config.graph_start_gal, config)),
    step=100.0,
)
graph_end = g2.number_input(
    f"Graph end tank size ({_volume_unit(config)})",
    min_value=2.0,
    value=float(_volume_to_display(config.graph_end_gal, config)),
    step=100.0,
)
graph_step = g3.number_input(
    f"Graph step ({_volume_unit(config)})",
    min_value=1.0,
    value=float(_volume_to_display(config.graph_step_gal, config)),
    step=50.0,
)
config.graph_start_gal = max(1, int(round(_volume_to_internal(graph_start, config))))
config.graph_end_gal = max(2, int(round(_volume_to_internal(graph_end, config))))
config.graph_step_gal = max(1, int(round(_volume_to_internal(graph_step, config))))

r1, r2, r3 = st.columns(3)
selected_tank = r1.number_input(
    f"Selected tank size ({_volume_unit(config)})",
    min_value=1.0,
    value=float(_volume_to_display(config.selected_tank_size_gal, config)),
    step=100.0,
)
config.selected_tank_size_gal = _volume_to_internal(selected_tank, config)
config.tank_parameters.initial_fill_percent = float(r2.number_input("Initial fill %", min_value=0.0, max_value=100.0, value=float(config.tank_parameters.initial_fill_percent), step=1.0))
config.tank_parameters.reliable_fill_percent = float(r3.number_input("Reserve threshold (% of daily demand)", min_value=0.0, max_value=100.0, value=float(config.tank_parameters.reliable_fill_percent), step=1.0))

_apply_surfaces(config, surfaces_edited)
_apply_demand(config, demand_edited)

st.session_state.config = config

_sidebar()

if st.button("Run Analysis", width="stretch"):
    if rainfall_df.empty:
        st.error("Upload rainfall CSV first.")
    elif config.graph_end_gal <= config.graph_start_gal:
        st.error("Graph end size must be greater than graph start size.")
    else:
        tank_sizes = list(range(config.graph_start_gal, config.graph_end_gal + 1, config.graph_step_gal))
        progress = st.progress(0, text="Analysis running: Part A - reliability curve")

        def update_curve_progress(index: int, total: int, _tank_size: float) -> None:
            percent = int((index / total) * 50) if total else 50
            progress.progress(percent, text=f"Analysis running: Part A - reliability curve ({index}/{total})")

        curve = reliability_curve(config, rainfall_df, tank_sizes, progress_callback=update_curve_progress)
        progress.progress(50, text="Analysis running: Part B - selected tank simulation")
        single = simulate_tank(config, rainfall_df, config.selected_tank_size_gal)
        progress.progress(75, text="Analysis running: Part B - preparing charts")
        st.session_state.curve_df = curve
        st.session_state.results_df = single
        progress.progress(100, text="Analysis complete")

curve_df = st.session_state.get("curve_df", pd.DataFrame())
results_df = st.session_state.get("results_df", pd.DataFrame())
if not curve_df.empty and not results_df.empty:
    curve_display = _curve_to_display_df(curve_df, config)
    single_display = _results_to_display_df(results_df, config)

    st.subheader("Reliability vs Tank Size")
    st.line_chart(curve_display, x=f"Tank Size ({_volume_unit(config)})", y="Reliability (%)", width="stretch")

    reliability = float(results_df["ReliabilityPercent"].iloc[0]) if not results_df.empty else 0.0
    st.metric("Reliability (selected tank)", f"{reliability:.2f}%")

    st.subheader("Tank Water Over Time")
    st.line_chart(single_display, x="Date", y=f"Water in Tank ({_volume_unit(config)})", width="stretch")

    st.subheader("Detailed Results")
    st.dataframe(single_display, width="stretch")

