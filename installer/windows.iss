; Inno Setup script for Expedient Employment (per-user install, no admin required).
; Packages the electron-builder unpacked output (gui/release/win-unpacked).
; Build via packaging/build-windows.ps1, which passes /DAppVersion=<version>.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

#define AppName "Expedient Employment"
#define AppId "com.expedient.employment"
#define AppPublisher "Expedient Employment contributors"
#define AppURL "https://github.com/BarnsL/expedient-employment"
#ifndef SourceDir
  #define SourceDir "..\gui\release\win-unpacked"
#endif

[Setup]
AppId={{{#AppId}}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
AppUpdatesURL={#AppURL}/releases
; Per-user install: no administrator rights required.
PrivilegesRequired=lowest
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; Allow installing over a running app's directory only after it is closed.
CloseApplications=yes
OutputDir=..\release
OutputBaseFilename=ExpedientEmployment-Setup-{#AppVersion}
SetupIconFile=..\gui\build\icon.ico
UninstallDisplayIcon={app}\{#AppName}.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppName}.exe"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppName}.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppName}.exe"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent
