"""Merge de heads: tn-publisher y tickets/vikunja

La rama integradora `feat/tn-publisher-module` agregó las tablas del
publicador de Tienda Nube mientras `main` avanzaba con triage de tickets y
la sincronización con Vikunja. Cada línea encadenó sus migraciones sobre el
head que veía, así que al juntarlas alembic queda con DOS heads y
`alembic upgrade head` falla — este repo ya tuvo ese incidente antes.

Esta migración no toca el esquema: solo vuelve a unir el grafo. El
`upgrade`/`downgrade` vacíos son deliberados.

Revision ID: 20260820_merge_tn_publisher_y_tickets
Revises: 20260820_fix_tn_category_profile_hint_nulls, 20260820_ticket_vikunja_sync
Create Date: 2026-08-20 00:00:00.000000

"""

revision = "20260820_merge_tn_publisher_y_tickets"
down_revision = (
    "20260820_fix_tn_category_profile_hint_nulls",
    "20260820_ticket_vikunja_sync",
)
branch_labels = None
depends_on = None


def upgrade():
    """Sin cambios de esquema: esta revisión existe solo para unir los heads."""


def downgrade():
    """Sin cambios de esquema que revertir."""
