"""Seed Inbox sector, Sin Clasificar tipo, and its workflow (tickets-ai-triage PR 3)

Single-box intake needs a Sector + TipoTicket + Workflow — with an initial and
a final EstadoTicket connected by a tickets_transiciones edge — to exist
BEFORE `crear_ticket` can accept a ticket with no explicit sector/tipo. With
no workflow row, `crear_ticket` 400s at `tickets.py:381-393` ("No hay
workflow configurado" / "no tiene estado inicial definido") before ever
reaching ticket creation — without this migration, PR 3's minimal `{texto}`
create path is dead on arrival.

`schema_campos={}` on the seeded TipoTicket is what makes the single-box
form require zero dynamic fields — any TipoTicket with a non-empty
`schema_campos` would force the advanced form open.

The seeded TipoTicket leaves `workflow_id` NULL, relying on the seeded
Workflow's `es_default=True` on the same sector — `crear_ticket` already
falls back to the sector's default workflow when a tipo has no workflow_id
of its own (`tickets.py:376-382`), so no extra FK is needed here.

downgrade() only deletes the seeded rows if no `tickets` row references the
seeded sector — silently orphaning `tickets.sector_id`/`tipo_ticket_id`
foreign keys on downgrade would be worse than refusing to run at all.

Revision ID: 20260805_seed_inbox
Revises: 20260805_propuestas_ia
Create Date: 2026-08-05
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "20260805_seed_inbox"
down_revision = "20260805_propuestas_ia"
branch_labels = None
depends_on = None

SECTOR_CODIGO = "INBOX"
TIPO_CODIGO = "SIN_CLASIFICAR"
ESTADO_INICIAL_CODIGO = "nuevo"
ESTADO_FINAL_CODIGO = "cerrado"


def upgrade() -> None:
    bind = op.get_bind()

    # Idempotency guard: a retried migration run must not crash on a
    # unique-violation. Checks the FULL seed shape (sector + default
    # workflow + tipo), not just the sector — a sector with this codigo but
    # a missing workflow/tipo means someone created it by hand, and this
    # migration must not silently pass while leaving crear_ticket's Inbox
    # defaults dead at runtime (400 with no signal, per obs #1305/#1334).
    existing_sector_id = bind.execute(
        sa.text("SELECT id FROM tickets_sectores WHERE codigo = :codigo"), {"codigo": SECTOR_CODIGO}
    ).scalar_one_or_none()
    if existing_sector_id is not None:
        has_default_workflow = bind.execute(
            sa.text("SELECT 1 FROM tickets_workflows WHERE sector_id = :sid AND es_default = true AND activo = true"),
            {"sid": existing_sector_id},
        ).scalar_one_or_none()
        has_tipo = bind.execute(
            sa.text("SELECT 1 FROM tickets_tipos WHERE sector_id = :sid AND codigo = :codigo"),
            {"sid": existing_sector_id, "codigo": TIPO_CODIGO},
        ).scalar_one_or_none()
        if has_default_workflow and has_tipo:
            return  # Full seed already present — this migration already ran.
        raise RuntimeError(
            f"Cannot seed Inbox: a sector with codigo='{SECTOR_CODIGO}' already exists "
            f"(id={existing_sector_id}) but is missing its default workflow and/or "
            f"'{TIPO_CODIGO}' tipo. Resolve the conflict by hand before re-running this "
            f"migration — completing it silently could leave crear_ticket's Inbox "
            f"defaults in an inconsistent state."
        )

    sectores = sa.table(
        "tickets_sectores",
        sa.column("id", sa.Integer),
        sa.column("codigo", sa.String),
        sa.column("nombre", sa.String),
        sa.column("activo", sa.Boolean),
        sa.column("configuracion", postgresql.JSONB),
    )
    sector_id = bind.execute(
        sectores.insert()
        .values(codigo=SECTOR_CODIGO, nombre="Bandeja de entrada", activo=True, configuracion={})
        .returning(sectores.c.id)
    ).scalar_one()

    workflows = sa.table(
        "tickets_workflows",
        sa.column("id", sa.Integer),
        sa.column("sector_id", sa.Integer),
        sa.column("nombre", sa.String),
        sa.column("es_default", sa.Boolean),
        sa.column("activo", sa.Boolean),
    )
    workflow_id = bind.execute(
        workflows.insert()
        .values(sector_id=sector_id, nombre="Bandeja de entrada", es_default=True, activo=True)
        .returning(workflows.c.id)
    ).scalar_one()

    tipos = sa.table(
        "tickets_tipos",
        sa.column("id", sa.Integer),
        sa.column("sector_id", sa.Integer),
        sa.column("codigo", sa.String),
        sa.column("nombre", sa.String),
        sa.column("schema_campos", postgresql.JSONB),
    )
    bind.execute(
        tipos.insert().values(sector_id=sector_id, codigo=TIPO_CODIGO, nombre="Sin clasificar", schema_campos={})
    )

    estados = sa.table(
        "tickets_estados",
        sa.column("id", sa.Integer),
        sa.column("workflow_id", sa.Integer),
        sa.column("codigo", sa.String),
        sa.column("nombre", sa.String),
        sa.column("orden", sa.Integer),
        sa.column("es_inicial", sa.Boolean),
        sa.column("es_final", sa.Boolean),
        sa.column("acciones_on_enter", postgresql.JSONB),
    )
    estado_inicial_id = bind.execute(
        estados.insert()
        .values(
            workflow_id=workflow_id,
            codigo=ESTADO_INICIAL_CODIGO,
            nombre="Nuevo",
            orden=1,
            es_inicial=True,
            es_final=False,
            acciones_on_enter=[],
        )
        .returning(estados.c.id)
    ).scalar_one()
    estado_final_id = bind.execute(
        estados.insert()
        .values(
            workflow_id=workflow_id,
            codigo=ESTADO_FINAL_CODIGO,
            nombre="Cerrado",
            orden=2,
            es_inicial=False,
            es_final=True,
            acciones_on_enter=[],
        )
        .returning(estados.c.id)
    ).scalar_one()

    transiciones = sa.table(
        "tickets_transiciones",
        sa.column("workflow_id", sa.Integer),
        sa.column("estado_origen_id", sa.Integer),
        sa.column("estado_destino_id", sa.Integer),
        sa.column("nombre", sa.String),
        sa.column("validaciones", postgresql.JSONB),
        sa.column("acciones", postgresql.JSONB),
    )
    bind.execute(
        transiciones.insert().values(
            workflow_id=workflow_id,
            estado_origen_id=estado_inicial_id,
            estado_destino_id=estado_final_id,
            nombre="Cerrar",
            validaciones=[],
            acciones=[],
        )
    )


def downgrade() -> None:
    bind = op.get_bind()

    sector_id = bind.execute(
        sa.text("SELECT id FROM tickets_sectores WHERE codigo = :codigo"), {"codigo": SECTOR_CODIGO}
    ).scalar_one_or_none()
    if sector_id is None:
        return

    referenced = bind.execute(
        sa.text("SELECT COUNT(*) FROM tickets WHERE sector_id = :sector_id"), {"sector_id": sector_id}
    ).scalar_one()
    if referenced:
        raise RuntimeError(
            f"Cannot downgrade 20260805_seed_inbox: {referenced} ticket(s) still reference the "
            f"seeded Inbox sector (id={sector_id}). Reassign or delete them first — silently "
            f"orphaning tickets.sector_id/tipo_ticket_id is worse than refusing to downgrade."
        )

    workflow_id = bind.execute(
        sa.text("SELECT id FROM tickets_workflows WHERE sector_id = :sector_id"), {"sector_id": sector_id}
    ).scalar_one_or_none()

    bind.execute(sa.text("DELETE FROM tickets_transiciones WHERE workflow_id = :wf"), {"wf": workflow_id})
    bind.execute(sa.text("DELETE FROM tickets_estados WHERE workflow_id = :wf"), {"wf": workflow_id})
    bind.execute(sa.text("DELETE FROM tickets_tipos WHERE sector_id = :sector_id"), {"sector_id": sector_id})
    bind.execute(sa.text("DELETE FROM tickets_workflows WHERE id = :wf"), {"wf": workflow_id})
    bind.execute(sa.text("DELETE FROM tickets_sectores WHERE id = :sector_id"), {"sector_id": sector_id})
