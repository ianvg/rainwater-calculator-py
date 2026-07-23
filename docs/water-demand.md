# Water demand

Water demand describes how stored rainwater is consumed. Enter only end uses supplied by the proposed rainwater system.

## Demand settings

Open **Demand parameters** to manage the project's demand objects and reusable demand-object library in one object-centered workspace. Separate simple, daily-only, hourly-only, and monthly-input pages are no longer required.

Unit labels appear beside input fields and in monthly-demand table headings. Confirm whether the project is using imperial or metric units before entering values.

## Demand objects

Each demand object has a name, descriptive type, schedule, and one of four calculation modes: scheduled instantaneous flow, fixture use, recurring daily volume, or January-December monthly volumes. The editor places these choices in separate **Identity**, **Demand calculation**, and **Billing** sections. Selecting a mode shows only its applicable inputs and explains how the selected schedule is interpreted. Built-in library templates cover simple recurring demand, toilets, sinks, urinals, ice making, cooling towers, ice skating, indoor processes, spray and drip irrigation, vehicle washing, and other outdoor uses.

**Fixture use** calculates daily demand as `people x uses per person per day x volume per use`. Fixture objects accept only an **Occupancy (binary)** schedule. That reusable schedule is the sole authority for both active days and hourly timing: `1` means occupied, `0` means unoccupied, and the calculated daily fixture volume is divided evenly among that day's occupied hours. An all-zero day has no fixture demand. For toilets, the editor labels the inputs as people, flushes per person per day, and volume per flush. The built-in Toilet object starts with 1 person, 3.0 flushes per person per day, and 1.28 gallons per flush, converted to liters in Metric (SI) projects. The frequency remains editable. EPA commercial guidance estimates three toilet flushes per day for female occupants and one for male occupants, while the EPA residential WaterSense calculator assumes 5.05 flushes per person per day. Therefore, 3.0 is a visible planning default rather than a universal rule; adjust it for residential use, occupancy mix, operating hours, and observed behavior. The 1.28-gallon default corresponds to the WaterSense labeled toilet limit. See [EPA WaterSense at Work](https://nepis.epa.gov/Exe/ZyPURL.cgi?Dockey=P1017K41.TXT) and [How the WaterSense Calculator Works](https://www.epa.gov/watersense/how-watersense-calculator-works).

The built-in Sink object uses the same activity calculation with people, uses per person per day, and volume per use. It does not assume a sink volume. Enter a measured or design value, or calculate it as `flow rate x minutes per use`; this prevents a toilet flush volume from being reused accidentally.

Recurring daily demand uses one daily volume and an **Occupancy (binary)** schedule. The schedule is the sole authority for active days and hourly timing: the daily volume is applied on days with one or more occupied hours and divided evenly among those hours. The mode has no separate operating-weekday controls or January-December daily-volume overrides. Monthly-volume mode requires a total for at least one month. Fixture-use, recurring-daily, and monthly-volume modes all require an occupancy schedule. Monthly totals are divided across the month's calendar days and then distributed across that schedule's occupied hours. The live summary estimates a typical weekday, typical week, January demand, and sewer-charge eligibility. Inline messages identify missing names, schedules, nonnumeric values, and zero-demand configurations before the object can be saved.

Each object also declares whether rainwater delivered to that end use is eligible for sewer-charge savings. Irrigation defaults to sewer-exempt; other types default to eligible. These are billing assumptions rather than physical properties, so review and edit the checkbox for local utility rules. When available rainwater cannot meet all end uses, the model has no demand-priority order and allocates delivered rainwater proportionally across that timestep's demands before calculating the sewer-eligible portion.

When an older project is opened, its simple recurring, occupancy-derived toilet/urinal, and monthly category inputs are converted once into equivalent demand objects. The legacy fields are then cleared, preserving calculated daily and hourly totals without double counting. Migrated objects initially retain the project's legacy sewer-eligibility percentage; editing an object replaces that fallback with its explicit eligible/exempt setting. Newly added objects are assigned automatically to every End-uses block; newly added End-uses blocks receive all existing project demand objects.

Only schedules already present in the current project's Schedules list can be assigned. Copy a template or custom library schedule into the project before creating a demand object. Scheduled-flow mode accepts either fractional or occupancy schedules; the three occupational modes accept only occupancy schedules. Each scheduled-flow demand object has an instantaneous on-flow that can be entered in **gpm**, **gal/hr**, **lpm**, or **liter/hr**. Switching the unit in the editor converts the current value without changing the physical flow. For every hour, demand equals the on-flow multiplied by the schedule value and the appropriate time conversion. Daily analysis sums those hourly volumes; hourly analysis applies each hourly volume directly. A project schedule cannot be deleted while a demand object references it, and renaming the schedule updates those references automatically.

The **Demand object library** appears to the right of the project demand-object list. Built-in templates and reusable custom objects are grouped separately. Double-click a library object, press Enter, or use **Add selected to project** to configure its project schedule and add it. The toolbar can create a custom object, duplicate any template into the custom group, or delete a selected custom object. **Save selected to library** stores a project object for reuse without retaining its project-specific schedule assignment.

## Hourly demand schedules

Open **Schedules**, immediately after **Rainwater Data**. The left management pane follows the OpenStudio toolbar pattern: select the white plus in the green circle to create and edit a typical-week schedule, select the white `x2` in the blue circle to duplicate the selected schedule, or select the white x in the red circle to delete it. The three controls are adjacent. Schedule copies are persisted with the project, and the selected list item is the active profile used by hourly analysis. Deleting the final schedule disables hourly analysis and restores the default even profile. Use **Analysis settings > Enable hourly demand schedule** to enable or disable hourly scheduling without deleting saved profiles.

Select the red trash icon to purge every project schedule that is neither the active profile nor assigned to a demand object. The confirmation dialog lists each schedule that will be removed. Active and assigned schedules are always retained, and the reusable Schedule library is not changed. The trash artwork is adapted from the MIT-licensed [Tabler Icons](https://github.com/tabler/tabler-icons) collection.

To rename a project schedule, select it, edit **Schedule name** under Schedule properties, and select **Rename** or press Enter. Press F2 while the schedule list has focus to select the name field. Names cannot be blank or duplicate another project schedule name.

The Schedule library appears on the right and groups entries under **Templates** and **Custom**. Fractional templates provide **Always on**, **Always off**, and **8 AM to 5 PM weekdays** profiles. Binary templates provide **Always occupied** and **Occupied 8 AM to 5 PM weekdays**. Select an entry and choose **Add selected to project**, double-click it, or press Enter to create an editable project-owned copy. The weekday business-hours templates cover 8:00 AM through 4:59 PM and have no weekend activity.

Use the green plus above the library to name and edit a new custom profile. The blue `x2` duplicates the selected template or custom profile into the Custom group, and the red x deletes a selected custom profile. Built-in templates cannot be deleted. To reuse a project schedule, select it in the project list and choose **Save selected to library**. The calculator stores a snapshot in the local custom library. Saving the same custom name again requires confirmation before replacing its library copy; built-in template names are reserved.

The typical-week editor supports two schedule types. **Fractional multiplier** schedules accept values from `0` to `1` and are available to scheduled instantaneous flow. **Occupancy (binary)** schedules accept only `0` or `1` and are required by all three occupational modes. Fixture-use and recurring-daily volumes are divided evenly among occupied hours, and an all-zero day is inactive. Copy controls can reuse Monday as the weekday or whole-week profile.

This follows the general [OpenStudio ScheduleRuleset](https://openstudio-sdk-documentation.s3.amazonaws.com/cpp/OpenStudio-3.8.0-doc/model/html/classopenstudio_1_1model_1_1_schedule_ruleset.html) pattern: time/value day profiles are selected according to the day of week. The calculator currently provides one explicit typical week rather than date-range rules, holidays, or design-day schedules. Because imported ACIS and ECCC rainfall is daily, each day's collected rainfall enters after hour 23, at the end-of-day midnight boundary. It cannot satisfy demand from earlier hours on that date.

## Rainwater system topology

Hourly analysis uses validated component-and-connection templates derived from the applied system type. A direct system routes the primary tank through a distribution pump to the end uses. An indirect system routes it through a transfer pump (also known as the filtration pump), filtration system, buffer tank, and unlimited-capacity booster pump. Both templates include collection, overflow discharge, end uses, and municipal backup paths.

For an indirect system, end-use demand draws from the buffer tank. When the buffer level falls below the configured **Buffer refill level**, a refill cycle starts and remains active until the buffer tank is full. The filtration system is selected at 15, 20, 30, 40, or 50 GPM, and the transfer pump is constrained to that same flow; the default is 20 GPM. Filter recovery is applied to this flow. If primary-tank water cannot meet the commanded refill flow and municipal backup is enabled, unlimited-capacity municipal water supplies the difference directly to the buffer tank. The simulation tracks municipal and rainwater volumes separately so municipal makeup does not count as rainwater reliability. Rainfall enters the primary tank at the end of each simulated day.

Hourly results include primary-tank and buffer-tank levels, pump delivery, filter throughput and loss where applicable, municipal makeup, rainwater shortfall, system unmet demand, and overflow. Distribution-pump capacity, filtration-system flow, transfer-pump type, filtration recovery, buffer storage, initial buffer fill, refill level, and municipal backup availability are configured under **System parameters**. A zero distribution-pump capacity means unlimited direct-system flow; a zero buffer size keeps the indirect path in pass-through mode without refill control.

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
