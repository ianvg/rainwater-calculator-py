from __future__ import annotations

import pandas as pd

from rainwater_app.defaults import default_project_config
from rainwater_app.equipment_catalog import (
    candidate_from_product,
    evaluate_combination_compatibility,
    evaluate_product_eligibility,
    update_candidate_snapshot,
)
from rainwater_app.optimization import optimize_indirect_system


def product(product_id: str, category: str, model: str, **properties: object) -> dict[str, object]:
    return {
        "id": product_id,
        "category": category,
        "manufacturer": "Approved Co",
        "model": model,
        "capacity": 100.0 if category != "Primary tank" else 1_000.0,
        "installed_cost": 100.0,
        "properties": properties,
        "dimensions": {},
        "tags": ["indoor"],
        "active": True,
    }


def test_missing_required_attribute_warns_by_default_and_can_be_required() -> None:
    pump = product("pump", "Filtration pump", "Pump")
    eligible, reasons = evaluate_product_eligibility(pump, {"required_voltage": "230"})
    assert eligible is True
    assert reasons == ["Missing voltage"]

    eligible, reasons = evaluate_product_eligibility(pump, {"required_standards": ["UL 778"]})
    assert eligible is True
    assert reasons == ["Missing required standard(s): UL 778"]

    eligible, reasons = evaluate_product_eligibility(
        pump, {"required_voltage": "230", "require_constraint_values": True}
    )
    assert eligible is False
    assert reasons == ["Missing voltage"]


def test_flow_range_compatibility_is_optional() -> None:
    pump = product("pump", "Filtration pump", "100 GPM pump", rated_flow_gpm=100)
    filtration = product(
        "filter", "Filtration unit", "Small filter", minimum_flow_gpm=10, maximum_flow_gpm=50
    )
    assert evaluate_combination_compatibility((pump, filtration), {})[0] is True

    compatible, reasons = evaluate_combination_compatibility(
        (pump, filtration), {"enforce_flow_compatibility": True}
    )
    assert compatible is False
    assert "outside" in reasons[0]


def test_library_update_preserves_project_overrides() -> None:
    original = product("pump", "Filtration pump", "Original", power_kw=.5)
    candidate = candidate_from_product(original)
    candidate["project_overrides"] = {"installed_cost": 777.0}
    replacement = product("pump", "Filtration pump", "Updated", power_kw=.7)

    updated = update_candidate_snapshot(candidate, replacement)

    assert updated["product_snapshot"]["model"] == "Updated"
    assert updated["project_overrides"] == {"installed_cost": 777.0}


def test_optimizer_uses_only_compatible_four_component_combinations() -> None:
    config = default_project_config("Catalog compatibility")
    candidates = [
        candidate_from_product(product("tank", "Primary tank", "Tank")),
        candidate_from_product(product("pump", "Filtration pump", "Pump", power_kw=.5, rated_flow_gpm=100)),
        candidate_from_product(product(
            "small-filter", "Filtration unit", "Small filter",
            minimum_flow_gpm=10, maximum_flow_gpm=50,
        )),
        candidate_from_product(product(
            "right-filter", "Filtration unit", "Right filter",
            minimum_flow_gpm=50, maximum_flow_gpm=150,
        )),
        candidate_from_product(product("buffer", "Buffer tank", "Buffer")),
    ]
    config.optimization_parameters.equipment_candidates = candidates
    config.optimization_parameters.equipment_constraints = {"enforce_flow_compatibility": True}
    config.optimization_parameters.minimum_reliability_percent = 0.0
    rainfall = pd.DataFrame({"Date": [pd.Timestamp("2025-01-01")], "Precipitation": [0.0]})

    results = optimize_indirect_system(config, rainfall)

    assert len(results) == 1
    assert results[0].filtration_unit.name == "Right filter"
    assert results[0].total_installed_cost == 400.0
