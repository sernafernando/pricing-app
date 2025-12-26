"""
Servicio para manejar la asignación de tickets a usuarios.

Usa el patrón Strategy para soportar diferentes algoritmos de asignación:
- Round Robin
- Basado en Carga
- Basado en Skills
- Manual
"""
import logging
from typing import Optional
from datetime import datetime
from sqlalchemy.orm import Session

from app.tickets.models.ticket import Ticket
from app.tickets.models.asignacion_ticket import AsignacionTicket, TipoAsignacion
from app.models.usuario import Usuario
from app.tickets.strategies.asignacion import (
    RoundRobinStrategy,
    CargaBalanceadaStrategy,
    SkillBasedStrategy
)
from app.tickets.events.event_bus import EventBus

logger = logging.getLogger(__name__)


class AsignacionService:
    """
    Servicio para asignar tickets a usuarios.
    
    Responsabilidades:
    - Asignación automática según configuración del sector
    - Asignación manual
    - Reasignación
    - Escalamiento
    - Registro de historial de asignaciones
    """
    
    # Mapeo de nombres de estrategias a clases
    STRATEGIES = {
        "round_robin": RoundRobinStrategy,
        "basado_en_carga": CargaBalanceadaStrategy,
        "basado_en_skills": SkillBasedStrategy,
        "manual": None,  # No auto-asigna
    }
    
    def __init__(self, db: Session):
        self.db = db
    
    def asignar_automaticamente(self, ticket: Ticket) -> Optional[AsignacionTicket]:
        """
        Asigna ticket automáticamente según configuración del sector.
        
        Args:
            ticket: Ticket a asignar
        
        Returns:
            AsignacionTicket creado o None si no se pudo/debía asignar
        """
        sector = ticket.sector
        config = sector.configuracion.get('asignacion', {})
        
        # Verificar si debe auto-asignar
        if not config.get('auto_assign', False):
            logger.info(f"Auto-asignación desactivada para sector {sector.codigo}")
            return None
        
        # Obtener tipo de estrategia
        strategy_name = config.get('tipo', 'round_robin')
        strategy_class = self.STRATEGIES.get(strategy_name)
        
        if strategy_class is None:
            logger.info(f"Estrategia '{strategy_name}' no auto-asigna (manual)")
            return None
        
        # Ejecutar estrategia
        strategy = strategy_class(self.db)
        usuario_asignado = strategy.asignar(ticket, sector)
        
        if not usuario_asignado:
            logger.warning(f"No se pudo encontrar usuario para asignar ticket #{ticket.id}")
            return None
        
        # Asignar
        asignacion = self._asignar_ticket(
            ticket=ticket,
            usuario_asignado=usuario_asignado,
            asignado_por=None,  # Automático
            tipo=TipoAsignacion.AUTOMATICO,
            motivo=f"Asignación automática ({strategy_name})"
        )
        
        logger.info(f"Ticket #{ticket.id} auto-asignado a usuario #{usuario_asignado.id} usando {strategy_name}")
        
        return asignacion
    
    def asignar_manual(
        self,
        ticket: Ticket,
        usuario_asignado: Usuario,
        asignado_por: Usuario,
        motivo: Optional[str] = None
    ) -> AsignacionTicket:
        """
        Asigna ticket manualmente.
        
        Args:
            ticket: Ticket a asignar
            usuario_asignado: Usuario al que asignar
            asignado_por: Usuario que hace la asignación
            motivo: Motivo opcional
        
        Returns:
            AsignacionTicket creada
        """
        asignacion = self._asignar_ticket(
            ticket=ticket,
            usuario_asignado=usuario_asignado,
            asignado_por=asignado_por,
            tipo=TipoAsignacion.MANUAL,
            motivo=motivo
        )
        
        logger.info(f"Ticket #{ticket.id} asignado manualmente a usuario #{usuario_asignado.id} por #{asignado_por.id}")
        
        return asignacion
    
    def reasignar(
        self,
        ticket: Ticket,
        nuevo_usuario: Usuario,
        usuario_que_reasigna: Usuario,
        motivo: Optional[str] = None
    ) -> AsignacionTicket:
        """
        Reasigna un ticket a otro usuario.
        
        Args:
            ticket: Ticket a reasignar
            nuevo_usuario: Nuevo usuario asignado
            usuario_que_reasigna: Usuario que hace la reasignación
            motivo: Motivo de la reasignación
        
        Returns:
            Nueva AsignacionTicket
        """
        # Finalizar asignación actual si existe
        asignacion_actual = ticket.asignacion_actual
        if asignacion_actual:
            asignacion_actual.fecha_finalizacion = datetime.now()
            self.db.add(asignacion_actual)
        
        # Crear nueva asignación
        nueva_asignacion = AsignacionTicket(
            ticket_id=ticket.id,
            asignado_a_id=nuevo_usuario.id,
            asignado_por_id=usuario_que_reasigna.id,
            tipo=TipoAsignacion.REASIGNACION,
            motivo=motivo or "Reasignación manual"
        )
        self.db.add(nueva_asignacion)
        self.db.commit()
        self.db.refresh(nueva_asignacion)
        
        # Disparar eventos
        EventBus.publish(
            "ticket.reassigned",
            ticket=ticket,
            usuario_anterior=asignacion_actual.asignado_a if asignacion_actual else None,
            usuario_nuevo=nuevo_usuario,
            reasignado_por=usuario_que_reasigna
        )
        
        logger.info(f"Ticket #{ticket.id} reasignado de usuario #{asignacion_actual.asignado_a_id if asignacion_actual else 'N/A'} a #{nuevo_usuario.id}")
        
        return nueva_asignacion
    
    def escalar(
        self,
        ticket: Ticket,
        usuario_escalador: Usuario,
        nivel_escalamiento: str = "supervisor",
        motivo: Optional[str] = None
    ) -> AsignacionTicket:
        """
        Escala un ticket a un nivel superior.
        
        Args:
            ticket: Ticket a escalar
            usuario_escalador: Usuario que escala
            nivel_escalamiento: Nivel al que escalar (supervisor, gerente, etc.)
            motivo: Motivo del escalamiento
        
        Returns:
            Nueva AsignacionTicket
        """
        # TODO: Implementar lógica de escalamiento jerárquico
        # Por ahora, simplemente lo marca como escalamiento
        
        # Finalizar asignación actual
        asignacion_actual = ticket.asignacion_actual
        if asignacion_actual:
            asignacion_actual.fecha_finalizacion = datetime.now()
            self.db.add(asignacion_actual)
        
        # TODO: Determinar supervisor/gerente según jerarquía
        # Por ahora dejamos sin asignar y se debe asignar manualmente
        
        nueva_asignacion = AsignacionTicket(
            ticket_id=ticket.id,
            asignado_a_id=None,  # TODO: Asignar a supervisor/gerente
            asignado_por_id=usuario_escalador.id,
            tipo=TipoAsignacion.ESCALAMIENTO,
            motivo=motivo or f"Escalado a {nivel_escalamiento}"
        )
        self.db.add(nueva_asignacion)
        self.db.commit()
        self.db.refresh(nueva_asignacion)
        
        # Disparar evento
        EventBus.publish(
            "ticket.escalado",
            ticket=ticket,
            escalado_por=usuario_escalador,
            nivel=nivel_escalamiento
        )
        
        logger.info(f"Ticket #{ticket.id} escalado a {nivel_escalamiento} por usuario #{usuario_escalador.id}")
        
        return nueva_asignacion
    
    def _asignar_ticket(
        self,
        ticket: Ticket,
        usuario_asignado: Usuario,
        asignado_por: Optional[Usuario],
        tipo: TipoAsignacion,
        motivo: Optional[str]
    ) -> AsignacionTicket:
        """
        Método interno para crear una asignación.
        
        Maneja:
        - Finalizar asignación anterior si existe
        - Crear nueva asignación
        - Disparar eventos
        """
        # Finalizar asignación actual si existe
        asignacion_actual = ticket.asignacion_actual
        if asignacion_actual:
            asignacion_actual.fecha_finalizacion = datetime.now()
            self.db.add(asignacion_actual)
        
        # Crear nueva asignación
        nueva_asignacion = AsignacionTicket(
            ticket_id=ticket.id,
            asignado_a_id=usuario_asignado.id,
            asignado_por_id=asignado_por.id if asignado_por else None,
            tipo=tipo,
            motivo=motivo
        )
        self.db.add(nueva_asignacion)
        self.db.commit()
        self.db.refresh(nueva_asignacion)
        
        # Disparar evento
        EventBus.publish(
            "ticket.assigned",
            ticket=ticket,
            usuario_asignado=usuario_asignado,
            asignado_por=asignado_por,
            tipo=tipo
        )
        
        return nueva_asignacion
