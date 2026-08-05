"""
Tests for the `PropuestaIA` model and `tickets_propuestas_ia` table (PR 2b).

Covers tasks 2b.1 (default `estado='pendiente'`), the partial unique index
`(ticket_id, campo) WHERE estado='pendiente'` (both halves: rejects a second
pending row, allows a second row once the first is resolved), 2b.5 (JSONB
round-trip on `valor_propuesto`), and the `estado` CHECK constraint. Written
FIRST (RED phase) per strict TDD.

Run:
    cd backend && source venv/bin/activate
    pytest tests/tickets/test_propuesta_ia_model.py -v
    # postgres-marked tests need POSTGRES_TEST_URL or a local PostgreSQL —
    # see conftest.py's `_postgres_reachable()`; CI provides a postgres service.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.core.security import get_password_hash
from app.models.rol import Rol
from app.models.usuario import AuthProvider, RolUsuario, Usuario
from app.tickets.models.propuesta_ia import PropuestaIA
from app.tickets.models.sector import Sector
from app.tickets.models.tipo_ticket import TipoTicket
from app.tickets.models.ticket import PrioridadTicket, Ticket
from app.tickets.models.workflow import EstadoTicket, Workflow


def _make_sector(db, codigo: str = "PROPUESTA_TEST") -> Sector:
    sector = Sector(codigo=codigo, nombre="Sector Test", activo=True)
    db.add(sector)
    db.flush()
    return sector


def _make_tipo_y_estado(db, sector: Sector) -> tuple[TipoTicket, EstadoTicket]:
    workflow = Workflow(sector_id=sector.id, nombre="WF Test", es_default=True, activo=True)
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
    return tipo, estado


def _make_usuario(db, rol: Rol, username: str) -> Usuario:
    usuario = Usuario(
        username=username,
        email=f"{username}@test.com",
        nombre="Propuesta Test User",
        password_hash=get_password_hash("pass"),
        rol=RolUsuario.VENTAS,
        rol_id=rol.id,
        auth_provider=AuthProvider.LOCAL,
        activo=True,
    )
    db.add(usuario)
    db.flush()
    return usuario


def _make_ticket(db, rol: Rol, suffix: str) -> Ticket:
    sector = _make_sector(db, codigo=f"PROPUESTA_TEST_{suffix}")
    tipo, estado = _make_tipo_y_estado(db, sector)
    creador = _make_usuario(db, rol, username=f"propuesta_test_user_{suffix}")

    ticket = Ticket(
        titulo="Ticket para propuestas IA",
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


class TestPropuestaIADefaults:
    """2b.1: a row creates with `estado='pendiente'` by default."""

    def test_creates_with_pendiente_default(self, db, rol_ventas):
        ticket = _make_ticket(db, rol_ventas, "sqlite")

        propuesta = PropuestaIA(
            ticket_id=ticket.id,
            campo="severidad",
            valor_propuesto={"valor": "mayor"},
        )
        db.add(propuesta)
        db.flush()
        db.refresh(propuesta)

        assert propuesta.estado == "pendiente"
        assert propuesta.id is not None
        assert propuesta.confirmado_por_id is None
        assert propuesta.confirmado_at is None
        assert propuesta.created_at is not None


class TestPartialUniqueIndexPendienteOnly:
    """2b.1 (postgres half): the partial unique index on
    `(ticket_id, campo) WHERE estado='pendiente'` rejects a second pending
    row for the same pair, but allows a second row once the first proposal
    is no longer pending — proving the index is genuinely partial, not a
    plain unique constraint.
    """

    @pytest.mark.postgres
    def test_rejects_second_pending_proposal_same_pair(self, pg_tickets_db):
        db = pg_tickets_db
        rol = Rol(codigo="VENTAS", nombre="Ventas", es_sistema=False, orden=10, activo=True)
        db.add(rol)
        db.flush()
        ticket = _make_ticket(db, rol, "pg_reject")

        db.add(PropuestaIA(ticket_id=ticket.id, campo="severidad", valor_propuesto={"valor": "mayor"}))
        db.flush()

        db.add(PropuestaIA(ticket_id=ticket.id, campo="severidad", valor_propuesto={"valor": "critica"}))
        with pytest.raises(IntegrityError):
            db.flush()

    @pytest.mark.postgres
    def test_allows_second_proposal_when_first_is_confirmada(self, pg_tickets_db):
        db = pg_tickets_db
        rol = Rol(codigo="VENTAS", nombre="Ventas", es_sistema=False, orden=10, activo=True)
        db.add(rol)
        db.flush()
        ticket = _make_ticket(db, rol, "pg_confirmada")

        primera = PropuestaIA(ticket_id=ticket.id, campo="severidad", valor_propuesto={"valor": "mayor"})
        db.add(primera)
        db.flush()
        primera.estado = "confirmada"
        db.flush()

        segunda = PropuestaIA(ticket_id=ticket.id, campo="severidad", valor_propuesto={"valor": "critica"})
        db.add(segunda)
        db.flush()  # No IntegrityError: the partial index only covers estado='pendiente'.

        assert segunda.id is not None

    @pytest.mark.postgres
    def test_allows_second_proposal_when_first_is_descartada(self, pg_tickets_db):
        db = pg_tickets_db
        rol = Rol(codigo="VENTAS", nombre="Ventas", es_sistema=False, orden=10, activo=True)
        db.add(rol)
        db.flush()
        ticket = _make_ticket(db, rol, "pg_descartada")

        primera = PropuestaIA(ticket_id=ticket.id, campo="severidad", valor_propuesto={"valor": "mayor"})
        db.add(primera)
        db.flush()
        primera.estado = "descartada"
        db.flush()

        segunda = PropuestaIA(ticket_id=ticket.id, campo="severidad", valor_propuesto={"valor": "critica"})
        db.add(segunda)
        db.flush()

        assert segunda.id is not None


class TestValorPropuestoJSONBRoundTrip:
    """2b.5: `valor_propuesto` JSONB round-trips a dict identically."""

    @pytest.mark.postgres
    def test_column_is_genuinely_jsonb_not_json(self, pg_tickets_db):
        """Regression guard: `pg_tickets_engine` shares Column objects with
        the SQLite `db` fixture, which patches JSONB → JSON in place for
        SQLite compatibility. If a test using `db` runs earlier in the same
        session, this table could silently get built with plain `json`
        instead of `jsonb` — a dict still round-trips through either type,
        so the round-trip test below would stay green while quietly no
        longer proving anything about JSONB, and no longer matching what
        the real migration creates in production.
        """
        row = pg_tickets_db.execute(
            text(
                "SELECT data_type FROM information_schema.columns "
                "WHERE table_name = 'tickets_propuestas_ia' AND column_name = 'valor_propuesto'"
            )
        ).one()
        assert row.data_type == "jsonb"

    @pytest.mark.postgres
    def test_valor_propuesto_round_trips(self, pg_tickets_db):
        db = pg_tickets_db
        rol = Rol(codigo="VENTAS", nombre="Ventas", es_sistema=False, orden=10, activo=True)
        db.add(rol)
        db.flush()
        ticket = _make_ticket(db, rol, "pg_jsonb")

        original = {"valor": "critica", "confianza_bruta": 0.91, "detalle": {"impacto": "alto"}}
        propuesta = PropuestaIA(ticket_id=ticket.id, campo="severidad", valor_propuesto=original)
        db.add(propuesta)
        db.flush()
        propuesta_id = propuesta.id

        db.expire_all()
        reloaded = db.get(PropuestaIA, propuesta_id)

        assert reloaded.valor_propuesto == original


class TestEstadoCheckConstraint:
    """The `estado` CHECK constraint rejects an out-of-vocabulary value —
    VARCHAR + CHECK (not a PG ENUM), same rationale as `Ticket.severidad`
    in PR 2a: an enum value can never be dropped, so `downgrade()` would
    be a lie.
    """

    @pytest.mark.postgres
    def test_invalid_estado_rejected(self, pg_tickets_db):
        db = pg_tickets_db
        rol = Rol(codigo="VENTAS", nombre="Ventas", es_sistema=False, orden=10, activo=True)
        db.add(rol)
        db.flush()
        ticket = _make_ticket(db, rol, "pg_check")

        propuesta = PropuestaIA(
            ticket_id=ticket.id,
            campo="severidad",
            valor_propuesto={"valor": "mayor"},
            estado="invalido",
        )
        db.add(propuesta)
        with pytest.raises(IntegrityError):
            db.flush()
