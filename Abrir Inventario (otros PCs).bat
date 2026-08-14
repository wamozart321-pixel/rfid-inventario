@echo off
rem ============================================================
rem  INVENTARIO RFID - acceso desde cualquier PC del local
rem  Copie este archivo al Escritorio de cada PC y haga doble clic.
rem  Si algun dia cambia la IP del PC principal, corrija la linea SERVIDOR.
rem ============================================================
set SERVIDOR=192.168.0.2:5000

set EDGE=%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe
if not exist "%EDGE%" set EDGE=%ProgramFiles%\Microsoft\Edge\Application\msedge.exe

if exist "%EDGE%" (
  start "" "%EDGE%" --app=http://%SERVIDOR%/escritorio
) else (
  start "" http://%SERVIDOR%/escritorio
)
