# Execution log

The execution log shows live, structured details about analyses, optimization, rainfall and weather operations, project files, exports, and report generation. Open it from **View > Execution log**, or enable **Settings > Show execution log**.

## Detail levels

- **Normal** shows major stages, completions, warnings, and failures.
- **Detailed** also shows repeated progress such as individual reliability-curve tank sizes and optimization combinations.
- **Diagnostic** adds low-level configuration context and exception tracebacks intended for troubleshooting.

The selected detail level and window visibility are application preferences. They are not stored in project files.

## Window controls

**Auto-scroll** keeps the newest entry visible. **Pause display** temporarily stops drawing new entries without stopping the underlying operation or file logging; resuming refreshes the window from retained history. Use **Clear**, **Copy**, and **Save log** to manage the displayed entries. **Open log folder** opens the directory containing the rotating diagnostic files.

The in-memory display retains the latest 5,000 entries. File logs rotate automatically to keep their disk usage bounded. Private absolute paths, home-directory locations, and common secret query parameters are redacted. Rainfall values, project addresses, and other project contents are not written to execution-log messages.

The log reports meaningful application operations rather than every executed Python source line. Literal source tracing would substantially reduce performance and is not appropriate for normal application use.
