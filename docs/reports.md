# Reports

Reports summarize the project information, end uses, collection surfaces, selected reliability, and reliability curve.

The surface-area summary includes only collection surfaces whose configured area is greater than zero. Zero-area default and custom surfaces are omitted from PDF, HTML, and LaTeX report output.

## Report information

When generating a report, review or enter:

- Client name
- Date
- Location
- Project name
- End uses of water

The PDF, LaTeX, and HTML outputs are generated from the same report content so their values and units remain aligned.

## Preview a report

Select **View > View PDF report** or **View > View HTML report**, then complete the report-information dialog. The application generates the report in a temporary directory and immediately opens it in the operating system's default PDF viewer or web browser. HTML previews are served only on the local loopback interface (`127.0.0.1`) while the application is running, avoiding browser restrictions on temporary `file://` pages. No save location is required for a preview.

Temporary previews are intended for review. Export a report when a permanent project deliverable is required.

## Export a report

Select **File > Export PDF report...** or **File > Export HTML report...**, complete the report-information dialog, and choose a permanent save location.

PDF and HTML use the same report metadata and normalized report content. Differences between the formats are limited to presentation and format-specific rendering.

## PDF details

When `pdflatex` is available, the application saves LaTeX source and compiles it. Without a LaTeX installation, the application generates the PDF directly with `pypdf`.

## HTML details

The generated file is self-contained and can be opened in a modern browser, emailed with the project deliverables, or printed to PDF. Its reliability chart includes point details on hover.

## Report review

Before issuing a report, verify the client, project, location, units, surface areas, runoff coefficients, end uses, analysis settings, and chart results against the saved project.
