"""The raw SQL in pedidos_export must only name columns that exist on tb_tiendanube_orders.

Migration 20250129_rename_tn_columns_lowercase renamed "tno_orderID" to tno_orderid,
but the export-80 sync kept quoting the old name, so every run failed with
UndefinedColumn and the copy of the TN order number into ws_internalid never ran.
"""

import re
from pathlib import Path

from app.models.tienda_nube_order import TiendaNubeOrder

ENDPOINT = Path(__file__).resolve().parents[2] / "app" / "api" / "endpoints" / "pedidos_export.py"

# Columns referenced through the tno alias, quoted or not: tno."tno_orderID", tno.tno_orderid
TNO_COLUMN = re.compile(r'\btno\."?([A-Za-z_][A-Za-z0-9_]*)"?')


def test_every_tno_column_in_the_export_sync_exists_on_the_model() -> None:
    source = ENDPOINT.read_text(encoding="utf-8")
    referenced = set(TNO_COLUMN.findall(source))
    existing = {column.name for column in TiendaNubeOrder.__table__.columns}

    assert referenced, "the export sync no longer reads tb_tiendanube_orders; update this test"
    assert referenced <= existing, f"unknown tb_tiendanube_orders columns: {sorted(referenced - existing)}"
