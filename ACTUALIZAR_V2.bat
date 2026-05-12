@echo off
title Actualizando a versión 2.0 Multi-Especialidad
color 0A

echo.
echo ============================================
echo   ACTUALIZACIÓN A VERSIÓN 2.0
echo ============================================
echo.

REM Cerrar Flask si está corriendo
echo [1/5] Cerrando procesos activos...
taskkill /F /IM python.exe /T 2>nul
timeout /t 2 /nobreak

REM Respaldar app.py actual
echo [2/5] Respaldando app.py anterior...
if exist "app.py" (
    ren "app.py" "app_v1_backup.py"
    echo ✅ app.py respaldado como app_v1_backup.py
)

REM Renombrar app_v2.py a app.py
echo [3/5] Activando versión 2.0...
if exist "app_v2.py" (
    ren "app_v2.py" "app.py"
    echo ✅ app_v2.py activado como app.py
)

REM Eliminar BD antigua
echo [4/5] Creando nueva base de datos...
if exist "instance\pañol.db" (
    del "instance\pañol.db"
    echo ✅ Base de datos anterior eliminada
)

echo.
echo [5/5] Iniciando sistema actualizado...
timeout /t 2 /nobreak
python run.py

pause
