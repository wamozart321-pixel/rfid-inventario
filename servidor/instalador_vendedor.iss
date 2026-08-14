; Instalador para los PCs de los VENDEDORES (solo consulta, ventana verde).
; Instala la app que se conecta al PC principal en modo vendedor: sin
; opciones de modificar, eliminar ni imprimir — solo información del repuesto.
; Compilar con: ISCC.exe instalador_vendedor.iss -> Instalar-InventarioRFID-Vendedores.exe

#define MyAppName "Inventario RFID (vendedores)"
#define MyAppVersion "1.0"
#define MyAppExeName "InventarioRFID-Vendedor.exe"

[Setup]
AppId={{9B0E5F7D-2A64-4C8B-E1D5-3F05RFID2026}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=REPUESTOSVOLKSWAGENCOM SAS
DefaultDirName={sd}\InventarioRFID-Vendedor
DisableProgramGroupPage=yes
PrivilegesRequired=admin
OutputDir=c:\Users\DISEÑO\Downloads\rfid-inventario
OutputBaseFilename=Instalar-InventarioRFID-Vendedores
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

[Files]
Source: "c:\Users\DISEÑO\Downloads\rfid-inventario\servidor\InventarioRFID-Vendedor.exe"; DestDir: "{app}"; Flags: ignoreversion
; Dirección del PC principal: solo se copia si no existe (no pisa una ya configurada)
Source: "c:\Users\DISEÑO\Downloads\rfid-inventario\servidor\cliente.json"; DestDir: "{app}"; Flags: onlyifdoesntexist uninsneveruninstall

[Icons]
Name: "{autodesktop}\Inventario RFID (consulta)"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
Name: "{commonstartup}\Inventario RFID (consulta)"; Filename: "{app}\{#MyAppExeName}"; Tasks: autostart

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Abrir Inventario RFID ahora"; Flags: nowait postinstall skipifsilent
