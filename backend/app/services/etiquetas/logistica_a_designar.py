"""The 'A designar' placeholder logística and what "a label without logistics" means for a bulk assignment.

'A designar' is not modeled in code: it is an ordinary `logisticas` row created from the config, used to mark labels
whose carrier is still undecided. For the overwrite guard of the bulk assignment it counts as no logistics at all,
like NULL: assigning over it is not a conflict, and "only the labels without logistics" changes it. It is recognized
by its normalized name (case, accents and repeated spaces ignored); renaming that row makes it an ordinary logística.
"""

import unicodedata
from typing import Optional, Set

from sqlalchemy import or_
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.models.etiqueta_envio import EtiquetaEnvio
from app.models.logistica import Logistica

NOMBRE_A_DESIGNAR = "a designar"


def _normalizar(nombre: str) -> str:
    sin_tildes = "".join(c for c in unicodedata.normalize("NFKD", nombre) if not unicodedata.combining(c))
    return " ".join(sin_tildes.lower().split())


def es_a_designar(nombre: Optional[str]) -> bool:
    """Whether a logística name is the 'A designar' placeholder."""
    return nombre is not None and _normalizar(nombre) == NOMBRE_A_DESIGNAR


def ids_a_designar(db: Session) -> Set[int]:
    """Ids of the placeholder logísticas (active or not): the table is small, so it is read whole."""
    return {id_ for id_, nombre in db.query(Logistica.id, Logistica.nombre).all() if es_a_designar(nombre)}


def sin_logistica(a_designar: Set[int]) -> ColumnElement[bool]:
    """Filter: the label has no logistics, or only the placeholder."""
    if not a_designar:
        return EtiquetaEnvio.logistica_id.is_(None)
    return or_(EtiquetaEnvio.logistica_id.is_(None), EtiquetaEnvio.logistica_id.in_(a_designar))
