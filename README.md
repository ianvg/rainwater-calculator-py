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
.\build_exe.ps1
```

The build output is:
- `dist\RainwaterCalculator.exe`

Copy `dist\RainwaterCalculator.exe` to another Windows machine and run it. The desktop app stores saved projects beside the executable in `rainwater_projects.db`.

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

### 4. Run tests
```powershell
python -m pytest
```

### 5. Run the Streamlit app
```powershell
streamlit run streamlit_app.py
```

The app should open in a browser at `http://localhost:8501`.

## Expected rainfall CSV format
The uploaded CSV must include these columns:
- `Date`
- `Precipitation`

## Legacy Flask app
The original Flask app is still present in `main.py` and `templates/`, but the new Streamlit app is the preferred path moving forward.

