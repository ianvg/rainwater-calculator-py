# Reports

Reports summarize the project inputs, hydraulic performance, end-use allocation, financial results, provenance, and reliability charts.

The HTML report begins with an **Executive design summary** containing the selected tank, reliability, average annual rainwater supply, municipal makeup, system unmet demand, overflow, first-flush and treatment losses, net annual savings, and simple payback. When financial inputs are not configured, the report says so instead of implying that zero-value economics represent a completed assessment.

The **Candidate tank performance** table extends the reliability curve with average annual supply, municipal makeup, system unmet demand, overflow, first-flush loss, treatment loss, end-of-record storage, net annual savings, and simple payback. The selected primary tank is highlighted. In HTML, select a column heading to sort the table.

The **Reconciled water balance** keeps two accounting stages separate. The collection balance shows potential rainfall volume, runoff-coefficient loss, gross runoff, first-flush diversion, and net collection. The primary-storage balance reconciles initial storage and collection against rainwater supply, treatment loss, overflow, and final storage. Runoff coefficients apply to every rainfall observation; first-flush diversion applies once at the start of a qualifying rainfall event.

The **End-use demand and savings** table reports each demand object's type, operating schedule, sewer eligibility, average annual demand, allocated rainwater supply, demand met, and water and sewer savings. When several objects operate on the same day, supplied rainwater is allocated in proportion to their simulated demand for that day.

The **Financial assumptions and results** section records tariffs, billing units, legacy sewer eligibility, installed cost, incentives, maintenance, analysis period, delivered rainwater, savings, net cost, payback, and undiscounted analysis-period net benefit.

The **Analysis provenance and reproducibility** section identifies the rainfall source and record coverage, missing calendar days, timestep and rainfall-timing assumptions, system and municipal-backup state, initial tank fill, filter recovery, application and algorithm versions, analysis signature, and report-generation timestamp.

Project information includes mean annual precipitation, calculated as the mean of the yearly precipitation totals in the imported record. The value is displayed in inches for Imperial projects and millimeters for Metric projects. The report also identifies whether the rainfall import uses **Total precipitation** or **Rain only**.

Each report includes a table of contents. HTML entries link to anchored report sections, LaTeX-generated PDFs use hyperlinked contents entries, and pypdf-generated PDFs include clickable contents links and document-outline bookmarks.

Project notes appear as the second report section, immediately after Project Information. Multiline notes retain their paragraph structure. Reports display `No notes provided.` when the project notes field is blank.

Report reliability is the percentage of simulated calendar days on which usable tank water can supply 100% of the daily demand. Water at or below the configured minimum operating level is unavailable for normal withdrawal and therefore can reduce reliability.

The reliability graph marks the selected tank size and its simulated reliability with a red circle.

The Yearly Demand Reliability plot appears immediately after the reliability curve. Each 100% stacked bar shows the percentage of days in that calendar year when complete demand was met by rainwater and when it was not; the two segments always total 100%. Yellow markers identify each year's reliability at the segment boundary. A final average-only slot reports the selected tank's overall reliability and identifies the number of analyzed years.

The Tank Level Distribution plot follows the yearly reliability plot. It groups the selected-tank simulation into six tank-level ranges and reports the number of days in each range.

The surface-area summary includes only collection surfaces whose configured area is greater than zero. It reports each surface's runoff coefficient and first-flush depth, followed by the antecedent dry period in its selected unit, detected event count, and total diverted volume. Daily and hourly result exports retain gross runoff, first-flush loss, and net collection separately. Zero-area default and custom surfaces are omitted from PDF, HTML, and LaTeX report output.

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

Select **Export > Export PDF report...** or **Export > Export HTML report...**, complete the report-information dialog, and choose a permanent save location.

Select **Include system-type visualization** in the report-information dialog to place a schematic of the applied direct or indirect system immediately after the Tank summary. The schematic identifies the primary analyzed tank size and the principal flow path to the end uses.

When **Multi-tank comparison** is enabled and comparison analysis is available, the report-information dialog enables **Include multi-tank sizing charts**. Selecting it appends **Tank level distribution - multitank**, the combined yearly reliability comparison, one stacked yearly demand reliability chart for each comparison tank, and the combined tank-water history. The primary tank's original charts remain in their normal report positions. The option is disabled when multi-tank comparison is not active.

In HTML reports, the combined **Yearly demand reliability - multitank** chart includes a checked legend control for each tank size. Clear a tank's checkbox to hide its line and select it again to restore the line.

The HTML multi-tank **Tank Water Over Time** chart supports **Single year** and **Custom range** views. In single-year mode, use the previous and next controls to cycle through analyzed years. In custom-range mode, use the two range endpoints to choose the first and last displayed month; both endpoints snap to whole months. Checked tank-size controls independently hide or restore each comparison line. Hover near a daily point to see its tank size, date, and stored-water value. PDF and LaTeX reports remain static and show the complete available record.

PDF and HTML use the same report metadata and normalized report content. Differences between the formats are limited to presentation and format-specific rendering.

## PDF details

When `pdflatex` is available, the application saves LaTeX source and compiles it. Without a LaTeX installation, the application generates the PDF directly with `pypdf`.

## HTML details

The generated file can be opened in a modern browser, emailed with the project deliverables, or printed to PDF. The optional location map currently uses online Leaflet assets and OpenStreetMap tiles, so that part of the report requires network access. Its reliability chart includes point details on hover. In the Yearly Demand Reliability chart, hover over either stacked-bar segment to see the year's met and unmet day counts and percentages. Hover over a yellow marker to see that year's reliability or the overall reliability across the analyzed years.

## Report review

Before issuing a report, verify the client, project, location, units, surface areas, runoff coefficients, end uses, analysis settings, and chart results against the saved project.
