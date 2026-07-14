# Projects

A project groups the rainfall series, inputs, collection surfaces, demand settings, and analysis results for one study.

## Project settings

Enter a project name, street address, city, state/province/region, postal code, unit system, and country in the Project Settings section. Address components are stored separately in the project file and are combined as the default report location. They are not transmitted to an online geocoding service.

The country is stored as an ISO 3166-1 alpha-3 code. The other fields represent common concepts from ISO 19160-4 and UPU S42: thoroughfare/delivery information, locality, administrative region, and postcode. This component model supports later country-specific formatting, but the calculator does not currently implement the complete library of S42 national address templates.

### Select a location on OpenStreetMap

Select **Find on OpenStreetMap...** to open an interactive map in the default browser. Click a point and select **Use selected location**. After the application accepts the location, the map requests that its browser window close and focus returns to the calculator. The exact clicked latitude and longitude are stored with the project and displayed below the address fields. The application sends the selected coordinate to OpenStreetMap Nominatim once to retrieve the nearest mapped address, then fills the structured address fields. Review the result because reverse geocoding identifies the nearest suitable mapped object and may not return the physical or postal address expected for the site.

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
