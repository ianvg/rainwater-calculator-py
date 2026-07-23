from __future__ import annotations

import pandas as pd

from rainwater_app.candidate_service import CandidateAnalysisService
from rainwater_app.defaults import default_project_config


def test_candidate_service_adds_financials_and_stably_sorts_missing_values() -> None:
    config = default_project_config("Candidates")
    config.financial_parameters.water_rate = 10.0
    config.financial_parameters.installed_cost = 1_000.0
    curve = pd.DataFrame(
        {
            "TankSizeGallons": [2_000.0, 1_000.0, 3_000.0],
            "ReliabilityPercent": [90.0, 80.0, 95.0],
            "AverageAnnualRainwaterSuppliedGallons": [50_000.0, 40_000.0, pd.NA],
            "AverageAnnualSewerEligibleRainwaterSuppliedGallons": [0.0, 0.0, pd.NA],
            "AverageAnnualPumpFlowGallons": [0.0, 0.0, pd.NA],
        }
    )
    service = CandidateAnalysisService(config)

    result = service.build(curve)
    sorted_result = service.sorted_data(result, "LifecycleNPV", reverse=True)

    assert result["LifecycleNPV"].notna().sum() == 2
    assert sorted_result.iloc[-1]["TankSizeGallons"] == 3_000.0


def test_candidate_service_formats_units_and_export_columns() -> None:
    config = default_project_config("Metric candidates")
    config.unit_system = "Metric"
    config.country_code = "CAN"
    service = CandidateAnalysisService(config)
    data = pd.DataFrame(
        {"TankSizeGallons": [1_000.0], "ReliabilityPercent": [90.0]}
    )

    rows = service.display_rows(data, ("TankSizeGallons", "ReliabilityPercent"))
    exported = service.export_data(data)

    assert rows == [["3,785", "90"]]
    assert "TankSize (L)" in exported
