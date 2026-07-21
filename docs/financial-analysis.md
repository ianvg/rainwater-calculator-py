# Financial analysis

The **Financial analysis** tab provides simple-payback and discounted lifecycle results based on the latest hydraulic simulation. Unlike the original ROI spreadsheet workflow, the application does not ask the user to multiply demand by an estimated tank efficiency. It calculates delivered rainwater from the simulation and averages delivered volume across the modeled calendar years.

Enter the currency label, tariff billing unit, water and sewer rates, installed cost, incentives or rebates, fixed annual maintenance, annual maintenance as a percentage of installed cost, analysis period, and discount rate. Separate annual escalation assumptions apply to utility rates, maintenance, electricity, and replacement costs. Each demand object controls whether its delivered rainwater is eligible for sewer-charge savings; irrigation objects default to sewer-exempt. **Legacy aggregate demand eligible for sewer savings** is retained only for aggregate demand and demand objects migrated from older projects.

Pump electricity is calculated from simulated pumped volume:

`annual pump energy = average annual pumped volume / rated pump flow x rated pump power`

Enter pump power and rated flow from a consistent operating point. A zero pump power disables the energy calculation. When pump power is positive, rated flow must also be positive. Electricity cost uses the electricity price shared with the indirect-system optimizer.

Enter a recurring equipment replacement cost and interval when lifecycle replacements are expected. A zero interval disables replacement. Replacement cost is escalated to its future-year value and charged at each interval strictly before the end of the study period; the model does not purchase a replacement on the final study date when it would provide no modeled service.

## Cash-flow timing and outputs

Year 0 contains installed cost less incentives. Avoided utility charges, maintenance, and electricity occur at each year end. Future values use their configured escalation rates and are discounted with the selected annual discount rate. The tab reports:

- first-year gross and net annual savings;
- simple payback using first-year net savings;
- nominal analysis-period net benefit, including escalation and replacements;
- lifecycle net present value (NPV);
- discounted payback;
- internal rate of return (IRR); and
- pump energy, electricity cost, and nominal replacement costs.

Water savings use all delivered rainwater; sewer savings use only delivered rainwater allocated to eligible end uses. Payback displays **Not achieved** when the applicable cumulative savings do not recover the initial cost. IRR is reported only for a conventional cash-flow sequence with exactly one sign change. It displays **Not uniquely defined** when replacement or operating cash flows create multiple sign changes, avoiding presentation of one potentially misleading IRR root.

The same lifecycle calculation is applied to every reliability-curve candidate and indirect-system optimization combination. **Lifecycle NPV** is available as an optimization objective. Candidate financial cells remain blank until at least one financial rate or cost is configured.

The current model uses flat volumetric water and sewer rates. Tiered tariffs remain excluded because defensible tier calculations require explicit billing periods, fixed-charge treatment, baseline municipal consumption, tier ordering, and rules for allocating rainwater savings across tiers. Financing, taxes, depreciation, and terminal residual value are also outside the current cash-flow model.
