"""Add jurisdiccion, alicuota_no_inscripto, minimos to impuestos_empresa.
Seed percepciones IIBB por jurisdiccion.

Revision ID: a8b4c6d7e152
Revises: f7d3e5a6b041
Create Date: 2026-03-26
"""

from alembic import op
import sqlalchemy as sa

revision = "a8b4c6d7e152"
down_revision = "f7d3e5a6b041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. Agregar columnas nuevas ────────────────────────────────
    op.add_column("impuestos_empresa", sa.Column("alicuota_no_inscripto", sa.Numeric(8, 4), nullable=True))
    op.add_column("impuestos_empresa", sa.Column("alicuota_convenio", sa.Numeric(8, 4), nullable=True))
    op.add_column("impuestos_empresa", sa.Column("segun_padron", sa.Boolean(), server_default="false", nullable=False))
    op.add_column("impuestos_empresa", sa.Column("jurisdiccion", sa.String(100), nullable=True))
    op.add_column("impuestos_empresa", sa.Column("base_imponible_minima", sa.Numeric(18, 2), nullable=True))
    op.add_column("impuestos_empresa", sa.Column("percepcion_minima", sa.Numeric(18, 2), nullable=True))
    op.add_column("impuestos_empresa", sa.Column("minimo_incluye_iva", sa.Boolean(), server_default="false", nullable=False))

    op.create_index("ix_impuestos_empresa_jurisdiccion", "impuestos_empresa", ["jurisdiccion"])

    # ── 2. Actualizar percepciones IIBB existentes (genéricas) ────
    # Borrar las genéricas que seedeamos antes, reemplazar por jurisdiccionales
    op.execute("DELETE FROM impuestos_empresa WHERE nombre LIKE 'Perc. IIBB%'")

    # ── 3. Seed percepciones IIBB por jurisdicción ────────────────
    op.execute("""
        INSERT INTO impuestos_empresa
            (nombre, tipo, alicuota, alicuota_no_inscripto, alicuota_convenio,
             segun_padron, jurisdiccion, base_imponible_minima, percepcion_minima,
             minimo_incluye_iva, aplica_a)
        VALUES
        ('Perc. IIBB Buenos Aires',   'percepcion', 0,     8.0000, 0,      true,  'Buenos Aires',   3500,   NULL, true,  'compras'),
        ('Perc. IIBB CABA',           'percepcion', 0,     6.0000, 0,      true,  'CABA',           3000,   NULL, true,  'compras'),
        ('Perc. IIBB Catamarca',      'percepcion', 2.5,   2.5000, 2.5,    false, 'Catamarca',      NULL,   NULL, false, 'compras'),
        ('Perc. IIBB Corrientes',     'percepcion', 1.5,   2.2500, 0.75,   false, 'Corrientes',     80000,  NULL, true,  'compras'),
        ('Perc. IIBB Entre Ríos',     'percepcion', 0,     6.0000, 0,      true,  'Entre Ríos',     NULL,   NULL, false, 'compras'),
        ('Perc. IIBB Jujuy',          'percepcion', 0,     6.0000, 0,      true,  'Jujuy',          NULL,   NULL, false, 'compras'),
        ('Perc. IIBB Misiones',       'percepcion', 3.31,  3.3100, 3.31,   false, 'Misiones',       NULL,   14000, false, 'compras'),
        ('Perc. IIBB Neuquén',        'percepcion', 2.0,   4.0000, 0,      false, 'Neuquén',        8000,   NULL, true,  'compras'),
        ('Perc. IIBB Salta',          'percepcion', 3.6,   10.800, 3.6,    false, 'Salta',          NULL,   NULL, false, 'compras'),
        ('Perc. IIBB San Juan',       'percepcion', 3.0,   3.0000, 1.0,    false, 'San Juan',       NULL,   NULL, false, 'compras'),
        ('Perc. IIBB San Luis',       'percepcion', 2.0,   4.0000, 2.0,    false, 'San Luis',       100000, NULL, true,  'compras'),
        ('Perc. IIBB Tucumán',        'percepcion', 0,     7.0000, 0,      true,  'Tucumán',        NULL,   200,  false, 'compras')
    """)

    # ── 4. Actualizar retenciones IIBB existentes con jurisdicción ─
    op.execute("UPDATE impuestos_empresa SET jurisdiccion = 'CABA' WHERE nombre = 'Ret. IIBB CABA'")
    op.execute("UPDATE impuestos_empresa SET jurisdiccion = 'Buenos Aires' WHERE nombre = 'Ret. IIBB Prov. Buenos Aires'")


def downgrade() -> None:
    op.drop_index("ix_impuestos_empresa_jurisdiccion", table_name="impuestos_empresa")
    op.drop_column("impuestos_empresa", "minimo_incluye_iva")
    op.drop_column("impuestos_empresa", "percepcion_minima")
    op.drop_column("impuestos_empresa", "base_imponible_minima")
    op.drop_column("impuestos_empresa", "jurisdiccion")
    op.drop_column("impuestos_empresa", "segun_padron")
    op.drop_column("impuestos_empresa", "alicuota_convenio")
    op.drop_column("impuestos_empresa", "alicuota_no_inscripto")

    # Re-seed las percepciones genéricas originales
    op.execute("""
        INSERT INTO impuestos_empresa (nombre, tipo, alicuota, aplica_a) VALUES
        ('Perc. IVA', 'percepcion', 3.0000, 'compras'),
        ('Perc. IIBB CABA', 'percepcion', 3.0000, 'compras'),
        ('Perc. IIBB Prov. Buenos Aires', 'percepcion', 3.0000, 'compras')
    """)
