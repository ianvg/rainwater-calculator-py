# Equipment catalog roadmap

The first equipment-library release establishes stable product IDs, a reusable user-level library, project snapshots and overrides, candidate/fixed/excluded dispositions, structured project constraints, required companion categories, and optional pump-to-filtration-unit flow-range checking.

## Implemented foundation

- Shared editable equipment library with illustrative starter products.
- Explicit **Add/update starter products** operation; existing project snapshots remain unchanged.
- Explicit **Update from library** operation for selected project snapshots.
- Project overrides that survive library updates and can be cleared independently.
- Four optimization categories: primary tank, filtration pump, filtration unit, and buffer tank.
- Approved-vendor, required-tag, and required-standard eligibility.
- Voltage, phase, pressure-class, and connection-size requirements.
- Optional length, width, height, footprint, and access-clearance constraints.
- Missing constrained values pass with a warning by default, with a project option to require them.
- Optional filtration flow-range compatibility and required companion categories.
- Compatibility review with rejection and warning reasons.

## Next rule capabilities

The rule representation will be clarified using real project catalogs before adding a general-purpose rule editor. Candidate additions include:

1. Explicit compatible and prohibited product pairs.
2. Capacity relationships, such as a minimum buffer volume derived from pump flow.
3. Pressure-drop and pump-curve relationships rather than nameplate flow alone.
4. Electrical-service aggregation across multiple selected components.
5. Alternative or quantity-based companion requirements.
6. Constraint templates for organizational standards and common project types.
7. Import validation and column mapping for vendor CSV or workbook catalogs.
8. Library revision history, comparison, and rollback.

Explicit product-pair rules and buffer-tank-to-pump capacity rules are intentionally deferred. Adding them after the compatibility-review workflow has been used on real projects avoids locking the application into a rule language that is either too narrow or too difficult to maintain.
