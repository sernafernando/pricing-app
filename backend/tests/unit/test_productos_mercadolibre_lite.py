"""
Unit tests for the `lite` query param on
GET /productos/{item_id}/mercadolibre.

The promotions panel (ProductoMLAsPanel) only needs persisted fields
(mla, lista_nombre, pricelist_id, publication_status). It does NOT need
the live ml-webhook enrichment (precio_ml, catalog_product_id, etc).

`lite=true` must skip the live `ml_webhook_client.get_items_batch(...)` call.
`lite` absent/false must keep calling it (regression — ModalInfoProducto
depends on the full response).

NOTE: this is a unit test (mocked `db`) rather than a full TestClient
integration test. `obtener_datos_ml_producto` uses raw Postgres SQL
(`mla = ANY(:mla_ids)`) which the sqlite-backed test DB cannot execute,
so we drive the endpoint function directly with a mocked session instead.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.api.endpoints.productos_detail import obtener_datos_ml_producto


def _make_db(pub_row) -> MagicMock:
    """Build a mocked db.query()/db.execute() session returning one publication."""
    db = MagicMock()

    # db.query(PublicacionML).filter(...).all() -> [pub_row]
    db.query.return_value.filter.return_value.all.return_value = [pub_row]

    # every db.execute(...) call (precios_ml, catalog status, pub status) -> empty
    empty_result = MagicMock()
    empty_result.fetchall.return_value = []
    db.execute.return_value = empty_result

    return db


def _pub_row() -> SimpleNamespace:
    return SimpleNamespace(
        mla="MLA9101",
        item_title="Producto test lite",
        lista_nombre="Clásica",
        pricelist_id=4,
    )


class TestMercadolibreLiteParam:
    def test_lite_true_skips_live_batch_call(self) -> None:
        db = _make_db(_pub_row())
        current_user = SimpleNamespace(id=1)

        with patch(
            "app.services.ml_webhook_client.ml_webhook_client.get_items_batch",
            new_callable=AsyncMock,
        ) as mock_batch:
            result = asyncio.run(obtener_datos_ml_producto(item_id=9101, db=db, current_user=current_user, lite=True))

        mock_batch.assert_not_called()

        publicaciones = result["publicaciones_ml"]
        assert len(publicaciones) == 1
        assert publicaciones[0]["mla"] == "MLA9101"
        assert publicaciones[0]["lista_nombre"] == "Clásica"
        assert publicaciones[0]["pricelist_id"] == 4

    def test_lite_absent_still_calls_live_batch(self) -> None:
        db = _make_db(_pub_row())
        current_user = SimpleNamespace(id=1)

        with patch(
            "app.services.ml_webhook_client.ml_webhook_client.get_items_batch",
            new_callable=AsyncMock,
            return_value={},
        ) as mock_batch:
            asyncio.run(obtener_datos_ml_producto(item_id=9101, db=db, current_user=current_user))

        mock_batch.assert_called_once()

    def test_lite_false_still_calls_live_batch(self) -> None:
        db = _make_db(_pub_row())
        current_user = SimpleNamespace(id=1)

        with patch(
            "app.services.ml_webhook_client.ml_webhook_client.get_items_batch",
            new_callable=AsyncMock,
            return_value={},
        ) as mock_batch:
            asyncio.run(obtener_datos_ml_producto(item_id=9101, db=db, current_user=current_user, lite=False))

        mock_batch.assert_called_once()


class TestPromoSummaryEnrichment:
    """T2 — promo_active_count / promo_has_applied / promo_applied_name
    enrichment via fetch_promo_summary_by_mla, merged per-mla into
    publicaciones_ml. Graceful degradation: enrichment failure never
    breaks the endpoint (still 200, full publicaciones list, fields absent).
    """

    def test_success_path_adds_promo_fields_per_mla(self) -> None:
        db = _make_db(_pub_row())
        current_user = SimpleNamespace(id=1)

        with (
            patch(
                "app.services.ml_webhook_client.ml_webhook_client.get_items_batch",
                new_callable=AsyncMock,
            ),
            patch(
                "app.api.endpoints.productos_detail.fetch_promo_summary_by_mla",
                return_value={
                    "MLA9101": {
                        "active_count": 2,
                        "has_applied": True,
                        "applied_name": "Oferta Relámpago",
                    }
                },
            ) as mock_summary,
        ):
            result = asyncio.run(obtener_datos_ml_producto(item_id=9101, db=db, current_user=current_user, lite=True))

        mock_summary.assert_called_once_with(["MLA9101"])
        publicaciones = result["publicaciones_ml"]
        assert publicaciones[0]["promo_active_count"] == 2
        assert publicaciones[0]["promo_has_applied"] is True
        assert publicaciones[0]["promo_applied_name"] == "Oferta Relámpago"

    def test_mla_absent_from_summary_leaves_fields_absent(self) -> None:
        db = _make_db(_pub_row())
        current_user = SimpleNamespace(id=1)

        with (
            patch(
                "app.services.ml_webhook_client.ml_webhook_client.get_items_batch",
                new_callable=AsyncMock,
            ),
            patch(
                "app.api.endpoints.productos_detail.fetch_promo_summary_by_mla",
                return_value={},
            ),
        ):
            result = asyncio.run(obtener_datos_ml_producto(item_id=9101, db=db, current_user=current_user, lite=True))

        publicaciones = result["publicaciones_ml"]
        assert "promo_active_count" not in publicaciones[0]
        assert "promo_has_applied" not in publicaciones[0]
        assert "promo_applied_name" not in publicaciones[0]

    def test_summary_runtime_error_degrades_gracefully(self) -> None:
        """ML_WEBHOOK_DB_URL unset -> RuntimeError -> endpoint still 200
        with full publicaciones list, no promo fields."""
        db = _make_db(_pub_row())
        current_user = SimpleNamespace(id=1)

        with (
            patch(
                "app.services.ml_webhook_client.ml_webhook_client.get_items_batch",
                new_callable=AsyncMock,
            ),
            patch(
                "app.api.endpoints.productos_detail.fetch_promo_summary_by_mla",
                side_effect=RuntimeError("ML_WEBHOOK_DB_URL no configurada"),
            ),
        ):
            result = asyncio.run(obtener_datos_ml_producto(item_id=9101, db=db, current_user=current_user, lite=True))

        publicaciones = result["publicaciones_ml"]
        assert len(publicaciones) == 1
        assert publicaciones[0]["mla"] == "MLA9101"
        assert "promo_active_count" not in publicaciones[0]

    def test_summary_generic_exception_degrades_gracefully(self) -> None:
        db = _make_db(_pub_row())
        current_user = SimpleNamespace(id=1)

        with (
            patch(
                "app.services.ml_webhook_client.ml_webhook_client.get_items_batch",
                new_callable=AsyncMock,
            ),
            patch(
                "app.api.endpoints.productos_detail.fetch_promo_summary_by_mla",
                side_effect=Exception("connection refused"),
            ),
        ):
            result = asyncio.run(obtener_datos_ml_producto(item_id=9101, db=db, current_user=current_user, lite=True))

        publicaciones = result["publicaciones_ml"]
        assert len(publicaciones) == 1
        assert publicaciones[0]["mla"] == "MLA9101"


class TestMatchesFilter:
    """T8 — per-MLA `matches_filter` on the lite endpoint (feature
    productos-promo-filter-per-mla). Reuses `select_promo_resolver` (SAME
    dispatch as the list endpoint) bounded by the product's own `mla_ids`,
    never a second independent predicate. Fail-open: unavailable cross-DB
    never hides publications nor raises 503."""

    def _make_db_two_pubs(self) -> MagicMock:
        db = MagicMock()
        pub_a = SimpleNamespace(mla="MLA_A", item_title="A", lista_nombre="Clásica", pricelist_id=4)
        pub_b = SimpleNamespace(mla="MLA_B", item_title="B", lista_nombre="Clásica", pricelist_id=4)
        db.query.return_value.filter.return_value.all.return_value = [pub_a, pub_b]
        empty_result = MagicMock()
        empty_result.fetchall.return_value = []
        db.execute.return_value = empty_result
        return db

    def test_no_filter_active_matches_filter_absent_for_all(self) -> None:
        db = self._make_db_two_pubs()
        current_user = SimpleNamespace(id=1)

        with (
            patch(
                "app.services.ml_webhook_client.ml_webhook_client.get_items_batch",
                new_callable=AsyncMock,
            ),
            patch("app.api.endpoints.productos_detail.fetch_mlas_with_active_promo_type") as mock_resolver,
        ):
            result = asyncio.run(obtener_datos_ml_producto(item_id=9101, db=db, current_user=current_user, lite=True))

        mock_resolver.assert_not_called()
        for pub in result["publicaciones_ml"]:
            assert "matches_filter" not in pub

    def test_filter_active_bounded_to_product_mla_ids_and_per_pub_membership(self) -> None:
        db = self._make_db_two_pubs()
        current_user = SimpleNamespace(id=1)

        with (
            patch(
                "app.services.ml_webhook_client.ml_webhook_client.get_items_batch",
                new_callable=AsyncMock,
            ),
            patch(
                "app.api.endpoints.productos_detail.fetch_mlas_with_active_promo_type",
                return_value={"MLA_A"},
            ) as mock_resolver,
        ):
            result = asyncio.run(
                obtener_datos_ml_producto(
                    item_id=9101,
                    db=db,
                    current_user=current_user,
                    lite=True,
                    promo_tipos="Campaña",
                    promo_estado="aplicada",
                )
            )

        mock_resolver.assert_called_once_with(["Campaña"], True, mla_ids=["MLA_A", "MLA_B"])
        publicaciones = {p["mla"]: p for p in result["publicaciones_ml"]}
        assert publicaciones["MLA_A"]["matches_filter"] is True
        assert publicaciones["MLA_B"]["matches_filter"] is False

    def test_cross_db_unavailable_fails_open_no_503_no_hiding(self) -> None:
        db = self._make_db_two_pubs()
        current_user = SimpleNamespace(id=1)

        with (
            patch(
                "app.services.ml_webhook_client.ml_webhook_client.get_items_batch",
                new_callable=AsyncMock,
            ),
            patch(
                "app.api.endpoints.productos_detail.fetch_mlas_with_active_promo_type",
                side_effect=RuntimeError("ML_WEBHOOK_DB_URL no configurada"),
            ),
        ):
            result = asyncio.run(
                obtener_datos_ml_producto(
                    item_id=9101,
                    db=db,
                    current_user=current_user,
                    lite=True,
                    promo_tipos="Campaña",
                    promo_estado="aplicada",
                )
            )

        assert len(result["publicaciones_ml"]) == 2
        for pub in result["publicaciones_ml"]:
            assert pub.get("matches_filter") is not False

    def test_candidate_but_not_started_under_aplicada_does_not_overclaim(self) -> None:
        """`promo_estado=aplicada` must not mark matches_filter=true unless
        `ml_item_promotions` confirms status='started' — driven entirely by
        the resolver's own SQL (status='started'), never by
        promo_active_count/promo_has_applied hints."""
        db = self._make_db_two_pubs()
        current_user = SimpleNamespace(id=1)

        with (
            patch(
                "app.services.ml_webhook_client.ml_webhook_client.get_items_batch",
                new_callable=AsyncMock,
            ),
            patch(
                "app.api.endpoints.productos_detail.fetch_mlas_with_active_promo_type",
                return_value=set(),
            ),
        ):
            result = asyncio.run(
                obtener_datos_ml_producto(
                    item_id=9101,
                    db=db,
                    current_user=current_user,
                    lite=True,
                    promo_tipos="Campaña",
                    promo_estado="aplicada",
                )
            )

        for pub in result["publicaciones_ml"]:
            assert pub["matches_filter"] is False


class TestExistingFieldsUnchangedOnSuccess:
    def test_existing_fields_unchanged_on_success(self) -> None:
        """R7 — pre-existing fields/values unchanged, only new keys added."""
        db = _make_db(_pub_row())
        current_user = SimpleNamespace(id=1)

        with (
            patch(
                "app.services.ml_webhook_client.ml_webhook_client.get_items_batch",
                new_callable=AsyncMock,
            ),
            patch(
                "app.api.endpoints.productos_detail.fetch_promo_summary_by_mla",
                return_value={},
            ),
        ):
            result = asyncio.run(obtener_datos_ml_producto(item_id=9101, db=db, current_user=current_user, lite=True))

        pub = result["publicaciones_ml"][0]
        assert pub["mla"] == "MLA9101"
        assert pub["titulo"] == "Producto test lite"
        assert pub["lista_nombre"] == "Clásica"
        assert pub["pricelist_id"] == 4


class TestPromoEstadoValidation:
    """`promo_estado` must be validated identically to the LISTADO endpoint so
    both call sites of `select_promo_resolver` reject the same inputs. An
    unrecognized value must 422, not silently degrade to `disponible`
    semantics via the resolver's `applied_only` fallback."""

    def test_invalid_promo_estado_raises_422(self) -> None:
        db = _make_db(_pub_row())
        current_user = SimpleNamespace(id=1)

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(
                obtener_datos_ml_producto(
                    item_id=9101,
                    db=db,
                    current_user=current_user,
                    lite=True,
                    promo_tipos="Campaña",
                    promo_estado="bogus",
                )
            )

        assert exc_info.value.status_code == 422

    @pytest.mark.parametrize("estado", ["disponible", "aplicada", "sin_aplicar", None])
    def test_valid_promo_estado_does_not_raise(self, estado) -> None:
        db = _make_db(_pub_row())
        current_user = SimpleNamespace(id=1)

        with (
            patch(
                "app.services.ml_webhook_client.ml_webhook_client.get_items_batch",
                new_callable=AsyncMock,
            ),
            patch(
                "app.api.endpoints.productos_detail.fetch_mlas_with_active_promo_type",
                return_value=set(),
            ),
            patch(
                "app.api.endpoints.productos_detail.fetch_mlas_with_candidate_only_for_types",
                return_value=set(),
            ),
        ):
            result = asyncio.run(
                obtener_datos_ml_producto(
                    item_id=9101,
                    db=db,
                    current_user=current_user,
                    lite=True,
                    promo_tipos="Campaña" if estado is not None else None,
                    promo_estado=estado,
                )
            )

        assert "publicaciones_ml" in result
