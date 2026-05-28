"""Tests de _validar_serial_core: el gate de disponibilidad del prearmador.

La validación decide por `tb_item_serials.is_available` (estado HOY), no por
si el serial estuvo alguna vez en una factura. La traza solo informa el "dónde"
cuando el serial está ocupado.
"""

from app.models.commercial_transaction import CommercialTransaction
from app.models.tb_item_serials import TbItemSerial
from app.models.tb_item_transaction_serials import TbItemTransactionSerial
from app.models.tb_sale_order_serial import TbSaleOrderSerial
from app.routers import prearmado


def _crear_serial(db, is_id: int = 1, item_id: int = 10, serial: str = "ABC123", is_available: bool = True):
    s = TbItemSerial(
        comp_id=1,
        is_id=is_id,
        bra_id=1,
        item_id=item_id,
        is_serial=serial,
        is_available=is_available,
    )
    db.add(s)
    db.flush()
    return s


def _crear_factura(db, is_id: int, ct_transaction: int = 5000, ct_soh_id: int = 777) -> None:
    """Deja al serial registrado en una factura emitida (traza histórica)."""
    db.add(CommercialTransaction(ct_transaction=ct_transaction, comp_id=1, bra_id=1, ct_soh_id=ct_soh_id))
    db.add(TbItemTransactionSerial(comp_id=1, bra_id=1, its_id=1, is_id=is_id, ct_transaction=ct_transaction))
    db.flush()


def _crear_sale_order(db, is_id: int, soh_id: int = 888) -> None:
    db.add(TbSaleOrderSerial(comp_id=1, bra_id=1, sose_id=1, is_id=is_id, soh_id=soh_id))
    db.flush()


def _refetch_no_llamar(is_id):
    raise AssertionError(f"refetch no debería llamarse (is_id={is_id})")


def test_serial_disponible_es_valido(db, monkeypatch):
    """is_available=True → válido, sin tocar el ERP."""
    monkeypatch.setattr(prearmado, "_refetch_serial_is_available", _refetch_no_llamar)
    _crear_serial(db, is_id=1, item_id=10, serial="ABC123", is_available=True)

    resp = prearmado._validar_serial_core(db, "ABC123", 10)

    assert resp.valid is True
    assert resp.motivo is None


def test_serial_facturado_pero_disponible_es_valido(db, monkeypatch):
    """Regresión: un serial que ESTUVO en una factura pero hoy está disponible
    (ej: se le hizo NC) es válido. La traza no debe bloquearlo."""
    monkeypatch.setattr(prearmado, "_refetch_serial_is_available", _refetch_no_llamar)
    _crear_serial(db, is_id=1, item_id=10, serial="ABC123", is_available=True)
    _crear_factura(db, is_id=1)

    resp = prearmado._validar_serial_core(db, "ABC123", 10)

    assert resp.valid is True
    assert resp.motivo is None


def test_serial_no_disponible_y_facturado(db, monkeypatch):
    """is_available=False y el ERP lo confirma → bloqueado, con la factura donde está."""
    monkeypatch.setattr(prearmado, "_refetch_serial_is_available", lambda is_id: False)
    _crear_serial(db, is_id=1, item_id=10, serial="ABC123", is_available=False)
    _crear_factura(db, is_id=1, ct_transaction=5000, ct_soh_id=777)

    resp = prearmado._validar_serial_core(db, "ABC123", 10)

    assert resp.valid is False
    assert resp.motivo == "AlreadyInvoiced"
    assert resp.usado_en_factura == 5000
    assert resp.usado_en_factura_soh_id == 777


def test_local_ocupado_pero_erp_lo_libera(db, monkeypatch):
    """is_available=False local pero el ERP (refetch) lo da libre → válido.
    El refetch cubre el is_available local desactualizado."""
    monkeypatch.setattr(prearmado, "_refetch_serial_is_available", lambda is_id: True)
    _crear_serial(db, is_id=1, item_id=10, serial="ABC123", is_available=False)
    _crear_factura(db, is_id=1)

    resp = prearmado._validar_serial_core(db, "ABC123", 10)

    assert resp.valid is True
    assert resp.motivo is None


def test_no_disponible_sin_rastro_de_factura(db, monkeypatch):
    """No disponible y sin rastro en facturas → NoDisponible."""
    monkeypatch.setattr(prearmado, "_refetch_serial_is_available", lambda is_id: False)
    _crear_serial(db, is_id=1, item_id=10, serial="ABC123", is_available=False)

    resp = prearmado._validar_serial_core(db, "ABC123", 10)

    assert resp.valid is False
    assert resp.motivo == "NoDisponible"


def test_no_disponible_con_erp_caido(db, monkeypatch):
    """Si el refetch falla (None), se cae al estado local: queda bloqueado."""
    monkeypatch.setattr(prearmado, "_refetch_serial_is_available", lambda is_id: None)
    _crear_serial(db, is_id=1, item_id=10, serial="ABC123", is_available=False)

    resp = prearmado._validar_serial_core(db, "ABC123", 10)

    assert resp.valid is False
    assert resp.motivo == "NoDisponible"


def test_is_available_none_se_verifica_contra_erp(db, monkeypatch):
    """is_available NULL local se trata como no-disponible y dispara el refetch;
    si el ERP lo da libre, el serial es válido."""
    monkeypatch.setattr(prearmado, "_refetch_serial_is_available", lambda is_id: True)
    _crear_serial(db, is_id=1, item_id=10, serial="ABC123", is_available=None)

    resp = prearmado._validar_serial_core(db, "ABC123", 10)

    assert resp.valid is True


def test_sale_order_pendiente_bloquea_aunque_este_disponible(db, monkeypatch):
    """El check de sale order pendiente sigue siendo un gate duro, antes del
    gate de disponibilidad — un serial en un pedido pendiente se bloquea cuando
    el ERP confirma que sigue asignado."""
    monkeypatch.setattr(prearmado, "_refetch_serial_is_available", _refetch_no_llamar)
    monkeypatch.setattr(prearmado, "_refetch_serial_sale_order", lambda is_id: (True, 888))
    _crear_serial(db, is_id=1, item_id=10, serial="ABC123", is_available=True)
    _crear_sale_order(db, is_id=1, soh_id=888)

    resp = prearmado._validar_serial_core(db, "ABC123", 10)

    assert resp.valid is False
    assert resp.motivo == "AlreadyInSaleOrder"
    assert resp.usado_en_soh_id == 888


def test_sale_order_local_pero_erp_dice_no_es_valido(db, monkeypatch):
    """Regresión: si la fila local de sale_order_serials es un fantasma (el ERP
    ya no la tiene), no se bloquea. Es el bug del sync upsert-only para pedidos.
    Se mockea también el refetch de is_available para asegurar que el happy path
    no toca el ERP — si lo hace, la lógica cambió y este test debe revisarse."""
    monkeypatch.setattr(prearmado, "_refetch_serial_sale_order", lambda is_id: (False, None))
    monkeypatch.setattr(prearmado, "_refetch_serial_is_available", _refetch_no_llamar)
    _crear_serial(db, is_id=1, item_id=10, serial="ABC123", is_available=True)
    _crear_sale_order(db, is_id=1, soh_id=888)  # fila local fantasma

    resp = prearmado._validar_serial_core(db, "ABC123", 10)

    assert resp.valid is True
    assert resp.motivo is None


def test_sale_order_refetch_falla_cae_a_local(db, monkeypatch):
    """Si el refetch del sale order falla (None), se respeta el bloqueo local
    con el soh_id que tenemos guardado."""
    monkeypatch.setattr(prearmado, "_refetch_serial_sale_order", lambda is_id: (None, None))
    _crear_serial(db, is_id=1, item_id=10, serial="ABC123", is_available=True)
    _crear_sale_order(db, is_id=1, soh_id=888)

    resp = prearmado._validar_serial_core(db, "ABC123", 10)

    assert resp.valid is False
    assert resp.motivo == "AlreadyInSaleOrder"
    assert resp.usado_en_soh_id == 888


def test_sale_order_erp_devuelve_soh_id_fresco(db, monkeypatch):
    """Si el ERP confirma el bloqueo y devuelve un soh_id distinto al local
    (serial movido entre pedidos), reportamos el fresco del ERP."""
    monkeypatch.setattr(prearmado, "_refetch_serial_sale_order", lambda is_id: (True, 999))
    _crear_serial(db, is_id=1, item_id=10, serial="ABC123", is_available=True)
    _crear_sale_order(db, is_id=1, soh_id=888)  # local desactualizado

    resp = prearmado._validar_serial_core(db, "ABC123", 10)

    assert resp.valid is False
    assert resp.motivo == "AlreadyInSaleOrder"
    assert resp.usado_en_soh_id == 999


def test_serial_inexistente(db, monkeypatch):
    """Un serial que no existe en tb_item_serials → SerialNotFound."""
    monkeypatch.setattr(prearmado, "_refetch_serial_is_available", _refetch_no_llamar)

    resp = prearmado._validar_serial_core(db, "NO-EXISTE", 10)

    assert resp.valid is False
    assert resp.motivo == "SerialNotFound"


def test_item_mismatch(db, monkeypatch):
    """El serial existe pero pertenece a otro item → ItemMismatch."""
    monkeypatch.setattr(prearmado, "_refetch_serial_is_available", _refetch_no_llamar)
    _crear_serial(db, is_id=1, item_id=99, serial="ABC123", is_available=True)

    resp = prearmado._validar_serial_core(db, "ABC123", 10)

    assert resp.valid is False
    assert resp.motivo == "ItemMismatch"
    assert resp.item_id_real == 99
