"""Bulk edit of sell-out campaigns and its preview (edición masiva M1, S2-S5), on Postgres (`_world`).

Each row goes through the single edit's own step (`campanas.editar_campana_sin_commit`): the full body is rebuilt
from the stored campaign and only the filled fields (`fecha_desde`, `fecha_hasta`, `acumulable`) are overlaid. All
or nothing, every refused row named. The preview writes nothing, and its numbers equal, line for line, what the
apply plus the `sell_out.drain` rebuild do on the same data: caps, stacking and fixed-total splits included.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Iterator, Optional

import pytest
from sqlalchemy import Engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from app.models.auditoria import TipoAccion
from app.models.sell_out import SellOutCampana
from app.schemas.sell_out import SellOutCampanaIn
from app.services.sell_out import asignacion, edicion_masiva, queue, reparto
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


def _session(engine: Engine) -> Session:
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


def _editar(engine: Engine, ids: list[int], **cambios: object) -> tuple[list[int], list[int]]:
    with _session(engine) as db:
        return edicion_masiva.editar_campanas(db, ids, cambios, USUARIO)


def _previa(engine: Engine, ids: list[int], **cambios: object) -> dict:
    with _session(engine) as db:
        return edicion_masiva.previa_edicion(db, ids, cambios, USUARIO)


def _drain(engine: Engine) -> None:
    """What the `sell_out.drain` handler does with one batch: claim, rebuild, ack, in one transaction."""
    with _session(engine) as db:
        claimed = queue.claim_batch(db, queue.BATCH_SIZE)
        asignacion.recalcular(db, claimed)
        queue.ack(db, claimed)
        db.commit()


def _consumir(engine: Engine) -> None:
    """The world's starting `sell_out_consumos`: campaigns written with SQL were never queued."""
    with _session(engine) as db:
        queue.enqueue(db, [cid for (cid,) in db.query(SellOutCampana.id)])
        db.commit()
    _drain(engine)


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


# ── The preview ─────────────────────────────────────────────────────
#
# The preview runs the edit AND the rebuild the drain would run, then rolls both back: its numbers must equal, line
# for line, what the apply plus a drain do on the same data, linked campaigns outside the selection included.

TABLAS = (
    "sell_out_campanas",
    "sell_out_campana_grupos",
    "sell_out_campana_items",
    "sell_out_consumos",
    "sell_out_dirty",
    "auditoria",
)


def _snapshot(engine: Engine) -> tuple:
    with engine.connect() as conn:
        return tuple(conn.execute(text(f"SELECT * FROM {tabla} ORDER BY 1")).all() for tabla in TABLAS)


def _claves(engine: Engine, cid: int) -> dict:
    return {(c[1], c[2]): c for c in w.consumos(engine, cid)}


def _diferencia(antes: dict, despues: dict) -> dict:
    """What the rebuild took away from and gave to one campaign: lines gone or new, units down or up, and the signed
    money of the lines that leave, enter, shrink or grow (a deduction's lines are negative)."""
    cero = {"lineas": 0, "unidades": 0, "monto": Decimal(0)}
    salen, entran = dict(cero), dict(cero)
    for clave in antes.keys() | despues.keys():
        previo, nuevo = antes.get(clave), despues.get(clave)
        unidades = (nuevo[5] if nuevo else 0) - (previo[5] if previo else 0)
        salen["unidades"] += max(-unidades, 0)
        entran["unidades"] += max(unidades, 0)
        if nuevo is None:
            salen["lineas"] += 1
            salen["monto"] += previo[6]
        elif previo is None:
            entran["lineas"] += 1
            entran["monto"] += nuevo[6]
        elif abs(nuevo[6]) < abs(previo[6]):
            salen["monto"] += previo[6] - nuevo[6]
        elif abs(nuevo[6]) > abs(previo[6]):
            entran["monto"] += nuevo[6] - previo[6]
    return {"salen": salen, "entran": entran}


def _comparar(engine: Engine, ids: list[int], **cambios: object) -> tuple[dict, dict]:
    """Preview (asserting it leaves every table byte-identical), then apply and drain: `(previa, {campana_id:
    what really left and entered})` over every campaign with consumptions."""
    with engine.connect() as conn:
        todas = [cid for (cid,) in conn.execute(text("SELECT id FROM sell_out_campanas ORDER BY id"))]
    antes_tablas = _snapshot(engine)
    antes = {cid: _claves(engine, cid) for cid in todas}
    previa = _previa(engine, ids, **cambios)
    assert _snapshot(engine) == antes_tablas
    _editar(engine, ids, **cambios)
    _drain(engine)
    real = {cid: _diferencia(antes[cid], _claves(engine, cid)) for cid in todas}
    return previa, real


def _vista(previa: dict) -> dict:
    """`{campana_id: {salen, entran}}` of every campaign the preview lists, selected or linked."""
    return {c["id"]: {"salen": c["salen"], "entran": c["entran"]} for c in previa["cambian"] + previa["vinculadas"]}


def _movidas(real: dict, previa: dict) -> dict:
    """The edited campaigns (always listed) and every other campaign whose consumptions moved."""
    editadas = {c["id"] for c in previa["cambian"]}
    return {
        cid: d for cid, d in real.items() if cid in editadas or any(d["salen"].values()) or any(d["entran"].values())
    }


def test_the_preview_writes_nothing(engine: Engine) -> None:
    g = w.grupo(engine, [ROUTERS])
    a = w.campana(engine, [g])
    invertida = w.campana(engine, [g], desde=date(2026, 12, 1), hasta=date(2026, 12, 31))
    w.venta(engine, "fuera", ROUTER, 2, date(2026, 11, 20))
    _consumir(engine)
    antes = _snapshot(engine)

    previa = _previa(engine, [a, invertida, 999999], fecha_hasta=date(2026, 11, 10))

    assert _snapshot(engine) == antes
    assert [c["id"] for c in previa["cambian"]] == [a]
    assert [r["id"] for r in previa["rechazadas"]] == [invertida, 999999]
    assert previa["cambian"][0]["salen"] == {"lineas": 1, "unidades": 2, "monto": Decimal("20.00")}


def test_the_preview_equals_the_apply_and_the_rebuild_when_no_cap_binds(engine: Engine) -> None:
    g = w.grupo(engine, [ROUTERS])
    ars = w.campana(engine, [g], nombre="Rebate Q4 2026")
    usd = w.campana(engine, [g], nombre="MARCA PROG 3.0", moneda="USD", tc_modo="fijo", tipo_cambio="1000")
    w.venta(engine, "fuera", ROUTER, 4, date(2026, 10, 25))  # enters: the new start is earlier
    w.venta(engine, "ml", ROUTER, 1, date(2026, 10, 28))  # enters
    w.venta(engine, "fuera", ROUTER, 2, date(2026, 11, 10))  # stays
    w.venta(engine, "tn", ROUTER, 3, date(2026, 11, 25))  # leaves: the new end is earlier
    w.venta(engine, "fuera", ROUTER, 5, date(2026, 12, 5))  # outside both ranges
    _consumir(engine)

    previa, real = _comparar(engine, [ars, usd], fecha_desde=date(2026, 10, 20), fecha_hasta=date(2026, 11, 15))

    assert _vista(previa) == _movidas(real, previa)
    assert real[ars]["salen"] == {"lineas": 1, "unidades": 3, "monto": Decimal("30.00")}
    assert real[ars]["entran"] == {"lineas": 2, "unidades": 5, "monto": Decimal("50.00")}
    assert previa["vinculadas"] == []
    totales = previa["totales"]
    assert (totales["salen"]["lineas"], totales["entran"]["lineas"], totales["entran"]["unidades"]) == (2, 4, 10)
    assert totales["salen"]["montos"] == [
        {"moneda": "ARS", "monto": Decimal("30.00")},
        {"moneda": "USD", "monto": Decimal("30.00")},
    ]
    assert totales["entran"]["montos"] == [
        {"moneda": "ARS", "monto": Decimal("50.00")},
        {"moneda": "USD", "monto": Decimal("50.00")},
    ]


def test_an_earlier_sale_entering_under_a_full_cap_takes_the_units_of_a_later_line(engine: Engine) -> None:
    g = w.grupo(engine, [ROUTERS])
    cid = w.campana(engine, [g], tope_unidades=3)
    w.venta(engine, "fuera", ROUTER, 3, date(2026, 11, 10))  # credited today, it fills the cap
    w.venta(engine, "fuera", ROUTER, 4, date(2026, 10, 25))  # enters, earlier: it takes the cap
    _consumir(engine)

    previa, real = _comparar(engine, [cid], fecha_desde=date(2026, 10, 20))

    assert _vista(previa) == _movidas(real, previa)
    assert real[cid]["salen"] == {"lineas": 1, "unidades": 3, "monto": Decimal("30.00")}
    assert real[cid]["entran"] == {"lineas": 1, "unidades": 3, "monto": Decimal("30.00")}


def test_units_a_shortened_range_frees_under_a_full_cap_go_to_a_later_sale_already_inside(engine: Engine) -> None:
    g = w.grupo(engine, [ROUTERS])
    cid = w.campana(engine, [g], tope_unidades=3)
    w.venta(engine, "fuera", ROUTER, 3, date(2026, 11, 5))  # credited, it fills the cap
    w.venta(engine, "fuera", ROUTER, 4, date(2026, 11, 20))  # inside the dates, not credited: no cap left
    _consumir(engine)

    previa, real = _comparar(engine, [cid], fecha_desde=date(2026, 11, 10))

    assert _vista(previa) == _movidas(real, previa)
    assert real[cid]["salen"] == {"lineas": 1, "unidades": 3, "monto": Decimal("30.00")}
    assert real[cid]["entran"] == {"lineas": 1, "unidades": 3, "monto": Decimal("30.00")}  # no credit is lost


def test_turning_a_campaign_non_stackable_takes_units_from_a_linked_campaign_outside_the_selection(
    engine: Engine,
) -> None:
    g = w.grupo(engine, [ROUTERS])
    elegida = w.campana(engine, [g], nombre="Rebate Q4 2026")  # lower id: it takes precedence
    vinculada = w.campana(engine, [g], nombre="MODELO 8180")  # not selected, shares the product
    w.venta(engine, "fuera", ROUTER, 2, date(2026, 11, 10))
    _consumir(engine)

    previa, real = _comparar(engine, [elegida], acumulable=False)

    assert _vista(previa) == _movidas(real, previa)
    assert previa["vinculadas"] == [
        {
            "id": vinculada,
            "nombre": "MODELO 8180",
            "moneda": "ARS",
            "en_seleccion": False,
            "incluye_pendientes": False,
            "salen": {"lineas": 1, "unidades": 2, "monto": Decimal("20.00")},
            "entran": {"lineas": 0, "unidades": 0, "monto": Decimal(0)},
        }
    ]
    assert previa["totales"]["salen"]["lineas"] == 1


def test_a_monto_total_campaign_loses_only_the_share_of_products_left_with_no_sale(engine: Engine) -> None:
    """A fixed total spreads each product's share over the sales left in the dates (`reparto.repartir`): a product
    that keeps a sale keeps its whole share, moved; only the share of a product left with NO sale goes."""
    g = w.grupo(engine, [ROUTERS, SWITCHES])
    cid = w.monto_total(engine, [g], "1000", nombre="Rebate Q4 2026")
    w.reparto(engine, cid, ROUTER, porcentaje="60")
    w.reparto(engine, cid, SWITCH, porcentaje="40")
    w.venta(engine, "fuera", ROUTER, 2, date(2026, 11, 10))  # stays: ROUTER keeps its 600
    w.venta(engine, "fuera", ROUTER, 2, date(2026, 11, 25))  # leaves, its money moves to the other ROUTER sales
    w.venta(engine, "fuera", SWITCH, 1, date(2026, 11, 25))  # leaves, SWITCH has no sale left: 400 unassigned
    w.venta(engine, "fuera", ROUTER, 1, date(2026, 10, 25))  # enters, diluting ROUTER's rows
    _consumir(engine)

    previa, real = _comparar(engine, [cid], fecha_desde=date(2026, 10, 20), fecha_hasta=date(2026, 11, 15))

    assert _vista(previa) == _movidas(real, previa)
    neto = real[cid]["entran"]["monto"] - real[cid]["salen"]["monto"]
    assert neto == Decimal("-400.00")  # only SWITCH's share stops being credited


def test_a_sale_entering_on_a_share_that_had_no_sale_credits_the_whole_share(engine: Engine) -> None:
    g = w.grupo(engine, [ROUTERS, SWITCHES])
    cid = w.monto_total(engine, [g], "1000")
    w.reparto(engine, cid, ROUTER, porcentaje="60")
    w.reparto(engine, cid, SWITCH, porcentaje="40")  # no sale in the dates: unassigned today
    w.venta(engine, "fuera", ROUTER, 2, date(2026, 11, 10))
    w.venta(engine, "fuera", SWITCH, 1, date(2026, 10, 25))  # enters: SWITCH's 400 is credited
    _consumir(engine)

    previa, real = _comparar(engine, [cid], fecha_desde=date(2026, 10, 20))

    assert _vista(previa) == _movidas(real, previa)
    assert real[cid]["entran"] == {"lineas": 1, "unidades": 1, "monto": Decimal("400.00")}
    assert previa["totales"]["entran"]["montos"] == [{"moneda": "ARS", "monto": Decimal("400.00")}]


def test_a_negative_monto_total_keeps_each_line_money_on_the_line_side(engine: Engine) -> None:
    """A deduction's lines are negative: a leaving -100 line is `salen` -100, never +100 entering."""
    g = w.grupo(engine, [ROUTERS])
    cid = w.monto_total(engine, [g], "-200", nombre="Rebate Q4 2026")
    w.reparto(engine, cid, ROUTER, porcentaje="100")
    w.venta(engine, "fuera", ROUTER, 1, date(2026, 11, 10))  # stays, takes the whole -200
    w.venta(engine, "fuera", ROUTER, 1, date(2026, 11, 25))  # leaves with its -100
    _consumir(engine)

    previa, real = _comparar(engine, [cid], fecha_hasta=date(2026, 11, 15))

    assert _vista(previa) == _movidas(real, previa)
    assert real[cid]["salen"] == {"lineas": 1, "unidades": 1, "monto": Decimal("-100.00")}
    assert real[cid]["entran"] == {"lineas": 0, "unidades": 0, "monto": Decimal("-100.00")}  # the stayer grew
    assert previa["totales"]["salen"]["montos"] == [{"moneda": "ARS", "monto": Decimal("-100.00")}]
    assert previa["totales"]["entran"]["montos"] == [{"moneda": "ARS", "monto": Decimal("-100.00")}]


SIN_IVA = 9999  # a product with no VAT rate: a campaign loaded with VAT cannot be rebuilt over its sales


def test_a_rebuild_that_would_fail_is_refused_in_spanish_naming_the_campaign(engine: Engine) -> None:
    w.execute(
        engine,
        "INSERT INTO productos_erp (item_id, codigo, descripcion, marca, categoria) "
        "VALUES (:i, 'C9999', 'Producto', 'MARCA PROG', 'Routers')",
        i=SIN_IVA,
    )
    try:
        cid = w.campana(engine, [w.grupo(engine, [{"item_id": SIN_IVA}])], nombre="Rebate Q4 2026")
        w.execute(engine, "UPDATE sell_out_campanas SET monto_incluye_iva = true")
        w.venta(engine, "fuera", SIN_IVA, 1, date(2026, 12, 10))  # outside today: the rebuild does not fail yet
        _consumir(engine)
        antes = _snapshot(engine)

        with pytest.raises(service.SellOutError) as exc:
            _previa(engine, [cid], fecha_hasta=date(2026, 12, 31))

        assert str(exc.value) == (
            "La edición no se puede recalcular: la campaña Rebate Q4 2026 se carga con IVA y el producto 9999 "
            "(C9999) no tiene IVA"
        )
        assert _snapshot(engine) == antes
    finally:
        w.clean(engine)  # its group's filter references the product
        w.execute(engine, "DELETE FROM productos_erp WHERE item_id = :i", i=SIN_IVA)


@pytest.mark.parametrize(
    ("causa", "item_id", "fecha", "origen", "mensaje"),
    [
        (
            "sin_tipo_cambio",
            None,
            date(2026, 11, 2),
            None,
            "la campaña Rebate Q4 2026 no tiene cotización BNA para convertir la venta del 02/11/2026",
        ),
        (
            "producto_sin_iva",
            ROUTER,
            None,
            None,
            "la campaña Rebate Q4 2026 se carga con IVA y el producto 2964 (C2964) no tiene IVA",
        ),
        (
            "producto_sin_iva",
            None,
            None,
            None,
            "la campaña Rebate Q4 2026 se carga con IVA y un producto que alcanza no tiene IVA",
        ),
        (
            "reparto_invalido",
            ROUTER,
            None,
            reparto.RepartoInvalido("x", causa="signo", item_id=ROUTER),
            "en la campaña Rebate Q4 2026, el reparto del producto 2964 tiene que tener el signo del monto total",
        ),
        (
            "monto_negativo",
            None,
            None,
            None,
            "la campaña Rebate Q4 2026 daría un monto negativo, y solo una campaña por monto total puede ser negativa",
        ),
    ],
)
def test_each_rebuild_refusal_is_explained_from_its_fields(
    engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
    causa: str,
    item_id: Optional[int],
    fecha: Optional[date],
    origen: Optional[Exception],
    mensaje: str,
) -> None:
    """The reason comes from the error's fields (`campana_id`, `causa`, `item_id`, `fecha`), never from its text."""
    cid = w.campana(engine, [w.grupo(engine, [ROUTERS])], nombre="Rebate Q4 2026")

    def _falla(db: Session, campana_ids: list[int]) -> None:
        error = asignacion.SellOutAsignacionError(
            "texto interno que nadie lee", campana_id=cid, causa=causa, item_id=item_id, fecha=fecha
        )
        raise error from origen

    monkeypatch.setattr(asignacion, "recalcular", _falla)

    with pytest.raises(service.SellOutError) as exc:
        _previa(engine, [cid], fecha_hasta=date(2026, 12, 31))

    assert str(exc.value) == f"La edición no se puede recalcular: {mensaje}"


AVISO = "incluye cambios pendientes que no causa esta edición"


def _pendiente(engine: Engine, cid: int) -> None:
    """A queue row nobody drained yet: the stored lines of `cid` are behind."""
    w.execute(engine, "INSERT INTO sell_out_dirty (campana_id) VALUES (:c)", c=cid)


def test_a_campaign_with_pending_work_is_flagged_and_its_numbers_are_unchanged(engine: Engine) -> None:
    con = w.campana(engine, [w.grupo(engine, [ROUTERS])], nombre="Rebate Q4 2026")
    sin = w.campana(engine, [w.grupo(engine, [SWITCHES])], nombre="MODELO 8180")
    w.venta(engine, "fuera", ROUTER, 2, date(2026, 11, 10))
    _consumir(engine)
    w.venta(engine, "fuera", ROUTER, 1, date(2026, 11, 12))  # inside the dates, not drained yet
    _pendiente(engine, con)

    previa, real = _comparar(engine, [con, sin], acumulable=False)  # the edit by itself moves nothing

    por_id = {c["id"]: c for c in previa["cambian"]}
    assert (por_id[con]["incluye_pendientes"], por_id[sin]["incluye_pendientes"]) == (True, False)
    assert previa["aviso_pendientes"] == AVISO
    assert _vista(previa) == _movidas(real, previa)  # the numbers, as before the flag: the pending line included
    assert por_id[con]["entran"] == {"lineas": 1, "unidades": 1, "monto": Decimal("10.00")}


def test_a_linked_campaign_with_pending_work_is_flagged_in_vinculadas(engine: Engine) -> None:
    g = w.grupo(engine, [ROUTERS])
    elegida = w.campana(engine, [g], nombre="Rebate Q4 2026")
    vinculada = w.campana(engine, [g], nombre="MODELO 8180")
    w.venta(engine, "fuera", ROUTER, 2, date(2026, 11, 10))
    _consumir(engine)
    _pendiente(engine, vinculada)

    previa, real = _comparar(engine, [elegida], acumulable=False)

    assert _vista(previa) == _movidas(real, previa)
    [fila] = previa["vinculadas"]
    assert (fila["id"], fila["incluye_pendientes"]) == (vinculada, True)
    assert previa["cambian"][0]["incluye_pendientes"] is False
    assert previa["aviso_pendientes"] == AVISO


def test_no_pending_work_no_flag_and_no_notice(engine: Engine) -> None:
    cid = w.campana(engine, [w.grupo(engine, [ROUTERS])])
    _consumir(engine)

    previa = _previa(engine, [cid], acumulable=False)

    assert previa["cambian"][0]["incluye_pendientes"] is False
    assert previa["aviso_pendientes"] is None


def _lecturas(engine: Engine, monkeypatch: pytest.MonkeyPatch, ids: list[int]) -> int:
    """Statements the preview runs AFTER its rolled-back loop (whose step is per campaign, like the apply's)."""
    sentencias: list[str] = []
    marca: list[int] = []
    aplicar = edicion_masiva._aplicar

    def _marcar(*args: object, **kwargs: object) -> tuple:
        resultado = aplicar(*args, **kwargs)
        marca.append(len(sentencias))
        return resultado

    def _contar(conn, cursor, statement, parameters, context, executemany) -> None:
        sentencias.append(statement)

    monkeypatch.setattr(edicion_masiva, "_aplicar", _marcar)
    event.listen(engine, "before_cursor_execute", _contar)
    try:
        _previa(engine, ids, fecha_hasta=date(2026, 12, 31))
    finally:
        event.remove(engine, "before_cursor_execute", _contar)
    return len(sentencias) - marca[0]


def test_the_preview_reads_with_a_fixed_number_of_queries_whatever_the_number_of_campaigns(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    g = w.grupo(engine, [ROUTERS])
    ids = [w.campana(engine, [g], nombre=f"MODELO 8180 {n}") for n in range(6)]
    w.venta(engine, "fuera", ROUTER, 1, date(2026, 11, 10))
    w.venta(engine, "fuera", ROUTER, 1, date(2026, 12, 10))
    _consumir(engine)

    assert _lecturas(engine, monkeypatch, ids[:2]) == _lecturas(engine, monkeypatch, ids)
