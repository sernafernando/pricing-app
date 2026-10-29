"""`migrar_offsets_a_sell_out` (sell-in-sell-out T15) against Postgres: each legacy
offset either becomes one sell-out campaign through the campaigns service or is
reported with its reason; every case checks the stored rows, the CSV line and
the JSON summary."""

from __future__ import annotations

import csv
import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Iterator

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import sessionmaker

from app.core import database
from app.models.auditoria import Auditoria
from app.models.offset_ganancia import OffsetGanancia
from app.models.offset_grupo import OffsetGrupo
from app.models.offset_grupo_filtro import OffsetGrupoFiltro
from app.models.offset_migracion_pendiente import OffsetMigracionPendiente
from app.models.producto import ProductoERP
from app.models.sell_in import SellInBonoMarca
from app.models.sell_out import SellOutCampana, SellOutCampanaGrupo, SellOutCampanaItem, SellOutDirty
from app.scripts import migrar_offsets_a_sell_out as script
from tests.services.sell._schema import throwaway_schema
from tests.services.sell_out import _world as w

pytestmark = pytest.mark.postgres

HOY = "2026-10-22"
COLUMNAS = [
    "offset_id",
    "tipo",
    "descripcion",
    "alcance",
    "valor",
    "moneda",
    "desde",
    "hasta",
    "resultado",
    "campana_id",
    "motivo",
    "avisos",
]
VENCIDO = "Vencido el {}: migrarlo cambia las cifras históricas de sell out en Métricas ML"
_STUBS = [
    "CREATE TABLE usuarios (id INTEGER PRIMARY KEY)",
    "INSERT INTO usuarios VALUES (7), (8)",
    "CREATE TABLE pedidos_compra (id BIGINT PRIMARY KEY)",  # sell_in_bonos_marca.pedido_id's FK target
]
_TABLES = [
    ProductoERP.__table__,
    OffsetGrupo.__table__,
    OffsetGrupoFiltro.__table__,
    OffsetGanancia.__table__,
    OffsetMigracionPendiente.__table__,
    SellOutCampana.__table__,
    SellOutCampanaGrupo.__table__,
    SellOutCampanaItem.__table__,
    SellOutDirty.__table__,
    Auditoria.__table__,
    SellInBonoMarca.__table__,
]
# Every table the script could write, for the dry-run check.
_ESCRITAS = (
    "offset_grupos",
    "offset_grupo_filtros",
    "sell_out_campanas",
    "sell_out_campana_grupos",
    "sell_out_campana_items",
    "sell_out_dirty",
    "auditoria",
    "offsets_migracion_pendientes",
)


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with throwaway_schema("migrar_offsets", _TABLES, _STUBS, after=w._install) as engine:
        yield engine


@pytest.fixture(autouse=True)
def _clean(engine: Engine) -> Iterator[None]:
    yield
    with engine.begin() as conn:
        for table in (
            "sell_out_campanas",
            "offsets_ganancia",
            "offset_grupos",
            "auditoria",
            "sell_out_dirty",
            "offsets_migracion_pendientes",
            "sell_in_bonos_marca",
        ):
            conn.execute(text(f"DELETE FROM {table}"))


@pytest.fixture()
def correr(engine, monkeypatch, capsys, tmp_path):
    """Runs `main` on the test schema; returns (exit code, JSON summary, {offset_id: CSV row})."""
    monkeypatch.setattr(database, "SessionLocal", sessionmaker(bind=engine))

    def run(*args: str):
        path = tmp_path / "reporte.csv"
        code = script.main(["--csv", str(path), "--hoy", HOY, *args])
        salida = capsys.readouterr()
        run.err = salida.err
        summary = json.loads(salida.out)
        raw = Path(path).read_bytes()
        assert raw.startswith(b"\xef\xbb\xbf")  # BOM: Excel reads the accents as UTF-8
        lineas = list(csv.reader(raw.decode("utf-8-sig").splitlines(), delimiter=";"))
        assert lineas[0] == COLUMNAS
        return code, summary, {int(fila[0]): dict(zip(COLUMNAS, fila)) for fila in lineas[1:]}

    return run


def _offset(engine: Engine, **values) -> int:
    row = {
        "item_id": None,
        "marca": None,
        "categoria": None,
        "subcategoria_id": None,
        "grupo_id": None,
        "tipo_offset": "monto_por_unidad",
        "monto": 3.5,
        "porcentaje": None,
        "moneda": "USD",
        "tipo_cambio": None,
        "descripcion": "SP Epson",
        "fecha_desde": date(2026, 9, 1),
        "fecha_hasta": date(2026, 12, 15),
        "max_unidades": None,
        "max_monto_usd": None,
        "aplica_ml": True,
        "aplica_fuera": True,
        "aplica_tienda_nube": True,
        "usuario_id": 7,
        **values,
    }
    with engine.begin() as conn:
        return conn.execute(
            text(
                f"INSERT INTO offsets_ganancia ({', '.join(row)}) VALUES ({', '.join(':' + k for k in row)}) "
                "RETURNING id"
            ),
            row,
        ).scalar_one()


def _campanas(engine: Engine) -> list:
    with engine.connect() as conn:
        return conn.execute(text("SELECT * FROM sell_out_campanas ORDER BY id")).mappings().all()


def _filtros(engine: Engine, grupo_id: int) -> list[tuple]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT marca, categoria, subcategoria_id, item_id FROM offset_grupo_filtros "
                "WHERE grupo_id = :g ORDER BY id"
            ),
            {"g": grupo_id},
        )
        return [tuple(r) for r in rows]


def _grupos_de(engine: Engine, campana_id: int) -> list[tuple]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT g.id, g.nombre FROM sell_out_campana_grupos cg JOIN offset_grupos g ON g.id = cg.grupo_id "
                "WHERE cg.campana_id = :c ORDER BY cg.id"
            ),
            {"c": campana_id},
        )
        return [tuple(r) for r in rows]


def _count(engine: Engine, table: str) -> int:
    with engine.connect() as conn:
        return conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one()


def _no_migrado(engine, correr, motivo: str, **values) -> None:
    offset_id = _offset(engine, **values)
    code, summary, filas = correr("--apply")
    assert code == 0
    assert (filas[offset_id]["resultado"], filas[offset_id]["motivo"], filas[offset_id]["campana_id"]) == (
        "no migrado",
        motivo,
        "",
    )
    assert _campanas(engine) == [] and _count(engine, "offset_grupos") == 0
    assert (summary["no_migrados"], summary["migrados"], summary["campana_ids"]) == (1, 0, [])


# ── Mapping ──────────────────────────────────────────────────────────


def test_an_active_per_unit_usd_offset_becomes_one_campaign_through_the_service(engine, correr) -> None:
    offset_id = _offset(engine, item_id=2964, max_unidades=500, max_monto_usd=1000, tipo_cambio=1400)

    code, summary, filas = correr("--apply")

    assert code == 0
    [c] = _campanas(engine)
    assert c["offset_origen_id"] == offset_id
    assert (c["nombre"], c["tipo"], c["monto_unit"], c["moneda"], c["tc_modo"], c["tipo_cambio"]) == (
        "SP Epson",
        "por_unidad",
        Decimal("3.50"),
        "USD",
        "al_cobro",  # the service's default for USD
        None,
    )
    assert f"Migrado del offset #{offset_id}" in c["descripcion"]
    assert (c["fecha_desde"], c["fecha_hasta"]) == (date(2026, 9, 1), date(2026, 12, 15))
    assert (c["tope_unidades"], c["tope_monto"], c["acumulable"], c["usuario_id"]) == (500, Decimal("1000.00"), True, 7)
    [(grupo_id, nombre)] = _grupos_de(engine, c["id"])
    assert nombre == f"Offset #{offset_id}: SP Epson"
    assert _filtros(engine, grupo_id) == [(None, None, None, 2964)]
    with engine.connect() as conn:  # audited and queued like any campaign the service loads
        audit = conn.execute(text("SELECT valores_nuevos FROM auditoria")).scalar_one()
        assert conn.execute(text("SELECT campana_id FROM sell_out_dirty")).scalar_one() == c["id"]
    assert (audit["campana_id"], audit["offset_origen_id"]) == (c["id"], offset_id)

    assert filas[offset_id] == {
        "offset_id": str(offset_id),
        "tipo": "monto_por_unidad",
        "descripcion": "SP Epson",
        "alcance": "producto 2964",
        "valor": "3,50",
        "moneda": "USD",
        "desde": "2026-09-01",
        "hasta": "2026-12-15",
        "resultado": "migrado",
        "campana_id": str(c["id"]),
        "motivo": "",
        "avisos": "El tipo de cambio del offset (1400,00) no se migró: la campaña queda con tipo de cambio al cobro",
    }
    assert summary == {
        "dry_run": False,
        "offsets": 1,
        "migrados": 1,
        "migrarian": 0,
        "ya_migrados": 0,
        "no_migrados": 0,
        "con_error": [],
        "campana_ids": [c["id"]],
        "pendientes": 0,
        "vencidos_migrados": [],
    }


def test_an_offset_without_a_group_gets_a_new_group_with_one_filter_per_scope_field(engine, correr) -> None:
    # The legacy offset reaches a product matching ANY of its fields; a group matches ANY of its filter rows.
    offset_id = _offset(engine, marca="TP-LINK", categoria="Routers", subcategoria_id=12, item_id=950)

    _, _, filas = correr("--apply")

    [c] = _campanas(engine)
    [(grupo_id, _)] = _grupos_de(engine, c["id"])
    assert _filtros(engine, grupo_id) == [
        ("TP-LINK", None, None, None),
        (None, "Routers", None, None),
        (None, None, 12, None),
        (None, None, None, 950),
    ]
    assert filas[offset_id]["alcance"] == "marca TP-LINK o categoría Routers o subcategoría 12 o producto 950"


# B1: a campaign in pesos holds no USD cap and a campaign covers every channel. Migrating such an offset (active or
# expired) would credit beyond what the legacy offset credited, so it goes to the review table instead.
_VENCIDO = {"fecha_desde": date(2026, 3, 1), "fecha_hasta": date(2026, 6, 30)}
_IRREPRESENTABLES = {
    "tope_usd_en_pesos": (
        {"marca": "MERCUSYS", "moneda": "ARS", "monto": 50, "max_unidades": 10, "max_monto_usd": 300},
        "El tope en USD (300,00) no se puede guardar en una campaña en pesos",
    ),
    "canales": (
        {"item_id": 2964, "aplica_fuera": False, "aplica_tienda_nube": False},
        "No aplicaba a: fuera de ML, Tienda Nube; una campaña aplica a todos los canales",
    ),
    "ambos": (
        {"item_id": 950, "moneda": "ARS", "monto": 50, "max_monto_usd": 100, "aplica_ml": False},
        "El tope en USD (100,00) no se puede guardar en una campaña en pesos | "
        "No aplicaba a: ML; una campaña aplica a todos los canales",
    ),
}


@pytest.mark.parametrize("vencido", [False, True], ids=["activo", "vencido"])
@pytest.mark.parametrize("caso", list(_IRREPRESENTABLES))
def test_an_offset_a_campaign_cannot_represent_goes_to_review_not_to_a_wider_campaign(
    engine, correr, caso, vencido
) -> None:
    valores, motivo = _IRREPRESENTABLES[caso]
    otro = _offset(engine, item_id=2270)  # an unrelated offset still migrates

    offset_id = _offset(engine, **valores, **(_VENCIDO if vencido else {}))
    code, summary, filas = correr("--apply")

    assert code == 0
    assert (filas[offset_id]["resultado"], filas[offset_id]["motivo"], filas[offset_id]["campana_id"]) == (
        "no migrado",
        motivo,
        "",
    )
    assert filas[offset_id]["avisos"] == ""
    [c] = _campanas(engine)
    assert c["offset_origen_id"] == otro
    assert _count(engine, "offset_grupos") == 1  # only the unrelated offset's
    pendientes = _pendientes(engine)
    assert list(pendientes) == [offset_id]
    assert (pendientes[offset_id]["motivo"], pendientes[offset_id]["avisos"]) == (motivo, None)
    assert (summary["migrados"], summary["no_migrados"], summary["pendientes"]) == (1, 1, 1)
    assert (summary["campana_ids"], summary["vencidos_migrados"], summary["con_error"]) == ([c["id"]], [], [])

    # The dry run says the same.
    code, summary, filas = correr()
    assert code == 0
    assert (filas[offset_id]["resultado"], filas[offset_id]["motivo"]) == ("no migrado", motivo)
    assert summary["pendientes"] == 1


@pytest.mark.parametrize("default,esperado", [(None, date(2026, 12, 31)), ("2027-03-31", date(2027, 3, 31))])
def test_an_open_ended_offset_ends_on_the_default_date_and_warns(engine, correr, default, esperado) -> None:
    offset_id = _offset(engine, item_id=2964, fecha_hasta=None)

    _, summary, filas = correr("--apply", *(["--fecha-hasta-default", default] if default else []))

    [c] = _campanas(engine)
    assert c["fecha_hasta"] == esperado
    assert filas[offset_id]["hasta"] == ""
    assert filas[offset_id]["avisos"] == f"Sin fecha hasta: se usó {esperado.isoformat()}, revisar"
    assert summary["migrados"] == 1


def test_an_offset_ending_today_is_still_active(engine, correr) -> None:
    offset_id = _offset(engine, item_id=2964, fecha_hasta=date(2026, 10, 22))

    _, _, filas = correr("--apply")

    assert filas[offset_id]["resultado"] == "migrado"
    assert _campanas(engine)[0]["fecha_hasta"] == date(2026, 10, 22)


# ── Not migrated ─────────────────────────────────────────────────────


def test_a_fixed_amount_offset_is_not_migrated(engine, correr) -> None:
    _no_migrado(
        engine,
        correr,
        "Monto fijo: no tiene equivalente en una campaña por unidad",
        marca="EPSON",
        tipo_offset="monto_fijo",
        monto=10000,
    )


def test_a_negative_amount_is_not_migrated(engine, correr) -> None:
    _no_migrado(engine, correr, "Monto negativo o cero", item_id=2964, monto=-2)


def test_an_offset_without_scope_is_not_migrated(engine, correr) -> None:
    _no_migrado(engine, correr, "Sin alcance: no indica marca, categoría, subcategoría, producto ni grupo")


def test_an_offset_without_user_needs_the_fallback_user(engine, correr) -> None:
    _no_migrado(engine, correr, "Sin usuario: indicar --usuario-id", item_id=2964, usuario_id=None)

    _, summary, filas = correr("--apply", "--usuario-id", "8")

    [c] = _campanas(engine)
    assert c["usuario_id"] == 8
    assert (summary["migrados"], next(iter(filas.values()))["resultado"]) == (1, "migrado")


def test_a_validation_error_reports_that_offset_and_the_others_continue(engine, correr) -> None:
    falla = _offset(engine, item_id=2964, fecha_desde=date(2027, 2, 1), fecha_hasta=None)
    sigue = _offset(engine, item_id=950)

    code, summary, filas = correr("--apply")

    assert code == 1
    assert (filas[falla]["resultado"], filas[falla]["motivo"]) == (
        "no migrado",
        "La fecha hasta no puede ser anterior a la fecha desde",
    )
    [c] = _campanas(engine)
    assert (c["offset_origen_id"], filas[sigue]["resultado"]) == (sigue, "migrado")
    assert _count(engine, "offset_grupos") == 1  # the failing offset's new group was rolled back with it
    assert (summary["con_error"], summary["no_migrados"], summary["migrados"]) == ([falla], 1, 1)


def test_a_value_the_campaign_cannot_hold_is_reported_as_an_error(engine, correr) -> None:
    offset_id = _offset(engine, item_id=2964, monto=1.125)  # monto_unit keeps 2 decimals; never rounded

    code, summary, filas = correr("--apply")

    assert code == 1
    assert (filas[offset_id]["resultado"], filas[offset_id]["motivo"]) == (
        "no migrado",
        "Valor no válido en: monto_unit",
    )
    assert _campanas(engine) == []
    assert (summary["con_error"], summary["no_migrados"]) == ([offset_id], 1)


# ── Re-run and dry run ───────────────────────────────────────────────


def test_a_rerun_reports_the_migrated_offsets_and_creates_nothing(engine, correr) -> None:
    offset_id = _offset(engine, item_id=2964)
    correr("--apply")
    [c] = _campanas(engine)

    code, summary, filas = correr("--apply")

    assert code == 0
    assert _campanas(engine) == [c]
    assert _count(engine, "offset_grupos") == 1
    assert (filas[offset_id]["resultado"], filas[offset_id]["campana_id"]) == ("ya migrado", str(c["id"]))
    assert (summary["ya_migrados"], summary["migrados"], summary["campana_ids"]) == (1, 0, [])


def test_the_default_dry_run_writes_nothing_and_reports_what_it_would_migrate(engine, correr) -> None:
    por_producto = _offset(engine, item_id=2964)
    sin_fin = _offset(engine, marca="TP-LINK", fecha_hasta=None)
    vencido = _offset(engine, item_id=2964, fecha_desde=date(2026, 1, 1), fecha_hasta=date(2026, 1, 31))
    antes = {table: _count(engine, table) for table in _ESCRITAS}

    code, summary, filas = correr()

    assert {table: _count(engine, table) for table in _ESCRITAS} == antes
    assert code == 0
    assert [filas[i]["resultado"] for i in (por_producto, sin_fin, vencido)] == ["migraría (dry-run)"] * 3
    assert filas[sin_fin]["avisos"] == "Sin fecha hasta: se usó 2026-12-31, revisar"
    assert filas[vencido]["avisos"] == VENCIDO.format("2026-01-31")
    assert (summary["dry_run"], summary["migrarian"], summary["no_migrados"], summary["campana_ids"]) == (
        True,
        3,
        0,
        [],
    )
    assert summary["vencidos_migrados"] == [vencido]
    assert correr.err.splitlines()[-1] == (
        f"AVISO: 1 offset(s) vencido(s) se migrarían ({vencido}): cambian las cifras históricas de sell out "
        "en Métricas ML"
    )


def test_the_csv_path_is_required() -> None:
    with pytest.raises(SystemExit) as caught:
        script.main([])
    assert caught.value.code == 2


def test_an_unwritable_report_path_stops_before_migrating_anything(engine, monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(database, "SessionLocal", sessionmaker(bind=engine))
    _offset(engine, item_id=2964)

    with pytest.raises(OSError):
        script.main(["--csv", str(tmp_path / "no-existe" / "reporte.csv"), "--hoy", HOY, "--apply"])

    assert _campanas(engine) == [] and _count(engine, "offset_grupos") == 0


def test_a_database_error_on_one_offset_is_reported_and_the_others_still_migrate(engine, correr, monkeypatch) -> None:
    falla = _offset(engine, item_id=2964)
    sana = _offset(engine, item_id=950)
    real = script._nuevo_grupo

    def nuevo_grupo(db, offset, usuario_id):
        if offset.id == falla:
            db.execute(text("SELECT * FROM tabla_que_no_existe"))
        return real(db, offset, usuario_id)

    monkeypatch.setattr(script, "_nuevo_grupo", nuevo_grupo)

    code, summary, filas = correr("--apply")

    assert code == 1
    assert (filas[falla]["resultado"], filas[falla]["motivo"].split(":")[0]) == ("no migrado", "Error de base de datos")
    assert filas[sana]["resultado"] == "migrado"
    assert [c["offset_origen_id"] for c in _campanas(engine)] == [sana]
    assert _count(engine, "offset_grupos") == 1  # the failed offset's group rolled back
    assert summary["con_error"] == [falla]


def test_a_validation_error_without_a_field_names_the_campaign() -> None:
    from pydantic import BaseModel, ValidationError, model_validator

    class Modelo(BaseModel):
        @model_validator(mode="after")
        def falla(self):
            raise ValueError("fechas cruzadas")

    with pytest.raises(ValidationError) as exc:
        Modelo()
    assert script._campos(exc.value) == "campaña"


def test_the_dry_run_reports_an_offset_that_validation_refuses_and_exits_1(engine, correr) -> None:
    rechazado = _offset(engine, item_id=2964, fecha_desde=date(2027, 2, 1), fecha_hasta=None)
    antes = {table: _count(engine, table) for table in _ESCRITAS}

    code, summary, filas = correr()

    assert {table: _count(engine, table) for table in _ESCRITAS} == antes
    assert (code, filas[rechazado]["resultado"], summary["con_error"]) == (1, "no migrado", [rechazado])


def test_a_database_error_reading_one_offset_is_reported_and_the_others_still_migrate(
    engine, correr, monkeypatch
) -> None:
    falla = _offset(engine, item_id=2964)
    sana = _offset(engine, item_id=950)
    real = script._ya_migrada

    def ya_migrada(db, offset_id):
        if offset_id == falla:
            db.execute(text("SELECT * FROM tabla_que_no_existe"))
        return real(db, offset_id)

    monkeypatch.setattr(script, "_ya_migrada", ya_migrada)

    code, summary, filas = correr("--apply")

    assert code == 1
    assert (filas[falla]["resultado"], filas[falla]["motivo"].split(":")[0]) == ("no migrado", "Error de base de datos")
    assert [c["offset_origen_id"] for c in _campanas(engine)] == [sana]
    assert summary["con_error"] == [falla]


def test_an_offset_deleted_during_the_run_is_reported_and_the_run_goes_on(engine, correr, monkeypatch) -> None:
    primero = _offset(engine, item_id=2964)
    borrado = _offset(engine, item_id=950)
    real = script._ya_migrada

    def ya_migrada(db, offset_id):
        if offset_id == primero:
            with engine.begin() as conn:
                conn.execute(text("DELETE FROM offsets_ganancia WHERE id = :i"), {"i": borrado})
        return real(db, offset_id)

    monkeypatch.setattr(script, "_ya_migrada", ya_migrada)

    code, summary, filas = correr("--apply")

    assert code == 0
    assert (filas[borrado]["resultado"], filas[borrado]["motivo"]) == ("no migrado", "El offset ya no existe")
    assert [c["offset_origen_id"] for c in _campanas(engine)] == [primero]


# ── Review table (T22a) ──────────────────────────────────────────────


def _pendientes(engine: Engine) -> dict:
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT * FROM offsets_migracion_pendientes ORDER BY offset_id")).mappings().all()
    return {r["offset_id"]: dict(r) for r in rows}


def test_apply_stores_each_offset_it_could_not_migrate_with_its_full_detail(engine, correr) -> None:
    fijo = _offset(
        engine,
        marca="EPSON",
        tipo_offset="monto_fijo",
        monto=10000.5,
        moneda="ARS",
        tipo_cambio=1400,
        descripcion="Bono anual",
        fecha_hasta=None,
        max_unidades=50,
        max_monto_usd=900,
        aplica_fuera=False,
    )
    migrado = _offset(engine, item_id=2964)

    code, summary, filas = correr("--apply")

    assert code == 0
    pendientes = _pendientes(engine)
    assert list(pendientes) == [fijo]
    fila = pendientes[fijo]
    assert {k: fila[k] for k in fila if k not in ("id", "registrado_en")} == {
        "offset_id": fijo,
        "tipo_offset": "monto_fijo",
        "descripcion": "Bono anual",
        "marca": "EPSON",
        "categoria": None,
        "subcategoria_id": None,
        "item_id": None,
        "grupo_id": None,
        "monto": 10000.5,
        "porcentaje": None,
        "moneda": "ARS",
        "tipo_cambio": 1400.0,
        "fecha_desde": date(2026, 9, 1),
        "fecha_hasta": None,
        "max_unidades": 50,
        "max_monto_usd": 900.0,
        "aplica_ml": True,
        "aplica_fuera": False,
        "aplica_tienda_nube": True,
        "usuario_id": 7,
        "motivo": "Monto fijo: no tiene equivalente en una campaña por unidad",
        "avisos": None,
    }
    assert fila["registrado_en"] is not None
    assert filas[fijo]["motivo"] == fila["motivo"]
    assert filas[migrado]["resultado"] == "migrado"
    assert summary["pendientes"] == 1


def test_a_validation_error_is_stored_for_review_too(engine, correr) -> None:
    offset_id = _offset(engine, item_id=2964, monto=1e20)

    code, _, filas = correr("--apply")

    assert code == 1
    assert _pendientes(engine)[offset_id]["motivo"] == filas[offset_id]["motivo"]


def test_a_rerun_updates_the_review_row_instead_of_adding_another(engine, correr) -> None:
    offset_id = _offset(engine, marca="EPSON", tipo_offset="monto_fijo", monto=100)
    correr("--apply")
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE offsets_ganancia SET monto = -1, tipo_offset = 'monto_por_unidad' WHERE id = :i"),
            {"i": offset_id},
        )

    correr("--apply")

    pendientes = _pendientes(engine)
    assert list(pendientes) == [offset_id]
    assert (pendientes[offset_id]["motivo"], pendientes[offset_id]["monto"]) == ("Monto negativo o cero", -1.0)


def test_an_offset_that_migrates_later_leaves_the_review_table(engine, correr) -> None:
    offset_id = _offset(engine, item_id=2964, monto=0)
    correr("--apply")
    assert list(_pendientes(engine)) == [offset_id]
    with engine.begin() as conn:
        conn.execute(text("UPDATE offsets_ganancia SET monto = 2 WHERE id = :i"), {"i": offset_id})

    _, summary, filas = correr("--apply")

    assert filas[offset_id]["resultado"] == "migrado"
    assert _pendientes(engine) == {}
    assert summary["pendientes"] == 0


def test_the_dry_run_leaves_an_existing_review_table_as_it_was(engine, correr) -> None:
    offset_id = _offset(engine, marca="EPSON", tipo_offset="monto_fijo", monto=100)
    correr("--apply")
    antes = _pendientes(engine)
    with engine.begin() as conn:
        conn.execute(text("UPDATE offsets_ganancia SET monto = 200 WHERE id = :i"), {"i": offset_id})

    _, summary, _ = correr()

    assert _pendientes(engine) == antes
    assert summary["pendientes"] == 1  # what --apply would store


def test_a_failure_keeping_the_review_row_keeps_the_reason_and_fails_the_run(engine, correr, monkeypatch) -> None:
    falla = _offset(engine, marca="EPSON", tipo_offset="monto_fijo", monto=100)
    sana = _offset(engine, marca="LENOVO", tipo_offset="monto_fijo", monto=200)
    real = script._guardar_pendiente

    def guardar(db, offset, motivo, avisos):
        if offset.id == falla:
            db.execute(text("SELECT * FROM tabla_que_no_existe"))
        return real(db, offset, motivo, avisos)

    monkeypatch.setattr(script, "_guardar_pendiente", guardar)

    code, summary, filas = correr("--apply")

    assert code == 1
    assert filas[falla]["motivo"] == "Monto fijo: no tiene equivalente en una campaña por unidad"
    assert "No se actualizó la tabla de revisión" in filas[falla]["avisos"]
    assert list(_pendientes(engine)) == [sana]
    assert (summary["pendientes"], summary["con_error"]) == (1, [falla])


# ── Expired offsets (T22d) ───────────────────────────────────────────


def test_an_expired_offset_migrates_with_its_real_dates_and_a_warning(engine, correr, capsys) -> None:
    # Owner: "migrar todo". It changes the historical sell-out figures, so the CSV and the summary say so.
    offset_id = _offset(engine, item_id=2964, fecha_desde=date(2026, 3, 1), fecha_hasta=date(2026, 10, 21))

    code, summary, filas = correr("--apply")

    assert code == 0
    [c] = _campanas(engine)
    assert (c["offset_origen_id"], c["fecha_desde"], c["fecha_hasta"]) == (
        offset_id,
        date(2026, 3, 1),
        date(2026, 10, 21),
    )
    assert (filas[offset_id]["resultado"], filas[offset_id]["campana_id"]) == ("migrado", str(c["id"]))
    assert filas[offset_id]["avisos"] == VENCIDO.format("2026-10-21")
    assert (summary["migrados"], summary["vencidos_migrados"], summary["pendientes"]) == (1, [offset_id], 0)
    assert _pendientes(engine) == {}
    assert correr.err.splitlines()[-1] == (
        f"AVISO: 1 offset(s) vencido(s) migrado(s) ({offset_id}): cambian las cifras históricas de sell out "
        "en Métricas ML"
    )


def test_an_expired_offset_that_is_not_migrated_is_not_listed_as_migrated_expired(engine, correr) -> None:
    offset_id = _offset(engine, item_id=2964, monto=0, fecha_desde=date(2026, 1, 1), fecha_hasta=date(2026, 1, 31))

    _, summary, filas = correr("--apply")

    assert (filas[offset_id]["resultado"], filas[offset_id]["motivo"]) == ("no migrado", "Monto negativo o cero")
    assert summary["vencidos_migrados"] == []
    assert "AVISO" not in correr.err


# ── Grouped offsets (T22d) ───────────────────────────────────────────


def _items_de(engine: Engine, campana_id: int) -> list[tuple]:
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT item_id, monto_unit FROM sell_out_campana_items WHERE campana_id = :c ORDER BY item_id"),
            {"c": campana_id},
        )
        return [tuple(r) for r in rows]


def _grupo_tplink(engine: Engine, **ref) -> tuple[int, list[int]]:
    """A TP-LINK group (reaches 2964 and 2270) with a reference offset without product and two per-product ones;
    the cap comes from the first offset by id that has one (the second), like the legacy group summary."""
    grupo_id = w.grupo(engine, [{"marca": "TP-LINK"}])
    base = {"grupo_id": grupo_id, "descripcion": "Grupo TP-LINK"}
    ids = [
        _offset(engine, **base, monto=2, fecha_desde=date(2026, 9, 1), fecha_hasta=date(2026, 11, 30), **ref),
        _offset(
            engine,
            **base,
            item_id=2964,
            monto=3.5,
            max_unidades=100,
            max_monto_usd=500,
            fecha_desde=date(2026, 9, 1),
            fecha_hasta=date(2026, 11, 30),
        ),
        _offset(engine, **base, item_id=2270, monto=4, max_unidades=999, fecha_hasta=date(2026, 11, 30)),
    ]
    return grupo_id, ids


def test_a_group_becomes_one_campaign_linked_to_its_group_with_per_product_amounts(engine, correr) -> None:
    grupo_id, (ref, o2, o3) = _grupo_tplink(engine)

    code, summary, filas = correr("--apply")

    assert code == 0
    [c] = _campanas(engine)
    assert c["offset_origen_id"] == ref
    assert (c["tipo"], c["monto_unit"], c["moneda"]) == ("por_unidad", Decimal("2.00"), "USD")
    assert (c["tope_unidades"], c["tope_monto"]) == (100, Decimal("500.00"))
    assert (c["fecha_desde"], c["fecha_hasta"]) == (date(2026, 9, 1), date(2026, 11, 30))
    assert [g for g, _ in _grupos_de(engine, c["id"])] == [grupo_id]  # the existing group, no new one
    assert _count(engine, "offset_grupos") == 1
    assert _filtros(engine, grupo_id) == [("TP-LINK", None, None, None)]
    assert _items_de(engine, c["id"]) == [(2270, Decimal("4.00")), (2964, Decimal("3.50"))]
    assert {i: (filas[i]["resultado"], filas[i]["campana_id"]) for i in (ref, o2, o3)} == dict.fromkeys(
        (ref, o2, o3), ("migrado", str(c["id"]))
    )
    assert filas[ref]["avisos"] == ""
    otro = f"migrado en la campaña #{c['id']} del grupo #{grupo_id}"
    assert (filas[o2]["avisos"], filas[o3]["avisos"]) == (otro, otro)
    assert filas[o2]["alcance"] == f"grupo #{grupo_id}"
    assert (summary["migrados"], summary["campana_ids"], summary["no_migrados"]) == (3, [c["id"]], 0)
    assert (summary["pendientes"], summary["vencidos_migrados"], _pendientes(engine)) == (0, [], {})


def test_a_group_reference_with_a_product_also_gets_its_own_amount(engine, correr) -> None:
    grupo_id = w.grupo(engine, [{"marca": "TP-LINK"}])
    ref = _offset(engine, grupo_id=grupo_id, item_id=2964, monto=3, max_unidades=10)
    otro = _offset(engine, grupo_id=grupo_id, item_id=2270, monto=5)

    _, summary, filas = correr("--apply")

    [c] = _campanas(engine)
    assert (c["offset_origen_id"], c["monto_unit"], c["tope_unidades"]) == (ref, Decimal("3.00"), 10)
    assert _items_de(engine, c["id"]) == [(2270, Decimal("5.00")), (2964, Decimal("3.00"))]
    assert filas[otro]["resultado"] == "migrado" and summary["migrados"] == 2


def test_a_group_without_end_date_ends_on_the_default_with_a_warning(engine, correr) -> None:
    grupo_id = w.grupo(engine, [{"marca": "TP-LINK"}])
    ref = _offset(engine, grupo_id=grupo_id, fecha_hasta=None, moneda="ARS", monto=100, max_unidades=50)
    otro = _offset(engine, grupo_id=grupo_id, item_id=2964, moneda="ARS", monto=150, fecha_hasta=None)

    _, _, filas = correr("--apply")

    [c] = _campanas(engine)
    assert (c["fecha_hasta"], c["moneda"], c["tope_unidades"]) == (date(2026, 12, 31), "ARS", 50)
    assert filas[ref]["avisos"] == "Sin fecha hasta: se usó 2026-12-31, revisar"
    assert filas[otro]["avisos"].startswith(f"migrado en la campaña #{c['id']} del grupo #{grupo_id}")


def test_a_group_rerun_reports_every_offset_as_already_migrated(engine, correr) -> None:
    _, ids = _grupo_tplink(engine)
    correr("--apply")
    [c] = _campanas(engine)

    code, summary, filas = correr("--apply")

    assert code == 0
    assert _campanas(engine) == [c]
    assert {i: (filas[i]["resultado"], filas[i]["campana_id"]) for i in ids} == dict.fromkeys(
        ids, ("ya migrado", str(c["id"]))
    )
    assert (summary["ya_migrados"], summary["migrados"], summary["campana_ids"]) == (3, 0, [])


def test_an_offset_added_to_a_migrated_group_goes_to_review_not_already_migrated(engine, correr) -> None:
    grupo_id, ids = _grupo_tplink(engine)
    correr("--apply")
    [c] = _campanas(engine)
    nuevo = _offset(engine, grupo_id=grupo_id, monto=9, fecha_hasta=date(2026, 11, 30))

    code, summary, filas = correr("--apply")

    assert code == 0
    assert _campanas(engine) == [c]
    assert {i: filas[i]["resultado"] for i in ids} == dict.fromkeys(ids, "ya migrado")
    motivo = (
        f"Grupo #{grupo_id}: el offset se agregó después de migrar el grupo a la campaña #{c['id']}; revisar a mano"
    )
    assert (filas[nuevo]["resultado"], filas[nuevo]["motivo"]) == ("no migrado", motivo)
    assert _pendientes(engine)[nuevo]["motivo"] == motivo
    assert (summary["ya_migrados"], summary["pendientes"]) == (3, 1)


def test_a_group_with_more_products_than_a_campaign_holds_says_so(engine, correr) -> None:
    grupo_id = w.grupo(engine, [{"marca": "TP-LINK"}])
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO productos_erp (item_id, codigo, descripcion) VALUES (:i, :c, 'P')"),
            [{"i": 10000 + i, "c": f"X{i}"} for i in range(501)],
        )
    ids = [_offset(engine, grupo_id=grupo_id)] + [
        _offset(engine, grupo_id=grupo_id, item_id=10000 + i) for i in range(501)
    ]

    _, summary, filas = correr("--apply")

    motivo = f"Grupo #{grupo_id}: tiene 501 productos con monto propio y una campaña admite hasta 500; revisar a mano"
    assert {filas[i]["motivo"] for i in ids} == {motivo}
    assert _campanas(engine) == [] and summary["pendientes"] == 502


def test_a_rerun_over_a_group_whose_campaign_was_voided_says_so(engine, correr) -> None:
    _, ids = _grupo_tplink(engine)
    correr("--apply")
    [c] = _campanas(engine)
    with engine.begin() as conn:
        conn.execute(text("UPDATE sell_out_campanas SET estado = 'anulada' WHERE id = :c"), {"c": c["id"]})

    _, _, filas = correr("--apply")

    assert {filas[i]["resultado"] for i in ids} == {"ya migrado"}
    assert all(f"La campaña #{c['id']} está anulada" in filas[i]["avisos"] for i in ids)


def test_a_group_dry_run_writes_nothing_and_reports_every_offset(engine, correr) -> None:
    _, ids = _grupo_tplink(engine)
    antes = {table: _count(engine, table) for table in _ESCRITAS}

    code, summary, filas = correr()

    assert {table: _count(engine, table) for table in _ESCRITAS} == antes
    assert code == 0
    assert [filas[i]["resultado"] for i in ids] == ["migraría (dry-run)"] * 3
    assert (summary["migrarian"], summary["campana_ids"]) == (3, [])


def test_an_expired_group_migrates_with_its_real_dates_and_a_warning_on_each_offset(engine, correr) -> None:
    grupo_id = w.grupo(engine, [{"marca": "TP-LINK"}])
    ids = [
        _offset(engine, grupo_id=grupo_id, fecha_desde=date(2026, 5, 1), fecha_hasta=date(2026, 6, 30)),
        _offset(engine, grupo_id=grupo_id, item_id=2964, fecha_desde=date(2026, 5, 1), fecha_hasta=date(2026, 6, 30)),
    ]

    code, summary, filas = correr("--apply")

    assert code == 0
    [c] = _campanas(engine)
    assert (c["fecha_desde"], c["fecha_hasta"]) == (date(2026, 5, 1), date(2026, 6, 30))
    assert filas[ids[0]]["avisos"] == VENCIDO.format("2026-06-30")
    assert filas[ids[1]]["avisos"] == (
        f"migrado en la campaña #{c['id']} del grupo #{grupo_id} | " + VENCIDO.format("2026-06-30")
    )
    assert summary["vencidos_migrados"] == ids


_RECHAZOS = {
    "fechas": (
        [{"fecha_hasta": date(2026, 11, 30)}, {"item_id": 2964, "fecha_hasta": date(2026, 12, 15)}],
        "Grupo #{g}: sus offsets tienen períodos distintos y una campaña tiene uno solo; revisar a mano",
        0,
    ),
    "tipos": (
        [{"tipo_offset": "monto_fijo", "monto": 100}, {"item_id": 2964}],
        "Grupo #{g}: no todos sus offsets son monto por unidad (monto_fijo, monto_por_unidad); revisar a mano",
        0,
    ),
    "monedas": (
        [{}, {"item_id": 2964, "moneda": "ARS", "monto": 100}],
        "Grupo #{g}: mezcla monedas (ARS, USD)",
        0,
    ),
    "monto": ([{}, {"item_id": 2964, "monto": 0}], "Grupo #{g}: el offset #{o1} tiene monto negativo o cero", 0),
    "sin_producto": (
        [{}, {}],
        "Grupo #{g}: el offset #{o1} no indica producto (solo el primero del grupo puede no indicarlo)",
        0,
    ),
    "repetido": (
        [{}, {"item_id": 2964}, {"item_id": 2964, "monto": 9}],
        "Grupo #{g}: el producto 2964 tiene más de un offset",
        0,
    ),
    "sin_usuario": (
        [{"usuario_id": None}, {"item_id": 2964, "usuario_id": None}],
        "Grupo #{g}: sin usuario; indicar --usuario-id",
        0,
    ),
    # B1: the legacy capped the group in USD; a campaign in pesos would be uncapped.
    "tope_usd_en_pesos_vencido": (
        [
            {"moneda": "ARS", "monto": 100, "max_monto_usd": 50, **_VENCIDO},
            {"item_id": 2964, "moneda": "ARS", "monto": 150, **_VENCIDO},
        ],
        "Grupo #{g}: El tope en USD (50,00) no se puede guardar en una campaña en pesos",
        0,
    ),
    # B1: one offset of the group skipped ML; a campaign covers every channel.
    "canales": (
        [{}, {"item_id": 2964, "aplica_ml": False}],
        "Grupo #{g}: No aplicaba a: ML; una campaña aplica a todos los canales",
        0,
    ),
}


@pytest.mark.parametrize("caso", list(_RECHAZOS))
def test_a_group_that_cannot_be_modeled_stores_every_offset_for_review_and_creates_nothing(
    engine, correr, caso
) -> None:
    valores, motivo, codigo = _RECHAZOS[caso]
    grupo_id = w.grupo(engine, [{"marca": "TP-LINK"}])
    ids = [_offset(engine, grupo_id=grupo_id, **v) for v in valores]
    motivo = motivo.format(g=grupo_id, o1=ids[1])

    code, summary, filas = correr("--apply")

    assert code == codigo
    assert _campanas(engine) == [] and _count(engine, "offset_grupos") == 1
    assert _count(engine, "sell_out_campana_items") == 0
    assert {i: (filas[i]["resultado"], filas[i]["motivo"], filas[i]["campana_id"]) for i in ids} == dict.fromkeys(
        ids, ("no migrado", motivo, "")
    )
    pendientes = _pendientes(engine)
    assert {i: (pendientes[i]["motivo"], pendientes[i]["grupo_id"]) for i in pendientes} == dict.fromkeys(
        ids, (motivo, grupo_id)
    )
    assert (summary["no_migrados"], summary["pendientes"], summary["migrados"]) == (len(ids), len(ids), 0)
    assert summary["con_error"] == (ids if codigo else [])


FUERA_DE_FILTROS = (
    "Grupo #{g}: los productos {items} no están en sus filtros (venían de sus offsets): "
    "van a un grupo nuevo de la misma campaña"
)


def test_a_group_product_outside_its_filters_goes_to_a_new_group_of_the_same_campaign(engine, correr) -> None:
    # Owner: "El grupo lo arma el operador": the legacy money path reaches the group's filters AND the products of its
    # offsets (`_consumo_grupos`), so a product outside the filters is part of the group, not an error.
    grupo_id = w.grupo(engine, [{"marca": "TP-LINK"}])
    ref = _offset(engine, grupo_id=grupo_id, monto=2, max_monto_usd=2000)
    o950 = _offset(engine, grupo_id=grupo_id, item_id=950, monto=7)  # MERCUSYS: outside the TP-LINK filter
    o2964 = _offset(engine, grupo_id=grupo_id, item_id=2964, monto=3)  # inside it

    code, summary, filas = correr("--apply")

    assert code == 0
    [c] = _campanas(engine)
    assert (c["offset_origen_id"], c["monto_unit"], c["tope_monto"]) == (ref, Decimal("2.00"), Decimal("2000.00"))
    grupos = [g for g, _ in _grupos_de(engine, c["id"])]
    assert grupos[0] == grupo_id and len(grupos) == 2  # one campaign, one shared cap over both groups
    nuevo = grupos[1]
    assert _filtros(engine, grupo_id) == [("TP-LINK", None, None, None)]  # the operator's group is left as it was
    assert _filtros(engine, nuevo) == [(None, None, None, 950)]
    assert _items_de(engine, c["id"]) == [(950, Decimal("7.00")), (2964, Decimal("3.00"))]
    aviso = FUERA_DE_FILTROS.format(g=grupo_id, items="950")
    assert {i: (filas[i]["resultado"], filas[i]["campana_id"]) for i in (ref, o950, o2964)} == dict.fromkeys(
        (ref, o950, o2964), ("migrado", str(c["id"]))
    )
    assert filas[ref]["avisos"] == aviso
    assert (summary["migrados"], summary["no_migrados"], summary["pendientes"], _pendientes(engine)) == (3, 0, 0, {})

    grupos_antes = _count(engine, "offset_grupos")
    code, _, filas = correr("--apply")  # a re-run creates nothing: the new group is reached through the campaign

    assert code == 0 and _count(engine, "offset_grupos") == grupos_antes and len(_campanas(engine)) == 1
    assert {filas[i]["resultado"] for i in (ref, o950, o2964)} == {"ya migrado"}


def test_a_refused_group_campaign_leaves_no_new_group_behind(engine, correr, monkeypatch) -> None:
    # R3-001: the new group is flushed before the campaign is created; a refusal after it must roll it back.
    grupo_id = w.grupo(engine, [{"marca": "TP-LINK"}])
    ids = [_offset(engine, grupo_id=grupo_id), _offset(engine, grupo_id=grupo_id, item_id=950)]  # 950: MERCUSYS
    antes = {table: _count(engine, table) for table in _ESCRITAS}
    vistos = []

    def rechazar(db, data, usuario_id, offset_origen_id):
        vistos.append(list(data.grupo_ids))  # the new group exists in the transaction at this point
        raise script.campanas.SellOutError("rechazada")

    monkeypatch.setattr(script.campanas, "crear_campana", rechazar)

    code, summary, filas = correr("--apply")

    assert code == 1
    assert len(vistos) == 1 and vistos[0][0] == grupo_id and len(vistos[0]) == 2
    escritas = {table: _count(engine, table) for table in _ESCRITAS if table != "offsets_migracion_pendientes"}
    assert escritas == {table: antes[table] for table in escritas}
    assert {filas[i]["resultado"] for i in ids} == {"no migrado"}
    assert {filas[i]["avisos"] for i in ids} == {""}  # nothing moved: no "van a un grupo nuevo" on a refusal
    assert {i: p["motivo"] for i, p in _pendientes(engine).items()} == dict.fromkeys(
        ids, f"Grupo #{grupo_id}: rechazada"
    )


@pytest.fixture()
def sin_fk_de_producto(engine: Engine) -> Iterator[None]:
    """`offsets_ganancia` without its product FK, as a legacy table may be: an offset can name a deleted product.
    Teardown removes only the offsets naming a missing product and restores each FK with its own name and definition."""
    with engine.begin() as conn:
        fks = conn.execute(
            text(
                "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conrelid = 'offsets_ganancia'::regclass AND contype = 'f' "
                "AND confrelid = 'productos_erp'::regclass"
            )
        ).all()
        for nombre, _ in fks:
            conn.execute(text(f'ALTER TABLE offsets_ganancia DROP CONSTRAINT "{nombre}"'))
    assert fks, "offsets_ganancia should reference productos_erp"
    yield
    with engine.begin() as conn:
        conn.execute(
            text(
                "DELETE FROM offsets_ganancia o WHERE o.item_id IS NOT NULL "
                "AND NOT EXISTS (SELECT 1 FROM productos_erp p WHERE p.item_id = o.item_id)"
            )
        )
        for nombre, definicion in fks:
            conn.execute(text(f'ALTER TABLE offsets_ganancia ADD CONSTRAINT "{nombre}" {definicion}'))


@pytest.mark.parametrize("args", [(), ("--apply",)], ids=["dry_run", "apply"])
def test_a_group_product_that_does_not_exist_is_refused_the_same_in_dry_run_and_apply(
    engine, correr, sin_fk_de_producto, args
) -> None:
    # Review R3-dryrun-apply-divergence: the dry run must report what `--apply` does for the products' group.
    grupo_id = w.grupo(engine, [{"marca": "TP-LINK"}])
    ids = [_offset(engine, grupo_id=grupo_id), _offset(engine, grupo_id=grupo_id, item_id=999999)]
    motivo = f"Grupo #{grupo_id}: el producto 999999 de sus offsets no existe; revisar a mano"
    antes = _count(engine, "offset_grupos")

    code, summary, filas = correr(*args)

    assert code == 0
    assert _campanas(engine) == [] and _count(engine, "offset_grupos") == antes
    assert {i: (filas[i]["resultado"], filas[i]["motivo"]) for i in ids} == dict.fromkeys(ids, ("no migrado", motivo))
    assert summary["pendientes"] == 2


def test_a_group_without_filters_reaches_the_products_of_its_offsets(engine, correr) -> None:
    # Group #1 in prod (offsets 14/15/16): the operator picked products, the group has no filter rows.
    grupo_id = w.grupo(engine, [])
    ids = [
        _offset(engine, grupo_id=grupo_id, item_id=2964, monto=20, max_monto_usd=2000),
        _offset(engine, grupo_id=grupo_id, item_id=2270, monto=20),
        _offset(engine, grupo_id=grupo_id, item_id=950, monto=20),
    ]

    code, summary, filas = correr("--apply")

    assert code == 0
    [c] = _campanas(engine)
    assert c["tope_monto"] == Decimal("2000.00")
    grupos = [g for g, _ in _grupos_de(engine, c["id"])]
    assert grupos[0] == grupo_id and len(grupos) == 2
    assert _filtros(engine, grupo_id) == []
    assert _filtros(engine, grupos[1]) == [(None, None, None, 2964), (None, None, None, 2270), (None, None, None, 950)]
    assert _items_de(engine, c["id"]) == [(950, Decimal("20.00")), (2270, Decimal("20.00")), (2964, Decimal("20.00"))]
    assert filas[ids[0]]["avisos"] == FUERA_DE_FILTROS.format(g=grupo_id, items="2964, 2270, 950")
    assert {filas[i]["resultado"] for i in ids} == {"migrado"}
    assert (summary["migrados"], summary["pendientes"]) == (3, 0)


def test_the_dry_run_of_a_group_without_filters_matches_apply(engine, correr) -> None:
    # Review: a product reached only through the new group must pass the service's reach rule, as the dry run assumes.
    grupo_id = w.grupo(engine, [])
    ids = [
        _offset(engine, grupo_id=grupo_id, item_id=2964, monto=20, max_monto_usd=2000),
        _offset(engine, grupo_id=grupo_id, item_id=950, monto=20),
    ]

    code, _, filas = correr()
    code_apply, _, filas_apply = correr("--apply")

    assert (code, code_apply) == (0, 0)
    assert {i: filas[i]["resultado"] for i in ids} == dict.fromkeys(ids, "migraría (dry-run)")
    assert {i: filas_apply[i]["resultado"] for i in ids} == dict.fromkeys(ids, "migrado")
    assert (
        filas[ids[0]]["avisos"]
        == filas_apply[ids[0]]["avisos"]
        == FUERA_DE_FILTROS.format(g=grupo_id, items="2964, 950")
    )


def test_the_dry_run_plans_a_group_product_outside_its_filters_as_apply_does(engine, correr) -> None:
    # A1: the dry run reports what `--apply` does and writes nothing.
    grupo_id = w.grupo(engine, [{"marca": "TP-LINK"}])
    ids = [_offset(engine, grupo_id=grupo_id), _offset(engine, grupo_id=grupo_id, item_id=950)]  # 950: MERCUSYS
    aviso = FUERA_DE_FILTROS.format(g=grupo_id, items="950")
    antes = {table: _count(engine, table) for table in _ESCRITAS}

    code, summary, filas = correr()

    assert {table: _count(engine, table) for table in _ESCRITAS} == antes
    assert code == 0
    assert {i: filas[i]["resultado"] for i in ids} == dict.fromkeys(ids, "migraría (dry-run)")
    assert filas[ids[0]]["avisos"] == aviso
    assert (summary["pendientes"], summary["migrarian"], summary["no_migrados"], summary["con_error"]) == (
        0,
        2,
        0,
        [],
    )

    code_apply, summary_apply, filas_apply = correr("--apply")

    assert code_apply == code
    assert {i: filas_apply[i]["resultado"] for i in ids} == dict.fromkeys(ids, "migrado")
    assert filas_apply[ids[0]]["avisos"] == aviso
    assert len(_campanas(engine)) == 1


@pytest.mark.parametrize("cual,campana,nuevo", [(0, "2,00", 5), (1, "3,50", 9)], ids=["referencia", "producto"])
def test_an_offset_whose_amount_changed_after_its_group_migrated_goes_to_review(
    engine, correr, cual, campana, nuevo
) -> None:
    # A2: the campaign keeps the old amount; reporting it "ya migrado" would hide the difference.
    grupo_id, ids = _grupo_tplink(engine)
    correr("--apply")
    [c] = _campanas(engine)
    items = _items_de(engine, c["id"])
    with engine.begin() as conn:
        conn.execute(text("UPDATE offsets_ganancia SET monto = :m WHERE id = :i"), {"m": nuevo, "i": ids[cual]})

    code, summary, filas = correr("--apply")

    assert code == 0
    assert _campanas(engine) == [c] and _items_de(engine, c["id"]) == items
    motivo = (
        f"Grupo #{grupo_id}: el monto del offset cambió después de migrar el grupo a la campaña #{c['id']} "
        f"(campaña {campana}, offset {nuevo},00); revisar a mano"
    )
    cambiado = ids[cual]
    assert (filas[cambiado]["resultado"], filas[cambiado]["motivo"], filas[cambiado]["campana_id"]) == (
        "no migrado",
        motivo,
        "",
    )
    otros = [i for i in ids if i != cambiado]
    assert {i: (filas[i]["resultado"], filas[i]["campana_id"]) for i in otros} == dict.fromkeys(
        otros, ("ya migrado", str(c["id"]))
    )
    pendientes = _pendientes(engine)
    assert list(pendientes) == [cambiado] and pendientes[cambiado]["motivo"] == motivo
    assert pendientes[cambiado]["monto"] == nuevo
    assert (summary["ya_migrados"], summary["no_migrados"], summary["pendientes"], summary["migrados"]) == (
        2,
        1,
        1,
        0,
    )


# ── Cost percentage (T22e) and fixed amount ──────────────────────────


def _bono(engine: Engine, porcentaje="4", **values) -> int:
    row = {
        "alcance": "marca",
        "marca": "TP-LINK",
        "categoria": None,
        "tipo": "porcentaje",
        "monto_unit": None,
        "porcentaje": porcentaje,
        "moneda": "ARS",
        "fecha_desde": date(2026, 10, 1),
        "fecha_hasta": date(2026, 12, 31),
        "estado": "activa",
        "usuario_id": 7,
        **values,
    }
    with engine.begin() as conn:
        return conn.execute(
            text(
                f"INSERT INTO sell_in_bonos_marca ({', '.join(row)}) VALUES ({', '.join(':' + k for k in row)}) "
                "RETURNING id"
            ),
            row,
        ).scalar_one()


SIN_BONO = "Porcentaje sobre costo: no hay un bono de sell in equivalente; cargarlo a mano"


def _porcentaje(engine, correr, **values) -> tuple[int, int, dict, dict]:
    """A cost-percentage offset run with --apply: (offset id, exit code, its CSV row, its review row);
    nothing is created, neither a campaign nor a bono."""
    bonos = _count(engine, "sell_in_bonos_marca")
    offset_id = _offset(
        engine, **{"marca": "TP-LINK", "tipo_offset": "porcentaje_costo", "monto": None, "porcentaje": 4, **values}
    )
    code, summary, filas = correr("--apply")
    assert _campanas(engine) == [] and _count(engine, "offset_grupos") == 0
    assert _count(engine, "sell_in_bonos_marca") == bonos
    assert (filas[offset_id]["resultado"], filas[offset_id]["campana_id"]) == ("no migrado", "")
    assert (summary["no_migrados"], summary["pendientes"], summary["con_error"]) == (1, 1, [])
    return offset_id, code, filas[offset_id], _pendientes(engine)[offset_id]


def test_a_cost_percentage_already_loaded_by_hand_as_a_bono_is_reported_with_it(engine, correr) -> None:
    bono = _bono(engine, marca="tp-link ")  # same brand, case and spaces aside
    _bono(engine, marca="EPSON")
    _bono(engine, estado="anulada")
    _bono(engine, alcance="categoria", marca=None, categoria="TP-LINK")
    _bono(engine, tipo="por_unidad", porcentaje=None, monto_unit=5)

    _, code, fila, pendiente = _porcentaje(engine, correr, marca=" TP-Link")

    assert code == 0
    assert (fila["motivo"], fila["avisos"]) == (f"ya cargado a mano como bono #{bono}", "")
    assert (pendiente["motivo"], pendiente["avisos"], pendiente["porcentaje"]) == (fila["motivo"], None, 4.0)


def test_a_bono_with_another_percentage_is_reported_with_a_warning(engine, correr) -> None:
    bono = _bono(engine, porcentaje="3.5")

    _, _, fila, pendiente = _porcentaje(engine, correr)

    assert fila["motivo"] == f"ya cargado a mano como bono #{bono}"
    assert fila["avisos"] == pendiente["avisos"] == "el bono tiene 3,5 % y el offset 4 %"


def test_several_equivalent_bonos_are_all_named(engine, correr) -> None:
    uno, otro = _bono(engine), _bono(engine, porcentaje="5")

    _, _, fila, _ = _porcentaje(engine, correr)

    assert fila["motivo"] == f"ya cargado a mano como bonos #{uno}, #{otro}"
    assert fila["avisos"] == f"el bono #{otro} tiene 5 % y el offset 4 %"


def test_a_cost_percentage_without_an_equivalent_bono_is_stored_with_its_detail(engine, correr) -> None:
    _bono(engine, marca="EPSON")

    _, code, fila, pendiente = _porcentaje(engine, correr)

    assert code == 0
    assert fila["motivo"] == pendiente["motivo"] == SIN_BONO
    assert (pendiente["tipo_offset"], pendiente["marca"], pendiente["porcentaje"]) == (
        "porcentaje_costo",
        "TP-LINK",
        4.0,
    )


@pytest.mark.parametrize(
    "alcance", [{"marca": None, "categoria": "TP-LINK"}, {"marca": None, "item_id": 2964}, {"categoria": "Routers"}]
)
def test_a_cost_percentage_not_scoped_to_a_brand_alone_has_no_equivalent_bono(engine, correr, alcance) -> None:
    _bono(engine)

    _, _, fila, _ = _porcentaje(engine, correr, **alcance)

    assert fila["motivo"] == SIN_BONO


@pytest.mark.parametrize(
    "fechas,coincide",
    [
        ({"fecha_desde": date(2026, 3, 1), "fecha_hasta": date(2026, 6, 30)}, False),  # expired before the bono
        ({"fecha_desde": date(2027, 1, 1), "fecha_hasta": None}, False),  # open-ended, after the bono
        ({"fecha_desde": date(2026, 3, 1), "fecha_hasta": None}, True),  # open-ended, reaching the bono
        ({"fecha_desde": date(2026, 3, 1), "fecha_hasta": date(2026, 10, 1)}, True),  # ends on its first day
        ({"fecha_desde": date(2026, 12, 31), "fecha_hasta": date(2027, 2, 28)}, True),  # starts on its last day
    ],
    ids=["vencido", "abierto_despues", "abierto_cubre", "termina_el_primer_dia", "empieza_el_ultimo_dia"],
)
def test_a_cost_percentage_matches_only_a_bono_covering_its_dates(engine, correr, fechas, coincide) -> None:
    # A4: a bono of another period is not the one loaded by hand for this offset.
    bono = _bono(engine)  # 2026-10-01..2026-12-31

    _, code, fila, pendiente = _porcentaje(engine, correr, **fechas)

    assert code == 0
    motivo = f"ya cargado a mano como bono #{bono}" if coincide else SIN_BONO
    assert (fila["motivo"], fila["avisos"]) == (motivo, "")
    assert (pendiente["motivo"], pendiente["avisos"]) == (motivo, None)


def test_only_the_bonos_covering_the_offset_dates_are_named(engine, correr) -> None:
    _bono(engine, porcentaje="5", fecha_desde=date(2026, 1, 1), fecha_hasta=date(2026, 2, 28))
    cubre = _bono(engine)

    _, _, fila, _ = _porcentaje(engine, correr)

    assert (fila["motivo"], fila["avisos"]) == (f"ya cargado a mano como bono #{cubre}", "")


def test_a_fixed_amount_offset_is_stored_for_review(engine, correr) -> None:
    offset_id = _offset(engine, marca="EPSON", tipo_offset="monto_fijo", monto=10000)

    code, _, filas = correr("--apply")

    assert code == 0
    motivo = "Monto fijo: no tiene equivalente en una campaña por unidad"
    assert (filas[offset_id]["resultado"], filas[offset_id]["motivo"]) == ("no migrado", motivo)
    assert (_pendientes(engine)[offset_id]["motivo"], _campanas(engine)) == (motivo, [])
