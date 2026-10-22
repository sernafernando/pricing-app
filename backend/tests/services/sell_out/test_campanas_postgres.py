"""Sell-out campaigns service on Postgres: what is stored is what the API returns and the audit records.

SQLite stores NUMERIC as a float and drops the time zone of `timestamptz`, so
the exact stored values are proven here, in a throwaway schema whose session
time zone is not UTC (like production's).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models.auditoria import Auditoria, TipoAccion
from app.models.sell_out import SellOutCampana
from app.schemas.sell_out import SellOutCampanaIn, SellOutCampanaOut
from app.services.sell_out import campanas as service
from app.services.sell_out import resumen

pytestmark = pytest.mark.postgres

# The service queues each change (T7 S3); an edit reads the reach (filters, products) before applying it;
# the API shape carries what each campaign credited (`resumen`, T7 S5).
TABLES = (
    "sell_out_campanas",
    "sell_out_campana_grupos",
    "auditoria",
    "sell_out_dirty",
    "sell_out_consumos",
    "offset_grupo_filtros",
    "productos_erp",
)
USUARIO = 7
GRUPO = 1
_STUBS = [
    "CREATE TABLE usuarios (id INTEGER PRIMARY KEY)",
    "CREATE TABLE offset_grupos (id INTEGER PRIMARY KEY, nombre VARCHAR(100) NOT NULL)",
    "CREATE TABLE offsets_ganancia (id INTEGER PRIMARY KEY)",  # the legacy offset a campaign migrates (T15)
    "INSERT INTO offsets_ganancia VALUES (123)",
    f"INSERT INTO usuarios VALUES ({USUARIO})",
    f"INSERT INTO offset_grupos VALUES ({GRUPO}, 'TP-Link redes')",
]
DECIMALES = ("monto_unit", "porcentaje", "tipo_cambio", "tope_monto")


@pytest.fixture()
def Session():
    from tests.conftest import POSTGRES_TEST_URL, _postgres_reachable, _restore_pristine_pg_types

    if not _postgres_reachable():
        pytest.skip(f"PostgreSQL not reachable at {POSTGRES_TEST_URL}")
    schema = f"sell_out_svc_{uuid.uuid4().hex[:8]}"
    admin = create_engine(POSTGRES_TEST_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f"CREATE SCHEMA {schema}"))
    options = f"-csearch_path={schema} -ctimezone=America/Argentina/Buenos_Aires"
    eng = create_engine(POSTGRES_TEST_URL, connect_args={"options": options})
    tables = [Base.metadata.tables[name] for name in TABLES]
    found = {column: column.type for table in tables for column in table.columns}
    try:
        with eng.begin() as conn:
            for statement in _STUBS:
                conn.execute(text(statement))
        _restore_pristine_pg_types(tables)
        try:
            Base.metadata.create_all(bind=eng, tables=tables)
        finally:
            for column, column_type in found.items():
                column.type = column_type
        yield sessionmaker(bind=eng)
    finally:
        eng.dispose()
        with admin.connect() as conn:
            conn.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        admin.dispose()


def _data(**overrides) -> SellOutCampanaIn:
    body = {
        "nombre": "Campaña TP-Link noviembre",
        "fecha_desde": date(2026, 11, 1),
        "fecha_hasta": date(2026, 11, 30),
        "tipo": "por_unidad",
        "monto_unit": "1500",
        "grupo_ids": [GRUPO],
    }
    body.update(overrides)
    return SellOutCampanaIn.model_validate(body)


def _api(session, campana_id: int) -> dict:
    """The campaign as the API returns it, read back from the database in a fresh session."""
    campana = session.get(SellOutCampana, campana_id)
    return SellOutCampanaOut.model_validate(resumen.serializar(session, [campana])[0]).model_dump(mode="json")


def _audit(session, tipo: TipoAccion) -> Auditoria:
    return session.query(Auditoria).filter(Auditoria.tipo_accion == tipo).order_by(Auditoria.id.desc()).first()


def test_rate_set_time_is_stored_and_audited_as_the_api_returns_it(Session) -> None:
    with Session() as db:
        campana_id = service.crear_campana(db, _data(), USUARIO).id
        service.definir_tipo_cambio(db, campana_id, Decimal("1450.5"), USUARIO)
    with Session() as db:
        api = _api(db, campana_id)
        stored = db.execute(
            text("SELECT tc_definido_en FROM sell_out_campanas WHERE id = :id"), {"id": campana_id}
        ).scalar_one()
        nuevos = _audit(db, TipoAccion.SELL_OUT_CAMPANA_TC_DEFINIDO).valores_nuevos
    assert stored.utcoffset() is not None  # timestamptz, read back in the session's (non-UTC) zone
    assert api["tc_definido_en"] is not None
    assert nuevos["tc_definido_en"] == api["tc_definido_en"]
    assert datetime.fromisoformat(api["tc_definido_en"]) == stored  # the same instant
    assert (nuevos["tipo_cambio"], api["tipo_cambio"]) == ("1450.500000", "1450.500000")

    # Values read back from the database (the "before" of a later change, an edit keeping the rate)
    # are audited the same way.
    with Session() as db:
        service.definir_tipo_cambio(db, campana_id, Decimal("1460"), USUARIO)
    with Session() as db:
        assert (
            _audit(db, TipoAccion.SELL_OUT_CAMPANA_TC_DEFINIDO).valores_anteriores["tc_definido_en"]
            == (api["tc_definido_en"])
        )
        segundo = _api(db, campana_id)["tc_definido_en"]
    with Session() as db:
        service.editar_campana(db, campana_id, _data(nombre="Otra"), USUARIO)
    with Session() as db:
        editada = _audit(db, TipoAccion.SELL_OUT_CAMPANA_EDITADA)
        assert _api(db, campana_id)["tc_definido_en"] == segundo
    assert editada.valores_anteriores["tc_definido_en"] == segundo
    assert editada.valores_nuevos["tc_definido_en"] == segundo


@pytest.mark.parametrize(
    "overrides,esperado",
    [
        (
            {
                "monto_unit": "9999999999999999.99",
                "tope_unidades": 2147483647,
                "tope_monto": "9999999999999999.99",
                "tc_modo": "fijo",
                "tipo_cambio": "999999999999.999999",
            },
            {
                "monto_unit": "9999999999999999.99",
                "porcentaje": None,
                "tipo_cambio": "999999999999.999999",
                "tope_monto": "9999999999999999.99",
            },
        ),
        (
            {"monto_unit": "3", "tope_monto": "1E+3", "tc_modo": "fijo", "tipo_cambio": "1450.5"},
            {"monto_unit": "3.00", "porcentaje": None, "tipo_cambio": "1450.500000", "tope_monto": "1000.00"},
        ),
        (
            {"tipo": "porcentaje", "monto_unit": None, "porcentaje": "99.9999", "moneda": "ARS"},
            {"monto_unit": None, "porcentaje": "99.9999", "tipo_cambio": None, "tope_monto": None},
        ),
        (
            {"tipo": "porcentaje", "monto_unit": None, "porcentaje": "2.5"},
            {"monto_unit": None, "porcentaje": "2.5000", "tipo_cambio": None, "tope_monto": None},
        ),
    ],
)
def test_create_and_edit_store_and_audit_the_same_decimals(Session, overrides, esperado) -> None:
    with Session() as db:
        campana_id = service.crear_campana(db, _data(**overrides), USUARIO).id
    with Session() as db:
        creada = _api(db, campana_id)
        nuevos = _audit(db, TipoAccion.SELL_OUT_CAMPANA_CREADA).valores_nuevos
    assert {c: creada[c] for c in DECIMALES} == esperado
    assert {c: nuevos[c] for c in DECIMALES} == esperado

    with Session() as db:
        service.editar_campana(db, campana_id, _data(**overrides, nombre="Otra"), USUARIO)
    with Session() as db:
        editada = _api(db, campana_id)
        audit = _audit(db, TipoAccion.SELL_OUT_CAMPANA_EDITADA)
    assert {c: editada[c] for c in DECIMALES} == esperado
    assert {c: audit.valores_nuevos[c] for c in DECIMALES} == esperado
    assert {c: audit.valores_anteriores[c] for c in DECIMALES} == esperado


def test_a_migrated_campaign_stores_audits_and_returns_its_legacy_offset_and_an_edit_keeps_it(Session) -> None:
    with Session() as db:
        migrada = service.crear_campana(db, _data(), USUARIO, offset_origen_id=123).id
        manual = service.crear_campana(db, _data(nombre="Manual"), USUARIO).id
    with Session() as db:
        assert (_api(db, migrada)["offset_origen_id"], _api(db, manual)["offset_origen_id"]) == (123, None)
        creadas = db.query(Auditoria).filter(Auditoria.tipo_accion == TipoAccion.SELL_OUT_CAMPANA_CREADA)
        valores = {a.valores_nuevos["campana_id"]: a.valores_nuevos for a in creadas}
    assert valores[migrada]["offset_origen_id"] == 123
    assert "offset_origen_id" not in valores[manual]  # a campaign loaded by hand audits as before

    with Session() as db:
        service.editar_campana(db, migrada, _data(nombre="Editada"), USUARIO)
    with Session() as db:
        assert _api(db, migrada)["offset_origen_id"] == 123
