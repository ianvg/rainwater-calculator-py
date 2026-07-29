"""Read-only integration with precipitation-quality catalogue schema v2."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date
import json
from math import asin, cos, radians, sin, sqrt
import shutil
from pathlib import Path
import tempfile
import sqlite3
from types import TracebackType

import pandas as pd


SUPPORTED_CATALOGUE_SCHEMA = 2
MM_PER_INCH = 25.4


@dataclass(frozen=True)
class CatalogueMetadata:
    catalogue_version: str
    data_cutoff: date
    released_at: date
    schema_version: int
    assessment_engine_version: str
    methodology_version: str
    scope: str
    production_ready: bool


@dataclass(frozen=True)
class StationRecommendation:
    station_key: str
    provider: str
    provider_station_id: str
    name: str
    country_code: str
    subdivision_code: str
    latitude: float
    longitude: float
    timezone: str
    daily_boundary: str
    distance_km: float
    elevation_m: float | None
    coverage_percent: float
    missing_days: int
    complete_years: int
    longest_gap_days: int
    meets_coverage_filter: bool
    suitability_level: str
    finding_codes: tuple[str, ...]

    @property
    def source_label(self) -> str:
        return f"{self.name} ({self.provider}:{self.provider_station_id})"


@dataclass(frozen=True)
class CatalogueCoverage:
    """Calendar-day coverage stored for one provider station and year range."""

    provider: str
    provider_station_id: str
    start_year: int
    end_year: int
    expected_days: int
    observed_days: int
    missing_days: int

    @property
    def completeness_percent(self) -> float:
        return 100.0 * self.observed_days / self.expected_days


class CatalogueManager:
    """Open, validate, query, and import from an installed offline catalogue."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        path: Path,
        metadata: CatalogueMetadata,
    ) -> None:
        self._connection = connection
        self.path = path
        self.metadata = metadata

    @staticmethod
    def discover(search_paths: tuple[Path, ...]) -> tuple[Path, ...]:
        """Return valid-looking SQLite files without opening provider networks."""
        candidates: set[Path] = set()
        for root in search_paths:
            if root.is_file():
                candidates.add(root.resolve())
            elif root.is_dir():
                candidates.update(item.resolve() for item in root.glob("*.sqlite"))
        return tuple(sorted(candidates, key=lambda item: str(item).casefold()))

    @classmethod
    def open(cls, path: str | Path) -> "CatalogueManager":
        resolved = Path(path).resolve()
        if not resolved.is_file():
            raise FileNotFoundError(f"Precipitation catalogue not found: {resolved}")
        connection = sqlite3.connect(f"{resolved.as_uri()}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            integrity = connection.execute("PRAGMA quick_check").fetchone()[0]
            if str(integrity).casefold() != "ok":
                raise ValueError(f"Catalogue integrity check failed: {integrity}")
            rows = connection.execute("SELECT key, value FROM catalogue_metadata")
            values = {str(row["key"]): str(row["value"]) for row in rows}
            required = {
                "catalogue_version",
                "data_cutoff",
                "released_at",
                "schema_version",
                "assessment_engine_version",
                "methodology_version",
            }
            missing = sorted(required.difference(values))
            if missing:
                raise ValueError("Catalogue metadata is missing: " + ", ".join(missing))
            schema_version = int(values["schema_version"])
            if schema_version != SUPPORTED_CATALOGUE_SCHEMA:
                raise ValueError(
                    f"Unsupported catalogue schema {schema_version}; "
                    f"expected {SUPPORTED_CATALOGUE_SCHEMA}."
                )
            metadata = CatalogueMetadata(
                catalogue_version=values["catalogue_version"],
                data_cutoff=date.fromisoformat(values["data_cutoff"]),
                released_at=date.fromisoformat(values["released_at"]),
                schema_version=schema_version,
                assessment_engine_version=values["assessment_engine_version"],
                methodology_version=values["methodology_version"],
                scope=values.get("scope", "unspecified"),
                production_ready=values.get("production_ready", "false").casefold() == "true",
            )
        except Exception:
            connection.close()
            raise
        return cls(connection, resolved, metadata)

    def recommendations_nearby(
        self,
        *,
        latitude: float,
        longitude: float,
        start_year: int,
        end_year: int,
        purpose: str | None = "long_term_yield",
        radius_km: float = 250.0,
        limit: int = 10,
    ) -> tuple[StationRecommendation, ...]:
        if purpose is not None and purpose not in {"long_term_yield", "storm_event"}:
            raise ValueError("Purpose must be long_term_yield or storm_event.")
        if end_year < start_year:
            raise ValueError("End year must not precede start year.")
        has_summary = self._connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' "
            "AND name='station_quality_summary'"
        ).fetchone() is not None
        if has_summary:
            rows = self._connection.execute(
                """
                SELECT s.*, q.expected_days, q.observed_days, q.missing_days,
                       0 AS complete_years, q.longest_gap_days,
                       q.coverage_percent, q.meets_coverage_filter
                FROM stations s JOIN station_quality_summary q USING(station_key)
                WHERE q.meets_coverage_filter = 1
                """
            ).fetchall()
        else:
            rows = self._connection.execute(
                """
                SELECT s.*, SUM(q.expected_days) AS expected_days,
                       SUM(q.observed_days) AS observed_days,
                       SUM(q.expected_days) - SUM(q.observed_days) AS missing_days,
                       SUM(q.complete_year) AS complete_years,
                       MAX(q.longest_gap_days) AS longest_gap_days
                FROM stations s
                JOIN station_year_quality q ON q.station_key = s.station_key
                WHERE q.year BETWEEN ? AND ?
                GROUP BY s.station_key
                """,
                (start_year, end_year),
            ).fetchall()
        results: list[StationRecommendation] = []
        for row in rows:
            distance = _haversine_km(latitude, longitude, row["latitude"], row["longitude"])
            if distance > radius_km:
                continue
            coverage = (
                float(row["coverage_percent"]) if has_summary
                else 100.0 * int(row["observed_days"]) / int(row["expected_days"])
            )
            if purpose is None:
                level, findings = "not_assessed", ()
            else:
                assessment = self._connection.execute(
                    """
                    SELECT level, findings_json
                    FROM suitability_assessments
                    WHERE station_key = ? AND purpose = ?
                      AND requested_start <= ? AND requested_end >= ?
                    ORDER BY requested_start DESC, requested_end ASC
                    LIMIT 1
                    """,
                    (
                        row["station_key"],
                        purpose,
                        date(start_year, 1, 1).isoformat(),
                        date(end_year, 12, 31).isoformat(),
                    ),
                ).fetchone()
                level, findings = _assessment_evidence(
                    assessment,
                    purpose=purpose,
                    coverage_percent=coverage,
                    complete_years=int(row["complete_years"]),
                    longest_gap_days=int(row["longest_gap_days"]),
                    station_key=str(row["station_key"]),
                    connection=self._connection,
                )
            results.append(
                StationRecommendation(
                    station_key=str(row["station_key"]),
                    provider=str(row["provider"]),
                    provider_station_id=str(row["provider_station_id"]),
                    name=str(row["name"]),
                    country_code=str(row["country_code"]),
                    subdivision_code=str(row["subdivision_code"] or ""),
                    latitude=float(row["latitude"]),
                    longitude=float(row["longitude"]),
                    timezone=str(row["timezone"] or ""),
                    daily_boundary=str(row["daily_boundary"] or ""),
                    distance_km=distance,
                    elevation_m=(float(row["elevation_m"]) if row["elevation_m"] is not None else None),
                    coverage_percent=coverage,
                    missing_days=int(row["missing_days"]),
                    complete_years=int(row["complete_years"]),
                    longest_gap_days=int(row["longest_gap_days"]),
                    meets_coverage_filter=(
                        bool(row["meets_coverage_filter"]) if has_summary
                        else coverage >= 95.0 and int(row["longest_gap_days"]) <= 31
                    ),
                    suitability_level=level,
                    finding_codes=findings,
                )
            )
        if purpose is None:
            results.sort(
                key=lambda item: (
                    -item.coverage_percent,
                    item.distance_km,
                    item.name.casefold(),
                )
            )
        else:
            level_rank = {"recommended": 0, "suitable_with_caveats": 1, "unsuitable": 2}
            results.sort(
                key=lambda item: (
                    level_rank.get(item.suitability_level, 3),
                    -item.coverage_percent,
                    item.distance_km,
                    item.name.casefold(),
                )
            )
        return tuple(results[: max(limit, 0)])

    def coverage_for_stations(
        self,
        *,
        provider: str,
        provider_station_ids: tuple[str, ...],
        start_year: int,
        end_year: int,
    ) -> dict[str, CatalogueCoverage]:
        """Return complete catalogue coverage summaries keyed by provider station ID.

        A station is omitted when even one requested calendar year is absent. This
        prevents a partial catalogue period from being presented as coverage for the
        whole weather-import request.
        """
        if end_year < start_year:
            raise ValueError("Coverage end year must not precede its start year.")
        requested_ids = {
            station_id.strip().casefold(): station_id.strip()
            for station_id in provider_station_ids
            if station_id.strip()
        }
        if not requested_ids:
            return {}
        rows = self._connection.execute(
            """
            SELECT s.provider_station_id,
                   COUNT(*) AS year_count,
                   SUM(q.expected_days) AS expected_days,
                   SUM(q.observed_days) AS observed_days
            FROM stations s
            JOIN station_year_quality q ON q.station_key = s.station_key
            WHERE UPPER(s.provider) = UPPER(?) AND q.year BETWEEN ? AND ?
            GROUP BY s.station_key, s.provider_station_id
            """,
            (provider, start_year, end_year),
        ).fetchall()
        expected_year_count = end_year - start_year + 1
        results: dict[str, CatalogueCoverage] = {}
        for row in rows:
            catalogue_id = str(row["provider_station_id"])
            requested_id = requested_ids.get(catalogue_id.casefold())
            if requested_id is None or int(row["year_count"]) != expected_year_count:
                continue
            expected_days = int(row["expected_days"])
            observed_days = int(row["observed_days"])
            results[requested_id] = CatalogueCoverage(
                provider=provider.upper(),
                provider_station_id=requested_id,
                start_year=start_year,
                end_year=end_year,
                expected_days=expected_days,
                observed_days=observed_days,
                missing_days=expected_days - observed_days,
            )
        return results

    def import_daily_rainfall(
        self, station_key: str, start: date, end: date
    ) -> pd.DataFrame:
        """Return calculator rainfall in inches with missing dates explicitly tagged."""
        if end < start:
            raise ValueError("Rainfall end date must not precede its start date.")
        rows = self._connection.execute(
            """
            SELECT observation_date, normalized_amount_mm, availability, qualifiers_json
            FROM daily_observations
            WHERE station_key = ? AND observation_date BETWEEN ? AND ?
            ORDER BY observation_date
            """,
            (station_key, start.isoformat(), end.isoformat()),
        ).fetchall()
        if not rows:
            raise ValueError(f"No catalogue observations found for station {station_key}.")
        missing_dates: list[str] = []
        qualifier_by_date: dict[str, list[str]] = {}
        amounts: list[float] = []
        dates: list[pd.Timestamp] = []
        for row in rows:
            observed_on = str(row["observation_date"])
            dates.append(pd.Timestamp(observed_on))
            qualifiers = list(json.loads(row["qualifiers_json"]))
            if qualifiers:
                qualifier_by_date[observed_on] = qualifiers
            if row["availability"] == "missing" or row["normalized_amount_mm"] is None:
                missing_dates.append(observed_on)
                amounts.append(0.0)
            else:
                amounts.append(float(row["normalized_amount_mm"]) / MM_PER_INCH)
        rainfall = pd.DataFrame({"Date": dates, "Precipitation": amounts})
        rainfall.attrs.update(
            {
                "known_missing_dates": missing_dates,
                "observation_qualifiers": qualifier_by_date,
                "catalogue_version": self.metadata.catalogue_version,
                "catalogue_schema_version": self.metadata.schema_version,
                "catalogue_station_key": station_key,
                "catalogue_scope": self.metadata.scope,
                "catalogue_production_ready": self.metadata.production_ready,
                "precipitation_unit": "inch",
            }
        )
        return rainfall

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> "CatalogueManager":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()


def apply_catalogue_provenance(config: object, recommendation: StationRecommendation, metadata: CatalogueMetadata) -> None:
    """Attach a selected catalogue station and release identity to a project config."""
    config.rainfall_source_label = recommendation.source_label
    config.rainfall_data_type = "observed"
    config.rainfall_temporal_resolution = "daily"
    config.weather_station_latitude = recommendation.latitude
    config.weather_station_longitude = recommendation.longitude
    config.precipitation_catalogue_version = metadata.catalogue_version
    config.precipitation_catalogue_schema_version = metadata.schema_version
    config.precipitation_catalogue_station_key = recommendation.station_key
    config.precipitation_catalogue_scope = metadata.scope
    config.precipitation_catalogue_production_ready = metadata.production_ready


def install_catalogue(source: str | Path, install_dir: str | Path) -> Path:
    """Validate and atomically copy a catalogue into the calculator data directory."""
    source_path = Path(source).resolve()
    with CatalogueManager.open(source_path) as catalogue:
        version = catalogue.metadata.catalogue_version
    destination_dir = Path(install_dir).resolve()
    destination_dir.mkdir(parents=True, exist_ok=True)
    base_name = f"precipitation-quality-{version}"
    source_digest = _file_sha256(source_path)
    destination = destination_dir / f"{base_name}.sqlite"
    suffix = 2
    while destination.exists():
        if _file_sha256(destination) == source_digest:
            return destination
        destination = destination_dir / f"{base_name}-{suffix}.sqlite"
        suffix += 1
    with tempfile.NamedTemporaryFile(
        dir=destination_dir, prefix=f".{base_name}-", suffix=".tmp", delete=False
    ) as temporary:
        temporary_path = Path(temporary.name)
    try:
        shutil.copyfile(source_path, temporary_path)
        with CatalogueManager.open(temporary_path):
            pass
        temporary_path.replace(destination)
    finally:
        temporary_path.unlink(missing_ok=True)
    return destination


def preferred_catalogue(paths: tuple[Path, ...]) -> tuple[Path, CatalogueMetadata] | None:
    """Choose the newest supported release, preferring production catalogues."""
    valid: list[tuple[Path, CatalogueMetadata]] = []
    for path in paths:
        try:
            with CatalogueManager.open(path) as catalogue:
                valid.append((path, catalogue.metadata))
        except (OSError, sqlite3.Error, ValueError):
            continue
    if not valid:
        return None
    return max(
        valid,
        key=lambda item: (
            item[1].production_ready,
            item[1].data_cutoff,
            item[1].released_at,
            item[1].catalogue_version,
            str(item[0]).casefold(),
        ),
    )


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _assessment_evidence(
    assessment: sqlite3.Row | None,
    *,
    purpose: str,
    coverage_percent: float,
    complete_years: int,
    longest_gap_days: int,
    station_key: str,
    connection: sqlite3.Connection,
) -> tuple[str, tuple[str, ...]]:
    if assessment is not None:
        findings_payload = json.loads(assessment["findings_json"])
        findings = tuple(
            str(item.get("code", item)) if isinstance(item, dict) else str(item)
            for item in findings_payload
        )
        return str(assessment["level"]), findings
    findings: list[str] = []
    if coverage_percent < 90.0:
        findings.append("insufficient_coverage")
    if purpose == "long_term_yield" and complete_years < 10:
        findings.append("insufficient_complete_years")
    if longest_gap_days > 31:
        findings.append("long_gap")
    if purpose == "storm_event":
        resolutions = {
            str(row[0])
            for row in connection.execute(
                "SELECT temporal_resolution FROM station_inventory WHERE station_key = ?",
                (station_key,),
            )
        }
        if not resolutions.intersection({"hourly", "subhourly"}):
            findings.append("insufficient_temporal_resolution")
    return ("recommended" if not findings else "unsuitable"), tuple(findings)


def _haversine_km(
    latitude_a: float, longitude_a: float, latitude_b: float, longitude_b: float
) -> float:
    earth_radius_km = 6371.0088
    lat_a = radians(latitude_a)
    lat_b = radians(latitude_b)
    delta_latitude = lat_b - lat_a
    delta_longitude = radians(longitude_b - longitude_a)
    haversine = (
        sin(delta_latitude / 2.0) ** 2
        + cos(lat_a) * cos(lat_b) * sin(delta_longitude / 2.0) ** 2
    )
    return 2.0 * earth_radius_km * asin(sqrt(haversine))
