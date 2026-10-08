"""Golden snapshot of the Productos listing (`GET /productos`), pinned BEFORE the
pricing-context lift (P1 of `publicaciones-ml-vista`).

Why a golden: the markup prefetch and the two closures `_lookup_comision` /
`_resolve_envio` inside `listar_productos` are being moved to a shared service.
The refactor must not change a single byte of the response, and the response is
a long tail of derived numbers (markups per list, rebate, cuotas, pvp, PPP) that
no hand-written assertion covers. So the full serialized response of a seeded
catalogue is committed and compared byte for byte.

The snapshot MUST be generated on code that has NOT been refactored. It is
written only when `PRODUCTOS_GOLDEN_UPDATE=1`; a missing snapshot without that
flag is a failure ("snapshot missing"), never a silent pass.

Regenerate (only when the Productos output is intentionally changed):

    PRODUCTOS_GOLDEN_UPDATE=1 pytest tests/integration/test_productos_listing_golden.py

Seed coverage: USD and ARS costs, a grupo with a shipping average and one
without, price above and below `monto_tier3`, real shipping through the stubbed
cross-DB fetch, an active offer, pvp and cuota lists, rebate, an unmapped
subcategory (default grupo), and (variant) no active commission version.
Everything time dependent is pinned to fixed dates so two runs are identical.

Like the sibling listing tests, the endpoint function is called directly on the
SQLite `db` fixture with the Postgres-only raw queries short-circuited.
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.api.endpoints.productos_listing import listar_productos
from app.models.comision_config import SubcategoriaGrupo
from app.models.comision_versionada import ComisionAdicionalCuota, ComisionBase, ComisionVersion
from app.models.oferta_ml import OfertaML
from app.models.pricing_constants import PricingConstants
from app.models.producto import ProductoERP, ProductoPricing, TipoMoneda
from app.models.publicacion_ml import PublicacionML
from app.models.tipo_cambio import TipoCambio

GOLDEN_PATH = Path(__file__).resolve().parent.parent / "fixtures" / "productos_listing_golden.json"
UPDATE_ENV = "PRODUCTOS_GOLDEN_UPDATE"

_POSTGRES_ONLY_RAW_SQL_MARKERS = ("tienda_nube_productos", "v_ml_catalog_status_latest")
_FETCH_LIST_COST = "app.services.envio_real_service._fetch_list_cost_by_mla"
_PXQ_FILTER_READER = "app.api.endpoints.productos_listing.fetch_mlas_with_pxq_tiers"
_PXQ_QUICKVIEW_READER = "app.api.endpoints.productos_listing.fetch_pxq_tiers_by_mla"

# Far past / far future: always "current" whatever day the test runs.
_PAST = date(2000, 1, 1)
_FUTURE = date(2099, 12, 31)


def _patch_postgres_only_sql(db) -> None:
    original_execute = db.execute

    def _execute_patch(statement, *args, **kwargs):
        if any(marker in str(statement) for marker in _POSTGRES_ONLY_RAW_SQL_MARKERS):
            mock_result = MagicMock()
            mock_result.fetchall.return_value = []
            return mock_result
        return original_execute(statement, *args, **kwargs)

    db.execute = _execute_patch


def _seed_pricing_base(db, *, with_commission_version: bool) -> None:
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
            fecha_desde=_PAST,
        )
    )
    db.add(TipoCambio(fecha=date(2020, 1, 1), moneda="USD", compra=990.0, venta=1000.0))
    # grupo 1: subcat 100 (has a shipping average); grupo 2: subcat 200 (no product
    # has envio > 0 there, so its average stays 0.0).
    db.add(SubcategoriaGrupo(subcat_id=100, grupo_id=1))
    db.add(SubcategoriaGrupo(subcat_id=200, grupo_id=2))
    if with_commission_version:
        version = ComisionVersion(nombre="golden", fecha_desde=_PAST, fecha_hasta=None, activo=True)
        db.add(version)
        db.flush()
        db.add(ComisionBase(version_id=version.id, grupo_id=1, comision_base=12.5))
        db.add(ComisionBase(version_id=version.id, grupo_id=2, comision_base=15.0))
        for cuotas, adicional in ((3, 3.0), (6, 5.0), (9, 7.0), (12, 9.0)):
            db.add(ComisionAdicionalCuota(version_id=version.id, cuotas=cuotas, adicional=adicional))
    db.flush()


def _producto(item_id, *, costo, moneda, subcat, envio, iva=21.0, marca="Golden") -> ProductoERP:
    return ProductoERP(
        item_id=item_id,
        codigo=f"G{item_id}",
        descripcion=f"Golden {item_id}",
        marca=marca,
        categoria="Cat",
        subcategoria_id=subcat,
        costo=costo,
        moneda_costo=moneda,
        iva=iva,
        envio=envio,
        stock=item_id,
        activo=True,
    )


def _seed_catalogue(db) -> None:
    db.add_all(
        [
            # 1: ARS, price below tier3, grupo 1, offer on MLA1
            _producto(1, costo=10000.0, moneda=TipoMoneda.ARS, subcat=100, envio=0.0),
            # 2: USD, price above tier3, no ERP envio -> grupo-1 average applies
            _producto(2, costo=20.0, moneda=TipoMoneda.USD, subcat=100, envio=0.0),
            # 3: ARS, grupo 2 (average 0.0), ERP envio set
            _producto(3, costo=5000.0, moneda=TipoMoneda.ARS, subcat=200, envio=500.0),
            # 4: ARS, unmapped subcategory -> default grupo, above tier3, no envio
            _producto(4, costo=8000.0, moneda=TipoMoneda.ARS, subcat=999, envio=0.0),
            # 5: grupo 2, real shipping through the stubbed cross-DB fetch, rebate + cuotas + pvp
            _producto(5, costo=7000.0, moneda=TipoMoneda.ARS, subcat=200, envio=0.0),
            # 6, 7: feed the grupo-1 shipping average (envio > 0 and active)
            _producto(6, costo=3000.0, moneda=TipoMoneda.ARS, subcat=100, envio=1500.0),
            _producto(7, costo=3500.0, moneda=TipoMoneda.ARS, subcat=100, envio=2500.0),
        ]
    )
    db.flush()
    pricing = {
        1: dict(precio_lista_ml=20000.0, markup_calculado=22.5),
        # 2: USD cost, shipping resolved through the grupo-1 average
        2: dict(
            precio_lista_ml=60000.0,
            markup_calculado=15.0,
            participa_rebate=True,
            precio_3_cuotas=65000.0,
            precio_pvp=70000.0,
        ),
        # 3: grupo 2, ERP envio
        3: dict(
            precio_lista_ml=40000.0,
            markup_calculado=31.0,
            participa_rebate=True,
            precio_6_cuotas=42000.0,
        ),
        # 4: default grupo, above tier3 -> grupo-1 average
        4: dict(
            precio_lista_ml=45000.0,
            markup_calculado=11.0,
            participa_rebate=True,
            precio_pvp=47000.0,
            precio_pvp_3_cuotas=49000.0,
        ),
        5: dict(
            precio_lista_ml=30000.0,
            markup_calculado=18.0,
            participa_rebate=True,
            porcentaje_rebate=3.8,
            precio_3_cuotas=35000.0,
            precio_6_cuotas=38000.0,
            precio_9_cuotas=41000.0,
            precio_12_cuotas=44000.0,
            precio_pvp=36000.0,
            precio_pvp_3_cuotas=39000.0,
            precio_pvp_6_cuotas=42000.0,
            precio_pvp_9_cuotas=45000.0,
            precio_pvp_12_cuotas=48000.0,
        ),
        6: dict(precio_lista_ml=9000.0, markup_calculado=40.0),
        7: dict(precio_lista_ml=10000.0, markup_calculado=42.0),
    }
    for item_id, fields in pricing.items():
        # `fecha_modificacion` has a now() server default: pin it or the snapshot drifts.
        db.add(ProductoPricing(item_id=item_id, fecha_modificacion=datetime(2026, 1, 1, 12, 0, 0), **fields))
    db.add(PublicacionML(mla="MLA1", item_id=1, pricelist_id=4, activo=True))
    db.add(PublicacionML(mla="MLA5", item_id=5, pricelist_id=4, activo=True))
    db.add(PublicacionML(mla="MLA6", item_id=6, pricelist_id=17, activo=True))
    db.flush()
    db.add(
        OfertaML(
            mla="MLA1",
            fecha_desde=_PAST,
            fecha_hasta=_FUTURE,
            precio_final=18000.0,
            pvp_seller=21000.0,
            aporte_meli_pesos=3000.0,
            aporte_meli_porcentaje=14.29,
        )
    )
    db.commit()


def _serialize_obj(obj) -> str:
    """Deterministic text of a JSON-able object; floats keep their `repr`."""
    return json.dumps(obj, sort_keys=True, indent=1, ensure_ascii=False) + "\n"


def _serialize(result) -> str:
    return _serialize_obj(result.model_dump(mode="json"))


def _run(db, **kwargs) -> str:
    _patch_postgres_only_sql(db)
    with patch(_FETCH_LIST_COST, return_value={"MLA5": 1234.5}):
        result = listar_productos(db=db, current_user=SimpleNamespace(id=1), page=1, page_size=50, **kwargs)
    return _serialize(result)


def _load_golden() -> dict:
    if not GOLDEN_PATH.exists():
        return {}
    return json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))


def _assert_matches_golden(variant: str, produced: str) -> None:
    golden = _load_golden()
    if os.environ.get(UPDATE_ENV) == "1":
        golden[variant] = json.loads(produced)
        GOLDEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN_PATH.write_text(
            json.dumps(golden, sort_keys=True, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        return
    assert variant in golden, (
        f"golden snapshot missing for variant {variant!r} at {GOLDEN_PATH}; "
        f"generate it on UNREFACTORED code with {UPDATE_ENV}=1"
    )
    # Compare the serialized text, not parsed objects: floats are compared by
    # `repr`, so 0.1 + 0.2 style drift is a failure, not a rounding.
    assert produced == _serialize_obj(golden[variant])


@pytest.fixture()
def seeded(db):
    _seed_pricing_base(db, with_commission_version=True)
    _seed_catalogue(db)
    return db


@pytest.fixture()
def seeded_without_commission_version(db):
    _seed_pricing_base(db, with_commission_version=False)
    _seed_catalogue(db)
    return db


class TestProductosListingGolden:
    def test_default(self, seeded) -> None:
        _assert_matches_golden("default", _run(seeded))

    def test_sort_by_markup(self, seeded) -> None:
        _assert_matches_golden(
            "sort_markup",
            _run(seeded, orden_campos="markup_clasica", orden_direcciones="desc"),
        )

    def test_pxq_filter(self, seeded) -> None:
        with (
            patch(_PXQ_FILTER_READER, return_value={"MLA1", "MLA5"}),
            patch(_PXQ_QUICKVIEW_READER, return_value={}),
        ):
            produced = _run(seeded, con_pxq=True)
        _assert_matches_golden("pxq_filter", produced)

    def test_missing_commission_version(self, seeded_without_commission_version) -> None:
        _assert_matches_golden("no_commission_version", _run(seeded_without_commission_version))

    def test_seed_exercises_the_interesting_branches(self, seeded) -> None:
        """Guard against a vacuous golden: the snapshot must actually contain
        derived numbers, otherwise a refactor could 'preserve' all-nulls."""
        produced = json.loads(_run(seeded))
        rows = {p["item_id"]: p for p in produced["productos"]}
        assert len(rows) == 7
        # Offer markup (MLA1), rebate markup and a cuota markup are computed, not null.
        assert rows[1]["mejor_oferta_markup"] is not None
        assert rows[5]["markup_rebate"] is not None
        assert rows[5]["markup_3_cuotas"] is not None
        # The shipping branches show through the rebate markup of 2 (grupo average,
        # USD), 3 (ERP envio) and 4 (default grupo): all computed.
        for item_id in (2, 3, 4):
            assert rows[item_id]["markup_rebate"] is not None


# Statements issued by `listar_productos` for the seeded catalogue. Recorded on
# the unrefactored endpoint: moving the prefetch into a service must neither add
# nor drop a query.
EXPECTED_DEFAULT_STATEMENTS = 18


class TestProductosListingStatementCount:
    def test_default_variant_statement_count(self, seeded, query_counter) -> None:
        with query_counter() as counter:
            _run(seeded)
        assert counter.total == EXPECTED_DEFAULT_STATEMENTS
