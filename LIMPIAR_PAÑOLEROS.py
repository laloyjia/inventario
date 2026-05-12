#!/usr/bin/env python
"""
Script para limpiar pañoleros antiguos/duplicados
"""
from app import app, db, Usuario

with app.app_context():
    # Eliminar todos los pañoleros
    pañoleros_viejos = Usuario.query.filter_by(rol='Pañolero').all()

    print(f"🗑️  Eliminando {len(pañoleros_viejos)} pañoleros antiguos...")

    for pañolero in pañoleros_viejos:
        print(f"   - Eliminando: {pañolero.username} ({pañolero.email})")
        db.session.delete(pañolero)

    db.session.commit()

    print("\n✅ Pañoleros antiguos eliminados")
    print("\nAhora ejecuta: python run.py")
