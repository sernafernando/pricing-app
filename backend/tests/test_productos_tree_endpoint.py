"""
RED/GREEN — `GET /productos/{item_id}/mercadolibre/tree` endpoint
(productos-catalog-family-tree PR2, tasks 14/15).

Unit-tests the endpoint FUNCTION directly (mirrors
`test_productos_mercadolibre_lite.py`'s pattern) since the sibling flat
endpoint's raw-SQL steps aren't sqlite-portable; the tree endpoint itself
is pure ORM + service calls, but we still avoid a full TestClient round
trip to keep the lazy-fill / promo-resolver mocking simple and explicit.

Spec coverage:
  - keeps the existing flat endpoint untouched (separate route).
  - returns the recursive node JSON described by the design.
  - lazy-fill: the endpoint calls `lazy_fill_links` (pool-safe, decoupled
    from the request `db` session — see review fix 1/4) before assembly.
  - graceful degradation: `lazy_fill_links` never raises (fail-open by
    contract) so a proxy failure never surfaces as a 500/503 here.
  - partial-data fail-open: one mla lacking a link row still returns a
    best-effort tree (plain leaf), no 500.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.api.endpoints.productos_detail import obtener_arbol_ml_producto


def _pub(mla: str) -> SimpleNamespace:
    return SimpleNamespace(mla=mla)


def _make_db(pubs) -> MagicMock:
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = pubs
    return db


class TestTreeEndpointLazyFill:
    def test_calls_lazy_fill_links_before_assembly(self) -> None:
        db = _make_db([_pub("MLA1")])
        current_user = SimpleNamespace(id=1)

        with (
            patch("app.api.endpoints.productos_detail.lazy_fill_links") as mock_fill,
            patch("app.api.endpoints.productos_detail.assemble_publication_tree") as mock_assemble,
        ):
            mock_assemble.return_value = SimpleNamespace(
                item_id=1,
                tree=SimpleNamespace(level=0, kind="producto", children=[]),
                skipped_anomalous_edges=0,
                skipped_edges=[],
            )
            obtener_arbol_ml_producto(item_id=1, db=db, current_user=current_user)

        mock_fill.assert_called_once_with(["MLA1"], 1)

    def test_lazy_fill_noop_still_returns_degraded_tree(self) -> None:
        """`lazy_fill_links` is fail-open by its OWN contract (never
        raises internally). Here it's a no-op (as it would be if the
        proxy were down and every failure were swallowed inside it) and
        the endpoint must still return a best-effort tree."""
        db = _make_db([_pub("MLA1")])
        current_user = SimpleNamespace(id=1)

        with (
            patch("app.api.endpoints.productos_detail.lazy_fill_links", return_value=None) as mock_fill,
            patch("app.api.endpoints.productos_detail.assemble_publication_tree") as mock_assemble,
        ):
            mock_assemble.return_value = SimpleNamespace(
                item_id=1,
                tree=SimpleNamespace(level=0, kind="producto", children=[]),
                skipped_anomalous_edges=0,
                skipped_edges=[],
            )
            result = obtener_arbol_ml_producto(item_id=1, db=db, current_user=current_user)

        mock_fill.assert_called_once()
        assert result.item_id == 1


class TestTreeEndpointResponse:
    def test_returns_recursive_tree_json(self) -> None:
        db = _make_db([])
        current_user = SimpleNamespace(id=1)

        with (
            patch("app.api.endpoints.productos_detail.lazy_fill_links") as mock_fill,
            patch("app.api.endpoints.productos_detail.assemble_publication_tree") as mock_assemble,
        ):
            mock_assemble.return_value = SimpleNamespace(
                item_id=42,
                tree=SimpleNamespace(level=0, kind="producto", children=[]),
                skipped_anomalous_edges=0,
                skipped_edges=[],
            )
            result = obtener_arbol_ml_producto(item_id=42, db=db, current_user=current_user)

        # no MLAs for this product -> lazy-fill is never invoked at all.
        mock_fill.assert_not_called()
        assert result.item_id == 42
        assert result.tree.kind == "producto"


class TestTreeEndpointPartialDataFailOpen:
    def test_one_mla_missing_link_row_still_returns_best_effort_tree(self) -> None:
        """Integration-ish: real assemble_publication_tree, real (sqlite) db
        fixture, one mla with NO ml_publication_links row -> still 200,
        plain leaf, no 500."""
        pytest.importorskip("app.models.ml_publication_link")

    def test_via_real_db_fixture(self, db) -> None:
        from app.models.producto import ProductoERP
        from app.models.publicacion_ml import PublicacionML

        db.add(ProductoERP(item_id=777, codigo="C777", descripcion="Producto 777"))
        db.flush()
        db.add(PublicacionML(mla="MLA777", item_id=777, pricelist_id=4, activo=True))
        db.commit()

        current_user = SimpleNamespace(id=1)

        with patch("app.api.endpoints.productos_detail.lazy_fill_links"):
            result = obtener_arbol_ml_producto(item_id=777, db=db, current_user=current_user)

        assert result.item_id == 777
        assert len(result.tree.children) == 1
        assert result.tree.children[0].mla == "MLA777"
        assert result.tree.children[0].kind == "publicacion"


class TestTreeEndpointPromoNodeSummary:
    """catalog-tree-node-summary PR — the tree endpoint batch-fetches the
    collapsed-node promo summary ONCE (no N+1) and forwards it into
    `assemble_publication_tree`, fail-open on cross-DB failure."""

    def test_batch_fetches_summary_once_and_forwards_to_assembly(self) -> None:
        db = _make_db([_pub("MLA1"), _pub("MLA2")])
        current_user = SimpleNamespace(id=1)

        with (
            patch("app.api.endpoints.productos_detail.lazy_fill_links"),
            patch("app.api.endpoints.productos_detail.assemble_publication_tree") as mock_assemble,
            patch("app.api.endpoints.productos_detail.fetch_promo_node_summary_by_mla") as mock_summary,
        ):
            mock_summary.return_value = {"MLA1": {"started_count": 1, "candidate_count": 0}}
            mock_assemble.return_value = SimpleNamespace(
                item_id=1,
                tree=SimpleNamespace(level=0, kind="producto", children=[]),
                skipped_anomalous_edges=0,
                skipped_edges=[],
            )
            obtener_arbol_ml_producto(item_id=1, db=db, current_user=current_user)

        mock_summary.assert_called_once_with(["MLA1", "MLA2"])
        _, kwargs = mock_assemble.call_args
        assert kwargs["promo_summary_by_mla"] == {"MLA1": {"started_count": 1, "candidate_count": 0}}

    def test_cross_db_failure_is_fail_open_tree_still_returns(self) -> None:
        """A RuntimeError (ML_WEBHOOK_DB_URL unset) or a SQLAlchemyError
        must never 500 the tree — the summary field is simply absent."""
        db = _make_db([_pub("MLA1")])
        current_user = SimpleNamespace(id=1)

        with (
            patch("app.api.endpoints.productos_detail.lazy_fill_links"),
            patch("app.api.endpoints.productos_detail.assemble_publication_tree") as mock_assemble,
            patch(
                "app.api.endpoints.productos_detail.fetch_promo_node_summary_by_mla",
                side_effect=RuntimeError("ML_WEBHOOK_DB_URL no configurada"),
            ),
        ):
            mock_assemble.return_value = SimpleNamespace(
                item_id=1,
                tree=SimpleNamespace(level=0, kind="producto", children=[]),
                skipped_anomalous_edges=0,
                skipped_edges=[],
            )
            result = obtener_arbol_ml_producto(item_id=1, db=db, current_user=current_user)

        assert result.item_id == 1
        _, kwargs = mock_assemble.call_args
        assert kwargs["promo_summary_by_mla"] is None

    def test_no_mlas_never_calls_summary_fetch(self) -> None:
        db = _make_db([])
        current_user = SimpleNamespace(id=1)

        with (
            patch("app.api.endpoints.productos_detail.lazy_fill_links"),
            patch("app.api.endpoints.productos_detail.assemble_publication_tree") as mock_assemble,
            patch("app.api.endpoints.productos_detail.fetch_promo_node_summary_by_mla") as mock_summary,
        ):
            mock_assemble.return_value = SimpleNamespace(
                item_id=42,
                tree=SimpleNamespace(level=0, kind="producto", children=[]),
                skipped_anomalous_edges=0,
                skipped_edges=[],
            )
            obtener_arbol_ml_producto(item_id=42, db=db, current_user=current_user)

        mock_summary.assert_not_called()
