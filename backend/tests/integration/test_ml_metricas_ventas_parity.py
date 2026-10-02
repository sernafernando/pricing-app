"""ODD `metricas-ml-tablero`, "Sin tabla resumen" ST1: the Métricas ML board
and the Ventas ML screen read the SAME orders with the SAME rules, so for the
same period their totals agree: units, gross, Total Gauss and markup.

Seeded: lone orders, a multi-item order, a pack whose markup is all-or-
nothing, an unresolved order, one being recalculated, a cancellation ML did
not cover (out of both), one it covered (in both), and sales outside the
period on either side.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from app.core.config import settings
from app.models.permiso import Permiso, RolPermisoBase
from app.services.ml_daily_metrics import board
from tests.services.ml_daily_metrics.seed import Line, seed_group, seed_order, seed_sale

NOW = datetime(2026, 9, 30, 18, 0, tzinfo=timezone.utc)
BA = ZoneInfo("America/Argentina/Buenos_Aires")
PERIOD = {"date_from": "2026-09-01", "date_to": "2026-09-30"}


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setattr(settings, "ML_USER_ID", 999)
    monkeypatch.setattr(settings, "ML_ORDERS_OPS_ENABLED", True)
    monkeypatch.setattr(board, "now_utc", lambda: NOW)


def _grant(db, rol, *codigos: str) -> None:
    for codigo in codigos:
        permiso = db.query(Permiso).filter(Permiso.codigo == codigo).first()
        if not permiso:
            permiso = Permiso(codigo=codigo, nombre=codigo, descripcion="", categoria="t", orden=300)
            db.add(permiso)
            db.flush()
        db.add(RolPermisoBase(rol_id=rol.id, permiso_id=permiso.id))
    db.flush()


def _at(day: date, hour: int = 12) -> datetime:
    return datetime(day.year, day.month, day.day, hour, tzinfo=BA).astimezone(timezone.utc)


def _seed(db) -> None:
    sep = date(2026, 9, 1)
    seed_sale(db, 101, _at(sep), [Line(11, "MLA1", 2, Decimal("150"))], tg="40", costo="200")
    # First minutes of the period in Buenos Aires (03:05 UTC): IN.
    seed_sale(db, 102, _at(date(2026, 9, 2)), [Line(12, "MLA2", 1, Decimal("999"))], tg="99", costo="500")
    # Before the period: out of both. (Minutes either side of a Buenos Aires
    # midnight are pinned by `test_board_from_orders.py`'s brute force: under
    # SQLite Ventas ML's tz-aware bounds compare as UTC wall clocks.)
    seed_sale(db, 103, _at(date(2026, 8, 20)), [Line(12, "MLA2", 5, Decimal("10"))], tg="1", costo="5")
    seed_sale(
        db,
        104,
        _at(date(2026, 9, 10)),
        [Line(21, "MLA3", 1, Decimal("500"), Decimal("300")), Line(22, "MLA4", 2, Decimal("80"), Decimal("50"))],
        tg="80",
        costo="400",
    )
    seed_order(db, 105, _at(date(2026, 9, 12)), [Line(11, "MLA1", 1, Decimal("100"))], pack_id=55, tg="30", costo="100")
    seed_order(
        db, 106, _at(date(2026, 9, 12)), [Line(12, "MLA2", 1, Decimal("100"))], pack_id=55, gauss_status="unresolved"
    )
    seed_group(db, "p:55", [105, 106], _at(date(2026, 9, 12)))
    seed_sale(db, 107, _at(date(2026, 9, 15)), [Line(11, "MLA1", 3, Decimal("100"))], gauss_status="unresolved")
    # Unresolved with its cost known: gross in, never Total Gauss or markup.
    seed_sale(
        db, 112, _at(date(2026, 9, 15)), [Line(14, "MLA6", 1, Decimal("80"))], costo="20", gauss_status="unresolved"
    )
    seed_sale(db, 108, _at(date(2026, 9, 16)), [Line(11, "MLA1", 1, Decimal("100"))], tg="5", costo="50", dirty=True)
    seed_sale(
        db, 109, _at(date(2026, 9, 17)), [Line(13, "MLA5", 7, Decimal("100"))], tg="70", costo="100", status="cancelled"
    )
    seed_sale(
        db,
        110,
        _at(date(2026, 9, 18)),
        [Line(13, "MLA5", 1, Decimal("100"))],
        tg="10",
        costo="50",
        status="cancelled",
        covered=True,
    )
    seed_sale(db, 111, _at(date(2026, 10, 1)), [Line(11, "MLA1", 9, Decimal("100"))], tg="9", costo="90")
    db.commit()


def test_board_totals_equal_the_ventas_ml_kpis_for_the_same_period(db, client, admin_auth_headers, rol_admin):
    _grant(db, rol_admin, "ml_ops.ver", "ml_metricas.ver", "ml_metricas.ver_ganancia")
    _seed(db)
    switches = {"include_unknown": "true", "include_in_dispute": "true", "include_cancelled": "false"}

    kpis = client.get("/api/ml-ventas-ops/sales/kpis", params={**PERIOD, **switches}, headers=admin_auth_headers)
    listing = client.get(
        "/api/ml-ventas-ops/sales", params={**PERIOD, **switches, "limit": 200}, headers=admin_auth_headers
    )
    tablero = client.get("/api/ml-metricas/board", params=PERIOD, headers=admin_auth_headers)
    assert kpis.status_code == listing.status_code == tablero.status_code == 200, (kpis.text, listing.text)
    ventas, board_kpis = kpis.json(), tablero.json()["kpis"]

    # "Canceladas" off hides the plain cancellations; one ML covered stays.
    listed_units = sum(
        item["quantity"] for sale in listing.json()["sales"] for order in sale["orders"] for item in order["items"]
    )
    assert board_kpis["units"]["value"] == listed_units == 2 + 1 + 1 + 2 + 1 + 1 + 3 + 1 + 1 + 1
    assert board_kpis["gross"]["value"] == pytest.approx(ventas["gross_billed_ars"])
    assert board_kpis["total_gauss"]["value"] == pytest.approx(ventas["total_gauss_sum"])
    assert board_kpis["markup"]["value"] == pytest.approx(ventas["markup_weighted_pct"], abs=0.05)
