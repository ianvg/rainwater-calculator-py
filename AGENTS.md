# Repository Guidelines

## Project Structure & Module Organization

The full supported product interface is the Tkinter desktop application in `tkinter_app.py`. Shared domain code lives in `rainwater_app/`: `engine.py` performs simulations, `models.py` defines project data, `storage.py` handles persistence, and `acis.py`, `eccc.py`, and `geocoding.py` integrate external services. `streamlit_app.py` is a deliberately limited, read-only viewer for saved projects and must not become a second authoring or analysis interface. Tests are under `tests/` and mirror the shared modules. Store application images and diagrams in `assets/`, user documentation in `docs/`, and packaging configuration in `RainwaterCalculator.spec` and `build_exe.ps1`. Treat sample rainfall files and `Weather Station Data Folder/` as data, not source code.

## Build, Test, and Development Commands

Create an environment and install development dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev,docs]"
```

Run the desktop product with `.\.venv\Scripts\python.exe tkinter_app.py`. Install `.[viewer]` and run `.\.venv\Scripts\python.exe -m streamlit run streamlit_app.py` only when testing the optional read-only viewer.

Use `.\.venv\Scripts\python.exe -m pytest` for the complete test suite. Build documentation with `.\.venv\Scripts\python.exe -m mkdocs build --strict`, or preview it with `mkdocs serve`. Create the Windows executable with `powershell -ExecutionPolicy Bypass -File .\build_exe.ps1`.

## Coding Style & Naming Conventions

Use four-space indentation, type hints, and standard Python naming: `snake_case` for functions and variables, `PascalCase` for classes, and uppercase names for constants. Keep UI orchestration in `tkinter_app.py`; place reusable calculations, parsing, storage, and integrations in `rainwater_app/`. Prefer small helpers and structured data over duplicated widget or report logic. Preserve ASCII unless user-facing content requires otherwise.

## Testing Guidelines

Tests use `pytest`. Name files `test_<module>.py` and functions `test_<behavior>()`. Add focused tests for calculations, project-file compatibility, API parsing, and generated report markup. Mock network behavior; tests must not depend on live ACIS, ECCC, or OpenStreetMap services. Run tests and `mkdocs build --strict` before submitting changes.

## Commit & Pull Request Guidelines

Recent commits use concise, imperative summaries such as `Improve project workflows and demand scheduling`. Keep each commit cohesive and avoid generated `site/`, `.venv/`, or local project files. Pull requests should explain user-visible behavior, list verification commands, link relevant issues, and include screenshots for Tkinter layout or chart changes. Call out storage-schema compatibility, external-service changes, and any untested platform-specific behavior.

## Security & Configuration

Do not commit credentials or private project locations. Configure service overrides through environment variables such as `RWH_OSM_TILE_URL` and `RWH_NOMINATIM_URL`. Respect provider rate limits and keep network calls off the Tkinter UI thread.
