"""Stored markups follow a costo SI recompute (sell-in-costo-si T3 PR 4). Owner L15: "se tienen que recalcular todos
los costos posteriores"; D4: prices never move; orchestrator: inline is OK, but "cannot compute" never passes silently.
The pricing callback runs inside `queue.drenar`'s product transaction, sees the NEW average, also covers the combos
that contain the product, and a pricing gap never rolls the average back. Uses its own world (the engine's tables plus
pricing's). Invented data."""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from typing import Iterator

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import sessionmaker

from app.models.comision_config import SubcategoriaGrupo
from app.models.comision_versionada import ComisionAdicionalCuota, ComisionBase, ComisionVersion
from app.models.oferta_ml import OfertaML
from app.models.pricing_constants import PricingConstants
from app.models.producto import ProductoPricing
from app.models.publicacion_ml import PublicacionML
from app.services import recalcular_markups_service as rms
from app.services.costo_si import despues, lote, queue
from app.services.costo_si.despues import pricing as despues_pricing
from tests.services.costo_si import _world as w
from tests.services.sell._schema import throwaway_schema

pytestmark = pytest.mark.postgres

P, COMBO, GEMELO = 5601, 5602, 5603
PRECIO = 250_000.0
_PRICING = [
    ProductoPricing.__table__,
    SubcategoriaGrupo.__table__,
    ComisionVersion.__table__,
    ComisionBase.__table__,
    ComisionAdicionalCuota.__table__,
    PricingConstants.__table__,
    PublicacionML.__table__,
    OfertaML.__table__,
]


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with throwaway_schema("costo_si_pricing", [*w.TABLES, *_PRICING], w.STUBS, after=w.install) as engine:
        yield engine


@pytest.fixture(autouse=True)
def _solo_pricing(engine: Engine, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Only this area's callback is registered; shipping is not what this tests (every product ships at 0)."""
    monkeypatch.setattr(despues, "_CALLBACKS", {})
    monkeypatch.setattr(despues, "_cargados", True)
    despues.registrar("pricing", despues_pricing.recalcular_markups)
    monkeypatch.setattr(rms, "resolver_costos_envio_batch", lambda db, ids: {})
    yield
    w.run(engine, "DELETE FROM productos_pricing")
    w.run(engine, "DELETE FROM comisiones_base")
    w.run(engine, "DELETE FROM comisiones_versiones")
    w.clean(engine)


def _comision(engine: Engine) -> None:
    w.run(
        engine, "INSERT INTO comisiones_versiones (id, nombre, fecha_desde, activo) VALUES (1, 'T', '2000-01-01', true)"
    )
    w.run(engine, "INSERT INTO comisiones_base (version_id, grupo_id, comision_base) VALUES (1, 1, 12)")


def _pricing(engine: Engine, item_id: int) -> None:
    """Through the ORM, so the model's defaults apply (999 = a stale markup nobody recomputed yet)."""
    with sessionmaker(bind=engine)() as db:
        db.add(
            ProductoPricing(
                item_id=item_id, precio_lista_ml=PRECIO, markup_calculado=999, precio_pvp=PRECIO * 1.2, markup_pvp=999
            )
        )
        db.commit()


def _producto_con_costo_si(engine: Engine) -> None:
    """P: list cost USD 40 today, but 25 on the date its first sell in applies (S2), so its costo SI (25) differs
    from its list cost. COMBO = 2 x P (not a PC)."""
    w.producto(engine, P, costo="40")
    w.costo_lista(engine, P, datetime(2026, 9, 1), "25")
    w.producto(engine, COMBO, costo="90")
    w.run(engine, "UPDATE productos_erp SET iva = 21")
    w.run(
        engine,
        "INSERT INTO combo_componentes (combo_item_id, componente_item_id, cantidad) VALUES (:c, :p, 2)",
        c=COMBO,
        p=P,
    )
    w.tipo_cambio(engine, date.today(), 1000)
    w.bono_marca(engine, "3.6", date(2026, 10, 1), date(2026, 12, 31))  # queues P from 10-01


def _drenar(engine: Engine) -> queue.Drenado:
    return queue.drenar(
        sessionmaker(bind=engine, autoflush=False),
        datetime.now(UTC) + timedelta(minutes=1),
        is_transient=lambda exc: False,
    )


def _fila(engine: Engine, item_id: int) -> tuple:
    return w.rows(
        engine,
        "SELECT precio_lista_ml, markup_calculado, precio_pvp, markup_pvp FROM productos_pricing WHERE item_id = :i",
        i=item_id,
    )[0]


def test_the_callback_sees_the_new_average_and_covers_the_combos_containing_the_product(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    vistos = []

    def probe(db, ids):
        vistos.append({i: lote.actuales(db, [i])[i].fuente for i in ids})
        return []

    monkeypatch.setattr(despues_pricing, "recalcular_markups_guardados", probe)
    _producto_con_costo_si(engine)

    assert _drenar(engine).cambiados == 1

    assert vistos == [{P: lote.FUENTE_COSTO_SI, COMBO: lote.FUENTE_COSTO_SI}]


def test_the_stored_markups_move_to_costo_si_and_the_prices_stay(engine: Engine) -> None:
    """After the recompute, P's stored markups equal those of a twin whose list cost IS P's costo SI."""
    _comision(engine)
    _producto_con_costo_si(engine)
    _pricing(engine, P)
    _pricing(engine, COMBO)

    assert _drenar(engine).cambiados == 1

    promedio = w.rows(engine, "SELECT promedio_usd FROM costo_si_pasos WHERE item_id = :i ORDER BY orden DESC", i=P)[0][
        0
    ]
    w.producto(engine, GEMELO, costo=str(promedio))
    w.run(engine, "UPDATE productos_erp SET iva = 21")
    _pricing(engine, GEMELO)
    with sessionmaker(bind=engine)() as db:
        assert rms.recalcular_markups_guardados(db, [GEMELO]) == []
        db.commit()
    precio, markup, pvp, markup_pvp = _fila(engine, P)
    assert (precio, pvp) == (PRECIO, PRECIO * 1.2)  # D4
    assert markup != 999 and markup_pvp != 999
    assert (markup, markup_pvp) == _fila(engine, GEMELO)[1::2]
    assert _fila(engine, COMBO)[1::2] != (999, 999)  # the combo containing P was recomputed too (L15)


def test_a_markup_that_cannot_be_recomputed_is_logged_and_the_average_still_commits(
    engine: Engine, caplog: pytest.LogCaptureFixture
) -> None:
    """No commission configured: the markup is skipped with a warning naming the product and the reason, and the
    new costo SI is saved anyway."""
    _producto_con_costo_si(engine)
    _pricing(engine, P)

    with caplog.at_level(logging.WARNING, logger=rms.logger.name):
        drenado = _drenar(engine)

    assert (drenado.cambiados, drenado.fallidos) == (1, {})
    assert w.pasos(engine, P) != []
    assert _fila(engine, P)[1] == 999  # left as it was: nothing to recompute it with
    assert any(
        str(P) in r.getMessage() and "markup_calculado" in r.getMessage() and rms.SIN_COMISION in r.getMessage()
        for r in caplog.records
    )
