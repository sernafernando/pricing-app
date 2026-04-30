"""
T-8.1 — Test manual: clasificación tipo_dia + sábado split.

Verifica `HorasExtrasService._clasificar_tipo_dia` para todos los casos:
- Lunes (laboral) → 1 tramo `habil_50` cubriendo el día completo.
- Sábado → 2 tramos: `habil_50` 00:00-13:00 + `sabado_100` 13:00-24:00.
- Domingo → 1 tramo `domingo_100`.
- Feriado (registrado en `rrhh_horarios_excepciones` con `es_laborable=False`) →
  1 tramo `feriado_100` cubriendo todo el día.

Cada test hace su propia limpieza en `finally` (la única fila que insertamos
es la excepción de feriado de prueba).

Uso:
    cd /var/www/html/pricing-app/backend
    python -m app.scripts.test_manual_rrhh_he_clasificacion

Salida: PASS/FAIL por aserción. Exit 0 si todo PASS, 1 si algún FAIL.

Spec ref: "Clasificación de tipo de día con corte de sábado configurable".
"""

from __future__ import annotations

import os
import sys
from datetime import date, time, timedelta
from pathlib import Path

if __name__ == "__main__":
    backend_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if backend_path not in sys.path:
        sys.path.insert(0, backend_path)

    from dotenv import load_dotenv

    env_path = Path(backend_path) / ".env"
    load_dotenv(dotenv_path=env_path)

from app.core.database import SessionLocal
from app.models.rrhh_horario import RRHHHorarioExcepcion
from app.models.rrhh_horas_extras import TipoDiaHE
from app.services.rrhh_horas_extras_service import HorasExtrasService


HORA_CORTE_SABADO = time(13, 0)


def _proximo_dia_semana(dia_semana: int, base: date | None = None) -> date:
    """Devuelve la próxima fecha (>= base) cuyo weekday() == dia_semana."""
    base = base or date.today()
    delta = (dia_semana - base.weekday()) % 7
    return base + timedelta(days=delta)


def _ok(msg: str) -> None:
    print(f"  PASS - {msg}")


def _fail(msg: str) -> None:
    print(f"  FAIL - {msg}")


def main() -> int:
    print("Iniciando test_manual_rrhh_he_clasificacion (T-8.1)")
    db = SessionLocal()
    fallos = 0
    feriado_inserted: RRHHHorarioExcepcion | None = None
    feriado_fecha: date | None = None

    try:
        service = HorasExtrasService(db)

        # ─── Caso 1: Lunes ────────────────────────────────────────────
        lunes = _proximo_dia_semana(0)
        tramos = service._clasificar_tipo_dia(lunes, HORA_CORTE_SABADO)
        if len(tramos) == 1 and tramos[0][0] == TipoDiaHE.HABIL_50:
            _ok(f"Lunes {lunes} -> 1 tramo habil_50 (got {tramos[0][0].value})")
        else:
            fallos += 1
            _fail(f"Lunes {lunes} esperaba [habil_50] (1 tramo); got {tramos}")

        # ─── Caso 2: Sábado split ────────────────────────────────────
        sabado = _proximo_dia_semana(5)
        tramos = service._clasificar_tipo_dia(sabado, HORA_CORTE_SABADO)
        if (
            len(tramos) == 2
            and tramos[0][0] == TipoDiaHE.HABIL_50
            and tramos[1][0] == TipoDiaHE.SABADO_100
            and tramos[0][2] == HORA_CORTE_SABADO
            and tramos[1][1] == HORA_CORTE_SABADO
        ):
            _ok(f"Sabado {sabado} split -> habil_50 [00:00-13:00] + sabado_100 [13:00-24:00]")
        else:
            fallos += 1
            _fail(f"Sabado {sabado} split incorrecto; got {tramos}")

        # ─── Caso 3: Domingo ──────────────────────────────────────────
        domingo = _proximo_dia_semana(6)
        tramos = service._clasificar_tipo_dia(domingo, HORA_CORTE_SABADO)
        if len(tramos) == 1 and tramos[0][0] == TipoDiaHE.DOMINGO_100:
            _ok(f"Domingo {domingo} -> 1 tramo domingo_100")
        else:
            fallos += 1
            _fail(f"Domingo {domingo} esperaba [domingo_100]; got {tramos}")

        # ─── Caso 4: Feriado (insertar excepción temporal) ─────────────
        # Buscamos un martes futuro (laboral) que no tenga excepción ya.
        feriado_fecha = _proximo_dia_semana(1, base=date.today() + timedelta(days=14))
        existe = db.query(RRHHHorarioExcepcion).filter(RRHHHorarioExcepcion.fecha == feriado_fecha).first()
        if existe is not None:
            print(f"  WARN - {feriado_fecha} ya tiene excepción registrada; uso fecha alternativa para no pisar")
            feriado_fecha = feriado_fecha + timedelta(days=7)

        feriado_inserted = RRHHHorarioExcepcion(
            fecha=feriado_fecha,
            tipo="feriado",
            descripcion="TEST_HE_T81 — feriado de prueba (cleanup automático)",
            es_laborable=False,
        )
        db.add(feriado_inserted)
        db.commit()

        tramos = service._clasificar_tipo_dia(feriado_fecha, HORA_CORTE_SABADO)
        if len(tramos) == 1 and tramos[0][0] == TipoDiaHE.FERIADO_100:
            _ok(f"Feriado {feriado_fecha} -> 1 tramo feriado_100")
        else:
            fallos += 1
            _fail(f"Feriado {feriado_fecha} esperaba [feriado_100]; got {tramos}")

        # ─── Caso 5: Feriado laborable (es_laborable=True) ─────────────
        # Si el día base es martes y la excepción es es_laborable=True, debería
        # clasificarse como habil_50 (no feriado_100). Reusamos otra fecha.
        laborable_fecha = feriado_fecha + timedelta(days=7)
        existe2 = db.query(RRHHHorarioExcepcion).filter(RRHHHorarioExcepcion.fecha == laborable_fecha).first()
        if existe2 is None and laborable_fecha.weekday() < 5:
            laborable_inserted = RRHHHorarioExcepcion(
                fecha=laborable_fecha,
                tipo="dia_especial",
                descripcion="TEST_HE_T81 — día especial laborable (cleanup auto)",
                es_laborable=True,
            )
            db.add(laborable_inserted)
            db.commit()
            try:
                tramos = service._clasificar_tipo_dia(laborable_fecha, HORA_CORTE_SABADO)
                if len(tramos) == 1 and tramos[0][0] == TipoDiaHE.HABIL_50:
                    _ok(f"Día especial laborable {laborable_fecha} -> habil_50 (NO feriado_100)")
                else:
                    fallos += 1
                    _fail(f"Día especial laborable {laborable_fecha} esperaba habil_50; got {tramos}")
            finally:
                db.delete(laborable_inserted)
                db.commit()
        else:
            print(f"  SKIP - laborable_fecha {laborable_fecha} no es martes o ya existe excepción")

    except Exception as exc:
        fallos += 1
        _fail(f"Excepción inesperada: {exc!r}")
        import traceback

        traceback.print_exc()
    finally:
        # Cleanup: borrar la excepción de feriado de prueba si fue insertada.
        try:
            if feriado_inserted is not None and feriado_fecha is not None:
                row = db.query(RRHHHorarioExcepcion).filter(RRHHHorarioExcepcion.fecha == feriado_fecha).first()
                if row is not None and "TEST_HE_T81" in (row.descripcion or ""):
                    db.delete(row)
                    db.commit()
                    print(f"  Cleanup: excepción de prueba {feriado_fecha} eliminada")
        except Exception as cleanup_exc:
            print(f"  WARN - Cleanup falló: {cleanup_exc!r}")
        finally:
            db.close()

    if fallos == 0:
        print("\nResultado: PASS (T-8.1)")
        return 0
    print(f"\nResultado: FAIL ({fallos} aserciones fallidas)")
    return 1


if __name__ == "__main__":
    sys.exit(main())
