"""Read-only integration with precipitation-quality catalogue schema v2."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import json
from math import asin, cos, radians, sin, sqrt
from pathlib import Path
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
    distance_km: float
    elevation_m: float | None
    coverage_percent: float
    complete_years: int
    longest_gap_days: int
    suitability_level: str
    finding_codes: tuple[str, ...]

    @property
    def source_label(self) -> str:
        return f"{self.name} ({self.provider}:{self.provider_station_id})"


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
        purpose: str = "long_term_yield",
        radius_km: float = 250.0,
        limit: int = 10,
    ) -> tuple[StationRecommendation, ...]:
        if purpose not in {"long_term_yield", "storm_event"}:
            raise ValueError("Purpose must be long_term_yield or storm_event.")
        if end_year < start_year:
            raise ValueError("End year must not precede start year.")
        rows = self._connection.execute(
            """
            SELECT s.*, SUM(q.expected_days) AS expected_days,
                   SUM(q.observed_days) AS observed_days,
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
            coverage = 100.0 * int(row["observed_days"]) / int(row["expected_days"])
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
                    distance_km=distance,
                    elevation_m=(float(row["elevation_m"]) if row["elevation_m"] is not None else None),
                    coverage_percent=coverage,
                    complete_years=int(row["complete_years"]),
                    longest_gap_days=int(row["longest_gap_days"]),
                    suitability_level=level,
                    finding_codes=findings,
                )
            )
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
