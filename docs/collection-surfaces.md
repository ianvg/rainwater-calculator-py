# Collection surfaces

Collection surfaces describe the areas that receive rainfall and direct a portion of it to storage.

Open **Collection surfaces** to add and edit collection areas. Select the information icon beside the tab's surface table for guidance on area measurement. Roof collection area is the gross horizontal plan-view area projected over the ground, not the larger area measured along a sloped roof surface.

## Add a standard surface

Select **Add collection surface** to open the compact surface library. Choose a predefined surface type and enter its collection area. The application supplies the current default runoff coefficient for that surface type. The selected surface is added to the project table even when its area is left blank, so the area can be entered later. Unselected library templates remain hidden; use **Custom surface** when none of the predefined types fit.

Examples include roof membrane, asphalt-shingle roof, and metal roof. Default coefficients are starting assumptions and should be checked against project conditions and design guidance.

## Edit a surface

Double-click a collection-surface row to open the edit dialog. Modify its name, area, surface type, or runoff coefficient as applicable. First-flush settings belong to the first-flush device in the system builder.

The edit dialog displays the default runoff coefficient below the editable coefficient. This makes it possible to compare the project value with the application default.

## Add a custom surface

Use **Custom surface** in the library when the predefined list does not represent the project. Enter a descriptive name, area, and defensible runoff coefficient.

## Runoff coefficient

The runoff coefficient is the fraction of incident rainfall assumed to become collectable runoff. It normally ranges from `0` to `1`.

A higher coefficient produces more calculated gross runoff for the same rainfall and area. Do not reduce it again for a first-flush diversion that is configured explicitly; the engine reports that loss separately.

## First-flush diversion

Select the inline **First-flush device** in the system builder to enter a non-negative diversion depth for each collection surface. The value is inches in English (I-P) projects and millimeters in Metric (SI) projects; it is stored internally in inches. Zero disables diversion for that surface. Removing the device, or routing collection directly to the primary tank, disables all first-flush diversion while leaving the stored device settings available for later use.

### Sizing methods

**Manual per-surface depth (legacy)** preserves the original workflow. The analysis uses each surface's entered depth without imposing a guided minimum. Existing and older projects load in this mode, so enabling the new guidance does not silently change prior results.

**Guided three-layer sizing** provides a planning assistant without replacing the explicit surface inputs:

1. The **location layer** identifies a documented built-in baseline from the project's country and state or province where one is available. The initial built-in set covers the Australian `0.20 mm` planning rule of thumb, the Canadian `0.30 mm` model-code provision, the Texas `0.41 mm` minimum, and the Washington and District of Columbia `0.508 mm` lower baselines. Coordinates are not treated as a direct predictor of contamination. When no built-in rule is identified, verify the applicable local requirement.
2. The **design layer** selects the code/minimum baseline, an enhanced non-potable `1.2 mm` target, a conservative/high-deposition `2.0 mm` target, or a custom/site-tested value subject to the identified regulatory floor. These are transparent planning presets, not water-quality guarantees.
3. The **rainfall-history layer** uses the antecedent dry period below to decide when diversion occurs.

Choose **Apply guided floor to active surfaces** to raise active surface depths below the selected target. Larger site-specific depths are retained. This explicit action prevents a later address change from silently changing analysis inputs. You can return to manual mode or edit any surface depth at any time.

The location baseline is a starting point, not a complete code database. Confirm the governing authority and consider intended use, roof material and condition, trees and animals, local air quality, wildfire or industrial exposure, maintenance, and treatment. First flush is pretreatment; water intended for drinking still requires an appropriate water-safety assessment and treatment train.

Built-in values are traceable to [Australian YourHome guidance](https://www.yourhome.gov.au/water/rainwater), the [Canadian model plumbing-code text](https://publications-cnrc.canada.ca/eng/view/ft/?dp=2&dsl=en&id=6e7cabf5-d83e-4efd-9a1c-6515fc7cdc71), the [Texas Water Development Board manual](https://www.twdb.texas.gov/innovativewater/rainwater/doc/RainwaterHarvestingManual_3rdedition.pdf), the [Washington plumbing provision](https://lawfilesext.leg.wa.gov/Law/WSR/2012/07/12-07-018.htm), and [District of Columbia guidance](https://doee.dc.gov/sites/default/files/dc/sites/ddoe/publication/attachments/Ch3.2RainwaterHarvesting_0.pdf). The preset context is supported by [Lay et al. (2024)](https://doi.org/10.3390/w16101421). See the [WHO rainwater collection technical sheet](https://cdn.who.int/media/docs/default-source/wash-documents/sanitary-inspection-packages/2-tfs-rainwater-collection-storage-d.pdf) for drinking-water risk management and maintenance context.

The first-flush device's **Antecedent dry period** defines rainfall events using rainfall history and defaults to the paper's recommended single dry day. Enter the threshold in either days or hours; changing the unit converts the displayed value without changing the duration. A wet observation begins a new event when it is the first wet observation or when the time since the preceding wet observation exceeds the configured duration. First flush is diverted only on that first wet observation; consecutive wet observations do not divert another first flush. If rainfall on the first observation is shallower than the configured diversion depth, all runoff from that observation is diverted and no unused allowance carries to the next observation.

For each surface, the calculator follows the paper's runoff equation by subtracting the first-flush depth before applying area and runoff coefficient. Equivalently, diverted volume is `area x runoff coefficient x min(rainfall depth, first-flush depth)` with the required unit conversions.

After running an analysis, open **Results > First-flush summaries** to review reconciled yearly and rainfall-event totals for gross runoff, first-flush diversion, and net collection. Event rows retain the simulation event identifier and timing; yearly event counts assign an event to the year in which it begins, even if the event continues into the next year. The same tables are available as an optional report section.

This rainfall-history criterion follows the preferred criterion reported by Khan's 2026 multi-model comparison, [“How much to divert? A multi-model analysis of first flush optimisation in rainwater harvesting systems”](https://doi.org/10.1080/1573062X.2026.2695189). The calculator implements the hydraulic rainfall-history criterion; it does not reproduce the paper's broader savings and economic optimization models.
