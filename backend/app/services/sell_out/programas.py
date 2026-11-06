"""Sell-out programs, read only: the legacy higher level that grouped campaigns ("Programa" on screen until the
tab went away; the tactical is the brand's program now).

Programs are no longer created, edited or assigned from the app. Stored ones stay as they are: a campaign keeps its
`programa_id`, its renewal keeps it too (`renovacion.borrador`), and the campaign list still filters by it. No
allocator, cap or money path reads `programa_id`.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.sell_out import SellOutCampana, SellOutPrograma


class ProgramaError(ValueError):
    """The request cannot be served as asked (a 422); the message is for the operator."""


class ProgramaNoExiste(ProgramaError):
    """The program does not exist (a 404)."""


def validar_asignable(db: Session, programa_id: int) -> SellOutPrograma:
    """The program, which may take campaigns, share-locked until commit so it is not archived meanwhile.
    `ProgramaNoExiste` for an unknown one; a `ProgramaError` (422) for an archived one."""
    programa = db.query(SellOutPrograma).filter(SellOutPrograma.id == programa_id).with_for_update(read=True).first()
    if programa is None:
        raise ProgramaNoExiste(f"El programa {programa_id} no existe.")
    if programa.estado == "archivado":
        raise ProgramaError(f"El programa «{programa.nombre}» está archivado.")
    return programa


def programas_de(db: Session, campanas: list[SellOutCampana]) -> dict[int, dict]:
    """`{programa_id: {id, nombre}}` of the programs these campaigns belong to, in one query."""
    ids = {c.programa_id for c in campanas if c.programa_id is not None}
    if not ids:
        return {}
    rows = db.query(SellOutPrograma.id, SellOutPrograma.nombre).filter(SellOutPrograma.id.in_(ids))
    return {pid: {"id": pid, "nombre": nombre} for pid, nombre in rows}
