# Troubleshooting

## Project database recovery

The application checks SQLite integrity when it starts and whenever another project database is opened. If the active database is damaged, the newest valid automatic backup is restored and the damaged file is preserved in the per-user backup directory. Follow the recovery notice, then verify the restored project's latest inputs and results.

If no valid backup exists, the application refuses to replace the damaged database. Preserve the file, review the backup directory described in [Project storage and recovery](project-storage.md), and open an earlier project copy with **File > Open project...**. Do not edit or truncate SQLite files manually.

## A project does not open

Confirm that the selected file exists and is a valid RWH Calculator database. If it was moved, open it from its new location instead of using the recent-project list.

## Rainfall CSV import fails

Confirm that the file contains `Date` and `Precipitation` columns, that dates are valid, and that precipitation cells contain numeric values. Open the file in a spreadsheet editor to inspect its headings and rows.

## ACIS stations do not load

Check the internet connection and selected state, then try again. The ACIS service may occasionally be unavailable. A compatible CSV can be used when online importing is unavailable.

## Analysis cannot run

Check for imported rainfall, at least one usable collection surface, nonzero demand where applicable, and valid tank-size settings. Review the message displayed by the application for the specific invalid field.

## Results look unexpected

Verify units first. Then review rainfall completeness, collection areas, runoff coefficients, demand values, tank range, graph step, and initial conditions. Compare a few assumptions with an independent calculation.

## PDF generation fails

The primary PDF renderer requires WeasyPrint and its native text-layout libraries. Install the project dependencies from `pyproject.toml`; on Windows, verify the packaged application contains the required WeasyPrint libraries. If primary PDF generation is unavailable, use **View/Export legacy PDF report**. The legacy option uses `pdflatex` when available and falls back to direct generation with `pypdf`; if LaTeX compilation fails, inspect the saved `.tex` source and error details. HTML report generation remains available without LaTeX.

## Local user guide is unavailable

Packaged releases include the local guide. When running from source, build it with:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[docs]"
.\.venv\Scripts\python.exe -m mkdocs build
```

Then select **Help > User guide** again.
