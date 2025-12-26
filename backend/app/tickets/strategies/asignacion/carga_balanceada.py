"""
Estrategia de Carga Balanceada para asignación de tickets.

Asigna tickets al usuario con menos tickets activos.
"""
from typing import Optional
from sqlalchemy import func
from app.tickets.strategies.asignacion.base import AsignacionStrategy
from app.tickets.models.ticket import Ticket
from app.tickets.models.sector import Sector
from app.tickets.models.asignacion_ticket import AsignacionTicket
from app.tickets.models.workflow import EstadoTicket
from app.models.usuario import Usuario


class CargaBalanceadaStrategy(AsignacionStrategy):
    """
    Asigna tickets al usuario con menor carga de trabajo.
    
    Algoritmo:
    1. Obtener usuarios disponibles
    2. Contar tickets activos (no en estado final) por usuario en este sector
    3. Asignar al usuario con menos tickets activos
    """
    
    def asignar(self, ticket: Ticket, sector: Sector) -> Optional[Usuario]:
        """Asigna al usuario con menos tickets activos"""
        config = sector.configuracion.get('asignacion', {})
        permiso = config.get('solo_con_permiso')
        
        usuarios_disponibles = self._get_usuarios_disponibles(sector, permiso)
        
        if not usuarios_disponibles:
            return None
        
        if len(usuarios_disponibles) == 1:
            return usuarios_disponibles[0]
        
        # Contar tickets activos por usuario en este sector
        carga = self.db.query(
            AsignacionTicket.asignado_a_id,
            func.count(AsignacionTicket.id).label('cantidad')
        ).join(Ticket)\
         .join(EstadoTicket, Ticket.estado_id == EstadoTicket.id)\
         .filter(
             Ticket.sector_id == sector.id,
             EstadoTicket.es_final == False,
             AsignacionTicket.fecha_finalizacion == None
         )\
         .group_by(AsignacionTicket.asignado_a_id)\
         .all()
        
        # Convertir a dict {usuario_id: cantidad_tickets}
        carga_dict = {usuario_id: count for usuario_id, count in carga}
        
        # Encontrar usuario con menor carga (0 si no tiene tickets)
        usuario_menor_carga = min(
            usuarios_disponibles,
            key=lambda u: carga_dict.get(u.id, 0)
        )
        
        return usuario_menor_carga
