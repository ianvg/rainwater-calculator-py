# Water demand

Water demand describes how stored rainwater is consumed. Enter only end uses supplied by the proposed rainwater system.

## Demand settings

Open **Demand parameters** to manage the project's demand objects and reusable demand-object library in one object-centered workspace. Separate simple, daily-only, hourly-only, and monthly-input pages are no longer required.

Unit labels appear beside input fields and in monthly-demand table headings. Confirm whether the project is using imperial or metric units before entering values.

## Demand objects

Each demand object has a name, descriptive type, schedule, and one of three calculation modes: scheduled instantaneous flow, recurring daily volume, or January-December monthly volumes. The editor places these choices in separate **Identity**, **Demand calculation**, and **Billing** sections. Selecting a mode shows only its applicable inputs and explains how the selected schedule is interpreted. Built-in library templates cover simple recurring demand, toilets, urinals, ice making, cooling towers, ice skating, indoor processes, spray and drip irrigation, vehicle washing, and other outdoor uses.

Monthly values are edited directly in the demand-object dialog. Recurring daily demand can optionally use January-December daily-volume overrides; monthly-volume mode requires a total for at least one month. The live summary estimates a typical weekday, typical week, January demand, and sewer-charge eligibility. Inline messages identify missing names, schedules, weekdays, nonnumeric values, and zero-demand configurations before the object can be saved.

Each object also declares whether rainwater delivered to that end use is eligible for sewer-charge savings. Irrigation defaults to sewer-exempt; other types default to eligible. These are billing assumptions rather than physical properties, so review and edit the checkbox for local utility rules. When available rainwater cannot meet all end uses, the model has no demand-priority order and allocates delivered rainwater proportionally across that timestep's demands before calculating the sewer-eligible portion.

When an older project is opened, its simple recurring, occupancy-derived toilet/urinal, and monthly category inputs are converted once into equivalent demand objects. The legacy fields are then cleared, preserving calculated daily and hourly totals without double counting. Migrated objects initially retain the project's legacy sewer-eligibility percentage; editing an object replaces that fallback with its explicit eligible/exempt setting. Newly added objects are assigned automatically to every End-uses block; newly added End-uses blocks receive all existing project demand objects.

Only schedules already present in the current project's Schedules list can be assigned. Copy a template or custom library schedule into the project before creating an object. Each demand object has an instantaneous on-flow that can be entered in **gpm**, **gal/hr**, **lpm**, or **liter/hr**. Switching the unit in the editor converts the current value without changing the physical flow. For every hour, demand equals the on-flow multiplied by the schedule value and the appropriate time conversion. Daily analysis sums those hourly volumes; hourly analysis applies each hourly volume directly. Recurring daily objects use explicit Monday-Sunday checkboxes rather than assuming that a count of operating days always means Monday through Friday. A project schedule cannot be deleted while a demand object references it, and renaming the schedule updates those references automatically.

The **Demand object library** appears to the right of the project demand-object list. Built-in templates and reusable custom objects are grouped separately. Double-click a library object, press Enter, or use **Add selected to project** to configure its project schedule and add it. The toolbar can create a custom object, duplicate any template into the custom group, or delete a selected custom object. **Save selected to library** stores a project object for reuse without retaining its project-specific schedule assignment.

## Hourly demand schedules

Open **Schedules**, immediately after **Rainwater Data**. The left management pane follows the OpenStudio toolbar pattern: select the white plus in the green circle to create and edit a typical-week schedule, select the white `x2` in the blue circle to duplicate the selected schedule, or select the white x in the red circle to delete it. The three controls are adjacent. Schedule copies are persisted with the project, and the selected list item is the active profile used by hourly analysis. Deleting the final schedule disables hourly analysis and restores the default even profile. Use **Analysis settings > Enable hourly demand schedule** to enable or disable hourly scheduling without deleting saved profiles.

To rename a project schedule, select it, edit **Schedule name** under Schedule properties, and select **Rename** or press Enter. Press F2 while the schedule list has focus to select the name field. Names cannot be blank or duplicate another project schedule name.

The Schedule library appears on the right and groups entries under **Templates** and **Custom**. Templates provide **Always on**, **Always off**, and **8 AM to 5 PM weekdays** profiles. Select an entry and choose **Add selected to project**, double-click it, or press Enter to create an editable project-owned copy. The weekday business-hours template applies demand from 8:00 AM through 4:59 PM and has no weekend demand.

Use the green plus above the library to name and edit a new custom profile. The blue `x2` duplicates the selected template or custom profile into the Custom group, and the red x deletes a selected custom profile. Built-in templates cannot be deleted. To reuse a project schedule, select it in the project list and choose **Save selected to library**. The calculator stores a snapshot in the local custom library. Saving the same custom name again requires confirmation before replacing its library copy; built-in template names are reserved.

The typical-week editor defines 24 hourly multipliers for each day from Monday through Sunday. Values range from `0` (off, or 0% of the on value) to `1` (fully on, or 100% of the on value). Intermediate values such as `0.5` represent partial operation. Demand-object multipliers act directly on instantaneous flow. The active project-level schedule is normalized only when distributing simple and monthly daily demand totals. Copy controls can reuse Monday as the weekday or whole-week profile.

This follows the general [OpenStudio ScheduleRuleset](https://openstudio-sdk-documentation.s3.amazonaws.com/cpp/OpenStudio-3.8.0-doc/model/html/classopenstudio_1_1model_1_1_schedule_ruleset.html) pattern: time/value day profiles are selected according to the day of week. The calculator currently provides one explicit typical week rather than date-range rules, holidays, or design-day schedules. Because imported ACIS and ECCC rainfall is daily, each day's collected rainfall enters after hour 23, at the end-of-day midnight boundary. It cannot satisfy demand from earlier hours on that date.

## Rainwater system topology

Hourly analysis uses validated component-and-connection templates derived from the applied system type. A direct system routes the primary tank through a distribution pump to the end uses. An indirect system routes it through a filtration pump, filter, buffer tank, and unlimited-capacity booster pump. Both templates include collection, overflow discharge, end uses, and municipal backup paths.

For an indirect system, end-use demand draws from the buffer tank. When the buffer level falls below the configured **Buffer refill level**, a refill cycle starts and remains active until the buffer tank is full. The filtration pump transfers available primary-tank water at no more than its configured flow capacity; the default is 20 gal/min. Filter recovery is applied to this flow. If primary-tank water cannot meet the commanded refill flow and municipal backup is enabled, unlimited-capacity municipal water supplies the difference directly to the buffer tank. The simulation tracks municipal and rainwater volumes separately so municipal makeup does not count as rainwater reliability. Rainfall enters the primary tank at the end of each simulated day.

Hourly results include primary-tank and buffer-tank levels, pump delivery, filter throughput and loss where applicable, municipal makeup, rainwater shortfall, system unmet demand, and overflow. Distribution-pump capacity, filtration-pump capacity, filtration recovery, buffer storage, initial buffer fill, refill level, and municipal backup availability are configured under **System parameters**. A zero pump capacity means unlimited flow; a zero buffer size keeps the indirect path in pass-through mode without refill control.

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
