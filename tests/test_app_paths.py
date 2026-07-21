from __future__ import annotations

from pathlib import Path

from rainwater_app.app_paths import (
    migrate_legacy_application_data,
    project_backup_dir,
    user_cache_dir,
    user_data_dir,
)


def test_user_data_directory_is_native_to_each_platform() -> None:
    home = Path("/users/example")

    assert user_data_dir(
        platform="win32", environ={"LOCALAPPDATA": "C:/Users/example/AppData/Local"}, home=home
    ) == Path("C:/Users/example/AppData/Local/RWH Calculator")
    assert user_data_dir(platform="darwin", environ={}, home=home) == (
        home / "Library" / "Application Support" / "RWH Calculator"
    )
    assert user_data_dir(platform="linux", environ={}, home=home) == (
        home / ".local" / "share" / "rwh-calculator"
    )
    assert user_data_dir(
        platform="linux", environ={"XDG_DATA_HOME": "/data"}, home=home
    ) == Path("/data/rwh-calculator")


def test_environment_overrides_keep_portable_and_test_deployments_available(tmp_path) -> None:
    data = tmp_path / "portable-data"
    cache = tmp_path / "portable-cache"

    assert user_data_dir(environ={"RWH_APP_DATA_DIR": str(data)}) == data.resolve()
    assert user_cache_dir(environ={"RWH_APP_CACHE_DIR": str(cache)}) == cache.resolve()


def test_legacy_migration_copies_without_overwriting_or_deleting_source(tmp_path) -> None:
    legacy = tmp_path / "legacy"
    destination = tmp_path / "user-data"
    legacy.mkdir()
    (legacy / "rainwater_projects.db").write_bytes(b"legacy database")
    (legacy / "recent_projects.json").write_text('["old.db"]', encoding="utf-8")
    destination.mkdir()
    (destination / "recent_projects.json").write_text('["new.db"]', encoding="utf-8")

    migrated = migrate_legacy_application_data(legacy, destination)

    assert migrated == (destination / "rainwater_projects.db",)
    assert (destination / "rainwater_projects.db").read_bytes() == b"legacy database"
    assert (destination / "recent_projects.json").read_text(encoding="utf-8") == '["new.db"]'
    assert (legacy / "rainwater_projects.db").exists()


def test_project_backup_directory_is_stable_and_collision_resistant(tmp_path) -> None:
    data_dir = tmp_path / "data"

    first = project_backup_dir(tmp_path / "one" / "project.db", data_dir=data_dir)
    second = project_backup_dir(tmp_path / "two" / "project.db", data_dir=data_dir)

    assert first == project_backup_dir(tmp_path / "one" / "project.db", data_dir=data_dir)
    assert first.parent == data_dir / "backups"
    assert first != second
