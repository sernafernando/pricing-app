"""
Tests for the `agente-ia` service-user authentication boundary
(tickets-ai-triage PR 6).

Covers the `backend/tickets-triage` spec's "Service-User Authentication
Boundary" requirement (obs #1304/#1303): a seeded `Usuario`
(`username='agente-ia'`, `password_hash=NULL`, role `AGENTE_IA` holding only
`tickets.ver` + `tickets.agente`) authenticates via the standard JWT path,
is refused cleanly by `/auth/login`, has the transition graph enforced like
any other actor (not privileged), is denied outside its granted scope, and
is killable via `usuario.activo=False`.

Tasks 6.1/6.2 (the login guard itself) already merged to `main` via PR 1 —
`test_login_rejected_cleanly` here only verifies that guard still holds for
THIS specific seeded user, it is not the guard's own regression test.

Written FIRST (RED phase) per strict TDD.

Run:
    cd backend && source venv/bin/activate && pytest tests/tickets/test_agente_ia_auth.py -v
"""

from datetime import timedelta

from app.core.security import create_access_token, get_password_hash
from app.models.permiso import Permiso, RolPermisoBase
from app.models.rol import Rol
from app.models.usuario import AuthProvider, RolUsuario, Usuario
from app.tickets.models.sector import Sector
from app.tickets.models.ticket import PrioridadTicket, Ticket
from app.tickets.models.tipo_ticket import TipoTicket
from app.tickets.models.workflow import EstadoTicket, TransicionEstado, Workflow

_seq = [0]


def _make_permiso(db, codigo: str) -> Permiso:
    p = db.query(Permiso).filter(Permiso.codigo == codigo).first()
    if not p:
        p = Permiso(codigo=codigo, nombre=codigo, categoria="tickets")
        db.add(p)
        db.flush()
    return p


def _make_agente_ia_user(db) -> Usuario:
    """Mirrors 20260807_seed_agente_ia_service_user.py's shape: a role
    holding only tickets.ver + tickets.agente (NOT tickets.gestionar), and a
    user with password_hash=NULL, activo=True."""
    _seq[0] += 1
    rol = Rol(codigo=f"AGENTE_IA_{_seq[0]}", nombre="Agente IA", es_sistema=True, orden=900, activo=True)
    db.add(rol)
    db.flush()

    for codigo in ("tickets.ver", "tickets.agente"):
        permiso = _make_permiso(db, codigo)
        db.add(RolPermisoBase(rol_id=rol.id, permiso_id=permiso.id))
    db.flush()

    user = Usuario(
        username="agente-ia",
        nombre="Agente IA",
        password_hash=None,
        rol=None,
        rol_id=rol.id,
        auth_provider=AuthProvider.LOCAL,
        activo=True,
    )
    db.add(user)
    db.flush()
    return user


def _make_rol_ventas(db) -> Rol:
    _seq[0] += 1
    rol = Rol(codigo=f"VENTAS_AGT_{_seq[0]}", nombre="Ventas", orden=10, activo=True)
    db.add(rol)
    db.flush()
    return rol


def _make_creador(db) -> Usuario:
    _seq[0] += 1
    u = Usuario(
        username=f"creador_{_seq[0]}",
        email=f"creador_{_seq[0]}@test.com",
        nombre=f"Creador {_seq[0]}",
        password_hash=get_password_hash("pass"),
        rol=RolUsuario.VENTAS,
        rol_id=_make_rol_ventas(db).id,
        auth_provider=AuthProvider.LOCAL,
        activo=True,
    )
    db.add(u)
    db.flush()
    return u


def _agente_headers(user: Usuario) -> dict:
    """A real 90-day service token, minted exactly like
    scripts/mint_agente_token.py mints one."""
    token = create_access_token({"sub": user.username}, timedelta(days=90))
    return {"Authorization": f"Bearer {token}"}


def _make_sector(db) -> Sector:
    _seq[0] += 1
    s = Sector(codigo=f"AGT_SECT_{_seq[0]}", nombre=f"Agente Sector {_seq[0]}", activo=True)
    db.add(s)
    db.flush()
    return s


def _make_workflow(db, sector: Sector, *, with_transicion: bool):
    """2-state workflow, edge configurable — same shape as
    test_workflow_enforcement.py's `_make_workflow` (kept local per this
    test suite's own convention, not imported)."""
    wf = Workflow(sector_id=sector.id, nombre="Agente WF Test", es_default=True, activo=True)
    db.add(wf)
    db.flush()

    estado_a = EstadoTicket(workflow_id=wf.id, codigo="abierto", nombre="Abierto", orden=1, es_inicial=True)
    estado_b = EstadoTicket(workflow_id=wf.id, codigo="cerrado", nombre="Cerrado", orden=2, es_final=True)
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

    return tipo, estado_a, estado_b


def _make_ticket(db, *, sector: Sector, tipo: TipoTicket, estado: EstadoTicket, creador: Usuario) -> Ticket:
    t = Ticket(
        titulo="Agente Test Ticket",
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


class TestLoginRejectedCleanlyForAgenteIa:
    """SC: `POST /auth/login` for agente-ia (password_hash=NULL) fails with
    401/400, never an unhandled bcrypt.checkpw(None, ...) exception.

    The guard itself (auth.py's NULL-hash check) already merged to `main`
    via PR 1 — this only verifies it still holds for THIS specific seeded
    user, per the design's own open question / merge-blocker note."""

    def test_login_rejected_cleanly(self, client, db):
        _make_agente_ia_user(db)

        resp = client.post("/api/auth/login", json={"username": "agente-ia", "password": "cualquier-cosa"})

        # `client` uses raise_server_exceptions=False (conftest.py) — an
        # unhandled AttributeError from bcrypt.checkpw(None, ...) would NOT
        # propagate as a Python exception here, it would surface as some
        # non-2xx status. Asserting the EXACT safe status (not just
        # `!= 200`) is what actually distinguishes "handled 401" from "the
        # guard regressed and this became a 500".
        assert resp.status_code in (400, 401)
        assert resp.status_code != 500


class TestServiceTokenTransicionScope:
    """SC: service token succeeds on POST /transicion, and the transition
    graph is STILL enforced for this actor like any other — the agent is not
    privileged."""

    def test_valid_transition_succeeds(self, client, db):
        agente = _make_agente_ia_user(db)
        creador = _make_creador(db)
        sector = _make_sector(db)
        tipo, estado_a, estado_b = _make_workflow(db, sector, with_transicion=True)
        ticket = _make_ticket(db, sector=sector, tipo=tipo, estado=estado_a, creador=creador)

        resp = client.post(
            f"/api/tickets/tickets/{ticket.id}/transicion",
            json={"nuevo_estado_id": estado_b.id},
            headers=_agente_headers(agente),
        )

        assert resp.status_code == 200
        db.refresh(ticket)
        assert ticket.estado_id == estado_b.id

    def test_graph_still_enforced_unconfigured_transition_rejected(self, client, db):
        """Same actor, but the edge does not exist — 409, exactly like any
        human user. Proves 'the agent is not privileged', not just that it
        can authenticate."""
        agente = _make_agente_ia_user(db)
        creador = _make_creador(db)
        sector = _make_sector(db)
        tipo, estado_a, estado_b = _make_workflow(db, sector, with_transicion=False)
        ticket = _make_ticket(db, sector=sector, tipo=tipo, estado=estado_a, creador=creador)

        resp = client.post(
            f"/api/tickets/tickets/{ticket.id}/transicion",
            json={"nuevo_estado_id": estado_b.id},
            headers=_agente_headers(agente),
        )

        assert resp.status_code == 409
        db.refresh(ticket)
        assert ticket.estado_id == estado_a.id


class TestServiceTokenDeniedOutsideGrantedScope:
    """SC: the same JWT fails 403 on a route requiring tickets.gestionar
    (delete attachment) and on an admin route (tickets.admin)."""

    def test_403_on_tickets_gestionar_only_route(self, client, db):
        agente = _make_agente_ia_user(db)

        resp = client.delete(
            "/api/tickets/tickets/999999/adjuntos/999999",
            headers=_agente_headers(agente),
        )

        # Permission is checked BEFORE the adjunto lookup in
        # eliminar_adjunto (tickets.py) — a bogus id still proves the 403
        # gate, not a 404 masking it.
        assert resp.status_code == 403

    def test_403_on_admin_route(self, client, db):
        agente = _make_agente_ia_user(db)

        resp = client.post(
            "/api/tickets/sectores",
            json={"codigo": "NOPE", "nombre": "No debería poder crear esto"},
            headers=_agente_headers(agente),
        )

        assert resp.status_code == 403


class TestKillSwitch:
    """SC: usuario.activo=False -> 401 on the next request with the SAME
    JWT, no new token needed, no deploy — deps.py:44-45."""

    def test_deactivation_kills_the_existing_token(self, client, db):
        agente = _make_agente_ia_user(db)
        headers = _agente_headers(agente)

        # Sanity: token works while active.
        ok = client.get("/api/auth/me", headers=headers)
        assert ok.status_code == 200

        agente.activo = False
        db.flush()

        resp = client.get("/api/auth/me", headers=headers)
        assert resp.status_code == 401


class TestServiceUserCanComment:
    """SC: agente-ia posts a comment successfully — it resolves to a real
    Usuario row, satisfying tickets_comentarios.usuario_id NOT NULL."""

    def test_agente_can_post_comment(self, client, db):
        agente = _make_agente_ia_user(db)
        creador = _make_creador(db)
        sector = _make_sector(db)
        tipo, estado_a, _ = _make_workflow(db, sector, with_transicion=False)
        ticket = _make_ticket(db, sector=sector, tipo=tipo, estado=estado_a, creador=creador)

        resp = client.post(
            f"/api/tickets/tickets/{ticket.id}/comentarios",
            json={"contenido": "Clasificado automáticamente por triage IA.", "es_interno": False},
            headers=_agente_headers(agente),
        )

        assert resp.status_code == 201
        assert resp.json()["contenido"] == "Clasificado automáticamente por triage IA."
