"""Tests for AI ticket triage (tickets-ai-triage PR 4a): `TriagePropuesta`
parsing, parser isolation from the ML-bot schema, the per-field confidence
gate, `run_triage`'s degradation paths, and the `crear_ticket` endpoint's
`BackgroundTasks` scheduling.

No pytest-asyncio in this project — async code is driven with
`asyncio.run(...)` (see `tests/unit/test_ml_bot_drafting_service.py`).

Written FIRST (RED phase) per strict TDD.

Run:
    cd backend && source venv/bin/activate
    pytest tests/tickets/test_triage_service.py -v
"""

import asyncio
import json
from unittest.mock import patch

import pytest
from pydantic import ValidationError

import app.tickets.api.endpoints.tickets as tickets_module
from app.core.config import Settings
from app.core.security import create_access_token, get_password_hash
from app.main import app
from app.models.rol import Rol
from app.models.usuario import AuthProvider, RolUsuario, Usuario
from app.services.ml_questions.llm_provider import LlmProviderError, parse_llm_output
from app.tickets.api.deps import get_triage_provider
from app.tickets.models.propuesta_ia import PropuestaIA
from app.tickets.models.sector import Sector
from app.tickets.models.ticket import PrioridadTicket, Ticket
from app.tickets.models.tipo_ticket import TipoTicket
from app.tickets.models.workflow import EstadoTicket, TransicionEstado, Workflow
from app.tickets.services.triage_service import (
    TriagePropuesta,
    pasa_umbral_confianza,
    run_triage,
)

INBOX_SECTOR_CODIGO = "INBOX"
INBOX_TIPO_CODIGO = "SIN_CLASIFICAR"

_seq = [0]


class FakeProvider:
    """Duck-typed `LlmProvider` — never touches the network. `calls` counts
    `complete()` invocations so tests can assert zero network calls when a
    degradation path is expected to short-circuit before calling it."""

    def __init__(self, response=None, configured=True, raises=None, model="fake-model"):
        self.response = response
        self._configured = configured
        self.raises = raises
        self.model = model
        self.calls = 0

    def is_configured(self) -> bool:
        return self._configured

    async def complete(self, system_prompt: str, user_payload: str) -> str:
        self.calls += 1
        if self.raises is not None:
            raise self.raises
        return self.response


class _FakeBackgroundDb:
    """Stands in for `get_background_db()` in tests, reusing the test's own
    transactional `db` fixture instead of opening a real second connection.
    Mirrors the real contract: commit on success, rollback on exception."""

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


def _patch_background_db(db):
    return patch("app.tickets.services.triage_service.get_background_db", return_value=_FakeBackgroundDb(db))


def _valid_payload(**overrides) -> dict:
    payload = {
        "tipo": "bug",
        "titulo": "Arreglar error de facturación",
        "resumen": "El usuario no puede facturar desde ayer",
        "severidad": "mayor",
        "urgencia": "alta",
        "confianza_severidad": 0.82,
        "confianza_urgencia": 0.9,
        "confianza_global": 0.85,
        "detalle": {
            "esperado": "Poder facturar",
            "actual": "El botón de facturar no responde",
            "pasos": ["Ir a Ventas", "Click en Facturar"],
            "alcance": "Un usuario",
            "impacto": "No puede vender",
            "workaround": "",
        },
        "area_probable": "facturacion",
        "tamano": "M",
    }
    payload.update(overrides)
    return payload


def _make_sector(db, codigo: str) -> Sector:
    sector = Sector(codigo=codigo, nombre="Sector Triage Test", activo=True, configuracion={})
    db.add(sector)
    db.flush()
    return sector


def _make_tipo_y_estado(db, sector: Sector) -> tuple[TipoTicket, EstadoTicket]:
    workflow = Workflow(sector_id=sector.id, nombre="WF Triage Test", es_default=True, activo=True)
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
        nombre="Triage Test User",
        password_hash=get_password_hash("pass"),
        rol=RolUsuario.VENTAS,
        rol_id=rol.id,
        auth_provider=AuthProvider.LOCAL,
        activo=True,
    )
    db.add(usuario)
    db.flush()
    return usuario


def _make_ticket(db, rol: Rol, suffix: str, texto: str = "No puedo facturar desde ayer") -> Ticket:
    _seq[0] += 1
    sector = _make_sector(db, codigo=f"TRIAGE_TEST_{suffix}_{_seq[0]}")
    tipo, estado = _make_tipo_y_estado(db, sector)
    creador = _make_usuario(db, rol, username=f"triage_test_user_{suffix}_{_seq[0]}")

    ticket = Ticket(
        titulo="Ticket para triage",
        prioridad=PrioridadTicket.MEDIA,
        sector_id=sector.id,
        tipo_ticket_id=tipo.id,
        estado_id=estado.id,
        creador_id=creador.id,
        campos_metadata={},
        texto_original=texto,
    )
    db.add(ticket)
    db.flush()
    return ticket


class TestTriagePropuestaValidation:
    """4a.1: table-driven Pydantic units, no DB, no network."""

    def test_valid_payload_parses(self) -> None:
        propuesta = TriagePropuesta(**_valid_payload())
        assert propuesta.tipo == "bug"
        assert propuesta.severidad == "mayor"
        assert propuesta.detalle.pasos == ["Ir a Ventas", "Click en Facturar"]

    def test_extra_field_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TriagePropuesta(**_valid_payload(campo_inventado="x"))

    def test_missing_required_field_rejected(self) -> None:
        payload = _valid_payload()
        del payload["tipo"]
        with pytest.raises(ValidationError):
            TriagePropuesta(**payload)

    def test_out_of_range_confianza_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TriagePropuesta(**_valid_payload(confianza_global=1.5))

    def test_unknown_enum_value_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TriagePropuesta(**_valid_payload(tipo="incidencia"))

    def test_null_severidad_and_confianza_is_valid(self) -> None:
        """'Return null with low confidence rather than guess' — null must
        be an accepted value, not an error."""
        propuesta = TriagePropuesta(**_valid_payload(severidad=None, confianza_severidad=None))
        assert propuesta.severidad is None
        assert propuesta.confianza_severidad is None


class TestNormalizeStringNull:
    """Real pre-push review finding: the prompt asks the model to return a
    JSON `null` for an unsure field, but a model can still literally emit
    the STRING "null". Because the schema is closed and all-or-nothing,
    that single wrong token would otherwise fail the ENTIRE proposal —
    including a sibling field that WAS confidently classified."""

    def test_string_null_severidad_normalizes_to_none(self) -> None:
        propuesta = TriagePropuesta(**_valid_payload(severidad="null"))
        assert propuesta.severidad is None

    def test_string_null_does_not_drop_sibling_field(self) -> None:
        """The exact bug: without normalization, this payload raises
        ValidationError and the whole proposal — including the confidently
        classified `urgencia` — is lost."""
        propuesta = TriagePropuesta(**_valid_payload(severidad="null", confianza_severidad=None))
        assert propuesta.severidad is None
        assert propuesta.urgencia == "alta"
        assert propuesta.confianza_urgencia == 0.9

    def test_real_severidad_value_is_untouched(self) -> None:
        propuesta = TriagePropuesta(**_valid_payload(severidad="critica"))
        assert propuesta.severidad == "critica"


class TestTriageMinConfianzaBounds:
    """Real pre-push review finding: an unbounded float lets a typo like
    `6` instead of `0.6` in `.env` silently disable triage forever (no
    confianza value would ever reach it) — must fail loudly at startup."""

    def test_out_of_range_value_raises_at_construction(self) -> None:
        """Matches the field name in the error, not just `ValidationError`
        broadly — the test environment already has required Settings
        fields (SECRET_KEY/DATABASE_URL/ERP_BASE_URL) set via env vars, so
        an unrelated missing-field error would also raise ValidationError
        and pass this test for the wrong reason (obs #1350's lesson)."""
        with pytest.raises(ValidationError, match="TICKETS_TRIAGE_MIN_CONFIANZA"):
            Settings(TICKETS_TRIAGE_MIN_CONFIANZA=6)

    def test_negative_value_raises_at_construction(self) -> None:
        with pytest.raises(ValidationError, match="TICKETS_TRIAGE_MIN_CONFIANZA"):
            Settings(TICKETS_TRIAGE_MIN_CONFIANZA=-0.1)


class TestParserIsolation:
    """4a.3: `TriagePropuesta` validates a ticket-shaped payload that FAILS
    the ML bot's `_REQUIRED_FIELDS` check — the guard against someone
    'helpfully' unifying the two parsers later."""

    def test_ticket_payload_validates_but_fails_ml_bot_parser(self) -> None:
        payload = _valid_payload()

        propuesta = TriagePropuesta(**payload)
        assert propuesta.tipo == "bug"

        with pytest.raises(LlmProviderError):
            parse_llm_output(json.dumps(payload))


class TestPasaUmbralConfianza:
    """Pure-function unit tests for the gate, no DB."""

    def test_none_is_below_threshold(self) -> None:
        assert pasa_umbral_confianza(None) is False

    def test_below_threshold_is_gated(self) -> None:
        assert pasa_umbral_confianza(0.4) is False

    def test_at_or_above_threshold_passes(self) -> None:
        assert pasa_umbral_confianza(0.6) is True
        assert pasa_umbral_confianza(0.85) is True


class TestConfidenceGatePerField:
    """4a.4/4a.6: fake-provider proof that the gate is per-field — a gated
    field writes zero rows while its sibling still writes one."""

    def test_gated_field_writes_nothing_sibling_still_writes(self, db, rol_ventas) -> None:
        ticket = _make_ticket(db, rol_ventas, "gate")
        payload = _valid_payload(confianza_severidad=0.4, confianza_urgencia=0.85)
        provider = FakeProvider(response=json.dumps(payload))

        with _patch_background_db(db):
            asyncio.run(run_triage(ticket.id, provider))

        propuestas = db.query(PropuestaIA).filter(PropuestaIA.ticket_id == ticket.id).all()
        assert {p.campo for p in propuestas} == {"urgencia"}
        assert propuestas[0].valor_propuesto == {"valor": "alta"}

    def test_null_confianza_treated_as_below_threshold(self, db, rol_ventas) -> None:
        ticket = _make_ticket(db, rol_ventas, "gate-null")
        payload = _valid_payload(confianza_severidad=None, confianza_urgencia=None)
        provider = FakeProvider(response=json.dumps(payload))

        with _patch_background_db(db):
            asyncio.run(run_triage(ticket.id, provider))

        assert db.query(PropuestaIA).filter(PropuestaIA.ticket_id == ticket.id).count() == 0


class TestRunTriageDirectCall:
    """4a.6: `run_triage` called directly with a fake provider writes
    proposal rows, exactly one in-process call, zero network."""

    def test_writes_pending_rows_with_zero_network(self, db, rol_ventas) -> None:
        ticket = _make_ticket(db, rol_ventas, "direct")
        provider = FakeProvider(response=json.dumps(_valid_payload()))

        with _patch_background_db(db):
            asyncio.run(run_triage(ticket.id, provider))

        assert provider.calls == 1
        propuestas = db.query(PropuestaIA).filter(PropuestaIA.ticket_id == ticket.id).all()
        assert {p.campo for p in propuestas} == {"severidad", "urgencia"}
        for p in propuestas:
            assert p.estado == "pendiente"
            assert p.modelo == provider.model


class TestSessionNotHeldAcrossNetworkCall:
    """Real pre-push review finding (CRITICAL, matches the 2026-06-24 pool
    exhaustion incident fixed by PR #811): the DB session must NEVER be
    held open across `await provider.complete()` — a burst of ticket
    creations holding a pool connection idle for ~45s each would exhaust
    the connection pool for the whole application, not just triage.
    Proven structurally: the read session opens and CLOSES BEFORE the
    network call, and a fresh session opens only AFTER it returns."""

    def test_session_closes_before_network_call_and_reopens_after(self, db, rol_ventas) -> None:
        ticket = _make_ticket(db, rol_ventas, "pool")
        events: list[str] = []

        class _TrackingCtx(_FakeBackgroundDb):
            def __enter__(self):
                events.append("enter")
                return super().__enter__()

            def __exit__(self, exc_type, exc, tb):
                events.append("exit")
                return super().__exit__(exc_type, exc, tb)

        provider = FakeProvider(response=json.dumps(_valid_payload()))
        real_complete = provider.complete

        async def _tracked_complete(system_prompt: str, user_payload: str) -> str:
            events.append("network_call")
            return await real_complete(system_prompt, user_payload)

        provider.complete = _tracked_complete

        with patch("app.tickets.services.triage_service.get_background_db", return_value=_TrackingCtx(db)):
            asyncio.run(run_triage(ticket.id, provider))

        assert events == ["enter", "exit", "network_call", "enter", "exit"]


class TestWriteRaceDegradesGracefully:
    """Real pre-push review finding: `_ya_tiene_propuesta_activa` shrinks
    the race window but does not close it — a genuine unique-index
    conflict at commit time (the documented last-resort backstop for a
    true race) must degrade like every other failure, never raise out of
    `run_triage`. SQLite's test-only FULL unique index on
    (ticket_id, campo) — stricter than Postgres's WHERE-pendiente partial
    index — gives a deterministic way to trigger a write-phase
    IntegrityError without needing real concurrency."""

    def test_unique_index_conflict_at_commit_does_not_raise(self, db, rol_ventas) -> None:
        ticket = _make_ticket(db, rol_ventas, "race")
        # estado='descartada': the app-level check only looks at
        # pendiente/confirmada, so it does NOT skip this field — but
        # SQLite's full unique index still rejects a second row for the
        # same (ticket_id, campo) regardless of estado.
        db.add(
            PropuestaIA(
                ticket_id=ticket.id,
                campo="severidad",
                valor_propuesto={"valor": "trivial"},
                estado="descartada",
            )
        )
        db.flush()

        provider = FakeProvider(response=json.dumps(_valid_payload()))

        with _patch_background_db(db):
            asyncio.run(run_triage(ticket.id, provider))  # must not raise


class TestDegradationNotConfigured:
    """4a.9: unset key -> `is_configured()` False -> skipped, logged, zero
    network calls, ticket stays fully usable."""

    def test_unconfigured_provider_writes_nothing_and_never_calls_complete(self, db, rol_ventas) -> None:
        ticket = _make_ticket(db, rol_ventas, "unconf")
        provider = FakeProvider(configured=False)

        with patch("app.tickets.services.triage_service.get_background_db") as mock_bg:
            asyncio.run(run_triage(ticket.id, provider))
            mock_bg.assert_not_called()

        assert provider.calls == 0
        assert db.query(PropuestaIA).filter(PropuestaIA.ticket_id == ticket.id).count() == 0


class TestDegradationProviderFails:
    """4a.10: provider raises/times out or returns malformed output -> zero
    rows, no retry scheduled (there is no retry mechanism in this module)."""

    def test_provider_raises_writes_nothing(self, db, rol_ventas) -> None:
        ticket = _make_ticket(db, rol_ventas, "fails")
        provider = FakeProvider(raises=LlmProviderError("boom"))

        with _patch_background_db(db):
            asyncio.run(run_triage(ticket.id, provider))

        assert provider.calls == 1
        assert db.query(PropuestaIA).filter(PropuestaIA.ticket_id == ticket.id).count() == 0

    def test_malformed_response_writes_nothing(self, db, rol_ventas) -> None:
        ticket = _make_ticket(db, rol_ventas, "malformed")
        provider = FakeProvider(response="esto no es json")

        with _patch_background_db(db):
            asyncio.run(run_triage(ticket.id, provider))

        assert db.query(PropuestaIA).filter(PropuestaIA.ticket_id == ticket.id).count() == 0


class TestDuplicateProposalGuard:
    """SCOPE: 'if a confirmada or pendiente row already exists for the
    ticket, refuse to write duplicates' — the app-level check that makes
    the partial unique index a last-resort backstop for a real race,
    rather than the primary mechanism."""

    def test_existing_pending_row_blocks_a_second_write_sibling_still_writes(self, db, rol_ventas) -> None:
        ticket = _make_ticket(db, rol_ventas, "dup")
        db.add(PropuestaIA(ticket_id=ticket.id, campo="severidad", valor_propuesto={"valor": "critica"}))
        db.flush()

        provider = FakeProvider(response=json.dumps(_valid_payload()))

        with _patch_background_db(db):
            asyncio.run(run_triage(ticket.id, provider))

        severidad_rows = (
            db.query(PropuestaIA).filter(PropuestaIA.ticket_id == ticket.id, PropuestaIA.campo == "severidad").all()
        )
        assert len(severidad_rows) == 1
        assert severidad_rows[0].valor_propuesto == {"valor": "critica"}  # untouched, not overwritten

        urgencia_rows = (
            db.query(PropuestaIA).filter(PropuestaIA.ticket_id == ticket.id, PropuestaIA.campo == "urgencia").all()
        )
        assert len(urgencia_rows) == 1  # sibling field still writes


TICKETS_ENDPOINT = "/api/tickets/tickets"


def _headers(user: Usuario) -> dict:
    token = create_access_token(data={"sub": user.username})
    return {"Authorization": f"Bearer {token}"}


def _seed_inbox(db) -> None:
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
    estado_final = EstadoTicket(workflow_id=wf.id, codigo="cerrado", nombre="Cerrado", orden=2, es_final=True)
    db.add_all([estado_inicial, estado_final])
    db.flush()

    db.add(
        TransicionEstado(
            workflow_id=wf.id, estado_origen_id=estado_inicial.id, estado_destino_id=estado_final.id, nombre="Cerrar"
        )
    )
    db.flush()


class TestCrearTicketSchedulesTriage:
    """4a.13/4a.15: `POST /tickets` returns 201, schedules `run_triage` via
    `background_tasks.add_task` — never awaited inline, never a real
    network call — with the provider injected via
    `app.dependency_overrides[get_triage_provider]`."""

    def test_add_task_scheduled_never_awaited(self, client, db, rol_ventas) -> None:
        _seq[0] += 1
        user = _make_usuario(db, rol_ventas, username=f"triage_endpoint_user_{_seq[0]}")
        _seed_inbox(db)

        fake_provider = FakeProvider(response=json.dumps(_valid_payload()))
        app.dependency_overrides[get_triage_provider] = lambda: fake_provider

        with patch.object(tickets_module.BackgroundTasks, "add_task") as mock_add_task:
            resp = client.post(
                TICKETS_ENDPOINT,
                json={"texto": "No puedo facturar desde ayer"},
                headers=_headers(user),
            )

        assert resp.status_code == 201
        mock_add_task.assert_called_once()
        called_args = mock_add_task.call_args.args
        assert called_args[0] is run_triage
        assert called_args[1] == resp.json()["id"]
        assert called_args[2] is fake_provider
        # never awaited inline, never a real network call:
        assert fake_provider.calls == 0

    def test_titulo_only_creation_does_not_schedule_triage(self, client, db, rol_ventas) -> None:
        """Real pre-push review finding: the legacy titulo-only path (no
        `texto`) leaves `texto_original` NULL — scheduling `run_triage`
        there just opens a DB session to log a no-op warning on every
        normal advanced-form submission."""
        _seq[0] += 1
        user = _make_usuario(db, rol_ventas, username=f"triage_endpoint_titulo_only_{_seq[0]}")
        _seed_inbox(db)

        fake_provider = FakeProvider(response=json.dumps(_valid_payload()))
        app.dependency_overrides[get_triage_provider] = lambda: fake_provider

        with patch.object(tickets_module.BackgroundTasks, "add_task") as mock_add_task:
            resp = client.post(
                TICKETS_ENDPOINT,
                json={"titulo": "Solicitud de acceso a reportes"},
                headers=_headers(user),
            )

        assert resp.status_code == 201
        mock_add_task.assert_not_called()
