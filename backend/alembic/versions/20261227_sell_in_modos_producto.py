"""sell in: a product's dated cost modes (weighted, last, manual) and their permissions

Revision ID: 20261227_sell_in_modos_producto
Revises: 20261226_ml_ads_display_catalog
Create Date: 2026-11-02

Owner: "Para sell in vamos a mantener el FIFO pero además quiero un sistema que con un permiso aparte se pueda elegir
ponderar el stock y el precio y no usar solo fifo [...] también que te deje setear que el costo sea el del último [...]
y otro permiso aparte para poder setear cantidad y costo a mano". Design: handoffs `sell-in-costos-propuesta.md`.

- `sell_in_modos_producto`: append-only rows, one per change of a product's mode (`fifo`, `ponderado`, `ultimo`,
  `manual`) from `desde` on. No row means FIFO, so every product stays as it is. A `manual` row carries the typed
  quantity and unit cost plus the product's cost frozen when it was saved; the others carry none of the three. A row
  made from a sell-in load (`origen = 'carga'`) names that purchase.
- `sell_in_consumos.modo_id`: a manual block's units are consumed from its mode row, not from a purchase line, so a
  consumption has exactly one source (`compra_item_id` or `modo_id`). Only a manual consumption may be negative: a
  manual cost above the frozen cost raises the sale's cost (owner, 2026-11-02).
- Triggers keep that sign rule in the database, not in the costing code: `sell_in_consumos_modo_manual` refuses a
  consumption whose `modo_id` is not a `manual` row of the same product, and the `sell_in_modos_producto` triggers
  refuse UPDATE, DELETE and TRUNCATE on the modes, so the row checked at insert cannot change afterwards. A trigger
  rather than a composite FK: the FK would need a copy of `modo` on every consumption plus a matching UNIQUE on the
  modes.
- Permissions `sell_in.costo_ponderado`, `sell_in.costo_ultimo`, `sell_in.costo_manual` and
  `sell_in.costo_retroactivo` (backdate a mode), ADMIN only (owner, 2026-11-02). Seeded only where the permission
  tables exist, so the sell-in schema tests can run the chain without them.

LOCK NOTE: the `sell_in_consumos` changes take an ACCESS EXCLUSIVE lock held to the end of the transaction. The
column is nullable without a default (no rewrite), but each of the two new CHECKs and each of the two new indexes
reads the whole table once while it is locked (measured: about 1.5 s on 3M rows). The sell-in drain reads and writes
it, so they run with `lock_timeout = '5s'` and the deploy is retried; the previous value is saved and restored, as in
20261217.

Downgrade: drops the manual consumptions (they would break the restored NOT NULL and CHECK), then the triggers, the
column, the table and the permissions. Rows valued under `ponderado` or `ultimo` keep their amounts, and the dropped
manual units are not re-allocated, until each product's next recompute (FIFO-only then); nothing is enqueued.
"""

from typing import List, Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261227_sell_in_modos_producto"
down_revision: Union[str, None] = "20261226_ml_ads_display_catalog"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LOCK_TIMEOUT = "5s"

# (codigo, nombre, descripcion, orden)
PERMISOS = [
    (
        "sell_in.costo_ponderado",
        "Sell in: ponderar el costo (PPP)",
        "Elegir que el sell in de un producto pondere las unidades y el valor de sus lotes en vez de usar FIFO.",
        87,
    ),
    (
        "sell_in.costo_ultimo",
        "Sell in: costo del último lote",
        "Elegir que todas las unidades que quedan de un producto tomen el valor de su lote más reciente.",
        88,
    ),
    (
        "sell_in.costo_manual",
        "Sell in: cantidad y costo a mano",
        "Cargar a mano la cantidad y el costo (por ejemplo, el de reposición) del sell in de un producto.",
        89,
    ),
    (
        "sell_in.costo_retroactivo",
        "Sell in: aplicar un modo de costo hacia atrás",
        "Aplicar un modo de costo de sell in desde una fecha pasada; cambia ventas ya registradas.",
        90,
    ),
]
ROLES = ("ADMIN",)

_INSERT_PERMISO = sa.text("""
    INSERT INTO permisos (codigo, nombre, descripcion, categoria, orden, es_critico, created_at)
    VALUES (:codigo, :nombre, :descripcion, 'productos', :orden, false, NOW())
    ON CONFLICT (codigo) DO NOTHING
""")
_INSERT_ROL_PERMISO = sa.text("""
    INSERT INTO roles_permisos_base (rol_id, permiso_id)
    SELECT r.id, p.id FROM roles r CROSS JOIN permisos p
    WHERE r.codigo = :rol AND p.codigo = :codigo
    ON CONFLICT DO NOTHING
""")
_DELETES = [
    "DELETE FROM roles_permisos_base WHERE permiso_id IN (SELECT id FROM permisos WHERE codigo = :codigo)",
    "DELETE FROM usuarios_permisos_override WHERE permiso_id IN (SELECT id FROM permisos WHERE codigo = :codigo)",
    "DELETE FROM permisos WHERE codigo = :codigo",
]

UPGRADE = [
    """
    CREATE TABLE IF NOT EXISTS sell_in_modos_producto (
        id BIGSERIAL PRIMARY KEY,
        item_id INTEGER NOT NULL REFERENCES productos_erp (item_id),
        modo VARCHAR(10) NOT NULL,
        desde DATE NOT NULL,
        cantidad INTEGER,
        costo_unit NUMERIC(18, 6),
        costo_base_unit NUMERIC(18, 6),
        origen VARCHAR(8) DEFAULT 'visor' NOT NULL,
        compra_id BIGINT REFERENCES sell_in_compras (id) ON DELETE RESTRICT,
        usuario_id INTEGER NOT NULL REFERENCES usuarios (id) ON DELETE RESTRICT,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
        CONSTRAINT ck_sell_in_modos_producto_modo CHECK (modo IN ('fifo', 'ponderado', 'ultimo', 'manual')),
        CONSTRAINT ck_sell_in_modos_producto_origen CHECK (origen IN ('visor', 'carga')),
        CONSTRAINT ck_sell_in_modos_producto_manual CHECK (
            (modo = 'manual' AND COALESCE(cantidad > 0 AND costo_unit > 0 AND costo_base_unit >= 0, false))
            OR (modo <> 'manual' AND cantidad IS NULL AND costo_unit IS NULL AND costo_base_unit IS NULL)
        ),
        CONSTRAINT ck_sell_in_modos_producto_compra CHECK ((origen = 'carga') = (compra_id IS NOT NULL))
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_sell_in_modos_producto_item_desde ON sell_in_modos_producto (item_id, desde, id)",
    "CREATE INDEX IF NOT EXISTS ix_sell_in_modos_producto_compra_id ON sell_in_modos_producto (compra_id) "
    "WHERE compra_id IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix_sell_in_modos_producto_usuario_id ON sell_in_modos_producto (usuario_id)",
    "ALTER TABLE sell_in_consumos ADD COLUMN IF NOT EXISTS modo_id BIGINT "
    "REFERENCES sell_in_modos_producto (id) ON DELETE RESTRICT",
    "ALTER TABLE sell_in_consumos ALTER COLUMN compra_item_id DROP NOT NULL",
    "ALTER TABLE sell_in_consumos DROP CONSTRAINT IF EXISTS ck_sell_in_consumos_origen",
    "ALTER TABLE sell_in_consumos ADD CONSTRAINT ck_sell_in_consumos_origen "
    "CHECK ((compra_item_id IS NULL) <> (modo_id IS NULL))",
    "ALTER TABLE sell_in_consumos DROP CONSTRAINT IF EXISTS ck_sell_in_consumos_descuento_no_negativo",
    "ALTER TABLE sell_in_consumos ADD CONSTRAINT ck_sell_in_consumos_descuento_no_negativo "
    "CHECK (descuento_ars >= 0 OR modo_id IS NOT NULL)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_sell_in_consumos_canal_venta_modo "
    "ON sell_in_consumos (canal, venta_ref, modo_id) WHERE modo_id IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix_sell_in_consumos_modo_id ON sell_in_consumos (modo_id)",
    """
    CREATE OR REPLACE FUNCTION sell_in_modos_producto_append_only() RETURNS TRIGGER AS $trg$
    BEGIN
        IF TG_LEVEL = 'STATEMENT' THEN
            RAISE EXCEPTION 'sell_in_modos_producto is append-only: % refused', TG_OP USING ERRCODE = 'check_violation';
        END IF;
        RAISE EXCEPTION 'sell_in_modos_producto is append-only: % refused on id %', TG_OP, OLD.id
            USING ERRCODE = 'check_violation';
    END;
    $trg$ LANGUAGE plpgsql
    """,
    "DROP TRIGGER IF EXISTS trg_sell_in_modos_producto_append_only ON sell_in_modos_producto",
    "CREATE TRIGGER trg_sell_in_modos_producto_append_only BEFORE UPDATE OR DELETE ON sell_in_modos_producto "
    "FOR EACH ROW EXECUTE FUNCTION sell_in_modos_producto_append_only()",
    # Row triggers do not see TRUNCATE (CASCADE included); a statement trigger does.
    "DROP TRIGGER IF EXISTS trg_sell_in_modos_producto_no_truncate ON sell_in_modos_producto",
    "CREATE TRIGGER trg_sell_in_modos_producto_no_truncate BEFORE TRUNCATE ON sell_in_modos_producto "
    "FOR EACH STATEMENT EXECUTE FUNCTION sell_in_modos_producto_append_only()",
    """
    CREATE OR REPLACE FUNCTION sell_in_consumos_modo_manual() RETURNS TRIGGER AS $trg$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM sell_in_modos_producto m
            WHERE m.id = NEW.modo_id AND m.modo = 'manual' AND m.item_id = NEW.item_id
        ) THEN
            RAISE EXCEPTION 'sell_in_consumos.modo_id % is not a manual block of item %', NEW.modo_id, NEW.item_id
                USING ERRCODE = 'check_violation';
        END IF;
        RETURN NEW;
    END;
    $trg$ LANGUAGE plpgsql
    """,
    "DROP TRIGGER IF EXISTS trg_sell_in_consumos_modo_manual ON sell_in_consumos",
    "CREATE TRIGGER trg_sell_in_consumos_modo_manual BEFORE INSERT OR UPDATE OF modo_id, item_id ON sell_in_consumos "
    "FOR EACH ROW WHEN (NEW.modo_id IS NOT NULL) EXECUTE FUNCTION sell_in_consumos_modo_manual()",
]

DOWNGRADE = [
    "DELETE FROM sell_in_consumos WHERE modo_id IS NOT NULL",
    "DROP TRIGGER IF EXISTS trg_sell_in_consumos_modo_manual ON sell_in_consumos",
    "DROP FUNCTION IF EXISTS sell_in_consumos_modo_manual()",
    "DROP INDEX IF EXISTS ix_sell_in_consumos_modo_id",
    "DROP INDEX IF EXISTS uq_sell_in_consumos_canal_venta_modo",
    "ALTER TABLE sell_in_consumos DROP CONSTRAINT IF EXISTS ck_sell_in_consumos_descuento_no_negativo",
    "ALTER TABLE sell_in_consumos ADD CONSTRAINT ck_sell_in_consumos_descuento_no_negativo CHECK (descuento_ars >= 0)",
    "ALTER TABLE sell_in_consumos DROP CONSTRAINT IF EXISTS ck_sell_in_consumos_origen",
    "ALTER TABLE sell_in_consumos ALTER COLUMN compra_item_id SET NOT NULL",
    "ALTER TABLE sell_in_consumos DROP COLUMN IF EXISTS modo_id",
    "DROP TABLE IF EXISTS sell_in_modos_producto",  # its append-only triggers go with it
    "DROP FUNCTION IF EXISTS sell_in_modos_producto_append_only()",
]


def _run(statements: List[str]) -> None:
    # Restores the caller's lock_timeout. The permission seeding (`_con_permisos`) inspects the live connection,
    # so this revision runs online only, as every deploy does.
    op.execute("SELECT set_config('sell_in_modos.lock_timeout_previo', current_setting('lock_timeout'), true)")
    op.execute(f"SELECT set_config('lock_timeout', '{LOCK_TIMEOUT}', true)")
    for statement in statements:
        op.execute(statement)
    op.execute("SELECT set_config('lock_timeout', current_setting('sell_in_modos.lock_timeout_previo'), true)")


def _con_permisos() -> bool:
    inspector = sa.inspect(op.get_bind())
    return all(
        inspector.has_table(t) for t in ("permisos", "roles", "roles_permisos_base", "usuarios_permisos_override")
    )


def upgrade() -> None:
    _run(UPGRADE)
    if not _con_permisos():
        return
    conn = op.get_bind()
    for codigo, nombre, descripcion, orden in PERMISOS:
        conn.execute(_INSERT_PERMISO, {"codigo": codigo, "nombre": nombre, "descripcion": descripcion, "orden": orden})
        for rol in ROLES:
            conn.execute(_INSERT_ROL_PERMISO, {"rol": rol, "codigo": codigo})


def downgrade() -> None:
    if _con_permisos():
        conn = op.get_bind()
        for codigo, *_ in PERMISOS:
            for statement in _DELETES:
                conn.execute(sa.text(statement), {"codigo": codigo})
    _run(DOWNGRADE)
