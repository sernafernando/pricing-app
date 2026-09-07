"""Pure mapping from raw ML billing detail payloads to `MlBillingCharge` /
`MlBillingChargeOrder` DTOs (ml-ventas-desglose-costos, corte 2).

No I/O, no DB — fully unit-testable against fixtures, mirroring the
`ml_orders_ingestion/mapper.py` fail-closed contract: `map_billing_detail`
NEVER raises. It returns either a populated `BillingChargeDTO` or a
`MappingError`, so a caller can never observe a partially-populated DTO.

Sign rule (investigation §5.b, §6): every amount ML reports is POSITIVE —
0 negatives measured across 1000 billing details. This mapper is the ONLY
place that applies a sign, and it does so from `charge_info.detail_type`
(a real field: "CHARGE" vs "BONUS"), NEVER from a string-prefix heuristic
on `detail_sub_type` (real ML reversal codes like BVFV/BXD/BFF do start
with "B", but that is not the rule — `detail_type` is).

PII (investigation §6): `sales_info[].payer_nickname` and
`sales_info[].state_name` are buyer PII. They are discarded before
`raw_detail` is built — never persisted, by design agreement.
"""

from __future__ import annotations

import copy
import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger(__name__)

# Keys stripped from every `sales_info[]` entry before persistence. Buyer
# PII the mapper must never let through — see module docstring.
_SALES_INFO_PII_KEYS = ("payer_nickname", "state_name")

# `detail_type` values that flip the stored amount negative. Everything
# else (including an unrecognized/absent `detail_type`) stays positive —
# a silent sign flip on an unknown type would be worse than leaving it
# as ML reported the raw magnitude.
_NEGATIVE_DETAIL_TYPES = frozenset({"BONUS"})


class MappingError:
    """Non-exception failure value returned by `map_billing_detail`. See
    `ml_orders_ingestion/mapper.py::MappingError` for the same fail-closed
    return-value-union rationale."""

    __slots__ = ("reason", "raw_payload")

    def __init__(self, reason: str, raw_payload: Optional[Dict[str, Any]] = None) -> None:
        self.reason = reason
        self.raw_payload = raw_payload

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"MappingError(reason={self.reason!r})"


@dataclass(frozen=True)
class BillingChargeDTO:
    detail_id: str
    period_key: Optional[str]
    detail_type: Optional[str]
    detail_sub_type: Optional[str]
    amount: Optional[Decimal]
    document_id: Optional[str]
    order_ids: List[int] = field(default_factory=list)
    raw_detail: Dict[str, Any] = field(default_factory=dict)


def _as_dict(value: Any, field_name: str) -> Dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise TypeError(f"{field_name} is not an object: {value!r}")
    return value


def _as_list(value: Any, field_name: str) -> List[Any]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise TypeError(f"{field_name} is not a list: {value!r}")
    return value


def _strip_sales_info_pii(sales_info: List[Any]) -> List[Dict[str, Any]]:
    """Deep-copies `sales_info` and pops the PII keys from every entry.
    A deep copy (not a shallow dict-comprehension over the original) so
    no reference to the raw payload's dicts survives into `raw_detail`."""
    cleaned: List[Dict[str, Any]] = []
    for entry in sales_info:
        if not isinstance(entry, dict):
            continue
        entry_copy = copy.deepcopy(entry)
        for key in _SALES_INFO_PII_KEYS:
            entry_copy.pop(key, None)
        cleaned.append(entry_copy)
    return cleaned


def _payload_without_pii(raw: Any) -> Any:
    """El payload crudo, con la PII de `sales_info` afuera.

    Existe para el camino de ERROR. `_strip_sales_info_pii` recibe la lista
    de `sales_info`; acá hace falta limpiar el payload entero, porque el
    `MappingError` lo guarda tal cual y el barrido del corte 3 lo va a
    loguear o persistir -- que es justamente para lo que existe
    `raw_payload`. El happy path ya limpiaba; este no, y la PII salía por
    la puerta de atrás.
    """
    if not isinstance(raw, dict):
        return raw
    cleaned = dict(raw)
    sales_info = cleaned.get("sales_info")
    if isinstance(sales_info, list):
        cleaned["sales_info"] = _strip_sales_info_pii(sales_info)
    return cleaned


def _dedup_order_ids(items_info: List[Any]) -> List[int]:
    """Order-preserving dedup of `items_info[].order_id`, coerced to
    `int` (BigInteger-range safe, see `app/models/ml_billing.py`)."""
    seen: set[int] = set()
    result: List[int] = []
    for item in items_info:
        if not isinstance(item, dict):
            continue
        order_id = item.get("order_id")
        if order_id is None:
            continue
        order_id_int = int(order_id)
        if order_id_int not in seen:
            seen.add(order_id_int)
            result.append(order_id_int)
    return result


def map_billing_detail(raw: Dict[str, Any], period_key: Optional[str]) -> Union[BillingChargeDTO, MappingError]:
    """Maps one raw ML billing detail (from `get_billing_details`'s
    `results[]`) into a `BillingChargeDTO`.

    Args:
        raw: One element of the billing details `results[]` array, shaped
            `{charge_info, items_info, sales_info, shipping_info,
            discount_info, document_info}` (investigation §1/§6).
        period_key: The billing period this detail was fetched from, or
            None if unknown to the caller.

    Returns:
        A `BillingChargeDTO`, or a `MappingError` if the payload is
        malformed. Never raises.
    """
    # ML devuelve `results: [...]`; un elemento que no sea dict rompería en
    # el primer `.get()` con AttributeError y voltearía el barrido. Fail
    # closed acá, con el mismo shape de error que el resto.
    if not isinstance(raw, dict):
        return MappingError(f"detalle no es un dict: {type(raw).__name__}", _payload_without_pii(raw))

    try:
        charge_info = _as_dict(raw.get("charge_info"), "charge_info")
        detail_id = charge_info.get("detail_id")
        if not detail_id:
            return MappingError("missing charge_info.detail_id", _payload_without_pii(raw))
        detail_id = str(detail_id)

        detail_type = charge_info.get("detail_type")
        detail_sub_type = charge_info.get("detail_sub_type")
        document_id = _as_dict(raw.get("document_info"), "document_info").get("document_id")

        raw_amount = charge_info.get("detail_amount")
        # `Decimal(str(...))`, NO `float(...)`: la columna es `Numeric(14, 2)`
        # y estos montos se suman de a miles para armar el "Neto" de una
        # venta. Pasar por binario flotante en el camino del dinero
        # introduce un error que no existe en decimal (0.1 + 0.2 da
        # 0.30000000000000004) y que después es imposible de rastrear.
        # `str()` primero para no heredar el ruido si ML mandó un float.
        amount: Optional[Decimal] = None
        if raw_amount is not None:
            amount = Decimal(str(raw_amount))
            if detail_type in _NEGATIVE_DETAIL_TYPES:
                amount = -amount

        items_info = _as_list(raw.get("items_info"), "items_info")
        order_ids = _dedup_order_ids(items_info)

        sales_info = _as_list(raw.get("sales_info"), "sales_info")
        raw_detail = {
            "charge_info": charge_info,
            "items_info": items_info,
            "sales_info": _strip_sales_info_pii(sales_info),
            "shipping_info": _as_dict(raw.get("shipping_info"), "shipping_info"),
            "discount_info": _as_dict(raw.get("discount_info"), "discount_info"),
            "document_info": _as_dict(raw.get("document_info"), "document_info"),
        }

        return BillingChargeDTO(
            detail_id=detail_id,
            period_key=period_key,
            detail_type=detail_type,
            detail_sub_type=detail_sub_type,
            amount=amount,
            document_id=document_id,
            order_ids=order_ids,
            raw_detail=raw_detail,
        )
    # `ArithmeticError` está acá por `decimal.InvalidOperation`, que es lo
    # que levanta `Decimal(str(...))` con un `detail_amount` como "N/A" o
    # "1.234,56". Hereda de `ArithmeticError`, NO de `ValueError`: cuando
    # este mapper usaba `float()` alcanzaba con `ValueError`, y al pasar a
    # Decimal el contrato "nunca levanta" se rompió en silencio. Un solo
    # cargo raro habría volteado el barrido diario entero.
    # `AttributeError` por un `raw` que no sea dict (ver el guard de arriba,
    # que cubre el caso conocido; esto es el cinturón).
    except (TypeError, ValueError, ArithmeticError, AttributeError) as e:
        logger.warning(f"Error mapeando detalle de facturación: {e}")
        # El payload va SIN PII también por el camino de error. El happy
        # path lo limpiaba y este no: en cuanto el barrido del corte 3
        # loguee o persista un MappingError -- que es exactamente para lo
        # que existe `raw_payload` -- el `payer_nickname` y el `state_name`
        # salían por donde el diseño dijo que nunca iban a salir.
        return MappingError(str(e), _payload_without_pii(raw))
