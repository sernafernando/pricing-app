"""TP-Link ingestion resolves its store ids from the `tplink` clave (no
hardcoded store id) and fails closed when none are configured."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.services.tiendas_oficiales import StoreClaveNotConfigured

_APP = Path(__file__).resolve().parents[2] / "app"


def test_aggregation_sql_filters_by_the_store_id_list() -> None:
    from app.scripts import _tplink_metricas_core as core

    sql = core.build_aggregation_sql()
    assert "mlp_official_store_id IN :store_ids" in sql.text
    assert "= :store_id\n" not in sql.text
    assert sql._bindparams["store_ids"].expanding is True


def test_aggregation_sql_selects_the_store_column_the_fold_reads() -> None:
    from app.scripts import _tplink_metricas_core as core

    assert "tmlip.mlp_official_store_id as mlp_official_store_id" in core.build_aggregation_sql().text


def test_a_row_without_the_store_column_fails_loudly_instead_of_storing_null() -> None:
    from app.scripts import _tplink_metricas_core as core

    row = _order_row()
    del row.mlp_official_store_id
    with pytest.raises(AttributeError):
        core.fold_order_rows([row], db_session=MagicMock())


def _order_row(**overrides) -> SimpleNamespace:
    values = dict(
        id_operacion=1,
        ml_id="ML1",
        mlp_id=1,
        pack_id=None,
        item_id=1,
        codigo="C",
        descripcion="D",
        marca="TP-LINK",
        categoria="R",
        subcategoria="S",
        cantidad=1,
        monto_unitario=1000.0,
        monto_total=1000.0,
        costo_sin_iva=400.0,
        iva=21.0,
        comision_base_porcentaje=12.0,
        subcat_id=None,
        pricelist_id=None,
        tipo_logistica=None,
        seller_shipping_cost=0.0,
        shipment_total=0.0,
        envio_producto=None,
        fecha_venta=datetime(2026, 7, 1, 10, 0, 0),
        mlod_id=1,
        mlp_official_store_id=471846,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def test_folded_row_keeps_the_real_store_id_of_the_order() -> None:
    from app.scripts import _tplink_metricas_core as core

    row = SimpleNamespace(
        id_operacion=1,
        ml_id="ML1",
        mlp_id=1,
        pack_id=None,
        item_id=1,
        codigo="C",
        descripcion="D",
        marca="TP-LINK",
        categoria="R",
        subcategoria="S",
        cantidad=1,
        monto_unitario=1000.0,
        monto_total=1000.0,
        costo_sin_iva=400.0,
        iva=21.0,
        comision_base_porcentaje=12.0,
        subcat_id=None,
        pricelist_id=None,
        tipo_logistica=None,
        seller_shipping_cost=0.0,
        shipment_total=0.0,
        envio_producto=None,
        fecha_venta=datetime(2026, 7, 1, 10, 0, 0),
        mlod_id=1,
        mlp_official_store_id=471846,
    )
    folded = core.fold_order_rows([row], db_session=MagicMock())
    assert folded[1]["mlp_official_store_id"] == 471846


@pytest.mark.parametrize("module", ["agregar_metricas_tplink", "agregar_metricas_tplink_incremental"])
def test_jobs_bind_every_store_of_the_clave(module: str) -> None:
    import importlib

    mod = importlib.import_module(f"app.scripts.{module}")
    db = MagicMock()
    with patch.object(mod, "require_store_ids_for_clave", return_value=[2645, 471846]) as resolver:
        if module == "agregar_metricas_tplink_incremental":
            from datetime import datetime

            mod.calcular_metricas_locales(db, datetime(2026, 1, 1), datetime(2026, 1, 2))
        else:
            from datetime import date

            with patch.object(mod, "SessionLocal", return_value=db):
                mod.agregar_metricas_rango(date(2026, 1, 1), date(2026, 1, 1))
    resolver.assert_called_once_with(db, "tplink")
    params = db.execute.call_args_list[0].args[1]
    assert params["store_ids"] == [2645, 471846]


def test_incremental_job_fails_closed_without_stores() -> None:
    from datetime import datetime

    from app.scripts import agregar_metricas_tplink_incremental as mod

    db = MagicMock()
    with patch.object(mod, "require_store_ids_for_clave", side_effect=StoreClaveNotConfigured("tplink")):
        with pytest.raises(StoreClaveNotConfigured):
            mod.calcular_metricas_locales(db, datetime(2026, 1, 1), datetime(2026, 1, 2))
    db.execute.assert_not_called()


def test_no_hardcoded_tplink_store_id_left_in_app_code() -> None:
    offenders = []
    for path in _APP.rglob("*.py"):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"\b2645\b", line):
                offenders.append(f"{path.relative_to(_APP)}:{lineno}")
    assert offenders == []
