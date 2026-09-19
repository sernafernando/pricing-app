"""Prefilter candidates. match_fabricante_exacto exists but match_renglones must not call it."""

from __future__ import annotations

import re
from typing import Any

from app.services.oc_match.maestro import Articulo, fab_core, norm, norm_code

STOP = {
    "DE",
    "DEL",
    "LA",
    "EL",
    "LOS",
    "LAS",
    "Y",
    "PARA",
    "CON",
    "UN",
    "UNA",
    "THE",
    "AND",
    "P",
    "PUERTOS",
    "MBPS",
}
COLORES_CANON = {
    "ROSE": "ROSA",
    "ROSA": "ROSA",
    "PINK": "ROSA",
    "GRAPHITE": "NEGRO",
    "GRAFITE": "NEGRO",
    "GRAFITO": "NEGRO",
    "BLACK": "NEGRO",
    "NEGRO": "NEGRO",
    "WHITE": "BLANCO",
    "BLANCO": "BLANCO",
    "GREY": "GRIS",
    "GRAY": "GRIS",
    "GRIS": "GRIS",
    "SILVER": "PLATA",
    "PLATA": "PLATA",
    "BLUE": "BLUE",
    "RED": "RED",
    "GREEN": "GREEN",
}
MAX_CANDIDATOS = 24
MAX_CANDIDATOS_MAIL = 8


def tokens(text: str) -> list[str]:
    raw = re.findall(r"[A-Z0-9]+", norm(text))
    out: list[str] = []
    for t in raw:
        if t in STOP:
            continue
        if len(t) >= 3 or any(c.isdigit() for c in t):
            out.append(t)
    return out


def pack_hint(text: str) -> str | None:
    t = norm(text)
    m = re.search(r"(\d)\s*-?\s*PACK", t) or re.search(r"PACK\s*(?:DE\s*)?(\d)", t)
    return m.group(1) if m else None


def colores_en(text: str) -> set[str]:
    toks = set(tokens(text))
    found: set[str] = set()
    for tok, canon in COLORES_CANON.items():
        if tok in toks:
            found.add(canon)
    return found


def peso_token(t: str) -> int:
    if t in COLORES_CANON:
        return 0
    has_digit = any(c.isdigit() for c in t)
    has_alpha = any(c.isalpha() for c in t)
    if has_digit and has_alpha:
        return 10
    if len(t) >= 5:
        return 3
    if has_digit:
        return 2
    return 1


def parece_combo(text: str) -> bool:
    t = norm(text)
    return " + " in t or "+" in t or "MOUSE PAD" in t or ("AURICULAR" in t and "MOUSE" in t)


def match_fabricante_exacto(
    renglon: dict[str, Any],
    idx: dict[str, list[Articulo]],
    idx_core: dict[str, list[Articulo]] | None = None,
) -> Articulo | None:
    """Kept for port fidelity. MUST NOT be called from match_renglones (no fab on tb_item)."""
    raw = renglon.get("codigo_fabricante")
    key = norm_code(raw)
    if len(key) >= 3:
        hits = idx.get(key) or []
        if len(hits) == 1:
            return hits[0]
    if idx_core is not None:
        core = fab_core(raw)
        if len(core) >= 5:
            hits = idx_core.get(core) or []
            if len(hits) == 1:
                return hits[0]
    return None


def puntuar(renglon: dict[str, Any], art: Articulo) -> int:
    desc = str(renglon.get("descripcion") or "")
    q_tokens = tokens(
        " ".join(
            [
                desc,
                str(renglon.get("codigo_fabricante") or ""),
                str(renglon.get("codigo_proveedor") or ""),
            ]
        )
    )
    hay = norm(art.haystack())
    score = 0
    for t in q_tokens:
        w = peso_token(t)
        if w and t in hay:
            score += w
    ean = re.sub(r"\D", "", str(renglon.get("ean") or ""))
    if ean and ean == re.sub(r"\D", "", art.ean):
        score += 6
    last4 = re.sub(r"\D", "", str(renglon.get("ean_ultimos4") or ""))
    if len(last4) == 4 and art.ean.endswith(last4):
        score += 4
    fab_q = fab_core(renglon.get("codigo_fabricante"))
    fab_a = fab_core(art.fabricante)
    if fab_q and fab_a:
        if fab_q == fab_a:
            score += 14
        elif len(fab_q) >= 5 and (fab_q in fab_a or fab_a in fab_q):
            score += 8
    pq, pa = pack_hint(desc), pack_hint(art.descripcion)
    if pq and pa and pq != pa:
        score -= 8
    elif pq and pa and pq == pa:
        score += 6
    cq, ca = colores_en(desc), colores_en(art.descripcion + " " + art.marca)
    if cq and ca and cq.isdisjoint(ca):
        score -= 4
    elif cq and cq & ca:
        score += 3
    if not parece_combo(desc) and parece_combo(art.descripcion):
        score -= 5
    return score


def candidatos(renglon: dict[str, Any], articulos: list[Articulo]) -> list[tuple[int, Articulo]]:
    scored = [(puntuar(renglon, a), a) for a in articulos]
    scored.sort(key=lambda x: x[0], reverse=True)
    return [(s, a) for s, a in scored if s > 0][:MAX_CANDIDATOS]


def candidatos_para_operador(
    ranked: list[tuple[int, Articulo]],
    sugerido_id: str | None = None,
    limite: int = MAX_CANDIDATOS_MAIL,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for s, a in ranked[:limite]:
        row = art_publico(a)
        row["score"] = s
        row["sugerido_gemini"] = bool(sugerido_id and a.item_id == str(sugerido_id))
        out.append(row)
    return out


def art_publico(art: Articulo) -> dict[str, str]:
    return {
        "item_id": art.item_id,
        "ean": art.ean,
        "descripcion": art.descripcion,
        "marca": art.marca,
        "fabricante": art.fabricante,
        "categoria": art.categoria,
        "subcategoria": art.subcategoria,
    }
