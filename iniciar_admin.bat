@echo off
title PanolERP - ADMIN CENTRAL
REM ===== CONFIGURACIÓN ADMIN CENTRAL =====
REM Este PC RECIBE los cambios de todos los demás. NO definir PANOL_ADMIN_URL.
set PANOL_NODO=admin_central
set PANOL_SYNC_TOKEN=CAMBIAR_ESTE_TOKEN_POR_UNO_LARGO_Y_RANDOM
set PANOL_SECRET_KEY=otra_clave_distinta_para_sesiones
REM ========================================
echo.
echo ========================================
echo   PanolERP - ADMIN CENTRAL
echo   Nodo: %PANOL_NODO%
echo ========================================
echo.
call venv\Scripts\activate
python run.py
pause
