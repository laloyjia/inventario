"""
PROBAR_SISTEMA.py — Script de pruebas automáticas para PanolERP

CÓMO USARLO:
1. En una terminal: python run.py   (deja la app corriendo en :8080)
2. En OTRA terminal: python PROBAR_SISTEMA.py
3. Ve los resultados: cada prueba imprime [OK] o [FALLA]

Si requests no está instalado:
    pip install requests
"""
import requests
import json
import sys
from datetime import datetime

BASE = 'http://127.0.0.1:8080'
session = requests.Session()

# Contadores
ok = 0
fail = 0

def check(nombre, condicion, detalle=''):
    global ok, fail
    if condicion:
        print(f"  [OK]   {nombre}")
        ok += 1
    else:
        print(f"  [FALLA] {nombre}  {detalle}")
        fail += 1

def req(metodo, ruta, **kw):
    """Hacer petición con allow_redirects=False para ver redirecciones."""
    kw.setdefault('allow_redirects', False)
    return session.request(metodo, BASE + ruta, **kw)

print("=" * 60)
print("BATERÍA DE PRUEBAS — PanolERP")
print(f"Servidor: {BASE}")
print(f"Hora:     {datetime.now()}")
print("=" * 60)

# ============== 1. SERVIDOR VIVO ==============
print("\n[1] El servidor responde")
try:
    r = requests.get(BASE + '/login', timeout=5)
    check("GET /login responde 200", r.status_code == 200,
          f"status={r.status_code}")
except Exception as e:
    print(f"\n[ERROR FATAL] No puedo conectar al servidor en {BASE}")
    print(f"  Detalle: {e}")
    print("\n  ¿Está corriendo `python run.py` en otra terminal?")
    sys.exit(1)

# ============== 2. LOGIN ADMIN ==============
print("\n[2] Login del administrador central")
r = req('POST', '/login', data={'username': 'admin_central', 'password': 'admin123'})
check("POST /login admin_central redirige (302)", r.status_code in (302, 303))
check("Sesión guardada en cookie", 'session' in session.cookies.get_dict())

# ============== 3. DASHBOARD ADMIN MUESTRA 8 ESPECIALIDADES ==============
print("\n[3] Dashboard admin muestra 8 áreas")
r = req('GET', '/dashboard_admin', allow_redirects=True)
check("GET /dashboard_admin responde 200", r.status_code == 200)
for esp in ['Electrónica', 'Mecánica Automotriz', 'Electricidad', 'Gráfica',
            'ACLE', 'Oficina', 'Biblioteca']:
    check(f"  Aparece '{esp}'", esp in r.text)

# ============== 4. LOGOUT Y LOGIN COMO PAÑOLERO ELECTRÓNICA ==============
print("\n[4] Login como pañolero de Electrónica")
req('GET', '/logout')
r = req('POST', '/login', data={'username': 'pañolero_electronica', 'password': 'pañol123'})
check("POST /login pañolero_electronica redirige", r.status_code in (302, 303))

r = req('GET', '/inventario', allow_redirects=True)
check("GET /inventario carga", r.status_code == 200)
check("  Página menciona Electrónica", 'Electrónica' in r.text or 'electronica' in r.text.lower())

# ============== 5. AGREGAR ITEM ==============
print("\n[5] Agregar ítem al pañol de Electrónica")
r = req('POST', '/agregar', data={
    'nombre': 'Multímetro Digital DT830',
    'codigo_barras': 'TEST-MULTI-001',
    'categoria': 'Herramienta',
    'cantidad': 5,
    'ubicacion': 'Estante A1',
})
check("POST /agregar redirige", r.status_code in (302, 303))

# ============== 6. AGREGAR ESTUDIANTE ==============
print("\n[6] Alta de estudiante")
rut_test = f"TEST-{datetime.now().strftime('%H%M%S')}"
r = req('POST', '/agregar_estudiante', data={
    'rut_matricula': rut_test,
    'nombre': 'Estudiante de Prueba',
    'curso': '4to A',
})
check("POST /agregar_estudiante redirige", r.status_code in (302, 303))

# ============== 7. ORDEN DE TRABAJO ==============
print("\n[7] Crear orden de trabajo")
r = req('POST', '/agregar_ot', data={
    'titulo': 'OT de prueba automática',
    'profesional_cargo': 'Profesor Test',
    'alumnos_cargo': 'Alumno A, Alumno B',
    'descripcion': 'Reparación tablero',
    'herramientas_utilizadas': 'Destornillador x1\nTester x1',
    'repuestos_utilizados': 'Resistencia 1k x10',
})
check("POST /agregar_ot redirige", r.status_code in (302, 303))

# ============== 8. PRÉSTAMO EXTERNO ==============
print("\n[8] Préstamo externo")
r = req('POST', '/agregar_prestamo_externo', data={
    'codigo_item': 'TEST-MULTI-001',
    'cantidad': 1,
    'tipo_persona': 'externo',
    'persona_retira': 'Juan Pérez (visitante)',
    'profesor_cargo': 'Prof. García',
    'especialidad_destino': 'Mecánica Automotriz',
    'tipo_movimiento': 'prestamo',
})
check("POST /agregar_prestamo_externo redirige", r.status_code in (302, 303))

# ============== 9. EXPORTAR EXCEL ==============
print("\n[9] Exportar inventario a Excel")
r = req('GET', '/exportar_excel')
check("GET /exportar_excel responde 200", r.status_code == 200)
check("  Es un archivo XLSX", r.headers.get('Content-Type', '').startswith(
    'application/vnd.openxmlformats'))
if r.status_code == 200:
    with open('inventario_exportado_test.xlsx', 'wb') as f:
        f.write(r.content)
    print(f"        Excel guardado: inventario_exportado_test.xlsx ({len(r.content)} bytes)")

# ============== 10. AUDITORÍA ==============
print("\n[10] Página de auditoría")
r = req('GET', '/auditoria')
check("GET /auditoria responde 200", r.status_code == 200)

# ============== 11. CAMBIO DE USUARIO: BIBLIOTECA ==============
print("\n[11] Login como pañolero de Biblioteca")
req('GET', '/logout')
r = req('POST', '/login', data={'username': 'pañolero_biblioteca', 'password': 'pañol123'})
check("POST /login pañolero_biblioteca redirige", r.status_code in (302, 303))

# ============== 12. AGREGAR LIBRO ==============
print("\n[12] Agregar libro a la biblioteca")
r = req('POST', '/agregar_libro', data={
    'nombre': 'Cien años de soledad',
    'autor': 'Gabriel García Márquez',
    'isbn': '978-84-376-0494-7',
    'editorial': 'Editorial Sudamericana',
    'anio_publicacion': '1967',
    'cantidad': 3,
    'ubicacion': 'Estante Lit. Latinoamericana',
})
check("POST /agregar_libro redirige", r.status_code in (302, 303))

# ============== 13. CATÁLOGO BIBLIOTECA ==============
print("\n[13] Catálogo de biblioteca")
r = req('GET', '/biblioteca', allow_redirects=True)
check("GET /biblioteca responde 200", r.status_code == 200)
check("  Aparece 'Cien años de soledad'", 'Cien años' in r.text)

print("\n[13b] Búsqueda en catálogo")
r = req('GET', '/biblioteca?q=García', allow_redirects=True)
check("GET /biblioteca?q=García responde 200", r.status_code == 200)

# ============== 14. ATRASADOS (JSON) ==============
print("\n[14] Reporte de libros atrasados (JSON)")
r = req('GET', '/biblioteca/atrasados')
check("GET /biblioteca/atrasados responde 200", r.status_code == 200)
try:
    data = r.json()
    check("  Devuelve JSON con 'atrasados' y 'total'",
          'atrasados' in data and 'total' in data,
          f"Respuesta: {data}")
except Exception as e:
    check("  Devuelve JSON válido", False, str(e))

# ============== 15. CAMBIO DE USUARIO: OFICINA ==============
print("\n[15] Login como pañolero de Oficina")
req('GET', '/logout')
r = req('POST', '/login', data={'username': 'pañolero_oficina', 'password': 'pañol123'})
check("POST /login pañolero_oficina redirige", r.status_code in (302, 303))

# ============== 16. AGREGAR CONSUMIBLE ==============
print("\n[16] Agregar consumible a Oficina")
r = req('POST', '/agregar', data={
    'nombre': 'Resma papel A4',
    'codigo_barras': 'OFI-RESMA-001',
    'categoria': 'Oficina',
    'cantidad': 50,
    'ubicacion': 'Bodega 2',
})
check("POST /agregar (oficina) redirige", r.status_code in (302, 303))

# ============== 17. REGISTRAR CONSUMO ==============
print("\n[17] Registrar consumo (descuenta del total)")
r = req('POST', '/registrar_consumo', data={
    'codigo_item': 'OFI-RESMA-001',
    'cantidad': 2,
    'persona_retira': 'Inspectoría',
    'motivo': 'Reposición secretaría',
})
check("POST /registrar_consumo redirige", r.status_code in (302, 303))

# ============== RESUMEN ==============
req('GET', '/logout')
print("\n" + "=" * 60)
print(f"RESUMEN: {ok} OK / {fail} FALLAS")
if fail == 0:
    print("✅ TODAS LAS PRUEBAS PASARON")
else:
    print(f"⚠️ {fail} prueba(s) fallaron — revisa los detalles arriba")
print("=" * 60)
sys.exit(0 if fail == 0 else 1)
