from __future__ import annotations

from dataclasses import dataclass


MANUAL_SIZING_METHOD = "manual"
GUIDED_SIZING_METHOD = "guided"
FIRST_FLUSH_SIZING_METHODS = {MANUAL_SIZING_METHOD, GUIDED_SIZING_METHOD}

CODE_MINIMUM_PRESET = "code_minimum"
ENHANCED_NONPOTABLE_PRESET = "enhanced_nonpotable"
CONSERVATIVE_PRESET = "conservative"
CUSTOM_SITE_TESTED_PRESET = "custom_site_tested"
FIRST_FLUSH_DESIGN_PRESETS = {
    CODE_MINIMUM_PRESET,
    ENHANCED_NONPOTABLE_PRESET,
    CONSERVATIVE_PRESET,
    CUSTOM_SITE_TESTED_PRESET,
}

SIZING_METHOD_LABELS = {
    MANUAL_SIZING_METHOD: "Manual per-surface depth (legacy)",
    GUIDED_SIZING_METHOD: "Guided three-layer sizing",
}
DESIGN_PRESET_LABELS = {
    CODE_MINIMUM_PRESET: "Code/minimum baseline",
    ENHANCED_NONPOTABLE_PRESET: "Enhanced non-potable (1.2 mm)",
    CONSERVATIVE_PRESET: "Conservative/high-deposition (2.0 mm)",
    CUSTOM_SITE_TESTED_PRESET: "Custom/site-tested with baseline floor",
}


@dataclass(frozen=True)
class RegulatoryBaseline:
    depth_mm: float
    label: str
    source: str


@dataclass(frozen=True)
class FirstFlushGuidance:
    baseline: RegulatoryBaseline
    preset: str
    preset_depth_mm: float | None

    @property
    def automatic_target_mm(self) -> float:
        """Return the floor applied before any larger site-specific surface depth."""
        return max(self.baseline.depth_mm, self.preset_depth_mm or 0.0)


def normalize_first_flush_sizing_method(value: object) -> str:
    normalized = str(value).strip().casefold()
    return normalized if normalized in FIRST_FLUSH_SIZING_METHODS else MANUAL_SIZING_METHOD


def normalize_first_flush_design_preset(value: object) -> str:
    normalized = str(value).strip().casefold()
    return normalized if normalized in FIRST_FLUSH_DESIGN_PRESETS else CODE_MINIMUM_PRESET


def _normalized_region(value: object) -> str:
    return " ".join(str(value).strip().casefold().replace(".", "").split())


def regulatory_baseline(country_code: object, state_or_province: object = "") -> RegulatoryBaseline:
    """Return a documented planning baseline for the supported jurisdictions.

    Coordinates alone are deliberately not treated as a water-quality predictor. The
    project's country and state/province identify the jurisdiction; unsupported places
    return a zero floor with a prompt to verify local requirements.
    """
    country = str(country_code).strip().upper()
    region = _normalized_region(state_or_province)

    if country == "AUS":
        return RegulatoryBaseline(
            0.20,
            "Australia planning baseline",
            "Australian YourHome rule of thumb: 10 L per 50 m2 of roof",
        )
    if country == "CAN":
        return RegulatoryBaseline(
            0.30,
            "Canada code baseline",
            "Canadian model plumbing-code provision: at least 0.3 L/m2 of roof",
        )
    if country == "USA":
        if region in {"tx", "texas"}:
            return RegulatoryBaseline(
                0.41,
                "Texas minimum",
                "Texas Water Development Board: 10 gal per 1,000 ft2 of roof",
            )
        if region in {"wa", "washington", "washington state"}:
            return RegulatoryBaseline(
                0.508,
                "Washington requirement",
                "Washington plumbing provision: first 0.02 inch per event",
            )
        if region in {"dc", "district of columbia", "washington dc"}:
            return RegulatoryBaseline(
                0.508,
                "District of Columbia lower baseline",
                "DC guidance range: 0.02 to 0.06 inch; lower bound used as the floor",
            )

    return RegulatoryBaseline(
        0.0,
        "No built-in regulatory baseline",
        "Verify the applicable local code or authority requirement",
    )


def first_flush_guidance(
    country_code: object,
    state_or_province: object,
    preset: object,
) -> FirstFlushGuidance:
    normalized_preset = normalize_first_flush_design_preset(preset)
    preset_depths = {
        CODE_MINIMUM_PRESET: None,
        ENHANCED_NONPOTABLE_PRESET: 1.2,
        CONSERVATIVE_PRESET: 2.0,
        CUSTOM_SITE_TESTED_PRESET: None,
    }
    return FirstFlushGuidance(
        baseline=regulatory_baseline(country_code, state_or_province),
        preset=normalized_preset,
        preset_depth_mm=preset_depths[normalized_preset],
    )
