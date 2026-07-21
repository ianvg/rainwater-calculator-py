import pandas as pd

from rainwater_app.recommendations import recommend_tank_sizes, selected_design_warnings


def _candidate_data() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "TankSizeGallons": [1000.0, 2000.0, 3000.0, 4000.0],
            "ReliabilityPercent": [70.0, 85.0, 86.0, 86.4],
            "RainwaterSuppliedGallons": [700.0, 850.0, 860.0, 864.0],
            "OverflowGallons": [50.0, 100.0, 200.0, 500.0],
            "TreatmentLossGallons": [10.0, 10.0, 10.0, 10.0],
            "NetAnnualSavings": [100.0, 140.0, 150.0, 151.0],
            "SimplePaybackYears": [14.0, 10.0, 8.0, 9.0],
        }
    )


def test_recommendations_apply_target_knee_payback_and_nearby_rules() -> None:
    result = recommend_tank_sizes(
        _candidate_data(),
        reliability_target_percent=80.0,
        marginal_gain_threshold=1.0,
        selected_tank_size_gallons=2000.0,
    )

    by_role = {item.role: item for item in result.recommendations}
    assert by_role["Smallest tank meeting reliability target"].tank_size_gallons == 2000.0
    assert by_role["Reliability-versus-capacity knee"].tank_size_gallons == 2000.0
    assert by_role["Lowest-payback feasible candidate"].tank_size_gallons == 3000.0
    assert all(item.tank_size_gallons not in {2000.0, 3000.0} for item in result.alternatives)
    assert any(item.tank_size_gallons == 1000.0 for item in result.alternatives)


def test_recommendations_do_not_invent_unavailable_target_or_payback() -> None:
    data = _candidate_data().drop(columns=["SimplePaybackYears"])
    result = recommend_tank_sizes(
        data,
        reliability_target_percent=99.0,
        marginal_gain_threshold=0.0,
    )

    roles = {item.role for item in result.recommendations}
    assert "Smallest tank meeting reliability target" not in roles
    assert "Lowest-payback feasible candidate" not in roles


def test_selected_design_warnings_cover_hydraulic_data_and_finances() -> None:
    warnings = selected_design_warnings(
        _candidate_data(),
        selected_tank_size_gallons=4000.0,
        reliability_target_percent=90.0,
        financial_configured=False,
        missing_calendar_days=3,
        incomplete_calendar_years=1,
        excessive_overflow_fraction=0.25,
    )

    assert any("below the 90.0%" in warning for warning in warnings)
    assert any("overflow" in warning for warning in warnings)
    assert any("3 missing day" in warning for warning in warnings)
    assert any("1 incomplete calendar year" in warning for warning in warnings)
    assert any("Financial rates and costs" in warning for warning in warnings)


def test_selected_design_warnings_disclose_rainfall_quality_details() -> None:
    warnings = selected_design_warnings(
        _candidate_data(),
        selected_tank_size_gallons=4000.0,
        reliability_target_percent=80.0,
        financial_configured=True,
        missing_calendar_days=12,
        incomplete_calendar_years=2,
        completeness_percent=98.4,
        completeness_rating="Good",
        partial_years=(2022, 2024),
        longest_missing_period=("2024-04-01", "2024-04-07", 7),
        rainfall_data_type="unclassified",
    )

    assert any("2024-04-01 to 2024-04-07" in warning for warning in warnings)
    assert any("2022, 2024" in warning for warning in warnings)
    assert any("98.40% (Good)" in warning for warning in warnings)
    assert any("unclassified" in warning for warning in warnings)
