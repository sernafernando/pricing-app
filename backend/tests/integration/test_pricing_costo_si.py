"""Pricing computes with costo SI (sell-in-costo-si T3 PR 4). Spec: handoffs/sell-in-costo-si-feature.md S13 ("costo SI
is THE cost for everything ... pricing calculator, Productos markups"), D1 (markups over costo SI), D4 ("el precio de
una venta no se toca, ni de las publicaciones"), owner L18 (costo SI in the product's cost currency).

Method: product X has list cost USD 100 and costo SI USD 80; its twin T has list cost USD 80 and no costo SI. Both
products are otherwise identical, so every calculation for X must equal T's. Before T3 they differed, because X was
priced at 100. The reader (`lote.actuales`) is tested on Postgres by PR 1; here it answers costo SI for X and the
list cost ('lista', Q1) for everything else. Invented data."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.api.endpoints import pricing as ep
from app.api.endpoints import productos_pricing as epp
from app.api.endpoints.productos_shared import CalculoPVPMasivoRequest, CalculoWebMasivoRequest, RebateUpdate
from app.models.comision_versionada import ComisionBase, ComisionVersion
from app.models.producto import ProductoERP, ProductoPricing
from app.models.tipo_cambio import TipoCambio
from app.services import recalcular_markups_service as rms
from app.services.costo_si import lote
from tests.costo_si_lista import actuales_lista

X, T, ARS_SI, OTRO = 9101, 9102, 9103, 9104
TC = 1000.0
PRECIO = 250_000.0
_FUERA = {"item_id", "producto", "descripcion", "codigo", "item_code", "actualizado"}


def _costo_si(item_id: int, costo: str, moneda: str, tc) -> lote.Costo:
    tc = Decimal(str(tc)) if tc else None
    return lote.Costo(
        item_id,
        Decimal(costo),
        moneda,
        lote.FUENTE_COSTO_SI,
        date(2026, 11, 1),
        tc if moneda == "USD" else None,
        lote.en_pesos(Decimal(costo), moneda, tc),
    )


@pytest.fixture()
def lector(monkeypatch):
    """The reader: costo SI for the ids in `si` (USD 80 for X by default), the list cost for the rest."""
    si = {X: ("80", "USD")}

    def actuales(db, item_ids, *, tipo_cambio=None):
        out = actuales_lista(db, item_ids, tipo_cambio=tipo_cambio)
        tc = tipo_cambio or TC
        return {i: (_costo_si(i, *si[i], tc) if i in si else c) for i, c in out.items()}

    monkeypatch.setattr(lote, "actuales", actuales)
    return si


@pytest.fixture()
def mundo(db, lector, monkeypatch):
    for item_id, costo, moneda in ((X, 100, "USD"), (T, 80, "USD"), (ARS_SI, 60_000, "ARS"), (OTRO, 90, "USD")):
        db.add(
            ProductoERP(
                item_id=item_id,
                codigo=f"C{item_id}",
                descripcion="Producto",
                costo=costo,
                moneda_costo=moneda,
                iva=21.0,
                envio=0.0,
                activo=True,
            )
        )
    db.add(TipoCambio(fecha=date.today(), moneda="USD", compra=TC, venta=TC))
    version = ComisionVersion(nombre="Test", fecha_desde=date(2000, 1, 1), activo=True)
    db.add(version)
    db.flush()
    db.add(ComisionBase(version_id=version.id, grupo_id=1, comision_base=12.0))
    db.flush()
    # Shipping is not what this tests: every product ships at 0.
    monkeypatch.setattr(ep, "resolver_costo_envio", lambda db, producto, **k: 0.0)
    monkeypatch.setattr("app.services.envio_real_service.resolver_costo_envio", lambda db, producto, **k: 0.0)
    for mod in (epp, rms):
        monkeypatch.setattr(mod, "resolver_costos_envio_batch", lambda db, ids: {})
    return db


def _sin_id(respuesta: dict) -> dict:
    return {k: v for k, v in respuesta.items() if k not in _FUERA}


def _pricing(db, item_id: int, **valores) -> ProductoPricing:
    fila = ProductoPricing(item_id=item_id, **valores)
    db.add(fila)
    db.flush()
    return fila


_MARKUPS = (
    "markup_calculado",
    "markup_rebate",
    "markup_oferta",
    "markup_web_real",
    "markup_pvp",
    "markup_pvp_3_cuotas",
    "markup_pvp_6_cuotas",
    "markup_pvp_9_cuotas",
    "markup_pvp_12_cuotas",
)
_PRECIOS = (
    "precio_lista_ml",
    "precio_3_cuotas",
    "precio_6_cuotas",
    "precio_9_cuotas",
    "precio_12_cuotas",
    "precio_pvp",
    "precio_pvp_3_cuotas",
    "precio_web_transferencia",
)


def _fila(db, item_id: int, campos) -> dict:
    db.expire_all()
    fila = db.query(ProductoPricing).filter_by(item_id=item_id).one()
    return {c: (None if getattr(fila, c) is None else float(getattr(fila, c))) for c in campos}


# --- calculations (no write) -------------------------------------------------------------------------------------


def test_calcular_por_markup_prices_over_costo_si(mundo, active_user) -> None:
    """S13: the price for a target markup is computed from costo SI."""
    pedir = lambda i: ep.CalcularPorMarkupRequest(item_id=i, pricelist_id=4, markup_objetivo=30.0)  # noqa: E731
    x = ep.calcular_por_markup(pedir(X), db=mundo, current_user=active_user)
    t = ep.calcular_por_markup(pedir(T), db=mundo, current_user=active_user)
    assert x["costo_ars"] == 80_000.0
    assert _sin_id(x) == _sin_id(t)


def test_calcular_markup_get_is_over_costo_si(mundo, active_user) -> None:
    """D1: the markup of a price is over costo SI."""
    x = ep.calcular_markup_get(precio=PRECIO, item_id=X, db=mundo, current_user=active_user)
    t = ep.calcular_markup_get(precio=PRECIO, item_id=T, db=mundo, current_user=active_user)
    assert x["costo_ars"] == 80_000.0
    assert x["markup"] == t["markup"]


def test_calcular_por_precio_is_over_costo_si(mundo, active_user) -> None:
    pedir = lambda i: ep.CalcularPorPrecioRequest(item_id=i, pricelist_id=4, precio_manual=PRECIO)  # noqa: E731
    x = ep.calcular_por_precio(pedir(X), db=mundo, current_user=active_user)
    t = ep.calcular_por_precio(pedir(T), db=mundo, current_user=active_user)
    assert x["costo_ars"] == 80_000.0
    assert _sin_id(x) == _sin_id(t)


def test_variantes_envio_use_costo_si(mundo, active_user, monkeypatch) -> None:
    vistos = []
    monkeypatch.setattr(ep, "calcular_variantes_envio", lambda db, p, precio, costo, **k: vistos.append(costo) or {})
    x = ep.variantes_envio(item_id=X, precio=PRECIO, pricelist_id=4, db=mundo, current_user=active_user)
    assert (x["costo_ars"], vistos) == (80_000.0, [80_000.0])


def test_calcular_completo_prices_every_list_over_costo_si(mundo, active_user) -> None:
    pedir = lambda i: ep.CalcularPreciosCompletosRequest(item_id=i, markup_objetivo=30.0)  # noqa: E731
    x = ep.calcular_precios_completos(pedir(X), db=mundo, current_user=active_user)
    t = ep.calcular_precios_completos(pedir(T), db=mundo, current_user=active_user)
    assert x["clasica"]["costo_ars"] == 80_000.0
    assert (x["clasica"], x["cuotas"]) == (t["clasica"], t["cuotas"])


def test_an_ars_product_s_costo_si_is_pesos_at_any_rate(mundo, active_user, lector) -> None:
    """L18: an ARS product's costo SI is in pesos and is never re-converted at today's FX."""
    lector[ARS_SI] = ("50000", "ARS")
    mundo.query(TipoCambio).update({"venta": 7777.0})
    mundo.flush()
    r = ep.calcular_markup_get(precio=PRECIO, item_id=ARS_SI, db=mundo, current_user=active_user)
    assert r["costo_ars"] == 50_000.0


# --- writes: stored markups move, prices are the ones the PM sent (D4) ---------------------------------------------


def test_precios_set_stores_markups_over_costo_si_and_the_price_sent(mundo, active_user) -> None:
    for i in (X, T):
        ep.setear_precio(ep.SetPrecioRequest(item_id=i, precio_lista_ml=PRECIO), db=mundo, current_user=active_user)
    x = _fila(mundo, X, _MARKUPS + _PRECIOS)
    assert x["precio_lista_ml"] == PRECIO
    assert x["markup_calculado"] is not None
    assert x == _fila(mundo, T, _MARKUPS + _PRECIOS)


@pytest.mark.parametrize("lista_tipo", ["web", "pvp"])
def test_set_rapido_stores_markups_over_costo_si(mundo, active_user, lista_tipo) -> None:
    respuestas = [
        ep.setear_precio_rapido(
            item_id=i, precio=PRECIO, recalcular_cuotas=True, lista_tipo=lista_tipo, db=mundo, current_user=active_user
        )
        for i in (X, T)
    ]
    assert _sin_id(respuestas[0]) == _sin_id(respuestas[1])
    assert _fila(mundo, X, _MARKUPS + _PRECIOS) == _fila(mundo, T, _MARKUPS + _PRECIOS)


def test_set_cuota_and_recalcular_cuotas_store_markups_over_costo_si(mundo, active_user) -> None:
    for i in (X, T):
        _pricing(mundo, i, precio_lista_ml=PRECIO)
        ep.setear_precio_cuota(
            item_id=i, tipo_cuota="3", precio=PRECIO * 1.1, lista_tipo="web", db=mundo, current_user=active_user
        )
        ep.recalcular_cuotas_desde_clasica(item_id=i, lista_tipo="web", db=mundo, current_user=active_user)
    assert _fila(mundo, X, _MARKUPS + _PRECIOS) == _fila(mundo, T, _MARKUPS + _PRECIOS)


def test_aplicar_markup_masivo_prices_the_selection_over_costo_si_and_nothing_else(
    mundo, active_user, monkeypatch
) -> None:
    """The PM asks for it, so the selection is priced (from costo SI). A product outside it keeps its price (D4)."""
    monkeypatch.setattr("app.services.permisos_service.verificar_permiso", lambda *a, **k: True)
    _pricing(mundo, OTRO, precio_lista_ml=123_456.0)
    r = ep.aplicar_markup_masivo(
        ep.AplicarMarkupMasivoRequest(item_ids=[X, T], markup_objetivo=30.0), db=mundo, current_user=active_user
    )
    x, t = sorted(r.resultados if hasattr(r, "resultados") else r["resultados"], key=lambda f: _get(f, "item_id"))
    assert _get(x, "ok") and _get(x, "precio_nuevo") == _get(t, "precio_nuevo")
    assert _get(x, "markup_real") == _get(t, "markup_real")
    assert _fila(mundo, OTRO, ("precio_lista_ml",)) == {"precio_lista_ml": 123_456.0}


def _get(fila, campo):
    return fila[campo] if isinstance(fila, dict) else getattr(fila, campo)


def test_rebate_and_web_transferencia_store_markups_over_costo_si(mundo, active_user, monkeypatch) -> None:
    monkeypatch.setattr("app.services.permisos_service.verificar_permiso", lambda *a, **k: True)
    for i in (X, T):
        _pricing(mundo, i, precio_lista_ml=PRECIO, markup_calculado=10.0)
        epp.actualizar_rebate(
            i, RebateUpdate(participa_rebate=True, porcentaje_rebate=3.8), db=mundo, current_user=active_user
        )
        epp.actualizar_web_transferencia(
            i, participa=True, porcentaje_markup=6.0, preservar_porcentaje=False, db=mundo, current_user=active_user
        )
    x = _fila(mundo, X, ("markup_rebate", "markup_web_real", "precio_web_transferencia"))
    assert x["markup_rebate"] is not None and x["markup_web_real"] is not None
    assert x == _fila(mundo, T, ("markup_rebate", "markup_web_real", "precio_web_transferencia"))


def test_web_and_pvp_masivo_compute_over_costo_si(mundo, active_user) -> None:
    for i in (X, T):
        _pricing(mundo, i, precio_lista_ml=PRECIO, markup_calculado=10.0)
    epp.calcular_web_masivo(
        CalculoWebMasivoRequest(porcentaje_con_precio=6.0, porcentaje_sin_precio=6.0, item_ids=[X, T]),
        db=mundo,
        current_user=active_user,
    )
    epp.calcular_pvp_masivo(
        CalculoPVPMasivoRequest(markup_pvp_clasica=10.0, adicional_cuotas=0.0, item_ids=[X, T]),
        db=mundo,
        current_user=active_user,
    )
    x = _fila(mundo, X, _MARKUPS + _PRECIOS)
    assert x["markup_web_real"] is not None and x["markup_pvp"] is not None  # both runs computed X (never None == None)
    assert x == _fila(mundo, T, _MARKUPS + _PRECIOS)


# --- services -----------------------------------------------------------------------------------------------------


def test_recalcular_markups_is_over_costo_si(mundo) -> None:
    for i in (X, T):
        _pricing(mundo, i, precio_lista_ml=PRECIO)
    rms.recalcular_markups(mundo)
    x = _fila(mundo, X, ("markup_calculado",))
    assert x["markup_calculado"] is not None and x == _fila(mundo, T, ("markup_calculado",))


def test_mcp_precio_por_markup_is_over_costo_si(mundo) -> None:
    from app.mcp.write.live import precio_por_markup

    assert precio_por_markup(mundo, X, 30.0) == precio_por_markup(mundo, T, 30.0) is not None


def test_without_costo_si_the_cost_is_the_list_cost(mundo, active_user) -> None:
    """Q1: no costo SI -> the list cost, so a product with no sell in is priced as before."""
    r = ep.calcular_markup_get(precio=PRECIO, item_id=T, db=mundo, current_user=active_user)
    assert r["costo_ars"] == 80_000.0


# --- stored markups follow a costo SI change (L15, D4), and never silently skip -----------------------------------


def _todos_los_precios(item_id: int) -> dict:
    return dict(
        item_id=item_id,
        precio_lista_ml=PRECIO,
        precio_web_transferencia=PRECIO * 1.05,
        precio_pvp=PRECIO * 1.2,
        precio_pvp_3_cuotas=PRECIO * 1.3,
        participa_rebate=True,
        porcentaje_rebate=3.8,
    )


def test_a_costo_si_change_moves_the_stored_markups_never_the_prices(mundo, lector) -> None:
    from app.models.producto import ProductoPricing as PP

    for i in (X, T, OTRO):
        mundo.add(PP(**_todos_los_precios(i)))
    mundo.flush()
    rms.recalcular_markups_guardados(mundo, [X, T, OTRO])
    antes_otro = _fila(mundo, OTRO, _MARKUPS + _PRECIOS)
    precios_x = _fila(mundo, X, _PRECIOS)

    lector[X] = ("70", "USD")  # X's costo SI goes 80 -> 70; T is now list 80 vs X 70
    mundo.query(ProductoERP).filter_by(item_id=T).update({"costo": 70})
    mundo.flush()
    omitidos = rms.recalcular_markups_guardados(mundo, [X, T])

    assert omitidos == []
    assert _fila(mundo, X, _PRECIOS) == precios_x  # D4: no price moved
    assert _fila(mundo, X, _MARKUPS) == _fila(mundo, T, _MARKUPS)  # every stored markup is over 70 now
    assert _fila(mundo, X, ("markup_calculado",))["markup_calculado"] > 0
    assert _fila(mundo, OTRO, _MARKUPS + _PRECIOS) == antes_otro  # not asked: untouched


@pytest.mark.parametrize(
    "preparar, campo, motivo",
    [
        pytest.param("sin_costo", "todos", "sin_costo", id="sin_costo"),
        pytest.param("sin_tipo_cambio", "todos", "sin_tipo_cambio", id="sin_tipo_cambio"),
        pytest.param("sin_comision", "markup_calculado", "sin_comision", id="sin_comision"),
        pytest.param("sin_precio", "markup_web_real", "sin_precio", id="sin_precio"),
        pytest.param("sin_iva", "todos", "sin_iva", id="sin_iva"),
    ],
)
def test_a_markup_that_cannot_be_recomputed_is_logged_with_item_and_reason(
    mundo, lector, caplog, preparar, campo, motivo
) -> None:
    """Orchestrator condition: 'cannot compute' never passes silently; it is skipped (no exception) and logged."""
    fila = _pricing(mundo, X, precio_lista_ml=PRECIO, markup_web_real=12.0)
    if preparar == "sin_costo":
        lector.pop(X)
        mundo.query(ProductoERP).filter_by(item_id=X).update({"costo": 0})
    elif preparar == "sin_tipo_cambio":
        lector.pop(X)
        mundo.query(TipoCambio).delete()
    elif preparar == "sin_iva":
        mundo.query(ProductoERP).filter_by(item_id=X).update({"iva": None})
    elif preparar == "sin_comision":
        mundo.query(ComisionBase).delete()
    mundo.flush()
    if preparar != "sin_precio":
        fila.precio_web_transferencia = PRECIO
        mundo.flush()

    with caplog.at_level("WARNING", logger=rms.logger.name):
        omitidos = rms.recalcular_markups_guardados(mundo, [X])

    assert (X, campo, motivo) in omitidos
    assert any(
        r.levelname == "WARNING" and str(X) in r.getMessage() and campo in r.getMessage() and motivo in r.getMessage()
        for r in caplog.records
    )


# --- Productos listing and detail: the live markups (orchestrator: productos_listing is PR 4) ---------------------


def _con_cuotas(db) -> None:
    for i in (X, T):
        _pricing(
            db,
            i,
            precio_lista_ml=PRECIO,
            precio_3_cuotas=PRECIO * 1.1,
            precio_6_cuotas=PRECIO * 1.2,
            precio_pvp=PRECIO * 1.3,
            precio_pvp_3_cuotas=PRECIO * 1.4,
        )


def _markups(fila: dict) -> dict:
    return {k: v for k, v in fila.items() if k.startswith("markup") and not k.startswith("markup_adicional")}


@pytest.fixture()
def lector_productos(grant_permiso, rol_ventas, mundo):
    from tests.integration.test_producto_detail_cuota_markups import _guard_incompatible_raw_sql

    grant_permiso(rol_ventas, "productos.ver")
    _guard_incompatible_raw_sql(mundo)
    _con_cuotas(mundo)
    return mundo


def test_the_productos_listing_live_markups_are_over_costo_si(client, auth_headers, lector_productos) -> None:
    filas = client.get("/api/productos?page=1&page_size=50", headers=auth_headers).json()["productos"]
    x, t = (next(f for f in filas if f["item_id"] == i) for i in (X, T))
    assert x["markup_3_cuotas"] is not None and x["markup_pvp"] is not None
    assert _markups(x) == _markups(t)


def test_the_producto_detail_live_markups_are_over_costo_si(client, auth_headers, lector_productos) -> None:
    x, t = (client.get(f"/api/productos/{i}", headers=auth_headers).json() for i in (X, T))
    assert x["markup_3_cuotas"] is not None
    assert _markups(x) == _markups(t)


def test_a_listed_product_without_any_cost_shows_no_markup_never_zero(client, auth_headers, lector_productos) -> None:
    """Interface: unknown is never 0. A product with no costo SI and no list cost gets no live markup."""
    lector_productos.query(ProductoERP).filter_by(item_id=T).update({"costo": 0})
    lector_productos.flush()
    filas = client.get("/api/productos?page=1&page_size=50", headers=auth_headers).json()["productos"]
    t = next(f for f in filas if f["item_id"] == T)
    assert (t["markup_3_cuotas"], t["markup_pvp"], t["markup_pvp_3_cuotas"]) == (None, None, None)


# --- the other computation paths (verifier B5) --------------------------------------------------------------------


def test_promo_propagation_rebate_and_oferta_markups_are_over_costo_si(mundo) -> None:
    """promo_price_propagation writes these two through the calculator with no cost of its own."""
    from app.services.pricing_calculator import calcular_markup_oferta, calcular_markup_rebate

    filas = {
        i: _pricing(mundo, i, precio_lista_ml=PRECIO, participa_rebate=True, porcentaje_rebate=3.8) for i in (X, T)
    }
    productos = {i: mundo.query(ProductoERP).filter_by(item_id=i).one() for i in (X, T)}
    rebate = {i: calcular_markup_rebate(mundo, productos[i], filas[i], TC, costo_envio=0.0) for i in (X, T)}
    oferta = {i: calcular_markup_oferta(mundo, productos[i], TC, costo_envio=0.0) for i in (X, T)}
    assert rebate[X] is not None and rebate[X] == rebate[T]
    assert oferta[X] == oferta[T]


def test_the_pxq_context_cost_is_costo_si(mundo) -> None:
    from app.services.pxq_pricing_context import resolve_pxq_pricing_context
    from tests.services.test_pxq_pricing_context import _publish

    x = mundo.query(ProductoERP).filter_by(item_id=X).one()
    contexto = resolve_pxq_pricing_context(mundo, _publish(mundo, "MLA9101001", x, x.codigo).mla)
    assert contexto.costo_ars == pytest.approx(80_000.0)


def test_the_pxq_context_reads_costo_si_even_without_a_list_cost(mundo) -> None:
    """The reader decides: a product whose list cost is empty but has costo SI is priced, not 'sin_costo'."""
    from app.services.pxq_pricing_context import resolve_pxq_pricing_context
    from tests.services.test_pxq_pricing_context import _publish

    mundo.query(ProductoERP).filter_by(item_id=X).update({"costo": 0})
    mundo.flush()
    x = mundo.query(ProductoERP).filter_by(item_id=X).one()
    contexto = resolve_pxq_pricing_context(mundo, _publish(mundo, "MLA9101002", x, x.codigo).mla)
    assert contexto.costo_ars == pytest.approx(80_000.0)


def test_erp_sync_new_price_markup_is_over_costo_si(mundo) -> None:
    """A price first published by the ERP gets its markup over costo SI (X) like its twin's over the list cost (T)."""
    from tests.services.test_erp_sync_batch_prefetch import _producto, _run_sync
    from app.models.usuario import Usuario
    from app.core.constants import SYSTEM_USERNAME

    sistema = Usuario(username=SYSTEM_USERNAME, nombre="Sistema")
    mundo.add(sistema)
    mundo.commit()
    filas = [
        _producto(i, codigo=f"C{i}", iva=21, precio_publicado=PRECIO, moneda_costo="USD", coslis_price=costo)
        for i, costo in ((X, 100), (T, 80))
    ]
    _run_sync(mundo, filas, {}, sistema)
    x, t = (_fila(mundo, i, ("precio_lista_ml", "markup_calculado")) for i in (X, T))
    assert x["markup_calculado"] is not None and x == t


def _correr_script(monkeypatch, mundo, modulo, *args) -> None:
    import sys

    monkeypatch.setattr(modulo, "SessionLocal", lambda: mundo)
    monkeypatch.setattr(mundo, "close", lambda: None)
    monkeypatch.setattr(sys, "argv", [modulo.__name__, *args])
    modulo.main()


def test_the_web_transferencia_script_prices_over_costo_si_and_stays_manual(mundo, monkeypatch) -> None:
    """Q6: only its cost read changes; it runs when someone runs it (nothing calls it)."""
    from app.scripts import recalcular_precios_web_transferencia as script

    for i in (X, T):
        _pricing(mundo, i, precio_lista_ml=PRECIO, participa_web_transferencia=True, porcentaje_markup_web=6.0)
    _correr_script(monkeypatch, mundo, script, "--quiet")
    campos = ("precio_web_transferencia", "markup_web_real")
    x = _fila(mundo, X, campos)
    assert x["precio_web_transferencia"] is not None and x == _fila(mundo, T, campos)


def test_the_markups_script_recomputes_over_costo_si(mundo, monkeypatch) -> None:
    from app.scripts import recalcular_markups_pricing as script

    for i in (X, T):
        _pricing(mundo, i, precio_lista_ml=PRECIO, precio_pvp=PRECIO * 1.2)
    _correr_script(monkeypatch, mundo, script)
    x = _fila(mundo, X, _MARKUPS)
    assert x["markup_calculado"] is not None and x == _fila(mundo, T, _MARKUPS)


def test_the_ofertas_vigentes_markup_is_over_costo_si(mundo, active_user) -> None:
    from datetime import timedelta

    from app.api.endpoints.productos_detail import obtener_ofertas_vigentes
    from app.models.oferta_ml import OfertaML
    from app.models.publicacion_ml import PublicacionML

    hoy = date.today()
    for i in (X, T):
        mla = f"MLA{i}"
        mundo.add(PublicacionML(mla=mla, item_id=i, codigo=f"C{i}", pricelist_id=4))
        mundo.add(
            OfertaML(
                mla=mla, fecha_desde=hoy - timedelta(days=1), fecha_hasta=hoy + timedelta(days=1), pvp_seller=PRECIO
            )
        )
    mundo.flush()
    x, t = (obtener_ofertas_vigentes(i, db=mundo, current_user=active_user)["publicaciones"][0] for i in (X, T))
    assert x["oferta"]["markup_oferta"] is not None and x["oferta"]["markup_oferta"] == t["oferta"]["markup_oferta"]


def test_the_export_rebate_markup_filter_is_over_costo_si(mundo, client, auth_headers, monkeypatch) -> None:
    """A rebate price whose markup is positive over costo SI (80) but negative over the list cost (100): the
    'positive rebate markup' export keeps X."""
    import io

    import openpyxl

    from app.api.endpoints import productos_export
    from app.services.pricing_calculator import calcular_markup_rebate

    monkeypatch.setattr(productos_export, "_requerir_permiso_exportar", lambda *a, **k: None)
    fila = _pricing(mundo, X, precio_lista_ml=120_000.0, participa_rebate=True, porcentaje_rebate=3.8)
    x = mundo.query(ProductoERP).filter_by(item_id=X).one()
    assert calcular_markup_rebate(mundo, x, fila, TC, costo_envio=0.0, costo_ars=80_000.0) > 0  # the premise
    assert calcular_markup_rebate(mundo, x, fila, TC, costo_envio=0.0, costo_ars=100_000.0) < 0
    mundo.commit()

    r = client.get("/api/exportar-clasica?markup_rebate_positivo=true", headers=auth_headers)

    assert r.status_code == 200, r.text
    hoja = openpyxl.load_workbook(io.BytesIO(r.content)).active
    assert f"C{X}" in {c for fila in hoja.iter_rows(values_only=True) for c in fila}


def _sin_costo(mundo, lector) -> None:
    """T gets no cost at all: no costo SI and a list cost of 0 (the ERP's 'missing')."""
    lector.pop(X, None)
    mundo.query(ProductoERP).filter_by(item_id=T).update({"costo": 0})
    mundo.flush()


def test_web_masivo_writes_no_price_from_an_unknown_cost(mundo, active_user, lector, caplog) -> None:
    """D4 + 'never 0 for unknown': a product without a cost keeps its price; the skip is logged."""
    _pricing(mundo, T, precio_lista_ml=PRECIO, precio_web_transferencia=111_111.0)
    _sin_costo(mundo, lector)
    with caplog.at_level("WARNING"):
        epp.calcular_web_masivo(
            CalculoWebMasivoRequest(porcentaje_con_precio=6.0, porcentaje_sin_precio=6.0, item_ids=[T]),
            db=mundo,
            current_user=active_user,
        )
    assert _fila(mundo, T, ("precio_web_transferencia",)) == {"precio_web_transferencia": 111_111.0}
    assert any(str(T) in r.getMessage() and "sin_costo" in r.getMessage() for r in caplog.records)


def test_the_full_recompute_stores_no_markup_for_an_unknown_cost(mundo, lector, caplog) -> None:
    _pricing(mundo, T, precio_lista_ml=PRECIO, markup_calculado=12.0)
    _sin_costo(mundo, lector)
    with caplog.at_level("WARNING", logger=rms.logger.name):
        rms.recalcular_markups(mundo)
    assert _fila(mundo, T, ("markup_calculado",)) == {"markup_calculado": 12.0}
    assert any(str(T) in r.getMessage() and "sin_costo" in r.getMessage() for r in caplog.records)


# --- interfaz §7: an unknown cost stays None (never 0) and is logged; nothing is priced or written from it --------


def test_the_resolved_cost_is_none_when_unknown_and_the_ids_are_logged(mundo, lector, caplog) -> None:
    from app.services.pricing_calculator import costos_ars_actuales

    _sin_costo(mundo, lector)
    mundo.query(TipoCambio).delete()  # X keeps its list cost, USD 100, with no rate now
    mundo.flush()
    with caplog.at_level("INFO"):
        costos = costos_ars_actuales(mundo, [X, T, ARS_SI])
    assert costos == {X: None, T: None, ARS_SI: 60_000.0}
    assert any(
        f"sin_costo [{T}]" in r.getMessage() and f"sin_tipo_cambio [{X}]" in r.getMessage() for r in caplog.records
    )


def test_a_markup_read_without_a_cost_is_none_never_zero(mundo, active_user, lector) -> None:
    _sin_costo(mundo, lector)
    r = ep.calcular_markup_get(precio=PRECIO, item_id=T, db=mundo, current_user=active_user)
    assert (r["costo_ars"], r["markup"]) == (None, None)
    r = ep.calcular_por_precio(
        ep.CalcularPorPrecioRequest(item_id=T, pricelist_id=4, precio_manual=PRECIO), db=mundo, current_user=active_user
    )
    assert (r["costo_ars"], r["markup_resultante"]) == (None, None)


@pytest.mark.parametrize(
    "llamar",
    [
        pytest.param(
            lambda db, u: ep.calcular_por_markup(
                ep.CalcularPorMarkupRequest(item_id=T, pricelist_id=4, markup_objetivo=30.0), db=db, current_user=u
            ),
            id="calcular_por_markup",
        ),
        pytest.param(
            lambda db, u: ep.calcular_precios_completos(
                ep.CalcularPreciosCompletosRequest(item_id=T, markup_objetivo=30.0), db=db, current_user=u
            ),
            id="calcular_completo",
        ),
        pytest.param(
            lambda db, u: ep.variantes_envio(item_id=T, precio=PRECIO, pricelist_id=4, db=db, current_user=u),
            id="variantes_envio",
        ),
        pytest.param(
            lambda db, u: ep.recalcular_cuotas_desde_clasica(item_id=T, lista_tipo="web", db=db, current_user=u),
            id="recalcular_cuotas",
        ),
    ],
)
def test_a_price_from_an_unknown_cost_is_refused_and_nothing_is_written(mundo, active_user, lector, llamar) -> None:
    from fastapi import HTTPException

    from app.services.pricing_calculator import SIN_COSTO_ERROR

    _pricing(mundo, T, precio_lista_ml=PRECIO, precio_3_cuotas=PRECIO * 1.1)
    _sin_costo(mundo, lector)
    antes = _fila(mundo, T, _MARKUPS + _PRECIOS)
    with pytest.raises(HTTPException) as e:
        llamar(mundo, active_user)
    assert (e.value.status_code, e.value.detail) == (400, SIN_COSTO_ERROR)
    assert _fila(mundo, T, _MARKUPS + _PRECIOS) == antes


def test_set_rapido_without_a_cost_saves_the_price_keeps_the_cuotas_and_says_why(
    mundo, active_user, lector, caplog
) -> None:
    """The PM's price is saved; its markup is unknown (None), and the cuotas are not re-priced from no markup (D4)."""
    _pricing(mundo, T, precio_lista_ml=PRECIO, precio_3_cuotas=123_456.0)
    _sin_costo(mundo, lector)
    with caplog.at_level("WARNING"):
        r = ep.setear_precio_rapido(
            item_id=T, precio=PRECIO * 2, recalcular_cuotas=True, lista_tipo="web", db=mundo, current_user=active_user
        )
    fila = _fila(mundo, T, ("precio_lista_ml", "markup_calculado", "precio_3_cuotas"))
    assert fila == {"precio_lista_ml": PRECIO * 2, "markup_calculado": None, "precio_3_cuotas": 123_456.0}
    assert r["markup"] is None
    assert any(str(T) in m.getMessage() and "sin costo" in m.getMessage() for m in caplog.records)


def test_web_transferencia_on_without_a_cost_is_refused(mundo, active_user, lector, monkeypatch) -> None:
    from fastapi import HTTPException

    monkeypatch.setattr("app.services.permisos_service.verificar_permiso", lambda *a, **k: True)
    _pricing(mundo, T, precio_lista_ml=PRECIO)
    _sin_costo(mundo, lector)
    with pytest.raises(HTTPException) as e:
        epp.actualizar_web_transferencia(T, participa=True, db=mundo, current_user=active_user)
    assert e.value.status_code == 400
    assert _fila(mundo, T, ("precio_web_transferencia",)) == {"precio_web_transferencia": None}


@pytest.mark.parametrize("masivo", ["pvp", "cuotas"])
def test_the_bulk_runs_skip_an_unknown_cost_and_say_so(mundo, active_user, lector, caplog, masivo) -> None:
    from app.api.endpoints.productos_shared import RecalcularCuotasMasivoRequest

    _pricing(mundo, T, precio_lista_ml=PRECIO, precio_pvp=PRECIO, precio_3_cuotas=1.0, precio_pvp_3_cuotas=2.0)
    _sin_costo(mundo, lector)
    antes = _fila(mundo, T, _MARKUPS + _PRECIOS)
    with caplog.at_level("WARNING"):
        if masivo == "pvp":
            epp.calcular_pvp_masivo(
                CalculoPVPMasivoRequest(markup_pvp_clasica=10.0, adicional_cuotas=0.0, item_ids=[T]),
                db=mundo,
                current_user=active_user,
            )
        else:
            epp.recalcular_cuotas_masivo(
                RecalcularCuotasMasivoRequest(item_ids=[T]), db=mundo, current_user=active_user
            )
    assert _fila(mundo, T, _MARKUPS + _PRECIOS) == antes
    assert any(str(T) in r.getMessage() and "sin_costo" in r.getMessage() for r in caplog.records)


def test_erp_sync_keeps_a_new_price_without_a_markup_when_the_usd_cost_has_no_rate(mundo, caplog) -> None:
    from app.core.constants import SYSTEM_USERNAME
    from app.models.usuario import Usuario
    from tests.services.test_erp_sync_batch_prefetch import _producto, _run_sync

    mundo.query(TipoCambio).delete()
    mundo.add(Usuario(username=SYSTEM_USERNAME, nombre="Sistema"))
    mundo.commit()
    fila = _producto(T, codigo=f"C{T}", iva=21, precio_publicado=PRECIO, moneda_costo="USD", coslis_price=80)
    with caplog.at_level("INFO"):
        _run_sync(mundo, [fila], {}, mundo.query(Usuario).filter_by(username=SYSTEM_USERNAME).one())
    assert _fila(mundo, T, ("precio_lista_ml", "markup_calculado")) == {
        "precio_lista_ml": PRECIO,
        "markup_calculado": None,
    }
    assert any(str(T) in r.getMessage() and "sin costo en pesos" in r.getMessage() for r in caplog.records)


def test_precios_set_without_a_cost_saves_the_price_and_keeps_the_stored_cuotas(
    mundo, active_user, lector, caplog
) -> None:
    """No markup to price the omitted cuotas from: the stored ones stay (never wiped to NULL) and it is said."""
    cuotas = {"precio_3_cuotas": 1.0, "precio_6_cuotas": 2.0, "precio_9_cuotas": 3.0, "precio_12_cuotas": 4.0}
    _pricing(mundo, T, precio_lista_ml=PRECIO, **cuotas)
    _sin_costo(mundo, lector)
    with caplog.at_level("WARNING"):
        ep.setear_precio(
            ep.SetPrecioRequest(item_id=T, precio_lista_ml=PRECIO * 2, precio_3_cuotas=9.0),
            db=mundo,
            current_user=active_user,
        )
    fila = _fila(mundo, T, ("precio_lista_ml", "markup_calculado", *cuotas))
    assert fila == {**cuotas, "precio_lista_ml": PRECIO * 2, "markup_calculado": None, "precio_3_cuotas": 9.0}
    assert any(str(T) in r.getMessage() and "sin costo en pesos" in r.getMessage() for r in caplog.records)


def test_set_rapido_without_a_cost_keeps_the_web_transferencia_price_and_says_why(
    mundo, active_user, lector, caplog
) -> None:
    _pricing(
        mundo,
        T,
        precio_lista_ml=PRECIO,
        participa_web_transferencia=True,
        porcentaje_markup_web=5,
        precio_web_transferencia=777.0,
    )
    _sin_costo(mundo, lector)
    with caplog.at_level("WARNING"):
        ep.setear_precio_rapido(
            item_id=T, precio=PRECIO * 2, recalcular_cuotas=False, lista_tipo="web", db=mundo, current_user=active_user
        )
    assert _fila(mundo, T, ("precio_lista_ml", "precio_web_transferencia")) == {
        "precio_lista_ml": PRECIO * 2,
        "precio_web_transferencia": 777.0,
    }
    assert any(str(T) in r.getMessage() and "web transferencia" in r.getMessage() for r in caplog.records)
