"""The CSV export of the Publicaciones screen's current view (`/items/export`, `/products/export`).

The same discipline as Métricas ML's board export (`routers/ml_metricas.export_board`): the first short transaction
fixes the ORDERED keys of every row (`listing.ordered_keys`, `products.ordered_product_keys`: the list's own order,
the markup sort and filter included) and reads page 1; every later page of `EXPORT_PAGE_SIZE` keys is read BY KEY on
its own short session, so a change between pages can never repeat or drop a row. This module holds what the two
endpoints share: the caps, the columns (the list's own, by the screen's labels), the stream and the Ads cost read
once for the whole file. `;` delimiter and a UTF-8 BOM, so a spreadsheet in the Spanish locale opens it as is;
every free-text cell goes through `csv_text`.
"""

from __future__ import annotations

import csv
import io
import logging
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Callable, Iterator, Mapping, Optional, Sequence

from app.services.ml_daily_metrics import board
from app.services.ml_daily_metrics.kpi_strip import round_money, round_pp
from app.services.ml_publications.view.ads import AdsAvailability, AdsCostProvider
from app.utils.csv_cells import csv_money, csv_text

logger = logging.getLogger(__name__)

# Rows per page, each page on its own short DB session: memory and the pooled connection follow ONE page.
EXPORT_PAGE_SIZE = 500
# Beyond this many rows the export refuses (422) and asks for narrower filters, like Métricas ML's.
EXPORT_MAX_ROWS = 10_000

# The screen's labels of a row's `sku_divergence` kind (`skuDivergence.js`).
DIVERGENCE_LABELS = {"otro_producto": "Otro producto", "sin_coincidencia": "SKU sin coincidencia"}


def over_cap_message() -> str:
    return (
        f"Son más de {EXPORT_MAX_ROWS} filas, demasiadas para exportar de una vez. "
        "Acotá los filtros (estado, tienda, marca, búsqueda...)."
    )


@dataclass(frozen=True)
class Column:
    """One CSV column: its header (the screen's label), how a row fills it, and the permission it needs:
    `sales` = `ml_metricas.ver`, `margin` = `ml_metricas.ver_ganancia` (both when both are set)."""

    header: str
    cell: Callable[[Any, Any], Any]
    sales: bool = False
    margin: bool = False


def visible(columns: Sequence[Column], *, sales: bool, margin: bool) -> list[Column]:
    return [c for c in columns if (sales or not c.sales) and (margin or not c.margin)]


def _iso(value: Optional[datetime]) -> str:
    return value.isoformat() if value else ""


def _blank(value: Any) -> Any:
    return "" if value is None else value


def _money(value: Any) -> str:
    return csv_money(None if value is None else float(value))


def _store(item: Mapping[str, Any]) -> str:
    return csv_text(item["store_label"] or (str(item["official_store_id"]) if item["official_store_id"] else None))


def _divergence(item: Mapping[str, Any]) -> str:
    found = item["sku_divergence"]
    if found is None:
        return ""
    label = DIVERGENCE_LABELS.get(found["kind"], found["kind"])
    return csv_text(f"{label} ({found['codigo']})" if found["codigo"] else label)


def _worst(item: Mapping[str, Any]) -> str:
    return _money((item.get("markup") or {}).get("worst"))


def _metric(read: Callable[[board.Row], Any]) -> Callable[[Any, Optional[board.Row]], Any]:
    """A Métricas figure of the row: empty when Métricas has no row for it (never sold, unknown to the ERP)."""
    return lambda _, m: "" if m is None else _blank(read(m))


# A publication row (`listing._item`, its markup attached) and its Métricas ML row (`row_metrics`), or None.
ITEM_COLUMNS: tuple[Column, ...] = (
    Column("Publicación", lambda i, m: csv_text(i["item_id"])),
    Column("Título", lambda i, m: csv_text(i["title"])),
    Column("Estado", lambda i, m: csv_text(i["status"])),
    Column("Tipo", lambda i, m: csv_text(i["listing_type_id"])),
    Column("Full", lambda i, m: "Sí" if i["is_full"] else "No"),
    Column("Tienda", lambda i, m: _store(i)),
    Column("SKU", lambda i, m: csv_text(i["seller_sku"])),
    Column("Vínculo", lambda i, m: csv_text(i["link"]["state"])),
    Column("Código", lambda i, m: csv_text(i["link"]["codigo"])),
    Column("Producto", lambda i, m: csv_text(i["link"]["descripcion"])),
    Column("SKU distinto", lambda i, m: _divergence(i)),
    Column("Precio", lambda i, m: _money(i["price"]["amount"])),
    Column("Markup actual", lambda i, m: _worst(i), margin=True),
    Column("Ventas 7D", _metric(lambda m: m.windows["7d"]), sales=True),
    Column("Ventas 30D", _metric(lambda m: m.windows["30d"]), sales=True),
    Column("Markup real 30D", _metric(lambda m: _money(round_pp(m.markup))), sales=True, margin=True),
    Column("Facturado 30D", _metric(lambda m: _money(round_money(m.gross))), sales=True),
    Column("Total Gauss 30D", _metric(lambda m: _money(round_money(m.tg))), sales=True, margin=True),
    Column("Última venta", _metric(lambda m: _iso(m.last_sale_at)), sales=True),
    Column("Ageing (días)", _metric(lambda m: m.ageing_days), sales=True),
    Column("Stock propio", lambda i, m: _blank(i["stock"]["own"])),
    Column("Stock Full", lambda i, m: _blank(i["stock"]["full"])),
    Column("Stock ERP", lambda i, m: _blank(i["erp_stock"]["quantity"])),
    Column("Última actividad", lambda i, m: _iso(i["last_activity_at"])),
)

# A Producto-view row (`products._row`) and whether it has figures (some publication of it has a Board row).
PRODUCT_COLUMNS: tuple[Column, ...] = (
    Column("Código", lambda r, _: csv_text(r.sku)),
    Column("Producto", lambda r, _: csv_text(r.title)),
    Column("Marca", lambda r, _: csv_text(r.marca)),
    Column("Publicaciones", lambda r, _: r.publications_count),
    Column("Stock ERP", lambda r, _: _blank(r.stock)),
    Column("Ventas 7D", lambda r, has: r.windows["7d"] if has else "", sales=True),
    Column("Ventas 30D", lambda r, has: r.windows["30d"] if has else "", sales=True),
    Column("Markup real 30D", lambda r, has: _money(round_pp(r.markup)) if has else "", sales=True, margin=True),
    Column("Facturado 30D", lambda r, has: _money(round_money(r.gross)) if has else "", sales=True),
    Column("Total Gauss 30D", lambda r, has: _money(round_money(r.tg)) if has else "", sales=True, margin=True),
    Column("Última venta", lambda r, has: _iso(r.last_sale_at) if has else "", sales=True),
    Column("Ageing (días)", lambda r, has: _blank(r.ageing_days) if has else "", sales=True),
)


def lines(columns: Sequence[Column], rows: Sequence[tuple[Any, Any]]) -> list[list[Any]]:
    """The CSV lines of `(row, extra)` pairs, one cell per visible column."""
    return [[column.cell(row, extra) for column in columns] for row, extra in rows]


def _text(rows: Sequence[Sequence[Any]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")
    writer.writerows(rows)
    return buffer.getvalue()


def stream(
    columns: Sequence[Column],
    keys: Sequence[Any],
    first: list[list[Any]],
    fetch: Callable[[Sequence[Any]], list[list[Any]]],
    page_size: int,
    label: str,
    notes: Callable[[], Sequence[str]] = tuple,
) -> Iterator[str]:
    """The file: BOM and header, page 1 (already read), then every later page of keys through `fetch` (its own
    session). The 200 and the header are on the wire by then, so a page that fails ends the FILE with an error line
    saying how many rows it holds. `notes`, read once every page is written, are trailing lines that qualify the
    figures (e.g. `ADS_NOTE`)."""
    yield "﻿" + _text([[column.header for column in columns]])
    page, exported = first, 0
    for start in range(0, len(keys), page_size):
        if start:
            try:
                page = fetch(keys[start : start + page_size])
            except Exception:  # noqa: BLE001
                logger.exception("ml-publications %s export: page at %s failed", label, start)
                yield (
                    f"# ERROR: exportación incompleta — {exported} de {len(keys)} filas exportadas. Volvé a intentar.\n"
                )
                return
        yield _text(page)
        exported += len(page)
    for note in notes():
        yield note


# The trailing line of a file whose markup was asked net of Ads (`restar_publicidad`) but could not be: the list says
# it in its `ads` block (`reason`), the file in this line, the way it states a page that failed.
ADS_NOTE = (
    "# AVISO: el markup no descuenta la publicidad — el costo de Ads no estuvo disponible ({reason}). "
    "Volvé a intentar más tarde.\n"
)


class PrefetchedAds:
    """The Ads cost of the period, read ONCE through the request's provider (bound to the request session, which is
    closed before the file streams), BEFORE the keys are fixed: the markup sort and filter that fix them and every
    page that prices its rows read this one source, so a failure applies to the whole file alike. A provider that failed reads
    as failing on every page, so the markup degrades to the plain one exactly as the list's does."""

    def __init__(self, provider: AdsCostProvider, date_from: date, date_to: date) -> None:
        self._failed = False
        self._amounts: dict[str, float] = {}
        try:
            # Every MLA with cost in the period (the set-wide sort's own read): the keys are not fixed yet.
            self._amounts = dict(provider.amounts(None, date_from, date_to))
        except Exception:  # noqa: BLE001 -- the provider is an external source allowed to fail softly
            logger.warning("ads provider failed; the export's markup goes without Ads", exc_info=True)
            self._failed = True

    @property
    def failed(self) -> bool:
        return self._failed

    def availability(self) -> AdsAvailability:
        return AdsAvailability.AVAILABLE

    def amounts(self, mla_ids: Optional[Sequence[str]], date_from: date, date_to: date) -> Mapping[str, float]:
        if self._failed:
            raise RuntimeError("the Ads cost could not be read for this export")
        if mla_ids is None:
            return dict(self._amounts)
        return {mla: self._amounts[mla] for mla in mla_ids if mla in self._amounts}
