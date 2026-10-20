"""Costing reads the combo bill of materials from the app-owned
`combo_componentes`, never the ERP mirror `tb_item_association`
(combos-propios C2). The mirror holds rows the app table does not, so a
reader still on the mirror answers differently."""

from __future__ import annotations

from decimal import Decimal

from app.models.combo_componente import ComboComponente
from app.models.tb_item_association import TbItemAssociation
from app.services.ml_orders_ingestion.costeo_service import componentes_por_combo
from app.services.ml_orders_ingestion.tp_cost_fill import _combos_de


def _seed(db) -> None:
    # App table: combo 500 = 2 x 901 + 1 x 903; combo 700 = 1 x 903.
    db.add_all(
        [
            ComboComponente(combo_item_id=500, componente_item_id=901, cantidad=Decimal("2")),
            ComboComponente(combo_item_id=500, componente_item_id=903, cantidad=Decimal("1")),
            ComboComponente(combo_item_id=700, componente_item_id=903, cantidad=Decimal("1")),
        ]
    )
    # Mirror: a stale component (902) and a stale combo (600) the app table lacks.
    db.add_all(
        [
            TbItemAssociation(comp_id=1, itema_id=1, item_id=500, item_id_1=901, iasso_qty=2),
            TbItemAssociation(comp_id=1, itema_id=2, item_id=500, item_id_1=902, iasso_qty=1),
            TbItemAssociation(comp_id=1, itema_id=3, item_id=600, item_id_1=901, iasso_qty=1),
        ]
    )
    db.flush()


def test_componentes_por_combo_reads_the_app_table(db) -> None:
    _seed(db)

    assert componentes_por_combo(db, [500, 600, 700, 500]) == {
        500: [(901, Decimal("2")), (903, Decimal("1"))],
        700: [(903, Decimal("1"))],
    }
    assert componentes_por_combo(db, []) == {}


def test_tp_cost_fill_reverse_lookup_reads_the_app_table(db) -> None:
    _seed(db)

    assert _combos_de(db, [901, 902, 903]) == {901: {500}, 903: {500, 700}}
