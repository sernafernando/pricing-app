"""Pure store/channel scope helpers for sell-out tacticals."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from app.models.sell_out import SellOutCampana
from app.services.sell_out.alcance import Venta
from app.services.sell_out.asignacion import _asignar, _Tasas
from app.services.sell_out.tienda_scope import Scope, alcanza, scope_desde_tactical, target_key


def test_alcanza_todas_credits_any_official_store_but_not_sin_tienda_or_channels() -> None:
    scope = Scope(todas_tiendas=True, tope_compartido=False, oficiales=frozenset(), canales=frozenset())
    assert alcanza(scope, "ml", 57997) is True
    assert alcanza(scope, "ml", None) is False
    assert alcanza(scope, "fuera", None) is False


def test_alcanza_lista_and_channels() -> None:
    scope = Scope(
        todas_tiendas=False,
        tope_compartido=False,
        oficiales=frozenset({57997}),
        canales=frozenset({"fuera"}),
    )
    assert alcanza(scope, "ml", 57997) is True
    assert alcanza(scope, "ml", 2645) is False
    assert alcanza(scope, "fuera", None) is True
    assert alcanza(scope, "tn", None) is False


def test_scope_desde_tactical_reads_rows() -> None:
    tactical = SimpleNamespace(
        todas_tiendas=False,
        tope_compartido=True,
        tiendas=[
            SimpleNamespace(tipo="oficial", store_id=57997),
            SimpleNamespace(tipo="fuera", store_id=None),
        ],
    )
    assert scope_desde_tactical(tactical) == Scope(
        todas_tiendas=False,
        tope_compartido=True,
        oficiales=frozenset({57997}),
        canales=frozenset({"fuera"}),
    )


def test_target_key_buckets() -> None:
    assert target_key("ml", 57997) == ("oficial", 57997)
    assert target_key("fuera", None) == ("fuera", None)
    assert target_key("tn", None) == ("tienda_nube", None)


def _campana(**kwargs) -> SellOutCampana:
    base = dict(
        id=1,
        tipo="por_unidad",
        moneda="ARS",
        monto_unit=Decimal("10"),
        acumulable=True,
        monto_incluye_iva=False,
        fecha_desde=date(2026, 11, 1),
        fecha_hasta=date(2026, 11, 30),
        tope_unidades=1,
    )
    base.update(kwargs)
    return SellOutCampana(**base)


def test_asignar_skips_sales_outside_scope() -> None:
    campana = _campana()
    dentro = Venta("ml", 1, 2964, date(2026, 11, 2), 1, store_id=57997)
    fuera = Venta("ml", 2, 2964, date(2026, 11, 2), 1, store_id=2645)
    scope = Scope(
        todas_tiendas=False,
        tope_compartido=True,
        oficiales=frozenset({57997}),
        canales=frozenset(),
    )

    salida, _ = _asignar(
        [campana],
        {1: {2964: Decimal(21)}},
        [dentro, fuera],
        _Tasas({}, None),
        scopes={1: scope},
    )

    assert [(c.venta_ref, c.unidades) for c in salida[1]] == [(1, 1)]


def test_asignar_per_store_cap_gives_each_target_its_own_tope() -> None:
    campana = _campana(tope_unidades=1)
    a = Venta("ml", 1, 2964, date(2026, 11, 2), 1, store_id=57997)
    b = Venta("ml", 2, 2964, date(2026, 11, 2), 1, store_id=2645)
    scope = Scope(
        todas_tiendas=False,
        tope_compartido=False,
        oficiales=frozenset({57997, 2645}),
        canales=frozenset(),
    )

    salida, _ = _asignar(
        [campana],
        {1: {2964: Decimal(21)}},
        [a, b],
        _Tasas({}, None),
        scopes={1: scope},
    )

    assert sorted((c.venta_ref, c.unidades) for c in salida[1]) == [(1, 1), (2, 1)]


def test_asignar_shared_cap_one_pool_across_stores() -> None:
    campana = _campana(tope_unidades=1)
    a = Venta("ml", 1, 2964, date(2026, 11, 2), 1, store_id=57997)
    b = Venta("ml", 2, 2964, date(2026, 11, 3), 1, store_id=2645)
    scope = Scope(
        todas_tiendas=False,
        tope_compartido=True,
        oficiales=frozenset({57997, 2645}),
        canales=frozenset(),
    )

    salida, _ = _asignar(
        [campana],
        {1: {2964: Decimal(21)}},
        [a, b],
        _Tasas({}, None),
        scopes={1: scope},
    )

    assert [(c.venta_ref, c.unidades) for c in salida[1]] == [(1, 1)]
