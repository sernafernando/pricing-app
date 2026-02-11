"""
Event Bus simple para desacoplar componentes del sistema de tickets.

Permite publicar eventos y subscribirse a ellos sin dependencias externas.
Los handlers se ejecutan síncronamente pero pueden extenderse a async.

Eventos disponibles:
- ticket.created: Se crea un nuevo ticket
- ticket.assigned: Se asigna un ticket a un usuario
- ticket.reassigned: Se reasigna un ticket
- ticket.estado_changed: Cambia el estado de un ticket
- ticket.comentado: Se agrega un comentario
- ticket.closed: Se cierra un ticket
- ticket.escalado: Se escala un ticket
"""

import logging
from typing import Callable, Dict, List, Any

logger = logging.getLogger(__name__)


class EventBus:
    """
    Event bus simple en memoria para desacoplar componentes.

    Uso:
        # Registrar handler
        EventBus.subscribe("ticket.created", on_ticket_created_handler)

        # Publicar evento
        EventBus.publish("ticket.created", ticket=ticket_obj, usuario=user_obj)
    """

    _handlers: Dict[str, List[Callable]] = {}

    @classmethod
    def subscribe(cls, event_type: str, handler: Callable) -> None:
        """
        Registra un handler para un tipo de evento.

        Args:
            event_type: Tipo de evento (ej: "ticket.created")
            handler: Función que manejará el evento
        """
        if event_type not in cls._handlers:
            cls._handlers[event_type] = []

        if handler not in cls._handlers[event_type]:
            cls._handlers[event_type].append(handler)
            logger.info(f"Handler {handler.__name__} registrado para evento '{event_type}'")

    @classmethod
    def unsubscribe(cls, event_type: str, handler: Callable) -> None:
        """
        Desregistra un handler de un tipo de evento.

        Args:
            event_type: Tipo de evento
            handler: Función a desregistrar
        """
        if event_type in cls._handlers and handler in cls._handlers[event_type]:
            cls._handlers[event_type].remove(handler)
            logger.info(f"Handler {handler.__name__} desregistrado del evento '{event_type}'")

    @classmethod
    def publish(cls, event_type: str, **payload: Any) -> None:
        """
        Publica un evento y ejecuta todos los handlers registrados.

        Los handlers se ejecutan síncronamente en el orden de registro.
        Si un handler falla, se loguea el error pero no detiene la ejecución
        de los demás handlers.

        Args:
            event_type: Tipo de evento a publicar
            **payload: Datos del evento (keyword arguments)
        """
        handlers = cls._handlers.get(event_type, [])

        if not handlers:
            logger.debug(f"No hay handlers registrados para evento '{event_type}'")
            return

        logger.info(f"Publicando evento '{event_type}' a {len(handlers)} handler(s)")

        for handler in handlers:
            try:
                handler(**payload)
            except Exception as e:
                logger.error(f"Error en handler {handler.__name__} para evento '{event_type}': {str(e)}", exc_info=True)

    @classmethod
    def clear(cls) -> None:
        """Limpia todos los handlers registrados (útil para testing)"""
        cls._handlers.clear()
        logger.info("Todos los handlers del EventBus han sido limpiados")

    @classmethod
    def get_handlers(cls, event_type: str) -> List[Callable]:
        """Retorna los handlers registrados para un tipo de evento"""
        return cls._handlers.get(event_type, []).copy()
