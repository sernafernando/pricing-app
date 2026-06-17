"""
Tests for GET /tickets/tickets/mis-pendientes/count — badge breakdown.

Covers REQ-01 through REQ-09, all 11 scenarios (SC-01 to SC-11).
Written FIRST (RED phase) per strict TDD.

Run:
    cd backend && source venv/bin/activate && pytest tests/tickets/test_badge_count.py -v
"""

from datetime import datetime, UTC, timedelta

from app.models.permiso import Permiso, UsuarioPermisoOverride
from app.models.rol import Rol
from app.models.usuario import Usuario, RolUsuario, AuthProvider
from app.core.security import get_password_hash, create_access_token
from app.tickets.models.asignacion_ticket import AsignacionTicket, TipoAsignacion
from app.tickets.models.historial_ticket import HistorialTicket
from app.tickets.models.sector import Sector
from app.tickets.models.sector_usuario import SectorUsuario
from app.tickets.models.ticket import Ticket, PrioridadTicket
from app.tickets.models.tipo_ticket import TipoTicket
from app.tickets.models.workflow import EstadoTicket, Workflow


# ---------------------------------------------------------------------------
# Helper builders
# ---------------------------------------------------------------------------

_user_counter = [0]


def _make_user(db, rol_ventas: Rol, username_suffix: str = "") -> Usuario:
    _user_counter[0] += 1
    suffix = username_suffix or str(_user_counter[0])
    u = Usuario(
        username=f"badge_user_{suffix}",
        email=f"badge_{suffix}@test.com",
        nombre=f"Badge User {suffix}",
        password_hash=get_password_hash("pass"),
        rol=RolUsuario.VENTAS,
        rol_id=rol_ventas.id,
        auth_provider=AuthProvider.LOCAL,
        activo=True,
    )
    db.add(u)
    db.flush()
    return u


def _make_sector(db) -> Sector:
    _user_counter[0] += 1
    s = Sector(
        codigo=f"SECT_{_user_counter[0]}",
        nombre=f"Sector {_user_counter[0]}",
        activo=True,
    )
    db.add(s)
    db.flush()
    return s


def _make_workflow_and_tipo(db, sector: Sector) -> tuple[Workflow, TipoTicket, EstadoTicket, EstadoTicket]:
    wf = Workflow(sector_id=sector.id, nombre="WF Test", es_default=True, activo=True)
    db.add(wf)
    db.flush()

    estado_abierto = EstadoTicket(
        workflow_id=wf.id,
        codigo="abierto",
        nombre="Abierto",
        orden=1,
        es_inicial=True,
        es_final=False,
    )
    estado_cerrado = EstadoTicket(
        workflow_id=wf.id,
        codigo="cerrado",
        nombre="Cerrado",
        orden=2,
        es_inicial=False,
        es_final=True,
    )
    db.add_all([estado_abierto, estado_cerrado])
    db.flush()

    tipo = TipoTicket(sector_id=sector.id, codigo="consulta", nombre="Consulta", workflow_id=wf.id)
    db.add(tipo)
    db.flush()

    return wf, tipo, estado_abierto, estado_cerrado


def _make_ticket(db, *, sector: Sector, tipo: TipoTicket, estado: EstadoTicket, creador: Usuario) -> Ticket:
    t = Ticket(
        titulo="Test Ticket",
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


def _add_historial(db, *, ticket: Ticket, usuario: Usuario, accion: str, fecha=None) -> HistorialTicket:
    h = HistorialTicket(
        ticket_id=ticket.id,
        usuario_id=usuario.id,
        accion=accion,
        descripcion=f"Test: {accion}",
        cambios={},
        fecha=fecha or datetime.now(UTC),
    )
    db.add(h)
    db.flush()
    return h


def _assign(db, *, ticket: Ticket, to_user: Usuario, by_user: Usuario, activa: bool = True) -> AsignacionTicket:
    a = AsignacionTicket(
        ticket_id=ticket.id,
        asignado_a_id=to_user.id,
        asignado_por_id=by_user.id,
        tipo=TipoAsignacion.MANUAL,
        fecha_finalizacion=None if activa else datetime.now(UTC),
    )
    db.add(a)
    db.flush()
    return a


def _give_permiso(db, user: Usuario, codigo: str) -> None:
    """Grant a permission to user via override (concedido=True)."""
    permiso = db.query(Permiso).filter(Permiso.codigo == codigo).first()
    if not permiso:
        permiso = Permiso(codigo=codigo, nombre=codigo, categoria="tickets")
        db.add(permiso)
        db.flush()

    override = UsuarioPermisoOverride(
        usuario_id=user.id,
        permiso_id=permiso.id,
        concedido=True,
    )
    db.add(override)
    db.flush()


def _headers(user: Usuario) -> dict:
    token = create_access_token(data={"sub": user.username})
    return {"Authorization": f"Bearer {token}"}


ENDPOINT = "/api/tickets/tickets/mis-pendientes/count"


# ---------------------------------------------------------------------------
# SC-01 / TC-01: sin_asignar — open ticket with no active assignment
# ---------------------------------------------------------------------------


class TestSinAsignar:
    def test_sin_asignar_no_assignment(self, client, db, rol_ventas):
        """SC-01: Open unassigned ticket in scope → sin_asignar=1."""
        user = _make_user(db, rol_ventas, "sc01")
        _give_permiso(db, user, "tickets.ver")
        sector = _make_sector(db)
        _, tipo, abierto, _ = _make_workflow_and_tipo(db, sector)
        db.add(SectorUsuario(sector_id=sector.id, usuario_id=user.id, activo=True))
        db.flush()

        ticket = _make_ticket(db, sector=sector, tipo=tipo, estado=abierto, creador=user)
        # Give it activity so con_actividad_nueva is non-zero (helps validate independence)
        _add_historial(db, ticket=ticket, usuario=user, accion="created")

        resp = client.get(ENDPOINT, headers=_headers(user))
        assert resp.status_code == 200
        body = resp.json()
        assert body["sin_asignar"] >= 1
        assert body["asignados_a_mi"] == 0
        assert body["asignados_a_otros"] == 0


# ---------------------------------------------------------------------------
# SC-02 / TC-02: asignados_a_mi
# ---------------------------------------------------------------------------


class TestAsignadosAMi:
    def test_asignados_a_mi_active_assignment(self, client, db, rol_ventas):
        """SC-02: Ticket with active assignment to me → asignados_a_mi=1, sin_asignar=0."""
        user = _make_user(db, rol_ventas, "sc02")
        _give_permiso(db, user, "tickets.ver")
        sector = _make_sector(db)
        _, tipo, abierto, _ = _make_workflow_and_tipo(db, sector)
        db.add(SectorUsuario(sector_id=sector.id, usuario_id=user.id, activo=True))
        db.flush()

        ticket = _make_ticket(db, sector=sector, tipo=tipo, estado=abierto, creador=user)
        _add_historial(db, ticket=ticket, usuario=user, accion="created")
        _assign(db, ticket=ticket, to_user=user, by_user=user, activa=True)

        resp = client.get(ENDPOINT, headers=_headers(user))
        assert resp.status_code == 200
        body = resp.json()
        assert body["asignados_a_mi"] >= 1
        assert body["sin_asignar"] == 0
        assert body["asignados_a_otros"] == 0


# ---------------------------------------------------------------------------
# SC-03 / TC-03: asignados_a_otros (tickets.ver user)
# ---------------------------------------------------------------------------


class TestAsignadosAOtros:
    def test_asignados_a_otros_con_permiso(self, client, db, rol_ventas):
        """SC-03: Ticket assigned to another user → asignados_a_otros=1 for tickets.ver user."""
        me = _make_user(db, rol_ventas, "sc03_me")
        other = _make_user(db, rol_ventas, "sc03_other")
        _give_permiso(db, me, "tickets.ver")
        sector = _make_sector(db)
        _, tipo, abierto, _ = _make_workflow_and_tipo(db, sector)
        db.add(SectorUsuario(sector_id=sector.id, usuario_id=me.id, activo=True))
        db.flush()

        ticket = _make_ticket(db, sector=sector, tipo=tipo, estado=abierto, creador=me)
        _add_historial(db, ticket=ticket, usuario=me, accion="created")
        _assign(db, ticket=ticket, to_user=other, by_user=me, activa=True)

        resp = client.get(ENDPOINT, headers=_headers(me))
        assert resp.status_code == 200
        body = resp.json()
        assert body["asignados_a_otros"] >= 1
        assert body["sin_asignar"] == 0
        assert body["asignados_a_mi"] == 0


# ---------------------------------------------------------------------------
# SC-04 / TC-04: asignados_a_otros = 0 without tickets.ver
# ---------------------------------------------------------------------------


class TestAsignadosAOtrosSinPermiso:
    def test_asignados_a_otros_sin_permiso_es_cero(self, client, db, rol_ventas):
        """SC-04: Non-tickets.ver user → asignados_a_otros always 0."""
        me = _make_user(db, rol_ventas, "sc04_me")
        other = _make_user(db, rol_ventas, "sc04_other")
        # me does NOT get tickets.ver
        sector = _make_sector(db)
        _, tipo, abierto, _ = _make_workflow_and_tipo(db, sector)

        ticket = _make_ticket(db, sector=sector, tipo=tipo, estado=abierto, creador=me)
        _add_historial(db, ticket=ticket, usuario=me, accion="created")
        _assign(db, ticket=ticket, to_user=other, by_user=me, activa=True)

        resp = client.get(ENDPOINT, headers=_headers(me))
        assert resp.status_code == 200
        body = resp.json()
        assert body["asignados_a_otros"] == 0


# ---------------------------------------------------------------------------
# SC-05 / TC-05: con_actividad_nueva with prior revisado
# ---------------------------------------------------------------------------


class TestConActividadNueva:
    def test_con_actividad_nueva_con_revisado_previo(self, client, db, rol_ventas):
        """SC-05: Activity newer than last revisado → con_actividad_nueva=1."""
        user = _make_user(db, rol_ventas, "sc05")
        _give_permiso(db, user, "tickets.ver")
        sector = _make_sector(db)
        _, tipo, abierto, _ = _make_workflow_and_tipo(db, sector)
        db.add(SectorUsuario(sector_id=sector.id, usuario_id=user.id, activo=True))
        db.flush()

        ticket = _make_ticket(db, sector=sector, tipo=tipo, estado=abierto, creador=user)
        t_revision = datetime.now(UTC) - timedelta(hours=2)
        t_actividad = datetime.now(UTC) - timedelta(hours=1)

        _add_historial(db, ticket=ticket, usuario=user, accion="revisado", fecha=t_revision)
        _add_historial(db, ticket=ticket, usuario=user, accion="comentado", fecha=t_actividad)

        resp = client.get(ENDPOINT, headers=_headers(user))
        assert resp.status_code == 200
        assert resp.json()["con_actividad_nueva"] >= 1

    def test_con_actividad_nueva_sin_revisado(self, client, db, rol_ventas):
        """SC-06: No revisado entry + activity exists → con_actividad_nueva=1."""
        user = _make_user(db, rol_ventas, "sc06")
        _give_permiso(db, user, "tickets.ver")
        sector = _make_sector(db)
        _, tipo, abierto, _ = _make_workflow_and_tipo(db, sector)
        db.add(SectorUsuario(sector_id=sector.id, usuario_id=user.id, activo=True))
        db.flush()

        ticket = _make_ticket(db, sector=sector, tipo=tipo, estado=abierto, creador=user)
        _add_historial(db, ticket=ticket, usuario=user, accion="created")

        resp = client.get(ENDPOINT, headers=_headers(user))
        assert resp.status_code == 200
        assert resp.json()["con_actividad_nueva"] >= 1

    def test_con_actividad_nueva_no_triggered_cuando_revisado_posterior(self, client, db, rol_ventas):
        """SC-07: Revisado AFTER activity → con_actividad_nueva=0 for that ticket."""
        user = _make_user(db, rol_ventas, "sc07")
        _give_permiso(db, user, "tickets.ver")
        sector = _make_sector(db)
        _, tipo, abierto, _ = _make_workflow_and_tipo(db, sector)
        db.add(SectorUsuario(sector_id=sector.id, usuario_id=user.id, activo=True))
        db.flush()

        ticket = _make_ticket(db, sector=sector, tipo=tipo, estado=abierto, creador=user)
        t_actividad = datetime.now(UTC) - timedelta(hours=2)
        t_revision = datetime.now(UTC) - timedelta(hours=1)

        _add_historial(db, ticket=ticket, usuario=user, accion="comentado", fecha=t_actividad)
        _add_historial(db, ticket=ticket, usuario=user, accion="revisado", fecha=t_revision)

        resp = client.get(ENDPOINT, headers=_headers(user))
        assert resp.status_code == 200
        assert resp.json()["con_actividad_nueva"] == 0


# ---------------------------------------------------------------------------
# SC-08 / TC-08: Overlap — asignados_a_mi AND con_actividad_nueva
# ---------------------------------------------------------------------------


class TestOverlap:
    def test_overlap_asignados_a_mi_y_actividad(self, client, db, rol_ventas):
        """SC-08: Ticket assigned to me + new activity → counted in BOTH."""
        user = _make_user(db, rol_ventas, "sc08")
        _give_permiso(db, user, "tickets.ver")
        sector = _make_sector(db)
        _, tipo, abierto, _ = _make_workflow_and_tipo(db, sector)
        db.add(SectorUsuario(sector_id=sector.id, usuario_id=user.id, activo=True))
        db.flush()

        ticket = _make_ticket(db, sector=sector, tipo=tipo, estado=abierto, creador=user)
        _add_historial(db, ticket=ticket, usuario=user, accion="created")
        _assign(db, ticket=ticket, to_user=user, by_user=user, activa=True)

        resp = client.get(ENDPOINT, headers=_headers(user))
        assert resp.status_code == 200
        body = resp.json()
        assert body["asignados_a_mi"] >= 1
        assert body["con_actividad_nueva"] >= 1
        # pendientes = sin_asignar + asignados_a_mi (ticket counted only once in asignados_a_mi)
        assert body["pendientes"] == body["sin_asignar"] + body["asignados_a_mi"]


# ---------------------------------------------------------------------------
# SC-09 / TC-09: pendientes arithmetic invariant
# ---------------------------------------------------------------------------


class TestPendientesArithmetic:
    def test_pendientes_equals_sin_asignar_plus_asignados_a_mi(self, client, db, rol_ventas):
        """SC-09: pendientes == sin_asignar + asignados_a_mi in all states."""
        user = _make_user(db, rol_ventas, "sc09")
        _give_permiso(db, user, "tickets.ver")
        sector = _make_sector(db)
        _, tipo, abierto, _ = _make_workflow_and_tipo(db, sector)
        db.add(SectorUsuario(sector_id=sector.id, usuario_id=user.id, activo=True))
        db.flush()

        # Create two tickets: one unassigned, one assigned to me
        t1 = _make_ticket(db, sector=sector, tipo=tipo, estado=abierto, creador=user)
        t2 = _make_ticket(db, sector=sector, tipo=tipo, estado=abierto, creador=user)
        _add_historial(db, ticket=t1, usuario=user, accion="created")
        _add_historial(db, ticket=t2, usuario=user, accion="created")
        _assign(db, ticket=t2, to_user=user, by_user=user, activa=True)

        resp = client.get(ENDPOINT, headers=_headers(user))
        assert resp.status_code == 200
        body = resp.json()
        assert body["pendientes"] == body["sin_asignar"] + body["asignados_a_mi"]


# ---------------------------------------------------------------------------
# SC-10 / TC-10: Closed ticket excluded from all fields
# ---------------------------------------------------------------------------


class TestClosedTicketExcluded:
    def test_ticket_cerrado_excluido(self, client, db, rol_ventas):
        """SC-10: Closed ticket (es_final=True) excluded from all five fields."""
        user = _make_user(db, rol_ventas, "sc10")
        _give_permiso(db, user, "tickets.ver")
        sector = _make_sector(db)
        _, tipo, abierto, cerrado = _make_workflow_and_tipo(db, sector)
        db.add(SectorUsuario(sector_id=sector.id, usuario_id=user.id, activo=True))
        db.flush()

        ticket = _make_ticket(db, sector=sector, tipo=tipo, estado=cerrado, creador=user)
        _add_historial(db, ticket=ticket, usuario=user, accion="created")

        resp = client.get(ENDPOINT, headers=_headers(user))
        assert resp.status_code == 200
        body = resp.json()
        assert body["sin_asignar"] == 0
        assert body["asignados_a_mi"] == 0
        assert body["asignados_a_otros"] == 0
        assert body["con_actividad_nueva"] == 0
        assert body["pendientes"] == 0


# ---------------------------------------------------------------------------
# SC-11 / TC-11: Scope — non-tickets.ver user sees only own tickets
# ---------------------------------------------------------------------------


class TestScopeNonPermiso:
    def test_scope_sin_permiso_solo_ve_propios(self, client, db, rol_ventas):
        """SC-11: Non-tickets.ver user sees only tickets they created."""
        me = _make_user(db, rol_ventas, "sc11_me")
        other = _make_user(db, rol_ventas, "sc11_other")
        # me does NOT get tickets.ver
        sector = _make_sector(db)
        _, tipo, abierto, _ = _make_workflow_and_tipo(db, sector)
        db.add(SectorUsuario(sector_id=sector.id, usuario_id=me.id, activo=True))
        db.flush()

        # Ticket created by other in same sector — me should NOT see it
        t_other = _make_ticket(db, sector=sector, tipo=tipo, estado=abierto, creador=other)
        _add_historial(db, ticket=t_other, usuario=other, accion="created")

        # Ticket created by me — me SHOULD see it
        t_mine = _make_ticket(db, sector=sector, tipo=tipo, estado=abierto, creador=me)
        _add_historial(db, ticket=t_mine, usuario=me, accion="created")

        resp = client.get(ENDPOINT, headers=_headers(me))
        assert resp.status_code == 200
        body = resp.json()
        # Total visible tickets = sin_asignar + asignados_a_mi + asignados_a_otros
        total_visible = body["sin_asignar"] + body["asignados_a_mi"] + body["asignados_a_otros"]
        # Should only see the 1 ticket me created, not other's
        assert total_visible == 1
        assert body["sin_asignar"] == 1  # t_mine is unassigned
