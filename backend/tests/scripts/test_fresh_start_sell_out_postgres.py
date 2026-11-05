"""`fresh_start_sell_out` against Postgres: the owner's "empezar de 0" deletes every legacy sell-out campaign,
program, product group and offset (with their consumptions, queue rows and audit rows) in one transaction, and
nothing else. Dry run by default; `--apply` needs `--confirm "BORRAR TODO"`; any tactical stops it untouched."""

from __future__ import annotations

import json
from typing import Iterator

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import sessionmaker

from app.core import database
from app.models.auditoria import Auditoria
from app.models.offset_ganancia import OffsetGanancia
from app.models.offset_grupo import OffsetGrupo
from app.models.offset_grupo_consumo import OffsetGrupoConsumo, OffsetGrupoResumen
from app.models.offset_grupo_filtro import OffsetGrupoFiltro
from app.models.offset_individual_consumo import OffsetIndividualConsumo, OffsetIndividualResumen
from app.models.offset_migracion_pendiente import OffsetMigracionPendiente
from app.models.producto import ProductoERP
from app.models.sell_in import SellInBonoItem, SellInBonoMarca
from app.models.sell_out import (
    SellOutCampana,
    SellOutCampanaGrupo,
    SellOutCampanaItem,
    SellOutConsumo,
    SellOutDirty,
    SellOutPrograma,
)
from app.models.tactical import Tactical
from app.scripts import fresh_start_sell_out as script
from app.services.sell_out import asignacion, triggers
from tests.services.sell._schema import throwaway_schema
from tests.services.sell_out import _world as w

pytestmark = pytest.mark.postgres

CONFIRMACION = "BORRAR TODO"
_STUBS = [
    "CREATE TABLE usuarios (id INTEGER PRIMARY KEY)",
    "INSERT INTO usuarios VALUES (7)",
    "CREATE TABLE pedidos_compra (id BIGINT PRIMARY KEY)",  # sell_in_bonos_marca.pedido_id's FK target
]
_TABLES = [
    ProductoERP.__table__,
    OffsetGrupo.__table__,
    OffsetGrupoFiltro.__table__,
    OffsetGanancia.__table__,
    OffsetGrupoConsumo.__table__,
    OffsetGrupoResumen.__table__,
    OffsetIndividualConsumo.__table__,
    OffsetIndividualResumen.__table__,
    OffsetMigracionPendiente.__table__,
    Tactical.__table__,
    SellOutPrograma.__table__,
    SellOutCampana.__table__,
    SellOutCampanaGrupo.__table__,
    SellOutCampanaItem.__table__,
    SellOutConsumo.__table__,
    SellOutDirty.__table__,
    Auditoria.__table__,
    SellInBonoMarca.__table__,
    SellInBonoItem.__table__,
]
# What one `_mundo` loads, per table the script reports.
ESPERADO = {
    "sell_out_campanas": 2,
    "sell_out_campana_grupos": 2,
    "sell_out_campana_items": 1,
    "sell_out_consumos": 1,
    "sell_out_dirty": 1,
    "sell_out_programas": 1,
    "auditoria": 5,
    "offset_grupo_consumo": 1,
    "offset_grupo_resumen": 1,
    "offset_individual_consumo": 1,
    "offset_individual_resumen": 1,
    "offsets_ganancia": 2,
    "offset_grupo_filtros": 2,
    "offset_grupos": 2,
    "offsets_migracion_pendientes": 1,
}
CEROS = dict.fromkeys(ESPERADO, 0)


def _install(engine: Engine) -> None:
    w._install(engine)
    with engine.begin() as conn:
        for statement in triggers.UPGRADE_SQL:
            if "CREATE TRIGGER" in statement and "ON ventas_" in statement:
                continue  # the sale tables are not part of this world
            conn.exec_driver_sql(statement)
        # Every row the queue ever takes, kept where no cascade reaches: the queue itself is emptied by the
        # campaigns' cascade, so only this log tells whether a delete enqueued anything.
        conn.exec_driver_sql("CREATE TABLE dirty_log (campana_id BIGINT)")
        conn.exec_driver_sql(
            "CREATE FUNCTION log_dirty() RETURNS TRIGGER AS $f$ BEGIN "
            "INSERT INTO dirty_log VALUES (NEW.campana_id); RETURN NEW; END $f$ LANGUAGE plpgsql"
        )
        conn.exec_driver_sql(
            "CREATE TRIGGER trg_dirty_log BEFORE INSERT ON sell_out_dirty FOR EACH ROW EXECUTE FUNCTION log_dirty()"
        )


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with throwaway_schema("fresh_start", _TABLES, _STUBS, after=_install) as engine:
        yield engine


@pytest.fixture(autouse=True)
def _clean(engine: Engine) -> Iterator[None]:
    yield
    with engine.begin() as conn:
        for table in (
            "sell_out_campanas",
            "sell_out_programas",
            "tacticals",
            "offset_grupo_consumo",
            "offset_grupo_resumen",
            "offset_individual_consumo",
            "offset_individual_resumen",
            "offsets_ganancia",
            "offset_grupos",
            "offsets_migracion_pendientes",
            "auditoria",
            "sell_in_bonos_marca",
            "dirty_log",
        ):
            conn.execute(text(f"DELETE FROM {table}"))


@pytest.fixture()
def correr(engine, monkeypatch, capsys):
    """Runs `main` on the test schema; returns (exit code, JSON summary or None, stderr)."""
    monkeypatch.setattr(database, "SessionLocal", sessionmaker(bind=engine))

    def run(*args: str):
        code = script.main(list(args))
        salida = capsys.readouterr()
        return code, (json.loads(salida.out) if salida.out.strip() else None), salida.err

    return run


def _id(engine: Engine, sql: str, **params) -> int:
    with engine.begin() as conn:
        return conn.execute(text(sql), params).scalar_one()


def _offset(engine: Engine, grupo_id=None) -> int:
    return _id(
        engine,
        "INSERT INTO offsets_ganancia (marca, grupo_id, tipo_offset, monto, moneda, descripcion, fecha_desde, "
        "aplica_ml, aplica_fuera, aplica_tienda_nube, usuario_id) VALUES ('TP-LINK', :g, 'monto_por_unidad', 3.5, "
        "'USD', 'Offset', '2026-09-01', true, true, true, 7) RETURNING id",
        g=grupo_id,
    )


def _audit(engine: Engine, tipo: str) -> None:
    w.execute(engine, "INSERT INTO auditoria (usuario_id, tipo_accion, fecha) VALUES (7, :t, '2026-11-01')", t=tipo)


def _bono(engine: Engine, offset_origen_id=None) -> int:
    return _id(
        engine,
        "INSERT INTO sell_in_bonos_marca (alcance, marca, tipo, porcentaje, moneda, fecha_desde, fecha_hasta, estado, "
        "usuario_id, offset_origen_id) VALUES ('marca', 'TP-LINK', 'porcentaje', 4, 'ARS', '2026-10-01', "
        "'2026-12-31', 'activa', 7, :o) RETURNING id",
        o=offset_origen_id,
    )


def _mundo(engine: Engine) -> dict:
    """The legacy world: a program, two campaigns (one in it, one over a hidden group), a grouped and a loose
    offset with their consumptions, a pending migration row, the sell-out audit rows and the rows that must stay
    (a sell-in bonus migrated from the loose offset and two unrelated audit rows)."""
    grupo = w.grupo(engine, [{"marca": "TP-LINK"}])
    oculto = w.grupo(engine, [{"item_id": 2964}])
    w.execute(engine, "UPDATE offset_grupos SET oculto = true WHERE id = :g", g=oculto)
    programa = _id(engine, "INSERT INTO sell_out_programas (nombre, usuario_id) VALUES ('Programa', 7) RETURNING id")
    campana = w.campana(engine, [grupo], programa_id=programa)
    otra = w.campana(engine, [oculto])
    w.monto_item(engine, otra, 2964, "5.00")
    w.execute(
        engine,
        "INSERT INTO sell_out_consumos (campana_id, canal, venta_ref, item_id, fecha_venta, unidades, monto) "
        "VALUES (:c, 'fuera', 1, 2964, '2026-11-02', 1, 10)",
        c=campana,
    )
    w.execute(engine, "INSERT INTO sell_out_dirty (campana_id) VALUES (:c)", c=campana)
    agrupado = _offset(engine, grupo)
    suelto = _offset(engine)
    w.execute(
        engine,
        "INSERT INTO offset_grupo_consumo (grupo_id, tipo_venta, fecha_venta, cantidad, offset_id, "
        "monto_offset_aplicado) VALUES (:g, 'ml', '2026-11-02', 1, :o, 10)",
        g=grupo,
        o=agrupado,
    )
    w.execute(engine, "INSERT INTO offset_grupo_resumen (grupo_id) VALUES (:g)", g=grupo)
    w.execute(
        engine,
        "INSERT INTO offset_individual_consumo (offset_id, tipo_venta, fecha_venta, cantidad, monto_offset_aplicado) "
        "VALUES (:o, 'ml', '2026-11-02', 1, 10)",
        o=suelto,
    )
    w.execute(engine, "INSERT INTO offset_individual_resumen (offset_id) VALUES (:o)", o=suelto)
    w.execute(engine, "INSERT INTO offsets_migracion_pendientes (offset_id, motivo) VALUES (:o, 'x')", o=suelto)
    for tipo in (
        "SELL_OUT_CAMPANA_CREADA",
        "SELL_OUT_CAMPANA_EDITADA",
        "SELL_OUT_CAMPANA_ANULADA",
        "SELL_OUT_CAMPANA_TC_DEFINIDO",
        "SELL_OUT_CAMPANA_PROGRAMA",
    ):
        _audit(engine, tipo)
    for tipo in ("SELL_IN_BONO_CREADO", "MODIFICAR_PRECIO_WEB"):
        _audit(engine, tipo)
    return {"bono": _bono(engine, offset_origen_id=suelto)}


def _conteo(engine: Engine) -> dict:
    with engine.connect() as conn:
        filas = {t: conn.execute(text(f"SELECT count(*) FROM {t}")).scalar_one() for t in ESPERADO if t != "auditoria"}
        filas["auditoria"] = conn.execute(
            text("SELECT count(*) FROM auditoria WHERE tipo_accion LIKE 'SELL_OUT_%'")
        ).scalar_one()
    return filas


def _quedan(engine: Engine, sql: str) -> list:
    with engine.connect() as conn:
        return [tuple(r) for r in conn.execute(text(sql))]


def test_dry_run_counts_every_table_and_deletes_nothing(engine, correr):
    _mundo(engine)

    code, summary, _ = correr()

    assert code == 0
    assert summary == {"dry_run": True, "antes": ESPERADO, "despues": ESPERADO}
    assert _conteo(engine) == ESPERADO


def test_apply_without_the_exact_confirmation_refuses_and_deletes_nothing(engine, correr):
    _mundo(engine)

    for args in (["--apply"], ["--apply", "--confirm", "borrar todo"], ["--apply", "--confirm", "SI"]):
        code, summary, err = correr(*args)
        assert code == 2
        assert summary is None
        assert 'Para borrar hay que confirmar con --confirm "BORRAR TODO"' in err
    assert _conteo(engine) == ESPERADO


def test_apply_deletes_the_legacy_world_and_keeps_sell_in_and_other_audit_rows(engine, correr):
    quedan = _mundo(engine)

    code, summary, _ = correr("--apply", "--confirm", CONFIRMACION)

    assert code == 0
    assert summary == {"dry_run": False, "antes": ESPERADO, "despues": CEROS}
    assert _conteo(engine) == CEROS
    # Sell in stays; its `offset_origen_id` (no FK) is left pointing at the deleted offset.
    assert _quedan(engine, "SELECT id FROM sell_in_bonos_marca") == [(quedan["bono"],)]
    assert sorted(_quedan(engine, "SELECT tipo_accion FROM auditoria")) == [
        ("MODIFICAR_PRECIO_WEB",),
        ("SELL_IN_BONO_CREADO",),
    ]
    assert _quedan(engine, "SELECT count(*) FROM productos_erp") == [(len(w.PRODUCTOS),)]


def test_deleting_filters_and_groups_after_the_campaigns_queues_nothing(engine, correr):
    _mundo(engine)
    w.execute(engine, "DELETE FROM dirty_log")

    code, _, _ = correr("--apply", "--confirm", CONFIRMACION)

    assert code == 0
    assert _quedan(engine, "SELECT campana_id FROM dirty_log") == []


def test_a_second_apply_deletes_nothing(engine, correr):
    _mundo(engine)
    assert correr("--apply", "--confirm", CONFIRMACION)[0] == 0

    code, summary, _ = correr("--apply", "--confirm", CONFIRMACION)

    assert code == 0
    assert summary == {"dry_run": False, "antes": CEROS, "despues": CEROS}


@pytest.mark.parametrize("vinculo", ["solo", "campana"])
def test_any_tactical_stops_the_run_and_deletes_nothing(engine, correr, vinculo):
    _mundo(engine)
    tactical = _id(
        engine,
        "INSERT INTO tacticals (tipo, nombre, marca, fecha_desde, fecha_hasta, moneda, usuario_id) "
        "VALUES ('sell_out', 'Tactical', 'TP-LINK', '2026-11-01', '2026-11-30', 'ARS', 7) RETURNING id",
    )
    if vinculo == "campana":
        grupo = w.grupo(engine, [{"item_id": 950}])
        w.execute(engine, "UPDATE offset_grupos SET oculto = true WHERE id = :g", g=grupo)
        w.campana(engine, [grupo], tactical_id=tactical, tactical_linea=1)
    antes = _conteo(engine)

    for args in ([], ["--apply", "--confirm", CONFIRMACION]):
        code, summary, err = correr(*args)
        assert code == 1
        assert summary is None
        assert "Hay tacticals cargados" in err
    assert _conteo(engine) == antes
    assert _quedan(engine, "SELECT count(*) FROM tacticals") == [(1,)]


def test_a_campaign_the_drain_holds_stops_the_run_within_the_lock_timeout(engine, correr, monkeypatch):
    _mundo(engine)
    monkeypatch.setattr(script, "LOCK_TIMEOUT", "200ms")
    campana = _quedan(engine, "SELECT min(id) FROM sell_out_campanas")[0][0]
    otra = create_engine(engine.url, connect_args={"options": f"-csearch_path={_schema(engine)}"})
    try:
        with otra.connect() as conn, conn.begin():
            conn.execute(text("SELECT pg_advisory_xact_lock(:ns, :c)"), {"ns": asignacion.LOCK_NAMESPACE, "c": campana})

            code, summary, err = correr("--apply", "--confirm", CONFIRMACION)

        assert code == 1
        assert summary is None
        assert "Otro proceso está usando campañas o tacticals" in err
        assert _conteo(engine) == ESPERADO
    finally:
        otra.dispose()


def test_a_campaign_being_loaded_meanwhile_stops_the_run(engine, correr, monkeypatch):
    """A campaign another transaction is still writing is not in the run's snapshot: the run must wait for it
    (and give up), never delete what it read and leave the new one behind."""
    _mundo(engine)
    monkeypatch.setattr(script, "LOCK_TIMEOUT", "200ms")
    otra = create_engine(engine.url, connect_args={"options": f"-csearch_path={_schema(engine)}"})
    try:
        with otra.connect() as conn, conn.begin():
            conn.execute(
                text(
                    "INSERT INTO sell_out_campanas (nombre, fecha_desde, fecha_hasta, tipo, monto_unit, moneda, "
                    "acumulable, monto_incluye_iva, estado, usuario_id) VALUES ('Nueva', '2026-11-01', '2026-11-30', "
                    "'por_unidad', 10, 'ARS', true, false, 'activa', 7)"
                )
            )

            code, summary, err = correr("--apply", "--confirm", CONFIRMACION)

        assert code == 1
        assert summary is None
        assert "Otro proceso está usando campañas o tacticals" in err
        assert _conteo(engine) == {**ESPERADO, "sell_out_campanas": 3}
    finally:
        otra.dispose()


def _schema(engine: Engine) -> str:
    with engine.connect() as conn:
        return conn.execute(text("SELECT current_schema()")).scalar_one()
