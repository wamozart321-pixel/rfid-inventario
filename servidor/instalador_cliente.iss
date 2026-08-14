; Instalador para los OTROS PCs del local (no el principal).
; Instala la app nativa que se conecta al PC principal del inventario.
; Compilar con: ISCC.exe instalador_cliente.iss -> Instalar-InventarioRFID-OtrosPCs.exe

#define MyAppName "Inventario RFID (otros PCs)"
#define MyAppVersion "1.0"
#define MyAppExeName "InventarioRFID-Cliente.exe"

[Setup]
AppId={{7F8C3D5B-0E42-4A6F-C9B3-1D83RFID2026}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=REPUESTOSVOLKSWAGENCOM SAS
DefaultDirName={sd}\InventarioRFID-Cliente
DisableProgramGroupPage=yes
PrivilegesRequired=admin
OutputDir=c:\Users\DISEÑO\Downloads\rfid-inventario
OutputBaseFilename=Instalar-InventarioRFID-OtrosPCs
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupIconFile=c:\Users\DISEÑO\Downloads\rfid-inventario\servidor\icono.ico
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "Crear icono en el Escritorio"; GroupDescription: "Accesos directos:"
Name: "autostart"; Description: "Abrir el inventario automáticamente al prender el PC"; GroupDescription: "Inicio automático:"
Name: "principal"; Description: "Este es el PC PRINCIPAL (rojo, con ⚙ Configuración)"; GroupDescription: "Tipo de PC:"; Flags: unchecked

[Files]
Source: "c:\Users\DISEÑO\Downloads\rfid-inventario\servidor\InventarioRFID-Cliente.exe"; DestDir: "{app}"; Flags: ignoreversion
; Dirección del servidor: solo se copia si no existe (no pisa una ya configurada)
Source: "c:\Users\DISEÑO\Downloads\rfid-inventario\servidor\cliente.json"; DestDir: "{app}"; Flags: onlyifdoesntexist uninsneveruninstall

[Icons]
Name: "{autodesktop}\Inventario RFID"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon and not principal
Name: "{autodesktop}\Inventario RFID"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--principal"; Tasks: desktopicon and principal
Name: "{commonstartup}\Inventario RFID"; Filename: "{app}\{#MyAppExeName}"; Tasks: autostart and not principal
Name: "{commonstartup}\Inventario RFID"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--principal"; Tasks: autostart and principal

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Abrir Inventario RFID ahora"; Flags: nowait postinstall skipifsilent; Tasks: not principal
Filename: "{app}\{#MyAppExeName}"; Parameters: "--principal"; Description: "Abrir Inventario RFID ahora"; Flags: nowait postinstall skipifsilent; Tasks: principal
