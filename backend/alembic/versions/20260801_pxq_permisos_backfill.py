"""ml-wholesale-pxq-pricing PR2: catálogo pxq.ver/pxq.escribir + backfill

Permisos:
- pxq.ver: ver tiers de precio por cantidad (mayorista) ML
- pxq.escribir: crear/editar/sincronizar tiers PxQ (el kill-switch
  PXQ_WRITE_ENABLED vive en la app; el permiso solo gatea el endpoint)

Backfill: a diferencia de `20260713_add_permisos_promociones.py`, que fija
una lista de roles hardcodeada, esta migración DERIVA los grants del estado
VIVO de `promos.escribir` al momento de correr — roles y overrides de
usuario, incluyendo los negativos (`concedido = false`), que se copian para
que un usuario explícitamente revocado de promos.escribir no reciba
pxq.escribir en silencio.

Esta migración es SQL autocontenido a propósito: NO importa código de la
app. Una migración es un snapshot histórico inmutable, y acoplarla a los
modelos ORM significa que el día que `Permiso` gane una columna NOT NULL sin
default, un `alembic upgrade` desde cero se rompe o cambia de comportamiento.
La lógica equivalente y testeada vive en
`app.services.pxq_permissions_backfill` para uso en runtime; acá el SQL
queda congelado.

Tampoco hace `commit()` propio: la transacción la maneja Alembic. Si una
migración posterior del mismo `upgrade head` falla, los grants tienen que
revertir con todo lo demás — un estado a medias en la tabla de permisos es
inaceptable en un camino de plata (`pxq.escribir` es crítico).

IMPORTANTE: el dry-run de conteo (roles / usuarios / overrides negativos)
debe correrse y registrarse ANTES de aplicar esta migración en cualquier
entorno real (ver `backend/scripts/pxq_permissions_dry_run.py`).

Revision ID: 20260801_pxq_permisos_backfill
Revises: 20260801_add_ml_pxq_tier
Create Date: 2026-08-01

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "20260801_pxq_permisos_backfill"
down_revision = "20260801_add_ml_pxq_tier"
branch_labels = None
depends_on = None


PERMISOS = (
    (
        "pxq.ver",
        "Ver precios mayoristas",
        "Ver los tramos de precio por cantidad (PxQ) de una publicación",
        "publicaciones",
        810,
        "false",
    ),
    (
        "pxq.escribir",
        "Editar precios mayoristas",
        "Crear, editar y sincronizar tramos de precio por cantidad (PxQ) con MercadoLibre",
        "publicaciones",
        811,
        "true",
    ),
)

CODIGOS = "'pxq.ver', 'pxq.escribir'"


def upgrade():
    for codigo, nombre, descripcion, categoria, orden, es_critico in PERMISOS:
        op.execute(f"""
            INSERT INTO permisos (codigo, nombre, descripcion, categoria, orden, es_critico, created_at)
            VALUES ('{codigo}', '{nombre}', '{descripcion}', '{categoria}', {orden}, {es_critico}, NOW())
            ON CONFLICT (codigo) DO NOTHING;
        """)

    # Grants de rol derivados del estado vivo de promos.escribir.
    op.execute(f"""
        INSERT INTO roles_permisos_base (rol_id, permiso_id)
        SELECT rpb.rol_id, nuevo.id
        FROM roles_permisos_base rpb
        JOIN permisos origen ON origen.id = rpb.permiso_id AND origen.codigo = 'promos.escribir'
        CROSS JOIN permisos nuevo
        WHERE nuevo.codigo IN ({CODIGOS})
          AND NOT EXISTS (
              SELECT 1 FROM roles_permisos_base existente
              WHERE existente.rol_id = rpb.rol_id AND existente.permiso_id = nuevo.id
          );
    """)

    # Overrides por usuario, incluidos los NEGATIVOS: `concedido` se copia tal
    # cual, así un usuario con promos.escribir revocado explícitamente queda
    # revocado también para PxQ en vez de heredarlo por el grant de su rol.
    op.execute(f"""
        INSERT INTO usuarios_permisos_override (usuario_id, permiso_id, concedido, otorgado_por_id, motivo, created_at)
        SELECT upo.usuario_id, nuevo.id, upo.concedido, upo.otorgado_por_id,
               'Backfill PxQ derivado de promos.escribir', NOW()
        FROM usuarios_permisos_override upo
        JOIN permisos origen ON origen.id = upo.permiso_id AND origen.codigo = 'promos.escribir'
        CROSS JOIN permisos nuevo
        WHERE nuevo.codigo IN ({CODIGOS})
          AND NOT EXISTS (
              SELECT 1 FROM usuarios_permisos_override existente
              WHERE existente.usuario_id = upo.usuario_id AND existente.permiso_id = nuevo.id
          );
    """)


def downgrade():
    op.execute(f"""
        DELETE FROM usuarios_permisos_override
        WHERE permiso_id IN (SELECT id FROM permisos WHERE codigo IN ({CODIGOS}));
    """)
    op.execute(f"""
        DELETE FROM roles_permisos_base
        WHERE permiso_id IN (SELECT id FROM permisos WHERE codigo IN ({CODIGOS}));
    """)
    op.execute(f"""
        DELETE FROM permisos WHERE codigo IN ({CODIGOS});
    """)
