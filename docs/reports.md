# Reports

Reports summarize the project information, end uses, collection surfaces, selected reliability, and reliability curve.

Project information includes mean annual precipitation, calculated as the mean of the yearly precipitation totals in the imported record. The value is displayed in inches for Imperial projects and millimeters for Metric projects. The report also identifies whether the rainfall import uses **Total precipitation** or **Rain only**.

Each report includes a table of contents. HTML entries link to anchored report sections, LaTeX-generated PDFs use hyperlinked contents entries, and pypdf-generated PDFs include clickable contents links and document-outline bookmarks.

Project notes appear as the second report section, immediately after Project Information. Multiline notes retain their paragraph structure. Reports display `No notes provided.` when the project notes field is blank.

Report reliability is the percentage of simulated calendar days on which the tank can supply 100% of the daily demand. The reserve threshold is not included in this percentage.

The reliability graph marks the selected tank size and its simulated reliability with a red circle.

The Yearly Demand Reliability plot appears immediately after the reliability curve. Each 100% stacked bar shows the percentage of days in that calendar year when complete demand was met by rainwater and when it was not; the two segments always total 100%.

The Tank Level Distribution plot follows the yearly reliability plot. It groups the selected-tank simulation into six tank-level ranges and reports the number of days in each range.

The surface-area summary includes only collection surfaces whose configured area is greater than zero. Zero-area default and custom surfaces are omitted from PDF, HTML, and LaTeX report output.

The tank summary appears below the surface-area summary and identifies the selected tank size using the project's current volume units. Additional tank properties, such as tank type, may be added in future versions.

The demand summary reports both mean simulated demand per day and mean total demand per month for each calendar month. The 12 months are arranged as two groups of Month, Demand per Day, and Demand per Month. Total Annual Demand is the mean of the simulated yearly demand totals and is displayed below two thin rules. Demand values use gallons for Imperial projects and liters for Metric projects, and all displayed demand values are rounded to the nearest whole unit.

## Report information

When generating a report, review or enter:

- Client name
- Date
- Location
- Project name
- Produced-by/author name, when configured in Project Settings
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
