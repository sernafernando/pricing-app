"""Bulk edit of sell-out campaigns (edición masiva M1, S2-S5), on Postgres (`_world`).

Each row goes through the single edit's own step (`campanas.editar_campana_sin_commit`): the full body is rebuilt
from the stored campaign and only the filled fields (`fecha_desde`, `fecha_hasta`, `acumulable`) are overlaid. All
or nothing, every refused row named.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Iterator

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import sessionmaker

from app.models.auditoria import TipoAccion
from app.models.sell_out import SellOutCampana
from app.schemas.sell_out import SellOutCampanaIn
from app.services.sell_out import edicion_masiva
from app.services.sell_out import campanas as service
from tests.services.sell_out import _world as w

pytestmark = pytest.mark.postgres

USUARIO = 7
ROUTER = 2964
SWITCH = 2270
ROUTERS = {"marca": "TP-LINK", "categoria": "Routers"}
SWITCHES = {"marca": "TP-LINK", "categoria": "Switches"}
EDITADA = TipoAccion.SELL_OUT_CAMPANA_EDITADA


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with w.world("sell_out_editar_masivo") as engine:
        yield engine


@pytest.fixture(autouse=True)
def _clean(engine: Engine) -> Iterator[None]:
    yield
    w.clean(engine)


def _session(engine: Engine):
    return sessionmaker(bind=engine, autoflush=False)()  # like production's `SessionLocal`


def _fila(engine: Engine, cid: int) -> dict:
    with engine.connect() as conn:
        return dict(conn.execute(text("SELECT * FROM sell_out_campanas WHERE id = :c"), {"c": cid}).mappings().one())


def _sin_marcas(fila: dict) -> dict:
    return {k: v for k, v in fila.items() if k not in ("updated_at",)}


def _hijos(engine: Engine, cid: int) -> tuple:
    with engine.connect() as conn:
        grupos = conn.execute(
            text("SELECT grupo_id FROM sell_out_campana_grupos WHERE campana_id = :c ORDER BY id"), {"c": cid}
        ).all()
        items = conn.execute(
            text(
                "SELECT item_id, monto_unit, reparto_porcentaje, reparto_monto FROM sell_out_campana_items "
                "WHERE campana_id = :c ORDER BY item_id"
            ),
            {"c": cid},
        ).all()
    return [tuple(r) for r in grupos], [tuple(r) for r in items]


def _audits(engine: Engine) -> list:
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT valores_nuevos, es_masivo FROM auditoria WHERE tipo_accion = :t ORDER BY id"),
            {"t": EDITADA.name},
        ).all()


def _queued(engine: Engine) -> list[int]:
    return [row[0] for row in w.queued(engine)]


def _editar(engine: Engine, ids, **cambios):
    with _session(engine) as db:
        return edicion_masiva.editar_campanas(db, ids, cambios, USUARIO)


# ── The single edit, through the step ───────────────────────────────


def test_the_single_edit_is_unchanged_one_audit_row_not_bulk_queued_and_committed(engine: Engine) -> None:
    g = w.grupo(engine, [ROUTERS])
    cid = w.campana(engine, [g], nombre="Rebate Q4 2026")
    body = {
        "nombre": "Rebate Q4 2026 bis",
        "fecha_desde": date(2026, 11, 1),
        "fecha_hasta": date(2026, 12, 15),
        "tipo": "por_unidad",
        "monto_unit": "12",
        "moneda": "ARS",
        "grupo_ids": [g],
    }

    with _session(engine) as db:
        service.editar_campana(db, cid, SellOutCampanaIn.model_validate(body), USUARIO)

    fila = _fila(engine, cid)  # read from another connection: committed
    assert (fila["nombre"], fila["fecha_hasta"], fila["monto_unit"]) == (
        "Rebate Q4 2026 bis",
        date(2026, 12, 15),
        Decimal("12.00"),
    )
    [(valores, masivo)] = _audits(engine)
    assert (valores["campana_id"], valores["fecha_hasta"], masivo) == (cid, "2026-12-15", False)
    assert _queued(engine) == [cid]


def test_the_step_alone_does_not_commit(engine: Engine) -> None:
    g = w.grupo(engine, [ROUTERS])
    cid = w.campana(engine, [g])
    with _session(engine) as db:
        data = service.entrada_guardada(db, db.get(SellOutCampana, cid))
        data.fecha_hasta = date(2026, 12, 31)
        service.editar_campana_sin_commit(db, cid, data, USUARIO, es_masivo=True)
        db.rollback()

    assert _fila(engine, cid)["fecha_hasta"] == date(2026, 11, 30)
    assert _audits(engine) == [] and _queued(engine) == []


# ── The bulk edit ───────────────────────────────────────────────────


def test_only_the_filled_fields_change_and_everything_else_keeps_its_stored_value(engine: Engine) -> None:
    g = w.grupo(engine, [ROUTERS])
    a = w.campana(engine, [g], nombre="MARCA PROG 3.0", descripcion="Q4", tope_unidades=50, acumulable=False)
    b = w.campana(engine, [g], nombre="MODELO 8180", tipo="porcentaje", monto_unit=None, porcentaje="5.5")
    antes = {cid: _sin_marcas(_fila(engine, cid)) for cid in (a, b)}

    assert _editar(engine, [b, a], fecha_hasta=date(2026, 12, 31)) == ([a, b], [])

    for cid in (a, b):
        assert _sin_marcas(_fila(engine, cid)) == {**antes[cid], "fecha_hasta": date(2026, 12, 31)}

    _editar(engine, [a], acumulable=True, fecha_desde=date(2026, 10, 1))
    assert _sin_marcas(_fila(engine, a)) == {
        **antes[a],
        "fecha_desde": date(2026, 10, 1),
        "fecha_hasta": date(2026, 12, 31),
        "acumulable": True,
    }


def test_an_al_cobro_campaign_keeps_the_rate_set_at_payment(engine: Engine) -> None:
    g = w.grupo(engine, [ROUTERS])
    cid = w.campana(engine, [g], moneda="USD", tc_modo="al_cobro")
    with _session(engine) as db:
        service.definir_tipo_cambio(db, cid, Decimal("1450.5"), USUARIO)
    antes = _fila(engine, cid)

    _editar(engine, [cid], fecha_hasta=date(2026, 12, 31))

    despues = _fila(engine, cid)
    assert (despues["tc_modo"], despues["tipo_cambio"], despues["tc_definido_en"]) == (
        "al_cobro",
        Decimal("1450.500000"),
        antes["tc_definido_en"],
    )


def test_groups_items_shares_and_program_are_kept(engine: Engine) -> None:
    routers, switches = w.grupo(engine, [ROUTERS]), w.grupo(engine, [SWITCHES])
    por_unidad = w.campana(engine, [switches, routers])
    w.monto_item(engine, por_unidad, ROUTER, "7.25")
    total = w.monto_total(engine, [routers, switches], "1000")
    w.reparto(engine, total, ROUTER, porcentaje="40")
    w.reparto(engine, total, SWITCH, monto="300")
    w.execute(engine, "INSERT INTO sell_out_programas (nombre, usuario_id) VALUES ('MARCA PROG 3.0', 7)")
    w.execute(engine, "UPDATE sell_out_campanas SET programa_id = (SELECT id FROM sell_out_programas)")
    antes = {cid: (_hijos(engine, cid), _fila(engine, cid)["programa_id"]) for cid in (por_unidad, total)}

    assert _editar(engine, [por_unidad, total], fecha_desde=date(2026, 10, 15)) == ([por_unidad, total], [])

    for cid in (por_unidad, total):
        assert (_hijos(engine, cid), _fila(engine, cid)["programa_id"]) == antes[cid]
        assert antes[cid][1] is not None


def test_inverted_dates_name_the_campaign_and_both_dates(engine: Engine) -> None:
    g = w.grupo(engine, [ROUTERS])
    cid = w.campana(engine, [g], nombre="Rebate Q4 2026")

    with pytest.raises(edicion_masiva.SellOutEdicionRechazada) as exc:
        _editar(engine, [cid], fecha_hasta=date(2026, 10, 31))

    assert exc.value.rechazadas == [
        (
            cid,
            "Rebate Q4 2026",
            "La campaña Rebate Q4 2026 quedaría con la fecha hasta (31/10/2026) antes que la fecha desde (01/11/2026)",
        )
    ]
    assert str(exc.value) == "No se editó ninguna campaña: 1 no se puede editar."
    assert exc.value.reintentar is False


def test_voided_and_unknown_campaigns_are_named(engine: Engine) -> None:
    g = w.grupo(engine, [ROUTERS])
    anulada = w.campana(engine, [g], nombre="MODELO 8180", estado="anulada")

    with pytest.raises(edicion_masiva.SellOutEdicionRechazada) as exc:
        _editar(engine, [999999, anulada], acumulable=False)

    assert exc.value.rechazadas == [
        (anulada, "MODELO 8180", f"La campaña {anulada} está anulada"),
        (999999, None, "La campaña 999999 no existe"),
    ]


def test_a_validation_error_of_the_step_is_named_with_its_message(engine: Engine) -> None:
    g = w.grupo(engine, [ROUTERS])
    cid = w.monto_total(engine, [g], "100", nombre="Rebate Q4 2026")
    w.reparto(engine, cid, ROUTER, monto="150")  # stored over the total by hand: the step's own rule refuses it

    with pytest.raises(edicion_masiva.SellOutEdicionRechazada) as exc:
        _editar(engine, [cid], fecha_hasta=date(2026, 12, 31))

    assert exc.value.rechazadas == [
        (cid, "Rebate Q4 2026", "El reparto (150.00) supera el monto total (100.00) en 50.00"),
    ]


def test_it_is_all_or_nothing_a_valid_row_is_not_changed_when_another_is_refused(engine: Engine) -> None:
    g = w.grupo(engine, [ROUTERS])
    valida = w.campana(engine, [g], desde=date(2026, 10, 1))
    invertida = w.campana(engine, [g], nombre="Rebate Q4 2026")
    posterior = w.campana(engine, [g], desde=date(2026, 10, 1))  # after the refused one in lock order
    antes = {cid: _fila(engine, cid) for cid in (valida, invertida, posterior)}

    with pytest.raises(edicion_masiva.SellOutEdicionRechazada) as exc:
        _editar(engine, [valida, invertida, posterior], fecha_hasta=date(2026, 10, 15))

    assert [r[0] for r in exc.value.rechazadas] == [invertida]
    assert {cid: _fila(engine, cid) for cid in antes} == antes
    assert _audits(engine) == [] and _queued(engine) == []


def test_each_changed_campaign_writes_one_bulk_audit_row_and_is_requeued_with_what_it_shared(engine: Engine) -> None:
    routers, switches = w.grupo(engine, [ROUTERS]), w.grupo(engine, [SWITCHES])
    a, b = w.campana(engine, [routers]), w.campana(engine, [switches])
    compartia = w.campana(engine, [routers], acumulable=False)  # shares products with `a`, not edited
    w.campana(engine, [w.grupo(engine, [{"item_id": 950}])])  # never shares

    assert _editar(engine, [a, b], fecha_hasta=date(2026, 12, 31)) == ([a, b], [])

    audits = _audits(engine)
    assert [(v["campana_id"], v["fecha_hasta"], masivo) for v, masivo in audits] == [
        (a, "2026-12-31", True),
        (b, "2026-12-31", True),
    ]
    assert _queued(engine) == sorted([a, b, compartia])


def test_a_campaign_already_with_the_values_is_sin_cambio_and_writes_nothing(engine: Engine) -> None:
    igual = w.campana(engine, [w.grupo(engine, [ROUTERS])], hasta=date(2026, 12, 31), acumulable=False)
    distinta = w.campana(engine, [w.grupo(engine, [SWITCHES])])  # shares nothing: it does not requeue `igual`
    antes = _fila(engine, igual)

    assert _editar(engine, [igual, distinta], fecha_hasta=date(2026, 12, 31), acumulable=False) == (
        [distinta],
        [igual],
    )

    assert _fila(engine, igual) == antes  # not even `updated_at`
    assert [v["campana_id"] for v, _ in _audits(engine)] == [distinta]
    assert _queued(engine) == [distinta]
