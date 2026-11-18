"""Regression: incremental + full liviano must map Full/Flex flags with key-present guard."""

from __future__ import annotations

import asyncio

import pytest

from app.models.mercadolibre_item_publicado import MercadoLibreItemPublicado
from app.scripts.sync_ml_items_publicados_full import apply_full_flex_flags as apply_full
from app.scripts.sync_ml_items_publicados_incremental import apply_full_flex_flags as apply_incremental
from app.scripts.sync_ml_items_publicados_incremental import procesar_items

APPLY_FNS = [
    pytest.param(apply_incremental, id="incremental"),
    pytest.param(apply_full, id="full"),
]


@pytest.mark.parametrize("apply_fn", APPLY_FNS)
def test_maps_both_flags_when_keys_present(apply_fn) -> None:
    item_dict: dict = {}
    apply_fn(
        item_dict,
        {
            "mlp_is4FulFillment": True,
            "mlp_is4FullAndFlex": "1",
        },
    )
    assert item_dict["mlp_is4FulFillment"] is True
    assert item_dict["mlp_is4FullAndFlex"] is True


@pytest.mark.parametrize("apply_fn", APPLY_FNS)
def test_absent_keys_do_not_set_fields(apply_fn) -> None:
    item_dict: dict = {}
    apply_fn(item_dict, {"mlp_id": 1, "mlp_itemTitle": "sin flags"})
    assert "mlp_is4FulFillment" not in item_dict
    assert "mlp_is4FullAndFlex" not in item_dict


@pytest.mark.parametrize("apply_fn", APPLY_FNS)
def test_present_false_allows_turning_flags_off(apply_fn) -> None:
    item_dict: dict = {}
    apply_fn(
        item_dict,
        {
            "mlp_is4FulFillment": False,
            "mlp_is4FullAndFlex": 0,
        },
    )
    assert item_dict["mlp_is4FulFillment"] is False
    assert item_dict["mlp_is4FullAndFlex"] is False


def test_incremental_update_absent_keys_do_not_clobber_existing_true(db) -> None:
    db.add(
        MercadoLibreItemPublicado(
            mlp_id=4242,
            mlp_publicationID="MLA42424242",
            mlp_itemTitle="seed",
            mlp_is4FulFillment=True,
            mlp_is4FullAndFlex=True,
        )
    )
    db.commit()

    asyncio.run(
        procesar_items(
            db,
            [
                {
                    "mlp_id": 4242,
                    "mlp_publicationID": "MLA42424242",
                    "mlp_itemTitle": "updated without flags",
                    "mlp_price": 100,
                }
            ],
            tipo="test",
        )
    )
    db.commit()

    row = db.query(MercadoLibreItemPublicado).filter(MercadoLibreItemPublicado.mlp_id == 4242).one()
    assert row.mlp_itemTitle == "updated without flags"
    assert row.mlp_is4FulFillment is True
    assert row.mlp_is4FullAndFlex is True

    asyncio.run(
        procesar_items(
            db,
            [
                {
                    "mlp_id": 4242,
                    "mlp_publicationID": "MLA42424242",
                    "mlp_itemTitle": "updated turning flags off",
                    "mlp_is4FulFillment": False,
                    "mlp_is4FullAndFlex": False,
                }
            ],
            tipo="test",
        )
    )
    db.commit()

    row = db.query(MercadoLibreItemPublicado).filter(MercadoLibreItemPublicado.mlp_id == 4242).one()
    assert row.mlp_is4FulFillment is False
    assert row.mlp_is4FullAndFlex is False
