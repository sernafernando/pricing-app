"""Tests for the AI proposal confirmation lifecycle (tickets-ai-triage PR 4b):
`confirmacion_service.confirmar/descartar/confirmar_batch`, the
`tickets.triage.confirmar` permission gate, the "never resurfaces" hard
invariant, batch atomicity under a simulated partial failure, and the
`POST /tickets/{id}/triage` single-flight guard.

Covers `backend/tickets-triage` spec requirements:
- Confirmation Lifecycle and Rejection Permanence
- Human-triggered retry, single-flight guard

Written FIRST (RED phase) per strict TDD.

Run:
    cd backend && source venv/bin/activate
    pytest tests/tickets/test_confirmacion_service.py -v
"""

import asyncio
import json
from unittest.mock import patch

import pytest
from sqlalchemy.exc import IntegrityError

import app.tickets.api.endpoints.propuestas as propuestas_module
from app.core.security import create_access_token, get_password_hash
from app.main import app
from app.models.permiso import Permiso, UsuarioPermisoOverride
from app.models.rol import Rol
from app.models.usuario import AuthProvider, RolUsuario, Usuario
from app.tickets.api.deps import get_triage_provider
from app.tickets.models.historial_ticket import HistorialTicket
from app.tickets.models.propuesta_ia import PropuestaIA
from app.tickets.models.sector import Sector
from app.tickets.models.ticket import PrioridadTicket, Ticket
from app.tickets.models.tipo_ticket import TipoTicket
from app.tickets.models.workflow import EstadoTicket, Workflow
from app.tickets.services import confirmacion_service
from app.tickets.services.triage_service import run_triage

_seq = [0]


def _make_sector(db) -> Sector:
    _seq[0] += 1
    s = Sector(codigo=f"CONFIRM_SECT_{_seq[0]}", nombre="Sector Confirm Test", activo=True, configuracion={})
    db.add(s)
    db.flush()
    return s


def _make_tipo_y_estado(db, sector: Sector) -> tuple[TipoTicket, EstadoTicket]:
    workflow = Workflow(sector_id=sector.id, nombre="WF Confirm Test", es_default=True, activo=True)
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


def _make_usuario(db, rol: Rol) -> Usuario:
    _seq[0] += 1
    usuario = Usuario(
        username=f"confirm_user_{_seq[0]}",
        email=f"confirm_{_seq[0]}@test.com",
        nombre="Confirm Test User",
        password_hash=get_password_hash("pass"),
        rol=RolUsuario.VENTAS,
        rol_id=rol.id,
        auth_provider=AuthProvider.LOCAL,
        activo=True,
    )
    db.add(usuario)
    db.flush()
    return usuario


def _make_ticket(db, rol: Rol) -> Ticket:
    sector = _make_sector(db)
    tipo, estado = _make_tipo_y_estado(db, sector)
    creador = _make_usuario(db, rol)
    ticket = Ticket(
        titulo="Ticket para confirmación",
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


def _make_propuesta(
    db, ticket: Ticket, campo: str = "severidad", valor: str = "mayor", estado: str = "pendiente"
) -> PropuestaIA:
    propuesta = PropuestaIA(ticket_id=ticket.id, campo=campo, valor_propuesto={"valor": valor}, estado=estado)
    db.add(propuesta)
    db.flush()
    return propuesta


def _give_permiso(db, user: Usuario, codigo: str = "tickets.triage.confirmar") -> None:
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


def _reload(db, ticket: Ticket) -> Ticket:
    """Real gotcha (matches obs #1350's pattern): `setattr(obj, "unmapped_attr", ...)`
    on a SQLAlchemy model silently creates a plain Python instance attribute
    when the column doesn't exist on the model — no error. `db.refresh()`
    only reloads MAPPED columns, so it does NOT clear that phantom
    attribute; a test asserting on it via `db.refresh(ticket)` would pass
    even if the column were never added to the model or migration.
    `db.expunge()` + a fresh query bypasses the session's identity map,
    forcing a genuine reconstruction from the DB row — the only way to
    prove the value was actually persisted to a real column."""
    ticket_id = ticket.id
    db.expunge(ticket)
    return db.query(Ticket).filter(Ticket.id == ticket_id).first()


class _FakeBackgroundDb:
    """Mirrors test_triage_service.py's own fixture — reuses the test's
    transactional `db` session instead of a real second connection."""

    def __init__(self, db):
        self._db = db

    def __enter__(self):
        return self._db

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc_type is None:
            self._db.commit()
        else:
            self._db.rollback()
        return False


class FakeProvider:
    def __init__(self, response: str):
        self.response = response
        self.calls = 0

    def is_configured(self) -> bool:
        return True

    async def complete(self, system_prompt: str, user_payload: str) -> str:
        self.calls += 1
        return self.response


def _valid_triage_payload(**overrides) -> dict:
    payload = {
        "tipo": "bug",
        "titulo": "Arreglar error de facturación",
        "resumen": "El usuario no puede facturar desde ayer",
        "severidad": "critica",
        "urgencia": "alta",
        "confianza_severidad": 0.9,
        "confianza_urgencia": 0.9,
        "confianza_global": 0.9,
        "detalle": {"esperado": "", "actual": "", "pasos": [], "alcance": "", "impacto": "", "workaround": ""},
        "area_probable": None,
        "tamano": None,
    }
    payload.update(overrides)
    return payload


class TestConfirmarWritesValueProvenanceHistory:
    """SC: Confirm writes state + provenance + history."""

    def test_confirmar_writes_ticket_column_origen_and_historial(self, db, rol_ventas):
        ticket = _make_ticket(db, rol_ventas)
        usuario = _make_usuario(db, rol_ventas)
        propuesta = _make_propuesta(db, ticket, campo="severidad", valor="critica")

        resultado = confirmacion_service.confirmar(db, propuesta.id, usuario)

        assert resultado.estado == "confirmada"
        assert resultado.confirmado_por_id == usuario.id
        assert resultado.confirmado_at is not None

        db.refresh(ticket)
        assert ticket.severidad == "critica"
        assert ticket.severidad_origen == "ia_confirmada"

        historial = (
            db.query(HistorialTicket)
            .filter(HistorialTicket.ticket_id == ticket.id, HistorialTicket.accion == "propuesta_confirmada")
            .all()
        )
        assert len(historial) == 1
        assert historial[0].cambios["campo"] == "severidad"
        assert historial[0].cambios["valor_nuevo"] == "critica"

    def test_confirmar_urgencia_writes_urgencia_column(self, db, rol_ventas):
        ticket = _make_ticket(db, rol_ventas)
        usuario = _make_usuario(db, rol_ventas)
        propuesta = _make_propuesta(db, ticket, campo="urgencia", valor="inmediata")

        confirmacion_service.confirmar(db, propuesta.id, usuario)

        db.refresh(ticket)
        assert ticket.urgencia == "inmediata"
        assert ticket.urgencia_origen == "ia_confirmada"
        # Confirming urgencia must never touch severidad.
        assert ticket.severidad is None

    def test_confirmar_titulo_writes_ticket_column_and_origen(self, db, rol_ventas):
        """Decision #1371 — closes the gap PR 4b explicitly left open: the
        generic setattr pattern extends to titulo with zero special-casing."""
        ticket = _make_ticket(db, rol_ventas)
        usuario = _make_usuario(db, rol_ventas)
        propuesta = _make_propuesta(db, ticket, campo="titulo", valor="Arreglar login roto")

        resultado = confirmacion_service.confirmar(db, propuesta.id, usuario)

        assert resultado.estado == "confirmada"
        ticket = _reload(db, ticket)
        assert ticket.titulo == "Arreglar login roto"
        assert ticket.titulo_origen == "ia_confirmada"

        historial = (
            db.query(HistorialTicket)
            .filter(HistorialTicket.ticket_id == ticket.id, HistorialTicket.accion == "propuesta_confirmada")
            .all()
        )
        assert len(historial) == 1
        assert historial[0].cambios["campo"] == "titulo"

    def test_confirmar_resumen_writes_ticket_column_and_origen_without_overwriting_descripcion(self, db, rol_ventas):
        """Decision #1 (obs #1371): `resumen` is a DEDICATED column — it
        must never overwrite `descripcion`, which carries the raw intake
        text and would leave the detail view with LESS information than
        the board card if clobbered."""
        ticket = _make_ticket(db, rol_ventas)
        ticket.descripcion = "Texto completo original del reporte, más largo que cualquier resumen."
        db.commit()
        usuario = _make_usuario(db, rol_ventas)
        propuesta = _make_propuesta(db, ticket, campo="resumen", valor="El usuario no puede loguearse desde ayer")

        confirmacion_service.confirmar(db, propuesta.id, usuario)

        ticket = _reload(db, ticket)
        assert ticket.resumen == "El usuario no puede loguearse desde ayer"
        assert ticket.resumen_origen == "ia_confirmada"
        assert ticket.descripcion == "Texto completo original del reporte, más largo que cualquier resumen."

    def test_confirmar_titulo_does_not_touch_texto_original(self, db, rol_ventas):
        """Regression: `texto_original` is the reporter's receipt (design
        §7) and must survive a title/summary confirmation untouched."""
        ticket = _make_ticket(db, rol_ventas)
        ticket.texto_original = "El login no funciona desde ayer a la tarde"
        db.commit()
        usuario = _make_usuario(db, rol_ventas)
        propuesta = _make_propuesta(db, ticket, campo="titulo", valor="Arreglar login roto")

        confirmacion_service.confirmar(db, propuesta.id, usuario)

        ticket = _reload(db, ticket)
        assert ticket.texto_original == "El login no funciona desde ayer a la tarde"


class TestConfirmarServiceErrors:
    def test_confirmar_unknown_id_raises_not_found(self, db, rol_ventas):
        usuario = _make_usuario(db, rol_ventas)
        with pytest.raises(confirmacion_service.PropuestaNoEncontradaError):
            confirmacion_service.confirmar(db, 999999, usuario)

    def test_confirmar_already_confirmed_raises_not_pending(self, db, rol_ventas):
        ticket = _make_ticket(db, rol_ventas)
        usuario = _make_usuario(db, rol_ventas)
        propuesta = _make_propuesta(db, ticket, estado="confirmada")

        with pytest.raises(confirmacion_service.PropuestaNoPendienteError):
            confirmacion_service.confirmar(db, propuesta.id, usuario)

        # Not-pending rejection must not touch the ticket.
        db.refresh(ticket)
        assert ticket.severidad is None


class TestConfirmarEndpointPermission:
    """SC: Confirm without permission is rejected (403)."""

    def test_confirmar_without_permiso_returns_403(self, client, db, rol_ventas):
        ticket = _make_ticket(db, rol_ventas)
        usuario = _make_usuario(db, rol_ventas)
        propuesta = _make_propuesta(db, ticket)

        resp = client.post(
            f"/api/tickets/propuestas/{propuesta.id}/confirmar",
            headers=_headers(usuario),
        )

        assert resp.status_code == 403
        db.refresh(ticket)
        assert ticket.severidad is None

    def test_confirmar_with_permiso_succeeds(self, client, db, rol_ventas):
        ticket = _make_ticket(db, rol_ventas)
        usuario = _make_usuario(db, rol_ventas)
        _give_permiso(db, usuario)
        propuesta = _make_propuesta(db, ticket)

        resp = client.post(
            f"/api/tickets/propuestas/{propuesta.id}/confirmar",
            headers=_headers(usuario),
        )

        assert resp.status_code == 200
        assert resp.json()["estado"] == "confirmada"

    def test_confirmar_batch_endpoint_succeeds_over_http(self, client, db, rol_ventas):
        """Real bug caught by pre-push review: `ConfirmarBatchRequest` had a
        stray required `pages: int` field left over from a bad string
        replace, which made every real HTTP call 422 — invisible to the
        service-level batch tests above, which never go through FastAPI's
        request validation. This is the regression guard for that class of
        bug: exercise the endpoint over HTTP, not just the service."""
        ticket1 = _make_ticket(db, rol_ventas)
        ticket2 = _make_ticket(db, rol_ventas)
        usuario = _make_usuario(db, rol_ventas)
        _give_permiso(db, usuario)
        p1 = _make_propuesta(db, ticket1, campo="severidad", valor="mayor")
        p2 = _make_propuesta(db, ticket2, campo="urgencia", valor="alta")

        resp = client.post(
            "/api/tickets/propuestas/confirmar-batch",
            json={"propuesta_ids": [p1.id, p2.id]},
            headers=_headers(usuario),
        )

        assert resp.status_code == 200
        body = resp.json()
        assert {p["estado"] for p in body} == {"confirmada"}

    def test_confirmar_titulo_endpoint_succeeds_over_http(self, client, db, rol_ventas):
        """HTTP-level regression guard (obs #1350's pattern): proves the
        full request/response path — auth, permission check, service call,
        `PropuestaResponse` serialization — works when `campo='titulo'`,
        not just the service function called directly."""
        ticket = _make_ticket(db, rol_ventas)
        usuario = _make_usuario(db, rol_ventas)
        _give_permiso(db, usuario)
        propuesta = _make_propuesta(db, ticket, campo="titulo", valor="Arreglar login roto")

        resp = client.post(
            f"/api/tickets/propuestas/{propuesta.id}/confirmar",
            headers=_headers(usuario),
        )

        assert resp.status_code == 200
        assert resp.json()["campo"] == "titulo"
        assert resp.json()["estado"] == "confirmada"
        ticket = _reload(db, ticket)
        assert ticket.titulo == "Arreglar login roto"
        assert ticket.titulo_origen == "ia_confirmada"


class TestDescartarNeverResurfaces:
    """SC: Human rejection never re-surfaces."""

    def test_descartar_sets_estado_descartada(self, db, rol_ventas):
        ticket = _make_ticket(db, rol_ventas)
        usuario = _make_usuario(db, rol_ventas)
        propuesta = _make_propuesta(db, ticket)

        resultado = confirmacion_service.descartar(db, propuesta.id, usuario)

        assert resultado.estado == "descartada"
        db.refresh(ticket)
        assert ticket.severidad is None  # descartar never writes to tickets

    @pytest.mark.postgres
    def test_discarded_row_stays_discarded_when_new_triage_run_proposes_again(self, pg_tickets_db):
        """Partial unique index only covers `estado='pendiente'` (Postgres
        semantics) — SQLite's `db` fixture builds a FULL unique index on
        `(ticket_id, campo)` instead (documented in `propuesta_ia.py`), so
        this scenario is only real on `pg_tickets_db` per that model's own
        guidance."""
        db = pg_tickets_db
        rol = Rol(codigo="VENTAS", nombre="Ventas", es_sistema=False, orden=10, activo=True)
        db.add(rol)
        db.flush()
        ticket = _make_ticket(db, rol)
        usuario = _make_usuario(db, rol)
        propuesta = _make_propuesta(db, ticket, campo="severidad", valor="menor")
        confirmacion_service.descartar(db, propuesta.id, usuario)
        assert propuesta.estado == "descartada"

        ticket.texto_original = "Sigue fallando, ahora es peor"
        db.commit()

        fake_provider = FakeProvider(json.dumps(_valid_triage_payload(severidad="critica")))
        with patch("app.tickets.services.triage_service.get_background_db", return_value=_FakeBackgroundDb(db)):
            asyncio.run(run_triage(ticket.id, fake_provider))

        db.refresh(propuesta)
        assert propuesta.estado == "descartada"  # HARD INVARIANT: never flips back

        nuevas = (
            db.query(PropuestaIA)
            .filter(
                PropuestaIA.ticket_id == ticket.id, PropuestaIA.campo == "severidad", PropuestaIA.id != propuesta.id
            )
            .all()
        )
        assert len(nuevas) == 1
        assert nuevas[0].estado == "pendiente"

    @pytest.mark.postgres
    def test_discarded_titulo_stays_discarded_when_new_triage_run_proposes_again(self, pg_tickets_db):
        """SCOPE: 'a discarded title proposal never resurfaces' — same
        invariant as severidad above, proven for the new `titulo` campo."""
        db = pg_tickets_db
        rol = Rol(codigo="VENTAS", nombre="Ventas", es_sistema=False, orden=10, activo=True)
        db.add(rol)
        db.flush()
        ticket = _make_ticket(db, rol)
        usuario = _make_usuario(db, rol)
        propuesta = _make_propuesta(db, ticket, campo="titulo", valor="Titulo viejo descartado")
        confirmacion_service.descartar(db, propuesta.id, usuario)
        assert propuesta.estado == "descartada"

        ticket.texto_original = "Sigue fallando, ahora con más detalle"
        db.commit()

        fake_provider = FakeProvider(json.dumps(_valid_triage_payload(confianza_global=0.9)))
        with patch("app.tickets.services.triage_service.get_background_db", return_value=_FakeBackgroundDb(db)):
            asyncio.run(run_triage(ticket.id, fake_provider))

        db.refresh(propuesta)
        assert propuesta.estado == "descartada"  # HARD INVARIANT: never flips back

        nuevas = (
            db.query(PropuestaIA)
            .filter(PropuestaIA.ticket_id == ticket.id, PropuestaIA.campo == "titulo", PropuestaIA.id != propuesta.id)
            .all()
        )
        assert len(nuevas) == 1
        assert nuevas[0].estado == "pendiente"


class TestConfirmarBatchAtomic:
    """SC: Batch confirm is one atomic operation."""

    def test_batch_confirms_across_multiple_tickets_in_one_call(self, db, rol_ventas):
        ticket1 = _make_ticket(db, rol_ventas)
        ticket2 = _make_ticket(db, rol_ventas)
        usuario = _make_usuario(db, rol_ventas)
        p1 = _make_propuesta(db, ticket1, campo="severidad", valor="mayor")
        p2 = _make_propuesta(db, ticket2, campo="urgencia", valor="alta")

        resultado = confirmacion_service.confirmar_batch(db, [p1.id, p2.id], usuario)

        assert {p.estado for p in resultado} == {"confirmada"}
        db.refresh(ticket1)
        db.refresh(ticket2)
        assert ticket1.severidad == "mayor"
        assert ticket2.urgencia == "alta"

    def test_batch_with_invalid_id_rejects_whole_batch_before_any_write(self, db, rol_ventas):
        """Pre-validation half: one id doesn't exist -> nothing is written,
        not even for the otherwise-valid sibling id in the same batch."""
        ticket1 = _make_ticket(db, rol_ventas)
        usuario = _make_usuario(db, rol_ventas)
        p1 = _make_propuesta(db, ticket1, campo="severidad", valor="mayor")

        with pytest.raises(confirmacion_service.PropuestaBatchInvalidaError):
            confirmacion_service.confirmar_batch(db, [p1.id, 999999], usuario)

        db.refresh(ticket1)
        assert ticket1.severidad is None
        db.refresh(p1)
        assert p1.estado == "pendiente"

    def test_batch_partial_write_failure_rolls_back_the_whole_batch(self, db, rol_ventas):
        """Mid-transaction half: what would have to break for this test to
        go red is the `except: db.rollback(); raise` in
        `confirmar_batch` — remove it and ticket1's already-flushed
        `severidad='mayor'` would leak through uncommitted (or the test's
        own re-query below would blow up with a DB-level pending-rollback
        error instead of cleanly observing `None`), proving the batch is
        NOT atomic. Forces the failure with a value that violates
        `ck_tickets_severidad`, not with a pre-validation short-circuit."""
        ticket1 = _make_ticket(db, rol_ventas)
        ticket2 = _make_ticket(db, rol_ventas)
        usuario = _make_usuario(db, rol_ventas)
        p1 = _make_propuesta(db, ticket1, campo="severidad", valor="mayor")
        # Bypasses TriagePropuesta's closed vocabulary on purpose — this
        # value could only reach the DB via a bug, but the CHECK
        # constraint (defense-in-depth) must still reject it.
        p2 = _make_propuesta(db, ticket2, campo="severidad", valor="no_existe")
        # Commit the arrange phase first: application-level rollback below
        # must only undo confirmar_batch's own pending work, not this test's
        # fixture data (see the `db` fixture's SAVEPOINT-restart docstring).
        db.commit()

        with pytest.raises(IntegrityError):
            confirmacion_service.confirmar_batch(db, [p1.id, p2.id], usuario)

        # The service must have rolled back — this query only succeeds if
        # the session is usable again, which requires the rollback to have
        # actually run.
        ticket1_fresh = db.query(Ticket).filter(Ticket.id == ticket1.id).first()
        assert ticket1_fresh.severidad is None
        p1_fresh = db.query(PropuestaIA).filter(PropuestaIA.id == p1.id).first()
        assert p1_fresh.estado == "pendiente"


TRIAGE_RETRIGGER_ENDPOINT = "/api/tickets/tickets/{id}/triage"


class TestRetriggerSingleFlightGuard:
    """SC: Human-triggered retry, single-flight guard."""

    def test_refuses_without_forzar_when_pendiente_exists(self, client, db, rol_ventas):
        ticket = _make_ticket(db, rol_ventas)
        usuario = _make_usuario(db, rol_ventas)
        _give_permiso(db, usuario)
        _make_propuesta(db, ticket, estado="pendiente")

        app.dependency_overrides[get_triage_provider] = lambda: FakeProvider("{}")
        with patch.object(propuestas_module.BackgroundTasks, "add_task") as mock_add_task:
            resp = client.post(TRIAGE_RETRIGGER_ENDPOINT.format(id=ticket.id), headers=_headers(usuario))

        assert resp.status_code == 409
        mock_add_task.assert_not_called()

    def test_refuses_without_forzar_when_confirmada_exists(self, client, db, rol_ventas):
        ticket = _make_ticket(db, rol_ventas)
        usuario = _make_usuario(db, rol_ventas)
        _give_permiso(db, usuario)
        _make_propuesta(db, ticket, estado="confirmada")

        app.dependency_overrides[get_triage_provider] = lambda: FakeProvider("{}")
        with patch.object(propuestas_module.BackgroundTasks, "add_task") as mock_add_task:
            resp = client.post(TRIAGE_RETRIGGER_ENDPOINT.format(id=ticket.id), headers=_headers(usuario))

        assert resp.status_code == 409
        mock_add_task.assert_not_called()

    def test_forzar_marks_pendiente_reemplazada_and_reschedules(self, client, db, rol_ventas):
        ticket = _make_ticket(db, rol_ventas)
        usuario = _make_usuario(db, rol_ventas)
        _give_permiso(db, usuario)
        pendiente = _make_propuesta(db, ticket, estado="pendiente")

        app.dependency_overrides[get_triage_provider] = lambda: FakeProvider("{}")
        with patch.object(propuestas_module.BackgroundTasks, "add_task") as mock_add_task:
            resp = client.post(
                TRIAGE_RETRIGGER_ENDPOINT.format(id=ticket.id), params={"forzar": "true"}, headers=_headers(usuario)
            )

        assert resp.status_code == 200
        mock_add_task.assert_called_once()
        db.refresh(pendiente)
        assert pendiente.estado == "reemplazada"

    def test_forzar_leaves_confirmada_untouched(self, client, db, rol_ventas):
        ticket = _make_ticket(db, rol_ventas)
        usuario = _make_usuario(db, rol_ventas)
        _give_permiso(db, usuario)
        confirmada = _make_propuesta(db, ticket, estado="confirmada")

        app.dependency_overrides[get_triage_provider] = lambda: FakeProvider("{}")
        with patch.object(propuestas_module.BackgroundTasks, "add_task") as mock_add_task:
            resp = client.post(
                TRIAGE_RETRIGGER_ENDPOINT.format(id=ticket.id), params={"forzar": "true"}, headers=_headers(usuario)
            )

        assert resp.status_code == 200
        mock_add_task.assert_called_once()
        db.refresh(confirmada)
        assert confirmada.estado == "confirmada"

    def test_retrigger_without_permiso_returns_403(self, client, db, rol_ventas):
        ticket = _make_ticket(db, rol_ventas)
        usuario = _make_usuario(db, rol_ventas)

        resp = client.post(TRIAGE_RETRIGGER_ENDPOINT.format(id=ticket.id), headers=_headers(usuario))

        assert resp.status_code == 403
