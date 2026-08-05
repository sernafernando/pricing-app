"""
Tests for POST /tickets/tickets/marcar-revisado/{ticket_id}.

Locks in the real route shape (double `/tickets` segment: the router itself
is mounted at `/tickets` on `TransicionEstado`/tickets endpoints, and
`main.py` adds the `/api/tickets` prefix on top) so a future regression in
`frontend/src/services/api.js`'s `marcarRevisado` path — the exact bug fixed
in this PR — is caught server-side too.

Written FIRST (RED phase) per strict TDD, even though the backend route
itself was never broken — the RED state here is "test references a route
that had not been asserted against for the double-segment shape before".

Run:
    cd backend && source venv/bin/activate && pytest tests/tickets/test_marcar_revisado.py -v
"""

from app.models.permiso import Permiso, UsuarioPermisoOverride
from app.models.rol import Rol
from app.models.usuario import Usuario, RolUsuario, AuthProvider
from app.core.security import get_password_hash, create_access_token
from app.tickets.models.historial_ticket import HistorialTicket
from app.tickets.models.sector import Sector
from app.tickets.models.ticket import Ticket, PrioridadTicket
from app.tickets.models.tipo_ticket import TipoTicket
from app.tickets.models.workflow import EstadoTicket, Workflow


_seq = [0]


def _make_user(db, rol: Rol) -> Usuario:
    _seq[0] += 1
    u = Usuario(
        username=f"mr_user_{_seq[0]}",
        email=f"mr_{_seq[0]}@test.com",
        nombre=f"MR User {_seq[0]}",
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
    s = Sector(codigo=f"MR_SECT_{_seq[0]}", nombre=f"MR Sector {_seq[0]}", activo=True)
    db.add(s)
    db.flush()
    return s


def _make_workflow_and_tipo(db, sector: Sector):
    wf = Workflow(sector_id=sector.id, nombre="MR WF", es_default=True, activo=True)
    db.add(wf)
    db.flush()
    estado = EstadoTicket(workflow_id=wf.id, codigo="abierto", nombre="Abierto", orden=1, es_inicial=True)
    db.add(estado)
    db.flush()
    tipo = TipoTicket(sector_id=sector.id, codigo="consulta", nombre="Consulta", workflow_id=wf.id)
    db.add(tipo)
    db.flush()
    return wf, tipo, estado


def _make_ticket(db, *, sector, tipo, estado, creador) -> Ticket:
    t = Ticket(
        titulo="MR Test Ticket",
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


class TestMarcarRevisadoRoute:
    """SC: the real double-`/tickets`-segment route resolves 2xx and writes
    a `tickets_historial` row with accion='revisado' — the fix in
    frontend/src/services/api.js targets exactly this path."""

    def test_marcar_revisado_writes_historial(self, client, db, rol_ventas):
        user = _make_user(db, rol_ventas)
        _give_permiso(db, user, "tickets.ver")
        sector = _make_sector(db)
        _, tipo, estado = _make_workflow_and_tipo(db, sector)
        ticket = _make_ticket(db, sector=sector, tipo=tipo, estado=estado, creador=user)

        resp = client.post(
            f"/api/tickets/tickets/marcar-revisado/{ticket.id}",
            headers=_headers(user),
        )

        assert resp.status_code == 200
        assert resp.json() == {"ok": True}

        historial = (
            db.query(HistorialTicket)
            .filter(HistorialTicket.ticket_id == ticket.id, HistorialTicket.accion == "revisado")
            .all()
        )
        assert len(historial) == 1

    def test_single_segment_path_is_not_the_real_route(self, client, db, rol_ventas):
        """Regression guard: the OLD (buggy) single-segment path the frontend
        used to call must NOT resolve — it 404s. This is the exact shape of
        the bug this PR fixes in api.js."""
        user = _make_user(db, rol_ventas)
        _give_permiso(db, user, "tickets.ver")
        sector = _make_sector(db)
        _, tipo, estado = _make_workflow_and_tipo(db, sector)
        ticket = _make_ticket(db, sector=sector, tipo=tipo, estado=estado, creador=user)

        resp = client.post(
            f"/api/tickets/marcar-revisado/{ticket.id}",
            headers=_headers(user),
        )

        assert resp.status_code == 404
