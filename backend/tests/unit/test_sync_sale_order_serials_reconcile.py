"""Tests de reconciliación per-scope en sync_sale_order_serials.

Cubre `reconciliar_sale_order_serials`: borra filas fantasma de un sale order o
de un is_id cuando el ERP devuelve el set actual; respeta el guard de respuesta
vacía y el aislamiento entre scopes distintos.
"""

from app.models.tb_sale_order_serial import TbSaleOrderSerial
from app.scripts.sync_sale_order_serials import reconciliar_sale_order_serials


def _crear_fila(db, sose_id: int, is_id: int, soh_id: int) -> None:
    db.add(TbSaleOrderSerial(comp_id=1, bra_id=1, sose_id=sose_id, is_id=is_id, soh_id=soh_id))
    db.flush()


def test_reconcilia_por_soh_id_borra_fantasma(db):
    """Una fila del pedido que el ERP ya no devuelve se elimina."""
    soh = 500
    _crear_fila(db, sose_id=1, is_id=10, soh_id=soh)
    _crear_fila(db, sose_id=2, is_id=11, soh_id=soh)  # fantasma
    _crear_fila(db, sose_id=3, is_id=12, soh_id=soh)

    # El ERP solo devuelve sose_id 1 y 3 — el 2 fue removido del pedido.
    eliminadas = reconciliar_sale_order_serials(db, "sohID", soh, sose_ids_vigentes=[1, 3])

    assert eliminadas == 1
    restantes = {r.sose_id for r in db.query(TbSaleOrderSerial).filter_by(soh_id=soh)}
    assert restantes == {1, 3}


def test_reconcilia_por_is_id_borra_fantasma(db):
    """Una fila vieja del serial que ya no está en ningún pedido se elimina."""
    serial = 99
    _crear_fila(db, sose_id=1, is_id=serial, soh_id=500)  # fantasma
    _crear_fila(db, sose_id=2, is_id=serial, soh_id=600)  # vigente

    # El ERP devuelve solo la asignación vigente (sose_id=2).
    eliminadas = reconciliar_sale_order_serials(db, "isID", serial, sose_ids_vigentes=[2])

    assert eliminadas == 1
    restantes = {r.sose_id for r in db.query(TbSaleOrderSerial).filter_by(is_id=serial)}
    assert restantes == {2}


def test_guard_lista_vacia_no_borra_nada(db):
    """Respuesta vacía del ERP → no se borra nada (posible fetch fallido)."""
    soh = 500
    _crear_fila(db, sose_id=1, is_id=10, soh_id=soh)
    _crear_fila(db, sose_id=2, is_id=11, soh_id=soh)

    eliminadas = reconciliar_sale_order_serials(db, "sohID", soh, sose_ids_vigentes=[])

    assert eliminadas == 0
    assert db.query(TbSaleOrderSerial).filter_by(soh_id=soh).count() == 2


def test_filter_name_desconocido_no_borra(db):
    """Un filter_name fuera de los soportados no toca nada."""
    _crear_fila(db, sose_id=1, is_id=10, soh_id=500)

    eliminadas = reconciliar_sale_order_serials(db, "otherID", 500, sose_ids_vigentes=[99])

    assert eliminadas == 0
    assert db.query(TbSaleOrderSerial).count() == 1


def test_no_toca_otros_pedidos(db):
    """La reconciliación de un pedido no afecta otros pedidos."""
    _crear_fila(db, sose_id=1, is_id=10, soh_id=500)
    _crear_fila(db, sose_id=2, is_id=11, soh_id=500)
    _crear_fila(db, sose_id=10, is_id=20, soh_id=600)
    _crear_fila(db, sose_id=11, is_id=21, soh_id=600)

    eliminadas = reconciliar_sale_order_serials(db, "sohID", 500, sose_ids_vigentes=[1])

    assert eliminadas == 1
    assert {r.sose_id for r in db.query(TbSaleOrderSerial).filter_by(soh_id=600)} == {10, 11}
    assert {r.sose_id for r in db.query(TbSaleOrderSerial).filter_by(soh_id=500)} == {1}
