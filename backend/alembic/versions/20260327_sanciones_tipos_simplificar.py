"""Simplificar tipos de sanción: 3 tipos base, dias_suspension ya no se usa en tipo

Los días de suspensión se calculan de fecha_desde/fecha_hasta en la sanción.
Se reemplaza el campo requiere_descuento por un default más genérico.

Revision ID: 20260327_sanciones_tipos
Revises: a8b4c6d7e152
Create Date: 2026-03-27
"""

from alembic import op

revision = "20260327_sanciones_tipos"
down_revision = "a8b4c6d7e152"
branch_labels = None
depends_on = None


def upgrade():
    # Limpiar tipos anteriores y reemplazar con los 3 correctos
    op.execute("""
        UPDATE rrhh_tipo_sancion SET activo = false
        WHERE nombre NOT IN ('Apercibimiento', 'Apercibimiento severo', 'Sanción');
    """)
    op.execute("""
        INSERT INTO rrhh_tipo_sancion (nombre, descripcion, dias_suspension, requiere_descuento, orden)
        VALUES
            ('Apercibimiento', 'Llamado de atención formal documentado', NULL, false, 1),
            ('Apercibimiento severo', 'Llamado de atención grave documentado', NULL, false, 2),
            ('Sanción', 'Sanción disciplinaria con posible suspensión', NULL, true, 3)
        ON CONFLICT (nombre) DO UPDATE SET
            descripcion = EXCLUDED.descripcion,
            dias_suspension = NULL,
            requiere_descuento = EXCLUDED.requiere_descuento,
            orden = EXCLUDED.orden,
            activo = true;
    """)
    # Limpiar dias_suspension de todos los tipos (ya no se usa a nivel tipo)
    op.execute("UPDATE rrhh_tipo_sancion SET dias_suspension = NULL;")


def downgrade():
    # Restaurar los 5 tipos originales
    op.execute("""
        UPDATE rrhh_tipo_sancion SET activo = true;
    """)
    op.execute("""
        UPDATE rrhh_tipo_sancion SET dias_suspension = 1 WHERE nombre = 'Suspensión 1 día';
        UPDATE rrhh_tipo_sancion SET dias_suspension = 3 WHERE nombre = 'Suspensión 3 días';
        UPDATE rrhh_tipo_sancion SET dias_suspension = 5 WHERE nombre = 'Suspensión 5 días';
    """)
