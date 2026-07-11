"""Dashboard moderno unificado para Admin y Jefe Tecnico."""
from flask import request, session, render_template
from datetime import datetime, timedelta
from sqlalchemy import func

TIPOS_AREA_JT = ('PANOL_TP',)


def registrar_dashboard_moderno(app, db, Item, Especialidad, Prestamo,
                                 PrestamoExterno, Estudiante, Usuario,
                                 OrdenTrabajo, Auditoria, login_requerido,
                                 jt_o_admin):

    def _especialidades_visibles(rol):
        q = Especialidad.query
        if rol == 'JefeTecnico':
            q = q.filter(Especialidad.tipo_area.in_(TIPOS_AREA_JT))
        return q.order_by(Especialidad.nombre).all()

    @app.route('/dashboard')
    @login_requerido
    @jt_o_admin
    def dashboard_moderno():
        rol = session.get('usuario_rol')
        especialidades = _especialidades_visibles(rol)
        ids_vis = [e.id for e in especialidades]
        es_jt = (rol == 'JefeTecnico')

        f_esp = request.args.get('especialidad_id', type=int)
        if f_esp and es_jt and f_esp not in ids_vis:
            f_esp = None

        def scope_item(q):
            if f_esp:
                return q.filter(Item.especialidad_id == f_esp)
            if es_jt and ids_vis:
                return q.filter(Item.especialidad_id.in_(ids_vis))
            return q

        def scope_prestamo(q):
            if f_esp:
                return q.join(Item, Prestamo.item_id == Item.id).filter(
                    Item.especialidad_id == f_esp)
            if es_jt and ids_vis:
                return q.join(Item, Prestamo.item_id == Item.id).filter(
                    Item.especialidad_id.in_(ids_vis))
            return q

        total_items = scope_item(Item.query).count()
        valor_total = int(scope_item(db.session.query(
            func.coalesce(func.sum(Item.precio_unitario * Item.cantidad_total), 0.0)
        )).scalar() or 0)
        stock_total = int(scope_item(db.session.query(
            func.coalesce(func.sum(Item.cantidad_total), 0))).scalar() or 0)
        stock_disponible = int(scope_item(db.session.query(
            func.coalesce(func.sum(Item.cantidad_disponible), 0))).scalar() or 0)
        prestamos_activos = scope_prestamo(
            Prestamo.query.filter(Prestamo.estado == 'Pendiente')).count()

        hoy = datetime.utcnow()
        inicio_mes = hoy.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        merma_mes = int(scope_prestamo(db.session.query(
            func.coalesce(func.sum(Prestamo.cantidad_mermada), 0)
        ).filter(Prestamo.fecha_prestamo >= inicio_mes)).scalar() or 0)

        q_alumnos = Estudiante.query.filter_by(activo=True)
        if f_esp:
            q_alumnos = q_alumnos.filter_by(especialidad_id=f_esp)
        elif es_jt and ids_vis:
            q_alumnos = q_alumnos.filter(Estudiante.especialidad_id.in_(ids_vis))
        total_alumnos = q_alumnos.count()

        hace_30 = hoy - timedelta(days=30)
        movimientos = {}
        for d in range(30, -1, -1):
            fecha = (hoy - timedelta(days=d)).date()
            movimientos[fecha.isoformat()] = {'prestamos': 0, 'devoluciones': 0}

        def scope_series(q):
            if f_esp:
                return q.join(Item, Prestamo.item_id == Item.id).filter(
                    Item.especialidad_id == f_esp)
            if es_jt and ids_vis:
                return q.join(Item, Prestamo.item_id == Item.id).filter(
                    Item.especialidad_id.in_(ids_vis))
            return q

        q_p = scope_series(db.session.query(
            func.date(Prestamo.fecha_prestamo).label('d'),
            func.count(Prestamo.id).label('n'),
        ).filter(Prestamo.fecha_prestamo >= hace_30)).group_by('d')
        for r in q_p.all():
            k = r.d.isoformat() if hasattr(r.d, 'isoformat') else str(r.d)
            if k in movimientos:
                movimientos[k]['prestamos'] = int(r.n)

        q_d = scope_series(db.session.query(
            func.date(Prestamo.fecha_devolucion).label('d'),
            func.count(Prestamo.id).label('n'),
        ).filter(Prestamo.fecha_devolucion >= hace_30,
                 Prestamo.estado == 'Devuelto')).group_by('d')
        for r in q_d.all():
            k = r.d.isoformat() if hasattr(r.d, 'isoformat') else str(r.d)
            if k in movimientos:
                movimientos[k]['devoluciones'] = int(r.n)

        series_labels = list(movimientos.keys())
        series_prestamos = [movimientos[k]['prestamos'] for k in series_labels]
        series_devoluciones = [movimientos[k]['devoluciones'] for k in series_labels]

        # Top 10 mas prestados - filter ANTES de limit
        q_top = db.session.query(
            Item.id, Item.nombre, Item.codigo_barras,
            func.count(Prestamo.id).label('total'),
        ).join(Prestamo, Prestamo.item_id == Item.id
        ).filter(Prestamo.fecha_prestamo >= hace_30)
        if f_esp:
            q_top = q_top.filter(Item.especialidad_id == f_esp)
        elif es_jt and ids_vis:
            q_top = q_top.filter(Item.especialidad_id.in_(ids_vis))
        q_top = q_top.group_by(Item.id, Item.nombre, Item.codigo_barras
        ).order_by(func.count(Prestamo.id).desc()).limit(10)
        top_prestados = q_top.all()

        q_merma = Item.query.filter(Item.cantidad_mermada > 0)
        if f_esp:
            q_merma = q_merma.filter(Item.especialidad_id == f_esp)
        elif es_jt and ids_vis:
            q_merma = q_merma.filter(Item.especialidad_id.in_(ids_vis))
        top_mermados = q_merma.order_by(Item.cantidad_mermada.desc()).limit(10).all()

        comparativa = []
        if not f_esp:
            for esp in especialidades:
                n_items = Item.query.filter_by(especialidad_id=esp.id).count()
                valor = db.session.query(
                    func.coalesce(func.sum(Item.precio_unitario * Item.cantidad_total), 0.0)
                ).filter(Item.especialidad_id == esp.id).scalar() or 0
                prestamos_esp = Prestamo.query.join(Item).filter(
                    Item.especialidad_id == esp.id,
                    Prestamo.estado == 'Pendiente'
                ).count()
                comparativa.append({
                    'id': esp.id, 'nombre': esp.nombre,
                    'tipo_area': esp.tipo_area or 'GENERAL',
                    'n_items': n_items, 'valor': int(valor),
                    'prestamos_activos': prestamos_esp,
                })

        tipos_dist = {}
        q_tipos = db.session.query(
            Especialidad.tipo_area, func.count(Item.id).label('n'),
        ).join(Item, Item.especialidad_id == Especialidad.id)
        if es_jt and ids_vis:
            q_tipos = q_tipos.filter(Especialidad.id.in_(ids_vis))
        if f_esp:
            q_tipos = q_tipos.filter(Especialidad.id == f_esp)
        q_tipos = q_tipos.group_by(Especialidad.tipo_area)
        for r in q_tipos.all():
            tipos_dist[r.tipo_area or 'GENERAL'] = int(r.n)

        heatmap = [[0] * 24 for _ in range(7)]
        q_hm = Prestamo.query.filter(Prestamo.fecha_prestamo >= hace_30)
        if f_esp:
            q_hm = q_hm.join(Item).filter(Item.especialidad_id == f_esp)
        elif es_jt and ids_vis:
            q_hm = q_hm.join(Item).filter(Item.especialidad_id.in_(ids_vis))
        for p in q_hm.all():
            if p.fecha_prestamo:
                heatmap[p.fecha_prestamo.weekday()][p.fecha_prestamo.hour] += 1

        q_ult = Prestamo.query
        if f_esp:
            q_ult = q_ult.join(Item).filter(Item.especialidad_id == f_esp)
        elif es_jt and ids_vis:
            q_ult = q_ult.join(Item).filter(Item.especialidad_id.in_(ids_vis))
        ultimos_movimientos = q_ult.order_by(
            Prestamo.fecha_prestamo.desc()).limit(15).all()

        q_sb = Item.query.filter(Item.cantidad_disponible < Item.cantidad_minima)
        if f_esp:
            q_sb = q_sb.filter(Item.especialidad_id == f_esp)
        elif es_jt and ids_vis:
            q_sb = q_sb.filter(Item.especialidad_id.in_(ids_vis))
        stock_bajo = q_sb.order_by(Item.cantidad_disponible.asc()).limit(10).all()

        q_ot = OrdenTrabajo.query.filter_by(estado='En Curso')
        if f_esp:
            q_ot = q_ot.filter_by(especialidad_id=f_esp)
        elif es_jt and ids_vis:
            q_ot = q_ot.filter(OrdenTrabajo.especialidad_id.in_(ids_vis))
        ot_pendientes = q_ot.count()

        esp_actual = Especialidad.query.get(f_esp) if f_esp else None

        return render_template(
            'dashboard_moderno.html',
            valor_total=valor_total, total_items=total_items,
            stock_total=stock_total, stock_disponible=stock_disponible,
            prestamos_activos=prestamos_activos, merma_mes=merma_mes,
            total_alumnos=total_alumnos, ot_pendientes=ot_pendientes,
            series_labels=series_labels, series_prestamos=series_prestamos,
            series_devoluciones=series_devoluciones,
            top_prestados=top_prestados, top_mermados=top_mermados,
            comparativa=comparativa, tipos_dist=tipos_dist,
            heatmap=heatmap, ultimos_movimientos=ultimos_movimientos,
            stock_bajo=stock_bajo, esp_actual=esp_actual,
            especialidades=especialidades, rol=rol, es_jt=es_jt,
        )
