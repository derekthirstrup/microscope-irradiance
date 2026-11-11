; Inno Setup script. Build after PyInstaller, from the repo root:
;   iscc /DMyAppVersion=1.0.0 packaging\installer.iss
#ifndef MyAppVersion
  #define MyAppVersion "1.0.0"
#endif
#define MyAppName "Irradiance Calculator"
#define MyAppExe "IrradianceCalculator.exe"

[Setup]
AppId={{8672A9CC-CF17-4162-B6EC-A7CB6E3A4237}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=Derek Thirstrup
AppPublisherURL=https://github.com/derekthirstrup/microscope-irradiance
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\dist
OutputBaseFilename=IrradianceCalculator-{#MyAppVersion}-windows-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#MyAppExe}
LicenseFile=..\LICENSE

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\IrradianceCalculator\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"
Name: "{group}\Example files"; Filename: "{app}\_internal\examples"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExe}"; Description: "Start {#MyAppName}"; Flags: nowait postinstall skipifsilent
