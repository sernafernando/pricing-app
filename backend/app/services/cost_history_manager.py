"""
Servicio para gestionar el historial de costos de productos.
Crea registros automáticamente cuando se actualiza el costo en productos_erp.
"""

from datetime import datetime
from sqlalchemy.orm import Session
from app.models.item_cost_list_history import ItemCostListHistory
from app.models.producto import ProductoERP
import logging

logger = logging.getLogger(__name__)


def crear_registro_historial_costo(
    db: Session, item_id: int, costo: float, moneda_costo: str, user_id: int = None
) -> ItemCostListHistory:
    """
    Crea un registro en item_cost_list_history para trackear cambios de costo.

    Args:
        db: Sesión de base de datos
        item_id: ID del item
        costo: Nuevo costo
        moneda_costo: Moneda ('ARS' o 'USD')
        user_id: ID del usuario que hizo el cambio (opcional)

    Returns:
        El registro creado
    """
    # Obtener el último iclh_id para generar el siguiente
    last_record = db.query(ItemCostListHistory).order_by(ItemCostListHistory.iclh_id.desc()).first()

    next_iclh_id = (last_record.iclh_id + 1) if last_record else 1

    # Mapear moneda a curr_id (1=ARS, 2=USD)
    curr_id = 2 if moneda_costo == "USD" else 1

    # Crear registro
    nuevo_registro = ItemCostListHistory(
        iclh_id=next_iclh_id,
        comp_id=1,  # Empresa por defecto
        coslis_id=1,  # Lista de costos principal
        item_id=item_id,
        iclh_lote=None,
        iclh_price=costo,
        iclh_price_aw=None,
        curr_id=curr_id,
        iclh_cd=datetime.now(),
        user_id_lastupdate=user_id,
    )

    db.add(nuevo_registro)
    db.flush()  # Para obtener el ID sin hacer commit

    logger.info(
        f"Registro de historial creado: item_id={item_id}, costo={costo}, moneda={moneda_costo}, iclh_id={next_iclh_id}"
    )

    return nuevo_registro


def actualizar_costo_con_historial(
    db: Session, item_id: int, nuevo_costo: float, moneda_costo: str, user_id: int = None, commit: bool = True
) -> tuple[ProductoERP, ItemCostListHistory]:
    """
    Actualiza el costo de un producto y crea registro en historial.

    Args:
        db: Sesión de base de datos
        item_id: ID del item
        nuevo_costo: Nuevo costo
        moneda_costo: Moneda ('ARS' o 'USD')
        user_id: ID del usuario que hizo el cambio (opcional)
        commit: Si debe hacer commit automáticamente

    Returns:
        Tupla con (producto_actualizado, registro_historial)
    """
    # Obtener producto
    producto = db.query(ProductoERP).filter(ProductoERP.item_id == item_id).first()

    if not producto:
        raise ValueError(f"Producto no encontrado: item_id={item_id}")

    # Verificar si cambió el costo
    costo_anterior = float(producto.costo) if producto.costo else 0
    moneda_anterior = producto.moneda_costo.value if producto.moneda_costo else "ARS"

    if costo_anterior != nuevo_costo or moneda_anterior != moneda_costo:
        logger.info(
            f"Actualizando costo: item_id={item_id}, {moneda_anterior} ${costo_anterior} -> {moneda_costo} ${nuevo_costo}"
        )

        # Actualizar producto
        producto.costo = nuevo_costo
        producto.moneda_costo = moneda_costo

        # Crear registro en historial solo si el costo es > 0
        historial = None
        if nuevo_costo > 0:
            historial = crear_registro_historial_costo(
                db=db, item_id=item_id, costo=nuevo_costo, moneda_costo=moneda_costo, user_id=user_id
            )

        if commit:
            db.commit()
            db.refresh(producto)
            if historial:
                db.refresh(historial)

        return (producto, historial)
    else:
        logger.debug(f"Sin cambios en costo para item_id={item_id}")
        return (producto, None)


def sincronizar_costos_faltantes(db: Session, commit: bool = True) -> int:
    """
    Sincroniza productos que tienen costo en productos_erp pero no en item_cost_list_history.
    Útil para productos combos o especiales que no vienen del ERP.

    Args:
        db: Sesión de base de datos
        commit: Si debe hacer commit automáticamente

    Returns:
        Cantidad de registros creados
    """
    logger.info("=== Sincronizando costos faltantes ===")

    # Obtener productos con costo > 0
    productos_con_costo = db.query(ProductoERP).filter(ProductoERP.costo > 0, ProductoERP.activo == True).all()

    logger.info(f"Productos con costo > 0: {len(productos_con_costo)}")

    registros_creados = 0

    for producto in productos_con_costo:
        # Verificar si tiene historial
        tiene_historial = (
            db.query(ItemCostListHistory)
            .filter(
                ItemCostListHistory.item_id == producto.item_id,
                ItemCostListHistory.coslis_id == 1,
                ItemCostListHistory.iclh_price > 0,
            )
            .first()
        )

        if not tiene_historial:
            logger.info(f"Producto sin historial: item_id={producto.item_id}, codigo={producto.codigo}")

            # Crear registro
            moneda = producto.moneda_costo.value if producto.moneda_costo else "ARS"
            crear_registro_historial_costo(
                db=db, item_id=producto.item_id, costo=float(producto.costo), moneda_costo=moneda, user_id=None
            )
            registros_creados += 1

    if commit:
        db.commit()

    logger.info(f"✅ Registros de historial creados: {registros_creados}")
    return registros_creados
