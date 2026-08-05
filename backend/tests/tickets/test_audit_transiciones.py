"""
Tests for the read-only pre-merge production transition audit
(scripts/audit_transiciones_tickets.py).

Covers the `backend/tickets-workflow-integrity` spec's "Pre-Merge Production
Transition Audit" requirement: the audit groups `tickets_historial` rows with
`accion='estado_changed'` by `(estado_anterior_id, estado_nuevo_id)` and
reports pairs that have no matching `tickets_transiciones` edge, with counts
and last-seen date. Zero writes.

Written FIRST (RED phase) per strict TDD.

Run:
    cd backend && source venv/bin/activate && pytest tests/tickets/test_audit_transiciones.py -v
"""

from datetime import datetime, UTC, timedelta

from app.models.usuario import Usuario, RolUsuario, AuthProvider
from app.core.security import get_password_hash
from app.tickets.models.historial_ticket import HistorialTicket
from app.tickets.models.sector import Sector
from app.tickets.models.ticket import Ticket, PrioridadTicket
from app.tickets.models.tipo_ticket import TipoTicket
from app.tickets.models.workflow import EstadoTicket, TransicionEstado, Workflow
from scripts.audit_transiciones_tickets import find_unconfigured_transitions


_seq = [0]


def _make_user(db, rol) -> Usuario:
    _seq[0] += 1
    u = Usuario(
        username=f"audit_user_{_seq[0]}",
        email=f"audit_{_seq[0]}@test.com",
        nombre=f"Audit User {_seq[0]}",
        password_hash=get_password_hash("pass"),
        rol=RolUsuario.VENTAS,
        rol_id=rol.id,
        auth_provider=AuthProvider.LOCAL,
        activo=True,
    )
    db.add(u)
    db.flush()
    return u


def _make_sector(db) -> Sector:
    _seq[0] += 1
    s = Sector(codigo=f"AUD_SECT_{_seq[0]}", nombre=f"Audit Sector {_seq[0]}", activo=True)
    db.add(s)
    db.flush()
    return s


def _make_workflow_3_states(db, sector: Sector):
    """3-state workflow with ONE configured edge (a -> b). c is unreachable
    via any `tickets_transiciones` row, so historial rows for a->c or b->c
    are "unconfigured" from the audit's point of view."""
    wf = Workflow(sector_id=sector.id, nombre="Audit WF", es_default=True, activo=True)
    db.add(wf)
    db.flush()

    estado_a = EstadoTicket(workflow_id=wf.id, codigo="a", nombre="Estado A", orden=1, es_inicial=True)
    estado_b = EstadoTicket(workflow_id=wf.id, codigo="b", nombre="Estado B", orden=2)
    estado_c = EstadoTicket(workflow_id=wf.id, codigo="c", nombre="Estado C", orden=3, es_final=True)
    db.add_all([estado_a, estado_b, estado_c])
    db.flush()

    db.add(
        TransicionEstado(
            workflow_id=wf.id,
            estado_origen_id=estado_a.id,
            estado_destino_id=estado_b.id,
            nombre="A a B",
        )
    )
    db.flush()

    tipo = TipoTicket(sector_id=sector.id, codigo="consulta", nombre="Consulta", workflow_id=wf.id)
    db.add(tipo)
    db.flush()

    return wf, tipo, estado_a, estado_b, estado_c


def _make_ticket(db, *, sector, tipo, estado, creador) -> Ticket:
    t = Ticket(
        titulo="Audit Test Ticket",
        prioridad=PrioridadTicket.MEDIA,
        sector_id=sector.id,
        tipo_ticket_id=tipo.id,
        estado_id=estado.id,
        creador_id=creador.id,
        campos_metadata={},
    )
    db.add(t)
    db.flush()
    return t


def _add_estado_changed(db, *, ticket, usuario, anterior, nuevo, fecha=None):
    h = HistorialTicket(
        ticket_id=ticket.id,
        usuario_id=usuario.id,
        accion="estado_changed",
        descripcion="test",
        estado_anterior_id=anterior.id,
        estado_nuevo_id=nuevo.id,
        cambios={},
        fecha=fecha or datetime.now(UTC),
    )
    db.add(h)
    db.flush()
    return h


class TestFindUnconfiguredTransitions:
    def test_configured_pair_excluded(self, db, rol_ventas):
        """A pair WITH a tickets_transiciones edge must not be reported."""
        user = _make_user(db, rol_ventas)
        sector = _make_sector(db)
        _, tipo, estado_a, estado_b, _ = _make_workflow_3_states(db, sector)
        ticket = _make_ticket(db, sector=sector, tipo=tipo, estado=estado_a, creador=user)
        _add_estado_changed(db, ticket=ticket, usuario=user, anterior=estado_a, nuevo=estado_b)

        result = find_unconfigured_transitions(db)

        pairs = {(r["estado_anterior_id"], r["estado_nuevo_id"]) for r in result}
        assert (estado_a.id, estado_b.id) not in pairs

    def test_unconfigured_pair_reported_with_count_and_last_seen(self, db, rol_ventas):
        """A pair with NO tickets_transiciones edge is reported with the
        correct count and the most recent `fecha`."""
        user = _make_user(db, rol_ventas)
        sector = _make_sector(db)
        _, tipo, estado_a, _, estado_c = _make_workflow_3_states(db, sector)
        ticket = _make_ticket(db, sector=sector, tipo=tipo, estado=estado_a, creador=user)

        older = datetime.now(UTC) - timedelta(days=2)
        newer = datetime.now(UTC) - timedelta(hours=1)
        _add_estado_changed(db, ticket=ticket, usuario=user, anterior=estado_a, nuevo=estado_c, fecha=older)
        _add_estado_changed(db, ticket=ticket, usuario=user, anterior=estado_a, nuevo=estado_c, fecha=newer)

        result = find_unconfigured_transitions(db)

        matches = [r for r in result if (r["estado_anterior_id"], r["estado_nuevo_id"]) == (estado_a.id, estado_c.id)]
        assert len(matches) == 1
        assert matches[0]["count"] == 2
        # SQLite round-trips datetimes as naive (drops tzinfo) — compare
        # naive-to-naive; PostgreSQL preserves tzinfo in production.
        assert matches[0]["last_seen"].replace(tzinfo=None) == newer.replace(tzinfo=None)

    def test_no_writes_performed(self, db, rol_ventas):
        """The audit is strictly read-only: running it must not add or
        modify any row (no pending/new objects in the session)."""
        user = _make_user(db, rol_ventas)
        sector = _make_sector(db)
        _, tipo, estado_a, _, estado_c = _make_workflow_3_states(db, sector)
        ticket = _make_ticket(db, sector=sector, tipo=tipo, estado=estado_a, creador=user)
        _add_estado_changed(db, ticket=ticket, usuario=user, anterior=estado_a, nuevo=estado_c)
        db.commit()

        find_unconfigured_transitions(db)

        assert len(db.new) == 0
        assert len(db.dirty) == 0
