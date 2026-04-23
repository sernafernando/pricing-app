"""
Service para el control de bajada a depósito de items RMA.

Maneja la lógica de negocio del escaneo en dos pasos:
1. RMA escanea → pendiente → rma
2. Depósito escanea con operador → rma → deposito

Y la excepción "no baja" para items que no van al depósito.
"""

import logging
from datetime import UTC, datetime, date
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models.rma_caso import RmaCaso
from app.models.rma_caso_historial import RmaCasoHistorial
from app.models.rma_caso_item import RmaCasoItem
from app.models.rma_control_deposito_item import ControlDepoItem
from app.models.operador import Operador
from app.models.operador_actividad import OperadorActividad
from app.models.usuario import Usuario

logger = logging.getLogger(__name__)

# Terminal states — cannot be scanned or changed
_TERMINAL_STATES = {"deposito", "no_baja"}


class ControlDepositoService:
    """Business logic for depósito control checklist."""

    def __init__(self, db: Session) -> None:
        self.db = db

    # ── Create entry (idempotent) ─────────────────────────

    def crear_entrada(self, item: RmaCasoItem, caso: RmaCaso) -> ControlDepoItem:
        """Create a checklist entry for an RMA item. Idempotent — skips if exists."""
        existing = self.db.query(ControlDepoItem).filter(ControlDepoItem.rma_caso_item_id == item.id).first()
        if existing:
            return existing

        entry = ControlDepoItem(
            rma_caso_item_id=item.id,
            caso_id=caso.id,
            numero_caso=caso.numero_caso,
            serial_number=item.serial_number,
            ean=item.ean,
            item_id=item.item_id,
            producto_desc=item.producto_desc,
            estado="pendiente",
        )
        self.db.add(entry)
        self.db.flush()

        logger.info(
            "Control depósito: entrada creada para item %d (caso %s, serial=%s)",
            item.id,
            caso.numero_caso,
            item.serial_number,
        )
        return entry

    # ── Scan ──────────────────────────────────────────────

    def scan(
        self,
        codigo: str,
        user: Usuario,
        operador_id: Optional[int] = None,
    ) -> dict:
        """Scan a serial or EAN to advance the item state.

        Logic:
        1. Try exact serial_number match (only active items)
        2. If no serial match, try EAN match
        3. If multiple EAN matches → 409 with disambiguation
        4. If item is pendiente → set to rma (RMA scan, no operador needed)
        5. If item is rma → require operador_id, set to deposito (Depósito scan)
        6. If item is terminal → 400

        Returns dict with item data and action taken.
        """
        codigo = codigo.strip()
        if not codigo:
            raise HTTPException(400, "Código vacío")

        # 1. Try serial match
        entry = (
            self.db.query(ControlDepoItem)
            .filter(
                ControlDepoItem.serial_number == codigo,
                ControlDepoItem.estado.notin_(_TERMINAL_STATES),
            )
            .first()
        )

        # 2. Try EAN match
        if not entry:
            ean_matches = (
                self.db.query(ControlDepoItem)
                .filter(
                    ControlDepoItem.ean == codigo,
                    ControlDepoItem.estado.notin_(_TERMINAL_STATES),
                )
                .all()
            )

            if len(ean_matches) == 1:
                entry = ean_matches[0]
            elif len(ean_matches) > 1:
                # Disambiguation needed
                raise HTTPException(
                    409,
                    detail={
                        "message": f"Múltiples items activos con EAN {codigo}. Escanear por serie.",
                        "items": [
                            {
                                "id": e.id,
                                "serial_number": e.serial_number,
                                "numero_caso": e.numero_caso,
                                "producto_desc": e.producto_desc,
                                "estado": e.estado,
                            }
                            for e in ean_matches
                        ],
                    },
                )

        # 3. Not found at all — check if it's already terminal
        if not entry:
            terminal = (
                self.db.query(ControlDepoItem)
                .filter(
                    or_(
                        ControlDepoItem.serial_number == codigo,
                        ControlDepoItem.ean == codigo,
                    ),
                    ControlDepoItem.estado.in_(_TERMINAL_STATES),
                )
                .first()
            )
            if terminal:
                raise HTTPException(
                    400,
                    f"Item ya procesado (estado: {terminal.estado})",
                )
            raise HTTPException(404, f"No se encontró item activo con código '{codigo}'")

        now = datetime.now(UTC)

        # 4. State transition
        if entry.estado == "pendiente":
            # RMA scan — no operador needed
            old_estado = entry.estado
            entry.estado = "rma"
            entry.pistoleado_rma_por = user.id
            entry.pistoleado_rma_fecha = now
            action = "rma_scan"

        elif entry.estado == "rma":
            # Depósito scan — operador required
            if not operador_id:
                # Tell frontend to ask for operador PIN
                return {
                    "requires_operador": True,
                    "item": self._serialize(entry),
                    "message": "Item requiere escaneo de depósito con PIN de operador",
                }

            operador = self.db.query(Operador).filter(Operador.id == operador_id, Operador.activo.is_(True)).first()
            if not operador:
                raise HTTPException(404, "Operador no encontrado o inactivo")

            old_estado = entry.estado
            entry.estado = "deposito"
            entry.pistoleado_depo_por = user.id
            entry.pistoleado_depo_operador_id = operador_id
            entry.pistoleado_depo_fecha = now
            action = "deposito_scan"

            # Log operator activity
            self.db.add(
                OperadorActividad(
                    operador_id=operador_id,
                    usuario_id=user.id,
                    tab_key="control-deposito",
                    accion="scan_deposito",
                    detalle={
                        "control_depo_item_id": entry.id,
                        "codigo": codigo,
                        "numero_caso": entry.numero_caso,
                        "serial_number": entry.serial_number,
                    },
                )
            )
        else:
            raise HTTPException(400, f"Estado '{entry.estado}' no permite escaneo")

        # Audit trail in RMA historial
        self.db.add(
            RmaCasoHistorial(
                caso_id=entry.caso_id,
                caso_item_id=entry.rma_caso_item_id,
                campo="control_deposito_estado",
                valor_anterior=old_estado,
                valor_nuevo=entry.estado,
                usuario_id=user.id,
            )
        )

        self.db.flush()

        logger.info(
            "Control depósito scan: item %d (%s) → %s by user %d",
            entry.id,
            codigo,
            entry.estado,
            user.id,
        )

        return {
            "requires_operador": False,
            "item": self._serialize(entry),
            "action": action,
            "message": f"Item escaneado → {entry.estado}",
        }

    # ── Mark as "no baja" ─────────────────────────────────

    def marcar_no_baja(
        self,
        item_id: int,
        user: Usuario,
        motivo: str,
    ) -> ControlDepoItem:
        """Mark an item as 'no baja a depósito'. Only from pendiente or rma."""
        entry = self.db.query(ControlDepoItem).filter(ControlDepoItem.id == item_id).first()
        if not entry:
            raise HTTPException(404, f"Item de control #{item_id} no encontrado")

        if entry.estado in _TERMINAL_STATES:
            raise HTTPException(
                400,
                f"Item ya está en estado terminal: {entry.estado}",
            )

        old_estado = entry.estado
        now = datetime.now(UTC)

        entry.estado = "no_baja"
        entry.no_baja_confirmado_por = user.id
        entry.no_baja_fecha = now
        entry.no_baja_motivo = motivo.strip()

        # Audit trail
        self.db.add(
            RmaCasoHistorial(
                caso_id=entry.caso_id,
                caso_item_id=entry.rma_caso_item_id,
                campo="control_deposito_estado",
                valor_anterior=old_estado,
                valor_nuevo="no_baja",
                usuario_id=user.id,
            )
        )

        self.db.flush()

        logger.info(
            "Control depósito no_baja: item %d (caso %s) by user %d — motivo: %s",
            entry.id,
            entry.numero_caso,
            user.id,
            motivo[:100],
        )
        return entry

    # ── List ──────────────────────────────────────────────

    def listar(
        self,
        fecha_desde: Optional[date] = None,
        fecha_hasta: Optional[date] = None,
        estado: Optional[str] = None,
        search: Optional[str] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[ControlDepoItem], int]:
        """Paginated list with filters. Returns (items, total_count)."""
        query = self.db.query(ControlDepoItem)

        if fecha_desde:
            query = query.filter(func.date(ControlDepoItem.created_at) >= fecha_desde)
        if fecha_hasta:
            query = query.filter(func.date(ControlDepoItem.created_at) <= fecha_hasta)
        if estado:
            query = query.filter(ControlDepoItem.estado == estado)
        if search:
            search_term = f"%{search.strip()}%"
            query = query.filter(
                or_(
                    ControlDepoItem.serial_number.ilike(search_term),
                    ControlDepoItem.ean.ilike(search_term),
                    ControlDepoItem.numero_caso.ilike(search_term),
                    ControlDepoItem.producto_desc.ilike(search_term),
                )
            )

        total = query.count()

        items = (
            query.order_by(ControlDepoItem.created_at.desc(), ControlDepoItem.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )

        return items, total

    # ── Stats ─────────────────────────────────────────────

    def stats(
        self,
        fecha_desde: Optional[date] = None,
        fecha_hasta: Optional[date] = None,
    ) -> dict:
        """Count per estado, optionally filtered by date range."""
        query = self.db.query(
            ControlDepoItem.estado,
            func.count(ControlDepoItem.id),
        )

        if fecha_desde:
            query = query.filter(func.date(ControlDepoItem.created_at) >= fecha_desde)
        if fecha_hasta:
            query = query.filter(func.date(ControlDepoItem.created_at) <= fecha_hasta)

        rows = query.group_by(ControlDepoItem.estado).all()

        result = {"pendiente": 0, "rma": 0, "deposito": 0, "no_baja": 0, "total": 0}
        for estado_val, count in rows:
            result[estado_val] = count
            result["total"] += count

        return result

    # ── Serialization ─────────────────────────────────────

    def _serialize(self, entry: ControlDepoItem) -> dict:
        """Serialize a ControlDepoItem to dict."""
        return {
            "id": entry.id,
            "rma_caso_item_id": entry.rma_caso_item_id,
            "caso_id": entry.caso_id,
            "numero_caso": entry.numero_caso,
            "serial_number": entry.serial_number,
            "ean": entry.ean,
            "item_id": entry.item_id,
            "producto_desc": entry.producto_desc,
            "estado": entry.estado,
            "pistoleado_rma_por": entry.pistoleado_rma_por,
            "pistoleado_rma_fecha": entry.pistoleado_rma_fecha.isoformat() if entry.pistoleado_rma_fecha else None,
            "pistoleado_depo_por": entry.pistoleado_depo_por,
            "pistoleado_depo_operador_id": entry.pistoleado_depo_operador_id,
            "pistoleado_depo_fecha": entry.pistoleado_depo_fecha.isoformat() if entry.pistoleado_depo_fecha else None,
            "no_baja_confirmado_por": entry.no_baja_confirmado_por,
            "no_baja_fecha": entry.no_baja_fecha.isoformat() if entry.no_baja_fecha else None,
            "no_baja_motivo": entry.no_baja_motivo,
            "created_at": entry.created_at.isoformat() if entry.created_at else None,
        }
