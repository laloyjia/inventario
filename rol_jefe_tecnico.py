"""Rol Jefe Técnico: acceso de solo lectura con capacidad de dejar observaciones.

Este módulo separado registra en la app Flask:
  - El modelo ComentarioSupervision (tabla para observaciones/comentarios).
  - Los decoradores de acceso combinado (Admin + Jefe Técnico).
  - Las rutas para crear/listar/resolver comentarios.
  - La creación automática del usuario 'jefe_tecnico' si no existe.

Uso: en app.py, tras crear los modelos, llamar a
    registrar_rol_jefe_tecnico(app, db, Usuario, Especialidad, Item, OrdenTrabajo,
                                login_requerido, registrar_auditoria,
                                generate_password_hash)
"""
from flask import request, session, flash, redirect, url_for, render_template
from datetime import datetime
from functools import wraps


def registrar_rol_jefe_tecnico(app, db, Usuario, Especialidad, Item,
                                OrdenTrabajo, login_requerido,
                                registrar_auditoria, generate_password_hash):
    """Registra el rol JT completo en la app Flask."""

    # ─────────────────────────────────────────────────────────────
    # MODELO: ComentarioSupervision
    # ─────────────────────────────────────────────────────────────
    class ComentarioSupervision(db.Model):
        __tablename__ = 'comentario_supervision'
        id = db.Column(db.Integer, primary_key=True)
        autor_id = db.Column(db.Integer, db.ForeignKey('usuario.id'),
                              nullable=False)
        # Contexto al que apunta el comentario. Ejemplos: 'Item', 'OrdenTrabajo',
        # 'Especialidad', 'General'
        tabla = db.Column(db.String(50), nullable=False)
        registro_id = db.Column(db.Integer, nullable=True)
        # Para agrupar comentarios de la misma especialidad
        especialidad_id = db.Column(db.Integer,
                                    db.ForeignKey('especialidad.id'),
                                    nullable=True, index=True)
        contenido = db.Column(db.Text, nullable=False)
        fecha = db.Column(db.DateTime, default=datetime.utcnow, index=True)
        resuelto = db.Column(db.Boolean, default=False, nullable=False)
        resuelto_por_id = db.Column(db.Integer,
                                    db.ForeignKey('usuario.id'), nullable=True)
        fecha_resuelto = db.Column(db.DateTime, nullable=True)
        respuesta = db.Column(db.Text, nullable=True)

        autor = db.relationship('Usuario', foreign_keys=[autor_id],
                                 backref='comentarios_hechos', lazy=True)
        resolutor = db.relationship('Usuario',
                                     foreign_keys=[resuelto_por_id], lazy=True)
        especialidad = db.relationship('Especialidad', lazy=True)

    # NOTA: la creacion de tabla se delega al db.create_all() principal
    # del app.py para evitar doble inicializacion en modulos importados.

    # ─────────────────────────────────────────────────────────────
    # USUARIO POR DEFECTO: jefe_tecnico
    # ─────────────────────────────────────────────────────────────
    def crear_jefe_tecnico():
        # Asegura que la tabla comentario_supervision exista. Es necesario porque
        # este modelo se registra DESPUÉS del db.create_all() principal de app.py,
        # así que en una BD nueva la tabla no se crearía al arranque. create_all
        # es idempotente: solo crea lo que falta.
        db.create_all()
        if not Usuario.query.filter_by(username='jefe_tecnico').first():
            db.session.add(Usuario(
                nombre="Jefe Técnico UTP",
                username="jefe_tecnico",
                password_hash=generate_password_hash("jefe123"),
                rol="JefeTecnico",
                email="jefe.tecnico@colegio.local",
                especialidad_id=None,
                must_change_password=True,
            ))
            db.session.commit()

    # Creacion perezosa del usuario JT: se hace en el primer request
    # via before_first_request para asegurar que las tablas esten listas.
    _jt_creado = {'v': False}
    @app.before_request
    def _crear_jt_lazy():
        if _jt_creado['v']:
            return
        try:
            crear_jefe_tecnico()
        except Exception as e:
            print(f'[JT] No se pudo crear jefe_tecnico automaticamente: {e}')
        _jt_creado['v'] = True

    # ─────────────────────────────────────────────────────────────
    # DECORADORES
    # ─────────────────────────────────────────────────────────────
    def jt_o_admin(f):
        """Permite acceso a Admin y JefeTecnico."""
        @wraps(f)
        def w(*a, **kw):
            if session.get('usuario_rol') not in ('Admin', 'JefeTecnico'):
                flash("❌ Acceso denegado. Requiere Administrador o Jefe Técnico.")
                return redirect(url_for('login'))
            return f(*a, **kw)
        return w

    # Exponer decorador al resto de la app
    app.jinja_env.globals['ROL_JT'] = 'JefeTecnico'
    app.config['DECORADOR_JT_O_ADMIN'] = jt_o_admin

    # ─────────────────────────────────────────────────────────────
    # RUTAS: comentarios de supervisión
    # ─────────────────────────────────────────────────────────────
    @app.route('/supervision/comentarios')
    @login_requerido
    @jt_o_admin
    def ver_comentarios():
        """Lista de comentarios/observaciones de supervisión.

        Alcance visual del JT: solo especialidades técnico-profesionales
        (tipo_area PANOL_TP). El Admin ve todo.
        """
        rol = session.get('usuario_rol')
        # Especialidades visibles según rol
        q_esp = Especialidad.query
        if rol == 'JefeTecnico':
            q_esp = q_esp.filter(Especialidad.tipo_area == 'PANOL_TP')
        especialidades = q_esp.order_by(Especialidad.nombre).all()
        ids_visibles = [e.id for e in especialidades]

        f_esp = request.args.get('especialidad_id', type=int)
        # Si el JT pide una especialidad fuera de su alcance, la ignora
        if f_esp and rol == 'JefeTecnico' and f_esp not in ids_visibles:
            f_esp = None
        f_estado = request.args.get('estado', 'pendientes')

        q = ComentarioSupervision.query
        if rol == 'JefeTecnico' and ids_visibles:
            # JT solo ve observaciones ligadas a sus especialidades o generales
            q = q.filter(
                (ComentarioSupervision.especialidad_id.in_(ids_visibles)) |
                (ComentarioSupervision.especialidad_id.is_(None))
            )
        if f_esp:
            q = q.filter_by(especialidad_id=f_esp)
        if f_estado == 'pendientes':
            q = q.filter_by(resuelto=False)
        elif f_estado == 'resueltos':
            q = q.filter_by(resuelto=True)
        comentarios = q.order_by(ComentarioSupervision.fecha.desc()).limit(200).all()

        # ── KPIs de cabecera (alcance = especialidades visibles del rol) ──
        if ids_visibles:
            total_items_v = Item.query.filter(
                Item.especialidad_id.in_(ids_visibles)).count()
        else:
            total_items_v = Item.query.count()
        q_all = ComentarioSupervision.query
        if rol == 'JefeTecnico' and ids_visibles:
            q_all = q_all.filter(
                (ComentarioSupervision.especialidad_id.in_(ids_visibles)) |
                (ComentarioSupervision.especialidad_id.is_(None))
            )
        jt_stats = {
            'areas': len(especialidades),
            'items': total_items_v,
            'abiertas': q_all.filter_by(resuelto=False).count(),
            'resueltas': q_all.filter_by(resuelto=True).count(),
        }

        return render_template('comentarios_supervision.html',
                                comentarios=comentarios,
                                especialidades=especialidades,
                                filtro_esp=f_esp,
                                filtro_estado=f_estado,
                                jt_stats=jt_stats)

    @app.route('/supervision/comentar', methods=['POST'])
    @login_requerido
    @jt_o_admin
    def crear_comentario():
        tabla = (request.form.get('tabla') or 'General').strip()
        registro_id = request.form.get('registro_id', type=int)
        especialidad_id = request.form.get('especialidad_id', type=int)
        contenido = (request.form.get('contenido') or '').strip()
        if not contenido:
            flash("⚠️ El comentario está vacío.")
            return redirect(request.referrer or url_for('ver_comentarios'))
        c = ComentarioSupervision(
            autor_id=session.get('usuario_id'),
            tabla=tabla,
            registro_id=registro_id,
            especialidad_id=especialidad_id,
            contenido=contenido[:2000],
        )
        db.session.add(c)
        db.session.commit()
        registrar_auditoria('crear', 'ComentarioSupervision', c.id,
                            valores_nuevos={
                                'tabla': tabla,
                                'contenido': contenido[:200],
                            })
        flash("✅ Observación registrada.")
        return redirect(request.referrer or url_for('ver_comentarios'))

    @app.route('/supervision/resolver/<int:c_id>', methods=['POST'])
    @login_requerido
    def resolver_comentario(c_id):
        c = ComentarioSupervision.query.get_or_404(c_id)
        # Solo Admin, JT o el propio autor pueden marcar resuelto
        rol = session.get('usuario_rol')
        if rol not in ('Admin', 'JefeTecnico') and session.get('usuario_id') != c.autor_id:
            flash("❌ Sin permiso para resolver este comentario.")
            return redirect(url_for('ver_comentarios'))
        respuesta = (request.form.get('respuesta') or '').strip()
        c.resuelto = True
        c.resuelto_por_id = session.get('usuario_id')
        c.fecha_resuelto = datetime.utcnow()
        c.respuesta = respuesta[:2000] or None
        db.session.commit()
        registrar_auditoria('resolver', 'ComentarioSupervision', c.id,
                            valores_nuevos={'respuesta': respuesta[:200]})
        flash("✅ Observación marcada como resuelta.")
        return redirect(url_for('ver_comentarios'))

    return ComentarioSupervision, jt_o_admin
