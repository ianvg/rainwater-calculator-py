# Financial analysis

The **Financial analysis** tab provides a selected-tank simple-payback estimate based on the latest hydraulic simulation. Unlike the original ROI spreadsheet workflow, the application does not ask the user to multiply demand by an estimated tank efficiency. It calculates delivered rainwater as simulated demand minus simulated unmet rainwater demand and averages the delivered volume across the modeled calendar years.

Enter the currency label, tariff billing unit, water and sewer rates, installed cost, incentives or rebates, fixed annual maintenance, annual maintenance as a percentage of installed cost, and analysis period. **Rainwater supply eligible for sewer savings** allows outdoor or otherwise sewer-exempt consumption to be excluded from the avoided sewer charge.

The tab reports average annual rainwater supplied, avoided municipal-water charges, avoided sewer charges, their combined gross annual utility savings, annual maintenance, net annual savings, net installed cost after incentives, simple payback, and undiscounted net benefit over the analysis period. Avoided municipal-water charges equal average annual rainwater supplied multiplied by the normalized water tariff. Payback displays **Not achieved** when net annual savings are zero or negative.

This first release uses simple flat tariffs. It excludes tariff tiers, escalation, financing, discount rates, pump energy, equipment replacement, net present value, and internal rate of return. These lifecycle features and candidate-tank financial comparisons remain on the roadmap.
