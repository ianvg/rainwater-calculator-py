# Engineering optimization

The **Optimization** tab treats indirect rainwater-system sizing as a deterministic, dynamic, nonlinear, simulation-based, constrained, discrete engineering optimization problem. It evaluates catalog equipment with the same hourly water-balance model used by the application and ranks only designs that satisfy the active constraints.

## How the problem is organized

An engineering optimization is commonly written as:

```text
find design variables x
that minimize or maximize objective f(x)
subject to inequality constraints g(x) <= 0,
equality constraints h(x) = 0, and allowable choices x in X
```

The application separates the problem into the following parts:

| Part | Meaning | Current implementation |
| --- | --- | --- |
| Design variables | Decisions left open to the optimizer | Primary tank product, filtration pump product, buffer tank product |
| Fixed parameters | Project values not changed by the optimizer | Rainfall, collection surfaces, demand, controls, tariffs, maintenance, electricity price |
| Governing model | Predicts each candidate's behavior | Hourly collection, storage, treatment, booster, demand, backup, and overflow mass balance |
| Objective | Defines which feasible design ranks highest | Simple payback, net annual savings, rainwater reliability, or analysis-period net benefit |
| Constraints | Define acceptable designs | Minimum reliability and optional makeup, cost, and positive-savings limits |
| Search method | Chooses which candidates to evaluate | Deterministic exhaustive enumeration of the current catalog |

The **Optimization problem definition and assumptions** table shows the actual values used, their classification, and the tab where each value is edited. Existing project inputs are not copied into optimization-specific fields, preventing two versions of the same assumption from drifting apart.

## Design variables

The current optimizer leaves three discrete catalog selections open:

- Primary tank product and capacity.
- Filtration pump product, capacity, power, and cost.
- Buffer tank product and capacity.

Select **Edit sample catalog** to view or bulk-edit comma-separated catalog rows in a separate window. Each row contains category, product name, capacity, installed cost, and power. Primary- and buffer-tank capacities use gallons; filtration-pump capacity uses gallons per hour; power uses kW. The catalog requires at least one product in every category and is saved with the project.

The supplied catalog is illustrative. Its product identifiers, capacities, power, and prices are development assumptions, not vendor data, quotations, or engineering recommendations.

## Objectives

Only one objective is used for ranking during a run:

- **Simple payback** minimizes net installed cost divided by positive net annual savings. A candidate with non-positive savings has no finite payback.
- **Net annual savings** maximizes avoided water and eligible sewer charges after maintenance and filtration-pump electricity.
- **Rainwater reliability** maximizes the percentage of hourly demand intervals fully supplied by rainwater.
- **Analysis-period net benefit** maximizes undiscounted net annual savings over the selected analysis period minus net installed cost.
- **Lifecycle NPV** maximizes discounted lifecycle value after escalation, electricity, maintenance, and recurring replacement costs.

Changing the objective changes ranking, not the hydraulic simulation or feasibility requirements.

## Constraints and feasibility

Minimum rainwater reliability is always evaluated. Optional constraints include maximum annual municipal makeup, maximum installed cost, and positive net annual savings. Blank maximum fields mean no limit. A candidate receives a rank only when every active constraint is satisfied.

Physical limits enforced inside the simulation include non-negative storage, tank-capacity limits, the primary minimum operating level, filtration-pump capacity, booster capacity, filter recovery, demand withdrawal, municipal-backup behavior, and overflow. Equipment catalog values must have positive capacity and non-negative cost and power.

## Fixed assumptions used by optimization

The optimizer reads the following project values without changing them:

- Historical daily rainfall record and collection surfaces.
- Runoff coefficients and collection areas.
- Recurring demand, demand objects, and hourly schedules.
- Primary-tank initial fill and minimum operating level.
- Filter recovery.
- Booster initial fill and refill level.
- Municipal-backup setting.
- Water and sewer tariffs and sewer-eligible percentage.
- Base installed cost and incentives.
- Fixed and percentage maintenance.
- Electricity price, financial analysis period, discount rate, escalation, and replacement assumptions.

Current model assumptions that materially affect interpretation are:

- Candidate systems are evaluated as indirect systems.
- Hydraulic calculations use hourly timesteps.
- Each day's collected rainfall enters storage after that day's demand, a conservative timing assumption.
- Municipal backup does not count as rainwater reliability or rainwater supplied.
- Filtration-pump energy is estimated from simulated transferred volume divided by rated capacity, multiplied by catalog power.
- Financial calculations use flat tariffs and the shared lifecycle cash-flow engine. NPV uses year-end cash flows and the configured discount and escalation rates.
- Catalog component costs are added to the base installed system cost; incentives are subtracted once.
- Percentage maintenance applies to total installed cost.
- Historical rainfall and configured demand are treated deterministically; uncertainty and climate projections are not currently sampled.

## Candidate evaluation

For every primary-tank, filtration-pump, and buffer-tank combination, the application:

1. Creates an indirect-system candidate.
2. Runs the same hourly mass-balance rules in aggregate-only mode, without constructing a full timestep table.
3. Calculates reliability, annual rainwater supply, municipal makeup, overflow, and pump energy.
4. Adds catalog costs to the base project cost.
5. Calculates maintenance, savings, payback, and analysis-period benefit.
6. Applies all active constraints.
7. Ranks feasible candidates by the selected objective.

Candidate-independent hourly demand, rainfall collection, and calendar arrays are prepared once and reused by every combination. Up to four unchanged prepared-input sets are retained in a bounded in-memory cache for repeated runs. The aggregate evaluator preallocates numeric arrays and returns only annual totals and reliability; the detailed hourly engine remains available for normal analysis and result inspection. This reduces DataFrame construction and repeated schedule calculations without changing the governing mass balance.

Optimization runs on a background worker thread so the Tkinter interface remains responsive. A snapshot of the project and rainfall record is taken when the run starts; edits made while it is running apply to the next run rather than changing the active calculation. Progress messages are returned safely to the main interface thread after every combination. Results show feasible ranking, selected products, reliability, municipal makeup, energy, installed cost, net annual savings, and simple payback.

## Classification and limitations

The current problem is:

- **Single-objective:** one ranking objective is selected per run.
- **Deterministic:** identical inputs produce identical results.
- **Dynamic:** tank volumes and flows change hourly.
- **Nonlinear:** storage limits, overflow, refill controls, reliability, and payback introduce discontinuities and ratios.
- **Discrete:** equipment is selected from a finite catalog.
- **Simulation-based:** performance is obtained by running the hourly model rather than a closed-form equation.

Exhaustive enumeration is appropriate while the catalog is modest because it is transparent and reproducible. Aggregate-only evaluation and prepared-input caching are implemented. Larger catalogs will still require candidate screening, parallel worker processes, cancellation, and coarse-to-fine search. Compiling the remaining sequential state loop may provide another improvement if profiling justifies an additional runtime dependency. Future multi-objective work should report a Pareto frontier rather than implying that one design is best for every engineering and economic criterion. Sensitivity and uncertainty analysis are also needed before results can support final design decisions.
