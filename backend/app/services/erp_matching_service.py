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

from datetime import datetime
from decimal import Decimal
from typing import Any, Final, Optional

from fastapi import HTTPException
from sqlalchemy import Date, text
from sqlalchemy.orm import Session, joinedload

from app.core.compras_empresa_erp_map import resolver_comp_bra
from app.core.logging import get_logger
from app.models.compra_evento import CompraEvento
from app.models.notificacion import (
    EstadoNotificacion,
    SeveridadNotificacion,
)
from app.models.pedido_compra import PedidoCompra
from app.models.proveedor import Proveedor
from app.services.notificacion_service import crear_notificaciones_para_permisos

logger = get_logger("services.erp_matching_service")


# ──────────────────────────────────────────────────────────────────────────
# Permisos de destinatarios de alertas del matching
# ──────────────────────────────────────────────────────────────────────────
#
# Las alertas `compras.pedido_monto_difiere_factura` y
# `compras.nc_monto_difiere_factura` requieren acción correctiva
# (ajuste de monto o vinculación manual). Los usuarios que pueden
# actuar son los que tienen permisos de gestión de OPs o de
# cuentas corrientes. Reemplaza el antipatrón previo
# `Notificacion(user_id=None)` que no era visible para nadie.
PERMISOS_NOTIF_MATCHING: list[str] = [
    "administracion.gestionar_ordenes_compra",
    "administracion.ver_cuentas_corrientes",
]


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


# Outcomes persisted on PedidoFacturaDocumento.auto_vinculo_estado.
AUTO_VINCULO_OK: Final[str] = "ok"
AUTO_VINCULO_SIN_MATCH: Final[str] = "sin_match"
AUTO_VINCULO_AMBIGUO: Final[str] = "ambiguo"
AUTO_VINCULO_SIN_MAPEO: Final[str] = "sin_mapeo"
AUTO_VINCULO_PENDIENTES: Final[frozenset[str]] = frozenset(
    {AUTO_VINCULO_SIN_MATCH, AUTO_VINCULO_AMBIGUO, AUTO_VINCULO_SIN_MAPEO}
)


def _buscar_ct_vigente(
    session: Session,
    *,
    comp_id: int,
    bra_id: int,
    supp_id: int,
    ct_docnumber: str,
) -> tuple[Optional[int], str]:
    """
    Busca en `v_facturas_compra_vigentes` una ct única para la tupla.

    Returns:
        `(ct_transaction, "ok")` if unique; `(None, "sin_match"|"ambiguo")`
        when 0 or >1 rows (caller must not auto-link).
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
    if len(filas) == 0:
        return None, AUTO_VINCULO_SIN_MATCH
    if len(filas) > 1:
        return None, AUTO_VINCULO_AMBIGUO
    return int(filas[0][0]), AUTO_VINCULO_OK


def _alertar_si_monto_difiere(
    session: Session,
    *,
    pedido: PedidoCompra,
    ct_transaction: int,
    ct_docnumber: str,
    ct_total: Decimal,
) -> None:
    """
    Batch I — Q3: al matchear pedido ↔ factura ERP, si los montos difieren,
    NO ajusta silenciosamente. Registra:

      1) Evento `monto_difiere_al_matchear` en `compras_eventos` con payload
         `{ct_transaction, ct_total_erp, monto_pedido, diferencia}`.
      2) Notificación con severidad WARNING para que el admin revise.
      3) Log WARNING.

    El admin puede aplicar el ajuste manualmente vía `ajustar_monto_con_factura`
    (endpoint dedicado con permiso `administracion.ajustar_monto_pedido`).

    Razón: la diferencia puede deberse a múltiples causas (variación de TC al
    pagar, ajuste de cantidades, descuento tardío del proveedor, diferencia
    impositiva) y cada una requiere distinto tratamiento contable. Ajustar
    automáticamente ocultaría el problema.
    """
    if ct_total is None:
        return
    monto_pedido = Decimal(str(pedido.monto))
    diferencia = ct_total - monto_pedido
    # Tolerancia: si la diferencia es de menos de 1 centavo, no alertamos.
    if abs(diferencia) < Decimal("0.01"):
        return

    # Evento (apuntado a quien creó el pedido, porque el match viene del sync).
    evento_mismatch = CompraEvento(
        entidad_tipo=CompraEvento.ENTIDAD_TIPO_PEDIDO,
        entidad_id=pedido.id,
        tipo="monto_difiere_al_matchear",
        usuario_id=pedido.creado_por_id,
        payload={
            "ct_transaction": int(ct_transaction),
            "ct_docnumber": ct_docnumber,
            "ct_total_erp": str(ct_total),
            "monto_pedido": str(monto_pedido),
            "diferencia": str(diferencia),
            "origen": "match_backward",
        },
    )
    session.add(evento_mismatch)

    # Notificación WARNING fan-out a admins con permisos de gestión de OPs
    # o CC (una fila por destinatario, para que el filtro del endpoint
    # `GET /notificaciones` -filtro estricto `user_id=current_user.id`- la
    # muestre). Si no hay destinatarios, el helper loggea WARNING.
    crear_notificaciones_para_permisos(
        session,
        permisos_requeridos=PERMISOS_NOTIF_MATCHING,
        tipo="compras.pedido_monto_difiere_factura",
        mensaje=(
            f"El pedido {pedido.numero} fue vinculado automáticamente a la factura "
            f"{ct_docnumber} (ct={ct_transaction}) pero el monto difiere: "
            f"pedido={monto_pedido} vs factura={ct_total} "
            f"(diferencia={diferencia}). Revisá y ajustá si corresponde."
        ),
        severidad=SeveridadNotificacion.WARNING,
        estado=EstadoNotificacion.PENDIENTE,
        item_id=pedido.id,
    )

    logger.warning(
        "match_backward MISMATCH monto pedido_id=%s ct=%s pedido=%s vs erp=%s (dif=%s)",
        pedido.id,
        ct_transaction,
        monto_pedido,
        ct_total,
        diferencia,
    )


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


# `ct_date` is the ERP's naive wall-clock document date (stored as parsed, no
# zone), so its date part is the invoice date as-is; no UTC→local shift.
# `date(...)` works in Postgres and SQLite; `.columns` types the SQLite string.
_FECHA_FACTURA_SQL = text(
    "SELECT date(ct_date) AS fecha FROM v_facturas_compra_vigentes WHERE ct_transaction = :ct"
).columns(fecha=Date)


def _seed_factura_junction_from_header(session: Session, pedido: PedidoCompra) -> None:
    """If header has a CT but junction is empty, materialize the first-link row."""
    from app.models.pedido_compra_factura import PedidoCompraFactura  # noqa: PLC0415

    if pedido.id is None or getattr(pedido, "ct_transaction_id", None) is None:
        return
    has_row = session.query(PedidoCompraFactura.id).filter(PedidoCompraFactura.pedido_id == pedido.id).first()
    if has_row is not None:
        return
    session.add(
        PedidoCompraFactura(
            pedido_id=pedido.id,
            ct_transaction_id=int(pedido.ct_transaction_id),
            fecha_factura=getattr(pedido, "fecha_factura", None),
        )
    )
    session.flush()


def _sync_header_factura_cache(session: Session, pedido: PedidoCompra) -> None:
    """Refresh header first-link cache from junction rows only (never header fallback)."""
    from app.models.pedido_compra_factura import PedidoCompraFactura  # noqa: PLC0415

    rows = (
        session.query(PedidoCompraFactura)
        .filter(PedidoCompraFactura.pedido_id == pedido.id)
        .order_by(PedidoCompraFactura.id)
        .all()
    )
    if rows:
        pedido.ct_transaction_id = int(rows[0].ct_transaction_id)
        pedido.fecha_factura = rows[0].fecha_factura
    else:
        pedido.ct_transaction_id = None
        pedido.fecha_factura = None


def _pedido_ids_for_ct(session: Session, ct_transaction: int) -> list[int]:
    """Pedidos that documentally own this CT (junction SoT ∪ header cache)."""
    from app.models.pedido_compra_factura import PedidoCompraFactura  # noqa: PLC0415

    ids = {
        int(pid)
        for (pid,) in session.query(PedidoCompraFactura.pedido_id)
        .filter(PedidoCompraFactura.ct_transaction_id == int(ct_transaction))
        .all()
    }
    ids.update(
        int(pid)
        for (pid,) in session.query(PedidoCompra.id).filter(PedidoCompra.ct_transaction_id == int(ct_transaction)).all()
    )
    return sorted(ids)


def copiar_facturas_erp(session: Session, *, origen_id: int, destino_id: int) -> int:
    """Copy junction invoice links from origen to destino; refresh destino header.

    Seeds origen from its header if the junction is still empty. Does not touch
    origen rows or sell-in. Returns how many links were copied. NO commit.
    """
    from app.models.pedido_compra_factura import PedidoCompraFactura  # noqa: PLC0415

    origen = session.get(PedidoCompra, origen_id)
    destino = session.get(PedidoCompra, destino_id)
    if origen is None or destino is None:
        return 0
    _seed_factura_junction_from_header(session, origen)
    n = 0
    for row in (
        session.query(PedidoCompraFactura)
        .filter(PedidoCompraFactura.pedido_id == origen_id)
        .order_by(PedidoCompraFactura.id)
        .all()
    ):
        exists = (
            session.query(PedidoCompraFactura.id)
            .filter(
                PedidoCompraFactura.pedido_id == destino_id,
                PedidoCompraFactura.ct_transaction_id == int(row.ct_transaction_id),
            )
            .first()
        )
        if exists is not None:
            continue
        session.add(
            PedidoCompraFactura(
                pedido_id=destino_id,
                ct_transaction_id=int(row.ct_transaction_id),
                fecha_factura=row.fecha_factura,
            )
        )
        n += 1
    session.flush()
    _sync_header_factura_cache(session, destino)
    return n


def _aplicar_sell_in_por_ct(session: Session, ct_transaction: int) -> None:
    """Reconcile sell-in for every pedido that owns this CT.

    Exclusivity is decided per CT inside `reconciliar_lineas_facturadas`
    (`_DOCUMENTOS_SQL`): shared CTs drop out of the snapshot, exclusive ones
    stay. Never wipe all lines of a pedido that still has other exclusive CTs.
    """
    for pid in _pedido_ids_for_ct(session, ct_transaction):
        reconciliar_lineas_facturadas(session, pid)


def asignar_factura_erp(session: Session, pedido: PedidoCompra, ct_transaction: Optional[int]) -> None:
    """Write path for ERP invoice links (M:N junction + header first-link cache).

    `ct_transaction` set: add a junction row if missing; refresh header cache;
    sell-in snapshot only when that CT is linked to exactly one pedido.
    `ct_transaction` None: remove every junction row for the pedido, clear
    header, and drop its sell-in lines. A ct missing from
    `v_facturas_compra_vigentes` still links, with `fecha_factura` NULL.
    NO commit.
    """
    from app.models.pedido_compra_factura import PedidoCompraFactura  # noqa: PLC0415

    if pedido.id is None:
        session.flush()

    if ct_transaction is None:
        session.query(PedidoCompraFactura).filter(PedidoCompraFactura.pedido_id == pedido.id).delete(
            synchronize_session=False
        )
        pedido.ct_transaction_id = None
        pedido.fecha_factura = None
        if pedido.id is not None:
            _borrar_lineas(session, pedido.id)
        return

    _seed_factura_junction_from_header(session, pedido)
    ct = int(ct_transaction)
    fecha = session.execute(_FECHA_FACTURA_SQL, {"ct": ct}).scalar()
    exists = (
        session.query(PedidoCompraFactura.id)
        .filter(
            PedidoCompraFactura.pedido_id == pedido.id,
            PedidoCompraFactura.ct_transaction_id == ct,
        )
        .first()
    )
    if exists is None:
        session.add(
            PedidoCompraFactura(
                pedido_id=pedido.id,
                ct_transaction_id=ct,
                fecha_factura=fecha,
            )
        )
        session.flush()
    _sync_header_factura_cache(session, pedido)
    _resolver_auto_vinculo_tras_asignar(session, pedido, ct)
    _aplicar_sell_in_por_ct(session, ct)


def _resolver_auto_vinculo_tras_asignar(session: Session, pedido: PedidoCompra, ct_transaction: int) -> None:
    """Clear pending auto-vínculo badges when Administración links the CT by hand."""
    from datetime import UTC, datetime as dt  # noqa: PLC0415

    from app.models.pedido_factura_documento import PedidoFacturaDocumento  # noqa: PLC0415

    ct = int(ct_transaction)
    docnumber = None
    # SAVEPOINT: a missing/broken view must not abort the outer assign txn
    # (same pattern as #2264 `_ct_docnumbers_by_id`).
    try:
        with session.begin_nested():
            docnumber = session.execute(
                text(
                    """
                    SELECT ct_docnumber
                    FROM v_facturas_compra_vigentes
                    WHERE ct_transaction = :ct
                    LIMIT 1
                    """
                ),
                {"ct": ct},
            ).scalar()
    except Exception as exc:  # noqa: BLE001 — view absent in SQLite unit tests
        logger.warning(
            "auto_vinculo clear: vista lookup skipped ct=%s: %s",
            ct,
            exc,
        )
    if not docnumber:
        try:
            with session.begin_nested():
                docnumber = session.execute(
                    text(
                        """
                        SELECT ct_docnumber
                        FROM tb_commercial_transactions
                        WHERE ct_transaction = :ct
                        LIMIT 1
                        """
                    ),
                    {"ct": ct},
                ).scalar()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "auto_vinculo clear: mirror lookup skipped ct=%s: %s",
                ct,
                exc,
            )
            return
    numero = str(docnumber or "").strip()
    if not numero or pedido.id is None:
        return
    stamp = dt.now(UTC)
    pendientes = (
        session.query(PedidoFacturaDocumento)
        .filter(
            PedidoFacturaDocumento.pedido_id == pedido.id,
            PedidoFacturaDocumento.cargada.is_(True),
            PedidoFacturaDocumento.numero == numero,
            PedidoFacturaDocumento.auto_vinculo_estado.in_(sorted(AUTO_VINCULO_PENDIENTES)),
        )
        .all()
    )
    for doc in pendientes:
        doc.auto_vinculo_estado = AUTO_VINCULO_OK
        doc.auto_vinculo_intentado_at = stamp
    if pendientes:
        session.flush()


def quitar_factura_erp(session: Session, pedido: PedidoCompra, ct_transaction: int) -> None:
    """Remove one CT link from a pedido; refresh header + sell-in gate. NO commit."""
    from app.models.pedido_compra_factura import PedidoCompraFactura  # noqa: PLC0415

    _seed_factura_junction_from_header(session, pedido)
    ct = int(ct_transaction)
    session.query(PedidoCompraFactura).filter(
        PedidoCompraFactura.pedido_id == pedido.id,
        PedidoCompraFactura.ct_transaction_id == ct,
    ).delete(synchronize_session=False)
    session.flush()
    _sync_header_factura_cache(session, pedido)
    if pedido.id is not None and pedido.ct_transaction_id is None:
        _borrar_lineas(session, pedido.id)
    elif pedido.id is not None and pedido.ct_transaction_id is not None:
        reconciliar_lineas_facturadas(session, pedido.id)
    _aplicar_sell_in_por_ct(session, ct)


_FECHA_VISTA_SQL = (
    "(SELECT date(v.ct_date) FROM v_facturas_compra_vigentes v "
    "WHERE v.ct_transaction = pedidos_compra.ct_transaction_id)"
)
# Core UPDATE on purpose: the ORM `onupdate` of updated_at does not fire, and
# `IS DISTINCT FROM` makes an unchanged row a no-op (Postgres and SQLite 3.39+).
_REFRESCAR_FECHAS_SQL = text(
    f"UPDATE pedidos_compra SET fecha_factura = {_FECHA_VISTA_SQL} "
    f"WHERE ct_transaction_id IS NOT NULL AND fecha_factura IS DISTINCT FROM {_FECHA_VISTA_SQL}"
)


def refrescar_fechas_factura(session: Session) -> int:
    """Re-read `fecha_factura` of every linked pedido from the view.

    `asignar_factura_erp` snapshots the date when the link is written; this
    catches what the ERP changes later: an edited ct_date, an annulled invoice
    (leaves the view → NULL) or a ct linked before it appeared in the view.
    One set-based UPDATE that touches only rows whose value differs. NO commit.

    Returns:
        how many pedidos changed.
    """
    actualizados = session.execute(_REFRESCAR_FECHAS_SQL).rowcount or 0
    logger.info("refrescar_fechas_factura: pedidos actualizados=%s", actualizados)
    return actualizados


# ERP documents that make up a linked pedido's invoiced units: its invoice
# plus every purchase credit note with a VIGENTE imputación (not a reversal and
# never reversed) to the pedido, to a pedido it was corrected from, or to its
# invoice — an ERP NC directly (origen_id = ct) or a local NC through its
# matched ct_transaction_id. UNION counts an NC imputed several times only once.
#
# Why the correction chain (`cadena`): a financial `corregir_pedido` leaves the
# clone pending while the imputaciones stay frozen on the original until the
# clone is approved (or forever, if it is rejected or cancelled); approval
# reverses them on the original and re-creates them on the clone. Following
# every `corregido_desde_id` hop therefore counts each credit note exactly once
# in every state: frozen → through the ancestor; transferred → the ancestor's
# copy is reversed (not vigente) and the clone's own counts. The whole chain,
# not one hop, because `crear_imputacion` does not guard the destination
# pedido's estado, so a credit note can still land on a cancelled ancestor.
# The cancelled original keeps no lines: it has no ct_transaction_id.
# Sell-in gate: each CT contributes units only when linked to exactly one
# pedido (junction SoT ∪ header-only fallback). Shared CTs stay documental.
# Links: every junction row for the scoped pedido; if the pedido has no
# junction rows yet, fall back to the header cache (pre-migration / seed).
_CT_OWNERS_EQ_1 = """(
  SELECT COUNT(*) FROM (
    SELECT f.pedido_id AS pid FROM pedido_compra_facturas f
    WHERE f.ct_transaction_id = links.ct
    UNION
    SELECT px.id FROM pedidos_compra px
    WHERE px.ct_transaction_id = links.ct
  ) owners
) = 1"""

_LINKS_SQL = """
SELECT f.pedido_id AS pedido_id, f.ct_transaction_id AS ct
FROM pedido_compra_facturas f
JOIN pedidos_compra p ON p.id = f.pedido_id
WHERE {scope_pedido}
UNION
SELECT p.id AS pedido_id, p.ct_transaction_id AS ct
FROM pedidos_compra p
WHERE p.ct_transaction_id IS NOT NULL AND {scope_pedido}
  AND NOT EXISTS (
    SELECT 1 FROM pedido_compra_facturas f2 WHERE f2.pedido_id = p.id
  )
"""

_DOCUMENTOS_SQL = (
    "SELECT links.pedido_id AS pedido_id, links.ct AS ct FROM ("
    + _LINKS_SQL
    + ") links WHERE "
    + _CT_OWNERS_EQ_1
    + """
UNION
SELECT links.pedido_id, n.ct
FROM ("""
    + _LINKS_SQL
    + """) links
JOIN (
  WITH RECURSIVE cadena(pedido_id, ancestro_id) AS (
    SELECT links.pedido_id, links.pedido_id FROM ("""
    + _LINKS_SQL
    + ") links WHERE "
    + _CT_OWNERS_EQ_1
    + """
    UNION
    SELECT c.pedido_id, a.corregido_desde_id
    FROM cadena c JOIN pedidos_compra a ON a.id = c.ancestro_id
    WHERE a.corregido_desde_id IS NOT NULL
  )
  SELECT pedido_id, ancestro_id FROM cadena
) cad ON cad.pedido_id = links.pedido_id
JOIN (
  SELECT i.destino_tipo, i.destino_id,
         CASE WHEN i.origen_tipo = 'nota_credito_erp' THEN i.origen_id ELSE ncl.ct_transaction_id END AS ct
  FROM imputaciones i
  LEFT JOIN notas_credito_local ncl ON i.origen_tipo = 'nota_credito_local' AND ncl.id = i.origen_id
  WHERE i.origen_tipo IN ('nota_credito_erp', 'nota_credito_local')
    AND i.es_reversal = false
    AND NOT EXISTS (SELECT 1 FROM imputaciones r WHERE r.es_reversal = true AND r.reimputada_desde_id = i.id)
) n ON (n.destino_tipo = 'pedido_compra' AND n.destino_id = cad.ancestro_id)
    OR (n.destino_tipo = 'factura_erp' AND n.destino_id = links.ct)
JOIN v_facturas_compra_vigentes vn ON vn.ct_transaction = n.ct AND vn.clasificacion = 'NC'
WHERE """
    + _CT_OWNERS_EQ_1
)
# Net units per item: it_qty is stored positive, the sign is the document's
# sd_plusorminus (what sale_document_classifier.signo_contable returns; -1 for
# credit notes). Only documents still in v_facturas_compra_vigentes count
# (annulled → no lines); a net below one unit is not stored (clamp at 0).
# FLOOR, not ROUND: cantidad is invoiced units that pay a per-unit bonus, so a
# fractional net (2.7) must count the whole units actually invoiced (2), never
# over-pay. FLOOR is explicit because a bare CAST(numeric AS INTEGER) rounds on
# PostgreSQL but truncates on SQLite (FLOOR exists there since 3.35, math
# functions are enabled by default). Same expression in the migration backfill.
# Combo components are left out and only the main line counts, as in the sales
# metrics scripts (no purchase line had association flags on prod 2026-10-19;
# the rule only guards against a future double count).
#
# Net amount (sell-in T3g-1, the base of a % sell in): SUM(it_qty * it_price *
# sd_plusorminus), rounded to cents, clamped at 0, in the lines' OWN currency
# (`it.curr_id`, 1=ARS, 2=USD as pedidos_service._curr_id_a_moneda). Measured on
# the dev-DB ERP mirror 2026-10-21 (50 invoices): 9 ARS-header invoices carry
# USD-priced lines (it_price in USD, ct_subtotal in ARS), so the header's
# curr_id_transaction would mislabel the amount; and it_price is already net of it_discount1..4
# (it_pricewithoothers is the pre-discount price). When the invoice and its
# credit notes mix currencies, or a line lacks a price or a known currency, no
# single amount exists: importe_neto and moneda are both NULL. CASE instead of
# GREATEST so the SQLite test engine runs it too. Same SQL in the migration
# 20261110_pedido_lineas_facturadas_importe backfill.
_IMPORTE_VALIDO = (
    "COUNT(DISTINCT it.curr_id) = 1 AND COUNT(it.curr_id) = COUNT(*) "
    "AND COUNT(it.it_price) = COUNT(*) AND MIN(it.curr_id) IN (1, 2)"
)
_LINEAS_ORIGEN_SQL = (
    "SELECT d.pedido_id AS pedido_id, it.item_id AS item_id, "
    "CAST(FLOOR(SUM(it.it_qty * v.sd_plusorminus)) AS INTEGER) AS cantidad, "
    "CASE WHEN " + _IMPORTE_VALIDO + " THEN CASE WHEN SUM(it.it_qty * it.it_price * v.sd_plusorminus) < 0 THEN 0 "
    "ELSE ROUND(SUM(it.it_qty * it.it_price * v.sd_plusorminus), 2) END END AS importe_neto, "
    "CASE WHEN " + _IMPORTE_VALIDO + " THEN CASE MIN(it.curr_id) WHEN 1 THEN 'ARS' ELSE 'USD' END END AS moneda "
    "FROM (" + _DOCUMENTOS_SQL + ") d "
    """JOIN v_facturas_compra_vigentes v ON v.ct_transaction = d.ct
JOIN tb_item_transactions it ON it.ct_transaction = d.ct
WHERE it.item_id IS NOT NULL
  AND NOT (
    COALESCE(it.it_isassociation, false) = true
    AND COALESCE(it.it_order, 1) <> 1
    AND it.it_isassociationgroup IS NOT NULL
  )
GROUP BY d.pedido_id, it.item_id
HAVING SUM(it.it_qty * v.sd_plusorminus) >= 1
"""
)
# Per invoice (sell in varias facturas, `PedidoCompraLineaFacturadaCt`): the same documents tagged with the invoice
# they belong to. `factura` is the linked CT itself, or for a credit note the invoice it is imputed to; NULL for one
# imputed to the whole operation (`destino_tipo = 'pedido_compra'`, through the corrected-from chain too). A credit
# note imputed both ways is one document of one bucket (MAX), so per (pedido, item) the buckets add up to the
# aggregate above, which keeps its own SQL untouched.
_DOCUMENTOS_CT_SQL = (
    "SELECT docs.pedido_id AS pedido_id, docs.ct AS ct, MAX(docs.factura) AS factura FROM ("
    "SELECT links.pedido_id AS pedido_id, links.ct AS ct, links.ct AS factura FROM ("
    + _LINKS_SQL
    + ") links WHERE "
    + _CT_OWNERS_EQ_1
    + """
UNION
SELECT links.pedido_id, n.ct, CASE WHEN n.destino_tipo = 'factura_erp' THEN links.ct END
FROM ("""
    + _LINKS_SQL
    + """) links
JOIN (
  WITH RECURSIVE cadena(pedido_id, ancestro_id) AS (
    SELECT links.pedido_id, links.pedido_id FROM ("""
    + _LINKS_SQL
    + ") links WHERE "
    + _CT_OWNERS_EQ_1
    + """
    UNION
    SELECT c.pedido_id, a.corregido_desde_id
    FROM cadena c JOIN pedidos_compra a ON a.id = c.ancestro_id
    WHERE a.corregido_desde_id IS NOT NULL
  )
  SELECT pedido_id, ancestro_id FROM cadena
) cad ON cad.pedido_id = links.pedido_id
JOIN (
  SELECT i.destino_tipo, i.destino_id,
         CASE WHEN i.origen_tipo = 'nota_credito_erp' THEN i.origen_id ELSE ncl.ct_transaction_id END AS ct
  FROM imputaciones i
  LEFT JOIN notas_credito_local ncl ON i.origen_tipo = 'nota_credito_local' AND ncl.id = i.origen_id
  WHERE i.origen_tipo IN ('nota_credito_erp', 'nota_credito_local')
    AND i.es_reversal = false
    AND NOT EXISTS (SELECT 1 FROM imputaciones r WHERE r.es_reversal = true AND r.reimputada_desde_id = i.id)
) n ON (n.destino_tipo = 'pedido_compra' AND n.destino_id = cad.ancestro_id)
    OR (n.destino_tipo = 'factura_erp' AND n.destino_id = links.ct)
JOIN v_facturas_compra_vigentes vn ON vn.ct_transaction = n.ct AND vn.clasificacion = 'NC'
WHERE """
    + _CT_OWNERS_EQ_1
    + ") docs GROUP BY docs.pedido_id, docs.ct"
)
# An invoice's bucket keeps the aggregate's rules (net >= 1 unit, amount clamped at 0); the operation's credit-note
# bucket is signed (net <> 0, amount unclamped): it only takes away.
_LINEAS_CT_ORIGEN_SQL = (
    "SELECT d.pedido_id AS pedido_id, d.factura AS factura, it.item_id AS item_id, "
    "CAST(FLOOR(SUM(it.it_qty * v.sd_plusorminus)) AS INTEGER) AS cantidad, "
    "CASE WHEN " + _IMPORTE_VALIDO + " THEN CASE WHEN d.factura IS NOT NULL "
    "AND SUM(it.it_qty * it.it_price * v.sd_plusorminus) < 0 THEN 0 "
    "ELSE ROUND(SUM(it.it_qty * it.it_price * v.sd_plusorminus), 2) END END AS importe_neto, "
    "CASE WHEN " + _IMPORTE_VALIDO + " THEN CASE MIN(it.curr_id) WHEN 1 THEN 'ARS' ELSE 'USD' END END AS moneda "
    "FROM (" + _DOCUMENTOS_CT_SQL + ") d "
    """JOIN v_facturas_compra_vigentes v ON v.ct_transaction = d.ct
JOIN tb_item_transactions it ON it.ct_transaction = d.ct
WHERE it.item_id IS NOT NULL
  AND NOT (
    COALESCE(it.it_isassociation, false) = true
    AND COALESCE(it.it_order, 1) <> 1
    AND it.it_isassociationgroup IS NOT NULL
  )
GROUP BY d.pedido_id, d.factura, it.item_id
HAVING (d.factura IS NOT NULL AND SUM(it.it_qty * v.sd_plusorminus) >= 1)
    OR (d.factura IS NULL AND CAST(FLOOR(SUM(it.it_qty * v.sd_plusorminus)) AS INTEGER) <> 0)
"""
)
_T = "pedido_compra_lineas_facturadas"
_TCT = "pedido_compra_lineas_facturadas_ct"
_BORRAR_LINEAS_SQL = (
    text(f"DELETE FROM {_T} WHERE pedido_id = :pid"),
    text(f"DELETE FROM {_TCT} WHERE pedido_id = :pid"),
)
# The corrected clone inherits the original's link and lines as-is (both snapshots).
_COPIAR_LINEAS_SQL = (
    text(
        f"INSERT INTO {_T} (pedido_id, item_id, cantidad, importe_neto, moneda) "
        f"SELECT :destino, item_id, cantidad, importe_neto, moneda FROM {_T} WHERE pedido_id = :origen"
    ),
    text(
        f"INSERT INTO {_TCT} (pedido_id, ct_transaction_id, item_id, cantidad, importe_neto, moneda) "
        f"SELECT :destino, ct_transaction_id, item_id, cantidad, importe_neto, moneda FROM {_TCT} "
        "WHERE pedido_id = :origen"
    ),
)


def _borrar_lineas(session: Session, pedido_id: int) -> None:
    """Drop both invoiced-lines snapshots of an operation (aggregate and per invoice)."""
    for sql in _BORRAR_LINEAS_SQL:
        session.execute(sql, {"pid": pedido_id})


_MATCH = f"s.pedido_id = {_T}.pedido_id AND s.item_id = {_T}.item_id"
# Set difference against the snapshot: delete what the ERP no longer has, then
# upsert the rest. ON CONFLICT (not INSERT ... WHERE NOT EXISTS) makes two
# concurrent reconciles of the same pedido safe under READ COMMITTED: the second
# one waits for the first and updates its row instead of raising on
# UNIQUE(pedido_id, item_id). The DO UPDATE ... WHERE skips unchanged rows, so
# they do not count as changes; IS DISTINCT FROM because importe_neto/moneda
# can be NULL on either side. `WHERE true` is required by SQLite to parse an
# upsert after INSERT ... SELECT. Supported by PostgreSQL and SQLite >= 3.39
# (IS DISTINCT FROM on row values).
_RECONCILIAR_SQL = (
    "WITH s AS ({origen}) DELETE FROM {t} WHERE {scope_t} AND NOT EXISTS (SELECT 1 FROM s WHERE {match})",
    "WITH s AS ({origen}) INSERT INTO {t} (pedido_id, item_id, cantidad, importe_neto, moneda) "
    "SELECT s.pedido_id, s.item_id, s.cantidad, s.importe_neto, s.moneda FROM s WHERE true "
    "ON CONFLICT (pedido_id, item_id) DO UPDATE SET cantidad = excluded.cantidad, "
    "importe_neto = excluded.importe_neto, moneda = excluded.moneda "
    "WHERE ({t}.cantidad, {t}.importe_neto, {t}.moneda) "
    "IS DISTINCT FROM (excluded.cantidad, excluded.importe_neto, excluded.moneda)",
)
# The per-invoice snapshot, same set difference: one upsert per bucket kind (each has its own partial unique index;
# ON CONFLICT names the index by its columns and predicate).
_MATCH_CT = (
    f"s.pedido_id = {_TCT}.pedido_id AND s.item_id = {_TCT}.item_id "
    f"AND s.factura IS NOT DISTINCT FROM {_TCT}.ct_transaction_id"
)
_UPSERT_CT = (
    "WITH s AS ({origen}) INSERT INTO {t} (pedido_id, ct_transaction_id, item_id, cantidad, importe_neto, moneda) "
    "SELECT s.pedido_id, s.factura, s.item_id, s.cantidad, s.importe_neto, s.moneda FROM s WHERE s.factura IS {nulo} "
    "ON CONFLICT ({conflicto}) WHERE ct_transaction_id IS {nulo} DO UPDATE SET cantidad = excluded.cantidad, "
    "importe_neto = excluded.importe_neto, moneda = excluded.moneda "
    "WHERE ({t}.cantidad, {t}.importe_neto, {t}.moneda) "
    "IS DISTINCT FROM (excluded.cantidad, excluded.importe_neto, excluded.moneda)"
)
_RECONCILIAR_CT_SQL = (
    "WITH s AS ({origen}) DELETE FROM {t} WHERE {scope_t} AND NOT EXISTS (SELECT 1 FROM s WHERE {match})",
    _UPSERT_CT.replace("{nulo}", "NOT NULL").replace("{conflicto}", "pedido_id, ct_transaction_id, item_id"),
    _UPSERT_CT.replace("{nulo}", "NULL").replace("{conflicto}", "pedido_id, item_id"),
)


def copiar_lineas_facturadas(session: Session, *, origen_id: int, destino_id: int) -> None:
    """Copy a pedido's invoiced-units snapshot to another one (corregir_pedido). NO commit."""
    for sql in _COPIAR_LINEAS_SQL:
        session.execute(sql, {"origen": origen_id, "destino": destino_id})


def reconciliar_lineas_facturadas(session: Session, pedido_id: Optional[int] = None) -> int:
    """Bring `pedido_compra_lineas_facturadas` (and its per-invoice split `pedido_compra_lineas_facturadas_ct`) in
    step with the ERP mirror.

    One pedido (`pedido_id`) or every pedido (None, the ERP sync hook). Flushes
    first because it reads `pedidos_compra.ct_transaction_id` from SQL. A pedido
    without a link, or whose invoice left the view, ends with no lines. NO commit.

    Returns:
        how many snapshot rows were deleted, updated or inserted.
    """
    session.flush()
    params = {"pid": pedido_id}
    scope_pedido = "p.id = :pid" if pedido_id is not None else "1 = 1"
    scope_t = f"{_T}.pedido_id = :pid" if pedido_id is not None else "1 = 1"
    origen = _LINEAS_ORIGEN_SQL.format(scope_pedido=scope_pedido)
    cambios = sum(
        session.execute(text(sql.format(origen=origen, t=_T, scope_t=scope_t, match=_MATCH)), params).rowcount or 0
        for sql in _RECONCILIAR_SQL
    )
    # The per-invoice split (sell in varias facturas): same scope, same transaction; not counted in `cambios`, which
    # keeps reporting the aggregate it always reported.
    origen_ct = _LINEAS_CT_ORIGEN_SQL.format(scope_pedido=scope_pedido)
    scope_ct = f"{_TCT}.pedido_id = :pid" if pedido_id is not None else "1 = 1"
    for sql in _RECONCILIAR_CT_SQL:
        session.execute(text(sql.format(origen=origen_ct, t=_TCT, scope_t=scope_ct, match=_MATCH_CT)), params)
    logger.info("reconciliar_lineas_facturadas: pedido_id=%s filas cambiadas=%s", pedido_id, cambios)
    return cambios


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
    ct_transaction, _match_estado = _buscar_ct_vigente(
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

    asignar_factura_erp(session, pedido, ct_transaction)
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
    # `ct_total` lo necesitamos para comparar contra `pedido.monto` y
    # alertar mismatch silencioso (Batch I — decisión Q3).
    stmt_vista = text(
        """
        SELECT v.ct_transaction, v.comp_id, v.bra_id, v.supp_id,
               v.ct_docnumber, v.ct_total
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

            ct_transaction, comp_id, bra_id, supp_id, ct_docnumber, ct_total = fila

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

            asignar_factura_erp(session, pedido, int(ct_transaction))
            _registrar_evento_match(
                session,
                pedido=pedido,
                ct_transaction=int(ct_transaction),
                origen="backward",
            )
            resumen["pedidos_asociados"] += 1

            # Batch I — Q3: detectar mismatch de monto y alertar (NO ajustar).
            # Comparación con tolerancia de centavo (Decimal strict).
            _alertar_si_monto_difiere(
                session,
                pedido=pedido,
                ct_transaction=int(ct_transaction),
                ct_docnumber=str(ct_docnumber or ""),
                ct_total=Decimal(str(ct_total or 0)),
            )
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


def match_ncs_backward(
    session: Session,
    *,
    cts_synced: list[int],
) -> dict[str, int]:
    """
    Compras v2 — Matching de NCs locales contra NCs sincronizadas del ERP.

    Para cada `ct_transaction` recién ingestado:
      1. Verifica que sea NC de compra (sd_iscreditnote=true AND sd_ispurchase=true)
         vía join con `tb_sale_document`.
      2. Busca una NC local tal que:
         - `nc.numero_nc_proveedor = ct.ct_docnumber`
         - `nc.proveedor_id → supp_id = ct.supp_id`
         - `nc.ct_transaction_id IS NULL` (no pisa matchings previos).
      3. Si hay match único → setea `nc.ct_transaction_id` + evento.
      4. Si el monto difiere: NO ajusta silenciosamente. Crea evento
         `nc_monto_difiere_al_matchear_erp` + notificación admin (mismo
         patrón que pedidos — Batch I previo).

    Invocada desde el hook inline del cron `sync_commercial_transactions_guid.py`
    en paralelo a `match_backward` (pedidos).

    NO commitea. NO levanta excepciones por ct individual (las cuenta en
    `errores`).

    Args:
        session: tx activa.
        cts_synced: lista de `ct_transaction` recién sincronizados.

    Returns:
        dict con `cts_procesadas`, `ncs_asociadas`, `errores`.
    """
    resumen = {
        "cts_procesadas": len(cts_synced),
        "ncs_asociadas": 0,
        "errores": 0,
    }
    if not cts_synced:
        return resumen

    # Import local — modelo NCs solo existe en compras v2.
    from app.models.nota_credito_local import NotaCreditoLocal  # noqa: PLC0415

    stmt_nc_erp = text(
        """
        SELECT ct.ct_transaction, ct.supp_id, ct.ct_docnumber, ct.ct_total
        FROM tb_commercial_transactions ct
        JOIN tb_sale_document sd ON sd.sd_id = ct.sd_id
        WHERE ct.ct_transaction = :ct
          AND sd.sd_iscreditnote = TRUE
          AND sd.sd_ispurchase = TRUE
          AND COALESCE(ct.ct_iscancelled, FALSE) = FALSE
        """
    )

    for ct_id in cts_synced:
        try:
            fila = session.execute(stmt_nc_erp, {"ct": ct_id}).first()
            if fila is None:
                # No es una NC de compra → no aplica.
                continue

            ct_transaction, supp_id, ct_docnumber, ct_total = fila
            if not ct_docnumber or supp_id is None:
                continue

            nc_local: Optional[NotaCreditoLocal] = (
                session.query(NotaCreditoLocal)
                .join(Proveedor, Proveedor.id == NotaCreditoLocal.proveedor_id)
                .filter(
                    NotaCreditoLocal.numero_nc_proveedor == ct_docnumber,
                    NotaCreditoLocal.ct_transaction_id.is_(None),
                    Proveedor.supp_id == int(supp_id),
                )
                .first()
            )
            if nc_local is None:
                continue

            nc_local.ct_transaction_id = int(ct_transaction)
            session.add(
                CompraEvento(
                    entidad_tipo=CompraEvento.ENTIDAD_TIPO_NC_LOCAL,
                    entidad_id=nc_local.id,
                    tipo="nc_factura_erp_vinculada",
                    usuario_id=nc_local.creado_por_id,
                    payload={
                        "ct_transaction": int(ct_transaction),
                        "ct_docnumber": str(ct_docnumber),
                        "modo": "backward",
                    },
                )
            )
            resumen["ncs_asociadas"] += 1

            # Detectar mismatch de monto (NO ajustar — solo alertar).
            ct_total_dec = Decimal(str(ct_total or 0))
            monto_nc = Decimal(str(nc_local.monto))
            diferencia = ct_total_dec - monto_nc
            if abs(diferencia) >= Decimal("0.01") and ct_total_dec > 0:
                session.add(
                    CompraEvento(
                        entidad_tipo=CompraEvento.ENTIDAD_TIPO_NC_LOCAL,
                        entidad_id=nc_local.id,
                        tipo="nc_monto_difiere_al_matchear_erp",
                        usuario_id=nc_local.creado_por_id,
                        payload={
                            "ct_transaction": int(ct_transaction),
                            "ct_docnumber": str(ct_docnumber),
                            "ct_total_erp": str(ct_total_dec),
                            "monto_nc": str(monto_nc),
                            "diferencia": str(diferencia),
                            "origen": "match_ncs_backward",
                        },
                    )
                )
                # Fan-out a admins con permiso de gestión de OPs o CC
                # (misma política que `_alertar_si_monto_difiere`).
                crear_notificaciones_para_permisos(
                    session,
                    permisos_requeridos=PERMISOS_NOTIF_MATCHING,
                    tipo="compras.nc_monto_difiere_factura",
                    mensaje=(
                        f"NC local {nc_local.numero} fue vinculada automáticamente a la "
                        f"NC del ERP {ct_docnumber} (ct={ct_transaction}) pero el monto "
                        f"difiere: nc_local={monto_nc} vs erp={ct_total_dec} "
                        f"(diferencia={diferencia}). Revisá y ajustá si corresponde."
                    ),
                    severidad=SeveridadNotificacion.WARNING,
                    estado=EstadoNotificacion.PENDIENTE,
                    item_id=nc_local.id,
                )
                logger.warning(
                    "match_ncs_backward MISMATCH monto nc_local_id=%s ct=%s nc=%s vs erp=%s",
                    nc_local.id,
                    ct_transaction,
                    monto_nc,
                    ct_total_dec,
                )

            logger.info(
                "match_ncs_backward: nc_local_id=%s ↔ ct_transaction=%s",
                nc_local.id,
                ct_transaction,
            )

        except Exception as exc:  # noqa: BLE001 — capturar TODO por ct
            resumen["errores"] += 1
            logger.exception(
                "match_ncs_backward: error procesando ct_transaction=%s: %s",
                ct_id,
                exc,
            )
            continue

    session.flush()

    # ── Propagación de cancelaciones ERP → NC local ──────────────────────
    # Para cada ct que fue ACTUALIZADO (puede estar en cts_synced), verificar
    # si pasó a ct_iscancelled=TRUE y si hay una NC local vinculada a ella.
    # Si la NC local está en un estado activo (aprobado, aplicada_parcial,
    # borrador, pendiente_aprobacion), se cancela automáticamente.
    #
    # Importante: esta operación corre DESPUÉS del matching principal para
    # evitar interferir con el flujo de vinculación.
    if cts_synced:
        _cancelar_ncs_locales_por_erp_cancelado(session, cts_synced=cts_synced, resumen=resumen)

    return resumen


def _cancelar_ncs_locales_por_erp_cancelado(
    session: Session,
    *,
    cts_synced: list[int],
    resumen: dict[str, int],
) -> None:
    """
    Para cada ct_transaction en cts_synced que sea una NC ERP cancelada,
    cancela la NC local vinculada (si existe y está en estado activo).

    Estados terminales que NO se tocan: 'cancelado', 'aplicada'.
    Estados que sí se cancelan: 'borrador', 'pendiente_aprobacion', 'aprobado',
    'aplicada_parcial', 'rechazado' (vía cancelar_definitivo → cancelado).

    Para 'aprobado' y 'aplicada_parcial' se usa la acción 'cancelar_aprobado'
    (que revierte imputaciones activas). Para 'rechazado', 'cancelar_definitivo'.
    Para los demás activos, 'cancelar' / 'rechazar_cancelar'.

    NO commitea. Errores individuales se cuentan en resumen['errores'].
    """
    from app.models.nota_credito_local import NotaCreditoLocal  # noqa: PLC0415
    from app.models.proveedor import Proveedor  # noqa: PLC0415
    from app.services import ncs_locales_service  # noqa: PLC0415
    from sqlalchemy.exc import SQLAlchemyError  # noqa: PLC0415

    # Mapa estado_origen → acción de cancelación válida según TRANSICIONES_VALIDAS.
    # Terminales cancelado/aplicada se omiten antes de llegar aquí; rechazado
    # still advances to cancelado when the ERP credit note was cancelled.
    _ACCION_CANCELAR: dict[str, str] = {
        "borrador": "cancelar",
        "pendiente_aprobacion": "rechazar_cancelar",
        "aprobado": "cancelar_aprobado",
        "aplicada_parcial": "cancelar_aprobado",
        "rechazado": "cancelar_definitivo",
    }

    # Buscar NCs ERP canceladas que estén en el batch de sync.
    # Construir IN clause con placeholders posicionales (compatible con
    # PostgreSQL y SQLite — evita el operador ANY que no existe en SQLite).
    placeholders = ", ".join(f":ct{i}" for i in range(len(cts_synced)))
    params = {f"ct{i}": ct for i, ct in enumerate(cts_synced)}
    stmt_canceladas = text(
        f"""
        SELECT ct.ct_transaction, ct.supp_id, ct.ct_docnumber
        FROM tb_commercial_transactions ct
        JOIN tb_sale_document sd ON sd.sd_id = ct.sd_id
        WHERE ct.ct_transaction IN ({placeholders})
          AND sd.sd_iscreditnote = TRUE
          AND sd.sd_ispurchase = TRUE
          AND COALESCE(ct.ct_iscancelled, FALSE) = TRUE
        """
    )
    try:
        filas_canceladas = session.execute(stmt_canceladas, params).all()
    except SQLAlchemyError as exc:
        logger.warning(
            "match_ncs_backward._cancelar: error buscando NCs ERP canceladas: %s",
            exc,
        )
        return

    if not filas_canceladas:
        return

    for fila in filas_canceladas:
        ct_id, supp_id_erp, ct_docnumber = fila[0], fila[1], fila[2]
        try:
            # Buscar NC local vinculada por ct_transaction_id (path normal).
            nc_local: Optional[NotaCreditoLocal] = (
                session.query(NotaCreditoLocal).filter(NotaCreditoLocal.ct_transaction_id == int(ct_id)).first()
            )

            # C2: Si no hay match por ct_transaction_id (NC nunca fue vinculada
            # porque la CT ya era cancelada desde el primer sync), intentar por
            # (proveedor.supp_id, numero_nc_proveedor) — la misma llave que usa
            # el matcher forward — siempre que tengamos los datos necesarios.
            if nc_local is None and supp_id_erp is not None and ct_docnumber:
                nc_local = (
                    session.query(NotaCreditoLocal)
                    .join(Proveedor, Proveedor.id == NotaCreditoLocal.proveedor_id)
                    .filter(
                        NotaCreditoLocal.numero_nc_proveedor == ct_docnumber,
                        NotaCreditoLocal.ct_transaction_id.is_(None),
                        Proveedor.supp_id == int(supp_id_erp),
                    )
                    .first()
                )
                if nc_local is not None:
                    # Vincular antes de cancelar para dejar trazabilidad.
                    nc_local.ct_transaction_id = int(ct_id)

            if nc_local is None:
                continue

            # Estados terminales que ya no requieren acción.
            if nc_local.estado in {"cancelado", "aplicada"}:
                continue

            # C1: Seleccionar acción según la matriz TRANSICIONES_VALIDAS.
            accion: Optional[str] = _ACCION_CANCELAR.get(nc_local.estado)
            if accion is None:
                logger.warning(
                    "match_ncs_backward._cancelar: nc_local_id=%s estado=%s no tiene "
                    "ruta de cancelación definida — se omite (ct=%s).",
                    nc_local.id,
                    nc_local.estado,
                    ct_id,
                )
                continue

            ncs_locales_service.transicionar(
                session,
                nc_id=nc_local.id,
                accion=accion,
                user_id=nc_local.creado_por_id,
                motivo=f"Cancelación automática: NC ERP ct={ct_id} fue cancelada en el ERP.",
            )
            resumen["ncs_canceladas_por_erp"] = resumen.get("ncs_canceladas_por_erp", 0) + 1

            logger.info(
                "match_ncs_backward: nc_local_id=%s cancelada (accion=%s) porque ct=%s fue cancelada en ERP",
                nc_local.id,
                accion,
                ct_id,
            )

        except HTTPException as exc:
            # W1: La máquina de estados levanta HTTPException para transiciones inválidas.
            # Es un error de datos (estado inesperado), no un error de infraestructura.
            resumen["errores"] += 1
            logger.error(
                "match_ncs_backward._cancelar: transición inválida para ct=%s nc_local estado=%s — %s",
                ct_id,
                nc_local.estado if nc_local else "desconocido",
                exc.detail,
            )
        except SQLAlchemyError as exc:
            resumen["errores"] += 1
            logger.exception(
                "match_ncs_backward._cancelar: error de base de datos procesando ct=%s: %s",
                ct_id,
                exc,
            )
        except Exception:
            # Re-raise para que errores inesperados NO queden silenciados.
            raise

    session.flush()


def _marcar_auto_vinculo(
    documento: Any,
    *,
    estado: str,
    ahora: datetime,
) -> None:
    """Stamp auto-vínculo outcome on the constancia row (when columns exist)."""
    if hasattr(documento, "auto_vinculo_estado"):
        documento.auto_vinculo_estado = estado
    if hasattr(documento, "auto_vinculo_intentado_at"):
        documento.auto_vinculo_intentado_at = ahora


def auto_vincular_por_constancia_cargada(
    session: Session,
    documento: Any,
    *,
    usuario_id: Optional[int] = None,
    ahora: Optional[datetime] = None,
) -> Optional[int]:
    """Link ERP CT by `documento.numero` after the cargada regret window.

    Resolves a unique vigente CT for the documento's pedido empresa+supp+numero,
    then adds that CT to every same-empresa/proveedor pedido whose cargada
    constancia with that numero already left its regret window (or is this
    row). M:N documental; does not change monto. Skips pedidos that already
    link the CT. Persists `auto_vinculo_estado` on `documento`. Returns the CT
    id, or None if no unique match. NO commit.
    """
    from datetime import UTC, datetime as dt  # noqa: PLC0415

    from sqlalchemy import and_, or_  # noqa: PLC0415

    from app.models.pedido_compra_factura import cts_for_pedido  # noqa: PLC0415
    from app.models.pedido_factura_documento import PedidoFacturaDocumento  # noqa: PLC0415

    stamp = ahora if ahora is not None else dt.now(UTC)
    numero = (getattr(documento, "numero", None) or "").strip()
    if not numero:
        return None
    pedido = getattr(documento, "pedido", None) or session.get(PedidoCompra, documento.pedido_id)
    if pedido is None:
        return None

    try:
        comp_id, bra_id = resolver_comp_bra(pedido.empresa_id)
    except KeyError:
        logger.warning(
            "auto_vincular_constancia: pedido_id=%s empresa_id=%s sin mapeo ERP",
            pedido.id,
            pedido.empresa_id,
        )
        _marcar_auto_vinculo(documento, estado=AUTO_VINCULO_SIN_MAPEO, ahora=stamp)
        session.flush()
        return None
    supp_id = _resolver_supp_id(session, pedido.proveedor_id)
    if supp_id is None:
        logger.warning(
            "auto_vincular_constancia: pedido_id=%s proveedor_id=%s sin supp_id",
            pedido.id,
            pedido.proveedor_id,
        )
        _marcar_auto_vinculo(documento, estado=AUTO_VINCULO_SIN_MAPEO, ahora=stamp)
        session.flush()
        return None

    ct_transaction, match_estado = _buscar_ct_vigente(
        session,
        comp_id=comp_id,
        bra_id=bra_id,
        supp_id=supp_id,
        ct_docnumber=numero,
    )
    if ct_transaction is None:
        logger.info(
            "auto_vincular_constancia: %s para numero=%s (pedido_id=%s)",
            match_estado,
            numero,
            pedido.id,
        )
        _marcar_auto_vinculo(documento, estado=match_estado, ahora=stamp)
        session.flush()
        return None

    docs = (
        session.query(PedidoFacturaDocumento)
        .options(joinedload(PedidoFacturaDocumento.pedido))
        .filter(
            PedidoFacturaDocumento.numero == numero,
            PedidoFacturaDocumento.cargada.is_(True),
            or_(
                PedidoFacturaDocumento.id == documento.id,
                PedidoFacturaDocumento.alerta_disparada_at.isnot(None),
                and_(
                    PedidoFacturaDocumento.alerta_pendiente_hasta.isnot(None),
                    PedidoFacturaDocumento.alerta_pendiente_hasta <= stamp,
                ),
            ),
        )
        .all()
    )
    for doc in docs:
        target = doc.pedido or session.get(PedidoCompra, doc.pedido_id)
        if target is None:
            continue
        if target.proveedor_id != pedido.proveedor_id:
            continue
        if target.empresa_id != pedido.empresa_id:
            continue
        linked = {ct for ct, _ in cts_for_pedido(session, target)}
        if int(ct_transaction) in linked:
            _marcar_auto_vinculo(doc, estado=AUTO_VINCULO_OK, ahora=stamp)
            continue
        asignar_factura_erp(session, target, ct_transaction)
        _registrar_evento_match(
            session,
            pedido=target,
            ct_transaction=ct_transaction,
            origen="auto_constancia_cargada",
            usuario_id=usuario_id,
        )
        _marcar_auto_vinculo(doc, estado=AUTO_VINCULO_OK, ahora=stamp)
        logger.info(
            "auto_vincular_constancia: pedido_id=%s ↔ ct=%s (numero=%s)",
            target.id,
            ct_transaction,
            numero,
        )
    _marcar_auto_vinculo(documento, estado=AUTO_VINCULO_OK, ahora=stamp)
    session.flush()
    return int(ct_transaction)


__all__ = [
    "AUTO_VINCULO_AMBIGUO",
    "AUTO_VINCULO_OK",
    "AUTO_VINCULO_PENDIENTES",
    "AUTO_VINCULO_SIN_MAPEO",
    "AUTO_VINCULO_SIN_MATCH",
    "asignar_factura_erp",
    "auto_vincular_por_constancia_cargada",
    "copiar_facturas_erp",
    "copiar_lineas_facturadas",
    "match_backward",
    "match_forward",
    "match_ncs_backward",
    "quitar_factura_erp",
    "reconciliar_lineas_facturadas",
    "refrescar_fechas_factura",
    "validar_catalogo_populado",
]
