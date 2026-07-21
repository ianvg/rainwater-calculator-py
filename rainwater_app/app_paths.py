from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Mapping


APP_DISPLAY_NAME = "RWH Calculator"
APP_DIRECTORY_NAME = "rwh-calculator"
DATA_DIRECTORY_OVERRIDE = "RWH_APP_DATA_DIR"
CACHE_DIRECTORY_OVERRIDE = "RWH_APP_CACHE_DIR"
LEGACY_DATA_FILES = (
    "rainwater_projects.db",
    "recent_projects.json",
    "app_preferences.json",
    "schedule_library.json",
    "demand_object_library.json",
)


def user_data_dir(
    *,
    platform: str | None = None,
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> Path:
    """Return the native per-user writable data directory for this application."""
    environment = os.environ if environ is None else environ
    override = environment.get(DATA_DIRECTORY_OVERRIDE, "").strip()
    if override:
        return Path(override).expanduser().resolve()
    platform_name = sys.platform if platform is None else platform
    home_dir = Path.home() if home is None else Path(home)
    if platform_name == "win32":
        root = environment.get("LOCALAPPDATA") or environment.get("APPDATA")
        return (Path(root) if root else home_dir / "AppData" / "Local") / APP_DISPLAY_NAME
    if platform_name == "darwin":
        return home_dir / "Library" / "Application Support" / APP_DISPLAY_NAME
    xdg_root = environment.get("XDG_DATA_HOME", "").strip()
    return (Path(xdg_root).expanduser() if xdg_root else home_dir / ".local" / "share") / APP_DIRECTORY_NAME


def user_cache_dir(
    *,
    platform: str | None = None,
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> Path:
    """Return the native per-user cache directory for provider response caches."""
    environment = os.environ if environ is None else environ
    override = environment.get(CACHE_DIRECTORY_OVERRIDE, "").strip()
    if override:
        return Path(override).expanduser().resolve()
    platform_name = sys.platform if platform is None else platform
    home_dir = Path.home() if home is None else Path(home)
    if platform_name == "win32":
        root = environment.get("LOCALAPPDATA") or environment.get("APPDATA")
        return (Path(root) if root else home_dir / "AppData" / "Local") / APP_DISPLAY_NAME / "Cache"
    if platform_name == "darwin":
        return home_dir / "Library" / "Caches" / APP_DISPLAY_NAME
    xdg_root = environment.get("XDG_CACHE_HOME", "").strip()
    return (Path(xdg_root).expanduser() if xdg_root else home_dir / ".cache") / APP_DIRECTORY_NAME


def project_backup_dir(project_path: Path, *, data_dir: Path | None = None) -> Path:
    """Return a collision-resistant per-user backup directory for one project file."""
    project = Path(project_path).expanduser().resolve()
    digest = hashlib.sha256(str(project).casefold().encode("utf-8")).hexdigest()[:12]
    safe_stem = "".join(character if character.isalnum() else "-" for character in project.stem)
    safe_stem = safe_stem.strip("-") or "project"
    return (data_dir or user_data_dir()) / "backups" / f"{safe_stem}-{digest}"


def _atomic_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{destination.name}.",
            suffix=".migration",
            dir=destination.parent,
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
        shutil.copy2(source, temporary)
        os.replace(temporary, destination)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def migrate_legacy_application_data(legacy_dir: Path, destination_dir: Path) -> tuple[Path, ...]:
    """Copy legacy beside-application data into the user directory when absent.

    Source files are intentionally retained so the migration is reversible and
    portable installations remain usable.
    """
    legacy = Path(legacy_dir).resolve()
    destination = Path(destination_dir).resolve()
    if legacy == destination:
        destination.mkdir(parents=True, exist_ok=True)
        return ()
    destination.mkdir(parents=True, exist_ok=True)
    migrated: list[Path] = []
    for name in LEGACY_DATA_FILES:
        source = legacy / name
        target = destination / name
        if not source.is_file() or target.exists():
            continue
        _atomic_copy(source, target)
        migrated.append(target)
    return tuple(migrated)
