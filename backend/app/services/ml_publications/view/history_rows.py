"""Readable Historial rows: one `ml_change_log` change list turned into lines a person can read.

Each stored change (`{"p", "old", "new"}`, as `diff.py` writes it) becomes one or more `Row`s with a Spanish label,
the values before and after already formatted for display (money as `$ 91.193`, counts, dates, Spanish names of
ML codes) and an `is_technical` flag. A value is never a dict or a list: a known nested structure (a promotion, a
price entry, a visits day, a sales week, a stock location) is flattened into scalar rows, and anything else is
reduced to a short text.

`is_technical` is an allowlist: a path is business only when a rule below says so; date windows, ids,
`last_updated`/`date_*` timestamps, reference dates and everything not named are technical, hidden by default and
counted (`visible`). The legacy `history.split` (business/technical lines with raw values) is left untouched so the
current panel keeps working while this shape rolls out.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Iterable, Optional, Sequence
from zoneinfo import ZoneInfo

LOCAL_TZ = ZoneInfo("America/Argentina/Buenos_Aires")


@dataclass(frozen=True)
class Row:
    path: str
    label: str
    before: Optional[str]
    after: Optional[str]
    is_technical: bool
    subject: Optional[str] = None  # what the line is about when the label alone is not enough (a promotion, a day)
    status_label: Optional[str] = None  # promotion lines only: the state in business words

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── Spanish names of ML codes (a code not listed keeps its own name) ─────────────────────────────────────────

ITEM_STATUS = {
    "active": "Activa",
    "paused": "Pausada",
    "closed": "Cerrada",
    "under_review": "En revisión",
    "inactive": "Inactiva",
    "payment_required": "Pago pendiente",
}
SUB_STATUS = {
    "out_of_stock": "Sin stock",
    "deleted": "Eliminada",
    "forbidden": "Prohibida",
    "freezed": "Congelada",
    "held": "Retenida",
    "suspended": "Suspendida",
    "warning": "Con advertencia",
    "waiting_for_patch": "Esperando corrección",
}
LISTING_TYPES = {"gold_special": "Clásica", "gold_pro": "Premium"}
LOGISTIC_TYPES = {"fulfillment": "Full", "self_service": "Flex", "cross_docking": "Colecta"}
STOCK_LOCATIONS = {
    "meli_facility": "Depósito de Mercado Libre",
    "selling_address": "Dirección del vendedor",
    "seller_warehouse": "Depósito del vendedor",
}
PROMOTION_TYPES = {
    "DEAL": "Campaña tradicional",
    "MARKETPLACE_CAMPAIGN": "Campaña de Mercado Libre",
    "SELLER_CAMPAIGN": "Campaña del vendedor",
    "SELLER_COUPON_CAMPAIGN": "Cupón del vendedor",
    "SMART": "Campaña co-fondeada",
    "SMART_LIGHTNING": "Oferta relámpago co-fondeada",
    "LIGHTNING": "Oferta relámpago",
    "DOD": "Oferta del día",
    "PRICE_DISCOUNT": "Descuento de precio",
    "VOLUME": "Descuento por volumen",
    "PRE_NEGOTIATED": "Descuento pre-acordado",
    "UNHEALTHY_STOCK": "Liquidación de stock",
    "CUSTOM": "Precio personalizado",
}
COMPETITION_STATUS = {
    "winning": "Ganando",
    "competing": "Compitiendo",
    "sharing_first_place": "Compartiendo el primer lugar",
    "listed": "Participando",
    "not_listed": "No participa",
}
PRICE_TYPES = {"standard": "Precio de lista", "promotion": "Precio de promoción"}

# Promotion state in business words (`events.PROMOTION_*` statuses, `events.FINISHED_*` reasons).
PROMOTION_STATUS = {"candidate": "Disponible para activar", "started": "Aplicada", "pending": "Pendiente"}
NO_LONGER_OFFERED = "Ya no se ofrece"
FINISHED_REASONS = {"absent": NO_LONGER_OFFERED, "withdrawn": NO_LONGER_OFFERED, "ended": "Finalizada"}


def promotion_status_label(status: Optional[str], reason: Optional[str] = None) -> Optional[str]:
    """`candidate` is offered, `started` applied, `pending` waiting; a finished one reads by its reason (an entry
    that vanished from ML's list is no longer offered). `None` for a state with no business name."""
    if reason in FINISHED_REASONS:
        return FINISHED_REASONS[reason]
    if status == "finished":
        return "Finalizada"
    return PROMOTION_STATUS.get(status) if isinstance(status, str) else None


# ── Display formatting ───────────────────────────────────────────────────────────────────────────────────────


def _decimal(value: Any) -> Optional[Decimal]:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _grouped(number: Decimal, decimals: int) -> str:
    text = f"{number:,.{decimals}f}"  # 81,191.59
    return text.replace(",", "_").replace(".", ",").replace("_", ".")


def number(value: Any) -> Optional[str]:
    amount = _decimal(value)
    if amount is None:
        return text_of(value)
    if amount == amount.to_integral_value():
        return _grouped(amount, 0)
    return _grouped(amount, 2).rstrip("0").rstrip(",")


def money(value: Any) -> Optional[str]:
    amount = _decimal(value)
    if amount is None:
        return text_of(value)
    whole = amount == amount.to_integral_value()
    return f"$ {_grouped(amount, 0 if whole else 2)}"


def percent(value: Any) -> Optional[str]:
    shown = number(value)
    return None if shown is None else f"{shown} %"


def _parse_moment(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or len(value) < 10:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00").replace("+0000", "+00:00"))
    except ValueError:
        return None


def day(value: Any) -> Optional[str]:
    """The calendar day written in the value (ML keys days at UTC midnight, so no time-zone shift)."""
    if isinstance(value, str) and re.match(r"^\d{4}-\d{2}-\d{2}", value):
        return date.fromisoformat(value[:10]).strftime("%d/%m/%Y")
    return text_of(value)


def moment(value: Any) -> Optional[str]:
    """A timestamp in Argentina's local time."""
    parsed = _parse_moment(value)
    if parsed is None:
        return text_of(value)
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(LOCAL_TZ)
    return parsed.strftime("%d/%m/%Y %H:%M")


def yes_no(value: Any) -> Optional[str]:
    return text_of(value) if not isinstance(value, bool) else ("Sí" if value else "No")


def names(table: dict[str, str]) -> Callable[[Any], Optional[str]]:
    def shown(value: Any) -> Optional[str]:
        if isinstance(value, str):
            return table.get(value, table.get(value.upper(), value))
        return text_of(value)

    return shown


NAME_KEYS = ("name", "value_name", "title", "item_id", "id", "type")


def text_of(value: Any) -> Optional[str]:
    """Any stored value as one short text: never a dict or a list."""
    if value is None:
        return None
    if isinstance(value, bool):
        return "Sí" if value else "No"
    if isinstance(value, (int, float)):
        return number(value)
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in NAME_KEYS:
            if value.get(key) not in (None, ""):
                return text_of(value[key])
        parts = [text_of(v) for v in value.values() if not isinstance(v, (dict, list)) and v is not None]
        return " · ".join(p for p in parts if p) or None
    if isinstance(value, (list, tuple)):
        parts = [text_of(v) for v in value]
        return ", ".join(p for p in parts if p) or None
    return str(value)


def attribute_value(value: Any) -> Optional[str]:
    """An item attribute: its value name (`{"name": "SKU", "value_name": "314"}` reads `314`)."""
    if isinstance(value, dict):
        return text_of(value.get("value_name")) or text_of(value.get("values"))
    return text_of(value)


def total_of(value: Any) -> Any:
    """`[{"full": 2}]` (replenishment totals by channel) as one number."""
    if isinstance(value, list):
        amounts = [_decimal(v) for entry in value if isinstance(entry, dict) for v in entry.values()]
        return sum((a for a in amounts if a is not None), Decimal(0)) if amounts else None
    return value


# ── Rules: path pattern -> builder of rows ───────────────────────────────────────────────────────────────────

Builder = Callable[[str, Any, Any, "re.Match[str]"], list[Row]]


def field(
    label: str,
    fmt: Callable[[Any], Optional[str]] = text_of,
    *,
    technical: bool = False,
    subject: Optional[Callable[["re.Match[str]"], Optional[str]]] = None,
) -> Builder:
    def build(path: str, old: Any, new: Any, match: "re.Match[str]") -> list[Row]:
        about = subject(match) if subject else None
        return [Row(path, label, fmt(old), fmt(new), technical, about)]

    return build


def _group(n: int, fmt: Callable[[Any], Optional[str]] = text_of) -> Callable[["re.Match[str]"], Optional[str]]:
    return lambda match: fmt(match.group(n))


def _sub_status(path: str, old: Any, new: Any, match: "re.Match[str]") -> list[Row]:
    shown = names(SUB_STATUS)
    return [Row(path, "Subestado", shown(old), shown(new), False)]


def _promotion_entry(path: str, old: Any, new: Any, match: "re.Match[str]") -> list[Row]:
    """A whole promotion added or removed: its name, type, state and (when set) price."""
    old = old if isinstance(old, dict) else {}
    new = new if isinstance(new, dict) else {}
    about = text_of(new.get("name") or old.get("name") or match.group(1))
    before_state = promotion_status_label(old.get("status")) if old else None
    after_state = promotion_status_label(new.get("status")) if new else (NO_LONGER_OFFERED if old else None)
    promo_type = names(PROMOTION_TYPES)
    rows = [
        Row(path, "Promoción", text_of(old.get("name")), text_of(new.get("name")), False, about),
        Row(path, "Tipo de promoción", promo_type(old.get("type")), promo_type(new.get("type")), False, about),
        Row(path, "Estado de la promoción", before_state, after_state, False, about, after_state or before_state),
    ]
    old_price, new_price = (_decimal(side.get("price")) for side in (old, new))
    if (old_price or 0) > 0 or (new_price or 0) > 0:
        priced = [money(p) if p else None for p in (old_price, new_price)]
        rows.append(Row(path, "Precio de la promoción", priced[0], priced[1], False, about))
    return rows


def _promotion_status(path: str, old: Any, new: Any, match: "re.Match[str]") -> list[Row]:
    before, after = promotion_status_label(old) or text_of(old), promotion_status_label(new) or text_of(new)
    return [Row(path, "Estado de la promoción", before, after, False, match.group(1), after or before)]


def _price_entry(path: str, old: Any, new: Any, match: "re.Match[str]") -> list[Row]:
    """A price entry added or removed: its amount (business) and its validity window (technical)."""
    old = old if isinstance(old, dict) else {}
    new = new if isinstance(new, dict) else {}
    label = PRICE_TYPES.get(new.get("type") or old.get("type"), "Precio por canal")
    rows = [Row(path, label, money(old.get("amount")), money(new.get("amount")), False)]

    def window(entry: dict) -> Optional[str]:
        conditions = entry.get("conditions") or {}
        start, end = conditions.get("start_time"), conditions.get("end_time")
        if not start and not end:
            return None
        return f"{moment(start) or '…'} al {moment(end) or '…'}"

    if window(old) or window(new):
        rows.append(Row(path, "Vigencia del precio", window(old), window(new), True))
    return rows


def _visits_day(path: str, old: Any, new: Any, match: "re.Match[str]") -> list[Row]:
    totals = [number(side.get("total")) if isinstance(side, dict) else None for side in (old, new)]
    return [Row(path, "Visitas del día", totals[0], totals[1], True, day(match.group(1)))]


def _sales_week(path: str, old: Any, new: Any, match: "re.Match[str]") -> list[Row]:
    """A week entering or leaving the rolling sales window: technical (the window moves every day)."""
    entry = new if isinstance(new, dict) else old if isinstance(old, dict) else {}
    about = f"{day(entry.get('start_date') or match.group(1))} al {day(entry.get('end_date')) or '…'}"
    units = [number(side.get("units_sold")) if isinstance(side, dict) else None for side in (old, new)]
    return [Row(path, "Unidades vendidas en la semana", units[0], units[1], True, about)]


def _stock_location(path: str, old: Any, new: Any, match: "re.Match[str]") -> list[Row]:
    quantities = [number(side.get("quantity")) if isinstance(side, dict) else None for side in (old, new)]
    return [Row(path, "Stock disponible", quantities[0], quantities[1], False, names(STOCK_LOCATIONS)(match.group(1)))]


def _rules(*pairs: tuple[str, Builder]) -> tuple[tuple["re.Pattern[str]", Builder], ...]:
    return tuple((re.compile(pattern), builder) for pattern, builder in pairs)


_KEY = r"\[([^\]]+)\]"

RULES: dict[str, tuple[tuple["re.Pattern[str]", Builder], ...]] = {
    "item": _rules(
        (r"^price$", field("Precio", money)),
        (r"^base_price$", field("Precio base", money)),
        (r"^original_price$", field("Precio original", money)),
        (r"^status$", field("Estado", names(ITEM_STATUS))),
        (r"^sub_status\[=.+\]$", _sub_status),
        (r"^sub_status$", field("Subestado", names(SUB_STATUS))),
        (r"^available_quantity$", field("Stock disponible", number)),
        (r"^sold_quantity$", field("Unidades vendidas", number)),
        (r"^listing_type_id$", field("Tipo de publicación", names(LISTING_TYPES))),
        (r"^title$", field("Título")),
        (r"^tags\[=.+\]$", field("Etiqueta")),
        (r"^shipping\.logistic_type$", field("Tipo de logística", names(LOGISTIC_TYPES))),
        (r"^catalog_listing$", field("Publicación de catálogo", yes_no)),
        (r"^sale_terms\[INSTALLMENTS_CAMPAIGN\]", field("Campaña de cuotas")),
        (r"^initial_quantity$", field("Cantidad inicial", number, technical=True)),
        (r"^expiration_time$", field("Vencimiento de la publicación", moment, technical=True)),
        (r"^health$", field("Salud de la publicación", number, technical=True)),
        (r"^attributes\[([^\]]+)\]", field("Ficha técnica", attribute_value, technical=True, subject=_group(1))),
    ),
    "prices": _rules(
        (rf"^prices{_KEY}$", _price_entry),
        (rf"^prices{_KEY}\.amount$", field("Precio por canal", money)),
        (rf"^prices{_KEY}\.regular_amount$", field("Precio regular por canal", money)),
    ),
    "sale_price": _rules(
        (r"^amount$", field("Precio de venta", money)),
        (r"^regular_amount$", field("Precio regular", money)),
        (r"^metadata\.promotion_type$", field("Tipo de promoción", names(PROMOTION_TYPES))),
        (r"^reference_date$", field("Fecha de referencia", moment, technical=True)),
    ),
    "promotions": _rules(
        (rf"^{_KEY}$", _promotion_entry),
        (rf"^{_KEY}\.status$", _promotion_status),
        (rf"^{_KEY}\.price$", field("Precio de la promoción", money, subject=_group(1))),
        (rf"^{_KEY}\.suggested_discounted_price$", field("Precio sugerido", money, technical=True, subject=_group(1))),
        (rf"^{_KEY}\.original_price$", field("Precio original", money, technical=True, subject=_group(1))),
        (rf"^{_KEY}\.max_discounted_price$", field("Precio máximo", money, technical=True, subject=_group(1))),
        (rf"^{_KEY}\.min_discounted_price$", field("Precio mínimo", money, technical=True, subject=_group(1))),
        (rf"^{_KEY}\.meli_percentage$", field("Aporte de Mercado Libre", percent, technical=True, subject=_group(1))),
        (rf"^{_KEY}\.seller_percentage$", field("Aporte del vendedor", percent, technical=True, subject=_group(1))),
        (rf"^{_KEY}\.start_date$", field("Inicio de la promoción", day, technical=True, subject=_group(1))),
        (rf"^{_KEY}\.finish_date$", field("Fin de la promoción", day, technical=True, subject=_group(1))),
    ),
    "visits": _rules(
        (r"^total_visits$", field("Visitas de los últimos 30 días", number)),
        (r"^date_from$", field("Inicio del período de visitas", day, technical=True)),
        (r"^date_to$", field("Fin del período de visitas", day, technical=True)),
        (rf"^results{_KEY}$", _visits_day),
        (rf"^results{_KEY}\.total$", field("Visitas del día", number, technical=True, subject=_group(1, day))),
        (rf"^results{_KEY}\.visits_detail$", field("Visitas por origen", technical=True, subject=_group(1, day))),
    ),
    "stock": _rules(
        (rf"^locations{_KEY}\.quantity$", field("Stock disponible", number, subject=_group(1, names(STOCK_LOCATIONS)))),
        (rf"^locations{_KEY}$", _stock_location),
        (r"^locations$", field("Stock por ubicación")),
    ),
    "replenishment": _rules(
        (r"^sales\.sales_totals\.units_sold$", field("Unidades vendidas", lambda v: number(total_of(v)))),
        (r"^sales\.sales_totals\.gmv$", field("Facturación", lambda v: money(total_of(v)))),
        (r"^sales\.sales_history\[([^\]]+)\]$", _sales_week),
        (
            r"^sales\.sales_history\[([^\]]+)\]\.units_sold$",
            field("Unidades vendidas en la semana", number, subject=_group(1, day)),
        ),
        (r"^stock\.total_stock$", field("Stock total", number, technical=True)),
        (r"^identifiers\.seller_sku$", field("SKU", technical=True)),
    ),
    "product_link": _rules(
        (r"^producto_item_id$", field("Producto vinculado")),
    ),
    "competition": _rules(
        (r"^status$", field("Competencia de catálogo", names(COMPETITION_STATUS))),
        (r"^price_to_win$", field("Precio para ganar", money)),
        (r"^current_price$", field("Precio actual en catálogo", money, technical=True)),
        (r"^winner\.price$", field("Precio del ganador", money, technical=True)),
        (r"^winner\.item_id$", field("Publicación ganadora", technical=True)),
        (r"^catalog_product_id$", field("Producto de catálogo", technical=True)),
        (r"^visit_share$", field("Participación en visitas", technical=True)),
        (r"^boosts$", field("Ventajas", technical=True)),
    ),
}

# Paths with no rule are technical; these give them a name by their last segment.
TECHNICAL_NAMES = {
    "last_updated": ("Última actualización", moment),
    "date_created": ("Fecha de creación", moment),
    "reference_date": ("Fecha de referencia", moment),
    "start_time": ("Inicio", moment),
    "end_time": ("Fin", moment),
    "currency_id": ("Moneda", text_of),
}


def _fallback(path: str, old: Any, new: Any) -> Row:
    last = re.split(r"[.\[]", path)[-1].rstrip("]")
    label, fmt = TECHNICAL_NAMES.get(last, ("Dato técnico", text_of))
    if last.endswith("_id") or last == "id":
        label = "Identificador"
    elif label == "Dato técnico" and last.startswith("date_"):
        label, fmt = "Fecha", moment
    return Row(path, label, fmt(old), fmt(new), True)


def readable(resource_type: str, changes: Iterable[dict[str, Any]]) -> list[Row]:
    """The rows of one log row's `changes`, in the row's own order."""
    rows: list[Row] = []
    rules = RULES.get(resource_type, ())
    for stored in changes:
        path = str(stored.get("p", ""))
        old, new = stored.get("old"), stored.get("new")
        for pattern, build in rules:
            match = pattern.search(path)
            if match:
                rows.extend(build(path, old, new, match))
                break
        else:
            rows.append(_fallback(path, old, new))
    return rows


def visible(rows: Sequence[Row], *, include_technical: bool) -> tuple[list[Row], int]:
    """`(shown, hidden)`: technical rows are hidden and counted unless asked for."""
    if include_technical:
        return list(rows), 0
    shown = [row for row in rows if not row.is_technical]
    return shown, len(rows) - len(shown)
