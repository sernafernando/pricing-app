"""
Estrategia basada en Skills/Competencias para asignación de tickets.

Asigna tickets según habilidades o asignaciones específicas (ej: Product Managers por marca).
"""

from typing import Optional
from app.tickets.strategies.asignacion.base import AsignacionStrategy
from app.tickets.strategies.asignacion.carga_balanceada import CargaBalanceadaStrategy
from app.tickets.models.ticket import Ticket
from app.tickets.models.sector import Sector
from app.tickets.models.marca_pm import MarcaPM
from app.models.usuario import Usuario


class SkillBasedStrategy(AsignacionStrategy):
    """
    Asigna tickets según skills o asignaciones específicas.

    Algoritmo:
    1. Lee el campo configurado en sector.configuracion.asignacion.skill_field
    2. Busca en la metadata del ticket ese campo
    3. Busca el usuario asignado a ese skill (ej: PM de esa marca)
    4. Si no encuentra, hace fallback a la estrategia configurada

    Ejemplo: Para sector Pricing con skill_field="marca_id":
    - Lee marca_id de ticket.metadata
    - Busca en MarcaPM el PM asignado a esa marca
    - Si no hay, usa fallback (default: carga_balanceada)
    """

    def asignar(self, ticket: Ticket, sector: Sector) -> Optional[Usuario]:
        """Asigna basado en skills"""
        config = sector.configuracion.get("asignacion", {})
        skill_field = config.get("skill_field")
        fallback_strategy_name = config.get("fallback", "basado_en_carga")

        # Si no hay skill_field configurado, ir directo al fallback
        if not skill_field:
            return self._fallback(ticket, sector, fallback_strategy_name)

        # Leer el valor del skill desde metadata
        skill_value = ticket.metadata.get(skill_field)

        if not skill_value:
            # No hay valor, usar fallback
            return self._fallback(ticket, sector, fallback_strategy_name)

        # Buscar usuario asignado según el skill
        # TODO: Esto debería ser más genérico, por ahora hardcodeado para marca_id
        if skill_field == "marca_id":
            usuario = self._get_pm_por_marca(skill_value)
            if usuario:
                return usuario

        # Si no se encontró, usar fallback
        return self._fallback(ticket, sector, fallback_strategy_name)

    def _get_pm_por_marca(self, marca_id: int) -> Optional[Usuario]:
        """Busca el Product Manager asignado a una marca"""
        marca_pm = self.db.query(MarcaPM).filter(MarcaPM.marca_id == marca_id).first()

        if marca_pm and marca_pm.usuario:
            return marca_pm.usuario

        return None

    def _fallback(self, ticket: Ticket, sector: Sector, strategy_name: str) -> Optional[Usuario]:
        """Ejecuta estrategia de fallback"""
        if strategy_name == "round_robin":
            from app.tickets.strategies.asignacion.round_robin import RoundRobinStrategy

            strategy = RoundRobinStrategy(self.db)
        else:  # default: basado_en_carga
            strategy = CargaBalanceadaStrategy(self.db)

        return strategy.asignar(ticket, sector)
