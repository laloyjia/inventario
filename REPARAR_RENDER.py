# -*- coding: utf-8 -*-
"""
REPARAR_RENDER.py
=================
Diagnostico y reparacion COMPLETA de la BD Postgres en Render.

Aplica todas las columnas y tablas faltantes que la app espera segun
el modelo actual.

USO en Render Shell:
    python REPARAR_RENDER.py

Es idempotente. Si todo ya esta migrado, no hace nada.
"""
import os
import sys

DB_URL = os.environ.get('DATABASE_URL', '')
if not DB_URL:
    print("[ERROR] No hay DATABASE_URL. Este script se ejecuta en Render.")
    sys.exit(1)

if DB_URL.startswith('postgres://'):
    DB_URL = DB_URL.replace('postgres://', 'postgresql://', 1)

try:
    import psycopg2
except ImportError:
    print("[ERROR] psycopg2 no instalado. Ejecuta: pip install psycopg2-binary")
    sys.exit(1)

print("[..] Conectando a Postgres...")
conn = psycopg2.connect(DB_URL)
conn.autocommit = True
cur = conn.cursor()


def tablas():
    cur.execute("""SELECT table_name FROM information_schema.tables
                   WHERE table_schema='public'""")
    return {r[0] for r in cur.fetchall()}


def cols_de(tabla):
    cur.execute("""SELECT column_name FROM information_schema.columns
                   WHERE table_name=%s""", (tabla,))
    return {r[0] for r in cur.fetchall()}


def ensure_column(tabla, columna, ddl):
    if tabla not in tablas():
        print(f"  [SKIP] tabla {tabla} no existe, saltando columna {columna}")
        return False
    if columna in cols_de(tabla):
        print(f"  [OK] {tabla}.{columna} ya existe")
        return False
    print(f"  [..] {tabla}.{columna} FALTA -- aplicando ALTER...")
    try:
        cur.execute(f"ALTER TABLE {tabla} ADD COLUMN {columna} {ddl}")
        print(f"  [OK] {tabla}.{columna} agregada")
        return True
    except Exception as e:
        print(f"  [ERROR] {tabla}.{columna}: {e}")
        return False


def ensure_table(nombre, ddl):
    if nombre in tablas():
        print(f"  [OK] tabla {nombre} ya existe")
        return False
    print(f"  [..] creando tabla {nombre}...")
    cur.execute(ddl)
    print(f"  [OK] tabla {nombre} creada")
    return True


print(f"\n[INFO] Tablas existentes: {sorted(tablas())}")

print("\n=== TABLA NUEVA: curso ===")
ensure_table('curso', """
CREATE TABLE IF NOT EXISTS curso (
    id SERIAL PRIMARY KEY,
    nombre VARCHAR(100) NOT NULL,
    nivel VARCHAR(20),
    letra VARCHAR(5),
    anio INTEGER,
    especialidad_id INTEGER NOT NULL REFERENCES especialidad(id),
    activo BOOLEAN NOT NULL DEFAULT TRUE,
    fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_curso_nombre_esp UNIQUE (nombre, especialidad_id)
)
""")

print("\n=== TABLA: usuario ===")
ensure_column('usuario', 'failed_attempts',      'INTEGER NOT NULL DEFAULT 0')
ensure_column('usuario', 'locked_until',         'TIMESTAMP NULL')
ensure_column('usuario', 'must_change_password', 'BOOLEAN NOT NULL DEFAULT FALSE')

print("\n=== TABLA: especialidad ===")
ensure_column('especialidad', 'tipo_area', "VARCHAR(20) NOT NULL DEFAULT 'GENERAL'")

print("\n=== TABLA: item ===")
ensure_column('item', 'autor',             'VARCHAR(200) NULL')
ensure_column('item', 'isbn',              'VARCHAR(50) NULL')
ensure_column('item', 'editorial',         'VARCHAR(200) NULL')
ensure_column('item', 'anio_publicacion',  'INTEGER NULL')
ensure_column('item', 'marca',             'VARCHAR(100) NULL')
ensure_column('item', 'modelo',            'VARCHAR(100) NULL')
ensure_column('item', 'numero_serie',      'VARCHAR(100) NULL')
ensure_column('item', 'estado',            'VARCHAR(50) NULL')
ensure_column('item', 'fecha_adquisicion', 'DATE NULL')
ensure_column('item', 'max_usos',          'INTEGER NULL')
ensure_column('item', 'usos_actuales',     'INTEGER NOT NULL DEFAULT 0')
ensure_column('item', 'desgaste',          'DOUBLE PRECISION NOT NULL DEFAULT 0')

print("\n=== TABLA: estudiante ===")
ensure_column('estudiante', 'curso_id', 'INTEGER NULL')
ensure_column('estudiante', 'email',    'VARCHAR(120) NULL')

print("\n=== TABLA: prestamo ===")
ensure_column('prestamo', 'panolero_dia_id', 'INTEGER NULL')

print("\n[OK] Reparacion finalizada.")
print("[INFO] Si Render tuvo el error 500, ahora reinicia el servicio:")
print("       Dashboard -> tu servicio -> Manual Deploy -> Deploy latest commit")
cur.close()
conn.close()
