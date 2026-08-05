"""
Tests for Ticket model severidad/urgencia/*_origen/texto_original columns (PR 2a).

Covers tasks 2a.1 (columns exist, are nullable, ticket stays unclassified) and
2a.4 (real PostgreSQL CHECK constraint rejects an out-of-vocabulary value).
Written FIRST (RED phase) per strict TDD.

Run:
    cd backend && source venv/bin/activate
    pytest tests/tickets/test_ticket_schema_columns.py -v
    # postgres-marked test needs POSTGRES_TEST_URL or a local PostgreSQL —
    # see conftest.py's `_postgres_reachable()`; CI provides a postgres service.
"""

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.security import get_password_hash
from app.models.rol import Rol
from app.models.usuario import AuthProvider, RolUsuario, Usuario
from app.tickets.models.sector import Sector
from app.tickets.models.tipo_ticket import TipoTicket
from app.tickets.models.ticket import PrioridadTicket, Ticket
from app.tickets.models.workflow import EstadoTicket, Workflow


def _make_sector(db, codigo: str = "SCHEMA_TEST") -> Sector:
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


def _make_creador(db, rol: Rol, username: str = "schema_test_user") -> Usuario:
    usuario = Usuario(
        username=username,
        email=f"{username}@test.com",
        nombre="Schema Test User",
        password_hash=get_password_hash("pass"),
        rol=RolUsuario.VENTAS,
        rol_id=rol.id,
        auth_provider=AuthProvider.LOCAL,
        activo=True,
    )
    db.add(usuario)
    db.flush()
    return usuario


class TestTicketSchemaColumns:
    """2a.1: the model exposes the five new columns and a ticket created
    without them stays unclassified — NULL, not a default value."""

    def test_new_columns_default_to_null(self, db, rol_ventas):
        sector = _make_sector(db)
        tipo, estado = _make_tipo_y_estado(db, sector)
        creador = _make_creador(db, rol_ventas)

        ticket = Ticket(
            titulo="Ticket sin clasificar",
            prioridad=PrioridadTicket.MEDIA,
            sector_id=sector.id,
            tipo_ticket_id=tipo.id,
            estado_id=estado.id,
            creador_id=creador.id,
            campos_metadata={},
        )
        db.add(ticket)
        db.flush()
        db.refresh(ticket)

        # Model exposes all five new columns.
        for column in ("severidad", "urgencia", "severidad_origen", "urgencia_origen", "texto_original"):
            assert hasattr(ticket, column), f"Ticket model is missing column '{column}'"

        # Invariant: severidad IS NULL (and its siblings) means "unclassified",
        # not a default string — nothing in this slice writes these columns.
        assert ticket.severidad is None
        assert ticket.urgencia is None
        assert ticket.severidad_origen is None
        assert ticket.urgencia_origen is None
        assert ticket.texto_original is None


class TestSeveridadUrgenciaCheckConstraint:
    """2a.4: real PostgreSQL CHECK constraints reject out-of-vocabulary values.

    VARCHAR + CHECK (not a PG ENUM — see the migration docstring for why),
    so this must run against real PostgreSQL: SQLite would silently accept
    the same DDL without enforcing it the same way psycopg2 surfaces it here.
    """

    @pytest.mark.postgres
    def test_invalid_severidad_rejected(self, pg_tickets_db):
        db = pg_tickets_db
        rol = Rol(codigo="VENTAS", nombre="Ventas", es_sistema=False, orden=10, activo=True)
        db.add(rol)
        db.flush()
        creador = _make_creador(db, rol, username="pg_schema_test_user")
        sector = _make_sector(db, codigo="SCHEMA_TEST_PG")
        tipo, estado = _make_tipo_y_estado(db, sector)

        ticket = Ticket(
            titulo="Ticket con severidad inválida",
            prioridad=PrioridadTicket.MEDIA,
            sector_id=sector.id,
            tipo_ticket_id=tipo.id,
            estado_id=estado.id,
            creador_id=creador.id,
            campos_metadata={},
            # Fits VARCHAR(12) but is not in the vocabulary — must trip the
            # CHECK constraint (IntegrityError), not a length truncation.
            severidad="urgente",
        )
        db.add(ticket)

        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()

    @pytest.mark.postgres
    def test_invalid_urgencia_rejected(self, pg_tickets_db):
        db = pg_tickets_db
        rol = Rol(codigo="VENTAS", nombre="Ventas", es_sistema=False, orden=10, activo=True)
        db.add(rol)
        db.flush()
        creador = _make_creador(db, rol, username="pg_schema_test_user_2")
        sector = _make_sector(db, codigo="SCHEMA_TEST_PG_2")
        tipo, estado = _make_tipo_y_estado(db, sector)

        ticket = Ticket(
            titulo="Ticket con urgencia inválida",
            prioridad=PrioridadTicket.MEDIA,
            sector_id=sector.id,
            tipo_ticket_id=tipo.id,
            estado_id=estado.id,
            creador_id=creador.id,
            campos_metadata={},
            # Fits VARCHAR(12) but is not in the vocabulary — must trip the
            # CHECK constraint (IntegrityError), not a length truncation.
            urgencia="grave",
        )
        db.add(ticket)

        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()
