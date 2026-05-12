#!/usr/bin/env python
"""
Script para resetear la BD y crear usuarios de prueba
"""

import os
import sqlite3
from werkzeug.security import generate_password_hash

# Ruta de la BD
db_path = os.path.join(os.path.dirname(__file__), 'instance', 'inventario.db')

print("🔴 Eliminando BD anterior...")
if os.path.exists(db_path):
    os.remove(db_path)
    print(f"✅ BD eliminada: {db_path}")

print("\n📝 Creando nueva BD con usuarios de prueba...")

# Importar la aplicación DESPUÉS de eliminar la BD
from app import app, db, Usuario, Especialidad, Estudiante

# Crear contexto de aplicación
with app.app_context():
    # Crear todas las tablas
    db.create_all()

    # Crear especialidades
    especialidades_lista = [
        {'nombre': 'Electrónica', 'color': '#FF6B6B'},
        {'nombre': 'Mecánica Automotriz', 'color': '#4ECDC4'},
        {'nombre': 'Mecánica Industrial', 'color': '#45B7D1'},
        {'nombre': 'Electricidad', 'color': '#FFA07A'},
        {'nombre': 'Gráfica', 'color': '#98D8C8'},
    ]

    for esp in especialidades_lista:
        if not Especialidad.query.filter_by(nombre=esp['nombre']).first():
            nueva_esp = Especialidad(
                nombre=esp['nombre'],
                descripcion=f"Especialidad de {esp['nombre']}",
                color=esp['color'],
                activa=True
            )
            db.session.add(nueva_esp)

    db.session.commit()
    print("✅ Especialidades creadas")

    # Crear admin
    if not Usuario.query.filter_by(username='admin_central').first():
        admin = Usuario(
            nombre='Administrador Central',
            username='admin_central',
            email='admin@colegio.local',
            password_hash=generate_password_hash('admin123'),
            rol='Admin',
            especialidad_id=None,
            activo=True
        )
        db.session.add(admin)
        print("✅ Admin creado: admin_central / admin123")

    db.session.commit()

    # Crear pañoleros
    especialidades = Especialidad.query.all()
    for esp in especialidades:
        username = f'pañolero_{esp.nombre.lower().replace(" ", "_")}'
        if not Usuario.query.filter_by(username=username).first():
            pañolero = Usuario(
                nombre=f'Pañolero {esp.nombre}',
                username=username,
                email=f'pañolero.{esp.nombre.lower().replace(" ", ".")}@colegio.local',
                password_hash=generate_password_hash('pañol123'),
                rol='Pañolero',
                especialidad_id=esp.id,
                activo=True
            )
            db.session.add(pañolero)
            print(f"✅ Pañolero creado: {username} / pañol123")

    db.session.commit()

    print("\n" + "="*60)
    print("✅ BD REINICIADA CON ÉXITO")
    print("="*60)
    print("\n📌 CREDENCIALES DE PRUEBA:")
    print("  Admin:")
    print("    Usuario: admin_central")
    print("    Contraseña: admin123")
    print("\n  Pañoleros:")
    print("    Usuario: pañolero_electrónica (o pañolero_electronica)")
    print("    Usuario: pañolero_mecánica_automotriz")
    print("    Usuario: pañolero_mecánica_industrial")
    print("    Usuario: pañolero_electricidad")
    print("    Usuario: pañolero_gráfica")
    print("    Contraseña: pañol123")
    print("\n" + "="*60)
