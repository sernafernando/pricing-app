"""
numeracion_service — correlativos `P-<EE>-<YYYY>-<NNNNN>` y `OP-...`.

Genera el próximo número correlativo para pedidos de compra y órdenes de
pago, usando la tabla `numeracion_contadores` con una PK compuesta
`(tipo, empresa_id, anio)` y un **SELECT FOR UPDATE** pesimista para evitar
gaps por race-conditions (design §2.6 / D9 / REQ-NUM-*).

Política de correlatividad (D21):
  - Gaps legítimos (por rollback de la transacción del caller) son
    aceptables: se documentan en la guía de usuario y no se reintentan.
  - NO permitimos dos procesos entregando el mismo número: el lock pesimista
    se libera al COMMIT del caller.

Zona horaria del año (D18):
  - Argentina (UTC-3). Evita que un job corriendo pasado el 31-dic 21:00
    UTC use el año siguiente cuando en ARG todavía es 31-dic.

Responsabilidad del caller:
  - La lectura+incremento DEBE ocurrir dentro de la misma transacción que
    el INSERT de la entidad numerada (pedido u OP). Si la entidad
    rollbackea, el contador también (y el gap queda en el log de Postgres,
    no en la secuencia visible — aunque al reusar la fila con el
    `ultimo_numero` anterior, el siguiente caller reasigna el mismo N+1,
    sin gap a nivel negocio).

Monitoring (Cierre 1 del usuario):
  - Bajo volumen alto (>100 compras/día) considerar monitorear
    `pg_stat_activity` y `pg_locks` para detectar contención. En v2 evaluar
    migrar a `UPDATE ... RETURNING` sin SELECT FOR UPDATE explícito.

Referencias:
  - design.md §2.6
  - tasks.md COMPRAS-2.2
"""

from __future__ import annotations

from datetime import datetime
from typing import Final, Literal
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.numeracion_contador import NumeracionContador

logger = get_logger("services.numeracion_service")


TipoDocumento = Literal["pedido", "orden_pago"]


TZ_ARGENTINA: Final[ZoneInfo] = ZoneInfo("America/Argentina/Buenos_Aires")

PREFIX: Final[dict[str, str]] = {
    "pedido": "P",
    "orden_pago": "OP",
}

# Alias por compatibilidad con el prompt (`PREFIJOS`) y el design (`PREFIX`).
PREFIJOS: Final[dict[str, str]] = PREFIX

# Umbral a partir del cual el correlativo ya no cabe en 5 dígitos y se
# loguea WARNING (no se recorta — se deja que crezca).
_WARN_CORRELATIVO_5_DIGITOS: Final[int] = 100_000


def generar_siguiente_numero(
    session: Session,
    *,
    tipo: TipoDocumento,
    empresa_id: int,
    anio: int | None = None,
) -> tuple[str, int]:
    """
    Genera el próximo correlativo dentro de la transacción del caller.

    Flujo:
        1. Valida `tipo ∈ PREFIX`.
        2. Resuelve `anio` con TZ Argentina si es None (D18).
        3. `SELECT ... FOR UPDATE` sobre la fila `(tipo, empresa_id, anio)`.
        4. Si no existe → INSERT con `ultimo_numero=1`.
           Si existe → UPDATE set `ultimo_numero = ultimo_numero + 1`.
        5. Retorna `(numero_formato_string, nuevo_entero)`.

    Formato: ``{PREFIX}-{empresa_id:02d}-{anio:04d}-{nuevo:05d}``
    Ej.: ``P-01-2026-00001``, ``OP-02-2026-04210``.

    Args:
        session: sesión SQLAlchemy síncrona. El lock se libera en el
            `commit`/`rollback` del caller.
        tipo: tipo de documento — `'pedido'` o `'orden_pago'`.
        empresa_id: ID de la empresa local (tabla `empresas`).
        anio: año del correlativo. Default: año actual en TZ Argentina.

    Returns:
        Tupla `(numero_str, nuevo_int)`:
          - `numero_str`: string formateado listo para persistir.
          - `nuevo_int`: el entero correlativo asignado (útil para auditoría
            y para el caller si necesita el número sin prefijo).

    Raises:
        ValueError: si `tipo` no está en PREFIX.

    Notes:
        - El caller debe estar DENTRO de una transacción abierta. El
          servicio NO abre ni cierra transacciones.
        - Si `nuevo > 99_999`, se sigue formateando pero con más de 5
          dígitos (sin truncar) y se emite `logger.warning` — tocó techo
          de padding.
    """
    if tipo not in PREFIX:
        raise ValueError(f"Tipo de numeración no soportado en v1: '{tipo}'. Valores válidos: {sorted(PREFIX.keys())}")

    anio_resuelto: int = anio if anio is not None else _anio_argentina_hoy()

    stmt = (
        select(NumeracionContador)
        .where(
            NumeracionContador.tipo == tipo,
            NumeracionContador.empresa_id == empresa_id,
            NumeracionContador.anio == anio_resuelto,
        )
        .with_for_update()
    )
    fila: NumeracionContador | None = session.execute(stmt).scalar_one_or_none()

    if fila is None:
        fila = NumeracionContador(
            tipo=tipo,
            empresa_id=empresa_id,
            anio=anio_resuelto,
            ultimo_numero=1,
        )
        session.add(fila)
        nuevo = 1
    else:
        nuevo = int(fila.ultimo_numero) + 1
        fila.ultimo_numero = nuevo

    # Forzar flush para que el lock se sostenga sobre la fila real y para
    # que el INSERT se materialice antes de retornar.
    session.flush()

    if nuevo >= _WARN_CORRELATIVO_5_DIGITOS:
        logger.warning(
            "Correlativo %s/%d/%d superó los 5 dígitos (nuevo=%d). El padding visible crece — no se trunca.",
            tipo,
            empresa_id,
            anio_resuelto,
            nuevo,
        )

    numero_str = f"{PREFIX[tipo]}-{empresa_id:02d}-{anio_resuelto:04d}-{nuevo:05d}"
    return numero_str, nuevo


def _anio_argentina_hoy() -> int:
    """
    Devuelve el año actual en la zona horaria Argentina (UTC-3, D18).

    Separado en helper para que los tests puedan monkeypatchear
    `datetime.now` sin tener que duplicar la lógica del TZ.
    """
    return datetime.now(TZ_ARGENTINA).year


__all__ = [
    "PREFIJOS",
    "PREFIX",
    "TZ_ARGENTINA",
    "TipoDocumento",
    "generar_siguiente_numero",
]
