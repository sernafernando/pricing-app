"""Recompute the Precio Costo of the PDF lines already loaded from the ERP cost list (vpf-costo-d-erp, owner L3).

Lines loaded before vpf-costo-d-erp keep the PDF's "Precio Costo" (that is why their Costo D was ~7% too high).
By default this only REPORTS what would change (dry run). `--aplicar` writes `ventas_fuera_operacion_lineas.precio_costo`
of those lines in one transaction (lines with a manual cost are skipped), after saving every changed line's
`id, precio_costo` to `--backup`; the existing trigger queues each line in `sell_dirty`, so offsets and sell in /
sell out are recomputed. Owner L3: "ask me with the impact before doing it".

    python -m app.scripts.recostear_ventas_fuera_erp [--desde 2026-11-01] [--hasta 2026-11-30]
    python -m app.scripts.recostear_ventas_fuera_erp --aplicar --backup /root/backup_vpf_costo.json

Undo: set each backed-up line's `precio_costo` back (the trigger requeues the derived metrics again).
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Optional

from app.core.database import SessionLocal
from app.services.ventas_fuera_pdf.costo_erp import Recosteo, recostear
from app.services.ventas_fuera_pdf.ventas import COSTO_D_FACTOR


def resumen(cambios: list[Recosteo]) -> str:
    """The impact table: lines, Costo D before / after, lines whose margin is negative before / after."""
    antes = sum((c.antes for c in cambios), Decimal("0")) * COSTO_D_FACTOR
    despues = sum((c.despues for c in cambios), Decimal("0")) * COSTO_D_FACTOR
    negativos_antes = sum(1 for c in cambios if c.antes > 0 and c.precio < c.antes * COSTO_D_FACTOR)
    negativos_despues = sum(1 for c in cambios if c.despues > 0 and c.precio < c.despues * COSTO_D_FACTOR)
    return "\n".join(
        [
            f"lineas que cambian: {len(cambios)} (con producto, se encolan en sell_dirty: "
            f"{sum(1 for c in cambios if c.item_id is not None)})",
            f"Costo D: {antes:,.2f} -> {despues:,.2f} ({despues - antes:+,.2f})",
            f"lineas con margen negativo: {negativos_antes} -> {negativos_despues}",
        ]
    )


def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--desde", type=date.fromisoformat)
    parser.add_argument("--hasta", type=date.fromisoformat)
    parser.add_argument("--aplicar", action="store_true", help="write the changes (default: dry run)")
    parser.add_argument(
        "--backup", type=Path, help="JSON file for the changed lines' previous cost (required with --aplicar)"
    )
    args = parser.parse_args(argv)
    if args.aplicar and args.backup is None:
        parser.error("--aplicar requires --backup")

    with SessionLocal() as db:
        cambios = recostear(db, args.desde, args.hasta)
        print(resumen(cambios))
        if not args.aplicar:
            print("dry run: nothing written")
            return
        args.backup.write_text(
            json.dumps([{"id": c.linea_id, "precio_costo": str(c.antes)} for c in cambios], indent=1)
        )
        aplicados = recostear(db, args.desde, args.hasta, aplicar=True)
        print(f"written: {len(aplicados)} lines; backup {args.backup}")


if __name__ == "__main__":
    main()
