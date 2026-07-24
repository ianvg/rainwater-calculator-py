# Reports

Reports summarize the project inputs, hydraulic performance, end-use allocation, financial results, provenance, and reliability charts.

The HTML report begins with an **Executive design summary** containing average annual precipitation, the selected tank, reliability, average annual rainwater supply, municipal makeup, system unmet demand, overflow, first-flush and treatment losses, net annual savings, and simple payback. When financial inputs are not configured, the report says so instead of implying that zero-value economics represent a completed assessment.

The **Candidate tank performance** table extends the reliability curve with average annual supply, municipal makeup, system unmet demand, overflow, first-flush loss, treatment loss, end-of-record storage, net annual savings, and simple payback. The selected primary tank is highlighted. In HTML, select a column heading to sort the table.

The **Reconciled water balance** keeps two accounting stages separate. The collection balance shows potential rainfall volume, runoff-coefficient loss, gross runoff, first-flush diversion, and net collection. The primary-storage balance reconciles initial storage and collection against rainwater supply, treatment loss, overflow, and final storage. Runoff coefficients apply to every rainfall observation; first-flush diversion applies once at the start of a qualifying rainfall event.

The **End-use demand and savings** table reports each demand object's type, operating schedule, sewer eligibility, average annual demand, allocated rainwater supply, demand met, and water and sewer savings. When several objects operate on the same day, supplied rainwater is allocated in proportion to their simulated demand for that day.

The **Financial assumptions and results** section records tariffs, billing units, legacy sewer eligibility, installed cost, incentives, maintenance, pump energy, electricity, escalation and replacement assumptions, discount rate, analysis period, delivered rainwater, first-year savings, net cost, simple and discounted payback, nominal analysis-period net benefit, lifecycle NPV, and IRR.

The **Rainfall quality and completeness** section reports a calendar-year completeness score and rating, observed and expected days, missing periods, explicit partial-year labels, duplicate dates, and invalid precipitation rows. The **Yearly rainfall summary** reports precipitation, wet days, missing days, and completeness for every year. The **Rainfall-event summary** reports the event count and up to the ten largest events using the project's antecedent-dry-period rule.

The **First-flush diversion summary** provides two reconciled tables. Yearly rows report events started, gross runoff, first-flush diversion, net collected water, and the diverted percentage. Event rows report the same volumes for every retained rainfall event together with its identifier, start, end, and wet-timestep count. An event that crosses New Year is counted in the year it starts, while each year's volume row contains only volumes occurring in that calendar year. The tables are also available under **Results > First-flush summaries**.

The **Analysis provenance and reproducibility** section identifies the rainfall source, explicit data classification, record coverage, temporal resolution, source timezone, timing metadata, import or retrieval timestamp, timestep and rainfall-timing assumptions, system and municipal-backup state, initial tank fill, filter recovery, application and algorithm versions, analysis signature, and report-generation timestamp.

All report formats consume the same validated report model. The model currently uses report schema version 2 and rejects missing required sections, unsupported schema versions, and non-finite numeric values before rendering. The HTML, LaTeX, and direct PDF outputs include the same design recommendations, review conditions, rainfall quality, yearly rainfall, rainfall-event, first-flush diversion, lifecycle financial, and provenance sections.

Report regression tests compare a deterministic representative report model with a versioned golden fixture. HTML tests snapshot its semantic section, table, navigation, and chart-label structure and perform offline validation of document landmarks, headings, accessible names, IDs, and internal links. Browser-based visual regression and accessibility auditing remain separate future checks.

Reliability curves, yearly reliability rows, tank-level distributions, and multi-tank series are prepared by shared UI-independent chart-data helpers. The desktop canvases and report renderers therefore consume the same converted units and aggregated values, while each output remains responsible for its own drawing and interaction behavior.

The HTML report embeds its styles, scripts, charts, and map layout without requiring Leaflet or another JavaScript mapping library. When project or weather-station coordinates are available, the static map loads the configured OpenStreetMap tiles and overlays labeled project and station markers. Map imagery requires an internet connection, while the coordinate table remains available offline. Every HTML chart includes a data table directly beneath it, so its values remain available when JavaScript is disabled, in print, and to assistive technology.

HTML and PDF exports are generated into temporary sibling files, checked for non-empty or valid output, and atomically replace the requested destination only after generation succeeds. An interrupted or failed export therefore does not overwrite an existing completed report.

The Executive Summary includes mean annual precipitation, calculated as the mean of the yearly precipitation totals in the imported record. The value is displayed in inches for English (I-P) projects and millimeters for Metric (SI) projects. The summary also identifies whether the rainfall import uses **Total precipitation** or **Rain only**.

Project Information appears before the Executive Summary in HTML, LaTeX, and direct-PDF reports.

Each report includes a table of contents. HTML entries link to anchored report sections, LaTeX-generated PDFs use hyperlinked contents entries, and pypdf-generated PDFs include clickable contents links and document-outline bookmarks.

Project notes appear immediately after the Executive Summary. Multiline notes retain their paragraph structure. Reports display `No notes provided.` when the project notes field is blank.

Report reliability is the percentage of simulated calendar days on which usable tank water can supply 100% of the daily demand. Water at or below the configured minimum operating level is unavailable for normal withdrawal and therefore can reduce reliability.

The reliability graph marks the selected tank size and its simulated reliability with a red circle.

The Yearly Demand Reliability plot appears immediately after the reliability curve. Each 100% stacked bar shows the percentage of days in that calendar year when complete demand was met by rainwater and when it was not; the two segments always total 100%. Yellow markers identify each year's reliability at the segment boundary. A final average-only slot reports the selected tank's overall reliability and identifies the number of analyzed years.

The Tank Level Distribution plot follows the yearly reliability plot. It groups the selected-tank simulation into six tank-level ranges and reports the number of days in each range.

The surface-area summary includes only collection surfaces whose configured area is greater than zero. It reports each surface's runoff coefficient and first-flush depth, followed by the antecedent dry period in its selected unit, detected event count, and total diverted volume. Daily and hourly result exports retain gross runoff, first-flush loss, and net collection separately. Zero-area default and custom surfaces are omitted from PDF, HTML, and LaTeX report output.

The **Rainfall volume summary** groups the mean annual collection volumes derived from the simulated calendar-year totals. **Total average rain** is gross runoff after applying each surface's runoff coefficient and before first flush. **Average first-flush diversion** is shown separately. **Total usable average rain** is the net collected volume after subtracting first-flush diversion, so total average rain equals first-flush diversion plus total usable average rain. Values use the project's displayed volume unit per year.

The tank summary appears below the surface-area summary and identifies the selected tank size using the project's current volume units. Additional tank properties, such as tank type, may be added in future versions.

The demand summary reports both mean simulated demand per day and mean total demand per month for each calendar month. The 12 months are arranged as two groups of Month, Demand per Day, and Demand per Month. Total Annual Demand is the mean of the simulated yearly demand totals and is displayed below two thin rules. Demand values use gallons for English (I-P) projects and liters for Metric (SI) projects, and all displayed demand values are rounded to the nearest whole unit.

## Report information

When generating a report, review or enter:

- Client name
- Date
- Location
- Project name
- Produced-by/author name, when configured in Project Settings
- End uses of water

The PDF, LaTeX, and HTML outputs are generated from the same report content so their values and units remain aligned.

Before previewing or exporting, open **Results > Report generation**. Select the core sections to include, or use **Select all**, **Clear all**, and **Restore defaults** for quick changes. The report cover is always included, and each format builds its table of contents from the selected sections. Section choices are saved with the project and apply to both preview and export.

Use **Supplemental visuals** on the same sub-tab to include the system-type visualization and, when comparison results are available, the multi-tank comparison charts.

## Preview a report

Select **View > View PDF report** or **View > View HTML report**, then complete the report-information dialog. The primary PDF uses WeasyPrint to render the same HTML document used by the HTML export. The application generates the report in a temporary directory and immediately opens it in the operating system's default PDF viewer or web browser. HTML previews are served only on the local loopback interface (`127.0.0.1`) while the application is running, avoiding browser restrictions on temporary `file://` pages. No save location is required for a preview.

Temporary previews are intended for review. Export a report when a permanent project deliverable is required.

## Export a report

Select **Export > Export PDF report...** or **Export > Export HTML report...**, complete the report-information dialog, and choose a permanent save location. **Export legacy PDF report...** retains the previous LaTeX/direct-PDF renderer as a secondary option during the transition.

## Compare saved projects

Select **Export > Export project comparison as PDF...** or **Export > Export project comparison as HTML...**. Choose at least two saved, analyzed projects and enter a report title. The selector initially lists projects in the current database; use **Add project database...** to include projects from one or more other rainwater project `.db` files. External databases are validated and opened read-only, and generating the comparison does not switch, save, rerun, or otherwise modify the active project.

The comparison reports project source, location, rainfall provenance and period, analysis status, collection area, mean annual precipitation, area-weighted runoff coefficient, selected tank, reliability, annual demand and water-balance results, first-flush and treatment losses, basic economics, and review conditions. Annual result volumes are calendar-year averages from saved analysis rows. If every selected project is Metric (SI), common areas, precipitation, tank sizes, and volumes use metric units; otherwise common comparison quantities use English units, with mixed-unit normalization called out in the report. Duplicate project names from different databases are labelled with their source database.

Projects without usable saved results cannot be included. Results whose saved analysis signature no longer matches their project inputs are labelled stale; older results without a signature are labelled not verifiable. The comparison never silently reruns either case.

Select **Include system-type visualization** under **Results > Report generation > Supplemental visuals** to place a schematic of the applied direct or indirect system in the report. The schematic identifies the primary analyzed tank size and the principal flow path to the end uses.

When **Multi-tank comparison** is enabled and comparison analysis is available, select **Include multi-tank comparison charts** under **Supplemental visuals**. This appends **Tank level distribution - multitank**, the combined yearly reliability comparison, one stacked yearly demand reliability chart for each comparison tank, and the combined tank-water history. If comparison results are unavailable, the saved option remains selected but no multi-tank charts are added.

In HTML reports, the combined **Yearly demand reliability - multitank** chart includes a checked legend control for each tank size. Clear a tank's checkbox to hide its line and select it again to restore the line.

The HTML multi-tank **Tank Water Over Time** chart supports **Single year** and **Custom range** views. In single-year mode, use the previous and next controls to cycle through analyzed years. In custom-range mode, use the two range endpoints to choose the first and last displayed month; both endpoints snap to whole months. Checked tank-size controls independently hide or restore each comparison line. Hover near a daily point to see its tank size, date, and stored-water value. PDF and LaTeX reports remain static and show the complete available record.

PDF and HTML use the same report metadata and normalized report content. Differences between the formats are limited to presentation and format-specific rendering.

## PDF details

The primary PDF report is rendered from the validated HTML report with WeasyPrint. It includes print-specific page sizing, page numbers, table wrapping, and static inline SVG charts. Browser-only interactions such as tooltips, sorting, and range controls are intentionally omitted from PDF output.

The secondary **Legacy PDF report** option preserves the earlier behavior: when `pdflatex` is available, the application saves LaTeX source and compiles it; without a LaTeX installation, it generates the PDF directly with `pypdf`.

## HTML details

The generated file can be opened in a modern browser, emailed with the project deliverables, or printed to PDF. The optional location map uses the configured OpenStreetMap tile source without loading Leaflet, so only the map imagery requires network access. Its reliability chart includes point details on hover. In the Yearly Demand Reliability chart, hover over either stacked-bar segment to see the year's met and unmet day counts and percentages. Hover over a yellow marker to see that year's reliability or the overall reliability across the analyzed years.

## Report review

Before issuing a report, verify the client, project, location, units, surface areas, runoff coefficients, end uses, analysis settings, and chart results against the saved project.
