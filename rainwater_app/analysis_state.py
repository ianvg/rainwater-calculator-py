from __future__ import annotations

import hashlib
import json
from dataclasses import asdict

import pandas as pd

from .models import ProjectConfig

ANALYSIS_ALGORITHM_VERSION = 10


def analysis_input_signature(config: ProjectConfig, rainfall_df: pd.DataFrame) -> str:
    rainfall = []
    if "Date" in rainfall_df and "Precipitation" in rainfall_df:
        normalized = rainfall_df[["Date", "Precipitation"]].copy()
        normalized["Date"] = pd.to_datetime(normalized["Date"], errors="coerce")
        normalized["Precipitation"] = pd.to_numeric(normalized["Precipitation"], errors="coerce").fillna(0.0)
        normalized = normalized.dropna(subset=["Date"]).sort_values("Date")
        rainfall = [
            [date.isoformat(), float(precipitation)]
            for date, precipitation in zip(normalized["Date"], normalized["Precipitation"])
        ]

    payload = {
        "algorithm_version": ANALYSIS_ALGORITHM_VERSION,
        "surfaces": [
            {
                "area": float(surface.area),
                "runoff_coefficient": float(surface.runoff_coefficient),
                "first_flush_depth_inches": float(surface.first_flush_depth_inches),
            }
            for surface in config.surfaces
        ],
        "first_flush_antecedent_dry_days": float(config.first_flush_antecedent_dry_days),
        "demand": asdict(config.demand),
        "graph_start_gal": int(config.graph_start_gal),
        "graph_end_gal": int(config.graph_end_gal),
        "graph_step_gal": int(config.graph_step_gal),
        "selected_tank_size_gal": float(config.selected_tank_size_gal),
        "multitank_comparison_enabled": bool(config.multitank_comparison_enabled),
        "comparison_tank_sizes_gal": sorted(float(value) for value in config.comparison_tank_sizes_gal),
        "tank_parameters": asdict(config.tank_parameters),
        "system_type": config.system_type,
        "system_layout": config.system_layout,
        "system_connections": config.system_connections,
        "system_parameters": asdict(config.system_parameters),
        "rainfall": rainfall,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
