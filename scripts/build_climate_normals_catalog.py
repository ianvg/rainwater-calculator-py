from __future__ import annotations

import argparse
import gzip
import json
from pathlib import Path

from rainwater_app.climate_normals import (
    BUNDLED_CATALOG_PATH,
    CLIMATE_NORMALS_PRODUCT_VERSION,
    _catalog_from_bulk_archive,
    climate_normals_bulk_archive_path,
)


def build_catalog(archive_path: Path, output_path: Path) -> int:
    catalog = _catalog_from_bulk_archive(archive_path)
    if not catalog:
        raise ValueError(f"No complete U.S. precipitation-normal stations found in {archive_path}.")
    payload = {
        "product_version": CLIMATE_NORMALS_PRODUCT_VERSION,
        "stations": catalog,
    }
    encoded = json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_suffix(f"{output_path.suffix}.tmp")
    try:
        with temporary_path.open("wb") as raw_output:
            with gzip.GzipFile(fileobj=raw_output, mode="wb", mtime=0) as compressed:
                compressed.write(encoded)
        temporary_path.replace(output_path)
    finally:
        temporary_path.unlink(missing_ok=True)
    return len(catalog)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the bundled NOAA Climate Normals station catalog."
    )
    parser.add_argument(
        "--archive",
        type=Path,
        default=climate_normals_bulk_archive_path(),
        help="Path to NOAA's versioned annual/seasonal by-station tar.gz archive.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=BUNDLED_CATALOG_PATH,
        help="Destination for the deterministic gzip-compressed JSON catalog.",
    )
    args = parser.parse_args()
    station_count = build_catalog(args.archive.resolve(), args.output.resolve())
    print(f"Wrote {station_count:,} stations to {args.output.resolve()}")


if __name__ == "__main__":
    main()
