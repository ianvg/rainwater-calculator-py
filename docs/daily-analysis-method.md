# Daily analysis formulas and mass balance

This page documents the formulas and calculation order used by the calculator's daily tank analysis. All calculations are performed internally in inches, square feet, and US gallons. Metric (SI) project inputs and displayed results are converted at the application boundary.

## Symbols

| Symbol | Definition | Internal unit |
| --- | --- | --- |
| `C` | Physical tank capacity | gal |
| `f_init` | Initial-fill percentage divided by 100 | fraction |
| `f_min` | Minimum operating level percentage divided by 100 | fraction |
| `S[t-1]` | Physical water stored at the end of the previous day | gal |
| `G[t]` | Gross runoff from collection surfaces on day `t` | gal/day |
| `F[t]` | First-flush volume diverted on day `t` | gal/day |
| `I[t]` | Net rainwater collected on day `t`, `G[t] - F[t]` | gal/day |
| `D[t]` | Total rainwater demand on day `t` | gal/day |
| `O[t]` | Tank overflow on day `t` | gal/day |
| `Q[t]` | Rainwater supplied to demand on day `t` | gal/day |
| `U[t]` | Unmet rainwater demand on day `t` | gal/day |
| `S[t]` | Physical water stored at the end of day `t` | gal |
| `M` | Minimum operating volume | gal |

## 1. Prepare the rainfall record

The import must provide `Date` and `Precipitation` columns. Dates that cannot be parsed are removed. Precipitation values that cannot be parsed are treated as zero. Records are sorted by date before simulation.

The daily engine does not infer missing calendar dates. The number of simulated timesteps is the number of valid imported rows, so a complete daily record is recommended.

## 2. Calculate collected rainwater

For each collection surface `j`, the normal collected volume is:

```text
surface collection[j,t]
  = area[j] x runoff coefficient[j] x precipitation[t] / 12 x 7.48052
```

The factors `/ 12` and `7.48052` convert rainfall depth in inches to feet and cubic feet to gallons. Gross runoff from all surfaces is summed.

```text
G[t] = sum(surface runoff[j,t])
```

Areas are constrained to zero or greater, and runoff coefficients are constrained from 0 through 1. A rainfall-history event starts after the configured antecedent dry period. At the start of each event, the diverted runoff from surface `j` is:

```text
F[j,t] = runoff coefficient[j] x area[j] x min(rainfall[t], first-flush depth[j]) / 12 x 7.48052
I[t] = G[t] - sum(F[j,t])
```

`F[j,t]` is evaluated only on the first wet observation after the configured antecedent dry period. The threshold can be entered in days or hours and is evaluated as a continuous duration. On consecutive wet observations it is zero, even when rainfall on the event's first observation was less than the configured first-flush depth. The default is one antecedent dry day, matching Model 2 in Khan (2026). Gross runoff, first-flush loss, and net collection are retained as separate result fields.

## 3. Calculate daily demand

The recurring occupancy demand for a date in month `m` is:

```text
female toilet demand
  = female occupancy[m] x flushes/person x toilet volume/flush

male toilet demand
  = 0.5 x male occupancy[m] x flushes/person x toilet volume/flush

male urinal demand
  = 0.5 x male occupancy[m] x flushes/person x urinal volume/flush
```

Simple daily demand is added to these occupancy demands. The daily-demand schedule applies this recurring total to the first configured number of weekdays beginning with Monday. For example, five operating days applies it Monday through Friday.

Monthly non-occupancy inputs are summed and distributed evenly over the actual number of calendar days in the month:

```text
daily monthly-use demand
  = (ice making + cooling tower + ice skating + other indoor
     + spray irrigation + drip irrigation + vehicle washing + other outdoor)
    / days in month
```

Demand objects that have hourly schedules also contribute to the daily total. Each object's scheduled daily volume is:

```text
object daily demand
  = object flow in gal/min x 60 x sum(24 hourly schedule multipliers)
```

The daily demand `D[t]` is the sum of recurring, monthly-use, and scheduled demand-object volumes.

## 4. Establish tank operating volumes

For every tank size, the initial physical storage and minimum operating volume are calculated independently:

```text
initial storage = C x f_init
M = C x f_min
```

The minimum operating volume remains part of the displayed physical tank level but cannot be withdrawn for normal demand. It is not an additional demand target.

## 5. Apply the daily mass balance

The daily calculation order is important. Demand is withdrawn from opening storage before that day's collected rainfall is added. This conservative convention prevents same-day rainfall from satisfying demand on that date.

For the first day:

```text
opening storage = initial storage
```

For later days:

```text
opening storage = S[t-1]
```

Only water above the minimum operating volume is usable:

```text
available for withdrawal = max(opening storage - M, 0)
```

Rainwater supply and unmet rainwater demand are then calculated:

```text
Q[t] = min(available for withdrawal, D[t])
U[t] = max(D[t] - Q[t], 0)
storage after withdrawal = opening storage - Q[t]
```

Collected rainfall is then added, overflow is removed, and closing physical storage is capped at capacity:

```text
storage before capacity limit = storage after withdrawal + I[t]
O[t] = max(storage before capacity limit - C, 0)
S[t] = min(max(storage before capacity limit, 0), C)
```

The daily conservation equation is:

```text
S[t-1] + I[t] = S[t] + Q[t] + O[t]
```

On the first day, replace `S[t-1]` with `initial storage`. Unmet demand is not part of the water balance because it is water requested but never present in the tank.

## Worked example

Assume a 5,000 gal tank, 50% initial fill, 10% minimum operating level, 3,000 gal collected on the first day, and 1,200 gal demand.

```text
initial storage = 5,000 x 0.50 = 2,500 gal
minimum operating volume = 5,000 x 0.10 = 500 gal
opening storage = 2,500 gal
available for withdrawal = 2,500 - 500 = 2,000 gal
rainwater supplied = min(2,000, 1,200) = 1,200 gal
unmet demand = 0 gal
storage after withdrawal = 2,500 - 1,200 = 1,300 gal
storage before capacity limit = 1,300 + 3,000 = 4,300 gal
overflow = 0 gal
end storage = 4,300 gal
```

The mass balance reconciles:

```text
2,500 + 3,000 = 4,300 + 1,200 + 0 = 5,500 gal
```

## Reliability

A day is counted as reliable when `Q[t]` is greater than or equal to `D[t]`. Zero-demand days are reliable because the complete demand of zero is met.

```text
reliability (%)
  = reliable simulated days / total simulated days x 100
```

## Multiple tank sizes

The reliability curve and comparison analysis repeat the complete procedure independently for every candidate capacity. Each tank receives the same rainfall, collection surfaces, demand record, initial-fill percentage, and minimum-operating-level percentage. Water does not flow between candidate tanks, and the end state from one candidate is never used to initialize another.

Each reliability-curve row aggregates the candidate's detailed daily result rather than using a separate approximation. The saved candidate dataset retains total demand, rainwater supplied, rainwater shortfall, municipal makeup, system unmet demand, overflow, first-flush loss, treatment loss, final storage, and average annual rainwater supply. The annual value is the basis for candidate savings and payback calculations.

## Daily versus hourly system behavior

The daily analysis is a primary-tank storage balance governed by the saved system-builder topology. Collection reaches storage only through a connected rainwater-input-to-primary-tank path, and rainwater reaches demand only through a connected primary-tank-to-end-uses path. A direct pump on that path applies its hourly capacity over 24 hours. A transfer-pump and filtration-system path applies either unlimited flow or the combined capacity of the linked nominal 15, 20, 30, 40, or 50 GPM skids multiplied by their parallel quantity over 24 hours, plus the configured recovery; raw pumped water, including filter loss, is removed from primary storage. Beginning-of-hour booster controls and municipal-backup flow remain exclusive to the hourly simulation because they require subdaily state and flow ordering.

Both resolutions use a conservative end-of-day rainfall convention. The daily analysis adds collected rainfall after the day's demand. The hourly analysis adds the daily rainfall total at hour 23 after that hour's demand. A future true subdaily rainfall workflow will use observed rainfall timestamps rather than this daily allocation assumption.

## Daily result columns

| Column | Meaning |
| --- | --- |
| `CollectedGallons` | `I[t]`, rainwater collected that day |
| `DemandGallons` | `D[t]`, total requested rainwater demand |
| `SewerEligibleDemandGallons` | Portion of `D[t]` assigned to sewer-eligible end uses |
| `DemandMet` | Whether `Q[t] >= D[t]` |
| `RainwaterSuppliedGallons` | `Q[t]`, demand supplied by rainwater |
| `SewerEligibleRainwaterSuppliedGallons` | Portion of `Q[t]` allocated proportionally to sewer-eligible end uses |
| `MinimumOperatingVolumeGallons` | `M`, protected physical storage |
| `UsableWaterAvailableGallons` | Water above `M` in closing storage after collection and overflow |
| `UnmetDemandGallons` | `U[t]`, requested demand not supplied by rainwater |
| `MainsMakeupGallons` | Municipal backup supplied against `U[t]` |
| `SystemUnmetDemandGallons` | Demand remaining after rainwater and municipal backup |
| `FilterLossGallons` | Raw water withdrawn but lost through configured treatment recovery |
| `OverflowGallons` | `O[t]`, water discharged above physical capacity |
| `WaterInTankGallons` | `S[t]`, end-of-day physical tank storage |
| `ReliabilityPercent` | Full-period reliability repeated on each result row |
