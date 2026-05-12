@echo off
title Reiniciando Base de Datos...
color 0A

echo.
echo ============================================
echo   REINICIANDO BASE DE DATOS
echo ============================================
echo.

REM Cerrar todos los procesos Python
echo [1/3] Cerrando procesos Flask...
taskkill /F /IM python.exe /T 2>nul
timeout /t 2 /nobreak

REM Eliminar la base de datos antigua
echo [2/3] Eliminando base de datos antigua...
if exist "instance\pañol.db" (
    del "instance\pañol.db"
    echo ✅ Base de datos eliminada
) else (
    echo ⚠️ Base de datos no encontrada (sin problema)
)

echo.
echo [3/3] Iniciando la aplicación...
echo.
python run.py

pause
