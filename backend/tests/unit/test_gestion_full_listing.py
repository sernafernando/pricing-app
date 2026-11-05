"""Unit tests for Gestión Full list shaping (no DB)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.services.gestion_full.listing import (
    _COUNT_SQL,
    _LIST_SQL,
    _row_dict,
    _sugerido,
    list_gestion_full,
)


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
        unidades_por_caja=6,
        qty_pm=12,
        pm_ready=True,
    )
    out = _row_dict(row)
    assert out["ean"] == "1210002615013"
    assert out["inventory_id"] == "CBOW39035"
    assert out["ventas_full_30d"] == 28
    assert out["ventas_colecta_flex_7d"] == 3
    assert out["ventas_colecta_flex_30d"] == 11
    assert out["target"] == 100
    assert out["sugerido"] == 30  # min(100-6, stock_erp 30)
    assert out["override"] == 12
    assert out["unidades_por_caja"] == 6
    assert out["qty_pm"] == 12
    assert out["pm_ready"] is True
    assert out["puede_editar_override"] is False


def test_sugerido_replenish_to_last_inbound_capped_by_stock_erp() -> None:
    assert _sugerido(100, 40, stock_erp=100) == 60
    assert _sugerido(100, 40, stock_erp=10) == 10
    assert _sugerido(100, 100, stock_erp=50) == 0
    assert _sugerido(100, 150, stock_erp=50) == 0
    assert _sugerido(100, None, stock_erp=80) == 80
    assert _sugerido(100, 40, stock_erp=None) == 0
    assert _sugerido(None, 40, stock_erp=10) is None


def _mock_db_for_list(list_rows: list | None = None) -> MagicMock:
    db = MagicMock()
    count_result = MagicMock()
    count_result.scalar.return_value = 2 if list_rows else 0
    list_result = MagicMock()
    list_result.mappings.return_value.all.return_value = list_rows or []
    facet_result = MagicMock()
    facet_result.all.return_value = [("M", "C", None, None)]
    db.execute.side_effect = [count_result, list_result, facet_result]
    return db


def test_list_gestion_full_passes_filters_and_pagination() -> None:
    list_rows = [
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
    db = _mock_db_for_list(list_rows)

    with patch(
        "app.services.gestion_full.listing.product_facet_options",
        return_value=MagicMock(model_dump=lambda: {"marcas": ["M"], "categorias": ["C"], "subcategorias": [], "pms": []}),
    ):
        payload = list_gestion_full(db, q="EAN", marcas=["M"], categorias=["C"], limit=50, offset=10)

    assert payload["total"] == 2
    assert payload["limit"] == 50
    assert payload["offset"] == 10
    assert len(payload["items"]) == 1
    assert payload["items"][0]["inventory_id"] == "INV1"
    assert payload["facets"]["product"]["marcas"] == ["M"]
    assert db.execute.call_count == 3
    params = db.execute.call_args_list[0].args[1]
    assert params["q"] == "EAN"
    assert params["has_marcas"] == 1
    assert params["marcas_upper"] == ["M"]
    assert params["has_categorias"] == 1
    assert params["categorias_upper"] == ["C"]
    assert params["full_mode"] == "en"
    assert params["include_zero_stock"] == 0
    assert params["has_pms"] == 0
    assert params["pms"] == []
    assert params["solo_listo"] == 0


def test_list_gestion_full_multi_marcas_uppercases_for_sql() -> None:
    db = _mock_db_for_list([])
    with patch(
        "app.services.gestion_full.listing.product_facet_options",
        return_value=MagicMock(
            model_dump=lambda: {"marcas": [], "categorias": [], "subcategorias": [], "pms": []}
        ),
    ):
        list_gestion_full(db, marcas=["tp-link", "EPSON"], categorias=["Camaras"])
    params = db.execute.call_args_list[0].args[1]
    assert params["has_marcas"] == 1
    assert params["marcas_upper"] == ["TP-LINK", "EPSON"]
    assert params["categorias_upper"] == ["CAMARAS"]


def test_list_gestion_full_passes_full_mode_and_zero_stock_flag() -> None:
    db = _mock_db_for_list([])
    with patch(
        "app.services.gestion_full.listing.product_facet_options",
        return_value=MagicMock(
            model_dump=lambda: {"marcas": [], "categorias": [], "subcategorias": [], "pms": []}
        ),
    ):
        list_gestion_full(db, full_mode="fuera", include_zero_stock=True)
    params = db.execute.call_args_list[0].args[1]
    assert params["full_mode"] == "fuera"
    assert params["include_zero_stock"] == 1
    assert params["has_marcas"] == 0
    assert params["marcas_upper"] == []


def test_list_gestion_full_normalizes_invalid_full_mode_to_en() -> None:
    db = _mock_db_for_list([])
    with patch(
        "app.services.gestion_full.listing.product_facet_options",
        return_value=MagicMock(
            model_dump=lambda: {"marcas": [], "categorias": [], "subcategorias": [], "pms": []}
        ),
    ):
        list_gestion_full(db, full_mode="nope")
    params = db.execute.call_args_list[0].args[1]
    assert params["full_mode"] == "en"


def test_list_gestion_full_clamps_limit() -> None:
    db = _mock_db_for_list([])
    with patch(
        "app.services.gestion_full.listing.product_facet_options",
        return_value=MagicMock(
            model_dump=lambda: {"marcas": [], "categorias": [], "subcategorias": [], "pms": []}
        ),
    ):
        payload = list_gestion_full(db, limit=9999, offset=-5)
    assert payload["limit"] == 500
    assert payload["offset"] == 0


def test_list_and_count_sql_match_family_id_exactly() -> None:
    for sql in (_LIST_SQL, _COUNT_SQL):
        text_sql = str(sql)
        assert "linked.family_id" in text_sql
        assert "CAST(linked.family_id AS TEXT) = :q" in text_sql


def test_list_gestion_full_include_facets_false_skips_facet_query() -> None:
    db = MagicMock()
    count_result = MagicMock()
    count_result.scalar.return_value = 0
    list_result = MagicMock()
    list_result.mappings.return_value.all.return_value = []
    db.execute.side_effect = [count_result, list_result]

    payload = list_gestion_full(db, include_facets=False)
    assert db.execute.call_count == 2
    assert payload["facets"]["product"]["marcas"] == []
    assert payload["facets"]["product"]["categorias"] == []
