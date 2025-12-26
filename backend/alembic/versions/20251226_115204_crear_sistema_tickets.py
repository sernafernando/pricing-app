"""crear sistema tickets

Revision ID: 20251226_tickets_01
Revises: 20251223_100905
Create Date: 2025-12-26

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision = '20251226_tickets_01'
down_revision = '20251223_100905'
branch_labels = None
depends_on = None


def upgrade():
    # ========================================
    # 1. Crear tabla tickets_sectores
    # ========================================
    op.create_table(
        'tickets_sectores',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('codigo', sa.String(50), nullable=False),
        sa.Column('nombre', sa.String(100), nullable=False),
        sa.Column('descripcion', sa.Text(), nullable=True),
        sa.Column('icono', sa.String(50), nullable=True),
        sa.Column('color', sa.String(20), nullable=True),
        sa.Column('activo', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('configuracion', JSONB, nullable=False, server_default='{}'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_tickets_sectores_id'), 'tickets_sectores', ['id'], unique=False)
    op.create_index(op.f('ix_tickets_sectores_codigo'), 'tickets_sectores', ['codigo'], unique=True)

    # ========================================
    # 2. Crear tabla tickets_workflows
    # ========================================
    op.create_table(
        'tickets_workflows',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('sector_id', sa.Integer(), nullable=False),
        sa.Column('nombre', sa.String(100), nullable=False),
        sa.Column('descripcion', sa.Text(), nullable=True),
        sa.Column('es_default', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('activo', sa.Boolean(), nullable=False, server_default='true'),
        sa.ForeignKeyConstraint(['sector_id'], ['tickets_sectores.id'], name='fk_workflows_sector_id'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_tickets_workflows_id'), 'tickets_workflows', ['id'], unique=False)
    op.create_index(op.f('ix_tickets_workflows_sector_id'), 'tickets_workflows', ['sector_id'], unique=False)

    # ========================================
    # 3. Crear tabla tickets_estados
    # ========================================
    op.create_table(
        'tickets_estados',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('workflow_id', sa.Integer(), nullable=False),
        sa.Column('codigo', sa.String(50), nullable=False),
        sa.Column('nombre', sa.String(100), nullable=False),
        sa.Column('descripcion', sa.Text(), nullable=True),
        sa.Column('orden', sa.Integer(), nullable=False),
        sa.Column('color', sa.String(20), nullable=True),
        sa.Column('es_inicial', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('es_final', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('acciones_on_enter', JSONB, nullable=False, server_default='[]'),
        sa.ForeignKeyConstraint(['workflow_id'], ['tickets_workflows.id'], name='fk_estados_workflow_id', ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_tickets_estados_id'), 'tickets_estados', ['id'], unique=False)
    op.create_index(op.f('ix_tickets_estados_workflow_id'), 'tickets_estados', ['workflow_id'], unique=False)

    # ========================================
    # 4. Crear tabla tickets_transiciones
    # ========================================
    op.create_table(
        'tickets_transiciones',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('workflow_id', sa.Integer(), nullable=False),
        sa.Column('estado_origen_id', sa.Integer(), nullable=False),
        sa.Column('estado_destino_id', sa.Integer(), nullable=False),
        sa.Column('nombre', sa.String(100), nullable=True),
        sa.Column('descripcion', sa.Text(), nullable=True),
        sa.Column('requiere_permiso', sa.String(100), nullable=True),
        sa.Column('solo_asignado', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('solo_creador', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('validaciones', JSONB, nullable=False, server_default='[]'),
        sa.Column('acciones', JSONB, nullable=False, server_default='[]'),
        sa.ForeignKeyConstraint(['workflow_id'], ['tickets_workflows.id'], name='fk_transiciones_workflow_id', ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['estado_origen_id'], ['tickets_estados.id'], name='fk_transiciones_estado_origen_id'),
        sa.ForeignKeyConstraint(['estado_destino_id'], ['tickets_estados.id'], name='fk_transiciones_estado_destino_id'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_tickets_transiciones_id'), 'tickets_transiciones', ['id'], unique=False)
    op.create_index(op.f('ix_tickets_transiciones_workflow_id'), 'tickets_transiciones', ['workflow_id'], unique=False)

    # ========================================
    # 5. Crear tabla tickets_tipos
    # ========================================
    op.create_table(
        'tickets_tipos',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('sector_id', sa.Integer(), nullable=False),
        sa.Column('workflow_id', sa.Integer(), nullable=True),
        sa.Column('codigo', sa.String(50), nullable=False),
        sa.Column('nombre', sa.String(100), nullable=False),
        sa.Column('descripcion', sa.Text(), nullable=True),
        sa.Column('icono', sa.String(50), nullable=True),
        sa.Column('color', sa.String(20), nullable=True),
        sa.Column('schema_campos', JSONB, nullable=False, server_default='{}'),
        sa.ForeignKeyConstraint(['sector_id'], ['tickets_sectores.id'], name='fk_tipos_sector_id'),
        sa.ForeignKeyConstraint(['workflow_id'], ['tickets_workflows.id'], name='fk_tipos_workflow_id'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_tickets_tipos_id'), 'tickets_tipos', ['id'], unique=False)
    op.create_index(op.f('ix_tickets_tipos_sector_id'), 'tickets_tipos', ['sector_id'], unique=False)

    # ========================================
    # 6. Crear tabla tickets
    # ========================================
    op.create_table(
        'tickets',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('titulo', sa.String(255), nullable=False),
        sa.Column('descripcion', sa.Text(), nullable=True),
        sa.Column('prioridad', sa.Enum('baja', 'media', 'alta', 'critica', name='prioridadticket'), nullable=False, server_default='media'),
        sa.Column('sector_id', sa.Integer(), nullable=False),
        sa.Column('tipo_ticket_id', sa.Integer(), nullable=False),
        sa.Column('estado_id', sa.Integer(), nullable=False),
        sa.Column('creador_id', sa.Integer(), nullable=False),
        sa.Column('metadata', JSONB, nullable=False, server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['sector_id'], ['tickets_sectores.id'], name='fk_tickets_sector_id'),
        sa.ForeignKeyConstraint(['tipo_ticket_id'], ['tickets_tipos.id'], name='fk_tickets_tipo_ticket_id'),
        sa.ForeignKeyConstraint(['estado_id'], ['tickets_estados.id'], name='fk_tickets_estado_id'),
        sa.ForeignKeyConstraint(['creador_id'], ['usuarios.id'], name='fk_tickets_creador_id'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_tickets_id'), 'tickets', ['id'], unique=False)
    op.create_index(op.f('ix_tickets_sector_id'), 'tickets', ['sector_id'], unique=False)
    op.create_index(op.f('ix_tickets_estado_id'), 'tickets', ['estado_id'], unique=False)
    op.create_index(op.f('ix_tickets_creador_id'), 'tickets', ['creador_id'], unique=False)
    op.create_index(op.f('ix_tickets_created_at'), 'tickets', ['created_at'], unique=False)

    # ========================================
    # 7. Crear tabla tickets_asignaciones
    # ========================================
    op.create_table(
        'tickets_asignaciones',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('ticket_id', sa.Integer(), nullable=False),
        sa.Column('asignado_a_id', sa.Integer(), nullable=False),
        sa.Column('asignado_por_id', sa.Integer(), nullable=True),
        sa.Column('tipo', sa.Enum('manual', 'automatico', 'reasignacion', 'escalamiento', name='tipoasignacion'), nullable=False),
        sa.Column('motivo', sa.String(500), nullable=True),
        sa.Column('fecha_asignacion', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('fecha_finalizacion', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['ticket_id'], ['tickets.id'], name='fk_asignaciones_ticket_id', ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['asignado_a_id'], ['usuarios.id'], name='fk_asignaciones_asignado_a_id'),
        sa.ForeignKeyConstraint(['asignado_por_id'], ['usuarios.id'], name='fk_asignaciones_asignado_por_id'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_tickets_asignaciones_id'), 'tickets_asignaciones', ['id'], unique=False)
    op.create_index(op.f('ix_tickets_asignaciones_ticket_id'), 'tickets_asignaciones', ['ticket_id'], unique=False)
    op.create_index(op.f('ix_tickets_asignaciones_asignado_a_id'), 'tickets_asignaciones', ['asignado_a_id'], unique=False)

    # ========================================
    # 8. Crear tabla tickets_historial
    # ========================================
    op.create_table(
        'tickets_historial',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('ticket_id', sa.Integer(), nullable=False),
        sa.Column('usuario_id', sa.Integer(), nullable=True),
        sa.Column('accion', sa.String(100), nullable=False),
        sa.Column('descripcion', sa.Text(), nullable=True),
        sa.Column('estado_anterior_id', sa.Integer(), nullable=True),
        sa.Column('estado_nuevo_id', sa.Integer(), nullable=True),
        sa.Column('cambios', JSONB, nullable=False, server_default='{}'),
        sa.Column('fecha', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['ticket_id'], ['tickets.id'], name='fk_historial_ticket_id', ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['usuario_id'], ['usuarios.id'], name='fk_historial_usuario_id'),
        sa.ForeignKeyConstraint(['estado_anterior_id'], ['tickets_estados.id'], name='fk_historial_estado_anterior_id'),
        sa.ForeignKeyConstraint(['estado_nuevo_id'], ['tickets_estados.id'], name='fk_historial_estado_nuevo_id'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_tickets_historial_id'), 'tickets_historial', ['id'], unique=False)
    op.create_index(op.f('ix_tickets_historial_ticket_id'), 'tickets_historial', ['ticket_id'], unique=False)
    op.create_index(op.f('ix_tickets_historial_fecha'), 'tickets_historial', ['fecha'], unique=False)

    # ========================================
    # 9. Crear tabla tickets_comentarios
    # ========================================
    op.create_table(
        'tickets_comentarios',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('ticket_id', sa.Integer(), nullable=False),
        sa.Column('usuario_id', sa.Integer(), nullable=False),
        sa.Column('contenido', sa.Text(), nullable=False),
        sa.Column('es_interno', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['ticket_id'], ['tickets.id'], name='fk_comentarios_ticket_id', ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['usuario_id'], ['usuarios.id'], name='fk_comentarios_usuario_id'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_tickets_comentarios_id'), 'tickets_comentarios', ['id'], unique=False)
    op.create_index(op.f('ix_tickets_comentarios_ticket_id'), 'tickets_comentarios', ['ticket_id'], unique=False)
    op.create_index(op.f('ix_tickets_comentarios_created_at'), 'tickets_comentarios', ['created_at'], unique=False)


def downgrade():
    # Eliminar en orden inverso debido a las foreign keys
    op.drop_index(op.f('ix_tickets_comentarios_created_at'), table_name='tickets_comentarios')
    op.drop_index(op.f('ix_tickets_comentarios_ticket_id'), table_name='tickets_comentarios')
    op.drop_index(op.f('ix_tickets_comentarios_id'), table_name='tickets_comentarios')
    op.drop_table('tickets_comentarios')

    op.drop_index(op.f('ix_tickets_historial_fecha'), table_name='tickets_historial')
    op.drop_index(op.f('ix_tickets_historial_ticket_id'), table_name='tickets_historial')
    op.drop_index(op.f('ix_tickets_historial_id'), table_name='tickets_historial')
    op.drop_table('tickets_historial')

    op.drop_index(op.f('ix_tickets_asignaciones_asignado_a_id'), table_name='tickets_asignaciones')
    op.drop_index(op.f('ix_tickets_asignaciones_ticket_id'), table_name='tickets_asignaciones')
    op.drop_index(op.f('ix_tickets_asignaciones_id'), table_name='tickets_asignaciones')
    op.drop_table('tickets_asignaciones')

    op.drop_index(op.f('ix_tickets_created_at'), table_name='tickets')
    op.drop_index(op.f('ix_tickets_creador_id'), table_name='tickets')
    op.drop_index(op.f('ix_tickets_estado_id'), table_name='tickets')
    op.drop_index(op.f('ix_tickets_sector_id'), table_name='tickets')
    op.drop_index(op.f('ix_tickets_id'), table_name='tickets')
    op.drop_table('tickets')
    op.execute('DROP TYPE prioridadticket')
    op.execute('DROP TYPE tipoasignacion')

    op.drop_index(op.f('ix_tickets_tipos_sector_id'), table_name='tickets_tipos')
    op.drop_index(op.f('ix_tickets_tipos_id'), table_name='tickets_tipos')
    op.drop_table('tickets_tipos')

    op.drop_index(op.f('ix_tickets_transiciones_workflow_id'), table_name='tickets_transiciones')
    op.drop_index(op.f('ix_tickets_transiciones_id'), table_name='tickets_transiciones')
    op.drop_table('tickets_transiciones')

    op.drop_index(op.f('ix_tickets_estados_workflow_id'), table_name='tickets_estados')
    op.drop_index(op.f('ix_tickets_estados_id'), table_name='tickets_estados')
    op.drop_table('tickets_estados')

    op.drop_index(op.f('ix_tickets_workflows_sector_id'), table_name='tickets_workflows')
    op.drop_index(op.f('ix_tickets_workflows_id'), table_name='tickets_workflows')
    op.drop_table('tickets_workflows')

    op.drop_index(op.f('ix_tickets_sectores_codigo'), table_name='tickets_sectores')
    op.drop_index(op.f('ix_tickets_sectores_id'), table_name='tickets_sectores')
    op.drop_table('tickets_sectores')
