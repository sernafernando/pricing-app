"""
Schemas y helpers de configuración del módulo compras (design §1.8, D10).

Expone:
  - `ConfiguracionToleranciaResponse`: schema de lectura para el admin UI.
  - `leer_configuracion(db, clave, default)`: helper server-side que
    lee una clave de la tabla `configuracion` y la convierte a `Decimal`.
    Usado por el servicio de reconciliación para obtener la tolerancia
    por moneda (claves `compras.cc_reconciliacion_tolerancia_ars` /
    `_usd`, sembradas por compras_012).
"""

from decimal import Decimal, InvalidOperation

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session


class ConfiguracionToleranciaResponse(BaseModel):
    """Fila de `configuracion` expuesta al admin UI."""

    clave: str = Field(..., max_length=100)
    valor: str
    descripcion: str | None = None

    model_config = ConfigDict(from_attributes=True)


def leer_configuracion(db: Session, clave: str, default: Decimal) -> Decimal:
    """Leer una clave de la tabla `configuracion` y convertirla a Decimal.

    Si la clave no existe o el valor no parsea a Decimal, retorna
    `default` (no lanza). Pensada para valores numéricos (tolerancias,
    límites). Para strings libres, acceder directo al modelo.

    Args:
        db: Session SQLAlchemy activa.
        clave: PK en `configuracion` (ej. "compras.cc_reconciliacion_tolerancia_ars").
        default: valor a retornar si no está seteado o no parsea.

    Returns:
        Valor como Decimal, o `default` en fallback.
    """
    # Import local para no crear ciclo a nivel módulo con app.models
    from app.models.configuracion import Configuracion

    fila = db.query(Configuracion).filter(Configuracion.clave == clave).first()
    if fila is None or fila.valor is None:
        return default
    try:
        return Decimal(str(fila.valor))
    except (InvalidOperation, ValueError):
        return default
