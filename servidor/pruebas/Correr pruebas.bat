@echo off
REM Doble clic aqui para comprobar que el programa sigue funcionando.
REM No toca el inventario de verdad: cada prueba usa una base temporal.
cd /d "%~dp0"
python correr.py %*
echo.
pause
