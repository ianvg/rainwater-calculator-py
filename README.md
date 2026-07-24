# Rainwater Calculator

The Tkinter desktop application is the complete supported product for project authoring, rainfall import, analysis, optimization, reporting, and persistence.

## Windows desktop app

### Run the Tkinter app locally
```powershell
cd C:\Projects\rainwater-calculator-py
.\.venv\Scripts\python.exe tkinter_app.py
```

### Build the Windows executable
```powershell
powershell -ExecutionPolicy Bypass -File .\build_exe.ps1
```

The build output is:
- `dist\RainwaterCalculator.exe`

Build the per-user Windows installer with Inno Setup 6:

```powershell
powershell -ExecutionPolicy Bypass -File .\build_installer.ps1
```

The installer output is `dist\RainwaterCalculator-Setup-<version>.exe`.

### Sharing the Windows app
For a simple handoff, you can share `dist\RainwaterCalculator.exe` directly. The recipient does not need Python installed because the executable bundles the Python runtime and required app dependencies.

Notes:
- Share the `.exe` from a trusted source. Windows SmartScreen may warn about unsigned executables.
- Saved projects are not inside the `.exe`. The default database and automatic backups use the operating system's per-user application-data directory.
- Windows uses `%LOCALAPPDATA%\RWH Calculator`; macOS uses `~/Library/Application Support/RWH Calculator`; Linux follows `XDG_DATA_HOME` or `~/.local/share/rwh-calculator`.
- Existing beside-executable data is copied into the new location on first run without deleting the original files.
- The installer and uninstaller do not remove user projects or backups.
- ACIS weather import requires internet access.

## Product interface policy

- **Tkinter desktop application:** the full supported product and authoritative workflow.
- **Streamlit project viewer:** an optional, read-only companion for inspecting saved inputs and results in a browser. It does not create or modify projects, import rainfall, run calculations, optimize systems, or export reports.
- **Flask:** retired. The legacy Flask entry point, templates, authentication prototype, and launchers have been removed.

## Development environment setup

These steps set up a local development environment from a fresh clone on Windows.

### 1. Clone the repository
```powershell
cd C:\Projects
git clone https://github.com/ianvg/rainwater-calculator-py.git
cd rainwater-calculator-py
```

### 2. Create and activate a virtual environment
Use Python 3.10 or newer.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

The `.venv` folder is intentionally not tracked in Git. If it is missing, broken, or was created on another machine, recreate it locally:

```powershell
Remove-Item -Recurse -Force .venv
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks activation scripts, run:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

Then activate the environment again.

### 3. Install dependencies
Install the package in editable mode with test dependencies:

```powershell
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

On Windows, prepare the pinned standalone WeasyPrint renderer used by PDF reports:

```powershell
powershell -ExecutionPolicy Bypass -File .\prepare_weasyprint.ps1
```

The executable build runs this preparation step automatically and verifies the downloaded archive's SHA-256 checksum.

### Build the user documentation

The end-user guide is written in Markdown under `docs/` and built with MkDocs Material:

```powershell
python -m pip install -e ".[docs]"
python -m mkdocs serve
```

Use `python -m mkdocs build --strict` to generate the offline guide in `site/`. The Windows executable build performs this step automatically and bundles the guide for **Help > User guide**.

### 4. Run tests
```powershell
python -m pytest
```

Run the same static quality check used by continuous integration:

```powershell
python -m ruff check .
```

Pull requests and pushes to `main` run the test suite on Python 3.10 and 3.13,
build the documentation strictly, run Ruff, and smoke-test the desktop entry
point on Windows plus the optional read-only viewer on Linux. The executable
workflow also tests before packaging and smoke-tests the packaged program before
uploading it.

### 5. Run the optional Streamlit viewer

Install its reviewed, hash-locked dependencies and then install the local project
without resolving another dependency set:

```powershell
.\.venv\Scripts\python.exe -m pip install --require-hashes -r requirements\viewer.txt
.\.venv\Scripts\python.exe -m pip install --no-build-isolation --no-deps -e .
```

Then launch the read-only viewer:

```powershell
python -m streamlit run streamlit_app.py --server.address 127.0.0.1 --browser.serverAddress 127.0.0.1
```

The viewer opens in a browser at `http://localhost:8501` and reads projects already saved by Tkinter. On Windows, `run_streamlit_viewer.bat` launches an already-installed viewer and reports the installation commands when dependencies are missing. It never installs or upgrades packages at application startup.

The launcher and documented command bind the unauthenticated viewer to `127.0.0.1`; do not expose it through a public interface or proxy without adding authentication and authorization.

Release builds install `requirements/desktop-build.txt` in pip hash-checking mode, run `pip-audit`, and emit a CycloneDX JSON SBOM beside the executable. Regenerate and review the lockfiles with Python 3.10 and `pip-compile --generate-hashes` whenever dependency declarations change.

### 6. Clean generated build artifacts
PyInstaller creates generated folders that can be removed to free disk space:

```powershell
Remove-Item -Recurse -Force build, dist
```

This does not remove source code, tests, README files, Git history, or the build script. It only removes generated packaging output. To recreate the executable later, run:

```powershell
powershell -ExecutionPolicy Bypass -File .\build_exe.ps1
```

## Expected rainfall CSV format
The uploaded CSV must include these columns:
- `Date`
- `Precipitation`

## License
RWH Calculator is open-source software released under the Zero-Clause BSD (0BSD) license. See `LICENSE`.

