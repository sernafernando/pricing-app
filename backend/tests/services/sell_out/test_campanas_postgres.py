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
from sqlalchemy.exc import IntegrityError
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
    "sell_out_campana_items",
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


@pytest.mark.parametrize("origen", [123, 999], ids=["offset_already_migrated", "unknown_offset"])
def test_a_second_campaign_for_one_offset_or_an_unknown_offset_is_refused_and_leaves_nothing(Session, origen) -> None:
    with Session() as db:
        service.crear_campana(db, _data(), USUARIO, offset_origen_id=123)
    counts = (
        "SELECT (SELECT count(*) FROM sell_out_campanas), (SELECT count(*) FROM auditoria), "
        "(SELECT count(*) FROM sell_out_dirty)"
    )
    with Session() as db:
        before = db.execute(text(counts)).one()
        with pytest.raises(IntegrityError):
            service.crear_campana(db, _data(nombre="Otra"), USUARIO, offset_origen_id=origen)
    with Session() as db:
        assert db.execute(text(counts)).one() == before


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


# ── Per-product amounts (T22b S25: legacy grouped offsets) ──────────

ROUTER, SWITCH, AJENO = 2964, 2270, 950


def _alcance(db) -> None:
    """Group 1 reaches the router and the switch; the third product is outside it."""
    for item_id in (ROUTER, SWITCH, AJENO):
        db.execute(
            text("INSERT INTO productos_erp (item_id, codigo, descripcion) VALUES (:i, :c, 'P')"),
            {"i": item_id, "c": f"C{item_id}"},
        )
    for item_id in (ROUTER, SWITCH):
        db.execute(
            text("INSERT INTO offset_grupo_filtros (grupo_id, item_id) VALUES (:g, :i)"), {"g": GRUPO, "i": item_id}
        )
    db.commit()


def _guardados(db, campana_id: int) -> list[tuple]:
    sql = "SELECT item_id, monto_unit FROM sell_out_campana_items WHERE campana_id = :c ORDER BY item_id"
    return [tuple(r) for r in db.execute(text(sql), {"c": campana_id})]


def test_a_campaign_stores_returns_audits_and_queues_its_product_amounts(Session) -> None:
    with Session() as db:
        _alcance(db)
        items = [{"item_id": SWITCH, "monto_unit": "7.5"}, {"item_id": ROUTER, "monto_unit": "25"}]
        campana_id = service.crear_campana(db, _data(items=items), USUARIO).id
    with Session() as db:
        assert _guardados(db, campana_id) == [(SWITCH, Decimal("7.50")), (ROUTER, Decimal("25.00"))]
        esperado = [{"item_id": SWITCH, "monto_unit": "7.50"}, {"item_id": ROUTER, "monto_unit": "25.00"}]
        # The response names each product (code and description); the audit keeps id and amount.
        assert [{k: i[k] for k in ("item_id", "monto_unit")} for i in _api(db, campana_id)["items"]] == esperado
        assert [i["codigo"] for i in _api(db, campana_id)["items"]] == [f"C{SWITCH}", f"C{ROUTER}"]
        assert _audit(db, TipoAccion.SELL_OUT_CAMPANA_CREADA).valores_nuevos["items"] == esperado
        assert db.execute(text("SELECT campana_id FROM sell_out_dirty")).scalars().all() == [campana_id]


def test_an_edit_replaces_the_product_amounts(Session) -> None:
    with Session() as db:
        _alcance(db)
        antes = [{"item_id": ROUTER, "monto_unit": "25"}, {"item_id": SWITCH, "monto_unit": "7.5"}]
        campana_id = service.crear_campana(db, _data(items=antes), USUARIO).id
        db.execute(text("DELETE FROM sell_out_dirty"))
        db.commit()
    with Session() as db:
        service.editar_campana(db, campana_id, _data(items=[{"item_id": SWITCH, "monto_unit": "8"}]), USUARIO)
    with Session() as db:
        assert _guardados(db, campana_id) == [(SWITCH, Decimal("8.00"))]
        audit = _audit(db, TipoAccion.SELL_OUT_CAMPANA_EDITADA)
        assert audit.valores_anteriores["items"] == [
            {"item_id": SWITCH, "monto_unit": "7.50"},
            {"item_id": ROUTER, "monto_unit": "25.00"},
        ]
        assert audit.valores_nuevos["items"] == [{"item_id": SWITCH, "monto_unit": "8.00"}]
        assert db.execute(text("SELECT campana_id FROM sell_out_dirty")).scalars().all() == [campana_id]
    with Session() as db:
        service.editar_campana(db, campana_id, _data(items=[]), USUARIO)  # cleared: the campaign amount for all
    with Session() as db:
        assert _guardados(db, campana_id) == []
        assert _api(db, campana_id)["items"] == []


def test_a_campaign_without_product_amounts_returns_an_empty_list(Session) -> None:
    with Session() as db:
        campana_id = service.crear_campana(db, _data(), USUARIO).id
    with Session() as db:
        assert _api(db, campana_id)["items"] == []
        assert _audit(db, TipoAccion.SELL_OUT_CAMPANA_CREADA).valores_nuevos["items"] == []


@pytest.mark.parametrize(
    "overrides,mensaje",
    [
        (
            {
                "tipo": "porcentaje",
                "monto_unit": None,
                "porcentaje": "2",
                "items": [{"item_id": ROUTER, "monto_unit": "5"}],
            },
            "Una campaña por porcentaje no lleva montos por producto",
        ),
        (
            {"items": [{"item_id": ROUTER, "monto_unit": "5"}, {"item_id": ROUTER, "monto_unit": "6"}]},
            f"El producto {ROUTER} tiene más de un monto",
        ),
        (
            {"items": [{"item_id": ROUTER, "monto_unit": "0"}]},
            f"El monto del producto {ROUTER} tiene que ser mayor a 0",
        ),
        (
            {"items": [{"item_id": ROUTER, "monto_unit": "-1"}]},
            f"El monto del producto {ROUTER} tiene que ser mayor a 0",
        ),
        (
            {"items": [{"item_id": AJENO, "monto_unit": "5"}]},
            f"El producto {AJENO} no está en los grupos de la campaña",
        ),
    ],
    ids=["porcentaje", "duplicado", "cero", "negativo", "fuera_del_alcance"],
)
def test_invalid_product_amounts_are_refused_and_leave_nothing(Session, overrides, mensaje) -> None:
    counts = (
        "SELECT (SELECT count(*) FROM sell_out_campanas), (SELECT count(*) FROM sell_out_campana_items), "
        "(SELECT count(*) FROM auditoria), (SELECT count(*) FROM sell_out_dirty)"
    )
    with Session() as db:
        _alcance(db)
        with pytest.raises(service.SellOutError) as caught:
            service.crear_campana(db, _data(**overrides), USUARIO)
        assert str(caught.value) == mensaje
    with Session() as db:
        assert tuple(db.execute(text(counts)).one()) == (0, 0, 0, 0)


def test_an_edit_with_a_product_outside_the_reach_keeps_the_campaign_as_it_was(Session) -> None:
    with Session() as db:
        _alcance(db)
        campana_id = service.crear_campana(db, _data(items=[{"item_id": ROUTER, "monto_unit": "25"}]), USUARIO).id
    with Session() as db:
        with pytest.raises(service.SellOutError):
            service.editar_campana(db, campana_id, _data(items=[{"item_id": AJENO, "monto_unit": "5"}]), USUARIO)
    with Session() as db:
        assert _guardados(db, campana_id) == [(ROUTER, Decimal("25.00"))]
        assert _audit(db, TipoAccion.SELL_OUT_CAMPANA_EDITADA) is None


def test_a_product_amount_with_more_decimals_than_the_column_is_rejected_not_rounded() -> None:
    with pytest.raises(ValueError):
        _data(items=[{"item_id": ROUTER, "monto_unit": "1.005"}])
