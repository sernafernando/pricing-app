"""GBP-layer conversion (PC2/U1 grams->kg, PC3/U2 dimension mapping).

design.md Decision 1's ordering constraint: unit conversion is applied
INSIDE the GBP source layer, BEFORE any precedence merge with stored
overrides. Full precedence resolution (`Resolved(value, source)`, stored
override lookup, profile fallback, D6 USD->ARS cost conversion) lands in
PR-5 — this module only converts a freshly extracted GBP row into TN's
units/axes. Convert-then-resolve, never resolve-then-convert: if
conversion ran AFTER precedence, a stored override (already in kg/cm)
would be divided by 1000 a second time on re-publish.
"""

from dataclasses import dataclass
from typing import Any

from app.services.tn_publish_core.extract import Absent, ExtractedReportRow

GRAMS_PER_KILOGRAM = 1000


def convert_weight_to_kg(weight_grams: Any) -> Any:
    """GBP reports `weight` in grams; TN wants kilograms (PC2/U1).

    Verified 36/36 against the live store (engram
    architecture/tn-api-field-map, #1517): GBP `1000` -> TN `1.000` kg,
    GBP `250` -> TN `0.250` kg. `Absent` passes through unconverted — there
    is no weight to convert.
    """
    if weight_grams is Absent:
        return Absent
    return float(weight_grams) / GRAMS_PER_KILOGRAM


@dataclass(frozen=True)
class ResolvedDimensions:
    width: Any
    depth: Any
    height: Any


def map_dimensions(large_cm: Any, wide_cm: Any, height_cm: Any) -> ResolvedDimensions:
    """GBP -> TN dimension mapping (PC3/U2).

    THIS LOOKS LIKE A SWAP BUG. IT IS NOT.

    GBP `large` (largo) maps to TN `width`, and GBP `wide` (ancho) maps to
    TN `depth` — GBP's English column names do not match TN's semantics.
    Confirmed 36/36 against the 535 already-published live products (zero
    exceptions, deterministic — see engram discovery/tn-dim-mapping-swap,
    #1519). GBP has no profundidad/depth column of its own; `wide` is it.
    Do NOT "fix" this to large->depth/wide->width — that would corrupt
    every future publish against the mapping the existing catalog already
    depends on. GBP `height` (alto) maps straight across to TN `height` —
    no swap on that axis.
    """

    def _to_float(value: Any) -> Any:
        return Absent if value is Absent else float(value)

    return ResolvedDimensions(
        width=_to_float(large_cm),
        depth=_to_float(wide_cm),
        height=_to_float(height_cm),
    )


@dataclass(frozen=True)
class ResolvedGbpFields:
    """A report-78 row's extraction-dependent fields after GBP-layer
    conversion (grams->kg, dimension mapping) — still GBP-sourced values,
    NOT yet merged against stored overrides/profile/operator edits (that
    precedence merge is PR-5)."""

    marca: str
    stock_disponible: str
    coslis_price: str
    iclh_price: str
    moneda_costo: str
    codigo: str
    promotional_price: Any
    weight_kg: Any
    width_cm: Any
    depth_cm: Any
    height_cm: Any


def resolve_gbp_fields(extracted: ExtractedReportRow) -> ResolvedGbpFields:
    """Apply GBP-layer conversion to a strictly extracted row.

    Ordering: MUST be called on the output of `extract_report_row` BEFORE
    any precedence merge (design.md Decision 1). Non-measurement fields
    pass through unchanged.
    """
    dims = map_dimensions(extracted.large_cm, extracted.wide_cm, extracted.height_cm)
    return ResolvedGbpFields(
        marca=extracted.marca,
        stock_disponible=extracted.stock_disponible,
        coslis_price=extracted.coslis_price,
        iclh_price=extracted.iclh_price,
        moneda_costo=extracted.moneda_costo,
        codigo=extracted.codigo,
        promotional_price=extracted.promotional_price,
        weight_kg=convert_weight_to_kg(extracted.weight_grams),
        width_cm=dims.width,
        depth_cm=dims.depth,
        height_cm=dims.height,
    )
