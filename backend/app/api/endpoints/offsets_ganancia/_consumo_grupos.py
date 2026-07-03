from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import or_, text

from app.core.database import get_db
from app.models.offset_ganancia import OffsetGanancia
from app.models.offset_grupo import OffsetGrupo
from app.models.offset_grupo_filtro import OffsetGrupoFiltro
from app.models.offset_grupo_consumo import OffsetGrupoConsumo, OffsetGrupoResumen
from app.models.cur_exch_history import CurExchHistory
from app.models.usuario import Usuario
from app.api.deps import get_current_user
from app.services.permisos_service import verificar_permiso
from app.services.offset_resumen_service import (
    fetch_offsets_limite_por_grupo,
    fetch_resumenes_grupo,
)

router = APIRouter()


@router.get("/offset-grupos/{grupo_id}/consumo")
def obtener_consumo_grupo(
    grupo_id: int, db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)
):
    """Obtiene el detalle de consumo de un grupo de offsets"""
    grupo = db.query(OffsetGrupo).filter(OffsetGrupo.id == grupo_id).first()
    if not grupo:
        raise HTTPException(404, "Grupo no encontrado")

    # Obtener consumos del grupo
    consumos = (
        db.query(OffsetGrupoConsumo)
        .filter(OffsetGrupoConsumo.grupo_id == grupo_id)
        .order_by(OffsetGrupoConsumo.fecha_venta.desc())
        .limit(100)
        .all()
    )

    return {
        "grupo": {"id": grupo.id, "nombre": grupo.nombre, "descripcion": grupo.descripcion},
        "consumos": [
            {
                "id": c.id,
                "grupo_id": c.grupo_id,
                "id_operacion": c.id_operacion,
                "venta_fuera_id": c.venta_fuera_id,
                "tipo_venta": c.tipo_venta,
                "fecha_venta": c.fecha_venta.isoformat() if c.fecha_venta else None,
                "item_id": c.item_id,
                "cantidad": c.cantidad,
                "offset_id": c.offset_id,
                "monto_offset_aplicado": float(c.monto_offset_aplicado) if c.monto_offset_aplicado else 0,
                "monto_offset_usd": float(c.monto_offset_usd) if c.monto_offset_usd else None,
                "cotizacion_dolar": float(c.cotizacion_dolar) if c.cotizacion_dolar else None,
            }
            for c in consumos
        ],
    }


@router.get("/offset-grupos-resumen")
def obtener_resumen_grupos(db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    """Obtiene el resumen de consumo de todos los grupos con límites"""
    # Obtener grupos que tienen offsets con límites
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
    _offsets_limite = fetch_offsets_limite_por_grupo(db, _grupo_ids)

    resultado = []
    for grupo in grupos_con_limites:
        # Obtener resumen si existe
        resumen = _resumenes_grupo.get(grupo.id)

        # Obtener límites del offset (asumimos que todos los offsets del grupo tienen el mismo límite)
        offset_con_limite = _offsets_limite.get(grupo.id)

        max_unidades = offset_con_limite.max_unidades if offset_con_limite else None
        max_monto_usd = offset_con_limite.max_monto_usd if offset_con_limite else None

        if resumen:
            total_unidades = resumen.total_unidades or 0
            total_monto_usd = float(resumen.total_monto_usd or 0)

            resultado.append(
                {
                    "grupo_id": grupo.id,
                    "grupo_nombre": grupo.nombre,
                    "total_unidades": total_unidades,
                    "total_monto_ars": float(resumen.total_monto_ars or 0),
                    "total_monto_usd": total_monto_usd,
                    "cantidad_ventas": resumen.cantidad_ventas or 0,
                    "limite_alcanzado": resumen.limite_alcanzado,
                    "fecha_limite_alcanzado": resumen.fecha_limite_alcanzado.isoformat()
                    if resumen.fecha_limite_alcanzado
                    else None,
                    "max_unidades": max_unidades,
                    "max_monto_usd": max_monto_usd,
                    "porcentaje_consumido_unidades": (total_unidades / max_unidades * 100) if max_unidades else None,
                    "porcentaje_consumido_monto": (total_monto_usd / max_monto_usd * 100) if max_monto_usd else None,
                }
            )
        else:
            resultado.append(
                {
                    "grupo_id": grupo.id,
                    "grupo_nombre": grupo.nombre,
                    "total_unidades": 0,
                    "total_monto_ars": 0,
                    "total_monto_usd": 0,
                    "cantidad_ventas": 0,
                    "limite_alcanzado": None,
                    "fecha_limite_alcanzado": None,
                    "max_unidades": max_unidades,
                    "max_monto_usd": max_monto_usd,
                    "porcentaje_consumido_unidades": 0 if max_unidades else None,
                    "porcentaje_consumido_monto": 0 if max_monto_usd else None,
                }
            )

    return resultado


@router.post("/offset-grupos/{grupo_id}/recalcular")
def recalcular_consumo_grupo(
    grupo_id: int, db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)
):
    """
    Recalcula el consumo de un grupo desde cero.
    Lee las ventas ML y fuera de ML y recalcula todo el consumo del grupo.
    Soporta tanto offsets con item_id directo como filtros de grupo (marca, categoría, etc.)
    """
    if not verificar_permiso(db, current_user, "config.editar_constantes"):
        raise HTTPException(status_code=403, detail="No tienes permiso para gestionar offsets de ganancia")
    grupo = db.query(OffsetGrupo).filter(OffsetGrupo.id == grupo_id).first()
    if not grupo:
        raise HTTPException(404, "Grupo no encontrado")

    # Eliminar consumos existentes del grupo
    db.query(OffsetGrupoConsumo).filter(OffsetGrupoConsumo.grupo_id == grupo_id).delete()

    # Obtener offsets del grupo
    offsets_grupo = db.query(OffsetGanancia).filter(OffsetGanancia.grupo_id == grupo_id).all()

    if not offsets_grupo:
        return {"mensaje": "No hay offsets en este grupo", "consumos_creados": 0}

    # Obtener filtros del grupo
    filtros_grupo = db.query(OffsetGrupoFiltro).filter(OffsetGrupoFiltro.grupo_id == grupo_id).all()

    # Determinar fecha de inicio (la más antigua de los offsets)
    fecha_inicio = min(o.fecha_desde for o in offsets_grupo)

    # Obtener item_ids directos de los offsets
    item_ids_directos = [o.item_id for o in offsets_grupo if o.item_id]

    # Obtener tipo cambio actual para conversiones (primero tipo_cambio, fallback CurExchHistory)
    from app.models.tipo_cambio import TipoCambio

    tc = db.query(TipoCambio).filter(TipoCambio.moneda == "USD").order_by(TipoCambio.fecha.desc()).first()
    if tc and tc.venta:
        cotizacion = float(tc.venta)
    else:
        tc_actual = db.query(CurExchHistory).order_by(CurExchHistory.ceh_cd.desc()).first()
        cotizacion = float(tc_actual.ceh_exchange) if tc_actual else 1000.0

    consumos_creados = 0
    total_unidades = 0
    total_monto_ars = 0
    total_monto_usd = 0
    operaciones_procesadas = set()  # Para evitar duplicados

    # Tomar el primer offset del grupo para obtener tipo y valores (asumimos todos tienen el mismo tipo)
    offset_ref = offsets_grupo[0]

    def calcular_monto_offset(offset, cantidad, costo, cot):
        """Calcula el monto del offset según su tipo"""
        if offset.tipo_offset == "monto_fijo":
            monto_offset = float(offset.monto or 0)
            if offset.moneda == "USD":
                return monto_offset * cot, monto_offset
            else:
                return monto_offset, monto_offset / cot if cot > 0 else 0
        elif offset.tipo_offset == "monto_por_unidad":
            monto_por_u = float(offset.monto or 0)
            if offset.moneda == "USD":
                return monto_por_u * cantidad * cot, monto_por_u * cantidad
            else:
                return monto_por_u * cantidad, monto_por_u * cantidad / cot if cot > 0 else 0
        elif offset.tipo_offset == "porcentaje_costo":
            porcentaje = float(offset.porcentaje or 0)
            monto_ars = costo * (porcentaje / 100)
            return monto_ars, monto_ars / cot if cot > 0 else 0
        return 0, 0

    def venta_matchea_filtros(marca, categoria, item_id):
        """Verifica si una venta matchea con algún filtro del grupo"""
        if not filtros_grupo:
            return False
        for f in filtros_grupo:
            matchea = True
            if f.marca and f.marca != marca:
                matchea = False
            if f.categoria and f.categoria != categoria:
                matchea = False
            if f.item_id and f.item_id != item_id:
                matchea = False
            if matchea:
                return True
        return False

    # ============================================
    # Procesar ventas ML con item_ids directos
    # ============================================
    if item_ids_directos:
        ventas_ml_query = text("""
            SELECT
                m.id_operacion,
                m.fecha_venta,
                m.item_id,
                m.cantidad,
                m.costo_total_sin_iva,
                m.cotizacion_dolar,
                m.marca,
                m.categoria
            FROM ml_ventas_metricas m
            WHERE m.item_id = ANY(:item_ids)
            AND m.fecha_venta >= :fecha_inicio
            ORDER BY m.fecha_venta
        """)

        ventas_ml = db.execute(
            ventas_ml_query, {"item_ids": item_ids_directos, "fecha_inicio": fecha_inicio}
        ).fetchall()

        for venta in ventas_ml:
            offset_aplicable = next((o for o in offsets_grupo if o.item_id == venta.item_id), None)
            if not offset_aplicable:
                continue

            cot = float(venta.cotizacion_dolar) if venta.cotizacion_dolar else cotizacion
            costo = float(venta.costo_total_sin_iva) if venta.costo_total_sin_iva else 0
            monto_offset_ars, monto_offset_usd = calcular_monto_offset(offset_aplicable, venta.cantidad, costo, cot)

            if monto_offset_ars == 0 and monto_offset_usd == 0:
                continue

            consumo = OffsetGrupoConsumo(
                grupo_id=grupo_id,
                id_operacion=venta.id_operacion,
                tipo_venta="ml",
                fecha_venta=venta.fecha_venta,
                item_id=venta.item_id,
                cantidad=venta.cantidad,
                offset_id=offset_aplicable.id,
                monto_offset_aplicado=monto_offset_ars,
                monto_offset_usd=monto_offset_usd,
                cotizacion_dolar=cot,
            )
            db.add(consumo)
            operaciones_procesadas.add(("ml", venta.id_operacion))
            consumos_creados += 1
            total_unidades += venta.cantidad
            total_monto_ars += monto_offset_ars
            total_monto_usd += monto_offset_usd

    # ============================================
    # Procesar ventas ML con filtros de grupo
    # ============================================
    if filtros_grupo:
        # Construir query dinámica basada en filtros (parametrizada para evitar SQLi)
        condiciones_filtro = []
        filtro_params = {"fecha_inicio": fecha_inicio}
        for idx, f in enumerate(filtros_grupo):
            conds = []
            if f.marca:
                key = f"ml_marca_{idx}"
                conds.append(f"m.marca = :{key}")
                filtro_params[key] = f.marca
            if f.categoria:
                key = f"ml_cat_{idx}"
                conds.append(f"m.categoria = :{key}")
                filtro_params[key] = f.categoria
            if f.item_id:
                key = f"ml_item_{idx}"
                conds.append(f"m.item_id = :{key}")
                filtro_params[key] = f.item_id
            if conds:
                condiciones_filtro.append(f"({' AND '.join(conds)})")

        if condiciones_filtro:
            where_filtros = " OR ".join(condiciones_filtro)
            ventas_ml_filtros_query = text(f"""
                SELECT
                    m.id_operacion,
                    m.fecha_venta,
                    m.item_id,
                    m.cantidad,
                    m.costo_total_sin_iva,
                    m.cotizacion_dolar,
                    m.marca,
                    m.categoria
                FROM ml_ventas_metricas m
                WHERE ({where_filtros})
                AND m.fecha_venta >= :fecha_inicio
                ORDER BY m.fecha_venta
            """)

            ventas_ml_filtros = db.execute(ventas_ml_filtros_query, filtro_params).fetchall()

            for venta in ventas_ml_filtros:
                # Skip si ya se procesó
                if ("ml", venta.id_operacion) in operaciones_procesadas:
                    continue

                cot = float(venta.cotizacion_dolar) if venta.cotizacion_dolar else cotizacion
                costo = float(venta.costo_total_sin_iva) if venta.costo_total_sin_iva else 0
                monto_offset_ars, monto_offset_usd = calcular_monto_offset(offset_ref, venta.cantidad, costo, cot)

                if monto_offset_ars == 0 and monto_offset_usd == 0:
                    continue

                consumo = OffsetGrupoConsumo(
                    grupo_id=grupo_id,
                    id_operacion=venta.id_operacion,
                    tipo_venta="ml",
                    fecha_venta=venta.fecha_venta,
                    item_id=venta.item_id,
                    cantidad=venta.cantidad,
                    offset_id=offset_ref.id,
                    monto_offset_aplicado=monto_offset_ars,
                    monto_offset_usd=monto_offset_usd,
                    cotizacion_dolar=cot,
                )
                db.add(consumo)
                operaciones_procesadas.add(("ml", venta.id_operacion))
                consumos_creados += 1
                total_unidades += venta.cantidad
                total_monto_ars += monto_offset_ars
                total_monto_usd += monto_offset_usd

    # ============================================
    # Procesar ventas fuera de ML con item_ids directos
    # ============================================
    if item_ids_directos:
        ventas_fuera_query = text("""
            SELECT
                v.id,
                v.fecha_venta,
                v.item_id,
                v.cantidad,
                v.costo_total,
                v.cotizacion_dolar,
                v.marca,
                v.categoria
            FROM ventas_fuera_ml_metricas v
            WHERE v.item_id = ANY(:item_ids)
            AND v.fecha_venta >= :fecha_inicio
            ORDER BY v.fecha_venta
        """)

        ventas_fuera = db.execute(
            ventas_fuera_query, {"item_ids": item_ids_directos, "fecha_inicio": fecha_inicio}
        ).fetchall()

        for venta in ventas_fuera:
            offset_aplicable = next((o for o in offsets_grupo if o.item_id == venta.item_id), None)
            if not offset_aplicable:
                continue

            cot = float(venta.cotizacion_dolar) if venta.cotizacion_dolar else cotizacion
            costo = float(venta.costo_total) if venta.costo_total else 0
            monto_offset_ars, monto_offset_usd = calcular_monto_offset(offset_aplicable, venta.cantidad, costo, cot)

            if monto_offset_ars == 0 and monto_offset_usd == 0:
                continue

            consumo = OffsetGrupoConsumo(
                grupo_id=grupo_id,
                venta_fuera_id=venta.id,
                tipo_venta="fuera_ml",
                fecha_venta=venta.fecha_venta,
                item_id=venta.item_id,
                cantidad=venta.cantidad,
                offset_id=offset_aplicable.id,
                monto_offset_aplicado=monto_offset_ars,
                monto_offset_usd=monto_offset_usd,
                cotizacion_dolar=cot,
            )
            db.add(consumo)
            operaciones_procesadas.add(("fuera", venta.id))
            consumos_creados += 1
            total_unidades += venta.cantidad
            total_monto_ars += monto_offset_ars
            total_monto_usd += monto_offset_usd

    # ============================================
    # Procesar ventas fuera de ML con filtros de grupo
    # ============================================
    if filtros_grupo:
        condiciones_filtro = []
        filtro_params_fuera = {"fecha_inicio": fecha_inicio}
        for idx, f in enumerate(filtros_grupo):
            conds = []
            if f.marca:
                key = f"fuera_marca_{idx}"
                conds.append(f"v.marca = :{key}")
                filtro_params_fuera[key] = f.marca
            if f.categoria:
                key = f"fuera_cat_{idx}"
                conds.append(f"v.categoria = :{key}")
                filtro_params_fuera[key] = f.categoria
            if f.item_id:
                key = f"fuera_item_{idx}"
                conds.append(f"v.item_id = :{key}")
                filtro_params_fuera[key] = f.item_id
            if conds:
                condiciones_filtro.append(f"({' AND '.join(conds)})")

        if condiciones_filtro:
            where_filtros = " OR ".join(condiciones_filtro)
            ventas_fuera_filtros_query = text(f"""
                SELECT
                    v.id,
                    v.fecha_venta,
                    v.item_id,
                    v.cantidad,
                    v.costo_total,
                    v.cotizacion_dolar,
                    v.marca,
                    v.categoria
                FROM ventas_fuera_ml_metricas v
                WHERE ({where_filtros})
                AND v.fecha_venta >= :fecha_inicio
                ORDER BY v.fecha_venta
            """)

            ventas_fuera_filtros = db.execute(ventas_fuera_filtros_query, filtro_params_fuera).fetchall()

            for venta in ventas_fuera_filtros:
                if ("fuera", venta.id) in operaciones_procesadas:
                    continue

                cot = float(venta.cotizacion_dolar) if venta.cotizacion_dolar else cotizacion
                costo = float(venta.costo_total) if venta.costo_total else 0
                monto_offset_ars, monto_offset_usd = calcular_monto_offset(offset_ref, venta.cantidad, costo, cot)

                if monto_offset_ars == 0 and monto_offset_usd == 0:
                    continue

                consumo = OffsetGrupoConsumo(
                    grupo_id=grupo_id,
                    venta_fuera_id=venta.id,
                    tipo_venta="fuera_ml",
                    fecha_venta=venta.fecha_venta,
                    item_id=venta.item_id,
                    cantidad=venta.cantidad,
                    offset_id=offset_ref.id,
                    monto_offset_aplicado=monto_offset_ars,
                    monto_offset_usd=monto_offset_usd,
                    cotizacion_dolar=cot,
                )
                db.add(consumo)
                operaciones_procesadas.add(("fuera", venta.id))
                consumos_creados += 1
                total_unidades += venta.cantidad
                total_monto_ars += monto_offset_ars
                total_monto_usd += monto_offset_usd

    # Actualizar o crear resumen
    resumen = db.query(OffsetGrupoResumen).filter(OffsetGrupoResumen.grupo_id == grupo_id).first()

    # Verificar si se alcanzó algún límite
    offset_con_limite = next((o for o in offsets_grupo if o.max_unidades or o.max_monto_usd), None)

    limite_alcanzado = None
    if offset_con_limite:
        if offset_con_limite.max_unidades and total_unidades >= offset_con_limite.max_unidades:
            limite_alcanzado = "unidades"
        elif offset_con_limite.max_monto_usd and total_monto_usd >= offset_con_limite.max_monto_usd:
            limite_alcanzado = "monto"

    if resumen:
        resumen.total_unidades = total_unidades
        resumen.total_monto_ars = total_monto_ars
        resumen.total_monto_usd = total_monto_usd
        resumen.cantidad_ventas = consumos_creados
        resumen.limite_alcanzado = limite_alcanzado
    else:
        resumen = OffsetGrupoResumen(
            grupo_id=grupo_id,
            total_unidades=total_unidades,
            total_monto_ars=total_monto_ars,
            total_monto_usd=total_monto_usd,
            cantidad_ventas=consumos_creados,
            limite_alcanzado=limite_alcanzado,
        )
        db.add(resumen)

    # Actualizar monto_consumido en todos los offsets del grupo
    for offset in offsets_grupo:
        offset.monto_consumido = total_monto_ars

    db.commit()

    return {
        "mensaje": f"Recálculo completado para grupo {grupo.nombre}",
        "consumos_creados": consumos_creados,
        "total_unidades": total_unidades,
        "total_monto_ars": total_monto_ars,
        "total_monto_usd": total_monto_usd,
        "limite_alcanzado": limite_alcanzado,
    }
