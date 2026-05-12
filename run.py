#!/usr/bin/env python
# Script para ejecutar PanolERP - Inventory System

import os
import sys

# Asegurar que estamos en el directorio correcto
sys.path.insert(0, os.path.dirname(__file__))

# Importar la aplicacion Flask
from app import app

if __name__ == '__main__':
    PORT = 8080
    print(f"\n{'='*50}")
    print(f"🚀 PanolERP iniciando en http://127.0.0.1:{PORT}")
    print(f"{'='*50}")
    print("📝 Presiona Ctrl+C para detener\n")

    app.run(host='127.0.0.1', port=PORT, debug=True)
