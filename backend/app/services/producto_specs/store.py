"""Read, pre-load and edit the specs of notebooks and PCs (abm-specs-productos S3, S4, S6).

The products are the ERP items of category 46 (notebooks, minus the FUNDAS and BASE REFRIGERANTE subcategories) and
47 (PCs), read from `tb_item`. Their specs live in `producto_specs`, one typed column per field.

Pre-load, per field, first source with a readable value wins:
  1. `ml`: the attributes of the product's winning linked ML publication (`normalize.ganador`: most fields read,
     then most recently updated on ML, then lowest MLA id);
  2. `erp_name`: the ERP product name;
  3. `combo` (PCs): the combo components whose category is a PC part (48-55).
A field whose origin is `manual` is never touched, value or emptiness. Running it twice with the same data writes
nothing the second time. Categorical values go through the field's normalized list (`producto_spec_valores`): an
existing value with the same identity (case and spacing folded) is reused as it is spelled there; a new one is added.

Postgres only: rows are locked while a product is pre-loaded or edited, so a manual edit is never lost to a pre-load
that read the row before it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Optional

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.producto_spec import MAX_VALOR_LENGTH, ProductoSpec, ProductoSpecValor
from app.services.producto_specs import normalize
from app.services.producto_specs.campos import (
    CATEGORIAS,
    CATEGORICO,
    NOMBRES,
    NOTEBOOK,
    ORIGEN_COMBO,
    ORIGEN_MANUAL,
    ORIGEN_ML,
    ORIGEN_NOMBRE_ERP,
    PC,
    POR_NOMBRE,
    SUBCATEGORIAS_EXCLUIDAS,
    campos_de,
    clave,
    en_rango,
)

_SPECS = ProductoSpec.__table__
_VALORES = ProductoSpecValor.__table__

_PRODUCTOS_SQL = """
    SELECT t.item_id, t.cat_id, COALESCE(p.descripcion, t.item_desc) AS descripcion, p.codigo, p.marca, p.stock
    FROM tb_item t
    LEFT JOIN productos_erp p ON p.item_id = t.item_id
    WHERE t.cat_id IN (46, 47)
      AND NOT (t.cat_id = 46 AND t.subcat_id IN :excluidas)
"""


@dataclass(frozen=True)
class Producto:
    item_id: int
    tipo: str
    descripcion: Optional[str]
    codigo: Optional[str]
    marca: Optional[str]
    stock: Optional[int]


class ProductoNoEncontrado(LookupError):
    """The item is not a notebook or a PC of the ERP."""


class ValorNoValido(ValueError):
    def __init__(self, campo: str, detalle: str) -> None:
        super().__init__(f"{campo}: {detalle}")
        self.campo = campo
        self.detalle = detalle


def productos(db: Session, item_ids: Optional[Iterable[int]] = None) -> list[Producto]:
    sql = _PRODUCTOS_SQL
    params: dict[str, Any] = {"excluidas": SUBCATEGORIAS_EXCLUIDAS}
    binds = [bindparam("excluidas", expanding=True)]
    if item_ids is not None:
        sql += " AND t.item_id IN :ids"
        params["ids"] = sorted(set(item_ids)) or [-1]
        binds.append(bindparam("ids", expanding=True))
    rows = db.execute(text(sql + " ORDER BY t.item_id").bindparams(*binds), params).all()
    seen: dict[int, Producto] = {}
    for row in rows:  # tb_item is keyed by (comp_id, item_id): keep one row per item
        seen.setdefault(
            row.item_id,
            Producto(row.item_id, CATEGORIAS[row.cat_id], row.descripcion, row.codigo, row.marca, row.stock),
        )
    return list(seen.values())


def producto(db: Session, item_id: int) -> Producto:
    found = productos(db, [item_id])
    if not found:
        raise ProductoNoEncontrado(item_id)
    return found[0]


# ---------------------------------------------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------------------------------------------


def _ml_candidatos(db: Session, prods: list[Producto]) -> dict[int, list[normalize.CandidatoMl]]:
    if not prods:
        return {}
    tipos = {p.item_id: p.tipo for p in prods}
    rows = db.execute(
        text(
            """
            SELECT DISTINCT ON (l.producto_item_id, m.item_id)
                   l.producto_item_id, m.item_id, m.ml_last_updated, m.raw -> 'attributes' AS attributes
            FROM ml_item_product_links l
            JOIN ml_items m ON m.item_id = l.item_id
            WHERE l.match_status = 'linked' AND l.producto_item_id IN :ids
            ORDER BY l.producto_item_id, m.item_id
            """
        ).bindparams(bindparam("ids", expanding=True)),
        {"ids": list(tipos)},
    ).all()
    out: dict[int, list[normalize.CandidatoMl]] = {}
    for row in rows:
        specs = normalize.ml_specs(row.attributes or [], tipos[row.producto_item_id])
        out.setdefault(row.producto_item_id, []).append(normalize.CandidatoMl(row.item_id, row.ml_last_updated, specs))
    return out


def _componentes(db: Session, prods: list[Producto]) -> dict[int, list[normalize.Componente]]:
    pcs = [p.item_id for p in prods if p.tipo == PC]
    if not pcs:
        return {}
    rows = db.execute(
        text(
            """
            SELECT DISTINCT c.combo_item_id, t.cat_id, COALESCE(p.descripcion, t.item_desc) AS descripcion, p.marca,
                   c.cantidad, c.componente_item_id
            FROM combo_componentes c
            JOIN tb_item t ON t.item_id = c.componente_item_id
            LEFT JOIN productos_erp p ON p.item_id = c.componente_item_id
            WHERE c.combo_item_id IN :ids AND t.cat_id IN :cats
            """
        ).bindparams(bindparam("ids", expanding=True), bindparam("cats", expanding=True)),
        {"ids": pcs, "cats": list(normalize.CATEGORIAS_COMPONENTE)},
    ).all()
    out: dict[int, list[normalize.Componente]] = {}
    for row in rows:
        out.setdefault(row.combo_item_id, []).append(
            normalize.Componente(row.cat_id, row.descripcion, row.marca, Decimal(row.cantidad or 1))
        )
    return out


# ---------------------------------------------------------------------------------------------------------------
# Normalized lists
# ---------------------------------------------------------------------------------------------------------------


class Listas:
    """The normalized lists, loaded once; `resolver` maps a value to its list spelling, adding it when new."""

    def __init__(self, db: Session) -> None:
        self._db = db
        self._por_clave: dict[tuple[str, str], str] = {
            (row.campo, row.clave): row.valor
            for row in db.execute(text("SELECT campo, clave, valor FROM producto_spec_valores"))
        }

    def existente(self, campo: str, valor: str) -> Optional[str]:
        """The list spelling of `valor`, or None when the field's list does not have it."""
        return self._por_clave.get((campo, clave(valor)))

    def resolver(self, campo: str, valor: str, *, usuario_id: Optional[int] = None) -> str:
        key = clave(valor)
        existing = self._por_clave.get((campo, key))
        if existing is not None:
            return existing
        display = " ".join(valor.split())
        stored = self._db.execute(
            pg_insert(_VALORES)
            .values(campo=campo, clave=key, valor=display, created_by=usuario_id)
            .on_conflict_do_update(index_elements=["campo", "clave"], set_={"campo": _VALORES.c.campo})
            .returning(_VALORES.c.valor)
        ).scalar_one()
        self._por_clave[(campo, key)] = stored
        return stored


def valores(db: Session, campo: str) -> list[Any]:
    """The values a field can take: the normalized list for a categorical field, the stored numbers for a numeric one."""
    definicion = POR_NOMBRE[campo]
    if definicion.tipo == CATEGORICO:
        rows = db.execute(
            text("SELECT valor FROM producto_spec_valores WHERE campo = :c ORDER BY lower(valor)"), {"c": campo}
        )
        return [row.valor for row in rows]
    column = _SPECS.c[campo]
    rows = db.execute(
        text(f"SELECT DISTINCT {column.name} AS v FROM producto_specs WHERE {column.name} IS NOT NULL ORDER BY 1")
    )
    return [numero_json(row.v) for row in rows]


def agregar_valor(db: Session, campo: str, valor: str, usuario_id: int) -> str:
    definicion = POR_NOMBRE.get(campo)
    if definicion is None or definicion.tipo != CATEGORICO:
        raise ValorNoValido(campo, "solo los campos de lista aceptan valores nuevos")
    limpio = " ".join((valor or "").split())
    if not limpio:
        raise ValorNoValido(campo, "el valor está vacío")
    if len(limpio) > MAX_VALOR_LENGTH:
        raise ValorNoValido(campo, f"el valor supera {MAX_VALOR_LENGTH} caracteres")
    return Listas(db).resolver(campo, limpio, usuario_id=usuario_id)


def numero_json(value):
    """A stored number as JSON shows it: 15.6 stays a float, 16 (or 15.0 from a Numeric) an int."""
    if isinstance(value, Decimal):
        return float(value) if value != value.to_integral_value() else int(value)
    return value


# ---------------------------------------------------------------------------------------------------------------
# Pre-load
# ---------------------------------------------------------------------------------------------------------------


def _merge(
    prod: Producto,
    actual: Optional[dict],
    ml: dict,
    nombre: dict,
    combo: dict,
    listas: Listas,
) -> tuple[dict, dict]:
    origenes_actuales = (actual or {}).get("origenes") or {}
    values: dict[str, Any] = {}
    origenes: dict[str, str] = {}
    aplicables = {c.nombre for c in campos_de(prod.tipo)}
    for campo in NOMBRES:
        if origenes_actuales.get(campo) == ORIGEN_MANUAL:
            values[campo] = actual.get(campo)
            origenes[campo] = ORIGEN_MANUAL
            continue
        values[campo] = None
        if campo not in aplicables:
            continue
        for origen, source in ((ORIGEN_ML, ml), (ORIGEN_NOMBRE_ERP, nombre), (ORIGEN_COMBO, combo)):
            value = source.get(campo)
            if value is None:
                continue
            if POR_NOMBRE[campo].tipo == CATEGORICO:
                value = listas.resolver(campo, str(value)[:MAX_VALOR_LENGTH])
            values[campo] = value
            origenes[campo] = origen
            break
    return values, origenes


def _row_dict(row) -> dict:
    return dict(row._mapping)


def _same(actual: dict, values: dict, origenes: dict, fuente_mla: Optional[str]) -> bool:
    if (actual.get("origenes") or {}) != origenes or actual.get("fuente_mla") != fuente_mla:
        return False
    for campo, value in values.items():
        stored = actual.get(campo)
        if isinstance(stored, Decimal) or isinstance(value, Decimal):
            if (stored is None) != (value is None) or (stored is not None and Decimal(stored) != Decimal(value)):
                return False
        elif stored != value:
            return False
    return True


def precargar(db: Session, item_ids: Optional[Iterable[int]] = None, *, now: Optional[datetime] = None) -> dict:
    """Pre-load the given products (all notebooks and PCs when None). Idempotent; never touches manual fields.
    Returns the counts {productos, creados, actualizados, sin_cambios}. The caller commits."""
    now = now or datetime.now(UTC)
    prods = productos(db, item_ids)
    counts = {"productos": len(prods), "creados": 0, "actualizados": 0, "sin_cambios": 0}
    if not prods:
        return counts
    ids = [p.item_id for p in prods]
    actuales = {
        row.item_id: _row_dict(row)
        for row in db.execute(
            text("SELECT * FROM producto_specs WHERE item_id IN :ids ORDER BY item_id FOR UPDATE").bindparams(
                bindparam("ids", expanding=True)
            ),
            {"ids": ids},
        )
    }
    candidatos = _ml_candidatos(db, prods)
    componentes = _componentes(db, prods)
    listas = Listas(db)

    for prod in prods:
        winner = normalize.ganador(candidatos.get(prod.item_id, []))
        ml = winner.specs if winner else {}
        nombre = normalize.nombre_erp_specs(prod.descripcion, prod.tipo)
        combo = normalize.combo_specs(componentes.get(prod.item_id, [])) if prod.tipo == PC else {}
        actual = actuales.get(prod.item_id)
        values, origenes = _merge(prod, actual, ml, nombre, combo, listas)
        fuente_mla = winner.mla if winner and any(o == ORIGEN_ML for o in origenes.values()) else None

        if actual is None:
            inserted = db.execute(
                pg_insert(_SPECS)
                .values(
                    item_id=prod.item_id,
                    tipo=prod.tipo,
                    **values,
                    origenes=origenes,
                    fuente_mla=fuente_mla,
                    precargado_at=now,
                )
                .on_conflict_do_nothing(index_elements=["item_id"])
            )
            # A row created meanwhile (a manual edit) wins: it is pre-loaded on the next run, under its lock.
            counts["creados" if inserted.rowcount else "sin_cambios"] += 1
            continue
        if actual["tipo"] == prod.tipo and _same(actual, values, origenes, fuente_mla):
            counts["sin_cambios"] += 1
            continue
        db.execute(
            _SPECS.update()
            .where(_SPECS.c.item_id == prod.item_id)
            .values(tipo=prod.tipo, **values, origenes=origenes, fuente_mla=fuente_mla, precargado_at=now)
        )
        counts["actualizados"] += 1
    return counts


# ---------------------------------------------------------------------------------------------------------------
# Read and manual edit
# ---------------------------------------------------------------------------------------------------------------


def leer(db: Session, item_id: int) -> tuple[Producto, Optional[dict]]:
    prod = producto(db, item_id)
    row = db.execute(text("SELECT * FROM producto_specs WHERE item_id = :i"), {"i": item_id}).first()
    return prod, (_row_dict(row) if row else None)


def _validar(campo: str, value: Any, tipo: str, listas: Listas) -> Any:
    definicion = POR_NOMBRE.get(campo)
    if definicion is None:
        raise ValorNoValido(campo, "no es un campo de specs")
    if not definicion.aplica(tipo):
        raise ValorNoValido(campo, f"no aplica a un producto de tipo {tipo}")
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if definicion.tipo == CATEGORICO:
        existing = listas.existente(campo, str(value))
        if existing is None:
            raise ValorNoValido(campo, f"'{value}' no está en la lista; agregalo primero")
        return existing
    try:
        number = Decimal(str(value).replace(",", "."))
    except InvalidOperation:
        raise ValorNoValido(campo, f"'{value}' no es un número") from None
    if not number.is_finite() or not en_rango(definicion, number):
        raise ValorNoValido(campo, f"debe estar entre {definicion.minimo} y {definicion.maximo} {definicion.unidad}")
    if definicion.decimales:
        return number.quantize(Decimal(1).scaleb(-definicion.decimales))
    if number != number.to_integral_value():
        raise ValorNoValido(campo, "debe ser un número entero")
    return int(number)


def editar(db: Session, item_id: int, cambios: dict[str, Any], usuario_id: int) -> None:
    """Set the given fields by hand: each one becomes `manual` (an empty value too), so no pre-load changes it."""
    prod = producto(db, item_id)
    listas = Listas(db)
    validated = {campo: _validar(campo, value, prod.tipo, listas) for campo, value in cambios.items()}
    if db.execute(text("SELECT 1 FROM producto_specs WHERE item_id = :i"), {"i": item_id}).first() is None:
        precargar(db, [item_id])  # the first edit of a product starts from its pre-load, not from an empty row
    db.execute(
        pg_insert(_SPECS).values(item_id=item_id, tipo=prod.tipo).on_conflict_do_nothing(index_elements=["item_id"])
    )
    row = db.execute(text("SELECT origenes FROM producto_specs WHERE item_id = :i FOR UPDATE"), {"i": item_id}).one()
    origenes = dict(row.origenes or {})
    for campo in validated:
        origenes[campo] = ORIGEN_MANUAL
    db.execute(
        _SPECS.update()
        .where(_SPECS.c.item_id == item_id)
        .values(**validated, origenes=origenes, updated_by=usuario_id, updated_at=datetime.now(UTC))
    )


# ---------------------------------------------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------------------------------------------


def _completos_sql(tipo: str) -> str:
    return " + ".join(f"(s.{c.nombre} IS NOT NULL)::int" for c in campos_de(tipo))


def listar(
    db: Session,
    *,
    tipo: Optional[str] = None,
    marca: Optional[str] = None,
    incompletos: bool = False,
    q: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[int, list[dict]]:
    """Notebooks and PCs with how many of their fields are filled. `incompletos`: some field still empty."""
    total_nb, total_pc = len(campos_de(NOTEBOOK)), len(campos_de(PC))
    sql = f"""
        WITH base AS (
            SELECT DISTINCT ON (t.item_id)
                   t.item_id,
                   CASE t.cat_id WHEN 46 THEN 'notebook' ELSE 'pc' END AS tipo,
                   COALESCE(p.descripcion, t.item_desc) AS descripcion, p.codigo, p.marca, p.stock
            FROM tb_item t
            LEFT JOIN productos_erp p ON p.item_id = t.item_id
            WHERE t.cat_id IN (46, 47) AND NOT (t.cat_id = 46 AND t.subcat_id IN :excluidas)
            ORDER BY t.item_id
        )
        SELECT b.*, s.updated_at,
               COALESCE(CASE WHEN b.tipo = 'pc' THEN {_completos_sql(PC)} ELSE {_completos_sql(NOTEBOOK)} END, 0)
                   AS completos,
               CASE WHEN b.tipo = 'pc' THEN {total_pc} ELSE {total_nb} END AS total
        FROM base b
        LEFT JOIN producto_specs s ON s.item_id = b.item_id
        WHERE (CAST(:tipo AS text) IS NULL OR b.tipo = :tipo)
          AND (CAST(:marca AS text) IS NULL OR upper(b.marca) = upper(:marca))
          AND (CAST(:q AS text) IS NULL OR b.descripcion ILIKE :like OR b.codigo ILIKE :like
               OR CAST(b.item_id AS text) = :q)
    """
    # Counted after the incomplete filter, so `total` pages exactly the rows the filter returns.
    sql = f"SELECT x.*, count(*) OVER () AS filas FROM ({sql}) x" + (" WHERE completos < total" if incompletos else "")
    sql += " ORDER BY COALESCE(stock, 0) DESC, descripcion, item_id LIMIT :limit OFFSET :offset"
    q_clean = (q or "").strip() or None
    rows = db.execute(
        text(sql).bindparams(bindparam("excluidas", expanding=True)),
        {
            "excluidas": SUBCATEGORIAS_EXCLUIDAS,
            "tipo": tipo,
            "marca": (marca or "").strip() or None,
            "q": q_clean,
            "like": f"%{q_clean}%" if q_clean else None,
            "limit": limit,
            "offset": offset,
        },
    ).all()
    total = rows[0].filas if rows else 0
    return total, [{k: v for k, v in row._mapping.items() if k != "filas"} for row in rows]


def marcas(db: Session, tipo: Optional[str] = None) -> list[str]:
    rows = db.execute(
        text(
            """
            SELECT DISTINCT upper(p.marca) AS marca
            FROM tb_item t JOIN productos_erp p ON p.item_id = t.item_id
            WHERE t.cat_id IN (46, 47) AND NOT (t.cat_id = 46 AND t.subcat_id IN :excluidas)
              AND p.marca IS NOT NULL AND p.marca <> ''
              AND (CAST(:tipo AS text) IS NULL OR (CASE t.cat_id WHEN 46 THEN 'notebook' ELSE 'pc' END) = :tipo)
            ORDER BY 1
            """
        ).bindparams(bindparam("excluidas", expanding=True)),
        {"excluidas": SUBCATEGORIAS_EXCLUIDAS, "tipo": tipo},
    )
    return [row.marca for row in rows]
