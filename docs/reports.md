# Reports

Reports summarize the project information, end uses, collection surfaces, selected reliability, and reliability curve.

## Report information

When generating a report, review or enter:

- Client name
- Date
- Location
- Project name
- End uses of water

The PDF, LaTeX, and HTML outputs are generated from the same report content so their values and units remain aligned.

## PDF report

Select **View > PDF report**, complete the report-information dialog, and choose a save location.

When `pdflatex` is available, the application saves LaTeX source and compiles it. Without a LaTeX installation, the application generates the PDF directly with `pypdf`.

## HTML report

Select **View > HTML report**, complete the report-information dialog, and choose a save location.

The generated file is self-contained and can be opened in a modern browser, emailed with the project deliverables, or printed to PDF. Its reliability chart includes point details on hover.

## Report review

Before issuing a report, verify the client, project, location, units, surface areas, runoff coefficients, end uses, analysis settings, and chart results against the saved project.
