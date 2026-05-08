"""
migrar_a_postgres.py — Migra los datos de instance/inventario.db (SQLite local)
a una base PostgreSQL en la nube.

USO:
    1. Asegúrate de tener la URL de PostgreSQL del proveedor (Render/Railway).
       Render la entrega como "Internal Database URL" o "External Database URL".
       Para correr este script localmente USA la "External" (la otra solo funciona dentro de Render).

    2. Configura la variable y corre el script:

       Windows PowerShell:
         $env:DATABASE_URL="postgresql://user:pass@host:5432/dbname"
         $env:SQLITE_PATH="instance/inventario.db"
         python migrar_a_postgres.py

       Linux / Mac:
         export DATABASE_URL="postgresql://user:pass@host:5432/dbname"
         python migrar_a_postgres.py

REQUISITOS:
    pip install psycopg2-binary sqlalchemy
"""
import os
import sys
import sqlite3
from datetime import datetime

try:
    from sqlalchemy import create_engine, MetaData, Table, text, inspect
except ImportError:
    print("[ERROR] Falta SQLAlchemy. Ejecuta: pip install sqlalchemy psycopg2-binary")
    sys.exit(1)


SQLITE_PATH = os.environ.get('SQLITE_PATH', 'instance/inventario.db')
PG_URL = os.environ.get('DATABASE_URL', '').strip()

if not PG_URL:
    print("[ERROR] Falta DATABASE_URL")
    print("Define la URL de PostgreSQL antes de ejecutar este script.")
    sys.exit(1)

# Render entrega "postgres://" pero SQLAlchemy 2.x exige "postgresql://"
if PG_URL.startswith('postgres://'):
    PG_URL = PG_URL.replace('postgres://', 'postgresql://', 1)

if not os.path.exists(SQLITE_PATH):
    print(f"[ERROR] No existe la BD SQLite: {SQLITE_PATH}")
    sys.exit(1)


# Tablas a migrar — orden IMPORTA por las foreign keys
TABLAS_ORDEN = [
    'especialidad',
    'usuario',
    'estudiante',
    'item',
    'prestamo',
    'auditoria',
    'alerta_stock',
    'orden_trabajo',
    'configuracion_sistema',
    'prestamo_externo',
    'sync_log',
]


def main():
    print("=" * 60)
    print("MIGRACIÓN SQLite → PostgreSQL")
    print(f"Origen:  {SQLITE_PATH}")
    print(f"Destino: {PG_URL.split('@')[-1] if '@' in PG_URL else PG_URL}")
    print(f"Hora:    {datetime.now()}")
    print("=" * 60)

    confirm = input("\n¿Continuar? Esto sobreescribirá los datos en PostgreSQL [s/N]: ")
    if confirm.lower() not in ('s', 'si', 'sí', 'y', 'yes'):
        print("Cancelado.")
        return 0

    # 1. Conectar al SQLite
    sqlite_con = sqlite3.connect(SQLITE_PATH)
    sqlite_con.row_factory = sqlite3.Row
    sqlite_cur = sqlite_con.cursor()

    # 2. Conectar al PostgreSQL e importar el modelo desde app.py para crear tablas
    print("\n[1/4] Creando tablas en PostgreSQL desde el modelo de app.py...")
    os.environ['DATABASE_URL'] = PG_URL

    # Importar después de fijar DATABASE_URL para que app.py la lea
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import app as panol_app
    with panol_app.app.app_context():
        panol_app.db.drop_all()      # tabula rasa por seguridad
        panol_app.db.create_all()
    print("   ✅ Tablas creadas")

    # 3. Conectar directo via SQLAlchemy core para insertar
    pg_engine = create_engine(PG_URL)
    metadata = MetaData()
    metadata.reflect(bind=pg_engine)

    print("\n[2/4] Tablas detectadas en PostgreSQL:")
    for t in metadata.tables:
        print(f"     - {t}")

    # 4. Migrar datos tabla por tabla
    print("\n[3/4] Migrando datos...")
    total_filas = 0
    with pg_engine.begin() as pg_con:
        # Desactivar FK checks durante la carga (PostgreSQL los hace al final del tx)
        for tabla in TABLAS_ORDEN:
            if tabla not in metadata.tables:
                print(f"     - {tabla}: SALTADO (no existe en PostgreSQL)")
                continue

            # Verificar que existe en SQLite
            existe = sqlite_cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (tabla,)
            ).fetchone()
            if not existe:
                print(f"     - {tabla}: SALTADO (no existe en SQLite)")
                continue

            filas = sqlite_cur.execute(f"SELECT * FROM {tabla}").fetchall()
            if not filas:
                print(f"     - {tabla}: 0 filas")
                continue

            pg_table = metadata.tables[tabla]
            pg_columns = set(c.name for c in pg_table.columns)
            datos = []
            for f in filas:
                row = dict(f)
                # Quedarse solo con columnas que existen en PG (por si hay diferencias)
                row = {k: v for k, v in row.items() if k in pg_columns}
                datos.append(row)

            pg_con.execute(pg_table.insert(), datos)
            print(f"     - {tabla}: {len(datos)} filas migradas")
            total_filas += len(datos)

        # 5. Re-secuenciar los IDs en PostgreSQL para que el próximo INSERT no choque
        print("\n[4/4] Re-secuenciando autoincrement de PostgreSQL...")
        for tabla in TABLAS_ORDEN:
            if tabla not in metadata.tables:
                continue
            try:
                # postgres usa secuencias <tabla>_<columna>_seq
                seq_name = f"{tabla}_id_seq"
                pg_con.execute(text(
                    f"SELECT setval('{seq_name}', "
                    f"COALESCE((SELECT MAX(id) FROM {tabla}), 0) + 1, false)"
                ))
            except Exception as e:
                print(f"     - {tabla}: secuencia no actualizada ({e})")

    sqlite_con.close()
    print(f"\n✅ Migración completa. Total: {total_filas} filas")
    print("\nSiguiente paso: configura DATABASE_URL en Render/Railway con la misma URL")
    print("y desplega tu app. Verifica el login con admin_central / admin123.")
    print("⚠️  Cambia la contraseña del admin después del primer login.")
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nCancelado por el usuario.")
        sys.exit(1)
