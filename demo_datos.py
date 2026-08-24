#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Crea un ENTORNO DE DEMOSTRACIÓN para presentar PanolERP:

  1. Un área (especialidad) llamada "Demostración".
  2. Un usuario pañolero de demo:   usuario: demostracion   clave: demo123
     (NO se le exige cambiar la contraseña, para entrar directo en la demo).
  3. Inventario de ejemplo (herramientas, componentes, materiales, fungibles),
     con stock bajo mínimo en algunos ítems (para mostrar alertas), precios,
     desgaste y bienes marcados con Decreto 240.
  4. Estudiantes de ejemplo y préstamos (pendientes y devueltos) para que las
     estadísticas y gráficos del dashboard se vean poblados.

USO  (desde Git Bash)
---------------------
  # SQLite local:
  python demo_datos.py

  # Base de Render (para presentar sobre el sitio en vivo):
  DATABASE_URL="postgresql://usuario:clave@host:5432/basedatos" python demo_datos.py

  # Volver a generar los datos desde cero (borra SOLO los del área Demostración):
  python demo_datos.py --reset

Es idempotente: si el área ya tiene datos, no los duplica (salvo con --reset).
"""
import sys
import random
from datetime import datetime, timedelta

from app import (app, db, Especialidad, Usuario, Item, Estudiante, Prestamo,
                 RegistroBaja)
from werkzeug.security import generate_password_hash

DEMO_ESP  = "Demostración"
DEMO_USER = "demostracion"
DEMO_PASS = "demo123"

# Demo 2: usuario para visualizar la vista del área Gráfica (caducidad + CEST)
DEMO_G_USER = "demo_grafica"
DEMO_G_PASS = "demo123"

# Demo 3: cuenta ADMIN de demostración (ve todo + Panel Gerencial)
DEMO_ADMIN_USER = "demo_admin"
DEMO_ADMIN_PASS = "demo123"

random.seed(42)


def _items_demo(esp_id):
    hoy = datetime.utcnow().date()
    data = [
        # nombre, categoria, total, disp, minima, precio, ubic, desgaste, dec240, max_usos, usos
        ("Taladro percutor 750W", "Herramientas", 8, 6, 3, 54990, "Estante A1", 12000, True, 500, 210),
        ("Juego de destornilladores", "Herramientas", 15, 15, 5, 12990, "Estante A2", 3000, False, None, 0),
        ("Cautín 60W", "Herramientas", 6, 2, 4, 22990, "Estante A1", 8000, False, 300, 180),
        ("Pistola de silicona", "Herramientas", 5, 1, 4, 9990, "Estante A3", 2000, False, None, 0),
        ("Alicate universal 1000V", "Herramientas", 9, 7, 3, 18990, "Estante A2", 4000, False, None, 0),
        ("Multímetro digital", "Componentes", 10, 8, 4, 39990, "Vitrina B1", 5000, True, None, 0),
        ("Osciloscopio 100MHz", "Componentes", 2, 2, 1, 349990, "Vitrina B2", 45000, True, None, 0),
        ("Fuente de poder 0-30V", "Componentes", 3, 1, 2, 89990, "Vitrina B1", 15000, True, None, 0),
        ("Protoboard 830 puntos", "Componentes", 25, 20, 8, 3990, "Cajón C2", 0, False, None, 0),
        ("Resistencias 1/4W (surtido)", "Componentes", 600, 540, 100, 15990, "Cajón C3", 0, False, None, 0),
        ("Estaño 60/40 rollo 250g", "Materiales", 20, 12, 6, 8990, "Cajón C1", 0, False, None, 0),
        ("Cable UTP Cat6 (m)", "Materiales", 300, 250, 50, 650, "Estante D2", 0, False, None, 0),
        ("Termorretráctil surtido", "Materiales", 40, 30, 10, 5990, "Cajón C1", 0, False, None, 0),
        ("Guantes nitrilo (par)", "Fungibles", 40, 8, 15, 2490, "Estante E1", 0, False, None, 0),
        ("Lentes de protección", "Fungibles", 35, 30, 10, 3490, "Estante E1", 0, False, None, 0),
        ("Mascarillas para soldar", "Fungibles", 50, 12, 20, 1990, "Estante E2", 0, False, None, 0),
        ("Barras de silicona (bolsa)", "Fungibles", 12, 3, 6, 3990, "Cajón C1", 0, False, None, 0),
        ("Brocas HSS set 13 pzas", "Herramientas", 7, 5, 3, 14990, "Estante A3", 3500, False, 400, 95),
        ("Cinta aislante (rollo)", "Fungibles", 60, 45, 20, 990, "Cajón C4", 0, False, None, 0),
        ("Sensor ultrasónico HC-SR04", "Componentes", 30, 26, 10, 2490, "Cajón C2", 0, False, None, 0),
    ]
    out = []
    for i, (nombre, cat, tot, disp, mini, precio, ubic, desg, dec, maxu, usos) in enumerate(data, 1):
        out.append(Item(
            codigo_barras=f"DEMO-{i:04d}",
            nombre=nombre, categoria=cat, especialidad_id=esp_id,
            cantidad_total=tot, cantidad_disponible=disp, cantidad_minima=mini,
            precio_unitario=precio, ubicacion=ubic, desgaste=desg,
            decreto_240=dec, max_usos=maxu, usos_actuales=usos,
            estado="Bueno",
            fecha_adquisicion=hoy - timedelta(days=random.randint(120, 900)),
        ))
    return out


def _items_grafica(esp_id):
    """Insumos gráficos con fecha de caducidad y marca CEST, para mostrar
    las funciones exclusivas del área Gráfica. Algunos vienen vencidos."""
    hoy = datetime.utcnow().date()
    # nombre, categoría, total, disp, mínima, precio, ubic, caducidad(días desde hoy o None), CEST
    data = [
        ("Tinta offset Cyan", "Material", 12, 9, 4, 18990, "Estante G1", 120, True),
        ("Tinta offset Magenta", "Material", 12, 8, 4, 18990, "Estante G1", 120, True),
        ("Tinta offset Amarillo", "Material", 10, 10, 4, 18990, "Estante G1", -15, True),   # vencida
        ("Tinta offset Negro", "Material", 15, 11, 5, 17990, "Estante G1", 200, True),
        ("Barniz UV brillante", "Material", 6, 4, 3, 25990, "Estante G2", -40, False),       # vencida
        ("Adhesivo para plastificado", "Material", 8, 5, 3, 12990, "Estante G2", 60, False),
        ("Papel couché 150g (resma)", "Fungible", 40, 32, 10, 8990, "Bodega G", None, False),
        ("Papel fotográfico A3 (caja)", "Fungible", 20, 14, 6, 15990, "Bodega G", None, True),
        ("Plancha CTP", "Componente", 30, 22, 8, 3990, "Estante G3", 90, False),
        ("Revelador de planchas (bidón)", "Material", 5, 2, 2, 45990, "Estante G2", 20, False),  # por vencer
        ("Cuchilla de guillotina (repuesto)", "Herramienta", 4, 4, 2, 32990, "Cajón G1", None, False),
        ("Cinta doble faz industrial", "Fungible", 25, 18, 8, 4990, "Cajón G1", None, False),
    ]
    out = []
    for i, (nombre, cat, tot, disp, mini, precio, ubic, cad, cest) in enumerate(data, 1):
        fcad = (hoy + timedelta(days=cad)) if cad is not None else None
        out.append(Item(
            codigo_barras=f"GDEMO-{i:04d}",
            nombre=nombre, categoria=cat, especialidad_id=esp_id,
            cantidad_total=tot, cantidad_disponible=disp, cantidad_minima=mini,
            precio_unitario=precio, ubicacion=ubic, estado="Bueno",
            fecha_caducidad=fcad, es_cest=cest,
            fecha_adquisicion=hoy - timedelta(days=random.randint(60, 400)),
        ))
    return out


def _registrobaja_demo(items):
    """Consumos/mermas de ejemplo repartidos en los últimos ~6 meses, para que
    el Panel Gerencial (consumo por mes, top insumos) se vea poblado."""
    ahora = datetime.utcnow()
    practicas = ['Montaje de circuito', 'Soldadura de componentes',
                 'Medición con instrumentos', 'Impresión / gráfica', 'Corte y armado']
    out = []
    for _ in range(24):
        it = random.choice(items)
        dias = random.randint(0, 175)
        out.append(RegistroBaja(
            item_id=it.id, item_nombre=it.nombre, especialidad_id=it.especialidad_id,
            cantidad=random.randint(1, 6), motivo='DEMO consumo',
            origen=random.choice(['merma_practica', 'merma_practica', 'baja_manual']),
            nombre_practica=random.choice(practicas), usuario_nombre='Demostración',
            fecha=ahora - timedelta(days=dias)))
    return out


def _estudiantes_demo(esp_id):
    nombres = [
        "Benjamín Soto", "Matías Rojas", "Vicente Muñoz", "Agustín Díaz",
        "Tomás Fuentes", "Joaquín Araya", "Cristóbal Vera", "Maximiliano Pino",
    ]
    out = []
    for i, n in enumerate(nombres, 1):
        out.append(Estudiante(
            rut_matricula=f"DEMO-AL{i:03d}",
            nombre=n, curso="3°A Demo", especialidad_id=esp_id,
            numero_lista=i, codigo_barras=f"ALDEMO{i:04d}",
            password_hash=generate_password_hash(f"DEMO-AL{i:03d}"),
            activo=True,
        ))
    return out


def _prestamos_demo(items, estudiantes):
    practicas = ["Montaje de circuito", "Mantención de equipos",
                 "Cableado estructurado", "Soldadura de componentes",
                 "Medición con instrumentos"]
    encargados = ["Pañolero Demostración"]
    out = []
    ahora = datetime.utcnow()
    for k in range(18):
        it = random.choice(items)
        es = random.choice(estudiantes)
        cant = random.randint(1, 3)
        devuelto = random.random() < 0.55
        fp = ahora - timedelta(days=random.randint(0, 28), hours=random.randint(0, 8))
        merma = random.choice([0, 0, 0, 1]) if devuelto else 0
        out.append(Prestamo(
            item_id=it.id, estudiante_id=es.id, cantidad=cant,
            cantidad_solicitada=cant, cantidad_mermada=merma,
            nombre_practica=random.choice(practicas),
            encargado=random.choice(encargados),
            profesor_nombre="Prof. Demostración",
            estado="Devuelto" if devuelto else "Pendiente",
            fecha_prestamo=fp,
            fecha_devolucion=(fp + timedelta(hours=random.randint(1, 6))) if devuelto else None,
        ))
    return out


def main():
    reset = "--reset" in sys.argv
    with app.app_context():
        # 1) Área demo
        esp = Especialidad.query.filter_by(nombre=DEMO_ESP).first()
        if not esp:
            esp = Especialidad(nombre=DEMO_ESP, color="#9333EA",
                               descripcion="Área de demostración para presentaciones",
                               tipo_area="PANOL_TP")
            db.session.add(esp)
            db.session.commit()
            print(f"[OK] Área '{DEMO_ESP}' creada (id={esp.id})")
        else:
            print(f"[=] Área '{DEMO_ESP}' ya existe (id={esp.id})")

        # 2) Usuario pañolero demo (entra directo, sin cambio de clave)
        u = Usuario.query.filter_by(username=DEMO_USER).first()
        if not u:
            u = Usuario(nombre="Pañolero Demostración", username=DEMO_USER,
                        password_hash=generate_password_hash(DEMO_PASS),
                        rol="Pañolero", email="demostracion@colegio.local",
                        especialidad_id=esp.id, must_change_password=False, activo=True)
            db.session.add(u)
            print(f"[OK] Usuario pañolero '{DEMO_USER}' creado  (clave: {DEMO_PASS})")
        else:
            u.password_hash = generate_password_hash(DEMO_PASS)
            u.must_change_password = False
            u.especialidad_id = esp.id
            u.activo = True
            print(f"[=] Usuario '{DEMO_USER}' actualizado (clave: {DEMO_PASS})")
        db.session.commit()

        # Reset opcional: borra SOLO datos del área demo
        if reset:
            ids_items = [i.id for i in Item.query.filter_by(especialidad_id=esp.id)]
            ids_est = [e.id for e in Estudiante.query.filter_by(especialidad_id=esp.id)]
            if ids_items:
                Prestamo.query.filter(Prestamo.item_id.in_(ids_items)).delete(synchronize_session=False)
            Item.query.filter_by(especialidad_id=esp.id).delete(synchronize_session=False)
            Estudiante.query.filter_by(especialidad_id=esp.id).delete(synchronize_session=False)
            db.session.commit()
            print(f"[OK] --reset: datos del área demo borrados ({len(ids_items)} ítems, {len(ids_est)} estudiantes)")

        # 3) Inventario (solo si el área tiene pocos ítems)
        if Item.query.filter_by(especialidad_id=esp.id).count() < 5:
            items = _items_demo(esp.id)
            db.session.add_all(items)
            db.session.commit()
            print(f"[OK] {len(items)} ítems de inventario creados")
        else:
            items = Item.query.filter_by(especialidad_id=esp.id).all()
            print(f"[=] El área ya tiene {len(items)} ítems (sin cambios; usa --reset para regenerar)")

        # 4) Estudiantes
        if Estudiante.query.filter_by(especialidad_id=esp.id).count() < 3:
            estudiantes = _estudiantes_demo(esp.id)
            db.session.add_all(estudiantes)
            db.session.commit()
            print(f"[OK] {len(estudiantes)} estudiantes de ejemplo creados")
        else:
            estudiantes = Estudiante.query.filter_by(especialidad_id=esp.id).all()
            print(f"[=] El área ya tiene {len(estudiantes)} estudiantes (sin cambios)")

        # 5) Préstamos (solo si no hay)
        ids_items = [i.id for i in items]
        tiene_prest = Prestamo.query.filter(Prestamo.item_id.in_(ids_items)).count() if ids_items else 0
        if items and estudiantes and tiene_prest == 0:
            prestamos = _prestamos_demo(items, estudiantes)
            db.session.add_all(prestamos)
            db.session.commit()
            pend = sum(1 for p in prestamos if p.estado == 'Pendiente')
            print(f"[OK] {len(prestamos)} préstamos creados ({pend} pendientes / {len(prestamos)-pend} devueltos)")
        else:
            print(f"[=] Ya existen préstamos en el área ({tiene_prest}); sin cambios")

        # ============ DEMO 2: vista del área GRÁFICA (caducidad + CEST) ============
        graf = Especialidad.query.filter_by(nombre='Gráfica').first()
        n_graf = 0
        if graf:
            gu = Usuario.query.filter_by(username=DEMO_G_USER).first()
            if not gu:
                gu = Usuario(nombre="Demostración Gráfica", username=DEMO_G_USER,
                             password_hash=generate_password_hash(DEMO_G_PASS),
                             rol="Pañolero", email="demo.grafica@colegio.local",
                             especialidad_id=graf.id, must_change_password=False, activo=True)
                db.session.add(gu)
                print(f"[OK] Usuario Gráfica demo '{DEMO_G_USER}' creado (clave: {DEMO_G_PASS})")
            else:
                gu.password_hash = generate_password_hash(DEMO_G_PASS)
                gu.must_change_password = False
                gu.especialidad_id = graf.id
                gu.activo = True
                print(f"[=] Usuario '{DEMO_G_USER}' actualizado (clave: {DEMO_G_PASS})")
            db.session.commit()
            # Solo ítems demo (GDEMO-*): no toca el inventario real de Gráfica
            existentes_g = Item.query.filter(
                Item.especialidad_id == graf.id,
                Item.codigo_barras.like('GDEMO-%')).count()
            if reset and existentes_g:
                Item.query.filter(Item.especialidad_id == graf.id,
                                  Item.codigo_barras.like('GDEMO-%')).delete(synchronize_session=False)
                db.session.commit()
                existentes_g = 0
            if existentes_g == 0:
                gi = _items_grafica(graf.id)
                db.session.add_all(gi)
                db.session.commit()
                n_graf = len(gi)
                print(f"[OK] {n_graf} ítems de ejemplo de Gráfica creados (con caducidad y CEST)")
            else:
                n_graf = existentes_g
                print(f"[=] Gráfica ya tiene {existentes_g} ítems demo (usa --reset para regenerar)")
        else:
            print("[WARN] No existe el área 'Gráfica'; se omitió el demo gráfico.")

        # ============ DEMO 3: cuenta ADMIN (ve todo + Panel Gerencial) ============
        au = Usuario.query.filter_by(username=DEMO_ADMIN_USER).first()
        if not au:
            au = Usuario(nombre="Administrador Demo", username=DEMO_ADMIN_USER,
                         password_hash=generate_password_hash(DEMO_ADMIN_PASS),
                         rol="Admin", email="demo.admin@colegio.local",
                         especialidad_id=None, must_change_password=False, activo=True)
            db.session.add(au)
            print(f"[OK] Cuenta ADMIN demo '{DEMO_ADMIN_USER}' creada (clave: {DEMO_ADMIN_PASS})")
        else:
            au.password_hash = generate_password_hash(DEMO_ADMIN_PASS)
            au.must_change_password = False
            au.rol = "Admin"
            au.activo = True
            print(f"[=] Cuenta ADMIN demo '{DEMO_ADMIN_USER}' actualizada (clave: {DEMO_ADMIN_PASS})")
        db.session.commit()

        # Consumos/mermas de ejemplo para los gráficos del panel gerencial
        pool = Item.query.filter(
            (Item.especialidad_id == esp.id) |
            (Item.codigo_barras.like('GDEMO-%'))).all()
        ya_hay = RegistroBaja.query.filter_by(motivo='DEMO consumo').count()
        if reset and ya_hay:
            RegistroBaja.query.filter_by(motivo='DEMO consumo').delete(synchronize_session=False)
            db.session.commit()
            ya_hay = 0
        if pool and ya_hay == 0:
            regs = _registrobaja_demo(pool)
            db.session.add_all(regs)
            db.session.commit()
            print(f"[OK] {len(regs)} consumos/mermas de ejemplo creados (para el Panel Gerencial)")
        else:
            print(f"[=] Ya hay {ya_hay} consumos demo (usa --reset para regenerar)")

        print("-" * 60)
        print("ENTORNO DE DEMOSTRACIÓN LISTO")
        print(f"  Demo ADMIN:          usuario '{DEMO_ADMIN_USER}'  /  clave '{DEMO_ADMIN_PASS}'  -> ve todo + Panel Gerencial")
        print(f"  Demo 1 (pañol TP):   usuario 'demostracion'  /  clave 'demo123'  -> área {DEMO_ESP}")
        print(f"  Demo 2 (Gráfica):    usuario '{DEMO_G_USER}'  /  clave '{DEMO_G_PASS}'  -> área Gráfica")
        print(f"  Ítems demo TP: {Item.query.filter_by(especialidad_id=esp.id).count()}  |  Ítems demo Gráfica: {n_graf}")
        print("-" * 60)


if __name__ == "__main__":
    main()
