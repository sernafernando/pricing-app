"""Tests for the logistic mode cascade (design D1 of ml-ventas-modo-logistico).

Behaviour-first: each test pins what the cascade PROMISES, not merely what
the code happens to do today. The precedence test below is mutation-verified
-- see its docstring.
"""

from __future__ import annotations

from app.services.ml_orders_ingestion.mode_resolution import (
    MODO_DESCONOCIDO,
    MODO_RETIRO,
    has_no_shipping_tag,
    resolve_modo_logistico,
)


def test_shipment_wins_over_conflicting_tag():
    """Order 2000016977234624-shaped: carries BOTH the `no_shipping` tag AND
    a delivered `cross_docking` shipment. The shipment must win -- a
    tag-driven badge would call a delivered sale "Retiro".

    Mutation-verified. Applied to `resolve_modo_logistico` (in
    `mode_resolution.py`), then reverted:

        if tagged_no_shipping:           # tag checked FIRST
            return MODO_RETIRO
        if has_shipment:
            return shipment_logistic_type if shipment_logistic_type else MODO_DESCONOCIDO
        return MODO_DESCONOCIDO

    With the tag branch first, this test FAILED: it asserts
    `"cross_docking"` and got `"retiro"`, because the mutated order let the
    tag win over the real shipment -- exactly the 2000016977234624 bug this
    cascade exists to prevent. Reverted, suite re-run green."""
    tags = ["no_shipping"]
    assert (
        resolve_modo_logistico(
            shipment_logistic_type="cross_docking",
            has_shipment=True,
            tagged_no_shipping=has_no_shipping_tag(tags),
        )
        == "cross_docking"
    )


def test_no_shipment_tag_present():
    assert (
        resolve_modo_logistico(
            shipment_logistic_type=None,
            has_shipment=False,
            tagged_no_shipping=True,
        )
        == MODO_RETIRO
    )


def test_no_shipment_no_tag():
    assert (
        resolve_modo_logistico(
            shipment_logistic_type=None,
            has_shipment=False,
            tagged_no_shipping=False,
        )
        == MODO_DESCONOCIDO
    )


def test_unknown_logistic_type_passthrough():
    """A `logistic_type` outside the observed set (`self_service`,
    `cross_docking`, `fulfillment`, `default`) is preserved verbatim, never
    coerced or dropped -- a future ML value must not silently disappear."""
    assert (
        resolve_modo_logistico(
            shipment_logistic_type="a_brand_new_ml_logistic_type",
            has_shipment=True,
            tagged_no_shipping=False,
        )
        == "a_brand_new_ml_logistic_type"
    )


def test_shipment_present_without_logistic_type_resolves_unknown_not_tag():
    """A shipment row can exist with a NULL `logistic_type`. That still
    outranks the tag -- there IS a real shipment -- so it resolves to
    `desconocido`, never falling through to `retiro`."""
    assert (
        resolve_modo_logistico(
            shipment_logistic_type=None,
            has_shipment=True,
            tagged_no_shipping=True,
        )
        == MODO_DESCONOCIDO
    )


def test_has_no_shipping_tag_true():
    assert has_no_shipping_tag(["paid", "no_shipping"]) is True


def test_has_no_shipping_tag_false_when_absent():
    assert has_no_shipping_tag(["paid"]) is False


def test_has_no_shipping_tag_false_when_empty_or_none():
    assert has_no_shipping_tag([]) is False
    assert has_no_shipping_tag(None) is False


def test_pack_collapse_uniform():
    from app.routers.ml_ventas_ops import _collapse

    assert _collapse(["cross_docking", "cross_docking"]) == "cross_docking"


def test_pack_collapse_mixed():
    from app.routers.ml_ventas_ops import _collapse

    assert _collapse(["cross_docking", "self_service"]) == "mixed"
