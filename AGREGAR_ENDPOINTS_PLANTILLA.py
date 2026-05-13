# -*- coding: utf-8 -*-
"""
AGREGAR_ENDPOINTS_PLANTILLA.py
==============================
Inserta los endpoints /descargar_plantilla y /descargar_plantilla_alumnos
en app.py SIN que se trunque el archivo.

Uso:
    python AGREGAR_ENDPOINTS_PLANTILLA.py

- Hace backup de app.py antes de tocarlo (app.py.bak_endpoints).
- Inserta los endpoints justo antes de "@app.route('/admin/reporte_mermas')".
- Idempotente: si ya están, no hace nada.
"""
import os
import shutil
import sys
from datetime import datetime

AQUI = os.path.dirname(os.path.abspath(__file__))
APP_PY = os.path.join(AQUI, 'app.py')

if not os.path.exists(APP_PY):
    print(f"[ERROR] No encuentro {APP_PY}")
    sys.exit(1)

# Backup
stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
backup = APP_PY + f".bak_endpoints_{stamp}"
shutil.copy2(APP_PY, backup)
print(f"[OK] Backup creado: {os.path.basename(backup)}")

# Leer contenido
with open(APP_PY, 'r', encoding='utf-8') as f:
    contenido = f.read()

# Si ya existen los endpoints, no hacer nada
if "@app.route('/descargar_plantilla_alumnos')" in contenido:
    print("[OK] Los endpoints ya estan presentes. No hago nada.")
    sys.exit(0)

# Texto a insertar
ENDPOINTS = '''
@app.route('/descargar_plantilla')
@login_requerido
def descargar_plantilla():
    """Descarga el archivo inventario_muestra.xlsx como plantilla."""
    aqui = os.path.dirname(os.path.abspath(__file__))
    plantilla = os.path.join(aqui, 'inventario_muestra.xlsx')
    if os.path.exists(plantilla):
        return send_file(plantilla, as_attachment=True,
                         download_name='plantilla_inventario.xlsx')
    # Fallback: generar al vuelo con las 11 columnas
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = 'Inventario'
    headers = ['Codigo de barra', 'Nombre', 'Descripcion', 'Categoria',
               'Cantidad', 'Ubicacion', 'Fecha adquisicion',
               'Desgaste ($)', 'Costo unitario ($)', 'Costo total ($)',
               'Imagen de referencia']
    for c, h in enumerate(headers, 1):
        ws.cell(row=1, column=c, value=h)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return send_file(buf, as_attachment=True,
                     download_name='plantilla_inventario.xlsx',
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


@app.route('/descargar_plantilla_alumnos')
@login_requerido
def descargar_plantilla_alumnos():
    """Descarga la plantilla Excel para carga masiva de alumnos (2 columnas)."""
    aqui = os.path.dirname(os.path.abspath(__file__))
    plantilla = os.path.join(aqui, 'alumnos_muestra.xlsx')
    if os.path.exists(plantilla):
        return send_file(plantilla, as_attachment=True,
                         download_name='plantilla_alumnos.xlsx')
    # Fallback: 2 columnas
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = 'Alumnos'
    ws.cell(row=1, column=1, value='N de lista')
    ws.cell(row=1, column=2, value='Nombre completo')
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return send_file(buf, as_attachment=True,
                     download_name='plantilla_alumnos.xlsx',
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


'''

# Intentar insertar antes de admin_reporte_mermas (si existe)
marker_pref = "@app.route('/admin/reporte_mermas')"
if marker_pref in contenido:
    nuevo = contenido.replace(marker_pref, ENDPOINTS + marker_pref, 1)
else:
    # Insertar antes del bloque __main__
    marker_main = "if __name__ == '__main__':"
    if marker_main not in contenido:
        print("[ERROR] No encuentro 'if __name__' ni 'admin/reporte_mermas' en app.py")
        print("        Es probable que app.py este truncado. Restaura con: git checkout -- app.py")
        sys.exit(2)
    nuevo = contenido.replace(marker_main, ENDPOINTS + marker_main, 1)

# Guardar
with open(APP_PY, 'w', encoding='utf-8') as f:
    f.write(nuevo)

# Verificar sintaxis
import py_compile
try:
    py_compile.compile(APP_PY, doraise=True)
    print("[OK] app.py modificado y compila sin errores.")
except py_compile.PyCompileError as e:
    print(f"[ERROR] El archivo modificado tiene errores de sintaxis: {e}")
    print(f"        Restaurando desde backup...")
    shutil.copy2(backup, APP_PY)
    print("[OK] Restaurado.")
    sys.exit(3)

print()
print("Listo. Siguientes pasos:")
print("  1. wc -l app.py    # debe ser ~2940")
print("  2. tail -1 app.py  # debe terminar con app.run")
print("  3. git add app.py inventario_muestra.xlsx alumnos_muestra.xlsx")
print("  4. git commit -m 'fix: reagregar endpoints descargar_plantilla y subir XLSX'")
print("  5. git push")
