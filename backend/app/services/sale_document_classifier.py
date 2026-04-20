"""
sale_document_classifier — predicados semánticos sobre tb_sale_document (ERP).

Clasifica un `SaleDocument` (réplica local del catálogo `tbSaleDocument` del
ERP) por sus flags booleanos — SIN listas hardcodeadas de `sd_id`. La única
excepción documentada es `hacc_group == 20101` para identificar el bucket
contable "Saldo / Ajuste" (no un sd_id, un grupo contable explicitado en el
ERP).

Contrato del design §2.1:
  - `clasificar_documento_compra(sd)`: devuelve el enum con la semántica del
    documento para el módulo de compras.
  - `afecta_cc_proveedor(sd)`: si un documento de ese tipo debe generar
    movimiento en `cc_proveedor_movimientos`.
  - `signo_contable(sd)`: delega a `sd.sd_plusorminus` — no lo reinventamos.
  - `es_anulacion(sd)`: `sd.sd_isannulment`.
  - `es_contraparte_de(sd, sd_base)`: predicado binario (heurística del
    design §2.1).
  - `es_contraparte(sd, session)`: helper que busca en DB si `sd` es
    contraparte de algún otro `SaleDocument` con `hacc_group` común y
    `sd_plusorminus` invertido. Útil para auditoría puntual.

Política sobre sd_id AMBIGUOS (Engram #124):
Los sd_id marcados como AMBIGUO en `compras_009_seed_tb_sale_document.py`
(flags inferidos, sin confirmación del usuario sobre uso real) emiten un
`logger.warning` cuando el clasificador los procesa. La clasificación NO se
altera, solo queda traza para auditoría posterior.

Referencias:
  - design.md §2.1 (orden de evaluación de predicados)
  - Engram obs #106 (fuente de datos del seed)
  - Engram obs #121 (decisión: seed estático, sin sync)
  - Engram obs #124 (decisión: 13 sd_id ambiguos con warning)
  - tasks.md COMPRAS-2.1
"""

from __future__ import annotations

from enum import Enum
from typing import Final

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.tb_sale_document import SaleDocument

logger = get_logger("services.sale_document_classifier")


class ClasificacionDocCompra(str, Enum):
    """
    Clasificación semántica de un documento del ERP para el módulo de compras.

    Valores según design §2.1. `UNKNOWN` existe como último recurso para
    detectar regresión — si el clasificador lo devuelve para un `sd_id` del
    seed, hay que revisar predicados. En v1, con el seed actual, NO debería
    aparecer nunca (el fallback es `IGNORAR`).
    """

    FACTURA = "FACTURA"
    NC = "NC"
    ND = "ND"
    REMITO = "REMITO"
    ORDEN_PAGO = "ORDEN_PAGO"
    ANULACION = "ANULACION"
    CONTRAPARTE = "CONTRAPARTE"
    AJUSTE_SALDO = "AJUSTE_SALDO"
    PRESUPUESTO = "PRESUPUESTO"
    IGNORAR = "IGNORAR"
    UNKNOWN = "UNKNOWN"


# ──────────────────────────────────────────────────────────────────────────
# Constantes
# ──────────────────────────────────────────────────────────────────────────

# `hacc_group` contable del ERP para "Saldos / Ajustes de cuenta" —
# documentado en design §2.1. Única excepción al "no números mágicos".
HACC_GROUP_AJUSTE_SALDO: Final[int] = 20101

# 13 sd_id cuya clasificación se infirió en Batch 1B por falta de
# confirmación del usuario (Engram #124). Al clasificarlos emitimos
# `logger.warning` para auditoría — la clasificación NO se altera.
SD_IDS_AMBIGUOS: Final[frozenset[int]] = frozenset({7, 15, 31, 33, 80, 125, 131, 145, 205, 301, 302, 350, 500})


# ──────────────────────────────────────────────────────────────────────────
# Predicados públicos
# ──────────────────────────────────────────────────────────────────────────


def clasificar_documento_compra(
    sd: SaleDocument,
    session: Session | None = None,
) -> ClasificacionDocCompra:
    """
    Devuelve la clasificación semántica del documento para el módulo compras.

    Orden de evaluación (design §2.1, mutuamente excluyente):
        1. IGNORAR    — si no es purchase.
        2. ANULACION  — si `sd_isannulment`.
        3. CONTRAPARTE — si se pasó `session` y `es_contraparte(sd, session)`
           retorna True (requiere consulta DB — por eso es opcional).
        4. PRESUPUESTO — si `sd_isquotation`.
        5. REMITO     — si `sd_ispackinglist`.
        6. NC         — si `sd_iscreditnote`.
        7. ND         — si `sd_isdebitnote`.
        8. ORDEN_PAGO — si `sd_isreceipt` (en compras, "recibo" = OP del
           proveedor).
        9. AJUSTE_SALDO — si `hacc_group == 20101`.
       10. FACTURA    — si `sd_isinbalance` AND `sd_istaxable`.
       11. IGNORAR    — fallback.

    **Backward-compat**: si `session` es `None` (comportamiento histórico),
    se salta el paso 3 y los documentos contraparte se clasifican como su
    tipo base (ej: sd_id=161 → FACTURA). El flujo principal de matching ERP
    usa la vista SQL `v_facturas_compra_vigentes` que YA excluye contrapartes
    a nivel DB (design §4.1), por lo que la clasificación Python no es el
    único filtro financiero.

    Cuando el caller SÍ necesita la semántica CONTRAPARTE (ej: auditoría,
    dashboards uno-a-uno), pasar la `session` SQLAlchemy para que el
    clasificador consulte el par inverso (convenio "sd_id mayor gana" del
    design §2.1 + RD3).

    Si `sd.sd_id` está en `SD_IDS_AMBIGUOS`, se emite un `logger.warning`
    con la clasificación resultante para auditoría (Engram #124).

    Args:
        sd: fila de `tb_sale_document`.
        session: sesión SQLAlchemy opcional para detectar CONTRAPARTE por
            lookup. Si es None (default), no se detecta contraparte.

    Returns:
        ClasificacionDocCompra correspondiente.
    """
    resultado = _clasificar_impl(sd, session=session)

    if sd.sd_id in SD_IDS_AMBIGUOS:
        logger.warning(
            "sd_id=%s ('%s') marcado como AMBIGUO — clasificación inferida: %s. "
            "Revisar cuando aparezca en datos reales (Engram #124).",
            sd.sd_id,
            sd.sd_desc,
            resultado.value,
        )

    return resultado


def _clasificar_impl(
    sd: SaleDocument,
    session: Session | None = None,
) -> ClasificacionDocCompra:
    """Implementación del algoritmo de clasificación.

    El paso CONTRAPARTE requiere una sesión SQLAlchemy activa (para buscar el
    par inverso). Si la sesión es None (caller no la pasó), se salta ese paso
    manteniendo el comportamiento histórico (backward-compat).
    """
    if not sd.sd_ispurchase:
        return ClasificacionDocCompra.IGNORAR

    if sd.sd_isannulment:
        return ClasificacionDocCompra.ANULACION

    # CONTRAPARTE: solo si el caller pasó session (requiere query a DB).
    # El chequeo va ANTES de los flags estructurales (factura/NC/ND/etc.)
    # porque una contraparte TAMBIÉN tiene sd_istaxable / sd_isinbalance
    # (es la imagen espejo del doc original). Sin este chequeo, el doc
    # matchearía el paso FACTURA y nunca sería clasificado como contraparte.
    if session is not None and es_contraparte(sd, session):
        return ClasificacionDocCompra.CONTRAPARTE

    if sd.sd_isquotation:
        return ClasificacionDocCompra.PRESUPUESTO

    if sd.sd_ispackinglist:
        return ClasificacionDocCompra.REMITO

    if sd.sd_iscreditnote:
        return ClasificacionDocCompra.NC

    if sd.sd_isdebitnote:
        return ClasificacionDocCompra.ND

    if sd.sd_isreceipt:
        return ClasificacionDocCompra.ORDEN_PAGO

    if sd.hacc_group == HACC_GROUP_AJUSTE_SALDO:
        return ClasificacionDocCompra.AJUSTE_SALDO

    if sd.sd_isinbalance and sd.sd_istaxable:
        return ClasificacionDocCompra.FACTURA

    return ClasificacionDocCompra.IGNORAR


def afecta_cc_proveedor(sd: SaleDocument, session: Session | None = None) -> bool:
    """
    Indica si el tipo de documento genera movimiento en `cc_proveedor_movimientos`.

    Reglas (design §2.1):
      - FACTURA, NC, ND, ORDEN_PAGO, AJUSTE_SALDO → True
      - REMITO, PRESUPUESTO, ANULACION, CONTRAPARTE, IGNORAR → False
      - UNKNOWN → False (conservador)

    ANULACION/CONTRAPARTE se tratan como "no afecta" porque su compensación
    ya está registrada en la vista `v_facturas_compra_vigentes` que los
    excluye (design §4.1).

    Args:
        sd: fila de `tb_sale_document`.
        session: sesión SQLAlchemy opcional. Si se provee, habilita la
            detección de CONTRAPARTE (que se descarta como "no afecta").
            Si es None, un doc contraparte se clasifica por sus flags
            (FACTURA / NC / etc.) y SÍ afectaría CC — pero la vista SQL
            `v_facturas_compra_vigentes` ya lo excluye a nivel DB.
    """
    tipo = clasificar_documento_compra(sd, session=session)
    return tipo in {
        ClasificacionDocCompra.FACTURA,
        ClasificacionDocCompra.NC,
        ClasificacionDocCompra.ND,
        ClasificacionDocCompra.ORDEN_PAGO,
        ClasificacionDocCompra.AJUSTE_SALDO,
    }


def signo_contable(sd: SaleDocument) -> int:
    """
    Devuelve +1 (debe) o -1 (haber) según el ERP.

    NO reinventamos el signo — se lee directamente de `sd.sd_plusorminus`.
    El ERP ya garantiza que siempre es 1 ó -1 (check constraint en la tabla).
    """
    return int(sd.sd_plusorminus)


def es_anulacion(sd: SaleDocument) -> bool:
    """True si el documento marca una anulación (`sd_isannulment`)."""
    return bool(sd.sd_isannulment)


def es_contraparte_de(sd: SaleDocument, sd_base: SaleDocument) -> bool:
    """
    Predicado binario del design §2.1.

    `sd` es contraparte de `sd_base` si:
      - comparten `hacc_group` (ambos no-nulos e iguales)
      - `sd_plusorminus` está invertido
      - son filas distintas (`sd_id` ≠)

    Args:
        sd: documento candidato a contraparte.
        sd_base: documento "principal" del que `sd` sería contraparte.

    Returns:
        True si se cumple la heurística, False si no o si algún `hacc_group`
        es NULL (no podemos afirmar contraparte sin grupo común).
    """
    if sd.sd_id == sd_base.sd_id:
        return False
    if sd.hacc_group is None or sd_base.hacc_group is None:
        return False
    if sd.hacc_group != sd_base.hacc_group:
        return False
    return int(sd.sd_plusorminus) == -int(sd_base.sd_plusorminus)


def es_contraparte(sd: SaleDocument, session: Session) -> bool:
    """
    Helper de auditoría: determina si `sd` es contraparte de algún otro
    documento existente en `tb_sale_document`.

    Heurística (design §2.1 + RD3): busca otra fila con mismo `hacc_group`
    y `sd_plusorminus` invertido. Si existe Y `sd.sd_id` es MAYOR que esa
    fila, `sd` es la contraparte (convenio "sd_id mayor = contraparte"
    usado también en la vista `v_facturas_compra_vigentes`, design §4.1).

    Si no hay `hacc_group`, no puede haber contraparte.

    Args:
        sd: fila candidata.
        session: sesión SQLAlchemy sincrónica.

    Returns:
        True si `sd` es la contraparte bajo el convenio "sd_id mayor gana",
        False en caso contrario.

    Notes:
        No usar en hot path: consulta DB. Para clasificación masiva usar la
        vista `v_facturas_compra_vigentes` (filtrada en SQL).
    """
    if sd.hacc_group is None:
        return False

    stmt = select(SaleDocument.sd_id).where(
        and_(
            SaleDocument.hacc_group == sd.hacc_group,
            SaleDocument.sd_plusorminus == -int(sd.sd_plusorminus),
            SaleDocument.sd_id != sd.sd_id,
        )
    )
    otros: list[int] = [row[0] for row in session.execute(stmt).all()]
    if not otros:
        return False

    # Convenio: el sd_id MAYOR es la contraparte cuando hay par inverso.
    return sd.sd_id > min(otros)


__all__ = [
    "ClasificacionDocCompra",
    "HACC_GROUP_AJUSTE_SALDO",
    "SD_IDS_AMBIGUOS",
    "afecta_cc_proveedor",
    "clasificar_documento_compra",
    "es_anulacion",
    "es_contraparte",
    "es_contraparte_de",
    "signo_contable",
]
