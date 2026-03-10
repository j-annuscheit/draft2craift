; Inno Setup script to build a classic "Setup.exe" installer for draft2craift.
; Prerequisite: run PyInstaller first to produce dist\draft2craift\...
;
; Build:
;   iscc packaging\installer.iss
;

#ifndef MyAppName
  #define MyAppName "draft2craift"
#endif
#ifndef MyAppVersion
  #define MyAppVersion "1.0.0"
#endif
#ifndef MyAppPublisher
  #define MyAppPublisher "draft2craift"
#endif
#ifndef MyAppExeName
  #define MyAppExeName "draft2craift.exe"
#endif
#ifndef MyAppSourceDir
  #define MyAppSourceDir "{#SourcePath}..\\dist\\draft2craift"
#endif
#ifndef MyOutputBaseFilename
  #define MyOutputBaseFilename "draft2craift-Setup"
#endif

[Setup]
AppId={{93B545BD-40D8-4BFC-8E8D-2FD1F9FC86F2}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir={#SourcePath}..\\dist_installer
OutputBaseFilename={#MyOutputBaseFilename}
Compression=lzma
SolidCompression=yes
WizardStyle=modern
LicenseFile={#SourcePath}..\\LICENSE

ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop icon"; GroupDescription: "Additional icons:"; Flags: unchecked

[Files]
Source: "{#MyAppSourceDir}\\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#SourcePath}..\\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SourcePath}..\\THIRD_PARTY_NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\\{#MyAppName}"; Filename: "{app}\\{#MyAppExeName}"
Name: "{autodesktop}\\{#MyAppName}"; Filename: "{app}\\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent
