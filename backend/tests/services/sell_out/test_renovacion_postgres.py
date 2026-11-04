"""Renewing a sell-out campaign on Postgres (campaign system, slice B), with sessions shaped like production's
(`autoflush=False`): the draft writes nothing (no campaign, share, audit row or queue entry) and saving it creates a
new campaign while the original stays as it was."""

from __future__ import annotations

from datetime import date
from typing import Iterator, Optional

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import sessionmaker

from app.services.sell_out import campanas, renovacion
from tests.services.sell_out import _world as w

pytestmark = pytest.mark.postgres
USUARIO = 7


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with w.world("so_renovacion_svc") as engine:
        yield engine


@pytest.fixture
def Sesion(engine) -> Iterator[sessionmaker]:
    w.clean(engine)
    yield sessionmaker(bind=engine, autoflush=False)


def _foto(engine: Engine) -> dict:
    """Every row the draft could have written, as it stands."""
    with engine.connect() as conn:
        return {
            tabla: [tuple(r) for r in conn.execute(text(f"SELECT * FROM {tabla} ORDER BY 1"))]
            for tabla in ("sell_out_campanas", "sell_out_campana_grupos", "sell_out_campana_items", "auditoria")
        } | {"sell_out_dirty": w.queued(engine)}


@pytest.mark.parametrize("estado", ["activa", "anulada"])
def test_the_draft_writes_nothing_and_saving_it_leaves_the_original(engine, Sesion, estado) -> None:
    grupo = w.grupo(engine, [{"marca": "TP-LINK"}])
    original = w.monto_total(engine, [grupo], "300000.00", nombre="Bono Q4 2026", estado=estado)
    w.reparto(engine, original, 2964, porcentaje="40")
    w.clear_queue(engine)
    antes = _foto(engine)

    with Sesion() as db:
        draft = renovacion.borrador(db, original)
        db.commit()  # even a commit after the draft stores nothing
    assert _foto(engine) == antes
    assert (draft.nombre, draft.fecha_desde, draft.fecha_hasta) == ("Bono Q1 2027", date(2027, 1, 1), date(2027, 3, 31))

    with Sesion() as db:
        nueva = campanas.crear_campana(db, draft, USUARIO).id
    despues = _foto(engine)
    assert nueva != original
    assert [f for f in despues["sell_out_campanas"] if f[0] == original] == [
        f for f in antes["sell_out_campanas"] if f[0] == original
    ]
    assert w.queued(engine) == [(nueva, 0, None)]
    with engine.connect() as conn:
        shares = conn.execute(
            text("SELECT item_id, reparto_porcentaje FROM sell_out_campana_items WHERE campana_id = :c"), {"c": nueva}
        ).all()
    assert [(i, float(p)) for i, p in shares] == [(2964, 40.0)]


def test_the_draft_of_an_unknown_campaign_is_none(Sesion) -> None:
    with Sesion() as db:
        assert renovacion.borrador(db, 999) is None


def _renovada_de(engine: Engine, campana_id: int) -> Optional[int]:
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT renovada_de_id FROM sell_out_campanas WHERE id = :c"), {"c": campana_id}
        ).scalar()


def test_the_draft_names_its_original_and_saving_it_stores_the_link(engine, Sesion) -> None:
    grupo = w.grupo(engine, [{"marca": "TP-LINK"}])
    original = w.campana(engine, [grupo], date(2026, 10, 1), date(2026, 12, 31), nombre="Modelo Q4 2026")

    with Sesion() as db:
        draft = renovacion.borrador(db, original)
    assert draft.renovada_de_id == original
    with Sesion() as db:
        nueva = campanas.crear_campana(db, draft, USUARIO).id

    assert _renovada_de(engine, nueva) == original
    assert _renovada_de(engine, original) is None
    with engine.connect() as conn:
        audit = conn.execute(
            text("SELECT valores_nuevos FROM auditoria WHERE tipo_accion = 'SELL_OUT_CAMPANA_CREADA' ORDER BY id DESC")
        ).scalar()
    assert audit["renovada_de_id"] == original


def test_an_edit_keeps_the_stored_link(engine, Sesion) -> None:
    grupo = w.grupo(engine, [{"marca": "TP-LINK"}])
    original = w.campana(engine, [grupo], date(2026, 10, 1), date(2026, 12, 31))
    with Sesion() as db:
        nueva = campanas.crear_campana(db, renovacion.borrador(db, original), USUARIO).id
    with Sesion() as db:
        draft = renovacion.borrador(db, original).model_copy(update={"renovada_de_id": None, "nombre": "Otro"})
        campanas.editar_campana(db, nueva, draft, USUARIO)

    assert _renovada_de(engine, nueva) == original


def test_a_link_to_a_campaign_that_does_not_exist_stores_nothing(engine, Sesion) -> None:
    grupo = w.grupo(engine, [{"marca": "TP-LINK"}])
    original = w.campana(engine, [grupo], date(2026, 10, 1), date(2026, 12, 31))
    antes = _foto(engine)
    with Sesion() as db:
        draft = renovacion.borrador(db, original).model_copy(update={"renovada_de_id": original + 999})
        with pytest.raises(campanas.SellOutError, match="no existe"):
            campanas.crear_campana(db, draft, USUARIO)

    assert _foto(engine) == antes


def test_deleting_the_original_clears_the_link(engine, Sesion) -> None:
    grupo = w.grupo(engine, [{"marca": "TP-LINK"}])
    original = w.campana(engine, [grupo], date(2026, 10, 1), date(2026, 12, 31))
    with Sesion() as db:
        nueva = campanas.crear_campana(db, renovacion.borrador(db, original), USUARIO).id
    w.execute(engine, "DELETE FROM sell_out_campanas WHERE id = :c", c=original)

    assert _renovada_de(engine, nueva) is None
