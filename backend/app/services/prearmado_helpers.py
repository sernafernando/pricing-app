"""
Helpers puros para el feature de Prearmado de Combos.

Contiene:
- `parse_windows_suffix`: detecta sufijo WH/WP del item_code del combo (Win11 implícito).
- `generar_codigo_prearmado`: genera código único legible vía secuencia Postgres.
"""

from datetime import datetime
from typing import Literal, Optional

import pytz
from sqlalchemy import text
from sqlalchemy.orm import Session


ARGENTINA_TZ = pytz.timezone("America/Argentina/Buenos_Aires")


def parse_windows_suffix(item_code: Optional[str]) -> Optional[Literal["home", "pro"]]:
    """
    Detecta el sufijo de Windows en el `item_code` del combo (case-insensitive).

    Reglas:
    - Termina en `WH` → 'home'
    - Termina en `WP` → 'pro'
    - Cualquier otro caso (None, vacío, otro sufijo) → None

    Win11 NO es un item real en el ERP — es metadata derivada del SKU.
    """
    if not item_code:
        return None
    code_upper = item_code.strip().upper()
    if code_upper.endswith("WH"):
        return "home"
    if code_upper.endswith("WP"):
        return "pro"
    return None


def generar_codigo_prearmado(db: Session) -> str:
    """
    Genera un código único legible para un nuevo prearmado.

    Formato: `PRA-YYYY-NNNNNN` (año en Argentina + seis dígitos del seq).
    La secuencia Postgres `prearmados_codigo_seq` garantiza atomicidad sin race conditions.

    Args:
        db: sesión SQLAlchemy ya abierta — no se commitea acá.
    """
    seq_value = db.execute(text("SELECT nextval('prearmados_codigo_seq')")).scalar()
    year = datetime.now(ARGENTINA_TZ).year
    return f"PRA-{year}-{seq_value:06d}"
