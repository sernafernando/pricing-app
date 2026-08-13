"""
Tests for GET /tickets/tickets/{ticket_id}/asignables.

Fixes a production defect: tickets sitting in the Inbox sector could not be
assigned to anyone. `TicketDetail.jsx`'s assign dropdown loaded
`sectoresAPI.listarUsuarios(ticket.sector.id)` — the ticket's OWN sector
members — which is correct for a real sector but wrong for the Inbox: a
shared triage queue that nobody "belongs" to (0 members by design).

This endpoint answers the actual question ("who can I assign this ticket
to?") instead of the proxy question ("who belongs to this sector?"):
- Normal sector -> its active members (unchanged behaviour).
- Inbox sector  -> distinct active members of ANY sector (shared queue).

The correspondence test (`TestAsignablesMatchesAsignarAcceptance`) is the
one that matters: every user `/asignables` offers for a ticket must be
accepted by `POST /asignar` for that same ticket, and no one else. The read
side and the write side must never be able to drift independently.

Run:
    cd backend && source venv/bin/activate && pytest tests/tickets/test_ticket_asignables.py -v
"""

from app.models.permiso import Permiso, UsuarioPermisoOverride
from app.models.rol import Rol
from app.models.usuario import Usuario, RolUsuario, AuthProvider
from app.core.security import get_password_hash, create_access_token
from app.tickets.models.sector import Sector
from app.tickets.models.sector_usuario import SectorUsuario
from app.tickets.models.ticket import Ticket, PrioridadTicket
from app.tickets.models.tipo_ticket import TipoTicket
from app.tickets.models.workflow import EstadoTicket, Workflow

INBOX_SECTOR_CODIGO = "INBOX"

_seq = [0]


def _make_user(db, rol: Rol, *, activo: bool = True) -> Usuario:
    _seq[0] += 1
    u = Usuario(
        username=f"asig_user_{_seq[0]}",
        email=f"asig_{_seq[0]}@test.com",
        nombre=f"Asig User {_seq[0]}",
        password_hash=get_password_hash("pass"),
        rol=RolUsuario.VENTAS,
        rol_id=rol.id,
        auth_provider=AuthProvider.LOCAL,
        activo=activo,
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


def _make_sector(db, *, codigo: str | None = None) -> Sector:
    _seq[0] += 1
    codigo = codigo or f"ASIG_SECT_{_seq[0]}"
    s = Sector(codigo=codigo, nombre=f"Sector {codigo}", activo=True, configuracion={})
    db.add(s)
    db.flush()
    return s


def _make_workflow(db, sector: Sector) -> tuple[TipoTicket, EstadoTicket]:
    """Minimal 1-state workflow — enough to hang a ticket off, transitions
    are irrelevant to this feature."""
    wf = Workflow(sector_id=sector.id, nombre="WF Asignables Test", es_default=True, activo=True)
    db.add(wf)
    db.flush()

    estado = EstadoTicket(
        workflow_id=wf.id, codigo="abierto", nombre="Abierto", orden=1, es_inicial=True, es_final=False
    )
    db.add(estado)
    db.flush()

    tipo = TipoTicket(sector_id=sector.id, codigo="consulta", nombre="Consulta", workflow_id=wf.id)
    db.add(tipo)
    db.flush()

    return tipo, estado


def _make_ticket(db, *, sector: Sector, tipo: TipoTicket, estado: EstadoTicket, creador: Usuario) -> Ticket:
    t = Ticket(
        titulo="Asignables Test Ticket",
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


def _add_membership(db, sector: Sector, user: Usuario, *, activo: bool = True) -> SectorUsuario:
    su = SectorUsuario(sector_id=sector.id, usuario_id=user.id, activo=activo)
    db.add(su)
    db.flush()
    return su


ASIGNABLES_ENDPOINT = "/api/tickets/tickets/{id}/asignables"
ASIGNAR_ENDPOINT = "/api/tickets/tickets/{id}/asignar"


class TestNormalSectorOffersOnlyItsOwnActiveMembers:
    """SC: a ticket in a normal sector offers exactly that sector's active
    members — never members of an unrelated sector."""

    def test_offers_own_sector_active_members_only(self, client, db, rol_ventas):
        gestor = _make_user(db, rol_ventas)
        _give_permiso(db, gestor, "tickets.gestionar")

        sector_a = _make_sector(db)
        sector_b = _make_sector(db)
        tipo_a, estado_a = _make_workflow(db, sector_a)
        _make_workflow(db, sector_b)

        miembro_a = _make_user(db, rol_ventas)
        miembro_b = _make_user(db, rol_ventas)
        _add_membership(db, sector_a, miembro_a)
        _add_membership(db, sector_b, miembro_b)

        ticket = _make_ticket(db, sector=sector_a, tipo=tipo_a, estado=estado_a, creador=gestor)

        resp = client.get(ASIGNABLES_ENDPOINT.format(id=ticket.id), headers=_headers(gestor))

        assert resp.status_code == 200
        ids = {u["id"] for u in resp.json()}
        assert ids == {miembro_a.id}


class TestInboxOffersDistinctActiveMembersOfEverySector:
    """SC: a ticket in the Inbox offers the distinct active members of
    every sector, with no duplicates — the Inbox is a shared triage queue,
    nobody "belongs" to it by design."""

    def test_offers_union_of_active_members_no_duplicates(self, client, db, rol_ventas):
        gestor = _make_user(db, rol_ventas)
        _give_permiso(db, gestor, "tickets.gestionar")

        inbox = _make_sector(db, codigo=INBOX_SECTOR_CODIGO)
        sector_a = _make_sector(db)
        sector_b = _make_sector(db)
        tipo_inbox, estado_inbox = _make_workflow(db, inbox)
        _make_workflow(db, sector_a)
        _make_workflow(db, sector_b)

        miembro_a = _make_user(db, rol_ventas)
        miembro_b = _make_user(db, rol_ventas)
        # Member of BOTH sectors -> must appear exactly once, not twice.
        miembro_ambos = _make_user(db, rol_ventas)
        _add_membership(db, sector_a, miembro_a)
        _add_membership(db, sector_b, miembro_b)
        _add_membership(db, sector_a, miembro_ambos)
        _add_membership(db, sector_b, miembro_ambos)

        ticket = _make_ticket(db, sector=inbox, tipo=tipo_inbox, estado=estado_inbox, creador=gestor)

        resp = client.get(ASIGNABLES_ENDPOINT.format(id=ticket.id), headers=_headers(gestor))

        assert resp.status_code == 200
        payload = resp.json()
        ids = [u["id"] for u in payload]
        assert set(ids) == {miembro_a.id, miembro_b.id, miembro_ambos.id}
        assert len(ids) == len(set(ids))  # no duplicates despite dual membership


class TestInactiveMembershipsExcluded:
    """SC: inactive memberships (soft-removed from a sector) and inactive
    users are excluded, in both the normal-sector and Inbox cases."""

    def test_inactive_membership_excluded_from_normal_sector(self, client, db, rol_ventas):
        gestor = _make_user(db, rol_ventas)
        _give_permiso(db, gestor, "tickets.gestionar")

        sector = _make_sector(db)
        tipo, estado = _make_workflow(db, sector)

        activo = _make_user(db, rol_ventas)
        removido = _make_user(db, rol_ventas)
        _add_membership(db, sector, activo)
        _add_membership(db, sector, removido, activo=False)

        ticket = _make_ticket(db, sector=sector, tipo=tipo, estado=estado, creador=gestor)

        resp = client.get(ASIGNABLES_ENDPOINT.format(id=ticket.id), headers=_headers(gestor))

        assert resp.status_code == 200
        ids = {u["id"] for u in resp.json()}
        assert ids == {activo.id}

    def test_inactive_user_excluded_from_inbox(self, client, db, rol_ventas):
        gestor = _make_user(db, rol_ventas)
        _give_permiso(db, gestor, "tickets.gestionar")

        inbox = _make_sector(db, codigo=INBOX_SECTOR_CODIGO)
        sector = _make_sector(db)
        tipo_inbox, estado_inbox = _make_workflow(db, inbox)
        _make_workflow(db, sector)

        activo = _make_user(db, rol_ventas)
        inactivo = _make_user(db, rol_ventas, activo=False)
        _add_membership(db, sector, activo)
        _add_membership(db, sector, inactivo)  # membership itself is active, user is not

        ticket = _make_ticket(db, sector=inbox, tipo=tipo_inbox, estado=estado_inbox, creador=gestor)

        resp = client.get(ASIGNABLES_ENDPOINT.format(id=ticket.id), headers=_headers(gestor))

        assert resp.status_code == 200
        ids = {u["id"] for u in resp.json()}
        assert ids == {activo.id}


class TestAsignablesRequiresGestionar:
    """SC: a user without `tickets.gestionar` cannot read `/asignables` —
    it must not be more permissive than the write endpoint it feeds."""

    def test_no_permiso_gets_403(self, client, db, rol_ventas):
        sin_permiso = _make_user(db, rol_ventas)

        sector = _make_sector(db)
        tipo, estado = _make_workflow(db, sector)
        ticket = _make_ticket(db, sector=sector, tipo=tipo, estado=estado, creador=sin_permiso)

        resp = client.get(ASIGNABLES_ENDPOINT.format(id=ticket.id), headers=_headers(sin_permiso))

        assert resp.status_code == 403


class TestAsignablesMatchesAsignarAcceptance:
    """The test that matters: every user `/asignables` offers for a given
    ticket is actually ACCEPTED by `POST /asignar` for that same ticket,
    and a user NOT offered is REJECTED. Read and write must not drift."""

    def test_every_offered_user_is_accepted_by_asignar_normal_sector(self, client, db, rol_ventas):
        gestor = _make_user(db, rol_ventas)
        _give_permiso(db, gestor, "tickets.gestionar")

        sector = _make_sector(db)
        tipo, estado = _make_workflow(db, sector)
        miembro = _make_user(db, rol_ventas)
        _add_membership(db, sector, miembro)

        ticket = _make_ticket(db, sector=sector, tipo=tipo, estado=estado, creador=gestor)

        offered = client.get(ASIGNABLES_ENDPOINT.format(id=ticket.id), headers=_headers(gestor)).json()
        assert {u["id"] for u in offered} == {miembro.id}

        for u in offered:
            resp = client.post(
                ASIGNAR_ENDPOINT.format(id=ticket.id),
                json={"usuario_id": u["id"]},
                headers=_headers(gestor),
            )
            assert resp.status_code == 200, resp.json()

    def test_every_offered_user_is_accepted_by_asignar_inbox(self, client, db, rol_ventas):
        gestor = _make_user(db, rol_ventas)
        _give_permiso(db, gestor, "tickets.gestionar")

        inbox = _make_sector(db, codigo=INBOX_SECTOR_CODIGO)
        sector_a = _make_sector(db)
        sector_b = _make_sector(db)
        tipo_inbox, estado_inbox = _make_workflow(db, inbox)
        _make_workflow(db, sector_a)
        _make_workflow(db, sector_b)

        miembro_a = _make_user(db, rol_ventas)
        miembro_b = _make_user(db, rol_ventas)
        _add_membership(db, sector_a, miembro_a)
        _add_membership(db, sector_b, miembro_b)

        ticket = _make_ticket(db, sector=inbox, tipo=tipo_inbox, estado=estado_inbox, creador=gestor)

        offered = client.get(ASIGNABLES_ENDPOINT.format(id=ticket.id), headers=_headers(gestor)).json()
        assert {u["id"] for u in offered} == {miembro_a.id, miembro_b.id}

        for u in offered:
            resp = client.post(
                ASIGNAR_ENDPOINT.format(id=ticket.id),
                json={"usuario_id": u["id"]},
                headers=_headers(gestor),
            )
            assert resp.status_code == 200, resp.json()

    def test_user_not_offered_is_rejected_by_asignar_normal_sector(self, client, db, rol_ventas):
        """A user who belongs to a DIFFERENT sector (so /asignables never
        offers them for THIS ticket) must be rejected by /asignar too."""
        gestor = _make_user(db, rol_ventas)
        _give_permiso(db, gestor, "tickets.gestionar")

        sector_a = _make_sector(db)
        sector_b = _make_sector(db)
        tipo_a, estado_a = _make_workflow(db, sector_a)
        _make_workflow(db, sector_b)

        ajeno = _make_user(db, rol_ventas)
        _add_membership(db, sector_b, ajeno)

        ticket = _make_ticket(db, sector=sector_a, tipo=tipo_a, estado=estado_a, creador=gestor)

        offered_ids = {
            u["id"] for u in client.get(ASIGNABLES_ENDPOINT.format(id=ticket.id), headers=_headers(gestor)).json()
        }
        assert ajeno.id not in offered_ids

        resp = client.post(
            ASIGNAR_ENDPOINT.format(id=ticket.id),
            json={"usuario_id": ajeno.id},
            headers=_headers(gestor),
        )
        assert resp.status_code == 400
        assert "no puede ser asignado" in resp.json()["error"]["message"]
