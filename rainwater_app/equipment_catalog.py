from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Iterable


EQUIPMENT_CATEGORIES = (
    "Primary tank",
    "Filtration pump",
    "Filtration unit",
    "Buffer tank",
)
CANDIDATE_DISPOSITIONS = ("Candidate", "Fixed", "Excluded")
EQUIPMENT_LIBRARY_SCHEMA_VERSION = 1


def built_in_equipment_library() -> list[dict[str, Any]]:
    """Return illustrative starter products, never vendor recommendations."""
    return [
        _product("builtin-primary-1000", "Primary tank", "PT-1000", 1_000, 4_000),
        _product("builtin-primary-2500", "Primary tank", "PT-2500", 2_500, 6_500),
        _product("builtin-primary-5000", "Primary tank", "PT-5000", 5_000, 9_500),
        _product("builtin-pump-5", "Filtration pump", "FP-5", 300, 1_200, power_kw=.37,
                 rated_flow_gpm=5, required_companion_categories=["Filtration unit"]),
        _product("builtin-pump-10", "Filtration pump", "FP-10", 600, 1_700, power_kw=.55,
                 rated_flow_gpm=10, required_companion_categories=["Filtration unit"]),
        _product("builtin-pump-20", "Filtration pump", "FP-20", 1_200, 2_500, power_kw=1.1,
                 rated_flow_gpm=20, required_companion_categories=["Filtration unit"]),
        _product("builtin-filter-5-15", "Filtration unit", "FU-5-15", 900, 1_100,
                 minimum_flow_gpm=5, maximum_flow_gpm=15,
                 required_companion_categories=["Filtration pump"]),
        _product("builtin-filter-10-25", "Filtration unit", "FU-10-25", 1_500, 1_650,
                 minimum_flow_gpm=10, maximum_flow_gpm=25,
                 required_companion_categories=["Filtration pump"]),
        _product("builtin-buffer-50", "Buffer tank", "BT-50", 50, 700),
        _product("builtin-buffer-100", "Buffer tank", "BT-100", 100, 1_000),
        _product("builtin-buffer-250", "Buffer tank", "BT-250", 250, 1_600),
    ]


def _product(
    product_id: str,
    category: str,
    model: str,
    capacity: float,
    installed_cost: float,
    **properties: Any,
) -> dict[str, Any]:
    return normalize_product({
        "id": product_id,
        "category": category,
        "manufacturer": "Illustrative",
        "model": model,
        "description": "Illustrative planning input; not a vendor quotation.",
        "capacity": float(capacity),
        "installed_cost": float(installed_cost),
        "properties": properties,
        "dimensions": {},
        "tags": [],
        "active": True,
    })


def normalize_product(product: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(product)
    result["id"] = str(result.get("id") or "").strip()
    result["category"] = str(result.get("category") or "").strip()
    result["manufacturer"] = str(result.get("manufacturer") or "").strip()
    result["model"] = str(result.get("model") or result.get("name") or "").strip()
    result["description"] = str(result.get("description") or "").strip()
    result["capacity"] = float(result.get("capacity", 0.0))
    result["installed_cost"] = float(result.get("installed_cost", result.get("cost", 0.0)))
    result["properties"] = dict(result.get("properties") or {})
    if "power_kw" in result:
        result["properties"].setdefault("power_kw", float(result.get("power_kw", 0.0)))
    result["dimensions"] = dict(result.get("dimensions") or {})
    result["tags"] = [str(value).strip() for value in result.get("tags", []) if str(value).strip()]
    result["standards"] = [str(value).strip() for value in result.get("standards", []) if str(value).strip()]
    result["active"] = bool(result.get("active", True))
    return result


def validate_library(products: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = [normalize_product(item) for item in products]
    seen: set[str] = set()
    for item in normalized:
        if not item["id"] or item["id"] in seen:
            raise ValueError("Every equipment product requires a unique stable ID.")
        seen.add(item["id"])
        if item["category"] not in EQUIPMENT_CATEGORIES:
            raise ValueError(f"Unsupported equipment category: {item['category'] or '(blank)'}.")
        if not item["model"] or item["capacity"] <= 0 or item["installed_cost"] < 0:
            raise ValueError("Every product requires a model, positive capacity, and non-negative cost.")
    return normalized


def load_equipment_library(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        products = built_in_equipment_library()
        save_equipment_library(path, products)
        return products
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return validate_library(payload.get("products", []))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return built_in_equipment_library()


def save_equipment_library(path: Path, products: Iterable[dict[str, Any]]) -> None:
    normalized = validate_library(products)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps({
        "schema_version": EQUIPMENT_LIBRARY_SCHEMA_VERSION,
        "products": normalized,
    }, indent=2), encoding="utf-8")
    temporary.replace(path)


def candidate_from_product(product: dict[str, Any], disposition: str = "Candidate") -> dict[str, Any]:
    normalized = normalize_product(product)
    return {
        "product_id": normalized["id"],
        "product_snapshot": normalized,
        "disposition": disposition if disposition in CANDIDATE_DISPOSITIONS else "Candidate",
        "project_overrides": {},
        "exclusion_reason": "",
    }


def effective_candidate_product(candidate: dict[str, Any]) -> dict[str, Any]:
    product = normalize_product(dict(candidate.get("product_snapshot") or {}))
    overrides = dict(candidate.get("project_overrides") or {})
    for key, value in overrides.items():
        if key in {"properties", "dimensions"}:
            product[key].update(dict(value or {}))
        else:
            product[key] = copy.deepcopy(value)
    return normalize_product(product)


def default_project_candidates(products: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [candidate_from_product(item) for item in products if bool(item.get("active", True))]


def update_candidate_snapshot(
    candidate: dict[str, Any], library_product: dict[str, Any]
) -> dict[str, Any]:
    updated = copy.deepcopy(candidate)
    updated["product_id"] = str(library_product["id"])
    updated["product_snapshot"] = normalize_product(library_product)
    return updated


def migrate_legacy_catalog(catalog: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for index, row in enumerate(catalog):
        category = "Buffer tank" if row.get("category") == "Booster tank" else str(row.get("category", ""))
        product = normalize_product({
            "id": f"legacy-{category.casefold().replace(' ', '-')}-{index + 1}",
            "category": category,
            "manufacturer": "Project catalog",
            "model": row.get("name", f"Product {index + 1}"),
            "capacity": row.get("capacity", 0.0),
            "installed_cost": row.get("cost", 0.0),
            "properties": {"power_kw": row.get("power_kw", 0.0)},
        })
        candidates.append(candidate_from_product(product))
    if candidates and not any(
        effective_candidate_product(item)["category"] == "Filtration unit" for item in candidates
    ):
        neutral = _product(
            "legacy-neutral-filter", "Filtration unit", "Existing project filtration", 1_000_000_000,
            0, minimum_flow_gpm=0, maximum_flow_gpm=1_000_000_000,
            required_companion_categories=["Filtration pump"],
        )
        candidates.append(candidate_from_product(neutral))
    return candidates


def default_equipment_constraints() -> dict[str, Any]:
    return {
        "enforce_flow_compatibility": False,
        "require_constraint_values": False,
        "approved_vendors": [],
        "required_tags": [],
        "required_standards": [],
        "required_voltage": "",
        "required_phase": "",
        "required_pressure_class": "",
        "required_connection_size": "",
        "maximum_length": None,
        "maximum_width": None,
        "maximum_height": None,
        "maximum_footprint": None,
        "minimum_access_clearance": None,
        "project_standards": "",
    }


def normalized_constraints(value: dict[str, Any] | None) -> dict[str, Any]:
    constraints = default_equipment_constraints()
    constraints.update(dict(value or {}))
    constraints["approved_vendors"] = [str(v).strip() for v in constraints["approved_vendors"] if str(v).strip()]
    constraints["required_tags"] = [str(v).strip() for v in constraints["required_tags"] if str(v).strip()]
    constraints["required_standards"] = [str(v).strip() for v in constraints["required_standards"] if str(v).strip()]
    return constraints


def evaluate_product_eligibility(
    product: dict[str, Any], constraints: dict[str, Any] | None
) -> tuple[bool, list[str]]:
    item = normalize_product(product)
    rules = normalized_constraints(constraints)
    warnings: list[str] = []
    failures: list[str] = []
    strict = bool(rules["require_constraint_values"])

    def compare_required(label: str, actual: Any, required: Any) -> None:
        if not required:
            return
        if actual in (None, ""):
            (failures if strict else warnings).append(f"Missing {label}")
        elif str(actual).casefold() != str(required).casefold():
            failures.append(f"{label.title()} does not meet project requirement")

    approved = {value.casefold() for value in rules["approved_vendors"]}
    if approved:
        if not item["manufacturer"]:
            (failures if strict else warnings).append("Missing manufacturer")
        elif item["manufacturer"].casefold() not in approved:
            failures.append("Manufacturer is not on the approved-vendor list")
    tags = {value.casefold() for value in item["tags"]}
    missing_tags = [value for value in rules["required_tags"] if value.casefold() not in tags]
    if missing_tags:
        (failures if tags or strict else warnings).append("Missing required tag(s): " + ", ".join(missing_tags))
    standards = {value.casefold() for value in item["standards"]}
    missing_standards = [
        value for value in rules["required_standards"] if value.casefold() not in standards
    ]
    if missing_standards:
        (failures if standards or strict else warnings).append(
            "Missing required standard(s): " + ", ".join(missing_standards)
        )
    props = item["properties"]
    if item["category"] == "Filtration pump":
        compare_required("voltage", props.get("voltage"), rules["required_voltage"])
        compare_required("phase", props.get("phase"), rules["required_phase"])
    if item["category"] in {"Filtration pump", "Filtration unit"}:
        compare_required("pressure class", props.get("pressure_class"), rules["required_pressure_class"])
        compare_required("connection size", props.get("connection_size"), rules["required_connection_size"])

    dimensions = item["dimensions"]
    for key, label in (("length", "length"), ("width", "width"), ("height", "height")):
        limit = rules.get(f"maximum_{key}")
        if limit in (None, ""):
            continue
        actual = dimensions.get(key)
        if actual in (None, ""):
            (failures if strict else warnings).append(f"Missing {label}")
        elif float(actual) > float(limit):
            failures.append(f"{label.title()} exceeds project maximum")
    footprint_limit = rules.get("maximum_footprint")
    if footprint_limit not in (None, ""):
        footprint = dimensions.get("footprint")
        if footprint in (None, "") and dimensions.get("length") not in (None, "") and dimensions.get("width") not in (None, ""):
            footprint = float(dimensions["length"]) * float(dimensions["width"])
        if footprint in (None, ""):
            (failures if strict else warnings).append("Missing footprint")
        elif float(footprint) > float(footprint_limit):
            failures.append("Footprint exceeds project maximum")
    clearance = rules.get("minimum_access_clearance")
    if clearance not in (None, ""):
        actual = dimensions.get("access_clearance")
        if actual in (None, ""):
            (failures if strict else warnings).append("Missing access clearance")
        elif float(actual) < float(clearance):
            failures.append("Access clearance is below project minimum")
    return not failures, [*failures, *warnings]


def evaluate_combination_compatibility(
    products: Iterable[dict[str, Any]], constraints: dict[str, Any] | None
) -> tuple[bool, list[str]]:
    items = [normalize_product(item) for item in products]
    categories = {item["category"] for item in items}
    rules = normalized_constraints(constraints)
    strict = bool(rules["require_constraint_values"])
    failures: list[str] = []
    warnings: list[str] = []
    for item in items:
        for required in item["properties"].get("required_companion_categories", []):
            if required not in categories:
                failures.append(f"{item['model']} requires a {required}")
    if rules["enforce_flow_compatibility"]:
        pump = next((item for item in items if item["category"] == "Filtration pump"), None)
        filtration = next((item for item in items if item["category"] == "Filtration unit"), None)
        if pump and filtration:
            flow = pump["properties"].get("rated_flow_gpm", pump["capacity"] / 60.0)
            minimum = filtration["properties"].get("minimum_flow_gpm")
            maximum = filtration["properties"].get("maximum_flow_gpm")
            if minimum in (None, "") or maximum in (None, ""):
                (failures if strict else warnings).append("Missing filtration-unit compatible flow range")
            elif not float(minimum) <= float(flow) <= float(maximum):
                failures.append(
                    f"{pump['model']} flow ({float(flow):g} GPM) is outside {filtration['model']} range "
                    f"({float(minimum):g}–{float(maximum):g} GPM)"
                )
    return not failures, [*failures, *warnings]
