; Instalador de GlowCam para Windows (Inno Setup 6)
; Incluye la cámara virtual (filtro DirectShow de OBS) para no tener que instalar OBS.

#ifndef AppVersion
  #define AppVersion "1.2.0"
#endif

[Setup]
AppId={{6E3B0C2A-5F1D-4C7E-9A3B-1D2C3B4A5F60}
AppName=GlowCam
AppVersion={#AppVersion}
AppPublisher=Glow Models Media
DefaultDirName={autopf}\GlowCam
DefaultGroupName=GlowCam
DisableProgramGroupPage=yes
DisableDirPage=yes
DisableReadyPage=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=GlowCam-Windows
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\GlowCam.exe
CloseApplications=yes

[Languages]
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "Crear un acceso directo en el escritorio"; GroupDescription: "Accesos directos:"

[Files]
Source: "..\dist\GlowCam\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Cámara virtual: solo se registra si OBS no está ya instalado (OBS ya la trae)
Source: "..\vcam\obs-virtualcam-module64.dll"; DestDir: "{app}\vcam"; Flags: ignoreversion regserver 64bit; Check: NeedsVirtualCam
Source: "..\vcam\obs-virtualcam-module32.dll"; DestDir: "{app}\vcam"; Flags: ignoreversion regserver 32bit; Check: NeedsVirtualCam
Source: "..\vcam\OBS-LICENSE.txt"; DestDir: "{app}\vcam"; Flags: ignoreversion skipifsourcedoesntexist

[Icons]
Name: "{group}\GlowCam"; Filename: "{app}\GlowCam.exe"
Name: "{autodesktop}\GlowCam"; Filename: "{app}\GlowCam.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\GlowCam.exe"; Description: "Abrir GlowCam"; Flags: nowait postinstall skipifsilent

[Code]
function OBSInstalled: Boolean;
begin
  Result := RegKeyExists(HKLM64, 'SOFTWARE\OBS Studio') or RegKeyExists(HKLM32, 'SOFTWARE\OBS Studio');
end;

function NeedsVirtualCam: Boolean;
begin
  Result := not OBSInstalled;
end;
