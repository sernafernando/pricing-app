"""Per-publication (`matches_filter`) fold for the wholesale-tier (PxQ)
filter, on both the flat `/mercadolibre` endpoint and the recursive
`/mercadolibre/tree` one.

Filtering the LISTING by "con precios mayoristas" and then showing every
publication of a matching product is only half the filter: a product usually
has several MLAs and only some carry tiers. This joins the mechanism that
already exists for promos and official stores (`_compose_matches`), rather
than adding a second, parallel one.

Same mocked-session strategy as `test_productos_mercadolibre_lite.py`: these
endpoints issue raw Postgres SQL that sqlite cannot run, so the endpoint
functions are driven directly.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy.exc import SQLAlchemyError

from app.api.endpoints.productos_detail import obtener_arbol_ml_producto, obtener_datos_ml_producto

_PXQ_READER = "app.api.endpoints.productos_detail.fetch_mlas_with_pxq_tiers"
_PROMO_READER = "app.api.endpoints.productos_detail.fetch_mlas_with_active_promo_type"


def _make_db_two_pubs() -> MagicMock:
    db = MagicMock()
    pub_a = SimpleNamespace(mla="MLA_A", item_title="A", lista_nombre="Clásica", pricelist_id=4)
    pub_b = SimpleNamespace(mla="MLA_B", item_title="B", lista_nombre="Clásica", pricelist_id=4)
    db.query.return_value.filter.return_value.all.return_value = [pub_a, pub_b]
    empty_result = MagicMock()
    empty_result.fetchall.return_value = []
    db.execute.return_value = empty_result
    return db


def _run_flat(**kwargs):
    with patch("app.services.ml_webhook_client.ml_webhook_client.get_items_batch", new_callable=AsyncMock):
        return asyncio.run(
            obtener_datos_ml_producto(
                item_id=9101, db=_make_db_two_pubs(), current_user=SimpleNamespace(id=1), lite=True, **kwargs
            )
        )


class TestFlatEndpointPxqMatchesFilter:
    def test_con_pxq_absent_does_not_call_the_reader(self) -> None:
        with patch(_PXQ_READER) as mock_reader:
            result = _run_flat()

        mock_reader.assert_not_called()
        for pub in result["publicaciones_ml"]:
            assert "matches_filter" not in pub

    def test_con_pxq_marks_only_the_publications_that_have_tiers(self) -> None:
        with patch(_PXQ_READER, return_value={"MLA_A"}) as mock_reader:
            result = _run_flat(con_pxq=True)

        mock_reader.assert_called_once_with(mla_ids=["MLA_A", "MLA_B"])
        pubs = {p["mla"]: p for p in result["publicaciones_ml"]}
        assert pubs["MLA_A"]["matches_filter"] is True
        assert pubs["MLA_B"]["matches_filter"] is False

    def test_cross_db_failure_fails_open_never_hides_a_publication(self) -> None:
        with patch(_PXQ_READER, side_effect=SQLAlchemyError("down")):
            result = _run_flat(con_pxq=True)

        assert len(result["publicaciones_ml"]) == 2
        for pub in result["publicaciones_ml"]:
            assert pub.get("matches_filter") is not False

    def test_composes_with_the_promo_filter_by_and_not_by_replacement(self) -> None:
        """Both filters on: only a publication satisfying BOTH matches."""
        with (
            patch(_PXQ_READER, return_value={"MLA_A", "MLA_B"}),
            patch(_PROMO_READER, return_value={"MLA_B"}),
        ):
            result = _run_flat(con_pxq=True, promo_tipos="SMART")

        pubs = {p["mla"]: p for p in result["publicaciones_ml"]}
        assert pubs["MLA_B"]["matches_filter"] is True
        assert pubs["MLA_A"]["matches_filter"] is False

    def test_pxq_failure_does_not_wipe_the_promo_verdict(self) -> None:
        """Fail-open on one filter keeps the other's answer — degrading must
        not silently widen the OTHER active filter."""
        with (
            patch(_PXQ_READER, side_effect=RuntimeError("down")),
            patch(_PROMO_READER, return_value={"MLA_B"}),
        ):
            result = _run_flat(con_pxq=True, promo_tipos="SMART")

        pubs = {p["mla"]: p for p in result["publicaciones_ml"]}
        assert pubs["MLA_B"]["matches_filter"] is True
        assert pubs["MLA_A"]["matches_filter"] is False


def _run_tree(**kwargs):
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = [
        SimpleNamespace(mla="MLA_A"),
        SimpleNamespace(mla="MLA_B"),
    ]
    with (
        patch("app.api.endpoints.productos_detail.lazy_fill_links"),
        patch("app.api.endpoints.productos_detail.fetch_promo_node_summary_by_mla", return_value={}),
        patch("app.api.endpoints.productos_detail.assemble_publication_tree") as mock_assemble,
    ):
        obtener_arbol_ml_producto(item_id=9101, db=db, current_user=SimpleNamespace(id=1), **kwargs)
    return mock_assemble.call_args.kwargs["matches_filter_by_mla"]


class TestTreeEndpointPxqMatchesFilter:
    def test_con_pxq_absent_leaves_matches_filter_unset(self) -> None:
        with patch(_PXQ_READER) as mock_reader:
            assert _run_tree() is None

        mock_reader.assert_not_called()

    def test_con_pxq_marks_only_the_nodes_that_have_tiers(self) -> None:
        with patch(_PXQ_READER, return_value={"MLA_A"}):
            assert _run_tree(con_pxq=True) == {"MLA_A": True, "MLA_B": False}

    def test_cross_db_failure_fails_open(self) -> None:
        with patch(_PXQ_READER, side_effect=SQLAlchemyError("down")):
            assert _run_tree(con_pxq=True) is None

    def test_composes_with_the_promo_filter(self) -> None:
        with (
            patch(_PXQ_READER, return_value={"MLA_A", "MLA_B"}),
            patch(_PROMO_READER, return_value={"MLA_B"}),
        ):
            assert _run_tree(con_pxq=True, promo_tipos="SMART") == {"MLA_A": False, "MLA_B": True}
