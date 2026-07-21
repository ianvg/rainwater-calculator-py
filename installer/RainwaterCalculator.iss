#define MyAppName "RWH Calculator"
#define MyAppVersion "0.1.1"
#define MyAppPublisher "RWH Calculator contributors"
#define MyAppExeName "RainwaterCalculator.exe"

[Setup]
AppId={{A2833970-0A87-4BE8-A634-404411EF7382}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\RWH Calculator
DefaultGroupName=RWH Calculator
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=RainwaterCalculator-Setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupIconFile=..\assets\app_icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
VersionInfoVersion={#MyAppVersion}
VersionInfoDescription=RWH Calculator installer
ChangesAssociations=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "..\dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\RWH Calculator"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\RWH Calculator"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch RWH Calculator"; Flags: nowait postinstall skipifsilent
