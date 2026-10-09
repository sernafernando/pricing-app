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

Persist everything (spec BS-5, owner decision): `raw_detail` is an
unmodified deep copy of the ML detail. `sales_info[].payer_nickname`,
`sales_info[].state_name`, `marketplace_info`, `currency_info` and any block
ML adds later are kept. This mapper used to discard the first two as buyer
PII; the owner reversed that (ML data is persisted whole, no invented PII
rules) and the same applies to `MappingError.raw_payload`.
"""

from __future__ import annotations

import copy
import logging
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger(__name__)

# `detail_type` values that flip the stored amount negative. Everything
# else (including an unrecognized/absent `detail_type`) stays positive —
# a silent sign flip on an unknown type would be worse than leaving it
# as ML reported the raw magnitude.
_NEGATIVE_DETAIL_TYPES = frozenset({"BONUS"})

# Closed set: the source is stored on the row and decides how its order is linked.
BILLING_SOURCES = frozenset({"general", "flex"})


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
    # The type of the document the fetch asked for (the detail itself does not
    # say), and ML's own legal fields from `charge_info`. The number is
    # absent while the legal document is still PROCESSING.
    document_type: Optional[str] = None
    legal_document_number: Optional[str] = None
    legal_document_status: Optional[str] = None
    # 'general' (`/details`) or 'flex' (`/flex/details`); flex detail_ids are
    # disjoint from the general ones (0 overlap across 47,094 captured ids).
    billing_source: str = "general"


@dataclass(frozen=True)
class BillingDocumentDTO:
    """One ML billing document with ML's own values only. Nothing derived:
    the stored detail count and sum are computed by query (BD-1, BS-3)."""

    document_id: str
    group: str
    document_type: str
    period_key: str
    user_id: Optional[int]
    amount: Optional[Decimal]
    unpaid_amount: Optional[Decimal]
    document_status: Optional[str]
    associated_document_id: Optional[str]
    count_details: Optional[int]
    expiration_date: Optional[date]
    currency_id: Optional[str]
    site_id: Optional[str]
    reference_number: Optional[str]
    legal_point_of_sale: Optional[int]
    legal_letter: Optional[str]
    legal_number: Optional[int]
    files: List[Any]
    raw: Dict[str, Any]


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


def _flex_order_id(shipping_info: Dict[str, Any]) -> Optional[int]:
    """The order of a flex row: `shipping_info.order.order_id`. Flex rows carry
    no `items_info`."""
    order = shipping_info.get("order")
    order_id = order.get("order_id") if isinstance(order, dict) else None
    return None if order_id is None else int(order_id)


def map_billing_detail(
    raw: Dict[str, Any], period_key: Optional[str], document_type: str = "BILL", billing_source: str = "general"
) -> Union[BillingChargeDTO, MappingError]:
    """Maps one raw ML billing detail (from `get_billing_details`'s
    `results[]`) into a `BillingChargeDTO`.

    Args:
        raw: One element of the billing details `results[]` array, shaped
            `{charge_info, items_info, sales_info, shipping_info,
            discount_info, document_info}` (investigation §1/§6).
        period_key: The billing period this detail was fetched from, or
            None if unknown to the caller.
        document_type: The document type the fetch asked for (`BILL`, the
            only one fetched before PR 2b, or `CREDIT_NOTE`).
        billing_source: `general` (default) or `flex`. A flex row is linked to
            its order through `shipping_info.order.order_id` (deduped with
            `items_info`); a general row only through `items_info`.

    Returns:
        A `BillingChargeDTO`, or a `MappingError` if the payload is
        malformed. Never raises.
    """
    # ML devuelve `results: [...]`; un elemento que no sea dict rompería en
    # el primer `.get()` con AttributeError y voltearía el barrido. Fail
    # closed acá, con el mismo shape de error que el resto.
    if not isinstance(raw, dict):
        return MappingError(f"detalle no es un dict: {type(raw).__name__}", raw)
    if billing_source not in BILLING_SOURCES:
        return MappingError(f"billing_source desconocido: {billing_source!r}", raw)

    try:
        charge_info = _as_dict(raw.get("charge_info"), "charge_info")
        detail_id = charge_info.get("detail_id")
        if not detail_id:
            return MappingError("missing charge_info.detail_id", raw)
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

        # Shape checks only (a malformed block is a MappingError); what is
        # stored is the whole detail, deep-copied so no reference to the
        # caller's dicts survives.
        _as_list(raw.get("sales_info"), "sales_info")
        shipping_info = _as_dict(raw.get("shipping_info"), "shipping_info")
        if billing_source == "flex":
            flex_order = _flex_order_id(shipping_info)
            if flex_order is not None and flex_order not in order_ids:
                order_ids.append(flex_order)
        _as_dict(raw.get("discount_info"), "discount_info")
        raw_detail = copy.deepcopy(raw)

        return BillingChargeDTO(
            detail_id=detail_id,
            period_key=period_key,
            detail_type=detail_type,
            detail_sub_type=detail_sub_type,
            amount=amount,
            document_id=document_id,
            order_ids=order_ids,
            raw_detail=raw_detail,
            document_type=document_type,
            legal_document_number=charge_info.get("legal_document_number"),
            legal_document_status=charge_info.get("legal_document_status"),
            billing_source=billing_source,
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
        # El payload va completo también por el camino de error: es lo que
        # el barrido loguea o persiste para diagnosticar la fila.
        return MappingError(str(e), raw)


# `PPPPLNNNNNNNN`: point of sale (4 digits), letter, number (8 digits), e.g.
# `0058A00975220` -> (58, "A", 975220).
_LEGAL_REFERENCE_RE = re.compile(r"^(\d{4})([A-Z])(\d{8})$")


def parse_legal_reference(reference: Any) -> tuple[Optional[int], Optional[str], Optional[int]]:
    """Splits a legal reference into (point of sale, letter, number).

    A string that does not have the shape yields `(None, None, None)`; the
    caller keeps the original string. Never raises (BD-2)."""
    if not isinstance(reference, str):
        return (None, None, None)
    match = _LEGAL_REFERENCE_RE.match(reference)
    if match is None:
        return (None, None, None)
    return (int(match.group(1)), match.group(2), int(match.group(3)))


def _optional_str(value: Any) -> Optional[str]:
    return None if value is None else str(value)


def _optional_money(value: Any) -> Optional[Decimal]:
    # `Decimal(str(...))`, never float: same money rule as the charge amount.
    return None if value is None else Decimal(str(value))


def map_billing_document(raw: Dict[str, Any], period_key: str, group: str) -> Union[BillingDocumentDTO, MappingError]:
    """Maps one element of ML's `/documents` list into a `BillingDocumentDTO`.

    Fail-closed like `map_billing_detail`: never raises, returns a
    `MappingError` for a payload it cannot trust."""
    if not isinstance(raw, dict):
        return MappingError(f"documento no es un dict: {type(raw).__name__}", raw)

    try:
        document_id = raw.get("id")
        if document_id is None or document_id == "":
            return MappingError("missing document id", raw)
        if not raw.get("document_type"):
            return MappingError("missing document_type", raw)

        files = raw.get("files")
        files = _as_list(files, "files")
        first_file = files[0] if files and isinstance(files[0], dict) else {}
        reference_number = first_file.get("reference_number")
        point_of_sale, letter, number = parse_legal_reference(reference_number)

        expiration = raw.get("expiration_date")
        expiration_date = date.fromisoformat(str(expiration)[:10]) if expiration else None
        count_details = raw.get("count_details")
        user_id = raw.get("user_id")

        return BillingDocumentDTO(
            document_id=str(document_id),
            group=group,
            document_type=str(raw["document_type"]),
            period_key=period_key,
            user_id=None if user_id is None else int(user_id),
            amount=_optional_money(raw.get("amount")),
            unpaid_amount=_optional_money(raw.get("unpaid_amount")),
            document_status=raw.get("document_status"),
            associated_document_id=_optional_str(raw.get("associated_document_id")),
            count_details=None if count_details is None else int(count_details),
            expiration_date=expiration_date,
            currency_id=raw.get("currency_id"),
            site_id=raw.get("site_id"),
            reference_number=_optional_str(reference_number),
            legal_point_of_sale=point_of_sale,
            legal_letter=letter,
            legal_number=number,
            files=copy.deepcopy(files),
            raw=copy.deepcopy(raw),
        )
    except (TypeError, ValueError, ArithmeticError, AttributeError) as e:
        logger.warning(f"Error mapeando documento de facturación: {e}")
        return MappingError(str(e), raw)
