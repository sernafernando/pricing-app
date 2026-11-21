"""The T4 dry-run report for the owner (sell-in-costo-si T4, plan handoffs/sell-in-costo-si-t4-plan.md §2): what the
deploy's history recalc will change, per month and channel, from an `impacto.Informe`.

Money is the stored sale cost in pesos: `delta = despues - antes`, so a positive delta is a higher cost (a lower
ganancia by the same amount). A sale whose cost becomes unknown on its date is not in `despues` nor in the delta: it
is counted apart with the cost it had (`sin_costo`, `antes_sin_costo`).
"""

from __future__ import annotations

import csv
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from app.services.costo_si.impacto import Cambio, Informe

CERO = Decimal(0)


@dataclass(frozen=True)
class FilaMes:
    canal: str
    mes: date
    filas: int  # sales re-costed with a known cost
    antes: Decimal
    despues: Decimal
    delta: Decimal
    sin_costo: int  # sales whose cost becomes unknown
    antes_sin_costo: Decimal


@dataclass(frozen=True)
class FilaProducto:
    canal: str
    item_id: int
    filas: int
    antes: Decimal
    despues: Decimal
    delta: Decimal


def por_canal_mes(cambios: Iterable[Cambio]) -> List[FilaMes]:
    grupos: Dict[tuple, List[Cambio]] = defaultdict(list)
    for c in cambios:
        grupos[(c.canal, c.mes)].append(c)
    out = []
    for (canal, mes), lista in sorted(grupos.items()):
        conocidos = [c for c in lista if c.despues is not None]
        antes = sum((c.antes or CERO for c in conocidos), CERO)
        despues = sum((c.despues for c in conocidos), CERO)
        desconocidos = [c for c in lista if c.despues is None]
        out.append(
            FilaMes(
                canal,
                mes,
                len(conocidos),
                antes,
                despues,
                despues - antes,
                len(desconocidos),
                sum((c.antes or CERO for c in desconocidos), CERO),
            )
        )
    return out


def top_productos(cambios: Iterable[Cambio], n: int) -> List[FilaProducto]:
    grupos: Dict[tuple, List[Cambio]] = defaultdict(list)
    for c in cambios:
        if c.despues is not None:
            grupos[(c.canal, c.item_id)].append(c)
    filas = []
    for (canal, item_id), lista in grupos.items():
        antes = sum((c.antes or CERO for c in lista), CERO)
        despues = sum((c.despues for c in lista), CERO)
        filas.append(FilaProducto(canal, item_id, len(lista), antes, despues, despues - antes))
    return sorted(filas, key=lambda f: (-abs(f.delta), f.canal, f.item_id))[:n]


def _m(valor: Decimal) -> str:
    return f"{valor:.2f}"


def _controles(informe: Informe, controles: Dict[int, Decimal]) -> List[str]:
    """Each control product's last average against the value validated by hand (T1), at that value's decimals."""
    ultimos: Dict[int, dict] = {}
    for f in informe.pasos.filas:
        if f["item_id"] not in ultimos or f["orden"] > ultimos[f["item_id"]]["orden"]:
            ultimos[f["item_id"]] = f
    out = ["| item | expected | computed | result |", "|---|---|---|---|"]
    for item_id, esperado in sorted(controles.items()):
        paso = ultimos.get(item_id)
        if paso is None or paso.get("promedio_usd") is None:
            out.append(f"| {item_id} | {esperado} | — | NO STEPS |")
            continue
        calculado = Decimal(paso["promedio_usd"])
        igual = calculado.quantize(esperado) == esperado
        out.append(f"| {item_id} | {esperado} | {calculado} | {'OK' if igual else 'DIFF'} |")
    return out


def resumen(informe: Informe, controles: Optional[Dict[int, Decimal]] = None, top: int = 20) -> str:
    pasos = informe.pasos
    con_pasos = len(pasos.desdes)
    lineas = [
        "# Costo SI T4 dry-run",
        "",
        "Read-only (BEGIN READ ONLY, rolled back). Money in ARS: delta = after - before, positive = higher cost "
        "(lower ganancia).",
        "",
        f"Products in scope: {pasos.alcance}; with costo SI: {con_pasos}; not computed: {len(pasos.fallidos)}; "
        f"steps: {len(pasos.filas)}.",
        "",
        "## Per channel and month",
        "",
        "| channel | month | sales re-costed | before | after | delta | sales left without cost | their cost before |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for f in por_canal_mes(informe.cambios):
        lineas.append(
            f"| {f.canal} | {f.mes:%Y-%m} | {f.filas} | {_m(f.antes)} | {_m(f.despues)} | {_m(f.delta)} | "
            f"{f.sin_costo} | {_m(f.antes_sin_costo)} |"
        )
    lineas += ["", f"## Top {top} products by |delta|", "", "| channel | item | sales | before | after | delta |"]
    lineas.append("|---|---|---|---|---|---|")
    for p in top_productos(informe.cambios, top):
        lineas.append(f"| {p.canal} | {p.item_id} | {p.filas} | {_m(p.antes)} | {_m(p.despues)} | {_m(p.delta)} |")
    productos_markup = {m.item_id for m in informe.markups}
    lineas += [
        "",
        "## Stored markups",
        "",
        f"Stored markups changed: {len(informe.markups)} ({len(productos_markup)} products). Not recomputable "
        f"(kept as stored): {len(informe.omitidos_markup)}.",
        "",
        "| item | markup | reason |",
        "|---|---|---|",
    ]
    lineas += [f"| {i} | {campo} | {motivo} |" for i, campo, motivo in informe.omitidos_markup]
    lineas += ["", "## Products not computed", "", "| item | reason |", "|---|---|"]
    lineas += [f"| {i} | {motivo} |" for i, motivo in sorted(pasos.fallidos.items())]
    if controles:
        lineas += ["", "## Controls (validated averages)", "", *_controles(informe, controles)]
    lineas += ["", "## Stand-ins (figures resting on them)", ""]
    lineas += [f"- {s.nombre}: {s.motivo}" for s in informe.sombras]
    return "\n".join(lineas) + "\n"


def _csv(ruta: Path, columnas: List[str], filas: Iterable[list]) -> None:
    with ruta.open("w", newline="") as f:
        escritor = csv.writer(f)
        escritor.writerow(columnas)
        for fila in filas:
            escritor.writerow(["" if v is None else v for v in fila])


def escribir(informe: Informe, carpeta: Path, controles: Optional[Dict[int, Decimal]] = None) -> None:
    """`resumen.md`, `por_canal_mes.csv`, `cambios.csv` (every sale row), `markups.csv` and `fallidos.csv`."""
    carpeta.mkdir(parents=True, exist_ok=True)
    (carpeta / "resumen.md").write_text(resumen(informe, controles))
    _csv(
        carpeta / "por_canal_mes.csv",
        ["canal", "mes", "filas", "antes", "despues", "delta", "sin_costo", "antes_sin_costo"],
        (
            [f.canal, f.mes, f.filas, f.antes, f.despues, f.delta, f.sin_costo, f.antes_sin_costo]
            for f in por_canal_mes(informe.cambios)
        ),
    )
    _csv(
        carpeta / "cambios.csv",
        ["canal", "item_id", "fila_id", "fecha", "antes", "despues"],
        ([c.canal, c.item_id, c.fila_id, c.fecha, c.antes, c.despues] for c in informe.cambios),
    )
    _csv(
        carpeta / "markups.csv",
        ["item_id", "campo", "antes", "despues"],
        ([m.item_id, m.campo, m.antes, m.despues] for m in informe.markups),
    )
    _csv(carpeta / "fallidos.csv", ["item_id", "motivo"], sorted(informe.pasos.fallidos.items()))
