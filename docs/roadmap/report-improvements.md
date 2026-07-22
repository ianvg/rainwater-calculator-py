# Report improvements

This subpage records report work that remains after the executive summary, candidate comparison, reconciled water balance, end-use allocation, financial disclosure, analysis provenance, recommendations, and review conditions were aligned across HTML, LaTeX, and direct PDF output.

## Presentation and usability

- [Implemented for HTML] Add an accessible data table beneath every chart so printed reports, assistive technology, and non-interactive readers receive the same values as hover tooltips.
- [Implemented initial decision aids] Add optional conclusions and design observations, including diminishing-return guidance whose threshold is explicitly user controlled.
- [Implemented initial conditions] Add prominent warnings for incomplete rainfall years, unconfigured tariffs or costs, low reliability, excessive overflow, and other review conditions.
- Improve print pagination with repeating table headers, controlled chart breaks, and fewer large blank areas.
- Improve narrow-screen handling for wide result tables and dense chart controls.
- Add SVG `title` and `desc` content, keyboard-accessible chart points, and patterns or direct labels so meaning does not depend only on color.
- Correct remaining legacy text-encoding defects in map and application symbols.
- [Implemented] Preserve all essential report content when JavaScript is disabled; interactivity remains an enhancement.
- Keep number precision and unit labels consistent across summaries, tables, charts, HTML, LaTeX, and direct PDF output.

## Report-generation architecture

- [Implemented initial schema] Replace the untyped report dictionary with a validated, versioned report model shared by HTML, LaTeX, and direct PDF renderers.
- Split the large inline HTML generator into maintained templates and reusable section, table, and chart components.
- [Implemented by retirement] Remove the separate legacy Flask report template so the desktop and legacy web paths cannot drift.
- [Implemented for the report path] Make report construction deterministic and read-only. Weather-station lookup and other network work completes before rendering and report generation does not mutate the project.
- [Implemented with a static tile viewport and offline coordinate table] Avoid a JavaScript mapping dependency while preserving labeled location context and an offline fallback.
- [Implemented] Write report files atomically by validating a temporary sibling file before replacing the requested destination.
- Add report-schema compatibility rules so saved or queued report data remains renderable after application upgrades.

## Verification

- Add golden tests for the normalized report model and representative HTML output.
- Validate generated HTML and run automated accessibility checks.
- Add browser visual-regression coverage at desktop and mobile widths plus print-preview coverage.
- [Implemented for core report sections, recommendations, and review conditions] Add cross-format parity checks for every required section and reported value. Expand assertions as new schema fields are introduced.
- Cover special characters, long notes, missing optional data, empty charts, large candidate sets, zero-value financial inputs, and extreme unit conversions.
