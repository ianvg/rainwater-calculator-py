from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from io import StringIO
from pathlib import Path
from typing import Any

import pandas as pd

from .models import DemandProfile, ProjectConfig, Surface, TankParameters


class SQLiteStore:
    def __init__(self, db_path: str = "rainwater_projects.db") -> None:
        self.db_path = Path(db_path)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS projects (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    config_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS rainfall_data (
                    project_id INTEGER NOT NULL,
                    date TEXT NOT NULL,
                    precipitation REAL NOT NULL,
                    FOREIGN KEY(project_id) REFERENCES projects(id)
                )
                """
            )
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(projects)").fetchall()}
            if "curve_json" not in columns:
                conn.execute("ALTER TABLE projects ADD COLUMN curve_json TEXT")
            if "results_json" not in columns:
                conn.execute("ALTER TABLE projects ADD COLUMN results_json TEXT")
            if "comparison_results_json" not in columns:
                conn.execute("ALTER TABLE projects ADD COLUMN comparison_results_json TEXT")
            conn.commit()

    def list_projects(self) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute("SELECT name FROM projects ORDER BY updated_at DESC, name ASC").fetchall()
        return [r["name"] for r in rows]

    def save_project(
        self,
        config: ProjectConfig,
        rainfall_df: pd.DataFrame | None = None,
        curve_df: pd.DataFrame | None = None,
        results_df: pd.DataFrame | None = None,
        comparison_results_df: pd.DataFrame | None = None,
    ) -> None:
        config_json = json.dumps(asdict(config))
        curve_json = self._df_to_json(curve_df)
        results_json = self._df_to_json(results_df)
        comparison_results_json = self._df_to_json(comparison_results_df)
        with self._connect() as conn:
            row = conn.execute("SELECT id FROM projects WHERE name = ?", (config.name,)).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO projects (name, config_json, curve_json, results_json, comparison_results_json) VALUES (?, ?, ?, ?, ?)",
                    (config.name, config_json, curve_json, results_json, comparison_results_json),
                )
                project_id = conn.execute("SELECT id FROM projects WHERE name = ?", (config.name,)).fetchone()["id"]
            else:
                project_id = row["id"]
                conn.execute(
                    """
                    UPDATE projects
                    SET config_json = ?, curve_json = ?, results_json = ?, comparison_results_json = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (config_json, curve_json, results_json, comparison_results_json, project_id),
                )
                conn.execute("DELETE FROM rainfall_data WHERE project_id = ?", (project_id,))

            if rainfall_df is not None and not rainfall_df.empty:
                records = [
                    (int(project_id), pd.Timestamp(d).strftime("%Y-%m-%d"), float(p))
                    for d, p in zip(rainfall_df["Date"], rainfall_df["Precipitation"])
                ]
                conn.executemany(
                    "INSERT INTO rainfall_data (project_id, date, precipitation) VALUES (?, ?, ?)",
                    records,
                )
            conn.commit()

    def load_project(self, name: str) -> tuple[ProjectConfig, pd.DataFrame]:
        config, rainfall_df, _curve_df, _results_df = self.load_project_with_analysis(name)
        return config, rainfall_df

    def load_project_with_analysis(self, name: str) -> tuple[ProjectConfig, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, config_json, curve_json, results_json FROM projects WHERE name = ?",
                (name,),
            ).fetchone()
            if row is None:
                raise ValueError(f"Project '{name}' not found.")

            config_dict: dict[str, Any] = json.loads(row["config_json"])
            rainfall_rows = conn.execute(
                "SELECT date, precipitation FROM rainfall_data WHERE project_id = ? ORDER BY date ASC",
                (row["id"],),
            ).fetchall()

        config = self._config_from_dict(config_dict)
        rainfall_df = pd.DataFrame(
            {
                "Date": [pd.to_datetime(r["date"]) for r in rainfall_rows],
                "Precipitation": [float(r["precipitation"]) for r in rainfall_rows],
            }
        )
        curve_df = self._df_from_json(row["curve_json"])
        results_df = self._df_from_json(row["results_json"])
        return config, rainfall_df, curve_df, results_df

    def load_comparison_results(self, name: str) -> pd.DataFrame:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT comparison_results_json FROM projects WHERE name = ?",
                (name,),
            ).fetchone()
        if row is None:
            raise ValueError(f"Project '{name}' not found.")
        return self._df_from_json(row["comparison_results_json"])

    @staticmethod
    def _df_to_json(df: pd.DataFrame | None) -> str | None:
        if df is None or df.empty:
            return None
        return df.to_json(orient="split", date_format="iso")

    @staticmethod
    def _df_from_json(payload: str | None) -> pd.DataFrame:
        if not payload:
            return pd.DataFrame()
        df = pd.read_json(StringIO(payload), orient="split")
        if "Date" in df:
            df["Date"] = pd.to_datetime(df["Date"])
        return df

    @staticmethod
    def _config_from_dict(payload: dict[str, Any]) -> ProjectConfig:
        surfaces = [Surface(**s) for s in payload.get("surfaces", [])]
        demand_payload = {
            "simple_daily_demand_gallons": 0.0,
            "daily_demand_days_per_week": 7,
            **payload.get("demand", {}),
        }
        demand = DemandProfile(**demand_payload)
        tank_params = TankParameters(**payload.get("tank_parameters", {}))

        return ProjectConfig(
            name=payload.get("name", "Unnamed Project"),
            author_name=payload.get("author_name", ""),
            notes=payload.get("notes", ""),
            street_address=payload.get("street_address", payload.get("address", "")),
            city=payload.get("city", ""),
            state_or_province=payload.get("state_or_province", ""),
            postal_code=payload.get("postal_code", ""),
            latitude=_optional_float(payload.get("latitude")),
            longitude=_optional_float(payload.get("longitude")),
            unit_system=payload.get("unit_system", "Imperial"),
            country_code=payload.get("country_code", "USA"),
            system_type=(
                payload.get("system_type")
                if payload.get("system_type") in {"Direct system", "Indirect system"}
                else "Direct system"
            ),
            acis_precipitation_field=payload.get("acis_precipitation_field", "TOTAL_PRECIPITATION"),
            canadian_precipitation_field=payload.get("canadian_precipitation_field", "TOTAL_PRECIPITATION"),
            surfaces=surfaces,
            demand=demand,
            graph_start_gal=int(payload.get("graph_start_gal", 500)),
            graph_end_gal=int(payload.get("graph_end_gal", 20000)),
            graph_step_gal=int(payload.get("graph_step_gal", 500)),
            selected_tank_size_gal=float(payload.get("selected_tank_size_gal", 5000.0)),
            multitank_comparison_enabled=bool(payload.get("multitank_comparison_enabled", False)),
            comparison_tank_sizes_gal=[
                float(value) for value in payload.get("comparison_tank_sizes_gal", []) if float(value) > 0
            ],
            rainfall_source_label=payload.get("rainfall_source_label"),
            analysis_input_signature=payload.get("analysis_input_signature"),
            analysis_unit_system=payload.get("analysis_unit_system"),
            tank_parameters=tank_params,
        )


def _optional_float(value: object) -> float | None:
    try:
        return None if value is None or value == "" else float(value)
    except (TypeError, ValueError):
        return None
