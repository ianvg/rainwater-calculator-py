# RWH Calculator

RWH Calculator is a desktop application for estimating rainwater harvesting tank performance from daily rainfall, collection surfaces, and water demand.

Use this guide to create a project, import rainfall records, describe collection surfaces and demand, run an analysis, and generate a report.

## Typical workflow

1. [Create or open a project](projects.md).
2. [Import daily rainfall data](rainfall-data.md).
3. Select imperial or metric units and enter the project settings.
4. [Define the collection surfaces](collection-surfaces.md).
5. [Enter the water demand](water-demand.md).
6. [Run the analysis and review the results](analysis.md).
7. [Generate a PDF or HTML report](reports.md).
8. Save the project.

!!! note
    RWH Calculator is a planning and analysis tool. Verify rainfall records, assumptions, local requirements, and calculated results before using them for design, permitting, construction, or operations.

## Where project information is stored

Projects are stored in SQLite database files. A project file can contain rainfall data, settings, collection surfaces, demand, and completed analysis results.

The application can save a project before rainfall data has been imported. Analysis requires suitable rainfall data and valid analysis settings.

## Getting help

Start with [Getting started](getting-started.md). For common errors, see [Troubleshooting](troubleshooting.md).
