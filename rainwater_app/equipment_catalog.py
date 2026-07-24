from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Iterable


EQUIPMENT_CATEGORIES = (
    "Primary tank",
    "Transfer pump",
    "Filtration system",
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
        *[
            _product(
                f"builtin-transfer-{flow}", "Transfer pump", f"TP-{flow}", flow * 60,
                cost, power_kw=power, rated_flow_gpm=flow, pump_type="External",
                required_companion_categories=["Filtration system"],
            )
            for flow, cost, power in (
                (15, 2_100, .75), (20, 2_500, 1.1), (30, 3_100, 1.5),
                (40, 3_800, 2.2), (50, 4_500, 3.0),
            )
        ],
        *[
            _product(
                f"builtin-filtration-{flow}", "Filtration system", f"FS-{flow}", flow * 60,
                cost, rated_flow_gpm=flow, minimum_flow_gpm=flow, maximum_flow_gpm=flow,
                required_companion_categories=["Transfer pump"],
            )
            for flow, cost in ((15, 1_300), (20, 1_650), (30, 2_100), (40, 2_650), (50, 3_200))
        ],
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
    result["category"] = {
        "Filtration pump": "Transfer pump",
        "Filtration unit": "Filtration system",
    }.get(result["category"], result["category"])
    result["manufacturer"] = str(result.get("manufacturer") or "").strip()
    result["model"] = str(result.get("model") or result.get("name") or "").strip()
    result["description"] = str(result.get("description") or "").strip()
    result["capacity"] = float(result.get("capacity", 0.0))
    result["installed_cost"] = float(result.get("installed_cost", result.get("cost", 0.0)))
    result["properties"] = dict(result.get("properties") or {})
    companions = result["properties"].get("required_companion_categories", [])
    result["properties"]["required_companion_categories"] = [
        {"Filtration pump": "Transfer pump", "Filtration unit": "Filtration system"}.get(
            str(value), str(value)
        )
        for value in companions
    ]
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
        effective_candidate_product(item)["category"] == "Filtration system" for item in candidates
    ):
        neutral = _product(
            "legacy-neutral-filter", "Filtration system", "Existing project filtration", 1_200,
            0, rated_flow_gpm=20, minimum_flow_gpm=20, maximum_flow_gpm=20,
            required_companion_categories=["Transfer pump"],
        )
        candidates.append(candidate_from_product(neutral))
    return candidates


def default_equipment_constraints() -> dict[str, Any]:
    return {
        "enforce_flow_compatibility": True,
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
    if item["category"] == "Transfer pump":
        flow = props.get("rated_flow_gpm", item["capacity"] / 60.0)
        if float(flow) not in {15.0, 20.0, 30.0, 40.0, 50.0}:
            failures.append("Rated flow must be 15, 20, 30, 40, or 50 GPM")
        pump_type = str(props.get("pump_type", "External"))
        if pump_type not in {"External", "Submersible"}:
            failures.append("Pump type must be External or Submersible")
        compare_required("voltage", props.get("voltage"), rules["required_voltage"])
        compare_required("phase", props.get("phase"), rules["required_phase"])
    if item["category"] == "Filtration system":
        flow = props.get("rated_flow_gpm", item["capacity"] / 60.0)
        if float(flow) not in {15.0, 20.0, 30.0, 40.0, 50.0}:
            failures.append("Rated flow must be 15, 20, 30, 40, or 50 GPM")
    if item["category"] in {"Transfer pump", "Filtration system"}:
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
    failures: list[str] = []
    warnings: list[str] = []
    for item in items:
        for required in item["properties"].get("required_companion_categories", []):
            if required not in categories:
                failures.append(f"{item['model']} requires a {required}")
    if rules["enforce_flow_compatibility"] or {
        "Transfer pump", "Filtration system"
    }.issubset(categories):
        pump = next((item for item in items if item["category"] == "Transfer pump"), None)
        filtration = next((item for item in items if item["category"] == "Filtration system"), None)
        if pump and filtration:
            flow = pump["properties"].get("rated_flow_gpm", pump["capacity"] / 60.0)
            filtration_flow = filtration["properties"].get(
                "rated_flow_gpm", filtration["capacity"] / 60.0
            )
            minimum = filtration["properties"].get("minimum_flow_gpm", filtration_flow)
            maximum = filtration["properties"].get("maximum_flow_gpm", filtration_flow)
            if minimum in (None, "") or maximum in (None, ""):
                failures.append("Missing filtration-system nominal flow")
            elif float(flow) != float(filtration_flow):
                failures.append(
                    f"{pump['model']} flow ({float(flow):g} GPM) does not match {filtration['model']} "
                    f"({float(filtration_flow):g} GPM)"
                )
    return not failures, [*failures, *warnings]
