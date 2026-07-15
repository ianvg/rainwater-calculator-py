# Water demand

Water demand describes how stored rainwater is consumed. Enter only end uses supplied by the proposed rainwater system.

## Demand settings

Open **Demand parameters** to configure simple daily demand and detailed monthly end-use inputs. The general demand controls appear above the monthly table. Available categories include occupancy-related fixtures, indoor processes, irrigation, vehicle washing, and other uses.

Unit labels appear beside input fields and in monthly-demand table headings. Confirm whether the project is using imperial or metric units before entering values.

## Hourly demand schedules

Open **Schedules**, immediately after **Rainwater Data**. The left management pane follows the OpenStudio toolbar pattern: select the white plus in the green circle to create and edit a typical-week schedule, select the white `x2` in the blue circle to duplicate the selected schedule, or select the white x in the red circle to delete it. The three controls are adjacent. Schedule copies are persisted with the project, and the selected list item is the active profile used by hourly analysis. Deleting the final schedule disables hourly analysis and restores the default even profile. Use **Analysis settings > Enable hourly demand schedule** to enable or disable hourly scheduling without deleting saved profiles.

The **Common schedules** library provides **Always on**, **Always off**, and **8 AM to 5 PM weekdays** templates. Choose a template and select **Add to project** (or press Enter) to create an editable project-owned copy. The weekday business-hours template applies demand from 8:00 AM through 4:59 PM and has no weekend demand.

The typical-week editor defines 24 hourly fractions for each day from Monday through Sunday; every day must total 100% of that day's calculated demand. Copy controls can reuse Monday as the weekday or whole-week profile.

This follows the general [OpenStudio ScheduleRuleset](https://openstudio-sdk-documentation.s3.amazonaws.com/cpp/OpenStudio-3.8.0-doc/model/html/classopenstudio_1_1model_1_1_schedule_ruleset.html) pattern: time/value day profiles are selected according to the day of week. The calculator currently provides one explicit typical week rather than date-range rules, holidays, or design-day schedules. Because imported ACIS and ECCC rainfall is daily, each day's collected rainfall enters after hour 23, at the end-of-day midnight boundary. It cannot satisfy demand from earlier hours on that date.

## Rainwater system topology

Hourly analysis uses validated component-and-connection templates derived from the applied system type. A direct system routes the primary tank through a distribution pump to the end uses. An indirect system routes it through a filtration pump, filter, booster tank, and unlimited-capacity booster pump. Both templates include collection, overflow discharge, end uses, and municipal backup paths.

For an indirect system, end-use demand draws from the booster tank. When the booster level falls below the configured **Booster refill level**, a refill cycle starts and remains active until the booster tank is full. The filtration pump transfers available primary-tank water at no more than its configured flow capacity; the default is 20 gal/min. Filter recovery is applied to this flow. If primary-tank water cannot meet the commanded refill flow and municipal backup is enabled, unlimited-capacity municipal water supplies the difference directly to the booster tank. The simulation tracks municipal and rainwater volumes separately so municipal makeup does not count as rainwater reliability. Rainfall enters the primary tank at the end of each simulated day.

Hourly results include primary-tank and booster-tank levels, pump delivery, filter throughput and loss where applicable, municipal makeup, rainwater shortfall, system unmet demand, and overflow. Distribution-pump capacity, filtration-pump capacity, filtration recovery, booster storage, initial booster fill, refill level, and municipal backup availability are configured under **System parameters**. A zero pump capacity means unlimited flow; a zero booster size keeps the indirect path in pass-through mode without refill control.

## Monthly demand

Monthly values allow seasonal uses such as irrigation or cooling demand to vary through the year.

Double-click a monthly-demand row to edit its values. Enter the demand for each month using the units displayed in the column headings.

## Occupancy

Male and female occupancy inputs represent people rather than a volume. Associated fixture rates and use assumptions determine the calculated water demand.

## Review checks

- Do not count an end use in both simple demand and detailed demand unless that is intentional.
- Confirm whether values are daily or monthly.
- Verify seasonal schedules.
- Check fixture-use and occupancy assumptions.
- Confirm that displayed units match the source calculations.
