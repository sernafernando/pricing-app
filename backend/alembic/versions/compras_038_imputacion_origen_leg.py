"""compras_038: pata origen en imputaciones (monto_origen + moneda_origen)

Revision ID: compras_038_imputacion_origen_leg
Revises: 20260801_pxq_tier_snapshot
Create Date: 2026-08-10

Etapa 1 de `compras-imputacion-doble-pata`.

PROBLEMA
--------
`imputaciones` es un vínculo polimórfico origen→destino, pero guarda UN SOLO
importe (`monto_imputado` + `moneda_imputada`). Hoy cada lado lee esa columna
con una regla distinta:

  - `pedidos_service.calcular_saldo_pendiente_pedido` filtra
    `moneda_imputada == pedido.moneda` → la lee como DENOMINADA EN DESTINO.
  - `ncs_locales_service.calcular_saldo_pendiente` la suma sin filtro de moneda
    → la lee como DENOMINADA EN ORIGEN.

La asimetría es inocua sólo porque cross-moneda está bloqueado para orígenes
NC. Al levantar ese bloqueo (etapa 2), una NC de 1.000 ARS imputada a un pedido
USD guardaría 0,66 USD y su propio saldo leería `1000 - 0,66` → la misma NC se
podría gastar ~1.500 veces.

SOLUCIÓN
--------
Cada fila pasa a registrar AMBAS patas de forma exacta:

  - `monto_origen` / `moneda_origen`     → lo que se consumió del ORIGEN, en la
                                           moneda del ORIGEN.
  - `monto_imputado` / `moneda_imputada` → lo que se aplicó al DESTINO, en la
                                           moneda del DESTINO (sin cambios).

NULLABILIDAD
------------
Las columnas quedan NULLABLE a nivel DB a propósito. Tras el backfill no queda
ninguna fila en NULL, pero mantenerlas nullable evita que una instancia de app
vieja (pre-etapa-1) rompa con 500 al insertar durante una ventana de deploy
rolling — sobre el camino del dinero eso sería un incidente. La obligatoriedad
la impone `imputaciones_service.crear_imputacion`, que es el ÚNICO lugar que
construye filas de esta tabla, con parámetros requeridos.
Promover a NOT NULL queda para una migración posterior, una vez que todas las
instancias corran código de etapa 1.

Los CHECK toleran NULL pero prohíben la pata a medias (`both-or-neither`).
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision = "compras_038_imputacion_origen_leg"
down_revision = "20260810_sector_tipo_check_ia"
branch_labels = None
depends_on = None


# ──────────────────────────────────────────────────────────────────────────
# Backfill — SQL portable (Postgres en prod, SQLite en los tests de migración).
# Se expone como constantes para que `tests/unit/test_migration_compras_038_
# origen_leg.py` ejercite EXACTAMENTE estas sentencias y no una copia.
# ──────────────────────────────────────────────────────────────────────────

# Paso 1 — caso general: la pata origen coincide con la pata destino.
#
# Es EXACTO (no una reconstrucción) para todas las filas cuyo origen y destino
# comparten moneda, y además para dos familias que graban `moneda_imputada` ya
# denominada en ORIGEN aunque el destino sea otra moneda:
#   - `dinero_a_cuenta`     → `dinero_a_cuenta_service.consumir` graba
#                             `moneda_imputada = dac.moneda`.
#   - `nota_credito_local`  → `ncs_locales_service.resolver_varianza_tc` graba
#                             `moneda_imputada = 'ARS'` (moneda de la ND/NC)
#                             sobre pedidos USD.
BACKFILL_BASE_SQL = """
UPDATE imputaciones
   SET monto_origen = monto_imputado,
       moneda_origen = moneda_imputada
 WHERE monto_origen IS NULL
"""

# Paso 2 — corrección para el ÚNICO caso donde `moneda_imputada` está
# denominada en DESTINO: origen `orden_pago` cross-moneda
# (`ordenes_pago_service.ejecutar_pago`, conversión OP↔pedido).
#
# Se reconstruye invirtiendo la conversión original con el `tipo_cambio` que la
# propia fila persiste — no se inventa nada externo:
#   - OP ARS → pedido USD: se grabó `USD = ARS / TC`  ⇒  `ARS = USD * TC`.
#   - OP USD → pedido ARS: se grabó `ARS = USD * TC`  ⇒  `USD = ARS / TC`.
#
# Caveat conocido: la conversión original cuantizó a 2 decimales, así que la
# inversión puede diferir del importe pre-conversión real por menos de un
# centavo. Es la mejor reconstrucción posible (el valor pre-conversión nunca se
# persistió) y NO afecta ninguna lectura: no existe hoy ninguna agregación
# origin-side sobre orígenes `orden_pago`. Las escrituras nuevas sí pasan el
# valor pre-conversión exacto, sin invertir la división.
#
# Filas cross-moneda sin `tipo_cambio` utilizable quedan con el backfill base:
# preferimos un dato conservador antes que fabricar uno.
BACKFILL_OP_CROSS_MONEDA_SQL = """
UPDATE imputaciones
   SET moneda_origen = (
           SELECT op.moneda FROM ordenes_pago op WHERE op.id = imputaciones.origen_id
       ),
       monto_origen = ROUND(
           CASE
               WHEN moneda_imputada = 'USD' THEN monto_imputado * tipo_cambio
               ELSE monto_imputado / tipo_cambio
           END, 2)
 WHERE origen_tipo = 'orden_pago'
   AND tipo_cambio IS NOT NULL
   AND tipo_cambio > 0
   AND EXISTS (
           SELECT 1 FROM ordenes_pago op
            WHERE op.id = imputaciones.origen_id
              AND op.moneda <> imputaciones.moneda_imputada
       )
"""


def upgrade() -> None:
    op.add_column("imputaciones", sa.Column("monto_origen", sa.Numeric(18, 2), nullable=True))
    op.add_column("imputaciones", sa.Column("moneda_origen", sa.String(3), nullable=True))

    conn = op.get_bind()
    conn.execute(sa.text(BACKFILL_BASE_SQL))
    conn.execute(sa.text(BACKFILL_OP_CROSS_MONEDA_SQL))

    # CHECKs NULL-tolerantes (ver nota de nullabilidad en el docstring).
    op.create_check_constraint(
        "ck_imputaciones_monto_origen_positivo",
        "imputaciones",
        "monto_origen IS NULL OR monto_origen > 0",
    )
    op.create_check_constraint(
        "ck_imputaciones_moneda_origen",
        "imputaciones",
        "moneda_origen IS NULL OR moneda_origen IN ('ARS','USD')",
    )
    # Both-or-neither: nunca media pata origen.
    op.create_check_constraint(
        "ck_imputaciones_origen_leg_completa",
        "imputaciones",
        "(monto_origen IS NULL AND moneda_origen IS NULL) OR (monto_origen IS NOT NULL AND moneda_origen IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_imputaciones_origen_leg_completa", "imputaciones", type_="check")
    op.drop_constraint("ck_imputaciones_moneda_origen", "imputaciones", type_="check")
    op.drop_constraint("ck_imputaciones_monto_origen_positivo", "imputaciones", type_="check")
    op.drop_column("imputaciones", "moneda_origen")
    op.drop_column("imputaciones", "monto_origen")
