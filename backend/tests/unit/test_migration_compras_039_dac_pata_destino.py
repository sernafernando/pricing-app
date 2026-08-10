"""
Migration tests for compras_039 — corrección de la pata DESTINO en las
imputaciones con origen `dinero_a_cuenta`.

Misma estrategia que `test_migration_compras_038_origen_leg.py`: el SQL con
riesgo contable vive en el módulo de migración como constante portable
(`FIX_DAC_PATA_DESTINO_SQL`) y estos tests ejecutan ESA MISMA sentencia contra
SQLite, así el test queda atado al artefacto real y no a una copia.

Cobertura:
  - DAC ARS → pedido USD: la pata destino pasa a USD con el TC del pedido.
  - DAC USD → pedido ARS: espejo.
  - La pata ORIGEN nunca se toca (el saldo del DAC ya era exacto).
  - Filas same-moneda no se tocan.
  - Filas cuyo pedido destino no tiene TC utilizable no se tocan.
  - Reversals se corrigen igual que las filas primarias.
  - Idempotencia: correr dos veces deja el mismo resultado.
  - Otros orígenes (`orden_pago`, `nota_credito_local`) no se tocan.
"""

from __future__ import annotations

import importlib.util
from decimal import Decimal
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool


def _cargar_migracion(nombre: str) -> object:
    ruta = Path(__file__).resolve().parents[2] / "alembic" / "versions" / f"{nombre}.py"
    spec = importlib.util.spec_from_file_location(nombre, ruta)
    assert spec is not None and spec.loader is not None, f"No pude cargar {ruta}"
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


_mig = _cargar_migracion("compras_039_dac_pata_destino")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_engine() -> sa.Engine:
    return create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def _create_schema(engine: sa.Engine) -> None:
    """Estado post-compras_038: `imputaciones` con la pata origen backfilleada."""
    with engine.connect() as conn:
        conn.execute(
            text("""
            CREATE TABLE pedidos_compra (
                id INTEGER PRIMARY KEY,
                moneda TEXT NOT NULL,
                monto NUMERIC(18,2) NOT NULL DEFAULT 0,
                tipo_cambio NUMERIC(18,6)
            )
        """)
        )
        conn.execute(
            text("""
            CREATE TABLE imputaciones (
                id INTEGER PRIMARY KEY,
                origen_tipo TEXT NOT NULL,
                origen_id INTEGER NOT NULL,
                destino_tipo TEXT NOT NULL,
                destino_id INTEGER,
                monto_imputado NUMERIC(18,2) NOT NULL,
                moneda_imputada TEXT NOT NULL,
                monto_origen NUMERIC(18,2),
                moneda_origen TEXT,
                tipo_cambio NUMERIC(18,6),
                proveedor_id INTEGER NOT NULL,
                es_reversal INTEGER NOT NULL DEFAULT 0,
                creado_por_id INTEGER NOT NULL
            )
        """)
        )
        conn.commit()


def _insert_pedido(engine: sa.Engine, *, id: int, moneda: str, tipo_cambio: str | None) -> None:
    with engine.connect() as conn:
        conn.execute(
            text("INSERT INTO pedidos_compra (id, moneda, monto, tipo_cambio) VALUES (:id, :m, 0, :tc)"),
            {"id": id, "m": moneda, "tc": tipo_cambio},
        )
        conn.commit()


def _insert_imputacion(
    engine: sa.Engine,
    *,
    id: int,
    origen_tipo: str = "dinero_a_cuenta",
    destino_tipo: str = "pedido_compra",
    destino_id: int,
    monto: str,
    moneda: str,
    es_reversal: bool = False,
) -> None:
    """Inserta una fila tal como la escribía el `consumir` viejo: las dos patas
    denominadas en la moneda del ORIGEN y sin `tipo_cambio`."""
    with engine.connect() as conn:
        conn.execute(
            text("""
            INSERT INTO imputaciones
              (id, origen_tipo, origen_id, destino_tipo, destino_id,
               monto_imputado, moneda_imputada, monto_origen, moneda_origen,
               tipo_cambio, proveedor_id, es_reversal, creado_por_id)
            VALUES
              (:id, :ot, 1, :dt, :did, :monto, :moneda, :monto, :moneda,
               NULL, 1, :rev, 1)
        """),
            {
                "id": id,
                "ot": origen_tipo,
                "dt": destino_tipo,
                "did": destino_id,
                "monto": monto,
                "moneda": moneda,
                "rev": 1 if es_reversal else 0,
            },
        )
        conn.commit()


def _fila(engine: sa.Engine, id: int) -> dict:
    with engine.connect() as conn:
        row = conn.execute(
            text("""
            SELECT monto_imputado, moneda_imputada, monto_origen, moneda_origen, tipo_cambio
              FROM imputaciones WHERE id = :id
        """),
            {"id": id},
        ).one()
    return {
        "monto_imputado": Decimal(str(row.monto_imputado)),
        "moneda_imputada": row.moneda_imputada,
        "monto_origen": Decimal(str(row.monto_origen)),
        "moneda_origen": row.moneda_origen,
        "tipo_cambio": None if row.tipo_cambio is None else Decimal(str(row.tipo_cambio)),
    }


def _run_upgrade(engine: sa.Engine) -> None:
    with engine.connect() as conn:
        conn.execute(text(_mig.FIX_DAC_PATA_DESTINO_SQL))
        conn.commit()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCompras039FixPataDestino:
    def test_dac_ars_contra_pedido_usd_se_denomina_en_usd(self) -> None:
        engine = _make_engine()
        _create_schema(engine)
        _insert_pedido(engine, id=1, moneda="USD", tipo_cambio="1500")
        _insert_imputacion(engine, id=10, destino_id=1, monto="150000", moneda="ARS")

        _run_upgrade(engine)

        fila = _fila(engine, 10)
        assert fila["moneda_imputada"] == "USD"
        assert fila["monto_imputado"] == Decimal("100")
        assert fila["tipo_cambio"] == Decimal("1500")
        # La pata origen NO se toca: el saldo del DAC ya era exacto.
        assert fila["monto_origen"] == Decimal("150000")
        assert fila["moneda_origen"] == "ARS"

    def test_dac_usd_contra_pedido_ars_espejo(self) -> None:
        engine = _make_engine()
        _create_schema(engine)
        _insert_pedido(engine, id=2, moneda="ARS", tipo_cambio="1500")
        _insert_imputacion(engine, id=11, destino_id=2, monto="100", moneda="USD")

        _run_upgrade(engine)

        fila = _fila(engine, 11)
        assert fila["moneda_imputada"] == "ARS"
        assert fila["monto_imputado"] == Decimal("150000")
        assert fila["tipo_cambio"] == Decimal("1500")
        assert fila["monto_origen"] == Decimal("100")
        assert fila["moneda_origen"] == "USD"

    def test_same_moneda_no_se_toca(self) -> None:
        engine = _make_engine()
        _create_schema(engine)
        _insert_pedido(engine, id=3, moneda="ARS", tipo_cambio="1500")
        _insert_imputacion(engine, id=12, destino_id=3, monto="5000", moneda="ARS")

        _run_upgrade(engine)

        fila = _fila(engine, 12)
        assert fila["moneda_imputada"] == "ARS"
        assert fila["monto_imputado"] == Decimal("5000")
        # Sin conversión no hay TC que grabar.
        assert fila["tipo_cambio"] is None

    def test_pedido_sin_tc_utilizable_no_se_toca(self) -> None:
        """Preferimos dejar la fila visible antes que fabricar un TC."""
        engine = _make_engine()
        _create_schema(engine)
        _insert_pedido(engine, id=4, moneda="USD", tipo_cambio=None)
        _insert_pedido(engine, id=5, moneda="USD", tipo_cambio="0")
        _insert_imputacion(engine, id=13, destino_id=4, monto="150000", moneda="ARS")
        _insert_imputacion(engine, id=14, destino_id=5, monto="150000", moneda="ARS")

        _run_upgrade(engine)

        for imp_id in (13, 14):
            fila = _fila(engine, imp_id)
            assert fila["moneda_imputada"] == "ARS"
            assert fila["monto_imputado"] == Decimal("150000")
            assert fila["tipo_cambio"] is None

        # …y quedan localizables con la query de diagnóstico.
        with engine.connect() as conn:
            pendientes = conn.execute(text(_mig.DIAGNOSTICO_PENDIENTES_SQL)).fetchall()
        assert {row.id for row in pendientes} == {13, 14}

    def test_reversal_se_corrige_igual_que_la_primaria(self) -> None:
        """Un reversal copia las dos patas verbatim: arrastra el mismo error."""
        engine = _make_engine()
        _create_schema(engine)
        _insert_pedido(engine, id=6, moneda="USD", tipo_cambio="1500")
        _insert_imputacion(engine, id=15, destino_id=6, monto="150000", moneda="ARS")
        _insert_imputacion(engine, id=16, destino_id=6, monto="150000", moneda="ARS", es_reversal=True)

        _run_upgrade(engine)

        assert _fila(engine, 15)["monto_imputado"] == _fila(engine, 16)["monto_imputado"] == Decimal("100")
        assert _fila(engine, 16)["moneda_imputada"] == "USD"

    def test_otros_origenes_no_se_tocan(self) -> None:
        engine = _make_engine()
        _create_schema(engine)
        _insert_pedido(engine, id=7, moneda="USD", tipo_cambio="1500")
        # NC local en ARS sobre un pedido USD — es la fila de varianza TC que
        # `resolver_varianza_tc` graba a propósito denominada en ARS.
        _insert_imputacion(engine, id=17, origen_tipo="nota_credito_local", destino_id=7, monto="5000", moneda="ARS")
        _insert_imputacion(engine, id=18, origen_tipo="orden_pago", destino_id=7, monto="5000", moneda="ARS")

        _run_upgrade(engine)

        for imp_id in (17, 18):
            fila = _fila(engine, imp_id)
            assert fila["moneda_imputada"] == "ARS"
            assert fila["monto_imputado"] == Decimal("5000")

    def test_idempotente(self) -> None:
        engine = _make_engine()
        _create_schema(engine)
        _insert_pedido(engine, id=8, moneda="USD", tipo_cambio="1500")
        _insert_imputacion(engine, id=19, destino_id=8, monto="150000", moneda="ARS")

        _run_upgrade(engine)
        primera = _fila(engine, 19)
        _run_upgrade(engine)

        assert _fila(engine, 19) == primera
