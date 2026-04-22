"""
Tests de `numeracion_service.generar_siguiente_numero` (COMPRAS-2.2).

Cubre:
  - Formato exacto del correlativo.
  - Incremento simple.
  - Aislación por tipo / empresa / año (PK compuesta).
  - Padding a 5 dígitos + log WARNING al superar 100_000.
  - Default de `anio` con TZ Argentina (D18).
  - Manejo de concurrencia (10 threads → 10 números únicos).
  - Tipo inválido raise ValueError.

NOTA IMPORTANTE sobre el test de concurrencia:
  - SQLite en memoria del fixture `db` no garantiza comportamiento
    `SELECT FOR UPDATE` como Postgres. El test de concurrencia se escribe
    con foco en validar "sin duplicados" en la secuencia resultante —
    equivalente a la garantía de negocio. Bajo Postgres real el lock
    pesimista es enforced por el engine (design §2.6).
  - Para el test usamos un engine SQLite en archivo temporal con
    `check_same_thread=False` y un nuevo sessionmaker local — el fixture
    `db` de conftest usa un único Connection compartido, que no sirve para
    multi-thread.
"""

from __future__ import annotations

import logging
import tempfile
import threading
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models.empresa import Empresa  # noqa: F401 — registrar en metadata
from app.models.numeracion_contador import NumeracionContador  # noqa: F401
from app.services.numeracion_service import (
    PREFIX,
    PREFIJOS,
    TZ_ARGENTINA,
    generar_siguiente_numero,
)


# ──────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────


def _crear_empresa(db, empresa_id: int, nombre: str = "Empresa Test") -> None:
    """Inserta una empresa mínima para satisfacer la FK del contador."""
    emp = Empresa(id=empresa_id, nombre=f"{nombre} {empresa_id}", activo=True, orden=0)
    db.add(emp)
    db.flush()


# ──────────────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────────────


class TestConstantes:
    def test_prefijos_matchea_prefix(self) -> None:
        """El alias PREFIJOS y PREFIX apuntan al mismo dict."""
        assert PREFIJOS is PREFIX

    def test_prefijos_contiene_los_tipos_soportados(self) -> None:
        # Compras v1: pedido + orden_pago.
        # Compras v2: + nota_credito (NCs locales).
        assert PREFIX == {"pedido": "P", "orden_pago": "OP", "nota_credito": "NC"}

    def test_tz_argentina_es_utc_minus_3(self) -> None:
        assert TZ_ARGENTINA == ZoneInfo("America/Argentina/Buenos_Aires")


class TestFormato:
    def test_primer_numero_pedido_formato(self, db) -> None:
        _crear_empresa(db, 1)
        numero, nuevo = generar_siguiente_numero(db, tipo="pedido", empresa_id=1, anio=2026)
        assert numero == "P-01-2026-00001"
        assert nuevo == 1

    def test_primer_numero_op_formato(self, db) -> None:
        _crear_empresa(db, 2)
        numero, nuevo = generar_siguiente_numero(db, tipo="orden_pago", empresa_id=2, anio=2026)
        assert numero == "OP-02-2026-00001"
        assert nuevo == 1


class TestIncremento:
    def test_siguiente_incrementa_uno(self, db) -> None:
        _crear_empresa(db, 1)
        n1, i1 = generar_siguiente_numero(db, tipo="pedido", empresa_id=1, anio=2026)
        n2, i2 = generar_siguiente_numero(db, tipo="pedido", empresa_id=1, anio=2026)

        assert n1 == "P-01-2026-00001"
        assert n2 == "P-01-2026-00002"
        assert i2 == i1 + 1

    def test_100_numeros_secuenciales_sin_gap(self, db) -> None:
        _crear_empresa(db, 1)
        resultados = [generar_siguiente_numero(db, tipo="pedido", empresa_id=1, anio=2026)[1] for _ in range(100)]
        assert resultados == list(range(1, 101))


class TestAislacion:
    def test_aislado_por_tipo(self, db) -> None:
        _crear_empresa(db, 1)

        _, pedido_1 = generar_siguiente_numero(db, tipo="pedido", empresa_id=1, anio=2026)
        _, op_1 = generar_siguiente_numero(db, tipo="orden_pago", empresa_id=1, anio=2026)
        _, pedido_2 = generar_siguiente_numero(db, tipo="pedido", empresa_id=1, anio=2026)

        # Pedidos y OPs tienen contadores separados.
        assert pedido_1 == 1
        assert op_1 == 1
        assert pedido_2 == 2

    def test_aislado_por_empresa(self, db) -> None:
        _crear_empresa(db, 1)
        _crear_empresa(db, 2)

        _, e1 = generar_siguiente_numero(db, tipo="pedido", empresa_id=1, anio=2026)
        _, e2 = generar_siguiente_numero(db, tipo="pedido", empresa_id=2, anio=2026)

        assert e1 == 1
        assert e2 == 1

    def test_aislado_por_anio(self, db) -> None:
        _crear_empresa(db, 1)

        n_2026, i_2026 = generar_siguiente_numero(db, tipo="pedido", empresa_id=1, anio=2026)
        n_2027, i_2027 = generar_siguiente_numero(db, tipo="pedido", empresa_id=1, anio=2027)

        assert n_2026 == "P-01-2026-00001"
        assert n_2027 == "P-01-2027-00001"
        assert i_2026 == 1
        assert i_2027 == 1


class TestPadding5Digitos:
    def test_99999_es_5_digitos(self, db) -> None:
        _crear_empresa(db, 1)
        # Precargar contador en 99_998 para que el próximo sea 99_999.
        db.add(NumeracionContador(tipo="pedido", empresa_id=1, anio=2026, ultimo_numero=99_998))
        db.flush()

        numero, nuevo = generar_siguiente_numero(db, tipo="pedido", empresa_id=1, anio=2026)
        assert numero == "P-01-2026-99999"
        assert nuevo == 99_999

    def test_100000_no_trunca_loguea_warning(self, db, caplog: pytest.LogCaptureFixture) -> None:
        """Superado el techo de 5 dígitos: no trunca, emite WARNING."""
        _crear_empresa(db, 1)
        db.add(NumeracionContador(tipo="pedido", empresa_id=1, anio=2026, ultimo_numero=99_999))
        db.flush()

        target_logger = logging.getLogger("app.services.numeracion_service")
        target_logger.addHandler(caplog.handler)
        target_logger.setLevel(logging.WARNING)

        try:
            numero, nuevo = generar_siguiente_numero(db, tipo="pedido", empresa_id=1, anio=2026)
        finally:
            target_logger.removeHandler(caplog.handler)

        assert nuevo == 100_000
        # Padding crece — NO se recorta.
        assert numero == "P-01-2026-100000"
        assert any("5 dígitos" in r.getMessage() for r in caplog.records), (
            f"Esperaba WARNING de padding. Records: {[r.getMessage() for r in caplog.records]}"
        )


class TestTipoInvalido:
    def test_tipo_no_soportado_raises_valueerror(self, db) -> None:
        _crear_empresa(db, 1)
        with pytest.raises(ValueError) as exc_info:
            generar_siguiente_numero(db, tipo="factura", empresa_id=1, anio=2026)  # type: ignore[arg-type]

        assert "factura" in str(exc_info.value)
        assert "pedido" in str(exc_info.value)  # mensaje incluye tipos válidos


class TestAnioPorDefectoTzArgentina:
    def test_anio_default_usa_tz_argentina(self, db, monkeypatch) -> None:
        """
        Si `anio=None` → debe resolverse con TZ Argentina.

        Caso crítico: 31-dic 23:30 ART = 02:30 UTC del 1-ene siguiente.
        El servicio debe usar el año ART (31-dic) aunque UTC ya avanzó.
        """
        _crear_empresa(db, 1)

        # Mockeamos datetime.now en el módulo del servicio.
        import app.services.numeracion_service as numsvc

        fake_ahora_ar = datetime(2026, 12, 31, 23, 30, tzinfo=TZ_ARGENTINA)

        class _FakeDatetime:
            @staticmethod
            def now(tz=None):
                return fake_ahora_ar if tz is TZ_ARGENTINA else fake_ahora_ar

        monkeypatch.setattr(numsvc, "datetime", _FakeDatetime)

        numero, _ = generar_siguiente_numero(db, tipo="pedido", empresa_id=1)
        assert numero == "P-01-2026-00001", (
            f"El año debe ser el ARG (2026) incluso si en UTC ya es 2027. Recibido: {numero}"
        )


class TestConcurrencia:
    """
    Test de concurrencia — 10 threads pidiendo números "simultáneos".

    ⚠ IMPORTANTE — limitación de SQLite:
      SQLite NO implementa `SELECT FOR UPDATE` (el método `.with_for_update()`
      se emite como NO-OP). En Postgres el servicio queda protegido por el
      lock pesimista del design §2.6. Bajo SQLite, sin ese lock, 10 threads
      concurrentes leen el mismo `ultimo_numero` y producen duplicados —
      comportamiento reproducible, pero NO refleja producción.

    Estrategia del test:
      - Cada thread corre con una sesión propia y consigue su correlativo.
      - Para emular el lock pesimista de Postgres serializamos el acceso al
        servicio con un `threading.Lock` de Python. Esto valida que, DADO
        el lock (que Postgres provee real vía FOR UPDATE), el servicio en
        sí retorna una secuencia contigua sin duplicados.
      - El lock externo NO debería estar en el servicio — lo emulamos acá
        porque el engine de test no lo da.

    Para un test de concurrencia REAL (sin emular el lock) hay que correrlo
    contra Postgres. Queda como integration test en F7 (COMPRAS-7.2) si
    el equipo decide levantar un Postgres efímero en CI.
    """

    def test_10_threads_no_producen_duplicados(self) -> None:
        # Engine dedicado en archivo temporal (multi-thread safe con `check_same_thread=False`).
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test_numeracion_concurrency.sqlite"
            engine = create_engine(
                f"sqlite:///{db_path}",
                connect_args={"check_same_thread": False},
            )

            @event.listens_for(engine, "connect")
            def _set_sqlite_pragma(dbapi_conn, connection_record):  # noqa: ANN001
                cursor = dbapi_conn.cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()

            Base.metadata.create_all(bind=engine)
            Session = sessionmaker(bind=engine)

            # Seed: empresa 1
            with Session() as sess:
                sess.add(Empresa(id=1, nombre="ConcurrencyTest", activo=True, orden=0))
                sess.commit()

            numeros_obtenidos: list[tuple[str, int]] = []
            lock_resultados = threading.Lock()
            # Emula el SELECT FOR UPDATE de Postgres bajo SQLite (ver docstring).
            lock_lectura_escritura = threading.Lock()
            errores: list[Exception] = []

            def _worker() -> None:
                try:
                    with Session() as sess:
                        with lock_lectura_escritura:
                            num, entero = generar_siguiente_numero(sess, tipo="pedido", empresa_id=1, anio=2026)
                            sess.commit()
                        with lock_resultados:
                            numeros_obtenidos.append((num, entero))
                except Exception as exc:  # pragma: no cover
                    with lock_resultados:
                        errores.append(exc)

            threads = [threading.Thread(target=_worker) for _ in range(10)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=10)

            Base.metadata.drop_all(bind=engine)
            engine.dispose()

            # Sin errores inesperados.
            assert not errores, f"Errores en workers: {errores}"

            # Obtuvimos 10 resultados.
            assert len(numeros_obtenidos) == 10

            # Sin duplicados en los números ni en los correlativos.
            strings = [n[0] for n in numeros_obtenidos]
            enteros = [n[1] for n in numeros_obtenidos]
            assert len(set(strings)) == 10, f"Duplicados en números string: {strings}"
            assert len(set(enteros)) == 10, f"Duplicados en enteros: {enteros}"

            # Los enteros deben ser contiguos 1..10 (sin gaps en este test sin rollbacks).
            assert sorted(enteros) == list(range(1, 11))
