# Projects

A project groups the rainfall series, inputs, collection surfaces, demand settings, and analysis results for one study.

Use the **System parameters** tab to classify the project as a **Direct system** or **Indirect system**, then select **Apply**. The gray status line identifies the currently applied type. The applied selection is stored with the project; it does not alter simulation calculations until system-specific calculation behavior is defined.

Applying **Indirect system** displays the current system schematic. It shows the primary analysis tank size and current volume units, a right-facing filtration pump, a filtration unit, and a smaller booster tank. An outlet arrow from the booster tank identifies flow to the end uses. Regular wave lines indicate the water level in both tanks. Applying **Direct system** hides the indirect-system schematic.

The **Component parameters** section controls hourly hydraulic behavior. Pump capacities are entered as volume per minute and stored internally as hourly flow. **Distribution pump capacity** limits direct-system delivery; zero leaves it unlimited. **Filtration pump capacity** limits primary-tank transfer in an indirect system and defaults to 20 gal/min. **Filter recovery** is the percentage of pumped primary-tank water delivered through filtration. **Booster tank size** enables intermediate storage; zero uses pass-through behavior. **Booster initial fill** sets its starting level, while **Booster refill level** sets the threshold that starts a refill cycle. When **Municipal backup enabled** is selected, municipal water makes up a shortfall in the commanded booster refill flow.

The **System parameters** screen contains the system builder and a right-side notebook. The **System object library** tab contains rainwater input, primary tank, filtration pump, filtration system, booster tank, booster pump, municipal water backup, and end-uses. Double-click an object, press Enter, use **Add selected**, or drag it from the library onto the canvas. The adjacent **System templates** tab can replace the canvas with a connected Direct or Indirect system assembled from those same library objects. Blue nodes are inputs and red nodes are outputs. Create a connection by selecting either endpoint and then a compatible endpoint of the opposite direction, or by dragging directly between the two nodes. Selected nodes use a lighter shade. During a drag, a compatible destination node also lightens when the pointer is over it. Dragging from a node creates a connection and does not move its system object. Right-click a node to start a connection, disconnect only that node, or disconnect every link attached to its object. Disconnecting an input removes incoming links; disconnecting an output removes outgoing links.

The **Edit** tab exposes settings for the selected object instead of showing a separate component-parameters section. Pump settings appear for pump objects, recovery appears for filtration, booster storage settings appear for the booster tank, and municipal-backup availability appears for the backup object. Selecting the primary tank exposes its size, initial fill, minimum operating level as a percentage of tank capacity, and tank-size simulation range. Selecting an **End-uses** object shows available and assigned project demand objects. Use **Add selected** or **Remove selected** (or double-click a list item) to manage its assignments; the canvas object shows the assigned demand count. Assignments are saved with the project and remain synchronized when a demand object is deleted. Drag placed objects to reposition them; collision handling prevents objects from overlapping. To resize an object, select it and drag near any corner. The **Geometry** tab enables multi-selection and collision-safe horizontal alignment. Each object exposes circular inlet and outlet nodes where applicable. Select an outlet node and then an inlet node to create a directional link; Escape cancels an unfinished link. Select a component or link and use Delete or **Delete selected** to remove it. Component positions, dimensions, and links are saved with the project. The previous indirect-system schematic is retained at `assets/indirect_system.svg`.

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

Select **File > Create new project** or press `Ctrl+N`. Unsaved values are cleared and the application returns to a new project state.

## Save a project

Select **File > Save project** or press `Ctrl+S` to save to the current project file. If the project does not yet have a chosen location, the application prompts for one.

Select **File > Save project as...** or press `Ctrl+Shift+S` to choose another database file or location. Projects can be saved before rainfall data is imported.

## Open a project

Select **File > Open project...** or press `Ctrl+O`, then choose the project database file. The file picker starts in the current user's home directory. Opening the file also loads the project. Progress is shown in the lower-right status area.

Use **File > Open recent project** to reopen a recently used file. Missing recent files are removed from the list when appropriate.

Previously saved analysis results are restored with the project, so the analysis does not need to be run again unless an input changes or a new result is required.

## Close a project

Select **File > Close project** or press `Ctrl+W`. Save changes first when they need to be retained.

## Project-file care

- Keep backup copies of important project database files.
- Do not edit a project database with a text editor.
- Avoid moving or deleting a project file while it is open.
- Use **Save project as...** when creating a separate design alternative.
