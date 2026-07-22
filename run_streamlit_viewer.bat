@echo off
setlocal

cd /d "%~dp0"

if not exist ".venv" (
    echo The project virtual environment is missing.
    echo Install it first with: python -m venv .venv
    echo Then install the locked viewer dependencies with:
    echo .venv\Scripts\python.exe -m pip install --require-hashes -r requirements\viewer.txt
    echo .venv\Scripts\python.exe -m pip install --no-build-isolation --no-deps -e .
    pause
    exit /b 1
)

.venv\Scripts\python.exe -c "import streamlit" >nul 2>&1
if errorlevel 1 (
    echo The optional Streamlit viewer dependencies are not installed.
    echo Install them with:
    echo .venv\Scripts\python.exe -m pip install --require-hashes -r requirements\viewer.txt
    echo .venv\Scripts\python.exe -m pip install --no-build-isolation --no-deps -e .
    pause
    exit /b 1
)

echo Starting the read-only project viewer...
.venv\Scripts\python.exe -m streamlit run streamlit_app.py --server.address 127.0.0.1 --browser.serverAddress 127.0.0.1

endlocal
