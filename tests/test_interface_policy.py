from __future__ import annotations

import ast
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def test_streamlit_is_a_read_only_viewer() -> None:
    source = (REPOSITORY_ROOT / "streamlit_app.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_names = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    called_attributes = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }

    assert {"simulate_tank", "simulate_hourly_tank", "reliability_curve"}.isdisjoint(
        imported_names
    )
    assert {
        "save_project",
        "delete_project",
        "file_uploader",
        "data_editor",
        "text_input",
        "number_input",
    }.isdisjoint(called_attributes)
    assert "read-only" in source.casefold()


def test_legacy_flask_application_is_retired() -> None:
    assert not (REPOSITORY_ROOT / "main.py").exists()
    templates = REPOSITORY_ROOT / "templates"
    assert not templates.exists() or not any(templates.iterdir())
    assert not (REPOSITORY_ROOT / "start.bat").exists()
    assert not (REPOSITORY_ROOT / "run_app.bat").exists()
