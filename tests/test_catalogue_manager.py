from datetime import date
from pathlib import Path
import sqlite3

import pytest

from rainwater_app.catalogue_manager import (
    CatalogueManager,
    apply_catalogue_provenance,
    install_catalogue,
    preferred_catalogue,
)
from rainwater_app.models import ProjectConfig


SCHEMA = """
CREATE TABLE catalogue_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE stations (
 station_key TEXT PRIMARY KEY, provider TEXT, provider_station_id TEXT, name TEXT,
 country_code TEXT, subdivision_code TEXT, latitude REAL, longitude REAL,
 elevation_m REAL, timezone TEXT, daily_boundary TEXT
);
CREATE TABLE station_year_quality (
 station_key TEXT, year INTEGER, expected_days INTEGER, observed_days INTEGER,
 complete_year INTEGER, longest_gap_days INTEGER
);
CREATE TABLE suitability_assessments (
 station_key TEXT, requested_start TEXT, requested_end TEXT, purpose TEXT,
 level TEXT, findings_json TEXT
);
CREATE TABLE station_inventory (station_key TEXT, temporal_resolution TEXT);
CREATE TABLE daily_observations (
 station_key TEXT, observation_date TEXT, normalized_amount_mm REAL,
 availability TEXT, qualifiers_json TEXT
);
"""


def _catalogue(
    path: Path, *, schema_version: int = 2, production_ready: bool = False
) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(SCHEMA)
    metadata = {
        "catalogue_version": "2025.1",
        "data_cutoff": "2025-12-31",
        "released_at": "2026-07-29",
        "schema_version": str(schema_version),
        "assessment_engine_version": "0.2.0",
        "methodology_version": "0.2.0",
        "scope": "synthetic NY/ON prototype",
        "production_ready": str(production_ready).lower(),
    }
    connection.executemany("INSERT INTO catalogue_metadata VALUES (?, ?)", metadata.items())
    connection.execute(
        "INSERT INTO stations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("ACIS:ALB", "ACIS", "ALB", "Albany", "US", "NY", 42.65, -73.75, 89.0, "America/New_York", "midnight"),
    )
    connection.execute(
        "INSERT INTO station_year_quality VALUES (?, ?, ?, ?, ?, ?)",
        ("ACIS:ALB", 2025, 365, 365, 1, 0),
    )
    connection.execute(
        "INSERT INTO suitability_assessments VALUES (?, ?, ?, ?, ?, ?)",
        ("ACIS:ALB", "2025-01-01", "2025-12-31", "long_term_yield", "recommended", "[]"),
    )
    connection.execute("INSERT INTO station_inventory VALUES (?, ?)", ("ACIS:ALB", "daily"))
    connection.executemany(
        "INSERT INTO daily_observations VALUES (?, ?, ?, ?, ?)",
        [
            ("ACIS:ALB", "2025-01-01", 25.4, "observed", "[]"),
            ("ACIS:ALB", "2025-01-02", None, "missing", '["estimated"]'),
        ],
    )
    connection.commit()
    connection.close()


def test_open_recommend_import_and_project_provenance(tmp_path: Path) -> None:
    path = tmp_path / "catalogue.sqlite"
    _catalogue(path)

    with CatalogueManager.open(path) as catalogue:
        recommendations = catalogue.recommendations_nearby(
            latitude=42.66,
            longitude=-73.76,
            start_year=2025,
            end_year=2025,
            radius_km=50.0,
        )
        rainfall = catalogue.import_daily_rainfall(
            "ACIS:ALB", date(2025, 1, 1), date(2025, 1, 2)
        )
        config = ProjectConfig(name="Catalogue project")
        apply_catalogue_provenance(config, recommendations[0], catalogue.metadata)

    assert recommendations[0].suitability_level == "recommended"
    assert recommendations[0].timezone == "America/New_York"
    assert recommendations[0].daily_boundary == "midnight"
    assert rainfall["Precipitation"].tolist() == [1.0, 0.0]
    assert rainfall.attrs["known_missing_dates"] == ["2025-01-02"]
    assert rainfall.attrs["observation_qualifiers"] == {"2025-01-02": ["estimated"]}
    assert config.precipitation_catalogue_version == "2025.1"
    assert config.precipitation_catalogue_station_key == "ACIS:ALB"
    assert not config.precipitation_catalogue_production_ready


def test_rejects_unsupported_catalogue_schema(tmp_path: Path) -> None:
    path = tmp_path / "future.sqlite"
    _catalogue(path, schema_version=3)

    with pytest.raises(ValueError, match="Unsupported catalogue schema 3"):
        CatalogueManager.open(path)


def test_discovery_is_deterministic(tmp_path: Path) -> None:
    first = tmp_path / "b.sqlite"
    second = tmp_path / "A.sqlite"
    _catalogue(first)
    _catalogue(second)

    assert CatalogueManager.discover((tmp_path,)) == (second.resolve(), first.resolve())


def test_install_is_validated_atomic_and_idempotent(tmp_path: Path) -> None:
    source = tmp_path / "source.sqlite"
    install_dir = tmp_path / "installed"
    _catalogue(source)

    first = install_catalogue(source, install_dir)
    second = install_catalogue(source, install_dir)

    assert first == second
    assert first.name == "precipitation-quality-2025.1.sqlite"
    with CatalogueManager.open(first) as catalogue:
        assert catalogue.metadata.catalogue_version == "2025.1"


def test_preferred_catalogue_prioritizes_production_release(tmp_path: Path) -> None:
    prototype = tmp_path / "prototype.sqlite"
    production = tmp_path / "production.sqlite"
    _catalogue(prototype)
    _catalogue(production, production_ready=True)

    selected = preferred_catalogue((prototype, production))

    assert selected is not None
    assert selected[0] == production
    assert selected[1].production_ready
