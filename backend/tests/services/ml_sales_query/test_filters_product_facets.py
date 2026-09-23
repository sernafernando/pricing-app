"""RED/GREEN tests for the D12a product-level facet filters (`marcas`,
`subcategorias`, `pms`) on `build_scope` (PFILT R35-R43).

PR9.T10/T10a/T12/T13/T15a/T16a-d: these tests seed `MlOrderItemCosto` rows
(the frozen cost snapshot) joined to `ProductoERP` (the catalog) and assert
`build_scope`'s `listing_query` includes/excludes GROUPS (never bare rows)
according to the facet contract:

- R38 conjunction: one item must satisfy ALL active facets at once.
- R39 unresolved items: no `ml_order_item_costos` row never matches a
  facet, and never drops the sale when no facet is active.
- R36a/R37: no publication-status/official-store filter exists on this
  screen -- proven by a same-request-with/without comparison, not by
  omission.
"""

from __future__ import annotations

import dataclasses


from datetime import datetime, timezone

import pytest

from app.core.config import settings
from app.core.security import get_password_hash
from app.models.marca_pm import MarcaPM
from app.models.ml_order_item_costo import MlOrderItemCosto
from app.models.ml_orders_ops import MlOrdersOps
from app.models.producto import ProductoERP
from app.models.usuario import AuthProvider, RolUsuario, Usuario
from app.services.ml_sales_query.filters import SalesFilter, build_scope


@pytest.fixture(autouse=True)
def _seller(monkeypatch):
    monkeypatch.setattr(settings, "ML_USER_ID", 999)


def _seed_order(db, order_id: int, *, pack_id: int | None = None, date_created=None) -> None:
    if date_created is None:
        date_created = datetime(2026, 1, 1, tzinfo=timezone.utc)
    db.add(
        MlOrdersOps(
            order_id=order_id,
            pack_id=pack_id,
            status="paid",
            ml_last_updated=date_created,
            date_created=date_created,
            seller_id=999,
            total_amount=100,
            paid_amount=100,
            currency_id="ARS",
        )
    )
    db.flush()


def _seed_producto(db, item_id: int, *, marca: str, categoria: str, subcategoria_id: int) -> None:
    db.add(
        ProductoERP(
            item_id=item_id,
            codigo=f"COD{item_id}",
            descripcion=f"Producto {item_id}",
            marca=marca,
            categoria=categoria,
            subcategoria_id=subcategoria_id,
        )
    )
    db.flush()


def _seed_costo(db, order_id: int, item_id: str, producto_item_id: int) -> None:
    db.add(
        MlOrderItemCosto(
            order_id=order_id,
            item_id=item_id,
            variation_id=None,
            costo_origen=100,
            moneda="ARS",
            costo_unitario_ars=100,
            iva_pct=21,
            precio_unitario=150,
            fuente="test",
            producto_item_id=producto_item_id,
        )
    )
    db.flush()


def _seed_pm_user(db, user_id: int, username: str) -> Usuario:
    user = Usuario(
        id=user_id,
        username=username,
        email=f"{username}@example.com",
        nombre=username,
        password_hash=get_password_hash("TestPass123!"),
        rol=RolUsuario.VENTAS,
        auth_provider=AuthProvider.LOCAL,
        activo=True,
    )
    db.add(user)
    db.flush()
    return user


def _ids(db, scope):
    return {row.order_id for row in scope.listing_query.with_entities(MlOrdersOps.order_id).all()}


class TestMarcaFilter:
    def test_matches_case_insensitively(self, db):
        _seed_order(db, 1)
        _seed_producto(db, 100, marca="Epson", categoria="Impresoras", subcategoria_id=1)
        _seed_costo(db, 1, "MLA1", 100)
        scope = build_scope(db, SalesFilter(marcas=("epson",)))
        assert _ids(db, scope) == {1}

    def test_non_matching_brand_excludes_the_sale(self, db):
        _seed_order(db, 2)
        _seed_producto(db, 200, marca="Lexmark", categoria="Impresoras", subcategoria_id=1)
        _seed_costo(db, 2, "MLA2", 200)
        scope = build_scope(db, SalesFilter(marcas=("epson",)))
        assert _ids(db, scope) == set()


class TestSubcategoriaFilter:
    def test_matches_by_id(self, db):
        _seed_order(db, 3)
        _seed_producto(db, 300, marca="Epson", categoria="Impresoras", subcategoria_id=42)
        _seed_costo(db, 3, "MLA3", 300)
        scope = build_scope(db, SalesFilter(subcategorias=(42,)))
        assert _ids(db, scope) == {3}

    def test_non_matching_id_excludes(self, db):
        _seed_order(db, 4)
        _seed_producto(db, 400, marca="Epson", categoria="Impresoras", subcategoria_id=1)
        _seed_costo(db, 4, "MLA4", 400)
        scope = build_scope(db, SalesFilter(subcategorias=(999,)))
        assert _ids(db, scope) == set()


class TestPmFilter:
    def test_pm_with_assigned_pairs_filters_by_them(self, db):
        _seed_order(db, 5)
        _seed_producto(db, 500, marca="Epson", categoria="Impresoras", subcategoria_id=1)
        _seed_costo(db, 5, "MLA5", 500)
        _seed_pm_user(db, 7, "pm7")
        db.add(MarcaPM(marca="Epson", categoria="Impresoras", usuario_id=7))
        db.flush()
        scope = build_scope(db, SalesFilter(pms=(7,)))
        assert _ids(db, scope) == {5}

    def test_pm_with_no_assigned_pairs_yields_empty_result(self, db):
        """R39/binding decision: a PM with no pairs returns EMPTY, never
        every sale."""
        _seed_order(db, 6)
        _seed_producto(db, 600, marca="Epson", categoria="Impresoras", subcategoria_id=1)
        _seed_costo(db, 6, "MLA6", 600)
        scope = build_scope(db, SalesFilter(pms=(999999,)))
        assert _ids(db, scope) == set()

    def test_pm_pair_wrong_categoria_does_not_match(self, db):
        _seed_order(db, 7)
        _seed_producto(db, 700, marca="Epson", categoria="Consumibles", subcategoria_id=1)
        _seed_costo(db, 7, "MLA7", 700)
        _seed_pm_user(db, 8, "pm8")
        db.add(MarcaPM(marca="Epson", categoria="Impresoras", usuario_id=8))
        db.flush()
        scope = build_scope(db, SalesFilter(pms=(8,)))
        assert _ids(db, scope) == set()


class TestUnresolvedItems:
    def test_no_cost_row_never_matches_a_facet_directly(self, db):
        _seed_order(db, 8)
        # No MlOrderItemCosto row at all for order 8.
        scope = build_scope(db, SalesFilter(marcas=("epson",)))
        assert _ids(db, scope) == set()

    def test_no_facet_active_still_returns_unresolved_sale(self, db):
        """R39: with NO product facet active, a sale whose only item has no
        `producto_item_id` row is still returned."""
        _seed_order(db, 9)
        scope = build_scope(db, SalesFilter())
        assert _ids(db, scope) == {9}

    def test_unrelated_filter_does_not_drop_pack_with_one_unresolved_sibling(self, db):
        """R39 pack case: pack has two orders, one item resolves and
        matches, the other has no cost row at all -- the pack must still
        come back whole."""
        _seed_order(db, 10, pack_id=555)
        _seed_order(db, 11, pack_id=555)
        _seed_producto(db, 1000, marca="Epson", categoria="Impresoras", subcategoria_id=1)
        _seed_costo(db, 10, "MLA10", 1000)
        # order 11 has no ml_order_item_costos row.
        scope = build_scope(db, SalesFilter(marcas=("epson",)))
        assert _ids(db, scope) == {10, 11}


class TestFacetConjunction:
    def test_pack_with_one_item_per_facet_does_not_match(self, db):
        """R38/T15a: pack holds a Lexmark printer and an Epson cartridge;
        filtering marca=Epson AND subcategoria=Impresoras (only the Lexmark
        item has that subcategoria) must NOT match -- no single item
        satisfies both."""
        _seed_order(db, 12, pack_id=777)
        _seed_order(db, 13, pack_id=777)
        _seed_producto(db, 1200, marca="Lexmark", categoria="Impresoras", subcategoria_id=1)
        _seed_producto(db, 1300, marca="Epson", categoria="Consumibles", subcategoria_id=2)
        _seed_costo(db, 12, "MLA12", 1200)
        _seed_costo(db, 13, "MLA13", 1300)
        scope = build_scope(db, SalesFilter(marcas=("epson",), subcategorias=(1,)))
        assert _ids(db, scope) == set()

    def test_pack_with_single_item_matching_both_facets_returns_whole_group(self, db):
        _seed_order(db, 14, pack_id=888)
        _seed_order(db, 15, pack_id=888)
        _seed_producto(db, 1400, marca="Epson", categoria="Impresoras", subcategoria_id=1)
        _seed_producto(db, 1500, marca="Lexmark", categoria="Consumibles", subcategoria_id=2)
        _seed_costo(db, 14, "MLA14", 1400)
        _seed_costo(db, 15, "MLA15", 1500)
        scope = build_scope(db, SalesFilter(marcas=("epson",), subcategorias=(1,)))
        assert _ids(db, scope) == {14, 15}

    def test_kpi_amounts_stay_the_groups_not_the_matched_items(self, db):
        """R38/T16d: the group's aggregate (here, its member count) is the
        whole pack's, not the single matching item's -- pinned so a caller
        never reads a facet-filtered KPI as brand-specific."""
        _seed_order(db, 16, pack_id=999)
        _seed_order(db, 17, pack_id=999)
        _seed_producto(db, 1600, marca="Epson", categoria="Impresoras", subcategoria_id=1)
        _seed_costo(db, 16, "MLA16", 1600)
        # Order 17 is the Lexmark half of the pack: it must be summed too.
        _seed_producto(db, 1700, marca="Lexmark", categoria="Consumibles", subcategoria_id=2)
        _seed_costo(db, 17, "MLA17", 1700)

        scope = build_scope(db, SalesFilter(marcas=("epson",)))

        assert _ids(db, scope) == {16, 17}
        # The AMOUNT, not just the ids: an aggregate over the filtered scope
        # is the WHOLE pack's (2 x 100), never the matching item's alone.
        total = sum(fila.total_amount for fila in scope.listing_query.with_entities(MlOrdersOps.total_amount).all())
        assert total == 200


class TestOutOfScopeFilters:
    def test_no_publication_status_or_official_store_param_changes_the_result(self, db):
        """R36a/R37: `SalesFilter` defines no publication-status/official-
        store field at all; this is a comparison proof that build_scope's
        behavior with the same base filters is identical regardless -- the
        parameters simply do not exist on the dataclass."""
        _seed_order(db, 18)
        _seed_producto(db, 1800, marca="Epson", categoria="Impresoras", subcategoria_id=1)
        _seed_costo(db, 18, "MLA18", 1800)
        # `SalesFilter` has no such field, so nothing can filter by it. The
        # real end-to-end proof (same rows with and without the query param)
        # lives in the router test; here we pin the dataclass surface.
        campos = {f.name for f in dataclasses.fields(SalesFilter)}
        assert "estado_mla" not in campos
        assert "estado_mla_actual" not in campos
        assert "tienda_oficial" not in campos
        assert _ids(db, build_scope(db, SalesFilter(marcas=("epson",)))) == {18}
