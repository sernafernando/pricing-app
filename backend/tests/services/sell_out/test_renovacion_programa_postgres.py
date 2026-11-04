"""Renovar programa on Postgres (sessions shaped like production's, `autoflush=False`): the preview of a program's
renewal writes nothing, and the renewal creates the next-quarter copy of each campaign of the program's latest
period in one all-or-nothing step, through the per-campaign renewal's draft and create.

- L is the quarter of the program's latest `fecha_hasta`. Candidates are its non-voided campaigns no copy names yet,
  ending in quarter L or L-1; the source period is the earliest quarter among them, and its candidates are renewed.
  Active not-renewed campaigns of L or L-1 outside the source are listed (`quedan_afuera`), not renewed.
- Voided campaigns of that period are skipped and listed as "anulada, no se renueva".
- A campaign is already renewed when another non-voided campaign names it in `renovada_de_id`.
- An archived program renews nothing."""

from __future__ import annotations

from datetime import date
from typing import Iterator

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import sessionmaker

from app.schemas.sell_out import SellOutProgramaIn
from app.services.sell_out import campanas, programas, renovacion, renovacion_programa
from tests.services.sell_out import _world as w

pytestmark = pytest.mark.postgres
USUARIO = 7
Q4_DESDE, Q4_HASTA = date(2026, 10, 1), date(2026, 12, 31)
Q1_DESDE, Q1_HASTA = date(2027, 1, 1), date(2027, 3, 31)


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with w.world("so_renovacion_prog") as engine:
        yield engine


@pytest.fixture
def Sesion(engine) -> Iterator[sessionmaker]:
    w.clean(engine)
    yield sessionmaker(bind=engine, autoflush=False)


def _programa(Sesion: sessionmaker, nombre: str = "MARCA PROG", estado: str = "activo") -> int:
    with Sesion() as db:
        pid = programas.crear(db, SellOutProgramaIn(nombre=nombre), USUARIO).id
    if estado != "activo":
        w.execute(Sesion.kw["bind"], "UPDATE sell_out_programas SET estado = :e WHERE id = :i", e=estado, i=pid)
    return pid


def _campana(engine: Engine, programa: int, nombre: str, desde: date, hasta: date, **values) -> int:
    grupo = w.grupo(engine, [{"marca": "TP-LINK"}])
    return w.campana(engine, [grupo], desde, hasta, nombre=nombre, programa_id=programa, **values)


def _foto(engine: Engine) -> dict:
    with engine.connect() as conn:
        return {
            tabla: [tuple(r) for r in conn.execute(text(f"SELECT * FROM {tabla} ORDER BY 1"))]
            for tabla in ("sell_out_campanas", "sell_out_campana_grupos", "sell_out_campana_items", "auditoria")
        } | {"sell_out_dirty": w.queued(engine)}


def _copias(engine: Engine) -> list[tuple]:
    with engine.connect() as conn:
        return [
            tuple(r)
            for r in conn.execute(
                text(
                    "SELECT renovada_de_id, nombre, fecha_desde, fecha_hasta, programa_id, estado FROM sell_out_campanas "
                    "WHERE renovada_de_id IS NOT NULL ORDER BY renovada_de_id"
                )
            )
        ]


def test_the_preview_lists_the_latest_quarter_campaigns_with_their_new_dates_and_writes_nothing(engine, Sesion) -> None:
    pid = _programa(Sesion)
    _campana(engine, pid, "Modelo A Q2 2026", date(2026, 4, 1), date(2026, 6, 30))  # older than L-1
    a = _campana(engine, pid, "Modelo A Q4 2026", Q4_DESDE, Q4_HASTA)
    b = _campana(engine, pid, "MODELO B", date(2026, 11, 1), date(2026, 11, 30))  # same quarter, other dates
    _campana(engine, None, "Fuera Q4 2026", Q4_DESDE, Q4_HASTA)  # not in the program
    w.clear_queue(engine)
    antes = _foto(engine)

    with Sesion() as db:
        previa = renovacion_programa.previa(db, pid)
        db.commit()

    assert _foto(engine) == antes
    assert (previa["programa_id"], previa["programa"], previa["fecha_desde"], previa["fecha_hasta"]) == (
        pid,
        "MARCA PROG",
        Q1_DESDE,
        Q1_HASTA,
    )
    assert previa["renovar"] == [
        {"campana_id": a, "nombre": "Modelo A Q4 2026", "nombre_nuevo": "Modelo A Q1 2027"},
        {"campana_id": b, "nombre": "MODELO B", "nombre_nuevo": "MODELO B"},
    ]
    assert previa["omitidas"] == previa["quedan_afuera"] == []
    assert (previa["periodo_desde"], previa["periodo_hasta"]) == (Q4_DESDE, Q4_HASTA)


def test_voided_and_already_renewed_campaigns_are_skipped_and_listed(engine, Sesion) -> None:
    pid = _programa(Sesion)
    activa = _campana(engine, pid, "Modelo A Q4 2026", Q4_DESDE, Q4_HASTA)
    anulada = _campana(engine, pid, "Modelo B Q4 2026", Q4_DESDE, Q4_HASTA, estado="anulada")
    renovada = _campana(engine, pid, "Modelo C Q4 2026", Q4_DESDE, Q4_HASTA)
    copia_anulada = _campana(engine, pid, "Modelo D Q4 2026", Q4_DESDE, Q4_HASTA)
    with Sesion() as db:  # renewed one at a time, the per-campaign way
        copia = campanas.crear_campana(db, renovacion.borrador(db, renovada), USUARIO).id
        descartada = campanas.crear_campana(db, renovacion.borrador(db, copia_anulada), USUARIO).id
        campanas.anular_campana(db, descartada, USUARIO, None)  # a voided copy does not count

    with Sesion() as db:
        previa = renovacion_programa.previa(db, pid)

    assert [r["campana_id"] for r in previa["renovar"]] == [activa, copia_anulada]
    assert previa["omitidas"] == [
        {"campana_id": anulada, "nombre": "Modelo B Q4 2026", "motivo": "anulada, no se renueva"},
        {
            "campana_id": renovada,
            "nombre": "Modelo C Q4 2026",
            "motivo": f"ya renovada en la campaña {copia} (Modelo C Q1 2027)",
        },
    ]
    # The hand-made copy sits in Q1 (now L): left out of this pass, and said so.
    assert previa["quedan_afuera"] == [{"campana_id": copia, "nombre": "Modelo C Q1 2027", "fecha_hasta": Q1_HASTA}]


def test_renewing_creates_every_copy_in_the_program_linked_audited_and_queued(engine, Sesion) -> None:
    pid = _programa(Sesion)
    a = _campana(engine, pid, "Modelo A Q4 2026", Q4_DESDE, Q4_HASTA)
    b = _campana(engine, pid, "Modelo B Q4 2026", Q4_DESDE, Q4_HASTA)
    anulada = _campana(engine, pid, "Modelo C Q4 2026", Q4_DESDE, Q4_HASTA, estado="anulada")
    w.clear_queue(engine)

    with Sesion() as db:
        out = renovacion_programa.renovar(db, pid, [b, a], USUARIO)

    assert _copias(engine) == [
        (a, "Modelo A Q1 2027", Q1_DESDE, Q1_HASTA, pid, "activa"),
        (b, "Modelo B Q1 2027", Q1_DESDE, Q1_HASTA, pid, "activa"),
    ]
    with engine.connect() as conn:
        creadas = dict(
            conn.execute(
                text("SELECT renovada_de_id, id FROM sell_out_campanas WHERE renovada_de_id IS NOT NULL")
            ).all()
        )
        audit = (
            conn.execute(
                text(
                    "SELECT valores_nuevos ->> 'renovada_de_id' FROM auditoria "
                    "WHERE tipo_accion = 'SELL_OUT_CAMPANA_CREADA' ORDER BY id"
                )
            )
            .scalars()
            .all()
        )
    assert out["creadas"] == [
        {"campana_id": a, "nueva_id": creadas[a]},
        {"campana_id": b, "nueva_id": creadas[b]},
    ]
    assert [o["campana_id"] for o in out["omitidas"]] == [anulada]
    assert audit == [str(a), str(b)]
    assert sorted(c for c, *_ in w.queued(engine)) == sorted(creadas.values())


def test_a_campaign_that_cannot_be_created_stores_nothing_for_any(engine, Sesion, monkeypatch) -> None:
    pid = _programa(Sesion)
    a = _campana(engine, pid, "Modelo A Q4 2026", Q4_DESDE, Q4_HASTA)
    b = _campana(engine, pid, "Modelo B Q4 2026", Q4_DESDE, Q4_HASTA)
    w.clear_queue(engine)
    antes = _foto(engine)
    real = campanas.crear_campana_sin_commit

    def segunda_falla(db, data, usuario_id, **kw):
        if data.renovada_de_id == b:
            raise campanas.SellOutError("Regla rota")
        return real(db, data, usuario_id, **kw)

    monkeypatch.setattr(campanas, "crear_campana_sin_commit", segunda_falla)
    with Sesion() as db:
        with pytest.raises(campanas.SellOutError, match=r"Modelo B Q4 2026.*Regla rota"):
            renovacion_programa.renovar(db, pid, [a, b], USUARIO)

    assert _foto(engine) == antes


def test_a_selection_that_no_longer_matches_the_preview_is_refused_and_a_second_click_creates_nothing(
    engine, Sesion
) -> None:
    pid = _programa(Sesion)
    a = _campana(engine, pid, "Modelo A Q4 2026", Q4_DESDE, Q4_HASTA)
    b = _campana(engine, pid, "Modelo B Q4 2026", Q4_DESDE, Q4_HASTA)
    antes = _foto(engine)

    with Sesion() as db:
        with pytest.raises(renovacion_programa.RenovacionDesactualizada, match="cambió"):
            renovacion_programa.renovar(db, pid, [a], USUARIO)
    assert _foto(engine) == antes

    with Sesion() as db:
        renovacion_programa.renovar(db, pid, [a, b], USUARIO)
    despues = _foto(engine)
    with Sesion() as db:  # the same click again: both are renewed now
        with pytest.raises(renovacion_programa.RenovacionDesactualizada):
            renovacion_programa.renovar(db, pid, [a, b], USUARIO)
    assert _foto(engine) == despues


def test_nothing_left_to_renew_is_refused(engine, Sesion) -> None:
    pid = _programa(Sesion)
    _campana(engine, pid, "Modelo A Q4 2026", Q4_DESDE, Q4_HASTA, estado="anulada")
    with Sesion() as db:
        assert renovacion_programa.previa(db, pid)["renovar"] == []
        with pytest.raises(campanas.SellOutError, match="No hay campañas para renovar"):
            renovacion_programa.renovar(db, pid, [], USUARIO)


def test_an_unknown_an_archived_or_an_empty_program_renews_nothing(engine, Sesion) -> None:
    archivado = _programa(Sesion, "Viejo", "archivado")
    _campana(engine, archivado, "Modelo Q4 2026", Q4_DESDE, Q4_HASTA)
    vacio = _programa(Sesion, "Vacío")
    with Sesion() as db:
        with pytest.raises(programas.ProgramaNoExiste):
            renovacion_programa.previa(db, 999999)
        with pytest.raises(programas.ProgramaError, match="archivado"):
            renovacion_programa.previa(db, archivado)
        with pytest.raises(programas.ProgramaError, match="archivado"):
            renovacion_programa.renovar(db, archivado, [], USUARIO)
        previa = renovacion_programa.previa(db, vacio)
    assert (previa["fecha_desde"], previa["renovar"], previa["omitidas"]) == (None, [], [])


def test_a_full_renewal_then_renews_the_copies_into_the_next_quarter(engine, Sesion) -> None:
    pid = _programa(Sesion)
    a = _campana(engine, pid, "Modelo A Q4 2026", Q4_DESDE, Q4_HASTA)
    b = _campana(engine, pid, "Modelo B Q4 2026", Q4_DESDE, Q4_HASTA)
    with Sesion() as db:
        primera = renovacion_programa.renovar(db, pid, [a, b], USUARIO)
    copias = [c["nueva_id"] for c in primera["creadas"]]

    with Sesion() as db:
        previa = renovacion_programa.previa(db, pid)
    assert (previa["periodo_desde"], previa["fecha_desde"], previa["fecha_hasta"]) == (
        Q1_DESDE,
        date(2027, 4, 1),
        date(2027, 6, 30),
    )
    assert [r["nombre_nuevo"] for r in previa["renovar"]] == ["Modelo A Q2 2027", "Modelo B Q2 2027"]
    assert previa["omitidas"] == previa["quedan_afuera"] == []  # the Q4 originals are renewed: out of the window
    with Sesion() as db:
        segunda = renovacion_programa.renovar(db, pid, copias, USUARIO)
    assert [c["campana_id"] for c in segunda["creadas"]] == copias


def test_with_one_campaign_renewed_by_hand_it_renews_the_others_and_leaves_the_copy(engine, Sesion) -> None:
    pid = _programa(Sesion)
    ids = [_campana(engine, pid, f"Modelo {n} Q4 2026", Q4_DESDE, Q4_HASTA) for n in range(1, 33)]
    with Sesion() as db:
        a_mano = campanas.crear_campana(db, renovacion.borrador(db, ids[0]), USUARIO).id

    with Sesion() as db:
        previa = renovacion_programa.previa(db, pid)
    assert (previa["periodo_desde"], previa["fecha_desde"]) == (Q4_DESDE, Q1_DESDE)
    assert [r["campana_id"] for r in previa["renovar"]] == ids[1:]
    assert [o["campana_id"] for o in previa["omitidas"]] == [ids[0]]
    assert [f["campana_id"] for f in previa["quedan_afuera"]] == [a_mano]

    with Sesion() as db:
        renovacion_programa.renovar(db, pid, ids[1:], USUARIO)
    copias = _copias(engine)
    assert [c[0] for c in copias] == ids  # one copy each, the hand-made one included
    with engine.connect() as conn:
        assert (
            conn.execute(
                text("SELECT count(*) FROM sell_out_campanas WHERE renovada_de_id = :c"), {"c": a_mano}
            ).scalar()
            == 0
        )


def test_a_quarter_older_than_the_one_before_the_latest_is_never_picked(engine, Sesion) -> None:
    pid = _programa(Sesion)
    _campana(engine, pid, "Modelo Q3 2026", date(2026, 7, 1), date(2026, 9, 30))  # never renewed, L-2
    q1 = _campana(engine, pid, "Modelo Q1 2027", Q1_DESDE, Q1_HASTA)  # L

    with Sesion() as db:
        previa = renovacion_programa.previa(db, pid)
    assert (previa["periodo_desde"], previa["periodo_hasta"]) == (Q1_DESDE, Q1_HASTA)
    assert [r["campana_id"] for r in previa["renovar"]] == [q1]
    assert previa["quedan_afuera"] == []


Q3_DESDE, Q3_HASTA = date(2026, 7, 1), date(2026, 9, 30)


def test_without_a_link_from_the_latest_quarter_the_one_before_is_not_renewed_again(engine, Sesion) -> None:
    """No backfill: campaigns renewed before the link existed point nowhere, so L-1 counts only when a campaign of L
    names one of L-1. An older link (Q2 -> Q3) does not pull the unlinked Q3 campaigns back in."""
    pid = _programa(Sesion)
    q2 = _campana(engine, pid, "Modelo A Q2 2026", date(2026, 4, 1), date(2026, 6, 30))
    _campana(engine, pid, "Modelo A Q3 2026", Q3_DESDE, Q3_HASTA, renovada_de_id=q2)
    _campana(engine, pid, "Modelo B Q3 2026", Q3_DESDE, Q3_HASTA)  # renewed into Q4 before the link existed
    q4 = [_campana(engine, pid, f"Modelo {n} Q4 2026", Q4_DESDE, Q4_HASTA) for n in "AB"]

    with Sesion() as db:
        previa = renovacion_programa.previa(db, pid)
    assert (previa["periodo_desde"], previa["fecha_desde"]) == (Q4_DESDE, Q1_DESDE)
    assert [r["campana_id"] for r in previa["renovar"]] == q4
    assert previa["omitidas"] == previa["quedan_afuera"] == []


def test_a_link_from_the_latest_quarter_into_the_one_before_brings_it_in(engine, Sesion) -> None:
    pid = _programa(Sesion)
    q3 = [_campana(engine, pid, f"Modelo {n} Q3 2026", Q3_DESDE, Q3_HASTA) for n in "AB"]
    q4 = _campana(engine, pid, "Modelo A Q4 2026", Q4_DESDE, Q4_HASTA, renovada_de_id=q3[0])

    with Sesion() as db:
        previa = renovacion_programa.previa(db, pid)
    assert (previa["periodo_desde"], previa["fecha_desde"]) == (Q3_DESDE, Q4_DESDE)
    assert [r["campana_id"] for r in previa["renovar"]] == [q3[1]]
    assert [f["campana_id"] for f in previa["quedan_afuera"]] == [q4]


def test_a_voided_copy_does_not_count_as_a_renewal(engine, Sesion) -> None:
    pid = _programa(Sesion)
    original = _campana(engine, pid, "Modelo A Q4 2026", Q4_DESDE, Q4_HASTA)
    with Sesion() as db:
        copia = campanas.crear_campana(db, renovacion.borrador(db, original), USUARIO).id
        campanas.anular_campana(db, copia, USUARIO, None)

    with Sesion() as db:
        previa = renovacion_programa.previa(db, pid)
    # A voided campaign does not set the latest quarter either: L is still Q4, and the original renews again.
    assert (previa["periodo_desde"], previa["fecha_desde"]) == (Q4_DESDE, Q1_DESDE)
    assert [r["campana_id"] for r in previa["renovar"]] == [original]
    assert previa["omitidas"] == previa["quedan_afuera"] == []
    with Sesion() as db:
        out = renovacion_programa.renovar(db, pid, [original], USUARIO)
    assert [c["campana_id"] for c in out["creadas"]] == [original]


def test_a_copy_moved_to_another_program_still_renews_its_original_but_brings_no_quarter_back(engine, Sesion) -> None:
    pid, otro = _programa(Sesion, "MARCA PROG"), _programa(Sesion, "Otro")
    q3 = _campana(engine, pid, "Modelo Q3 2026", Q3_DESDE, Q3_HASTA)  # pre-link, already renewed by hand
    q4 = _campana(engine, pid, "Modelo A Q4 2026", Q4_DESDE, Q4_HASTA)
    with Sesion() as db:
        copia = campanas.crear_campana(db, renovacion.borrador(db, q4), USUARIO).id
        programas.asignar(db, [copia], otro, USUARIO)
    # A copy of Q3 in the other program, ending in Q4: the other program's link, not this one's.
    _campana(engine, otro, "Ajena Q4 2026", Q4_DESDE, Q4_HASTA, renovada_de_id=q3)

    with Sesion() as db:
        previa = renovacion_programa.previa(db, pid)
    assert (previa["periodo_desde"], previa["renovar"]) == (Q4_DESDE, [])  # Q3 is not brought back
    assert previa["omitidas"] == [
        {
            "campana_id": q4,
            "nombre": "Modelo A Q4 2026",
            "motivo": f"ya renovada en la campaña {copia} (Modelo A Q1 2027)",
        }
    ]


def test_more_campaigns_than_one_renewal_takes_is_refused_in_the_preview_saying_why(
    engine, Sesion, monkeypatch
) -> None:
    monkeypatch.setattr(renovacion_programa, "RENOVAR_MAX", 1)
    pid = _programa(Sesion)
    for n in "AB":
        _campana(engine, pid, f"Modelo {n} Q4 2026", Q4_DESDE, Q4_HASTA)
    with Sesion() as db:
        with pytest.raises(
            campanas.SellOutError, match="El programa tiene 2 campañas para renovar: se renuevan hasta 1"
        ):
            renovacion_programa.previa(db, pid)
