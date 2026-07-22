# Collection surfaces

Collection surfaces describe the areas that receive rainfall and direct a portion of it to storage.

Open **Collection surfaces** to add and edit collection areas. Select the information icon beside the tab's surface table for guidance on area measurement. Roof collection area is the gross horizontal plan-view area projected over the ground, not the larger area measured along a sloped roof surface.

## Add a standard surface

Choose a predefined surface type and enter its collection area. The application supplies the current default runoff coefficient for that surface type.

Examples include roof membrane, asphalt-shingle roof, and metal roof. Default coefficients are starting assumptions and should be checked against project conditions and design guidance.

## Edit a surface

Double-click a collection-surface row to open the edit dialog. Modify its name, area, surface type, runoff coefficient, or first-flush depth as applicable.

The edit dialog displays the default runoff coefficient below the editable coefficient. This makes it possible to compare the project value with the application default.

## Add a custom surface

Use **Add collection surface** when the predefined list does not represent the project. Enter a descriptive name, area, and defensible runoff coefficient.

## Runoff coefficient

The runoff coefficient is the fraction of incident rainfall assumed to become collectable runoff. It normally ranges from `0` to `1`.

A higher coefficient produces more calculated gross runoff for the same rainfall and area. Do not reduce it again for a first-flush diversion that is configured explicitly; the engine reports that loss separately.

## First-flush diversion

Enter a non-negative first-flush depth for each surface. The value is inches in English (I-P) projects and millimeters in Metric (SI) projects; it is stored internally in inches. Zero disables diversion for that surface.

The **Antecedent dry period** defines rainfall events using rainfall history and defaults to the paper's recommended single dry day. Enter the threshold in either days or hours; changing the unit converts the displayed value without changing the duration. A wet observation begins a new event when it is the first wet observation or when the time since the preceding wet observation exceeds the configured duration. First flush is diverted only on that first wet observation; consecutive wet observations do not divert another first flush. If rainfall on the first observation is shallower than the configured diversion depth, all runoff from that observation is diverted and no unused allowance carries to the next observation.

For each surface, the calculator follows the paper's runoff equation by subtracting the first-flush depth before applying area and runoff coefficient. Equivalently, diverted volume is `area x runoff coefficient x min(rainfall depth, first-flush depth)` with the required unit conversions.

This rainfall-history criterion follows the preferred criterion reported by Khan's 2026 multi-model comparison, [“How much to divert? A multi-model analysis of first flush optimisation in rainwater harvesting systems”](https://doi.org/10.1080/1573062X.2026.2695189). The calculator implements the hydraulic rainfall-history criterion; it does not reproduce the paper's broader savings and economic optimization models.
