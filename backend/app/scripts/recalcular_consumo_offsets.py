"""
Script para recalcular el consumo de offsets con límites (grupos e individuales).
Lee las ventas ML y regenera las tablas de consumo y resumen.

Ejecutar:
    python app/scripts/recalcular_consumo_offsets.py

Opciones:
    --tipo <grupos|individuales|todos>   Qué tipo de offsets recalcular (default: todos)
    --grupo-id <id>   Recalcular solo un grupo específico
    --offset-id <id>  Recalcular solo un offset individual específico
    --quiet           Modo silencioso
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
from datetime import datetime
from sqlalchemy import or_, and_, text
from decimal import Decimal

from app.core.database import SessionLocal
from app.models.offset_ganancia import OffsetGanancia
from app.models.offset_grupo import OffsetGrupo
from app.models.offset_grupo_consumo import OffsetGrupoConsumo, OffsetGrupoResumen
from app.models.offset_individual_consumo import OffsetIndividualConsumo, OffsetIndividualResumen
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


def calcular_monto_offset(offset, cantidad, costo, cotizacion):
    """Calcula el monto del offset en ARS y USD"""
    if offset.tipo_offset == 'monto_fijo':
        monto_offset = float(offset.monto or 0)
        if offset.moneda == 'USD':
            monto_offset_ars = monto_offset * cotizacion
            monto_offset_usd = monto_offset
        else:
            monto_offset_ars = monto_offset
            monto_offset_usd = monto_offset / cotizacion if cotizacion > 0 else 0
    elif offset.tipo_offset == 'monto_por_unidad':
        monto_por_u = float(offset.monto or 0)
        if offset.moneda == 'USD':
            monto_offset_ars = monto_por_u * cantidad * cotizacion
            monto_offset_usd = monto_por_u * cantidad
        else:
            monto_offset_ars = monto_por_u * cantidad
            monto_offset_usd = monto_por_u * cantidad / cotizacion if cotizacion > 0 else 0
    elif offset.tipo_offset == 'porcentaje_costo':
        porcentaje = float(offset.porcentaje or 0)
        monto_offset_ars = costo * cantidad * (porcentaje / 100)
        monto_offset_usd = monto_offset_ars / cotizacion if cotizacion > 0 else 0
    else:
        monto_offset_ars = 0
        monto_offset_usd = 0

    return monto_offset_ars, monto_offset_usd


def recalcular_grupo(db, grupo_id: int, cotizacion: float, verbose: bool = True):
    """
    Recalcula el consumo de un grupo específico.
    Retorna un dict con estadísticas del proceso.
    """
    grupo = db.query(OffsetGrupo).filter(OffsetGrupo.id == grupo_id).first()
    if not grupo:
        return {"error": f"Grupo {grupo_id} no encontrado"}

    if verbose:
        print(f"\n  📦 Grupo: {grupo.nombre} (ID: {grupo_id})")

    # Eliminar consumos existentes del grupo
    eliminados = db.query(OffsetGrupoConsumo).filter(
        OffsetGrupoConsumo.grupo_id == grupo_id
    ).delete()

    # Obtener offsets del grupo
    offsets_grupo = db.query(OffsetGanancia).filter(
        OffsetGanancia.grupo_id == grupo_id
    ).all()

    if not offsets_grupo:
        if verbose:
            print(f"     Sin offsets en el grupo")
        return {"grupo_id": grupo_id, "consumos_creados": 0, "mensaje": "Sin offsets"}

    # Determinar fecha de inicio (la más antigua de los offsets)
    fecha_inicio = min(o.fecha_desde for o in offsets_grupo)

    # Obtener item_ids del grupo
    item_ids = [o.item_id for o in offsets_grupo if o.item_id]

    consumos_creados = 0
    total_unidades = 0
    total_monto_ars = Decimal('0')
    total_monto_usd = Decimal('0')

    if item_ids:
        # Obtener ventas ML
        ventas_ml_query = text("""
            SELECT
                m.id_operacion,
                m.fecha_venta,
                m.item_id,
                m.cantidad,
                m.costo_total_sin_iva,
                m.cotizacion_dolar,
                m.mlp_official_store_id
            FROM ml_ventas_metricas m
            WHERE m.item_id = ANY(:item_ids)
            AND m.fecha_venta >= :fecha_inicio
            ORDER BY m.fecha_venta
        """)

        ventas_ml = db.execute(ventas_ml_query, {
            "item_ids": item_ids,
            "fecha_inicio": fecha_inicio
        }).fetchall()

        for venta in ventas_ml:
            offset_aplicable = next(
                (o for o in offsets_grupo if o.item_id == venta.item_id),
                None
            )

            if not offset_aplicable:
                continue

            cot = float(venta.cotizacion_dolar) if venta.cotizacion_dolar else cotizacion
            costo = float(venta.costo_total_sin_iva) if venta.costo_total_sin_iva else 0

            monto_offset_ars, monto_offset_usd = calcular_monto_offset(
                offset_aplicable, venta.cantidad, costo / venta.cantidad if venta.cantidad else 0, cot
            )

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
                cotizacion_dolar=cot,
                tienda_oficial=str(venta.mlp_official_store_id) if venta.mlp_official_store_id else None
            )
            db.add(consumo)
            consumos_creados += 1
            total_unidades += venta.cantidad
            total_monto_ars += Decimal(str(monto_offset_ars))
            total_monto_usd += Decimal(str(monto_offset_usd))

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
        limite_info = f" | LÍMITE: {limite_alcanzado}" if limite_alcanzado else ""
        print(f"     {consumos_creados} consumos | {total_unidades} un. | ${float(total_monto_ars):,.0f} ARS{limite_info}")

    return {
        "grupo_id": grupo_id,
        "grupo_nombre": grupo.nombre,
        "consumos_creados": consumos_creados,
        "total_unidades": total_unidades,
        "total_monto_ars": float(total_monto_ars),
        "total_monto_usd": float(total_monto_usd),
        "limite_alcanzado": limite_alcanzado
    }


def recalcular_offset_individual(db, offset: OffsetGanancia, cotizacion: float, verbose: bool = True):
    """
    Recalcula el consumo de un offset individual (sin grupo).
    """
    if verbose:
        desc = offset.descripcion or f"Offset {offset.id}"
        nivel = "producto" if offset.item_id else "marca" if offset.marca else "categoría" if offset.categoria else "subcategoría"
        print(f"\n  📌 {desc} (ID: {offset.id}, nivel: {nivel})")

    # Eliminar consumos existentes del offset
    eliminados = db.query(OffsetIndividualConsumo).filter(
        OffsetIndividualConsumo.offset_id == offset.id
    ).delete()

    consumos_creados = 0
    total_unidades = 0
    total_monto_ars = Decimal('0')
    total_monto_usd = Decimal('0')

    fecha_inicio = offset.fecha_desde

    # Construir query según el nivel del offset
    if offset.item_id:
        # Offset por producto específico
        ventas_query = text("""
            SELECT
                m.id_operacion,
                m.fecha_venta,
                m.item_id,
                m.cantidad,
                m.costo_total_sin_iva,
                m.cotizacion_dolar,
                m.mlp_official_store_id
            FROM ml_ventas_metricas m
            WHERE m.item_id = :item_id
            AND m.fecha_venta >= :fecha_inicio
            ORDER BY m.fecha_venta
        """)
        params = {"item_id": offset.item_id, "fecha_inicio": fecha_inicio}

    elif offset.marca and not offset.categoria and not offset.subcategoria_id:
        # Offset por marca (sin categoría/subcategoría específica)
        ventas_query = text("""
            SELECT
                m.id_operacion,
                m.fecha_venta,
                m.item_id,
                m.cantidad,
                m.costo_total_sin_iva,
                m.cotizacion_dolar,
                m.mlp_official_store_id
            FROM ml_ventas_metricas m
            WHERE m.marca = :marca
            AND m.fecha_venta >= :fecha_inicio
            ORDER BY m.fecha_venta
        """)
        params = {"marca": offset.marca, "fecha_inicio": fecha_inicio}

    elif offset.categoria and not offset.marca and not offset.subcategoria_id:
        # Offset por categoría
        ventas_query = text("""
            SELECT
                m.id_operacion,
                m.fecha_venta,
                m.item_id,
                m.cantidad,
                m.costo_total_sin_iva,
                m.cotizacion_dolar,
                m.mlp_official_store_id
            FROM ml_ventas_metricas m
            WHERE m.categoria = :categoria
            AND m.fecha_venta >= :fecha_inicio
            ORDER BY m.fecha_venta
        """)
        params = {"categoria": offset.categoria, "fecha_inicio": fecha_inicio}

    elif offset.subcategoria_id:
        # Offset por subcategoría
        ventas_query = text("""
            SELECT
                m.id_operacion,
                m.fecha_venta,
                m.item_id,
                m.cantidad,
                m.costo_total_sin_iva,
                m.cotizacion_dolar,
                m.mlp_official_store_id
            FROM ml_ventas_metricas m
            WHERE m.subcategoria = (SELECT subcat_desc FROM tb_subcategory WHERE subcat_id = :subcat_id LIMIT 1)
            AND m.fecha_venta >= :fecha_inicio
            ORDER BY m.fecha_venta
        """)
        params = {"subcat_id": offset.subcategoria_id, "fecha_inicio": fecha_inicio}
    else:
        if verbose:
            print(f"     ⚠️ Offset sin criterio válido")
        return {"offset_id": offset.id, "consumos_creados": 0, "mensaje": "Sin criterio válido"}

    ventas = db.execute(ventas_query, params).fetchall()

    for venta in ventas:
        cot = float(venta.cotizacion_dolar) if venta.cotizacion_dolar else cotizacion
        costo_unitario = (float(venta.costo_total_sin_iva) / venta.cantidad) if venta.cantidad and venta.costo_total_sin_iva else 0

        monto_offset_ars, monto_offset_usd = calcular_monto_offset(
            offset, venta.cantidad, costo_unitario, cot
        )

        consumo = OffsetIndividualConsumo(
            offset_id=offset.id,
            id_operacion=venta.id_operacion,
            tipo_venta='ml',
            fecha_venta=venta.fecha_venta,
            item_id=venta.item_id,
            cantidad=venta.cantidad,
            monto_offset_aplicado=monto_offset_ars,
            monto_offset_usd=monto_offset_usd,
            cotizacion_dolar=cot,
            tienda_oficial=str(venta.mlp_official_store_id) if venta.mlp_official_store_id else None
        )
        db.add(consumo)
        consumos_creados += 1
        total_unidades += venta.cantidad
        total_monto_ars += Decimal(str(monto_offset_ars))
        total_monto_usd += Decimal(str(monto_offset_usd))

    # Actualizar o crear resumen
    resumen = db.query(OffsetIndividualResumen).filter(
        OffsetIndividualResumen.offset_id == offset.id
    ).first()

    limite_alcanzado = None
    if offset.max_unidades and total_unidades >= offset.max_unidades:
        limite_alcanzado = 'unidades'
    elif offset.max_monto_usd and float(total_monto_usd) >= offset.max_monto_usd:
        limite_alcanzado = 'monto'

    if resumen:
        resumen.total_unidades = total_unidades
        resumen.total_monto_ars = total_monto_ars
        resumen.total_monto_usd = total_monto_usd
        resumen.cantidad_ventas = consumos_creados
        resumen.limite_alcanzado = limite_alcanzado
    else:
        resumen = OffsetIndividualResumen(
            offset_id=offset.id,
            total_unidades=total_unidades,
            total_monto_ars=total_monto_ars,
            total_monto_usd=total_monto_usd,
            cantidad_ventas=consumos_creados,
            limite_alcanzado=limite_alcanzado
        )
        db.add(resumen)

    db.commit()

    if verbose:
        limite_info = f" | LÍMITE: {limite_alcanzado}" if limite_alcanzado else ""
        print(f"     {consumos_creados} consumos | {total_unidades} un. | ${float(total_monto_ars):,.0f} ARS{limite_info}")

    return {
        "offset_id": offset.id,
        "consumos_creados": consumos_creados,
        "total_unidades": total_unidades,
        "total_monto_ars": float(total_monto_ars),
        "total_monto_usd": float(total_monto_usd),
        "limite_alcanzado": limite_alcanzado
    }


def main():
    parser = argparse.ArgumentParser(description='Recalcular consumo de offsets con límites')
    parser.add_argument('--tipo', choices=['grupos', 'individuales', 'todos'], default='todos',
                        help='Qué tipo de offsets recalcular (default: todos)')
    parser.add_argument('--grupo-id', type=int, help='ID de grupo específico a recalcular')
    parser.add_argument('--offset-id', type=int, help='ID de offset individual específico a recalcular')
    parser.add_argument('--quiet', action='store_true', help='Modo silencioso')
    args = parser.parse_args()

    verbose = not args.quiet

    if verbose:
        print("=" * 60)
        print("RECALCULAR CONSUMO DE OFFSETS")
        print("=" * 60)
        print(f"Ejecutado: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    db = SessionLocal()

    try:
        cotizacion = obtener_cotizacion_actual(db)
        if verbose:
            print(f"Cotización USD/ARS: ${cotizacion:,.2f}")

        total_grupos = 0
        total_individuales = 0

        # Recalcular grupos
        if args.tipo in ['grupos', 'todos'] or args.grupo_id:
            if verbose:
                print(f"\n{'='*60}")
                print("GRUPOS DE OFFSETS")
                print("="*60)

            if args.grupo_id:
                resultado = recalcular_grupo(db, args.grupo_id, cotizacion, verbose)
                if "error" not in resultado:
                    total_grupos = 1
            else:
                grupos_con_limites = db.query(OffsetGrupo).join(
                    OffsetGanancia, OffsetGrupo.id == OffsetGanancia.grupo_id
                ).filter(
                    or_(
                        OffsetGanancia.max_unidades.isnot(None),
                        OffsetGanancia.max_monto_usd.isnot(None)
                    )
                ).distinct().all()

                if verbose:
                    print(f"Grupos con límites: {len(grupos_con_limites)}")

                for grupo in grupos_con_limites:
                    recalcular_grupo(db, grupo.id, cotizacion, verbose)
                    total_grupos += 1

        # Recalcular offsets individuales
        if args.tipo in ['individuales', 'todos'] or args.offset_id:
            if verbose:
                print(f"\n{'='*60}")
                print("OFFSETS INDIVIDUALES")
                print("="*60)

            if args.offset_id:
                offset = db.query(OffsetGanancia).filter(
                    OffsetGanancia.id == args.offset_id,
                    OffsetGanancia.grupo_id.is_(None)
                ).first()
                if offset:
                    recalcular_offset_individual(db, offset, cotizacion, verbose)
                    total_individuales = 1
                else:
                    print(f"Offset {args.offset_id} no encontrado o pertenece a un grupo")
            else:
                # Obtener offsets individuales con límites
                offsets_individuales = db.query(OffsetGanancia).filter(
                    OffsetGanancia.grupo_id.is_(None),
                    or_(
                        OffsetGanancia.max_unidades.isnot(None),
                        OffsetGanancia.max_monto_usd.isnot(None)
                    )
                ).all()

                if verbose:
                    print(f"Offsets individuales con límites: {len(offsets_individuales)}")

                for offset in offsets_individuales:
                    recalcular_offset_individual(db, offset, cotizacion, verbose)
                    total_individuales += 1

        if verbose:
            print(f"\n{'='*60}")
            print("COMPLETADO")
            print("="*60)
            print(f"Grupos procesados: {total_grupos}")
            print(f"Offsets individuales procesados: {total_individuales}")

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
