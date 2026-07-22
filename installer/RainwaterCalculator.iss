#define MyAppName "RWH Calculator"
#define MyAppVersion "0.1.2"
#define MyAppPublisher "RWH Calculator contributors"
#define MyAppExeName "RainwaterCalculator.exe"
#define ClimateNormalsArchiveName "us-climate-normals_1991-2020_v1.0.1_annualseasonal_multivariate_by-station_c20230404.tar.gz"
#define ClimateNormalsArchiveUrl "https://noaa-normals-pds.s3.amazonaws.com/normals-annualseasonal/1991-2020/archive/" + ClimateNormalsArchiveName
#define ClimateNormalsArchiveSha256 "0fdb814203150780d4ee0c5d53c7844a237a21881101fb7d922b0aa3a1fd190f"

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
Name: "climatenormals"; Description: "Download the NOAA 1991-2020 annual/seasonal Climate Normals archive (54.2 MB)"; GroupDescription: "Optional data:"; Flags: unchecked

[Files]
Source: "..\dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#ClimateNormalsArchiveUrl}"; DestDir: "{localappdata}\RWH Calculator\Cache\weather"; DestName: "{#ClimateNormalsArchiveName}"; ExternalSize: 54176270; Hash: "{#ClimateNormalsArchiveSha256}"; Flags: external download ignoreversion; Tasks: climatenormals

[Icons]
Name: "{autoprograms}\RWH Calculator"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\RWH Calculator"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch RWH Calculator"; Flags: nowait postinstall skipifsilent
