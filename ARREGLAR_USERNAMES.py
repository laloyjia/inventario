#!/usr/bin/env python
"""
Script para arreglar los usernames de pañoleros (sin tildes)
"""
import unicodedata

def remover_tildes(texto):
    """Remueve tildes y acentos de un texto"""
    return ''.join(
        c for c in unicodedata.normalize('NFD', texto)
        if unicodedata.category(c) != 'Mn'
    )

from app import app, db, Usuario, Especialidad

with app.app_context():
    # Obtener todos los pañoleros
    pañoleros = Usuario.query.filter_by(rol='Pañolero').all()

    print("🔧 Normalizando usernames de pañoleros...\n")

    for pañolero in pañoleros:
        especialidad = pañolero.especialidad_asignada.nombre
        nuevo_username = f"pañolero_{remover_tildes(especialidad.lower().replace(' ', '_'))}"

        if pañolero.username != nuevo_username:
            print(f"  {pañolero.username} → {nuevo_username}")
            pañolero.username = nuevo_username

    db.session.commit()

    print("\n✅ Usernames normalizados")
    print("\n📌 NUEVOS USERNAMES:")

    pañoleros = Usuario.query.filter_by(rol='Pañolero').all()
    for pañolero in pañoleros:
        print(f"  • {pañolero.username} (Especialidad: {pañolero.especialidad_asignada.nombre})")
