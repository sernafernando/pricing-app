"""
Tests for PATCH /tickets/{ticket_id} accepting urgencia/urgencia_origen
(tickets-ai-triage PR 5c, drag-and-drop write semantics — the URGENCY-column
drop path from design #1303 section 4: `{urgencia, urgencia_origen:'humano'}`
must persist both fields and land in `tickets_historial` like any other
tracked field change).

Written FIRST (RED phase) per strict TDD.

Run:
    cd backend && source venv/bin/activate
    pytest tests/tickets/test_ticket_update_urgencia.py -v
"""

from app.core.security import create_access_token, get_password_hash
from app.models.rol import Rol
from app.models.usuario import AuthProvider, RolUsuario, Usuario
from app.tickets.models.historial_ticket import HistorialTicket
from app.tickets.models.sector import Sector
from app.tickets.models.ticket import PrioridadTicket, Ticket
from app.tickets.models.tipo_ticket import TipoTicket
from app.tickets.models.workflow import EstadoTicket, Workflow

TICKETS_ENDPOINT = "/api/tickets/tickets"
_seq = [0]


def _make_user(db, rol: Rol) -> Usuario:
    _seq[0] += 1
    u = Usuario(
        username=f"dnd_user_{_seq[0]}",
        email=f"dnd_{_seq[0]}@test.com",
        nombre=f"DnD User {_seq[0]}",
        password_hash=get_password_hash("pass"),
        rol=RolUsuario.VENTAS,
        rol_id=rol.id,
        auth_provider=AuthProvider.LOCAL,
        activo=True,
    )
    db.add(u)
    db.flush()
    return u


def _headers(user: Usuario) -> dict:
    token = create_access_token(data={"sub": user.username})
    return {"Authorization": f"Bearer {token}"}


def _make_ticket(db, creador: Usuario, *, urgencia=None, urgencia_origen=None) -> Ticket:
    _seq[0] += 1
    sector = Sector(codigo=f"DND_SECT_{_seq[0]}", nombre="Sector DnD", activo=True)
    db.add(sector)
    db.flush()
    workflow = Workflow(sector_id=sector.id, nombre="WF DnD", es_default=True, activo=True)
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
    ticket = Ticket(
        titulo=f"Ticket DnD {_seq[0]}",
        prioridad=PrioridadTicket.MEDIA,
        sector_id=sector.id,
        tipo_ticket_id=tipo.id,
        estado_id=estado.id,
        creador_id=creador.id,
        urgencia=urgencia,
        urgencia_origen=urgencia_origen,
    )
    db.add(ticket)
    db.flush()
    return ticket


class TestPatchUrgenciaWriteSemantics:
    """SC: dropping a card on a different URGENCY column PATCHes urgencia +
    urgencia_origen and the change lands in tickets_historial."""

    def test_patch_urgencia_persists_both_fields_and_writes_historial(self, db, client, rol_ventas):
        user = _make_user(db, rol_ventas)
        ticket = _make_ticket(db, user, urgencia=None)

        resp = client.patch(
            f"{TICKETS_ENDPOINT}/{ticket.id}",
            json={"urgencia": "alta", "urgencia_origen": "humano"},
            headers=_headers(user),
        )

        assert resp.status_code == 200
        assert resp.json()["urgencia"] == "alta"
        assert resp.json()["urgencia_origen"] == "humano"

        db.refresh(ticket)
        assert ticket.urgencia == "alta"
        assert ticket.urgencia_origen == "humano"

        historial = db.query(HistorialTicket).filter(HistorialTicket.ticket_id == ticket.id).all()
        urgencia_entries = [h for h in historial if "urgencia" in (h.cambios or {})]
        assert len(urgencia_entries) == 1
        assert urgencia_entries[0].cambios["urgencia"] == {"valor_anterior": None, "valor_nuevo": "alta"}

    def test_patch_urgencia_explicit_null_clears_it(self, db, client, rol_ventas):
        """The 'Sin clasificar' urgency column drop must genuinely clear the
        field, not silently no-op — a plain `is not None` sentinel cannot
        distinguish 'field not sent' from 'field sent as null' (the exact
        shape of obs #1350's variant-5 trap, checked here up front)."""
        user = _make_user(db, rol_ventas)
        ticket = _make_ticket(db, user, urgencia="baja")

        resp = client.patch(
            f"{TICKETS_ENDPOINT}/{ticket.id}",
            json={"urgencia": None, "urgencia_origen": "humano"},
            headers=_headers(user),
        )

        assert resp.status_code == 200
        db.refresh(ticket)
        assert ticket.urgencia is None

    def test_patch_without_urgencia_field_leaves_it_unchanged(self, db, client, rol_ventas):
        user = _make_user(db, rol_ventas)
        ticket = _make_ticket(db, user, urgencia="alta")

        resp = client.patch(
            f"{TICKETS_ENDPOINT}/{ticket.id}",
            json={"titulo": "Nuevo titulo valido"},
            headers=_headers(user),
        )

        assert resp.status_code == 200
        db.refresh(ticket)
        assert ticket.urgencia == "alta"

    def test_patch_invalid_urgencia_value_is_rejected_422(self, db, client, rol_ventas):
        """A closed vocabulary at the schema layer, matching `ck_tickets_urgencia`
        — without it, a bad value reaches `db.commit()` and 500s as an
        unhandled `IntegrityError` instead of a clean 422 (GGA pre-push
        finding, fixed before this reached prod)."""
        user = _make_user(db, rol_ventas)
        ticket = _make_ticket(db, user, urgencia=None)

        resp = client.patch(
            f"{TICKETS_ENDPOINT}/{ticket.id}",
            json={"urgencia": "urgentisimo", "urgencia_origen": "humano"},
            headers=_headers(user),
        )

        assert resp.status_code == 422
        db.refresh(ticket)
        assert ticket.urgencia is None

    def test_patch_invalid_urgencia_origen_value_is_rejected_422(self, db, client, rol_ventas):
        user = _make_user(db, rol_ventas)
        ticket = _make_ticket(db, user, urgencia=None)

        resp = client.patch(
            f"{TICKETS_ENDPOINT}/{ticket.id}",
            json={"urgencia": "alta", "urgencia_origen": "un_robot_cualquiera"},
            headers=_headers(user),
        )

        assert resp.status_code == 422
        db.refresh(ticket)
        assert ticket.urgencia is None

    def test_clearing_urgencia_without_origen_also_clears_stale_origen(self, db, client, rol_ventas):
        """GGA pre-push finding: clearing urgencia (drop on 'Sin clasificar')
        without sending urgencia_origen must not leave a stale provenance
        pointing at a value that no longer exists — 'Provenance Is Always
        Visible' must never mean 'visible and false'."""
        user = _make_user(db, rol_ventas)
        ticket = _make_ticket(db, user, urgencia="alta", urgencia_origen="ia_confirmada")

        resp = client.patch(
            f"{TICKETS_ENDPOINT}/{ticket.id}",
            json={"urgencia": None},
            headers=_headers(user),
        )

        assert resp.status_code == 200
        db.refresh(ticket)
        assert ticket.urgencia is None
        assert ticket.urgencia_origen is None
