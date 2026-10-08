"""Unit tests for `app.services.pricing_context`: the Productos markup prefetch
and the two closures (`_lookup_comision`, `_resolve_envio`) lifted out of
`listar_productos`.

The contract is "identical to what the endpoint did inline", so every expected
number below is the value the old closure produced for the same inputs. The
endpoint-level proof is `tests/integration/test_productos_listing_golden.py`.
"""

from __future__ import annotations

from datetime import date, timedelta
from functools import partial

import pytest

from app.models.comision_config import SubcategoriaGrupo
from app.models.comision_versionada import ComisionAdicionalCuota, ComisionBase, ComisionVersion
from app.models.pricing_constants import PricingConstants
from app.models.producto import ProductoERP, TipoMoneda
from app.models.tipo_cambio import TipoCambio
from app.services.pricing_calculator import GRUPO_DEFAULT
from app.services.pricing_context import PricingContext, build_pricing_context, resolve_envio

HOY = date(2026, 10, 7)
CONSTANTES = {"monto_tier3": 33000.0}


def _ctx(**overrides) -> PricingContext:
    values = dict(
        hoy=HOY,
        tipo_cambio_usd=1000.0,
        constantes=CONSTANTES,
        subcat_to_grupo={100: 1, 200: 2},
        active_version_id=7,
        comision_base={1: 12.5, 2: 15.0},
        comision_adicional={3: 3.0, 6: 5.0, 9: 7.0, 12: 9.0},
        envio_promedio_by_grupo={1: 2000.0, 2: 0.0},
    )
    values.update(overrides)
    return PricingContext(**values)


class TestGrupoOf:
    def test_mapped_subcategory(self) -> None:
        assert _ctx().grupo_of(200) == 2

    def test_unmapped_subcategory_falls_back_to_default(self) -> None:
        assert _ctx().grupo_of(999) == GRUPO_DEFAULT

    def test_none_subcategory_falls_back_to_default(self) -> None:
        assert _ctx().grupo_of(None) == GRUPO_DEFAULT


class TestComision:
    """`comision(pricelist, grupo)` == the old `_lookup_comision`."""

    def test_classic_list_is_the_base(self) -> None:
        assert _ctx().comision(4, 1) == 12.5

    def test_cuota_list_adds_the_installment_surcharge(self) -> None:
        # 17 = 3 cuotas -> 12.5 + 3.0
        assert _ctx().comision(17, 1) == 15.5

    def test_pvp_list_resolves_through_its_web_equivalent(self) -> None:
        # 12 (pvp) -> 4 (web, base only); 18 (pvp 3 cuotas) -> 17
        assert _ctx().comision(12, 2) == 15.0
        assert _ctx().comision(18, 2) == 18.0

    def test_list_without_cuotas_mapping_is_the_base(self) -> None:
        assert _ctx().comision(5, 1) == 12.5

    def test_missing_surcharge_adds_zero(self) -> None:
        assert _ctx(comision_adicional={}).comision(14, 1) == 12.5

    def test_grupo_without_base_is_none(self) -> None:
        assert _ctx().comision(4, 99) is None

    def test_no_active_version_is_none(self) -> None:
        assert _ctx(active_version_id=None, comision_base={}, comision_adicional={}).comision(4, 1) is None


class TestCostoEnPesos:
    def test_ars_is_untouched(self) -> None:
        assert _ctx().costo_en_pesos(5000.0, "ARS") == 5000.0

    def test_usd_uses_the_prefetched_rate(self) -> None:
        assert _ctx(tipo_cambio_usd=1250.0).costo_en_pesos(20.0, "USD") == 25000.0

    def test_enum_currency_is_accepted(self) -> None:
        # ProductoERP.moneda_costo is a str-enum: TipoMoneda.USD == "USD".
        assert _ctx(tipo_cambio_usd=1000.0).costo_en_pesos(2.0, TipoMoneda.USD) == 2000.0

    def test_usd_without_rate_keeps_the_cost(self) -> None:
        assert _ctx(tipo_cambio_usd=None).costo_en_pesos(20.0, "USD") == 20.0


class TestResolveEnvio:
    """`resolve_envio(ctx, envio_real_by_item, ...)` == the old `_resolve_envio`."""

    def test_real_cost_wins_even_when_zero(self) -> None:
        assert resolve_envio(_ctx(), {1: 0.0}, 1, 500.0, 1, 50000.0) == 0.0
        assert resolve_envio(_ctx(), {1: 1234.5}, 1, 500.0, 1, 50000.0) == 1234.5

    def test_erp_envio_when_no_real_cost(self) -> None:
        assert resolve_envio(_ctx(), {}, 1, 500.0, 1, 50000.0) == 500.0

    def test_grupo_average_when_expensive_and_no_envio(self) -> None:
        assert resolve_envio(_ctx(), {}, 1, 0, 1, 33000.0) == 2000.0

    def test_no_average_below_tier3(self) -> None:
        assert resolve_envio(_ctx(), {}, 1, 0, 1, 32999.99) == 0

    def test_none_producto_envio_counts_as_zero(self) -> None:
        assert resolve_envio(_ctx(), {}, 1, None, 1, 40000.0) == 2000.0

    def test_unknown_grupo_average_is_zero(self) -> None:
        assert resolve_envio(_ctx(), {}, 1, 0, 42, 40000.0) == 0.0

    def test_missing_grupo_id_skips_the_average(self) -> None:
        assert resolve_envio(_ctx(), {}, 1, 0, None, 40000.0) == 0

    def test_default_tier3_when_there_are_no_constants(self) -> None:
        ctx = _ctx(constantes=None)
        assert resolve_envio(ctx, {}, 1, 0, 1, 33000.0) == 2000.0
        assert resolve_envio(ctx, {}, 1, 0, 1, 32999.0) == 0

    def test_partial_binding_matches_the_endpoint_call_shape(self) -> None:
        # The endpoint binds `_resolve_envio = partial(resolve_envio, ctx, envio_real_by_item)`
        # and calls it as `_resolve_envio(item_id, producto_envio, grupo_id, precio)`.
        bound = partial(resolve_envio, _ctx(), {9: 777.0})
        assert bound(9, 0, 1, 50000.0) == 777.0
        assert bound(8, 0, 1, 50000.0) == 2000.0


class TestBuildPricingContext:
    def _seed(self, db) -> None:
        db.add(
            PricingConstants(
                monto_tier1=15000,
                monto_tier2=24000,
                monto_tier3=33000,
                comision_tier1=1095,
                comision_tier2=2190,
                comision_tier3=2628,
                varios_porcentaje=6.5,
                grupo_comision_default=1,
                markup_adicional_cuotas=4.0,
                fecha_desde=date(2000, 1, 1),
            )
        )
        db.add(TipoCambio(fecha=date(2020, 1, 1), moneda="USD", compra=990.0, venta=1000.0))
        db.add(SubcategoriaGrupo(subcat_id=100, grupo_id=1))
        db.add(SubcategoriaGrupo(subcat_id=101, grupo_id=1))
        db.add(SubcategoriaGrupo(subcat_id=200, grupo_id=2))
        version = ComisionVersion(nombre="v", fecha_desde=date(2000, 1, 1), fecha_hasta=None, activo=True)
        db.add(version)
        db.flush()
        db.add(ComisionBase(version_id=version.id, grupo_id=1, comision_base=12.5))
        db.add(ComisionAdicionalCuota(version_id=version.id, cuotas=3, adicional=3.0))
        for item_id, subcat, envio, activo in (
            (1, 100, 1000.0, True),
            (2, 100, 3000.0, True),
            (3, 101, 5000.0, True),
            (4, 100, 9000.0, False),  # inactive: ignored
            (5, 200, 0.0, True),  # envio 0: ignored
        ):
            db.add(
                ProductoERP(
                    item_id=item_id,
                    codigo=f"C{item_id}",
                    descripcion="d",
                    subcategoria_id=subcat,
                    costo=1.0,
                    moneda_costo=TipoMoneda.ARS,
                    envio=envio,
                    activo=activo,
                )
            )
        db.commit()

    def test_prefetch_matches_the_old_inline_block(self, db) -> None:
        self._seed(db)
        ctx = build_pricing_context(db, HOY)

        assert ctx.hoy == HOY
        assert ctx.tipo_cambio_usd == 1000.0
        assert ctx.constantes["monto_tier3"] == 33000.0
        assert dict(ctx.subcat_to_grupo) == {100: 1, 101: 1, 200: 2}
        assert ctx.active_version_id is not None
        assert dict(ctx.comision_base) == {1: 12.5}
        assert dict(ctx.comision_adicional) == {3: 3.0}
        # Per-subcategory averages (100 -> 2000, 101 -> 5000), then the mean of
        # those per grupo; grupo 2 has no priced product -> 0.0.
        assert ctx.envio_promedio_by_grupo == {1: 3500.0, 2: 0.0}
        assert ctx.comision(17, 1) == 15.5

    def test_hoy_defaults_to_today(self, db) -> None:
        assert build_pricing_context(db).hoy == date.today()

    def test_expired_version_is_not_active(self, db) -> None:
        db.add(
            ComisionVersion(
                nombre="old",
                fecha_desde=date(2000, 1, 1),
                fecha_hasta=HOY - timedelta(days=1),
                activo=True,
            )
        )
        db.commit()
        ctx = build_pricing_context(db, HOY)
        assert ctx.active_version_id is None
        assert ctx.comision(4, 1) is None

    def test_inactive_version_is_not_active(self, db) -> None:
        db.add(ComisionVersion(nombre="off", fecha_desde=date(2000, 1, 1), fecha_hasta=None, activo=False))
        db.commit()
        assert build_pricing_context(db, HOY).active_version_id is None

    def test_context_is_frozen(self, db) -> None:
        ctx = build_pricing_context(db, HOY)
        with pytest.raises(Exception):
            ctx.hoy = date(2000, 1, 1)  # type: ignore[misc]
