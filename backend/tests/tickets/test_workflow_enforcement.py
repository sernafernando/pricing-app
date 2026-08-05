"""
Tests for server-side transition-graph enforcement on
POST /tickets/tickets/{ticket_id}/transicion.

Covers `backend/tickets-workflow-integrity` spec requirements:
- Server-Side Transition Graph Enforcement
- Enforcement Kill Switch (TICKETS_WORKFLOW_ENFORCE)

Written FIRST (RED phase) per strict TDD.

Run:
    cd backend && source venv/bin/activate && pytest tests/tickets/test_workflow_enforcement.py -v
"""

from app.core.config import settings
from app.models.permiso import Permiso, UsuarioPermisoOverride
from app.models.rol import Rol
from app.models.usuario import Usuario, RolUsuario, AuthProvider
from app.core.security import get_password_hash, create_access_token
from app.tickets.models.historial_ticket import HistorialTicket
from app.tickets.models.sector import Sector
from app.tickets.models.ticket import Ticket, PrioridadTicket
from app.tickets.models.tipo_ticket import TipoTicket
from app.tickets.models.workflow import EstadoTicket, TransicionEstado, Workflow


_seq = [0]


def _make_user(db, rol: Rol) -> Usuario:
    _seq[0] += 1
    u = Usuario(
        username=f"wf_user_{_seq[0]}",
        email=f"wf_{_seq[0]}@test.com",
        nombre=f"WF User {_seq[0]}",
        password_hash=get_password_hash("pass"),
        rol=RolUsuario.VENTAS,
        rol_id=rol.id,
        auth_provider=AuthProvider.LOCAL,
        activo=True,
    )
    db.add(u)
    db.flush()
    return u


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


def _make_sector(db) -> Sector:
    _seq[0] += 1
    s = Sector(codigo=f"WF_SECT_{_seq[0]}", nombre=f"WF Sector {_seq[0]}", activo=True)
    db.add(s)
    db.flush()
    return s


def _make_workflow(
    db, sector: Sector, *, with_transicion: bool
) -> tuple[Workflow, TipoTicket, EstadoTicket, EstadoTicket]:
    """Build a 2-state workflow. `with_transicion` controls whether a
    `tickets_transiciones` edge from estado_a -> estado_b is configured."""
    wf = Workflow(sector_id=sector.id, nombre="WF Enforcement Test", es_default=True, activo=True)
    db.add(wf)
    db.flush()

    estado_a = EstadoTicket(
        workflow_id=wf.id, codigo="abierto", nombre="Abierto", orden=1, es_inicial=True, es_final=False
    )
    estado_b = EstadoTicket(
        workflow_id=wf.id, codigo="cerrado", nombre="Cerrado", orden=2, es_inicial=False, es_final=True
    )
    db.add_all([estado_a, estado_b])
    db.flush()

    if with_transicion:
        db.add(
            TransicionEstado(
                workflow_id=wf.id,
                estado_origen_id=estado_a.id,
                estado_destino_id=estado_b.id,
                nombre="Cerrar",
            )
        )
        db.flush()

    tipo = TipoTicket(sector_id=sector.id, codigo="consulta", nombre="Consulta", workflow_id=wf.id)
    db.add(tipo)
    db.flush()

    return wf, tipo, estado_a, estado_b


def _make_ticket(db, *, sector: Sector, tipo: TipoTicket, estado: EstadoTicket, creador: Usuario) -> Ticket:
    t = Ticket(
        titulo="WF Test Ticket",
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


TRANSICION_ENDPOINT = "/api/tickets/tickets/{id}/transicion"


class TestInvalidTransitionRejected:
    """SC: no configured edge -> 409 with can_transition's Spanish message."""

    def test_unconfigured_transition_returns_409(self, client, db, rol_ventas):
        user = _make_user(db, rol_ventas)
        _give_permiso(db, user, "tickets.gestionar")
        sector = _make_sector(db)
        _, tipo, estado_a, estado_b = _make_workflow(db, sector, with_transicion=False)
        ticket = _make_ticket(db, sector=sector, tipo=tipo, estado=estado_a, creador=user)

        resp = client.post(
            TRANSICION_ENDPOINT.format(id=ticket.id),
            json={"nuevo_estado_id": estado_b.id},
            headers=_headers(user),
        )

        assert resp.status_code == 409
        assert "transición permitida" in resp.json()["error"]["message"]

        db.refresh(ticket)
        assert ticket.estado_id == estado_a.id


class TestValidTransitionSucceeds:
    """SC: configured edge -> 200, estado updates, historial row written."""

    def test_valid_transition_writes_history(self, client, db, rol_ventas):
        user = _make_user(db, rol_ventas)
        _give_permiso(db, user, "tickets.gestionar")
        sector = _make_sector(db)
        _, tipo, estado_a, estado_b = _make_workflow(db, sector, with_transicion=True)
        ticket = _make_ticket(db, sector=sector, tipo=tipo, estado=estado_a, creador=user)

        resp = client.post(
            TRANSICION_ENDPOINT.format(id=ticket.id),
            json={"nuevo_estado_id": estado_b.id},
            headers=_headers(user),
        )

        assert resp.status_code == 200
        db.refresh(ticket)
        assert ticket.estado_id == estado_b.id

        historial = (
            db.query(HistorialTicket)
            .filter(HistorialTicket.ticket_id == ticket.id, HistorialTicket.accion == "estado_changed")
            .all()
        )
        assert len(historial) == 1
        assert historial[0].estado_nuevo_id == estado_b.id


class TestReTransitionSameState:
    """SC: re-transition to the same state -> 409 idempotency-safe message."""

    def test_same_state_returns_409(self, client, db, rol_ventas):
        user = _make_user(db, rol_ventas)
        _give_permiso(db, user, "tickets.gestionar")
        sector = _make_sector(db)
        _, tipo, estado_a, _ = _make_workflow(db, sector, with_transicion=True)
        ticket = _make_ticket(db, sector=sector, tipo=tipo, estado=estado_a, creador=user)

        resp = client.post(
            TRANSICION_ENDPOINT.format(id=ticket.id),
            json={"nuevo_estado_id": estado_a.id},
            headers=_headers(user),
        )

        assert resp.status_code == 409
        assert resp.json()["error"]["message"] == "El ticket ya está en ese estado"


class TestEnforcementFlagOff:
    """SC: TICKETS_WORKFLOW_ENFORCE=False -> logs and proceeds (200)."""

    def test_flag_off_allows_unconfigured_transition(self, client, db, rol_ventas, monkeypatch):
        monkeypatch.setattr(settings, "TICKETS_WORKFLOW_ENFORCE", False)

        user = _make_user(db, rol_ventas)
        _give_permiso(db, user, "tickets.gestionar")
        sector = _make_sector(db)
        _, tipo, estado_a, estado_b = _make_workflow(db, sector, with_transicion=False)
        ticket = _make_ticket(db, sector=sector, tipo=tipo, estado=estado_a, creador=user)

        resp = client.post(
            TRANSICION_ENDPOINT.format(id=ticket.id),
            json={"nuevo_estado_id": estado_b.id},
            headers=_headers(user),
        )

        assert resp.status_code == 200
        db.refresh(ticket)
        assert ticket.estado_id == estado_b.id
