"""The single definition of what one shipping label COSTS US.

Two screens already answer this question -- the Etiquetas statistics and
export views -- and the ML sales breakdown is the third. Three answers to
"what did this shipment cost" is the two-numbers-for-one-sale failure the
breakdown module's own docstring calls the worst outcome available, so the
rules live here once and every caller reads them from here.

Two rules, both learned the expensive way:

1. THE CORDON STRINGS DO NOT MATCH ACROSS TABLES. `cp_cordones.cordon`
   stores `"Cordón 1"` (with the accent); `logistica_costo_cordon.cordon`
   stores `"Cordon 1"` (without it). Joining them raw matches NOTHING, so
   every Flex sale without a `costo_override` silently resolves to "cost
   unknown" -- the tariff path, which is the ordinary case, never fires.
   Three call sites already carried their own `func.replace(...)` to work
   around this; this module is where that stops being copied.

2. THE TARIFF'S `costo` IS NOT THE COST. A turbo shipment is billed at
   `costo_turbo`, and a turbo shipment on a rainy day carries a configured
   surcharge on top. Reading the plain `costo` column produces a number
   that disagrees with what the Etiquetas screen shows for the very same
   `shipping_id`.

`costo_efectivo` below is the Python mirror of `_build_costo_case`, the SQL
expression the Etiquetas endpoints use. They cannot be one implementation
-- one has to run inside a query and the other over already-loaded rows --
so `tests/services/test_logistica_costo_service.py` pins them to agree on
the same inputs. If you change one, that test fails until you change both.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.configuracion import Configuracion

# `cp_cordones` writes the accent, `logistica_costo_cordon` does not.
_CORDON_ACCENT = "ó"
_CORDON_PLAIN = "o"


def normalizar_cordon(cordon: Optional[str]) -> Optional[str]:
    """A `cp_cordones.cordon` value in `logistica_costo_cordon` spelling."""
    if cordon is None:
        return None
    return cordon.replace(_CORDON_ACCENT, _CORDON_PLAIN)


def cordon_normalizado_sql(columna: Any) -> Any:
    """`normalizar_cordon` as a SQL expression, for joins that normalise
    inside the query instead of in Python."""
    return func.replace(columna, _CORDON_ACCENT, _CORDON_PLAIN)


def _a_decimal(valor: Any) -> Optional[Decimal]:
    if valor is None:
        return None
    return Decimal(str(valor))


def costo_efectivo(
    *,
    costo_override: Any = None,
    es_turbo: bool = False,
    es_lluvia: bool = False,
    costo: Any = None,
    costo_turbo: Any = None,
    lluvia_tipo: str = "fijo",
    lluvia_valor: float = 0.0,
) -> Optional[Decimal]:
    """What this label costs us, in the same order of precedence the
    Etiquetas screens apply:

    1. `costo_override` wins outright when set -- a human typed it.
    2. turbo + lluvia -> `costo_turbo` plus the configured surcharge
       (`fijo` adds an amount, `porcentaje` adds a percentage).
    3. turbo -> `costo_turbo`, falling back to `costo` when the tariff row
       carries no turbo price.
    4. otherwise -> `costo`.

    Returns `None` when nothing resolves. That is deliberate and must stay:
    a `Decimal("0")` here would render as a shipment that cost us nothing,
    which is a lie a reader cannot detect.
    """
    return _al_centavo(
        _costo_sin_redondear(
            costo_override=costo_override,
            es_turbo=es_turbo,
            es_lluvia=es_lluvia,
            costo=costo,
            costo_turbo=costo_turbo,
            lluvia_tipo=lluvia_tipo,
            lluvia_valor=lluvia_valor,
        )
    )


def _al_centavo(valor: Optional[Decimal]) -> Optional[Decimal]:
    """The cent, ONCE, on the way out.

    `_build_costo_case` casts to `Numeric(12, 2)` in EVERY branch, so every
    branch here has to land on the same cent. Rounding only the one branch
    that happened to be covered by a test is how the first version of this
    shipped: the percentage case agreed while the plain and fixed-surcharge
    cases quietly differed by fractions on any tariff that is not round.
    Quantizing at the single exit makes a new branch correct by
    construction instead of by remembering.
    """
    if valor is None:
        return None
    return valor.quantize(Decimal("0.01"))


def _costo_sin_redondear(
    *,
    costo_override: Any,
    es_turbo: bool,
    es_lluvia: bool,
    costo: Any,
    costo_turbo: Any,
    lluvia_tipo: str,
    lluvia_valor: float,
) -> Optional[Decimal]:
    """The precedence itself. Rounding is the caller's single exit above."""
    override = _a_decimal(costo_override)
    if override is not None:
        return override

    normal = _a_decimal(costo)
    turbo = _a_decimal(costo_turbo)

    if not es_turbo:
        return normal

    turbo_efectivo = turbo if turbo is not None else normal
    if turbo_efectivo is None:
        return None

    if not es_lluvia or lluvia_valor <= 0:
        return turbo_efectivo

    recargo = Decimal(str(lluvia_valor))
    if lluvia_tipo == "porcentaje":
        return turbo_efectivo * (Decimal("1") + recargo / Decimal("100"))
    return turbo_efectivo + recargo


def get_lluvia_config(db: Session) -> tuple[str, float]:
    """The configured rain surcharge, as `(tipo, valor)`.

    Lives here rather than behind a private helper in `api/endpoints/`
    because a service must not reach up into the endpoint layer to learn a
    business rule. Defaults to `("fijo", 0.0)` -- no surcharge -- when the
    configuration is absent or unparseable, so a missing row cannot inflate
    a cost.
    """
    tipo_row = db.query(Configuracion.valor).filter(Configuracion.clave == "lluvia_offset_tipo").first()
    valor_row = db.query(Configuracion.valor).filter(Configuracion.clave == "lluvia_offset_valor").first()
    tipo = tipo_row[0] if tipo_row else "fijo"
    try:
        valor = float(valor_row[0]) if valor_row else 0.0
    except (ValueError, TypeError):
        valor = 0.0
    return tipo, valor
