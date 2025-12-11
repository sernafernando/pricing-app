"""
Script para recalcular el consumo de todos los grupos de offsets con límites.
Lee las ventas ML, fuera de ML y Tienda Nube y regenera la tabla offset_grupo_consumo y offset_grupo_resumen.

Soporta dos modos de matching:
1. Por offsets individuales del grupo (item_id específicos)
2. Por filtros de grupo (combinaciones de marca/categoría/subcategoría/item_id)

Ejecutar:
    python app/scripts/recalcular_consumo_grupos.py

Opciones:
    --grupo-id <id>   Recalcular solo un grupo específico
    --desde <fecha>   Fecha desde en formato YYYY-MM-DD (por defecto, toma fecha_desde de cada offset)
"""
import sys
from pathlib import Path

# Add backend directory to path
backend_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(backend_dir))

from dotenv import load_dotenv
env_path = backend_dir / '.env'
load_dotenv(dotenv_path=env_path)

import argparse
from datetime import datetime, date
from sqlalchemy import or_, text
from decimal import Decimal

from app.core.database import SessionLocal
from app.models.offset_ganancia import OffsetGanancia
from app.models.offset_grupo import OffsetGrupo
from app.models.offset_grupo_filtro import OffsetGrupoFiltro
from app.models.offset_grupo_consumo import OffsetGrupoConsumo, OffsetGrupoResumen
from app.models.cur_exch_history import CurExchHistory


def obtener_cotizacion_actual(db):
    """Obtiene la cotización USD/ARS más reciente (primero tipo_cambio, fallback CurExchHistory)"""
    from app.models.tipo_cambio import TipoCambio
    # Primero intentar con tipo_cambio
    tc = db.query(TipoCambio).filter(TipoCambio.moneda == "USD").order_by(TipoCambio.fecha.desc()).first()
    if tc and tc.venta:
        return float(tc.venta)
    # Fallback a CurExchHistory
    tc_fallback = db.query(CurExchHistory).order_by(CurExchHistory.ceh_cd.desc()).first()
    return float(tc_fallback.ceh_exchange) if tc_fallback else 1000.0


def construir_condicion_filtros(filtros, tabla_alias="m"):
    """
    Construye condiciones SQL para los filtros del grupo.
    Los filtros se combinan con OR entre sí, y dentro de cada filtro se combinan con AND.
    """
    if not filtros:
        return None, {}

    condiciones = []
    params = {}

    for i, filtro in enumerate(filtros):
        subcondiciones = []
        if filtro.marca:
            subcondiciones.append(f"{tabla_alias}.marca = :filtro_marca_{i}")
            params[f"filtro_marca_{i}"] = filtro.marca
        if filtro.categoria:
            subcondiciones.append(f"{tabla_alias}.categoria = :filtro_categoria_{i}")
            params[f"filtro_categoria_{i}"] = filtro.categoria
        if filtro.subcategoria_id:
            # Para subcategoría necesitamos hacer join con productos_erp
            subcondiciones.append(f"{tabla_alias}.item_id IN (SELECT item_id FROM productos_erp WHERE subcategoria_id = :filtro_subcat_{i})")
            params[f"filtro_subcat_{i}"] = filtro.subcategoria_id
        if filtro.item_id:
            subcondiciones.append(f"{tabla_alias}.item_id = :filtro_item_{i}")
            params[f"filtro_item_{i}"] = filtro.item_id

        if subcondiciones:
            condiciones.append("(" + " AND ".join(subcondiciones) + ")")

    if condiciones:
        return "(" + " OR ".join(condiciones) + ")", params

    return None, {}


def venta_matchea_filtro(venta, filtro):
    """
    Verifica si una venta matchea con un filtro específico.
    Todos los campos del filtro que no son None deben coincidir.
    """
    if filtro.marca and venta.marca != filtro.marca:
        return False
    if filtro.categoria and venta.categoria != filtro.categoria:
        return False
    if filtro.item_id and venta.item_id != filtro.item_id:
        return False
    # subcategoria_id no se puede verificar aquí sin join adicional
    return True


def calcular_monto_offset(offset, cantidad, costo, cotizacion):
    """
    Calcula el monto del offset según su tipo.
    Retorna (monto_ars, monto_usd)
    """
    cot = cotizacion if cotizacion and cotizacion > 0 else 1000.0

    if offset.tipo_offset == 'monto_fijo':
        monto = float(offset.monto or 0)
        if offset.moneda == 'USD':
            return monto * cot, monto
        else:
            return monto, monto / cot if cot > 0 else 0

    elif offset.tipo_offset == 'monto_por_unidad':
        monto_por_u = float(offset.monto or 0)
        if offset.moneda == 'USD':
            return monto_por_u * cantidad * cot, monto_por_u * cantidad
        else:
            return monto_por_u * cantidad, monto_por_u * cantidad / cot if cot > 0 else 0

    elif offset.tipo_offset == 'porcentaje_costo':
        porcentaje = float(offset.porcentaje or 0)
        monto_ars = costo * (porcentaje / 100)
        return monto_ars, monto_ars / cot if cot > 0 else 0

    return 0, 0


def recalcular_grupo(db, grupo_id: int, cotizacion: float, verbose: bool = True):
    """
    Recalcula el consumo de un grupo específico.
    Soporta dos modos:
    1. Offsets individuales por item_id (modo tradicional)
    2. Filtros de grupo (marca/categoría/subcategoría/item_id)

    Retorna un dict con estadísticas del proceso.
    """
    grupo = db.query(OffsetGrupo).filter(OffsetGrupo.id == grupo_id).first()
    if not grupo:
        return {"error": f"Grupo {grupo_id} no encontrado"}

    if verbose:
        print(f"\n{'='*60}")
        print(f"Procesando grupo: {grupo.nombre} (ID: {grupo_id})")
        print(f"{'='*60}")

    # Eliminar consumos existentes del grupo
    eliminados = db.query(OffsetGrupoConsumo).filter(
        OffsetGrupoConsumo.grupo_id == grupo_id
    ).delete()
    if verbose:
        print(f"  - Consumos anteriores eliminados: {eliminados}")

    # Obtener offsets del grupo
    offsets_grupo = db.query(OffsetGanancia).filter(
        OffsetGanancia.grupo_id == grupo_id
    ).all()

    # Obtener filtros del grupo
    filtros_grupo = db.query(OffsetGrupoFiltro).filter(
        OffsetGrupoFiltro.grupo_id == grupo_id
    ).all()

    if not offsets_grupo and not filtros_grupo:
        if verbose:
            print(f"  - No hay offsets ni filtros en este grupo")
        return {"grupo_id": grupo_id, "consumos_creados": 0, "mensaje": "Sin offsets ni filtros"}

    # Determinar fecha de inicio (la más antigua de los offsets)
    fecha_inicio = None
    if offsets_grupo:
        fecha_inicio = min(o.fecha_desde for o in offsets_grupo)
    if verbose:
        print(f"  - Fecha inicio offset: {fecha_inicio}")

    # Obtener item_ids de offsets individuales
    item_ids = [o.item_id for o in offsets_grupo if o.item_id]
    if verbose:
        print(f"  - Items directos en el grupo: {len(item_ids)}")
        print(f"  - Filtros de grupo: {len(filtros_grupo)}")

    # Determinar qué canales están habilitados (usar el primer offset del grupo como referencia)
    offset_ref = offsets_grupo[0] if offsets_grupo else None
    aplica_ml = offset_ref.aplica_ml if offset_ref else True
    aplica_fuera = offset_ref.aplica_fuera if offset_ref else True
    aplica_tienda_nube = offset_ref.aplica_tienda_nube if offset_ref else True

    if verbose:
        canales = []
        if aplica_ml:
            canales.append("ML")
        if aplica_fuera:
            canales.append("Fuera")
        if aplica_tienda_nube:
            canales.append("TN")
        print(f"  - Canales habilitados: {', '.join(canales)}")

    consumos_creados = 0
    total_unidades = 0
    total_monto_ars = Decimal('0')
    total_monto_usd = Decimal('0')

    # Construir condición de filtros si hay filtros de grupo
    condicion_filtros, params_filtros = construir_condicion_filtros(filtros_grupo, "m")

    # ========== VENTAS ML ==========
    if aplica_ml:
        # Construir query para ventas ML
        if item_ids and condicion_filtros:
            # Combinar items directos con filtros
            where_clause = f"(m.item_id = ANY(:item_ids) OR {condicion_filtros})"
        elif item_ids:
            where_clause = "m.item_id = ANY(:item_ids)"
        elif condicion_filtros:
            where_clause = condicion_filtros
        else:
            where_clause = "1=0"  # No hay condición, no buscar nada

        query_params = {"fecha_inicio": fecha_inicio}
        if item_ids:
            query_params["item_ids"] = item_ids
        query_params.update(params_filtros)

        ventas_ml_query = text(f"""
            SELECT
                m.id_operacion,
                m.fecha_venta,
                m.item_id,
                m.marca,
                m.categoria,
                m.cantidad,
                m.costo_total_sin_iva,
                m.cotizacion_dolar
            FROM ml_ventas_metricas m
            WHERE {where_clause}
            AND m.fecha_venta >= :fecha_inicio
            ORDER BY m.fecha_venta
        """)

        try:
            ventas_ml = db.execute(ventas_ml_query, query_params).fetchall()
            if verbose:
                print(f"  - Ventas ML encontradas: {len(ventas_ml)}")

            for venta in ventas_ml:
                # Encontrar el offset aplicable
                # Primero buscar por item_id directo
                offset_aplicable = next(
                    (o for o in offsets_grupo if o.item_id == venta.item_id),
                    None
                )

                # Si no hay match directo, verificar si matchea algún filtro
                if not offset_aplicable and filtros_grupo:
                    for filtro in filtros_grupo:
                        if venta_matchea_filtro(venta, filtro):
                            # Usar el primer offset del grupo como referencia para calcular
                            offset_aplicable = offsets_grupo[0] if offsets_grupo else None
                            break

                if not offset_aplicable:
                    continue

                cot = float(venta.cotizacion_dolar) if venta.cotizacion_dolar else cotizacion
                costo = float(venta.costo_total_sin_iva) if venta.costo_total_sin_iva else 0
                monto_offset_ars, monto_offset_usd = calcular_monto_offset(offset_aplicable, venta.cantidad, costo, cot)

                consumo = OffsetGrupoConsumo(
                    grupo_id=grupo_id,
                    id_operacion=venta.id_operacion,
                    tipo_venta='ml',
                    fecha_venta=venta.fecha_venta,
                    item_id=venta.item_id,
                    cantidad=venta.cantidad,
                    offset_id=offset_aplicable.id,
                    monto_offset_aplicado=monto_offset_ars,
                    monto_offset_usd=monto_offset_usd,
                    cotizacion_dolar=cot
                )
                db.add(consumo)
                consumos_creados += 1
                total_unidades += venta.cantidad
                total_monto_ars += Decimal(str(monto_offset_ars))
                total_monto_usd += Decimal(str(monto_offset_usd))

        except Exception as e:
            if verbose:
                print(f"  - Error en ventas ML: {e}")

    # ========== VENTAS FUERA ML ==========
    if aplica_fuera:
        # Construir condición de filtros para tabla fuera ML
        condicion_filtros_fuera, params_filtros_fuera = construir_condicion_filtros(filtros_grupo, "v")

        if item_ids and condicion_filtros_fuera:
            where_clause_fuera = f"(v.item_id = ANY(:item_ids) OR {condicion_filtros_fuera})"
        elif item_ids:
            where_clause_fuera = "v.item_id = ANY(:item_ids)"
        elif condicion_filtros_fuera:
            where_clause_fuera = condicion_filtros_fuera
        else:
            where_clause_fuera = "1=0"

        query_params_fuera = {"fecha_inicio": fecha_inicio}
        if item_ids:
            query_params_fuera["item_ids"] = item_ids
        query_params_fuera.update(params_filtros_fuera)

        ventas_fuera_query = text(f"""
            SELECT
                v.id,
                v.fecha_venta,
                v.item_id,
                v.marca,
                v.categoria,
                v.cantidad,
                v.costo_total,
                v.cotizacion_dolar
            FROM ventas_fuera_ml_metricas v
            WHERE {where_clause_fuera}
            AND v.fecha_venta >= :fecha_inicio
            ORDER BY v.fecha_venta
        """)

        try:
            ventas_fuera = db.execute(ventas_fuera_query, query_params_fuera).fetchall()
            if verbose:
                print(f"  - Ventas fuera ML encontradas: {len(ventas_fuera)}")

            for venta in ventas_fuera:
                offset_aplicable = next(
                    (o for o in offsets_grupo if o.item_id == venta.item_id),
                    None
                )

                if not offset_aplicable and filtros_grupo:
                    for filtro in filtros_grupo:
                        if venta_matchea_filtro(venta, filtro):
                            offset_aplicable = offsets_grupo[0] if offsets_grupo else None
                            break

                if not offset_aplicable:
                    continue

                cot = float(venta.cotizacion_dolar) if venta.cotizacion_dolar else cotizacion
                costo = float(venta.costo_total) if venta.costo_total else 0
                cantidad = int(venta.cantidad) if venta.cantidad else 0
                monto_offset_ars, monto_offset_usd = calcular_monto_offset(offset_aplicable, cantidad, costo, cot)

                consumo = OffsetGrupoConsumo(
                    grupo_id=grupo_id,
                    venta_fuera_id=venta.id,
                    tipo_venta='fuera_ml',
                    fecha_venta=venta.fecha_venta,
                    item_id=venta.item_id,
                    cantidad=cantidad,
                    offset_id=offset_aplicable.id,
                    monto_offset_aplicado=monto_offset_ars,
                    monto_offset_usd=monto_offset_usd,
                    cotizacion_dolar=cot
                )
                db.add(consumo)
                consumos_creados += 1
                total_unidades += cantidad
                total_monto_ars += Decimal(str(monto_offset_ars))
                total_monto_usd += Decimal(str(monto_offset_usd))

        except Exception as e:
            if verbose:
                print(f"  - Advertencia ventas fuera ML: {e}")

    # ========== VENTAS TIENDA NUBE ==========
    if aplica_tienda_nube:
        condicion_filtros_tn, params_filtros_tn = construir_condicion_filtros(filtros_grupo, "t")

        if item_ids and condicion_filtros_tn:
            where_clause_tn = f"(t.item_id = ANY(:item_ids) OR {condicion_filtros_tn})"
        elif item_ids:
            where_clause_tn = "t.item_id = ANY(:item_ids)"
        elif condicion_filtros_tn:
            where_clause_tn = condicion_filtros_tn
        else:
            where_clause_tn = "1=0"

        query_params_tn = {"fecha_inicio": fecha_inicio}
        if item_ids:
            query_params_tn["item_ids"] = item_ids
        query_params_tn.update(params_filtros_tn)

        ventas_tn_query = text(f"""
            SELECT
                t.id,
                t.it_transaction,
                t.fecha_venta,
                t.item_id,
                t.marca,
                t.categoria,
                t.cantidad,
                t.costo_total,
                t.cotizacion_dolar
            FROM ventas_tienda_nube_metricas t
            WHERE {where_clause_tn}
            AND t.fecha_venta >= :fecha_inicio
            ORDER BY t.fecha_venta
        """)

        try:
            ventas_tn = db.execute(ventas_tn_query, query_params_tn).fetchall()
            if verbose:
                print(f"  - Ventas Tienda Nube encontradas: {len(ventas_tn)}")

            for venta in ventas_tn:
                offset_aplicable = next(
                    (o for o in offsets_grupo if o.item_id == venta.item_id),
                    None
                )

                if not offset_aplicable and filtros_grupo:
                    for filtro in filtros_grupo:
                        if venta_matchea_filtro(venta, filtro):
                            offset_aplicable = offsets_grupo[0] if offsets_grupo else None
                            break

                if not offset_aplicable:
                    continue

                cot = float(venta.cotizacion_dolar) if venta.cotizacion_dolar else cotizacion
                costo = float(venta.costo_total) if venta.costo_total else 0
                cantidad = int(venta.cantidad) if venta.cantidad else 0
                monto_offset_ars, monto_offset_usd = calcular_monto_offset(offset_aplicable, cantidad, costo, cot)

                consumo = OffsetGrupoConsumo(
                    grupo_id=grupo_id,
                    venta_fuera_id=venta.id,  # Reutilizamos este campo para TN
                    tipo_venta='tienda_nube',
                    fecha_venta=venta.fecha_venta,
                    item_id=venta.item_id,
                    cantidad=cantidad,
                    offset_id=offset_aplicable.id,
                    monto_offset_aplicado=monto_offset_ars,
                    monto_offset_usd=monto_offset_usd,
                    cotizacion_dolar=cot
                )
                db.add(consumo)
                consumos_creados += 1
                total_unidades += cantidad
                total_monto_ars += Decimal(str(monto_offset_ars))
                total_monto_usd += Decimal(str(monto_offset_usd))

        except Exception as e:
            if verbose:
                print(f"  - Advertencia ventas Tienda Nube: {e}")

    # Actualizar o crear resumen
    resumen = db.query(OffsetGrupoResumen).filter(
        OffsetGrupoResumen.grupo_id == grupo_id
    ).first()

    # Verificar si se alcanzó algún límite
    offset_con_limite = next(
        (o for o in offsets_grupo if o.max_unidades or o.max_monto_usd),
        None
    )

    limite_alcanzado = None
    fecha_limite_alcanzado = None

    if offset_con_limite:
        if offset_con_limite.max_unidades and total_unidades >= offset_con_limite.max_unidades:
            limite_alcanzado = 'unidades'
        elif offset_con_limite.max_monto_usd and float(total_monto_usd) >= offset_con_limite.max_monto_usd:
            limite_alcanzado = 'monto'

        # Si se alcanzó límite, buscar cuándo
        if limite_alcanzado:
            # Obtener último consumo que alcanzó el límite
            consumos_ordenados = db.query(OffsetGrupoConsumo).filter(
                OffsetGrupoConsumo.grupo_id == grupo_id
            ).order_by(OffsetGrupoConsumo.fecha_venta).all()

            acum_unidades = 0
            acum_monto_usd = Decimal('0')
            for c in consumos_ordenados:
                acum_unidades += c.cantidad
                acum_monto_usd += c.monto_offset_usd or Decimal('0')

                if limite_alcanzado == 'unidades' and acum_unidades >= offset_con_limite.max_unidades:
                    fecha_limite_alcanzado = c.fecha_venta
                    break
                if limite_alcanzado == 'monto' and float(acum_monto_usd) >= offset_con_limite.max_monto_usd:
                    fecha_limite_alcanzado = c.fecha_venta
                    break

    if resumen:
        resumen.total_unidades = total_unidades
        resumen.total_monto_ars = total_monto_ars
        resumen.total_monto_usd = total_monto_usd
        resumen.cantidad_ventas = consumos_creados
        resumen.limite_alcanzado = limite_alcanzado
        resumen.fecha_limite_alcanzado = fecha_limite_alcanzado
    else:
        resumen = OffsetGrupoResumen(
            grupo_id=grupo_id,
            total_unidades=total_unidades,
            total_monto_ars=total_monto_ars,
            total_monto_usd=total_monto_usd,
            cantidad_ventas=consumos_creados,
            limite_alcanzado=limite_alcanzado,
            fecha_limite_alcanzado=fecha_limite_alcanzado
        )
        db.add(resumen)

    db.commit()

    if verbose:
        print(f"  - Consumos creados: {consumos_creados}")
        print(f"  - Total unidades: {total_unidades}")
        print(f"  - Total monto ARS: ${float(total_monto_ars):,.2f}")
        print(f"  - Total monto USD: U$S{float(total_monto_usd):,.2f}")
        if limite_alcanzado:
            print(f"  - LIMITE ALCANZADO: {limite_alcanzado}")
            print(f"  - Fecha límite: {fecha_limite_alcanzado}")

    return {
        "grupo_id": grupo_id,
        "grupo_nombre": grupo.nombre,
        "consumos_creados": consumos_creados,
        "total_unidades": total_unidades,
        "total_monto_ars": float(total_monto_ars),
        "total_monto_usd": float(total_monto_usd),
        "limite_alcanzado": limite_alcanzado,
        "fecha_limite_alcanzado": fecha_limite_alcanzado
    }


def main():
    parser = argparse.ArgumentParser(description='Recalcular consumo de grupos de offsets')
    parser.add_argument('--grupo-id', type=int, help='ID de grupo específico a recalcular')
    parser.add_argument('--quiet', action='store_true', help='Modo silencioso')
    args = parser.parse_args()

    verbose = not args.quiet

    if verbose:
        print("=" * 60)
        print("RECALCULAR CONSUMO DE GRUPOS DE OFFSETS")
        print("=" * 60)
        print(f"Ejecutado: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    db = SessionLocal()

    try:
        cotizacion = obtener_cotizacion_actual(db)
        if verbose:
            print(f"Cotización USD/ARS: ${cotizacion:,.2f}")

        if args.grupo_id:
            # Recalcular solo un grupo
            resultado = recalcular_grupo(db, args.grupo_id, cotizacion, verbose)
            if "error" in resultado:
                print(f"Error: {resultado['error']}")
                return 1
        else:
            # Recalcular todos los grupos que tienen:
            # 1. Offsets con límites (max_unidades o max_monto_usd)
            # 2. Filtros de grupo configurados
            from sqlalchemy.orm import aliased

            # Grupos con offsets con límites
            grupos_con_limites = db.query(OffsetGrupo).join(
                OffsetGanancia, OffsetGrupo.id == OffsetGanancia.grupo_id
            ).filter(
                or_(
                    OffsetGanancia.max_unidades.isnot(None),
                    OffsetGanancia.max_monto_usd.isnot(None)
                )
            ).distinct().all()

            # Grupos con filtros
            grupos_con_filtros = db.query(OffsetGrupo).join(
                OffsetGrupoFiltro, OffsetGrupo.id == OffsetGrupoFiltro.grupo_id
            ).distinct().all()

            # Combinar y eliminar duplicados
            grupos_ids_procesados = set()
            grupos_a_procesar = []

            for grupo in grupos_con_limites + grupos_con_filtros:
                if grupo.id not in grupos_ids_procesados:
                    grupos_ids_procesados.add(grupo.id)
                    grupos_a_procesar.append(grupo)

            if verbose:
                print(f"\nGrupos con límites: {len(grupos_con_limites)}")
                print(f"Grupos con filtros: {len(grupos_con_filtros)}")
                print(f"Total grupos a procesar (únicos): {len(grupos_a_procesar)}")

            for grupo in grupos_a_procesar:
                recalcular_grupo(db, grupo.id, cotizacion, verbose)

        if verbose:
            print("\n" + "=" * 60)
            print("COMPLETADO")
            print("=" * 60)

        return 0

    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
        db.rollback()
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
