; Layla Windows installer (Inno Setup 6+)
; Build the payload tree first (see build_installer.ps1), then compile this script.
;
; Prerequisites: Inno Setup installed, ISCC.exe on PATH.

#define MyAppName "Layla"
#ifndef MyAppVersion
#define MyAppVersion "0.0.0"
#endif
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

[Registry]
; Expose install root to launcher/updater without relying on heuristics.
Root: HKLM; Subkey: "SYSTEM\CurrentControlSet\Control\Session Manager\Environment"; ValueType: string; ValueName: "LAYLA_INSTALL_ROOT"; ValueData: "{app}"; Flags: preservestringtype uninsdeletevalue

[Code]
procedure InitializeWizard;
var
  DataDir: String;
begin
  DataDir := ExpandConstant('{localappdata}\Layla');
  if not DirExists(DataDir) then
    CreateDir(DataDir);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: String;
begin
  if CurUninstallStep = usUninstall then begin
    DataDir := ExpandConstant('{localappdata}\Layla');
    if DirExists(DataDir) then begin
      if MsgBox('Delete per-user Layla data at:' + #13#10 + DataDir + #13#10#13#10 + 'This includes runtime_config.json, layla.db, models, and logs.', mbConfirmation, MB_YESNO) = IDYES then begin
        DelTree(DataDir, True, True, True);
      end;
    end;
  end;
end;
