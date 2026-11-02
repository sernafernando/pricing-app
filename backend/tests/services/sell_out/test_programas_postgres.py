"""Sell-out programs on Postgres (campaign system S1): the list's counts, the assignment and the suggestions, with
sessions shaped like production's (`autoflush=False`)."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date
from typing import Iterator

import pytest
from sqlalchemy import Engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from app.models.auditoria import Auditoria, TipoAccion
from app.models.sell_out import SellOutCampana
from app.schemas.sell_out import SellOutCampanaIn, SellOutProgramaIn
from app.services.sell_out import campanas, programas
from tests.services.sell_out import _world as w

pytestmark = pytest.mark.postgres
USUARIO = 7


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with w.world("so_programas_svc") as engine:
        yield engine


@pytest.fixture
def Sesion(engine) -> Iterator[sessionmaker]:
    w.clean(engine)
    yield sessionmaker(bind=engine, autoflush=False)


@contextmanager
def _consultas(engine: Engine) -> Iterator[list]:
    vistas: list = []

    def contar(conn, cursor, statement, *args) -> None:
        if statement.lstrip().upper().startswith("SELECT"):
            vistas.append(statement)

    event.listen(engine, "before_cursor_execute", contar)
    try:
        yield vistas
    finally:
        event.remove(engine, "before_cursor_execute", contar)


def _programa(Sesion: sessionmaker, nombre: str, estado: str = "activo") -> int:
    with Sesion() as db:
        pid = programas.crear(db, SellOutProgramaIn(nombre=nombre), USUARIO).id
    if estado != "activo":
        w.execute(Sesion.kw["bind"], "UPDATE sell_out_programas SET estado = :e WHERE id = :i", e=estado, i=pid)
    return pid


def _campana(engine: Engine, nombre: str, desde: date, hasta: date, **values) -> int:
    return w.campana(engine, [], desde, hasta, nombre=nombre, **values)


def _auditoria(db: Session) -> list[Auditoria]:
    filtro = Auditoria.tipo_accion == TipoAccion.SELL_OUT_CAMPANA_PROGRAMA
    return db.query(Auditoria).filter(filtro).order_by(Auditoria.id).all()


def test_the_list_counts_each_program_campaigns_in_one_query(engine, Sesion) -> None:
    marca = _programa(Sesion, "MARCA PROG")
    rebate = _programa(Sesion, "Rebate", "archivado")
    _programa(Sesion, "aaa vacío")
    ids = [
        _campana(engine, "MARCA PROG 24", date(2024, 1, 1), date(2024, 12, 31), estado="anulada"),
        _campana(engine, "MARCA PROG 25", date(2025, 1, 1), date(2025, 12, 31)),
        _campana(engine, "MARCA PROG 26", date(2026, 1, 1), date(2026, 3, 31)),
    ]
    w.execute(engine, "UPDATE sell_out_campanas SET programa_id = :p", p=marca)
    _campana(engine, "Rebate Q4 2024", date(2024, 10, 1), date(2024, 12, 31), programa_id=rebate)
    _campana(engine, "TP-Link 2% noviembre", date(2026, 11, 1), date(2026, 11, 30))
    assert len(ids) == 3

    with Sesion() as db, _consultas(engine) as vistas:
        filas = programas.listar(db)
    assert len(vistas) == 2  # the counts, and the page's names for `nombres`
    assert [
        (f["nombre"], f["estado"], f["campanas"], f["activas"], f["nombres"], f["desde"], f["hasta"]) for f in filas
    ] == [
        ("aaa vacío", "activo", 0, 0, 0, None, None),
        ("MARCA PROG", "activo", 3, 2, 3, date(2024, 1, 1), date(2026, 3, 31)),
        ("Rebate", "archivado", 1, 1, 1, date(2024, 10, 1), date(2024, 12, 31)),
    ]
    with Sesion() as db:
        assert [f["nombre"] for f in programas.listar(db, "archivado")] == ["Rebate"]


def test_a_duplicate_name_found_only_by_the_unique_index_is_the_same_409(Sesion, monkeypatch) -> None:
    _programa(Sesion, "MARCA PROG")
    monkeypatch.setattr(programas, "_duplicado", lambda *args, **kwargs: None)  # a concurrent insert won the race
    with Sesion() as db, pytest.raises(programas.ProgramaDuplicado, match="«Marca Prog»"):
        programas.crear(db, SellOutProgramaIn(nombre="Marca Prog"), USUARIO)


def test_assign_is_audited_bulk_queues_nothing_and_keeps_the_money(engine, Sesion) -> None:
    programa = _programa(Sesion, "MARCA PROG")
    activa = _campana(engine, "MARCA PROG 25", date(2025, 1, 1), date(2025, 12, 31))
    anulada = _campana(engine, "MARCA PROG 24", date(2024, 1, 1), date(2024, 12, 31), estado="anulada")
    w.clear_queue(engine)
    with engine.connect() as conn:
        dinero = conn.execute(text("SELECT id, estado, monto_unit FROM sell_out_campanas ORDER BY id")).all()

    with Sesion() as db:
        assert programas.asignar(db, [anulada, activa], programa, USUARIO) == (2, 0)

    assert w.queued(engine) == []
    with engine.connect() as conn:
        assert conn.execute(text("SELECT id, estado, monto_unit FROM sell_out_campanas ORDER BY id")).all() == dinero
        assert conn.execute(text("SELECT DISTINCT programa_id FROM sell_out_campanas")).scalar_one() == programa
    with Sesion() as db:
        filas = _auditoria(db)
        assert [(f.valores_anteriores, f.valores_nuevos, f.es_masivo, f.item_id, f.usuario_id) for f in filas] == [
            (
                {"campana_id": cid, "programa_id": None, "programa": None},
                {"campana_id": cid, "programa_id": programa, "programa": "MARCA PROG"},
                True,
                None,
                USUARIO,
            )
            for cid in sorted([activa, anulada])
        ]
        assert programas.asignar(db, [activa], None, USUARIO) == (1, 0)
        assert _auditoria(db)[-1].es_masivo is False
    assert w.queued(engine) == []


def test_assign_is_all_or_nothing(engine, Sesion) -> None:
    marca = _programa(Sesion, "MARCA PROG")
    archivado = _programa(Sesion, "Rebate", "archivado")
    campana = _campana(engine, "MARCA PROG 25", date(2025, 1, 1), date(2025, 12, 31))

    with Sesion() as db:
        with pytest.raises(programas.ProgramaError, match="^La campaña 999999 no existe.$"):
            programas.asignar(db, [campana, 999999], marca, USUARIO)
        with pytest.raises(programas.ProgramaNoExiste):
            programas.asignar(db, [campana], 999999, USUARIO)
        with pytest.raises(programas.ProgramaError, match="«Rebate» está archivado"):
            programas.asignar(db, [campana], archivado, USUARIO)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT programa_id FROM sell_out_campanas")).scalar_one() is None
        assert conn.execute(text("SELECT count(*) FROM auditoria")).scalar_one() == 0


def test_editing_a_campaign_keeps_its_program(engine, Sesion) -> None:
    programa = _programa(Sesion, "MARCA PROG")
    grupo = w.grupo(engine, [{"marca": "TP-LINK"}])
    campana = w.campana(engine, [grupo], nombre="MARCA PROG 25", programa_id=programa)
    data = SellOutCampanaIn.model_validate(
        {
            "nombre": "MARCA PROG 25 bis",
            "fecha_desde": date(2026, 11, 1),
            "fecha_hasta": date(2026, 11, 30),
            "tipo": "por_unidad",
            "monto_unit": "10",
            "moneda": "ARS",
            "grupo_ids": [grupo],
        }
    )
    with Sesion() as db:
        campanas.editar_campana(db, campana, data, USUARIO)
    with Sesion() as db:
        fila = campanas.serializar(db, [db.get(SellOutCampana, campana)])[0]
    assert (fila["nombre"], fila["programa_id"], fila["programa"]) == (
        "MARCA PROG 25 bis",
        programa,
        {"id": programa, "nombre": "MARCA PROG"},
    )


def test_a_page_of_campaigns_reads_their_programs_in_one_query(engine, Sesion) -> None:
    marca = _programa(Sesion, "MARCA PROG")
    rebate = _programa(Sesion, "Rebate")
    ids = [
        _campana(engine, "MARCA PROG 25", date(2025, 1, 1), date(2025, 12, 31), programa_id=marca),
        _campana(engine, "Rebate Q4 2024", date(2024, 10, 1), date(2024, 12, 31), programa_id=rebate),
        _campana(engine, "TP-Link 2% noviembre", date(2026, 11, 1), date(2026, 11, 30)),
    ]
    with Sesion() as db:
        pagina = db.query(SellOutCampana).filter(SellOutCampana.id.in_(ids)).order_by(SellOutCampana.id).all()
        with _consultas(engine) as vistas:
            filas = campanas.serializar(db, pagina)
    assert sum("sell_out_programas" in v for v in vistas) == 1
    assert [f["programa"] for f in filas] == [
        {"id": marca, "nombre": "MARCA PROG"},
        {"id": rebate, "nombre": "Rebate"},
        None,
    ]


def test_suggestions_group_campaigns_without_a_program_by_identical_dates(engine, Sesion) -> None:
    """Production's repeated names (2026-11-02 read) share their dates and differ only in what they apply to; the
    families of names that carry their per-unit amount share a date range. So a suggestion is a date range with 2 or
    more campaigns, named by the words all its names start with."""
    marca = date(2026, 8, 1), date(2026, 12, 31)
    sp = date(2025, 11, 1), date(2026, 12, 31)
    programa = _programa(Sesion, "MARCA PROG")
    e = [
        _campana(engine, "MARCA PROGRAM1", *marca),
        _campana(engine, "MARCA PROG 3.0", *marca),
        _campana(engine, "MARCA PROGRAM1", *marca, estado="anulada"),
        _campana(engine, "MARCA PROGR 7.5", *marca),
    ]
    _campana(engine, "MARCA PROG 12", *marca, programa_id=programa)  # already in a program
    s = [_campana(engine, "M20 / M80 SP", *sp), _campana(engine, "M30/M70", *sp), _campana(engine, "M20 / M80 SP", *sp)]
    _campana(engine, "RB 8180", date(2026, 1, 1), date(2026, 12, 31))  # alone in its dates

    with Sesion() as db:
        grupos = programas.sugerencias(db)
    assert [
        (g["base"], g["fecha_desde"], g["fecha_hasta"], g["nombres"], [c["id"] for c in g["campanas"]]) for g in grupos
    ] == [
        ("MARCA", *marca, 3, [e[1], e[3], e[0], e[2]]),  # by name ignoring case, then id
        ("Del 01/11/2025 al 31/12/2026", *sp, 2, [s[0], s[2], s[1]]),
    ]
    assert grupos[0]["campanas"][3] == {
        "id": e[2],
        "nombre": "MARCA PROGRAM1",
        "fecha_desde": date(2026, 8, 1),
        "fecha_hasta": date(2026, 12, 31),
        "estado": "anulada",
    }


def test_por_programa_groups_a_page_in_constant_queries_under_the_filters(engine, Sesion) -> None:
    """Slice E: the grouped view's rows come in the same number of queries whatever the page holds; a program with
    no campaign under the filters is left out, and the campaigns without one come apart."""
    marca = _programa(Sesion, "MARCA PROG")
    modelos = _programa(Sesion, "Modelos SP")
    _programa(Sesion, "aaa vacío")
    _campana(engine, "MARCA PROG 3.0", date(2026, 8, 1), date(2026, 10, 31), programa_id=marca)
    _campana(engine, "marca  prog 3.0", date(2026, 8, 1), date(2026, 10, 31), programa_id=marca)
    _campana(engine, "MARCA PROGRAM1", date(2026, 9, 1), date(2026, 11, 30), programa_id=marca, estado="anulada")
    _campana(engine, "M20 / M80 SP", date(2025, 11, 1), date(2026, 10, 31), programa_id=modelos)
    _campana(engine, "MODELO 8180", date(2026, 1, 1), date(2026, 12, 31))

    def contar(filtros: campanas.FiltrosCampanas) -> tuple[list, int]:
        with Sesion() as db, _consultas(engine) as vistas:
            pagina = campanas.por_programa(db, filtros, page=1, page_size=50)
        return pagina, len(vistas)

    todos, consultas = contar(campanas.FiltrosCampanas())
    items, total, sin = todos
    assert [(g["nombre"], g["campanas"], g["activas"], g["nombres"], g["desde"], g["hasta"]) for g in items] == [
        ("MARCA PROG", 3, 2, 2, date(2026, 8, 1), date(2026, 11, 30)),
        ("Modelos SP", 1, 1, 1, date(2025, 11, 1), date(2026, 10, 31)),
    ]
    assert (total, sin["campanas"], sin["nombres"]) == (2, 1, 1)
    (activas, total, sin), consultas_filtradas = contar(campanas.FiltrosCampanas(estado="activa", q="marca"))
    assert ([(g["nombre"], g["campanas"]) for g in activas], total, sin) == ([("MARCA PROG", 2)], 1, None)
    assert consultas == consultas_filtradas <= 4
