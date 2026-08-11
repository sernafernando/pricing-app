"""
Integration tests for sorting on GET /api/productos/tienda.

Background: `listar_productos_tienda` declared `orden_campos` /
`orden_direcciones` but never read them, so every sortable column header on the
Tienda page was a no-op (the arrow moved, the rows did not). These tests lock
the implemented behaviour:

- single-column sort, ascending and descending
- multi-column sort applied in the order the client sent it
- unknown sort keys are ignored (never a 4xx/5xx, never an arbitrary order)
- `web_tarjeta` (no DB column) orders identically to `precio_web_transferencia`
- sorting composes with pagination: ORDER BY runs before LIMIT/OFFSET
- malformed input (mismatched lengths, empty tokens, junk direction) never 500s
- equal sort values get a stable `item_id` tiebreaker, so paging does not
  duplicate or drop rows

Run:
    pytest tests/integration/test_productos_tienda_orden.py -v
"""

from __future__ import annotations

import pytest

from app.models.producto import ProductoERP, ProductoPricing


ENDPOINT = "/api/productos/tienda"


def _guard_incompatible_raw_sql(db):
    """Stub the Postgres-only `= ANY(:ids)` raw-SQL lookups that
    `listar_productos_tienda` runs whenever the result set is non-empty.

    Same helper (and same rationale) as `_guard_incompatible_raw_sql` in
    test_productos_ppp.py, plus `tb_brand`: the Tienda endpoint additionally
    resolves brand markups through
    `SELECT brand_desc, brand_id FROM tb_brand WHERE brand_desc = ANY(:marcas)`,
    which the SQLite test DB cannot execute either. These are unrelated legacy
    features; every other statement (ORM-generated or raw) passes through to
    the real connection, so the ORDER BY / LIMIT / OFFSET path actually under
    test still runs for real against SQLite.
    """
    original_execute = db.execute

    class _EmptyResult:
        def fetchall(self):
            return []

    def _wrapped(statement, *args, **kwargs):
        sql_text = str(statement)
        if "tienda_nube_productos" in sql_text or "v_ml_catalog_status_latest" in sql_text or "tb_brand" in sql_text:
            return _EmptyResult()
        return original_execute(statement, *args, **kwargs)

    db.execute = _wrapped


# ==========================================================================
# Data fixtures
# ==========================================================================
#
# Deliberately built so that natural (insertion / PK) order differs from the
# order produced by every column under test. Otherwise a broken "sort the
# already-paginated slice" implementation would still pass.
#
#  item_id | codigo | marca | stock | precio_web_transferencia
#  --------+--------+-------+-------+-------------------------
#     101  | P-06   |  B    |   5   |  100
#     102  | P-05   |  A    |   3   |  300
#     103  | P-04   |  B    |   5   |  200
#     104  | P-03   |  A    |   1   |  500
#     105  | P-02   |  C    |   3   |  400
#     106  | P-01   |  C    |   9   |  600

_ROWS = [
    # (item_id, codigo, marca, stock, precio_web_transferencia)
    (101, "P-06", "B", 5, 100.0),
    (102, "P-05", "A", 3, 300.0),
    (103, "P-04", "B", 5, 200.0),
    (104, "P-03", "A", 1, 500.0),
    (105, "P-02", "C", 3, 400.0),
    (106, "P-01", "C", 9, 600.0),
]

ALL_IDS = [r[0] for r in _ROWS]


@pytest.fixture()
def catalogo(db) -> list[ProductoERP]:
    """Six products with pricing rows, seeded in an order that is not the
    sorted order of any tested column."""
    productos = []
    for item_id, codigo, marca, stock, _pwt in _ROWS:
        p = ProductoERP(
            item_id=item_id,
            codigo=codigo,
            descripcion=f"Producto {codigo}",
            marca=marca,
            categoria="CAT",
            costo=float(item_id),
            moneda_costo="ARS",
            iva=21.0,
            envio=0.0,
            stock=stock,
            activo=True,
        )
        db.add(p)
        productos.append(p)
    db.flush()

    for item_id, _codigo, _marca, _stock, pwt in _ROWS:
        db.add(
            ProductoPricing(
                item_id=item_id,
                precio_lista_ml=None,
                markup_calculado=None,
                participa_web_transferencia=True,
                precio_web_transferencia=pwt,
            )
        )
    db.flush()
    return productos


def _ids(response) -> list[int]:
    return [p["item_id"] for p in response.json()["productos"]]


def _get(client, auth_headers, **params) -> object:
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return client.get(f"{ENDPOINT}?{query}", headers=auth_headers)


# ==========================================================================
# Single-column sort
# ==========================================================================


class TestSingleColumnSort:
    def test_codigo_ascending(self, client, auth_headers, db, catalogo):
        _guard_incompatible_raw_sql(db)

        response = _get(client, auth_headers, page=1, page_size=50, orden_campos="codigo", orden_direcciones="asc")

        assert response.status_code == 200, response.text
        # codigo runs inversely to item_id by construction
        assert _ids(response) == [106, 105, 104, 103, 102, 101]

    def test_codigo_descending(self, client, auth_headers, db, catalogo):
        _guard_incompatible_raw_sql(db)

        response = _get(client, auth_headers, page=1, page_size=50, orden_campos="codigo", orden_direcciones="desc")

        assert response.status_code == 200, response.text
        assert _ids(response) == [101, 102, 103, 104, 105, 106]

    def test_stock_descending_uses_item_id_tiebreaker(self, client, auth_headers, db, catalogo):
        """stock has ties (5,5 and 3,3) — the tiebreaker must make the order
        fully deterministic rather than leaving it up to the DB."""
        _guard_incompatible_raw_sql(db)

        response = _get(client, auth_headers, page=1, page_size=50, orden_campos="stock", orden_direcciones="desc")

        assert response.status_code == 200, response.text
        assert _ids(response) == [106, 101, 103, 102, 105, 104]

    def test_repeated_identical_request_is_stable(self, client, auth_headers, db, catalogo):
        _guard_incompatible_raw_sql(db)

        first = _get(client, auth_headers, page=1, page_size=50, orden_campos="stock", orden_direcciones="asc")
        second = _get(client, auth_headers, page=1, page_size=50, orden_campos="stock", orden_direcciones="asc")

        assert first.status_code == 200
        assert _ids(first) == _ids(second)


# ==========================================================================
# Multi-column sort
# ==========================================================================


class TestMultiColumnSort:
    def test_marca_then_codigo(self, client, auth_headers, db, catalogo):
        """Shift+click builds an ordered list; columns must be applied in the
        order received, not reversed and not arbitrarily."""
        _guard_incompatible_raw_sql(db)

        response = _get(
            client,
            auth_headers,
            page=1,
            page_size=50,
            orden_campos="marca,codigo",
            orden_direcciones="asc,asc",
        )

        assert response.status_code == 200, response.text
        # A: P-03(104) P-05(102) | B: P-04(103) P-06(101) | C: P-01(106) P-02(105)
        assert _ids(response) == [104, 102, 103, 101, 106, 105]

    def test_marca_asc_codigo_desc_uses_per_column_direction(self, client, auth_headers, db, catalogo):
        _guard_incompatible_raw_sql(db)

        response = _get(
            client,
            auth_headers,
            page=1,
            page_size=50,
            orden_campos="marca,codigo",
            orden_direcciones="asc,desc",
        )

        assert response.status_code == 200, response.text
        assert _ids(response) == [102, 104, 101, 103, 105, 106]

    def test_secondary_column_only_breaks_ties_of_the_primary(self, client, auth_headers, db, catalogo):
        """stock asc, then codigo asc: primary must dominate."""
        _guard_incompatible_raw_sql(db)

        response = _get(
            client,
            auth_headers,
            page=1,
            page_size=50,
            orden_campos="stock,codigo",
            orden_direcciones="asc,asc",
        )

        assert response.status_code == 200, response.text
        # stock 1 -> 104 | stock 3 -> P-02(105), P-05(102) | stock 5 -> P-04(103), P-06(101) | stock 9 -> 106
        assert _ids(response) == [104, 105, 102, 103, 101, 106]


# ==========================================================================
# Unknown / unmapped keys
# ==========================================================================


class TestUnknownSortKeys:
    def test_unknown_key_is_ignored_not_an_error(self, client, auth_headers, db, catalogo):
        _guard_incompatible_raw_sql(db)

        response = _get(
            client,
            auth_headers,
            page=1,
            page_size=50,
            orden_campos="columna_inexistente",
            orden_direcciones="asc",
        )

        assert response.status_code == 200, response.text
        assert response.json()["total"] == len(ALL_IDS)
        assert sorted(_ids(response)) == sorted(ALL_IDS)

    def test_unknown_key_does_not_shift_the_direction_list(self, client, auth_headers, db, catalogo):
        """The unknown key consumes its own direction slot; the known key must
        still receive ITS direction ('desc'), not the unknown key's."""
        _guard_incompatible_raw_sql(db)

        response = _get(
            client,
            auth_headers,
            page=1,
            page_size=50,
            orden_campos="columna_inexistente,codigo",
            orden_direcciones="asc,desc",
        )

        assert response.status_code == 200, response.text
        assert _ids(response) == [101, 102, 103, 104, 105, 106]

    @pytest.mark.parametrize("campo", ["precio_sugerido", "precio_gremio"])
    def test_computed_only_keys_are_skipped_without_erroring(self, client, auth_headers, db, catalogo, campo):
        """precio_sugerido / precio_gremio have no DB column (both are derived
        per-row in Python from MarkupTienda* overrides). They are skipped like
        any other unmapped key — documented as a known no-op, not a 500."""
        _guard_incompatible_raw_sql(db)

        response = _get(client, auth_headers, page=1, page_size=50, orden_campos=campo, orden_direcciones="asc")

        assert response.status_code == 200, response.text
        assert sorted(_ids(response)) == sorted(ALL_IDS)


# ==========================================================================
# web_tarjeta — monotonic alias of precio_web_transferencia
# ==========================================================================


class TestWebTarjetaOrdering:
    """`web_tarjeta` is rendered client-side as
    `precio_web_transferencia * (1 + porcentaje / 100)` with a single global
    porcentaje, so its ordering must be identical to
    `precio_web_transferencia`'s."""

    def test_web_tarjeta_asc_matches_precio_web_transferencia_asc(self, client, auth_headers, db, catalogo):
        _guard_incompatible_raw_sql(db)

        response = _get(
            client,
            auth_headers,
            page=1,
            page_size=50,
            orden_campos="web_tarjeta",
            orden_direcciones="asc",
        )

        assert response.status_code == 200, response.text
        valores = [p["precio_web_transferencia"] for p in response.json()["productos"]]
        assert valores == sorted(valores)
        assert _ids(response) == [101, 103, 102, 105, 104, 106]

    def test_web_tarjeta_desc_matches_precio_web_transferencia_desc(self, client, auth_headers, db, catalogo):
        _guard_incompatible_raw_sql(db)

        response = _get(
            client,
            auth_headers,
            page=1,
            page_size=50,
            orden_campos="web_tarjeta",
            orden_direcciones="desc",
        )

        assert response.status_code == 200, response.text
        valores = [p["precio_web_transferencia"] for p in response.json()["productos"]]
        assert valores == sorted(valores, reverse=True)
        assert _ids(response) == [106, 104, 105, 102, 103, 101]

    @pytest.mark.parametrize("porcentaje", [0.5, 6.0, 42.0])
    def test_ordering_is_invariant_to_the_global_percentage(self, client, auth_headers, db, catalogo, porcentaje):
        """Multiplying by (1 + p/100) with p > 0 is strictly monotonic, so the
        rendered Web Tarjeta order equals the precio_web_transferencia order
        for ANY configured percentage. This is the property that makes the
        column mapping mathematically exact rather than an approximation."""
        _guard_incompatible_raw_sql(db)

        response = _get(
            client,
            auth_headers,
            page=1,
            page_size=50,
            orden_campos="web_tarjeta",
            orden_direcciones="asc",
        )

        assert response.status_code == 200, response.text
        rendered = [p["precio_web_transferencia"] * (1 + porcentaje / 100) for p in response.json()["productos"]]
        assert rendered == sorted(rendered)


# ==========================================================================
# Composition with pagination
# ==========================================================================


class TestSortComposesWithPagination:
    def test_paged_sort_equals_full_sort(self, client, auth_headers, db, catalogo):
        """ORDER BY must be applied before LIMIT/OFFSET. If it were applied to
        the already-paginated slice, page 2 would hold the wrong rows even
        though each page looked internally sorted."""
        _guard_incompatible_raw_sql(db)

        full = _get(client, auth_headers, page=1, page_size=50, orden_campos="stock", orden_direcciones="desc")
        assert full.status_code == 200, full.text
        esperado = _ids(full)
        assert esperado == [106, 101, 103, 102, 105, 104]

        paginado: list[int] = []
        for page in (1, 2, 3):
            response = _get(
                client,
                auth_headers,
                page=page,
                page_size=2,
                orden_campos="stock",
                orden_direcciones="desc",
            )
            assert response.status_code == 200, response.text
            assert response.json()["total"] == len(ALL_IDS)
            assert len(response.json()["productos"]) == 2
            paginado.extend(_ids(response))

        assert paginado == esperado

    def test_second_page_is_not_a_sorted_slice_of_unsorted_data(self, client, auth_headers, db, catalogo):
        """Regression guard for the specific silent-wrong-data failure mode.

        With stock DESC, page 2 must hold the 3rd/4th GLOBALLY sorted rows
        ([103, 102]). An implementation that sorted the already-paginated
        slice would return the natural rows 3-4 ([103, 104]) — internally
        sorted, silently wrong. The two results differ, so this test can tell
        them apart."""
        _guard_incompatible_raw_sql(db)

        response = _get(
            client,
            auth_headers,
            page=2,
            page_size=2,
            orden_campos="stock",
            orden_direcciones="desc",
        )

        assert response.status_code == 200, response.text
        assert _ids(response) == [103, 102]

    def test_pages_never_duplicate_or_drop_rows_on_tied_values(self, client, auth_headers, db, catalogo):
        """stock has ties across a page boundary; without the item_id
        tiebreaker the same row can appear on two pages (and another vanish)."""
        _guard_incompatible_raw_sql(db)

        vistos: list[int] = []
        for page in (1, 2, 3):
            response = _get(
                client,
                auth_headers,
                page=page,
                page_size=2,
                orden_campos="stock",
                orden_direcciones="asc",
            )
            assert response.status_code == 200, response.text
            vistos.extend(_ids(response))

        assert len(vistos) == len(set(vistos)), f"row seen on more than one page: {vistos}"
        assert sorted(vistos) == sorted(ALL_IDS)

    def test_total_is_unchanged_by_sorting(self, client, auth_headers, db, catalogo):
        _guard_incompatible_raw_sql(db)

        sin_orden = _get(client, auth_headers, page=1, page_size=50)
        con_orden = _get(client, auth_headers, page=1, page_size=50, orden_campos="codigo", orden_direcciones="asc")

        assert sin_orden.status_code == 200, sin_orden.text
        assert con_orden.status_code == 200, con_orden.text
        assert sin_orden.json()["total"] == con_orden.json()["total"] == len(ALL_IDS)


# ==========================================================================
# Malformed input
# ==========================================================================


class TestMalformedOrderingInput:
    def test_more_campos_than_direcciones_applies_only_complete_pairs(self, client, auth_headers, db, catalogo):
        _guard_incompatible_raw_sql(db)

        response = _get(
            client,
            auth_headers,
            page=1,
            page_size=50,
            orden_campos="codigo,marca",
            orden_direcciones="asc",
        )

        assert response.status_code == 200, response.text
        assert _ids(response) == [106, 105, 104, 103, 102, 101]

    def test_more_direcciones_than_campos_does_not_error(self, client, auth_headers, db, catalogo):
        _guard_incompatible_raw_sql(db)

        response = _get(
            client,
            auth_headers,
            page=1,
            page_size=50,
            orden_campos="codigo",
            orden_direcciones="asc,desc,asc",
        )

        assert response.status_code == 200, response.text
        assert _ids(response) == [106, 105, 104, 103, 102, 101]

    def test_empty_tokens_are_skipped(self, client, auth_headers, db, catalogo):
        _guard_incompatible_raw_sql(db)

        response = _get(
            client,
            auth_headers,
            page=1,
            page_size=50,
            orden_campos=",,codigo",
            orden_direcciones="asc,asc,asc",
        )

        assert response.status_code == 200, response.text
        assert _ids(response) == [106, 105, 104, 103, 102, 101]

    def test_unknown_direction_falls_back_to_ascending(self, client, auth_headers, db, catalogo):
        _guard_incompatible_raw_sql(db)

        response = _get(
            client,
            auth_headers,
            page=1,
            page_size=50,
            orden_campos="codigo",
            orden_direcciones="ASCENDENTE",
        )

        assert response.status_code == 200, response.text
        assert _ids(response) == [106, 105, 104, 103, 102, 101]

    def test_direction_is_case_insensitive(self, client, auth_headers, db, catalogo):
        _guard_incompatible_raw_sql(db)

        response = _get(client, auth_headers, page=1, page_size=50, orden_campos="codigo", orden_direcciones="DESC")

        assert response.status_code == 200, response.text
        assert _ids(response) == [101, 102, 103, 104, 105, 106]

    def test_campos_without_direcciones_is_a_no_op(self, client, auth_headers, db, catalogo):
        """Both params are required together (same contract as GET /productos)."""
        _guard_incompatible_raw_sql(db)

        response = _get(client, auth_headers, page=1, page_size=50, orden_campos="codigo")

        assert response.status_code == 200, response.text
        assert sorted(_ids(response)) == sorted(ALL_IDS)
