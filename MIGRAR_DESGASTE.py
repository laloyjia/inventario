# -*- coding: utf-8 -*-
"""
MIGRAR_DESGASTE.py
==================
Agrega la columna `desgaste` (FLOAT en pesos CLP) a la tabla `item`.

Antes de migrar hace un backup automático de instance/inventario.db.

Uso (desde el directorio del proyecto):
    python MIGRAR_DESGASTE.py

Es idempotente: si la columna ya existe, no hace nada (solo informa).
Funciona sobre SQLite y PostgreSQL.

En cloud (Render/Railway con DATABASE_URL) detecta automáticamente
el motor y aplica el ALTER correspondiente.
"""
import os
import sys
import shutil
import sqlite3
from datetime import datetime

# Permitir importar la app desde el mismo directorio
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

DB_PATH = os.path.join(SCRIPT_DIR, 'instance', 'inventario.db')


def backup_sqlite(path):
    """Copia la BD a un archivo con timestamp antes de tocar nada."""
    if not os.path.exists(path):
        print(f"[!] No existe la BD en: {path}")
        return None
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    dest = f"{path}.bak_desgaste_{stamp}"
    shutil.copy2(path, dest)
    size_kb = os.path.getsize(dest) / 1024
    print(f"[OK] Backup creado: {os.path.basename(dest)} ({size_kb:.1f} KB)")
    return dest


def migrar_sqlite():
    if not os.path.exists(DB_PATH):
        print(f"[ERROR] No encuentro la BD: {DB_PATH}")
        sys.exit(1)

    backup_sqlite(DB_PATH)

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(item)")
    cols = [row[1] for row in cur.fetchall()]

    if 'desgaste' in cols:
        print("[OK] La columna `desgaste` ya existe. No hago nada.")
        conn.close()
        return

    print("[..] Aplicando: ALTER TABLE item ADD COLUMN desgaste FLOAT NOT NULL DEFAULT 0")
    cur.execute("ALTER TABLE item ADD COLUMN desgaste FLOAT NOT NULL DEFAULT 0")
    conn.commit()

    cur.execute("PRAGMA table_info(item)")
    cols2 = [row[1] for row in cur.fetchall()]
    assert 'desgaste' in cols2, "La migración no aplicó la columna"
    print("[OK] Columna `desgaste` agregada con éxito.")

    # Verificar que cuente filas
    cur.execute("SELECT COUNT(*) FROM item")
    total = cur.fetchone()[0]
    print(f"[INFO] Items en la tabla: {total} (todos con desgaste = 0 por defecto)")
    conn.close()


def migrar_postgres():
    """Si está corriendo en Render/Railway, usa SQLAlchemy de la app."""
    try:
        from app import app, db
        from sqlalchemy import text
    except Exception as e:
        print(f"[ERROR] No pude importar app: {e}")
        sys.exit(1)

    with app.app_context():
        engine = db.engine
        with engine.begin() as conn:
            res = conn.execute(text("""
                SELECT column_name FROM information_schema.columns
                WHERE table_name='item' AND column_name='desgaste'
            """))
            if res.fetchone():
                print("[OK] La columna `desgaste` ya existe en Postgres. No hago nada.")
                return
            conn.execute(text(
                "ALTER TABLE item ADD COLUMN desgaste DOUBLE PRECISION NOT NULL DEFAULT 0"
            ))
            print("[OK] Columna `desgaste` agregada a Postgres.")


def main():
    db_url = os.environ.get('DATABASE_URL', '')
    if db_url.startswith('postgres'):
        print("[INFO] Detectado Postgres (DATABASE_URL). Migrando en cloud...")
        migrar_postgres()
    else:
        print(f"[INFO] Detectado SQLite local: {DB_PATH}")
        migrar_sqlite()
    print("\n[DONE] Migración finalizada. Ya puedes reiniciar la app.")


if __name__ == '__main__':
    main()
