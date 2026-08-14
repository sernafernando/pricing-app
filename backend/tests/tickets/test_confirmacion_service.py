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
from app.core.config import settings
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
    db, ticket: Ticket, campo: str = "severidad", valor="mayor", estado: str = "pendiente", confirmado_por_id=None
) -> PropuestaIA:
    propuesta = PropuestaIA(
        ticket_id=ticket.id,
        campo=campo,
        valor_propuesto={"valor": valor},
        estado=estado,
        confirmado_por_id=confirmado_por_id,
    )
    db.add(propuesta)
    db.flush()
    return propuesta


def _make_sector_con_workflow(db, tipo_codigo: str = "bug") -> tuple[Sector, TipoTicket, EstadoTicket]:
    """A DESTINATION sector — distinct from `_make_ticket`'s own origin
    sector — with its own default workflow, initial estado and one tipo.
    Used by sector-confirmation tests (§3/§4)."""
    sector = _make_sector(db)
    workflow = Workflow(sector_id=sector.id, nombre="WF Destino", es_default=True, activo=True)
    db.add(workflow)
    db.flush()
    estado_inicial = EstadoTicket(
        workflow_id=workflow.id, codigo="nuevo_destino", nombre="Nuevo", orden=1, es_inicial=True, es_final=False
    )
    db.add(estado_inicial)
    db.flush()
    tipo = TipoTicket(sector_id=sector.id, codigo=tipo_codigo, nombre=tipo_codigo, workflow_id=workflow.id)
    db.add(tipo)
    db.flush()
    return sector, tipo, estado_inicial


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
        "sector_codigo": "catalogo_sector",
        "tipo_ticket_codigo": "catalogo_tipo",
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

    def test_confirmar_human_confirmed_raises_not_pending(self, db, rol_ventas):
        """A row with a NON-null `confirmado_por_id` (a human already
        ratified or confirmed it) is genuinely settled — still rejected.
        `confirmado_por_id=None` (`ia_auto`, unreviewed) is a DIFFERENT
        case, covered by `TestConfirmarRatificaAplicadoIaAuto` — it now
        ratifies instead of raising, real pre-push review finding."""
        ticket = _make_ticket(db, rol_ventas)
        usuario = _make_usuario(db, rol_ventas)
        propuesta = _make_propuesta(db, ticket, estado="confirmada", confirmado_por_id=usuario.id)

        with pytest.raises(confirmacion_service.PropuestaNoPendienteError):
            confirmacion_service.confirmar(db, propuesta.id, usuario)

        # Not-pending rejection must not touch the ticket.
        db.refresh(ticket)
        assert ticket.severidad is None


class _QueryStub:
    """Minimal fake for the `.filter(...).first()` / `.filter(...).all()`
    chains this service uses — `.filter(...)` is a no-op, `.first()`/`.all()`
    return fixed values regardless of what was filtered on."""

    def __init__(self, first=None, all_: list | None = None) -> None:
        self._first = first
        self._all = all_ if all_ is not None else ([] if first is None else [first])

    def filter(self, *args, **kwargs) -> "_QueryStub":
        return self

    def first(self):
        return self._first

    def all(self) -> list:
        return self._all


def _stub_query_for(db, model, first=None, all_: list | None = None):
    """Patches `db.query(model)` to return a `_QueryStub`, simulating an ORM
    result a real INSERT can no longer produce — used both for a proposal's
    `ticket_id` that doesn't resolve to a real `Ticket` (FK-protected, see
    `TestConfirmarMissingTicket`) and for a `PropuestaIA.campo` outside the
    vocabulary this same fix's `ck_tickets_propuestas_ia_campo` CHECK
    constraint enforces at INSERT time in SQLite too (see
    `TestConfirmarCampoAllowlist`): the app-level guard in
    `_aplicar_confirmacion` must still hold even for a state the DB itself
    now makes unreachable through the ORM directly — e.g. a legacy row
    written before this migration, or any other bypass path.
    """
    original_query = db.query
    stub = _QueryStub(first=first, all_=all_)

    def fake_query(target, *args, **kwargs):
        if target is model:
            return stub
        return original_query(target, *args, **kwargs)

    return patch.object(db, "query", side_effect=fake_query)


def _make_ticket_query_empty(db):
    """See `_stub_query_for` — no ticket matches, simulating a proposal
    whose `ticket_id` no longer resolves to a real ticket."""
    return _stub_query_for(db, Ticket, first=None)


def _transient_propuesta(ticket_id: int, campo: str, propuesta_id: int, valor="x") -> PropuestaIA:
    """A `PropuestaIA` instance that is never `db.add()`-ed or flushed —
    purely in-memory, so it never touches `ck_tickets_propuestas_ia_campo`.
    Used together with `_stub_query_for` to exercise the app-level allowlist
    guard for a `campo` the DB CHECK constraint now forbids ever inserting."""
    return PropuestaIA(
        id=propuesta_id,
        ticket_id=ticket_id,
        campo=campo,
        valor_propuesto={"valor": valor},
        estado="pendiente",
    )


class TestConfirmarCampoAllowlist:
    """Defect 1 (structural): `PropuestaIA.campo` is a plain VARCHAR with no
    application-level validation, so an unvalidated `setattr(ticket,
    propuesta.campo, valor)` is an arbitrary-attribute-write primitive on
    `Ticket`. `_aplicar_confirmacion` must reject any `campo` outside
    `confirmacion_service.CAMPOS_CONFIRMABLES` BEFORE writing anything."""

    def test_confirmar_campo_not_in_allowlist_rejected_and_ticket_unmodified(self, db, rol_ventas):
        ticket = _make_ticket(db, rol_ventas)
        usuario = _make_usuario(db, rol_ventas)
        propuesta = _transient_propuesta(ticket.id, campo="creador_id", propuesta_id=900001, valor=999999)

        with _stub_query_for(db, PropuestaIA, first=propuesta):
            with pytest.raises(confirmacion_service.PropuestaCampoNoPermitidoError):
                confirmacion_service.confirmar(db, propuesta.id, usuario)

        # An exception raised AFTER a partial write is still a bug — assert
        # the ticket's actual state, not just that an exception was raised.
        ticket = _reload(db, ticket)
        assert ticket.creador_id != 999999
        assert propuesta.estado == "pendiente"

    def test_confirmar_campo_estado_id_rejected_workflow_engine_bypass_guard(self, db, rol_ventas):
        """THE regression guard for PR #1072/#1074's workflow-transition
        engine: a proposal with `campo='estado_id'` must NEVER let
        `confirmar()` write `ticket.estado_id` directly — that would walk
        straight around the graph-validated `POST /tickets/{id}/transicion`
        endpoint with zero validation. If this test goes red, the
        confirmation service has become an authorization bypass."""
        ticket = _make_ticket(db, rol_ventas)
        estado_original_id = ticket.estado_id
        usuario = _make_usuario(db, rol_ventas)
        propuesta = _transient_propuesta(ticket.id, campo="estado_id", propuesta_id=900002, valor=999999)

        with _stub_query_for(db, PropuestaIA, first=propuesta):
            with pytest.raises(confirmacion_service.PropuestaCampoNoPermitidoError):
                confirmacion_service.confirmar(db, propuesta.id, usuario)

        ticket = _reload(db, ticket)
        assert ticket.estado_id == estado_original_id

    def test_confirmar_campo_not_allowed_returns_400_over_http(self, client, db, rol_ventas):
        """HTTP-level regression guard (obs #1350's pattern): proves the
        rejection reaches the caller as a clean 400, not an unhandled 500
        from `setattr` on a non-existent/forbidden attribute."""
        ticket = _make_ticket(db, rol_ventas)
        usuario = _make_usuario(db, rol_ventas)
        _give_permiso(db, usuario)
        propuesta = _transient_propuesta(ticket.id, campo="estado_id", propuesta_id=900003, valor=999999)

        with _stub_query_for(db, PropuestaIA, first=propuesta):
            resp = client.post(
                f"/api/tickets/propuestas/{propuesta.id}/confirmar",
                headers=_headers(usuario),
            )

        assert resp.status_code == 400
        ticket = _reload(db, ticket)
        assert ticket.estado_id != 999999


class TestConfirmarMissingTicket:
    """Defect 2: a missing ticket (FK makes this unlikely, not impossible)
    must yield a clean 4xx, never an unhandled `setattr(None, ...)` 500."""

    def test_confirmar_missing_ticket_raises_domain_error_and_nothing_written(self, db, rol_ventas):
        ticket = _make_ticket(db, rol_ventas)
        usuario = _make_usuario(db, rol_ventas)
        propuesta = _make_propuesta(db, ticket, campo="severidad", valor="mayor")

        with _make_ticket_query_empty(db):
            with pytest.raises(confirmacion_service.TicketNoEncontradoError):
                confirmacion_service.confirmar(db, propuesta.id, usuario)

        db.refresh(propuesta)
        assert propuesta.estado == "pendiente"

    def test_confirmar_missing_ticket_returns_404_over_http(self, client, db, rol_ventas):
        ticket = _make_ticket(db, rol_ventas)
        usuario = _make_usuario(db, rol_ventas)
        _give_permiso(db, usuario)
        propuesta = _make_propuesta(db, ticket, campo="severidad", valor="mayor")

        with _make_ticket_query_empty(db):
            resp = client.post(
                f"/api/tickets/propuestas/{propuesta.id}/confirmar",
                headers=_headers(usuario),
            )

        assert resp.status_code == 404
        assert resp.status_code != 500


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
    def test_discarded_row_stays_discarded_when_new_triage_run_proposes_again(self, pg_tickets_db, monkeypatch):
        """Partial unique index only covers `estado='pendiente'` (Postgres
        semantics) — SQLite's `db` fixture builds a FULL unique index on
        `(ticket_id, campo)` instead (documented in `propuesta_ia.py`), so
        this scenario is only real on `pg_tickets_db` per that model's own
        guidance.

        Pins `TICKETS_TRIAGE_AUTO_APPLY=False`: this test's own invariant is
        proposal LIFECYCLE (`descartada` never resurfaces), independent of
        the auto-apply topology — and `pg_tickets_db`'s minimal schema
        (tickets + propuestas_ia only, no `tickets_historial`) doesn't carry
        the table auto-apply's domain write would need."""
        monkeypatch.setattr(settings, "TICKETS_TRIAGE_AUTO_APPLY", False)
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

        fake_provider = FakeProvider(
            json.dumps(
                _valid_triage_payload(
                    severidad="critica",
                    sector_codigo=ticket.sector.codigo,
                    tipo_ticket_codigo=ticket.tipo_ticket.codigo,
                )
            )
        )
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
    def test_discarded_titulo_stays_discarded_when_new_triage_run_proposes_again(self, pg_tickets_db, monkeypatch):
        """SCOPE: 'a discarded title proposal never resurfaces' — same
        invariant as severidad above, proven for the new `titulo` campo.
        Same `TICKETS_TRIAGE_AUTO_APPLY=False` pin, same reason."""
        monkeypatch.setattr(settings, "TICKETS_TRIAGE_AUTO_APPLY", False)
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

        fake_provider = FakeProvider(
            json.dumps(
                _valid_triage_payload(
                    confianza_global=0.9,
                    sector_codigo=ticket.sector.codigo,
                    tipo_ticket_codigo=ticket.tipo_ticket.codigo,
                )
            )
        )
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


class TestDescartarAplicadoIaAuto:
    """feat/tickets-triage-aplicar-directo: 'discarding an already-applied
    value must be expressible' — the UI consequence of the topology flip.
    A `confirmada` proposal with `confirmado_por_id IS NULL` (`ia_auto`,
    never reviewed) is the human REJECTING a value already live on the
    ticket, not approving a suggestion — `descartar()` must clear the
    ticket value AND its `<campo>_origen` for `CAMPOS_REVERTIBLES`, and
    still respect the 'never resurfaces' invariant on the proposal itself."""

    def test_descartar_ia_auto_severidad_clears_ticket_value_and_origen(self, db, rol_ventas):
        ticket = _make_ticket(db, rol_ventas)
        ticket.severidad = "critica"
        ticket.severidad_origen = "ia_auto"
        db.commit()
        usuario = _make_usuario(db, rol_ventas)
        propuesta = _make_propuesta(db, ticket, campo="severidad", valor="critica", estado="confirmada")
        assert propuesta.confirmado_por_id is None  # the ia_auto shape

        resultado = confirmacion_service.descartar(db, propuesta.id, usuario)

        assert resultado.estado == "descartada"
        assert resultado.confirmado_por_id == usuario.id  # who rejected it, recorded
        ticket = _reload(db, ticket)
        # decision #3: an ia_auto value being corrected/rejected must never
        # keep reading as 'IA automática' — the origen is cleared, not left
        # stale, the same "clearing clears provenance too" rule
        # `actualizar_ticket` already applies to urgencia.
        assert ticket.severidad is None
        assert ticket.severidad_origen is None

        historial = (
            db.query(HistorialTicket)
            .filter(HistorialTicket.ticket_id == ticket.id, HistorialTicket.accion == "propuesta_descartada")
            .all()
        )
        assert len(historial) == 1
        assert historial[0].cambios["campo"] == "severidad"

    def test_descartar_ia_auto_never_resurfaces_as_pendiente(self, db, rol_ventas):
        """Same hard invariant as the pendiente-discard case above, proven
        for the NEW ia_auto-discard path."""
        ticket = _make_ticket(db, rol_ventas)
        ticket.urgencia = "alta"
        ticket.urgencia_origen = "ia_auto"
        db.commit()
        usuario = _make_usuario(db, rol_ventas)
        propuesta = _make_propuesta(db, ticket, campo="urgencia", valor="alta", estado="confirmada")

        confirmacion_service.descartar(db, propuesta.id, usuario)

        db.refresh(propuesta)
        assert propuesta.estado == "descartada"

    def test_descartar_ia_auto_titulo_rejected_not_revertible(self, db, rol_ventas):
        """`titulo` is NOT NULL — there is no clean 'unset' state to revert
        to, so `descartar()` must refuse rather than guess, leaving both the
        ticket and the proposal exactly as they were."""
        ticket = _make_ticket(db, rol_ventas)
        ticket.titulo = "Titulo aplicado por la IA"
        ticket.titulo_origen = "ia_auto"
        db.commit()
        usuario = _make_usuario(db, rol_ventas)
        propuesta = _make_propuesta(db, ticket, campo="titulo", valor="Titulo aplicado por la IA", estado="confirmada")

        with pytest.raises(confirmacion_service.PropuestaNoDescartableError):
            confirmacion_service.descartar(db, propuesta.id, usuario)

        ticket = _reload(db, ticket)
        assert ticket.titulo == "Titulo aplicado por la IA"
        assert ticket.titulo_origen == "ia_auto"
        db.refresh(propuesta)
        assert propuesta.estado == "confirmada"  # untouched, not silently discarded

    def test_descartar_ia_auto_titulo_returns_409_over_http_not_500(self, client, db, rol_ventas):
        ticket = _make_ticket(db, rol_ventas)
        ticket.titulo = "Titulo aplicado por la IA"
        ticket.titulo_origen = "ia_auto"
        db.commit()
        usuario = _make_usuario(db, rol_ventas)
        _give_permiso(db, usuario)
        propuesta = _make_propuesta(db, ticket, campo="titulo", valor="Titulo aplicado por la IA", estado="confirmada")

        resp = client.post(
            f"/api/tickets/propuestas/{propuesta.id}/descartar",
            headers=_headers(usuario),
        )

        assert resp.status_code == 409
        assert resp.status_code != 500

    def test_descartar_ia_auto_stale_row_does_not_wipe_a_newer_human_correction(self, db, rol_ventas):
        """Real pre-push review finding: this proposal represents the value
        it applied at auto-apply time — but nothing keeps it in sync if a
        human corrects the SAME field through a different path
        (`actualizar_ticket`'s PATCH, e.g. a board drag), which never
        touches `tickets_propuestas_ia`. Discarding this now-STALE record
        must never destroy the newer human value — only mark it
        `descartada`."""
        ticket = _make_ticket(db, rol_ventas)
        ticket.urgencia = "baja"
        ticket.urgencia_origen = "ia_auto"
        db.commit()
        usuario = _make_usuario(db, rol_ventas)
        propuesta = _make_propuesta(db, ticket, campo="urgencia", valor="baja", estado="confirmada")

        # A human corrects it through the PATCH path — `descartar()` never
        # sees this write, exactly the gap the guard closes.
        ticket.urgencia = "inmediata"
        ticket.urgencia_origen = "humano"
        db.commit()

        resultado = confirmacion_service.descartar(db, propuesta.id, usuario)

        assert resultado.estado == "descartada"  # the stale record IS resolved
        ticket = _reload(db, ticket)
        assert ticket.urgencia == "inmediata"  # the human's newer value survives
        assert ticket.urgencia_origen == "humano"

    def test_descartar_human_confirmed_row_still_rejected_as_no_pendiente(self, db, rol_ventas):
        """A `confirmada` row with a NON-null `confirmado_por_id` (a human
        already ratified it via `confirmar()`) is a DIFFERENT case from
        ia_auto — nothing changed here, still rejected exactly like before
        this feature."""
        ticket = _make_ticket(db, rol_ventas)
        usuario = _make_usuario(db, rol_ventas)
        propuesta = _make_propuesta(db, ticket, campo="severidad", valor="mayor", estado="confirmada")
        propuesta.confirmado_por_id = usuario.id
        db.commit()

        with pytest.raises(confirmacion_service.PropuestaNoPendienteError):
            confirmacion_service.descartar(db, propuesta.id, usuario)


class TestConfirmarRatificaAplicadoIaAuto:
    """Real pre-push review finding (BLOCKING): before this, an already-
    applied `ia_auto` proposal outside `CAMPOS_REVERTIBLES` (titulo/sector/
    tipo_ticket/metadata_ia) had NO exit from "unreviewed" at all —
    `confirmar()` rejected it (`estado != 'pendiente'`) and `descartar()`
    rejected it too (`PropuestaNoDescartableError`). Every ticket
    auto-classified on one of those fields stayed in the board's
    unreviewed count FOREVER — exactly the "eternal pending" problem this
    feature (`TICKETS_TRIAGE_AUTO_APPLY`) was built to eliminate, just for
    a different subset of fields.

    `confirmar()` now RATIFIES an `ia_auto` row (sets `confirmado_por_id`/
    `confirmado_at` only) instead of rejecting it — the value is already on
    the ticket, so there is nothing to re-apply. This works for EVERY
    field, revertible or not: ratify ("I looked, it's fine") and discard
    ("correct it") are orthogonal actions; only discard is limited to
    `CAMPOS_REVERTIBLES`.
    """

    def test_confirmar_ia_auto_titulo_ratifies_without_touching_ticket(self, db, rol_ventas):
        """The exact non-revertible case with the worst gap: titulo has no
        clean 'unset' state, so before this fix there was NO way to mark it
        reviewed short of a full retrigger."""
        ticket = _make_ticket(db, rol_ventas)
        ticket.titulo = "Titulo aplicado por la IA"
        ticket.titulo_origen = "ia_auto"
        db.commit()
        usuario = _make_usuario(db, rol_ventas)
        propuesta = _make_propuesta(db, ticket, campo="titulo", valor="Titulo aplicado por la IA", estado="confirmada")
        assert propuesta.confirmado_por_id is None  # the ia_auto shape

        resultado = confirmacion_service.confirmar(db, propuesta.id, usuario)

        assert resultado.estado == "confirmada"
        assert resultado.confirmado_por_id == usuario.id
        assert resultado.confirmado_at is not None
        ticket = _reload(db, ticket)
        # Untouched — ratify never re-applies the value or origen.
        assert ticket.titulo == "Titulo aplicado por la IA"
        assert ticket.titulo_origen == "ia_auto"

        historial = (
            db.query(HistorialTicket)
            .filter(HistorialTicket.ticket_id == ticket.id, HistorialTicket.accion == "propuesta_ratificada")
            .all()
        )
        assert len(historial) == 1
        assert historial[0].cambios["campo"] == "titulo"

    def test_confirmar_ia_auto_sector_ratifies_without_domain_write(self, db, rol_ventas):
        """`sector` is the field with the strictest 'no revert' rule
        (moving it is a domain operation, `_confirmar_sector`) — ratify
        must never invoke that logic, only mark the proposal reviewed."""
        ticket = _make_ticket(db, rol_ventas)
        sector_original_id = ticket.sector_id
        usuario = _make_usuario(db, rol_ventas)
        # `valor_propuesto` deliberately does NOT reference a real sector
        # codigo — proving ratify never calls `_confirmar_sector` at all
        # (that call would fail loudly on a bogus codigo).
        propuesta = _make_propuesta(db, ticket, campo="sector", valor="codigo-inexistente", estado="confirmada")

        resultado = confirmacion_service.confirmar(db, propuesta.id, usuario)

        assert resultado.estado == "confirmada"
        assert resultado.confirmado_por_id == usuario.id
        ticket = _reload(db, ticket)
        assert ticket.sector_id == sector_original_id  # untouched

    def test_confirmar_ia_auto_severidad_ratify_leaves_revertible_value_untouched(self, db, rol_ventas):
        """Triangulation: ratify works identically for a REVERTIBLE field —
        it is orthogonal to `CAMPOS_REVERTIBLES`, which only gates
        `descartar()`."""
        ticket = _make_ticket(db, rol_ventas)
        ticket.severidad = "mayor"
        ticket.severidad_origen = "ia_auto"
        db.commit()
        usuario = _make_usuario(db, rol_ventas)
        propuesta = _make_propuesta(db, ticket, campo="severidad", valor="mayor", estado="confirmada")

        resultado = confirmacion_service.confirmar(db, propuesta.id, usuario)

        assert resultado.confirmado_por_id == usuario.id
        ticket = _reload(db, ticket)
        assert ticket.severidad == "mayor"
        assert ticket.severidad_origen == "ia_auto"  # still ia_auto, NOT bumped to ia_confirmada

    def test_confirmar_ia_auto_returns_200_over_http_not_409(self, client, db, rol_ventas):
        ticket = _make_ticket(db, rol_ventas)
        ticket.titulo = "Titulo aplicado por la IA"
        ticket.titulo_origen = "ia_auto"
        db.commit()
        usuario = _make_usuario(db, rol_ventas)
        _give_permiso(db, usuario)
        propuesta = _make_propuesta(db, ticket, campo="titulo", valor="Titulo aplicado por la IA", estado="confirmada")

        resp = client.post(
            f"/api/tickets/propuestas/{propuesta.id}/confirmar",
            headers=_headers(usuario),
        )

        assert resp.status_code == 200
        assert resp.json()["confirmado_por_id"] == usuario.id

    def test_confirmar_human_confirmed_row_still_rejected(self, db, rol_ventas):
        """A `confirmada` row with a NON-null `confirmado_por_id` (already
        ratified, or human-confirmed via the pendiente path) is a
        DIFFERENT, already-settled case — must stay rejected."""
        ticket = _make_ticket(db, rol_ventas)
        usuario = _make_usuario(db, rol_ventas)
        propuesta = _make_propuesta(db, ticket, campo="severidad", valor="mayor", estado="confirmada")
        propuesta.confirmado_por_id = usuario.id
        db.commit()

        with pytest.raises(confirmacion_service.PropuestaNoPendienteError):
            confirmacion_service.confirmar(db, propuesta.id, usuario)


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

    def test_batch_with_disallowed_campo_rejects_whole_batch_atomically(self, db, rol_ventas):
        """Defect 1 atomicity: one disallowed `campo` (here `estado_id`,
        the workflow-engine-bypass shape) in an otherwise-valid batch must
        roll back EVERY write in that batch — no partial writes, not even
        for the sibling proposal that was itself allowlisted."""
        ticket1 = _make_ticket(db, rol_ventas)
        ticket2 = _make_ticket(db, rol_ventas)
        usuario = _make_usuario(db, rol_ventas)
        p1 = _make_propuesta(db, ticket1, campo="severidad", valor="mayor")
        p2 = _transient_propuesta(ticket2.id, campo="estado_id", propuesta_id=900004, valor=999999)
        db.commit()

        with _stub_query_for(db, PropuestaIA, all_=[p1, p2]):
            with pytest.raises(confirmacion_service.PropuestaCampoNoPermitidoError):
                confirmacion_service.confirmar_batch(db, [p1.id, p2.id], usuario)

        ticket1_fresh = db.query(Ticket).filter(Ticket.id == ticket1.id).first()
        assert ticket1_fresh.severidad is None
        p1_fresh = db.query(PropuestaIA).filter(PropuestaIA.id == p1.id).first()
        assert p1_fresh.estado == "pendiente"
        ticket2_fresh = db.query(Ticket).filter(Ticket.id == ticket2.id).first()
        assert ticket2_fresh.estado_id == ticket2.estado_id

    def test_batch_missing_ticket_raises_domain_error_and_nothing_written(self, db, rol_ventas):
        ticket1 = _make_ticket(db, rol_ventas)
        usuario = _make_usuario(db, rol_ventas)
        p1 = _make_propuesta(db, ticket1, campo="severidad", valor="mayor")
        # Commit the arrange phase first (same reason as
        # `test_batch_partial_write_failure_rolls_back_the_whole_batch`
        # above): the service's own `db.rollback()` must only undo its
        # pending work, not this test's fixture data.
        db.commit()

        with _make_ticket_query_empty(db):
            with pytest.raises(confirmacion_service.TicketNoEncontradoError):
                confirmacion_service.confirmar_batch(db, [p1.id], usuario)

        # Post-rollback, `p1` is expired/detached (see the sibling
        # `test_batch_partial_write_failure_rolls_back_the_whole_batch`
        # test above) — a fresh query is the only reliable read here.
        p1_fresh = db.query(PropuestaIA).filter(PropuestaIA.id == p1.id).first()
        assert p1_fresh.estado == "pendiente"

    def test_batch_missing_ticket_returns_404_over_http(self, client, db, rol_ventas):
        ticket1 = _make_ticket(db, rol_ventas)
        usuario = _make_usuario(db, rol_ventas)
        _give_permiso(db, usuario)
        p1 = _make_propuesta(db, ticket1, campo="severidad", valor="mayor")

        with _make_ticket_query_empty(db):
            resp = client.post(
                "/api/tickets/propuestas/confirmar-batch",
                json={"propuesta_ids": [p1.id]},
                headers=_headers(usuario),
            )

        assert resp.status_code == 404
        assert resp.status_code != 500


class TestConfirmarSectorMovesEstadoAndHistory:
    """SC: 'confirming a sector moves sector_id AND estado_id to the
    target workflow's initial state, and writes history for both' — §3's
    domain dispatch. Confirming `sector` alone must never leave `estado_id`
    pointing at the OLD workflow's graph."""

    def test_confirmar_sector_moves_sector_and_estado_writes_history(self, db, rol_ventas):
        """Confirmed via `confirmar_batch` (sector + its matching tipo,
        auto-ordered): confirming `sector` ALONE now correctly requires the
        ticket's tipo to already belong there — see
        `test_confirmar_sector_solo_rejected_cuando_dejaria_tipo_huerfano`
        below (real pre-push review finding #2)."""
        ticket = _make_ticket(db, rol_ventas)
        estado_origen_id = ticket.estado_id
        sector_origen_id = ticket.sector_id
        destino, tipo_destino, estado_inicial_destino = _make_sector_con_workflow(db)
        usuario = _make_usuario(db, rol_ventas)
        propuesta_sector = _make_propuesta(db, ticket, campo="sector", valor=destino.codigo)
        propuesta_tipo = _make_propuesta(db, ticket, campo="tipo_ticket", valor=tipo_destino.codigo)

        resultado = confirmacion_service.confirmar_batch(db, [propuesta_sector.id, propuesta_tipo.id], usuario)

        assert {p.estado for p in resultado} == {"confirmada"}
        ticket = _reload(db, ticket)
        assert ticket.sector_id == destino.id
        assert ticket.sector_id != sector_origen_id
        assert ticket.tipo_ticket_id == tipo_destino.id
        assert ticket.estado_id == estado_inicial_destino.id
        assert ticket.estado_id != estado_origen_id

        historial = (
            db.query(HistorialTicket)
            .filter(HistorialTicket.ticket_id == ticket.id, HistorialTicket.accion == "propuesta_confirmada")
            .all()
        )
        assert len(historial) == 2
        sector_hist = next(h for h in historial if h.cambios["campo"] == "sector")
        assert sector_hist.estado_anterior_id == estado_origen_id
        assert sector_hist.estado_nuevo_id == estado_inicial_destino.id

    def test_confirmar_sector_invalido_rejected_and_ticket_unmodified(self, db, rol_ventas):
        ticket = _make_ticket(db, rol_ventas)
        sector_origen_id, estado_origen_id = ticket.sector_id, ticket.estado_id
        usuario = _make_usuario(db, rol_ventas)
        propuesta = _make_propuesta(db, ticket, campo="sector", valor="SECTOR_QUE_NO_EXISTE")

        with pytest.raises(confirmacion_service.PropuestaSectorInvalidoError):
            confirmacion_service.confirmar(db, propuesta.id, usuario)

        # An exception raised AFTER a partial write is still a bug — assert
        # the ticket's actual state, not just that an exception was raised.
        ticket = _reload(db, ticket)
        assert ticket.sector_id == sector_origen_id
        assert ticket.estado_id == estado_origen_id
        assert propuesta.estado == "pendiente"

    def test_confirmar_sector_solo_rejected_cuando_dejaria_tipo_huerfano(self, db, rol_ventas):
        """Real pre-push review finding #2, the mirror of
        `TestConfirmarTipoTicketSectorMismatch`: confirming `sector` ALONE
        (no `tipo_ticket` proposal in the same call) would leave
        `tipo_ticket_id` pointing at a tipo from the OLD sector — rejected,
        ticket left fully unmodified."""
        ticket = _make_ticket(db, rol_ventas)
        sector_origen_id = ticket.sector_id
        estado_origen_id = ticket.estado_id
        tipo_origen_id = ticket.tipo_ticket_id
        destino, _tipo, _estado = _make_sector_con_workflow(db)
        usuario = _make_usuario(db, rol_ventas)
        propuesta = _make_propuesta(db, ticket, campo="sector", valor=destino.codigo)

        with pytest.raises(confirmacion_service.PropuestaSectorDejaTipoHuerfanoError):
            confirmacion_service.confirmar(db, propuesta.id, usuario)

        ticket = _reload(db, ticket)
        assert ticket.sector_id == sector_origen_id
        assert ticket.estado_id == estado_origen_id
        assert ticket.tipo_ticket_id == tipo_origen_id
        assert propuesta.estado == "pendiente"

    def test_confirmar_sector_huerfano_returns_400_over_http_not_500(self, client, db, rol_ventas):
        """Real pre-push review finding (blocking): `PropuestaSectorDejaTipoHuerfanoError`
        was raised by the service but never imported/handled in
        `propuestas.py` — the common case of confirming a `sector`
        proposal alone from the UI would 500 instead of returning the
        explanatory 400. HTTP-level regression guard, per obs #1350's
        pattern: the service-level test above alone did not catch this."""
        ticket = _make_ticket(db, rol_ventas)
        destino, _tipo, _estado = _make_sector_con_workflow(db)
        usuario = _make_usuario(db, rol_ventas)
        _give_permiso(db, usuario)
        propuesta = _make_propuesta(db, ticket, campo="sector", valor=destino.codigo)

        resp = client.post(
            f"/api/tickets/propuestas/{propuesta.id}/confirmar",
            headers=_headers(usuario),
        )

        assert resp.status_code == 400
        assert resp.status_code != 500


class TestConfirmarTipoTicketSectorMismatch:
    """SC: 'confirming a tipo_ticket from a foreign sector is rejected and
    the ticket is left unmodified' — §3 + §4's ordering decision (single
    confirm REJECTS an out-of-order tipo_ticket)."""

    def test_confirmar_tipo_ticket_de_sector_ajeno_rejected_and_unmodified(self, db, rol_ventas):
        ticket = _make_ticket(db, rol_ventas)  # still in its ORIGIN sector
        tipo_original_id = ticket.tipo_ticket_id
        _destino, tipo_destino, _estado = _make_sector_con_workflow(db)  # ticket never moved here
        usuario = _make_usuario(db, rol_ventas)
        propuesta = _make_propuesta(db, ticket, campo="tipo_ticket", valor=tipo_destino.codigo)

        with pytest.raises(confirmacion_service.PropuestaTipoSectorInvalidoError):
            confirmacion_service.confirmar(db, propuesta.id, usuario)

        ticket = _reload(db, ticket)
        assert ticket.tipo_ticket_id == tipo_original_id
        assert propuesta.estado == "pendiente"

    def test_confirmar_tipo_ticket_after_sector_confirmed_succeeds(self, db, rol_ventas):
        """Companion GREEN case: once a ticket IS already inside a sector,
        confirming a tipo_ticket proposal for a DIFFERENT tipo within that
        SAME sector succeeds, no sector move needed. Built directly inside
        `destino` (rather than moving a ticket there first) to avoid a
        second `tipo_ticket` proposal on the same ticket, which SQLite's
        test-only FULL unique index on (ticket_id, campo) would reject
        regardless of `estado` — see `propuesta_ia.py`'s own docstring."""
        destino, tipo_destino, estado_inicial_destino = _make_sector_con_workflow(db, tipo_codigo="bug")
        creador = _make_usuario(db, rol_ventas)
        ticket = Ticket(
            titulo="Ticket ya en sector destino",
            prioridad=PrioridadTicket.MEDIA,
            sector_id=destino.id,
            tipo_ticket_id=tipo_destino.id,
            estado_id=estado_inicial_destino.id,
            creador_id=creador.id,
            campos_metadata={},
        )
        db.add(ticket)
        db.flush()
        usuario = _make_usuario(db, rol_ventas)

        otro_tipo = TipoTicket(
            sector_id=destino.id, codigo="feature", nombre="Feature", workflow_id=tipo_destino.workflow_id
        )
        db.add(otro_tipo)
        db.flush()
        propuesta_tipo = _make_propuesta(db, ticket, campo="tipo_ticket", valor=otro_tipo.codigo)

        resultado = confirmacion_service.confirmar(db, propuesta_tipo.id, usuario)

        assert resultado.estado == "confirmada"
        ticket = _reload(db, ticket)
        assert ticket.tipo_ticket_id == otro_tipo.id


class TestConfirmarTipoTicketMovesToOwnWorkflow:
    """Real pre-push review finding #1: `crear_ticket` resolves the
    workflow from the TIPO first, sector default only as fallback
    (`tickets.py`). `_confirmar_sector` moves `estado_id` to the sector's
    DEFAULT workflow's initial state; if the confirmed `tipo_ticket` has
    its OWN non-default workflow, `_confirmar_tipo_ticket` must move
    `estado_id` there too — never leave it stranded on the default
    workflow's graph."""

    def test_confirmar_tipo_con_workflow_propio_mueve_estado(self, db, rol_ventas):
        destino, _tipo_default, estado_inicial_default = _make_sector_con_workflow(db, tipo_codigo="bug")
        # A SECOND, non-default workflow in the SAME sector, with its own tipo.
        workflow_b = Workflow(sector_id=destino.id, nombre="WF No Default", es_default=False, activo=True)
        db.add(workflow_b)
        db.flush()
        estado_inicial_b = EstadoTicket(
            workflow_id=workflow_b.id, codigo="nuevo_b", nombre="Nuevo B", orden=1, es_inicial=True, es_final=False
        )
        db.add(estado_inicial_b)
        db.flush()
        tipo_b = TipoTicket(sector_id=destino.id, codigo="acceso", nombre="Acceso", workflow_id=workflow_b.id)
        db.add(tipo_b)
        db.flush()

        ticket = _make_ticket(db, rol_ventas)
        usuario = _make_usuario(db, rol_ventas)
        propuesta_sector = _make_propuesta(db, ticket, campo="sector", valor=destino.codigo)
        propuesta_tipo = _make_propuesta(db, ticket, campo="tipo_ticket", valor=tipo_b.codigo)

        confirmacion_service.confirmar_batch(db, [propuesta_sector.id, propuesta_tipo.id], usuario)

        ticket = _reload(db, ticket)
        assert ticket.sector_id == destino.id
        assert ticket.tipo_ticket_id == tipo_b.id
        # estado must be workflow_b's initial state, NOT the sector's
        # default-workflow initial state `_confirmar_sector` set first.
        assert ticket.estado_id == estado_inicial_b.id
        assert ticket.estado_id != estado_inicial_default.id

        historial = (
            db.query(HistorialTicket)
            .filter(HistorialTicket.ticket_id == ticket.id, HistorialTicket.accion == "propuesta_confirmada")
            .all()
        )
        tipo_hist = next(h for h in historial if h.cambios["campo"] == "tipo_ticket")
        assert tipo_hist.estado_anterior_id == estado_inicial_default.id
        assert tipo_hist.estado_nuevo_id == estado_inicial_b.id


class TestOrdenSectorAntesQueTipoEnBatch:
    """§4: 'batch confirm must not be able to produce an inconsistent
    pair.' Decision: single `confirmar()` REJECTS an out-of-order
    tipo_ticket (see `TestConfirmarTipoTicketSectorMismatch` above);
    `confirmar_batch()` instead AUTO-ORDERS — any `sector` proposal always
    applies before any `tipo_ticket` proposal in the same call."""

    def test_batch_confirms_sector_and_tipo_together_regardless_of_list_order(self, db, rol_ventas):
        ticket = _make_ticket(db, rol_ventas)
        destino, tipo_destino, estado_inicial_destino = _make_sector_con_workflow(db)
        usuario = _make_usuario(db, rol_ventas)
        propuesta_tipo = _make_propuesta(db, ticket, campo="tipo_ticket", valor=tipo_destino.codigo)
        propuesta_sector = _make_propuesta(db, ticket, campo="sector", valor=destino.codigo)

        # tipo_ticket's id sent FIRST in the batch — proves auto-ordering,
        # not accidental list order.
        resultado = confirmacion_service.confirmar_batch(db, [propuesta_tipo.id, propuesta_sector.id], usuario)

        assert {p.estado for p in resultado} == {"confirmada"}
        ticket = _reload(db, ticket)
        assert ticket.sector_id == destino.id
        assert ticket.tipo_ticket_id == tipo_destino.id
        assert ticket.estado_id == estado_inicial_destino.id


class TestConfirmarMetadataIa:
    """SC: 'area_probable/tamano/detalle land in campos_metadata on
    confirmation' — a MERGE into the existing JSONB blob, never an
    overwrite of unrelated keys already there."""

    def test_confirmar_metadata_ia_merges_into_campos_metadata(self, db, rol_ventas):
        ticket = _make_ticket(db, rol_ventas)
        ticket.campos_metadata = {"existing_key": "existing_value"}
        db.commit()
        usuario = _make_usuario(db, rol_ventas)
        valor = {
            "area_probable": "facturacion",
            "tamano": "M",
            "detalle": {"esperado": "x", "actual": "", "pasos": [], "alcance": "", "impacto": "", "workaround": ""},
        }
        propuesta = _make_propuesta(db, ticket, campo="metadata_ia", valor=valor)

        resultado = confirmacion_service.confirmar(db, propuesta.id, usuario)

        assert resultado.estado == "confirmada"
        ticket = _reload(db, ticket)
        assert ticket.campos_metadata["area_probable"] == "facturacion"
        assert ticket.campos_metadata["tamano"] == "M"
        assert ticket.campos_metadata["detalle"]["esperado"] == "x"
        assert ticket.campos_metadata["existing_key"] == "existing_value"  # merge, not overwrite


class TestCampoCheckConstraintPostgres:
    """@pytest.mark.postgres: 'the CHECK constraint accepts the new campos
    and still rejects garbage' — `ck_tickets_propuestas_ia_campo` mirrors
    `confirmacion_service.CAMPOS_CONFIRMABLES` at the DB layer, defense in
    depth added by PR #1095 and extended here."""

    @pytest.mark.postgres
    @pytest.mark.parametrize("campo", ["sector", "tipo_ticket", "metadata_ia"])
    def test_new_campos_accepted_by_check_constraint(self, pg_tickets_db, campo):
        db = pg_tickets_db
        rol = Rol(codigo="VENTAS", nombre="Ventas", es_sistema=False, orden=10, activo=True)
        db.add(rol)
        db.flush()
        ticket = _make_ticket(db, rol)

        db.add(PropuestaIA(ticket_id=ticket.id, campo=campo, valor_propuesto={"valor": "x"}))
        db.commit()  # must not raise

    @pytest.mark.postgres
    def test_garbage_campo_still_rejected_by_check_constraint(self, pg_tickets_db):
        db = pg_tickets_db
        rol = Rol(codigo="VENTAS", nombre="Ventas", es_sistema=False, orden=10, activo=True)
        db.add(rol)
        db.flush()
        ticket = _make_ticket(db, rol)

        db.add(PropuestaIA(ticket_id=ticket.id, campo="estado_id", valor_propuesto={"valor": 999}))
        with pytest.raises(IntegrityError):
            db.commit()


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

    def test_forzar_leaves_human_confirmed_untouched(self, client, db, rol_ventas):
        """A HUMAN-confirmed proposal (`confirmado_por_id` set — a decision
        a person already ratified) must never be silently replaced by a
        forced retrigger, unlike the `ia_auto` shape below."""
        ticket = _make_ticket(db, rol_ventas)
        usuario = _make_usuario(db, rol_ventas)
        _give_permiso(db, usuario)
        confirmada = _make_propuesta(db, ticket, estado="confirmada", confirmado_por_id=usuario.id)

        app.dependency_overrides[get_triage_provider] = lambda: FakeProvider("{}")
        with patch.object(propuestas_module.BackgroundTasks, "add_task") as mock_add_task:
            resp = client.post(
                TRIAGE_RETRIGGER_ENDPOINT.format(id=ticket.id), params={"forzar": "true"}, headers=_headers(usuario)
            )

        assert resp.status_code == 200
        mock_add_task.assert_called_once()
        db.refresh(confirmada)
        assert confirmada.estado == "confirmada"

    def test_forzar_degrades_unreviewed_ia_auto_to_reemplazada(self, client, db, rol_ventas):
        """Real pre-push review finding: with auto-apply, most proposals
        arrive already `confirmada` with `confirmado_por_id IS NULL`
        (`ia_auto`, never reviewed). Only degrading `pendiente` rows left
        every one of THESE active forever — `_ya_tiene_propuesta_activa`
        would then block EVERY field on the next `run_triage` call, making
        `forzar=true` return 200 and silently do nothing."""
        ticket = _make_ticket(db, rol_ventas)
        usuario = _make_usuario(db, rol_ventas)
        _give_permiso(db, usuario)
        ia_auto = _make_propuesta(db, ticket, estado="confirmada", confirmado_por_id=None)

        app.dependency_overrides[get_triage_provider] = lambda: FakeProvider("{}")
        with patch.object(propuestas_module.BackgroundTasks, "add_task") as mock_add_task:
            resp = client.post(
                TRIAGE_RETRIGGER_ENDPOINT.format(id=ticket.id), params={"forzar": "true"}, headers=_headers(usuario)
            )

        assert resp.status_code == 200
        mock_add_task.assert_called_once()
        db.refresh(ia_auto)
        assert ia_auto.estado == "reemplazada"

    def test_retrigger_without_permiso_returns_403(self, client, db, rol_ventas):
        ticket = _make_ticket(db, rol_ventas)
        usuario = _make_usuario(db, rol_ventas)

        resp = client.post(TRIAGE_RETRIGGER_ENDPOINT.format(id=ticket.id), headers=_headers(usuario))

        assert resp.status_code == 403

    def test_refuses_without_forzar_when_corregida_exists(self, client, db, rol_ventas):
        """Audit item 2 of 3 (design's `estado` consumer audit,
        propuestas.py:189-193): a `corregida` proposal is a settled human
        decision — the retrigger guard's `estado.in_(...)` tuple must
        include it, or a plain retrigger (no `forzar`) would silently
        proceed and re-surface a field the human already corrected."""
        ticket = _make_ticket(db, rol_ventas)
        usuario = _make_usuario(db, rol_ventas)
        _give_permiso(db, usuario)
        _make_propuesta(db, ticket, estado="corregida")

        app.dependency_overrides[get_triage_provider] = lambda: FakeProvider("{}")
        with patch.object(propuestas_module.BackgroundTasks, "add_task") as mock_add_task:
            resp = client.post(TRIAGE_RETRIGGER_ENDPOINT.format(id=ticket.id), headers=_headers(usuario))

        assert resp.status_code == 409
        mock_add_task.assert_not_called()

    def test_forzar_leaves_corregida_untouched(self, client, db, rol_ventas):
        """The `forzar` degrade loop (propuestas.py:211-215) must NOT touch
        a `corregida` row — a human correction is exactly as settled as a
        human ratification (`ia_confirmada`), never silently replaced."""
        ticket = _make_ticket(db, rol_ventas)
        usuario = _make_usuario(db, rol_ventas)
        _give_permiso(db, usuario)
        corregida = _make_propuesta(db, ticket, estado="corregida", confirmado_por_id=usuario.id)

        app.dependency_overrides[get_triage_provider] = lambda: FakeProvider("{}")
        with patch.object(propuestas_module.BackgroundTasks, "add_task") as mock_add_task:
            resp = client.post(
                TRIAGE_RETRIGGER_ENDPOINT.format(id=ticket.id), params={"forzar": "true"}, headers=_headers(usuario)
            )

        assert resp.status_code == 200
        mock_add_task.assert_called_once()
        db.refresh(corregida)
        assert corregida.estado == "corregida"


class TestResolverCorreccion:
    """Task 3: `confirmacion_service._resolver_correccion` — pure unit,
    no DB. Normalises a corrected value into `str | None` BEFORE the
    existing two-shape branch in `confirmar()`: `None` means "treat as a
    plain ratification", collapsing a same-value confirm to `None` too."""

    def test_none_input_returns_none(self, db, rol_ventas):
        ticket = _make_ticket(db, rol_ventas)
        propuesta = _make_propuesta(db, ticket, campo="severidad", valor="mayor")

        assert confirmacion_service._resolver_correccion(propuesta, None) is None

    def test_ineligible_campo_raises(self, db, rol_ventas):
        ticket = _make_ticket(db, rol_ventas)
        propuesta = _make_propuesta(db, ticket, campo="titulo", valor="Un titulo")

        with pytest.raises(confirmacion_service.CorreccionCampoNoPermitidoError):
            confirmacion_service._resolver_correccion(propuesta, "cualquier cosa")

    def test_out_of_vocabulary_value_raises(self, db, rol_ventas):
        ticket = _make_ticket(db, rol_ventas)
        propuesta = _make_propuesta(db, ticket, campo="urgencia", valor="baja")

        with pytest.raises(confirmacion_service.CorreccionValorInvalidoError):
            confirmacion_service._resolver_correccion(propuesta, "urgentisimo")

    def test_same_value_as_proposed_collapses_to_none(self, db, rol_ventas):
        """Spec: 'A Confirm Carrying The Same Value Is A Ratification, Not
        A Correction' — collapsing to `None` HERE is what lets both shapes
        of `confirmar()` stay unchanged for a same-value confirm."""
        ticket = _make_ticket(db, rol_ventas)
        propuesta = _make_propuesta(db, ticket, campo="severidad", valor="mayor")

        assert confirmacion_service._resolver_correccion(propuesta, "mayor") is None

    def test_differing_valid_value_returns_it(self, db, rol_ventas):
        ticket = _make_ticket(db, rol_ventas)
        propuesta = _make_propuesta(db, ticket, campo="severidad", valor="mayor")

        assert confirmacion_service._resolver_correccion(propuesta, "menor") == "menor"


class TestConfirmarConValorCorregido:
    """Task 7: the corrected-confirm integration tests, both shapes."""

    def test_pending_proposal_correction_writes_ticket_origen_and_historial(self, db, rol_ventas):
        """SC: Corrected confirm updates ticket, origen, and historial in
        one transaction."""
        ticket = _make_ticket(db, rol_ventas)
        usuario = _make_usuario(db, rol_ventas)
        propuesta = _make_propuesta(db, ticket, campo="severidad", valor="mayor")

        resultado = confirmacion_service.confirmar(db, propuesta.id, usuario, valor_corregido="menor")

        assert resultado.estado == "corregida"
        assert resultado.valor_corregido == "menor"
        assert resultado.confirmado_por_id == usuario.id

        ticket = _reload(db, ticket)
        assert ticket.severidad == "menor"
        assert ticket.severidad_origen == "humano"

        historial = (
            db.query(HistorialTicket)
            .filter(HistorialTicket.ticket_id == ticket.id, HistorialTicket.accion == "propuesta_corregida")
            .all()
        )
        assert len(historial) == 1
        assert historial[0].cambios["campo"] == "severidad"
        assert historial[0].cambios["valor_propuesto"] == "mayor"
        assert historial[0].cambios["valor_corregido"] == "menor"

    def test_unreviewed_ia_auto_correction_overwrites_applied_value(self, db, rol_ventas):
        """The second shape: an unreviewed `ia_auto` proposal
        (`estado='confirmada'`, `confirmado_por_id IS NULL`) that already
        applied its value onto the ticket — a corrected confirm must
        OVERWRITE that value, not merely ratify it."""
        ticket = _make_ticket(db, rol_ventas)
        ticket.urgencia = "baja"
        ticket.urgencia_origen = "ia_auto"
        db.commit()
        usuario = _make_usuario(db, rol_ventas)
        propuesta = _make_propuesta(db, ticket, campo="urgencia", valor="baja", estado="confirmada")
        assert propuesta.confirmado_por_id is None  # the ia_auto shape

        resultado = confirmacion_service.confirmar(db, propuesta.id, usuario, valor_corregido="inmediata")

        assert resultado.estado == "corregida"
        assert resultado.valor_corregido == "inmediata"
        ticket = _reload(db, ticket)
        assert ticket.urgencia == "inmediata"
        assert ticket.urgencia_origen == "humano"

    def test_same_value_confirm_ratifies_not_corrects(self, db, rol_ventas):
        ticket = _make_ticket(db, rol_ventas)
        usuario = _make_usuario(db, rol_ventas)
        propuesta = _make_propuesta(db, ticket, campo="severidad", valor="mayor")

        resultado = confirmacion_service.confirmar(db, propuesta.id, usuario, valor_corregido="mayor")

        assert resultado.estado == "confirmada"
        assert resultado.valor_corregido is None
        ticket = _reload(db, ticket)
        assert ticket.severidad == "mayor"
        assert ticket.severidad_origen == "ia_confirmada"

    def test_ineligible_campo_returns_400_and_leaves_ticket_untouched(self, db, rol_ventas):
        ticket = _make_ticket(db, rol_ventas)
        usuario = _make_usuario(db, rol_ventas)
        propuesta = _make_propuesta(db, ticket, campo="titulo", valor="Titulo original")

        with pytest.raises(confirmacion_service.CorreccionCampoNoPermitidoError):
            confirmacion_service.confirmar(db, propuesta.id, usuario, valor_corregido="Otro titulo")

        ticket = _reload(db, ticket)
        assert ticket.titulo != "Otro titulo"
        db.refresh(propuesta)
        assert propuesta.estado == "pendiente"

    def test_out_of_vocabulary_value_returns_400_and_leaves_proposal_pendiente(self, db, rol_ventas):
        ticket = _make_ticket(db, rol_ventas)
        usuario = _make_usuario(db, rol_ventas)
        propuesta = _make_propuesta(db, ticket, campo="urgencia", valor="baja")

        with pytest.raises(confirmacion_service.CorreccionValorInvalidoError):
            confirmacion_service.confirmar(db, propuesta.id, usuario, valor_corregido="urgentisimo")

        db.refresh(propuesta)
        assert propuesta.estado == "pendiente"
        ticket = _reload(db, ticket)
        assert ticket.urgencia is None

    def test_ineligible_campo_returns_400_over_http(self, client, db, rol_ventas):
        ticket = _make_ticket(db, rol_ventas)
        usuario = _make_usuario(db, rol_ventas)
        _give_permiso(db, usuario)
        propuesta = _make_propuesta(db, ticket, campo="titulo", valor="Titulo original")

        resp = client.post(
            f"/api/tickets/propuestas/{propuesta.id}/confirmar",
            json={"valor_corregido": "Otro titulo"},
            headers=_headers(usuario),
        )

        assert resp.status_code == 400
        ticket = _reload(db, ticket)
        assert ticket.titulo != "Otro titulo"

    def test_out_of_vocabulary_value_returns_400_over_http(self, client, db, rol_ventas):
        ticket = _make_ticket(db, rol_ventas)
        usuario = _make_usuario(db, rol_ventas)
        _give_permiso(db, usuario)
        propuesta = _make_propuesta(db, ticket, campo="urgencia", valor="baja")

        resp = client.post(
            f"/api/tickets/propuestas/{propuesta.id}/confirmar",
            json={"valor_corregido": "urgentisimo"},
            headers=_headers(usuario),
        )

        assert resp.status_code == 400
        db.refresh(propuesta)
        assert propuesta.estado == "pendiente"

    def test_corrected_confirm_without_permiso_returns_403(self, client, db, rol_ventas):
        ticket = _make_ticket(db, rol_ventas)
        usuario = _make_usuario(db, rol_ventas)
        propuesta = _make_propuesta(db, ticket, campo="severidad", valor="mayor")

        resp = client.post(
            f"/api/tickets/propuestas/{propuesta.id}/confirmar",
            json={"valor_corregido": "menor"},
            headers=_headers(usuario),
        )

        assert resp.status_code == 403
        ticket = _reload(db, ticket)
        assert ticket.severidad is None

    def test_corrected_confirm_succeeds_over_http(self, client, db, rol_ventas):
        ticket = _make_ticket(db, rol_ventas)
        usuario = _make_usuario(db, rol_ventas)
        _give_permiso(db, usuario)
        propuesta = _make_propuesta(db, ticket, campo="severidad", valor="mayor")

        resp = client.post(
            f"/api/tickets/propuestas/{propuesta.id}/confirmar",
            json={"valor_corregido": "menor"},
            headers=_headers(usuario),
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["estado"] == "corregida"
        assert body["valor_corregido"] == "menor"
