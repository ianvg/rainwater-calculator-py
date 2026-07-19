# Analysis and results

When an analysis has already been run, the calculator records a fingerprint of the rainfall and simulation inputs used for that run. If rainfall, collection surfaces, demand, tank parameters, or reliability-curve settings change, opening the **Results** tab displays a warning that the analysis must be run again. Project metadata such as the name, address, coordinates, and display units does not invalidate an analysis.

## Compare tank sizes

Open **Analysis settings**, immediately to the left of **Results**, to configure the reliability-curve range, primary tank, initial fill, and minimum operating level. Add one or more sizes to **Tank size comparison** and run the analysis. The table reports demand reliability for every comparison size, including sizes that do not fall on the regular graph step. Comparison sizes are saved with the project.

Select **Multi-tank comparison** to enable the tank-size comparison controls. The controls remain disabled when this option is clear. Existing comparison sizes remain saved while disabled but are excluded from multi-tank analysis and output.

The primary tank controls the detailed daily tank-level results, report tank summary, and selected marker on the reliability curve. Double-click a comparison row, or select it and choose **Use as primary**, to make that size the primary tank. Changing comparison sizes invalidates the saved analysis until it is run again.

## Results views

The **Results** tab contains **Single-tank summary**, **Candidate performance**, **Multitank summary**, and **Hourly results** sub-tabs. Single-tank summary shows the primary tank's reliability curve, daily storage, distribution, yearly reliability, and result rows. Multitank summary overlays every tank entered in **Tank size comparison** on three charts: tank water over time, tank-level distribution, and yearly demand reliability. Tank-level distributions use six percentage-of-capacity bins so different tank sizes can be compared on the same scale.

**Candidate performance** is a sortable table covering every capacity on the reliability curve. Each row reports reliability, total demand, rainwater supplied, sewer-eligible rainwater supplied, rainwater shortfall, municipal makeup, remaining system unmet demand, overflow, first-flush loss, treatment loss, and final primary-tank storage. When financial inputs are configured, it also reports end-use-aware net annual savings and simple payback. Select a row and choose **Use selected as primary**, or double-click it, to copy that capacity into the primary-tank input before rerunning the detailed analysis. **Export CSV** writes the full candidate dataset using the project's displayed volume unit.

Comparison simulations are saved with completed project analysis and restored when the project is reopened. Add at least two comparison sizes and run the analysis to compare multiple tanks together.

Changing only the project unit system does not require another analysis. Simulation values are stored in consistent internal units, and Results converts the saved tables and charts for display. When Results is opened after such a change, the application reports that the units were converted. Changes to physical or simulation parameters still require a rerun.

The results table contains every simulated daily record. Use its vertical scrollbar to move from the beginning to the end of the analysis period and its horizontal scrollbar to inspect all result columns.

The analysis simulates storage behavior through the rainfall record for a range of tank sizes.

## Analysis settings

Review the minimum and maximum tank size, graph step, initial storage assumptions, and any other available settings. Units are displayed next to numeric fields.

Each recurring-daily demand object selects how many days per week it applies. A five-day object applies Monday through Friday. Monthly-volume objects remain distributed across every day of the selected month, then follow their assigned hourly schedule within each day.

Enter the desired **Number of steps** and select **Auto** to divide the tank-size range into that many increments. New projects default to 20 steps. The selected count is stored with the project.

## Run the analysis

Select **Run analysis > Run single-tank analysis** or press `Ctrl+R` to analyze the primary tank without running the comparison tanks. Select **Run analysis > Run multi-tank analysis** or press `Ctrl+Alt+R` to analyze the primary tank and every enabled comparison size. Multi-tank analysis requires **Multi-tank comparison** to be enabled and at least one comparison size. The status area reports the current analysis part and progress.

While an analysis is running, select **Cancel analysis** beside the bottom progress bar to interrupt it. Cancellation is checked throughout reliability-curve and individual tank simulations. Any previous completed results remain available; partial results from the cancelled run are discarded.

When an hourly schedule is enabled, the primary-tank analysis also produces hourly component results. Open **Results > Hourly results** and select a year to inspect hourly storage, demand, pump and filter flow, municipal makeup, rainwater shortfall, and overflow. The year selector prevents long weather records from overloading the results table while the complete hourly record remains stored in the project.

If analysis cannot start, check that rainfall data has been imported and that required numeric values are valid and positive.

## Optimize an indirect system

The dedicated **Optimization** tab starts with a sample planning catalog of three primary tanks, three filtration pumps, and three buffer tanks. Select **Edit sample catalog** to open a bulk CSV-style editor where product category, name, capacity, installed cost, and filtration-pump power can be viewed, pasted, or changed. The edited catalog is saved with the project. It is illustrative input and is not vendor data or a market quotation. See [Engineering optimization](optimization.md) for the complete problem structure, assumptions, equations, classifications, and limitations.

Choose an objective from **Simple payback**, **Net annual savings**, **Rainwater reliability**, or **Analysis-period net benefit**. The optimizer runs every catalog combination through the hourly indirect-system model and ranks only feasible designs by that objective. Minimum reliability is always available; maximum annual municipal makeup, maximum installed cost, and a positive-net-annual-savings requirement are optional constraints. Leave either maximum field blank for no limit. The result table includes annual municipal makeup alongside reliability, energy, cost, savings, and payback. The main progress bar and status line update after each combination and reach 100% when optimization finishes.

At minimum, review **Minimum rainwater reliability**, **Electricity price**, and the selected objective before running the optimizer. The calculation reuses rainfall, collection, demand, minimum operating level, filter recovery, municipal-backup settings, and the assumptions on the **Financial analysis** tab. Catalog component costs are added to the base installed system cost. Estimated filtration-pump electricity and annual maintenance are deducted from annual water and sewer savings.

The current catalog is illustrative and is not vendor data or a market quotation. Product identifiers, capacities, power, and prices are placeholders for development and early planning. A result marked **Infeasible** does not meet the selected rainwater-reliability target. **Not achieved** means net annual savings are not positive, so a finite simple payback cannot be calculated.

## Reliability curve

The reliability curve compares tank size with the percentage of simulated calendar days on which the system can provide 100% of that day's water demand. For each day, the simulation compares the water available in the tank immediately before withdrawal with the full daily demand. A day is reliable when the available water is greater than or equal to that demand. Reliability is calculated as:

`reliability (%) = days with 100% of daily demand met / total simulated days x 100`

Days with zero demand count as days whose complete demand was met. The minimum operating level reduces the water available for normal withdrawal and therefore can affect reliability. Hover near chart points to inspect values. Tick marks help compare neighboring tank sizes.

The complete collection, demand, storage, overflow, withdrawal, and conservation procedure is documented in [Daily analysis formulas and mass balance](daily-analysis-method.md).

Increasing tank size generally improves reliability until collection or demand becomes the limiting factor. The curve should be interpreted together with project cost, available space, overflow, required backup supply, and design criteria.

## Tank water over time

The tank-water chart shows one calendar year of simulated storage for the selected tank size. Use the left and right controls to move through the available years, or type an available year in the year field and press `Enter`. Point markers can be hidden when the record is dense, leaving a clearer line chart.

## Yearly demand reliability

The yearly demand reliability chart is a 100% stacked bar chart. Each bar represents one calendar year and divides its simulated days into days when the complete daily demand was met by rainwater and days when it was not. The two percentages always sum to 100%. Hover over a bar segment to inspect the yearly day counts and percentages.

## Saved results

Completed results are stored when the project is saved. Reopening the project restores the results and charts without rerunning the analysis. Rerun the analysis after changing relevant rainfall, demand, surface, or tank settings; display-unit changes are converted without rerunning.
