"""A throwaway Postgres world for the sell-out allocation tests (T7 S2): the
campaign tables, the product groups and their filters, the three sale sources
and the BNA rates, plus bare stand-ins for what they reference.

Sales are written with `tests.services.sell_in._world.venta`, which shapes them
like production (fuera / TN at midnight UTC, a fuera return `signo = -1` with a
POSITIVE `cantidad`; ML one `ml_sale_lines` row per `ml_order_items_ops` row).
Products carry a brand, category and VAT like `productos_erp` (`iva` 21 or 10.5).
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date
from typing import Iterator, List, Optional, Sequence, Tuple

from sqlalchemy import Engine, text

from app.models.auditoria import Auditoria
from app.models.ml_orders_ops import MlOrderItemOps
from app.models.ml_sale_line import MlSaleLine
from app.models.offset_grupo import OffsetGrupo
from app.models.offset_grupo_filtro import OffsetGrupoFiltro
from app.models.producto import ProductoERP
from app.models.sell_out import SellOutCampana, SellOutCampanaGrupo, SellOutConsumo, SellOutDirty
from app.models.tipo_cambio import TipoCambio
from app.models.venta_fuera_ml_metrica import VentaFueraMLMetrica
from app.models.venta_tienda_nube_metrica import VentaTiendaNubeMetrica
from tests.services.sell._schema import throwaway_schema
from tests.services.sell_in._world import delete_venta, venta  # noqa: F401 - re-exported for the tests

STUBS = ["CREATE TABLE usuarios (id INTEGER PRIMARY KEY)", "INSERT INTO usuarios VALUES (7)"]
TABLES = [
    ProductoERP.__table__,
    OffsetGrupo.__table__,
    OffsetGrupoFiltro.__table__,
    SellOutCampana.__table__,
    SellOutCampanaGrupo.__table__,
    SellOutConsumo.__table__,
    SellOutDirty.__table__,
    Auditoria.__table__,
    TipoCambio.__table__,
    VentaFueraMLMetrica.__table__,
    VentaTiendaNubeMetrica.__table__,
    MlOrderItemOps.__table__,
    MlSaleLine.__table__,
]
# item_id -> (marca, categoria, subcategoria_id, iva)
PRODUCTOS = {
    2964: ("TP-LINK", "Routers", 11, 21.0),
    2270: ("TP-LINK", "Switches", 12, 10.5),
    950: ("MERCUSYS", "Routers", 11, 21.0),
}


def _install(engine: Engine) -> None:
    with engine.begin() as conn:
        for item_id, (marca, categoria, sub, iva) in PRODUCTOS.items():
            conn.execute(
                text(
                    "INSERT INTO productos_erp (item_id, codigo, descripcion, marca, categoria, subcategoria_id, iva) "
                    "VALUES (:i, :c, 'Producto', :m, :cat, :s, :iva)"
                ),
                {"i": item_id, "c": f"C{item_id}", "m": marca, "cat": categoria, "s": sub, "iva": iva},
            )


@contextmanager
def world(prefix: str) -> Iterator[Engine]:
    with throwaway_schema(prefix, TABLES, STUBS, after=_install) as engine:
        yield engine


def clean(engine: Engine) -> None:
    with engine.begin() as conn:
        for table in (
            "ml_order_items_ops",
            "ventas_fuera_ml_metricas",
            "ventas_tienda_nube_metricas",
            "sell_out_campanas",
            "offset_grupos",
            "tipo_cambio",
            "auditoria",
        ):
            conn.execute(text(f"DELETE FROM {table}"))  # sale lines, links, filters, consumptions, queue cascade


def queued(engine: Engine) -> List[Tuple[int, int, Optional[str]]]:
    """`(campana_id, attempts, last_error)` of `sell_out_dirty`, by campaign."""
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT campana_id, attempts, last_error FROM sell_out_dirty ORDER BY campana_id"))
        return [tuple(row) for row in rows]


def clear_queue(engine: Engine) -> None:
    execute(engine, "DELETE FROM sell_out_dirty")


def grupo(engine: Engine, filtros: Sequence[dict]) -> int:
    """An `offset_grupos` row with one `offset_grupo_filtros` row per dict (marca, categoria, ...)."""
    with engine.begin() as conn:
        gid = conn.execute(text("INSERT INTO offset_grupos (nombre) VALUES ('Grupo') RETURNING id")).scalar()
        for filtro in filtros:
            values = {"marca": None, "categoria": None, "subcategoria_id": None, "item_id": None, **filtro}
            conn.execute(
                text(
                    "INSERT INTO offset_grupo_filtros (grupo_id, marca, categoria, subcategoria_id, item_id) "
                    "VALUES (:g, :marca, :categoria, :subcategoria_id, :item_id)"
                ),
                {"g": gid, **values},
            )
    return gid


def campana(
    engine: Engine,
    grupos: Sequence[int],
    desde: date = date(2026, 11, 1),
    hasta: date = date(2026, 11, 30),
    **values,
) -> int:
    """A campaign as the API stores it: per unit, 10 ARS, no cap, stackable, unless overridden."""
    row = {
        "nombre": "Campaña",
        "fecha_desde": desde,
        "fecha_hasta": hasta,
        "tipo": "por_unidad",
        "monto_unit": "10.00",
        "porcentaje": None,
        "moneda": "ARS",
        "tc_modo": None,
        "tipo_cambio": None,
        "tope_unidades": None,
        "tope_monto": None,
        "acumulable": True,
        "monto_incluye_iva": False,
        "estado": "activa",
        **values,
    }
    columns = ", ".join(row)
    params = ", ".join(f":{c}" for c in row)
    with engine.begin() as conn:
        cid = conn.execute(
            text(f"INSERT INTO sell_out_campanas ({columns}, usuario_id) VALUES ({params}, 7) RETURNING id"), row
        ).scalar()
        for gid in grupos:
            conn.execute(
                text("INSERT INTO sell_out_campana_grupos (campana_id, grupo_id) VALUES (:c, :g)"), {"c": cid, "g": gid}
            )
    return cid


def tipo_cambio(engine: Engine, dia: date, venta_: float, moneda: str = "USD") -> None:
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO tipo_cambio (fecha, moneda, compra, venta) VALUES (:f, :m, :v, :v)"),
            {"f": dia, "m": moneda, "v": venta_},
        )


def execute(engine: Engine, sql: str, **params) -> None:
    with engine.begin() as conn:
        conn.execute(text(sql), params)


def consumos(engine: Engine, campana_id: Optional[int] = None) -> List[Tuple]:
    """`(campana_id, canal, venta_ref, item_id, fecha_venta, unidades, monto, tc_venta)`, in a stable order."""
    with engine.connect() as conn:
        return [
            tuple(row)
            for row in conn.execute(
                text(
                    "SELECT campana_id, canal, venta_ref, item_id, fecha_venta, unidades, monto, tc_venta "
                    "FROM sell_out_consumos WHERE campana_id = COALESCE(:c, campana_id) "
                    "ORDER BY campana_id, fecha_venta, canal, venta_ref"
                ),
                {"c": campana_id},
            )
        ]


def consumo_ids(engine: Engine) -> List[int]:
    with engine.connect() as conn:
        return [r[0] for r in conn.execute(text("SELECT id FROM sell_out_consumos ORDER BY id"))]
