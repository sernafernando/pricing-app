"""
Estrategia Round Robin para asignación de tickets.

Asigna tickets rotando entre usuarios disponibles en orden.
"""

from typing import Optional
from app.tickets.strategies.asignacion.base import AsignacionStrategy
from app.tickets.models.ticket import Ticket
from app.tickets.models.sector import Sector
from app.tickets.models.asignacion_ticket import AsignacionTicket
from app.models.usuario import Usuario


class RoundRobinStrategy(AsignacionStrategy):
    """
    Asigna tickets de forma rotativa entre usuarios disponibles.

    Algoritmo:
    1. Obtener usuarios disponibles con el permiso requerido
    2. Buscar la última asignación en este sector
    3. Asignar al siguiente usuario en la lista (circular)
    """

    def asignar(self, ticket: Ticket, sector: Sector) -> Optional[Usuario]:
        """Asigna usando round robin"""
        config = sector.configuracion.get("asignacion", {})
        permiso = config.get("solo_con_permiso")

        usuarios_disponibles = self._get_usuarios_disponibles(sector, permiso)

        if not usuarios_disponibles:
            return None

        # Si solo hay uno, asignarle
        if len(usuarios_disponibles) == 1:
            return usuarios_disponibles[0]

        # Obtener última asignación en este sector
        ultima_asignacion = (
            self.db.query(AsignacionTicket)
            .join(Ticket)
            .filter(Ticket.sector_id == sector.id)
            .order_by(AsignacionTicket.id.desc())
            .first()
        )

        # Si no hay asignaciones previas, asignar al primero
        if not ultima_asignacion:
            return usuarios_disponibles[0]

        # Encontrar índice del último asignado
        try:
            idx_actual = next(i for i, u in enumerate(usuarios_disponibles) if u.id == ultima_asignacion.asignado_a_id)
        except StopIteration:
            # El usuario ya no está disponible, empezar desde el principio
            return usuarios_disponibles[0]

        # Siguiente usuario (circular)
        siguiente_idx = (idx_actual + 1) % len(usuarios_disponibles)
        return usuarios_disponibles[siguiente_idx]
