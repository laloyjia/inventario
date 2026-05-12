@echo off
title Construyendo PanolERP.exe...
color 0A
echo.
echo ============================================
echo   CONSTRUCTOR DE PanolERP.exe
echo ============================================
echo.

REM Verificar que Python esta instalado
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python no esta instalado o no esta en el PATH.
    echo Descargalo desde https://www.python.org/downloads/
    pause
    exit /b 1
)

echo [1/3] Instalando dependencias necesarias...
pip install pyinstaller flask flask-sqlalchemy werkzeug pandas openpyxl --quiet
if errorlevel 1 (
    echo [ERROR] Fallo la instalacion de dependencias.
    pause
    exit /b 1
)

echo.
echo [2/3] Construyendo el ejecutable (esto puede tardar 1-2 minutos)...
pyinstaller PanolERP.spec --clean --noconfirm
if errorlevel 1 (
    echo [ERROR] Fallo la construccion del .exe
    pause
    exit /b 1
)

echo.
echo [3/3] Copiando la base de datos al directorio de salida...
if exist "instance\panol.db" (
    copy "instance\panol.db" "dist\" >nul
    echo Base de datos copiada.
)

echo.
echo ============================================
echo   LISTO! El archivo esta en:
echo   dist\PanolERP.exe
echo ============================================
echo.
echo Puedes copiar la carpeta "dist" a cualquier
echo computador Windows y ejecutar PanolERP.exe
echo (la base de datos panol.db viaja junto al .exe)
echo.
pause
