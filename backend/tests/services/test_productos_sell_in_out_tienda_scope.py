"""Markup companion resolver respects tactical store scope (union + per-target caps)."""

from __future__ import annotations

from decimal import Decimal

from app.services.productos_sell_in_out import _cap_restante
from app.services.sell_out.tienda_scope import Scope, alcanza_alguno


def test_alcanza_alguno_is_union() -> None:
    scope = Scope(
        todas_tiendas=False,
        tope_compartido=True,
        oficiales=frozenset({57997}),
        canales=frozenset({"fuera"}),
    )
    assert alcanza_alguno(scope, [("ml", 2645), ("fuera", None)]) is True
    assert alcanza_alguno(scope, [("ml", 2645), ("tn", None)]) is False
    assert alcanza_alguno(None, [("ml", 2645)]) is True


def test_cap_global_unchanged_without_contextos() -> None:
    scope = Scope(todas_tiendas=False, tope_compartido=False, oficiales=frozenset({1}), canales=frozenset())
    activa, libre = _cap_restante(
        tope_unidades=10,
        tope_monto=Decimal("100"),
        scope=scope,
        contextos=None,
        usado_global=(10, Decimal("100")),
        usado_target={},
    )
    assert (activa, libre) == (False, Decimal("0"))


def test_cap_per_target_stays_active_when_other_store_exhausted() -> None:
    scope = Scope(
        todas_tiendas=False,
        tope_compartido=False,
        oficiales=frozenset({57997, 2645}),
        canales=frozenset(),
    )
    usado = {("oficial", 57997): (1, Decimal("10")), ("oficial", 2645): (0, Decimal("0"))}
    activa, libre = _cap_restante(
        tope_unidades=1,
        tope_monto=Decimal("10"),
        scope=scope,
        contextos=[("ml", 2645)],
        usado_global=(1, Decimal("10")),
        usado_target=usado,
    )
    assert activa is True
    assert libre == Decimal("10")


def test_cap_per_target_exhausted_for_selected_store() -> None:
    scope = Scope(
        todas_tiendas=False,
        tope_compartido=False,
        oficiales=frozenset({57997, 2645}),
        canales=frozenset(),
    )
    usado = {("oficial", 57997): (1, Decimal("10")), ("oficial", 2645): (0, Decimal("0"))}
    activa, _ = _cap_restante(
        tope_unidades=1,
        tope_monto=Decimal("10"),
        scope=scope,
        contextos=[("ml", 57997)],
        usado_global=(1, Decimal("10")),
        usado_target=usado,
    )
    assert activa is False


def test_cap_union_active_if_any_selected_target_has_room() -> None:
    scope = Scope(
        todas_tiendas=False,
        tope_compartido=False,
        oficiales=frozenset({57997, 2645}),
        canales=frozenset(),
    )
    usado = {("oficial", 57997): (1, Decimal("10")), ("oficial", 2645): (0, Decimal("0"))}
    activa, libre = _cap_restante(
        tope_unidades=1,
        tope_monto=Decimal("10"),
        scope=scope,
        contextos=[("ml", 57997), ("ml", 2645)],
        usado_global=(1, Decimal("10")),
        usado_target=usado,
    )
    assert activa is True
    assert libre == Decimal("10")


def test_cap_shared_pool_uses_global_even_with_contextos() -> None:
    scope = Scope(
        todas_tiendas=False,
        tope_compartido=True,
        oficiales=frozenset({57997, 2645}),
        canales=frozenset(),
    )
    activa, libre = _cap_restante(
        tope_unidades=1,
        tope_monto=None,
        scope=scope,
        contextos=[("ml", 2645)],
        usado_global=(1, Decimal("0")),
        usado_target={("oficial", 2645): (0, Decimal("0"))},
    )
    assert (activa, libre) == (False, None)
