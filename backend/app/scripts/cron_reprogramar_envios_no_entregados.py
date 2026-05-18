"""
Cron nocturno: reprograma envíos en estado `not_delivered` al próximo día hábil.

Busca todas las etiquetas con:
  - mlstatus == 'not_delivered' (envíos ML, vía último registro en
    tb_mercadolibre_orders_shipping) **o** manual_status == 'not_delivered'
    (envíos manuales),
  - fecha_envio <= hoy,
  - flag_envio IS NULL (no flaggeados como mal pasado/cancelado/duplicado),
  - retornado IS NOT TRUE (no devueltos físicamente),
  - pistoleado_at IS NULL (no despachados por el operador).

Para cada match, actualiza `fecha_envio` al próximo día hábil calculado desde
HOY (no desde la fecha original, porque la idea es "que entre al flujo de mañana").

NO modifica mlstatus/manual_status: ML va a actualizar el estado en el próximo
update (decisión de producto). Tampoco toca logística ni transporte.

Estrategia:
  - Lockfile flock no-bloqueante (`/var/run/pricing-app/reprogramar_envios.lock`,
    fallback `/tmp/reprogramar_envios.lock`) — si ya hay otra corrida activa,
    sale con exit 1 SIN encolar.
  - Una sola query con dedup del último mlstatus por shipping_id
    (ROW_NUMBER OVER PARTITION BY mlshippingid ORDER BY mlm_id DESC).
  - Calcula el próximo día hábil UNA vez (es el mismo para todos los envíos del batch).
  - Bulk update + commit único. Si algo falla, rollback completo.
  - Loguea cada cambio individualmente para trazabilidad (shipping_id, fecha
    anterior → nueva).

Cron entry (NO se autoinstala — agregar manualmente al crontab del
usuario `www-data` o equivalente):

  45 23 * * * cd /var/www/html/pricing-app/backend && \\
    /var/www/html/pricing-app/backend/venv/bin/python \\
    -m app.scripts.cron_reprogramar_envios_no_entregados \\
    >> /var/log/pricing-app/reprogramar_envios.log 2>&1

Justificación del horario 23:45:
  - Cierre del día operativo: ya no se pistolean más envíos.
  - Antes de medianoche para que la nueva `fecha_envio` quede en la tabla
    del día siguiente cuando los managers abran la app a la mañana.

Exit codes:
  0 — OK (con o sin envíos reprogramados)
  1 — Lock activo (otra corrida en curso)
  2 — Error fatal en la query/update (rollback aplicado)

Uso manual:
    cd /var/www/html/pricing-app/backend
    python -m app.scripts.cron_reprogramar_envios_no_entregados
"""

from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

if __name__ == "__main__":
    backend_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if backend_path not in sys.path:
        sys.path.insert(0, backend_path)

    from dotenv import load_dotenv

    env_path = Path(backend_path) / ".env"
    load_dotenv(dotenv_path=env_path)


from datetime import datetime  # noqa: E402
from zoneinfo import ZoneInfo  # noqa: E402

from sqlalchemy import and_, desc, func, or_  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.core.logging import get_logger  # noqa: E402
from app.models.etiqueta_envio import EtiquetaEnvio  # noqa: E402
from app.models.mercadolibre_order_shipping import MercadoLibreOrderShipping  # noqa: E402
from app.utils.business_day import next_business_day  # noqa: E402

logger = get_logger("scripts.cron_reprogramar_envios_no_entregados")


ART_TZ = ZoneInfo("America/Argentina/Buenos_Aires")

LOCK_PATH_PRIMARY = Path(
    os.environ.get("REPROGRAMAR_ENVIOS_LOCK_PRIMARY", "/var/run/pricing-app/reprogramar_envios.lock")
)
LOCK_PATH_FALLBACK = Path(os.environ.get("REPROGRAMAR_ENVIOS_LOCK_FALLBACK", "/tmp/reprogramar_envios.lock"))


@contextmanager
def _file_lock() -> Iterator[Path]:
    """Lockfile flock no-bloqueante.

    Intenta `LOCK_PATH_PRIMARY`; si su parent no existe ni se puede crear,
    cae a `LOCK_PATH_FALLBACK`. Si otro proceso ya tiene el lock, levanta
    `SystemExit(1)` SIN encolar.
    """
    import fcntl

    path = LOCK_PATH_PRIMARY
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except (OSError, PermissionError):
        path = LOCK_PATH_FALLBACK
        path.parent.mkdir(parents=True, exist_ok=True)

    fd = os.open(str(path), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        logger.warning("⚠️ Otra corrida del cron reprogramar envíos está activa (lockfile=%s). Aborta.", path)
        raise SystemExit(1)

    try:
        os.ftruncate(fd, 0)
        os.write(fd, f"{os.getpid()}\n".encode("utf-8"))
    except OSError:
        pass

    try:
        yield path
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
        try:
            os.close(fd)
        except OSError:
            pass


def _reprogramar(db) -> dict[str, int]:
    """Reprograma envíos no entregados al próximo día hábil.

    Returns:
        Dict con counts: {procesados, reprogramados, nueva_fecha}.
    """
    hoy = datetime.now(ART_TZ).date()
    nueva_fecha = next_business_day(hoy, db)
    logger.info("🗓️ Hoy=%s — próximo día hábil=%s", hoy, nueva_fecha)

    # Último mlstatus por mlshippingid (dedup con ROW_NUMBER).
    ml_ranked = (
        db.query(
            MercadoLibreOrderShipping.mlshippingid.label("mlshippingid"),
            MercadoLibreOrderShipping.mlstatus.label("mlstatus"),
            func.row_number()
            .over(
                partition_by=MercadoLibreOrderShipping.mlshippingid,
                order_by=desc(MercadoLibreOrderShipping.mlm_id),
            )
            .label("rn"),
        )
        .filter(MercadoLibreOrderShipping.mlshippingid.isnot(None))
        .subquery()
    )
    ml_dedup = db.query(ml_ranked.c.mlshippingid, ml_ranked.c.mlstatus).filter(ml_ranked.c.rn == 1).subquery()

    envios = (
        db.query(EtiquetaEnvio)
        .outerjoin(ml_dedup, ml_dedup.c.mlshippingid == EtiquetaEnvio.shipping_id)
        .filter(
            EtiquetaEnvio.fecha_envio <= hoy,
            EtiquetaEnvio.flag_envio.is_(None),
            EtiquetaEnvio.retornado.isnot(True),
            EtiquetaEnvio.pistoleado_at.is_(None),
            or_(
                ml_dedup.c.mlstatus == "not_delivered",
                and_(
                    EtiquetaEnvio.es_manual.is_(True),
                    EtiquetaEnvio.manual_status == "not_delivered",
                ),
            ),
        )
        .all()
    )

    logger.info("🔍 Encontrados %s envíos en estado not_delivered para reprogramar", len(envios))

    reprogramados = 0
    for envio in envios:
        fecha_anterior = envio.fecha_envio
        if fecha_anterior == nueva_fecha:
            # Caso borde: el próximo día hábil cae el mismo día (no debería
            # pasar porque filtramos fecha_envio <= hoy, pero defensive).
            continue
        envio.fecha_envio = nueva_fecha
        reprogramados += 1
        logger.info(
            "↪️ shipping_id=%s fecha %s → %s (es_manual=%s)",
            envio.shipping_id,
            fecha_anterior,
            nueva_fecha,
            envio.es_manual,
        )

    db.commit()
    logger.info(
        "✅ Reprogramación completa: procesados=%s reprogramados=%s nueva_fecha=%s",
        len(envios),
        reprogramados,
        nueva_fecha,
    )
    return {
        "procesados": len(envios),
        "reprogramados": reprogramados,
    }


def main() -> int:
    """Entry point del cron.

    Returns:
        Exit code (0=OK, 1=lock, 2=error fatal).
    """
    try:
        with _file_lock() as lock_path:
            logger.info("🔒 Lock adquirido en %s (pid=%s)", lock_path, os.getpid())
            db = SessionLocal()
            try:
                try:
                    _reprogramar(db)
                except Exception:
                    db.rollback()
                    logger.exception("❌ Error fatal en reprogramación de envíos")
                    return 2
                return 0
            finally:
                db.close()
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 1
        return code


if __name__ == "__main__":
    sys.exit(main())
