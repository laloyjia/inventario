# -*- coding: utf-8 -*-
"""
REPARAR_RENDER.py
=================
Diagnostico y reparacion de la BD Postgres en Render.

Aplica TODAS las columnas faltantes en las tablas `usuario` e `item`
que la app espera segun el modelo actual.

USO:
    1. Sube este archivo al repo y haz push.
    2. En Render: Dashboard -> tu servicio -> Shell -> ejecutar:
         python REPARAR_RENDER.py

Es idempotente: si las columnas ya existen, no hace nada.
"""
import os
import sys

DB_URL = os.environ.get('DATABASE_URL', '')
if not DB_URL:
    print("[ERROR] No hay DATABASE_URL. Este script se ejecuta en Render.")
    sys.exit(1)

# Render entrega postgres:// pero SQLAlchemy quiere postgresql://
if DB_URL.startswith('postgres://'):
    DB_URL = DB_URL.replace('postgres://', 'postgresql://', 1)

try:
    import psycopg2
except ImportError:
    print("[ERROR] psycopg2 no instalado.")
    sys.exit(1)

print("[..] Conectando a Postgres...")
conn = psycopg2.connect(DB_URL)
conn.autocommit = True
cur = conn.cursor()


def cols_de(tabla):
    cur.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = %s
    """, (tabla,))
    return {r[0] for r in cur.fetchall()}


def ensure_column(tabla, columna, ddl):
    """Si la columna no existe, la crea. Idempotente."""
    if columna in cols_de(tabla):
        print(f"  [OK] {tabla}.{columna} ya existe")
        return False
    print(f"  [..] {tabla}.{columna} FALTA — aplicando ALTER...")
    cur.execute(f"ALTER TABLE {tabla} ADD COLUMN {columna} {ddl}")
    print(f"  [OK] {tabla}.{columna} agregada")
    return True


print("\n=== TABLA: usuario ===")
ensure_column('usuario', 'failed_attempts',      'INTEGER NOT NULL DEFAULT 0')
ensure_column('usuario', 'locked_until',         'TIMESTAMP NULL')
ensure_column('usuario', 'must_change_password', 'BOOLEAN NOT NULL DEFAULT FALSE')

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

print("\n=== TABLA: especialidad ===")
ensure_column('especialidad', 'tipo_area', "VARCHAR(20) NOT NULL DEFAULT 'GENERAL'")

print("\n[OK] Reparacion finalizada. Probar el login ahora.")
cur.close()
conn.close()
