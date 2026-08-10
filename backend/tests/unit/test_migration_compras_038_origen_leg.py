"""
Migration tests for compras_038 — pata origen (`monto_origen` / `moneda_origen`)
en `imputaciones`.

Estrategia: invocar `upgrade()`/`downgrade()` de Alembic fuera de su entorno
(env.py + alembic.ini + engine configurado) levanta "Can't invoke function,
proxy not established". Pero el backfill —la parte con riesgo contable real—
vive en el módulo de migración como SQL portable (`BACKFILL_BASE_SQL` /
`BACKFILL_OP_CROSS_MONEDA_SQL`) y estos tests ejecutan ESAS MISMAS sentencias
contra SQLite. Así el test queda atado al artefacto real, no a una copia.

El DDL de columnas/constraints sí se espeja (SQLite no soporta agregar CHECK
con ALTER TABLE); su simetría a nivel Postgres se verifica corriendo
`alembic upgrade head` contra la DB de staging.

Cobertura:
  - Las dos columnas se agregan como NULLABLE.
  - Backfill base: `monto_origen = monto_imputado`, `moneda_origen = moneda_imputada`.
  - Backfill correctivo: filas OP-origen cross-moneda (donde `moneda_imputada`
    es la moneda DESTINO) se reconstruyen a la moneda de la OP usando
    `tipo_cambio`.
  - Round-trip upgrade → downgrade.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.pool import StaticPool


def _cargar_migracion(nombre: str) -> object:
    """Carga un módulo de `alembic/versions/` por path.

    No sirve `import alembic.versions...`: el paquete `alembic` resuelve a la
    librería instalada, no al directorio del repo.
    """
    ruta = Path(__file__).resolve().parents[2] / "alembic" / "versions" / f"{nombre}.py"
    spec = importlib.util.spec_from_file_location(nombre, ruta)
    assert spec is not None and spec.loader is not None, f"No pude cargar {ruta}"
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


# El módulo de migración expone el SQL de backfill como constantes portables
# (Postgres + SQLite) justamente para poder ejercitarlas acá.
_mig = _cargar_migracion("compras_038_imputacion_origen_leg")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_engine() -> sa.Engine:
    return create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def _create_pre038_schema(engine: sa.Engine) -> None:
    """Estado pre-compras_038: `imputaciones` sin la pata origen."""
    with engine.connect() as conn:
        conn.execute(
            text("""
            CREATE TABLE IF NOT EXISTS ordenes_pago (
                id INTEGER PRIMARY KEY,
                moneda TEXT NOT NULL,
                monto_total NUMERIC(18,2) NOT NULL DEFAULT 0
            )
        """)
        )
        conn.execute(
            text("""
            CREATE TABLE IF NOT EXISTS imputaciones (
                id INTEGER PRIMARY KEY,
                origen_tipo TEXT NOT NULL,
                origen_id INTEGER NOT NULL,
                destino_tipo TEXT NOT NULL,
                destino_id INTEGER,
                monto_imputado NUMERIC(18,2) NOT NULL,
                moneda_imputada TEXT NOT NULL,
                tipo_cambio NUMERIC(18,6),
                proveedor_id INTEGER NOT NULL,
                es_reversal INTEGER NOT NULL DEFAULT 0,
                reimputada_desde_id INTEGER,
                creado_por_id INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        )
        conn.commit()


def _apply_upgrade_038(engine: sa.Engine) -> None:
    """DDL de compras_038.upgrade() espejada para SQLite.

    Los CHECK constraints con nombre se crean en la migración real via
    `op.create_check_constraint` (Postgres). SQLite no soporta agregarlos
    con ALTER TABLE, así que acá sólo se ejercita columnas + backfill.
    """
    with engine.connect() as conn:
        conn.execute(text("ALTER TABLE imputaciones ADD COLUMN monto_origen NUMERIC(18,2)"))
        conn.execute(text("ALTER TABLE imputaciones ADD COLUMN moneda_origen VARCHAR(3)"))
        # Backfill: SQL REAL de la migración, no una copia.
        conn.execute(text(_mig.BACKFILL_BASE_SQL))
        conn.execute(text(_mig.BACKFILL_OP_CROSS_MONEDA_SQL))
        conn.commit()


def _apply_downgrade_038(engine: sa.Engine) -> None:
    with engine.connect() as conn:
        conn.execute(text("ALTER TABLE imputaciones DROP COLUMN moneda_origen"))
        conn.execute(text("ALTER TABLE imputaciones DROP COLUMN monto_origen"))
        conn.commit()


def _insert_imputacion(engine: sa.Engine, **kwargs: object) -> None:
    cols = {
        "origen_tipo": "nota_credito_local",
        "origen_id": 1,
        "destino_tipo": "pedido_compra",
        "destino_id": 10,
        "monto_imputado": 1000,
        "moneda_imputada": "ARS",
        "tipo_cambio": None,
        "proveedor_id": 7,
        "es_reversal": 0,
        "creado_por_id": 1,
    }
    cols.update(kwargs)
    campos = ", ".join(cols.keys())
    binds = ", ".join(f":{k}" for k in cols)
    with engine.connect() as conn:
        conn.execute(text(f"INSERT INTO imputaciones ({campos}) VALUES ({binds})"), cols)
        conn.commit()


# ---------------------------------------------------------------------------
# Tests — estructura
# ---------------------------------------------------------------------------


class TestMigration038Columnas:
    def test_upgrade_agrega_monto_origen(self) -> None:
        engine = _make_engine()
        _create_pre038_schema(engine)
        _apply_upgrade_038(engine)

        cols = {c["name"]: c for c in inspect(engine).get_columns("imputaciones")}
        assert "monto_origen" in cols

    def test_upgrade_agrega_moneda_origen(self) -> None:
        engine = _make_engine()
        _create_pre038_schema(engine)
        _apply_upgrade_038(engine)

        cols = {c["name"]: c for c in inspect(engine).get_columns("imputaciones")}
        assert "moneda_origen" in cols

    def test_ambas_columnas_son_nullable(self) -> None:
        """NULLABLE a nivel DB: tolera filas escritas por instancias de app
        viejas durante una ventana de deploy rolling. La obligatoriedad la
        impone `crear_imputacion` en la capa de aplicación."""
        engine = _make_engine()
        _create_pre038_schema(engine)
        _apply_upgrade_038(engine)

        cols = {c["name"]: c for c in inspect(engine).get_columns("imputaciones")}
        assert cols["monto_origen"]["nullable"] is True
        assert cols["moneda_origen"]["nullable"] is True

    def test_downgrade_elimina_ambas_columnas(self) -> None:
        engine = _make_engine()
        _create_pre038_schema(engine)
        _apply_upgrade_038(engine)
        _apply_downgrade_038(engine)

        cols = {c["name"] for c in inspect(engine).get_columns("imputaciones")}
        assert "monto_origen" not in cols
        assert "moneda_origen" not in cols

    def test_downgrade_preserva_columnas_base(self) -> None:
        engine = _make_engine()
        _create_pre038_schema(engine)
        _apply_upgrade_038(engine)
        _apply_downgrade_038(engine)

        cols = {c["name"] for c in inspect(engine).get_columns("imputaciones")}
        base = {"id", "origen_tipo", "origen_id", "monto_imputado", "moneda_imputada", "tipo_cambio"}
        assert base <= cols, f"Faltan columnas base tras downgrade: {base - cols}"


# ---------------------------------------------------------------------------
# Tests — backfill
# ---------------------------------------------------------------------------


class TestMigration038Backfill:
    def test_backfill_nc_local_same_moneda_es_exacto(self) -> None:
        """NC local ARS → pedido ARS: la pata origen copia la destino tal cual."""
        engine = _make_engine()
        _create_pre038_schema(engine)
        _insert_imputacion(
            engine,
            origen_tipo="nota_credito_local",
            origen_id=5,
            monto_imputado=1000,
            moneda_imputada="ARS",
        )

        _apply_upgrade_038(engine)

        with engine.connect() as conn:
            row = conn.execute(text("SELECT monto_origen, moneda_origen FROM imputaciones")).fetchone()
        assert row is not None
        assert float(row[0]) == 1000.0
        assert row[1] == "ARS"

    def test_backfill_dinero_a_cuenta_es_exacto(self) -> None:
        """DAC: `moneda_imputada` ya es la moneda ORIGEN (dac.moneda), así que
        la copia directa es exacta incluso cross-moneda."""
        engine = _make_engine()
        _create_pre038_schema(engine)
        _insert_imputacion(
            engine,
            origen_tipo="dinero_a_cuenta",
            origen_id=3,
            monto_imputado=250,
            moneda_imputada="USD",
        )

        _apply_upgrade_038(engine)

        with engine.connect() as conn:
            row = conn.execute(text("SELECT monto_origen, moneda_origen FROM imputaciones")).fetchone()
        assert row is not None
        assert float(row[0]) == 250.0
        assert row[1] == "USD"

    def test_backfill_op_same_moneda_no_se_toca(self) -> None:
        """OP ARS → pedido ARS: el paso correctivo NO debe aplicarse."""
        engine = _make_engine()
        _create_pre038_schema(engine)
        with engine.connect() as conn:
            conn.execute(text("INSERT INTO ordenes_pago (id, moneda) VALUES (42, 'ARS')"))
            conn.commit()
        _insert_imputacion(
            engine,
            origen_tipo="orden_pago",
            origen_id=42,
            monto_imputado=5000,
            moneda_imputada="ARS",
            tipo_cambio=1500,
        )

        _apply_upgrade_038(engine)

        with engine.connect() as conn:
            row = conn.execute(text("SELECT monto_origen, moneda_origen FROM imputaciones")).fetchone()
        assert row is not None
        assert float(row[0]) == 5000.0
        assert row[1] == "ARS"

    def test_backfill_op_ars_a_pedido_usd_reconstruye_la_pata_origen(self) -> None:
        """OP ARS paga pedido USD: `monto_imputado` está en USD (destino).
        La pata origen debe reconstruirse a ARS = monto_imputado * TC."""
        engine = _make_engine()
        _create_pre038_schema(engine)
        with engine.connect() as conn:
            conn.execute(text("INSERT INTO ordenes_pago (id, moneda) VALUES (1, 'ARS')"))
            conn.commit()
        _insert_imputacion(
            engine,
            origen_tipo="orden_pago",
            origen_id=1,
            monto_imputado=1000,
            moneda_imputada="USD",
            tipo_cambio=1500,
        )

        _apply_upgrade_038(engine)

        with engine.connect() as conn:
            row = conn.execute(text("SELECT monto_origen, moneda_origen FROM imputaciones")).fetchone()
        assert row is not None
        assert float(row[0]) == 1500000.0
        assert row[1] == "ARS"

    def test_backfill_op_usd_a_pedido_ars_reconstruye_la_pata_origen(self) -> None:
        """OP USD paga pedido ARS: `monto_imputado` está en ARS (destino).
        La pata origen debe reconstruirse a USD = monto_imputado / TC."""
        engine = _make_engine()
        _create_pre038_schema(engine)
        with engine.connect() as conn:
            conn.execute(text("INSERT INTO ordenes_pago (id, moneda) VALUES (2, 'USD')"))
            conn.commit()
        _insert_imputacion(
            engine,
            origen_tipo="orden_pago",
            origen_id=2,
            monto_imputado=1500000,
            moneda_imputada="ARS",
            tipo_cambio=1500,
        )

        _apply_upgrade_038(engine)

        with engine.connect() as conn:
            row = conn.execute(text("SELECT monto_origen, moneda_origen FROM imputaciones")).fetchone()
        assert row is not None
        assert float(row[0]) == 1000.0
        assert row[1] == "USD"

    def test_backfill_op_cross_moneda_sin_tc_cae_al_backfill_base(self) -> None:
        """Sin TC no hay forma de reconstruir: se deja la copia base y NO se
        inventa un valor."""
        engine = _make_engine()
        _create_pre038_schema(engine)
        with engine.connect() as conn:
            conn.execute(text("INSERT INTO ordenes_pago (id, moneda) VALUES (9, 'ARS')"))
            conn.commit()
        _insert_imputacion(
            engine,
            origen_tipo="orden_pago",
            origen_id=9,
            monto_imputado=1000,
            moneda_imputada="USD",
            tipo_cambio=None,
        )

        _apply_upgrade_038(engine)

        with engine.connect() as conn:
            row = conn.execute(text("SELECT monto_origen, moneda_origen FROM imputaciones")).fetchone()
        assert row is not None
        assert float(row[0]) == 1000.0
        assert row[1] == "USD"

    def test_backfill_alcanza_a_los_reversals(self) -> None:
        """Los reversals también son filas: deben quedar con la pata origen."""
        engine = _make_engine()
        _create_pre038_schema(engine)
        _insert_imputacion(engine, origen_id=5, monto_imputado=400, moneda_imputada="ARS", es_reversal=0)
        _insert_imputacion(engine, origen_id=5, monto_imputado=400, moneda_imputada="ARS", es_reversal=1)

        _apply_upgrade_038(engine)

        with engine.connect() as conn:
            filas = conn.execute(text("SELECT monto_origen, moneda_origen FROM imputaciones ORDER BY id")).fetchall()
        assert len(filas) == 2
        for monto_origen, moneda_origen in filas:
            assert float(monto_origen) == 400.0
            assert moneda_origen == "ARS"

    def test_backfill_no_deja_ninguna_fila_con_pata_origen_incompleta(self) -> None:
        """Invariante both-or-neither: nunca media pata."""
        engine = _make_engine()
        _create_pre038_schema(engine)
        with engine.connect() as conn:
            conn.execute(text("INSERT INTO ordenes_pago (id, moneda) VALUES (1, 'ARS')"))
            conn.commit()
        _insert_imputacion(engine, origen_tipo="nota_credito_local", origen_id=5, moneda_imputada="ARS")
        _insert_imputacion(engine, origen_tipo="dinero_a_cuenta", origen_id=6, moneda_imputada="USD")
        _insert_imputacion(
            engine,
            origen_tipo="orden_pago",
            origen_id=1,
            moneda_imputada="USD",
            tipo_cambio=1500,
        )

        _apply_upgrade_038(engine)

        with engine.connect() as conn:
            incompletas = conn.execute(
                text("""
                SELECT COUNT(*) FROM imputaciones
                 WHERE (monto_origen IS NULL) <> (moneda_origen IS NULL)
                """)
            ).scalar()
        assert incompletas == 0


# ---------------------------------------------------------------------------
# Tests — el modelo SQLAlchemy declara la pata origen
# ---------------------------------------------------------------------------


class TestModeloImputacionPataOrigen:
    """`Base.metadata.create_all` (usado por la suite) tiene que crear las
    columnas nuevas, si no los tests de servicio corren contra un esquema viejo."""

    def test_modelo_declara_monto_origen(self) -> None:
        from app.models.imputacion import Imputacion

        col = Imputacion.__table__.columns["monto_origen"]
        assert isinstance(col.type, sa.Numeric)
        assert col.type.precision == 18
        assert col.type.scale == 2
        assert col.nullable is True

    def test_modelo_declara_moneda_origen(self) -> None:
        from app.models.imputacion import Imputacion

        col = Imputacion.__table__.columns["moneda_origen"]
        assert isinstance(col.type, sa.String)
        assert col.type.length == 3
        assert col.nullable is True

    def test_modelo_declara_los_checks_de_la_pata_origen(self) -> None:
        from app.models.imputacion import Imputacion

        nombres = {c.name for c in Imputacion.__table__.constraints if c.name}
        assert "ck_imputaciones_monto_origen_positivo" in nombres
        assert "ck_imputaciones_moneda_origen" in nombres
        assert "ck_imputaciones_origen_leg_completa" in nombres

    def test_docstring_del_modelo_no_afirma_que_cross_moneda_esta_prohibido(self) -> None:
        """El docstring decía "Cross-moneda prohibido en v1 (D3)" — es FALSO
        desde que OP↔pedido cross-moneda se soporta."""
        import app.models.imputacion as modulo

        assert "Cross-moneda prohibido" not in (modulo.__doc__ or "")
