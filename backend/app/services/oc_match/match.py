"""Match extracted renglones to tb_item candidates via Gemini. No fabricante exact path."""

from __future__ import annotations

import json
from typing import Any

from app.services.oc_match.candidatos import (
    art_publico,
    candidatos,
    candidatos_para_operador,
)
from app.services.oc_match.gemini_pool import GeminiPool
from app.services.oc_match.maestro import Articulo

PROMPT = """Sos el matching de artículos Gauss ↔ GBP.
Te doy renglones de una proforma y, para cada uno, una LISTA CERRADA de artículos del maestro GBP.

Devolvé SOLO JSON:
{
  "decisiones": [
    {
      "indice": number,
      "item_id": string o null,
      "ean": string o null,
      "confianza": "alta" | "media" | "baja",
      "motivo": string
    }
  ]
}

Reglas:
- indice debe coincidir con el renglón de entrada.
- item_id y ean SOLO si salen de la lista de ese renglón. Nunca inventes un EAN.
- Tu trabajo ES razonar, no exigir coincidencia literal de palabras.
- Color EN/ES es el mismo artículo. En Logitech (y en este maestro) GRAPHITE/GRAFITO/GRAFITE = negro (BLACK/NEGRO); ROSE = rosa (PINK/ROSA). También BLACK=NEGRO, WHITE=BLANCO, GREY/GRAY=GRIS.
- Si el renglón dice GRAPHITE/GRAFITE y en la lista hay el modelo suelto en NEGRO (p.ej. M196 NEGRO), elegilo. No lo dejes en no_hallado por “no hay grafito”, y no elijas el combo con mouse pad grafito si el renglón no pide combo.
- Si hay un SKU que dice GRAFITO y otro NEGRO/BLACK del mismo modelo pero otra variante (p.ej. M240 GRAFITO vs M240 SILENT BLACK), preferí el más específico; no los fusiones.
- ROSE/rosa vs NEGRO/graphite sí son SKUs distintos: si ambos están en la lista y el renglón nombra uno, elegí ese; si no aclara color y hay varios, confianza=baja.
- Pack 1 vs 3 son artículos distintos.
- Preferí el artículo suelto, no un combo/kit de fábrica, si el renglón no pide combo. Los combos armados internamente (EAN con / extra) ya no están en la lista.
- El EAN de la proforma puede ser viejo: priorizá descripción + modelo del maestro.
- Si no hay certeza: item_id del más plausible con confianza=baja (no se carga a la OC; se muestra al operador).
"""


def gemini_json(pool: GeminiPool, payload: dict[str, Any]) -> dict[str, Any]:
    return pool.generate_json(PROMPT + "\n\n" + json.dumps(payload, ensure_ascii=False))


def validar_decision(dec: dict[str, Any], ranked: list[tuple[int, Articulo]]) -> dict[str, Any]:
    cands = [a for _, a in ranked]
    by_id = {a.item_id: a for a in cands}
    by_ean = {a.ean: a for a in cands if a.ean}
    item_id = str(dec.get("item_id") or "").strip() or None
    ean = str(dec.get("ean") or "").strip() or None
    confianza = str(dec.get("confianza") or "baja").lower()
    motivo = str(dec.get("motivo") or "")
    art = by_id.get(item_id) if item_id else None
    if art is None and ean:
        art = by_ean.get(ean)
    if art is not None and confianza != "baja":
        return {
            "estado": "ok",
            "via": "gemini",
            "item_id": art.item_id,
            "ean": art.ean,
            "descripcion_gbp": art.descripcion,
            "confianza": confianza,
            "motivo": motivo,
        }
    sugerido = art.item_id if art is not None else None
    return {
        "estado": "no_hallado",
        "via": "gemini",
        "item_id": None,
        "ean": None,
        "descripcion_gbp": None,
        "confianza": confianza,
        "motivo": motivo or "baja confianza o id/ean fuera de la lista",
        "sugerido_id": sugerido,
        "candidatos": candidatos_para_operador(ranked, sugerido),
    }


def match_renglones(
    extraido: dict[str, Any],
    articulos: list[Articulo],
    pool: GeminiPool,
) -> dict[str, Any]:
    """Gemini-among-candidates only. Exact manufacturer-code shortcut is skipped."""
    pendientes: list[dict[str, Any]] = []
    salida_renglones: list[dict[str, Any]] = []

    for ren in extraido.get("renglones") or []:
        base: dict[str, Any] = {
            "descripcion": ren.get("descripcion"),
            "cantidad": ren.get("cantidad"),
            "precio_unitario": ren.get("precio_unitario"),
            "moneda": ren.get("moneda") or extraido.get("moneda"),
            "codigo_fabricante": ren.get("codigo_fabricante"),
            "codigo_proveedor": ren.get("codigo_proveedor"),
            "ean_proforma": ren.get("ean"),
            "ean_ultimos4": ren.get("ean_ultimos4"),
            "omitir": bool(ren.get("omitir")),
            "motivo_omitir": ren.get("motivo_omitir"),
        }
        if ren.get("omitir"):
            base["match"] = {
                "estado": "omitido",
                "via": None,
                "item_id": None,
                "ean": None,
                "descripcion_gbp": None,
                "confianza": None,
                "motivo": ren.get("motivo_omitir") or "omitido en extracción",
            }
            salida_renglones.append(base)
            continue
        ranked = candidatos(ren, articulos)
        arts = [a for _, a in ranked]
        if not arts:
            base["match"] = {
                "estado": "no_hallado",
                "via": "candidatos",
                "item_id": None,
                "ean": None,
                "descripcion_gbp": None,
                "confianza": "baja",
                "motivo": "ningún candidato en el maestro",
                "candidatos": [],
            }
            salida_renglones.append(base)
            continue
        slot = len(salida_renglones)
        pendientes.append(
            {
                "indice": slot,
                "renglon": {
                    "descripcion": ren.get("descripcion"),
                    "codigo_fabricante": ren.get("codigo_fabricante"),
                    "codigo_proveedor": ren.get("codigo_proveedor"),
                    "ean": ren.get("ean"),
                    "ean_ultimos4": ren.get("ean_ultimos4"),
                },
                "candidatos": [art_publico(a) for a in arts],
            }
        )
        base["_ranked"] = ranked
        salida_renglones.append(base)

    if pendientes:
        payload = {
            "renglones": [
                {
                    "indice": j,
                    "renglon": p["renglon"],
                    "candidatos": p["candidatos"],
                }
                for j, p in enumerate(pendientes)
            ]
        }
        raw = gemini_json(pool, payload)
        decs: dict[int, dict[str, Any]] = {}
        for d in raw.get("decisiones") or []:
            try:
                decs[int(d["indice"])] = d
            except (KeyError, TypeError, ValueError):
                continue
        for j, p in enumerate(pendientes):
            idx = p["indice"]
            ranked = salida_renglones[idx].pop("_ranked", [])
            salida_renglones[idx]["match"] = validar_decision(decs.get(j) or {}, ranked)

    for row in salida_renglones:
        row.pop("_ranked", None)

    estados = [r["match"]["estado"] for r in salida_renglones]
    return {
        "proveedor_razon_social": extraido.get("proveedor_razon_social"),
        "proveedor_cuit": extraido.get("proveedor_cuit"),
        "nro_documento": extraido.get("nro_documento"),
        "nro_pedido": extraido.get("nro_pedido"),
        "fecha": extraido.get("fecha"),
        "moneda": extraido.get("moneda"),
        "tipo_cambio": extraido.get("tipo_cambio"),
        "descuento_pct": extraido.get("descuento_pct"),
        "renglones": salida_renglones,
        "resumen": {
            "ok": estados.count("ok"),
            "no_hallado": estados.count("no_hallado"),
            "omitido": estados.count("omitido"),
        },
    }
