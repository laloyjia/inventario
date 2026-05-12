@echo off
title PanolERP - Sincronizar con admin
REM ===== Misma config que iniciar_nodo.bat =====
set PANOL_NODO=panol_electronica
set PANOL_ADMIN_URL=http://192.168.1.10:8080
set PANOL_SYNC_TOKEN=CAMBIAR_ESTE_TOKEN_POR_UNO_LARGO_Y_RANDOM
REM =============================================
call venv\Scripts\activate
python sync_cliente.py
pause
