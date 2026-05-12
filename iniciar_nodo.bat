@echo off
title PanolERP - NODO PAÑOL
REM ===== CONFIGURACIÓN NODO =====
REM ¡EDITAR estas líneas según el PC en el que estás!
set PANOL_NODO=panol_electronica
set PANOL_ADMIN_URL=http://192.168.1.10:8080
set PANOL_SYNC_TOKEN=CAMBIAR_ESTE_TOKEN_POR_UNO_LARGO_Y_RANDOM
set PANOL_SECRET_KEY=otra_clave_local
REM ===============================
echo.
echo ========================================
echo   PanolERP - NODO
echo   Nodo:    %PANOL_NODO%
echo   Admin:   %PANOL_ADMIN_URL%
echo ========================================
echo.
call venv\Scripts\activate
python run.py
pause
