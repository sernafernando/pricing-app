"""tb_item maestro: Articulo + combo filter. EAN = item_code. ERP listing table is out of scope."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.tb_brand import TBBrand
from app.models.tb_category import TBCategory
from app.models.tb_item import TBItem
from app.models.tb_subcategory import TBSubCategory

_EAN_LEN_ESTANDAR = (12, 13, 14)
_EAN_MAS_SUFIJO = re.compile(r"^(\d{12,14})-(.+)$")


def norm(text: object) -> str:
    s = "" if text is None else str(text).strip()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.upper()


def norm_code(text: object) -> str:
    return re.sub(r"[^A-Z0-9]", "", norm(text))


def fab_core(text: object) -> str:
    """TL-DECOX50-1 y DECO X50(1-PACK) → DECOX501."""
    k = norm_code(text)
    if k.startswith("TL") and len(k) > 5:
        k = k[2:]
    return k.replace("PACK", "")


def _es_sufijo_no_comprable(suf: str) -> bool:
    u = suf.upper()
    if u == "OB" or u.endswith("-OB"):
        return True
    if "WH" in u or "WP" in u:
        return True
    return bool(u) and u[0].isdigit()


def es_combo_interno(ean: object) -> bool:
    """Combo armado, config (RAM/OS) u Open Box — no se compra como SKU suelto."""
    e = str(ean or "").strip()
    if not e:
        return False
    if e.endswith("-") or e.upper().endswith("-OB"):
        return True
    m = _EAN_MAS_SUFIJO.match(e)
    if m and _es_sufijo_no_comprable(m.group(2)):
        return True
    if "/" not in e:
        return False
    digits = re.sub(r"\D", "", e)
    if len(digits) > 13:
        return True
    left = re.sub(r"\D", "", e.split("/", 1)[0])
    return len(left) in _EAN_LEN_ESTANDAR


@dataclass
class Articulo:
    item_id: str
    ean: str
    descripcion: str
    categoria: str
    subcategoria: str
    marca: str
    fabricante: str

    def haystack(self) -> str:
        return " ".join(
            [
                self.ean,
                self.descripcion,
                self.categoria,
                self.subcategoria,
                self.marca,
                self.fabricante,
            ]
        )


def sin_combos_internos(articulos: list[Articulo]) -> list[Articulo]:
    return [a for a in articulos if not es_combo_interno(a.ean)]


def cargar_maestro(db: Session) -> list[Articulo]:
    """Load tb_item joined to brand/cat/subcat. ean=item_code, fabricante empty."""
    rows = db.execute(
        select(
            TBItem.item_id,
            TBItem.item_code,
            TBItem.item_desc,
            TBCategory.cat_desc,
            TBSubCategory.subcat_desc,
            TBBrand.brand_desc,
        )
        .outerjoin(
            TBBrand,
            (TBBrand.comp_id == TBItem.comp_id) & (TBBrand.brand_id == TBItem.brand_id),
        )
        .outerjoin(
            TBCategory,
            (TBCategory.comp_id == TBItem.comp_id) & (TBCategory.cat_id == TBItem.cat_id),
        )
        .outerjoin(
            TBSubCategory,
            (TBSubCategory.comp_id == TBItem.comp_id)
            & (TBSubCategory.cat_id == TBItem.cat_id)
            & (TBSubCategory.subcat_id == TBItem.subcat_id),
        )
    ).all()
    out: list[Articulo] = []
    for item_id, item_code, item_desc, cat_desc, subcat_desc, brand_desc in rows:
        if item_id is None:
            continue
        ean = str(item_code or "").strip()
        if ean.endswith(".0"):
            ean = ean[:-2]
        out.append(
            Articulo(
                item_id=str(item_id),
                ean=ean,
                descripcion=str(item_desc or "").strip(),
                categoria=str(cat_desc or "").strip(),
                subcategoria=str(subcat_desc or "").strip(),
                marca=str(brand_desc or "").strip(),
                fabricante="",
            )
        )
    return out
