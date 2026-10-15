"""Split a sell-in purchase discount across the lines it covers.

Pure arithmetic with no DB access: the API calls it for the preview and again
when a purchase is saved, so both always agree.

Formulas:
- ``proporcional`` weights each line by ``costo_base_unit * cantidad`` (default).
- ``por_unidad`` weights each line by ``cantidad``.
- ``manual`` takes ``monto_manual`` per line; they must add up to the total.

Each share is rounded to cents with ROUND_HALF_UP and the rounding remainder
goes to the line with the largest weight (the first one on ties), so the
amounts always add up to exactly ``monto_total``. If that would push the line
below zero (only possible with totals of a few cents spread over many lines),
the remainder is taken one cent at a time from the heaviest lines instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")
UNIT_PRECISION = Decimal("0.000001")
FORMULAS = ("proporcional", "por_unidad", "manual")


class SellInSplitError(ValueError):
    """The purchase cannot be split as requested."""


@dataclass(frozen=True)
class Line:
    item_id: int
    cantidad: int
    costo_base_unit: Decimal
    monto_manual: Decimal | None = None


@dataclass(frozen=True)
class PreviewLine:
    item_id: int
    cantidad: int
    costo_base_unit: Decimal
    monto_asignado: Decimal
    descuento_unit: Decimal
    costo_con_sell_in_unit: Decimal
    porcentaje: Decimal | None


def _is_whole_cents(amount: Decimal) -> bool:
    return amount == amount.quantize(CENT)


def _validate(formula: str, monto_total: Decimal, lines: list[Line]) -> None:
    if formula not in FORMULAS:
        raise SellInSplitError(f"Fórmula desconocida: {formula!r}")
    if not lines:
        raise SellInSplitError("La compra no tiene líneas: la lista está vacía")
    if monto_total <= 0 or not _is_whole_cents(monto_total):
        raise SellInSplitError(f"El monto total debe ser positivo y en centavos: {monto_total}")
    seen: set[int] = set()
    for line in lines:
        if line.item_id in seen:
            raise SellInSplitError(f"Item duplicado en la compra: {line.item_id}")
        seen.add(line.item_id)
        if line.cantidad <= 0:
            raise SellInSplitError(f"La cantidad debe ser positiva (item {line.item_id})")
        if line.costo_base_unit < 0:
            raise SellInSplitError(f"El costo base no puede ser negativo (item {line.item_id})")


def _split_manual(monto_total: Decimal, lines: list[Line]) -> list[Decimal]:
    amounts: list[Decimal] = []
    for line in lines:
        if line.monto_manual is None:
            raise SellInSplitError(f"Falta el monto manual del item {line.item_id}")
        if line.monto_manual < 0:
            raise SellInSplitError(f"El monto manual no puede ser negativo (item {line.item_id})")
        if not _is_whole_cents(line.monto_manual):
            raise SellInSplitError(f"El monto manual debe ir en centavos (item {line.item_id})")
        amounts.append(line.monto_manual.quantize(CENT))
    if sum(amounts, Decimal("0")) != monto_total:
        raise SellInSplitError(f"La suma de los montos manuales no coincide con el total {monto_total}")
    return amounts


def _place_remainder(amounts: list[Decimal], weights: list[Decimal], remainder: Decimal) -> None:
    by_weight = sorted(range(len(weights)), key=lambda i: -weights[i])
    heaviest = by_weight[0]
    if amounts[heaviest] + remainder >= 0:
        amounts[heaviest] += remainder
        return
    # Negative remainder larger than the heaviest share: take it a cent at a time.
    while remainder < 0:
        for i in by_weight:
            if remainder == 0:
                break
            if amounts[i] > 0:
                amounts[i] -= CENT
                remainder += CENT


def split(formula: str, monto_total: Decimal, lines: list[Line]) -> list[Decimal]:
    """Return the amount assigned to each line, in the same order as ``lines``."""
    _validate(formula, monto_total, lines)
    if formula == "manual":
        return _split_manual(monto_total, lines)

    if formula == "proporcional":
        weights = [line.costo_base_unit * line.cantidad for line in lines]
    else:
        weights = [Decimal(line.cantidad) for line in lines]
    total_weight = sum(weights, Decimal("0"))
    if total_weight <= 0:
        raise SellInSplitError("El peso total es cero: no hay costo base para repartir proporcionalmente")

    amounts = [(monto_total * w / total_weight).quantize(CENT, rounding=ROUND_HALF_UP) for w in weights]
    remainder = monto_total - sum(amounts, Decimal("0"))
    if remainder:
        _place_remainder(amounts, weights, remainder)
    return amounts


def unit_discount(monto_asignado: Decimal, cantidad: int) -> Decimal:
    """Discount per unit, rounded half up to 6 decimals like ``costo_base_unit``."""
    if cantidad <= 0:
        raise SellInSplitError("La cantidad debe ser positiva")
    return (monto_asignado / cantidad).quantize(UNIT_PRECISION, rounding=ROUND_HALF_UP)


def preview(formula: str, monto_total: Decimal, lines: list[Line]) -> list[PreviewLine]:
    """Per-line view of a split: amount, unit discount, promotional unit cost and percentage.

    The promotional cost is not clamped: a discount above the base cost shows up
    as a negative cost (and a percentage above 100) so the caller can flag it.
    """
    rows: list[PreviewLine] = []
    for line, monto in zip(lines, split(formula, monto_total, lines)):
        descuento = unit_discount(monto, line.cantidad)
        porcentaje = None
        if line.costo_base_unit > 0:
            porcentaje = (descuento * 100 / line.costo_base_unit).quantize(CENT, rounding=ROUND_HALF_UP)
        rows.append(
            PreviewLine(
                item_id=line.item_id,
                cantidad=line.cantidad,
                costo_base_unit=line.costo_base_unit,
                monto_asignado=monto,
                descuento_unit=descuento,
                costo_con_sell_in_unit=(line.costo_base_unit - descuento).quantize(UNIT_PRECISION),
                porcentaje=porcentaje,
            )
        )
    return rows
