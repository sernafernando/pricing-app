"""
Reporte READ-ONLY de seriales fantasma en prearmados viejos.

Compara las filas de `prearmados_seriales` de cada prearmado contra la BOM ACTUAL
del combo (`tb_item_association` con `iasso_qty > 0`) y marca las sospechosas:

- FUERA_DE_BOM: el `componente_item_id` ya no existe en la BOM del combo. El
  componente fue removido por completo del combo → candidato fuerte a fantasma.
- EXCESO_CANTIDAD: el componente sigue en la BOM, pero el prearmado tiene más
  filas que la cantidad esperada hoy (ej: dos discos donde ahora va uno) →
  candidato de MENOR confianza, puede ser un cambio real de BOM.

IMPORTANTE: este script NO modifica nada. Es solo diagnóstico. Un prearmado en
estado `consumido`/`anulado` es historia (esa unidad física se armó con esos
componentes), así que se reporta aparte y NO debería tocarse a la ligera.

Corré SIEMPRE la reconciliación de asociaciones ANTES de este reporte, si no la
BOM "actual" todavía tiene los propios fantasmas:
    python -m app.scripts.sync_item_associations

Uso:
    python -m app.scripts.report_prearmado_ghost_serials
    python -m app.scripts.report_prearmado_ghost_serials --estado pendiente
    python -m app.scripts.report_prearmado_ghost_serials --combo-item-id 4296
    python -m app.scripts.report_prearmado_ghost_serials --solo-activos
"""

import argparse
import sys
from collections import defaultdict
from pathlib import Path

backend_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(backend_dir))

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import SessionLocal

ESTADOS_TERMINALES = ("consumido", "anulado")


def _bom_actual_por_combo(db: Session, combo_item_id: int) -> dict[int, float]:
    """
    Cantidad esperada por componente en la BOM ACTUAL del combo.

    Devuelve {componente_item_id: qty_total}, sumando `iasso_qty` de todas las
    asociaciones vigentes (iasso_qty > 0) de ese combo. Refleja cuántas unidades
    de cada componente debería tener hoy un prearmado de ese combo.
    """
    rows = (
        db.execute(
            text(
                """
            SELECT item_id_1 AS componente_item_id, SUM(iasso_qty) AS qty_total
            FROM tb_item_association
            WHERE item_id = :combo_id
              AND iasso_qty > 0
            GROUP BY item_id_1
            """
            ),
            {"combo_id": combo_item_id},
        )
        .mappings()
        .all()
    )
    return {r["componente_item_id"]: float(r["qty_total"]) for r in rows}


def reportar(db: Session, estado: str = None, combo_item_id: int = None, solo_activos: bool = False) -> dict:
    """Construye el reporte de filas sospechosas. NO modifica nada."""
    filtros = []
    params: dict = {}
    if estado:
        filtros.append("p.estado = :estado")
        params["estado"] = estado
    if combo_item_id is not None:
        filtros.append("p.combo_item_id = :combo_item_id")
        params["combo_item_id"] = combo_item_id
    if solo_activos:
        filtros.append("p.estado NOT IN ('consumido', 'anulado')")
    where = ("WHERE " + " AND ".join(filtros)) if filtros else ""

    prearmados = (
        db.execute(
            text(
                f"""
            SELECT p.id, p.codigo, p.estado, p.combo_item_id, p.combo_item_code
            FROM prearmados p
            {where}
            ORDER BY p.combo_item_id, p.id
            """
            ),
            params,
        )
        .mappings()
        .all()
    )

    # Cache de BOM por combo para no reconsultar por cada prearmado del mismo combo.
    bom_cache: dict[int, dict[int, float]] = {}
    hallazgos: list[dict] = []

    for p in prearmados:
        combo_id = p["combo_item_id"]
        if combo_id not in bom_cache:
            bom_cache[combo_id] = _bom_actual_por_combo(db, combo_id)
        bom = bom_cache[combo_id]

        seriales = (
            db.execute(
                text(
                    """
                SELECT id, componente_item_id, componente_item_code, serial,
                       requiere_serie, validado, is_id
                FROM prearmados_seriales
                WHERE prearmado_id = :pid
                ORDER BY componente_item_id, id
                """
                ),
                {"pid": p["id"]},
            )
            .mappings()
            .all()
        )

        # Conteo de filas por componente en este prearmado.
        conteo_por_comp: dict[int, int] = defaultdict(int)
        for s in seriales:
            conteo_por_comp[s["componente_item_id"]] += 1

        for s in seriales:
            comp_id = s["componente_item_id"]
            qty_esperada = bom.get(comp_id)
            motivo = None
            if qty_esperada is None:
                motivo = "FUERA_DE_BOM"
            elif conteo_por_comp[comp_id] > qty_esperada:
                motivo = "EXCESO_CANTIDAD"
            if motivo:
                hallazgos.append(
                    {
                        "prearmado_id": p["id"],
                        "codigo": p["codigo"],
                        "estado": p["estado"],
                        "combo_item_code": p["combo_item_code"],
                        "serial_row_id": s["id"],
                        "componente_item_id": comp_id,
                        "componente_item_code": s["componente_item_code"],
                        "serial": s["serial"],
                        "requiere_serie": s["requiere_serie"],
                        "validado": s["validado"],
                        "is_id": s["is_id"],
                        "qty_esperada": qty_esperada,
                        "qty_en_prearmado": conteo_por_comp[comp_id],
                        "motivo": motivo,
                        "terminal": p["estado"] in ESTADOS_TERMINALES,
                    }
                )

    return {"prearmados_revisados": len(prearmados), "hallazgos": hallazgos}


def imprimir(reporte: dict) -> None:
    hallazgos = reporte["hallazgos"]
    print("\n=== Reporte de seriales fantasma (READ-ONLY) ===")
    print(f"Prearmados revisados: {reporte['prearmados_revisados']}")
    print(f"Filas sospechosas:    {len(hallazgos)}\n")

    if not hallazgos:
        print("✅ Sin filas sospechosas. Nada para corregir.")
        return

    activos = [h for h in hallazgos if not h["terminal"]]
    terminales = [h for h in hallazgos if h["terminal"]]

    def _fila(h: dict) -> str:
        ser = h["serial"] or "(sin serie)"
        val = "validado" if h["validado"] else "SIN validar"
        return (
            f"  prearmado #{h['prearmado_id']} [{h['codigo']}] {h['estado']:11} "
            f"| {h['motivo']:15} | comp {h['componente_item_code']} (id {h['componente_item_id']}) "
            f"| serial_row_id={h['serial_row_id']} serial={ser} {val} "
            f"| esperado={h['qty_esperada']} en_prearmado={h['qty_en_prearmado']}"
        )

    if activos:
        print(f"--- ACTIVOS (pendiente/en_proceso/armado) — {len(activos)} fila(s), candidatos a limpiar ---")
        for h in activos:
            print(_fila(h))
        print()
    if terminales:
        print(f"--- TERMINALES (consumido/anulado) — {len(terminales)} fila(s), HISTORIA, revisar con cuidado ---")
        for h in terminales:
            print(_fila(h))
        print()

    # Resumen por motivo.
    por_motivo: dict[str, int] = defaultdict(int)
    for h in hallazgos:
        por_motivo[h["motivo"]] += 1
    print("Resumen por motivo:")
    for motivo, n in sorted(por_motivo.items()):
        print(f"  {motivo}: {n}")
    print("\nℹ️  Nada fue modificado. Revisá serial_row_id antes de cualquier borrado.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Reporte read-only de seriales fantasma en prearmados")
    parser.add_argument("--estado", type=str, help="Filtrar por un estado puntual")
    parser.add_argument("--combo-item-id", type=int, help="Filtrar por combo")
    parser.add_argument(
        "--solo-activos",
        action="store_true",
        help="Excluir consumido/anulado (solo los que todavía se arman)",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        reporte = reportar(
            db,
            estado=args.estado,
            combo_item_id=args.combo_item_id,
            solo_activos=args.solo_activos,
        )
        imprimir(reporte)
    finally:
        db.close()


if __name__ == "__main__":
    main()
