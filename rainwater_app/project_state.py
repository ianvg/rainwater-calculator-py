from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
import tempfile
from typing import Any, Mapping

import pandas as pd

from .models import ProjectConfig
from .storage import SQLiteStore


WORKING_DRAFT_SCHEMA_VERSION = 1


def _frame_payload(frame: pd.DataFrame | None) -> str:
    if frame is None or frame.empty:
        return ""
    metadata = json.dumps(
        {
            "shape": frame.shape,
            "columns": [str(column) for column in frame.columns],
            "dtypes": [str(dtype) for dtype in frame.dtypes],
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    try:
        row_hashes = pd.util.hash_pandas_object(frame, index=True, categorize=True)
        value_digest = hashlib.sha256(row_hashes.to_numpy().tobytes()).hexdigest()
    except TypeError:
        # Nested object values are uncommon in project frames but cannot be hashed
        # directly by pandas. JSON remains deterministic for that fallback case.
        value_digest = hashlib.sha256(
            frame.to_json(
                orient="split",
                date_format="iso",
                date_unit="ns",
                double_precision=15,
            ).encode("utf-8")
        ).hexdigest()
    return f"{metadata}:{value_digest}"


def project_state_fingerprint(
    config: ProjectConfig,
    rainfall_df: pd.DataFrame | None = None,
    curve_df: pd.DataFrame | None = None,
    results_df: pd.DataFrame | None = None,
    comparison_results_df: pd.DataFrame | None = None,
    hourly_results_df: pd.DataFrame | None = None,
    *,
    form_values: Mapping[str, object] | None = None,
    notes: str = "",
) -> str:
    """Return a stable digest for all user-owned state in an open project."""
    payload = {
        "config": asdict(config),
        "rainfall": _frame_payload(rainfall_df),
        "curve": _frame_payload(curve_df),
        "results": _frame_payload(results_df),
        "comparison_results": _frame_payload(comparison_results_df),
        "hourly_results": _frame_payload(hourly_results_df),
        "form_values": dict(sorted((form_values or {}).items())),
        "notes": notes,
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class WorkingDraftMetadata:
    project_name: str
    project_file_path: str
    baseline_fingerprint: str
    form_values: dict[str, Any]
    notes: str
    saved_at: str


@dataclass(frozen=True)
class WorkingDraft:
    metadata: WorkingDraftMetadata
    config: ProjectConfig
    rainfall_df: pd.DataFrame
    curve_df: pd.DataFrame
    results_df: pd.DataFrame
    comparison_results_df: pd.DataFrame
    hourly_results_df: pd.DataFrame


class WorkingDraftStore:
    """Persist one recoverable project draft outside the user's project file."""

    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)
        self.database_path = self.directory / "working_draft.db"
        self.metadata_path = self.directory / "working_draft.json"
        self.backup_dir = self.directory / "backups"

    def exists(self) -> bool:
        return self.database_path.is_file() and self.metadata_path.is_file()

    def save(
        self,
        config: ProjectConfig,
        rainfall_df: pd.DataFrame,
        curve_df: pd.DataFrame,
        results_df: pd.DataFrame,
        comparison_results_df: pd.DataFrame,
        hourly_results_df: pd.DataFrame,
        *,
        project_file_path: str | Path,
        baseline_fingerprint: str,
        form_values: Mapping[str, object],
        notes: str,
    ) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        store = SQLiteStore(
            self.database_path,
            backup_dir=self.backup_dir,
            backup_retention=2,
        )
        store.save_project(
            config,
            rainfall_df,
            curve_df,
            results_df,
            comparison_results_df,
            hourly_results_df,
        )
        metadata = {
            "schema_version": WORKING_DRAFT_SCHEMA_VERSION,
            "project_name": config.name,
            "project_file_path": str(Path(project_file_path)),
            "baseline_fingerprint": baseline_fingerprint,
            "form_values": dict(form_values),
            "notes": notes,
            "saved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        self._atomic_write_metadata(metadata)

    def load(self) -> WorkingDraft:
        payload = json.loads(self.metadata_path.read_text(encoding="utf-8"))
        schema_version = int(payload.get("schema_version", 0))
        if schema_version > WORKING_DRAFT_SCHEMA_VERSION:
            raise RuntimeError(
                f"Working draft schema {schema_version} is newer than the supported schema "
                f"{WORKING_DRAFT_SCHEMA_VERSION}."
            )
        project_name = str(payload.get("project_name", "")).strip()
        if not project_name:
            raise ValueError("The working draft does not identify a project.")
        store = SQLiteStore(
            self.database_path,
            backup_dir=self.backup_dir,
            backup_retention=2,
        )
        config, rainfall_df, curve_df, results_df = store.load_project_with_analysis(project_name)
        metadata = WorkingDraftMetadata(
            project_name=project_name,
            project_file_path=str(payload.get("project_file_path", "")),
            baseline_fingerprint=str(payload.get("baseline_fingerprint", "")),
            form_values=dict(payload.get("form_values", {})),
            notes=str(payload.get("notes", "")),
            saved_at=str(payload.get("saved_at", "")),
        )
        return WorkingDraft(
            metadata=metadata,
            config=config,
            rainfall_df=rainfall_df,
            curve_df=curve_df,
            results_df=results_df,
            comparison_results_df=store.load_comparison_results(project_name),
            hourly_results_df=store.load_hourly_results(project_name),
        )

    def clear(self) -> None:
        for path in (
            self.metadata_path,
            self.database_path,
            Path(f"{self.database_path}-wal"),
            Path(f"{self.database_path}-shm"),
        ):
            path.unlink(missing_ok=True)
        if self.backup_dir.is_dir():
            for backup in self.backup_dir.glob("working_draft-*.db"):
                backup.unlink(missing_ok=True)

    def _atomic_write_metadata(self, payload: Mapping[str, object]) -> None:
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                prefix=f".{self.metadata_path.name}.",
                suffix=".tmp",
                dir=self.directory,
                delete=False,
            ) as handle:
                temporary = Path(handle.name)
                json.dump(payload, handle, indent=2, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.metadata_path)
            temporary = None
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
