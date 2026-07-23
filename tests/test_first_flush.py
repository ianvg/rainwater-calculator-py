from __future__ import annotations

import pytest

from rainwater_app.first_flush import (
    CONSERVATIVE_PRESET,
    CUSTOM_SITE_TESTED_PRESET,
    ENHANCED_NONPOTABLE_PRESET,
    first_flush_guidance,
    regulatory_baseline,
)


@pytest.mark.parametrize(
    ("country", "region", "expected_mm"),
    [
        ("AUS", "", 0.20),
        ("CAN", "Ontario", 0.30),
        ("USA", "Texas", 0.41),
        ("USA", "WA", 0.508),
        ("USA", "District of Columbia", 0.508),
    ],
)
def test_supported_location_baselines(country: str, region: str, expected_mm: float) -> None:
    assert regulatory_baseline(country, region).depth_mm == pytest.approx(expected_mm)


def test_unsupported_location_requires_local_verification() -> None:
    baseline = regulatory_baseline("FRA", "Ile-de-France")

    assert baseline.depth_mm == 0.0
    assert "Verify" in baseline.source


def test_enhanced_and_conservative_presets_exceed_lower_location_baseline() -> None:
    enhanced = first_flush_guidance("CAN", "Ontario", ENHANCED_NONPOTABLE_PRESET)
    conservative = first_flush_guidance("CAN", "Ontario", CONSERVATIVE_PRESET)

    assert enhanced.automatic_target_mm == pytest.approx(1.2)
    assert conservative.automatic_target_mm == pytest.approx(2.0)


def test_custom_preset_retains_regulatory_floor() -> None:
    guidance = first_flush_guidance("USA", "Texas", CUSTOM_SITE_TESTED_PRESET)

    assert guidance.automatic_target_mm == pytest.approx(0.41)
