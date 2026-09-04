; Instalador del Sistema de Inventario RFID
; Compilar con: ISCC.exe instalador.iss  ->  genera Instalar-InventarioRFID.exe
; El instalador incluye una FOTO de la base de datos y de la configuración del
; momento en que se compila: en un PC nuevo arranca con ese catálogo; si ya hay
; datos, NO los toca... salvo que se marque la casilla "Reemplazar los datos"
; (para MUDAR el servidor a otro PC), que antes guarda copia de los actuales.

#define MyAppName "Inventario RFID"
#define MyAppVersion "2.3"
#define MyAppExeName "ServidorInventarioRFID.exe"

[Setup]
AppId={{6E7B2C4A-9D31-4F5E-B8A2-0C72RFID2026}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=REPUESTOSVOLKSWAGENCOM SAS
DefaultDirName={sd}\InventarioRFID
DisableProgramGroupPage=yes
PrivilegesRequired=admin
OutputDir=c:\Users\DISEÑO\Downloads\rfid-inventario
OutputBaseFilename=Instalar-InventarioRFID
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupIconFile=c:\Users\DISEÑO\Downloads\rfid-inventario\servidor\icono.ico
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "Crear icono en el Escritorio"; GroupDescription: "Accesos directos:"
Name: "autostart"; Description: "Iniciar con VENTANA al prender el PC (si alguien trabaja en este PC)"; GroupDescription: "Inicio automático:"
Name: "autostartsrv"; Description: "Modo PC SERVIDOR: tarea de Windows que arranca SIN VENTANA al prender el PC, aunque nadie inicie sesión (no se puede cerrar por accidente)"; GroupDescription: "Inicio automático:"; Flags: unchecked
Name: "reemplazardb"; Description: "REEMPLAZAR el inventario y la configuración de este PC por los que trae el instalador (para MUDAR el servidor a otro PC). De los actuales se guarda una copia antes de reemplazarlos."; GroupDescription: "Datos del inventario:"; Flags: unchecked

[Files]
Source: "c:\Users\DISEÑO\Downloads\rfid-inventario\servidor\ServidorInventarioRFID.exe"; DestDir: "{app}"; Flags: ignoreversion
; Datos: solo se copian si NO existen (nunca pisa un inventario ya en uso)
Source: "c:\Users\DISEÑO\Downloads\rfid-inventario\servidor\inventario.db"; DestDir: "{app}"; Flags: onlyifdoesntexist uninsneveruninstall skipifsourcedoesntexist
Source: "c:\Users\DISEÑO\Downloads\rfid-inventario\servidor\config.json"; DestDir: "{app}"; Flags: onlyifdoesntexist uninsneveruninstall skipifsourcedoesntexist
; ...y si se marcó "REEMPLAZAR", se pisan con los del instalador (ya respaldados)
Source: "c:\Users\DISEÑO\Downloads\rfid-inventario\servidor\inventario.db"; DestDir: "{app}"; Flags: ignoreversion uninsneveruninstall skipifsourcedoesntexist; Tasks: reemplazardb
Source: "c:\Users\DISEÑO\Downloads\rfid-inventario\servidor\config.json"; DestDir: "{app}"; Flags: ignoreversion uninsneveruninstall skipifsourcedoesntexist; Tasks: reemplazardb
; Instalador del inventario para los DEMÁS PCs (mostrador, vendedores y el
; principal): queda aquí para llevarlo en un USB. Es uno solo: el tipo de PC
; se elige durante su instalación.
Source: "c:\Users\DISEÑO\Downloads\rfid-inventario\Instalar-InventarioRFID-PCs.exe"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist

[Icons]
Name: "{autodesktop}\Servidor Inventario RFID"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
; en modo servidor NO se usa acceso de inicio: lo arranca la tarea de Windows
Name: "{commonstartup}\Servidor Inventario RFID"; Filename: "{app}\{#MyAppExeName}"; Tasks: autostart and not autostartsrv

[Run]
; Permiso del firewall para que los otros PCs y la pistola entren al puerto 5000
Filename: "netsh"; Parameters: "advfirewall firewall add rule name=""Inventario RFID"" dir=in action=allow protocol=TCP localport=5000"; Flags: runhidden
; Modo PC SERVIDOR: tarea que arranca el servidor al prender el equipo (como
; SYSTEM: corre aunque nadie inicie sesión) y se arranca ya mismo
Filename: "schtasks"; Parameters: "/create /f /tn ""Inventario RFID Servidor"" /sc onstart /ru SYSTEM /rl HIGHEST /tr ""{app}\{#MyAppExeName} --sinventana"""; Flags: runhidden; Tasks: autostartsrv
Filename: "schtasks"; Parameters: "/run /tn ""Inventario RFID Servidor"""; Flags: runhidden; Tasks: autostartsrv
Filename: "{app}\{#MyAppExeName}"; Description: "Abrir Inventario RFID ahora"; Flags: nowait postinstall skipifsilent; Tasks: not autostartsrv

[UninstallRun]
Filename: "schtasks"; Parameters: "/end /tn ""Inventario RFID Servidor"""; Flags: runhidden; RunOnceId: "parartarea"
Filename: "schtasks"; Parameters: "/delete /f /tn ""Inventario RFID Servidor"""; Flags: runhidden; RunOnceId: "quitartarea"
Filename: "netsh"; Parameters: "advfirewall firewall delete rule name=""Inventario RFID"""; Flags: runhidden; RunOnceId: "quitarfirewall"

[Code]
{ Si el servidor está abierto (ventana o tarea de Windows), sus archivos están
  EN USO y no se podrían reemplazar: se cierra antes de instalar. }
procedure PararServidor();
var
  codigo: Integer;
begin
  Exec('schtasks', '/end /tn "Inventario RFID Servidor"', '', SW_HIDE,
       ewWaitUntilTerminated, codigo);
  Exec('taskkill', '/f /im ServidorInventarioRFID.exe', '', SW_HIDE,
       ewWaitUntilTerminated, codigo);
  Sleep(1500);   { deja que Windows suelte la base de datos }
end;

{ Antes de REEMPLAZAR los datos, se guarda una copia de los que ya estaban en
  ese PC: quedan junto al programa como inventario_ANTES_<fecha>.db / .json.
  Así, si se reemplazó por error, se puede volver atrás renombrando. }
procedure RespaldarSiSeReemplaza();
var
  carpeta, sello, actual: String;
begin
  carpeta := ExpandConstant('{app}\');
  sello := GetDateTimeString('yyyy-mm-dd_hhnn', #0, #0);
  actual := carpeta + 'inventario.db';
  if FileExists(actual) then
    FileCopy(actual, carpeta + 'inventario_ANTES_' + sello + '.db', False);
  actual := carpeta + 'config.json';
  if FileExists(actual) then
    FileCopy(actual, carpeta + 'config_ANTES_' + sello + '.json', False);
end;

{ Deja SOLO el arranque elegido.

  Inno crea accesos directos pero NUNCA borra los de una instalación anterior:
  por eso, si alguna vez se marcó "iniciar con ventana", ese acceso se quedaba
  en la carpeta de Inicio y seguía abriendo la ventana del inventario al
  prender el PC — aunque después se instalara en modo SERVIDOR sin ventana.
  Eso es lo que pasó en el PC 192.168.0.5. }
procedure LimpiarArranques();
var
  atajo: String;
  codigo: Integer;
begin
  atajo := ExpandConstant('{commonstartup}\Servidor Inventario RFID.lnk');
  if WizardIsTaskSelected('autostartsrv') or (not WizardIsTaskSelected('autostart')) then
    DeleteFile(atajo);
  { y al revés: si ya no se quiere el modo servidor, fuera la tarea de Windows }
  if not WizardIsTaskSelected('autostartsrv') then
  begin
    Exec('schtasks', '/end /tn "Inventario RFID Servidor"', '', SW_HIDE,
         ewWaitUntilTerminated, codigo);
    Exec('schtasks', '/delete /f /tn "Inventario RFID Servidor"', '', SW_HIDE,
         ewWaitUntilTerminated, codigo);
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssInstall then
  begin
    PararServidor();
    if WizardIsTaskSelected('reemplazardb') then
      RespaldarSiSeReemplaza();
  end;
  if CurStep = ssPostInstall then
    LimpiarArranques();
end;

{ Aviso claro al marcar la casilla: es la única acción del instalador que
  puede pisar datos en uso. }
function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if (CurPageID = wpSelectTasks) and WizardIsTaskSelected('reemplazardb')
     and FileExists(ExpandConstant('{app}\inventario.db')) then
    Result := MsgBox('Este PC YA tiene un inventario guardado.' + #13#10#13#10 +
      'Marcaste REEMPLAZAR: sus productos, existencias y etiquetas se cambiarán ' +
      'por los que trae el instalador.' + #13#10#13#10 +
      'Se guardará una copia de los actuales (inventario_ANTES_...db) por si ' +
      'necesitas volver atrás.' + #13#10#13#10 +
      '¿Continuar y reemplazar los datos de este PC?',
      mbConfirmation, MB_YESNO) = IDYES;
end;
