"""Rentabilidad cards of Ventas por fuera and Tienda Nube with sales whose cost is unknown (costo SI T3 PR 10, D1).

A metric line whose `costo_total` is NULL (the costo SI crons store an unknown cost so) or 0 (legacy rows: a real
cost is never 0) is "sin costo": it counts in `monto_venta` and `total_ventas`, is counted in `ventas_sin_costo`,
and adds nothing to `costo_total`, `ganancia` or `markup_*`, which are computed over the costed lines only. A card
without any costed line shows those figures as null, never 0.

The endpoints run on a throwaway Postgres schema holding the tables they read (built from the ORM, without foreign
keys), seeded with invented rows. No offsets are seeded; Tienda Nube uses its default 1 % commission (no
`pricing_constants` row).
"""

from __future__ import annotations

from datetime import date
from typing import Iterator, Optional

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.schema import CreateTable

from app.api.endpoints.rentabilidad_fuera import obtener_rentabilidad_fuera
from app.api.endpoints.rentabilidad_tienda_nube import obtener_rentabilidad_tienda_nube
from app.models.offset_ganancia import OffsetGanancia
from app.models.offset_grupo_consumo import OffsetGrupoConsumo
from app.models.offset_grupo_filtro import OffsetGrupoFiltro
from app.models.offset_individual_consumo import OffsetIndividualConsumo
from app.models.pricing_constants import PricingConstants
from app.models.usuario import Usuario
from app.models.vendedor_excluido import VendedorExcluido
from app.models.venta_fuera_ml_metrica import VentaFueraMLMetrica
from app.models.venta_tienda_nube_metrica import VentaTiendaNubeMetrica
from tests.conftest import _patch_pg_types_for_sqlite, _restore_pristine_pg_types
from tests.services.sell._schema import throwaway_schema

_TABLES = [
    VentaFueraMLMetrica.__table__,
    VentaTiendaNubeMetrica.__table__,
    OffsetGanancia.__table__,
    OffsetGrupoFiltro.__table__,
    OffsetGrupoConsumo.__table__,
    OffsetIndividualConsumo.__table__,
    VendedorExcluido.__table__,
    PricingConstants.__table__,
]

DESDE = date(2026, 1, 1)
HASTA = date(2026, 1, 31)

# (marca, monto_total, costo_total, signo). ACME: one costed sale + one with unknown cost (NULL).
# CERO: its only line has a legacy cost of 0 (unknown). FULL: every line costed, a return included (the pin).
_LINEAS = [
    ("ACME", 1000, 600, 1),
    ("ACME", 500, None, 1),
    ("CERO", 300, 0, 1),
    ("FULL", 1000, 600, 1),
    ("FULL", 200, 100, 1),
    ("FULL", 100, 50, -1),
]


def _create_tables(engine: Engine) -> None:
    # Without foreign keys: the endpoints only need these tables, not everything they point to.
    _restore_pristine_pg_types(_TABLES)
    try:
        with engine.begin() as conn:
            for table in _TABLES:
                conn.execute(CreateTable(table, include_foreign_key_constraints=[]))
    finally:
        _patch_pg_types_for_sqlite()


def _insert(conn, table: str, it_transaction: int, marca: str, monto: int, costo: Optional[int], signo: int) -> None:
    conn.execute(
        text(
            f"INSERT INTO {table} (it_transaction, fecha_venta, item_id, codigo, descripcion, marca, categoria, "
            "cantidad, signo, monto_total, costo_total) "
            "VALUES (:it, '2026-01-15 12:00:00', :item, :codigo, 'Producto', :marca, 'Cat', 1, :signo, :monto, :costo)"
        ),
        {
            "it": it_transaction,
            "item": 1000 + it_transaction,
            "codigo": f"C{it_transaction}",
            "marca": marca,
            "signo": signo,
            "monto": monto,
            "costo": costo,
        },
    )


@pytest.fixture()
def db() -> Iterator[Session]:
    with throwaway_schema("rent_sin_costo", [], after=_create_tables) as engine:
        with engine.begin() as conn:
            for i, (marca, monto, costo, signo) in enumerate(_LINEAS, start=1):
                _insert(conn, "ventas_fuera_ml_metricas", i, marca, monto, costo, signo)
                _insert(conn, "ventas_tienda_nube_metricas", i, marca, monto, costo, signo)
        session = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
        try:
            yield session
        finally:
            session.close()


def _user() -> Usuario:
    user = Usuario()
    user.id = 1
    return user


def _fuera(db: Session):
    return obtener_rentabilidad_fuera(
        fecha_desde=DESDE,
        fecha_hasta=HASTA,
        sucursal=None,
        vendedor=None,
        marcas=None,
        categorias=None,
        subcategorias=None,
        productos=None,
        db=db,
        current_user=_user(),
    )


def _tn(db: Session):
    return obtener_rentabilidad_tienda_nube(
        fecha_desde=DESDE,
        fecha_hasta=HASTA,
        marcas=None,
        categorias=None,
        subcategorias=None,
        productos=None,
        vendedores=None,
        db=db,
        current_user=_user(),
    )


def _card(response, nombre: str):
    return next(card for card in response.cards if card.nombre == nombre)


def _figures(card, *extra: str) -> dict:
    keys = ("monto_venta", "costo_total", "ganancia", "markup_promedio", "ganancia_con_offset", "markup_con_offset")
    out = {key: getattr(card, key) for key in keys + extra}
    return {key: round(value, 2) if isinstance(value, float) else value for key, value in out.items()}


# ---------------------------------------------------------------------------
# Ventas por fuera
# ---------------------------------------------------------------------------


def test_fuera_card_with_an_unknown_cost_sums_only_the_costed_sales(db: Session) -> None:
    card = _card(_fuera(db), "ACME")

    assert _figures(card) == {
        "monto_venta": 1500.0,
        "costo_total": 600.0,
        "ganancia": 400.0,
        "markup_promedio": 66.67,
        "ganancia_con_offset": 400.0,
        "markup_con_offset": 66.67,
    }
    assert card.ventas_sin_costo == 1
    assert card.total_ventas == 2


def test_fuera_card_without_any_costed_sale_has_no_cost_ganancia_or_markup(db: Session) -> None:
    card = _card(_fuera(db), "CERO")

    assert _figures(card) == {
        "monto_venta": 300.0,
        "costo_total": None,
        "ganancia": None,
        "markup_promedio": None,
        "ganancia_con_offset": None,
        "markup_con_offset": None,
    }
    assert card.ventas_sin_costo == 1
    assert card.total_ventas == 1


def test_fuera_card_with_every_sale_costed_keeps_its_numbers(db: Session) -> None:
    card = _card(_fuera(db), "FULL")

    # Same figures as before the change: monto 1000 + 200 - 100, costo 600 + 100 - 50.
    assert _figures(card) == {
        "monto_venta": 1100.0,
        "costo_total": 650.0,
        "ganancia": 450.0,
        "markup_promedio": 69.23,
        "ganancia_con_offset": 450.0,
        "markup_con_offset": 69.23,
    }
    assert card.ventas_sin_costo == 0
    assert card.total_ventas == 1
    assert card.offset_total == 0.0


def test_fuera_totales_count_the_unknown_sales_apart(db: Session) -> None:
    totales = _fuera(db).totales

    assert _figures(totales) == {
        "monto_venta": 2900.0,
        "costo_total": 1250.0,
        "ganancia": 850.0,
        "markup_promedio": 68.0,
        "ganancia_con_offset": 850.0,
        "markup_con_offset": 68.0,
    }
    assert totales.ventas_sin_costo == 2
    assert totales.total_ventas == 4


# ---------------------------------------------------------------------------
# Tienda Nube (default commission 1 %)
# ---------------------------------------------------------------------------


def test_tn_card_with_an_unknown_cost_sums_only_the_costed_sales(db: Session) -> None:
    card = _card(_tn(db), "ACME")

    # monto_venta, comisión and monto limpio stay over every sale; the ganancia is the costed sale's
    # monto limpio (1000 - 1 %) minus its cost.
    assert _figures(card, "comision_tn", "monto_limpio") == {
        "monto_venta": 1500.0,
        "comision_tn": 15.0,
        "monto_limpio": 1485.0,
        "costo_total": 600.0,
        "ganancia": 390.0,
        "markup_promedio": 65.0,
        "ganancia_con_offset": 390.0,
        "markup_con_offset": 65.0,
    }
    assert card.ventas_sin_costo == 1
    assert card.total_ventas == 2


def test_tn_card_without_any_costed_sale_has_no_cost_ganancia_or_markup(db: Session) -> None:
    card = _card(_tn(db), "CERO")

    assert _figures(card, "comision_tn", "monto_limpio") == {
        "monto_venta": 300.0,
        "comision_tn": 3.0,
        "monto_limpio": 297.0,
        "costo_total": None,
        "ganancia": None,
        "markup_promedio": None,
        "ganancia_con_offset": None,
        "markup_con_offset": None,
    }
    assert card.ventas_sin_costo == 1


def test_tn_card_with_every_sale_costed_keeps_its_numbers(db: Session) -> None:
    card = _card(_tn(db), "FULL")

    # Same figures as before the change: monto 1100, comisión 11, limpio 1089, costo 650.
    assert _figures(card, "comision_tn", "monto_limpio") == {
        "monto_venta": 1100.0,
        "comision_tn": 11.0,
        "monto_limpio": 1089.0,
        "costo_total": 650.0,
        "ganancia": 439.0,
        "markup_promedio": 67.54,
        "ganancia_con_offset": 439.0,
        "markup_con_offset": 67.54,
    }
    assert card.ventas_sin_costo == 0
    assert card.total_ventas == 3
    assert card.offset_total == 0.0


def test_tn_totales_count_the_unknown_sales_apart(db: Session) -> None:
    totales = _tn(db).totales

    assert _figures(totales, "comision_tn", "monto_limpio") == {
        "monto_venta": 2900.0,
        "comision_tn": 29.0,
        "monto_limpio": 2871.0,
        "costo_total": 1250.0,
        "ganancia": 829.0,
        "markup_promedio": 66.32,
        "ganancia_con_offset": 829.0,
        "markup_con_offset": 66.32,
    }
    assert totales.ventas_sin_costo == 2
    assert totales.total_ventas == 6


# ---------------------------------------------------------------------------
# A line stored with a negative cost (e.g. a negative quantity) has a KNOWN cost: only NULL and 0 are unknown
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("tabla, leer", [("ventas_fuera_ml_metricas", _fuera), ("ventas_tienda_nube_metricas", _tn)])
def test_a_negative_cost_is_a_known_cost_not_sin_costo(db: Session, tabla: str, leer) -> None:
    _insert(db.connection(), tabla, 90, "NEGATIVO", 1000, 600, 1)
    _insert(db.connection(), tabla, 91, "NEGATIVO", -500, -300, 1)

    card = _card(leer(db), "NEGATIVO")

    assert card.ventas_sin_costo == 0
    assert card.costo_total == 300.0
    assert card.monto_venta == 500.0
