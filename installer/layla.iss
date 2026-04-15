; Layla Windows installer (Inno Setup 6+)
; Build the payload tree first (see build_installer.ps1), then compile this script.
;
; Prerequisites: Inno Setup installed, ISCC.exe on PATH.

#define MyAppName "Layla"
#define MyAppVersion "1.0.0"
#define MyPublisher "Layla"
#define DefaultInstallDir "{pf}\Layla"

[Setup]
AppId={{F3B4E2A1-7C9D-4F1E-8B2A-1D3E5F7A9B0C}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyPublisher}
DefaultDirName={#DefaultInstallDir}
DisableProgramGroupPage=yes
OutputDir=.\output
OutputBaseFilename=Layla-Setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
; Populate .\payload\Layla\ before compiling (agent tree, optional python\, layla.exe, docs)
Source: "payload\Layla\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\layla.exe"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\layla.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\layla.exe"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent

[Code]
procedure InitializeWizard;
var
  DataDir: String;
begin
  DataDir := ExpandConstant('{localappdata}\Layla');
  if not DirExists(DataDir) then
    CreateDir(DataDir);
end;
