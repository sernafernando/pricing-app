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

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20260801_pxq_permisos_backfill"
down_revision = "20260801_add_ml_pxq_tier"
branch_labels = None
depends_on = None


# Estos valores DEBEN coincidir con `_CATALOG` en
# `app/services/pxq_permissions_backfill.py`. La migración no puede importar
# ese módulo (ver arriba), así que la equivalencia la fuerza un test:
# `test_migration_catalog_matches_the_service_catalog`. Si divergen, el
# dry-run —que corre el servicio— deja de describir lo que escribe la
# migración, y ese conteo es el gate previo al deploy.
# La categoría propia y el orden contiguo siguen el precedente de
# `20260713_add_permisos_promociones.py` ("promos", 44/45).
PERMISOS = (
    (
        "pxq.ver",
        "Ver tiers PxQ ML",
        "Ver tiers de precio por cantidad (mayorista) ML",
        "pxq",
        50,
        "false",
    ),
    (
        "pxq.escribir",
        "Editar/sincronizar tiers PxQ ML",
        "Crear/editar/sincronizar tiers de precio por cantidad (mayorista) ML",
        "pxq",
        51,
        "true",
    ),
)

CODIGOS = tuple(row[0] for row in PERMISOS)
PROMOS_ESCRIBIR = "promos.escribir"
PXQ_ESCRIBIR = "pxq.escribir"


# Los statements viven a nivel de módulo para que un test pueda EJECUTARLOS,
# no solo leerlos. La paridad migración/servicio se sostenía con
# `assert "substring" in source`, que es frágil por construcción: renombrar un
# bindparam la rompe por la razón equivocada, y cambiar `= FALSE` por
# `IS FALSE` la deja pasar habiendo cambiado la semántica ante NULL. Lo que
# corre en el deploy es este SQL, así que es esto lo que hay que testear.
#
# CURRENT_TIMESTAMP en vez de NOW() para que sea neutro de dialecto y el test
# pueda correrlo sobre el SQLite de la suite.
SQL_INSERT_PERMISO = """
    INSERT INTO permisos (codigo, nombre, descripcion, categoria, orden, es_critico, created_at)
    VALUES (:codigo, :nombre, :descripcion, :categoria, :orden, :es_critico, CURRENT_TIMESTAMP)
    ON CONFLICT (codigo) DO NOTHING
"""

SQL_ROLE_GRANTS = """
    INSERT INTO roles_permisos_base (rol_id, permiso_id)
    SELECT rpb.rol_id, nuevo.id
    FROM roles_permisos_base rpb
    JOIN permisos origen ON origen.id = rpb.permiso_id AND origen.codigo = :promos
    CROSS JOIN permisos nuevo
    WHERE nuevo.codigo IN :codigos
      AND NOT EXISTS (
          SELECT 1 FROM roles_permisos_base existente
          WHERE existente.rol_id = rpb.rol_id AND existente.permiso_id = nuevo.id
      )
"""

# Overrides POSITIVOS: a ambos códigos, igual que el grant de rol.
# `otorgado_por_id` queda NULL a propósito: quien concedió promos.escribir no
# concedió esto, y atribuírselo falsea la auditoría del camino de plata.
SQL_POSITIVE_OVERRIDES = """
    INSERT INTO usuarios_permisos_override
        (usuario_id, permiso_id, concedido, otorgado_por_id, motivo, created_at)
    SELECT upo.usuario_id, nuevo.id, TRUE, NULL, :motivo, CURRENT_TIMESTAMP
    FROM usuarios_permisos_override upo
    JOIN permisos origen ON origen.id = upo.permiso_id AND origen.codigo = :promos
    CROSS JOIN permisos nuevo
    WHERE upo.concedido = TRUE
      AND nuevo.codigo IN :codigos
      AND NOT EXISTS (
          SELECT 1 FROM usuarios_permisos_override existente
          WHERE existente.usuario_id = upo.usuario_id AND existente.permiso_id = nuevo.id
      )
"""

# Overrides NEGATIVOS: SOLO a `pxq.escribir`. Una revocación de
# promos.escribir habla de ESCRIBIR; copiarla también a `pxq.ver` dejaría a esa
# persona sin poder siquiera MIRAR los tramos, que no es lo que nadie decidió.
SQL_NEGATIVE_OVERRIDES = """
    INSERT INTO usuarios_permisos_override
        (usuario_id, permiso_id, concedido, otorgado_por_id, motivo, created_at)
    SELECT upo.usuario_id, nuevo.id, FALSE, NULL, :motivo, CURRENT_TIMESTAMP
    FROM usuarios_permisos_override upo
    JOIN permisos origen ON origen.id = upo.permiso_id AND origen.codigo = :promos
    CROSS JOIN permisos nuevo
    WHERE upo.concedido = FALSE
      AND nuevo.codigo = :pxq_escribir
      AND NOT EXISTS (
          SELECT 1 FROM usuarios_permisos_override existente
          WHERE existente.usuario_id = upo.usuario_id AND existente.permiso_id = nuevo.id
      )
"""

MOTIVO_POSITIVO = "Backfill PxQ derivado de promos.escribir"
MOTIVO_NEGATIVO = "Backfill PxQ: revocación heredada de promos.escribir"


def apply_backfill(bind) -> None:
    """Ejecuta el backfill completo. Recibe el bind para que `upgrade()` le
    pase el de Alembic y el test le pase el de la sesión de pruebas."""
    for codigo, nombre, descripcion, categoria, orden, es_critico in PERMISOS:
        bind.execute(
            sa.text(SQL_INSERT_PERMISO),
            {
                "codigo": codigo,
                "nombre": nombre,
                "descripcion": descripcion,
                "categoria": categoria,
                "orden": orden,
                "es_critico": es_critico == "true",
            },
        )

    bind.execute(
        sa.text(SQL_ROLE_GRANTS).bindparams(sa.bindparam("codigos", expanding=True)),
        {"promos": PROMOS_ESCRIBIR, "codigos": list(CODIGOS)},
    )
    bind.execute(
        sa.text(SQL_POSITIVE_OVERRIDES).bindparams(sa.bindparam("codigos", expanding=True)),
        {"promos": PROMOS_ESCRIBIR, "codigos": list(CODIGOS), "motivo": MOTIVO_POSITIVO},
    )
    bind.execute(
        sa.text(SQL_NEGATIVE_OVERRIDES),
        {"promos": PROMOS_ESCRIBIR, "pxq_escribir": PXQ_ESCRIBIR, "motivo": MOTIVO_NEGATIVO},
    )


def upgrade():
    apply_backfill(op.get_bind())


def downgrade():
    bind = op.get_bind()
    for table in ("usuarios_permisos_override", "roles_permisos_base"):
        bind.execute(
            sa.text(f"""
                DELETE FROM {table}
                WHERE permiso_id IN (SELECT id FROM permisos WHERE codigo IN :codigos)
            """).bindparams(sa.bindparam("codigos", expanding=True)),
            {"codigos": list(CODIGOS)},
        )
    bind.execute(
        sa.text("DELETE FROM permisos WHERE codigo IN :codigos").bindparams(sa.bindparam("codigos", expanding=True)),
        {"codigos": list(CODIGOS)},
    )
