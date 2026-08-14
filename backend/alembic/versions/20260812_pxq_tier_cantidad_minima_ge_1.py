"""ml_pxq_tier: aceptar el tramo de UNA unidad (cantidad_minima >= 1)

El CheckConstraint original decía `cantidad_minima > 1`. Salió de leer la
documentación de MercadoLibre al pie de la letra, que afirma que
`min_purchase_unit` tiene que ser mayor que 1. La realidad la contradice en
las dos puntas.

1) ML LO ACEPTA. El nodo crudo de MLA1563835240 trae
   `{"id": "3396", "amount": 80999, "min_purchase_unit": 1}` conviviendo con
   dos tramos comunes, y con las dos `context_restrictions`
   (`channel_marketplace` y `user_type_business`).

2) Y CUMPLE UNA FUNCIÓN — esta es la razón decisiva. El tramo de 1 unidad es
   lo que habilita que la publicación figure como "Venta para negocios" en
   MercadoLibre. No es un residuo ni una entidad ajena a la tabla mayorista:
   es lo que prende la visibilidad B2B. Sin ese tramo la publicación no
   aparece en esa vitrina, así que un mirror que no puede representarlo
   tampoco puede describir el estado que el operador abre el panel a mirar.

Queda escrito acá y en `app/models/ml_pxq_tier.py` justamente porque este es
el tipo de restricción que alguien va a querer "restaurar por prolijidad"
leyendo la misma documentación dentro de seis meses. La doc no es la fuente
de verdad; la plataforma sí.

Lo que el constraint sigue rechazando —cero y negativos— no es una cantidad
que MercadoLibre pueda expresar.

El constraint se RENOMBRA de `ck_ml_pxq_tier_cantidad_minima_gt_1` a
`ck_ml_pxq_tier_cantidad_minima_ge_1`. Postgres no permite editar el cuerpo de
un CHECK in situ: hay que dropearlo y recrearlo igual. O sea que el renombre
sale GRATIS en DDL, y dejar un nombre que dice `gt_1` sobre un cuerpo que dice
`>= 1` es una trampa para el próximo que lea `\\d ml_pxq_tier` y le crea al
nombre en vez de al cuerpo.

Revision ID: 20260812_pxq_cantidad_ge_1
Revises: 20260811_ver_web_tarjeta
Create Date: 2026-08-12

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20260812_pxq_cantidad_ge_1"
down_revision = "20260811_ver_web_tarjeta"
branch_labels = None
depends_on = None

TABLE_NAME = "ml_pxq_tier"
OLD_CONSTRAINT_NAME = "ck_ml_pxq_tier_cantidad_minima_gt_1"
NEW_CONSTRAINT_NAME = "ck_ml_pxq_tier_cantidad_minima_ge_1"


def upgrade() -> None:
    op.drop_constraint(OLD_CONSTRAINT_NAME, TABLE_NAME, type_="check")
    op.create_check_constraint(NEW_CONSTRAINT_NAME, TABLE_NAME, "cantidad_minima >= 1")


def downgrade() -> None:
    # La trampa de este downgrade: si ya existen filas con `cantidad_minima = 1`
    # —y después de un solo `adopt-live` sobre una publicación B2B existen—
    # recrear `> 1` explota con un CheckViolation crudo, en medio de la
    # migración, sin decir qué hacer.
    #
    # Se REHÚSA en vez de borrar, y no por prolijidad. Esas filas son las que
    # habilitan "Venta para negocios": borrarlas silenciosamente le sacaría al
    # mirror el único registro local de un precio que sigue vivo en
    # MercadoLibre, junto con su `ml_price_id` y su snapshot. El operador se
    # enteraría recién cuando el panel dejara de mostrar el tramo, sin nada en
    # pantalla que explique la diferencia.
    #
    # Misma convención que `20260810_sector_tipo_metadata_check_ia.py`:
    # rehusar fuerte antes que fallar críptico o corromper datos.
    bind = op.get_bind()
    afectadas = bind.execute(
        sa.text(f"SELECT id, item_id FROM {TABLE_NAME} WHERE cantidad_minima = 1 ORDER BY id")
    ).all()
    if afectadas:
        ids = [row.id for row in afectadas]
        items = sorted({row.item_id for row in afectadas})
        raise RuntimeError(
            f"No se puede bajar {revision}: quedan {len(ids)} fila(s) en {TABLE_NAME} con cantidad_minima=1 "
            f"(tier ids {ids}, publicaciones {items}). El constraint viejo (`cantidad_minima > 1`) las "
            f"rechazaría. Borralas a mano primero —por ejemplo "
            f"`DELETE FROM {TABLE_NAME} WHERE cantidad_minima = 1;`— sabiendo lo que eso implica: el tramo de "
            f"1 unidad es lo que habilita 'Venta para negocios', y el precio SIGUE VIVO en MercadoLibre "
            f"(`pxq_diff` lo re-emite como untracked keep), así que borrar la fila local no lo saca de ML: "
            f"solo deja al mirror sin forma de representarlo."
        )
    op.drop_constraint(NEW_CONSTRAINT_NAME, TABLE_NAME, type_="check")
    op.create_check_constraint(OLD_CONSTRAINT_NAME, TABLE_NAME, "cantidad_minima > 1")
