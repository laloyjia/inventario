from flask import Flask, request, session, redirect, url_for, flash, render_template, send_file, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from datetime import datetime, timedelta
import json
import pandas as pd
import io
import os

app = Flask(__name__)

# ============================================================
# CONFIGURACIÓN — soporta tres modos de despliegue:
#   1. Local desarrollo:   SQLite en instance/inventario.db
#   2. Nodo en red local:  SQLite local + sincronización a un admin
#   3. Cloud (Render/Railway/etc): PostgreSQL via DATABASE_URL
# ============================================================

app.secret_key = os.getenv('PANOL_SECRET_KEY', 'llave_super_secreta_enterprise_v5_multiespecialidad')

# Carpeta instance para SQLite local
db_folder = os.path.join(os.path.dirname(__file__), 'instance')
os.makedirs(db_folder, exist_ok=True)

# Identificación del nodo
NODO_ID = os.getenv('PANOL_NODO', 'local')
PANOL_ADMIN_URL = os.getenv('PANOL_ADMIN_URL', '').rstrip('/')
ES_ADMIN_CENTRAL = (PANOL_ADMIN_URL == '')
PANOL_SYNC_TOKEN = os.getenv('PANOL_SYNC_TOKEN', 'CAMBIAR_ESTE_TOKEN_PRODUCCION')

# === Conexión a la base de datos ===
DATABASE_URL = os.getenv('DATABASE_URL', '').strip()
if DATABASE_URL:
    # Render entrega URLs como "postgres://..." pero SQLAlchemy 2.x exige "postgresql://"
    if DATABASE_URL.startswith('postgres://'):
        DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL
    USANDO_POSTGRES = DATABASE_URL.startswith('postgresql')
    print(f"[DB] Usando {'PostgreSQL' if USANDO_POSTGRES else 'externa'}: {DATABASE_URL.split('@')[-1] if '@' in DATABASE_URL else DATABASE_URL}")
else:
    # Fallback: SQLite local
    DB_PATH = os.getenv('PANOL_DB_PATH', os.path.join(db_folder, 'inventario.db'))
    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{DB_PATH}'
    USANDO_POSTGRES = False
    print(f"[DB] Usando SQLite local: {DB_PATH}")

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_pre_ping': True,        # detecta conexiones muertas (importante en cloud)
    'pool_recycle': 280,          # recicla conexiones cada ~5 min
}

# === Seguridad de cookies (importante en cloud) ===
EN_PRODUCCION = os.getenv('FLASK_ENV', '').lower() == 'production' or USANDO_POSTGRES
app.config['SESSION_COOKIE_HTTPONLY'] = True       # cookies no accesibles desde JS
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'      # mitiga CSRF cross-site
app.config['SESSION_COOKIE_SECURE'] = EN_PRODUCCION  # solo HTTPS en producción
app.config['PERMANENT_SESSION_LIFETIME'] = 60 * 60 * 8  # 8 horas

# === HTTPS forzado + headers de seguridad (Talisman, opcional) ===
if EN_PRODUCCION and os.getenv('FORCE_HTTPS', 'true').lower() != 'false':
    try:
        from flask_talisman import Talisman
        Talisman(app,
                 force_https=True,
                 strict_transport_security=True,
                 session_cookie_secure=True,
                 content_security_policy={
                     'default-src': ["'self'"],
                     'script-src': ["'self'", "'unsafe-inline'",
                                    'cdn.jsdelivr.net', 'cdnjs.cloudflare.com'],
                     'style-src': ["'self'", "'unsafe-inline'",
                                   'cdnjs.cloudflare.com', 'fonts.googleapis.com'],
                     'font-src': ["'self'", 'cdnjs.cloudflare.com', 'fonts.gstatic.com'],
                     'img-src': ["'self'", 'data:', 'https:'],
                 })
        print("[SEC] Talisman activo: HTTPS forzado + CSP")
    except ImportError:
        print("[SEC] Flask-Talisman no instalado, saltando endurecimiento HTTPS")

# === Rate limiting en login (anti brute-force, opcional) ===
try:
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address
    limiter = Limiter(get_remote_address, app=app,
                      default_limits=["500 per hour"],
                      storage_uri="memory://")
    print("[SEC] Rate limiter activo")
except ImportError:
    limiter = None
    print("[SEC] Flask-Limiter no instalado, saltando rate limiting")

db = SQLAlchemy(app)


# ========== FILTROS JINJA ==========

@app.template_filter('clp')
def format_clp(value):
    """Formatea un número como pesos chilenos: 12500 → '$ 12.500'.
    Acepta None, '' o no numérico y devuelve '$ 0'."""
    try:
        n = float(value or 0)
    except (TypeError, ValueError):
        n = 0
    # Separador de miles con punto, sin decimales (CLP no usa centavos)
    entero = int(round(n))
    return "$ " + f"{entero:,}".replace(",", ".")


# ========== TABLAS DE BASE DE DATOS (PanolERP fase 2) ==========

class Especialidad(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), unique=True, nullable=False)
    descripcion = db.Column(db.Text)
    color = db.Column(db.String(7), default="#2563eb")
    activa = db.Column(db.Boolean, default=True)
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)
    # Tipo de área: PANOL_TP, BIBLIOTECA, DEPORTIVO, INFORMATICA, GENERAL
    # Define qué campos del Item se muestran/usan en el formulario y la lista.
    tipo_area = db.Column(db.String(20), default='GENERAL', nullable=False,
                          server_default='GENERAL')
    usuarios = db.relationship('Usuario', backref='especialidad_asignada', lazy=True)
    items = db.relationship('Item', backref='especialidad', lazy=True)

class Usuario(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    username = db.Column(db.String(50), unique=True, nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=True)
    password_hash = db.Column(db.String(200), nullable=False)
    rol = db.Column(db.String(50), default='Pañolero')
    especialidad_id = db.Column(db.Integer, db.ForeignKey('especialidad.id'), nullable=True)
    activo = db.Column(db.Boolean, default=True)
    ultimo_login = db.Column(db.DateTime, nullable=True)
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)
    # Hardening seguridad (fase go-live)
    failed_attempts = db.Column(db.Integer, default=0, nullable=False, server_default='0')
    locked_until = db.Column(db.DateTime, nullable=True)
    must_change_password = db.Column(db.Boolean, default=False, nullable=False, server_default='false')
    alertas_stock = db.relationship('AlertaStock', backref='usuario', lazy=True)

class Curso(db.Model):
    """Curso/lectivo dentro de una especialidad. Ej: '3°A Electrónica'."""
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)  # ej: "3°A Electrónica" o "4°B"
    nivel = db.Column(db.String(20), nullable=True)     # ej: "3° Medio"
    letra = db.Column(db.String(5), nullable=True)      # ej: "A", "B"
    anio = db.Column(db.Integer, nullable=True)         # año lectivo
    especialidad_id = db.Column(db.Integer, db.ForeignKey('especialidad.id'), nullable=False)
    activo = db.Column(db.Boolean, default=True, nullable=False, server_default='1')
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)
    especialidad = db.relationship('Especialidad', backref='cursos', lazy=True)

    __table_args__ = (
        db.UniqueConstraint('nombre', 'especialidad_id', name='uq_curso_nombre_esp'),
    )

    @property
    def total_alumnos(self):
        return Estudiante.query.filter_by(curso_id=self.id, activo=True).count()


class Estudiante(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    rut_matricula = db.Column(db.String(50), unique=True, nullable=False)
    nombre = db.Column(db.String(100), nullable=False)
    curso = db.Column(db.String(50))  # legado: string libre (se mantiene por compatibilidad)
    curso_id = db.Column(db.Integer, db.ForeignKey('curso.id'), nullable=True)  # nuevo
    especialidad_id = db.Column(db.Integer, db.ForeignKey('especialidad.id'), nullable=False)
    email = db.Column(db.String(120), nullable=True)
    password_hash = db.Column(db.String(200), nullable=False)
    activo = db.Column(db.Boolean, default=True)
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)
    especialidad = db.relationship('Especialidad', backref='estudiantes', lazy=True)
    curso_rel = db.relationship('Curso', backref='alumnos', lazy=True)
    @property
    def tiene_deudas(self):
        return Prestamo.query.filter_by(estudiante_id=self.id, estado='Pendiente').count() > 0

    @property
    def curso_display(self):
        """Nombre legible del curso: usa el del FK si existe, si no el string legado."""
        if self.curso_rel:
            return self.curso_rel.nombre
        return self.curso or '—'


class Item(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    codigo_barras = db.Column(db.String(100), unique=True, nullable=True)
    nombre = db.Column(db.String(100), nullable=False)
    descripcion = db.Column(db.Text, nullable=True)
    especialidad_id = db.Column(db.Integer, db.ForeignKey('especialidad.id'), nullable=False)
    categoria = db.Column(db.String(50))
    cantidad_total = db.Column(db.Integer, default=0)
    cantidad_disponible = db.Column(db.Integer, default=0)
    cantidad_mermada = db.Column(db.Integer, default=0)
    cantidad_minima = db.Column(db.Integer, default=5)
    imagen_url = db.Column(db.String(500), default="")
    ubicacion = db.Column(db.String(200), default="Sin especificar")
    precio_unitario = db.Column(db.Float, default=0.0)
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)
    fecha_ultima_modificacion = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    # Campos específicos Biblioteca (nullable, solo se llenan en items bibliográficos)
    autor = db.Column(db.String(200), nullable=True)
    isbn = db.Column(db.String(50), nullable=True, index=True)
    editorial = db.Column(db.String(200), nullable=True)
    anio_publicacion = db.Column(db.Integer, nullable=True)
    # Campos específicos INFORMATICA / DEPORTIVO
    marca = db.Column(db.String(100), nullable=True)
    modelo = db.Column(db.String(100), nullable=True)
    numero_serie = db.Column(db.String(100), nullable=True, index=True)
    estado = db.Column(db.String(50), nullable=True)  # Nuevo/Bueno/Regular/Reposición
    # Fecha de adquisición (todos los tipos, opcional)
    fecha_adquisicion = db.Column(db.Date, nullable=True)
    # Cálculo de desgaste por uso (INFORMATICA, PANOL_TP, DEPORTIVO)
    max_usos = db.Column(db.Integer, nullable=True)  # tope total de préstamos antes de reponer
    usos_actuales = db.Column(db.Integer, default=0, nullable=False,
                              server_default='0')
    # Desgaste/depreciación acumulada expresada en pesos chilenos (CLP)
    desgaste = db.Column(db.Float, default=0.0, nullable=False, server_default='0')

    @property
    def porcentaje_desgaste(self):
        """Devuelve % de desgaste basado en usos, o None si no aplica."""
        if self.max_usos and self.max_usos > 0:
            return min(100, int((self.usos_actuales or 0) * 100 / self.max_usos))
        return None

    @property
    def costo_total(self):
        """Costo total estimado del stock = costo unitario × cantidad total."""
        return (self.precio_unitario or 0.0) * (self.cantidad_total or 0)

class Prestamo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(db.Integer, db.ForeignKey('item.id'), nullable=False)
    estudiante_id = db.Column(db.Integer, db.ForeignKey('estudiante.id'), nullable=False)
    profesor_id = db.Column(db.Integer, db.ForeignKey('usuario.id'), nullable=True)
    # Pañolero del día (estudiante designado que entregó el ítem). Opcional.
    panolero_dia_id = db.Column(db.Integer, db.ForeignKey('estudiante.id'), nullable=True)
    encargado = db.Column(db.String(100))
    cantidad = db.Column(db.Integer)
    cantidad_solicitada = db.Column(db.Integer, default=0)
    cantidad_mermada = db.Column(db.Integer, default=0)
    nombre_practica = db.Column(db.String(200), nullable=True)
    fecha_prestamo = db.Column(db.DateTime, default=datetime.utcnow)
    fecha_devolucion = db.Column(db.DateTime, nullable=True)
    estado = db.Column(db.String(20), default='Pendiente')
    item = db.relationship('Item', backref='prestamos_historial', lazy=True)
    # Como hay 2 FKs a estudiante (estudiante_id y panolero_dia_id), hay que
    # especificar explícitamente foreign_keys para evitar AmbiguousForeignKeysError.
    estudiante = db.relationship('Estudiante', backref='historial_solicitudes',
                                 foreign_keys=[estudiante_id], lazy=True)
    panolero_dia = db.relationship('Estudiante', backref='prestamos_atendidos',
                                   foreign_keys=[panolero_dia_id], lazy=True)
    profesor = db.relationship('Usuario', backref='prestamos_supervisados', lazy=True)
    # Campos específicos Biblioteca / préstamos con plazo
    fecha_devolucion_esperada = db.Column(db.DateTime, nullable=True)
    multa = db.Column(db.Float, default=0.0)

    @property
    def dias_atraso(self):
        if not self.fecha_devolucion_esperada or self.estado == 'Devuelto':
            return 0
        diff = (datetime.utcnow() - self.fecha_devolucion_esperada).days
        return max(0, diff)

class Auditoria(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuario.id'), nullable=True)
    especialidad_id = db.Column(db.Integer, db.ForeignKey('especialidad.id'), nullable=False)
    accion = db.Column(db.String(100))
    tabla = db.Column(db.String(50))
    registro_id = db.Column(db.Integer)
    valores_anteriores = db.Column(db.Text)
    valores_nuevos = db.Column(db.Text)
    fecha = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    ip_address = db.Column(db.String(50))
    usuario = db.relationship('Usuario', backref='auditorias', lazy=True)
    especialidad = db.relationship('Especialidad', backref='auditorias', lazy=True)

class AlertaStock(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(db.Integer, db.ForeignKey('item.id'), nullable=False)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuario.id'), nullable=False)
    cantidad_minima = db.Column(db.Integer, default=5)
    cantidad_actual = db.Column(db.Integer)
    activa = db.Column(db.Boolean, default=True)
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)
    fecha_ultima_alerta = db.Column(db.DateTime, nullable=True)
    item = db.relationship('Item', backref='alertas', lazy=True)

class OrdenTrabajo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    titulo = db.Column(db.String(200), nullable=False)
    descripcion = db.Column(db.Text, nullable=True)
    especialidad_id = db.Column(db.Integer, db.ForeignKey('especialidad.id'), nullable=False)
    profesional_cargo = db.Column(db.String(100), nullable=False)
    alumnos_cargo = db.Column(db.String(200), nullable=True)
    herramientas_utilizadas = db.Column(db.Text, nullable=True)
    repuestos_utilizados = db.Column(db.Text, nullable=True)
    profesor_id = db.Column(db.Integer, db.ForeignKey('usuario.id'), nullable=False)
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)
    estado = db.Column(db.String(50), default='Pendiente')
    especialidad = db.relationship('Especialidad', backref='ordenes_trabajo', lazy=True)
    profesor = db.relationship('Usuario', backref='ordenes_trabajo', lazy=True)

class ConfiguracionSistema(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    clave = db.Column(db.String(100), unique=True, nullable=False)
    valor = db.Column(db.Text)
    tipo = db.Column(db.String(20))
    descripcion = db.Column(db.Text)
    fecha_actualizacion = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class PrestamoExterno(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(db.Integer, db.ForeignKey('item.id'), nullable=False)
    especialidad_id = db.Column(db.Integer, db.ForeignKey('especialidad.id'), nullable=False)
    cantidad = db.Column(db.Integer, nullable=False, default=1)
    es_alumno = db.Column(db.Boolean, default=False)
    persona_retira = db.Column(db.String(200), nullable=False)
    profesor_cargo = db.Column(db.String(200), nullable=True)
    especialidad_destino = db.Column(db.String(100), nullable=True)
    encargado = db.Column(db.String(100))
    fecha_prestamo = db.Column(db.DateTime, default=datetime.utcnow)
    fecha_devolucion = db.Column(db.DateTime, nullable=True)
    estado = db.Column(db.String(20), default='Activo')
    # 'prestamo' (se devuelve) o 'consumo' (descuenta del total, sin devolución; oficina)
    tipo_movimiento = db.Column(db.String(20), default='prestamo')
    item = db.relationship('Item', backref='prestamos_externos', lazy=True)
    especialidad = db.relationship('Especialidad', backref='prestamos_externos', lazy=True)


# ========================================================================
# PAÑOLEROS DEL DÍA — estudiantes designados que pueden entregar insumos
# ========================================================================
MAX_PANOLEROS_DIA = 6   # tope de pañoleros activos por especialidad


class PanoleroDesignado(db.Model):
    """Designación de un estudiante como pañolero del día para una especialidad.
    Persisten hasta que el encargado del pañol los reemplaza o limpia.
    Solo cuentan los registros con activo=True (máx. 6 por especialidad)."""
    __tablename__ = 'panolero_designado'
    id = db.Column(db.Integer, primary_key=True)
    estudiante_id = db.Column(db.Integer, db.ForeignKey('estudiante.id'),
                              nullable=False, index=True)
    especialidad_id = db.Column(db.Integer, db.ForeignKey('especialidad.id'),
                                nullable=False, index=True)
    designado_por_id = db.Column(db.Integer, db.ForeignKey('usuario.id'),
                                 nullable=True)
    fecha_designacion = db.Column(db.DateTime, default=datetime.utcnow,
                                  nullable=False)
    fecha_baja = db.Column(db.DateTime, nullable=True)
    activo = db.Column(db.Boolean, default=True, nullable=False,
                       server_default='true', index=True)
    estudiante = db.relationship('Estudiante', backref='designaciones_panolero', lazy=True)
    especialidad = db.relationship('Especialidad', backref='panoleros_designados', lazy=True)
    designado_por = db.relationship('Usuario', foreign_keys=[designado_por_id], lazy=True)


# 11. SYNC LOG (registro de cambios para sincronización entre nodos y admin central)
class SyncLog(db.Model):
    __tablename__ = 'sync_log'
    id = db.Column(db.Integer, primary_key=True)
    nodo_origen = db.Column(db.String(80), nullable=False, index=True)   # quién originó el cambio
    tabla = db.Column(db.String(50), nullable=False)                      # ej. 'item', 'prestamo'
    registro_id_local = db.Column(db.Integer, nullable=False)             # id en la BD local del nodo
    accion = db.Column(db.String(20), nullable=False)                     # 'crear', 'actualizar', 'eliminar'
    payload = db.Column(db.Text)                                          # JSON con el snapshot del registro
    fecha = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    push_status = db.Column(db.String(20), default='pendiente')           # 'pendiente', 'enviado', 'error'
    push_intentos = db.Column(db.Integer, default=0)
    push_error = db.Column(db.Text, nullable=True)
    sync_uuid = db.Column(db.String(64), unique=True, index=True)         # idempotencia

# ========== INICIALIZACIÓN DE BD ==========

def crear_especialidades_por_defecto():
    """17 áreas: 5 TP (campus único) + 6 áreas en 2 sedes cada una (norte/sur)."""
    especialidades = [
        # === 5 especialidades TP (sede única) ===
        {'nombre': 'Electrónica', 'color': '#FF6B6B'},
        {'nombre': 'Mecánica Automotriz', 'color': '#4ECDC4'},
        {'nombre': 'Mecánica Industrial', 'color': '#45B7D1'},
        {'nombre': 'Electricidad', 'color': '#FFA07A'},
        {'nombre': 'Gráfica', 'color': '#98D8C8'},
        # === 6 áreas duplicadas por sede ===
        {'nombre': 'ACLE Sede Norte', 'color': '#A78BFA',
         'descripcion': 'Actividades Curriculares de Libre Elección — Sede Norte'},
        {'nombre': 'ACLE Sede Sur', 'color': '#7C3AED',
         'descripcion': 'Actividades Curriculares de Libre Elección — Sede Sur'},
        {'nombre': 'Biblioteca Sede Norte', 'color': '#10B981',
         'descripcion': 'Libros y material bibliográfico — Sede Norte'},
        {'nombre': 'Biblioteca Sede Sur', 'color': '#047857',
         'descripcion': 'Libros y material bibliográfico — Sede Sur'},
        {'nombre': 'Informática Sede Norte', 'color': '#3B82F6',
         'descripcion': 'Sala/equipos de informática — Sede Norte'},
        {'nombre': 'Informática Sede Sur', 'color': '#1E40AF',
         'descripcion': 'Sala/equipos de informática — Sede Sur'},
        {'nombre': 'Educación Física Sede Norte', 'color': '#F97316',
         'descripcion': 'Implementos deportivos — Sede Norte'},
        {'nombre': 'Educación Física Sede Sur', 'color': '#C2410C',
         'descripcion': 'Implementos deportivos — Sede Sur'},
        {'nombre': 'Salas de Clase Sede Norte', 'color': '#EC4899',
         'descripcion': 'Recursos de salas de clase — Sede Norte'},
        {'nombre': 'Salas de Clase Sede Sur', 'color': '#BE185D',
         'descripcion': 'Recursos de salas de clase — Sede Sur'},
        {'nombre': 'Oficina Sede Norte', 'color': '#F59E0B',
         'descripcion': 'Implementos administrativos — Sede Norte'},
        {'nombre': 'Oficina Sede Sur', 'color': '#B45309',
         'descripcion': 'Implementos administrativos — Sede Sur'},
    ]
    for esp_data in especialidades:
        if not Especialidad.query.filter_by(nombre=esp_data['nombre']).first():
            db.session.add(Especialidad(
                nombre=esp_data['nombre'],
                color=esp_data['color'],
                descripcion=esp_data.get('descripcion', '')
            ))
    db.session.commit()

def crear_admin_central():
    if not Usuario.query.filter_by(username='admin_central').first():
        db.session.add(Usuario(
            nombre="Administrador Central", username="admin_central",
            password_hash=generate_password_hash("admin123"),
            rol="Admin", email="admin@colegio.local", especialidad_id=None,
            must_change_password=True,  # forzado a cambiar en primer login
        ))
        db.session.commit()

def crear_pañoleros_por_especialidad():
    import unicodedata
    for esp in Especialidad.query.all():
        nombre_norm = ''.join(c for c in unicodedata.normalize('NFD', esp.nombre)
                              if unicodedata.category(c) != 'Mn').lower().replace(' ', '_')
        username = f"pañolero_{nombre_norm}"
        email = f"pañolero.{nombre_norm}@colegio.local"
        existe = Usuario.query.filter(
            (Usuario.username == username) | (Usuario.email == email) |
            ((Usuario.rol == 'Pañolero') & (Usuario.especialidad_id == esp.id))
        ).first()
        if not existe:
            db.session.add(Usuario(
                nombre=f"Pañolero {esp.nombre}", username=username,
                password_hash=generate_password_hash("pañol123"),
                rol="Pañolero", email=email, especialidad_id=esp.id,
                must_change_password=True,  # forzado a cambiar en primer login
            ))
    db.session.commit()

def _migrar_columnas_seguridad():
    """Añade columnas nuevas a usuario, especialidad e item si la BD ya existía.
    Idempotente — seguro de correr en cada arranque.
    """
    from sqlalchemy import inspect, text
    try:
        # 1) Asegurar que TODAS las tablas existan (curso, item, etc.). create_all es idempotente.
        db.create_all()

        insp = inspect(db.engine)
        tablas = set(insp.get_table_names())
        dialect = db.engine.dialect.name
        ts_type = 'TIMESTAMP' if dialect == 'postgresql' else 'DATETIME'
        date_type = 'DATE' if dialect == 'postgresql' else 'DATE'
        bool_default = 'FALSE' if dialect == 'postgresql' else '0'
        statements = []

        # === usuario: hardening de seguridad ===
        if 'usuario' in tablas:
            cols = {c['name'] for c in insp.get_columns('usuario')}
            if 'failed_attempts' not in cols:
                statements.append("ALTER TABLE usuario ADD COLUMN failed_attempts INTEGER NOT NULL DEFAULT 0")
            if 'locked_until' not in cols:
                statements.append(f"ALTER TABLE usuario ADD COLUMN locked_until {ts_type} NULL")
            if 'must_change_password' not in cols:
                statements.append(
                    f"ALTER TABLE usuario ADD COLUMN must_change_password BOOLEAN NOT NULL DEFAULT {bool_default}"
                )

        # === especialidad: tipo_area ===
        if 'especialidad' in tablas:
            cols = {c['name'] for c in insp.get_columns('especialidad')}
            if 'tipo_area' not in cols:
                statements.append(
                    "ALTER TABLE especialidad ADD COLUMN tipo_area VARCHAR(20) NOT NULL DEFAULT 'GENERAL'"
                )

        # === item: campos por tipo de área ===
        if 'item' in tablas:
            cols = {c['name'] for c in insp.get_columns('item')}
            if 'marca' not in cols:
                statements.append("ALTER TABLE item ADD COLUMN marca VARCHAR(100) NULL")
            if 'modelo' not in cols:
                statements.append("ALTER TABLE item ADD COLUMN modelo VARCHAR(100) NULL")
            if 'numero_serie' not in cols:
                statements.append("ALTER TABLE item ADD COLUMN numero_serie VARCHAR(100) NULL")
            if 'estado' not in cols:
                statements.append("ALTER TABLE item ADD COLUMN estado VARCHAR(50) NULL")
            if 'fecha_adquisicion' not in cols:
                statements.append(f"ALTER TABLE item ADD COLUMN fecha_adquisicion {date_type} NULL")
            if 'max_usos' not in cols:
                statements.append("ALTER TABLE item ADD COLUMN max_usos INTEGER NULL")
            if 'usos_actuales' not in cols:
                statements.append("ALTER TABLE item ADD COLUMN usos_actuales INTEGER NOT NULL DEFAULT 0")
            if 'desgaste' not in cols:
                statements.append("ALTER TABLE item ADD COLUMN desgaste FLOAT NOT NULL DEFAULT 0")

        # === prestamo: panolero_dia_id ===
        if 'prestamo' in tablas:
            cols = {c['name'] for c in insp.get_columns('prestamo')}
            if 'panolero_dia_id' not in cols:
                statements.append("ALTER TABLE prestamo ADD COLUMN panolero_dia_id INTEGER NULL")

        # === estudiante: curso_id (FK a curso) + email ===
        if 'estudiante' in tablas:
            cols = {c['name'] for c in insp.get_columns('estudiante')}
            if 'curso_id' not in cols:
                statements.append("ALTER TABLE estudiante ADD COLUMN curso_id INTEGER NULL")
            if 'email' not in cols:
                statements.append("ALTER TABLE estudiante ADD COLUMN email VARCHAR(120) NULL")

        if statements:
            with db.engine.begin() as conn:
                for s in statements:
                    conn.execute(text(s))
            print(f"[MIGRACION] Aplicadas {len(statements)} columnas nuevas")
    except Exception as e:
        print(f"[MIGRACION] Aviso: {e}")


# Mapeo de especialidad → tipo de área (se usa en seeders y en _asignar_tipo_area)
TIPO_AREA_POR_NOMBRE = {
    'Electrónica':                     'PANOL_TP',
    'Mecánica Automotriz':             'PANOL_TP',
    'Mecánica Industrial':             'PANOL_TP',
    'Electricidad':                    'PANOL_TP',
    'Gráfica':                         'PANOL_TP',
    'Biblioteca Sede Norte':           'BIBLIOTECA',
    'Biblioteca Sede Sur':             'BIBLIOTECA',
    'Educación Física Sede Norte':     'DEPORTIVO',
    'Educación Física Sede Sur':       'DEPORTIVO',
    'Informática Sede Norte':          'INFORMATICA',
    'Informática Sede Sur':            'INFORMATICA',
    'ACLE Sede Norte':                 'GENERAL',
    'ACLE Sede Sur':                   'GENERAL',
    'Salas de Clase Sede Norte':       'GENERAL',
    'Salas de Clase Sede Sur':         'GENERAL',
    'Oficina Sede Norte':              'GENERAL',
    'Oficina Sede Sur':                'GENERAL',
}


def _asignar_tipo_area():
    """Garantiza que cada especialidad tenga su tipo_area correcto. Idempotente."""
    cambios = 0
    for esp in Especialidad.query.all():
        tipo_esperado = TIPO_AREA_POR_NOMBRE.get(esp.nombre, 'GENERAL')
        if (esp.tipo_area or 'GENERAL') != tipo_esperado:
            esp.tipo_area = tipo_esperado
            cambios += 1
    if cambios:
        db.session.commit()
        print(f"[TIPO_AREA] {cambios} especialidades actualizadas")


def _flag_passwords_default():
    """Marca must_change_password=True en usuarios sembrados que aún tienen las
    contraseñas por defecto (admin123 / pañol123). Imprescindible para go-live cloud
    cuando la BD ya tenía esos usuarios creados antes de añadir el flag.
    """
    cambios = 0
    for u in Usuario.query.all():
        if u.must_change_password:
            continue
        # Admin con password default
        if u.username == 'admin_central' and check_password_hash(u.password_hash, 'admin123'):
            u.must_change_password = True
            cambios += 1
        # Pañoleros con password default
        elif u.rol == 'Pañolero' and check_password_hash(u.password_hash, 'pañol123'):
            u.must_change_password = True
            cambios += 1
    if cambios:
        db.session.commit()
        print(f"[SEC] {cambios} usuarios marcados para cambio obligatorio de contraseña")


with app.app_context():
    db.create_all()
    _migrar_columnas_seguridad()
    crear_especialidades_por_defecto()
    _asignar_tipo_area()
    crear_admin_central()
    crear_pañoleros_por_especialidad()
    _flag_passwords_default()
    print("✅ BD inicializada correctamente")
    print(f"✅ {Especialidad.query.count()} especialidades disponibles")
    print("✅ Admin central creado")
    print(f"✅ {Usuario.query.filter_by(rol='Pañolero').count()} pañoleros creados")


# ========================================================================
# SYNC: helpers para registrar cambios locales y consultarlos
# ========================================================================

import uuid as _uuid_mod

# Tablas que se sincronizan al admin central (la auditoría se conserva en cada nodo + admin)
TABLAS_SYNC = ('item', 'estudiante', 'prestamo', 'prestamo_externo',
               'orden_trabajo', 'usuario')


def _serializar_registro(obj):
    """Convierte un modelo SQLAlchemy a dict JSON-friendly. Solo columnas básicas."""
    if obj is None:
        return None
    out = {}
    for col in obj.__table__.columns:
        val = getattr(obj, col.name, None)
        if isinstance(val, datetime):
            out[col.name] = val.isoformat()
        else:
            out[col.name] = val
    return out


def registrar_cambio_sync(tabla, registro_id_local, accion, obj=None):
    """Registra un cambio local en SyncLog, listo para ser empujado al admin central.

    - Si este PC ES el admin central, no se registra (no necesita empujarse a sí mismo).
    - Si es un nodo cliente, se persiste un SyncLog con payload=snapshot del objeto.
    """
    if ES_ADMIN_CENTRAL:
        return  # el admin no se sincroniza consigo mismo
    if tabla not in TABLAS_SYNC:
        return
    payload = json.dumps(_serializar_registro(obj)) if obj else None
    entry = SyncLog(
        nodo_origen=NODO_ID,
        tabla=tabla,
        registro_id_local=registro_id_local,
        accion=accion,
        payload=payload,
        push_status='pendiente',
        sync_uuid=_uuid_mod.uuid4().hex,
    )
    db.session.add(entry)
    db.session.commit()


def _ack_sync_uuids(uuids_ok, uuids_error_map):
    """Marca SyncLogs como enviados/error después de un push. Solo en el nodo cliente."""
    if not uuids_ok and not uuids_error_map:
        return
    for uid in uuids_ok:
        log = SyncLog.query.filter_by(sync_uuid=uid).first()
        if log:
            log.push_status = 'enviado'
            log.push_intentos = (log.push_intentos or 0) + 1
            log.push_error = None
    for uid, err in uuids_error_map.items():
        log = SyncLog.query.filter_by(sync_uuid=uid).first()
        if log:
            log.push_status = 'error'
            log.push_intentos = (log.push_intentos or 0) + 1
            log.push_error = (err or '')[:500]
    db.session.commit()

# ========== DECORADORES ==========

def registrar_auditoria(accion, tabla, registro_id, valores_anteriores=None, valores_nuevos=None, especialidad_id=None):
    usuario_id = session.get('usuario_id')
    if especialidad_id is None and 'usuario_especialidad_id' in session:
        especialidad_id = session['usuario_especialidad_id']
    db.session.add(Auditoria(
        usuario_id=usuario_id, especialidad_id=especialidad_id,
        accion=accion, tabla=tabla, registro_id=registro_id,
        valores_anteriores=json.dumps(valores_anteriores) if valores_anteriores else None,
        valores_nuevos=json.dumps(valores_nuevos) if valores_nuevos else None,
        ip_address=request.remote_addr
    ))
    db.session.commit()

def login_requerido(f):
    @wraps(f)
    def w(*a, **kw):
        if 'usuario_id' not in session:
            flash("Debes iniciar sesión.")
            return redirect(url_for('login'))
        return f(*a, **kw)
    return w


@app.before_request
def _forzar_cambio_password_si_corresponde():
    """Si el usuario logueado tiene must_change_password=True, bloquear navegación
    a cualquier ruta excepto la de cambio de contraseña, logout, y assets estáticos."""
    if 'usuario_id' not in session:
        return
    if session.get('usuario_rol') == 'Estudiante':
        return  # estudiantes no tienen este flag
    rutas_permitidas = {'admin_cambiar_password', 'logout', 'static'}
    if request.endpoint in rutas_permitidas:
        return
    # Solo verificamos en BD si la sesión marca el flag — evita query por request.
    if not session.get('forzar_cambio_password'):
        # Refrescar desde BD una vez por sesión: si la BD dice que debe cambiar, redirigir.
        user = Usuario.query.get(session['usuario_id'])
        if user and user.must_change_password:
            session['forzar_cambio_password'] = True
        else:
            return
    flash("⚠️ Debes cambiar tu contraseña inicial antes de usar el sistema.")
    return redirect(url_for('admin_cambiar_password'))

def admin_requerido(f):
    @wraps(f)
    def w(*a, **kw):
        if session.get('usuario_rol') != 'Admin':
            flash("❌ Acceso denegado. Requiere Administrador.")
            return redirect(url_for('ver_inventario'))
        return f(*a, **kw)
    return w

def pañolero_o_admin(f):
    @wraps(f)
    def w(*a, **kw):
        if session.get('usuario_rol') not in ['Admin', 'Pañolero', 'Profesor']:
            flash("❌ Acceso denegado.")
            return redirect(url_for('ver_inventario'))
        return f(*a, **kw)
    return w

# ========== RUTAS BASICAS ==========

@app.route('/')
def index():
    if 'usuario_id' in session:
        if session.get('usuario_rol') == 'Admin':
            return redirect(url_for('dashboard_admin'))
        return redirect(url_for('ver_inventario'))
    return redirect(url_for('login'))

MAX_INTENTOS_LOGIN = 5
LOCKOUT_MINUTOS = 15


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        usuario = Usuario.query.filter_by(username=username).first()

        # 1) Bloqueo activo: rechazar incluso si la contraseña fuese correcta.
        if usuario and usuario.locked_until and usuario.locked_until > datetime.utcnow():
            restantes_min = int((usuario.locked_until - datetime.utcnow()).total_seconds() / 60) + 1
            flash(f"🔒 Cuenta bloqueada por intentos fallidos. Vuelve en {restantes_min} minutos.")
            return render_template('login.html')

        # 2) Login OK
        if usuario and usuario.activo and check_password_hash(usuario.password_hash, password):
            # Resetear contador de fallos al ingresar correctamente
            usuario.failed_attempts = 0
            usuario.locked_until = None

            session['usuario_id'] = usuario.id
            session['usuario_nombre'] = usuario.nombre
            session['usuario_rol'] = usuario.rol
            session['usuario_email'] = usuario.email
            if usuario.especialidad_id:
                session['usuario_especialidad_id'] = usuario.especialidad_id
                session['usuario_especialidad'] = usuario.especialidad_asignada.nombre
            usuario.ultimo_login = datetime.utcnow()
            db.session.commit()

            # Forzar cambio de contraseña en primer login
            if usuario.must_change_password:
                session['forzar_cambio_password'] = True
                flash("⚠️ Por seguridad, debes cambiar tu contraseña antes de continuar.")
                return redirect(url_for('admin_cambiar_password'))

            flash(f"✅ Bienvenido {usuario.nombre}")
            return redirect(url_for('index'))

        # 3) Login de estudiante (por RUT) — sin lockout (lo añadiremos si hace falta)
        estudiante = Estudiante.query.filter_by(rut_matricula=username).first()
        if estudiante and estudiante.activo and check_password_hash(estudiante.password_hash, password):
            session['usuario_id'] = estudiante.id
            session['usuario_nombre'] = estudiante.nombre
            session['usuario_rol'] = 'Estudiante'
            session['usuario_especialidad_id'] = estudiante.especialidad_id
            session['usuario_especialidad'] = estudiante.especialidad.nombre
            flash(f"✅ Bienvenido {estudiante.nombre}")
            return redirect(url_for('ver_inventario'))

        # 4) Credenciales incorrectas: si el usuario existe, incrementar contador.
        if usuario:
            usuario.failed_attempts = (usuario.failed_attempts or 0) + 1
            if usuario.failed_attempts >= MAX_INTENTOS_LOGIN:
                usuario.locked_until = datetime.utcnow() + timedelta(minutes=LOCKOUT_MINUTOS)
                usuario.failed_attempts = 0
                db.session.commit()
                flash(f"🔒 Demasiados intentos fallidos. Cuenta bloqueada por {LOCKOUT_MINUTOS} minutos.")
            else:
                restantes = MAX_INTENTOS_LOGIN - usuario.failed_attempts
                db.session.commit()
                flash(f"❌ Credenciales incorrectas. Te quedan {restantes} intento(s) antes del bloqueo.")
        else:
            # No revelar si el usuario existe o no: mensaje genérico.
            flash("❌ Credenciales incorrectas.")
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash("✅ Sesión cerrada.")
    return redirect(url_for('login'))

@app.route('/dashboard_admin')
@login_requerido
@admin_requerido
def dashboard_admin():
    # Al volver al panel, limpiamos cualquier área temporal que quedó del último ingreso
    session.pop('usuario_especialidad_id', None)
    session.pop('usuario_especialidad', None)
    session.pop('admin_viendo_especialidad', None)

    especialidades = Especialidad.query.filter_by(activa=True).all()
    total_items = Item.query.count()
    total_stock = sum(i.cantidad_total for i in Item.query.all())
    total_estudiantes = Estudiante.query.count()
    prestamos_activos = Prestamo.query.filter_by(estado='Pendiente').count()
    stats_por_especialidad = []
    for esp in especialidades:
        items_esp = Item.query.filter_by(especialidad_id=esp.id).all()
        prest_esp = Prestamo.query.join(Item).filter(
            Item.especialidad_id == esp.id, Prestamo.estado == 'Pendiente'
        ).count()
        stats_por_especialidad.append({
            'id': esp.id,
            'especialidad': esp.nombre,
            'color': esp.color or '#2563eb',
            'items_totales': len(items_esp),
            'stock_total': sum(i.cantidad_total for i in items_esp),
            'estudiantes': Estudiante.query.filter_by(especialidad_id=esp.id, activo=True).count(),
            'prestamos_activos': prest_esp,
        })
    return render_template('dashboard_admin.html',
                           especialidades=especialidades,
                           total_items=total_items, total_stock=total_stock,
                           total_estudiantes=total_estudiantes,
                           prestamos_activos=prestamos_activos,
                           stats_por_especialidad=stats_por_especialidad)

def _calcular_practicas_resumen(especialidad_id):
    practicas = {}
    qs = Prestamo.query.join(Item).filter(
        Item.especialidad_id == especialidad_id,
        Prestamo.nombre_practica.isnot(None),
        Prestamo.nombre_practica != ''
    ).all()
    for p in qs:
        n = p.nombre_practica
        if n not in practicas:
            practicas[n] = {'nombre_practica': n, 'fecha': p.fecha_prestamo,
                            'herr_detalles': [], 'mat_detalles': [],
                            'comp_detalles': [], 'fung_detalles': []}
        cat = (p.item.categoria or '').lower()
        linea = f"{p.item.nombre} x{p.cantidad}"
        if 'herr' in cat: practicas[n]['herr_detalles'].append(linea)
        elif 'mat' in cat: practicas[n]['mat_detalles'].append(linea)
        elif 'comp' in cat: practicas[n]['comp_detalles'].append(linea)
        else: practicas[n]['fung_detalles'].append(linea)
    return sorted(practicas.values(), key=lambda x: x['fecha'], reverse=True)

@app.route('/inventario')
@login_requerido
def ver_inventario():
    rol = session.get('usuario_rol')
    if rol == 'Admin':
        # Admin puede pasar ?especialidad_id=X para ver inventario de un área
        esp_query = request.args.get('especialidad_id', type=int)
        if not esp_query:
            return redirect(url_for('dashboard_admin'))
        esp_obj = Especialidad.query.get(esp_query)
        if not esp_obj:
            flash("❌ Especialidad no encontrada.")
            return redirect(url_for('dashboard_admin'))
        especialidad_id = esp_query
        # Setear sesión temporal para que los POSTs (agregar, prestar, etc.) sepan el área
        session['admin_viendo_especialidad'] = esp_obj.nombre
        session['usuario_especialidad_id'] = esp_query
        session['usuario_especialidad'] = esp_obj.nombre
    else:
        especialidad_id = session.get('usuario_especialidad_id')
    items = Item.query.filter_by(especialidad_id=especialidad_id) \
        .order_by(Item.categoria.asc(), Item.nombre.asc()).all()
    estudiantes = Estudiante.query.filter_by(especialidad_id=especialidad_id, activo=True).all()
    prestamos = Prestamo.query.join(Item).filter(
        Item.especialidad_id == especialidad_id
    ).order_by(Prestamo.fecha_prestamo.desc()).limit(50).all()
    prestamos_externos = PrestamoExterno.query.filter_by(
        especialidad_id=especialidad_id
    ).order_by(PrestamoExterno.fecha_prestamo.desc()).limit(50).all()
    ordenes_trabajo = OrdenTrabajo.query.filter_by(
        especialidad_id=especialidad_id
    ).order_by(OrdenTrabajo.fecha_creacion.desc()).limit(50).all()
    profesores = Usuario.query.filter(
        Usuario.rol.in_(['Profesor', 'Pañolero', 'Admin']),
        Usuario.activo == True
    ).all()
    usuarios_sistema = Usuario.query.filter(
        (Usuario.especialidad_id == especialidad_id) | (Usuario.rol == 'Admin')
    ).all()
    practicas_resumen = _calcular_practicas_resumen(especialidad_id)
    alertas = AlertaStock.query.filter_by(usuario_id=session.get('usuario_id'), activa=True).all()
    total_stock = sum(i.cantidad_total for i in items)
    prestamos_activos = Prestamo.query.join(Item).filter(
        Item.especialidad_id == especialidad_id, Prestamo.estado == 'Pendiente'
    ).count()
    # Tipo de área: define qué campos del formulario y columnas de la lista se muestran
    esp_obj_actual = Especialidad.query.get(especialidad_id)
    tipo_area = (esp_obj_actual.tipo_area or 'GENERAL') if esp_obj_actual else 'GENERAL'
    # Pañoleros del día activos para esta especialidad (máx. 6)
    panoleros_dia = _panoleros_dia_activos(especialidad_id) if especialidad_id else []
    return render_template('inventario.html',
                           items=items, estudiantes=estudiantes, prestamos=prestamos,
                           prestamos_externos=prestamos_externos,
                           ordenes_trabajo=ordenes_trabajo, profesores=profesores,
                           usuarios_sistema=usuarios_sistema,
                           practicas_resumen=practicas_resumen,
                           total_stock=total_stock,
                           prestamos_activos=prestamos_activos,
                           alertas=alertas,
                           tipo_area=tipo_area,
                           panoleros_dia=panoleros_dia,
                           max_panoleros_dia=MAX_PANOLEROS_DIA,
                           especialidad=(session.get('admin_viendo_especialidad')
                                          if session.get('usuario_rol') == 'Admin'
                                          else session.get('usuario_especialidad')))

@app.route('/auditoria')
@login_requerido
def ver_auditoria():
    rol = session.get('usuario_rol')
    # Filtros opcionales por query string
    f_esp = request.args.get('especialidad_id', type=int)
    f_user = (request.args.get('usuario') or '').strip()
    f_accion = (request.args.get('accion') or '').strip()
    f_desde = request.args.get('desde')
    f_hasta = request.args.get('hasta')

    q = Auditoria.query
    if rol != 'Admin':
        q = q.filter_by(especialidad_id=session.get('usuario_especialidad_id'))
    if f_esp:
        q = q.filter_by(especialidad_id=f_esp)
    if f_accion:
        q = q.filter(Auditoria.accion.ilike(f"%{f_accion}%"))
    if f_user:
        q = q.join(Usuario).filter(
            db.or_(Usuario.username.ilike(f"%{f_user}%"),
                   Usuario.nombre.ilike(f"%{f_user}%"))
        )
    if f_desde:
        try:
            q = q.filter(Auditoria.fecha >= datetime.fromisoformat(f_desde))
        except Exception: pass
    if f_hasta:
        try:
            q = q.filter(Auditoria.fecha <= datetime.fromisoformat(f_hasta))
        except Exception: pass

    logs = q.order_by(Auditoria.fecha.desc()).limit(500).all()
    especialidades = Especialidad.query.filter_by(activa=True).all()
    return render_template('auditoria.html', logs=logs,
                           especialidades=especialidades,
                           f_esp=f_esp, f_user=f_user, f_accion=f_accion,
                           f_desde=f_desde, f_hasta=f_hasta,
                           es_admin=(rol == 'Admin'))

# ========== ITEMS ==========

@app.route('/agregar', methods=['POST'])
@login_requerido
@pañolero_o_admin
def agregar_item():
    especialidad_id = session.get('usuario_especialidad_id')
    codigo = request.form.get('codigo_barras', '').strip() or datetime.now().strftime('%y%m%d%H%M%S') + "0"
    cantidad = int(request.form.get('cantidad', 1))
    imagen = request.form.get('imagen_url', '').strip()
    ubicacion = request.form.get('ubicacion', 'Sin especificar').strip()
    nombre = request.form.get('nombre', '').strip()
    categoria = request.form.get('categoria', '').strip()

    # Campos opcionales tipo-específicos
    autor = request.form.get('autor', '').strip() or None
    isbn = request.form.get('isbn', '').strip() or None
    editorial = request.form.get('editorial', '').strip() or None
    anio_pub = request.form.get('anio_publicacion', type=int)
    marca = request.form.get('marca', '').strip() or None
    modelo = request.form.get('modelo', '').strip() or None
    numero_serie = request.form.get('numero_serie', '').strip() or None
    estado = request.form.get('estado', '').strip() or None
    max_usos = request.form.get('max_usos', type=int)
    fecha_adq_raw = request.form.get('fecha_adquisicion', '').strip()
    fecha_adq = None
    if fecha_adq_raw:
        try:
            fecha_adq = datetime.fromisoformat(fecha_adq_raw).date()
        except Exception:
            fecha_adq = None
    # Costos y desgaste (en pesos chilenos, opcionales)
    descripcion = request.form.get('descripcion', '').strip() or None
    precio_unitario = request.form.get('precio_unitario', type=float) or 0.0
    desgaste = request.form.get('desgaste', type=float) or 0.0

    item_existente = Item.query.filter_by(codigo_barras=codigo, especialidad_id=especialidad_id).first()
    nuevo_item = None
    if item_existente:
        item_existente.cantidad_total += cantidad
        item_existente.cantidad_disponible += cantidad
        if imagen: item_existente.imagen_url = imagen
        if ubicacion: item_existente.ubicacion = ubicacion
        # Solo actualizar campos opcionales si vienen con valor (no sobreescribir con vacío)
        if autor: item_existente.autor = autor
        if isbn: item_existente.isbn = isbn
        if editorial: item_existente.editorial = editorial
        if anio_pub: item_existente.anio_publicacion = anio_pub
        if marca: item_existente.marca = marca
        if modelo: item_existente.modelo = modelo
        if numero_serie: item_existente.numero_serie = numero_serie
        if estado: item_existente.estado = estado
        if max_usos: item_existente.max_usos = max_usos
        if fecha_adq: item_existente.fecha_adquisicion = fecha_adq
        if descripcion: item_existente.descripcion = descripcion
        if precio_unitario: item_existente.precio_unitario = precio_unitario
        if desgaste: item_existente.desgaste = desgaste
    else:
        nuevo_item = Item(codigo_barras=codigo, nombre=nombre, categoria=categoria,
                          descripcion=descripcion,
                          especialidad_id=especialidad_id,
                          cantidad_total=cantidad, cantidad_disponible=cantidad,
                          imagen_url=imagen, ubicacion=ubicacion,
                          precio_unitario=precio_unitario, desgaste=desgaste,
                          autor=autor, isbn=isbn, editorial=editorial,
                          anio_publicacion=anio_pub,
                          marca=marca, modelo=modelo, numero_serie=numero_serie,
                          estado=estado, fecha_adquisicion=fecha_adq,
                          max_usos=max_usos)
        db.session.add(nuevo_item)
    db.session.commit()
    rid = item_existente.id if item_existente else nuevo_item.id
    registrar_auditoria('crear', 'Item', rid, valores_nuevos={'nombre': nombre, 'cantidad': cantidad})
    registrar_cambio_sync('item', rid, 'crear' if not item_existente else 'actualizar', item_existente or nuevo_item)
    flash(f"✅ Ítem '{nombre}' agregado.")
    return redirect(url_for('ver_inventario'))

@app.route('/eliminar/<int:item_id>', methods=['POST'])
@login_requerido
@pañolero_o_admin
def eliminar_item(item_id):
    item = Item.query.get_or_404(item_id)
    if session.get('usuario_rol') != 'Admin' and item.especialidad_id != session.get('usuario_especialidad_id'):
        flash("❌ Sin permiso.")
        return redirect(url_for('ver_inventario'))
    if Prestamo.query.filter_by(item_id=item.id, estado='Pendiente').first() or \
       PrestamoExterno.query.filter_by(item_id=item.id, estado='Activo').first():
        flash(f"⚠️ '{item.nombre}' tiene préstamos pendientes.")
        return redirect(url_for('ver_inventario'))
    registrar_auditoria('eliminar', 'Item', item.id,
                        valores_anteriores={'nombre': item.nombre, 'codigo': item.codigo_barras})
    registrar_cambio_sync('item', item.id, 'eliminar', item)
    db.session.delete(item)
    db.session.commit()
    flash(f"✅ Ítem '{item.nombre}' eliminado.")
    return redirect(url_for('ver_inventario'))

@app.route('/editar_item/<int:item_id>', methods=['POST'])
@login_requerido
@pañolero_o_admin
def editar_item(item_id):
    item = Item.query.get_or_404(item_id)
    if session.get('usuario_rol') != 'Admin' and item.especialidad_id != session.get('usuario_especialidad_id'):
        flash("❌ Sin permiso.")
        return redirect(url_for('ver_inventario'))
    item.nombre = request.form.get('nombre', item.nombre).strip()
    item.categoria = request.form.get('categoria', item.categoria)
    item.ubicacion = request.form.get('ubicacion', item.ubicacion)
    item.cantidad_minima = int(request.form.get('cantidad_minima') or item.cantidad_minima)

    # Imagen y descripción (solo se cambian si vienen valores)
    nueva_img = request.form.get('imagen_url', '').strip()
    if nueva_img:
        item.imagen_url = nueva_img
    nueva_desc = request.form.get('descripcion', None)
    if nueva_desc is not None and nueva_desc.strip() != '':
        item.descripcion = nueva_desc.strip()

    # Costo unitario y desgaste en pesos (acepta vacío = no cambia)
    precio_raw = request.form.get('precio_unitario', '').strip()
    if precio_raw != '':
        try:
            item.precio_unitario = float(precio_raw)
        except ValueError:
            pass
    desg_raw = request.form.get('desgaste', '').strip()
    if desg_raw != '':
        try:
            item.desgaste = float(desg_raw)
        except ValueError:
            pass

    # Fecha de adquisición (opcional)
    fecha_adq_raw = request.form.get('fecha_adquisicion', '').strip()
    if fecha_adq_raw:
        try:
            item.fecha_adquisicion = datetime.fromisoformat(fecha_adq_raw).date()
        except Exception:
            pass

    # Ajuste de stock: soporta dos formas
    # 1) cantidad_total → setear total absoluto
    # 2) ajuste_cantidad → delta a sumar/restar
    nueva = request.form.get('cantidad_total')
    ajuste = request.form.get('ajuste_cantidad')
    if nueva is not None and nueva != '':
        diff = int(nueva) - item.cantidad_total
        item.cantidad_total = int(nueva)
        item.cantidad_disponible = max(0, item.cantidad_disponible + diff)
    elif ajuste is not None and ajuste != '' and ajuste != '0':
        try:
            d = int(ajuste)
            item.cantidad_total = max(0, item.cantidad_total + d)
            item.cantidad_disponible = max(0, item.cantidad_disponible + d)
        except ValueError:
            pass
    db.session.commit()
    registrar_auditoria('actualizar', 'Item', item.id, valores_nuevos={'nombre': item.nombre})
    registrar_cambio_sync('item', item.id, 'actualizar', item)
    flash(f"✅ Ítem actualizado.")
    return redirect(url_for('ver_inventario'))

# ========== ESTUDIANTES ==========

@app.route('/agregar_estudiante', methods=['POST'])
@login_requerido
@pañolero_o_admin
def agregar_estudiante():
    rut = request.form.get('rut_matricula', '').strip()
    nombre = request.form.get('nombre', '').strip()
    curso = request.form.get('curso', '').strip()
    especialidad_id = session.get('usuario_especialidad_id') or request.form.get('especialidad_id', type=int)
    if not rut or not nombre:
        flash("❌ RUT y nombre obligatorios.")
        return redirect(url_for('ver_inventario'))
    if Estudiante.query.filter_by(rut_matricula=rut).first():
        flash(f"⚠️ RUT {rut} ya existe.")
        return redirect(url_for('ver_inventario'))
    nuevo = Estudiante(rut_matricula=rut, nombre=nombre, curso=curso,
                       especialidad_id=especialidad_id,
                       password_hash=generate_password_hash(rut), activo=True)
    db.session.add(nuevo); db.session.commit()
    registrar_auditoria('crear', 'Estudiante', nuevo.id,
                        valores_nuevos={'rut': rut, 'nombre': nombre, 'curso': curso})
    registrar_cambio_sync('estudiante', nuevo.id, 'crear', nuevo)
    flash(f"✅ Estudiante {nombre} agregado.")
    return redirect(url_for('ver_inventario'))

@app.route('/cargar_alumnos_excel', methods=['POST'])
@login_requerido
@pañolero_o_admin
def cargar_alumnos_excel():
    """Carga masiva de alumnos desde Excel.

    Formato esperado (4 columnas en orden fijo):
      Col 1 → RUT / Matrícula (obligatorio, único)
      Col 2 → Nombre completo  (obligatorio)
      Col 3 → Curso            (ej: "3°A Electrónica"; si no existe se crea)
      Col 4 → Email            (opcional)

    Reglas:
      - Solo el pañolero crea alumnos en SU especialidad.
      - Si el RUT ya existe, se actualizan nombre/curso/email (no se duplica).
      - Si el curso no existe en esa especialidad, se crea automáticamente.
      - Contraseña inicial = RUT (el alumno la cambia en su primer login).
    """
    archivo = request.files.get('archivo_excel')
    if not archivo or archivo.filename == '':
        flash("❌ No subiste ningún archivo.")
        return redirect(url_for('ver_inventario'))

    especialidad_id = session.get('usuario_especialidad_id')
    if not especialidad_id:
        flash("❌ Tu cuenta no tiene una especialidad asignada.")
        return redirect(url_for('ver_inventario'))

    try:
        df = pd.read_excel(archivo, header=None, dtype=object, sheet_name=0)
    except Exception as e:
        flash(f"❌ No pude leer el Excel: {e}")
        return redirect(url_for('ver_inventario'))

    if len(df) == 0:
        flash("⚠️ El Excel está vacío.")
        return redirect(url_for('ver_inventario'))

    # Detectar cabecera: si la primera fila col 0 dice "rut" / "matricula" / etc., saltar
    inicio = 0
    primera = df.iloc[0]
    try:
        primer_rut = str(primera[0]).strip().lower()
        if any(x in primer_rut for x in ('rut', 'matric', 'cédula', 'cedula', 'id alumno')):
            inicio = 1
    except Exception:
        pass

    def col(fila, i, default=''):
        try:
            v = fila[i]
        except (IndexError, KeyError):
            return default
        if v is None:
            return default
        if isinstance(v, float) and pd.isna(v):
            return default
        s = str(v).strip()
        if not s or s.lower() == 'nan':
            return default
        return s

    # Cache de cursos creados/encontrados en esta carga
    cursos_cache = {}

    def get_or_create_curso(nombre_curso):
        """Devuelve un Curso para el nombre dado, creándolo si hace falta."""
        if not nombre_curso:
            return None
        clave = nombre_curso.strip().lower()
        if clave in cursos_cache:
            return cursos_cache[clave]
        c = Curso.query.filter_by(nombre=nombre_curso, especialidad_id=especialidad_id).first()
        if not c:
            # Parsear nivel y letra simples (ej: "3°A", "4°B Electrónica")
            import re
            m = re.match(r'^\s*(\d+)\s*[°º]?\s*([A-Z])?', nombre_curso, re.IGNORECASE)
            nivel = letra = None
            if m:
                nivel = f"{m.group(1)}° Medio" if m.group(1) else None
                letra = m.group(2).upper() if m.group(2) else None
            c = Curso(nombre=nombre_curso, nivel=nivel, letra=letra,
                      anio=datetime.now().year,
                      especialidad_id=especialidad_id, activo=True)
            db.session.add(c)
            db.session.flush()
        cursos_cache[clave] = c
        return c

    creados = actualizados = cursos_nuevos = 0
    errores = []
    ya_existian = set()

    for idx in range(inicio, len(df)):
        fila = df.iloc[idx]
        rut = col(fila, 0)
        nombre = col(fila, 1)
        nombre_curso = col(fila, 2)
        email = col(fila, 3) or None

        if not rut or not nombre:
            # Saltar filas en blanco al final del Excel
            if rut or nombre or nombre_curso:
                errores.append(f"Fila {idx + 1}: falta RUT o nombre")
            continue

        # Curso (crear si no existe)
        curso_obj = None
        if nombre_curso:
            antes = Curso.query.filter_by(nombre=nombre_curso,
                                          especialidad_id=especialidad_id).first() is not None
            curso_obj = get_or_create_curso(nombre_curso)
            if not antes and curso_obj is not None:
                cursos_nuevos += 1

        existente = Estudiante.query.filter_by(rut_matricula=rut).first()
        if existente:
            # Solo actualizar si pertenece a esta especialidad (seguridad)
            if existente.especialidad_id != especialidad_id and session.get('usuario_rol') != 'Admin':
                errores.append(f"Fila {idx + 1}: RUT {rut} pertenece a otra especialidad")
                continue
            existente.nombre = nombre
            if nombre_curso:
                existente.curso = nombre_curso
                if curso_obj:
                    existente.curso_id = curso_obj.id
            if email:
                existente.email = email
            registrar_cambio_sync('estudiante', existente.id, 'actualizar', existente)
            actualizados += 1
            ya_existian.add(rut)
        else:
            nuevo = Estudiante(
                rut_matricula=rut, nombre=nombre,
                curso=nombre_curso or None,
                curso_id=curso_obj.id if curso_obj else None,
                especialidad_id=especialidad_id,
                email=email,
                password_hash=generate_password_hash(rut),
                activo=True,
            )
            db.session.add(nuevo)
            db.session.flush()
            registrar_cambio_sync('estudiante', nuevo.id, 'crear', nuevo)
            creados += 1

    db.session.commit()
    registrar_auditoria('importar', 'Estudiante', 0,
                        valores_nuevos={'creados': creados,
                                        'actualizados': actualizados,
                                        'cursos_nuevos': cursos_nuevos,
                                        'errores': len(errores)})

    msg = (f"✅ Carga de alumnos: {creados} nuevo(s), {actualizados} actualizado(s), "
           f"{cursos_nuevos} curso(s) creado(s).")
    if errores:
        msg += f" ⚠️ {len(errores)} fila(s) con error: " + " | ".join(errores[:3])
    flash(msg)
    return redirect(url_for('ver_inventario'))


@app.route('/eliminar_estudiante/<int:est_id>', methods=['POST'])
@login_requerido
@pañolero_o_admin
def eliminar_estudiante(est_id):
    est = Estudiante.query.get_or_404(est_id)
    if Prestamo.query.filter_by(estudiante_id=est.id, estado='Pendiente').first():
        flash(f"⚠️ {est.nombre} tiene préstamos pendientes.")
        return redirect(url_for('ver_inventario'))
    est.activo = False
    db.session.commit()
    registrar_auditoria('eliminar', 'Estudiante', est.id,
                        valores_anteriores={'nombre': est.nombre, 'rut': est.rut_matricula})
    registrar_cambio_sync('estudiante', est.id, 'actualizar', est)
    flash(f"✅ {est.nombre} dado de baja.")
    return redirect(url_for('ver_inventario'))

# ========== PRESTAMOS ESTUDIANTES ==========

@app.route('/registrar_salida', methods=['POST'])
@login_requerido
@pañolero_o_admin
def registrar_salida():
    estudiante_id = request.form.get('estudiante_id', type=int)
    profesor_id = request.form.get('profesor_id', type=int)
    nombre_practica = (request.form.get('nombre_practica') or '').strip()
    try:
        carrito = json.loads(request.form.get('carrito_data', '[]'))
    except Exception:
        carrito = []
    estudiante = Estudiante.query.get(estudiante_id)
    if not estudiante:
        flash("❌ Estudiante no encontrado.")
        return redirect(url_for('ver_inventario'))
    if not carrito:
        flash("⚠️ No hay items en el carrito.")
        return redirect(url_for('ver_inventario'))

    # Plazo: obligatorio si todos los items son de BIBLIOTECA, opcional en otros.
    plazo_dias = request.form.get('plazo_dias', type=int)

    # Pañolero del día (estudiante designado que atiende este préstamo). Opcional.
    panolero_dia_id = request.form.get('panolero_dia_id', type=int)
    if panolero_dia_id:
        # Validar que sea un pañolero del día activo de esta especialidad
        pd = PanoleroDesignado.query.filter_by(
            estudiante_id=panolero_dia_id,
            especialidad_id=session.get('usuario_especialidad_id'),
            activo=True
        ).first()
        if not pd:
            flash("⚠️ Pañolero del día seleccionado no está activo. El préstamo quedará a nombre del encargado.")
            panolero_dia_id = None

    creados = 0
    for entry in carrito:
        item = Item.query.get(entry.get('item_id'))
        cantidad = int(entry.get('cantidad') or 1)
        if not item or item.cantidad_disponible < cantidad: continue

        # Plazo de devolución: BIBLIOTECA forza 14 días por defecto si no vino otro valor.
        tipo_area_item = (item.especialidad.tipo_area or 'GENERAL') if item.especialidad else 'GENERAL'
        if plazo_dias and plazo_dias > 0:
            fecha_limite = datetime.utcnow() + timedelta(days=plazo_dias)
        elif tipo_area_item == 'BIBLIOTECA':
            fecha_limite = datetime.utcnow() + timedelta(days=14)
        else:
            fecha_limite = None

        item.cantidad_disponible -= cantidad
        # Incrementar usos_actuales si el ítem tiene max_usos configurado (desgaste por uso)
        if item.max_usos:
            item.usos_actuales = (item.usos_actuales or 0) + cantidad

        db.session.add(Prestamo(item_id=item.id, estudiante_id=estudiante.id,
                                profesor_id=profesor_id,
                                panolero_dia_id=panolero_dia_id,
                                encargado=session.get('usuario_nombre'),
                                cantidad=cantidad, cantidad_solicitada=cantidad,
                                nombre_practica=nombre_practica, estado='Pendiente',
                                fecha_devolucion_esperada=fecha_limite))
        creados += 1
    db.session.commit()
    registrar_auditoria('crear', 'Prestamo', estudiante.id,
                        valores_nuevos={'practica': nombre_practica, 'items': creados})
    flash(f"✅ {creados} préstamo(s) registrado(s) a {estudiante.nombre}.")
    return redirect(url_for('ver_inventario'))

@app.route('/devolver_prestamo/<int:prestamo_id>', methods=['POST'])
@login_requerido
@pañolero_o_admin
def devolver_prestamo(prestamo_id):
    prest = Prestamo.query.get_or_404(prestamo_id)
    cd = int(request.form.get('cantidad_devuelta') or prest.cantidad)
    cm = int(request.form.get('cantidad_mermada') or 0)
    if cd + cm > prest.cantidad:
        flash("❌ Devuelto + mermado supera lo prestado.")
        return redirect(url_for('ver_inventario'))
    prest.item.cantidad_disponible += cd
    if cm > 0:
        prest.item.cantidad_mermada += cm
        prest.item.cantidad_total -= cm
        prest.cantidad_mermada = cm
    prest.estado = 'Devuelto'
    prest.fecha_devolucion = datetime.utcnow()
    db.session.commit()
    registrar_auditoria('actualizar', 'Prestamo', prest.id,
                        valores_nuevos={'devuelto': cd, 'mermado': cm})
    registrar_cambio_sync('prestamo', prest.id, 'actualizar', prest)
    registrar_cambio_sync('item', prest.item.id, 'actualizar', prest.item)
    flash(f"✅ Préstamo #{prest.id} cerrado.")
    return redirect(url_for('ver_inventario'))

# ========== PRESTAMOS EXTERNOS ==========

@app.route('/agregar_prestamo_externo', methods=['POST'])
@login_requerido
@pañolero_o_admin
def agregar_prestamo_externo():
    codigo = (request.form.get('codigo_item') or '').strip()
    cantidad = int(request.form.get('cantidad') or 1)
    esp_dest = (request.form.get('especialidad_destino') or '').strip()
    tipo_p = request.form.get('tipo_persona') or 'externo'
    persona = (request.form.get('persona_retira') or '').strip()
    profesor = (request.form.get('profesor_cargo') or '').strip()
    especialidad_id = session.get('usuario_especialidad_id')
    item = Item.query.filter_by(codigo_barras=codigo, especialidad_id=especialidad_id).first()
    if not item:
        flash(f"❌ Ítem '{codigo}' no existe.")
        return redirect(url_for('ver_inventario'))
    if item.cantidad_disponible < cantidad:
        flash(f"❌ Stock insuficiente: {item.cantidad_disponible}.")
        return redirect(url_for('ver_inventario'))
    # tipo_movimiento: 'prestamo' (se devuelve) o 'consumo' (oficina, no se devuelve)
    tipo_mov = (request.form.get('tipo_movimiento') or 'prestamo').lower().strip()
    if tipo_mov not in ('prestamo', 'consumo'):
        tipo_mov = 'prestamo'

    item.cantidad_disponible -= cantidad
    if tipo_mov == 'consumo':
        # Consumo: descontar también del total (no vuelve nunca)
        item.cantidad_total -= cantidad
    elif item.max_usos:
        # Préstamo (no consumo) cuenta para desgaste si el ítem tiene max_usos
        item.usos_actuales = (item.usos_actuales or 0) + cantidad

    p = PrestamoExterno(item_id=item.id, especialidad_id=especialidad_id,
                        cantidad=cantidad, es_alumno=(tipo_p == 'alumno'),
                        persona_retira=persona, profesor_cargo=profesor,
                        especialidad_destino=esp_dest,
                        encargado=session.get('usuario_nombre'),
                        estado=('Consumido' if tipo_mov == 'consumo' else 'Activo'),
                        tipo_movimiento=tipo_mov,
                        fecha_devolucion=(datetime.utcnow() if tipo_mov == 'consumo' else None))
    db.session.add(p); db.session.commit()
    registrar_auditoria('crear', 'PrestamoExterno', p.id,
                        valores_nuevos={'item': item.nombre, 'persona': persona, 'tipo': tipo_mov})
    accion = 'Consumo registrado' if tipo_mov == 'consumo' else 'Préstamo externo'
    flash(f"✅ {accion}: {item.nombre} → {persona}.")
    return redirect(url_for('ver_inventario'))

@app.route('/devolver_externo/<int:ext_id>', methods=['POST'])
@login_requerido
@pañolero_o_admin
def devolver_externo(ext_id):
    ext = PrestamoExterno.query.get_or_404(ext_id)
    if ext.tipo_movimiento == 'consumo':
        flash("⚠️ Este movimiento es un consumo (oficina), no se puede devolver.")
        return redirect(url_for('ver_inventario'))
    ext.item.cantidad_disponible += ext.cantidad
    ext.estado = 'Devuelto'
    ext.fecha_devolucion = datetime.utcnow()
    db.session.commit()
    registrar_auditoria('actualizar', 'PrestamoExterno', ext.id,
                        valores_nuevos={'estado': 'Devuelto'})
    registrar_cambio_sync('prestamo_externo', ext.id, 'actualizar', ext)
    registrar_cambio_sync('item', ext.item.id, 'actualizar', ext.item)
    flash(f"✅ Préstamo externo #{ext.id} devuelto.")
    return redirect(url_for('ver_inventario'))

# ========== ORDENES DE TRABAJO ==========

@app.route('/agregar_ot', methods=['POST'])
@login_requerido
@pañolero_o_admin
def agregar_ot():
    titulo = (request.form.get('titulo') or '').strip()
    profesional = (request.form.get('profesional_cargo') or '').strip()
    alumnos = (request.form.get('alumnos_cargo') or '').strip()
    descripcion = (request.form.get('descripcion') or '').strip()
    herr = request.form.get('herramientas_utilizadas') or ''
    rep = request.form.get('repuestos_utilizados') or ''
    if not titulo or not profesional:
        flash("❌ Título y profesional obligatorios.")
        return redirect(url_for('ver_inventario'))
    ot = OrdenTrabajo(titulo=titulo, descripcion=descripcion,
                      especialidad_id=session.get('usuario_especialidad_id'),
                      profesional_cargo=profesional, alumnos_cargo=alumnos,
                      herramientas_utilizadas=herr, repuestos_utilizados=rep,
                      profesor_id=session.get('usuario_id'), estado='Pendiente')
    db.session.add(ot); db.session.commit()
    registrar_auditoria('crear', 'OrdenTrabajo', ot.id, valores_nuevos={'titulo': titulo})
    registrar_cambio_sync('orden_trabajo', ot.id, 'crear', ot)
    flash(f"✅ OT #{ot.id} creada.")
    return redirect(url_for('imprimir_ot', ot_id=ot.id))

@app.route('/completar_ot/<int:ot_id>', methods=['POST'])
@login_requerido
@pañolero_o_admin
def completar_ot(ot_id):
    ot = OrdenTrabajo.query.get_or_404(ot_id)
    ot.estado = 'Completada'
    db.session.commit()
    registrar_auditoria('actualizar', 'OrdenTrabajo', ot.id, valores_nuevos={'estado': 'Completada'})
    registrar_cambio_sync('orden_trabajo', ot.id, 'actualizar', ot)
    flash(f"✅ OT #{ot.id} completada.")
    return redirect(url_for('ver_inventario'))

@app.route('/imprimir_ot/<int:ot_id>')
@login_requerido
def imprimir_ot(ot_id):
    ot = OrdenTrabajo.query.get_or_404(ot_id)
    def parse(t):
        if not t: return []
        try:
            d = json.loads(t)
            if isinstance(d, list): return d
        except Exception: pass
        return [{'nombre': l.strip(), 'cantidad': '', 'codigo': ''}
                for l in t.splitlines() if l.strip()]
    return render_template('imprimir_ot.html', ot=ot,
                           herramientas=parse(ot.herramientas_utilizadas),
                           repuestos=parse(ot.repuestos_utilizados))

@app.route('/imprimir_externo/<int:ext_id>')
@login_requerido
def imprimir_externo(ext_id):
    return render_template('imprimir_externo.html',
                           prestamo=PrestamoExterno.query.get_or_404(ext_id))

# ========== HOJA DE VIDA ==========

@app.route('/buscar_hoja_vida', methods=['POST'])
@login_requerido
def buscar_hoja_vida():
    rut = (request.form.get('scan_estudiante') or '').strip()
    est = Estudiante.query.filter_by(rut_matricula=rut).first()
    if not est:
        flash(f"❌ RUT {rut} no encontrado.")
        return redirect(url_for('ver_inventario'))
    return redirect(url_for('hoja_vida', est_id=est.id))

@app.route('/hoja_vida/<int:est_id>')
@login_requerido
def hoja_vida(est_id):
    est = Estudiante.query.get_or_404(est_id)
    prestamos = Prestamo.query.filter_by(estudiante_id=est.id, estado='Pendiente') \
                              .order_by(Prestamo.fecha_prestamo.desc()).all()
    return render_template('hoja_vida.html', estudiante=est, prestamos=prestamos)

@app.route('/procesar_hoja_vida', methods=['POST'])
@login_requerido
@pañolero_o_admin
def procesar_hoja_vida():
    ids = request.form.getlist('prestamo_id[]')
    buenas = request.form.getlist('cant_buena[]')
    malas = request.form.getlist('cant_mala[]')
    procesados = 0
    for pid, cb, cm in zip(ids, buenas, malas):
        try: prest = Prestamo.query.get(int(pid))
        except: continue
        if not prest or prest.estado != 'Pendiente': continue
        cb = int(cb or 0); cm = int(cm or 0)
        if cb + cm == 0: continue
        prest.item.cantidad_disponible += cb
        if cm > 0:
            prest.item.cantidad_mermada += cm
            prest.item.cantidad_total -= cm
            prest.cantidad_mermada = cm
        if cb + cm >= prest.cantidad:
            prest.estado = 'Devuelto'
            prest.fecha_devolucion = datetime.utcnow()
        procesados += 1
    db.session.commit()
    registrar_auditoria('actualizar', 'Prestamo', 0, valores_nuevos={'procesados': procesados})
    flash(f"✅ {procesados} préstamo(s) procesado(s).")
    return redirect(url_for('ver_inventario'))

@app.route('/credenciales')
@login_requerido
def credenciales():
    if session.get('usuario_rol') == 'Admin':
        qs = Estudiante.query.filter_by(activo=True).all()
    else:
        qs = Estudiante.query.filter_by(
            especialidad_id=session.get('usuario_especialidad_id'), activo=True
        ).all()
    estudiantes = [{'rut_matricula': e.rut_matricula, 'nombre': e.nombre,
                    'carrera': e.especialidad.nombre if e.especialidad else '',
                    'curso': e.curso or ''} for e in qs]
    return render_template('credenciales.html', estudiantes=estudiantes)

# ========== EXCEL ==========

@app.route('/cargar_excel', methods=['POST'])
@login_requerido
@pañolero_o_admin
def cargar_excel():
    """Carga masiva desde Excel.

    Formato esperado (13 columnas A–M, orden FIJO; las extras son opcionales):
      A (1)  → Código de barra (si está vacía, se autogenera)
      B (2)  → Nombre del ítem (OBLIGATORIO)
      C (3)  → Descripción
      D (4)  → Marca
      E (5)  → Modelo
      F (6)  → Categoría (si está vacía → 'General')
      G (7)  → Cantidad (numérico, OBLIGATORIO)
      H (8)  → Ubicación
      I (9)  → Fecha adquisición (YYYY-MM-DD)
      J (10) → Desgaste ($) (numérico)
      K (11) → Costo unitario ($) (numérico)
      L (12) → Costo total ($) — IGNORADO (lo calcula la app: costo_unit × cantidad)
      M (13) → URL/ruta de imagen de referencia

    Si el código ya existe en esta especialidad, SUMA al stock existente.
    Si es nuevo, lo crea. La primera fila se detecta como cabecera si la
    columna G (Cantidad) no es numérica.
    """
    archivo = request.files.get('archivo_excel')
    if not archivo or archivo.filename == '':
        flash("❌ No subiste ningún archivo.")
        return redirect(url_for('ver_inventario'))

    try:
        df = pd.read_excel(archivo, header=None, dtype=object)
    except Exception as e:
        flash(f"❌ No pude leer el Excel: {e}")
        return redirect(url_for('ver_inventario'))

    if len(df) == 0:
        flash("⚠️ El Excel está vacío.")
        return redirect(url_for('ver_inventario'))

    # Detectar si la primera fila es cabecera (columna G = índice 6 = Cantidad, no numérica)
    inicio = 0
    primera = df.iloc[0]
    try:
        int(float(str(primera[6]).strip()))
    except (ValueError, TypeError, IndexError):
        inicio = 1  # primera fila es cabecera, saltarla

    especialidad_id = session.get('usuario_especialidad_id')
    if not especialidad_id and session.get('usuario_rol') != 'Admin':
        flash("❌ No tienes especialidad asignada.")
        return redirect(url_for('ver_inventario'))

    def col(fila, i, default=''):
        """Saca el valor de la columna i (0-indexed). Devuelve default si está vacío."""
        try:
            v = fila[i]
        except (IndexError, KeyError):
            return default
        if v is None:
            return default
        if isinstance(v, float) and pd.isna(v):
            return default
        s = str(v).strip()
        if not s or s.lower() == 'nan':
            return default
        return s

    creados = actualizados = 0
    errores = []

    for idx in range(inicio, len(df)):
        fila = df.iloc[idx]
        nombre = col(fila, 1)  # B
        if not nombre:
            continue  # filas vacías al final del Excel

        codigo = col(fila, 0)  # A
        if not codigo:
            # Autogenerar único: timestamp + idx para evitar colisiones
            codigo = datetime.now().strftime('%y%m%d%H%M%S') + f"{idx:04d}"

        descripcion = col(fila, 2, '') or None  # C
        marca = col(fila, 3, '') or None        # D — NUEVO
        modelo = col(fila, 4, '') or None       # E — NUEVO
        categoria = col(fila, 5, 'General')     # F

        try:
            cantidad = int(float(col(fila, 6, '0')))  # G
        except Exception:
            errores.append(f"Fila {idx + 1}: cantidad inválida")
            continue
        if cantidad < 0:
            errores.append(f"Fila {idx + 1}: cantidad negativa")
            continue

        ubicacion = col(fila, 7, '')  # H

        # Fecha adquisición (I) — opcional
        fecha_raw = col(fila, 8, '')
        fecha_adq = None
        if fecha_raw:
            try:
                if hasattr(fecha_raw, 'date'):
                    fecha_adq = fecha_raw.date()
                else:
                    fecha_adq = datetime.fromisoformat(str(fecha_raw)[:10]).date()
            except Exception:
                fecha_adq = None

        # Desgaste $ (J) y costo unitario $ (K) — opcionales
        try:
            desgaste_val = float(col(fila, 9, '0') or 0)
        except Exception:
            desgaste_val = 0.0
        try:
            precio_val = float(col(fila, 10, '0') or 0)
        except Exception:
            precio_val = 0.0

        # Col L (costo total) se ignora: lo calcula la app
        imagen = col(fila, 12, '')  # M

        existente = Item.query.filter_by(
            codigo_barras=codigo, especialidad_id=especialidad_id
        ).first()
        if existente:
            existente.cantidad_total += cantidad
            existente.cantidad_disponible += cantidad
            # Solo sobrescribir si el Excel trae valor
            if descripcion:
                existente.descripcion = descripcion
            if marca:
                existente.marca = marca
            if modelo:
                existente.modelo = modelo
            if categoria and categoria != 'General':
                existente.categoria = categoria
            if ubicacion:
                existente.ubicacion = ubicacion
            if imagen:
                existente.imagen_url = imagen
            if fecha_adq:
                existente.fecha_adquisicion = fecha_adq
            if desgaste_val:
                existente.desgaste = desgaste_val
            if precio_val:
                existente.precio_unitario = precio_val
            registrar_cambio_sync('item', existente.id, 'actualizar', existente)
            actualizados += 1
        else:
            nuevo = Item(
                codigo_barras=codigo, nombre=nombre,
                descripcion=descripcion, marca=marca, modelo=modelo,
                categoria=categoria,
                especialidad_id=especialidad_id,
                cantidad_total=cantidad, cantidad_disponible=cantidad,
                ubicacion=ubicacion, imagen_url=imagen,
                fecha_adquisicion=fecha_adq,
                desgaste=desgaste_val, precio_unitario=precio_val,
            )
            db.session.add(nuevo)
            db.session.flush()
            registrar_cambio_sync('item', nuevo.id, 'crear', nuevo)
            creados += 1

    db.session.commit()
    registrar_auditoria('importar', 'Item', 0,
                        valores_nuevos={'creados': creados,
                                        'actualizados': actualizados,
                                        'errores': len(errores)})

    msg = f"✅ Excel cargado: {creados} ítem(s) nuevo(s), {actualizados} actualizado(s)."
    if errores:
        msg += f" ⚠️ {len(errores)} fila(s) con errores: " + " | ".join(errores[:3])
    flash(msg)
    return redirect(url_for('ver_inventario'))

@app.route('/exportar_excel')
@login_requerido
def exportar_excel():
    if session.get('usuario_rol') == 'Admin':
        items = Item.query.order_by(Item.especialidad_id.asc(),
                                    Item.categoria.asc(),
                                    Item.nombre.asc()).all()
    else:
        items = Item.query.filter_by(
            especialidad_id=session.get('usuario_especialidad_id')
        ).order_by(Item.categoria.asc(), Item.nombre.asc()).all()
    # Formato estándar A–M (13 columnas) — coincide con cargar_excel para roundtrip exacto
    df = pd.DataFrame([{
        'Código de barra': i.codigo_barras,                                      # A
        'Nombre': i.nombre,                                                       # B
        'Descripción': i.descripcion or '',                                       # C
        'Marca': i.marca or '',                                                   # D
        'Modelo': i.modelo or '',                                                 # E
        'Categoría': i.categoria,                                                 # F
        'Cantidad': i.cantidad_total,                                             # G
        'Ubicación': i.ubicacion,                                                 # H
        'Fecha adquisición': i.fecha_adquisicion.isoformat() if i.fecha_adquisicion else '',  # I
        'Desgaste ($)': i.desgaste or 0,                                          # J
        'Costo unitario ($)': i.precio_unitario or 0,                             # K
        'Costo total ($)': (i.precio_unitario or 0) * (i.cantidad_total or 0),    # L
        'Imagen de referencia': i.imagen_url or '',                               # M
        # Columnas auxiliares (informativas; el importador las ignora porque
        # solo lee las primeras 13 columnas en orden)
        'Especialidad': i.especialidad.nombre if i.especialidad else '',
        'Disponible': i.cantidad_disponible,
        'Mermada': i.cantidad_mermada,
    } for i in items])
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='Inventario', index=False)
    buf.seek(0)
    fname = f"inventario_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
    return send_file(buf, as_attachment=True, download_name=fname,
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

# ========== USUARIOS ==========

@app.route('/agregar_usuario', methods=['POST'])
@login_requerido
@pañolero_o_admin
def agregar_usuario():
    nombre = (request.form.get('nombre') or '').strip()
    username = (request.form.get('username') or '').strip()
    password = request.form.get('password') or ''
    rol = request.form.get('rol') or 'Profesor'
    if not (nombre and username and password):
        flash("❌ Faltan datos.")
        return redirect(url_for('ver_inventario'))
    if Usuario.query.filter_by(username=username).first():
        flash(f"⚠️ '{username}' ya existe.")
        return redirect(url_for('ver_inventario'))
    u = Usuario(nombre=nombre, username=username,
                password_hash=generate_password_hash(password),
                rol=rol, especialidad_id=session.get('usuario_especialidad_id'), activo=True)
    db.session.add(u); db.session.commit()
    registrar_auditoria('crear', 'Usuario', u.id, valores_nuevos={'username': username, 'rol': rol})
    flash(f"✅ Usuario '{username}' creado.")
    return redirect(url_for('ver_inventario'))

@app.route('/eliminar_usuario/<int:usuario_id>', methods=['POST'])
@login_requerido
@pañolero_o_admin
def eliminar_usuario(usuario_id):
    if usuario_id == session.get('usuario_id'):
        flash("❌ No puedes eliminarte.")
        return redirect(url_for('ver_inventario'))
    u = Usuario.query.get_or_404(usuario_id)
    if u.rol == 'Admin':
        flash("❌ Admin Central no se elimina aquí.")
        return redirect(url_for('ver_inventario'))
    u.activo = False
    db.session.commit()
    registrar_auditoria('eliminar', 'Usuario', u.id, valores_anteriores={'username': u.username})
    flash(f"✅ '{u.username}' desactivado.")
    return redirect(url_for('ver_inventario'))

# ========== GESTION PAÑOLEROS ==========

@app.route('/admin/panoleros')
@login_requerido
@admin_requerido
def gestionar_panoleros():
    """Lista todos los pañoleros (activos e inactivos)."""
    especialidades = Especialidad.query.filter_by(activa=True).order_by(Especialidad.nombre).all()
    panoleros = Usuario.query.filter_by(rol='Pañolero') \
        .order_by(Usuario.activo.desc(), Usuario.nombre.asc()).all()
    return render_template('gestionar_pañoleros.html',
                           especialidades=especialidades,
                           pañoleros=panoleros)

@app.route('/admin/panolero/crear', methods=['POST'])
@login_requerido
@admin_requerido
def crear_panolero():
    """Crea un pañolero. Permite múltiples por especialidad (genera usernames únicos)."""
    import unicodedata
    nombre = (request.form.get('nombre') or '').strip()
    username_custom = (request.form.get('username') or '').strip()
    especialidad_id = request.form.get('especialidad_id', type=int)
    password = (request.form.get('password') or '').strip()
    email_custom = (request.form.get('email') or '').strip()

    if not nombre or not especialidad_id or not password:
        flash("❌ Faltan datos: nombre, especialidad y contraseña son obligatorios.")
        return redirect(url_for('gestionar_panoleros'))

    esp = Especialidad.query.get(especialidad_id)
    if not esp:
        flash("❌ Especialidad no encontrada.")
        return redirect(url_for('gestionar_panoleros'))

    def slugify(s):
        s = ''.join(c for c in unicodedata.normalize('NFD', s)
                    if unicodedata.category(c) != 'Mn')
        return s.lower().replace(' ', '_').replace('.', '_')

    # Usar username custom si viene; si no, generar uno único basado en especialidad
    if username_custom:
        username = slugify(username_custom)
    else:
        base = f"pañolero_{slugify(esp.nombre)}"
        username = base
        n = 2
        while Usuario.query.filter_by(username=username).first():
            username = f"{base}_{n}"
            n += 1

    if Usuario.query.filter_by(username=username).first():
        flash(f"❌ El usuario '{username}' ya existe. Elige otro.")
        return redirect(url_for('gestionar_panoleros'))

    email = email_custom or f"{username}@colegio.local"
    if Usuario.query.filter_by(email=email).first():
        # Email ya en uso, generar único
        email = f"{username}_{datetime.now().strftime('%H%M%S')}@colegio.local"

    nuevo = Usuario(nombre=nombre, username=username, email=email,
                    password_hash=generate_password_hash(password),
                    rol='Pañolero', especialidad_id=especialidad_id, activo=True)
    db.session.add(nuevo); db.session.commit()
    registrar_auditoria('crear', 'Usuario', nuevo.id,
                        valores_nuevos={'nombre': nombre, 'username': username,
                                        'rol': 'Pañolero', 'especialidad': esp.nombre})
    flash(f"✅ Pañolero '{nombre}' creado con usuario '{username}'.")
    return redirect(url_for('gestionar_panoleros'))


@app.route('/admin/panolero/<int:panolero_id>/editar', methods=['POST'])
@login_requerido
@admin_requerido
def editar_panolero(panolero_id):
    """Edita datos de un pañolero existente."""
    p = Usuario.query.get(panolero_id)
    if not p or p.rol != 'Pañolero':
        flash("❌ Pañolero no encontrado.")
        return redirect(url_for('gestionar_panoleros'))

    nuevo_nombre = (request.form.get('nombre') or '').strip()
    nuevo_username = (request.form.get('username') or '').strip()
    nueva_esp = request.form.get('especialidad_id', type=int)
    nuevo_email = (request.form.get('email') or '').strip()
    nuevo_password = (request.form.get('password') or '').strip()
    activo = request.form.get('activo') == 'on'

    cambios = {}

    if nuevo_nombre and nuevo_nombre != p.nombre:
        cambios['nombre'] = (p.nombre, nuevo_nombre)
        p.nombre = nuevo_nombre

    if nuevo_username and nuevo_username != p.username:
        # Verificar que no choque con otro
        otro = Usuario.query.filter(Usuario.username == nuevo_username, Usuario.id != p.id).first()
        if otro:
            flash(f"❌ Ya existe un usuario con username '{nuevo_username}'.")
            return redirect(url_for('gestionar_panoleros'))
        cambios['username'] = (p.username, nuevo_username)
        p.username = nuevo_username

    if nueva_esp and nueva_esp != p.especialidad_id:
        esp = Especialidad.query.get(nueva_esp)
        if esp:
            cambios['especialidad'] = (
                (p.especialidad_asignada.nombre if p.especialidad_asignada else None),
                esp.nombre
            )
            p.especialidad_id = nueva_esp

    if nuevo_email and nuevo_email != p.email:
        otro = Usuario.query.filter(Usuario.email == nuevo_email, Usuario.id != p.id).first()
        if otro:
            flash(f"❌ Ya existe un usuario con email '{nuevo_email}'.")
            return redirect(url_for('gestionar_panoleros'))
        cambios['email'] = (p.email, nuevo_email)
        p.email = nuevo_email

    if activo != p.activo:
        cambios['activo'] = (p.activo, activo)
        p.activo = activo

    if nuevo_password:
        p.password_hash = generate_password_hash(nuevo_password)
        cambios['password'] = ('***', '***cambiada***')

    if not cambios:
        flash("⚠️ No se detectaron cambios.")
        return redirect(url_for('gestionar_panoleros'))

    db.session.commit()
    registrar_auditoria('actualizar', 'Usuario', p.id, valores_nuevos=cambios)
    flash(f"✅ Pañolero '{p.nombre}' actualizado ({len(cambios)} cambio(s)).")
    return redirect(url_for('gestionar_panoleros'))


@app.route('/admin/panolero/<int:panolero_id>/toggle', methods=['POST'])
@login_requerido
@admin_requerido
def toggle_panolero(panolero_id):
    """Activar / desactivar pañolero (sin eliminar)."""
    p = Usuario.query.get(panolero_id)
    if not p or p.rol != 'Pañolero':
        flash("❌ Pañolero no encontrado.")
        return redirect(url_for('gestionar_panoleros'))
    p.activo = not p.activo
    db.session.commit()
    estado = 'activado' if p.activo else 'desactivado'
    registrar_auditoria('actualizar', 'Usuario', p.id,
                        valores_nuevos={'estado': estado})
    flash(f"✅ Pañolero '{p.nombre}' {estado}.")
    return redirect(url_for('gestionar_panoleros'))

@app.route('/admin/panolero/<int:panolero_id>/eliminar', methods=['POST'])
@login_requerido
@admin_requerido
def eliminar_panolero(panolero_id):
    p = Usuario.query.get(panolero_id)
    if not p or p.rol != 'Pañolero':
        flash("❌ Pañolero no encontrado.")
        return redirect(url_for('gestionar_panoleros'))
    registrar_auditoria('eliminar', 'Usuario', panolero_id,
                        valores_anteriores={'nombre': p.nombre, 'username': p.username})
    db.session.delete(p); db.session.commit()
    flash(f"✅ Pañolero eliminado.")
    return redirect(url_for('gestionar_panoleros'))

@app.route('/admin/panolero/<int:panolero_id>/resetear-contrasena', methods=['POST'])
@login_requerido
@admin_requerido
def resetear_contrasena_panolero(panolero_id):
    p = Usuario.query.get(panolero_id)
    if not p or p.rol != 'Pañolero':
        flash("❌ Pañolero no encontrado.")
        return redirect(url_for('gestionar_panoleros'))
    p.password_hash = generate_password_hash("pañol123")
    db.session.commit()
    registrar_auditoria('actualizar', 'Usuario', panolero_id,
                        valores_nuevos={'accion': 'resetear_contraseña'})
    flash(f"✅ Contraseña de '{p.nombre}' reseteada a: pañol123")
    return redirect(url_for('gestionar_panoleros'))


# ========================================================================
# BIBLIOTECA: catálogo, libros atrasados, alta de libros
# ========================================================================

def _es_biblioteca():
    """True si el usuario actual está en la especialidad Biblioteca o es Admin."""
    rol = session.get('usuario_rol')
    nombre_esp = (session.get('usuario_especialidad') or '').lower()
    return rol == 'Admin' or 'biblioteca' in nombre_esp


@app.route('/biblioteca')
@login_requerido
def biblioteca_catalogo():
    """Catálogo bibliográfico: lista todos los items con datos de libro y permite buscar."""
    q = (request.args.get('q') or '').strip()
    rol = session.get('usuario_rol')

    # Determinar el id de la especialidad Biblioteca
    bib = Especialidad.query.filter_by(nombre='Biblioteca').first()
    if not bib:
        flash("⚠️ La especialidad 'Biblioteca' no existe en la BD.")
        return redirect(url_for('ver_inventario'))

    base_query = Item.query.filter_by(especialidad_id=bib.id)
    if q:
        like = f"%{q}%"
        base_query = base_query.filter(
            db.or_(
                Item.nombre.ilike(like),
                Item.autor.ilike(like),
                Item.isbn.ilike(like),
                Item.editorial.ilike(like),
                Item.codigo_barras.ilike(like),
            )
        )

    libros = base_query.order_by(Item.categoria.asc(), Item.nombre.asc()).limit(500).all()

    # Si la plantilla específica de biblioteca no existe aún, reutilizamos inventario.html
    # con un set de variables compatible.
    return render_template('inventario.html',
                           items=libros,
                           estudiantes=Estudiante.query.filter_by(activo=True).all(),
                           prestamos=Prestamo.query.join(Item).filter(
                               Item.especialidad_id == bib.id
                           ).order_by(Prestamo.fecha_prestamo.desc()).limit(100).all(),
                           prestamos_externos=[],
                           ordenes_trabajo=[],
                           profesores=Usuario.query.filter(Usuario.rol == 'Profesor').all(),
                           usuarios_sistema=[],
                           practicas_resumen=[],
                           total_stock=sum(l.cantidad_total for l in libros),
                           prestamos_activos=Prestamo.query.join(Item).filter(
                               Item.especialidad_id == bib.id,
                               Prestamo.estado == 'Pendiente'
                           ).count(),
                           alertas=[],
                           especialidad='Biblioteca')


@app.route('/biblioteca/atrasados')
@login_requerido
def biblioteca_atrasados():
    """Devuelve JSON con los préstamos atrasados (días > 0)."""
    bib = Especialidad.query.filter_by(nombre='Biblioteca').first()
    if not bib:
        return jsonify({'atrasados': [], 'total': 0})

    pendientes = Prestamo.query.join(Item).filter(
        Item.especialidad_id == bib.id,
        Prestamo.estado == 'Pendiente',
        Prestamo.fecha_devolucion_esperada.isnot(None)
    ).all()

    atrasados = []
    for p in pendientes:
        if p.dias_atraso > 0:
            atrasados.append({
                'prestamo_id': p.id,
                'libro': p.item.nombre,
                'autor': p.item.autor or '',
                'isbn': p.item.isbn or '',
                'estudiante': p.estudiante.nombre if p.estudiante else '',
                'curso': p.estudiante.curso if p.estudiante else '',
                'fecha_prestamo': p.fecha_prestamo.strftime('%Y-%m-%d'),
                'fecha_limite': p.fecha_devolucion_esperada.strftime('%Y-%m-%d'),
                'dias_atraso': p.dias_atraso,
            })
    return jsonify({'atrasados': atrasados, 'total': len(atrasados)})


@app.route('/agregar_libro', methods=['POST'])
@login_requerido
@pañolero_o_admin
def agregar_libro():
    """Alta de libro con campos bibliográficos completos."""
    bib = Especialidad.query.filter_by(nombre='Biblioteca').first()
    if not bib:
        flash("❌ La especialidad Biblioteca no existe.")
        return redirect(url_for('ver_inventario'))

    titulo = (request.form.get('nombre') or '').strip()
    if not titulo:
        flash("❌ Falta el título del libro.")
        return redirect(url_for('biblioteca_catalogo'))

    isbn = (request.form.get('isbn') or '').strip() or None
    autor = (request.form.get('autor') or '').strip() or None
    editorial = (request.form.get('editorial') or '').strip() or None
    try:
        anio = int(request.form.get('anio_publicacion') or 0) or None
    except Exception:
        anio = None
    cantidad = int(request.form.get('cantidad') or 1)
    ubicacion = (request.form.get('ubicacion') or 'Sin especificar').strip()

    # Si el ISBN existe en biblioteca, sumar stock
    existente = None
    if isbn:
        existente = Item.query.filter_by(especialidad_id=bib.id, isbn=isbn).first()
    if existente:
        existente.cantidad_total += cantidad
        existente.cantidad_disponible += cantidad
        item_id = existente.id
        accion = 'actualizar'
    else:
        codigo = isbn or datetime.now().strftime('%y%m%d%H%M%S') + "L"
        nuevo = Item(
            codigo_barras=codigo, nombre=titulo, categoria='Biblioteca',
            especialidad_id=bib.id,
            cantidad_total=cantidad, cantidad_disponible=cantidad,
            ubicacion=ubicacion,
            autor=autor, isbn=isbn, editorial=editorial, anio_publicacion=anio,
        )
        db.session.add(nuevo)
        db.session.flush()
        item_id = nuevo.id
        accion = 'crear'
    db.session.commit()
    registrar_auditoria(accion, 'Item', item_id,
                        valores_nuevos={'titulo': titulo, 'autor': autor, 'isbn': isbn})
    flash(f"✅ Libro '{titulo}' registrado.")
    return redirect(url_for('biblioteca_catalogo'))


# ========================================================================
# OFICINA: registro de consumos (sin devolución)
# ========================================================================

@app.route('/registrar_consumo', methods=['POST'])
@login_requerido
@pañolero_o_admin
def registrar_consumo():
    """Registra un consumo de oficina. Descuenta del stock TOTAL (no vuelve)."""
    codigo = (request.form.get('codigo_item') or '').strip()
    cantidad = int(request.form.get('cantidad') or 1)
    persona = (request.form.get('persona_retira') or '').strip()
    motivo = (request.form.get('motivo') or '').strip()

    especialidad_id = session.get('usuario_especialidad_id')
    item = Item.query.filter_by(codigo_barras=codigo, especialidad_id=especialidad_id).first()
    if not item:
        flash(f"❌ Ítem '{codigo}' no existe en este pañol/área.")
        return redirect(url_for('ver_inventario'))
    if item.cantidad_disponible < cantidad:
        flash(f"❌ Stock insuficiente: {item.cantidad_disponible}.")
        return redirect(url_for('ver_inventario'))
    if not persona:
        flash("❌ Indica quién retira el consumible.")
        return redirect(url_for('ver_inventario'))

    item.cantidad_disponible -= cantidad
    item.cantidad_total -= cantidad

    consumo = PrestamoExterno(
        item_id=item.id, especialidad_id=especialidad_id,
        cantidad=cantidad, es_alumno=False,
        persona_retira=persona, profesor_cargo='',
        especialidad_destino=motivo or 'Consumo interno',
        encargado=session.get('usuario_nombre'),
        estado='Consumido', tipo_movimiento='consumo',
        fecha_devolucion=datetime.utcnow()
    )
    db.session.add(consumo)
    db.session.commit()
    registrar_auditoria('consumir', 'Item', item.id,
                        valores_nuevos={'item': item.nombre, 'cantidad': cantidad, 'persona': persona})
    flash(f"✅ Consumo registrado: {cantidad} × {item.nombre} → {persona}.")
    return redirect(url_for('ver_inventario'))


# ========================================================================
# API DE SINCRONIZACIÓN (solo cuando ES_ADMIN_CENTRAL)
# ========================================================================

def _verificar_token_sync():
    """Lee el header Authorization y valida contra PANOL_SYNC_TOKEN."""
    auth = request.headers.get('Authorization', '')
    if not auth.startswith('Bearer '):
        return False
    return auth[7:].strip() == PANOL_SYNC_TOKEN


@app.route('/api/sync/push', methods=['POST'])
def api_sync_push():
    """Recibe un lote de cambios desde un nodo. Solo el admin central acepta esto.

    Body JSON: {
      "nodo": "panol_electronica",
      "cambios": [
        {"sync_uuid": "...", "tabla": "item", "registro_id_local": 12,
         "accion": "crear", "payload": {...}},
        ...
      ]
    }
    Respuesta: {"ok": [uuid,...], "error": {uuid: msg, ...}}
    """
    if not ES_ADMIN_CENTRAL:
        return jsonify({'error': 'Este nodo no es admin central'}), 403
    if not _verificar_token_sync():
        return jsonify({'error': 'Token inválido'}), 401

    try:
        data = request.get_json(force=True)
    except Exception:
        return jsonify({'error': 'JSON inválido'}), 400

    nodo = (data or {}).get('nodo', 'desconocido')
    cambios = (data or {}).get('cambios', [])

    ok_uuids = []
    err_map = {}

    for ch in cambios:
        uid = ch.get('sync_uuid')
        try:
            _aplicar_cambio_remoto(nodo, ch)
            ok_uuids.append(uid)
        except Exception as e:
            err_map[uid] = f"{type(e).__name__}: {e}"
            db.session.rollback()

    db.session.commit()
    return jsonify({'ok': ok_uuids, 'error': err_map,
                    'recibidos': len(cambios), 'aplicados': len(ok_uuids)})


def _aplicar_cambio_remoto(nodo, ch):
    """Aplica un cambio recibido desde un nodo en la BD del admin central.

    Estrategia: localiza el registro por (nodo + registro_id_local) usando código de barras
    o RUT como clave natural cuando aplica. Si no existe, lo crea. Si existe, actualiza.
    """
    tabla = ch['tabla']
    accion = ch['accion']
    payload = ch.get('payload') or {}

    # Idempotencia: si ya recibimos este sync_uuid, ignorar
    uid = ch.get('sync_uuid')
    if uid:
        existente_uuid = SyncLog.query.filter_by(sync_uuid=uid).first()
        if existente_uuid and existente_uuid.push_status == 'aplicado':
            return  # ya lo aplicamos antes
        if not existente_uuid:
            db.session.add(SyncLog(
                nodo_origen=nodo, tabla=tabla,
                registro_id_local=ch.get('registro_id_local', 0),
                accion=accion,
                payload=json.dumps(payload),
                sync_uuid=uid,
                push_status='aplicado',
            ))

    if tabla == 'item':
        _upsert_item(nodo, payload, accion)
    elif tabla == 'estudiante':
        _upsert_estudiante(nodo, payload, accion)
    elif tabla == 'prestamo':
        _upsert_prestamo(nodo, payload, accion)
    elif tabla == 'prestamo_externo':
        _upsert_prestamo_externo(nodo, payload, accion)
    elif tabla == 'orden_trabajo':
        _upsert_orden_trabajo(nodo, payload, accion)
    else:
        raise ValueError(f"Tabla {tabla} no soportada")


def _to_dt(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None


def _upsert_item(nodo, p, accion):
    """Localiza item por código de barras + especialidad_id, o crea."""
    codigo = p.get('codigo_barras')
    esp_id = p.get('especialidad_id')
    item = None
    if codigo and esp_id:
        item = Item.query.filter_by(codigo_barras=codigo, especialidad_id=esp_id).first()
    if accion == 'eliminar':
        if item:
            db.session.delete(item)
        return
    if not item:
        item = Item(codigo_barras=codigo, especialidad_id=esp_id, nombre=p.get('nombre', ''))
        db.session.add(item)
    # Copiar campos seguros (no id)
    for k in ('nombre', 'descripcion', 'categoria', 'cantidad_total',
              'cantidad_disponible', 'cantidad_mermada', 'cantidad_minima',
              'imagen_url', 'ubicacion', 'precio_unitario', 'desgaste',
              'autor', 'isbn', 'editorial', 'anio_publicacion',
              'marca', 'modelo', 'numero_serie', 'estado',
              'fecha_adquisicion', 'max_usos'):
        if k in p:
            setattr(item, k, p[k])


def _upsert_estudiante(nodo, p, accion):
    rut = p.get('rut_matricula')
    if not rut:
        raise ValueError("Estudiante sin RUT")
    est = Estudiante.query.filter_by(rut_matricula=rut).first()
    if not est:
        est = Estudiante(rut_matricula=rut, nombre=p.get('nombre', ''),
                         especialidad_id=p.get('especialidad_id'),
                         password_hash=p.get('password_hash', generate_password_hash(rut)))
        db.session.add(est)
    for k in ('nombre', 'curso', 'especialidad_id', 'activo', 'password_hash'):
        if k in p:
            setattr(est, k, p[k])


def _upsert_prestamo(nodo, p, accion):
    """Para préstamos: usamos clave compuesta (nodo, registro_id_local) almacenada como prefijo."""
    # Mapeamos local id a un registro en el admin con descripción única
    encargado_marker = f"[{nodo}#{p.get('id')}] " + (p.get('encargado') or '')
    pres = Prestamo.query.filter(Prestamo.encargado.like(f"[{nodo}#{p.get('id')}]%")).first()

    item = None
    if p.get('item_id'):
        # En el admin no podemos usar el item_id local; tenemos que resolver por código.
        # Asumimos que el item ya fue sincronizado antes. Si no existe, fallamos suave.
        # (Una mejora futura: incluir codigo_barras en el payload del préstamo.)
        item = Item.query.get(p.get('item_id'))
    if not item:
        # Sin item válido no podemos persistir un préstamo nuevo
        if not pres:
            raise ValueError(f"Item local {p.get('item_id')} no encontrado en admin")

    if not pres:
        pres = Prestamo(item_id=item.id if item else 0,
                        estudiante_id=p.get('estudiante_id') or 0,
                        cantidad=p.get('cantidad') or 1,
                        encargado=encargado_marker)
        db.session.add(pres)
    for k in ('cantidad', 'cantidad_solicitada', 'cantidad_mermada',
              'nombre_practica', 'estado', 'multa'):
        if k in p:
            setattr(pres, k, p[k])
    pres.fecha_prestamo = _to_dt(p.get('fecha_prestamo')) or pres.fecha_prestamo
    pres.fecha_devolucion = _to_dt(p.get('fecha_devolucion'))
    pres.fecha_devolucion_esperada = _to_dt(p.get('fecha_devolucion_esperada'))


def _upsert_prestamo_externo(nodo, p, accion):
    marker = f"[{nodo}#{p.get('id')}]"
    pe = PrestamoExterno.query.filter(PrestamoExterno.encargado.like(f"{marker}%")).first()
    if not pe:
        pe = PrestamoExterno(item_id=p.get('item_id') or 0,
                             especialidad_id=p.get('especialidad_id') or 0,
                             cantidad=p.get('cantidad') or 1,
                             persona_retira=p.get('persona_retira') or '',
                             encargado=f"{marker} {p.get('encargado') or ''}")
        db.session.add(pe)
    for k in ('cantidad', 'es_alumno', 'persona_retira', 'profesor_cargo',
              'especialidad_destino', 'estado', 'tipo_movimiento'):
        if k in p:
            setattr(pe, k, p[k])
    pe.fecha_prestamo = _to_dt(p.get('fecha_prestamo')) or pe.fecha_prestamo
    pe.fecha_devolucion = _to_dt(p.get('fecha_devolucion'))


def _upsert_orden_trabajo(nodo, p, accion):
    marker = f"[{nodo}#{p.get('id')}]"
    ot = OrdenTrabajo.query.filter(OrdenTrabajo.titulo.like(f"{marker}%")).first()
    if not ot:
        ot = OrdenTrabajo(titulo=f"{marker} {p.get('titulo') or ''}",
                          especialidad_id=p.get('especialidad_id') or 0,
                          profesional_cargo=p.get('profesional_cargo') or '',
                          profesor_id=p.get('profesor_id') or 0)
        db.session.add(ot)
    for k in ('descripcion', 'alumnos_cargo', 'herramientas_utilizadas',
              'repuestos_utilizados', 'estado'):
        if k in p:
            setattr(ot, k, p[k])


@app.route('/api/sync/status')
def api_sync_status():
    """Estado del sistema de sync. Útil para que un nodo sepa si el admin está vivo."""
    if not _verificar_token_sync():
        return jsonify({'error': 'Token inválido'}), 401
    info = {
        'es_admin_central': ES_ADMIN_CENTRAL,
        'nodo_id': NODO_ID,
        'fecha_servidor': datetime.utcnow().isoformat(),
    }
    if ES_ADMIN_CENTRAL:
        info['cambios_recibidos'] = SyncLog.query.filter_by(push_status='aplicado').count()
    else:
        info['cambios_pendientes'] = SyncLog.query.filter_by(push_status='pendiente').count()
        info['cambios_enviados'] = SyncLog.query.filter_by(push_status='enviado').count()
        info['cambios_error'] = SyncLog.query.filter_by(push_status='error').count()
    return jsonify(info)


# Alias para mantener compatibilidad con la plantilla
@app.route('/exportar_inventario')
@login_requerido
def exportar_inventario():
    return exportar_excel()


@app.route('/descargar_plantilla_alumnos')
@login_requerido
def descargar_plantilla_alumnos():
    """Descarga la plantilla Excel para carga masiva de alumnos."""
    aqui = os.path.dirname(os.path.abspath(__file__))
    plantilla = os.path.join(aqui, 'alumnos_muestra.xlsx')
    if not os.path.exists(plantilla):
        # Generar plantilla mínima al vuelo
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.title = 'Alumnos'
        for c, h in enumerate(['RUT / Matrícula', 'Nombre completo', 'Curso', 'Email'], 1):
            ws.cell(row=1, column=c, value=h)
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        return send_file(buf, as_attachment=True,
                         download_name='plantilla_alumnos.xlsx',
                         mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    return send_file(plantilla, as_attachment=True,
                     download_name='plantilla_alumnos.xlsx')


@app.route('/descargar_plantilla')
@login_requerido
def descargar_plantilla():
    """Descarga el archivo inventario_muestra.xlsx como plantilla."""
    aqui = os.path.dirname(os.path.abspath(__file__))
    plantilla = os.path.join(aqui, 'inventario_muestra.xlsx')
    if not os.path.exists(plantilla):
        # Si no está, generamos una plantilla mínima al vuelo (13 columnas A–M, mismo orden que /cargar_excel)
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill, Alignment
        wb = Workbook()
        ws = wb.active
        ws.title = 'Inventario'
        headers = ['Código de barra', 'Nombre', 'Descripción', 'Marca', 'Modelo',
                   'Categoría', 'Cantidad', 'Ubicación', 'Fecha adquisición',
                   'Desgaste ($)', 'Costo unitario ($)', 'Costo total ($)',
                   'Imagen de referencia']
        for c, h in enumerate(headers, 1):
            cell = ws.cell(row=1, column=c, value=h)
            cell.font = Font(bold=True, color='FFFFFF')
            cell.fill = PatternFill(start_color='1E3A8A', end_color='1E3A8A', fill_type='solid')
            cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
        ws.row_dimensions[1].height = 30
        ws.freeze_panes = 'A2'
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        return send_file(buf, as_attachment=True,
                         download_name='plantilla_inventario.xlsx',
                         mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    return send_file(plantilla, as_attachment=True,
                     download_name='plantilla_inventario.xlsx')



@app.route('/etiqueta/<int:item_id>')
@login_requerido
def etiqueta_item(item_id):
    """Vista imprimible con código de barras Code128 del ítem (4 copias por defecto)."""
    item = Item.query.get_or_404(item_id)
    if session.get('usuario_rol') != 'Admin' and item.especialidad_id != session.get('usuario_especialidad_id'):
        flash("❌ No tienes acceso a este ítem.")
        return redirect(url_for('ver_inventario'))
    return render_template('etiqueta.html', item=item,
                           especialidad=item.especialidad.nombre if item.especialidad else '',
                           now=datetime.now().strftime('%d/%m/%Y'))


# ========================================================================
# RUTAS DE ADMINISTRADOR CENTRAL (vistas globales y reportes)
# ========================================================================

@app.route('/admin/buscar')
@login_requerido
@admin_requerido
def admin_buscar_items():
    """Buscador global de ítems (en las 8 áreas)."""
    q = (request.args.get('q') or '').strip()
    if not q:
        return render_template('admin_buscar.html', items=[], q='')
    like = f"%{q}%"
    items = Item.query.filter(
        db.or_(
            Item.nombre.ilike(like),
            Item.codigo_barras.ilike(like),
            Item.autor.ilike(like) if hasattr(Item, 'autor') else False,
            Item.isbn.ilike(like) if hasattr(Item, 'isbn') else False,
        )
    ).order_by(Item.especialidad_id.asc(), Item.nombre.asc()).limit(200).all()
    return render_template('admin_buscar.html', items=items, q=q)



# ------------------------------------------------------------------
# Endpoints de administrador (stubs temporales).
# El archivo original venia truncado; estos stubs garantizan que la
# app levante. Reemplazar con las implementaciones reales cuando se
# necesiten.
# ------------------------------------------------------------------

@app.route('/admin/exportar_completo')
@login_requerido
@admin_requerido
def admin_exportar_completo():
    """Exporta TODO el inventario consolidado por area (placeholder)."""
    items = Item.query.order_by(Item.especialidad_id.asc(),
                                Item.categoria.asc(), Item.nombre.asc()).all()
    df = pd.DataFrame([{
        'Especialidad':   i.especialidad.nombre if i.especialidad else '',
        'Codigo':         i.codigo_barras,
        'Nombre':         i.nombre,
        'Categoria':      i.categoria,
        'Cantidad total': i.cantidad_total,
        'Disponible':     i.cantidad_disponible,
        'Mermada':        i.cantidad_mermada,
        'Ubicacion':      i.ubicacion,
        'Costo unitario': i.precio_unitario or 0,
        'Desgaste $':     i.desgaste or 0,
        'Costo total':    (i.precio_unitario or 0) * (i.cantidad_total or 0),
    } for i in items])
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='Consolidado', index=False)
    buf.seek(0)
    fname = f"inventario_consolidado_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
    return send_file(buf, as_attachment=True, download_name=fname,
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


@app.route('/admin/reporte_mermas')
@login_requerido
@admin_requerido
def admin_reporte_mermas():
    """Reporte de mermas (placeholder). Reescribir cuando se necesite."""
    flash("Reporte de mermas: funcion en construccion.")
    return redirect(url_for('ver_inventario'))


if __name__ == '__main__':
    import threading, webbrowser, sys
    es_exe = getattr(sys, 'frozen', False)
    def abrir_navegador():
        import time; time.sleep(1.5)
        webbrowser.open('http://127.0.0.1:8080')
    PORT = 8080
    if es_exe:
        threading.Thread(target=abrir_navegador, daemon=True).start()
        app.run(host='127.0.0.1', port=PORT, debug=False, use_reloader=False)
    else:
        app.run(host='127.0.0.1', port=PORT, debug=True)
