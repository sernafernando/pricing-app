"""
erp_matching_service — matching bidireccional pedido_compra ↔ factura ERP.

Responsabilidad: vincular filas de `tb_commercial_transactions` (sincronizadas
desde el ERP externo) con `pedidos_compra` del módulo propio, usando como
llave la tupla `(comp_id, bra_id, supp_id, ct_docnumber)` filtrada por la
vista `v_facturas_compra_vigentes` (design §4.1).

Dos modos:
  - `match_forward`  — pedido → factura. Se invoca cuando un usuario carga
    `numero_factura` a un pedido ya aprobado y queremos saber si esa factura
    ya existe en el ERP.
  - `match_backward` — factura → pedido. Se invoca desde el hook inline del
    cron `sync_commercial_transactions_guid.py` (design §5) después de
    ingestar ct nuevos, para asociarlos con pedidos que habían quedado
    esperando factura.

Reglas de seguridad (críticas para un matching sobre plata real):
  - Nunca pisa un `ct_transaction_id` ya seteado. Si hay conflicto, loggea
    y saltea ese pedido/ct (semántica: el primer matcheo gana).
  - Nunca cruza empresas: traducción `empresa_id ↔ (comp_id, bra_id)` via
    `resolver_comp_bra` (`backend/app/core/compras_empresa_erp_map.py`).
  - El pre-check defensivo `validar_catalogo_populado` asegura que
    `tb_sale_document` esté seeded — si está vacío, la vista filtra TODO
    (no hay `sd_isannulment` para comparar) y el matcheo produciría
    silenciosamente 0 asociaciones. Abortamos ruidoso.

Referencias:
  - design.md §2.5, §4.1, §5
  - tasks.md COMPRAS-2.7 (esqueleto) y COMPRAS-3.5 (implementación)
  - Engram #117 (design), #125 (bug clasificador conocido, no bloquea acá)
"""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.compras_empresa_erp_map import resolver_comp_bra
from app.core.logging import get_logger
from app.models.compra_evento import CompraEvento
from app.models.pedido_compra import PedidoCompra
from app.models.proveedor import Proveedor

logger = get_logger("services.erp_matching_service")


# ──────────────────────────────────────────────────────────────────────────
# Pre-check defensivo
# ──────────────────────────────────────────────────────────────────────────


def validar_catalogo_populado(session: Session) -> None:
    """
    Pre-check para el hook del sync: `tb_sale_document` DEBE tener filas.

    Razón: la vista `v_facturas_compra_vigentes` hace `JOIN tb_sale_document`
    en la CTE `anuladas` y en `base`. Si el catálogo está vacío, el JOIN no
    produce filas, `anuladas` queda vacía, `base` queda vacía y `match_backward`
    retorna 0 asociaciones sin ninguna señal de error. Es peor que fallar:
    queda oculto hasta que alguien se dé cuenta de que los pedidos no se
    matchean hace días.

    Este check corre ANTES del matching y levanta `RuntimeError` ruidoso
    (no HTTPException — esto no es un endpoint). El caller (hook del sync)
    lo captura en su try/except, loggea y notifica al admin, pero deja que
    el sync base siga funcionando.

    Args:
        session: sesión SQLAlchemy.

    Raises:
        RuntimeError: si `tb_sale_document` está vacío.
    """
    count = session.execute(text("SELECT COUNT(*) FROM tb_sale_document")).scalar_one()
    if count == 0:
        raise RuntimeError(
            "ABORT matching: tb_sale_document está vacío. "
            "Aplicar seed (migración compras_009_seed_tb_sale_document) "
            "antes de correr el hook de matching ERP ↔ pedidos."
        )


# ──────────────────────────────────────────────────────────────────────────
# Helpers internos
# ──────────────────────────────────────────────────────────────────────────


def _resolver_supp_id(session: Session, proveedor_id: int) -> Optional[int]:
    """Traduce `proveedor_id` local a `supp_id` del ERP (nullable)."""
    supp_id = session.execute(
        text("SELECT supp_id FROM proveedores WHERE id = :pid"),
        {"pid": proveedor_id},
    ).scalar_one_or_none()
    return int(supp_id) if supp_id is not None else None


def _buscar_ct_vigente(
    session: Session,
    *,
    comp_id: int,
    bra_id: int,
    supp_id: int,
    ct_docnumber: str,
) -> Optional[int]:
    """
    Busca en `v_facturas_compra_vigentes` una ct única para la tupla.

    Returns:
        `ct_transaction` si hay match único; `None` si hay 0 o >1 coincidencias
        (en caso ambiguo, el caller decide; por ahora, no se auto-asocia).
    """
    stmt = text(
        """
        SELECT ct_transaction
        FROM v_facturas_compra_vigentes
        WHERE comp_id = :comp_id
          AND bra_id = :bra_id
          AND supp_id = :supp_id
          AND ct_docnumber = :ct_docnumber
        LIMIT 2
        """
    )
    filas = session.execute(
        stmt,
        {
            "comp_id": comp_id,
            "bra_id": bra_id,
            "supp_id": supp_id,
            "ct_docnumber": ct_docnumber,
        },
    ).all()
    if len(filas) != 1:
        return None
    return int(filas[0][0])


def _registrar_evento_match(
    session: Session,
    *,
    pedido: PedidoCompra,
    ct_transaction: int,
    origen: str,
    usuario_id: Optional[int] = None,
) -> None:
    """
    Inserta evento `matcheado_con_erp` en `compras_eventos`.

    `origen` es `'forward'` (manual) o `'backward'` (hook del sync).
    `usuario_id` es nullable en esta tabla? NO — es NOT NULL. Para runs
    del sistema usamos el creador del pedido como proxy de auditoría
    (el que inició la cadena).
    """
    payload: dict[str, Any] = {
        "ct_transaction": ct_transaction,
        "modo": origen,
        "numero_factura": pedido.numero_factura,
    }
    evento = CompraEvento(
        entidad_tipo=CompraEvento.ENTIDAD_TIPO_PEDIDO,
        entidad_id=pedido.id,
        tipo="matcheado_con_erp",
        usuario_id=usuario_id if usuario_id is not None else pedido.creado_por_id,
        payload=payload,
    )
    session.add(evento)


# ──────────────────────────────────────────────────────────────────────────
# Operaciones públicas
# ──────────────────────────────────────────────────────────────────────────


def match_forward(
    session: Session,
    *,
    pedido_compra_id: int,
    usuario_id: Optional[int] = None,
) -> Optional[int]:
    """
    Pedido → Factura.

    Dado un pedido con `numero_factura` cargado y sin `ct_transaction_id`,
    busca en `v_facturas_compra_vigentes` una ct que matchee con la tupla
    `(comp_id, bra_id, supp_id, ct_docnumber)` calculada a partir de
    `pedido.empresa_id` + `pedido.proveedor_id.supp_id` + `pedido.numero_factura`.

    Si hay match único:
        - setea `pedido.ct_transaction_id = ct.ct_transaction`
        - inserta evento `'matcheado_con_erp'` en `compras_eventos`

    NO commitea. Responsabilidad del caller.

    Args:
        session: tx activa del caller.
        pedido_compra_id: PK del pedido a matchear.
        usuario_id: opcional, para auditoría del evento. Si None, usa
            `pedido.creado_por_id`.

    Returns:
        `ct_transaction` (BIGINT) si matcheó; `None` si no encontró o si el
        pedido no cumple precondiciones (sin numero_factura, ya matcheado,
        proveedor sin supp_id, empresa no mapeada).

    Raises:
        ValueError: si `pedido_compra_id` no existe.
    """
    pedido = session.get(PedidoCompra, pedido_compra_id)
    if pedido is None:
        raise ValueError(f"pedido_compra_id={pedido_compra_id} no existe.")

    # Precondiciones
    if pedido.ct_transaction_id is not None:
        logger.debug(
            "match_forward: pedido_id=%s ya tiene ct_transaction_id=%s — skip",
            pedido.id,
            pedido.ct_transaction_id,
        )
        return None
    if not pedido.numero_factura:
        logger.debug("match_forward: pedido_id=%s sin numero_factura — skip", pedido.id)
        return None

    # Traducción empresa_id → (comp_id, bra_id)
    try:
        comp_id, bra_id = resolver_comp_bra(pedido.empresa_id)
    except KeyError:
        logger.warning(
            "match_forward: pedido_id=%s empresa_id=%s sin mapeo ERP — skip",
            pedido.id,
            pedido.empresa_id,
        )
        return None

    # proveedor_id → supp_id
    supp_id = _resolver_supp_id(session, pedido.proveedor_id)
    if supp_id is None:
        logger.warning(
            "match_forward: pedido_id=%s proveedor_id=%s sin supp_id ERP — skip",
            pedido.id,
            pedido.proveedor_id,
        )
        return None

    # Match via vista
    ct_transaction = _buscar_ct_vigente(
        session,
        comp_id=comp_id,
        bra_id=bra_id,
        supp_id=supp_id,
        ct_docnumber=pedido.numero_factura,
    )
    if ct_transaction is None:
        logger.info(
            "match_forward: pedido_id=%s sin match vigente para (%s,%s,%s,%s)",
            pedido.id,
            comp_id,
            bra_id,
            supp_id,
            pedido.numero_factura,
        )
        return None

    pedido.ct_transaction_id = ct_transaction
    _registrar_evento_match(
        session,
        pedido=pedido,
        ct_transaction=ct_transaction,
        origen="forward",
        usuario_id=usuario_id,
    )
    session.flush()

    logger.info(
        "match_forward: pedido_id=%s ↔ ct_transaction=%s (modo=forward)",
        pedido.id,
        ct_transaction,
    )
    return ct_transaction


def match_backward(
    session: Session,
    *,
    cts_synced: list[int],
) -> dict[str, int]:
    """
    Factura → Pedido. Invocado desde el hook inline del sync (design §5).

    Para cada `ct_transaction` recién sincronizado:
      1. Valida que esté "vigente" (existe en `v_facturas_compra_vigentes`
         → no es anulación ni contraparte ni remito).
      2. Busca un `pedido_compra` tal que:
         - `pedido.numero_factura = ct.ct_docnumber`
         - `pedido.proveedor_id → supp_id = ct.supp_id`
         - `pedido.empresa_id → (comp_id, bra_id) = (ct.comp_id, ct.bra_id)`
         - `pedido.ct_transaction_id IS NULL` (no pisa matchings previos)
      3. Si hay match único → asocia + registra evento.

    El hook del sync guarda `cts_synced` como lista de `ct_transaction`
    procesados (INSERT + UPDATE). Puede ser grande — una ventana de sync
    típica son 100-500 ids.

    Args:
        session: tx activa del caller.
        cts_synced: lista de `ct_transaction` (BIGINT) recién ingestados.

    Returns:
        dict con keys:
          - `cts_procesadas`: total de ids recibidos (= len(cts_synced))
          - `pedidos_asociados`: cuántos pedidos matchearon
          - `errores`: errores no fatales (logs) — excepciones por ct individual

    Raises:
        RuntimeError: via `validar_catalogo_populado` si `tb_sale_document`
            está vacío. El caller (hook) captura y loggea.
    """
    validar_catalogo_populado(session)

    resumen = {
        "cts_procesadas": len(cts_synced),
        "pedidos_asociados": 0,
        "errores": 0,
    }
    if not cts_synced:
        return resumen

    # Query SQL que junta la vista con datos de la ct y busca el pedido
    # candidato. Hacemos 1 round-trip por ct (simple y auditable); si el
    # volumen crece, se puede batchear con `WHERE ct_transaction IN (...)`.
    stmt_vista = text(
        """
        SELECT v.ct_transaction, v.comp_id, v.bra_id, v.supp_id, v.ct_docnumber
        FROM v_facturas_compra_vigentes v
        WHERE v.ct_transaction = :ct
        """
    )

    for ct_id in cts_synced:
        try:
            fila = session.execute(stmt_vista, {"ct": ct_id}).first()
            if fila is None:
                # ct no está en la vista → es anulación, contraparte, remito,
                # etc. NO hay pedido que matchear. Es normal, no es error.
                continue

            ct_transaction, comp_id, bra_id, supp_id, ct_docnumber = fila

            # Buscar pedido candidato
            pedido: Optional[PedidoCompra] = (
                session.query(PedidoCompra)
                .join(Proveedor, Proveedor.id == PedidoCompra.proveedor_id)
                .filter(
                    PedidoCompra.numero_factura == ct_docnumber,
                    PedidoCompra.ct_transaction_id.is_(None),
                    Proveedor.supp_id == supp_id,
                )
                .first()
            )
            if pedido is None:
                continue

            # Validar mapeo empresa → (comp_id, bra_id) coincide con la ct
            try:
                empresa_comp, empresa_bra = resolver_comp_bra(pedido.empresa_id)
            except KeyError:
                logger.warning(
                    "match_backward: pedido_id=%s empresa_id=%s sin mapeo ERP — skip",
                    pedido.id,
                    pedido.empresa_id,
                )
                continue
            if (empresa_comp, empresa_bra) != (int(comp_id), int(bra_id)):
                logger.warning(
                    "match_backward: pedido_id=%s empresa %s mapea (%s,%s) pero ct=%s tiene (%s,%s) — skip",
                    pedido.id,
                    pedido.empresa_id,
                    empresa_comp,
                    empresa_bra,
                    ct_transaction,
                    comp_id,
                    bra_id,
                )
                continue

            pedido.ct_transaction_id = int(ct_transaction)
            _registrar_evento_match(
                session,
                pedido=pedido,
                ct_transaction=int(ct_transaction),
                origen="backward",
            )
            resumen["pedidos_asociados"] += 1
            logger.info(
                "match_backward: pedido_id=%s ↔ ct_transaction=%s (modo=backward)",
                pedido.id,
                ct_transaction,
            )

        except Exception as exc:  # noqa: BLE001 — queremos capturar TODO por ct
            resumen["errores"] += 1
            logger.exception(
                "match_backward: error procesando ct_transaction=%s: %s",
                ct_id,
                exc,
            )
            continue

    session.flush()
    return resumen


__all__ = [
    "match_backward",
    "match_forward",
    "validar_catalogo_populado",
]
