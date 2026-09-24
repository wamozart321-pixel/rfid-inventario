@echo off
rem Arma ServidorInventarioRFID.exe (un solo archivo) con todo lo que necesita:
rem   templates, static  = las pantallas
rem   apks               = las apps de Android; el servidor las pasa a «subidos»
rem                        y las pistolas/celulares se actualizan solas con ellas
rem   certifi            = certificados para hablar con GitHub (actualizaciones)
rem Luego: los instaladores con Inno Setup (instalador.iss e instalador_inventario.iss).
rem ANTES, si se cambió templates\escritorio.html: traducir la copia para la
rem pistola Alien (Android 4.4) con «cd es5» y «node construir.mjs».
rem La prueba test_es5.py avisa si se olvidó.
cd /d "%~dp0"
python -m PyInstaller --onefile --noconsole --name ServidorInventarioRFID --icon icono.ico ^
  --add-data "templates;templates" --add-data "static;static" --add-data "apks;apks" ^
  --collect-data certifi --distpath dist --workpath build --noconfirm app.py
if errorlevel 1 (echo. & echo  FALLO al compilar & pause & exit /b 1)
copy /y dist\ServidorInventarioRFID.exe ServidorInventarioRFID.exe >nul
echo.
echo  Listo: ServidorInventarioRFID.exe
