"""Costo SI T4 dry-run: what the deploy's history recalc will change, measured on a database without writing to it
(plan handoffs/sell-in-costo-si-t4-plan.md §2; owner L17: "cuando deployamos se debería disparar").

    python -m app.scripts.costo_si_t4_dry_run --out <dir> [--url-env VAR] [--control ITEM=AVERAGE ...]

The database URL is read from the environment variable `--url-env` (default COSTO_SI_DRY_RUN_DATABASE_URL) and never
printed. Read-only by construction (`simulacion`): its own connection, every transaction `BEGIN READ ONLY`, no SET,
rolled back at the end; a write would raise on the server. Writes the report files (`impacto_reporte.escribir`) to
`--out`, outside the repository.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Dict, List, Optional

from app.services.costo_si import impacto, impacto_reporte, simulacion

URL_ENV = "COSTO_SI_DRY_RUN_DATABASE_URL"


def _controles(valores: List[str]) -> Dict[int, Decimal]:
    out: Dict[int, Decimal] = {}
    for valor in valores:
        item, _, promedio = valor.partition("=")
        try:
            out[int(item)] = Decimal(promedio)
        except (ValueError, InvalidOperation) as exc:
            raise argparse.ArgumentTypeError(f"--control expects ITEM=AVERAGE, got {valor!r}") from exc
    return out


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", required=True, type=Path, help="folder for resumen.md and the CSV files")
    parser.add_argument("--url-env", default=URL_ENV, help=f"env var holding the database URL (default {URL_ENV})")
    parser.add_argument("--control", action="append", default=[], help="ITEM=AVERAGE validated by hand (T1)")
    args = parser.parse_args(argv)
    url = os.environ.get(args.url_env)
    if not url:
        print(f"costo_si_t4_dry_run: set {args.url_env} to the database URL", file=sys.stderr)
        return 2
    controles = _controles(args.control)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    inicio = time.monotonic()
    motor = simulacion.motor_solo_lectura(url)
    try:
        with simulacion.simular(motor) as sim:
            informe = impacto.calcular(sim)
    finally:
        motor.dispose()
    impacto_reporte.escribir(informe, args.out, controles)
    print(
        f"costo_si_t4_dry_run: {informe.pasos.alcance} products, {len(informe.cambios)} sale rows, "
        f"{len(informe.markups)} markups, {len(informe.pasos.fallidos)} not computed, "
        f"{time.monotonic() - inicio:.0f}s -> {args.out / 'resumen.md'}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
