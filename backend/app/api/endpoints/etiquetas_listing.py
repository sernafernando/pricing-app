"""
Endpoint de listado de etiquetas de envío + smart polling.

Incluye:
- GET /etiquetas-envio (listado con filtros, paginación)
- GET /etiquetas-envio/check-updates (smart polling ligero)
"""

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, case, cast, func, Numeric, or_
from sqlalchemy.orm import Session, aliased

from app.core.database import get_db
from app.api.deps import get_current_user
from app.models.usuario import Usuario
from app.models.etiqueta_envio import EtiquetaEnvio
from app.models.etiqueta_colecta import EtiquetaColecta
from app.models.logistica import Logistica
from app.models.transporte import Transporte
from app.models.codigo_postal_cordon import CodigoPostalCordon
from app.models.sale_order_status import SaleOrderStatus
from app.models.operador import Operador
from app.models.logistica_costo_cordon import LogisticaCostoCordon
from app.models.mercadolibre_order_header import MercadoLibreOrderHeader
from app.models.mercadolibre_user_data import MercadoLibreUserData

from app.api.endpoints.etiquetas_shared import (
    _check_permiso,
    _build_costo_case,
    _get_lluvia_config,
    _soh_status_subquery,
    _manual_soh_status_subquery,
    _facturado_ml_subquery,
    _facturado_manual_subquery,
    _shipping_dedup_subquery,
    CheckUpdatesResponse,
    EtiquetaEnvioResponse,
    EtiquetaPaginatedResponse,
)

router = APIRouter()


@router.get(
    "/etiquetas-envio",
    summary="Listar etiquetas con datos de envío",
    responses={
        200: {
            "description": "Lista o paginado de etiquetas",
            "content": {
                "application/json": {
                    "schema": {
                        "oneOf": [
                            {"type": "array", "items": {"$ref": "#/components/schemas/EtiquetaEnvioResponse"}},
                            {"$ref": "#/components/schemas/EtiquetaPaginatedResponse"},
                        ]
                    }
                }
            },
        }
    },
)
def listar_etiquetas(
    fecha_envio: Optional[date] = Query(None, description="Filtrar por fecha de envío exacta"),
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
    page: Optional[int] = Query(None, ge=1, description="Página (si se omite, devuelve lista completa)"),
    page_size: int = Query(100, ge=1, le=500, description="Tamaño de página (default 100, max 500)"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """
    Lista etiquetas de envío con JOINs a:
    - tb_mercadolibre_orders_shipping (datos del envío)
    - cp_cordones (cordón del CP)
    - tb_sale_order_header (ssos_id del pedido ERP)
    - tb_sale_order_status (nombre y color del estado)
    - logisticas (nombre y color de la logística)
    """
    _check_permiso(db, current_user, "envios_flex.ver")

    # ── Pre-filtrar shipping_ids por fecha ───────────────────────
    # Obtener solo los IDs que coinciden con el rango de fechas ANTES de
    # armar las subqueries pesadas. Esto reduce el scan de 88k+ filas a
    # ~50-200 del día, haciendo que los JOINs sean instantáneos.
    ids_fecha_q = db.query(EtiquetaEnvio.shipping_id)
    if fecha_envio:
        ids_fecha_q = ids_fecha_q.filter(EtiquetaEnvio.fecha_envio == fecha_envio)
    elif fecha_desde or fecha_hasta:
        if fecha_desde:
            ids_fecha_q = ids_fecha_q.filter(EtiquetaEnvio.fecha_envio >= fecha_desde)
        if fecha_hasta:
            ids_fecha_q = ids_fecha_q.filter(EtiquetaEnvio.fecha_envio <= fecha_hasta)
    ids_fecha_sub = ids_fecha_q.scalar_subquery()

    soh_sub = _soh_status_subquery(db, shipping_ids_sub=ids_fecha_sub)
    manual_soh_sub = _manual_soh_status_subquery(db, shipping_ids_sub=ids_fecha_sub)
    facturado_ml_sub = _facturado_ml_subquery(db, shipping_ids_sub=ids_fecha_sub)
    facturado_manual_sub = _facturado_manual_subquery(db, shipping_ids_sub=ids_fecha_sub)
    ManualSaleOrderStatus = aliased(SaleOrderStatus)

    # Subquery: costo vigente por (logistica_id, cordon) donde vigente_desde <= hoy.
    # Usamos max(id) como criterio único — el registro más reciente (mayor id) es
    # siempre la última intención del usuario, incluso si hay duplicados por fecha.
    # cp_cordones usa tildes (Cordón) pero logistica_costo_cordon no (Cordon),
    # así que normalizamos con REPLACE en la condición del JOIN.
    hoy = date.today()
    max_costo_sub = (
        db.query(
            LogisticaCostoCordon.logistica_id.label("costo_logistica_id"),
            LogisticaCostoCordon.cordon.label("costo_cordon"),
            func.max(LogisticaCostoCordon.id).label("max_id"),
        )
        .filter(LogisticaCostoCordon.vigente_desde <= hoy)
        .group_by(
            LogisticaCostoCordon.logistica_id,
            LogisticaCostoCordon.cordon,
        )
        .subquery()
    )

    costo_sub = (
        db.query(
            LogisticaCostoCordon.logistica_id.label("costo_log_id"),
            LogisticaCostoCordon.cordon.label("costo_cordon_val"),
            LogisticaCostoCordon.costo.label("costo_valor"),
            LogisticaCostoCordon.costo_turbo.label("costo_turbo_valor"),
        )
        .join(
            max_costo_sub,
            LogisticaCostoCordon.id == max_costo_sub.c.max_id,
        )
        .subquery()
    )

    # Expresión para normalizar cordón: "Cordón 1" → "Cordon 1" (quitar tilde)
    cordon_normalizado = func.replace(CodigoPostalCordon.cordon, "ó", "o")

    # Subquery deduplicada: una fila por mlshippingid (evita duplicados por items)
    shipping_sub = _shipping_dedup_subquery(db, shipping_ids_sub=ids_fecha_sub)

    # Expresiones COALESCE: para envíos manuales priorizar manual_*, sino ML shipping
    eff_receiver = func.coalesce(EtiquetaEnvio.manual_receiver_name, shipping_sub.c.mlreceiver_name)
    eff_street = func.coalesce(EtiquetaEnvio.manual_street_name, shipping_sub.c.mlstreet_name)
    eff_street_num = func.coalesce(EtiquetaEnvio.manual_street_number, shipping_sub.c.mlstreet_number)
    eff_zip = func.coalesce(EtiquetaEnvio.manual_zip_code, shipping_sub.c.mlzip_code)
    eff_city = func.coalesce(EtiquetaEnvio.manual_city_name, shipping_sub.c.mlcity_name)
    eff_status = func.coalesce(EtiquetaEnvio.manual_status, shipping_sub.c.mlstatus)

    # CP efectivo para resolver cordón: si hay transporte con CP, usar ese;
    # sino, usar el CP del cliente (eff_zip).  La etiqueta sigue mostrando
    # el CP del cliente — esto solo afecta la resolución de cordón/costo.
    eff_zip_for_cordon = func.coalesce(Transporte.cp, eff_zip)

    # Lluvia offset config
    lluvia_tipo, lluvia_valor = _get_lluvia_config(db)

    # Alias para segundo join a Usuario (flag_envio_usuario)
    FlagUsuario = aliased(Usuario)
    # Alias para tercer join a Usuario (retornado_usuario)
    RetornadoUsuario = aliased(Usuario)

    query = (
        db.query(
            EtiquetaEnvio.shipping_id,
            EtiquetaEnvio.sender_id,
            EtiquetaEnvio.nombre_archivo,
            EtiquetaEnvio.fecha_envio,
            EtiquetaEnvio.logistica_id,
            EtiquetaEnvio.transporte_id,
            EtiquetaEnvio.latitud,
            EtiquetaEnvio.longitud,
            EtiquetaEnvio.direccion_completa,
            EtiquetaEnvio.direccion_comentario,
            EtiquetaEnvio.pistoleado_at,
            EtiquetaEnvio.pistoleado_caja,
            EtiquetaEnvio.es_manual,
            EtiquetaEnvio.manual_bra_id,
            EtiquetaEnvio.manual_soh_id,
            EtiquetaEnvio.manual_cust_id,
            EtiquetaEnvio.manual_comment,
            EtiquetaEnvio.manual_phone,
            EtiquetaEnvio.es_outlet,
            EtiquetaEnvio.es_turbo,
            EtiquetaEnvio.es_lluvia,
            EtiquetaEnvio.flag_envio,
            EtiquetaEnvio.flag_envio_motivo,
            EtiquetaEnvio.flag_envio_at,
            EtiquetaEnvio.retornado,
            EtiquetaEnvio.retornado_at,
            Operador.nombre.label("pistoleado_operador_nombre"),
            Logistica.nombre.label("logistica_nombre"),
            Logistica.color.label("logistica_color"),
            Transporte.nombre.label("transporte_nombre"),
            Transporte.color.label("transporte_color"),
            Transporte.direccion.label("transporte_direccion"),
            Transporte.cp.label("transporte_cp"),
            Transporte.localidad.label("transporte_localidad"),
            Transporte.telefono.label("transporte_telefono"),
            Transporte.horario.label("transporte_horario"),
            eff_receiver.label("mlreceiver_name"),
            eff_street.label("mlstreet_name"),
            eff_street_num.label("mlstreet_number"),
            eff_zip.label("mlzip_code"),
            eff_city.label("mlcity_name"),
            eff_status.label("mlstatus"),
            func.coalesce(EtiquetaEnvio.manual_status, shipping_sub.c.mlsubstatus).label("mlsubstatus"),
            EtiquetaEnvio.ml_date_delivered,
            shipping_sub.c.ml_estimated_delivery_time_date,
            CodigoPostalCordon.cordon,
            func.coalesce(soh_sub.c.soh_ssos_id, manual_soh_sub.c.manual_ssos_id).label("ssos_id"),
            case(
                (
                    func.coalesce(SaleOrderStatus.ssos_name, ManualSaleOrderStatus.ssos_name).isnot(None),
                    func.coalesce(SaleOrderStatus.ssos_name, ManualSaleOrderStatus.ssos_name),
                ),
                (
                    or_(
                        facturado_ml_sub.c.shipping_id_str.isnot(None),
                        facturado_manual_sub.c.shipping_id_str.isnot(None),
                    ),
                    "Facturado",
                ),
                else_=None,
            ).label("ssos_name"),
            case(
                (
                    func.coalesce(SaleOrderStatus.ssos_color, ManualSaleOrderStatus.ssos_color).isnot(None),
                    func.coalesce(SaleOrderStatus.ssos_color, ManualSaleOrderStatus.ssos_color),
                ),
                (
                    or_(
                        facturado_ml_sub.c.shipping_id_str.isnot(None),
                        facturado_manual_sub.c.shipping_id_str.isnot(None),
                    ),
                    "#22c55e",
                ),
                else_=None,
            ).label("ssos_color"),
            func.coalesce(
                cast(EtiquetaEnvio.costo_override, Numeric(12, 2)),
                _build_costo_case(
                    costo_sub.c.costo_turbo_valor,
                    costo_sub.c.costo_valor,
                    lluvia_tipo,
                    lluvia_valor,
                ),
            ).label("costo_envio"),
            EtiquetaEnvio.costo_override,
            MercadoLibreUserData.nickname.label("mluser_nickname"),
            MercadoLibreOrderHeader.mlorder_id.label("ml_order_id"),
            Usuario.nombre.label("creado_por_usuario_nombre"),
            FlagUsuario.nombre.label("flag_envio_usuario_nombre"),
            RetornadoUsuario.nombre.label("retornado_usuario_nombre"),
        )
        .outerjoin(
            Logistica,
            EtiquetaEnvio.logistica_id == Logistica.id,
        )
        .outerjoin(
            Transporte,
            EtiquetaEnvio.transporte_id == Transporte.id,
        )
        .outerjoin(
            shipping_sub,
            EtiquetaEnvio.shipping_id == shipping_sub.c.mlshippingid,
        )
        .outerjoin(
            MercadoLibreOrderHeader,
            shipping_sub.c.mlo_id == MercadoLibreOrderHeader.mlo_id,
        )
        .outerjoin(
            MercadoLibreUserData,
            MercadoLibreOrderHeader.mluser_id == MercadoLibreUserData.mluser_id,
        )
        .outerjoin(
            CodigoPostalCordon,
            eff_zip_for_cordon == CodigoPostalCordon.codigo_postal,
        )
        .outerjoin(
            soh_sub,
            soh_sub.c.shipping_id_str == EtiquetaEnvio.shipping_id,
        )
        .outerjoin(
            SaleOrderStatus,
            soh_sub.c.soh_ssos_id == SaleOrderStatus.ssos_id,
        )
        .outerjoin(
            manual_soh_sub,
            manual_soh_sub.c.shipping_id_str == EtiquetaEnvio.shipping_id,
        )
        .outerjoin(
            ManualSaleOrderStatus,
            manual_soh_sub.c.manual_ssos_id == ManualSaleOrderStatus.ssos_id,
        )
        .outerjoin(
            facturado_ml_sub,
            facturado_ml_sub.c.shipping_id_str == EtiquetaEnvio.shipping_id,
        )
        .outerjoin(
            facturado_manual_sub,
            facturado_manual_sub.c.shipping_id_str == EtiquetaEnvio.shipping_id,
        )
        .outerjoin(
            Operador,
            EtiquetaEnvio.pistoleado_operador_id == Operador.id,
        )
        .outerjoin(
            Usuario,
            EtiquetaEnvio.creado_por_usuario_id == Usuario.id,
        )
        .outerjoin(
            FlagUsuario,
            EtiquetaEnvio.flag_envio_usuario_id == FlagUsuario.id,
        )
        .outerjoin(
            RetornadoUsuario,
            EtiquetaEnvio.retornado_usuario_id == RetornadoUsuario.id,
        )
        .outerjoin(
            costo_sub,
            and_(
                costo_sub.c.costo_log_id == EtiquetaEnvio.logistica_id,
                costo_sub.c.costo_cordon_val == cordon_normalizado,
            ),
        )
    )

    # ── Filtros ──────────────────────────────────────────────────

    # fecha_envio = exacta (backward compatible), fecha_desde/fecha_hasta = rango
    if fecha_envio:
        query = query.filter(EtiquetaEnvio.fecha_envio == fecha_envio)
    else:
        if fecha_desde:
            query = query.filter(EtiquetaEnvio.fecha_envio >= fecha_desde)
        if fecha_hasta:
            query = query.filter(EtiquetaEnvio.fecha_envio <= fecha_hasta)

    if cordon:
        query = query.filter(CodigoPostalCordon.cordon == cordon)

    if logistica_id is not None:
        query = query.filter(EtiquetaEnvio.logistica_id == logistica_id)

    if sin_logistica:
        query = query.filter(EtiquetaEnvio.logistica_id.is_(None))

    if solo_outlet:
        query = query.filter(EtiquetaEnvio.es_outlet.is_(True))

    if solo_turbo:
        query = query.filter(EtiquetaEnvio.es_turbo.is_(True))

    if mlstatus:
        query = query.filter(eff_status == mlstatus)

    if ssos_id is not None:
        query = query.filter(or_(soh_sub.c.soh_ssos_id == ssos_id, manual_soh_sub.c.manual_ssos_id == ssos_id))

    if pistoleado == "si":
        query = query.filter(EtiquetaEnvio.pistoleado_at.isnot(None))
    elif pistoleado == "no":
        query = query.filter(EtiquetaEnvio.pistoleado_at.is_(None))

    if sin_cordon:
        query = query.filter(CodigoPostalCordon.cordon.is_(None))

    if search:
        search_term = f"%{search}%"
        query = query.filter(
            (EtiquetaEnvio.shipping_id.ilike(search_term))
            | (eff_receiver.ilike(search_term))
            | (eff_street.ilike(search_term))
            | (eff_city.ilike(search_term))
            | (MercadoLibreUserData.nickname.ilike(search_term))
        )

    # Excluir etiquetas que existen en colecta (son de otro flujo)
    colecta_ids = db.query(EtiquetaColecta.shipping_id).subquery()
    query = query.filter(~EtiquetaEnvio.shipping_id.in_(db.query(colecta_ids.c.shipping_id)))

    # Ordenar por shipping_id desc (más recientes primero)
    query = query.order_by(EtiquetaEnvio.shipping_id.desc())

    # ── Paginación (opcional, backwards compatible) ──────────
    # Si page se envía explícitamente → respuesta paginada {items, total, page, page_size}
    # Si page NO se envía (None) → lista plana [] (comportamiento original)
    if page is not None:
        # Count total ANTES de aplicar LIMIT/OFFSET.
        # Construimos un count query SEPARADO y ligero que solo incluye
        # los JOINs estrictamente necesarios según los filtros activos.
        # La query principal tiene 14 LEFT OUTER JOINs para traer datos de
        # display — pero un LEFT JOIN nunca cambia la cantidad de filas,
        # así que el count no los necesita excepto cuando se filtra por
        # columnas de tablas joineadas (cordon, mlstatus, ssos_id, search).
        count_q = db.query(func.count(EtiquetaEnvio.shipping_id)).select_from(EtiquetaEnvio)

        # Fecha
        if fecha_envio:
            count_q = count_q.filter(EtiquetaEnvio.fecha_envio == fecha_envio)
        else:
            if fecha_desde:
                count_q = count_q.filter(EtiquetaEnvio.fecha_envio >= fecha_desde)
            if fecha_hasta:
                count_q = count_q.filter(EtiquetaEnvio.fecha_envio <= fecha_hasta)

        # Filtros directos sobre etiquetas_envio (no necesitan JOIN)
        if logistica_id is not None:
            count_q = count_q.filter(EtiquetaEnvio.logistica_id == logistica_id)
        if sin_logistica:
            count_q = count_q.filter(EtiquetaEnvio.logistica_id.is_(None))
        if solo_outlet:
            count_q = count_q.filter(EtiquetaEnvio.es_outlet.is_(True))
        if solo_turbo:
            count_q = count_q.filter(EtiquetaEnvio.es_turbo.is_(True))
        if pistoleado == "si":
            count_q = count_q.filter(EtiquetaEnvio.pistoleado_at.isnot(None))
        elif pistoleado == "no":
            count_q = count_q.filter(EtiquetaEnvio.pistoleado_at.is_(None))

        # Filtros que necesitan JOINs — solo agregarlos si están activos
        if cordon or sin_cordon:
            count_q = count_q.outerjoin(Transporte, EtiquetaEnvio.transporte_id == Transporte.id)
            count_q = count_q.outerjoin(
                CodigoPostalCordon,
                func.coalesce(Transporte.cp, EtiquetaEnvio.manual_zip_code) == CodigoPostalCordon.codigo_postal,
            )
            if cordon:
                count_q = count_q.filter(CodigoPostalCordon.cordon == cordon)
            if sin_cordon:
                count_q = count_q.filter(CodigoPostalCordon.cordon.is_(None))

        if mlstatus:
            count_q = count_q.outerjoin(shipping_sub, shipping_sub.c.mlshippingid == EtiquetaEnvio.shipping_id)
            eff_status_count = func.coalesce(EtiquetaEnvio.manual_status, shipping_sub.c.mlstatus)
            count_q = count_q.filter(eff_status_count == mlstatus)

        if ssos_id is not None:
            count_q = count_q.outerjoin(soh_sub, soh_sub.c.shipping_id_str == EtiquetaEnvio.shipping_id)
            count_q = count_q.outerjoin(manual_soh_sub, manual_soh_sub.c.shipping_id_str == EtiquetaEnvio.shipping_id)
            count_q = count_q.filter(or_(soh_sub.c.soh_ssos_id == ssos_id, manual_soh_sub.c.manual_ssos_id == ssos_id))

        if search:
            # Search needs shipping + user data JOINs
            search_term = f"%{search}%"
            if not mlstatus:
                count_q = count_q.outerjoin(shipping_sub, shipping_sub.c.mlshippingid == EtiquetaEnvio.shipping_id)
            count_q = count_q.outerjoin(
                MercadoLibreOrderHeader, shipping_sub.c.mlo_id == MercadoLibreOrderHeader.mlo_id
            )
            count_q = count_q.outerjoin(
                MercadoLibreUserData, MercadoLibreOrderHeader.mlo_seller_id == MercadoLibreUserData.user_id
            )
            eff_receiver_count = func.coalesce(EtiquetaEnvio.manual_receiver_name, shipping_sub.c.mlreceiver_name)
            eff_street_count = func.coalesce(EtiquetaEnvio.manual_street_name, shipping_sub.c.mlstreet_name)
            eff_city_count = func.coalesce(EtiquetaEnvio.manual_city_name, shipping_sub.c.mlcity_name)
            count_q = count_q.filter(
                (EtiquetaEnvio.shipping_id.ilike(search_term))
                | (eff_receiver_count.ilike(search_term))
                | (eff_street_count.ilike(search_term))
                | (eff_city_count.ilike(search_term))
                | (MercadoLibreUserData.nickname.ilike(search_term))
            )

        # Excluir colecta
        count_q = count_q.filter(~EtiquetaEnvio.shipping_id.in_(db.query(colecta_ids.c.shipping_id)))

        total_count = count_q.scalar() or 0
        offset = (page - 1) * page_size
        query = query.limit(page_size).offset(offset)

    rows = query.all()

    items = [
        EtiquetaEnvioResponse(
            shipping_id=row.shipping_id,
            sender_id=row.sender_id,
            nombre_archivo=row.nombre_archivo,
            fecha_envio=row.fecha_envio,
            logistica_id=row.logistica_id,
            logistica_nombre=row.logistica_nombre,
            logistica_color=row.logistica_color,
            mluser_nickname=row.mluser_nickname,
            mlreceiver_name=row.mlreceiver_name,
            mlstreet_name=row.mlstreet_name,
            mlstreet_number=row.mlstreet_number,
            mlzip_code=row.mlzip_code,
            mlcity_name=row.mlcity_name,
            mlstatus=row.mlstatus,
            mlsubstatus=row.mlsubstatus,
            cordon=row.cordon,
            latitud=row.latitud,
            longitud=row.longitud,
            direccion_completa=row.direccion_completa,
            direccion_comentario=row.direccion_comentario,
            ssos_id=row.ssos_id,
            ssos_name=row.ssos_name,
            ssos_color=row.ssos_color,
            pistoleado_at=str(row.pistoleado_at) if row.pistoleado_at else None,
            pistoleado_caja=row.pistoleado_caja,
            pistoleado_operador_nombre=row.pistoleado_operador_nombre,
            costo_envio=float(row.costo_envio) if row.costo_envio is not None else None,
            costo_override=float(row.costo_override) if row.costo_override is not None else None,
            es_manual=row.es_manual,
            manual_bra_id=row.manual_bra_id,
            manual_soh_id=row.manual_soh_id,
            manual_cust_id=row.manual_cust_id,
            manual_comment=row.manual_comment,
            manual_phone=row.manual_phone,
            es_outlet=row.es_outlet,
            es_turbo=row.es_turbo,
            ml_date_delivered=str(row.ml_date_delivered) if row.ml_date_delivered else None,
            ml_estimated_delivery_time_date=str(row.ml_estimated_delivery_time_date)
            if row.ml_estimated_delivery_time_date
            else None,
            es_lluvia=row.es_lluvia,
            flag_envio=row.flag_envio,
            flag_envio_motivo=row.flag_envio_motivo,
            flag_envio_at=str(row.flag_envio_at) if row.flag_envio_at else None,
            flag_envio_usuario_nombre=row.flag_envio_usuario_nombre,
            retornado=row.retornado,
            retornado_at=str(row.retornado_at) if row.retornado_at else None,
            retornado_usuario_nombre=row.retornado_usuario_nombre,
            creado_por_usuario_nombre=row.creado_por_usuario_nombre,
            transporte_id=row.transporte_id,
            transporte_nombre=row.transporte_nombre,
            transporte_color=row.transporte_color,
            transporte_direccion=row.transporte_direccion,
            transporte_cp=row.transporte_cp,
            transporte_localidad=row.transporte_localidad,
            transporte_telefono=row.transporte_telefono,
            transporte_horario=row.transporte_horario,
        )
        for row in rows
    ]

    if page is not None:
        return EtiquetaPaginatedResponse(
            items=items,
            total=total_count,
            page=page,
            page_size=page_size,
        )

    return items


@router.get(
    "/etiquetas-envio/check-updates",
    response_model=CheckUpdatesResponse,
    summary="Check ligero para polling — count + last_updated",
)
def check_updates(
    fecha_envio: Optional[date] = Query(None, description="Fecha de envío exacta"),
    fecha_desde: Optional[date] = Query(None, description="Desde fecha (inclusive)"),
    fecha_hasta: Optional[date] = Query(None, description="Hasta fecha (inclusive)"),
    logistica_id: Optional[int] = Query(None, description="Filtrar por logística"),
    sin_logistica: bool = Query(False, description="Solo sin logística"),
    solo_outlet: bool = Query(False, description="Solo outlet"),
    solo_turbo: bool = Query(False, description="Solo turbo"),
    pistoleado: Optional[str] = Query(None, pattern="^(si|no)$", description="Filtrar por pistoleado: si/no"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> CheckUpdatesResponse:
    """
    Endpoint ultra-ligero para smart polling (cada ~10s).

    Devuelve solo COUNT(*) + MAX(updated_at) sobre EtiquetaEnvio
    con filtros básicos (fecha, logística, outlet, turbo, pistoleado).

    NO hace JOINs pesados (ML shipping, cordón, estado ERP, search).
    Si cualquier etiqueta dentro del rango cambia, el frontend recarga.

    Filtros que requieren JOINs (cordon, sin_cordon, mlstatus, ssos_id,
    search) se omiten intencionalmente — el COUNT puede diferir del
    total visible, pero last_updated siempre detectará cambios.
    """
    _check_permiso(db, current_user, "envios_flex.ver")

    query = db.query(
        func.count(EtiquetaEnvio.shipping_id).label("count"),
        func.max(EtiquetaEnvio.updated_at).label("last_updated"),
    )

    # ── Filtros directos sobre EtiquetaEnvio (sin JOINs) ──
    if fecha_envio:
        query = query.filter(EtiquetaEnvio.fecha_envio == fecha_envio)
    else:
        if fecha_desde:
            query = query.filter(EtiquetaEnvio.fecha_envio >= fecha_desde)
        if fecha_hasta:
            query = query.filter(EtiquetaEnvio.fecha_envio <= fecha_hasta)

    if logistica_id is not None:
        query = query.filter(EtiquetaEnvio.logistica_id == logistica_id)

    if sin_logistica:
        query = query.filter(EtiquetaEnvio.logistica_id.is_(None))

    if solo_outlet:
        query = query.filter(EtiquetaEnvio.es_outlet.is_(True))

    if solo_turbo:
        query = query.filter(EtiquetaEnvio.es_turbo.is_(True))

    if pistoleado == "si":
        query = query.filter(EtiquetaEnvio.pistoleado_at.isnot(None))
    elif pistoleado == "no":
        query = query.filter(EtiquetaEnvio.pistoleado_at.is_(None))

    row = query.one()

    return CheckUpdatesResponse(
        count=row.count,
        last_updated=row.last_updated.isoformat() if row.last_updated else None,
    )
