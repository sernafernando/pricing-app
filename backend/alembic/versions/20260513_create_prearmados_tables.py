"""Crear tablas prearmados + prearmados_seriales + secuencia codigo

Revision ID: 20260513_create_prearmados
Revises: 20260511_add_batch_id_envio
Create Date: 2026-05-13

"""

from alembic import op


revision = "20260513_create_prearmados"
down_revision = "20260511_add_batch_id_envio"
branch_labels = None
depends_on = None


def upgrade():
    # Secuencia para codigo legible (PRA-YYYY-NNNNNN)
    op.execute("CREATE SEQUENCE prearmados_codigo_seq START 1;")

    # Cabecera del prearmado
    op.execute("""
        CREATE TABLE prearmados (
            id SERIAL PRIMARY KEY,
            codigo VARCHAR(50) NOT NULL UNIQUE,
            comp_id INTEGER NOT NULL DEFAULT 1,
            bra_id INTEGER NOT NULL DEFAULT 1,
            combo_item_id INTEGER NOT NULL,
            combo_item_code VARCHAR(100) NOT NULL,
            combo_item_desc VARCHAR(500),
            incluye_windows VARCHAR(10)
                CHECK (incluye_windows IN ('home','pro') OR incluye_windows IS NULL),
            estado VARCHAR(20) NOT NULL DEFAULT 'pendiente'
                CHECK (estado IN ('pendiente','en_proceso','armado','consumido','anulado')),
            consumido_por_soh_id INTEGER,
            consumido_por_bra_id INTEGER,
            consumido_at TIMESTAMPTZ,
            created_by_user_id INTEGER NOT NULL REFERENCES usuarios(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            notas TEXT
        );
    """)

    op.execute("CREATE INDEX ix_prearmados_combo_item_id ON prearmados(combo_item_id);")
    op.execute("CREATE INDEX ix_prearmados_estado ON prearmados(estado);")
    op.execute("CREATE INDEX ix_prearmados_codigo ON prearmados(codigo);")
    op.execute("CREATE INDEX ix_prearmados_created_by_user_id ON prearmados(created_by_user_id);")
    op.execute("""
        CREATE INDEX ix_prearmados_consumido_por_soh_id
        ON prearmados(consumido_por_soh_id)
        WHERE consumido_por_soh_id IS NOT NULL;
    """)

    # Detalle: seriales cargados por componente
    op.execute("""
        CREATE TABLE prearmados_seriales (
            id SERIAL PRIMARY KEY,
            prearmado_id INTEGER NOT NULL REFERENCES prearmados(id) ON DELETE CASCADE,
            componente_item_id INTEGER NOT NULL,
            componente_item_code VARCHAR(100) NOT NULL,
            componente_item_desc VARCHAR(500),
            serial VARCHAR(255),
            is_id INTEGER,
            cantidad_esperada INTEGER NOT NULL DEFAULT 1,
            requiere_serie BOOLEAN NOT NULL DEFAULT true,
            validado BOOLEAN NOT NULL DEFAULT false,
            validado_at TIMESTAMPTZ,
            origen VARCHAR(20) NOT NULL DEFAULT 'bom'
                CHECK (origen IN ('bom','sufijo')),
            sufijo VARCHAR(10),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)

    op.execute("CREATE INDEX ix_pre_ser_prearmado_id ON prearmados_seriales(prearmado_id);")
    op.execute("CREATE INDEX ix_pre_ser_componente_item_id ON prearmados_seriales(componente_item_id);")
    op.execute("""
        CREATE INDEX ix_pre_ser_is_id
        ON prearmados_seriales(is_id)
        WHERE is_id IS NOT NULL;
    """)
    op.execute("""
        CREATE INDEX ix_pre_ser_serial_upper
        ON prearmados_seriales (UPPER(serial))
        WHERE serial IS NOT NULL;
    """)


def downgrade():
    op.execute("DROP TABLE IF EXISTS prearmados_seriales;")
    op.execute("DROP TABLE IF EXISTS prearmados;")
    op.execute("DROP SEQUENCE IF EXISTS prearmados_codigo_seq;")
