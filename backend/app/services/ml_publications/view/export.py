"""The CSV export of the Publicaciones screen's current view (`/items/export`, `/products/export`), and the Auditoría
de stock workbook (`/stock-audit/export`, at the end).

The same discipline as Métricas ML's board export (`routers/ml_metricas.export_board`): the first short transaction
fixes the ORDERED keys of every row (`listing.ordered_keys`, `products.ordered_product_keys`: the list's own order,
the markup sort and filter included) and reads page 1; every later page of `EXPORT_PAGE_SIZE` keys is read BY KEY on
its own short session, so a change between pages can never repeat or drop a row. This module holds what the two
endpoints share: the page size, the columns (the list's own, by the screen's labels), the stream and the Ads cost read
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
from app.services.ml_publications.listing_kind import kind_label
from app.services.ml_publications.view.ads import AdsAvailability, AdsCostProvider
from app.utils.csv_cells import csv_money, csv_text

logger = logging.getLogger(__name__)

# Rows per page, each page on its own short DB session: memory and the pooled connection follow ONE page. There is
# no row cap: the export fixes EVERY key (a few bytes each), never more than one page of rows.
EXPORT_PAGE_SIZE = 500

# The screen's labels of a row's `sku_divergence` kind (`skuDivergence.js`).
DIVERGENCE_LABELS = {"otro_producto": "Otro producto", "sin_coincidencia": "SKU sin coincidencia"}


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


def _siso_worst(item: Mapping[str, Any]) -> str:
    """Markup actual c/ SISO: its worst variation, "Pendiente" when it has no value because a unit's sell in / sell
    out could not be priced (as the list says), empty otherwise."""
    siso = item.get("markup_siso") or {}
    if siso.get("worst") is None and siso.get("pending"):
        return "Pendiente"
    return _money(siso.get("worst"))


def _sell_shown(row: Any) -> Optional[float]:
    """Markup real 30D c/ SISO as the views show it: the Board's `markup_sell`, the plain markup where neither
    applies (Auditoría's rule)."""
    return round_pp(row.markup_sell if row.markup_sell is not None else row.markup)


def _metric(read: Callable[[board.Row], Any]) -> Callable[[Any, Optional[board.Row]], Any]:
    """A Métricas figure of the row: empty when Métricas has no row for it (never sold, unknown to the ERP)."""
    return lambda _, m: "" if m is None else _blank(read(m))


# A publication row (`listing._item`, its markup attached) and its Métricas ML row (`row_metrics`), or None.
ITEM_COLUMNS: tuple[Column, ...] = (
    Column("Publicación", lambda i, m: csv_text(i["item_id"])),
    Column("Título", lambda i, m: csv_text(i["title"])),
    Column("Estado", lambda i, m: csv_text(i["status"])),
    # The readable type, as the list's Tipo badge (owner, 2026-11-02): Clásica, 3 cuotas, ..., not ML's raw id.
    Column("Tipo", lambda i, m: csv_text(kind_label(i["listing_kind"]))),
    Column("Full", lambda i, m: "Sí" if i["is_full"] else "No"),
    Column("Tienda", lambda i, m: _store(i)),
    Column("SKU", lambda i, m: csv_text(i["seller_sku"])),
    Column("Vínculo", lambda i, m: csv_text(i["link"]["state"])),
    Column("Código", lambda i, m: csv_text(i["link"]["codigo"])),
    Column("Producto", lambda i, m: csv_text(i["link"]["descripcion"])),
    Column("SKU distinto", lambda i, m: _divergence(i)),
    Column("Precio", lambda i, m: _money(i["price"]["amount"])),
    Column("Markup actual", lambda i, m: _worst(i), margin=True),
    Column("Markup actual c/ SISO", lambda i, m: _siso_worst(i), margin=True),
    Column("Ventas 7D", _metric(lambda m: m.windows["7d"]), sales=True),
    Column("Ventas 30D", _metric(lambda m: m.windows["30d"]), sales=True),
    Column("Markup real 30D", _metric(lambda m: _money(round_pp(m.markup))), sales=True, margin=True),
    Column("Markup real 30D c/ SISO", _metric(lambda m: _money(_sell_shown(m))), sales=True, margin=True),
    Column("Facturado 30D", _metric(lambda m: _money(round_money(m.gross))), sales=True),
    Column("Total Gauss 30D", _metric(lambda m: _money(round_money(m.tg))), sales=True, margin=True),
    Column("Última venta", _metric(lambda m: _iso(m.last_sale_at)), sales=True),
    Column("Ageing (días)", _metric(lambda m: m.ageing_days), sales=True),
    Column("Stock ERP", lambda i, m: _blank(i["erp_stock"]["quantity"])),
    Column("Stock Full", lambda i, m: _blank(i["stock"]["full"])),
    Column("Stock total", lambda i, m: _blank(i["stock_total"])),
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
    Column("Markup real 30D c/ SISO", lambda r, has: _money(_sell_shown(r)) if has else "", sales=True, margin=True),
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


# ── The Auditoría de stock workbook (`/stock-audit/export`, L7) ──────────────────────────────────

AUDIT_KINDS = {
    "producto": "Producto",
    "pc": "PC",
    "variante": "Variante",
    "pack": "Pack",
    "marca": "Marca",
    "categoria": "Categoría",
}


def _sold(ventas: Optional[Mapping[str, Any]], key: str, factor: float) -> Any:
    return None if ventas is None else ventas[key] * factor


def _day(at: Optional[datetime]) -> Optional[str]:
    """A moment as its business day (the Board's clock), the way the view shows the last sale."""
    return None if at is None else at.astimezone(board.BUSINESS_TZ).date().isoformat()


def _rotation(ventas: Optional[Mapping[str, Any]]) -> list[Any]:
    """The Rotación columns (rotacion S2): Última venta, the days since it, the ageing, Días de cobertura ("∞" with
    stock and no sale) and Rotación (veces); empty cells where the view reads "—"."""
    if ventas is None:
        return [None] * 5
    coverage = "∞" if ventas["cobertura_infinita"] else ventas["dias_cobertura"]
    return [
        _day(ventas["ultima_venta"]),
        ventas["ultima_venta_dias"],
        ventas["ageing_dias"],
        coverage,
        ventas["rotacion"],
    ]


def _envio(ventas: Optional[Mapping[str, Any]], factor: float) -> list[Any]:
    """auditoria-stock-niveles S3/S5: each window's ERP and Full units (in base units, like the totals) and the ERP
    ones without shipping data."""
    if ventas is None:
        return [None] * 5
    split = ventas["envio"]
    return [
        split["7d"]["erp"] * factor,
        split["7d"]["full"] * factor,
        split["30d"]["erp"] * factor,
        split["30d"]["full"] * factor,
        split["30d"]["sin_envio"] * factor,
    ]


def _by_source(ventas: Optional[Mapping[str, Any]]) -> list[Any]:
    """S4/S5: Días de cobertura and Rotación of ERP and of Full ("∞" with stock and no sale)."""
    if ventas is None:
        return [None] * 4
    erp, full = ventas["por_origen"]["erp"], ventas["por_origen"]["full"]

    def days(part: Mapping[str, Any]) -> Any:
        return "∞" if part["cobertura_infinita"] else part["dias_cobertura"]

    return [days(erp), days(full), erp["rotacion"], full["rotacion"]]


def _shown(ventas: Optional[Mapping[str, Any]], sell: str, plain: str) -> Any:
    """The figure the view shows: the sell in / out one where it applies, else the plain one."""
    if ventas is None:
        return None
    return ventas.get(sell) if ventas.get(sell) is not None else ventas.get(plain)


def stock_audit_lines(rows: Sequence[Mapping[str, Any]], *, sales: bool, margin: bool) -> list[list[Any]]:
    """The audit's rows (`stock_audit.row_out`, in the view's order) as sheet lines: the header, then each base row
    followed by its variants and packs. A variant's ERP is the base's and stays empty; its Full and its sales are in
    base units (a pack's times its quantity), as the view shows them. Values the view reads "—" are empty cells,
    never 0; the sales columns only with `sales` (`ml_metricas.ver`), the profit and markups only with `margin`.

    At the Marca / Categoría levels (auditoria-stock-niveles S5) a row is a group (`stock_audit.group_out`) carrying
    its base rows in `filas` and, a brand, its categories in `categorias`: each group line is followed by its
    categories' lines (each followed by its products) or its products."""
    header = ["Tipo", "Código", "Producto", "Producto base", "Cantidad", "Costo", "Moneda costo"]
    header += ["Stock ERP", "Stock Full", "Stock total"]
    header += [
        "Valor ERP USD",
        "Valor ERP ARS",
        "Valor Full USD",
        "Valor Full ARS",
        "Valor total USD",
        "Valor total ARS",
    ]
    header += ["Sin costo", "Publicaciones", "Publicación activa", "Promo aplicada"]
    if sales:
        header += ["Ventas 7D", "Ventas 30D", "Facturado 30D"]
        header += [
            "Ventas 7D ERP",
            "Ventas 7D Full",
            "Ventas 30D ERP",
            "Ventas 30D Full",
            "Ventas 30D sin dato de envío",
        ]
        header += ["Última venta", "Días desde última venta", "Ageing (días)", "Días de cobertura", "Rotación (veces)"]
        header += ["Días de cobertura ERP", "Días de cobertura Full", "Rotación ERP", "Rotación Full"]
        if margin:
            header += ["Total Gauss 30D", "Markup real 30D", "Markup actual mín", "Markup actual máx"]
            header += ["Markup actual c/ SISO mín", "Markup actual c/ SISO máx"]

    def yes_no(value: Optional[bool]) -> Optional[str]:
        return None if value is None else ("Sí" if value else "No")

    def figures(
        ventas: Optional[Mapping[str, Any]],
        factor: float,
        markup: Optional[Mapping[str, Any]],
        siso: Optional[Mapping[str, Any]] = None,
    ) -> list[Any]:
        if not sales:
            return []
        out = [_sold(ventas, "unidades_7d", factor), _sold(ventas, "unidades_30d", factor)]
        out.append(None if ventas is None else ventas["facturado_30d"])
        out += _envio(ventas, factor)
        out += _rotation(ventas)
        out += _by_source(ventas)
        if margin:
            out += [
                _shown(ventas, "total_gauss_sell_30d", "total_gauss_30d"),
                _shown(ventas, "markup_sell_30d", "markup_30d"),
            ]
            out += [None, None] if markup is None else [markup["min"], markup["max"]]
            out += [None, None] if siso is None else [siso["min"], siso["max"]]
        return out

    lines: list[list[Any]] = [header]

    def group(row: Mapping[str, Any]) -> None:
        erp, full, total = row["erp"], row["full"], row["total"]
        lines.append(
            [AUDIT_KINDS.get(row["tipo"], row["tipo"]), None, row["descripcion"], None, None, None, None]
            + [erp["unidades"], full["unidades"], total["unidades"]]
            + [erp["usd"], erp["ars"], full["usd"], full["ars"], total["usd"], total["ars"]]
            + [yes_no(row["sin_costo"]), row["publications_count"], yes_no(row["publicacion_activa"])]
            + [yes_no(row["promo_aplicada"])]
            + figures(row["ventas"], 1, row.get("markup_actual"), row.get("markup_siso"))
        )
        for categoria in row.get("categorias", []):
            group(categoria)
        products(row.get("filas", []))

    def products(rows: Sequence[Mapping[str, Any]]) -> None:
        for row in rows:
            product(row)

    def product(row: Mapping[str, Any]) -> None:
        erp, full, total = row["erp"], row["full"], row["total"]
        lines.append(
            [AUDIT_KINDS.get(row["tipo"], row["tipo"]), row["codigo"], row["descripcion"], None, 1, row["costo"]]
            + [row["moneda_costo"], erp["unidades"], full["unidades"], total["unidades"]]
            + [erp["usd"], erp["ars"], full["usd"], full["ars"], total["usd"], total["ars"]]
            + [yes_no(row.get("sin_costo", False)), row["publications_count"], yes_no(row["publicacion_activa"])]
            + [yes_no(row["promo_aplicada"])]
            + figures(row["ventas"], 1, row.get("markup_actual"), row.get("markup_siso"))
        )
        for v in row["variantes"]:
            vfull = v["full"]
            lines.append(
                [AUDIT_KINDS.get(v["tipo"], v["tipo"]), v["codigo"], v["descripcion"], row["codigo"], v["cantidad"]]
                + [v["costo"], v["moneda_costo"], None, v["full_unidades_base"], v["full_unidades_base"]]
                + [None, None, vfull["usd"], vfull["ars"], vfull["usd"], vfull["ars"]]
                + [yes_no(v.get("sin_costo", False)), v["publications_count"], None, None]
                + figures(v["ventas"], v["cantidad"], v.get("markup_actual"), v.get("markup_siso"))
            )

    for row in rows:
        if row["tipo"] in ("marca", "categoria"):
            group(row)
        else:
            product(row)
    return lines


def workbook(lines: Sequence[Sequence[Any]], title: str) -> bytes:
    """One sheet of `lines` (the first is the header, in bold, frozen) as .xlsx bytes."""
    from openpyxl import Workbook
    from openpyxl.styles import Font

    book = Workbook()
    sheet = book.active
    sheet.title = title[:31]
    for line in lines:
        sheet.append([_cell(value) for value in line])
    # openpyxl reads a text starting with "=" as a formula: every text cell stays text (no formula injection).
    for row in sheet.iter_rows():
        for cell in row:
            if isinstance(cell.value, str):
                cell.data_type = "s"
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    sheet.freeze_panes = "A2"
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def _cell(value: Any) -> Any:
    """A sheet cell: a whole number as an int, anything else as it is."""
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value
