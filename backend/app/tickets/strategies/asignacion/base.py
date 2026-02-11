"""
Base abstracta para estrategias de asignación de tickets.

Implementa el patrón Strategy para permitir diferentes
algoritmos de asignación configur

ables por sector.
"""

from abc import ABC, abstractmethod
from typing import Optional, List
from sqlalchemy.orm import Session

from app.tickets.models.ticket import Ticket
from app.tickets.models.sector import Sector
from app.models.usuario import Usuario


class AsignacionStrategy(ABC):
    """
    Clase base abstracta para estrategias de asignación.

    Cada estrategia implementa un algoritmo diferente para
    determinar a qué usuario asignar un ticket.
    """

    def __init__(self, db: Session):
        self.db = db

    @abstractmethod
    def asignar(self, ticket: Ticket, sector: Sector) -> Optional[Usuario]:
        """
        Determina a qué usuario asignar el ticket.

        Args:
            ticket: Ticket a asignar
            sector: Sector del ticket (contiene configuración)

        Returns:
            Usuario al que asignar o None si no se puede asignar
        """
        pass

    def _get_usuarios_disponibles(self, sector: Sector, permiso: Optional[str] = None) -> List[Usuario]:
        """
        Obtiene usuarios disponibles para asignación en un sector.

        Args:
            sector: Sector del ticket
            permiso: Código de permiso requerido (opcional)

        Returns:
            Lista de usuarios disponibles
        """
        # TODO: Implementar filtrado por permisos cuando se integre
        # con el sistema de permisos existente

        # Por ahora retorna todos los usuarios activos
        query = self.db.query(Usuario).filter(Usuario.activo == True)

        # Si hay permiso requerido, filtrar (TODO)
        if permiso:
            # query = query.join(...).filter(tiene_permiso(permiso))
            pass

        return query.all()
