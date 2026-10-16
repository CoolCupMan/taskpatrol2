; Inno Setup script for TaskPatrol. Built by packaging/build.py, which passes
; the per-version values below with /D. Every version gets its own AppId, install
; folder, Start-menu entry and uninstaller, so versions install side by side.

#ifndef AppVersion
  #error Run packaging/build.py instead of compiling this script directly.
#endif

#define AppName "TaskPatrol"
#define ExeName AppName + "-" + AppVersion + ".exe"

[Setup]
AppId={{{#AppGuid}}
AppName={#AppName} {#AppVersion}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#Publisher}
VersionInfoVersion={#AppVersion}
VersionInfoProductName={#AppName} {#AppVersion}
DefaultDirName={autopf}\{#AppName}\{#AppVersion}
DefaultGroupName={#AppName} {#AppVersion}
DisableProgramGroupPage=yes
UninstallDisplayName={#AppName} {#AppVersion}
UninstallDisplayIcon={app}\{#ExeName}
SetupIconFile={#IconFile}
OutputBaseFilename={#AppName}-{#AppVersion}-Setup
AppMutex={#AppMutex}
; Per-user install by default (no admin needed); the dialog lets users choose all-users.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#SourceExe}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName} {#AppVersion}"; Filename: "{app}\{#ExeName}"; AppUserModelID: "{#AppUserModelID}"
Name: "{group}\Uninstall {#AppName} {#AppVersion}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName} {#AppVersion}"; Filename: "{app}\{#ExeName}"; AppUserModelID: "{#AppUserModelID}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#ExeName}"; Description: "{cm:LaunchProgram,{#AppName} {#AppVersion}}"; Flags: nowait postinstall skipifsilent
