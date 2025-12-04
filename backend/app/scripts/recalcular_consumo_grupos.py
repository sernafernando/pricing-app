"""
Script para recalcular el consumo de todos los grupos de offsets con límites.
Lee las ventas ML y fuera de ML y regenera la tabla offset_grupo_consumo y offset_grupo_resumen.

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
from app.models.offset_grupo_consumo import OffsetGrupoConsumo, OffsetGrupoResumen
from app.models.cur_exch_history import CurExchHistory


def obtener_cotizacion_actual(db):
    """Obtiene la cotización USD/ARS más reciente"""
    tc = db.query(CurExchHistory).order_by(CurExchHistory.ceh_cd.desc()).first()
    return float(tc.ceh_exchange) if tc else 1000.0


def recalcular_grupo(db, grupo_id: int, cotizacion: float, verbose: bool = True):
    """
    Recalcula el consumo de un grupo específico.
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

    if not offsets_grupo:
        if verbose:
            print(f"  - No hay offsets en este grupo")
        return {"grupo_id": grupo_id, "consumos_creados": 0, "mensaje": "Sin offsets"}

    # Determinar fecha de inicio (la más antigua de los offsets)
    fecha_inicio = min(o.fecha_desde for o in offsets_grupo)
    if verbose:
        print(f"  - Fecha inicio offset: {fecha_inicio}")

    # Obtener item_ids del grupo
    item_ids = [o.item_id for o in offsets_grupo if o.item_id]
    if verbose:
        print(f"  - Items en el grupo: {len(item_ids)}")

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
                m.cotizacion_dolar
            FROM ml_ventas_metricas m
            WHERE m.item_id = ANY(:item_ids)
            AND m.fecha_venta >= :fecha_inicio
            ORDER BY m.fecha_venta
        """)

        ventas_ml = db.execute(ventas_ml_query, {
            "item_ids": item_ids,
            "fecha_inicio": fecha_inicio
        }).fetchall()

        if verbose:
            print(f"  - Ventas ML encontradas: {len(ventas_ml)}")

        for venta in ventas_ml:
            # Encontrar el offset aplicable
            offset_aplicable = next(
                (o for o in offsets_grupo if o.item_id == venta.item_id),
                None
            )

            if not offset_aplicable:
                continue

            # Calcular monto del offset
            cot = float(venta.cotizacion_dolar) if venta.cotizacion_dolar else cotizacion
            costo = float(venta.costo_total_sin_iva) if venta.costo_total_sin_iva else 0

            if offset_aplicable.tipo_offset == 'monto_fijo':
                monto_offset = float(offset_aplicable.monto or 0)
                if offset_aplicable.moneda == 'USD':
                    monto_offset_ars = monto_offset * cot
                    monto_offset_usd = monto_offset
                else:
                    monto_offset_ars = monto_offset
                    monto_offset_usd = monto_offset / cot if cot > 0 else 0
            elif offset_aplicable.tipo_offset == 'monto_por_unidad':
                monto_por_u = float(offset_aplicable.monto or 0)
                if offset_aplicable.moneda == 'USD':
                    monto_offset_ars = monto_por_u * venta.cantidad * cot
                    monto_offset_usd = monto_por_u * venta.cantidad
                else:
                    monto_offset_ars = monto_por_u * venta.cantidad
                    monto_offset_usd = monto_por_u * venta.cantidad / cot if cot > 0 else 0
            elif offset_aplicable.tipo_offset == 'porcentaje_costo':
                porcentaje = float(offset_aplicable.porcentaje or 0)
                monto_offset_ars = costo * (porcentaje / 100)
                monto_offset_usd = monto_offset_ars / cot if cot > 0 else 0
            else:
                continue

            # Crear registro de consumo
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

        # Obtener ventas fuera de ML
        ventas_fuera_query = text("""
            SELECT
                v.id,
                v.fecha_venta,
                v.item_id,
                v.cantidad,
                v.costo_total_sin_iva,
                v.cotizacion_dolar
            FROM ventas_fuera_ml v
            WHERE v.item_id = ANY(:item_ids)
            AND v.fecha_venta >= :fecha_inicio
            ORDER BY v.fecha_venta
        """)

        try:
            ventas_fuera = db.execute(ventas_fuera_query, {
                "item_ids": item_ids,
                "fecha_inicio": fecha_inicio
            }).fetchall()

            if verbose:
                print(f"  - Ventas fuera ML encontradas: {len(ventas_fuera)}")

            for venta in ventas_fuera:
                offset_aplicable = next(
                    (o for o in offsets_grupo if o.item_id == venta.item_id),
                    None
                )

                if not offset_aplicable:
                    continue

                cot = float(venta.cotizacion_dolar) if venta.cotizacion_dolar else cotizacion
                costo = float(venta.costo_total_sin_iva) if venta.costo_total_sin_iva else 0

                if offset_aplicable.tipo_offset == 'monto_fijo':
                    monto_offset = float(offset_aplicable.monto or 0)
                    if offset_aplicable.moneda == 'USD':
                        monto_offset_ars = monto_offset * cot
                        monto_offset_usd = monto_offset
                    else:
                        monto_offset_ars = monto_offset
                        monto_offset_usd = monto_offset / cot if cot > 0 else 0
                elif offset_aplicable.tipo_offset == 'monto_por_unidad':
                    monto_por_u = float(offset_aplicable.monto or 0)
                    if offset_aplicable.moneda == 'USD':
                        monto_offset_ars = monto_por_u * venta.cantidad * cot
                        monto_offset_usd = monto_por_u * venta.cantidad
                    else:
                        monto_offset_ars = monto_por_u * venta.cantidad
                        monto_offset_usd = monto_por_u * venta.cantidad / cot if cot > 0 else 0
                elif offset_aplicable.tipo_offset == 'porcentaje_costo':
                    porcentaje = float(offset_aplicable.porcentaje or 0)
                    monto_offset_ars = costo * (porcentaje / 100)
                    monto_offset_usd = monto_offset_ars / cot if cot > 0 else 0
                else:
                    continue

                consumo = OffsetGrupoConsumo(
                    grupo_id=grupo_id,
                    venta_fuera_id=venta.id,
                    tipo_venta='fuera_ml',
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
                print(f"  - Advertencia: No se pudo consultar ventas_fuera_ml: {e}")

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
            # Recalcular todos los grupos con límites
            grupos_con_limites = db.query(OffsetGrupo).join(
                OffsetGanancia, OffsetGrupo.id == OffsetGanancia.grupo_id
            ).filter(
                or_(
                    OffsetGanancia.max_unidades.isnot(None),
                    OffsetGanancia.max_monto_usd.isnot(None)
                )
            ).distinct().all()

            if verbose:
                print(f"\nGrupos con límites encontrados: {len(grupos_con_limites)}")

            for grupo in grupos_con_limites:
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
