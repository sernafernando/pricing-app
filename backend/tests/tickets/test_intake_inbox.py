"""
Tests for single-box intake + the seeded Inbox sector/tipo/workflow.

Covers `frontend/tickets-board` spec requirements:
- Single-Box Intake, One Required Field
- `texto_original` Is Immutable After Creation

Also locks in the process-gate concern from design #1303 §7: without the
seeded Inbox workflow (Sector INBOX / TipoTicket SIN_CLASIFICAR / Workflow
es_default=True / an initial+final EstadoTicket / a tickets_transiciones
edge), `crear_ticket` 400s at `tickets.py:381-393` before ever reaching
ticket creation — so this suite seeds that data itself (tests run against
`Base.metadata.create_all`, not real Alembic migrations) and asserts the
minimal create path actually reaches the seeded initial state.

Written FIRST (RED phase) per strict TDD.

Run:
    cd backend && source venv/bin/activate && pytest tests/tickets/test_intake_inbox.py -v
"""

from app.models.rol import Rol
from app.models.usuario import Usuario, RolUsuario, AuthProvider
from app.core.security import get_password_hash, create_access_token
from app.tickets.api.endpoints.tickets import _derivar_titulo
from app.tickets.models.sector import Sector
from app.tickets.models.ticket import Ticket
from app.tickets.models.tipo_ticket import TipoTicket
from app.tickets.models.workflow import EstadoTicket, TransicionEstado, Workflow

INBOX_SECTOR_CODIGO = "INBOX"
INBOX_TIPO_CODIGO = "SIN_CLASIFICAR"

_seq = [0]


def _make_user(db, rol: Rol) -> Usuario:
    _seq[0] += 1
    u = Usuario(
        username=f"intake_user_{_seq[0]}",
        email=f"intake_{_seq[0]}@test.com",
        nombre=f"Intake User {_seq[0]}",
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


def _seed_inbox(db) -> tuple[Sector, TipoTicket, EstadoTicket, EstadoTicket]:
    """Mirrors `20260805_seed_inbox_sector_and_workflow.py`'s data shape via
    the ORM, since tests build the schema from models (`Base.metadata`), not
    by replaying real Alembic migrations."""
    sector = Sector(codigo=INBOX_SECTOR_CODIGO, nombre="Bandeja de entrada", activo=True, configuracion={})
    db.add(sector)
    db.flush()

    wf = Workflow(sector_id=sector.id, nombre="Bandeja de entrada", es_default=True, activo=True)
    db.add(wf)
    db.flush()

    tipo = TipoTicket(sector_id=sector.id, codigo=INBOX_TIPO_CODIGO, nombre="Sin clasificar", schema_campos={})
    db.add(tipo)
    db.flush()

    estado_inicial = EstadoTicket(
        workflow_id=wf.id, codigo="nuevo", nombre="Nuevo", orden=1, es_inicial=True, es_final=False
    )
    estado_final = EstadoTicket(
        workflow_id=wf.id, codigo="cerrado", nombre="Cerrado", orden=2, es_inicial=False, es_final=True
    )
    db.add_all([estado_inicial, estado_final])
    db.flush()

    db.add(
        TransicionEstado(
            workflow_id=wf.id,
            estado_origen_id=estado_inicial.id,
            estado_destino_id=estado_final.id,
            nombre="Cerrar",
        )
    )
    db.flush()

    return sector, tipo, estado_inicial, estado_final


def _make_other_sector(db) -> tuple[Sector, TipoTicket, EstadoTicket]:
    """A non-Inbox sector with its own workflow, used to prove explicit
    sector_id/tipo_ticket_id still win over the Inbox defaults."""
    sector = Sector(codigo="OTRO_SECT", nombre="Otro Sector", activo=True, configuracion={})
    db.add(sector)
    db.flush()

    wf = Workflow(sector_id=sector.id, nombre="Otro WF", es_default=True, activo=True)
    db.add(wf)
    db.flush()

    tipo = TipoTicket(sector_id=sector.id, codigo="consulta", nombre="Consulta", schema_campos={})
    db.add(tipo)
    db.flush()

    estado = EstadoTicket(workflow_id=wf.id, codigo="abierto", nombre="Abierto", orden=1, es_inicial=True)
    db.add(estado)
    db.flush()

    return sector, tipo, estado


TICKETS_ENDPOINT = "/api/tickets/tickets"


class TestMinimalTextoCreatesTicketWithInboxDefaults:
    """SC: minimal submission (`{texto}` only) succeeds, defaults to the
    seeded Inbox pair, and reaches the seeded initial state."""

    def test_minimal_texto_creates_with_inbox_defaults_and_derived_titulo(self, client, db, rol_ventas):
        user = _make_user(db, rol_ventas)
        _, _, estado_inicial, _ = _seed_inbox(db)

        resp = client.post(
            TICKETS_ENDPOINT,
            json={"texto": "No puedo facturar desde ayer"},
            headers=_headers(user),
        )

        assert resp.status_code == 201
        body = resp.json()
        assert body["sector"]["codigo"] == INBOX_SECTOR_CODIGO
        assert body["tipo_ticket"]["codigo"] == INBOX_TIPO_CODIGO
        assert body["titulo"] == "No puedo facturar desde ayer"
        assert body["estado"]["id"] == estado_inicial.id
        assert body["estado"]["codigo"] == "nuevo"

    def test_derives_titulo_from_first_80_chars_of_long_texto(self, client, db, rol_ventas):
        user = _make_user(db, rol_ventas)
        _seed_inbox(db)
        texto = "Necesito ayuda urgente con la facturacion " * 5  # > 80 chars

        resp = client.post(TICKETS_ENDPOINT, json={"texto": texto}, headers=_headers(user))

        assert resp.status_code == 201
        body = resp.json()
        assert body["titulo"] == texto.strip()[:80].rstrip()
        assert len(body["titulo"]) <= 80

        ticket = db.query(Ticket).filter(Ticket.id == body["id"]).first()
        assert ticket.texto_original == texto


class TestExplicitSectorAndTipoStillHonored:
    """SC: advanced path still honors explicit values over Inbox defaults."""

    def test_explicit_sector_and_tipo_override_inbox_defaults(self, client, db, rol_ventas):
        user = _make_user(db, rol_ventas)
        _seed_inbox(db)
        otro_sector, otro_tipo, _ = _make_other_sector(db)

        resp = client.post(
            TICKETS_ENDPOINT,
            json={
                "texto": "Consulta comercial",
                "sector_id": otro_sector.id,
                "tipo_ticket_id": otro_tipo.id,
            },
            headers=_headers(user),
        )

        assert resp.status_code == 201
        body = resp.json()
        assert body["sector"]["codigo"] == "OTRO_SECT"
        assert body["tipo_ticket"]["codigo"] == "consulta"


class TestTextoOriginalImmutableAfterCreation:
    """SC: `texto_original` is written once and PATCH cannot change it —
    regression lock for the field's absence from `TicketUpdate`."""

    def test_patch_with_texto_original_does_not_change_it(self, client, db, rol_ventas):
        user = _make_user(db, rol_ventas)
        _seed_inbox(db)

        create_resp = client.post(
            TICKETS_ENDPOINT,
            json={"texto": "no puedo facturar desde ayer"},
            headers=_headers(user),
        )
        ticket_id = create_resp.json()["id"]

        patch_resp = client.patch(
            f"{TICKETS_ENDPOINT}/{ticket_id}",
            json={"texto_original": "un atacante intenta reescribir esto", "titulo": "Nuevo titulo valido"},
            headers=_headers(user),
        )

        assert patch_resp.status_code == 200
        ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
        assert ticket.texto_original == "no puedo facturar desde ayer"
        assert ticket.titulo == "Nuevo titulo valido"


class TestTextoValidation:
    """Edge cases for the single required field."""

    def test_texto_shorter_than_5_chars_is_rejected(self, client, db, rol_ventas):
        user = _make_user(db, rol_ventas)
        _seed_inbox(db)

        resp = client.post(TICKETS_ENDPOINT, json={"texto": "hi"}, headers=_headers(user))

        assert resp.status_code == 422

    def test_missing_texto_and_titulo_is_rejected(self, client, db, rol_ventas):
        user = _make_user(db, rol_ventas)
        _seed_inbox(db)

        resp = client.post(TICKETS_ENDPOINT, json={}, headers=_headers(user))

        assert resp.status_code == 422


class TestDerivarTituloPureFunction:
    """Unit coverage for the pure derivation helper — no DB needed."""

    def test_short_texto_returned_as_is(self):
        assert _derivar_titulo("  no puedo facturar  ") == "no puedo facturar"

    def test_long_texto_truncated_to_80_chars(self):
        texto = "a" * 120
        resultado = _derivar_titulo(texto)
        assert resultado == "a" * 80
        assert len(resultado) == 80
