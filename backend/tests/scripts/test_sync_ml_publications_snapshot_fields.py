"""Snapshot sync must persist shipping fields and SELLER_SKU from value_name."""

from __future__ import annotations

from app.scripts.sync_ml_publications_full import extraer_datos_publicacion, sanitizar_datos_ml


def test_extraer_seller_sku_uses_value_name_when_value_id_null() -> None:
    item = {
        "listing_type_id": "gold_special",
        "sale_terms": [],
        "attributes": [
            {
                "id": "SELLER_SKU",
                "name": "SKU",
                "value_id": None,
                "value_name": "840006603337",
            }
        ],
    }

    _campaign, seller_sku, item_id = extraer_datos_publicacion(item)

    assert seller_sku == "840006603337"
    assert item_id == 840006603337


def test_sanitizar_persists_shipping_fields() -> None:
    item = {
        "title": "Example",
        "price": 100,
        "base_price": 100,
        "available_quantity": 1,
        "sold_quantity": 0,
        "status": "active",
        "listing_type_id": "gold_special",
        "permalink": "https://example.test/MLA1",
        "shipping": {
            "mode": "me2",
            "logistic_type": "cross_docking",
            "local_pick_up": True,
            "free_shipping": True,
            "store_pick_up": False,
            "tags": ["self_service_in", "mandatory_free_shipping"],
        },
    }

    datos = sanitizar_datos_ml(item, campaign="Clásica", seller_sku="840006603337", item_id=840006603337)

    assert datos["seller_sku"] == "840006603337"
    assert datos["shipping_mode"] == "me2"
    assert datos["logistic_type"] == "cross_docking"
    assert datos["local_pick_up"] is True
    assert datos["free_shipping"] is True
    assert datos["store_pick_up"] is False
    assert datos["shipping_tags"] == ["self_service_in", "mandatory_free_shipping"]
