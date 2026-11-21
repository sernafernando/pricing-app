"""Run the real costo SI code against a database without writing to it (sell-in-costo-si T4 dry-run, plan
handoffs/sell-in-costo-si-t4-plan.md §2: "SELECT only, rollback, no SET").

A prod database before the Costo SI deploy has no `costo_si_pasos` (and may lack other tables or columns that the
pending migrations add). A `Sombra` lets the code that will run after the deploy (the engine's inputs, the `lote`
reader, the areas' report-only paths) run unchanged anyway: every statement sent through its connection that names a
shadowed table gets a CTE of that name in front, and a CTE hides the table of the same name in the whole statement.

- `costo_si_pasos` is always shadowed, by the steps the caller computed in memory (`fijar_pasos`): the history the
  recompute WILL store, never the one on the database.
- A model table missing on the database is shadowed empty; a model table missing columns is shadowed as the real
  table plus those columns at their server default (else NULL). Every one is listed in `sombras` so the report says
  which figures rest on a stand-in (a data backfill inside a pending migration is NOT reproduced).

`motor_solo_lectura(url)` opens its own connection (no pool, none of the app engine's checkout `SET`s): psycopg2 opens
every transaction with `BEGIN READ ONLY` (the connection's `readonly` attribute, not a SET statement: the session
default stays off), so any write raises on the server, and the caller rolls back at the end. On top of that, only the
`PERMITIDAS` statements leave the process: anything else, a SET above all, raises `SentenciaNoPermitida` first.
"""

from __future__ import annotations

import json
import re
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Dict, Iterable, Iterator, List, Optional, Sequence

from sqlalchemy import Table, create_engine, event, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from app.core.database import Base

PASOS = "costo_si_pasos"
_PREFIJO = "csi_sombra_"
_DIALECTO = postgresql.dialect()
# What may come before a statement's first keyword: blanks and `--` comment lines.
_INICIO = re.compile(r"^(?:\s+|--[^\n]*\n)*", re.S)
_WITH = re.compile(r"WITH(?:\s+RECURSIVE)?\s", re.I)


# The only statements the read-only engine sends: reads, and the savepoints `begin_nested` uses. Anything else (a SET
# above all: through PgBouncer a session SET leaks to the next client) raises before it reaches the server.
PERMITIDAS = ("SELECT", "WITH", "SHOW", "SAVEPOINT", "RELEASE", "ROLLBACK")
_PRIMERA = re.compile(r"[A-Za-z]+")


class SentenciaNoPermitida(RuntimeError):
    """A statement other than a read reached the read-only engine."""


def _verificar(sentencia: str) -> None:
    cuerpo = sentencia[_INICIO.match(sentencia).end() :]
    palabra = _PRIMERA.match(cuerpo)
    if palabra is None or palabra.group(0).upper() not in PERMITIDAS:
        raise SentenciaNoPermitida(f"read-only dry-run refused: {cuerpo[:80]!r}")


@dataclass(frozen=True)
class TablaSombra:
    nombre: str
    motivo: str  # 'pasos' | 'falta tabla' | 'faltan columnas: a, b'


def _tipo(columna) -> str:
    return columna.type.compile(dialect=_DIALECTO)


def _default(columna) -> str:
    """A missing column's value in the stand-in: its server default when it is a plain literal, else NULL."""
    server = columna.server_default
    literal = getattr(getattr(server, "arg", None), "text", None)
    valor = literal if literal is not None else "NULL"
    return f"CAST({valor} AS {_tipo(columna)})"


def _json(valor):
    if isinstance(valor, (Decimal, date, datetime)):
        return str(valor)
    return valor


class Sombra:
    """The stand-ins of one database (built by `preparar`) and the steps to read as `costo_si_pasos`."""

    def __init__(self, tablas: Dict[str, Table], faltantes: Dict[str, Optional[List[str]]], esquema: str):
        self._tablas = tablas
        self._faltantes = faltantes  # table -> None (whole table missing) | the missing column names
        self._esquema = esquema
        self._pasos: List[dict] = []
        nombres = [PASOS, *sorted(faltantes)]
        self._patron = re.compile(r"\b(" + "|".join(re.escape(n) for n in nombres) + r")\b")

    @property
    def sombras(self) -> List[TablaSombra]:
        out = [TablaSombra(PASOS, "pasos")]
        for nombre, columnas in sorted(self._faltantes.items()):
            if nombre == PASOS:
                continue
            out.append(
                TablaSombra(nombre, "falta tabla" if columnas is None else "faltan columnas: " + ", ".join(columnas))
            )
        return out

    def fijar_pasos(self, filas: Iterable[dict]) -> None:
        """The rows `costo_si_pasos` reads as from now on (each a dict of its columns; missing ones are NULL)."""
        self._pasos = [dict(f) for f in filas]

    def _cte(self, nombre: str) -> tuple:
        tabla = self._tablas[nombre]
        param = f"{_PREFIJO}{nombre}"
        if nombre == PASOS:
            columnas = ", ".join(f"{c.name} {_tipo(c)}" for c in tabla.columns)
            filas = json.dumps([{k: _json(v) for k, v in f.items()} for f in self._pasos])
            return f"{nombre} AS (SELECT * FROM jsonb_to_recordset(CAST(%({param})s AS jsonb)) AS t({columnas}))", {
                param: filas
            }
        faltan = self._faltantes[nombre]
        if faltan is None:
            columnas = ", ".join(f"CAST(NULL AS {_tipo(c)}) AS {c.name}" for c in tabla.columns)
            return f"{nombre} AS (SELECT {columnas} WHERE false)", {}
        extra = ", ".join(f"{_default(tabla.columns[c])} AS {c}" for c in faltan)
        return f'{nombre} AS (SELECT t.*, {extra} FROM "{self._esquema}".{nombre} t)', {}

    def reescribir(self, sentencia: str, parametros):
        """`sentencia` with a CTE in front for every shadowed table it names (unchanged when it names none)."""
        nombres = sorted(set(self._patron.findall(sentencia)))
        if not nombres or not isinstance(parametros, dict):
            return sentencia, parametros
        ctes, extra = [], {}
        for nombre in nombres:
            cte, params = self._cte(nombre)
            ctes.append(cte)
            extra.update(params)
        inicio = _INICIO.match(sentencia).end()
        cuerpo = sentencia[inicio:]
        con = _WITH.match(cuerpo)
        if con:
            nueva = f"{cuerpo[: con.end()]}{', '.join(ctes)}, {cuerpo[con.end() :]}"
        else:
            nueva = f"WITH {', '.join(ctes)} {cuerpo}"
        return nueva, {**parametros, **extra}

    def instalar(self, conexion: Connection) -> None:
        @event.listens_for(conexion, "before_cursor_execute", retval=True)
        def _antes(conn, cursor, sentencia, parametros, contexto, executemany):
            if executemany:
                return sentencia, parametros
            return self.reescribir(sentencia, parametros)


def _modelos() -> Dict[str, Table]:
    import app.models  # noqa: F401  (every model registers its table on Base.metadata)

    return {t.name: t for t in Base.metadata.sorted_tables}


def preparar(conexion: Connection, tablas: Optional[Sequence[str]] = None) -> Sombra:
    """The stand-ins for this database: `costo_si_pasos`, plus every model table (of `tablas`, default all) missing on
    the database or missing columns there. Reads `information_schema` only. Installs the rewrite on `conexion`."""
    modelos = _modelos()
    esquema = conexion.execute(text("SELECT current_schema()")).scalar()
    existentes: Dict[str, set] = {}
    for tabla, columna in conexion.execute(
        text("SELECT table_name, column_name FROM information_schema.columns WHERE table_schema = :s"), {"s": esquema}
    ):
        existentes.setdefault(tabla, set()).add(columna)
    faltantes: Dict[str, Optional[List[str]]] = {}
    for nombre in tablas if tablas is not None else sorted(modelos):
        tabla = modelos.get(nombre)
        if tabla is None or nombre == PASOS:
            continue
        if nombre not in existentes:
            faltantes[nombre] = None
            continue
        faltan = [c.name for c in tabla.columns if c.name not in existentes[nombre]]
        if faltan:
            faltantes[nombre] = faltan
    sombra = Sombra(modelos, faltantes, esquema)
    sombra.instalar(conexion)
    return sombra


def motor_solo_lectura(url: str, **opciones) -> Engine:
    """An engine whose every transaction is `BEGIN READ ONLY` (psycopg2's `readonly` attribute, no SET), with no pool
    and none of the app engine's checkout hooks. `opciones` go to `create_engine` (tests: a schema's search_path)."""
    motor = create_engine(url, poolclass=NullPool, **opciones)

    @event.listens_for(motor, "connect")
    def _solo_lectura(dbapi_conn, _registro):
        dbapi_conn.readonly = True

    @event.listens_for(motor, "before_cursor_execute")
    def _solo_lecturas(conn, cursor, sentencia, parametros, contexto, executemany):
        _verificar(sentencia)

    return motor


@dataclass
class Simulacion:
    db: Session
    sombra: Sombra
    notas: List[str] = field(default_factory=list)


@contextmanager
def simular(motor: Engine, tablas: Optional[Sequence[str]] = None) -> Iterator[Simulacion]:
    """One read-only session with the stand-ins installed; always rolled back at the end."""
    with motor.connect() as conexion:
        try:
            sombra = preparar(conexion, tablas)
            db = Session(bind=conexion, autoflush=False)
            try:
                yield Simulacion(db, sombra)
            finally:
                db.close()
        finally:
            conexion.rollback()
