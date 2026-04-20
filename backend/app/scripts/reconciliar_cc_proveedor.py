"""
Cron standalone de reconciliación CC proveedor (design §8, D5).

Compara el libro mayor propio (`cc_proveedor_movimientos`) contra el
snapshot sincronizado del ERP (`cuentas_corrientes_proveedores`) para
cada (proveedor, moneda) con movimientos en los últimos 365 días. Si
la diferencia supera la `tolerancia_aplicada` por moneda (leída de la
tabla `configuracion`), persiste una fila `divergencia` en
`cc_reconciliacion_log` + crea 1 alerta banner + N notificaciones.

Se ejecuta DIARIAMENTE a las 03:00 AM desde el orquestador de cron
(NO es hook post-sync — decisión D5, aislamiento de fallos entre sync
y reconciliación).

Uso manual:
    python -m app.scripts.reconciliar_cc_proveedor
    python -m app.scripts.reconciliar_cc_proveedor --fecha 2026-04-20

Idempotencia: la UNIQUE constraint `(fecha_corrida, proveedor_id, moneda)`
en `cc_reconciliacion_log` garantiza que re-correr con la misma fecha
NO duplica logs (la segunda corrida explota en el flush y se rollbackea).

Referencias:
  - design.md §8
  - tasks.md COMPRAS-3.6
  - Cierre 2 del usuario: tolerancia por moneda (ARS/USD separadas).
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

backend_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(backend_dir))

from app.core.database import SessionLocal  # noqa: E402
from app.core.logging import get_logger  # noqa: E402
from app.schemas.configuracion_compras import leer_configuracion  # noqa: E402
from app.services.cc_proveedor_service import reconciliar_diario  # noqa: E402

logger = get_logger("scripts.reconciliar_cc_proveedor")


# Defaults si la tabla `configuracion` no tiene la clave seeded.
# Coinciden con los defaults del seed `compras_012_seed_configuracion_compras`.
_DEFAULT_TOLERANCIA_ARS = Decimal("100.00")
_DEFAULT_TOLERANCIA_USD = Decimal("1.00")

# Claves en `configuracion` (seed compras_012).
_CLAVE_TOLERANCIA_ARS = "compras.cc_reconciliacion_tolerancia_ars"
_CLAVE_TOLERANCIA_USD = "compras.cc_reconciliacion_tolerancia_usd"


def correr(fecha: date, *, ventana_dias: int = 365) -> dict:
    """Entry point testeable del cron.

    Args:
        fecha: fecha de la corrida (UNIQUE constraint en log).
        ventana_dias: filtro de proveedores activos.

    Returns:
        Resumen retornado por `reconciliar_diario`.
    """
    session = SessionLocal()
    try:
        tolerancias = {
            "ARS": leer_configuracion(session, _CLAVE_TOLERANCIA_ARS, _DEFAULT_TOLERANCIA_ARS),
            "USD": leer_configuracion(session, _CLAVE_TOLERANCIA_USD, _DEFAULT_TOLERANCIA_USD),
        }
        logger.info(
            "Corriendo reconciliación CC fecha=%s tolerancias=%s ventana_dias=%s",
            fecha,
            tolerancias,
            ventana_dias,
        )

        resumen = reconciliar_diario(
            session,
            fecha_corrida=fecha,
            tolerancias=tolerancias,
            ventana_dias=ventana_dias,
        )
        session.commit()

        logger.info("Reconciliación %s completada: %s", fecha, resumen)
        return resumen
    except Exception:
        session.rollback()
        logger.exception("Reconciliación %s falló — rollback aplicado", fecha)
        raise
    finally:
        session.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Cron standalone: reconciliación CC libro mayor vs snapshot ERP.")
    parser.add_argument(
        "--fecha",
        type=str,
        default=None,
        help="Fecha de corrida en formato YYYY-MM-DD (default: hoy).",
    )
    parser.add_argument(
        "--ventana-dias",
        type=int,
        default=365,
        help="Días hacia atrás para filtrar proveedores activos (default: 365).",
    )
    args = parser.parse_args()

    fecha_corrida = date.fromisoformat(args.fecha) if args.fecha else date.today()
    resumen = correr(fecha_corrida, ventana_dias=args.ventana_dias)
    print(f"Reconciliación {fecha_corrida}: {resumen}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
