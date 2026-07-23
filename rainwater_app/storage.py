from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
import shutil
import tempfile
from typing import Any, Iterator

import pandas as pd

from .rainfall import HOURLY_PRECIPITATION_COLUMNS, has_hourly_rainfall
from .equipment_catalog import migrate_legacy_catalog, normalized_constraints
from .first_flush import (
    normalize_first_flush_design_preset,
    normalize_first_flush_sizing_method,
)
from .system_model import ensure_primary_overflow_paths
from .models import (
    DemandObject,
    DemandProfile,
    FRACTIONAL_SCHEDULE_TYPE,
    FinancialParameters,
    OCCUPANCY_SCHEDULE_TYPE,
    normalize_unit_system,
    normalize_filtration_system_flow_gpm,
    normalize_transfer_pump_type,
    OptimizationParameters,
    ProjectConfig,
    Surface,
    SystemComponentParameters,
    TankParameters,
    WEEKDAY_KEYS,
    migrate_legacy_demand_inputs,
    normalized_schedule_months,
    normalize_schedule_type,
)


STORAGE_SCHEMA_VERSION = 1
PROJECT_SCHEMA_VERSION = 13
DEFAULT_BACKUP_RETENTION = 10


class StorageRecoveryError(RuntimeError):
    """Raised when a damaged project database has no usable automatic backup."""


class SQLiteStore:
    def __init__(
        self,
        db_path: str = "rainwater_projects.db",
        *,
        backup_dir: str | Path | None = None,
        backup_retention: int = DEFAULT_BACKUP_RETENTION,
    ) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.backup_dir = (
            Path(backup_dir)
            if backup_dir is not None
            else self.db_path.parent / "backups" / self.db_path.stem
        )
        self.backup_retention = max(int(backup_retention), 1)
        self.recovery_notice: str | None = None
        self.last_backup_error: str | None = None
        self._recover_if_needed()
        self._init_db()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA synchronous = FULL")
        try:
            yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._connect() as conn:
            existing_version = int(conn.execute("PRAGMA user_version").fetchone()[0])
        if existing_version > STORAGE_SCHEMA_VERSION:
            raise RuntimeError(
                f"Project database schema {existing_version} is newer than the supported "
                f"schema {STORAGE_SCHEMA_VERSION}. Upgrade the application before opening it."
            )
        if self.db_path.stat().st_size > 0 and existing_version < STORAGE_SCHEMA_VERSION:
            if self._create_backup_safely("pre-schema-upgrade") is None:
                raise StorageRecoveryError(
                    "Cannot upgrade the project database schema because its pre-upgrade "
                    f"backup failed: {self.last_backup_error or 'unknown backup error'}"
                )
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode = WAL")
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
                    hourly_precipitation_json TEXT,
                    FOREIGN KEY(project_id) REFERENCES projects(id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS system_templates (
                    name TEXT PRIMARY KEY COLLATE NOCASE,
                    template_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
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
            if "hourly_results_json" not in columns:
                conn.execute("ALTER TABLE projects ADD COLUMN hourly_results_json TEXT")
            rainfall_columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(rainfall_data)").fetchall()
            }
            if "hourly_precipitation_json" not in rainfall_columns:
                conn.execute("ALTER TABLE rainfall_data ADD COLUMN hourly_precipitation_json TEXT")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS storage_metadata "
                "(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            conn.execute(
                "INSERT OR REPLACE INTO storage_metadata (key, value) VALUES (?, ?)",
                ("storage_schema_version", str(STORAGE_SCHEMA_VERSION)),
            )
            conn.execute(f"PRAGMA user_version = {STORAGE_SCHEMA_VERSION}")
            conn.commit()

    @staticmethod
    def _database_is_valid(path: Path) -> bool:
        if not path.is_file() or path.stat().st_size == 0:
            return False
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(path, timeout=5.0)
            result = connection.execute("PRAGMA quick_check").fetchone()
            return bool(result and str(result[0]).casefold() == "ok")
        except (OSError, sqlite3.DatabaseError):
            return False
        finally:
            if connection is not None:
                connection.close()

    def list_backups(self) -> list[Path]:
        if not self.backup_dir.is_dir():
            return []
        return sorted(
            (
                candidate
                for candidate in self.backup_dir.glob(f"{self.db_path.stem}-*.db")
                if not candidate.name.endswith("-corrupt.db")
            ),
            reverse=True,
        )

    def create_backup(self, reason: str = "manual") -> Path:
        if not self._database_is_valid(self.db_path):
            raise StorageRecoveryError("Cannot back up a missing or invalid project database.")
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        clean_reason = "".join(
            character if character.isalnum() else "-" for character in reason.casefold()
        ).strip("-") or "backup"
        destination = self.backup_dir / f"{self.db_path.stem}-{timestamp}-{clean_reason}.db"
        temporary: Path | None = None
        source_connection: sqlite3.Connection | None = None
        destination_connection: sqlite3.Connection | None = None
        try:
            with tempfile.NamedTemporaryFile(
                prefix=f".{destination.name}.",
                suffix=".tmp",
                dir=self.backup_dir,
                delete=False,
            ) as handle:
                temporary = Path(handle.name)
            source_connection = sqlite3.connect(self.db_path, timeout=30.0)
            destination_connection = sqlite3.connect(temporary)
            source_connection.backup(destination_connection)
            destination_connection.commit()
            destination_connection.close()
            destination_connection = None
            source_connection.close()
            source_connection = None
            if not self._database_is_valid(temporary):
                raise StorageRecoveryError("The generated project backup did not pass validation.")
            Path(f"{temporary}-wal").unlink(missing_ok=True)
            Path(f"{temporary}-shm").unlink(missing_ok=True)
            os.replace(temporary, destination)
            temporary = None
            for stale in self.list_backups()[self.backup_retention :]:
                stale.unlink(missing_ok=True)
            self.last_backup_error = None
            return destination
        finally:
            if destination_connection is not None:
                destination_connection.close()
            if source_connection is not None:
                source_connection.close()
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def _create_backup_safely(self, reason: str) -> Path | None:
        try:
            return self.create_backup(reason)
        except (OSError, sqlite3.DatabaseError, StorageRecoveryError) as exc:
            self.last_backup_error = str(exc)
            return None

    def restore_latest_backup(self) -> Path:
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        valid_backup = next(
            (candidate for candidate in self.list_backups() if self._database_is_valid(candidate)),
            None,
        )
        if valid_backup is None:
            raise StorageRecoveryError(
                f"No valid backup is available for {self.db_path.name}."
            )
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        quarantined = self.backup_dir / f"{self.db_path.stem}-{timestamp}-corrupt.db"
        if self.db_path.exists():
            shutil.copy2(self.db_path, quarantined)
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                prefix=f".{self.db_path.name}.",
                suffix=".restore",
                dir=self.db_path.parent,
                delete=False,
            ) as handle:
                temporary = Path(handle.name)
            shutil.copy2(valid_backup, temporary)
            if not self._database_is_valid(temporary):
                raise StorageRecoveryError("The selected backup failed validation during restore.")
            Path(f"{temporary}-wal").unlink(missing_ok=True)
            Path(f"{temporary}-shm").unlink(missing_ok=True)
            Path(f"{self.db_path}-wal").unlink(missing_ok=True)
            Path(f"{self.db_path}-shm").unlink(missing_ok=True)
            os.replace(temporary, self.db_path)
            temporary = None
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        self.recovery_notice = (
            f"Recovered {self.db_path.name} from backup {valid_backup.name}. "
            f"The damaged file was preserved as {quarantined.name}."
        )
        return valid_backup

    def _recover_if_needed(self) -> None:
        if not self.db_path.exists() or self.db_path.stat().st_size == 0:
            return
        if self._database_is_valid(self.db_path):
            return
        self.restore_latest_backup()

    def list_projects(self) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute("SELECT name FROM projects ORDER BY updated_at DESC, name ASC").fetchall()
        return [r["name"] for r in rows]

    def schema_versions(self) -> dict[str, int]:
        with self._connect() as conn:
            storage_version = int(conn.execute("PRAGMA user_version").fetchone()[0])
        return {
            "storage": storage_version,
            "project": PROJECT_SCHEMA_VERSION,
        }

    def list_system_templates(self) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT name FROM system_templates ORDER BY name COLLATE NOCASE"
            ).fetchall()
        return [str(row["name"]) for row in rows]

    def save_system_template(
        self, name: str, template: dict[str, Any], *, replace: bool = False
    ) -> None:
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("Template name cannot be blank.")
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT name FROM system_templates WHERE name = ? COLLATE NOCASE", (clean_name,)
            ).fetchone()
            if existing is not None and not replace:
                raise ValueError(f"A system template named '{clean_name}' already exists.")
            if existing is None:
                conn.execute(
                    "INSERT INTO system_templates (name, template_json) VALUES (?, ?)",
                    (clean_name, json.dumps(template)),
                )
            else:
                conn.execute(
                    "UPDATE system_templates SET name = ?, template_json = ?, "
                    "updated_at = CURRENT_TIMESTAMP WHERE name = ? COLLATE NOCASE",
                    (clean_name, json.dumps(template), str(existing["name"])),
                )
            conn.commit()
        self._create_backup_safely("template-save")

    def load_system_template(self, name: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT template_json FROM system_templates WHERE name = ? COLLATE NOCASE", (name,)
            ).fetchone()
        if row is None:
            raise ValueError(f"System template '{name}' not found.")
        payload = json.loads(row["template_json"])
        if not isinstance(payload, dict):
            raise ValueError(f"System template '{name}' is invalid.")
        return payload

    def rename_system_template(self, old_name: str, new_name: str) -> None:
        clean_name = new_name.strip()
        if not clean_name:
            raise ValueError("Template name cannot be blank.")
        with self._connect() as conn:
            collision = conn.execute(
                "SELECT name FROM system_templates WHERE name = ? COLLATE NOCASE "
                "AND name <> ? COLLATE NOCASE", (clean_name, old_name)
            ).fetchone()
            if collision is not None:
                raise ValueError(f"A system template named '{clean_name}' already exists.")
            cursor = conn.execute(
                "UPDATE system_templates SET name = ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE name = ? COLLATE NOCASE", (clean_name, old_name)
            )
            if cursor.rowcount == 0:
                raise ValueError(f"System template '{old_name}' not found.")
            conn.commit()
        self._create_backup_safely("template-rename")

    def delete_system_template(self, name: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM system_templates WHERE name = ? COLLATE NOCASE", (name,)
            )
            conn.commit()
        self._create_backup_safely("template-delete")

    def save_project(
        self,
        config: ProjectConfig,
        rainfall_df: pd.DataFrame | None = None,
        curve_df: pd.DataFrame | None = None,
        results_df: pd.DataFrame | None = None,
        comparison_results_df: pd.DataFrame | None = None,
        hourly_results_df: pd.DataFrame | None = None,
    ) -> None:
        config_json = json.dumps(
            {"project_schema_version": PROJECT_SCHEMA_VERSION, **asdict(config)}
        )
        curve_json = self._df_to_json(curve_df)
        results_json = self._df_to_json(results_df)
        comparison_results_json = self._df_to_json(comparison_results_df)
        hourly_results_json = self._df_to_json(hourly_results_df)
        with self._connect() as conn:
            row = conn.execute("SELECT id FROM projects WHERE name = ?", (config.name,)).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO projects (name, config_json, curve_json, results_json, comparison_results_json, hourly_results_json) VALUES (?, ?, ?, ?, ?, ?)",
                    (config.name, config_json, curve_json, results_json, comparison_results_json, hourly_results_json),
                )
                project_id = conn.execute("SELECT id FROM projects WHERE name = ?", (config.name,)).fetchone()["id"]
            else:
                project_id = row["id"]
                conn.execute(
                    """
                    UPDATE projects
                    SET config_json = ?, curve_json = ?, results_json = ?, comparison_results_json = ?, hourly_results_json = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (config_json, curve_json, results_json, comparison_results_json, hourly_results_json, project_id),
                )
                conn.execute("DELETE FROM rainfall_data WHERE project_id = ?", (project_id,))

            if rainfall_df is not None and not rainfall_df.empty:
                include_hourly = has_hourly_rainfall(rainfall_df)
                records = [
                    (
                        int(project_id),
                        pd.Timestamp(row["Date"]).strftime("%Y-%m-%d"),
                        float(row["Precipitation"]),
                        json.dumps([
                            float(row[column]) for column in HOURLY_PRECIPITATION_COLUMNS
                        ]) if include_hourly else None,
                    )
                    for _, row in rainfall_df.iterrows()
                ]
                conn.executemany(
                    "INSERT INTO rainfall_data "
                    "(project_id, date, precipitation, hourly_precipitation_json) "
                    "VALUES (?, ?, ?, ?)",
                    records,
                )
            conn.commit()
        self._create_backup_safely("project-save")

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
            project_schema_version = int(config_dict.pop("project_schema_version", 0))
            if project_schema_version > PROJECT_SCHEMA_VERSION:
                raise RuntimeError(
                    f"Project schema {project_schema_version} is newer than the supported "
                    f"schema {PROJECT_SCHEMA_VERSION}. Upgrade the application before loading it."
                )
            rainfall_rows = conn.execute(
                "SELECT date, precipitation, hourly_precipitation_json FROM rainfall_data "
                "WHERE project_id = ? ORDER BY date ASC",
                (row["id"],),
            ).fetchall()

        config = self._config_from_dict(
            config_dict, project_schema_version=project_schema_version
        )
        rainfall_df = pd.DataFrame(
            {
                "Date": [pd.to_datetime(r["date"]) for r in rainfall_rows],
                "Precipitation": [float(r["precipitation"]) for r in rainfall_rows],
            }
        )
        hourly_profiles = [r["hourly_precipitation_json"] for r in rainfall_rows]
        if hourly_profiles and all(profile is not None for profile in hourly_profiles):
            parsed_profiles = [json.loads(profile) for profile in hourly_profiles]
            if all(isinstance(profile, list) and len(profile) == 24 for profile in parsed_profiles):
                for hour, column in enumerate(HOURLY_PRECIPITATION_COLUMNS):
                    rainfall_df[column] = [float(profile[hour]) for profile in parsed_profiles]
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

    def load_hourly_results(self, name: str) -> pd.DataFrame:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT hourly_results_json FROM projects WHERE name = ?",
                (name,),
            ).fetchone()
        if row is None:
            raise ValueError(f"Project '{name}' not found.")
        return self._df_from_json(row["hourly_results_json"])

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
    def _config_from_dict(
        payload: dict[str, Any], *, project_schema_version: int = 0
    ) -> ProjectConfig:
        surfaces = [Surface(**s) for s in payload.get("surfaces", [])]
        demand_payload = {
            "simple_daily_demand_gallons": 0.0,
            "daily_demand_days_per_week": 7,
            **payload.get("demand", {}),
        }
        raw_schedule_library = demand_payload.get("hourly_schedule_library", {})
        raw_demand_objects = demand_payload.get("demand_objects", [])
        demand_objects: list[DemandObject] = []
        for item in raw_demand_objects:
            if not isinstance(item, dict):
                continue
            object_payload = dict(item)
            legacy_daily = object_payload.pop("daily_demand_gallons", None)
            if "instantaneous_demand_gallons_per_minute" not in object_payload and legacy_daily is not None:
                schedule = raw_schedule_library.get(object_payload.get("schedule_name", ""), {})
                positive_daily_hours = [
                    sum(min(max(float(value), 0.0), 1.0) for value in values[:24])
                    for values in schedule.values()
                    if isinstance(values, list)
                ]
                scheduled_hours = max(positive_daily_hours, default=0.0)
                object_payload["instantaneous_demand_gallons_per_minute"] = (
                    max(float(legacy_daily), 0.0) / (60.0 * scheduled_hours)
                    if scheduled_hours > 0.0
                    else 0.0
                )
            demand_objects.append(DemandObject(**object_payload))
        demand_payload["demand_objects"] = demand_objects
        demand = DemandProfile(**demand_payload)
        demand.hourly_schedule_types = {
            name: normalize_schedule_type(demand.hourly_schedule_types.get(name))
            for name in demand.hourly_schedule_library
        }
        demand.hourly_schedule_months = {
            name: normalized_schedule_months(months)
            for name, months in demand.hourly_schedule_months.items()
            if name in demand.hourly_schedule_library
        }
        if demand.hourly_schedule_enabled and not demand.hourly_schedule_library:
            demand.hourly_schedule_library[demand.active_hourly_schedule_name] = {
                day: list(values) for day, values in demand.hourly_weekly_fractions.items()
            }
        if demand.hourly_schedule_library and demand.active_hourly_schedule_name not in demand.hourly_schedule_library:
            demand.active_hourly_schedule_name = next(iter(demand.hourly_schedule_library))
        migrated_indices = migrate_legacy_demand_inputs(demand)
        if project_schema_version < 6:
            _migrate_fixture_operating_days_to_schedules(demand)
        if project_schema_version < 8:
            _migrate_occupational_schedules_to_occupancy(demand)
        if project_schema_version < 9:
            _migrate_recurring_operating_days_to_schedules(demand)
        system_layout = [
            dict(item) for item in payload.get("system_layout", []) if isinstance(item, dict)
        ]
        system_connections = [
            {str(key): str(value) for key, value in item.items()}
            for item in payload.get("system_connections", [])
            if isinstance(item, dict)
        ]
        system_layout, system_connections = ensure_primary_overflow_paths(
            system_layout, system_connections
        )
        if migrated_indices:
            for item in system_layout:
                if item.get("component_type") != "end_uses":
                    continue
                assigned = list(item.get("demand_object_indices", []))
                item["demand_object_indices"] = list(dict.fromkeys([*assigned, *migrated_indices]))
        tank_payload = payload.get("tank_parameters", {})
        tank_params = TankParameters(
            initial_fill_percent=float(tank_payload.get("initial_fill_percent", 50.0)),
            # The legacy reliable_fill_percent was only a reporting target, not protected
            # storage. Migrating it to dead storage would silently change old results.
            minimum_operating_volume_percent=float(
                tank_payload.get("minimum_operating_volume_percent", 0.0)
            ),
        )
        system_payload = dict(payload.get("system_parameters", {}))
        if "filtration_system_flow_gpm" not in system_payload:
            legacy_capacity = float(
                system_payload.get("filtration_pump_capacity_gallons_per_hour", 1200.0)
            )
            system_payload["filtration_system_flow_gpm"] = normalize_filtration_system_flow_gpm(
                legacy_capacity / 60.0
            )
        else:
            system_payload["filtration_system_flow_gpm"] = normalize_filtration_system_flow_gpm(
                system_payload["filtration_system_flow_gpm"]
            )
        system_payload["transfer_pump_type"] = normalize_transfer_pump_type(
            system_payload.get("transfer_pump_type")
        )
        system_params = SystemComponentParameters(**system_payload)
        system_params.synchronize_filtration_flow()
        financial_params = FinancialParameters(**payload.get("financial_parameters", {}))
        optimization_payload = dict(payload.get("optimization_parameters", {}))
        if not optimization_payload.get("equipment_candidates") and optimization_payload.get("catalog"):
            optimization_payload["equipment_candidates"] = migrate_legacy_catalog(
                optimization_payload["catalog"]
            )
        optimization_payload["equipment_constraints"] = normalized_constraints(
            optimization_payload.get("equipment_constraints")
        )
        optimization_params = OptimizationParameters(**optimization_payload)

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
            unit_system=normalize_unit_system(payload.get("unit_system")),
            country_code=payload.get("country_code", "USA"),
            system_type=(
                payload.get("system_type")
                if payload.get("system_type") in {"Direct system", "Indirect system"}
                else "Direct system"
            ),
            system_layout=system_layout,
            system_connections=system_connections,
            acis_precipitation_field=payload.get("acis_precipitation_field", "TOTAL_PRECIPITATION"),
            canadian_precipitation_field=payload.get("canadian_precipitation_field", "TOTAL_PRECIPITATION"),
            surfaces=surfaces,
            first_flush_sizing_method=normalize_first_flush_sizing_method(
                payload.get("first_flush_sizing_method", "manual")
            ),
            first_flush_design_preset=normalize_first_flush_design_preset(
                payload.get("first_flush_design_preset", "code_minimum")
            ),
            first_flush_antecedent_dry_days=max(
                float(payload.get("first_flush_antecedent_dry_days", 1.0)), 0.0
            ),
            first_flush_antecedent_dry_unit=(
                str(payload.get("first_flush_antecedent_dry_unit", "days")).casefold()
                if str(payload.get("first_flush_antecedent_dry_unit", "days")).casefold()
                in {"days", "hours"}
                else "days"
            ),
            demand=demand,
            graph_start_gal=int(payload.get("graph_start_gal", 500)),
            graph_end_gal=int(payload.get("graph_end_gal", 20000)),
            graph_step_gal=int(payload.get("graph_step_gal", 500)),
            graph_auto_step_count=max(1, int(payload.get("graph_auto_step_count", 20))),
            selected_tank_size_gal=float(payload.get("selected_tank_size_gal", 5000.0)),
            recommendation_reliability_target_percent=min(
                max(float(payload.get("recommendation_reliability_target_percent", 90.0)), 0.0),
                100.0,
            ),
            recommendation_marginal_gain_threshold=max(
                float(payload.get("recommendation_marginal_gain_threshold", 1.0)), 0.0
            ),
            multitank_comparison_enabled=bool(payload.get("multitank_comparison_enabled", False)),
            comparison_tank_sizes_gal=[
                float(value) for value in payload.get("comparison_tank_sizes_gal", []) if float(value) > 0
            ],
            use_synthetic_hourly_rainfall=bool(
                payload.get("use_synthetic_hourly_rainfall", False)
            ),
            rainfall_source_label=payload.get("rainfall_source_label"),
            rainfall_data_type=(
                str(payload.get("rainfall_data_type", "unclassified")).casefold()
                if str(payload.get("rainfall_data_type", "unclassified")).casefold()
                in {"unclassified", "observed", "synthetic", "interpolated", "reanalysis"}
                else "unclassified"
            ),
            rainfall_temporal_resolution=(
                str(payload.get("rainfall_temporal_resolution", "daily")).casefold()
                if str(payload.get("rainfall_temporal_resolution", "daily")).casefold()
                in {"daily", "hourly", "subhourly", "monthly", "unknown"}
                else "unknown"
            ),
            rainfall_timezone=str(payload.get("rainfall_timezone", "Unspecified")),
            rainfall_timing_type=str(
                payload.get(
                    "rainfall_timing_type",
                    "Daily totals; within-day timing not observed",
                )
            ),
            rainfall_retrieved_at=payload.get("rainfall_retrieved_at"),
            rainfall_known_missing_dates=[
                str(value) for value in payload.get("rainfall_known_missing_dates", [])
            ],
            weather_station_latitude=_optional_float(payload.get("weather_station_latitude")),
            weather_station_longitude=_optional_float(payload.get("weather_station_longitude")),
            analysis_input_signature=payload.get("analysis_input_signature"),
            analysis_unit_system=(
                normalize_unit_system(payload.get("analysis_unit_system"))
                if payload.get("analysis_unit_system")
                else None
            ),
            tank_parameters=tank_params,
            system_parameters=system_params,
            financial_parameters=financial_params,
            optimization_parameters=optimization_params,
            report_sections={
                str(key): bool(value)
                for key, value in payload.get("report_sections", {}).items()
            } if isinstance(payload.get("report_sections", {}), dict) else {},
            report_include_system_visualization=bool(
                payload.get("report_include_system_visualization", False)
            ),
            report_include_multitank_charts=bool(
                payload.get("report_include_multitank_charts", False)
            ),
        )


def _migrate_fixture_operating_days_to_schedules(demand: DemandProfile) -> None:
    """Preserve legacy fixture weekdays while making schedules authoritative."""
    for demand_object in demand.demand_objects:
        if demand_object.demand_mode != "fixture_usage":
            continue
        source_name = demand_object.schedule_name
        source = demand.hourly_schedule_library.get(source_name)
        if source is None:
            continue
        legacy_days = set(demand_object.operating_weekdays or [])
        migrated: dict[str, list[float]] = {}
        for day_index, day_key in enumerate(WEEKDAY_KEYS):
            values = [
                min(max(float(value), 0.0), 1.0)
                for value in source.get(day_key, [])[:24]
            ]
            values.extend([0.0] * (24 - len(values)))
            if day_index not in legacy_days:
                values = [0.0] * 24
            elif not any(values):
                # The legacy hourly engine spread a fixed daily volume evenly when
                # its selected schedule had no active hours on an operating day.
                values = [1.0] * 24
            migrated[day_key] = values

        source_normalized = {
            day_key: (
                [
                    min(max(float(value), 0.0), 1.0)
                    for value in source.get(day_key, [])[:24]
                ]
                + [0.0] * max(24 - len(source.get(day_key, [])[:24]), 0)
            )[:24]
            for day_key in WEEKDAY_KEYS
        }
        if migrated != source_normalized:
            base_name = f"{source_name} ({demand_object.name} fixture days)"
            migrated_name = base_name
            suffix = 2
            while migrated_name in demand.hourly_schedule_library:
                migrated_name = f"{base_name} {suffix}"
                suffix += 1
            demand.hourly_schedule_library[migrated_name] = migrated
            demand.hourly_schedule_types[migrated_name] = FRACTIONAL_SCHEDULE_TYPE
            demand_object.schedule_name = migrated_name
        demand_object.operating_weekdays = [
            index
            for index, day_key in enumerate(WEEKDAY_KEYS)
            if any(migrated[day_key])
        ]
        demand_object.operating_days_per_week = len(
            demand_object.operating_weekdays
        )


def _migrate_occupational_schedules_to_occupancy(demand: DemandProfile) -> None:
    """Convert legacy occupational timing profiles to binary occupancy schedules."""
    converted_names: dict[str, str] = {}
    for demand_object in demand.demand_objects:
        if demand_object.demand_mode not in {
            "fixture_usage",
            "recurring_daily",
            "monthly_volume",
        }:
            continue
        source_name = demand_object.schedule_name
        source = demand.hourly_schedule_library.get(source_name)
        if source is None and demand_object.demand_mode == "monthly_volume" and not source_name:
            source_name = "Always occupied"
            source = {day: [1.0] * 24 for day in WEEKDAY_KEYS}
            demand.hourly_schedule_library.setdefault(source_name, source)
            demand.hourly_schedule_types[source_name] = OCCUPANCY_SCHEDULE_TYPE
            demand_object.schedule_name = source_name
        if source is None:
            continue
        if demand.hourly_schedule_types.get(source_name) == OCCUPANCY_SCHEDULE_TYPE:
            continue
        converted_name = converted_names.get(source_name)
        if converted_name is None:
            binary = {
                day: [
                    1.0 if float(value) > 0.0 else 0.0
                    for value in source.get(day, [])[:24]
                ]
                + [0.0] * max(24 - len(source.get(day, [])[:24]), 0)
                for day in WEEKDAY_KEYS
            }
            base_name = f"{source_name} occupancy"
            converted_name = base_name
            suffix = 2
            while converted_name in demand.hourly_schedule_library:
                converted_name = f"{base_name} {suffix}"
                suffix += 1
            demand.hourly_schedule_library[converted_name] = binary
            demand.hourly_schedule_types[converted_name] = OCCUPANCY_SCHEDULE_TYPE
            converted_names[source_name] = converted_name
        demand_object.schedule_name = converted_name
        if demand_object.demand_mode == "fixture_usage":
            occupancy = demand.hourly_schedule_library[converted_name]
            demand_object.operating_weekdays = [
                index
                for index, day in enumerate(WEEKDAY_KEYS)
                if any(occupancy[day])
            ]
            demand_object.operating_days_per_week = len(
                demand_object.operating_weekdays
            )


def _migrate_recurring_operating_days_to_schedules(demand: DemandProfile) -> None:
    """Preserve legacy recurring weekdays in the now-authoritative schedule."""
    for demand_object in demand.demand_objects:
        if demand_object.demand_mode != "recurring_daily":
            continue
        source_name = demand_object.schedule_name
        source = demand.hourly_schedule_library.get(source_name)
        if source is None:
            continue
        legacy_days = set(demand_object.operating_weekdays or [])
        masked = {
            day: (
                [
                    1.0 if float(value) > 0.0 else 0.0
                    for value in source.get(day, [])[:24]
                ]
                + [0.0] * max(24 - len(source.get(day, [])[:24]), 0)
                if index in legacy_days
                else [0.0] * 24
            )
            for index, day in enumerate(WEEKDAY_KEYS)
        }
        source_binary = {
            day: [
                1.0 if float(value) > 0.0 else 0.0
                for value in source.get(day, [])[:24]
            ]
            + [0.0] * max(24 - len(source.get(day, [])[:24]), 0)
            for day in WEEKDAY_KEYS
        }
        if masked != source_binary:
            base_name = f"{source_name} ({demand_object.name} recurring days)"
            migrated_name = base_name
            suffix = 2
            while migrated_name in demand.hourly_schedule_library:
                migrated_name = f"{base_name} {suffix}"
                suffix += 1
            demand.hourly_schedule_library[migrated_name] = masked
            demand.hourly_schedule_types[migrated_name] = OCCUPANCY_SCHEDULE_TYPE
            demand_object.schedule_name = migrated_name
        demand_object.operating_weekdays = [
            index
            for index, day in enumerate(WEEKDAY_KEYS)
            if any(masked[day])
        ]
        demand_object.operating_days_per_week = len(
            demand_object.operating_weekdays
        )


def _optional_float(value: object) -> float | None:
    try:
        return None if value is None or value == "" else float(value)
    except (TypeError, ValueError):
        return None
