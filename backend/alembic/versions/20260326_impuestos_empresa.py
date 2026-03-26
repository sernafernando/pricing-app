"""Create impuestos_empresa table with seed data.

Revision ID: e6c2d4f5a930
Revises: d5b1c3e4f820
Create Date: 2026-03-26
"""

from alembic import op
import sqlalchemy as sa

revision = "e6c2d4f5a930"
down_revision = "d5b1c3e4f820"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "impuestos_empresa",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("nombre", sa.String(255), nullable=False),
        sa.Column("tipo", sa.String(50), nullable=False),
        sa.Column("codigo_afip", sa.Integer(), nullable=True),
        sa.Column("alicuota", sa.Numeric(8, 4), nullable=False),
        sa.Column("aplica_a", sa.String(20), nullable=False, server_default="ambos"),
        sa.Column("notas", sa.Text(), nullable=True),
        sa.Column("activo", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_impuestos_empresa_id", "impuestos_empresa", ["id"])
    op.create_index("ix_impuestos_empresa_tipo", "impuestos_empresa", ["tipo"])

    # ── Seed: impuestos más comunes ───────────────────────────────
    op.execute("""
        INSERT INTO impuestos_empresa (nombre, tipo, codigo_afip, alicuota, aplica_a) VALUES
        -- IVA
        ('IVA 21%',          'iva', 5,    21.0000, 'ambos'),
        ('IVA 10.5%',        'iva', 4,    10.5000, 'ambos'),
        ('IVA 27%',          'iva', 6,    27.0000, 'ambos'),
        ('IVA 5%',           'iva', 8,     5.0000, 'ambos'),
        ('IVA 2.5%',         'iva', 9,     2.5000, 'ambos'),
        ('IVA Exento',       'iva', 3,     0.0000, 'ambos'),
        ('IVA No Gravado',   'iva', 2,     0.0000, 'ambos'),

        -- Retenciones
        ('Ret. Ganancias (general)',       'retencion', 217,   2.0000, 'compras'),
        ('Ret. Ganancias (honorarios)',    'retencion', 217,  10.0000, 'compras'),
        ('Ret. Ganancias (alquileres)',    'retencion', 217,   6.0000, 'compras'),
        ('Ret. IVA',                       'retencion', 218,  50.0000, 'compras'),
        ('Ret. IIBB CABA',                'retencion', NULL,   3.0000, 'compras'),
        ('Ret. IIBB Prov. Buenos Aires',  'retencion', NULL,   2.5000, 'compras'),
        ('Ret. SUSS',                      'retencion', 353,  11.0000, 'compras'),

        -- Percepciones
        ('Perc. IVA',                      'percepcion', 767,   3.0000, 'compras'),
        ('Perc. IIBB CABA',               'percepcion', NULL,   3.0000, 'compras'),
        ('Perc. IIBB Prov. Buenos Aires', 'percepcion', NULL,   3.0000, 'compras'),

        -- Otros
        ('Impuesto Interno',               'otro', NULL,   0.0000, 'ambos'),
        ('Imp. Débitos y Créditos',        'otro', NULL,   0.6000, 'ambos')
    """)


def downgrade() -> None:
    op.drop_index("ix_impuestos_empresa_tipo", table_name="impuestos_empresa")
    op.drop_index("ix_impuestos_empresa_id", table_name="impuestos_empresa")
    op.drop_table("impuestos_empresa")
