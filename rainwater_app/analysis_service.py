"""UI-independent coordination of the complete tank-analysis workflow."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import pandas as pd

from .engine import (
    AnalysisCancelledError,
    prepare_daily_inputs,
    reliability_curve,
    simulate_hourly_tank,
    simulate_tank,
)
from .models import ProjectConfig


@dataclass(frozen=True)
class AnalysisProgressEvent:
    phase: str
    current: int
    total: int
    tank_size_gallons: float | None = None


@dataclass(frozen=True)
class AnalysisOutcome:
    curve: pd.DataFrame
    selected_tank: pd.DataFrame
    hourly_selected_tank: pd.DataFrame
    comparison_tanks: dict[float, pd.DataFrame]


ProgressCallback = Callable[[AnalysisProgressEvent], None]
CancellationCallback = Callable[[], bool]


class AnalysisService:
    """Run hydraulic analyses without importing or owning a UI toolkit."""

    def run(
        self,
        config: ProjectConfig,
        rainfall_df: pd.DataFrame,
        *,
        include_comparisons: bool = False,
        progress_callback: ProgressCallback | None = None,
        cancel_callback: CancellationCallback | None = None,
    ) -> AnalysisOutcome:
        def cancelled() -> bool:
            return bool(cancel_callback and cancel_callback())

        def report(event: AnalysisProgressEvent) -> None:
            if progress_callback is not None:
                progress_callback(event)

        tank_sizes = sorted(
            {
                *(
                    float(size)
                    for size in range(
                        config.graph_start_gal,
                        config.graph_end_gal + 1,
                        config.graph_step_gal,
                    )
                ),
                float(config.selected_tank_size_gal),
                *(
                    float(size)
                    for size in config.comparison_tank_sizes_gal
                    if include_comparisons
                ),
            }
        )

        def curve_progress(index: int, total: int, tank_size: float) -> None:
            report(AnalysisProgressEvent("reliability_curve", index, total, tank_size))

        prepared_daily = prepare_daily_inputs(config, rainfall_df)
        curve = reliability_curve(
            config,
            rainfall_df,
            tank_sizes,
            progress_callback=curve_progress,
            cancel_callback=cancelled,
            prepared_inputs=prepared_daily,
        )
        if cancelled():
            raise AnalysisCancelledError("Analysis cancelled by user.")
        report(AnalysisProgressEvent("selected_tank", 0, 1, config.selected_tank_size_gal))
        selected = simulate_tank(
            config,
            rainfall_df,
            config.selected_tank_size_gal,
            cancel_callback=cancelled,
            prepared_inputs=prepared_daily,
        )
        hourly = (
            simulate_hourly_tank(
                config,
                rainfall_df,
                config.selected_tank_size_gal,
                cancel_callback=cancelled,
            )
            if config.demand.hourly_schedule_enabled
            else pd.DataFrame()
        )
        comparison_sizes = (
            sorted(set(float(size) for size in config.comparison_tank_sizes_gal))
            if include_comparisons
            else []
        )
        comparisons: dict[float, pd.DataFrame] = {}
        for index, tank_size in enumerate(comparison_sizes, start=1):
            if cancelled():
                raise AnalysisCancelledError("Analysis cancelled by user.")
            report(
                AnalysisProgressEvent(
                    "comparison_tank", index, len(comparison_sizes), tank_size
                )
            )
            comparisons[tank_size] = (
                selected.copy()
                if abs(tank_size - config.selected_tank_size_gal) < 0.01
                else simulate_tank(
                    config,
                    rainfall_df,
                    tank_size,
                    cancel_callback=cancelled,
                    prepared_inputs=prepared_daily,
                )
            )
        if cancelled():
            raise AnalysisCancelledError("Analysis cancelled by user.")
        return AnalysisOutcome(curve, selected, hourly, comparisons)
