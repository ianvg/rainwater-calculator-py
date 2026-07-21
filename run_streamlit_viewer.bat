@echo off
setlocal

cd /d "%~dp0"

if not exist ".venv" (
    echo Creating virtual environment...
    python -m venv .venv
)

call .venv\Scripts\activate.bat

echo Installing the optional Streamlit viewer...
pip install --disable-pip-version-check -e ".[viewer]"
if errorlevel 1 (
    echo Failed to install viewer dependencies.
    pause
    exit /b 1
)

echo Starting the read-only project viewer...
streamlit run streamlit_app.py

endlocal
