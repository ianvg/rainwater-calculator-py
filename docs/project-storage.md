# Project storage and recovery

## Per-user application data

The application keeps writable state outside the installation directory. The default locations are:

| Platform | Application data | Provider cache |
| --- | --- | --- |
| Windows | `%LOCALAPPDATA%\RWH Calculator` | `%LOCALAPPDATA%\RWH Calculator\Cache` |
| macOS | `~/Library/Application Support/RWH Calculator` | `~/Library/Caches/RWH Calculator` |
| Linux | `${XDG_DATA_HOME:-~/.local/share}/rwh-calculator` | `${XDG_CACHE_HOME:-~/.cache}/rwh-calculator` |

The application-data directory contains the default `rainwater_projects.db`, preferences, recent-project history, reusable schedule and demand-object libraries, logs, and the backup directory. ACIS and ECCC response caches use the platform cache directory. Set `RWH_APP_DATA_DIR` or `RWH_APP_CACHE_DIR` to an absolute custom location for managed, test, or intentionally portable deployments.

## Unsaved-work recovery

The desktop application marks an edited project with an asterisk in the window title and displays **Unsaved changes** in the status area. Creating, opening, or closing a project and exiting the application offer **Save**, **Don't Save**, and **Cancel** choices when edits are pending. The same guard applies to the operating system's window-close button.

While a project has unsaved changes, a working recovery draft is refreshed in the per-user application-data directory. After a crash, power loss, or forced termination, the next launch offers to restore that draft. A successful project save or an intentional **Don't Save** removes it. Working drafts supplement the saved-project backups below; they are not a replacement for saving a named project.

## Migration from portable installations

On startup, the desktop application looks beside the executable or source entry point for the former writable files. When a destination file does not already exist, it is copied atomically into the per-user data directory. Existing destination files are never overwritten, and the legacy source files are retained. The application reports which files were copied.

This migration includes the default project database, preferences, recent-project history, and custom schedule and demand-object libraries. Project databases created elsewhere with **Save project as** remain where the user selected them.

## Automatic backups

Every successful project save creates a validated SQLite snapshot. Template-library mutations are backed up as well. The ten newest snapshots are retained by default. Backups for both the default database and externally located project databases are stored under the per-user `backups` directory; a path-derived identifier prevents files with the same name from colliding.

SQLite uses write-ahead logging and full synchronous commits, so committed writes can be replayed after an interruption. At startup or when opening another project file, the application performs an integrity check. If the database is damaged, it restores the newest valid snapshot, preserves a copy of the damaged database in the backup directory, and displays a recovery notice. If no valid snapshot exists, the application refuses to overwrite the damaged file and reports the recovery error.

## Schema compatibility

The SQLite database and each serialized project configuration carry explicit schema versions. Older unversioned project configurations remain supported through the existing migrations. A database or project created by a newer unsupported schema is rejected instead of being silently downgraded.

## Windows installation and removal

`RainwaterCalculator-Setup-<version>.exe` is a per-user installer. It installs program files under `%LOCALAPPDATA%\Programs\RWH Calculator`, creates Start-menu shortcuts, and optionally creates a desktop shortcut. Administrator rights are not required.

Uninstalling removes installed program files and shortcuts but intentionally retains projects, backups, preferences, logs, and caches. Remove `%LOCALAPPDATA%\RWH Calculator` manually only after preserving any project files that are still needed.

Developers can build the installer with:

```powershell
powershell -ExecutionPolicy Bypass -File .\build_installer.ps1
```

The script requires Inno Setup 6 and builds the PyInstaller executable first when necessary.
