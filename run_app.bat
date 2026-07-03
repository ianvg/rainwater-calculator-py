@echo off
setlocal

cd /d "%~dp0"

echo [1/4] Ensuring upload folder exists...
if not exist "data" mkdir "data"

echo [2/4] Ensuring Python dependencies are installed...
python -m pip install --disable-pip-version-check flask flask-bootstrap flask-pymongo flask-wtf wtforms werkzeug pandas numpy scipy matplotlib mpld3 bokeh
if errorlevel 1 (
    echo Failed to install Python dependencies.
    pause
    exit /b 1
)

echo [3/4] Starting MongoDB (best effort)...
where mongod >nul 2>&1
if errorlevel 1 (
    echo WARNING: 'mongod' was not found in PATH.
    echo Make sure MongoDB is running on localhost:27017 before using the app.
) else (
    sc query MongoDB >nul 2>&1
    if not errorlevel 1 (
        net start MongoDB >nul 2>&1
    ) else (
        start "MongoDB" mongod
        timeout /t 3 >nul
    )
)

echo [4/4] Launching Flask app...
python main.py

endlocal
