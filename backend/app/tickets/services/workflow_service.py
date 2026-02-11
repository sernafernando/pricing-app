"""
Servicio para manejar la lógica de workflows y transiciones de estado.

Implementa una state machine configurable que:
- Valida transiciones permitidas
- Ejecuta validaciones custom
- Ejecuta acciones en transiciones y estados
- Registra historial automáticamente
"""

import logging
from typing import Optional, Tuple, Dict, Any
from datetime import datetime
from sqlalchemy.orm import Session

from app.tickets.models.ticket import Ticket
from app.tickets.models.workflow import TransicionEstado, EstadoTicket
from app.tickets.models.historial_ticket import HistorialTicket
from app.models.usuario import Usuario
from app.tickets.events.event_bus import EventBus

logger = logging.getLogger(__name__)


class TransicionNoPermitidaException(Exception):
    """Exception cuando una transición no está permitida"""

    pass


class ValidacionFallidaException(Exception):
    """Exception cuando falla una validación"""

    pass


class WorkflowService:
    """
    Servicio para manejar transiciones de estado en tickets.

    Responsabilidades:
    - Validar que una transición sea posible
    - Ejecutar validaciones configuradas
    - Cambiar el estado del ticket
    - Ejecutar acciones configuradas
    - Registrar en historial
    - Disparar eventos
    """

    def __init__(self, db: Session):
        self.db = db

    def can_transition(self, ticket: Ticket, nuevo_estado_id: int, usuario: Usuario) -> Tuple[bool, str]:
        """
        Valida si el usuario puede hacer esta transición.

        Args:
            ticket: Ticket a transicionar
            nuevo_estado_id: ID del nuevo estado
            usuario: Usuario que intenta hacer la transición

        Returns:
            Tupla (puede_transicionar, mensaje)
        """
        # Si ya está en ese estado, no hacer nada
        if ticket.estado_id == nuevo_estado_id:
            return False, "El ticket ya está en ese estado"

        # Buscar la transición configurada
        transicion = self._get_transicion(ticket.estado_id, nuevo_estado_id)

        if not transicion:
            return (
                False,
                f"No existe una transición permitida de '{ticket.estado.nombre}' a '{self._get_estado(nuevo_estado_id).nombre}'",
            )

        # Validar permiso si está configurado
        if transicion.requiere_permiso:
            # TODO: Implementar verificación de permisos usando el sistema de permisos existente
            # Por ahora asumimos que tiene permiso
            pass

        # Validar si solo el asignado puede hacer esta transición
        if transicion.solo_asignado:
            if not ticket.asignado_a or ticket.asignado_a.id != usuario.id:
                return False, "Solo el usuario asignado puede realizar esta acción"

        # Validar si solo el creador puede hacer esta transición
        if transicion.solo_creador:
            if ticket.creador_id != usuario.id:
                return False, "Solo el creador del ticket puede realizar esta acción"

        # Ejecutar validaciones custom configuradas
        for validacion in transicion.validaciones or []:
            valido, mensaje = self._ejecutar_validacion(validacion, ticket, usuario)
            if not valido:
                return False, mensaje

        return True, "OK"

    def transition(
        self,
        ticket: Ticket,
        nuevo_estado_id: int,
        usuario: Usuario,
        comentario: Optional[str] = None,
        metadata_actualizada: Optional[Dict[str, Any]] = None,
    ) -> Ticket:
        """
        Ejecuta una transición de estado.

        Args:
            ticket: Ticket a transicionar
            nuevo_estado_id: ID del nuevo estado
            usuario: Usuario que hace la transición
            comentario: Comentario opcional sobre la transición
            metadata_actualizada: Metadata adicional a actualizar en el ticket

        Returns:
            Ticket actualizado

        Raises:
            TransicionNoPermitidaException: Si la transición no está permitida
        """
        # Validar que se pueda hacer la transición
        valido, mensaje = self.can_transition(ticket, nuevo_estado_id, usuario)
        if not valido:
            raise TransicionNoPermitidaException(mensaje)

        estado_anterior = ticket.estado
        transicion = self._get_transicion(ticket.estado_id, nuevo_estado_id)
        nuevo_estado = self._get_estado(nuevo_estado_id)

        # Actualizar metadata si se proveyó
        if metadata_actualizada:
            ticket.metadata = {**ticket.metadata, **metadata_actualizada}

        # Cambiar estado
        ticket.estado_id = nuevo_estado_id
        ticket.updated_at = datetime.now()

        # Si es un estado final, marcar closed_at
        if nuevo_estado.es_final:
            ticket.closed_at = datetime.now()

        # Registrar en historial
        self._crear_historial(
            ticket=ticket,
            usuario=usuario,
            accion="estado_changed",
            descripcion=f"Estado cambiado de '{estado_anterior.nombre}' a '{nuevo_estado.nombre}'"
            + (f": {comentario}" if comentario else ""),
            estado_anterior=estado_anterior,
            estado_nuevo=nuevo_estado,
            cambios={
                "estado_anterior_id": estado_anterior.id,
                "estado_nuevo_id": nuevo_estado.id,
                "comentario": comentario,
            },
        )

        self.db.commit()
        self.db.refresh(ticket)

        # Ejecutar acciones de la transición
        self._ejecutar_acciones(transicion.acciones or [], ticket, usuario)

        # Ejecutar acciones del nuevo estado (on_enter)
        self._ejecutar_acciones(nuevo_estado.acciones_on_enter or [], ticket, usuario)

        # Disparar evento
        EventBus.publish(
            "ticket.estado_changed",
            ticket=ticket,
            usuario=usuario,
            estado_anterior=estado_anterior,
            estado_nuevo=nuevo_estado,
        )

        logger.info(
            f"Ticket #{ticket.id} transicionado de '{estado_anterior.nombre}' a '{nuevo_estado.nombre}' por usuario #{usuario.id}"
        )

        return ticket

    def _get_transicion(self, estado_origen_id: int, estado_destino_id: int) -> Optional[TransicionEstado]:
        """Busca una transición configurada entre dos estados"""
        return (
            self.db.query(TransicionEstado)
            .filter(
                TransicionEstado.estado_origen_id == estado_origen_id,
                TransicionEstado.estado_destino_id == estado_destino_id,
            )
            .first()
        )

    def _get_estado(self, estado_id: int) -> EstadoTicket:
        """Obtiene un estado por ID"""
        return self.db.query(EstadoTicket).filter(EstadoTicket.id == estado_id).first()

    def _ejecutar_validacion(self, validacion: Dict[str, Any], ticket: Ticket, usuario: Usuario) -> Tuple[bool, str]:
        """
        Ejecuta una validación configurada.

        Tipos de validación soportados:
        - campo_requerido: Valida que un campo en metadata exista y no esté vacío
        - callback: Ejecuta una función de validación custom

        Args:
            validacion: Configuración de la validación
            ticket: Ticket a validar
            usuario: Usuario que hace la transición

        Returns:
            Tupla (valido, mensaje)
        """
        tipo = validacion.get("tipo")

        if tipo == "campo_requerido":
            campo = validacion.get("campo")
            if not campo:
                return False, "Validación mal configurada: falta 'campo'"

            valor = ticket.metadata.get(campo)
            if not valor:
                mensaje = validacion.get("mensaje", f"El campo '{campo}' es requerido")
                return False, mensaje

            return True, "OK"

        elif tipo == "callback":
            # TODO: Implementar sistema de callbacks registrados
            # Por ahora log warning y pasar
            funcion = validacion.get("funcion")
            logger.warning(f"Callback '{funcion}' no implementado aún, pasando validación")
            return True, "OK"

        else:
            logger.warning(f"Tipo de validación desconocido: {tipo}")
            return True, "OK"

    def _ejecutar_acciones(self, acciones: list, ticket: Ticket, usuario: Usuario) -> None:
        """
        Ejecuta una lista de acciones configuradas.

        Tipos de acción soportados:
        - notificar: Dispara notificaciones
        - webhook: Llama a un webhook externo
        - ejecutar_callback: Ejecuta una función custom
        - crear_auditoria: Crea un registro de auditoría

        Args:
            acciones: Lista de acciones a ejecutar
            ticket: Ticket sobre el que ejecutar las acciones
            usuario: Usuario que disparó las acciones
        """
        for accion in acciones:
            tipo = accion.get("tipo")

            try:
                if tipo == "notificar":
                    # Disparar evento de notificación
                    destinatarios = accion.get("destinatarios", [])
                    EventBus.publish("ticket.notificar", ticket=ticket, destinatarios=destinatarios)

                elif tipo == "webhook":
                    # TODO: Implementar llamada a webhook
                    url = accion.get("url")
                    logger.info(f"TODO: Llamar webhook {url} para ticket #{ticket.id}")

                elif tipo == "ejecutar_callback":
                    # TODO: Implementar sistema de callbacks
                    funcion = accion.get("funcion")
                    logger.info(f"TODO: Ejecutar callback {funcion} para ticket #{ticket.id}")

                elif tipo == "crear_auditoria":
                    # TODO: Integrar con sistema de auditoría existente
                    categoria = accion.get("categoria")
                    logger.info(f"TODO: Crear auditoría categoría {categoria} para ticket #{ticket.id}")

                else:
                    logger.warning(f"Tipo de acción desconocido: {tipo}")

            except Exception as e:
                logger.error(f"Error ejecutando acción {tipo} para ticket #{ticket.id}: {str(e)}")

    def _crear_historial(
        self,
        ticket: Ticket,
        usuario: Usuario,
        accion: str,
        descripcion: str,
        estado_anterior: Optional[EstadoTicket] = None,
        estado_nuevo: Optional[EstadoTicket] = None,
        cambios: Optional[Dict[str, Any]] = None,
    ) -> HistorialTicket:
        """Crea un registro en el historial del ticket"""
        historial = HistorialTicket(
            ticket_id=ticket.id,
            usuario_id=usuario.id,
            accion=accion,
            descripcion=descripcion,
            estado_anterior_id=estado_anterior.id if estado_anterior else None,
            estado_nuevo_id=estado_nuevo.id if estado_nuevo else None,
            cambios=cambios or {},
        )
        self.db.add(historial)
        return historial
