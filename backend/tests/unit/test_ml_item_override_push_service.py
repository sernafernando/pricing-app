"""`ml_item_override_push_service`: push a publication's local override to ML ("Actualizar en ML", Publicaciones ML T8c).

The owner's rule (L20): editing never writes ML; pushing is a separate button, "no siempre se puede modificar en ml".
So `plan_push` sends only what differs from ML's data AND what ML lets change, and names every field it leaves out
with the reason; the write through the proxy builds on it.
"""

from __future__ import annotations

import pytest

from app.services.ml_item_override_push_service import PushFacts, plan_push

ORIGINAL = {
    "titulo": "Router TP-Link Archer AX55",
    "descripcion": "Router WiFi 6",
    "fotos": [{"id": "P1", "url": "https://x/p1"}, {"id": "P2", "url": "https://x/p2"}],
    "atributos": [
        {"id": "BRAND", "name": "Marca", "value_name": "TP-Link"},
        {"id": "MODEL", "name": "Modelo", "value_name": "Archer AX55"},
    ],
}
NOTHING = {"titulo": None, "descripcion": None, "fotos": None, "atributos": None}
LIVE = PushFacts(status="active", deleted=False, catalog_listing=False, sold_quantity=0, has_variations=False)


def override(**fields) -> dict:
    return {**NOTHING, **fields}


# ── plan_push: what ML lets change ──────────────────────────────────


def test_the_title_goes_when_the_publication_has_no_sales() -> None:
    plan = plan_push(LIVE, ORIGINAL, override(titulo="Router AX55 WiFi 6"))
    assert (plan.refused, plan.item_body, plan.descripcion, plan.omitidos) == (
        None,
        {"title": "Router AX55 WiFi 6"},
        None,
        (),
    )


def test_the_title_is_left_out_once_the_publication_sold() -> None:
    facts = PushFacts(status="active", deleted=False, catalog_listing=False, sold_quantity=3, has_variations=False)
    plan = plan_push(facts, ORIGINAL, override(titulo="Otro", descripcion="Nueva"))
    assert plan.item_body == {}
    assert plan.descripcion == "Nueva"
    assert plan.omitidos == (("titulo", "La publicación tiene ventas: Mercado Libre no deja cambiar el título."),)


def test_pictures_go_as_ids_in_the_new_order_unless_there_are_variations() -> None:
    reordered = override(fotos=[ORIGINAL["fotos"][1]])
    assert plan_push(LIVE, ORIGINAL, reordered).item_body == {"pictures": [{"id": "P2"}]}
    facts = PushFacts(status="active", deleted=False, catalog_listing=False, sold_quantity=0, has_variations=True)
    plan = plan_push(facts, ORIGINAL, reordered)
    assert plan.item_body == {}
    assert plan.omitidos == (
        ("fotos", "La publicación tiene variaciones: las fotos se cambian en Mercado Libre, por variación."),
    )


def test_only_changed_attribute_values_go_and_a_dropped_attribute_is_not_deleted() -> None:
    kept = [{"id": "MODEL", "name": "Modelo", "value_name": "Archer AX55 Pro"}]
    plan = plan_push(LIVE, ORIGINAL, override(atributos=kept))
    assert plan.item_body == {"attributes": [{"id": "MODEL", "value_name": "Archer AX55 Pro"}]}
    assert plan.omitidos == (("atributos", "Los atributos quitados no se borran en Mercado Libre: Marca."),)


def test_a_blank_description_is_left_out() -> None:
    plan = plan_push(LIVE, ORIGINAL, override(descripcion=""))
    assert plan.descripcion is None
    assert plan.omitidos == (("descripcion", "Mercado Libre no acepta una descripción vacía."),)


def test_fields_equal_to_ml_are_not_sent() -> None:
    same = override(titulo=ORIGINAL["titulo"], descripcion=ORIGINAL["descripcion"], fotos=ORIGINAL["fotos"])
    plan = plan_push(LIVE, ORIGINAL, same)
    assert (plan.item_body, plan.descripcion, plan.omitidos) == ({}, None, ())


@pytest.mark.parametrize(
    ("facts", "reason"),
    [
        (
            PushFacts(status="active", deleted=False, catalog_listing=True, sold_quantity=0, has_variations=False),
            "Las publicaciones de catálogo no se pueden modificar en Mercado Libre.",
        ),
        (
            PushFacts(status="closed", deleted=True, catalog_listing=False, sold_quantity=0, has_variations=False),
            "La publicación está eliminada.",
        ),
        (
            PushFacts(
                status="under_review", deleted=False, catalog_listing=False, sold_quantity=0, has_variations=False
            ),
            "Una publicación en estado under_review no se puede modificar.",
        ),
    ],
)
def test_a_publication_ml_does_not_let_modify_is_refused(facts: PushFacts, reason: str) -> None:
    assert plan_push(facts, ORIGINAL, override(titulo="Otro")).refused == reason


def test_a_paused_publication_can_be_modified() -> None:
    facts = PushFacts(status="paused", deleted=False, catalog_listing=False, sold_quantity=0, has_variations=False)
    assert plan_push(facts, ORIGINAL, override(titulo="Otro")).item_body == {"title": "Otro"}
