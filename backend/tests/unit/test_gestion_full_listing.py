"""Unit tests for Gestión Full list shaping (no DB)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services.gestion_full.listing import _row_dict, _sugerido, list_gestion_full


def test_row_dict_maps_full_windows_and_leaves_later_fields_null() -> None:
    row = SimpleNamespace(
        producto_item_id=70,
        ean="1210002615013",
        descripcion="TAPO C200",
        marca="TP-LINK",
        categoria="Camaras",
        inventory_id="CBOW39035",
        user_product_id="MLAU1",
        mla="MLA1",
        stock_erp=30,
        stock_full=6,
        ventas_full_7d=8,
        ventas_full_14d=14,
        ventas_full_21d=19,
        ventas_full_30d=28,
        ventas_colecta_flex_7d=3,
        ventas_colecta_flex_30d=11,
        target=100,
        override=12,
    )
    out = _row_dict(row)
    assert out["ean"] == "1210002615013"
    assert out["inventory_id"] == "CBOW39035"
    assert out["ventas_full_30d"] == 28
    assert out["ventas_colecta_flex_7d"] == 3
    assert out["ventas_colecta_flex_30d"] == 11
    assert out["target"] == 100
    assert out["sugerido"] == 94  # 100 target - 6 stock_full
    assert out["override"] == 12
    assert out["puede_editar_override"] is False


def test_sugerido_replenish_to_last_inbound() -> None:
    assert _sugerido(100, 40) == 60
    assert _sugerido(100, 100) == 0
    assert _sugerido(100, 150) == 0
    assert _sugerido(100, None) == 100
    assert _sugerido(None, 40) is None


def test_list_gestion_full_passes_filters_and_pagination() -> None:
    db = MagicMock()
    count_result = MagicMock()
    count_result.scalar.return_value = 2
    list_result = MagicMock()
    list_result.mappings.return_value.all.return_value = [
        SimpleNamespace(
            producto_item_id=1,
            ean="EAN1",
            descripcion="A",
            marca="M",
            categoria="C",
            inventory_id="INV1",
            user_product_id="MLAU1",
            mla="MLA1",
            stock_erp=1,
            stock_full=2,
            ventas_full_7d=1,
            ventas_full_14d=2,
            ventas_full_21d=3,
            ventas_full_30d=4,
            ventas_colecta_flex_7d=0,
            ventas_colecta_flex_30d=2,
            target=None,
            override=None,
        )
    ]
    db.execute.side_effect = [count_result, list_result]

    payload = list_gestion_full(db, q="EAN", marca="M", categoria="C", limit=50, offset=10)

    assert payload["total"] == 2
    assert payload["limit"] == 50
    assert payload["offset"] == 10
    assert len(payload["items"]) == 1
    assert payload["items"][0]["inventory_id"] == "INV1"
    assert db.execute.call_count == 2
    params = db.execute.call_args_list[0].args[1]
    assert params["q"] == "EAN"
    assert params["marca"] == "M"
    assert params["categoria"] == "C"
    assert params["full_mode"] == "en"
    assert params["include_zero_stock"] == 0


def test_list_gestion_full_passes_full_mode_and_zero_stock_flag() -> None:
    db = MagicMock()
    count_result = MagicMock()
    count_result.scalar.return_value = 0
    list_result = MagicMock()
    list_result.mappings.return_value.all.return_value = []
    db.execute.side_effect = [count_result, list_result]

    list_gestion_full(db, full_mode="fuera", include_zero_stock=True)
    params = db.execute.call_args_list[0].args[1]
    assert params["full_mode"] == "fuera"
    assert params["include_zero_stock"] == 1


def test_list_gestion_full_normalizes_invalid_full_mode_to_en() -> None:
    db = MagicMock()
    count_result = MagicMock()
    count_result.scalar.return_value = 0
    list_result = MagicMock()
    list_result.mappings.return_value.all.return_value = []
    db.execute.side_effect = [count_result, list_result]

    list_gestion_full(db, full_mode="nope")
    params = db.execute.call_args_list[0].args[1]
    assert params["full_mode"] == "en"


def test_list_gestion_full_clamps_limit() -> None:
    db = MagicMock()
    count_result = MagicMock()
    count_result.scalar.return_value = 0
    list_result = MagicMock()
    list_result.mappings.return_value.all.return_value = []
    db.execute.side_effect = [count_result, list_result]

    payload = list_gestion_full(db, limit=9999, offset=-5)
    assert payload["limit"] == 500
    assert payload["offset"] == 0
