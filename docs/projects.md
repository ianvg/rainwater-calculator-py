# Projects

A project groups the rainfall series, inputs, collection surfaces, demand settings, and analysis results for one study.

Use the **System parameters** tab to classify the project as a **Direct system** or **Indirect system**, then select **Apply**. The gray status line identifies the currently applied type. Applying a template stores both its type and executable canvas topology with the project.

Applying **Indirect system** displays the current system schematic. It shows the primary analysis tank size and current volume units, a right-facing filtration pump, a filtration unit, and a smaller buffer tank. An outlet arrow from the buffer tank identifies flow to the end uses. Regular wave lines indicate the water level in both tanks. Applying **Direct system** hides the indirect-system schematic.

The **Component parameters** section controls hourly hydraulic behavior. Pump capacities are entered as volume per minute and stored internally as hourly flow. **Distribution pump capacity** limits direct-system delivery; zero leaves it unlimited. **Filtration pump capacity** limits primary-tank transfer in an indirect system and defaults to 20 gal/min. **Filter recovery** is the percentage of pumped primary-tank water delivered through filtration. **Buffer tank size** enables intermediate storage; zero uses pass-through behavior. **Buffer initial fill** sets its starting level, while **Buffer refill level** sets the threshold that starts a refill cycle. When **Municipal backup enabled** is selected, municipal water makes up a shortfall in the commanded buffer refill flow.

The **System parameters** screen contains the system builder and a right-side notebook. The **System object library** tab contains rainwater input, primary tank, filtration pump, filtration system, buffer tank, booster pump, municipal water backup, first-flush diversion, Overflow pipe, and end-uses. The first-flush diversion and Overflow pipe are terminal objects with an inlet only. Every primary tank has a mandatory orange **OF** outlet that must connect directly to an Overflow pipe; saved layouts created before this requirement are migrated automatically. Double-click an object, press Enter, use **Add selected**, or drag it from the library onto the canvas. The adjacent **System templates** tab is a template library. Its immutable built-in section contains connected Direct and Indirect systems assembled from the same objects. The custom section contains designs saved in the current project database. Use **Save current as custom** to capture the canvas geometry, object details, links, component parameters, and tank-sizing settings. Custom templates can be applied later, renamed, or deleted; applying any template replaces the current canvas. Blue nodes are inputs, red nodes are normal outputs, and the orange node is the dedicated overflow outlet. Create a connection by selecting either endpoint and then a compatible endpoint of the opposite direction, or by dragging directly between the two nodes. Selected nodes use a lighter shade. During a drag, a compatible destination node also lightens when the pointer is over it. Dragging from a node creates a connection and does not move its system object. Right-click a node to start a connection, disconnect only that node, or disconnect every link attached to its object. Disconnecting an input removes incoming links; disconnecting an output removes outgoing links.

The builder displays live configuration warnings below the canvas. It checks required components and collection/supply reachability, missing component connections, invalid directions, flow loops, filtration-pump ordering, booster discharge through a pump, municipal-backup destinations, first-flush routing, unsupported multiple primary tanks, and unlinked optional tank nodes. Analysis is disabled for a saved custom graph until all displayed warnings are corrected. Legacy projects with no saved builder canvas continue to use their selected valid built-in Direct or Indirect topology.

The complete **Builder** sub-tab is vertically scrollable. Use its right-side scrollbar or the mouse wheel while the pointer is anywhere over the Builder page to reach the instructions, controls, and full configuration-warning area. Scrolling is scoped to this sub-tab and does not move the Animation page or other application tabs.

The toolbar above the canvas changes the editor view in 10% increments. Zoom out is limited to three steps (70%) and zoom in is limited to three steps (130%) from the default 100%. While the pointer is over the builder canvas, hold Shift and scroll up to zoom in or scroll down to zoom out; ordinary scrolling continues to move the Builder page. Hold the middle mouse button and drag over the canvas to pan. The pan range is limited to the workspace visible at the maximum 70% zoom-out level, so the view cannot drift into unlimited empty space; at 70% no additional panning is available. Zoom and pan affect only the editor view. Saved object positions, custom-template geometry, dragging, resizing, object drops, and connection hit targets continue to use unchanged system coordinates.

The **Animation** sub-tab provides a one-day view of the hourly hydraulic simulation. Choose any day in the imported rainfall record and select **Simulate day**. The friendly media-player panel uses circular previous, play/pause day, play/pause hour, stop, and next controls with persistent labels, hover feedback, and keyboard focus indication. Whole-day play is visually emphasized. A draggable 24-hour seek bar changes the selected hour, while the adjacent readout reports elapsed and total day time. Stop returns the active hour to the beginning of its animation without discarding the simulated day. Playback settings are grouped separately from transport controls. Set **Seconds per hour** from 0.1 to 60.0 seconds to control both playback modes. Select **Show instantaneous pipe flow** to label every connection with its effective hourly flow in GPM for Imperial projects or LPM for Metric projects. Enable **Auto-play next day** to select the next available imported rainfall date after hour 23, simulate it, and immediately continue whole-day playback. When no later date exists, **Repeat day** determines whether the final day returns to hour 0 and loops; otherwise playback stops. For single-hour playback, set **After one hour** to **Advance to next hour** to play once, select the following hour, and stop, or select **Loop current hour** to repeat the displayed hour until paused. Active connections display blue pulses moving from their source to their destination. A primary or buffer tank contains an inner blue rectangle whose height is its simulated percentage fill and displays current volume over capacity. The Overflow pipe displays cumulative overflow from the beginning of the simulated record and updates through the active hour. Pump objects show a clockwise rotating gear while their simulated flow is positive. Animation targets 25 frames per second while playback is active, providing smoother motion without a background redraw loop when stopped. The hour header reports collected rainfall and demand for the active hour. Playback uses the current canvas topology and component parameters.

Animation commands also report their state in the application's bottom status bar, in the same location as the selected-day simulation message. The status identifies whole-day or one-hour playback, pause and stop actions, previous/next hour selection, and automatic playback completion.

System-object blocks can also be dragged directly within the Animation display. Starting a drag pauses playback. The object follows collision and workspace bounds, connected lines redraw as it moves, and releasing it updates the shared Builder layout and saved project geometry rather than creating an animation-only position.

End-use blocks can display small pixel-art scenes for assigned demand-object types. The initial irrigation scene is original canvas-drawn artwork showing a gardener holding a hose, animated water droplets, a flower, and grass. It appears only when the End-uses block has an assigned **Irrigation system** demand object whose hourly schedule is active during the displayed hour and the system has positive demand. The artwork is generated by the application and does not require an external sprite asset.

The saved canvas governs the hourly hydraulic simulation. A rainwater-input block contributes collected rainfall only when it has a connected path to a primary tank. A connected primary-tank path supplies end uses; filtration-pump and filtration blocks apply the configured pump limit and recovery, buffer storage applies its fill and refill controls, and municipal backup supplies only a connected end-use or buffer destination. Removing a connection removes that flow path from the next hourly analysis. Projects created before the builder was introduced, with no saved canvas, retain their selected Direct or Indirect template behavior.

A buffer tank initially shows a translucent prospective second inlet with a translucent plus sign to its left. Select either affordance to add the inlet. While that inlet is unlinked, a red minus sign appears beside it and removes it; linked inlets must be disconnected before they can be removed. The two buffer inlets retain separate connection and disconnection state when the project is saved.

A primary tank similarly shows a translucent prospective second outlet with a plus sign to its right. Select the node or plus sign to add the outlet, then connect it to a first-flush diversion object. While the second outlet is unlinked, its red minus sign removes it; disconnect a linked outlet before removing it. The normal supply outlet and the diversion outlet retain separate connection and disconnection state, including in saved custom templates.

The **Edit** tab exposes settings for the selected object instead of showing a separate component-parameters section. Pump settings appear for pump objects, recovery appears for filtration, buffer storage settings appear for the buffer tank, and municipal-backup availability appears for the backup object. Selecting the primary tank exposes its size, initial fill, minimum operating level as a percentage of tank capacity, and tank-size simulation range. Selecting an **End-uses** object shows available and assigned project demand objects. Use **Add selected** or **Remove selected** (or double-click a list item) to manage its assignments; the canvas object shows the assigned demand count. Assignments are saved with the project and remain synchronized when a demand object is deleted. Drag placed objects to reposition them; collision handling prevents objects from overlapping. To resize an object, select it and drag near any corner. The **Geometry** tab enables multi-selection and collision-safe horizontal alignment. Each object exposes circular inlet and outlet nodes where applicable. Select an outlet node and then an inlet node to create a directional link; Escape cancels an unfinished link. Select a component or link and use Delete or **Delete selected** to remove it. Component positions, dimensions, and links are saved with the project. The previous indirect-system schematic is retained at `assets/indirect_system.svg`.

## Project settings

Enter the project name, optional produced-by/author name, unit system, and country in **Project Settings**. Enter the street address, city, state/province/region, and postal code in the separate **Project Location** section immediately below it. Address components are stored separately in the project file and are combined as the default report location. They are transmitted to OpenStreetMap Nominatim only when an address or coordinate lookup is explicitly selected.

When an author name is provided, reports display a **Produced by** line near the top. Leaving the field blank is valid and omits that line from reports.

Use the multiline **Notes** section between Project Settings and Project Location for free-form project notes. Notes are stored with the project and appear as the second section of generated reports.

The Project Inputs tab scrolls vertically when its project metadata, notes, and location fields exceed the available window height. Collection areas, demand parameters, and simulation settings have separate tabs.

The country is stored as an ISO 3166-1 alpha-3 code. The other fields represent common concepts from ISO 19160-4 and UPU S42: thoroughfare/delivery information, locality, administrative region, and postcode. This component model supports later country-specific formatting, but the calculator does not currently implement the complete library of S42 national address templates.

### Select a location on OpenStreetMap

Select **Find on OpenStreetMap...** to open an interactive map in a separate calculator window. Click a point and select **Use selected location**, or press Enter; Escape cancels the selection. The map window closes after selection and focus returns to the calculator. The exact clicked latitude and longitude are stored with the project and displayed below the address fields. The application sends the selected coordinate to OpenStreetMap Nominatim once to retrieve the nearest mapped address, then fills the structured address fields. Review the result because reverse geocoding identifies the nearest suitable mapped object and may not return the physical or postal address expected for the site.

Latitude and longitude can also be entered directly. Enter both values in decimal degrees; latitude must be between -90 and 90 and longitude between -180 and 180. Manual coordinates can be saved alongside a manually entered address without contacting OpenStreetMap. To replace the address fields with the nearest mapped address for those coordinates, select **Find nearest OSM address**. To find coordinates for the manually entered address, select **Find nearest coordinates from OSM**; the best matching Nominatim result fills the latitude and longitude fields while retaining the entered address. Review the coordinates because address searches can be ambiguous. The map picker starts at manually entered coordinates when they are present.

Map tiles and address lookup require an internet connection. The map displays OpenStreetMap attribution, requests only tiles needed for the interactive viewport, and does not provide bulk or offline downloading. Do not submit personal or confidential locations. Production deployments can replace the services with the `RWH_OSM_TILE_URL` and `RWH_NOMINATIM_URL` environment variables.

## Create a project

Select **File > Create new project** or press `Ctrl+N`. If the current project has unsaved changes, choose **Save**, **Don't Save**, or **Cancel**.

## Save a project

Select **File > Save project** or press `Ctrl+S` to save to the current project file. If the project does not yet have a chosen location, the application prompts for one.

Select **File > Save project as...** or press `Ctrl+Shift+S` to choose another database file or location. Projects can be saved before rainfall data is imported.

## Open a project

Select **File > Open project...** or press `Ctrl+O`, then choose the project database file. The file picker starts in the current user's home directory. Opening the file also loads the project. Progress is shown in the lower-right status area.

Use **File > Open recent project** to reopen a recently used file. Missing recent files are removed from the list when appropriate.

Previously saved analysis results are restored with the project, so the analysis does not need to be run again unless an input changes or a new result is required.

## Close a project

Select **File > Close project** or press `Ctrl+W`. The application displays the same Save / Don't Save / Cancel choice used by New, Open, Exit, and the window-close button whenever changes are pending. An asterisk in the title and **Unsaved changes** in the status area identify that state.

## Project-file care

- Successful saves automatically create validated backups in the platform-specific per-user application-data directory. The ten newest snapshots are retained.
- Do not edit a project database with a text editor.
- Avoid moving or deleting a project file while it is open.
- Use **Save project as...** when creating a separate design alternative.
- See [Project storage and recovery](project-storage.md) for native Windows, macOS, and Linux paths, legacy migration, schema compatibility, and corruption recovery.
