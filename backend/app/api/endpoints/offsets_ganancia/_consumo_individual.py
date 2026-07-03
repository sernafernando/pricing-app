from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import or_, text

from app.core.database import get_db
from app.models.offset_ganancia import OffsetGanancia
from app.models.offset_grupo import OffsetGrupo
from app.models.offset_grupo_consumo import OffsetGrupoConsumo
from app.models.offset_individual_consumo import OffsetIndividualConsumo, OffsetIndividualResumen
from app.models.cur_exch_history import CurExchHistory
from app.models.usuario import Usuario
from app.api.deps import get_current_user
from app.services.permisos_service import verificar_permiso
from app.services.offset_resumen_service import (
    fetch_offsets_limite_por_grupo,
    fetch_resumenes_grupo,
    fetch_resumenes_individuales,
)

router = APIRouter()


@router.get("/offset-individuales-resumen")
def obtener_resumen_offsets_individuales(
    db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)
):
    """Obtiene el resumen de consumo de todos los offsets individuales con límites"""
    # Obtener offsets individuales (sin grupo) que tienen límites
    offsets_con_limites = (
        db.query(OffsetGanancia)
        .filter(
            OffsetGanancia.grupo_id.is_(None),
            or_(OffsetGanancia.max_unidades.isnot(None), OffsetGanancia.max_monto_usd.isnot(None)),
        )
        .all()
    )

    # Prefetch de resúmenes individuales en UNA sola query (evita N+1 en el loop de abajo)
    _offset_ids = [o.id for o in offsets_con_limites]
    _resumenes = fetch_resumenes_individuales(db, _offset_ids)

    resultado = []
    for offset in offsets_con_limites:
        # Determinar nivel del offset
        if offset.item_id:
            nivel = "producto"
            nombre = f"Producto {offset.item_id}"
        elif offset.marca:
            nivel = "marca"
            nombre = offset.marca
        elif offset.categoria:
            nivel = "categoria"
            nombre = offset.categoria
        elif offset.subcategoria_id:
            nivel = "subcategoria"
            nombre = f"Subcategoría {offset.subcategoria_id}"
        else:
            nivel = "otro"
            nombre = "Offset"

        # Obtener resumen si existe (prefetched above — O(1), not per-offset)
        resumen = _resumenes.get(offset.id)

        if resumen:
            total_unidades = resumen.total_unidades or 0
            total_monto_usd = float(resumen.total_monto_usd or 0)

            resultado.append(
                {
                    "offset_id": offset.id,
                    "descripcion": offset.descripcion or nombre,
                    "nivel": nivel,
                    "nombre_nivel": nombre,
                    "total_unidades": total_unidades,
                    "total_monto_ars": float(resumen.total_monto_ars or 0),
                    "total_monto_usd": total_monto_usd,
                    "cantidad_ventas": resumen.cantidad_ventas or 0,
                    "limite_alcanzado": resumen.limite_alcanzado,
                    "fecha_limite_alcanzado": resumen.fecha_limite_alcanzado.isoformat()
                    if resumen.fecha_limite_alcanzado
                    else None,
                    "max_unidades": offset.max_unidades,
                    "max_monto_usd": float(offset.max_monto_usd) if offset.max_monto_usd else None,
                    "porcentaje_consumido_unidades": (total_unidades / offset.max_unidades * 100)
                    if offset.max_unidades
                    else None,
                    "porcentaje_consumido_monto": (total_monto_usd / float(offset.max_monto_usd) * 100)
                    if offset.max_monto_usd
                    else None,
                }
            )
        else:
            resultado.append(
                {
                    "offset_id": offset.id,
                    "descripcion": offset.descripcion or nombre,
                    "nivel": nivel,
                    "nombre_nivel": nombre,
                    "total_unidades": 0,
                    "total_monto_ars": 0,
                    "total_monto_usd": 0,
                    "cantidad_ventas": 0,
                    "limite_alcanzado": None,
                    "fecha_limite_alcanzado": None,
                    "max_unidades": offset.max_unidades,
                    "max_monto_usd": float(offset.max_monto_usd) if offset.max_monto_usd else None,
                    "porcentaje_consumido_unidades": 0 if offset.max_unidades else None,
                    "porcentaje_consumido_monto": 0 if offset.max_monto_usd else None,
                }
            )

    return resultado


@router.get("/offsets/{offset_id}/consumo")
def obtener_consumo_offset_individual(
    offset_id: int, db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)
):
    """Obtiene el detalle de consumo de un offset individual"""
    offset = db.query(OffsetGanancia).filter(OffsetGanancia.id == offset_id).first()
    if not offset:
        raise HTTPException(404, "Offset no encontrado")

    # Determinar si es de grupo o individual
    if offset.grupo_id:
        # Es de grupo, obtener consumos del grupo
        consumos = (
            db.query(OffsetGrupoConsumo)
            .filter(OffsetGrupoConsumo.offset_id == offset_id)
            .order_by(OffsetGrupoConsumo.fecha_venta.desc())
            .limit(100)
            .all()
        )

        return {
            "offset": {
                "id": offset.id,
                "descripcion": offset.descripcion,
                "tipo": "grupo",
                "grupo_id": offset.grupo_id,
            },
            "consumos": [
                {
                    "id": c.id,
                    "id_operacion": c.id_operacion,
                    "venta_fuera_id": c.venta_fuera_id,
                    "tipo_venta": c.tipo_venta,
                    "fecha_venta": c.fecha_venta.isoformat() if c.fecha_venta else None,
                    "item_id": c.item_id,
                    "cantidad": c.cantidad,
                    "monto_offset_aplicado": float(c.monto_offset_aplicado) if c.monto_offset_aplicado else 0,
                    "monto_offset_usd": float(c.monto_offset_usd) if c.monto_offset_usd else None,
                }
                for c in consumos
            ],
        }
    else:
        # Es individual
        consumos = (
            db.query(OffsetIndividualConsumo)
            .filter(OffsetIndividualConsumo.offset_id == offset_id)
            .order_by(OffsetIndividualConsumo.fecha_venta.desc())
            .limit(100)
            .all()
        )

        return {
            "offset": {
                "id": offset.id,
                "descripcion": offset.descripcion,
                "tipo": "individual",
                "item_id": offset.item_id,
                "marca": offset.marca,
                "categoria": offset.categoria,
                "subcategoria_id": offset.subcategoria_id,
            },
            "consumos": [
                {
                    "id": c.id,
                    "id_operacion": c.id_operacion,
                    "venta_fuera_id": c.venta_fuera_id,
                    "tipo_venta": c.tipo_venta,
                    "fecha_venta": c.fecha_venta.isoformat() if c.fecha_venta else None,
                    "item_id": c.item_id,
                    "cantidad": c.cantidad,
                    "monto_offset_aplicado": float(c.monto_offset_aplicado) if c.monto_offset_aplicado else 0,
                    "monto_offset_usd": float(c.monto_offset_usd) if c.monto_offset_usd else None,
                }
                for c in consumos
            ],
        }


@router.post("/offsets/{offset_id}/recalcular")
def recalcular_consumo_offset_individual(
    offset_id: int, db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)
):
    """Recalcula el consumo de un offset individual desde cero."""
    if not verificar_permiso(db, current_user, "config.editar_constantes"):
        raise HTTPException(status_code=403, detail="No tienes permiso para gestionar offsets de ganancia")
    offset = (
        db.query(OffsetGanancia)
        .filter(
            OffsetGanancia.id == offset_id,
            OffsetGanancia.grupo_id.is_(None),  # Solo offsets individuales
        )
        .first()
    )

    if not offset:
        raise HTTPException(404, "Offset individual no encontrado")

    # Verificar que tenga límites
    if not offset.max_unidades and not offset.max_monto_usd:
        raise HTTPException(400, "Este offset no tiene límites configurados")

    # Eliminar consumos existentes
    db.query(OffsetIndividualConsumo).filter(OffsetIndividualConsumo.offset_id == offset_id).delete()

    # Obtener cotización (primero tipo_cambio, fallback CurExchHistory)
    from app.models.tipo_cambio import TipoCambio

    tc = db.query(TipoCambio).filter(TipoCambio.moneda == "USD").order_by(TipoCambio.fecha.desc()).first()
    if tc and tc.venta:
        cotizacion = float(tc.venta)
    else:
        tc_actual = db.query(CurExchHistory).order_by(CurExchHistory.ceh_cd.desc()).first()
        cotizacion = float(tc_actual.ceh_exchange) if tc_actual else 1000.0

    fecha_inicio = offset.fecha_desde

    # Construir query según el nivel del offset
    if offset.item_id:
        ventas_query = text("""
            SELECT m.id_operacion, m.fecha_venta, m.item_id, m.cantidad,
                   m.costo_total_sin_iva, m.cotizacion_dolar
            FROM ml_ventas_metricas m
            WHERE m.item_id = :item_id AND m.fecha_venta >= :fecha_inicio
            ORDER BY m.fecha_venta
        """)
        params = {"item_id": offset.item_id, "fecha_inicio": fecha_inicio}
    elif offset.marca and not offset.categoria and not offset.subcategoria_id:
        ventas_query = text("""
            SELECT m.id_operacion, m.fecha_venta, m.item_id, m.cantidad,
                   m.costo_total_sin_iva, m.cotizacion_dolar
            FROM ml_ventas_metricas m
            WHERE m.marca = :marca AND m.fecha_venta >= :fecha_inicio
            ORDER BY m.fecha_venta
        """)
        params = {"marca": offset.marca, "fecha_inicio": fecha_inicio}
    elif offset.categoria and not offset.marca and not offset.subcategoria_id:
        ventas_query = text("""
            SELECT m.id_operacion, m.fecha_venta, m.item_id, m.cantidad,
                   m.costo_total_sin_iva, m.cotizacion_dolar
            FROM ml_ventas_metricas m
            WHERE m.categoria = :categoria AND m.fecha_venta >= :fecha_inicio
            ORDER BY m.fecha_venta
        """)
        params = {"categoria": offset.categoria, "fecha_inicio": fecha_inicio}
    elif offset.subcategoria_id:
        ventas_query = text("""
            SELECT m.id_operacion, m.fecha_venta, m.item_id, m.cantidad,
                   m.costo_total_sin_iva, m.cotizacion_dolar
            FROM ml_ventas_metricas m
            WHERE m.subcategoria = (SELECT subcat_desc FROM tb_subcategory WHERE subcat_id = :subcat_id LIMIT 1)
            AND m.fecha_venta >= :fecha_inicio
            ORDER BY m.fecha_venta
        """)
        params = {"subcat_id": offset.subcategoria_id, "fecha_inicio": fecha_inicio}
    else:
        raise HTTPException(400, "Offset sin criterio válido")

    ventas = db.execute(ventas_query, params).fetchall()

    consumos_creados = 0
    total_unidades = 0
    total_monto_ars = 0.0
    total_monto_usd = 0.0

    for venta in ventas:
        cot = float(venta.cotizacion_dolar) if venta.cotizacion_dolar else cotizacion
        costo_unitario = (
            (float(venta.costo_total_sin_iva) / venta.cantidad) if venta.cantidad and venta.costo_total_sin_iva else 0
        )

        # Calcular monto según tipo de offset
        if offset.tipo_offset == "monto_fijo":
            monto = float(offset.monto or 0)
            if offset.moneda == "USD":
                monto_ars = monto * cot
                monto_usd = monto
            else:
                monto_ars = monto
                monto_usd = monto / cot if cot > 0 else 0
        elif offset.tipo_offset == "monto_por_unidad":
            monto_por_u = float(offset.monto or 0)
            if offset.moneda == "USD":
                monto_ars = monto_por_u * venta.cantidad * cot
                monto_usd = monto_por_u * venta.cantidad
            else:
                monto_ars = monto_por_u * venta.cantidad
                monto_usd = monto_por_u * venta.cantidad / cot if cot > 0 else 0
        elif offset.tipo_offset == "porcentaje_costo":
            porcentaje = float(offset.porcentaje or 0)
            monto_ars = costo_unitario * venta.cantidad * (porcentaje / 100)
            monto_usd = monto_ars / cot if cot > 0 else 0
        else:
            continue

        consumo = OffsetIndividualConsumo(
            offset_id=offset_id,
            id_operacion=venta.id_operacion,
            tipo_venta="ml",
            fecha_venta=venta.fecha_venta,
            item_id=venta.item_id,
            cantidad=venta.cantidad,
            monto_offset_aplicado=monto_ars,
            monto_offset_usd=monto_usd,
            cotizacion_dolar=cot,
        )
        db.add(consumo)
        consumos_creados += 1
        total_unidades += venta.cantidad
        total_monto_ars += monto_ars
        total_monto_usd += monto_usd

    # Actualizar o crear resumen
    resumen = db.query(OffsetIndividualResumen).filter(OffsetIndividualResumen.offset_id == offset_id).first()

    limite_alcanzado = None
    if offset.max_unidades and total_unidades >= offset.max_unidades:
        limite_alcanzado = "unidades"
    elif offset.max_monto_usd and total_monto_usd >= float(offset.max_monto_usd):
        limite_alcanzado = "monto"

    if resumen:
        resumen.total_unidades = total_unidades
        resumen.total_monto_ars = total_monto_ars
        resumen.total_monto_usd = total_monto_usd
        resumen.cantidad_ventas = consumos_creados
        resumen.limite_alcanzado = limite_alcanzado
    else:
        resumen = OffsetIndividualResumen(
            offset_id=offset_id,
            total_unidades=total_unidades,
            total_monto_ars=total_monto_ars,
            total_monto_usd=total_monto_usd,
            cantidad_ventas=consumos_creados,
            limite_alcanzado=limite_alcanzado,
        )
        db.add(resumen)

    # Actualizar monto_consumido en el offset
    offset.monto_consumido = total_monto_ars

    db.commit()

    return {
        "mensaje": f"Recálculo completado para offset {offset.descripcion or offset.id}",
        "consumos_creados": consumos_creados,
        "total_unidades": total_unidades,
        "total_monto_ars": total_monto_ars,
        "total_monto_usd": total_monto_usd,
        "limite_alcanzado": limite_alcanzado,
    }


@router.get("/offsets-con-limites-resumen")
def obtener_resumen_todos_offsets_con_limites(
    db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)
):
    """Obtiene un resumen combinado de todos los offsets con límites (grupos e individuales)"""
    resultado = {
        "grupos": [],
        "individuales": [],
        "totales": {
            "total_grupos": 0,
            "total_individuales": 0,
            "grupos_con_limite_alcanzado": 0,
            "individuales_con_limite_alcanzado": 0,
        },
    }

    # Obtener grupos con límites
    grupos_con_limites = (
        db.query(OffsetGrupo)
        .join(OffsetGanancia, OffsetGrupo.id == OffsetGanancia.grupo_id)
        .filter(or_(OffsetGanancia.max_unidades.isnot(None), OffsetGanancia.max_monto_usd.isnot(None)))
        .distinct()
        .all()
    )

    # Prefetch resumenes y offsets-con-límite en dos queries bounded (una por
    # tipo), en vez de resolverlos por-grupo dentro del loop.
    _grupo_ids = [g.id for g in grupos_con_limites]
    _resumenes_grupo = fetch_resumenes_grupo(db, _grupo_ids)
    # Tie-break determinístico: el offset de menor id gana (antes era .first()
    # sin ORDER BY -> no determinístico). Ver design.md §4.
    _offsets_limite_grupo = fetch_offsets_limite_por_grupo(db, _grupo_ids)

    for grupo in grupos_con_limites:
        resumen = _resumenes_grupo.get(grupo.id)

        offset_limite = _offsets_limite_grupo.get(grupo.id)

        grupo_info = {
            "tipo": "grupo",
            "id": grupo.id,
            "nombre": grupo.nombre,
            "total_unidades": resumen.total_unidades if resumen else 0,
            "total_monto_usd": float(resumen.total_monto_usd) if resumen and resumen.total_monto_usd else 0,
            "max_unidades": offset_limite.max_unidades if offset_limite else None,
            "max_monto_usd": float(offset_limite.max_monto_usd)
            if offset_limite and offset_limite.max_monto_usd
            else None,
            "limite_alcanzado": resumen.limite_alcanzado if resumen else None,
        }
        resultado["grupos"].append(grupo_info)

        if resumen and resumen.limite_alcanzado:
            resultado["totales"]["grupos_con_limite_alcanzado"] += 1

    resultado["totales"]["total_grupos"] = len(grupos_con_limites)

    # Obtener offsets individuales con límites
    offsets_individuales = (
        db.query(OffsetGanancia)
        .filter(
            OffsetGanancia.grupo_id.is_(None),
            or_(OffsetGanancia.max_unidades.isnot(None), OffsetGanancia.max_monto_usd.isnot(None)),
        )
        .all()
    )

    _offset_ids = [o.id for o in offsets_individuales]
    _resumenes_individuales = fetch_resumenes_individuales(db, _offset_ids)

    for offset in offsets_individuales:
        resumen = _resumenes_individuales.get(offset.id)

        # Determinar nivel
        if offset.item_id:
            nivel = "producto"
        elif offset.marca:
            nivel = "marca"
        elif offset.categoria:
            nivel = "categoria"
        else:
            nivel = "subcategoria"

        offset_info = {
            "tipo": "individual",
            "id": offset.id,
            "descripcion": offset.descripcion,
            "nivel": nivel,
            "total_unidades": resumen.total_unidades if resumen else 0,
            "total_monto_usd": float(resumen.total_monto_usd) if resumen and resumen.total_monto_usd else 0,
            "max_unidades": offset.max_unidades,
            "max_monto_usd": float(offset.max_monto_usd) if offset.max_monto_usd else None,
            "limite_alcanzado": resumen.limite_alcanzado if resumen else None,
        }
        resultado["individuales"].append(offset_info)

        if resumen and resumen.limite_alcanzado:
            resultado["totales"]["individuales_con_limite_alcanzado"] += 1

    resultado["totales"]["total_individuales"] = len(offsets_individuales)

    return resultado
