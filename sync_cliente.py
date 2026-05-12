"""
sync_cliente.py — Empuja los cambios pendientes de este nodo al admin central.

Este script lee la BD local (instance/inventario.db), saca los SyncLog en estado
'pendiente' y los manda en lote al admin central via POST /api/sync/push.

Configuración por variables de entorno (las mismas que usa app.py):
  PANOL_DB_PATH      Ruta de la BD local (default: instance/inventario.db)
  PANOL_NODO         Identificador del nodo (default: local)
  PANOL_ADMIN_URL    URL del admin central (ej. http://192.168.1.10:8080)
  PANOL_SYNC_TOKEN   Token compartido (igual en admin y todos los nodos)

USO MANUAL:
  python sync_cliente.py
  python sync_cliente.py --status      # solo muestra cuántos cambios hay
  python sync_cliente.py --batch 100   # envía solo los primeros 100

USO AUTOMÁTICO:
  Programar como tarea de Windows que corra cada 5 minutos.
  Ver CONFIGURAR_SINCRONIZACION.md para los pasos.
"""
import os
import sys
import json
import sqlite3
import argparse
from datetime import datetime

try:
    import requests
except ImportError:
    print("[ERROR] Falta el paquete `requests`. Instálalo con: pip install requests")
    sys.exit(1)


def cargar_config():
    aqui = os.path.dirname(os.path.abspath(__file__))
    db_path = os.environ.get('PANOL_DB_PATH', os.path.join(aqui, 'instance', 'inventario.db'))
    nodo = os.environ.get('PANOL_NODO', 'local')
    admin = (os.environ.get('PANOL_ADMIN_URL') or '').rstrip('/')
    token = os.environ.get('PANOL_SYNC_TOKEN', 'CAMBIAR_ESTE_TOKEN_PRODUCCION')
    if not admin:
        print("[ERROR] Falta PANOL_ADMIN_URL. Este script solo se corre en NODOS, no en el admin.")
        sys.exit(2)
    if not os.path.exists(db_path):
        print(f"[ERROR] No existe la BD: {db_path}")
        sys.exit(3)
    return {'db_path': db_path, 'nodo': nodo, 'admin': admin, 'token': token}


def cmd_status(cfg):
    con = sqlite3.connect(cfg['db_path'])
    cur = con.cursor()
    pend = cur.execute("SELECT COUNT(*) FROM sync_log WHERE push_status='pendiente'").fetchone()[0]
    enviados = cur.execute("SELECT COUNT(*) FROM sync_log WHERE push_status='enviado'").fetchone()[0]
    err = cur.execute("SELECT COUNT(*) FROM sync_log WHERE push_status='error'").fetchone()[0]
    con.close()

    print(f"\n=== Estado de sincronización del nodo '{cfg['nodo']}' ===")
    print(f"  BD local:        {cfg['db_path']}")
    print(f"  Admin central:   {cfg['admin']}")
    print(f"  Cambios pendientes:  {pend}")
    print(f"  Cambios enviados:    {enviados}")
    print(f"  Cambios con error:   {err}")

    # Probar conectividad con admin
    try:
        r = requests.get(f"{cfg['admin']}/api/sync/status",
                         headers={'Authorization': f"Bearer {cfg['token']}"},
                         timeout=5)
        if r.status_code == 200:
            print(f"\n  Admin: VIVO ✅  →  {r.json()}")
        else:
            print(f"\n  Admin respondió {r.status_code}: {r.text[:200]}")
    except Exception as e:
        print(f"\n  ❌ Admin NO responde: {e}")


def cmd_push(cfg, batch_size=200):
    con = sqlite3.connect(cfg['db_path'])
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    pendientes = cur.execute(
        "SELECT id, sync_uuid, tabla, registro_id_local, accion, payload "
        "FROM sync_log WHERE push_status='pendiente' "
        "ORDER BY id ASC LIMIT ?", (batch_size,)
    ).fetchall()

    if not pendientes:
        print(f"[{datetime.now().isoformat(timespec='seconds')}] Sin cambios pendientes.")
        con.close()
        return 0

    cambios = []
    for r in pendientes:
        try:
            payload = json.loads(r['payload']) if r['payload'] else {}
        except Exception:
            payload = {}
        cambios.append({
            'sync_uuid': r['sync_uuid'],
            'tabla': r['tabla'],
            'registro_id_local': r['registro_id_local'],
            'accion': r['accion'],
            'payload': payload,
        })

    body = {'nodo': cfg['nodo'], 'cambios': cambios}
    try:
        resp = requests.post(
            f"{cfg['admin']}/api/sync/push",
            json=body,
            headers={'Authorization': f"Bearer {cfg['token']}",
                     'Content-Type': 'application/json'},
            timeout=30,
        )
    except Exception as e:
        print(f"[ERROR] No pude conectar al admin: {e}")
        # Marcar como error pero permitir reintento más tarde
        for r in pendientes:
            cur.execute(
                "UPDATE sync_log SET push_intentos=push_intentos+1, "
                "push_error=? WHERE id=?",
                (str(e)[:500], r['id'])
            )
        con.commit()
        con.close()
        return 1

    if resp.status_code != 200:
        print(f"[ERROR] Admin respondió {resp.status_code}: {resp.text[:300]}")
        con.close()
        return 2

    data = resp.json()
    ok_uuids = set(data.get('ok', []))
    err_map = data.get('error', {})

    for r in pendientes:
        uid = r['sync_uuid']
        if uid in ok_uuids:
            cur.execute(
                "UPDATE sync_log SET push_status='enviado', push_intentos=push_intentos+1, "
                "push_error=NULL WHERE id=?",
                (r['id'],)
            )
        elif uid in err_map:
            cur.execute(
                "UPDATE sync_log SET push_status='error', push_intentos=push_intentos+1, "
                "push_error=? WHERE id=?",
                (err_map[uid][:500], r['id'])
            )
    con.commit()
    con.close()

    ts = datetime.now().isoformat(timespec='seconds')
    print(f"[{ts}] Enviados: {len(ok_uuids)}/{len(pendientes)}, "
          f"errores: {len(err_map)}")
    return 0


def main():
    p = argparse.ArgumentParser(description="Sync cliente PanolERP")
    p.add_argument('--status', action='store_true', help='Solo mostrar estado, no enviar')
    p.add_argument('--batch', type=int, default=200, help='Tamaño de lote (default 200)')
    args = p.parse_args()

    cfg = cargar_config()
    if args.status:
        cmd_status(cfg)
        return 0
    return cmd_push(cfg, batch_size=args.batch)


if __name__ == '__main__':
    sys.exit(main())
