"""Tests de reconciliación por combo en sync_item_associations.

Cubre `reconciliar_asociaciones_combo`: borrar componentes fantasma de un combo
modificado en el ERP, el guard de respuesta vacía y el aislamiento entre combos.
"""

from app.models.tb_item_association import TbItemAssociation
from app.scripts.sync_item_associations import reconciliar_asociaciones_combo


def _crear_asociacion(db, itema_id: int, item_id: int, item_id_1: int) -> None:
    db.add(
        TbItemAssociation(
            comp_id=1,
            itema_id=itema_id,
            item_id=item_id,
            item_id_1=item_id_1,
            iasso_qty=1,
        )
    )
    db.flush()


def test_borra_asociacion_fantasma(db):
    """Una asociación local que el ERP ya no devuelve se elimina."""
    combo = 100
    _crear_asociacion(db, itema_id=1, item_id=combo, item_id_1=500)  # mother viejo
    _crear_asociacion(db, itema_id=2, item_id=combo, item_id_1=600)  # gabinete
    _crear_asociacion(db, itema_id=3, item_id=combo, item_id_1=501)  # mother nuevo

    # El ERP solo devuelve gabinete y mother nuevo: el viejo (itema_id=1) se borró.
    eliminadas = reconciliar_asociaciones_combo(db, combo, itema_ids_vigentes=[2, 3])

    assert eliminadas == 1
    restantes = {a.itema_id for a in db.query(TbItemAssociation).filter_by(item_id=combo)}
    assert restantes == {2, 3}


def test_guard_lista_vacia_no_borra_nada(db):
    """Si el ERP no devuelve asociaciones (posible fetch fallido), no se borra nada."""
    combo = 100
    _crear_asociacion(db, itema_id=1, item_id=combo, item_id_1=500)
    _crear_asociacion(db, itema_id=2, item_id=combo, item_id_1=600)

    eliminadas = reconciliar_asociaciones_combo(db, combo, itema_ids_vigentes=[])

    assert eliminadas == 0
    assert db.query(TbItemAssociation).filter_by(item_id=combo).count() == 2


def test_no_toca_otros_combos(db):
    """La reconciliación de un combo no afecta las asociaciones de otro."""
    combo_a, combo_b = 100, 200
    _crear_asociacion(db, itema_id=1, item_id=combo_a, item_id_1=500)
    _crear_asociacion(db, itema_id=2, item_id=combo_a, item_id_1=600)
    _crear_asociacion(db, itema_id=10, item_id=combo_b, item_id_1=700)
    _crear_asociacion(db, itema_id=11, item_id=combo_b, item_id_1=800)

    # Reconciliamos el combo A dejando vigente solo itema_id=1.
    eliminadas = reconciliar_asociaciones_combo(db, combo_a, itema_ids_vigentes=[1])

    assert eliminadas == 1
    assert {a.itema_id for a in db.query(TbItemAssociation).filter_by(item_id=combo_b)} == {10, 11}
    assert {a.itema_id for a in db.query(TbItemAssociation).filter_by(item_id=combo_a)} == {1}


def test_sin_fantasmas_no_borra(db):
    """Si todas las asociaciones locales siguen vigentes, no se borra nada."""
    combo = 100
    _crear_asociacion(db, itema_id=1, item_id=combo, item_id_1=500)
    _crear_asociacion(db, itema_id=2, item_id=combo, item_id_1=600)

    eliminadas = reconciliar_asociaciones_combo(db, combo, itema_ids_vigentes=[1, 2])

    assert eliminadas == 0
    assert db.query(TbItemAssociation).filter_by(item_id=combo).count() == 2
