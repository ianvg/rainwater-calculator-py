# Rainwater Calculator

This repository now includes standalone local Python applications for rainwater tank sizing.

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

Copy `dist\RainwaterCalculator.exe` to another Windows machine and run it. The desktop app stores saved projects beside the executable in `rainwater_projects.db`.

### Sharing the Windows app
For a simple handoff, you can share `dist\RainwaterCalculator.exe` directly. The recipient does not need Python installed because the executable bundles the Python runtime and required app dependencies.

Notes:
- Share the `.exe` from a trusted source. Windows SmartScreen may warn about unsigned executables.
- Saved projects are not inside the `.exe`; they are stored in `rainwater_projects.db` beside the executable after the user saves projects.
- If you want to send existing saved projects, include `rainwater_projects.db` with the `.exe`.
- ACIS weather import requires internet access.

## New standalone app (recommended)

### 1. Run with one click on Windows
- Double click `run_standalone_app.bat`

### 2. Run manually
```powershell
cd C:\Projects\rainwater-calculator-py
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
streamlit run streamlit_app.py
```

The app opens in your browser and stores projects in a local SQLite file:
- `rainwater_projects.db`

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

### 5. Run the Streamlit app
```powershell
streamlit run streamlit_app.py
```

The app should open in a browser at `http://localhost:8501`.

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

## Legacy Flask app
The original Flask app is still present in `main.py` and `templates/`, but the new Streamlit app is the preferred path moving forward.

