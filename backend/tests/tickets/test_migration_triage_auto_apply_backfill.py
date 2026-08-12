"""Tests for the `20260812_triage_auto_apply_backfill` DATA migration
(feat/tickets-triage-aplicar-directo): applies pending AI-triage proposals
directly onto their tickets (severidad/urgencia/resumen/titulo), and its
`downgrade()` reverts precisely the values it (or the ordinary auto-apply
write path) marked `ia_auto` — never a human-set value, even one that
coexists on the SAME ticket as an AI one.

Runs the real `upgrade()`/`downgrade()` functions against Postgres
(`pg_tickets_db`'s tables + connection) via Alembic's `Operations` proxy —
mirrors `test_migration_ml_bot_messages_bot_columns.py`'s pattern, adapted
to Postgres because the migration's raw SQL (`UPDATE ... FROM`, JSONB
`->>`) is Postgres-only, same reason `pg_tickets_db` itself exists.

Run:
    cd backend && source venv/bin/activate
    pytest tests/tickets/test_migration_triage_auto_apply_backfill.py -v -m postgres
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from app.models.rol import Rol
from app.models.usuario import AuthProvider, RolUsuario, Usuario
from app.tickets.models.propuesta_ia import PropuestaIA
from app.tickets.models.sector import Sector
from app.tickets.models.ticket import PrioridadTicket, Ticket
from app.tickets.models.tipo_ticket import TipoTicket
from app.tickets.models.workflow import EstadoTicket, Workflow

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_REVISION = "20260812_triage_auto_apply"

_seq = [0]


def _load_migration():
    path = _BACKEND_ROOT / "alembic" / "versions" / f"{_REVISION}.py"
    spec = importlib.util.spec_from_file_location("triage_auto_apply_backfill_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_migration_fn(db, fn) -> None:
    """Runs a migration's `upgrade`/`downgrade` (which call `op.get_bind()`
    internally) against `db`'s own connection — same transaction, so the
    session's own fixture writes and the migration's raw SQL see each
    other without a separate commit."""
    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext

    ctx = MigrationContext.configure(db.connection())
    op_obj = Operations(ctx)
    op_obj._install_proxy()
    try:
        fn()
    finally:
        op_obj._remove_proxy()


def _make_rol(db) -> Rol:
    rol = Rol(codigo="VENTAS", nombre="Ventas", es_sistema=False, orden=10, activo=True)
    db.add(rol)
    db.flush()
    return rol


def _make_sector_tipo_estado(db) -> tuple[Sector, TipoTicket, EstadoTicket]:
    _seq[0] += 1
    sector = Sector(codigo=f"MIGR_BACKFILL_{_seq[0]}", nombre="Sector Migracion", activo=True, configuracion={})
    db.add(sector)
    db.flush()
    workflow = Workflow(sector_id=sector.id, nombre="WF Migracion", es_default=True, activo=True)
    db.add(workflow)
    db.flush()
    estado = EstadoTicket(
        workflow_id=workflow.id, codigo="abierto", nombre="Abierto", orden=1, es_inicial=True, es_final=False
    )
    db.add(estado)
    db.flush()
    tipo = TipoTicket(sector_id=sector.id, codigo="consulta", nombre="Consulta", workflow_id=workflow.id)
    db.add(tipo)
    db.flush()
    return sector, tipo, estado


def _make_usuario(db, rol: Rol) -> Usuario:
    _seq[0] += 1
    usuario = Usuario(
        username=f"migr_backfill_user_{_seq[0]}",
        email=f"migr_backfill_{_seq[0]}@test.com",
        nombre="Migration Backfill Test User",
        password_hash="x",
        rol=RolUsuario.VENTAS,
        rol_id=rol.id,
        auth_provider=AuthProvider.LOCAL,
        activo=True,
    )
    db.add(usuario)
    db.flush()
    return usuario


def _make_ticket(db, rol: Rol, *, texto_original: str | None = None, titulo: str = "Ticket de migracion") -> Ticket:
    sector, tipo, estado = _make_sector_tipo_estado(db)
    creador = _make_usuario(db, rol)
    ticket = Ticket(
        titulo=titulo,
        prioridad=PrioridadTicket.MEDIA,
        sector_id=sector.id,
        tipo_ticket_id=tipo.id,
        estado_id=estado.id,
        creador_id=creador.id,
        campos_metadata={},
        texto_original=texto_original,
    )
    db.add(ticket)
    db.flush()
    return ticket


def _make_pendiente(db, ticket: Ticket, campo: str, valor: str) -> PropuestaIA:
    p = PropuestaIA(ticket_id=ticket.id, campo=campo, valor_propuesto={"valor": valor}, estado="pendiente")
    db.add(p)
    db.flush()
    return p


def _reload_ticket(db, ticket: Ticket) -> Ticket:
    db.expire(ticket)
    return db.query(Ticket).filter(Ticket.id == ticket.id).first()


def _reload_propuesta(db, propuesta: PropuestaIA) -> PropuestaIA:
    db.expire(propuesta)
    return db.query(PropuestaIA).filter(PropuestaIA.id == propuesta.id).first()


@pytest.mark.postgres
class TestUpgradeAppliesPendingProposals:
    def test_pending_severidad_gets_applied_as_ia_auto(self, pg_tickets_db):
        db = pg_tickets_db
        rol = _make_rol(db)
        ticket = _make_ticket(db, rol)
        propuesta = _make_pendiente(db, ticket, "severidad", "critica")
        migration = _load_migration()

        _run_migration_fn(db, migration.upgrade)

        ticket = _reload_ticket(db, ticket)
        assert ticket.severidad == "critica"
        assert ticket.severidad_origen == "ia_auto"
        propuesta = _reload_propuesta(db, propuesta)
        assert propuesta.estado == "confirmada"
        assert propuesta.confirmado_por_id is None
        assert propuesta.confirmado_at is not None

    def test_pending_titulo_gets_applied_when_texto_original_present(self, pg_tickets_db):
        db = pg_tickets_db
        rol = _make_rol(db)
        ticket = _make_ticket(db, rol, texto_original="Texto original del reclamo", titulo="Texto original del recla")
        propuesta = _make_pendiente(db, ticket, "titulo", "Titulo mejor propuesto por la IA")
        migration = _load_migration()

        _run_migration_fn(db, migration.upgrade)

        ticket = _reload_ticket(db, ticket)
        assert ticket.titulo == "Titulo mejor propuesto por la IA"
        assert ticket.titulo_origen == "ia_auto"
        propuesta = _reload_propuesta(db, propuesta)
        assert propuesta.estado == "confirmada"
        assert propuesta.confirmado_por_id is None

    def test_pending_titulo_skipped_when_no_texto_original(self, pg_tickets_db):
        """A titulo proposal without `texto_original` should not exist in
        practice (`_debe_proponer_titulo` never proposes one) — but the
        migration's own guard must hold even for a legacy/manually-inserted
        row, never overwriting a human-typed titulo it cannot prove is
        machine-derived."""
        db = pg_tickets_db
        rol = _make_rol(db)
        ticket = _make_ticket(db, rol, texto_original=None, titulo="Titulo escrito por una persona")
        propuesta = _make_pendiente(db, ticket, "titulo", "Titulo que la IA hubiera propuesto")
        migration = _load_migration()

        _run_migration_fn(db, migration.upgrade)

        ticket = _reload_ticket(db, ticket)
        assert ticket.titulo == "Titulo escrito por una persona"
        assert ticket.titulo_origen is None
        propuesta = _reload_propuesta(db, propuesta)
        assert propuesta.estado == "pendiente"  # guard skipped it — left exactly as it was

    def test_human_value_on_one_ticket_untouched_while_ai_value_applies_on_another(self, pg_tickets_db):
        """The fixture the decision explicitly asked for: a human-set value
        coexists (across two tickets, and across two fields on the SAME
        ticket) with an AI-pending one — only the AI one moves."""
        db = pg_tickets_db
        rol = _make_rol(db)

        ticket_humano = _make_ticket(db, rol)
        ticket_humano.severidad = "trivial"
        ticket_humano.severidad_origen = "humano"
        db.flush()

        ticket_mixto = _make_ticket(db, rol)
        ticket_mixto.urgencia = "baja"
        ticket_mixto.urgencia_origen = "humano"
        db.flush()
        propuesta_severidad = _make_pendiente(db, ticket_mixto, "severidad", "mayor")

        migration = _load_migration()
        _run_migration_fn(db, migration.upgrade)

        ticket_humano = _reload_ticket(db, ticket_humano)
        assert ticket_humano.severidad == "trivial"
        assert ticket_humano.severidad_origen == "humano"  # completely untouched

        ticket_mixto = _reload_ticket(db, ticket_mixto)
        assert ticket_mixto.urgencia == "baja"
        assert ticket_mixto.urgencia_origen == "humano"  # its human value survives too
        assert ticket_mixto.severidad == "mayor"  # the AI one applied
        assert ticket_mixto.severidad_origen == "ia_auto"
        propuesta_severidad = _reload_propuesta(db, propuesta_severidad)
        assert propuesta_severidad.estado == "confirmada"

    def test_marking_is_coupled_to_the_write_not_to_origen_shape(self, pg_tickets_db):
        """Real pre-push review finding (BLOCKING): the exact three-step
        sequence that opens the corruption path.

        1. Runtime auto-apply writes `severidad='mayor'` and marks the
           original proposal `confirmada` (simulated directly here — this
           happens through `run_triage`/`confirmacion_service`, outside the
           migration).
        2. `TICKETS_TRIAGE_AUTO_APPLY=False` + a forced retrigger demotes
           that `ia_auto`/`confirmada` proposal to `reemplazada` and inserts
           a NEW `pendiente` proposal with a DIFFERENT value (`'critica'`)
           — the ticket's `severidad`/`severidad_origen` are untouched by
           this step (auto-apply is off).
        3. This migration runs. `tickets.severidad IS NOT NULL` already
           (still `'mayor'`), so the `UPDATE tickets` guard correctly skips
           writing anything for this ticket/campo.

        A marking step keyed only on `t.severidad_origen = 'ia_auto'` would
        still match the NEW `'critica'` pendiente proposal (same ticket,
        same campo, ticket origen unrelated to what THIS row asked for) and
        wrongly mark it `confirmada` — claiming a write that never
        happened. The proposal must be left exactly as it was: `pendiente`.
        """
        db = pg_tickets_db
        rol = _make_rol(db)
        ticket = _make_ticket(db, rol)

        # Step 1: simulate the runtime auto-apply that already landed
        # 'mayor' on the ticket, with its own proposal confirmed.
        ticket.severidad = "mayor"
        ticket.severidad_origen = "ia_auto"
        db.flush()
        propuesta_original = PropuestaIA(
            ticket_id=ticket.id,
            campo="severidad",
            valor_propuesto={"valor": "mayor"},
            estado="confirmada",
            confirmado_por_id=None,
        )
        db.add(propuesta_original)
        db.flush()

        # Step 2: forced retrigger with the kill switch off — demotes the
        # original proposal and inserts a new, different-valued pendiente
        # one. The ticket itself is NOT touched (auto-apply disabled).
        propuesta_original.estado = "reemplazada"
        db.flush()
        propuesta_nueva = _make_pendiente(db, ticket, "severidad", "critica")

        migration = _load_migration()

        # Step 3: the migration runs.
        _run_migration_fn(db, migration.upgrade)

        ticket = _reload_ticket(db, ticket)
        assert ticket.severidad == "mayor"  # untouched — column already claimed
        assert ticket.severidad_origen == "ia_auto"

        propuesta_nueva = _reload_propuesta(db, propuesta_nueva)
        # The bug: a shape-only join (`t.severidad_origen = 'ia_auto'`)
        # would mark this `confirmada` even though the migration's own
        # UPDATE never touched this ticket/campo — it never actually wrote
        # 'critica' anywhere. Discarding this proposal afterward would then
        # wipe the ticket's real, correct 'mayor' value.
        assert propuesta_nueva.estado == "pendiente"
        assert propuesta_nueva.confirmado_at is None

        propuesta_original = _reload_propuesta(db, propuesta_original)
        assert propuesta_original.estado == "reemplazada"  # untouched by the migration

    def test_pending_ticket_column_already_non_null_is_not_overwritten(self, pg_tickets_db):
        """Defensive guard: if the ticket's own column is already claimed
        (should not happen given `_ya_tiene_propuesta_activa`'s invariant,
        but the migration must not assume it), the pending proposal is
        left `pendiente` rather than clobbering whatever is already there."""
        db = pg_tickets_db
        rol = _make_rol(db)
        ticket = _make_ticket(db, rol)
        ticket.urgencia = "inmediata"
        ticket.urgencia_origen = "humano"
        db.flush()
        propuesta = _make_pendiente(db, ticket, "urgencia", "baja")
        migration = _load_migration()

        _run_migration_fn(db, migration.upgrade)

        ticket = _reload_ticket(db, ticket)
        assert ticket.urgencia == "inmediata"
        assert ticket.urgencia_origen == "humano"
        propuesta = _reload_propuesta(db, propuesta)
        assert propuesta.estado == "pendiente"


@pytest.mark.postgres
class TestDowngradeRevertsPrecisely:
    def test_downgrade_reverts_severidad_and_returns_proposal_to_pendiente(self, pg_tickets_db):
        db = pg_tickets_db
        rol = _make_rol(db)
        ticket = _make_ticket(db, rol)
        propuesta = _make_pendiente(db, ticket, "severidad", "critica")
        migration = _load_migration()
        _run_migration_fn(db, migration.upgrade)

        _run_migration_fn(db, migration.downgrade)

        ticket = _reload_ticket(db, ticket)
        assert ticket.severidad is None
        assert ticket.severidad_origen is None
        propuesta = _reload_propuesta(db, propuesta)
        assert propuesta.estado == "pendiente"
        assert propuesta.confirmado_at is None

    def test_downgrade_recomputes_derived_titulo_from_texto_original(self, pg_tickets_db):
        """`titulo` is NOT NULL — downgrade cannot null it out. It must
        recompute `_derivar_titulo`'s own truncation (first 80 chars,
        trimmed) from the immutable `texto_original`, the exact value the
        ticket carried before this migration ever ran."""
        db = pg_tickets_db
        rol = _make_rol(db)
        texto = "A" * 90  # no whitespace — TRIM/LEFT/RTRIM match Python's strip()[:80].rstrip() exactly
        ticket = _make_ticket(db, rol, texto_original=texto, titulo="A" * 80)
        propuesta = _make_pendiente(db, ticket, "titulo", "Titulo mejor propuesto por la IA")
        migration = _load_migration()
        _run_migration_fn(db, migration.upgrade)

        _run_migration_fn(db, migration.downgrade)

        ticket = _reload_ticket(db, ticket)
        assert ticket.titulo == "A" * 80
        assert ticket.titulo_origen is None
        propuesta = _reload_propuesta(db, propuesta)
        assert propuesta.estado == "pendiente"

    def test_downgrade_leaves_human_value_on_the_same_ticket_untouched(self, pg_tickets_db):
        """The precise-revert requirement, proven through a full
        upgrade+downgrade round trip: a human value coexisting on the SAME
        ticket as an AI one survives both directions."""
        db = pg_tickets_db
        rol = _make_rol(db)
        ticket = _make_ticket(db, rol)
        ticket.urgencia = "baja"
        ticket.urgencia_origen = "humano"
        db.flush()
        propuesta_severidad = _make_pendiente(db, ticket, "severidad", "mayor")
        migration = _load_migration()
        _run_migration_fn(db, migration.upgrade)

        _run_migration_fn(db, migration.downgrade)

        ticket = _reload_ticket(db, ticket)
        assert ticket.urgencia == "baja"
        assert ticket.urgencia_origen == "humano"  # never touched by either direction
        assert ticket.severidad is None
        assert ticket.severidad_origen is None
        propuesta_severidad = _reload_propuesta(db, propuesta_severidad)
        assert propuesta_severidad.estado == "pendiente"

    def test_downgrade_never_reverts_a_proposal_over_a_since_corrected_human_value(self, pg_tickets_db):
        """Real pre-push review finding: a human can correct the SAME field
        through `actualizar_ticket`'s PATCH — a completely different write
        path that never touches `tickets_propuestas_ia` — any time AFTER
        this migration's `upgrade()` ran but BEFORE `downgrade()` runs.
        `downgrade()` must recognize the ticket no longer carries
        `origen='ia_auto'` and leave BOTH the ticket AND the proposal
        exactly as they are — never revert the proposal to `pendiente`
        over a value a person already fixed."""
        db = pg_tickets_db
        rol = _make_rol(db)
        ticket = _make_ticket(db, rol)
        propuesta = _make_pendiente(db, ticket, "urgencia", "baja")
        migration = _load_migration()
        _run_migration_fn(db, migration.upgrade)

        ticket = _reload_ticket(db, ticket)
        assert ticket.urgencia_origen == "ia_auto"  # sanity: upgrade did apply it
        # A human corrects it — simulates `actualizar_ticket`'s PATCH path.
        ticket.urgencia = "inmediata"
        ticket.urgencia_origen = "humano"
        db.flush()

        _run_migration_fn(db, migration.downgrade)

        ticket = _reload_ticket(db, ticket)
        assert ticket.urgencia == "inmediata"  # the human's correction survives
        assert ticket.urgencia_origen == "humano"
        propuesta = _reload_propuesta(db, propuesta)
        assert propuesta.estado == "confirmada"  # NOT reverted to pendiente over it

    def test_downgrade_recomputes_titulo_matching_python_strip_for_leading_newline(self, pg_tickets_db):
        """Postgres's bare `TRIM(BOTH FROM ...)` strips only plain spaces;
        `_derivar_titulo` uses Python's `str.strip()`, which also strips
        tabs/newlines/CR. A `texto_original` starting with a newline must
        recompute the SAME titulo either way."""
        db = pg_tickets_db
        rol = _make_rol(db)
        texto = "\n\t  Reclamo con espacios raros al principio y al final  \t\n"
        titulo_esperado = texto.strip()[:80].rstrip()
        ticket = _make_ticket(db, rol, texto_original=texto, titulo=titulo_esperado)
        propuesta = _make_pendiente(db, ticket, "titulo", "Titulo mejor propuesto por la IA")
        migration = _load_migration()
        _run_migration_fn(db, migration.upgrade)

        _run_migration_fn(db, migration.downgrade)

        ticket = _reload_ticket(db, ticket)
        assert ticket.titulo == titulo_esperado
        propuesta = _reload_propuesta(db, propuesta)
        assert propuesta.estado == "pendiente"

    def test_downgrade_never_wipes_a_ratified_severidad_value(self, pg_tickets_db):
        """Real pre-push review finding (BLOCKING): `confirmacion_service.
        confirmar()`'s ratify branch (feat/tickets-triage-aplicar-directo)
        marks an ia_auto proposal `confirmado_por_id = <usuario>` WITHOUT
        touching the ticket — `severidad_origen` stays 'ia_auto' forever,
        that is the whole point of ratify (a human looked and agrees, no
        rewrite needed). The proposal-revert step already excludes this
        row correctly (`confirmado_por_id IS NULL`), but the OLD
        ticket-column clear matched on `{campo}_origen = 'ia_auto'` alone
        — wiping a value a human explicitly ratified. The clear must be
        coupled to the SAME proposals the revert step actually touched."""
        db = pg_tickets_db
        rol = _make_rol(db)
        ticket = _make_ticket(db, rol)
        usuario = _make_usuario(db, rol)
        propuesta = _make_pendiente(db, ticket, "severidad", "critica")
        migration = _load_migration()
        _run_migration_fn(db, migration.upgrade)

        # Simulates `confirmacion_service.confirmar()`'s ratify branch: a
        # human looked at the auto-applied value and agreed — only the
        # proposal's confirmador changes, the ticket is untouched.
        propuesta = _reload_propuesta(db, propuesta)
        propuesta.confirmado_por_id = usuario.id
        db.flush()

        _run_migration_fn(db, migration.downgrade)

        ticket = _reload_ticket(db, ticket)
        assert ticket.severidad == "critica"  # survives — a human ratified it
        assert ticket.severidad_origen == "ia_auto"
        propuesta = _reload_propuesta(db, propuesta)
        assert propuesta.estado == "confirmada"  # NOT reverted to pendiente

    def test_downgrade_never_wipes_a_ratified_titulo_value(self, pg_tickets_db):
        """Same gap, worse consequence for `titulo`: the old code would
        have RECOMPUTED the machine-derived truncation over a title a
        human explicitly ratified."""
        db = pg_tickets_db
        rol = _make_rol(db)
        texto = "Texto original del reclamo"
        ticket = _make_ticket(db, rol, texto_original=texto, titulo="Texto original del recla")
        usuario = _make_usuario(db, rol)
        propuesta = _make_pendiente(db, ticket, "titulo", "Titulo mejor propuesto por la IA")
        migration = _load_migration()
        _run_migration_fn(db, migration.upgrade)

        propuesta = _reload_propuesta(db, propuesta)
        propuesta.confirmado_por_id = usuario.id
        db.flush()

        _run_migration_fn(db, migration.downgrade)

        ticket = _reload_ticket(db, ticket)
        assert ticket.titulo == "Titulo mejor propuesto por la IA"  # survives
        assert ticket.titulo_origen == "ia_auto"
        propuesta = _reload_propuesta(db, propuesta)
        assert propuesta.estado == "confirmada"

    def test_downgrade_never_touches_human_confirmed_ia_confirmada_row(self, pg_tickets_db):
        """`confirmado_por_id IS NOT NULL` means a human already ratified
        it (`ia_confirmada`, via `confirmar()`) — downgrade's own criteria
        (`confirmado_por_id IS NULL`) must never revert that."""
        db = pg_tickets_db
        rol = _make_rol(db)
        ticket = _make_ticket(db, rol)
        usuario = _make_usuario(db, rol)
        ticket.severidad = "mayor"
        ticket.severidad_origen = "ia_confirmada"
        db.flush()
        propuesta = PropuestaIA(
            ticket_id=ticket.id,
            campo="severidad",
            valor_propuesto={"valor": "mayor"},
            estado="confirmada",
            confirmado_por_id=usuario.id,
        )
        db.add(propuesta)
        db.flush()
        migration = _load_migration()

        _run_migration_fn(db, migration.downgrade)

        ticket = _reload_ticket(db, ticket)
        assert ticket.severidad == "mayor"
        assert ticket.severidad_origen == "ia_confirmada"
        propuesta = _reload_propuesta(db, propuesta)
        assert propuesta.estado == "confirmada"
