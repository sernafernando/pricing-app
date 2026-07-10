"""
Failing-first unit tests for the shared TP-Link per-order aggregation core
(`app.scripts._tplink_metricas_core`), slice 1 of tplink-metricas-dual-key-dedup.

SQLite-runnable: uses synthetic SimpleNamespace rows to mimic the shape of
rows returned by the (Postgres-only) aggregating CTE. Does NOT exercise raw
SQL — that is covered by the Postgres integration tests in a later slice.

Covers (design v2 / D1):
  - Multi-item order -> one folded row with SUMMED monto_total, cantidad,
    costo, comision, ganancia, and shipping applied EXACTLY ONCE per order.
  - Pack-offset (count_per_pack) counts DISTINCT ORDERS, not detail rows.
  - Single-item order stays identical to the non-folded per-detail result
    (parity with the pre-existing incremental behavior).
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest


def _detail_row(
    *,
    mlo_id: int,
    ml_id: str,
    mlp_id: int,
    pack_id: str | None,
    monto_unitario: float,
    cantidad: float,
    costo_sin_iva: float,
    seller_shipping_cost: float | None,
    shipment_total: float | None,
    iva: float = 21.0,
    comision_base_porcentaje: float = 12.0,
    tipo_logistica: str | None = "self_service",
    codigo: str = "SKU-1",
    descripcion: str = "PRODUCTO 1",
    marca: str = "TP-LINK",
    categoria: str = "REDES",
    subcategoria: str = "ROUTERS",
    subcat_id: int | None = None,
    pricelist_id: int | None = None,
    envio_producto: float | None = None,
    item_id: int = 1,
    mlod_id: int | None = None,
) -> SimpleNamespace:
    """Build a synthetic per-detail row matching the aggregating CTE's projection."""
    return SimpleNamespace(
        id_operacion=mlo_id,
        ml_id=ml_id,
        mlp_id=mlp_id,
        pack_id=pack_id,
        item_id=item_id,
        codigo=codigo,
        descripcion=descripcion,
        marca=marca,
        categoria=categoria,
        subcategoria=subcategoria,
        cantidad=cantidad,
        monto_unitario=monto_unitario,
        monto_total=monto_unitario * cantidad,
        costo_sin_iva=costo_sin_iva,
        iva=iva,
        comision_base_porcentaje=comision_base_porcentaje,
        subcat_id=subcat_id,
        pricelist_id=pricelist_id,
        tipo_logistica=tipo_logistica,
        seller_shipping_cost=seller_shipping_cost,
        shipment_total=shipment_total,
        envio_producto=envio_producto,
        fecha_venta=datetime(2026, 7, 1, 10, 0, 0),
        mlod_id=mlod_id,
    )


def _get_core_module():
    import app.scripts._tplink_metricas_core as core

    return core


class TestFoldMultiItemOrder:
    """A multi-detail order must fold into ONE row with summed metrics."""

    def test_multi_item_order_folds_to_one_row(self) -> None:
        core = _get_core_module()

        rows = [
            _detail_row(
                mlo_id=100,
                ml_id="ML100",
                mlp_id=111,
                pack_id="PACK-A",
                monto_unitario=1000.0,
                cantidad=1,
                costo_sin_iva=400.0,
                seller_shipping_cost=200.0,
                shipment_total=2000.0,
                codigo="SKU-A",
                item_id=1,
            ),
            _detail_row(
                mlo_id=100,
                ml_id="ML100",
                mlp_id=222,
                pack_id="PACK-A",
                monto_unitario=1000.0,
                cantidad=1,
                costo_sin_iva=300.0,
                seller_shipping_cost=200.0,
                shipment_total=2000.0,
                codigo="SKU-B",
                item_id=2,
            ),
        ]

        folded = core.fold_order_rows(rows)

        assert len(folded) == 1
        order = folded[100]

        # Keys per design v2: id_operacion=mlo_id, ml_order_id=str(ml_id), mla_id=first detail's str(mlp_id)
        assert order["id_operacion"] == 100
        assert order["ml_order_id"] == "ML100"
        assert order["mla_id"] == "111"

        # Sums across the two details
        assert order["cantidad"] == 2
        assert order["monto_total"] == pytest.approx(2000.0)
        assert order["costo_total_sin_iva"] == pytest.approx(700.0)

    def test_shipping_applied_exactly_once_per_order(self) -> None:
        """Regression guard for the double-subtraction hazard (D1)."""
        core = _get_core_module()

        single = _detail_row(
            mlo_id=200,
            ml_id="ML200",
            mlp_id=333,
            pack_id=None,
            monto_unitario=2000.0,
            cantidad=1,
            costo_sin_iva=400.0,
            seller_shipping_cost=200.0,
            shipment_total=2000.0,
        )
        multi = [
            _detail_row(
                mlo_id=201,
                ml_id="ML201",
                mlp_id=444,
                pack_id="PACK-B",
                monto_unitario=1000.0,
                cantidad=1,
                costo_sin_iva=200.0,
                seller_shipping_cost=200.0,
                shipment_total=2000.0,
                codigo="SKU-C",
            ),
            _detail_row(
                mlo_id=201,
                ml_id="ML201",
                mlp_id=555,
                pack_id="PACK-B",
                monto_unitario=1000.0,
                cantidad=1,
                costo_sin_iva=200.0,
                seller_shipping_cost=200.0,
                shipment_total=2000.0,
                codigo="SKU-D",
            ),
        ]

        folded_single = core.fold_order_rows([single])
        folded_multi = core.fold_order_rows(multi)

        # Same total monto/costo/shipping split across two orders (200 vs 201);
        # the per-order shipping cost (sin IVA) must be identical since
        # shipment_total/seller_shipping_cost are the same in both scenarios,
        # and it must be subtracted only ONCE from the multi-item order's ganancia.
        costo_envio_single = folded_single[200]["costo_envio_ml"]
        costo_envio_multi = folded_multi[201]["costo_envio_ml"]

        assert costo_envio_single == pytest.approx(costo_envio_multi)
        assert costo_envio_multi > 0

        # ganancia = monto_limpio - costo_total; verify shipping subtracted once
        # by reconstructing monto_limpio without any double subtraction:
        # sum(detail monto_limpio excluding shipping) - costo_envio_once
        expected_ganancia = folded_multi[201]["monto_limpio"] - folded_multi[201]["costo_total_sin_iva"]
        assert folded_multi[201]["ganancia"] == pytest.approx(expected_ganancia)


class TestPackOffsetCountsDistinctOrders:
    """count_per_pack must count DISTINCT ORDERS per pack, not raw detail rows."""

    def test_count_per_pack_counts_orders_not_detail_rows(self) -> None:
        core = _get_core_module()

        # Order 300 has 2 details in pack PACK-X; order 301 has 1 detail, also PACK-X.
        rows = [
            _detail_row(
                mlo_id=300,
                ml_id="ML300",
                mlp_id=1,
                pack_id="PACK-X",
                monto_unitario=500.0,
                cantidad=1,
                costo_sin_iva=100.0,
                seller_shipping_cost=None,
                shipment_total=None,
                codigo="SKU-E",
            ),
            _detail_row(
                mlo_id=300,
                ml_id="ML300",
                mlp_id=2,
                pack_id="PACK-X",
                monto_unitario=500.0,
                cantidad=1,
                costo_sin_iva=100.0,
                seller_shipping_cost=None,
                shipment_total=None,
                codigo="SKU-F",
            ),
            _detail_row(
                mlo_id=301,
                ml_id="ML301",
                mlp_id=3,
                pack_id="PACK-X",
                monto_unitario=500.0,
                cantidad=1,
                costo_sin_iva=100.0,
                seller_shipping_cost=None,
                shipment_total=None,
                codigo="SKU-G",
            ),
        ]

        pack_counts = core.count_per_pack(rows)

        # 3 detail rows total, but only 2 DISTINCT orders share PACK-X.
        assert pack_counts["PACK-X"] == 2


class TestSingleItemOrderParity:
    """A single-item order's folded result must be identical to the per-detail result."""

    def test_single_item_order_stays_identical(self) -> None:
        core = _get_core_module()

        row = _detail_row(
            mlo_id=400,
            ml_id="ML400",
            mlp_id=999,
            pack_id=None,
            monto_unitario=1500.0,
            cantidad=1,
            costo_sin_iva=500.0,
            seller_shipping_cost=None,
            shipment_total=None,
        )

        folded = core.fold_order_rows([row])
        order = folded[400]

        # Single-item order: sums equal the single detail's own values.
        assert order["monto_total"] == pytest.approx(1500.0)
        assert order["cantidad"] == 1
        assert order["costo_total_sin_iva"] == pytest.approx(500.0)
        assert order["id_operacion"] == 400
        assert order["ml_order_id"] == "ML400"
        assert order["mla_id"] == "999"


class TestQueryBuilderShape:
    """SQL string guards (SQLite-safe) for the shared aggregating query builder."""

    def test_query_has_no_distinct_on(self) -> None:
        core = _get_core_module()
        sql_text = core.build_aggregation_sql()
        assert "DISTINCT ON" not in str(sql_text), (
            "The core aggregating query must NOT use DISTINCT ON — it must return "
            "ALL details per order so the Python fold can SUM them (design v2 D1)."
        )

    def test_query_uses_half_open_date_bounds(self) -> None:
        core = _get_core_module()
        sql_text = core.build_aggregation_sql()
        sql_str = str(sql_text)
        assert ">= :from_ts" in sql_str
        assert "< :to_ts" in sql_str
        assert "BETWEEN :from_date AND :to_date" not in sql_str

    def test_query_selects_mlo_cd_as_date_window_column(self) -> None:
        core = _get_core_module()
        sql_text = core.build_aggregation_sql()
        assert "mlo_cd" in str(sql_text)


class TestShippingProrationAcrossSharedShipment:
    """R3-001 (BLOCKER): shipping must be PRORATED across orders sharing a
    `mlshippingid`, not charged in full to every order.

    `shipment_total`'s underlying subquery joins on `mlshippingid`, which can
    span MULTIPLE orders (not just multiple details of ONE order). Charging
    the full `seller_shipping_cost` to every order sharing that shipment
    overcounts shipping system-wide and deflates ganancia.
    """

    def test_shipping_prorated_across_two_orders_sharing_one_shipment(self) -> None:
        core = _get_core_module()

        # Two DIFFERENT orders (200 and 201) share one mlshippingid. The SQL
        # subquery for shipment_total sums over BOTH orders' details, so both
        # rows report the SAME shipment_total and seller_shipping_cost.
        shared_seller_shipping_cost = 300.0  # with IVA, whole shipment
        shared_shipment_total = 4000.0  # with IVA, monto across BOTH orders

        order_a_monto = 1000.0
        order_b_monto = 3000.0

        order_a = _detail_row(
            mlo_id=200,
            ml_id="ML200",
            mlp_id=1,
            pack_id=None,
            monto_unitario=order_a_monto,
            cantidad=1,
            costo_sin_iva=300.0,
            seller_shipping_cost=shared_seller_shipping_cost,
            shipment_total=shared_shipment_total,
            mlod_id=1,
        )
        order_b = _detail_row(
            mlo_id=201,
            ml_id="ML201",
            mlp_id=2,
            pack_id=None,
            monto_unitario=order_b_monto,
            cantidad=1,
            costo_sin_iva=900.0,
            seller_shipping_cost=shared_seller_shipping_cost,
            shipment_total=shared_shipment_total,
            mlod_id=1,
        )

        folded = core.fold_order_rows([order_a, order_b])

        shipping_a = folded[200]["costo_envio_ml"]
        shipping_b = folded[201]["costo_envio_ml"]

        total_shipping_sin_iva = shared_seller_shipping_cost / core.DEFAULT_IVA_MULTIPLIER
        expected_a = total_shipping_sin_iva * (order_a_monto / shared_shipment_total)
        expected_b = total_shipping_sin_iva * (order_b_monto / shared_shipment_total)

        assert shipping_a == pytest.approx(expected_a)
        assert shipping_b == pytest.approx(expected_b)

        # No overcounting: the two orders' shipping sums to the shipment total.
        assert (shipping_a + shipping_b) == pytest.approx(total_shipping_sin_iva)

        # Regression guard for the pre-fix bug: full shipping was charged to BOTH orders.
        assert shipping_a != pytest.approx(total_shipping_sin_iva)
        assert shipping_b != pytest.approx(total_shipping_sin_iva)


class _FakePricingConstantsQuery:
    """Minimal stand-in for `db.query(PricingConstants).filter(...).order_by(...).first()`."""

    def __init__(self, constants: SimpleNamespace) -> None:
        self._constants = constants

    def filter(self, *args, **kwargs) -> "_FakePricingConstantsQuery":
        return self

    def order_by(self, *args, **kwargs) -> "_FakePricingConstantsQuery":
        return self

    def first(self) -> SimpleNamespace:
        return self._constants


class _FakeDbSession:
    """Minimal stand-in `db_session` so `calcular_metricas_ml` takes the
    offset_flex-enabled branch (real synthetic tests were passing
    `db_session=None`, which made `offset_flex` always 0 — R3-003).
    """

    def __init__(self, offset_flex: float = 500.0, monto_tier3: float = 33000.0) -> None:
        # Includes every field calcular_comision_ml also reads off this same
        # stubbed row (comision_ml is computed dynamically from
        # fecha_venta + comision_base_porcentaje in these tests).
        self._constants = SimpleNamespace(
            offset_flex=offset_flex,
            monto_tier1=15000.0,
            monto_tier2=24000.0,
            monto_tier3=monto_tier3,
            comision_tier1=1095.0,
            comision_tier2=2190.0,
            comision_tier3=2628.0,
            varios_porcentaje=6.5,
            fecha_desde=None,
        )

    def query(self, *args, **kwargs) -> _FakePricingConstantsQuery:
        return _FakePricingConstantsQuery(self._constants)


class TestOffsetFlexAppliedOncePerOrder:
    """R3-002 (BLOCKER): offset_flex is a FIXED per-shipment amount, must be
    applied ONCE per order, never summed across qualifying details.
    """

    def test_offset_flex_not_multiplied_across_multiple_qualifying_details(self) -> None:
        core = _get_core_module()
        fake_db = _FakeDbSession(offset_flex=500.0, monto_tier3=33000.0)

        # Two details in the same self_service order, BOTH under monto_tier3
        # (both qualify for the offset individually).
        rows = [
            _detail_row(
                mlo_id=500,
                ml_id="ML500",
                mlp_id=1,
                pack_id="PACK-Z",
                monto_unitario=1000.0,
                cantidad=1,
                costo_sin_iva=200.0,
                seller_shipping_cost=None,
                shipment_total=None,
                tipo_logistica="self_service",
                mlod_id=1,
            ),
            _detail_row(
                mlo_id=500,
                ml_id="ML500",
                mlp_id=2,
                pack_id="PACK-Z",
                monto_unitario=1500.0,
                cantidad=1,
                costo_sin_iva=300.0,
                seller_shipping_cost=None,
                shipment_total=None,
                tipo_logistica="self_service",
                mlod_id=2,
            ),
        ]

        folded = core.fold_order_rows(rows, db_session=fake_db)

        # Applied ONCE (500.0), not summed (1000.0) across the two qualifying details.
        assert folded[500]["offset_flex"] == pytest.approx(500.0)

    def test_offset_flex_zero_when_no_detail_qualifies(self) -> None:
        core = _get_core_module()
        fake_db = _FakeDbSession(offset_flex=500.0, monto_tier3=33000.0)

        rows = [
            _detail_row(
                mlo_id=501,
                ml_id="ML501",
                mlp_id=1,
                pack_id=None,
                monto_unitario=50000.0,  # above monto_tier3 -> does not qualify
                cantidad=1,
                costo_sin_iva=200.0,
                seller_shipping_cost=None,
                shipment_total=None,
                tipo_logistica="self_service",
                mlod_id=1,
            ),
        ]

        folded = core.fold_order_rows(rows, db_session=fake_db)
        assert folded[501]["offset_flex"] == pytest.approx(0.0)


class TestIterableConsumedOnceOnly:
    """R2-001 (CRITICAL): `fold_order_rows` must materialize its `rows`
    argument exactly once — a one-shot generator must still produce correct
    pack counts and folded values.

    `count_per_pack()`'s return value is not currently surfaced in the folded
    output (its consumer, `calcular_metricas_ml`'s `count_per_pack` param, is
    marked DEPRECATED upstream), so we spy on the internal call to prove
    `count_per_pack()` still receives the FULL row set even when the caller
    passed a one-shot generator — this is exactly what silently breaks if
    `rows` is iterated twice without materializing it first.
    """

    def _row_generator(self):
        yield _detail_row(
            mlo_id=600,
            ml_id="ML600",
            mlp_id=1,
            pack_id="PACK-GEN",
            monto_unitario=500.0,
            cantidad=1,
            costo_sin_iva=100.0,
            seller_shipping_cost=None,
            shipment_total=None,
            mlod_id=1,
        )
        yield _detail_row(
            mlo_id=601,
            ml_id="ML601",
            mlp_id=2,
            pack_id="PACK-GEN",
            monto_unitario=500.0,
            cantidad=1,
            costo_sin_iva=100.0,
            seller_shipping_cost=None,
            shipment_total=None,
            mlod_id=1,
        )

    def test_accepts_one_shot_generator_without_losing_pack_counts(self) -> None:
        core = _get_core_module()

        folded = core.fold_order_rows(self._row_generator())

        assert len(folded) == 2
        assert folded[600]["monto_total"] == pytest.approx(500.0)
        assert folded[601]["monto_total"] == pytest.approx(500.0)

    def test_count_per_pack_receives_full_materialized_row_set_from_generator(self, monkeypatch) -> None:
        core = _get_core_module()

        original_count_per_pack = core.count_per_pack
        captured: dict[str, list] = {}

        def _spy(rows):
            materialized = list(rows)
            captured["rows"] = materialized
            return original_count_per_pack(materialized)

        monkeypatch.setattr(core, "count_per_pack", _spy)

        core.fold_order_rows(self._row_generator())

        # Pre-fix: the generator is exhausted by the grouping loop BEFORE
        # count_per_pack() is called, so it would receive an EMPTY iterable.
        assert len(captured["rows"]) == 2


class TestRepresentativeDetailIsDeterministic:
    """R3-006: the representative detail (for descriptive fields / mla_id)
    must be picked deterministically by minimum `mlod_id`, not by caller
    iteration order.
    """

    def test_representative_picked_by_min_mlod_id_regardless_of_list_order(self) -> None:
        core = _get_core_module()

        # Deliberately out of mlod_id order in the input list.
        rows = [
            _detail_row(
                mlo_id=700,
                ml_id="ML700",
                mlp_id=999,  # higher mlod_id, should NOT be the representative
                pack_id=None,
                monto_unitario=100.0,
                cantidad=1,
                costo_sin_iva=50.0,
                seller_shipping_cost=None,
                shipment_total=None,
                mlod_id=5,
                codigo="SKU-LATER",
            ),
            _detail_row(
                mlo_id=700,
                ml_id="ML700",
                mlp_id=111,  # lowest mlod_id, SHOULD be the representative
                pack_id=None,
                monto_unitario=200.0,
                cantidad=1,
                costo_sin_iva=80.0,
                seller_shipping_cost=None,
                shipment_total=None,
                mlod_id=1,
                codigo="SKU-FIRST",
            ),
        ]

        folded = core.fold_order_rows(rows)

        assert folded[700]["mla_id"] == "111"
        assert folded[700]["codigo"] == "SKU-FIRST"


class TestEdgeCases:
    """R3-007: missing publication, empty input, zero/negative amounts."""

    def test_missing_publication_yields_none_mla_id(self) -> None:
        core = _get_core_module()

        row = _detail_row(
            mlo_id=800,
            ml_id="ML800",
            mlp_id=None,  # unresolved publication
            pack_id=None,
            monto_unitario=1000.0,
            cantidad=1,
            costo_sin_iva=200.0,
            seller_shipping_cost=None,
            shipment_total=None,
            mlod_id=1,
        )

        folded = core.fold_order_rows([row])
        assert folded[800]["mla_id"] is None
        assert folded[800]["id_operacion"] == 800
        assert folded[800]["ml_order_id"] == "ML800"

    def test_empty_input_returns_empty_dict(self) -> None:
        core = _get_core_module()
        folded = core.fold_order_rows([])
        assert folded == {}

    def test_zero_cantidad_and_costo_does_not_crash(self) -> None:
        core = _get_core_module()

        row = _detail_row(
            mlo_id=900,
            ml_id="ML900",
            mlp_id=1,
            pack_id=None,
            monto_unitario=0.0,
            cantidad=0,
            costo_sin_iva=0.0,
            seller_shipping_cost=None,
            shipment_total=None,
            mlod_id=1,
        )

        folded = core.fold_order_rows([row])
        assert folded[900]["cantidad"] == 0
        assert folded[900]["costo_total_sin_iva"] == pytest.approx(0.0)
        # No division-by-zero on markup_porcentaje when costo_total_sin_iva == 0.
        assert folded[900]["markup_porcentaje"] == pytest.approx(0.0)
