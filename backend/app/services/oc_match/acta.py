"""Acta de cierre and Excel filename. Mail-only fields dropped; Sucursal from empresa map."""

from __future__ import annotations

import re
import unicodedata
from typing import Any


def _slug(raw: object, max_len: int = 40) -> str:
    s = str(raw or "").strip()
    s = unicodedata.normalize("NFKD", s)
    s = s.encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^\w]+", "_", s).strip("_")
    return s[:max_len] or "s_n"


def proveedor_txt(matched: dict[str, Any]) -> str:
    return str(matched.get("proveedor_razon_social") or "Proveedor s/d").strip()


def nro_pedido_txt(matched: dict[str, Any]) -> str:
    return str(matched.get("nro_pedido") or matched.get("nro_documento") or "s/n").strip()


def nombre_excel(matched: dict[str, Any], mid: str) -> str:
    return f"{_slug(proveedor_txt(matched))}_{_slug(nro_pedido_txt(matched))}_{_slug(mid, 16)}.xlsx"


def _fmt_cand(c: dict[str, Any]) -> str:
    ean = c.get("ean") or "-"
    fab = c.get("fabricante") or ""
    extra = f" | fab {fab}" if fab else ""
    marca = f" [{c.get('marca')}]" if c.get("marca") else ""
    sug = " (sugerido)" if c.get("sugerido_gemini") else ""
    return f"    - {c.get('descripcion') or ''} | EAN {ean} | id {c.get('item_id')}{marca}{extra}{sug}"


def acta_cierre(
    matched: dict[str, Any],
    job: dict[str, Any],
    *,
    error: str | None = None,
    excel_nombre: str | None = None,
) -> str:
    renglones = matched.get("renglones") or []
    res = matched.get("resumen") or {}
    lineas = [
        "Gauss OC — resultado del matching (todavía sin nro. de OC en GBP).",
        "",
        f"Sucursal: {job.get('Sucursal') or '-'}",
        f"Proveedor: {proveedor_txt(matched)}",
        f"CUIT: {matched.get('proveedor_cuit') or '-'}",
        f"Nro. pedido: {matched.get('nro_pedido') or '-'}",
        f"Nro. documento: {matched.get('nro_documento') or '-'}",
        f"Fecha papel: {matched.get('fecha') or '-'}",
        f"Moneda: {matched.get('moneda') or '-'}  |  TC: {matched.get('tipo_cambio') or '-'}",
        f"Resumen: ok={res.get('ok', 0)}  no_hallado={res.get('no_hallado', 0)}  omitido={res.get('omitido', 0)}",
    ]
    if excel_nombre:
        lineas.append(f"Excel: {excel_nombre}. Importar a mano en GBP.")
    if error:
        lineas += ["", "ERROR", str(error)]

    oks = [r for r in renglones if (r.get("match") or {}).get("estado") == "ok"]
    noh = [r for r in renglones if (r.get("match") or {}).get("estado") == "no_hallado"]
    omi = [r for r in renglones if (r.get("match") or {}).get("estado") == "omitido"]

    lineas += ["", f"CARGADOS EN EL EXCEL ({len(oks)})"]
    if not oks:
        lineas.append("  (ninguno)")
    for r in oks:
        m = r.get("match") or {}
        lineas.append(f"  - {r.get('cantidad') or '?'} x {r.get('descripcion') or '-'}")
        lineas.append(
            f"      GBP: {m.get('ean')} | {m.get('descripcion_gbp') or ''} | "
            f"via {m.get('via') or '-'} | confianza={m.get('confianza') or '-'}"
        )
        if m.get("motivo"):
            lineas.append(f"      motivo: {m.get('motivo')}")

    lineas += ["", f"NO HALLADOS — no van al Excel; revisar a mano ({len(noh)})"]
    if not noh:
        lineas.append("  (ninguno)")
    for r in noh:
        m = r.get("match") or {}
        lineas.append(f"  - {r.get('cantidad') or '?'} x {r.get('descripcion') or '-'}")
        lineas.append(f"      confianza={m.get('confianza') or '-'}")
        if m.get("motivo"):
            lineas.append(f"      motivo: {m.get('motivo')}")
        cands = m.get("candidatos") or []
        if cands:
            lineas.append("      candidatos GBP:")
            for c in cands[:8]:
                lineas.append(_fmt_cand(c))

    lineas += ["", f"OMITIDOS — no se compran / no van a la OC ({len(omi)})"]
    if not omi:
        lineas.append("  (ninguno)")
    for r in omi:
        m = r.get("match") or {}
        mot = m.get("motivo") or r.get("motivo_omitir") or "omitido"
        conf = m.get("confianza") or "-"
        lineas.append(f"  - {r.get('descripcion') or '-'} (confianza={conf}; {mot})")

    return "\n".join(lineas)
