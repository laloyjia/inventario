"""Dashboard moderno unificado para Admin y Jefe Técnico.

Contiene toda la lógica de agregación de datos que alimenta el nuevo dashboard
(KPIs, series temporales, rankings, mapa de calor, comparativas).

Uso: en app.py, llamar a
    registrar_dashboard_moderno(app, db, Item, Especialidad, Prestamo,
                                 PrestamoExterno, Estudiante, Usuario,
                                 OrdenTrabajo, Auditoria, login_requerido,
                                 jt_o_admin)
"""
from flask import request, session, render_template
from datetime import datetime, timedelta
from sqlalchemy import func, case


def registrar_dashboard_moderno(app, db, Item, Especialidad, Prestamo,
                                 PrestamoExterno, Estudiante, Usuario,
                                 OrdenTrabajo, Auditoria, login_requerido,
                                 jt_o_admin):

    @app.route('/dashboard')
    @login_requerido
    @jt_o_admin
    def dashboard_moderno():
        """Dashboard unificado con métricas de control de stock."""
        rol = session.get('usuario_rol')
        # Filtro opcional: especialidad_id para ver una sola área
        f_esp = request.args.get('especialidad_id', type=int)

        # ── KPIs ───────────────────────────────────────────────────
        q_items = Item.query
        if f_esp:
            q_items = q_items.filter_by(especialidad_id=f_esp)

        # Valor total (patrimonio) - sumar precio_unitario * cantidad_total
        valor_total_row = db.session.query(
            func.coalesce(func.sum(Item.precio_unitario * Item.cantidad_total), 0.0)
        )
        if f_esp:
            valor_total_row = valor_total_row.filter(Item.especialidad_id == f_esp)
        valor_total = int(valor_total_row.scalar() or 0)

        # Contadores
        total_items = q_items.count()
        stock_total = db.session.query(func.coalesce(func.sum(Item.cantidad_total), 0))
        if f_esp:
            stock_total = stock_total.filter(Item.especialidad_id == f_esp)
        stock_total = int(stock_total.scalar() or 0)

        stock_disponible = db.session.query(func.coalesce(func.sum(Item.cantidad_disponible), 0))
        if f_esp:
            stock_disponible = stock_disponible.filter(Item.especialidad_id == f_esp)
        stock_disponible = int(stock_disponible.scalar() or 0)

        # Préstamos activos
        q_prest_activos = Prestamo.query.filter_by(estado='Pendiente')
        if f_esp:
            q_prest_activos = q_prest_activos.join(Item).filter(Item.especialidad_id == f_esp)
        prestamos_activos = q_prest_activos.count()

        # Mermas del mes
        hoy = datetime.utcnow()
        inicio_mes = hoy.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        merma_mes_row = db.session.query(
            func.coalesce(func.sum(Prestamo.cantidad_mermada), 0)
        ).filter(Prestamo.fecha_prestamo >= inicio_mes)
        if f_esp:
            merma_mes_row = merma_mes_row.join(Item).filter(Item.especialidad_id == f_esp)
        merma_mes = int(merma_mes_row.scalar() or 0)

        # Total de alumnos
        q_alumnos = Estudiante.query.filter_by(activo=True)
        if f_esp:
            q_alumnos = q_alumnos.filter_by(especialidad_id=f_esp)
        total_alumnos = q_alumnos.count()

        # ── Series: movimientos últimos 30 días ───────────────────
        hace_30 = hoy - timedelta(days=30)
        movimientos = {}
        for d in range(30, -1, -1):
            fecha = (hoy - timedelta(days=d)).date()
            movimientos[fecha.isoformat()] = {'prestamos': 0, 'devoluciones': 0}

        q_p = db.session.query(
            func.date(Prestamo.fecha_prestamo).label('d'),
            func.count(Prestamo.id).label('n'),
        ).filter(Prestamo.fecha_prestamo >= hace_30).group_by('d')
        if f_esp:
            q_p = q_p.join(Item).filter(Item.especialidad_id == f_esp)
        for row in q_p.all():
            key = row.d.isoformat() if hasattr(row.d, 'isoformat') else str(row.d)
            if key in movimientos:
                movimientos[key]['prestamos'] = int(row.n)

        q_d = db.session.query(
            func.date(Prestamo.fecha_devolucion).label('d'),
            func.count(Prestamo.id).label('n'),
        ).filter(Prestamo.fecha_devolucion >= hace_30,
                 Prestamo.estado == 'Devuelto').group_by('d')
        if f_esp:
            q_d = q_d.join(Item).filter(Item.especialidad_id == f_esp)
        for row in q_d.all():
            key = row.d.isoformat() if hasattr(row.d, 'isoformat') else str(row.d)
            if key in movimientos:
                movimientos[key]['devoluciones'] = int(row.n)

        series_labels = list(movimientos.keys())
        series_prestamos = [movimientos[k]['prestamos'] for k in series_labels]
        series_devoluciones = [movimientos[k]['devoluciones'] for k in series_labels]

        # ── Top 10 items más prestados ────────────────────────────
        q_top = db.session.query(
            Item.id, Item.nombre, Item.codigo_barras,
            func.count(Prestamo.id).label('total'),
        ).join(Prestamo, Prestamo.item_id == Item.id
        ).filter(Prestamo.fecha_prestamo >= hace_30
        ).group_by(Item.id, Item.nombre, Item.codigo_barras
        ).order_by(func.count(Prestamo.id).desc()).limit(10)
        if f_esp:
            q_top = q_top.filter(Item.especialidad_id == f_esp)
        top_prestados = q_top.all()

        # ── Top 10 items con más merma (histórico) ────────────────
        q_merma = Item.query.filter(Item.cantidad_mermada > 0)
        if f_esp:
            q_merma = q_merma.filter(Item.especialidad_id == f_esp)
        top_mermados = q_merma.order_by(Item.cantidad_mermada.desc()).limit(10).all()

        # ── Comparativa por especialidad (para vista general) ─────
        comparativa = []
        if not f_esp:
            for esp in Especialidad.query.order_by(Especialidad.nombre).all():
                n_items = Item.query.filter_by(especialidad_id=esp.id).count()
                valor = db.session.query(
                    func.coalesce(func.sum(Item.precio_unitario * Item.cantidad_total), 0.0)
                ).filter(Item.especialidad_id == esp.id).scalar() or 0
                prestamos = Prestamo.query.join(Item).filter(
                    Item.especialidad_id == esp.id,
                    Prestamo.estado == 'Pendiente'
                ).count()
                comparativa.append({
                    'id': esp.id,
                    'nombre': esp.nombre,
                    'tipo_area': esp.tipo_area or 'GENERAL',
                    'items': n_items,
                    'valor': int(valor),
                    'prestamos_activos': prestamos,
                })

        # ── Distribución por tipo de área (gráfico dona) ──────────
        tipos_dist = {}
        q_tipos = db.session.query(
            Especialidad.tipo_area,
            func.count(Item.id).label('n'),
        ).join(Item, Item.especialidad_id == Especialidad.id
        ).group_by(Especialidad.tipo_area)
        for row in q_tipos.all():
            tipos_dist[row.tipo_area or 'GENERAL'] = int(row.n)

        # ── Mapa de calor: préstamos por día de semana × hora ─────
        # Últimos 30 días. Grilla 7 filas (L-D) × 24 columnas (0-23h).
        heatmap = [[0] * 24 for _ in range(7)]
        q_hm = Prestamo.query.filter(Prestamo.fecha_prestamo >= hace_30)
        if f_esp:
            q_hm = q_hm.join(Item).filter(Item.especialidad_id == f_esp)
        for p in q_hm.all():
            if p.fecha_prestamo:
                heatmap[p.fecha_prestamo.weekday()][p.fecha_prestamo.hour] += 1

        # ── Últimos 15 movimientos ────────────────────────────────
        q_ult = Prestamo.query.order_by(Prestamo.fecha_prestamo.desc()).limit(15)
        if f_esp:
            q_ult = q_ult.join(Item).filter(Item.especialidad_id == f_esp)
        ultimos_movimientos = q_ult.all()

        # ── Alertas: stock bajo (< cantidad_minima) ───────────────
        q_stock_bajo = Item.query.filter(
            Item.cantidad_disponible < Item.cantidad_minima
        )
        if f_esp:
            q_stock_bajo = q_stock_bajo.filter(Item.especialidad_id == f_esp)
        stock_bajo = q_stock_bajo.order_by(Item.cantidad_disponible.asc()).limit(10).all()

        # ── Órdenes de trabajo en curso ───────────────────────────
        q_ot = OrdenTrabajo.query.filter_by(estado='En Curso')
        if f_esp:
            q_ot = q_ot.filter_by(especialidad_id=f_esp)
        ot_pendientes = q_ot.count()

        # ── Info del filtro actual ────────────────────────────────
        esp_actual = Especialidad.query.get(f_esp) if f_esp else None
        especialidades = Especialidad.query.order_by(Especialidad.nombre).all()

        return render_template(
            'dashboard_moderno.html',
            # KPIs
            valor_total=valor_total,
            total_items=total_items,
            stock_total=stock_total,
            stock_disponible=stock_disponible,
            prestamos_activos=prestamos_activos,
            merma_mes=merma_mes,
            total_alumnos=total_alumnos,
            ot_pendientes=ot_pendientes,
            # Series
            series_labels=series_labels,
            series_prestamos=series_prestamos,
            series_devoluciones=series_devoluciones,
            # Rankings
            top_prestados=top_prestados,
            top_mermados=top_mermados,
            # Comparativa
            comparativa=comparativa,
            tipos_dist=tipos_dist,
            heatmap=heatmap,
            ultimos_movimientos=ultimos_movimientos,
            stock_bajo=stock_bajo,
            # Meta
            esp_actual=esp_actual,
            especialidades=especialidades,
            rol=rol,
            es_jt=(rol == 'JefeTecnico'),
        )
