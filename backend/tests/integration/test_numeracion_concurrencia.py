"""
Test de concurrencia REAL del servicio de numeración contra Postgres.

COMPRAS-7.4 — Fase 7.

Los tests unitarios de `numeracion_service` corren contra SQLite con un
`threading.Lock()` emulado. Ese setup cubre la API pero NO reproduce la
semántica de `SELECT ... FOR UPDATE` que es el core del lock en producción.

Este test lanza N workers en paralelo invocando `generar_siguiente_numero`
sobre el mismo `(tipo, empresa_id, anio)` y valida que NO hay colisiones:
todos los números son distintos y consecutivos.

**Política de ejecución**:

Se saltea por default (la CI y la mayoría de los devs corren sin Postgres
local). Para habilitarlo:

    export TESTING_POSTGRES_URL="postgresql://user:pass@localhost:5432/pricing_test"
    # Y correr alembic upgrade head contra esa DB ANTES.

La URL debe apuntar a una DB **vacía/descartable** — el test crea y usa
la tabla `compras_numeracion` que Alembic ya debió haber creado.

Referencias:
  - design.md §6.2 (numeracion_service — SELECT FOR UPDATE)
  - tasks.md COMPRAS-7.4
  - backend/app/services/numeracion_service.py
"""

from __future__ import annotations

import os
import threading
from typing import Generator

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

POSTGRES_URL = os.environ.get("TESTING_POSTGRES_URL")

pytestmark = pytest.mark.skipif(
    POSTGRES_URL is None,
    reason=(
        "TESTING_POSTGRES_URL no configurada — test de concurrencia requiere "
        "Postgres real (SELECT FOR UPDATE no es fiable en SQLite). "
        "Exportar TESTING_POSTGRES_URL=postgresql://... para habilitarlo."
    ),
)


@pytest.fixture(scope="module")
def pg_engine() -> Generator[Engine, None, None]:
    engine = create_engine(POSTGRES_URL, pool_size=20, max_overflow=0)
    # Smoke: asegurarnos que la tabla existe (alembic upgrade head debió correr).
    with engine.connect() as conn:
        exists = conn.execute(
            text(
                """
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_name = 'compras_numeracion'
                )
                """
            )
        ).scalar()
        if not exists:
            pytest.skip(
                "Tabla `compras_numeracion` no existe en la DB apuntada. Correr `alembic upgrade head` primero."
            )
    yield engine
    engine.dispose()


@pytest.fixture
def clean_numeracion_row(pg_engine: Engine) -> Generator[None, None, None]:
    """Borra la fila del test ANTES (para arrancar en 0) y DESPUÉS (cleanup)."""
    with pg_engine.begin() as conn:
        conn.execute(
            text(
                """
                DELETE FROM compras_numeracion
                WHERE tipo = 'pedido' AND empresa_id = 1 AND anio = 2999
                """
            )
        )
    yield
    with pg_engine.begin() as conn:
        conn.execute(
            text(
                """
                DELETE FROM compras_numeracion
                WHERE tipo = 'pedido' AND empresa_id = 1 AND anio = 2999
                """
            )
        )


def test_generar_siguiente_numero_concurrencia_10_workers(pg_engine: Engine, clean_numeracion_row) -> None:
    """
    10 workers concurrentes invocando `generar_siguiente_numero('pedido', empresa_id=1, anio=2999)`.

    Invariantes:
      - Los 10 números devueltos son DISTINTOS (no hay colisión).
      - Los 10 enteros son exactamente {1, 2, ..., 10} (sin gaps — cada worker
        commitea su propia transacción, así que bajo FOR UPDATE el contador
        avanza 1 por worker).
      - Al final, el `ultimo_numero` persistido = 10.
    """
    from app.services.numeracion_service import generar_siguiente_numero

    SessionLocal = sessionmaker(bind=pg_engine, autoflush=False, expire_on_commit=False)

    resultados: list[tuple[str, int]] = []
    excepciones: list[Exception] = []
    lock = threading.Lock()
    start_gate = threading.Event()

    def worker() -> None:
        start_gate.wait()  # todos arrancan al unísono
        session = SessionLocal()
        try:
            numero, nuevo = generar_siguiente_numero(
                session,
                tipo="pedido",
                empresa_id=1,
                anio=2999,
            )
            session.commit()
            with lock:
                resultados.append((numero, nuevo))
        except Exception as exc:  # noqa: BLE001 — recolectamos todas las excepciones
            session.rollback()
            with lock:
                excepciones.append(exc)
        finally:
            session.close()

    threads = [threading.Thread(target=worker, name=f"worker-{i}") for i in range(10)]
    for t in threads:
        t.start()

    start_gate.set()  # start!

    for t in threads:
        t.join(timeout=30)
        assert not t.is_alive(), f"Worker {t.name} no terminó en 30s — deadlock?"

    # ─── Asserts ──────────────────────────────────────────────────────────
    assert not excepciones, f"Workers lanzaron {len(excepciones)} excepciones: {excepciones[:3]}"
    assert len(resultados) == 10, f"Solo {len(resultados)}/10 workers completaron exitosamente."

    enteros = sorted(n for _, n in resultados)
    assert enteros == list(range(1, 11)), (
        f"Se esperaban enteros 1..10 consecutivos, se obtuvieron {enteros}. "
        f"Esto indica colisión, skip de números, o race condition en el lock."
    )

    numeros_str = [s for s, _ in resultados]
    assert len(set(numeros_str)) == 10, f"Hay duplicados en los strings generados: {sorted(numeros_str)}"

    # Estado final persistido
    with pg_engine.connect() as conn:
        ultimo = conn.execute(
            text(
                """
                SELECT ultimo_numero FROM compras_numeracion
                WHERE tipo = 'pedido' AND empresa_id = 1 AND anio = 2999
                """
            )
        ).scalar()
        assert ultimo == 10, f"ultimo_numero esperado=10, obtenido={ultimo}"
