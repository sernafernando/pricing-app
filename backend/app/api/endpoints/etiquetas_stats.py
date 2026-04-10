"""
Endpoints de estadísticas de etiquetas de envío.

Incluye:
- GET /etiquetas-envio/estadisticas (distribución por cordón, logística, estado)
- GET /etiquetas-envio/estadisticas-por-dia (vista calendario)
"""

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, case, cast, func, Numeric, or_
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.api.deps import get_current_user
from app.models.usuario import Usuario
from app.models.etiqueta_envio import EtiquetaEnvio
from app.models.etiqueta_colecta import EtiquetaColecta
from app.models.logistica import Logistica
from app.models.transporte import Transporte
from app.models.codigo_postal_cordon import CodigoPostalCordon
from app.models.sale_order_status import SaleOrderStatus
from app.models.logistica_costo_cordon import LogisticaCostoCordon

from app.api.endpoints.etiquetas_shared import (
    _check_permiso,
    _build_costo_case,
    _get_lluvia_config,
    _soh_status_subquery,
    _manual_soh_status_subquery,
    _facturado_ml_subquery,
    _facturado_manual_subquery,
    _shipping_dedup_subquery,
    EstadisticaDiaItem,
    EstadisticasEnvioResponse,
    EstadisticasPorDiaResponse,
)

router = APIRouter()


@router.get(
    "/etiquetas-envio/estadisticas",
    response_model=EstadisticasEnvioResponse,
    summary="Estadísticas de distribución de etiquetas",
)
def estadisticas_etiquetas(
    fecha_envio: Optional[date] = Query(None, description="Fecha de envío exacta (por defecto hoy)"),
    fecha_desde: Optional[date] = Query(None, description="Filtrar desde fecha (inclusive)"),
    fecha_hasta: Optional[date] = Query(None, description="Filtrar hasta fecha (inclusive)"),
    cordon: Optional[str] = Query(None, description="Filtrar por cordón"),
    logistica_id: Optional[int] = Query(None, description="Filtrar por logística"),
    sin_logistica: bool = Query(False, description="Solo etiquetas sin logística asignada"),
    mlstatus: Optional[str] = Query(None, description="Filtrar por estado ML"),
    ssos_id: Optional[int] = Query(None, description="Filtrar por estado ERP"),
    solo_outlet: bool = Query(False, description="Solo etiquetas de productos outlet"),
    solo_turbo: bool = Query(False, description="Solo etiquetas de envíos turbo"),
    pistoleado: Optional[str] = Query(None, pattern="^(si|no)$", description="Filtrar por pistoleado: si/no"),
    sin_cordon: bool = Query(False, description="Solo etiquetas sin cordón asignado"),
    search: Optional[str] = Query(None, description="Buscar por shipping_id, destinatario o dirección"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> EstadisticasEnvioResponse:
    """
    Distribución de etiquetas por cordón, logística y estado.

    Acepta los mismos filtros que el listado para que las stats sean
    el resumen exacto de lo que el usuario ve en la tabla.
    """
    _check_permiso(db, current_user, "envios_flex.ver")

    # Determinar filtro de fechas: exacta (backward compatible) o rango
    if fecha_envio:
        fecha_filter = EtiquetaEnvio.fecha_envio == fecha_envio
        fecha_costo = fecha_envio
    elif fecha_desde or fecha_hasta:
        conditions = []
        if fecha_desde:
            conditions.append(EtiquetaEnvio.fecha_envio >= fecha_desde)
        if fecha_hasta:
            conditions.append(EtiquetaEnvio.fecha_envio <= fecha_hasta)
        fecha_filter = and_(*conditions) if len(conditions) > 1 else conditions[0]
        fecha_costo = fecha_hasta or fecha_desde or date.today()
    else:
        fecha_filter = EtiquetaEnvio.fecha_envio == date.today()
        fecha_costo = date.today()

    # ── Pre-filtrar shipping_ids por fecha ────────────────────────
    # Obtener solo los IDs del rango de fechas ANTES de armar subqueries
    # pesadas. Reduce scan de 88k+ filas a ~50-200 (performance).
    ids_fecha_stats = db.query(EtiquetaEnvio.shipping_id).filter(fecha_filter).scalar_subquery()

    # ── Subquery de IDs filtrados ────────────────────────────────
    # Construye la misma lógica de filtros del listado como subquery
    # de shipping_ids. Todas las queries de stats la usan para limitar
    # al mismo set que ve el usuario en la tabla.
    shipping_stats = _shipping_dedup_subquery(db, shipping_ids_sub=ids_fecha_stats)
    soh_sub = _soh_status_subquery(db, shipping_ids_sub=ids_fecha_stats)
    manual_soh_sub = _manual_soh_status_subquery(db, shipping_ids_sub=ids_fecha_stats)
    facturado_ml_stats = _facturado_ml_subquery(db, shipping_ids_sub=ids_fecha_stats)
    facturado_manual_stats = _facturado_manual_subquery(db, shipping_ids_sub=ids_fecha_stats)

    stats_eff_zip = func.coalesce(
        EtiquetaEnvio.manual_zip_code,
        shipping_stats.c.mlzip_code,
    )
    stats_eff_status = func.coalesce(
        EtiquetaEnvio.manual_status,
        shipping_stats.c.mlstatus,
    )
    stats_eff_receiver = func.coalesce(
        EtiquetaEnvio.manual_receiver_name,
        shipping_stats.c.mlreceiver_name,
    )
    stats_eff_street = func.coalesce(
        EtiquetaEnvio.manual_street_name,
        shipping_stats.c.mlstreet_name,
    )
    stats_eff_city = func.coalesce(
        EtiquetaEnvio.manual_city_name,
        shipping_stats.c.mlcity_name,
    )

    # CP efectivo para resolver cordón en stats: si hay transporte con CP,
    # usar ese; sino, usar el CP del cliente.  Mismo patrón que listar_etiquetas.
    stats_eff_zip_for_cordon = func.coalesce(Transporte.cp, stats_eff_zip)

    filtered_ids_q = (
        db.query(EtiquetaEnvio.shipping_id)
        .outerjoin(
            shipping_stats,
            EtiquetaEnvio.shipping_id == shipping_stats.c.mlshippingid,
        )
        .outerjoin(
            Transporte,
            EtiquetaEnvio.transporte_id == Transporte.id,
        )
        .outerjoin(
            CodigoPostalCordon,
            stats_eff_zip_for_cordon == CodigoPostalCordon.codigo_postal,
        )
        .outerjoin(
            soh_sub,
            soh_sub.c.shipping_id_str == EtiquetaEnvio.shipping_id,
        )
        .outerjoin(
            manual_soh_sub,
            manual_soh_sub.c.shipping_id_str == EtiquetaEnvio.shipping_id,
        )
        .filter(fecha_filter)
    )

    # Aplicar los mismos filtros que el listado
    if cordon:
        filtered_ids_q = filtered_ids_q.filter(CodigoPostalCordon.cordon == cordon)
    if logistica_id:
        filtered_ids_q = filtered_ids_q.filter(EtiquetaEnvio.logistica_id == logistica_id)
    if sin_logistica:
        filtered_ids_q = filtered_ids_q.filter(EtiquetaEnvio.logistica_id.is_(None))
    if solo_outlet:
        filtered_ids_q = filtered_ids_q.filter(EtiquetaEnvio.es_outlet.is_(True))
    if solo_turbo:
        filtered_ids_q = filtered_ids_q.filter(EtiquetaEnvio.es_turbo.is_(True))
    if mlstatus:
        filtered_ids_q = filtered_ids_q.filter(stats_eff_status == mlstatus)
    if ssos_id is not None:
        filtered_ids_q = filtered_ids_q.filter(
            or_(soh_sub.c.soh_ssos_id == ssos_id, manual_soh_sub.c.manual_ssos_id == ssos_id)
        )
    if pistoleado == "si":
        filtered_ids_q = filtered_ids_q.filter(EtiquetaEnvio.pistoleado_at.isnot(None))
    elif pistoleado == "no":
        filtered_ids_q = filtered_ids_q.filter(EtiquetaEnvio.pistoleado_at.is_(None))
    if sin_cordon:
        filtered_ids_q = filtered_ids_q.filter(CodigoPostalCordon.cordon.is_(None))
    if search:
        search_term = f"%{search}%"
        filtered_ids_q = filtered_ids_q.filter(
            (EtiquetaEnvio.shipping_id.ilike(search_term))
            | (stats_eff_receiver.ilike(search_term))
            | (stats_eff_street.ilike(search_term))
            | (stats_eff_city.ilike(search_term))
        )

    # Excluir etiquetas que existen en colecta (son de otro flujo)
    colecta_ids_stats = db.query(EtiquetaColecta.shipping_id).subquery()
    filtered_ids_q = filtered_ids_q.filter(~EtiquetaEnvio.shipping_id.in_(db.query(colecta_ids_stats.c.shipping_id)))

    filtered_ids_sub = filtered_ids_q.subquery()

    # Filtro reutilizable: restringe a los shipping_ids filtrados
    ids_filter = EtiquetaEnvio.shipping_id.in_(db.query(filtered_ids_sub.c.shipping_id))

    # Base counts: total, flagged, retornados en UNA sola query con CASE/WHEN.
    # Antes eran 3 queries separadas escaneando la misma tabla con el mismo filtro.
    counts_row = (
        db.query(
            func.count().label("total"),
            func.count(case((EtiquetaEnvio.flag_envio.isnot(None), 1))).label("flagged"),
            func.count(case((EtiquetaEnvio.retornado.is_(True), 1))).label("retornados"),
        )
        .filter(ids_filter)
        .one()
    )
    total = counts_row.total
    flagged = counts_row.flagged
    retornados = counts_row.retornados

    # Por cordón
    cordon_rows = (
        db.query(
            CodigoPostalCordon.cordon,
            func.count().label("cantidad"),
        )
        .select_from(EtiquetaEnvio)
        .outerjoin(
            shipping_stats,
            EtiquetaEnvio.shipping_id == shipping_stats.c.mlshippingid,
        )
        .outerjoin(
            Transporte,
            EtiquetaEnvio.transporte_id == Transporte.id,
        )
        .join(
            CodigoPostalCordon,
            stats_eff_zip_for_cordon == CodigoPostalCordon.codigo_postal,
        )
        .filter(
            ids_filter,
            CodigoPostalCordon.cordon.isnot(None),
        )
        .group_by(CodigoPostalCordon.cordon)
        .all()
    )
    por_cordon = {row.cordon: row.cantidad for row in cordon_rows}
    con_cordon = sum(por_cordon.values())

    # Por logística
    logistica_rows = (
        db.query(
            Logistica.nombre,
            func.count().label("cantidad"),
        )
        .join(EtiquetaEnvio, EtiquetaEnvio.logistica_id == Logistica.id)
        .filter(ids_filter)
        .group_by(Logistica.nombre)
        .all()
    )
    por_logistica = {row.nombre: row.cantidad for row in logistica_rows}
    con_logistica = sum(por_logistica.values())

    # Por estado ML
    ml_status_rows = (
        db.query(
            stats_eff_status.label("eff_mlstatus"),
            func.count().label("cantidad"),
        )
        .select_from(EtiquetaEnvio)
        .outerjoin(
            shipping_stats,
            EtiquetaEnvio.shipping_id == shipping_stats.c.mlshippingid,
        )
        .filter(
            ids_filter,
            stats_eff_status.isnot(None),
        )
        .group_by(stats_eff_status)
        .all()
    )
    por_estado_ml = {row.eff_mlstatus: row.cantidad for row in ml_status_rows}

    # Por estado ERP (ML + manuales)
    erp_status_rows = (
        db.query(
            SaleOrderStatus.ssos_name,
            func.count().label("cantidad"),
        )
        .join(soh_sub, soh_sub.c.soh_ssos_id == SaleOrderStatus.ssos_id)
        .join(
            EtiquetaEnvio,
            EtiquetaEnvio.shipping_id == soh_sub.c.shipping_id_str,
        )
        .filter(ids_filter)
        .group_by(SaleOrderStatus.ssos_name)
        .all()
    )
    por_estado_erp = {row.ssos_name: row.cantidad for row in erp_status_rows}

    # Agregar manuales con pedido ERP
    manual_erp_rows = (
        db.query(
            SaleOrderStatus.ssos_name,
            func.count().label("cantidad"),
        )
        .join(manual_soh_sub, manual_soh_sub.c.manual_ssos_id == SaleOrderStatus.ssos_id)
        .join(
            EtiquetaEnvio,
            EtiquetaEnvio.shipping_id == manual_soh_sub.c.shipping_id_str,
        )
        .filter(ids_filter)
        .group_by(SaleOrderStatus.ssos_name)
        .all()
    )
    for row in manual_erp_rows:
        por_estado_erp[row.ssos_name] = por_estado_erp.get(row.ssos_name, 0) + row.cantidad

    # Contar "Facturado": envíos sin estado ERP activo pero con ct_transaction en history
    facturado_count = (
        db.query(func.count())
        .select_from(EtiquetaEnvio)
        .outerjoin(
            soh_sub,
            soh_sub.c.shipping_id_str == EtiquetaEnvio.shipping_id,
        )
        .outerjoin(
            manual_soh_sub,
            manual_soh_sub.c.shipping_id_str == EtiquetaEnvio.shipping_id,
        )
        .outerjoin(
            facturado_ml_stats,
            facturado_ml_stats.c.shipping_id_str == EtiquetaEnvio.shipping_id,
        )
        .outerjoin(
            facturado_manual_stats,
            facturado_manual_stats.c.shipping_id_str == EtiquetaEnvio.shipping_id,
        )
        .filter(
            ids_filter,
            soh_sub.c.soh_ssos_id.is_(None),
            manual_soh_sub.c.manual_ssos_id.is_(None),
            or_(
                facturado_ml_stats.c.shipping_id_str.isnot(None),
                facturado_manual_stats.c.shipping_id_str.isnot(None),
            ),
        )
        .scalar()
    ) or 0
    if facturado_count > 0:
        por_estado_erp["Facturado"] = facturado_count

    # ── Costos de envío ─────────────────────────────────────────
    # max(id) como criterio único — evita duplicados cuando hay múltiples registros
    # con la misma (logistica_id, cordon, vigente_desde).
    max_costo_stats = (
        db.query(
            LogisticaCostoCordon.logistica_id.label("costo_logistica_id"),
            LogisticaCostoCordon.cordon.label("costo_cordon"),
            func.max(LogisticaCostoCordon.id).label("max_id"),
        )
        .filter(LogisticaCostoCordon.vigente_desde <= fecha_costo)
        .group_by(
            LogisticaCostoCordon.logistica_id,
            LogisticaCostoCordon.cordon,
        )
        .subquery()
    )

    costo_stats = (
        db.query(
            LogisticaCostoCordon.logistica_id.label("costo_log_id"),
            LogisticaCostoCordon.cordon.label("costo_cordon_val"),
            LogisticaCostoCordon.costo.label("costo_valor"),
            LogisticaCostoCordon.costo_turbo.label("costo_turbo_valor"),
        )
        .join(
            max_costo_stats,
            LogisticaCostoCordon.id == max_costo_stats.c.max_id,
        )
        .subquery()
    )

    cordon_norm = func.replace(CodigoPostalCordon.cordon, "ó", "o")

    # Lluvia offset config
    lluvia_tipo_s, lluvia_valor_s = _get_lluvia_config(db)

    costo_efectivo = func.coalesce(
        cast(EtiquetaEnvio.costo_override, Numeric(12, 2)),
        _build_costo_case(
            costo_stats.c.costo_turbo_valor,
            costo_stats.c.costo_valor,
            lluvia_tipo_s,
            lluvia_valor_s,
        ),
    )

    costo_rows = (
        db.query(
            Logistica.nombre.label("log_nombre"),
            func.coalesce(func.sum(costo_efectivo), 0).label("costo_sum"),
        )
        .select_from(EtiquetaEnvio)
        .join(Logistica, EtiquetaEnvio.logistica_id == Logistica.id)
        .outerjoin(
            shipping_stats,
            EtiquetaEnvio.shipping_id == shipping_stats.c.mlshippingid,
        )
        .outerjoin(
            Transporte,
            EtiquetaEnvio.transporte_id == Transporte.id,
        )
        .join(
            CodigoPostalCordon,
            stats_eff_zip_for_cordon == CodigoPostalCordon.codigo_postal,
        )
        .outerjoin(
            costo_stats,
            and_(
                costo_stats.c.costo_log_id == EtiquetaEnvio.logistica_id,
                costo_stats.c.costo_cordon_val == cordon_norm,
            ),
        )
        .filter(
            ids_filter,
            CodigoPostalCordon.cordon.isnot(None),
        )
        .group_by(Logistica.nombre)
        .all()
    )

    costo_por_logistica = {row.log_nombre: float(row.costo_sum) for row in costo_rows}
    costo_total = sum(costo_por_logistica.values())

    # Sumar también etiquetas con costo_override que NO tienen logística
    costo_sin_logistica = (
        db.query(
            func.coalesce(func.sum(cast(EtiquetaEnvio.costo_override, Numeric(12, 2))), 0),
        )
        .filter(
            ids_filter,
            EtiquetaEnvio.logistica_id.is_(None),
            EtiquetaEnvio.costo_override.isnot(None),
        )
        .scalar()
    )
    costo_total += float(costo_sin_logistica or 0)

    return EstadisticasEnvioResponse(
        total=total,
        por_cordon=por_cordon,
        sin_cordon=max(0, total - con_cordon),
        por_logistica=por_logistica,
        sin_logistica=max(0, total - con_logistica),
        por_estado_ml=por_estado_ml,
        por_estado_erp=por_estado_erp,
        costo_total=costo_total,
        costo_por_logistica=costo_por_logistica,
        flagged=flagged,
        retornados=retornados,
    )


@router.get(
    "/etiquetas-envio/estadisticas-por-dia",
    response_model=EstadisticasPorDiaResponse,
    summary="Estadísticas agrupadas por día para vista calendario",
)
def estadisticas_por_dia(
    fecha_desde: date = Query(..., description="Fecha inicio (inclusive)"),
    fecha_hasta: date = Query(..., description="Fecha fin (inclusive)"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> EstadisticasPorDiaResponse:
    """
    Devuelve estadísticas agrupadas por fecha_envio para la vista calendario.

    Para cada día en el rango devuelve:
    - total, flex (no manual), manuales (es_manual=True)
    - distribución por cordón (CABA, Cordón 1, etc.)
    - con/sin logística asignada

    Solo incluye días que tienen al menos 1 etiqueta.
    """
    _check_permiso(db, current_user, "envios_flex.ver")

    # Pre-filtrar shipping_ids por rango de fechas (performance)
    ids_fecha_cal = (
        db.query(EtiquetaEnvio.shipping_id)
        .filter(
            EtiquetaEnvio.fecha_envio >= fecha_desde,
            EtiquetaEnvio.fecha_envio <= fecha_hasta,
        )
        .scalar_subquery()
    )

    shipping_stats = _shipping_dedup_subquery(db, shipping_ids_sub=ids_fecha_cal)

    stats_eff_zip = func.coalesce(
        EtiquetaEnvio.manual_zip_code,
        shipping_stats.c.mlzip_code,
    )
    stats_eff_zip_for_cordon = func.coalesce(Transporte.cp, stats_eff_zip)

    # Estado ML efectivo (manual_status overrides mlstatus de ML)
    stats_eff_status = func.coalesce(
        EtiquetaEnvio.manual_status,
        shipping_stats.c.mlstatus,
    )

    # Query base: una fila por (fecha_envio, es_manual, cordon, tiene_logistica, mlstatus)
    base_q = (
        db.query(
            EtiquetaEnvio.fecha_envio,
            EtiquetaEnvio.es_manual,
            CodigoPostalCordon.cordon,
            case(
                (EtiquetaEnvio.logistica_id.isnot(None), True),
                else_=False,
            ).label("tiene_logistica"),
            stats_eff_status.label("mlstatus"),
            func.count().label("cantidad"),
        )
        .outerjoin(
            shipping_stats,
            EtiquetaEnvio.shipping_id == shipping_stats.c.mlshippingid,
        )
        .outerjoin(
            Transporte,
            EtiquetaEnvio.transporte_id == Transporte.id,
        )
        .outerjoin(
            CodigoPostalCordon,
            stats_eff_zip_for_cordon == CodigoPostalCordon.codigo_postal,
        )
        .filter(
            EtiquetaEnvio.fecha_envio >= fecha_desde,
            EtiquetaEnvio.fecha_envio <= fecha_hasta,
            # Excluir etiquetas que existen en colecta
            ~EtiquetaEnvio.shipping_id.in_(db.query(EtiquetaColecta.shipping_id)),
        )
        .group_by(
            EtiquetaEnvio.fecha_envio,
            EtiquetaEnvio.es_manual,
            CodigoPostalCordon.cordon,
            "tiene_logistica",
            stats_eff_status,
        )
        .all()
    )

    # Agrupar resultados por fecha
    dias_map: dict[date, EstadisticaDiaItem] = {}

    for row in base_q:
        fecha = row.fecha_envio
        if fecha not in dias_map:
            dias_map[fecha] = EstadisticaDiaItem(fecha=fecha)

        dia = dias_map[fecha]
        cantidad = row.cantidad

        dia.total += cantidad

        if row.es_manual:
            dia.manuales += cantidad
        else:
            dia.flex += cantidad

        if row.cordon:
            dia.por_cordon[row.cordon] = dia.por_cordon.get(row.cordon, 0) + cantidad
        else:
            dia.sin_cordon += cantidad

        if row.tiene_logistica:
            dia.con_logistica += cantidad
        else:
            dia.sin_logistica += cantidad

        if row.mlstatus == "shipped":
            dia.enviados += cantidad
        elif row.mlstatus == "not_delivered":
            dia.no_entregados += cantidad

    # Ordenar por fecha
    dias = sorted(dias_map.values(), key=lambda d: d.fecha)

    return EstadisticasPorDiaResponse(dias=dias)
