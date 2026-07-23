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
    rated_flow = float(properties.get("rated_flow_gpm", 0.0))
    return {
        "id": product_id,
        "category": category,
        "manufacturer": "Approved Co",
        "model": model,
        "capacity": (
            1_000.0 if category == "Primary tank"
            else rated_flow * 60.0 if rated_flow else 100.0
        ),
        "installed_cost": 100.0,
        "properties": properties,
        "dimensions": {},
        "tags": ["indoor"],
        "active": True,
    }


def test_missing_required_attribute_warns_by_default_and_can_be_required() -> None:
    pump = product(
        "pump", "Filtration pump", "Pump", rated_flow_gpm=20, pump_type="External"
    )
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


def test_transfer_pump_must_match_filtration_system_flow() -> None:
    pump = product("pump", "Transfer pump", "20 GPM pump", rated_flow_gpm=20)
    filtration = product(
        "filter", "Filtration system", "15 GPM system", rated_flow_gpm=15,
        minimum_flow_gpm=15, maximum_flow_gpm=15,
    )
    compatible, reasons = evaluate_combination_compatibility((pump, filtration), {})
    assert compatible is False
    assert "does not match" in reasons[0]

    matching = product(
        "filter-20", "Filtration system", "20 GPM system", rated_flow_gpm=20,
        minimum_flow_gpm=20, maximum_flow_gpm=20,
    )
    assert evaluate_combination_compatibility((pump, matching), {})[0] is True


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
        candidate_from_product(product("pump", "Transfer pump", "Pump", power_kw=.5, rated_flow_gpm=20)),
        candidate_from_product(product(
            "small-filter", "Filtration system", "15 GPM system", rated_flow_gpm=15,
            minimum_flow_gpm=15, maximum_flow_gpm=15,
        )),
        candidate_from_product(product(
            "right-filter", "Filtration system", "20 GPM system", rated_flow_gpm=20,
            minimum_flow_gpm=20, maximum_flow_gpm=20,
        )),
        candidate_from_product(product("buffer", "Buffer tank", "Buffer")),
    ]
    config.optimization_parameters.equipment_candidates = candidates
    config.optimization_parameters.equipment_constraints = {"enforce_flow_compatibility": True}
    config.optimization_parameters.minimum_reliability_percent = 0.0
    rainfall = pd.DataFrame({"Date": [pd.Timestamp("2025-01-01")], "Precipitation": [0.0]})

    results = optimize_indirect_system(config, rainfall)

    assert len(results) == 1
    assert results[0].filtration_unit.name == "20 GPM system"
    assert results[0].total_installed_cost == 400.0
