; Instalador del INVENTARIO para los PCs que NO son el servidor.
; Un solo programa sirve para los tres tipos de PC (principal, mostrador y
; vendedor): el tipo se elige aquí y viaja en el acceso directo.
; Compilar con: ISCC.exe instalador_inventario.iss
;   -> Instalar-InventarioRFID-PCs.exe

#define MyAppName "Inventario RFID"
#define MyAppVersion "2.4"
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
OutputBaseFilename=Instalar-InventarioRFID-PCs
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupIconFile=c:\Users\DISEÑO\Downloads\rfid-inventario\servidor\icono.ico
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "Crear icono en el Escritorio"; GroupDescription: "Accesos directos:"
Name: "autostart"; Description: "Abrir el inventario al prender el PC"; GroupDescription: "Inicio automático:"

[Files]
Source: "c:\Users\DISEÑO\Downloads\rfid-inventario\servidor\InventarioRFID-Cliente.exe"; DestDir: "{app}"; Flags: ignoreversion
; Dirección del servidor: solo se copia si no existe (no pisa una ya configurada)
Source: "c:\Users\DISEÑO\Downloads\rfid-inventario\servidor\cliente.json"; DestDir: "{app}"; Flags: onlyifdoesntexist uninsneveruninstall

[Icons]
Name: "{autodesktop}\{code:NombreModo}"; Filename: "{app}\{#MyAppExeName}"; Parameters: "{code:ParamModo}"; Tasks: desktopicon
Name: "{commonstartup}\{code:NombreModo}"; Filename: "{app}\{#MyAppExeName}"; Parameters: "{code:ParamModo}"; Tasks: autostart

[Run]
Filename: "{app}\{#MyAppExeName}"; Parameters: "{code:ParamModo}"; Description: "Abrir el inventario ahora"; Flags: nowait postinstall skipifsilent

[Code]
var
  PaginaModo: TInputOptionWizardPage;

procedure InitializeWizard();
begin
  PaginaModo := CreateInputOptionPage(wpSelectTasks,
    'Para qué se va a usar este PC',
    'El programa es el mismo; lo que cambia es lo que deja hacer.',
    'Elige una opción. Si te equivocas, se corrige volviendo a instalar.',
    True, False);
  PaginaModo.Add('PC PRINCIPAL (rojo) — todo, y además ⚙ Configuración:' + #13#10 +
                 '     impresoras, diseño de etiqueta y copias de seguridad.');
  PaginaModo.Add('PC de MOSTRADOR (naranja) — consultar y modificar productos,' + #13#10 +
                 '     imprimir etiquetas y hacer conteos. Sin Configuración.');
  PaginaModo.Add('PC de VENDEDOR (verde) — solo consulta. Puede corregir las' + #13#10 +
                 '     referencias aplicables y la rotación, nada más.');
  PaginaModo.SelectedValueIndex := 1;    { mostrador: lo más habitual }
end;

function ParamModo(Param: String): String;
begin
  if PaginaModo.SelectedValueIndex = 0 then
    Result := '--principal'
  else if PaginaModo.SelectedValueIndex = 2 then
    Result := '--vendedor'
  else
    Result := '';
end;

function NombreModo(Param: String): String;
begin
  if PaginaModo.SelectedValueIndex = 0 then
    Result := 'Inventario RFID (principal)'
  else if PaginaModo.SelectedValueIndex = 2 then
    Result := 'Inventario RFID (vendedor)'
  else
    Result := 'Inventario RFID';
end;

{ Si este PC ya se había instalado con OTRO tipo, sus accesos directos
  seguirían ahí y abrirían el modo viejo. Se borran los que no tocan. }
procedure LimpiarAtajosDeOtrosModos();
var
  nombres: array[0..2] of String;
  i: Integer;
  bueno: String;
begin
  nombres[0] := 'Inventario RFID';
  nombres[1] := 'Inventario RFID (principal)';
  nombres[2] := 'Inventario RFID (vendedor)';
  bueno := NombreModo('');
  for i := 0 to 2 do
    if nombres[i] <> bueno then
    begin
      DeleteFile(ExpandConstant('{autodesktop}\') + nombres[i] + '.lnk');
      DeleteFile(ExpandConstant('{commonstartup}\') + nombres[i] + '.lnk');
    end;
  { y si ya no se quiere que arranque solo, fuera el de inicio }
  if not WizardIsTaskSelected('autostart') then
    DeleteFile(ExpandConstant('{commonstartup}\') + bueno + '.lnk');
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  codigo: Integer;
begin
  if CurStep = ssInstall then
    Exec('taskkill', '/f /im ' + '{#MyAppExeName}', '', SW_HIDE,
         ewWaitUntilTerminated, codigo);
  if CurStep = ssPostInstall then
    LimpiarAtajosDeOtrosModos();
end;
