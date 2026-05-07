"""
Limpieza de bloques HE en estado `error_fichadas` con `error_tipo` legacy.

Antes del cambio de lógica del validador (PR #630), el algoritmo era estricto
sobre el `tipo` (entrada/salida) de cada fichada. El sync de Hikvision alterna
los tipos por orden y a veces los marcaba mal, generando bloques con error_tipo:
  - fichadas_desbalanceadas
  - sin_fichada_entrada
  - sin_fichada_salida
  - solapamiento

Con la nueva lógica (primera fichada = entrada, última = salida, sin scope de
almuerzo) muchos de esos bloques son válidos y deberían tener HE calculado.

Este script encuentra bloques `error_fichadas` con error_tipo legacy y los
pasa a estado `detectada` (registra en historial append-only). El cron de
03:30 (o el endpoint POST /rrhh/horas-extras/recalcular) los recalcula con
la nueva lógica:

  - Si las fichadas son ≥2: genera bloque `detectada` con HE real (o se
    descarta si está bajo tolerancia).
  - Si solo hay 1 fichada: vuelve a `error_fichadas` con error_tipo nuevo
    `fichada_unica`.

NO toca:
  - Bloques con error_tipo='fichada_unica' (legítimos con la nueva lógica)
  - Bloques en otros estados (aprobada / liquidada / rechazada / detectada /
    pendiente_asignacion_turno)

USO:
  cd backend
  source venv/bin/activate
  python -m app.scripts.cleanup_he_legacy_errors             # dry-run por default
  python -m app.scripts.cleanup_he_legacy_errors --apply     # aplica los cambios
  python -m app.scripts.cleanup_he_legacy_errors --apply --recalcular
                                                              # aplica + dispara
                                                              # recálculo inmediato
"""

import os
import sys
from pathlib import Path

if __name__ == "__main__":
    backend_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if backend_path not in sys.path:
        sys.path.insert(0, backend_path)

    from dotenv import load_dotenv

    env_path = Path(backend_path) / ".env"
    load_dotenv(dotenv_path=env_path)


from datetime import datetime  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.models.rrhh_horas_extras import (  # noqa: E402
    EstadoHE,
    ErrorTipoHE,
    RRHHHorasExtras,
    RRHHHorasExtrasHistorial,
)
from app.services.rrhh_hikvision_client import ART_TZ  # noqa: E402
from app.services.rrhh_horas_extras_service import HorasExtrasService  # noqa: E402

# error_tipo "viejos" generados antes de la regla pragmática primera/última fichada.
LEGACY_ERROR_TIPOS = (
    ErrorTipoHE.FICHADAS_DESBALANCEADAS.value,
    ErrorTipoHE.SIN_FICHADA_ENTRADA.value,
    ErrorTipoHE.SIN_FICHADA_SALIDA.value,
    ErrorTipoHE.SOLAPAMIENTO.value,
)


def cleanup(apply: bool = False, recalcular: bool = False) -> dict:
    """Limpia bloques error_fichadas legacy.

    Args:
        apply: si False (default), solo imprime qué haría (dry-run).
        recalcular: si True y apply=True, dispara service.detectar_he_periodo
                    sobre el rango (min_fecha, max_fecha) de bloques afectados.

    Returns:
        dict con counts.
    """
    db = SessionLocal()
    try:
        bloques = (
            db.query(RRHHHorasExtras)
            .filter(
                RRHHHorasExtras.estado == EstadoHE.ERROR_FICHADAS.value,
                RRHHHorasExtras.error_tipo.in_(LEGACY_ERROR_TIPOS),
            )
            .order_by(RRHHHorasExtras.fecha.asc(), RRHHHorasExtras.empleado_id.asc())
            .all()
        )

        if not bloques:
            print("No hay bloques error_fichadas con error_tipo legacy. Nada que hacer.")
            return {"detectados": 0, "actualizados": 0, "recalculados": 0}

        # Resumen por error_tipo.
        por_tipo: dict[str, int] = {}
        for b in bloques:
            por_tipo[b.error_tipo] = por_tipo.get(b.error_tipo, 0) + 1

        print(f"Bloques con error_tipo legacy detectados: {len(bloques)}")
        for tipo, count in sorted(por_tipo.items()):
            print(f"  {tipo}: {count}")
        print()

        rango_fechas = (bloques[0].fecha, bloques[-1].fecha)
        empleados_ids = sorted({b.empleado_id for b in bloques})
        print(f"Rango de fechas afectado: {rango_fechas[0]} → {rango_fechas[1]}")
        print(f"Empleados afectados: {len(empleados_ids)}")
        print()

        if not apply:
            print("=== DRY-RUN. Usá --apply para ejecutar los cambios. ===")
            return {"detectados": len(bloques), "actualizados": 0, "recalculados": 0}

        # Apply: cambiar estado a detectada + log historial append-only.
        ahora = datetime.now(ART_TZ)
        for b in bloques:
            estado_anterior = b.estado
            error_tipo_anterior = b.error_tipo
            b.estado = EstadoHE.DETECTADA.value
            b.error_tipo = None
            historial = RRHHHorasExtrasHistorial(
                he_id=b.id,
                accion="cleanup_legacy_errors",
                estado_anterior=estado_anterior,
                estado_nuevo=EstadoHE.DETECTADA.value,
                usuario_id=None,
                motivo=(
                    f"Limpieza de error_tipo legacy ({error_tipo_anterior}) tras cambio "
                    "de validador (regla primera/última fichada)."
                ),
                snapshot={
                    "estado_anterior": estado_anterior,
                    "error_tipo_anterior": error_tipo_anterior,
                },
                created_at=ahora,
            )
            db.add(historial)

        db.commit()
        print(f"Estado actualizado: {len(bloques)} bloques pasaron a `detectada`.")
        print()

        recalculados = 0
        if recalcular:
            print("Disparando recálculo del rango...")
            service = HorasExtrasService(db)
            resultado = service.detectar_he_periodo(rango_fechas[0], rango_fechas[1])
            recalculados = resultado.get("creados", 0) + resultado.get("actualizados", 0)
            print(f"  Procesados: {resultado.get('procesados', 0)}")
            print(f"  Creados: {resultado.get('creados', 0)}")
            print(f"  Actualizados: {resultado.get('actualizados', 0)}")
            print(f"  Pendientes turno: {resultado.get('pendientes_turno', 0)}")
            print(f"  Errores: {resultado.get('errores', 0)}")
        else:
            print(
                "El cron de las 03:30 (o POST /rrhh/horas-extras/recalcular) los va\n"
                "a procesar con la nueva lógica. Para forzar ahora, usá --recalcular."
            )

        return {
            "detectados": len(bloques),
            "actualizados": len(bloques),
            "recalculados": recalculados,
        }

    finally:
        db.close()


if __name__ == "__main__":
    apply = "--apply" in sys.argv
    recalcular = "--recalcular" in sys.argv

    if not apply:
        print("=== DRY-RUN (no se modifica nada — usá --apply para ejecutar) ===\n")
    else:
        print("=== APLICANDO CAMBIOS ===\n")

    cleanup(apply=apply, recalcular=recalcular)
