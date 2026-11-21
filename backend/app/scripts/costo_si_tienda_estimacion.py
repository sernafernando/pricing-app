"""Costo SI T3 PR 6 estimate: how the Tienda Gremio / Sugerido prices move once they are priced over costo SI (owner
L20: "los precios de gremio y sugerido toman costo si"), measured on a database without writing to it.

    python -m app.scripts.costo_si_tienda_estimacion --out <dir> [--url-env VAR]

The database URL is read from the environment variable `--url-env` (default COSTO_SI_DRY_RUN_DATABASE_URL) and never
printed. Read-only by construction, the T4 dry-run's `simulacion`: its own connection, every transaction `BEGIN READ
ONLY`, only SELECT (no SET, no CREATE), `costo_si_pasos` and any table the pending migrations add as MATERIALIZED CTEs,
rolled back at the end. Before the deploy there is no costo SI history, so the one the deploy's recompute WILL store
is computed in memory first (`impacto.calcular_pasos` over `queue.productos_vigentes`, as the T4 dry-run does).

Per active product, in pesos at the current USD rate:
- Gremio (no manual price: a manual one is stored and does not move, D4): list cost vs costo SI, x (1 + varios) x
  (1 + the product's or the brand's Gremio markup).
- Sugerido: before = list cost x (1 + varios) x (1 + clásica + sugerido); after = costo SI x (1 + varios) x (1 +
  clásica over costo SI + sugerido). The deploy's drain stores a product's costo SI steps and rewrites its clásica
  markup over them in ONE transaction (`queue.drenar` -> `despues.pricing`), so the listing never pairs a costo SI
  with a clásica still over the list cost; here the rewritten one is estimated as (1 + clásica over costo SI) = (1 +
  clásica) x list / costo SI, which holds while the stored markup is up to date with the list cost (the ML price does
  not move, D4). `clasica_sin_recalculo`: a costo SI product whose clásica the drain cannot rewrite (no ML price, no
  list 4 commission for its group, no IVA), so its stored one would stay over the list cost.
A product whose costo SI in pesos is unknown gets no price after (`sin_costo`). Brand markups are matched by
`brand_desc` like the gremio export. Writes `tienda_estimacion.csv` and prints a summary.
"""

from __future__ import annotations

import argparse
import csv
import logging
import os
import statistics
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.markup_tienda import MarkupTiendaBrand, MarkupTiendaProducto
from app.models.precio_gremio_override import PrecioGremioOverride
from app.models.producto import ProductoERP, ProductoPricing
from app.services.costo_si import impacto, lote, queue, simulacion
from app.services.pricing_calculator import (
    costos_ars_de,
    moneda_de,
    obtener_comision_base,
    obtener_constantes_pricing,
    obtener_grupo_subcategoria,
    obtener_tipo_cambio_actual,
)

URL_ENV = "COSTO_SI_DRY_RUN_DATABASE_URL"


@dataclass
class Fila:
    item_id: int
    stock: float
    fuente: Optional[str]
    costo_lista_ars: Optional[float]
    costo_si_ars: Optional[float]
    gremio_antes: Optional[float] = None
    gremio_despues: Optional[float] = None
    sugerido_antes: Optional[float] = None
    sugerido_despues: Optional[float] = None
    clasica_sin_recalculo: bool = False


def _lista_ars(p: ProductoERP, tc: Optional[float]) -> Optional[float]:
    if p.costo is None or p.costo <= 0:
        return None
    if moneda_de(p.moneda_costo) == "ARS":
        return float(p.costo)
    return float(p.costo) * tc if tc else None


def _precio(costo: Optional[float], factor: float, markup: Optional[float]) -> Optional[float]:
    return None if costo is None or markup is None else costo * factor * (1 + markup / 100)


def estimar(db: Session) -> List[Fila]:
    """Every active product's Gremio / Sugerido before and after, over the costo SI `db` reads (the caller has the
    history in place)."""
    tc = obtener_tipo_cambio_actual(db, "USD")
    factor = 1 + obtener_constantes_pricing(db).get("varios", 6.5) / 100
    productos = db.query(ProductoERP, ProductoPricing).outerjoin(
        ProductoPricing, ProductoPricing.item_id == ProductoERP.item_id
    )
    productos = productos.filter(ProductoERP.activo.is_(True)).all()
    costos = lote.actuales(db, [p.item_id for p, _ in productos], tipo_cambio=tc)
    si_ars = costos_ars_de(costos)
    por_producto = {m.item_id: m for m in db.query(MarkupTiendaProducto).filter(MarkupTiendaProducto.activo.is_(True))}
    por_marca: Dict[str, MarkupTiendaBrand] = {
        m.brand_desc.upper(): m
        for m in db.query(MarkupTiendaBrand).filter(MarkupTiendaBrand.activo.is_(True)).order_by(MarkupTiendaBrand.id)
        if m.brand_desc
    }
    manuales = {o.item_id for o in db.query(PrecioGremioOverride.item_id)}
    comisiones: Dict[int, bool] = {}
    out: List[Fila] = []
    for p, pricing in productos:
        lista, si = _lista_ars(p, tc), si_ars.get(p.item_id)
        c = costos.get(p.item_id)
        fila = Fila(p.item_id, float(p.stock or 0), c.fuente if c else None, lista, si)
        mp, mb = por_producto.get(p.item_id), por_marca.get((p.marca or "").upper())
        gremio = mp.markup_porcentaje if mp else (mb.markup_porcentaje if mb else None)
        if p.item_id not in manuales:
            fila.gremio_antes, fila.gremio_despues = _precio(lista, factor, gremio), _precio(si, factor, gremio)
        sugerido = mp.markup_sugerido if mp and mp.markup_sugerido is not None else None
        if sugerido is None and mb and mb.markup_sugerido is not None:
            sugerido = mb.markup_sugerido
        clasica = pricing.markup_calculado if pricing else None
        if clasica is not None:
            extra = sugerido or 0.0
            fila.sugerido_antes = _precio(lista, factor, clasica + extra)
            if lista and si:
                fila.sugerido_despues = _precio(si, factor, ((1 + clasica / 100) * lista / si - 1) * 100 + extra)
            if fila.fuente == lote.FUENTE_COSTO_SI:
                fila.clasica_sin_recalculo = not _recalculable(db, p, pricing, comisiones)
        out.append(fila)
    return out


def _recalculable(db: Session, p: ProductoERP, pricing: ProductoPricing, comisiones: Dict[int, bool]) -> bool:
    """Whether the drain's `recalcular_markups_guardados` can rewrite this clásica markup (`_markup_clasica`): an ML
    price, an IVA and a list 4 commission for the product's group (cached per subcategory)."""
    if not pricing.precio_lista_ml or pricing.precio_lista_ml <= 0 or p.iva is None:
        return False
    if p.subcategoria_id not in comisiones:
        grupo = obtener_grupo_subcategoria(db, p.subcategoria_id)
        comisiones[p.subcategoria_id] = bool(obtener_comision_base(db, 4, grupo))
    return comisiones[p.subcategoria_id]


def _resumen(filas: List[Fila], campo: str, antes: str = "antes") -> str:
    pares = [(getattr(f, f"{campo}_{antes}"), getattr(f, f"{campo}_despues")) for f in filas]
    pares = [(a, d) for a, d in pares if a]
    sin_costo = sum(1 for a, d in pares if d is None)
    cambian = [(a, d) for a, d in pares if d is not None and abs(d - a) >= 0.01]
    if not cambian:
        return f"{campo}: {len(pares)} priced, 0 change, {sin_costo} lose their price (no costo SI in pesos)"
    pct = sorted((d - a) / a * 100 for a, d in cambian)
    ars = sorted(d - a for a, d in cambian)
    q = statistics.quantiles(pct, n=10) if len(pct) > 1 else [pct[0]] * 9
    return (
        f"{campo}: {len(pares)} priced, {len(cambian)} change, {sin_costo} lose their price (no costo SI in pesos); "
        f"change % median {statistics.median(pct):.1f} (p10 {q[0]:.1f}, p90 {q[-1]:.1f}, min {pct[0]:.1f}); "
        f"ARS median {statistics.median(ars):,.0f} (min {ars[0]:,.0f})"
    )


def resumen(filas: List[Fila]) -> List[str]:
    con_stock = [f for f in filas if f.stock > 0]
    out = [
        f"active products {len(filas)}, with stock {len(con_stock)}; fuente costo_si "
        f"{sum(1 for f in filas if f.fuente == lote.FUENTE_COSTO_SI)}"
    ]
    for nombre, grupo in (("all", filas), ("with stock", con_stock)):
        out.append(f"[{nombre}] " + _resumen(grupo, "gremio"))
        out.append(f"[{nombre}] " + _resumen(grupo, "sugerido"))
        out.append(f"[{nombre}] clásica the drain cannot rewrite: {sum(f.clasica_sin_recalculo for f in grupo)}")
    return out


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", required=True, type=Path, help="folder for tienda_estimacion.csv")
    parser.add_argument("--url-env", default=URL_ENV, help=f"env var holding the database URL (default {URL_ENV})")
    args = parser.parse_args(argv)
    url = os.environ.get(args.url_env)
    if not url:
        print(f"costo_si_tienda_estimacion: set {args.url_env} to the database URL", file=sys.stderr)
        return 2
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(message)s")
    motor = simulacion.motor_solo_lectura(url)
    try:
        with simulacion.simular(motor) as sim:
            sim.sombra.fijar_pasos([])
            pasos = impacto.calcular_pasos(sim.db, queue.productos_vigentes(sim.db))
            sim.sombra.fijar_pasos(pasos.filas)
            filas = estimar(sim.db)
    finally:
        motor.dispose()
    args.out.mkdir(parents=True, exist_ok=True)
    with open(args.out / "tienda_estimacion.csv", "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(Fila.__dataclass_fields__))
        writer.writeheader()
        writer.writerows(asdict(f) for f in filas)
    print(f"costo_si_tienda_estimacion: {len(pasos.fallidos)} products not computed")
    for linea in resumen(filas):
        print(linea)
    return 0


if __name__ == "__main__":
    sys.exit(main())
