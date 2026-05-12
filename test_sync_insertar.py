"""test_sync_insertar.py — Inserta un cambio falso en sync_log para probar push."""
import sqlite3, json, uuid, os, sys

aqui = os.path.dirname(os.path.abspath(__file__))
db = os.path.join(aqui, 'instance', 'inventario.db')

if not os.path.exists(db):
    print(f"[ERROR] No existe la BD: {db}")
    sys.exit(1)

con = sqlite3.connect(db)
cur = con.cursor()

payload = {
    'codigo_barras': 'TEST-SYNC-001',
    'nombre': 'Item de prueba sync',
    'especialidad_id': 1,
    'cantidad_total': 10,
    'cantidad_disponible': 10,
    'categoria': 'Test',
}

cur.execute(
    "INSERT INTO sync_log(nodo_origen, tabla, registro_id_local, accion, "
    "payload, push_status, sync_uuid) VALUES (?, ?, ?, ?, ?, ?, ?)",
    ('panol_test', 'item', 9999, 'crear',
     json.dumps(payload), 'pendiente', uuid.uuid4().hex)
)
con.commit()

# Mostrar el último cambio insertado
fila = cur.execute(
    "SELECT id, sync_uuid, nodo_origen, tabla, accion, push_status "
    "FROM sync_log ORDER BY id DESC LIMIT 1"
).fetchone()
con.close()

print("✅ Cambio falso insertado en sync_log:")
print(f"   id={fila[0]}  uuid={fila[1][:12]}...  "
      f"nodo={fila[2]}  tabla={fila[3]}  accion={fila[4]}  status={fila[5]}")
print("\nAhora ejecuta:  python sync_cliente.py")
