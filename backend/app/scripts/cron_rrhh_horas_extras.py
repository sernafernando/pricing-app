"""
Cron diario de detección de horas extras (HE).

Procesa D-1 (ayer) completo para todos los empleados activos y luego
ejecuta una purga de alertas leídas viejas según `dias_retencion_alertas`
del singleton de configuración.

Estrategia:
  - Lockfile flock no-bloqueante (`/var/run/pricing-app/rrhh_he_cron.lock`,
    fallback `/tmp/rrhh_he_cron.lock`) — si ya hay otra corrida activa,
    sale con exit 1 SIN encolar.
  - Chequea `RRHHHorasExtrasConfig.cron_activo`. Si está deshabilitado,
    sale con exit 3 sin tocar nada.
  - Detección con `HorasExtrasService.detectar_he_periodo(ayer, ayer)`
    + commit. Idempotente (recalcula bloques editables, conserva
    bloques congelados).
  - Purga final con `service.purgar_alertas_viejas()` (lee retención de
    config). Si la purga falla, NO rompe el exit code de la detección
    (la detección ya commiteó).
  - TZ explícita: usa `ART_TZ` de `rrhh_hikvision_client` para evitar
    drift si el servidor cambia de zona (riesgo §12 del design).

Cron entry (NO se autoinstala — agregar manualmente al crontab del
usuario `www-data` o equivalente. Independiente: NO se integra en
`sync_all_incremental.sh`):

  30 3 * * * cd /var/www/html/pricing-app/backend && \\
    /var/www/html/pricing-app/backend/venv/bin/python \\
    -m app.scripts.cron_rrhh_horas_extras \\
    >> /var/log/pricing-app/rrhh_he_cron.log 2>&1

Justificación del horario 03:30 AM:
  - Después de `sync_hikvision_fichadas` (cada 2h, ciclos 02:00 y 04:00)
    — corre entre ciclos para no chocar contra el sync de fichadas.
  - Después de `reconciliar_cc_proveedor` (03:00 AM) — separa cargas.
  - Antes del inicio de jornada (~06:00) — los managers ven HE de ayer
    al entrar.

Exit codes:
  0 — OK (detección + purga completadas, o detección OK con purga fallida)
  1 — Lock activo (otra corrida en curso)
  2 — Error fatal en detección (rollback aplicado)
  3 — Cron deshabilitado por config (cron_activo=false)

Uso manual:
    cd /var/www/html/pricing-app/backend
    python -m app.scripts.cron_rrhh_horas_extras

Referencias:
  - design.md §8 (estructura del cron)
  - tasks.md Batch 5 (T-5.1..T-5.5)
  - openspec/changes/rrhh-horas-extras/specs/cron-diario.md
"""

from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from datetime import timedelta
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

from app.core.database import SessionLocal  # noqa: E402
from app.core.logging import get_logger  # noqa: E402
from app.models.rrhh_horas_extras import RRHHHorasExtrasConfig  # noqa: E402
from app.services.rrhh_hikvision_client import ART_TZ  # noqa: E402
from app.services.rrhh_horas_extras_service import HorasExtrasService  # noqa: E402

logger = get_logger("scripts.cron_rrhh_horas_extras")


LOCK_PATH_PRIMARY = Path(os.environ.get("RRHH_HE_CRON_LOCK_PRIMARY", "/var/run/pricing-app/rrhh_he_cron.lock"))
LOCK_PATH_FALLBACK = Path(os.environ.get("RRHH_HE_CRON_LOCK_FALLBACK", "/tmp/rrhh_he_cron.lock"))


@contextmanager
def _file_lock() -> Iterator[Path]:
    """Lockfile flock no-bloqueante.

    Intenta `LOCK_PATH_PRIMARY`; si su parent no existe ni se puede crear,
    cae a `LOCK_PATH_FALLBACK`. Si otro proceso ya tiene el lock, levanta
    `SystemExit(1)` SIN encolar.

    Yields:
        Path al lockfile efectivamente adquirido (para logging).
    """
    import fcntl

    # Elegir path: primario si su parent existe (o se puede crear), fallback si no.
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
        logger.warning("⚠️ Otra corrida del cron HE está activa (lockfile=%s). Aborta.", path)
        raise SystemExit(1)

    # Escribir PID para diagnóstico operacional.
    try:
        os.ftruncate(fd, 0)
        os.write(fd, f"{os.getpid()}\n".encode("utf-8"))
    except OSError:
        # Falla al escribir PID no es crítica — seguimos con el lock adquirido.
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


def _run_detection(db, ayer) -> dict[str, int]:
    """Step D-1: detección de HE para `ayer` completo.

    Args:
        db: sesión SQLAlchemy abierta.
        ayer: fecha a procesar (date).

    Returns:
        Dict con counts retornado por `detectar_he_periodo`
        (procesados, creados, actualizados, alertas, errores, pendientes_turno).
    """
    logger.info("🔄 Iniciando detección HE para fecha=%s", ayer)
    service = HorasExtrasService(db)
    result = service.detectar_he_periodo(ayer, ayer)
    db.commit()
    logger.info(
        "✅ Detección HE completada fecha=%s procesados=%s creados=%s "
        "actualizados=%s alertas=%s errores=%s pendientes_turno=%s",
        ayer,
        result.get("procesados", 0),
        result.get("creados", 0),
        result.get("actualizados", 0),
        result.get("alertas", 0),
        result.get("errores", 0),
        result.get("pendientes_turno", 0),
    )
    return result


def _run_purga(db) -> dict[str, int]:
    """Step final: purga de alertas leídas viejas (revisión 2 — Q4).

    Lee `dias_retencion_alertas` del singleton de config (default 15).
    Hard-delete de alertas con `leida_at IS NOT NULL` y
    `created_at < (today - dias)`. Las alertas no leídas NUNCA se purgan.

    Args:
        db: sesión SQLAlchemy abierta (ya commiteada por la detección).

    Returns:
        Dict {purgadas, retenidas}.
    """
    logger.info("🔄 Iniciando purga de alertas viejas")
    service = HorasExtrasService(db)
    resultado = service.purgar_alertas_viejas()
    logger.info(
        "🗑️ Purga alertas: %s eliminadas, %s retenidas",
        resultado.get("purgadas", 0),
        resultado.get("retenidas", 0),
    )
    return resultado


def main() -> int:
    """Entry point del cron.

    Returns:
        Exit code (0=OK, 1=lock, 2=error fatal, 3=cron deshabilitado).
    """
    # TZ explícita: zona Argentina (ART, UTC-3) — coherente con Hikvision.
    ayer = datetime.now(ART_TZ).date() - timedelta(days=1)

    try:
        with _file_lock() as lock_path:
            logger.info("🔒 Lock adquirido en %s (pid=%s)", lock_path, os.getpid())
            db = SessionLocal()
            try:
                cfg = db.query(RRHHHorasExtrasConfig).filter(RRHHHorasExtrasConfig.id == 1).one_or_none()
                if cfg is None or not cfg.cron_activo:
                    logger.warning("⚠️ Cron HE deshabilitado por config (cron_activo=false). Aborta.")
                    return 3

                # Step 1: detección D-1 (commit interno).
                try:
                    _run_detection(db, ayer)
                except Exception:
                    db.rollback()
                    logger.exception("❌ Error fatal en detección HE fecha=%s", ayer)
                    return 2

                # Step 2: purga (revisión 2 Q4). NO rompe exit code si falla:
                # la detección ya commiteó y eso es lo que importa.
                try:
                    _run_purga(db)
                except Exception:
                    db.rollback()
                    logger.exception("❌ Error en purga de alertas (no bloquea exit)")

                return 0
            finally:
                db.close()
    except SystemExit as exc:
        # `_file_lock` levanta SystemExit(1) si el lock está activo.
        code = exc.code if isinstance(exc.code, int) else 1
        return code


if __name__ == "__main__":
    sys.exit(main())
