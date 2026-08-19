"""GBP-layer conversion (PC2/U1 grams->kg, PC3/U2 dimension mapping) and
precedence resolution (PC4/PC5, D2/D8).

design.md Decision 1's ordering constraint: unit conversion is applied
INSIDE the GBP source layer, BEFORE any precedence merge with stored
overrides. Overrides are stored already-canonical (kg, cm, ARS) — merging
them in `resolve_field` never re-applies GBP-layer conversion, so a stored
override can never be divided by 1000 a second time on re-publish.
Convert-then-resolve, never resolve-then-convert.
"""

from dataclasses import dataclass
from datetime import date
from typing import Any, Literal, Optional

from app.services.tn_publish_core.extract import Absent, ExtractedReportRow, ReportFieldError

GRAMS_PER_KILOGRAM = 1000


class InvalidReportValueError(ReportFieldError):
    """Raised when a report-78 row's field KEY is present but its VALUE
    cannot be coerced to the type this publisher needs (e.g. non-numeric,
    non-blank junk like `"N/A"` in a measurement field).

    Distinct from BOTH `Absent` (GBP explicitly reports "no value" via a
    blank/zero convention — `extract.py`'s `_is_absent_value`) and
    `MissingReportFieldError` (the KEY itself is missing). Junk is not
    absence: `_is_absent_value` deliberately treats unparseable values as
    "present" so this error can fire instead of silently discarding a data
    problem as if GBP had reported nothing. `str(...)` names both the
    offending field and the offending raw value, so the operator/log can
    tell a GBP schema/data problem apart from a normal absence.
    """

    def __init__(self, field_name: str, raw_value: Any):
        super().__init__(f"Report 78 row field {field_name!r} has an unparseable value: {raw_value!r}")
        self.field_name = field_name
        self.raw_value = raw_value


def convert_weight_to_kg(weight_grams: Any) -> Any:
    """GBP reports `weight` in grams; TN wants kilograms (PC2/U1).

    Verified 36/36 against the live store (engram
    architecture/tn-api-field-map, #1517): GBP `1000` -> TN `1.000` kg,
    GBP `250` -> TN `0.250` kg. `Absent` passes through unconverted — there
    is no weight to convert. A present-but-unparseable value (e.g. `"N/A"`)
    raises `InvalidReportValueError` naming the field and the raw value,
    instead of letting a bare `ValueError` from `float(...)` escape.
    """
    if weight_grams is Absent:
        return Absent
    try:
        return float(weight_grams) / GRAMS_PER_KILOGRAM
    except (TypeError, ValueError) as exc:
        raise InvalidReportValueError("weight", weight_grams) from exc


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

    def _to_float(field_name: str, value: Any) -> Any:
        if value is Absent:
            return Absent
        try:
            return float(value)
        except (TypeError, ValueError) as exc:
            raise InvalidReportValueError(field_name, value) from exc

    return ResolvedDimensions(
        width=_to_float("large", large_cm),
        depth=_to_float("wide", wide_cm),
        height=_to_float("height", height_cm),
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


Source = Literal["operator", "override", "gbp", "profile", "empty"]


@dataclass(frozen=True)
class Resolved:
    """One field's final value plus WHERE it came from (PC4, D2/D8) — the
    D2 audit primitive: every transmitted field can answer "why is this the
    number that went live" from `source` alone."""

    value: Any
    source: Source


def resolve_field(
    *,
    gbp_value: Any = Absent,
    override_value: Any = Absent,
    profile_value: Any = Absent,
    operator_value: Any = Absent,
) -> Resolved:
    """Precedence merge (PC4, design Decision 1/D2/D8):

        empty < profile < gbp < stored override < operator in-session edit

    Each layer is skipped when it is `Absent` OR `None` — a stored override
    or profile value is never forced to compete with a GBP-reported
    `Absent` measurement, it simply falls through to the next
    lower-precedence layer that DOES carry a value. Callers pass
    already-converted/already-canonical values (see the module docstring);
    this function performs no unit conversion of its own.
    """
    for value, source in (
        (operator_value, "operator"),
        (override_value, "override"),
        (gbp_value, "gbp"),
        (profile_value, "profile"),
    ):
        if value is not Absent and value is not None:
            return Resolved(value, source)
    return Resolved(None, "empty")


class MissingExchangeRateError(ReportFieldError):
    """Raised by `resolve_cost` when `moneda_costo == "USD"` and NO usable
    `TipoCambio` row exists at all (an empty table, or every row's `venta`
    is null/zero) — D6's "empty TipoCambio table BLOCKS the cost field"
    requirement. Never falls through to sending the unconverted USD figure
    as if it were ARS (the `pricing_calculator.convertir_a_pesos` defect
    this change explicitly must not replicate)."""

    def __init__(self):
        super().__init__("No hay tipo de cambio USD disponible para convertir el costo")
        self.field_name = "cost"


def _latest_usd_rate(db: Any) -> Optional[float]:
    """Today's `TipoCambio.venta` for USD, falling back to the most recent
    row available (design Decision D6) — mirrors the existing
    `pedidos_service`/`ncs_locales_service` today's-rate lookup, but adds
    the fallback-to-latest step those two stop short of (they return `None`
    when today's row is missing; here that would incorrectly present a
    genuinely-populated `tipo_cambio` table as "empty")."""
    from app.models.tipo_cambio import TipoCambio  # noqa: PLC0415

    today = date.today()
    row = (
        db.query(TipoCambio)
        .filter(TipoCambio.moneda == "USD", TipoCambio.fecha == today)
        .order_by(TipoCambio.id.desc())
        .first()
    )
    if row is None or not row.venta:
        row = (
            db.query(TipoCambio)
            .filter(TipoCambio.moneda == "USD")
            .order_by(TipoCambio.fecha.desc(), TipoCambio.id.desc())
            .first()
        )
    if row is None or not row.venta:
        return None
    return float(row.venta)


def resolve_cost(db: Any, raw_cost: Any, moneda_costo: str) -> Resolved:
    """D6 cost currency resolution: `ARS` passes through unconverted; `USD`
    converts at `_latest_usd_rate`; an `Absent`/missing cost resolves
    `empty` (no cost reported, not a rate problem). Raises
    `MissingExchangeRateError` — never silently sends an unconverted USD
    figure as ARS — when the currency is `USD` and no usable rate exists.
    """
    if raw_cost is Absent or raw_cost is None:
        return Resolved(None, "empty")
    try:
        amount = float(raw_cost)
    except (TypeError, ValueError) as exc:
        raise InvalidReportValueError("cost", raw_cost) from exc

    moneda = (moneda_costo or "").strip().upper()
    if moneda == "ARS":
        return Resolved(amount, "gbp")
    if moneda == "USD":
        rate = _latest_usd_rate(db)
        if rate is None:
            raise MissingExchangeRateError()
        return Resolved(amount * rate, "gbp")
    raise InvalidReportValueError("Moneda_Costo", moneda_costo)
