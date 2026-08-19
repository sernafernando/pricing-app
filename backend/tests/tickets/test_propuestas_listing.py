"""Tests for GET /tickets/{id}/propuestas (tickets-ai-triage PR 4c).

Gap found while implementing the confirm UI: PR 4b shipped confirm/discard/
batch/retrigger, but never a read endpoint for "which proposals are pending
right now for this ticket" — without it the confirm UI has no data to
render. Added here, scoped minimally: pending-only, no `tickets.triage.confirmar`
required (spec: confidence must be visible before confirming, independent of
who may confirm), gated by the same creador-or-`tickets.ver` access check the
sibling `/historial` and `/comentarios` endpoints already use.

Written FIRST (RED phase) per strict TDD.

Run:
    cd backend && source venv/bin/activate
    pytest tests/tickets/test_propuestas_listing.py -v
"""

from app.core.security import create_access_token, get_password_hash
from app.models.permiso import Permiso, UsuarioPermisoOverride
from app.models.usuario import AuthProvider, RolUsuario, Usuario
from app.tickets.models.propuesta_ia import PropuestaIA
from app.tickets.models.sector import Sector
from app.tickets.models.ticket import PrioridadTicket, Ticket
from app.tickets.models.tipo_ticket import TipoTicket
from app.tickets.models.workflow import EstadoTicket, Workflow

ENDPOINT = "/api/tickets/tickets/{id}/propuestas"
_seq = [0]


def _make_ticket(db, rol) -> Ticket:
    _seq[0] += 1
    sector = Sector(codigo=f"PROP_LIST_SECT_{_seq[0]}", nombre="Sector Listado", activo=True, configuracion={})
    db.add(sector)
    db.flush()
    workflow = Workflow(sector_id=sector.id, nombre="WF Listado", es_default=True, activo=True)
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
    creador = Usuario(
        username=f"prop_list_creador_{_seq[0]}",
        email=f"prop_list_creador_{_seq[0]}@test.com",
        nombre="Creador Listado",
        password_hash=get_password_hash("pass"),
        rol=RolUsuario.VENTAS,
        rol_id=rol.id,
        auth_provider=AuthProvider.LOCAL,
        activo=True,
    )
    db.add(creador)
    db.flush()
    ticket = Ticket(
        titulo="Ticket para listado de propuestas",
        prioridad=PrioridadTicket.MEDIA,
        sector_id=sector.id,
        tipo_ticket_id=tipo.id,
        estado_id=estado.id,
        creador_id=creador.id,
        campos_metadata={},
    )
    db.add(ticket)
    db.flush()
    return ticket


def _make_usuario(db, rol) -> Usuario:
    _seq[0] += 1
    usuario = Usuario(
        username=f"prop_list_user_{_seq[0]}",
        email=f"prop_list_user_{_seq[0]}@test.com",
        nombre="Usuario Listado",
        password_hash=get_password_hash("pass"),
        rol=RolUsuario.VENTAS,
        rol_id=rol.id,
        auth_provider=AuthProvider.LOCAL,
        activo=True,
    )
    db.add(usuario)
    db.flush()
    return usuario


def _make_propuesta(
    db, ticket: Ticket, campo: str, valor: str, confianza: float, estado: str = "pendiente", confirmado_por_id=None
):
    p = PropuestaIA(
        ticket_id=ticket.id,
        campo=campo,
        valor_propuesto={"valor": valor},
        confianza=confianza,
        estado=estado,
        confirmado_por_id=confirmado_por_id,
    )
    db.add(p)
    db.flush()
    return p


def _give_permiso(db, user: Usuario, codigo: str) -> None:
    permiso = db.query(Permiso).filter(Permiso.codigo == codigo).first()
    if not permiso:
        permiso = Permiso(codigo=codigo, nombre=codigo, categoria="tickets")
        db.add(permiso)
        db.flush()
    db.add(UsuarioPermisoOverride(usuario_id=user.id, permiso_id=permiso.id, concedido=True))
    db.flush()


def _headers(user: Usuario) -> dict:
    token = create_access_token(data={"sub": user.username})
    return {"Authorization": f"Bearer {token}"}


class TestListarPropuestasPendientes:
    def test_returns_only_pending_for_this_ticket(self, client, db, rol_ventas):
        ticket = _make_ticket(db, rol_ventas)
        otro_ticket = _make_ticket(db, rol_ventas)
        usuario = _make_usuario(db, rol_ventas)
        _give_permiso(db, usuario, "tickets.ver")

        pendiente = _make_propuesta(db, ticket, "severidad", "mayor", 0.82)
        # Human-confirmed (`confirmado_por_id` set) — a decision a person
        # already ratified, nothing left to review. Excluded.
        _make_propuesta(db, ticket, "urgencia", "alta", 0.5, estado="confirmada", confirmado_por_id=usuario.id)
        _make_propuesta(db, ticket, "titulo", "x", 0.9, estado="descartada")
        _make_propuesta(db, otro_ticket, "severidad", "critica", 0.99)

        resp = client.get(ENDPOINT.format(id=ticket.id), headers=_headers(usuario))

        assert resp.status_code == 200
        body = resp.json()
        assert [p["id"] for p in body] == [pendiente.id]
        assert body[0]["campo"] == "severidad"
        assert body[0]["confianza"] == 0.82

    def test_includes_unreviewed_ia_auto_alongside_pending(self, client, db, rol_ventas):
        """feat/tickets-triage-aplicar-directo: a `confirmada` proposal with
        `confirmado_por_id IS NULL` is the AI having already applied it —
        still a human's job to review, so it belongs in this listing next to
        genuinely `pendiente` ones. A human-confirmed row (non-null
        confirmador, previous test) stays excluded either way."""
        ticket = _make_ticket(db, rol_ventas)
        usuario = _make_usuario(db, rol_ventas)
        _give_permiso(db, usuario, "tickets.ver")

        pendiente = _make_propuesta(db, ticket, "severidad", "mayor", 0.82)
        ia_auto = _make_propuesta(db, ticket, "urgencia", "alta", 0.91, estado="confirmada", confirmado_por_id=None)

        resp = client.get(ENDPOINT.format(id=ticket.id), headers=_headers(usuario))

        assert resp.status_code == 200
        body = resp.json()
        assert {p["id"] for p in body} == {pendiente.id, ia_auto.id}
        ia_auto_body = next(p for p in body if p["id"] == ia_auto.id)
        assert ia_auto_body["estado"] == "confirmada"
        assert ia_auto_body["confirmado_por_id"] is None

    def test_visible_without_triage_confirmar_permission(self, client, db, rol_ventas):
        """SC: confidence must be visible before confirming, independent of
        who may confirm — a `tickets.ver`-only user can list proposals."""
        ticket = _make_ticket(db, rol_ventas)
        usuario = _make_usuario(db, rol_ventas)
        _give_permiso(db, usuario, "tickets.ver")
        _make_propuesta(db, ticket, "severidad", "mayor", 0.82)

        resp = client.get(ENDPOINT.format(id=ticket.id), headers=_headers(usuario))

        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_creador_can_list_own_ticket_proposals_without_tickets_ver(self, client, db, rol_ventas):
        ticket = _make_ticket(db, rol_ventas)
        creador = db.query(Usuario).filter(Usuario.id == ticket.creador_id).first()
        _make_propuesta(db, ticket, "severidad", "mayor", 0.82)

        resp = client.get(ENDPOINT.format(id=ticket.id), headers=_headers(creador))

        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_unrelated_user_without_tickets_ver_gets_403(self, client, db, rol_ventas):
        ticket = _make_ticket(db, rol_ventas)
        usuario = _make_usuario(db, rol_ventas)
        _make_propuesta(db, ticket, "severidad", "mayor", 0.82)

        resp = client.get(ENDPOINT.format(id=ticket.id), headers=_headers(usuario))

        assert resp.status_code == 403

    def test_unknown_ticket_returns_404(self, client, db, rol_ventas):
        usuario = _make_usuario(db, rol_ventas)
        _give_permiso(db, usuario, "tickets.ver")

        resp = client.get(ENDPOINT.format(id=999999), headers=_headers(usuario))

        assert resp.status_code == 404


class TestTicketResponseIncludesProvenance:
    """SC: Provenance Is Always Visible — the ticket detail response must
    carry `severidad`/`urgencia`/`resumen` and their `*_origen` fields, not
    just the confirmation service writing them silently to the DB."""

    def test_ticket_response_exposes_severidad_and_origen(self, client, db, rol_ventas):
        ticket = _make_ticket(db, rol_ventas)
        ticket.severidad = "mayor"
        ticket.severidad_origen = "ia_confirmada"
        ticket.resumen = "No puede facturar desde ayer"
        ticket.resumen_origen = "ia_confirmada"
        db.commit()
        usuario = _make_usuario(db, rol_ventas)
        _give_permiso(db, usuario, "tickets.ver")

        resp = client.get(f"/api/tickets/tickets/{ticket.id}", headers=_headers(usuario))

        assert resp.status_code == 200
        body = resp.json()
        assert body["severidad"] == "mayor"
        assert body["severidad_origen"] == "ia_confirmada"
        assert body["resumen"] == "No puede facturar desde ayer"
        assert body["resumen_origen"] == "ia_confirmada"
        assert body["urgencia"] is None
        assert body["urgencia_origen"] is None


class TestPropuestaResponseExposesEjemplosUsados:
    """tickets-triage-feedback PR4b (real pre-push review finding): the
    column was written by `run_triage` and read by the frontend, but
    `PropuestaResponse` never declared it — Pydantic's `from_attributes`
    serializes only declared fields, so the API silently dropped it and the
    frontend badge could never render. Exercised through the REAL endpoint
    (not a mocked API client), unlike the frontend's own component tests."""

    def test_ejemplos_usados_round_trips_through_the_endpoint(self, client, db, rol_ventas):
        ticket = _make_ticket(db, rol_ventas)
        usuario = _make_usuario(db, rol_ventas)
        _give_permiso(db, usuario, "tickets.ver")

        con_ejemplos = _make_propuesta(db, ticket, "severidad", "mayor", 0.82)
        con_ejemplos.ejemplos_usados = 3
        sin_retrieval = _make_propuesta(db, ticket, "titulo", "Arreglar bug", 0.9)
        db.flush()

        resp = client.get(ENDPOINT.format(id=ticket.id), headers=_headers(usuario))

        assert resp.status_code == 200
        body = {p["id"]: p for p in resp.json()}
        assert body[con_ejemplos.id]["ejemplos_usados"] == 3
        assert body[sin_retrieval.id]["ejemplos_usados"] is None
