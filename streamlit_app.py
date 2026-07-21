from __future__ import annotations

import pandas as pd
import streamlit as st

from rainwater_app.app_paths import project_backup_dir, user_data_dir
from rainwater_app.models import MONTH_KEYS, ProjectConfig
from rainwater_app.rainfall_quality import assess_rainfall_record, rainfall_data_type_label
from rainwater_app.reporting import report_average_annual_precipitation
from rainwater_app.storage import SQLiteStore
from rainwater_app.units import (
    area_to_display,
    area_unit,
    precip_to_display,
    precip_unit,
    volume_to_display,
    volume_unit,
)


st.set_page_config(page_title="RWH Calculator Project Viewer", layout="wide")


def _surface_rows(config: ProjectConfig) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Surface": surface.name,
                f"Area ({area_unit(config)})": area_to_display(surface.area, config),
                "Runoff coefficient": surface.runoff_coefficient,
                f"First flush ({precip_unit(config)})": precip_to_display(
                    surface.first_flush_depth_inches, config
                ),
            }
            for surface in config.surfaces
        ]
    )


def _monthly_demand_rows(config: ProjectConfig) -> pd.DataFrame:
    demand = config.demand
    rows: list[dict[str, object]] = []
    for month in MONTH_KEYS:
        rows.append(
            {
                "Month": month.title(),
                "Male occupancy": demand.male_occupancy[month],
                "Female occupancy": demand.female_occupancy[month],
                f"Ice making ({volume_unit(config)}/month)": volume_to_display(
                    demand.ice_making[month], config
                ),
                f"Cooling tower ({volume_unit(config)}/month)": volume_to_display(
                    demand.cooling_tower[month], config
                ),
                f"Irrigation ({volume_unit(config)}/month)": volume_to_display(
                    demand.spray_irrigation[month] + demand.drip_irrigation[month], config
                ),
                f"Other demand ({volume_unit(config)}/month)": volume_to_display(
                    demand.ice_skating[month]
                    + demand.other_indoor[month]
                    + demand.vehicular_washing[month]
                    + demand.other_outdoor[month],
                    config,
                ),
            }
        )
    return pd.DataFrame(rows)


def _rainfall_display(rainfall: pd.DataFrame, config: ProjectConfig) -> pd.DataFrame:
    display = rainfall.loc[:, ["Date", "Precipitation"]].copy()
    display["Date"] = pd.to_datetime(display["Date"], errors="coerce")
    column = f"Precipitation ({precip_unit(config)})"
    display[column] = pd.to_numeric(display.pop("Precipitation"), errors="coerce").map(
        lambda value: precip_to_display(float(value), config)
    )
    return display


def _curve_display(curve: pd.DataFrame, config: ProjectConfig) -> pd.DataFrame:
    display = curve.loc[:, ["TankSizeGallons", "ReliabilityPercent"]].copy()
    tank_column = f"Tank size ({volume_unit(config)})"
    display[tank_column] = display.pop("TankSizeGallons").map(
        lambda value: volume_to_display(float(value), config)
    )
    return display.rename(columns={"ReliabilityPercent": "Reliability (%)"})


def _result_display(results: pd.DataFrame, config: ProjectConfig) -> pd.DataFrame:
    display = results.copy()
    display["Date"] = pd.to_datetime(display.get("Date"), errors="coerce")
    volume_columns = {
        "CollectedGallons": "Collected",
        "DemandGallons": "Demand",
        "RainwaterSuppliedGallons": "Rainwater supplied",
        "MainsMakeupGallons": "Municipal makeup",
        "OverflowGallons": "Overflow",
        "WaterInTankGallons": "Water in tank",
    }
    for source, label in volume_columns.items():
        if source not in display:
            continue
        target = f"{label} ({volume_unit(config)})"
        display[target] = pd.to_numeric(display.pop(source), errors="coerce").map(
            lambda value: volume_to_display(float(value), config)
        )
    return display


def _show_scope() -> None:
    st.info(
        "This is a deliberately limited, read-only viewer for projects already created "
        "and analyzed by the Tkinter desktop application."
    )
    st.markdown(
        """
        Supported here:

        - open a saved project from the local project database;
        - inspect project inputs, rainfall quality, saved reliability results, and daily results;
        - use browser-native tables and charts for lightweight review.

        Tkinter-only product capabilities:

        - create, edit, rename, save, or delete projects;
        - import rainfall or search weather stations;
        - run analysis, optimization, or design recommendations;
        - configure system networks, demand objects, finances, or reports;
        - export authoritative HTML, LaTeX, PDF, or CSV deliverables.
        """
    )


st.title("RWH Calculator Project Viewer")
st.caption("Read-only companion to the Tkinter desktop product")

application_data_dir = user_data_dir()
project_path = application_data_dir / "rainwater_projects.db"
store = SQLiteStore(
    str(project_path),
    backup_dir=project_backup_dir(project_path, data_dir=application_data_dir),
)
projects = store.list_projects()
if not projects:
    _show_scope()
    st.warning(
        "No saved projects are available. Create and analyze a project in the Tkinter "
        "desktop application, then reopen this viewer."
    )
    st.stop()

selected_project = st.sidebar.selectbox("Saved project", projects)
st.sidebar.caption("Viewing only; project changes are made in Tkinter.")
config, rainfall_df, curve_df, results_df = store.load_project_with_analysis(selected_project)
quality = assess_rainfall_record(
    rainfall_df,
    known_missing_dates=config.rainfall_known_missing_dates,
    antecedent_dry_days=config.first_flush_antecedent_dry_days,
)

overview_tab, rainfall_tab, results_tab, scope_tab = st.tabs(
    ["Overview", "Rainfall", "Saved results", "Viewer scope"]
)

with overview_tab:
    st.subheader(config.name)
    metric_columns = st.columns(4)
    metric_columns[0].metric("Unit system", config.unit_system)
    metric_columns[1].metric(
        "Selected tank", f"{volume_to_display(config.selected_tank_size_gal, config):,.0f} {volume_unit(config)}"
    )
    metric_columns[2].metric("Collection surfaces", len(config.surfaces))
    metric_columns[3].metric("System type", config.system_type)

    st.markdown(
        f"**Author:** {config.author_name or 'Not specified'}  \n"
        f"**Location:** {', '.join(value for value in (config.city, config.state_or_province) if value) or 'Not specified'}  \n"
        f"**Notes:** {config.notes or 'No notes provided.'}"
    )
    st.subheader("Collection surfaces")
    st.dataframe(_surface_rows(config), width="stretch", hide_index=True)
    st.subheader("Monthly demand inputs")
    st.dataframe(_monthly_demand_rows(config), width="stretch", hide_index=True)

with rainfall_tab:
    st.subheader("Rainfall provenance and quality")
    quality_metrics = st.columns(4)
    quality_metrics[0].metric(
        f"Completeness ({quality.completeness_rating})",
        f"{quality.completeness_percent:.2f}%",
    )
    quality_metrics[1].metric("Observed days", f"{quality.observed_days:,}")
    quality_metrics[2].metric("Missing days", f"{quality.missing_days:,}")
    quality_metrics[3].metric("Rainfall events", f"{quality.event_count:,}")
    st.markdown(
        f"**Source:** {config.rainfall_source_label or 'Not recorded'}  \n"
        f"**Classification:** {rainfall_data_type_label(config.rainfall_data_type)}  \n"
        f"**Resolution:** {config.rainfall_temporal_resolution.title()}  \n"
        f"**Source timezone:** {config.rainfall_timezone or 'Unspecified'}  \n"
        f"**Timing metadata:** {config.rainfall_timing_type}  \n"
        f"**Imported/retrieved:** {config.rainfall_retrieved_at or 'Not recorded'}  \n"
        f"**Average annual precipitation:** "
        f"{report_average_annual_precipitation(rainfall_df, config):,.2f} {precip_unit(config)}"
    )
    if quality.partial_years:
        st.warning(
            "Partial or incomplete calendar years: "
            + ", ".join(str(year) for year in quality.partial_years)
        )
    st.dataframe(_rainfall_display(rainfall_df, config), width="stretch", hide_index=True)

with results_tab:
    if curve_df.empty or results_df.empty:
        st.warning(
            "This project has no complete saved analysis. Run and save the analysis in "
            "the Tkinter desktop application."
        )
    else:
        reliability = float(results_df["ReliabilityPercent"].iloc[0])
        st.metric("Selected-tank reliability", f"{reliability:.2f}%")
        curve_display = _curve_display(curve_df, config)
        tank_column = f"Tank size ({volume_unit(config)})"
        st.subheader("Reliability versus tank size")
        st.line_chart(curve_display, x=tank_column, y="Reliability (%)", width="stretch")
        result_display = _result_display(results_df, config)
        water_column = f"Water in tank ({volume_unit(config)})"
        if water_column in result_display:
            st.subheader("Stored water over time")
            st.line_chart(result_display, x="Date", y=water_column, width="stretch")
        st.subheader("Saved daily results")
        st.dataframe(result_display, width="stretch", hide_index=True)

with scope_tab:
    _show_scope()
