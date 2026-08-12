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

import re

import pytest
from sqlalchemy import bindparam, text
from sqlalchemy.sql.elements import TextClause

from app.models.markup_tienda import MarkupTiendaBrand, MarkupTiendaProducto
from app.models.precio_gremio_override import PrecioGremioOverride
from app.models.producto import ProductoERP, ProductoPricing
from app.models.tb_brand import TBBrand


ENDPOINT = "/api/productos/tienda"


def _guard_incompatible_raw_sql(db):
    """Make the Postgres-only `= ANY(:ids)` raw-SQL lookups that
    `listar_productos_tienda` runs survive the SQLite test DB.

    Same rationale as `_guard_incompatible_raw_sql` in test_productos_ppp.py,
    with two deliberate differences:

    1. Only `text()` statements are intercepted. The ORDER BY for
       `precio_sugerido` / `precio_gremio` joins `tb_brand` inside the MAIN
       ORM query, so a substring match on the compiled SQL would swallow the
       very query under test. `TextClause` is the exact discriminator: the
       three legacy lookups are the only raw ones in this endpoint.
    2. The `tb_brand` lookup is EMULATED rather than stubbed empty, by
       rewriting `= ANY(:marcas)` into an expanding `IN :marcas`. Stubbing it
       out would leave the Python display path with no brand markups at all,
       which is precisely the fallback branch these tests must exercise —
       the SQL order and the displayed value could then never be compared.

    `tienda_nube_productos` (unrelated to ordering) and
    `v_ml_catalog_status_latest` (a Postgres VIEW with no SQLite counterpart)
    stay stubbed empty.
    """
    original_execute = db.execute

    class _EmptyResult:
        def fetchall(self):
            return []

    def _wrapped(statement, *args, **kwargs):
        if not isinstance(statement, TextClause):
            return original_execute(statement, *args, **kwargs)

        sql_text = str(statement)
        if "tienda_nube_productos" in sql_text or "v_ml_catalog_status_latest" in sql_text:
            return _EmptyResult()
        if "= ANY(" not in sql_text:
            return original_execute(statement, *args, **kwargs)

        params = args[0] if args else (kwargs.get("params") or kwargs.get("parameters") or {})
        rewritten = text(re.sub(r"=\s*ANY\(:(\w+)\)", r"IN :\1", sql_text))
        for name, value in params.items():
            if isinstance(value, (list, tuple, set)):
                rewritten = rewritten.bindparams(bindparam(name, expanding=True))
        return original_execute(rewritten, params)

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
    def test_derived_keys_do_not_error_without_any_markup_configured(self, client, auth_headers, db, catalogo, campo):
        """precio_sugerido / precio_gremio have no DB column, but they are now
        sorted in SQL. With no MarkupTienda* row anywhere every value is NULL,
        which must degrade to "everything last, stable by item_id" — not a
        500 and not a dropped row."""
        _guard_incompatible_raw_sql(db)

        response = _get(client, auth_headers, page=1, page_size=50, orden_campos=campo, orden_direcciones="asc")

        assert response.status_code == 200, response.text
        assert response.json()["total"] == len(ALL_IDS)
        assert _ids(response) == sorted(ALL_IDS)


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


# ==========================================================================
# precio_sugerido / precio_gremio — derived values sorted in SQL
# ==========================================================================
#
# Neither column exists in the DB: both are derived per row from
# MarkupTiendaProducto / MarkupTiendaBrand (or the manual override in
# precio_gremio_override) over a currency-converted cost. They are now sorted
# in SQL, so these tests have to prove two independent things:
#
#   1. the SQL ORDER BY reproduces the value the endpoint actually DISPLAYS
#      (`precio_gremio_sin_iva` / `precio_sugerido_sin_iva`, the primary value
#      of each cell in frontend/src/pages/Tienda.jsx), and
#   2. the LEFT JOINs the ORDER BY needs do not add or drop a single row.
#
# (2) is the dangerous one — a join fan-out would silently corrupt totals and
# pagination — so it gets its own class, plus a fixture that deliberately
# seeds the collisions (same brand_desc on two brand_ids, several markup rows
# per brand) that could produce one.

_TIPO_CAMBIO_USD = 1000.0

_MARCA_CON_MARKUP = "ACME"  # in tb_brand, has a brand-level markup
_MARCA_SIN_MARKUP = "ZETA"  # in tb_brand, no markup row at all
_MARCA_DESCONOCIDA = "NADA"  # not in tb_brand at all

# item_id | marca | moneda | costo | markup_calculado | product markup | override
# --------+-------+--------+-------+------------------+----------------+---------
#   201   | ACME  | ARS    |  100  |        10        |       --       |   --
#   202   | ACME  | ARS    |  100  |        10        | 50 / sug 30    |   --
#   203   | ZETA  | USD    |    1  |        10        |       --       |   --
#   204   | NADA  | ARS    |  100  |       None       |       --       |   --
#   205   | ACME  | ARS    |  100  |        10        |       --       | 999999
#   206   | ACME  | ARS    |    0  |        10        |       --       |   --
#   207   | ACME  | ARS    |  100  |        10        | 70 / sug None  |   --
#   208   | ACME  | ARS    |  101  |        36        |       --       |   --
#
# 208 exists purely to make the BRAND-level markup_sugerido observable in the
# order: with the brand's +5 it lands just above 202, without it just below.
# Every other row shifts by the same factor when the fallback breaks, so the
# relative order would not move and the bug would pass unnoticed.
_ROWS_DERIVADO = [
    # (item_id, marca, moneda_costo, costo, markup_calculado)
    (201, _MARCA_CON_MARKUP, "ARS", 100.0, 10.0),
    (202, _MARCA_CON_MARKUP, "ARS", 100.0, 10.0),
    (203, _MARCA_SIN_MARKUP, "USD", 1.0, 10.0),
    (204, _MARCA_DESCONOCIDA, "ARS", 100.0, None),
    (205, _MARCA_CON_MARKUP, "ARS", 100.0, 10.0),
    (206, _MARCA_CON_MARKUP, "ARS", 0.0, 10.0),
    (207, _MARCA_CON_MARKUP, "ARS", 100.0, 10.0),
    (208, _MARCA_CON_MARKUP, "ARS", 101.0, 36.0),
]

IDS_DERIVADO = [r[0] for r in _ROWS_DERIVADO]

_OVERRIDE_GREMIO_SIN_IVA = 999999.0


@pytest.fixture()
def tipo_cambio_usd(db):
    """Today's USD rate, so `convertir_a_pesos` actually converts."""
    from datetime import date

    from app.models.tipo_cambio import TipoCambio

    db.add(TipoCambio(fecha=date.today(), moneda="USD", compra=_TIPO_CAMBIO_USD - 50, venta=_TIPO_CAMBIO_USD))
    db.flush()


@pytest.fixture()
def catalogo_derivado(db):
    """Catalog exercising every branch of the two derived formulas:
    brand markup, product markup overriding it, product markup with a NULL
    markup_sugerido (brand still wins the sugerido), a manual gremio
    override, a brand with no markup, a brand missing from tb_brand, a NULL
    markup_calculado and a zero cost."""
    for item_id, marca, moneda, costo, markup_calculado in _ROWS_DERIVADO:
        db.add(
            ProductoERP(
                item_id=item_id,
                codigo=f"D-{item_id}",
                descripcion=f"Derivado {item_id}",
                marca=marca,
                categoria="CAT",
                costo=costo,
                moneda_costo=moneda,
                iva=21.0,
                envio=0.0,
                stock=1,
                activo=True,
            )
        )
    db.flush()
    for item_id, _marca, _moneda, _costo, markup_calculado in _ROWS_DERIVADO:
        db.add(ProductoPricing(item_id=item_id, markup_calculado=markup_calculado))
    db.flush()

    db.add_all(
        [
            TBBrand(comp_id=1, brand_id=10, bra_id=10, brand_desc=_MARCA_CON_MARKUP),
            TBBrand(comp_id=1, brand_id=20, bra_id=20, brand_desc=_MARCA_SIN_MARKUP),
        ]
    )
    db.add(
        MarkupTiendaBrand(
            comp_id=1,
            brand_id=10,
            brand_desc=_MARCA_CON_MARKUP,
            markup_porcentaje=20.0,
            markup_sugerido=5.0,
            activo=True,
        )
    )
    db.add_all(
        [
            MarkupTiendaProducto(item_id=202, markup_porcentaje=50.0, markup_sugerido=30.0, activo=True),
            MarkupTiendaProducto(item_id=207, markup_porcentaje=70.0, markup_sugerido=None, activo=True),
        ]
    )
    db.add(
        PrecioGremioOverride(
            item_id=205,
            precio_gremio_sin_iva_manual=_OVERRIDE_GREMIO_SIN_IVA,
            precio_gremio_con_iva_manual=_OVERRIDE_GREMIO_SIN_IVA * 1.21,
        )
    )
    db.flush()


def _valores(response, campo: str) -> list:
    return [p[campo] for p in response.json()["productos"]]


def _orden_esperado_desde_python(response, campo: str, *, descendente: bool) -> list[int]:
    """Recompute the expected id order from the values the endpoint DISPLAYS.

    Takes an UNSORTED response — i.e. the values produced by the endpoint's
    own Python path (`computar_precio_sugerido` / the gremio formula around
    productos_listing.py) — and applies the ordering contract in Python:
    NULLs last in both directions, `item_id` ascending as the tiebreaker.
    """
    filas = [(p["item_id"], p[campo]) for p in response.json()["productos"]]
    con_valor = [f for f in filas if f[1] is not None]
    sin_valor = sorted(f[0] for f in filas if f[1] is None)
    con_valor.sort(key=lambda f: (-f[1] if descendente else f[1], f[0]))
    return [f[0] for f in con_valor] + sin_valor


class TestDerivedPriceOrdering:
    def test_precio_gremio_ascending(self, client, auth_headers, db, catalogo_derivado, tipo_cambio_usd):
        _guard_incompatible_raw_sql(db)

        response = _get(
            client, auth_headers, page=1, page_size=50, orden_campos="precio_gremio", orden_direcciones="asc"
        )

        assert response.status_code == 200, response.text
        # 201: 100*1.065*1.20 = 127.80  (brand markup 20)
        # 202: 100*1.065*1.50 = 159.75  (product markup 50 overrides brand 20)
        # 207: 100*1.065*1.70 = 181.05  (product markup 70)
        # 205: manual override, wins outright
        # 203/204/206: no markup / no cost -> NULL, last, by item_id
        assert _ids(response) == [201, 208, 202, 207, 205, 203, 204, 206]
        assert _valores(response, "precio_gremio_sin_iva")[:5] == pytest.approx(
            [127.80, 129.078, 159.75, 181.05, 999999.0]
        )

    def test_precio_gremio_descending(self, client, auth_headers, db, catalogo_derivado, tipo_cambio_usd):
        _guard_incompatible_raw_sql(db)

        response = _get(
            client, auth_headers, page=1, page_size=50, orden_campos="precio_gremio", orden_direcciones="desc"
        )

        assert response.status_code == 200, response.text
        assert _ids(response) == [205, 207, 202, 208, 201, 203, 204, 206]

    def test_precio_sugerido_ascending_with_ties(self, client, auth_headers, db, catalogo_derivado, tipo_cambio_usd):
        """201, 205 and 207 all land on markup_clasica 10 + brand sugerido 5:
        201 and 205 have no product row, 207 has one whose markup_sugerido is
        NULL, so the brand value still applies (that NULL must NOT block the
        fallback). The three-way tie is broken by item_id."""
        _guard_incompatible_raw_sql(db)

        response = _get(
            client, auth_headers, page=1, page_size=50, orden_campos="precio_sugerido", orden_direcciones="asc"
        )

        assert response.status_code == 200, response.text
        # 201/205/207: 100*1.065*1.15 = 122.475
        # 202: 100*1.065*1.40 = 149.10   (product sugerido 30 overrides brand 5)
        # 203: 1 USD -> 1000 ARS, *1.065*1.10 = 1171.50
        # 204 (markup_calculado NULL) / 206 (costo 0): NULL, last
        assert _ids(response) == [201, 205, 207, 202, 208, 203, 204, 206]
        assert _valores(response, "precio_sugerido_sin_iva")[:6] == pytest.approx(
            [122.475, 122.475, 122.475, 149.10, 151.66665, 1171.50]
        )

    def test_precio_sugerido_descending(self, client, auth_headers, db, catalogo_derivado, tipo_cambio_usd):
        """Ties keep the ASCENDING item_id tiebreaker even when the primary
        direction is desc — that is what makes paging stable."""
        _guard_incompatible_raw_sql(db)

        response = _get(
            client, auth_headers, page=1, page_size=50, orden_campos="precio_sugerido", orden_direcciones="desc"
        )

        assert response.status_code == 200, response.text
        assert _ids(response) == [203, 208, 202, 201, 205, 207, 204, 206]

    @pytest.mark.parametrize("campo", ["precio_sugerido", "precio_gremio"])
    @pytest.mark.parametrize("direccion", ["asc", "desc"])
    def test_sql_order_equals_the_python_computed_display_order(
        self, client, auth_headers, db, catalogo_derivado, tipo_cambio_usd, campo, direccion
    ):
        """The whole point of the change: the SQL expression must rank rows
        exactly like the Python formula that fills the response. Expected
        order is derived from the endpoint's own unsorted output, so this
        stays honest even if the formula changes."""
        _guard_incompatible_raw_sql(db)

        sin_orden = _get(client, auth_headers, page=1, page_size=50)
        assert sin_orden.status_code == 200, sin_orden.text

        con_orden = _get(client, auth_headers, page=1, page_size=50, orden_campos=campo, orden_direcciones=direccion)
        assert con_orden.status_code == 200, con_orden.text

        esperado = _orden_esperado_desde_python(sin_orden, f"{campo}_sin_iva", descendente=(direccion == "desc"))
        assert _ids(con_orden) == esperado

    def test_both_derived_keys_at_once_adds_the_joins_only_once(
        self, client, auth_headers, db, catalogo_derivado, tipo_cambio_usd
    ):
        """precio_sugerido then precio_gremio: the second key must reuse the
        joins added by the first (a duplicate join would fan rows out) and
        still break the sugerido ties by gremio."""
        _guard_incompatible_raw_sql(db)

        response = _get(
            client,
            auth_headers,
            page=1,
            page_size=50,
            orden_campos="precio_sugerido,precio_gremio",
            orden_direcciones="asc,asc",
        )

        assert response.status_code == 200, response.text
        # sugerido tie {201, 205, 207} resolved by gremio: 127.80 < 181.05 < 999999
        assert _ids(response) == [201, 207, 205, 202, 208, 203, 204, 206]
        assert response.json()["total"] == len(IDS_DERIVADO)


class TestDerivedPriceCurrencyConversion:
    def test_usd_cost_is_converted_before_comparing(self, client, auth_headers, db, catalogo_derivado, tipo_cambio_usd):
        """203 costs 1 USD. Compared raw it is the cheapest row by far;
        converted at 1000 ARS/USD it is the most expensive. Asserting it sorts
        LAST proves the CASE conversion is really in the ORDER BY."""
        _guard_incompatible_raw_sql(db)

        response = _get(
            client, auth_headers, page=1, page_size=50, orden_campos="precio_sugerido", orden_direcciones="asc"
        )

        assert response.status_code == 200, response.text
        con_valor = [p["item_id"] for p in response.json()["productos"] if p["precio_sugerido_sin_iva"] is not None]
        assert con_valor[-1] == 203

    def test_without_an_exchange_rate_the_raw_cost_is_used(self, client, auth_headers, db, catalogo_derivado):
        """No `tipo_cambio_usd` fixture => `obtener_tipo_cambio_actual` returns
        None and `convertir_a_pesos` returns the cost untouched. The SQL side
        must drop the CASE entirely, so 203 flips to first."""
        _guard_incompatible_raw_sql(db)

        response = _get(
            client, auth_headers, page=1, page_size=50, orden_campos="precio_sugerido", orden_direcciones="asc"
        )

        assert response.status_code == 200, response.text
        assert _ids(response)[0] == 203
        assert _valores(response, "precio_sugerido_sin_iva")[0] == pytest.approx(1.0 * 1.065 * 1.10)


class TestDerivedPriceNullHandling:
    @pytest.mark.parametrize("campo", ["precio_sugerido", "precio_gremio"])
    @pytest.mark.parametrize("direccion", ["asc", "desc"])
    def test_rows_without_a_value_always_sort_last(
        self, client, auth_headers, db, catalogo_derivado, tipo_cambio_usd, campo, direccion
    ):
        """`nullslast()` in BOTH directions, same as every other sort key
        here. A product with no markup / no cost must never displace a priced
        one, and must never disappear."""
        _guard_incompatible_raw_sql(db)

        response = _get(client, auth_headers, page=1, page_size=50, orden_campos=campo, orden_direcciones=direccion)

        assert response.status_code == 200, response.text
        valores = _valores(response, f"{campo}_sin_iva")
        primer_null = next((i for i, v in enumerate(valores) if v is None), len(valores))
        assert all(v is None for v in valores[primer_null:]), valores
        assert sorted(_ids(response)) == sorted(IDS_DERIVADO)

    def test_zero_cost_and_missing_markup_yield_null_not_zero(
        self, client, auth_headers, db, catalogo_derivado, tipo_cambio_usd
    ):
        _guard_incompatible_raw_sql(db)

        response = _get(
            client, auth_headers, page=1, page_size=50, orden_campos="precio_gremio", orden_direcciones="asc"
        )

        assert response.status_code == 200, response.text
        por_id = {p["item_id"]: p for p in response.json()["productos"]}
        assert por_id[206]["precio_gremio_sin_iva"] is None  # costo 0
        assert por_id[203]["precio_gremio_sin_iva"] is None  # brand without markup
        assert por_id[204]["precio_gremio_sin_iva"] is None  # brand missing from tb_brand
        assert por_id[204]["precio_sugerido_sin_iva"] is None  # markup_calculado NULL


# ==========================================================================
# The one that matters: the sort JOINs must not change the result set
# ==========================================================================


@pytest.fixture()
def marcas_duplicadas(db):
    """Seed exactly the collisions that could make the sort joins fan out:

    - the same `brand_desc` on two different `brand_id`s (tb_brand's PK is
      (comp_id, brand_id), so brand_desc is NOT unique), and
    - several active markup rows sharing a `brand_id` across comp_ids
      (`markups_tienda_brand` is unique on (comp_id, brand_id), not on
      brand_id alone).

    A naive `LEFT JOIN markups_tienda_brand ON brand_desc = marca` would
    multiply every ACME product by four here.
    """
    db.add_all(
        [
            TBBrand(comp_id=2, brand_id=11, bra_id=11, brand_desc=_MARCA_CON_MARKUP),
            TBBrand(comp_id=3, brand_id=12, bra_id=12, brand_desc=_MARCA_CON_MARKUP),
        ]
    )
    db.add_all(
        [
            MarkupTiendaBrand(
                comp_id=2, brand_id=12, brand_desc=_MARCA_CON_MARKUP, markup_porcentaje=33.0, activo=True
            ),
            MarkupTiendaBrand(
                comp_id=3, brand_id=12, brand_desc=_MARCA_CON_MARKUP, markup_porcentaje=44.0, activo=True
            ),
            MarkupTiendaBrand(
                comp_id=4,
                brand_id=12,
                brand_desc=_MARCA_CON_MARKUP,
                markup_sugerido=7.0,
                markup_porcentaje=55.0,
                activo=True,
            ),
        ]
    )
    db.flush()


class TestDerivedSortJoinsDoNotChangeTheResultSet:
    """The single biggest risk of sorting these two keys in SQL: the LEFT
    JOINs needed by the ORDER BY silently duplicating or dropping rows."""

    @pytest.mark.parametrize("campo", ["precio_sugerido", "precio_gremio"])
    @pytest.mark.parametrize("direccion", ["asc", "desc"])
    def test_ids_and_total_are_identical_to_the_unsorted_request(
        self, client, auth_headers, db, catalogo_derivado, tipo_cambio_usd, campo, direccion
    ):
        _guard_incompatible_raw_sql(db)

        sin_orden = _get(client, auth_headers, page=1, page_size=50)
        con_orden = _get(client, auth_headers, page=1, page_size=50, orden_campos=campo, orden_direcciones=direccion)

        assert sin_orden.status_code == 200, sin_orden.text
        assert con_orden.status_code == 200, con_orden.text
        assert sorted(_ids(con_orden)) == sorted(_ids(sin_orden)) == sorted(IDS_DERIVADO)
        assert con_orden.json()["total"] == sin_orden.json()["total"] == len(IDS_DERIVADO)

    @pytest.mark.parametrize("campo", ["precio_sugerido", "precio_gremio"])
    def test_no_row_is_returned_twice(self, client, auth_headers, db, catalogo_derivado, tipo_cambio_usd, campo):
        _guard_incompatible_raw_sql(db)

        response = _get(client, auth_headers, page=1, page_size=50, orden_campos=campo, orden_direcciones="asc")

        assert response.status_code == 200, response.text
        ids = _ids(response)
        assert len(ids) == len(set(ids)) == len(IDS_DERIVADO)

    @pytest.mark.parametrize("campo", ["precio_sugerido", "precio_gremio"])
    def test_colliding_brand_rows_do_not_fan_out(
        self, client, auth_headers, db, catalogo_derivado, marcas_duplicadas, tipo_cambio_usd, campo
    ):
        """Same assertion as above but with duplicate brand_descs and several
        markup rows per brand_id — the shape that a plain join would multiply.
        Result set must be byte-for-byte the same size."""
        _guard_incompatible_raw_sql(db)

        sin_orden = _get(client, auth_headers, page=1, page_size=50)
        con_orden = _get(client, auth_headers, page=1, page_size=50, orden_campos=campo, orden_direcciones="asc")

        assert sin_orden.status_code == 200, sin_orden.text
        assert con_orden.status_code == 200, con_orden.text
        ids = _ids(con_orden)
        assert len(ids) == len(set(ids))
        assert sorted(ids) == sorted(_ids(sin_orden)) == sorted(IDS_DERIVADO)
        assert con_orden.json()["total"] == sin_orden.json()["total"] == len(IDS_DERIVADO)

    def test_colliding_brand_rows_still_match_the_displayed_value(
        self, client, auth_headers, db, catalogo_derivado, marcas_duplicadas, tipo_cambio_usd
    ):
        """With collisions present, the SQL tie-break (greatest id) and the
        Python one (last row of an id-ordered query) must still agree,
        otherwise the arrow would order by a value nobody can see."""
        _guard_incompatible_raw_sql(db)

        sin_orden = _get(client, auth_headers, page=1, page_size=50)
        con_orden = _get(
            client, auth_headers, page=1, page_size=50, orden_campos="precio_gremio", orden_direcciones="asc"
        )

        assert sin_orden.status_code == 200, sin_orden.text
        assert con_orden.status_code == 200, con_orden.text
        assert _ids(con_orden) == _orden_esperado_desde_python(sin_orden, "precio_gremio_sin_iva", descendente=False)

    @pytest.mark.parametrize("campo", ["precio_sugerido", "precio_gremio"])
    def test_pagination_visits_every_row_exactly_once(
        self, client, auth_headers, db, catalogo_derivado, tipo_cambio_usd, campo
    ):
        """A fan-out shows up as a row appearing on two pages (and another
        vanishing off the end), which a single-page assertion can miss."""
        _guard_incompatible_raw_sql(db)

        vistos: list[int] = []
        for page in (1, 2, 3, 4):
            response = _get(client, auth_headers, page=page, page_size=2, orden_campos=campo, orden_direcciones="asc")
            assert response.status_code == 200, response.text
            assert response.json()["total"] == len(IDS_DERIVADO)
            vistos.extend(_ids(response))

        assert len(vistos) == len(set(vistos)), f"row seen on more than one page: {vistos}"
        assert sorted(vistos) == sorted(IDS_DERIVADO)

    @pytest.mark.parametrize("campo", ["precio_sugerido", "precio_gremio"])
    def test_paged_sort_equals_full_sort(self, client, auth_headers, db, catalogo_derivado, tipo_cambio_usd, campo):
        """ORDER BY still runs before count()/offset()/limit() with the extra
        joins in place."""
        _guard_incompatible_raw_sql(db)

        full = _get(client, auth_headers, page=1, page_size=50, orden_campos=campo, orden_direcciones="desc")
        assert full.status_code == 200, full.text

        paginado: list[int] = []
        for page in (1, 2, 3, 4):
            response = _get(client, auth_headers, page=page, page_size=2, orden_campos=campo, orden_direcciones="desc")
            assert response.status_code == 200, response.text
            paginado.extend(_ids(response))

        assert paginado == _ids(full)

    @pytest.mark.parametrize("campo", ["codigo", "stock", "web_tarjeta", "precio_clasica"])
    def test_existing_sort_keys_are_untouched_by_the_new_joins(self, client, auth_headers, db, catalogo, campo):
        """Regression guard: the derived-price joins are built lazily, so a
        request that does not ask for them must not pay for them nor change."""
        _guard_incompatible_raw_sql(db)

        response = _get(client, auth_headers, page=1, page_size=50, orden_campos=campo, orden_direcciones="asc")

        assert response.status_code == 200, response.text
        assert response.json()["total"] == len(ALL_IDS)
        assert sorted(_ids(response)) == sorted(ALL_IDS)
