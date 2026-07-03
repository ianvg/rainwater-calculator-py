from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
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
            conn.commit()

    def list_projects(self) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute("SELECT name FROM projects ORDER BY updated_at DESC, name ASC").fetchall()
        return [r["name"] for r in rows]

    def save_project(self, config: ProjectConfig, rainfall_df: pd.DataFrame) -> None:
        config_json = json.dumps(asdict(config))
        with self._connect() as conn:
            row = conn.execute("SELECT id FROM projects WHERE name = ?", (config.name,)).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO projects (name, config_json) VALUES (?, ?)",
                    (config.name, config_json),
                )
                project_id = conn.execute("SELECT id FROM projects WHERE name = ?", (config.name,)).fetchone()["id"]
            else:
                project_id = row["id"]
                conn.execute(
                    "UPDATE projects SET config_json = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (config_json, project_id),
                )
                conn.execute("DELETE FROM rainfall_data WHERE project_id = ?", (project_id,))

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
        with self._connect() as conn:
            row = conn.execute("SELECT id, config_json FROM projects WHERE name = ?", (name,)).fetchone()
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
        return config, rainfall_df

    @staticmethod
    def _config_from_dict(payload: dict[str, Any]) -> ProjectConfig:
        surfaces = [Surface(**s) for s in payload.get("surfaces", [])]
        demand_payload = {"simple_daily_demand_gallons": 0.0, **payload.get("demand", {})}
        demand = DemandProfile(**demand_payload)
        tank_params = TankParameters(**payload.get("tank_parameters", {}))

        return ProjectConfig(
            name=payload.get("name", "Unnamed Project"),
            unit_system=payload.get("unit_system", "Imperial"),
            surfaces=surfaces,
            demand=demand,
            graph_start_gal=int(payload.get("graph_start_gal", 500)),
            graph_end_gal=int(payload.get("graph_end_gal", 20000)),
            graph_step_gal=int(payload.get("graph_step_gal", 500)),
            selected_tank_size_gal=float(payload.get("selected_tank_size_gal", 5000.0)),
            tank_parameters=tank_params,
        )
