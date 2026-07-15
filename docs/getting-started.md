# Getting started

## Start the Windows application

Open `RainwaterCalculator.exe`. The application opens to the project workspace.

When running from source instead:

```powershell
cd C:\Projects\rainwater-calculator-py
.\.venv\Scripts\python.exe tkinter_app.py
```

## Main areas

The application is organized into tabs for project inputs, system parameters, rainfall importing, demand, collection surfaces, analysis settings, and results. The exact tabs visible may vary as the application develops.

The status area at the bottom reports actions such as opening a project, importing rainfall, running an analysis, and generating a report. Longer operations display progress at the lower right.

## Units

Choose imperial or metric units before entering project values. Unit labels beside fields and in table headings show the expected display unit.

Changing the unit system changes how values are displayed. Review all settings after changing units, especially tank sizes, graph steps, surface areas, rainfall, and demand.

## First analysis

1. Select **File > Create new project**.
2. Enter a project name and select the desired units.
3. Import rainfall from a CSV file or ACIS.
4. Add at least one collection surface with a positive area.
5. Enter the applicable water demand.
6. Review tank and graph settings.
7. Select **Run analysis > Run single-tank analysis**, or choose the multi-tank command when comparison sizes are configured.
8. Review the results and reliability curve.
9. Select **File > Save project as...** to choose a project-file location.
