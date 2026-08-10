"""compras_039: corregir la pata destino de las imputaciones dinero_a_cuenta

Revision ID: compras_039_dac_pata_destino
Revises: compras_038_imputacion_origen_leg
Create Date: 2026-08-10

PROBLEMA
--------
`dinero_a_cuenta_service.consumir` grababa la imputación DAC→pedido con
`moneda_imputada = dac.moneda` — la moneda del ORIGEN — y no convertía nunca,
ni guardaba `tipo_cambio`. Cuando el DAC y el pedido están en monedas
distintas, `pedidos_service.calcular_saldo_pendiente_pedido` filtra
`Imputacion.moneda_imputada == pedido.moneda` y DESCARTA la fila: el dinero a
cuenta se gastaba pero la deuda del pedido no bajaba. Es el espejo exacto del
bug de NCs, del lado destino.

QUÉ CORRIGE ESTA MIGRACIÓN
--------------------------
La pata ORIGEN de estas filas YA es correcta: compras_038 la backfilleó con
`monto_origen = monto_imputado, moneda_origen = moneda_imputada`, y para este
origen ambas estaban efectivamente denominadas en la moneda del DAC. Así que
acá sólo se reescribe la pata DESTINO:

  - `moneda_imputada` ← moneda del pedido destino.
  - `monto_imputado`  ← el monto origen convertido a esa moneda.
  - `tipo_cambio`     ← el TC usado en la conversión.

CAVEAT DEL TC (leer antes de aprobar)
-------------------------------------
El TC realmente usado al consumir era el de la OP que consumía, y ese dato
NUNCA se persistió en la fila (ni hay FK a la OP consumidora desde
`imputaciones`). El único TC alcanzable desde la fila es el del propio pedido
destino (`pedidos_compra.tipo_cambio`), que es el TC de referencia declarado
para ese pedido — y que la propia OP actualiza cuando corre con
`actualizar_tc_pedido = True`.

Se usa ése, y sólo cuando es > 0. Es una aproximación, pero la fila HOY
contribuye CERO al saldo del pedido (queda filtrada por moneda), así que
cualquier conversión con el TC declarado del pedido está estrictamente más
cerca de la verdad que no imputar nada. La pata origen no se toca, así que el
saldo del DAC sigue siendo exacto.

Filas cuyo pedido destino no tiene un TC utilizable NO se tocan: preferimos
dejarlas visibles antes que fabricar un TC (mismo criterio que compras_038).
Quedan localizables con `DIAGNOSTICO_PENDIENTES_SQL`.

Reversals (`es_reversal = TRUE`) se corrigen igual: `desimputar` copia las dos
patas verbatim, así que arrastran el mismo error y deben compensar el mismo
número.

Idempotente: tras correr, `moneda_imputada` ya coincide con la del pedido y el
WHERE deja de matchear.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision = "compras_039_dac_pata_destino"
down_revision = "compras_038_imputacion_origen_leg"
branch_labels = None
depends_on = None


# ──────────────────────────────────────────────────────────────────────────
# SQL portable (Postgres en prod, SQLite en el test de migración). Se expone
# como constante para que `tests/unit/test_migration_compras_039_dac_pata_
# destino.py` ejercite ESTA sentencia y no una copia.
# ──────────────────────────────────────────────────────────────────────────

FIX_DAC_PATA_DESTINO_SQL = """
UPDATE imputaciones
   SET monto_imputado = ROUND(
           CASE
               WHEN moneda_origen = 'USD'
                   THEN monto_origen * (
                       SELECT p.tipo_cambio FROM pedidos_compra p WHERE p.id = imputaciones.destino_id
                   )
               ELSE monto_origen / (
                       SELECT p.tipo_cambio FROM pedidos_compra p WHERE p.id = imputaciones.destino_id
                   )
           END, 2),
       moneda_imputada = (
           SELECT p.moneda FROM pedidos_compra p WHERE p.id = imputaciones.destino_id
       ),
       tipo_cambio = (
           SELECT p.tipo_cambio FROM pedidos_compra p WHERE p.id = imputaciones.destino_id
       )
 WHERE origen_tipo = 'dinero_a_cuenta'
   AND destino_tipo = 'pedido_compra'
   AND monto_origen IS NOT NULL
   AND moneda_origen IS NOT NULL
   AND EXISTS (
           SELECT 1 FROM pedidos_compra p
            WHERE p.id = imputaciones.destino_id
              AND p.moneda <> imputaciones.moneda_imputada
              AND p.tipo_cambio IS NOT NULL
              AND p.tipo_cambio > 0
       )
"""

# Filas que quedan sin corregir por falta de TC en el pedido destino. No se
# ejecuta en la migración: existe para auditarlas a mano después del deploy.
DIAGNOSTICO_PENDIENTES_SQL = """
SELECT i.id, i.origen_id, i.destino_id, i.monto_origen, i.moneda_origen,
       i.monto_imputado, i.moneda_imputada, p.moneda AS pedido_moneda,
       p.tipo_cambio AS pedido_tipo_cambio
  FROM imputaciones i
  JOIN pedidos_compra p ON p.id = i.destino_id
 WHERE i.origen_tipo = 'dinero_a_cuenta'
   AND i.destino_tipo = 'pedido_compra'
   AND p.moneda <> i.moneda_imputada
"""


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text(FIX_DAC_PATA_DESTINO_SQL))


def downgrade() -> None:
    # Sin vuelta atrás: la pata destino previa era la moneda del ORIGEN, que es
    # exactamente `monto_origen` / `moneda_origen`. Restaurarla sería reintroducir
    # el bug a mano y perder el `tipo_cambio` recién grabado. La migración es un
    # arreglo de datos, no un cambio de esquema — el downgrade es no-op a propósito.
    pass
