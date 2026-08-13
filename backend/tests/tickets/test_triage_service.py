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
from app.core.config import Settings, settings
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
    _ya_tiene_propuesta_activa,
    catalogo_sectores_activos,
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
        self.last_user_payload: str | None = None

    def is_configured(self) -> bool:
        return self._configured

    async def complete(self, system_prompt: str, user_payload: str) -> str:
        self.calls += 1
        self.last_user_payload = user_payload
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
    """Placeholder `sector_codigo`/`tipo_ticket_codigo` — fine for tests that
    parse `TriagePropuesta` with no `context` (schema-only checks). Tests
    that drive `run_triage` against the real `db` fixture MUST override
    both with values that actually exist in that session's catalogue (see
    `_valid_payload_for_ticket`) or parsing rejects them as hallucinated."""
    payload = {
        "sector_codigo": "catalogo_sector",
        "tipo_ticket_codigo": "catalogo_tipo",
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


def _valid_payload_for_ticket(ticket, **overrides) -> dict:
    """Same shape as `_valid_payload`, but `sector_codigo`/`tipo_ticket_codigo`
    default to the REAL sector/tipo `_make_ticket` created for this ticket —
    required whenever `run_triage` runs against the real `db` fixture, since
    its catalogue is built live from whatever sectors/tipos exist in that
    session (see `catalogo_sectores_activos`)."""
    return _valid_payload(sector_codigo=ticket.sector.codigo, tipo_ticket_codigo=ticket.tipo_ticket.codigo, **overrides)


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


def _make_ticket(
    db,
    rol: Rol,
    suffix: str,
    texto: str | None = "No puedo facturar desde ayer",
    *,
    descripcion: str | None = None,
    titulo: str = "Ticket para triage",
) -> Ticket:
    _seq[0] += 1
    sector = _make_sector(db, codigo=f"TRIAGE_TEST_{suffix}_{_seq[0]}")
    tipo, estado = _make_tipo_y_estado(db, sector)
    creador = _make_usuario(db, rol, username=f"triage_test_user_{suffix}_{_seq[0]}")

    ticket = Ticket(
        titulo=titulo,
        prioridad=PrioridadTicket.MEDIA,
        sector_id=sector.id,
        tipo_ticket_id=tipo.id,
        estado_id=estado.id,
        creador_id=creador.id,
        campos_metadata={},
        texto_original=texto,
        descripcion=descripcion,
    )
    db.add(ticket)
    db.flush()
    return ticket


class TestTriagePropuestaValidation:
    """4a.1: table-driven Pydantic units, no DB, no network."""

    def test_valid_payload_parses(self) -> None:
        propuesta = TriagePropuesta(**_valid_payload())
        assert propuesta.sector_codigo == "catalogo_sector"
        assert propuesta.tipo_ticket_codigo == "catalogo_tipo"
        assert propuesta.severidad == "mayor"
        assert propuesta.detalle.pasos == ["Ir a Ventas", "Click en Facturar"]

    def test_extra_field_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TriagePropuesta(**_valid_payload(campo_inventado="x"))

    def test_missing_required_field_rejected(self) -> None:
        payload = _valid_payload()
        del payload["sector_codigo"]
        with pytest.raises(ValidationError):
            TriagePropuesta(**payload)

    def test_out_of_range_confianza_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TriagePropuesta(**_valid_payload(confianza_global=1.5))

    def test_unknown_enum_value_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TriagePropuesta(**_valid_payload(severidad="incidencia"))

    def test_hallucinated_sector_codigo_rejected_by_catalogo(self) -> None:
        """§1's extraction contract: 'a hallucinated code is a rejected
        proposal, not a write' — enforced by `TriagePropuesta` itself when a
        catalogue is passed as `context`, not by a later business-rule
        filter."""
        catalogo = {"sistema": {"bug", "feature"}}
        with pytest.raises(ValidationError, match="sector_codigo"):
            TriagePropuesta.model_validate(
                _valid_payload(sector_codigo="sector_que_no_existe", tipo_ticket_codigo="bug"),
                context={"catalogo_sectores": catalogo},
            )

    def test_hallucinated_tipo_ticket_codigo_rejected_by_catalogo(self) -> None:
        """Triangulation: sector_codigo IS in the catalogue, but the tipo
        doesn't belong to it — must still be rejected."""
        catalogo = {"sistema": {"bug", "feature"}}
        with pytest.raises(ValidationError, match="tipo_ticket_codigo"):
            TriagePropuesta.model_validate(
                _valid_payload(sector_codigo="sistema", tipo_ticket_codigo="acceso"),
                context={"catalogo_sectores": catalogo},
            )

    def test_codigos_en_catalogo_son_aceptados(self) -> None:
        """Companion GREEN case: codes that ARE in the catalogue parse."""
        catalogo = {"sistema": {"bug", "feature"}}
        propuesta = TriagePropuesta.model_validate(
            _valid_payload(sector_codigo="sistema", tipo_ticket_codigo="feature"),
            context={"catalogo_sectores": catalogo},
        )
        assert propuesta.sector_codigo == "sistema"
        assert propuesta.tipo_ticket_codigo == "feature"

    def test_empty_catalogo_dict_skips_validation_same_as_none(self) -> None:
        """Real pre-push review finding: an EMPTY dict (no sectors
        configured, or none with any tipo) is falsy but not None. Treating
        only `None` as 'skip validation' would reject sector_codigo — and
        because this schema is all-or-nothing, drag titulo/resumen/
        metadata_ia down with it too, the exact regression commit 3cbb65db
        ('gate the judgements, not the transformations') fixed, entering
        through a different door."""
        propuesta = TriagePropuesta.model_validate(
            _valid_payload(sector_codigo="cualquiera", tipo_ticket_codigo="cualquiera"),
            context={"catalogo_sectores": {}},
        )
        assert propuesta.sector_codigo == "cualquiera"
        assert propuesta.titulo == _valid_payload()["titulo"]

    def test_null_severidad_and_confianza_is_valid(self) -> None:
        """'Return null with low confidence rather than guess' — null must
        be an accepted value, not an error."""
        propuesta = TriagePropuesta(**_valid_payload(severidad=None, confianza_severidad=None))
        assert propuesta.severidad is None
        assert propuesta.confianza_severidad is None


class TestTituloResumenLengthEnforcement:
    """SCOPE: 'server-side length enforcement rejects an over-long model
    response rather than truncating silently or writing it through' — the
    LLM contract caps titulo at 120 chars / resumen at 180 (PR 06)."""

    def test_titulo_over_120_chars_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TriagePropuesta(**_valid_payload(titulo="x" * 121))

    def test_resumen_over_180_chars_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TriagePropuesta(**_valid_payload(resumen="x" * 181))

    def test_titulo_at_exactly_120_chars_is_valid(self) -> None:
        """Triangulation: the boundary itself must NOT be rejected — proves
        the constraint is `max_length=120`, not an off-by-one `<120`."""
        propuesta = TriagePropuesta(**_valid_payload(titulo="x" * 120))
        assert len(propuesta.titulo) == 120


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
        assert propuesta.sector_codigo == "catalogo_sector"

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


class TestCatalogoSectoresActivos:
    """SC: 'the payload includes the configured catalogue and excludes
    INBOX' — `catalogo_sectores_activos` is the extraction contract's
    source of truth for both the LLM user payload and the schema
    validator's context."""

    def test_excludes_inbox_and_includes_active_sectors(self, db) -> None:
        _seed_inbox(db)
        sector = _make_sector(db, codigo="CATALOGO_TEST_SECTOR")
        _make_tipo_y_estado(db, sector)

        catalogo = catalogo_sectores_activos(db)

        codigos = {entry["sector_codigo"] for entry in catalogo}
        assert INBOX_SECTOR_CODIGO not in codigos
        assert "CATALOGO_TEST_SECTOR" in codigos
        entry = next(e for e in catalogo if e["sector_codigo"] == "CATALOGO_TEST_SECTOR")
        assert entry["tipos_ticket"] == ["consulta"]

    def test_inactive_sector_excluded(self, db) -> None:
        """Triangulation: an active sector is included (above), an inactive
        one is dropped — proves the filter runs, not just present-by-luck."""
        sector = _make_sector(db, codigo="CATALOGO_TEST_INACTIVO")
        _make_tipo_y_estado(db, sector)
        sector.activo = False
        db.flush()

        catalogo = catalogo_sectores_activos(db)

        assert "CATALOGO_TEST_INACTIVO" not in {e["sector_codigo"] for e in catalogo}

    def test_user_payload_carries_catalogo_and_excludes_inbox(self, db, rol_ventas) -> None:
        """End-to-end: the JSON `run_triage` sends the model carries
        `catalogo_sectores` and never offers Inbox as a destination."""
        _seed_inbox(db)
        ticket = _make_ticket(db, rol_ventas, "catalogo-payload")
        provider = FakeProvider(response=json.dumps(_valid_payload_for_ticket(ticket)))

        with _patch_background_db(db):
            asyncio.run(run_triage(ticket.id, provider))

        enviado = json.loads(provider.last_user_payload)
        codigos = {entry["sector_codigo"] for entry in enviado["catalogo_sectores"]}
        assert ticket.sector.codigo in codigos
        assert INBOX_SECTOR_CODIGO not in codigos


class TestConfidenceGatePerField:
    """4a.4/4a.6: fake-provider proof that the gate is per-field — a gated
    field writes zero rows while its sibling still writes one."""

    def test_gated_field_writes_nothing_sibling_still_writes(self, db, rol_ventas) -> None:
        ticket = _make_ticket(db, rol_ventas, "gate")
        payload = _valid_payload_for_ticket(ticket, confianza_severidad=0.4, confianza_urgencia=0.85)
        provider = FakeProvider(response=json.dumps(payload))

        with _patch_background_db(db):
            asyncio.run(run_triage(ticket.id, provider))

        propuestas = db.query(PropuestaIA).filter(PropuestaIA.ticket_id == ticket.id).all()
        # `_valid_payload()`'s default confianza_global (0.85) still gates
        # sector/tipo_ticket/titulo/resumen/metadata_ia above threshold,
        # independently of the gated confianza_severidad here — sibling
        # fields must not affect each other (PR 06, decision #1371).
        assert {p.campo for p in propuestas} == {
            "sector",
            "tipo_ticket",
            "urgencia",
            "titulo",
            "resumen",
            "metadata_ia",
        }
        urgencia = next(p for p in propuestas if p.campo == "urgencia")
        assert urgencia.valor_propuesto == {"valor": "alta"}

    def test_null_confianza_treated_as_below_threshold(self, db, rol_ventas) -> None:
        ticket = _make_ticket(db, rol_ventas, "gate-null")
        payload = _valid_payload_for_ticket(ticket, confianza_severidad=None, confianza_urgencia=None)
        provider = FakeProvider(response=json.dumps(payload))

        with _patch_background_db(db):
            asyncio.run(run_triage(ticket.id, provider))

        propuestas = db.query(PropuestaIA).filter(PropuestaIA.ticket_id == ticket.id).all()
        # severidad/urgencia are gated out by their own null confidences;
        # sector/tipo_ticket/titulo/resumen/metadata_ia gate independently
        # on confianza_global (0.85, unaffected by the null siblings) and
        # still write.
        assert {p.campo for p in propuestas} == {"sector", "tipo_ticket", "titulo", "resumen", "metadata_ia"}


class TestTituloResumenNoSeGatean:
    """Supersedes decision #1371, which gated titulo/resumen on
    `confianza_global`. That conflated two different kinds of work:

    - severidad/urgencia are JUDGEMENTS. A confidently wrong "critica"
      sends the maintainer to the wrong ticket and teaches him to distrust
      every badge, so a threshold earns its keep.
    - titulo/resumen are TRANSFORMATIONS. Summarising text is something the
      model can always do; a mediocre title costs nothing, and is still far
      better than the first 80 raw characters the server derives otherwise.

    Real production evidence (ticket #34): for an administrative request
    with no impact information the model correctly returned severidad=null
    and urgencia=null, and rated ITSELF 0.0 across the board because it
    could not classify the request. It had nonetheless written
    "Crear usuarios para GBP y Pricing" and a clean one-line resumen — both
    of which the old gate discarded. The model's doubt about CLASSIFYING
    must not suppress work it already did.
    """

    def test_titulo_y_resumen_se_escriben_con_confianza_cero(self, db, rol_ventas) -> None:
        """The exact production case that exposed this."""
        ticket = _make_ticket(db, rol_ventas, "titulo-sin-gate")
        payload = _valid_payload_for_ticket(
            ticket,
            confianza_global=0.0,
            severidad=None,
            urgencia=None,
            confianza_severidad=0.0,
            confianza_urgencia=0.0,
        )
        provider = FakeProvider(response=json.dumps(payload))

        with _patch_background_db(db):
            asyncio.run(run_triage(ticket.id, provider))

        propuestas = {p.campo: p for p in db.query(PropuestaIA).filter(PropuestaIA.ticket_id == ticket.id).all()}
        assert propuestas["titulo"].valor_propuesto == {"valor": payload["titulo"]}
        assert propuestas["resumen"].valor_propuesto == {"valor": payload["resumen"]}
        # metadata_ia is the same kind of ungated transformation.
        assert propuestas["metadata_ia"].valor_propuesto["valor"]["area_probable"] == payload["area_probable"]
        # ...and the judgements the model declined to make stay unproposed.
        assert "severidad" not in propuestas
        assert "urgencia" not in propuestas
        assert "sector" not in propuestas
        assert "tipo_ticket" not in propuestas

    def test_severidad_y_urgencia_siguen_gateadas(self, db, rol_ventas) -> None:
        """Regression guard: relaxing the text fields must NOT relax the
        judgement fields. A low-confidence severidad/sector/tipo_ticket
        still write nothing — extends decision #1371 to the new campos this
        change adds (sector/tipo_ticket are judgements too, see
        `run_triage`'s write-loop comment)."""
        ticket = _make_ticket(db, rol_ventas, "juicios-gateados")
        payload = _valid_payload_for_ticket(
            ticket, confianza_severidad=0.2, confianza_urgencia=0.2, confianza_global=0.0
        )
        provider = FakeProvider(response=json.dumps(payload))

        with _patch_background_db(db):
            asyncio.run(run_triage(ticket.id, provider))

        campos = {p.campo for p in db.query(PropuestaIA).filter(PropuestaIA.ticket_id == ticket.id).all()}
        assert campos == {"titulo", "resumen", "metadata_ia"}
        assert "sector" not in campos
        assert "tipo_ticket" not in campos

    def test_confianza_alta_escribe_todo(self, db, rol_ventas, monkeypatch) -> None:
        """Isolates GATING (which fields become proposals) from auto-apply
        ROUTING (feat/tickets-triage-aplicar-directo) — the topology flip
        has its own dedicated test class below; this one keeps testing the
        original `estado='pendiente'` shape it was written for."""
        monkeypatch.setattr(settings, "TICKETS_TRIAGE_AUTO_APPLY", False)
        ticket = _make_ticket(db, rol_ventas, "titulo-gate-high")
        payload = _valid_payload_for_ticket(ticket, confianza_global=0.9)
        provider = FakeProvider(response=json.dumps(payload))

        with _patch_background_db(db):
            asyncio.run(run_triage(ticket.id, provider))

        propuestas = {p.campo: p for p in db.query(PropuestaIA).filter(PropuestaIA.ticket_id == ticket.id).all()}
        assert propuestas["titulo"].valor_propuesto == {"valor": payload["titulo"]}
        assert propuestas["titulo"].estado == "pendiente"
        assert propuestas["resumen"].valor_propuesto == {"valor": payload["resumen"]}
        assert propuestas["resumen"].estado == "pendiente"
        assert propuestas["sector"].valor_propuesto == {"valor": payload["sector_codigo"]}
        assert propuestas["tipo_ticket"].valor_propuesto == {"valor": payload["tipo_ticket_codigo"]}

    def test_run_triage_degrades_to_nothing_when_titulo_too_long(self, db, rol_ventas) -> None:
        """The over-long titulo fails `TriagePropuesta` parsing entirely
        (closed schema, all-or-nothing) — the proposal is rejected outright,
        never truncated and never written through."""
        ticket = _make_ticket(db, rol_ventas, "titulo-too-long")
        payload = _valid_payload_for_ticket(ticket, titulo="x" * 121)
        provider = FakeProvider(response=json.dumps(payload))

        with _patch_background_db(db):
            asyncio.run(run_triage(ticket.id, provider))

        assert db.query(PropuestaIA).filter(PropuestaIA.ticket_id == ticket.id).count() == 0


class TestRunTriageDirectCall:
    """4a.6: `run_triage` called directly with a fake provider writes
    proposal rows, exactly one in-process call, zero network."""

    def test_writes_pending_rows_with_zero_network(self, db, rol_ventas, monkeypatch) -> None:
        """Isolates the write LOOP (one proposal row per surviving field)
        from auto-apply ROUTING — see `test_confianza_alta_escribe_todo`'s
        docstring above for why the flag is pinned False here."""
        monkeypatch.setattr(settings, "TICKETS_TRIAGE_AUTO_APPLY", False)
        ticket = _make_ticket(db, rol_ventas, "direct")
        provider = FakeProvider(response=json.dumps(_valid_payload_for_ticket(ticket)))

        with _patch_background_db(db):
            asyncio.run(run_triage(ticket.id, provider))

        assert provider.calls == 1
        propuestas = db.query(PropuestaIA).filter(PropuestaIA.ticket_id == ticket.id).all()
        assert {p.campo for p in propuestas} == {
            "sector",
            "tipo_ticket",
            "severidad",
            "urgencia",
            "titulo",
            "resumen",
            "metadata_ia",
        }
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

        provider = FakeProvider(response=json.dumps(_valid_payload_for_ticket(ticket)))
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

        provider = FakeProvider(response=json.dumps(_valid_payload_for_ticket(ticket)))

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


class TestFallbackToDescripcionForLegacyTickets:
    """fix/tickets-board-scope-y-legacy — 33/35 production tickets predate
    single-box intake: `texto_original IS NULL` but they carry a
    human-written `titulo` + `descripcion` from the old two-field form.
    `run_triage` must fall back to `descripcion` as the text SOURCE, but
    must NEVER propose an AI `titulo` for these — that title is a
    person's own words, not a machine-derived fragment (obs #1400: a
    field's MEANING changing breaks every consumer that trusted the old
    one, silently)."""

    def test_falls_back_to_descripcion_when_texto_original_is_null(self, db, rol_ventas) -> None:
        ticket = _make_ticket(db, rol_ventas, "legacy", texto=None, descripcion="Reclamo legado sin texto_original")
        provider = FakeProvider(response=json.dumps(_valid_payload_for_ticket(ticket)))

        with _patch_background_db(db):
            asyncio.run(run_triage(ticket.id, provider))

        assert provider.calls == 1
        assert json.loads(provider.last_user_payload)["texto"] == "Reclamo legado sin texto_original"

    def test_no_titulo_proposal_written_for_legacy_ticket_but_resumen_severidad_urgencia_still_are(
        self, db, rol_ventas
    ) -> None:
        ticket = _make_ticket(db, rol_ventas, "legacy2", texto=None, descripcion="Otro reclamo legado")
        provider = FakeProvider(response=json.dumps(_valid_payload_for_ticket(ticket)))

        with _patch_background_db(db):
            asyncio.run(run_triage(ticket.id, provider))

        campos = {p.campo for p in db.query(PropuestaIA).filter(PropuestaIA.ticket_id == ticket.id).all()}
        assert "titulo" not in campos
        assert "resumen" in campos
        assert "severidad" in campos
        assert "urgencia" in campos

    def test_ticket_with_texto_original_still_gets_titulo_proposal(self, db, rol_ventas) -> None:
        ticket = _make_ticket(db, rol_ventas, "modern")  # default texto_original set
        provider = FakeProvider(response=json.dumps(_valid_payload_for_ticket(ticket)))

        with _patch_background_db(db):
            asyncio.run(run_triage(ticket.id, provider))

        campos = {p.campo for p in db.query(PropuestaIA).filter(PropuestaIA.ticket_id == ticket.id).all()}
        assert "titulo" in campos

    def test_ticket_with_neither_texto_original_nor_descripcion_is_skipped_cleanly(self, db, rol_ventas) -> None:
        ticket = _make_ticket(db, rol_ventas, "empty", texto=None, descripcion=None)
        provider = FakeProvider()

        with _patch_background_db(db):
            asyncio.run(run_triage(ticket.id, provider))

        assert provider.calls == 0
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

        provider = FakeProvider(response=json.dumps(_valid_payload_for_ticket(ticket)))

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


class TestYaTienePropuestaActivaIncludesCorregida:
    """Design's `estado` consumer audit, item 1 of 3 (the CRITICAL one):
    without `corregida` in this guard's `estado.in_(...)` tuple, a
    re-triage after a correction would re-surface a field the human
    already decided — breaking spec #1304's "human rejection never
    re-surfaces" invariant, extended to `corregida`, with NO visible
    change at this call site (the exact #1400 failure shape)."""

    def test_returns_true_for_corregida(self, db, rol_ventas) -> None:
        ticket = _make_ticket(db, rol_ventas, "corregida_guard")
        db.add(
            PropuestaIA(
                ticket_id=ticket.id,
                campo="severidad",
                valor_propuesto={"valor": "mayor"},
                valor_corregido="menor",
                estado="corregida",
            )
        )
        db.flush()

        assert _ya_tiene_propuesta_activa(db, ticket.id, "severidad") is True

    def test_re_triage_after_correction_writes_no_new_proposal_for_that_campo(self, db, rol_ventas) -> None:
        """End-to-end regression, the #1400 shape through `run_triage`
        itself: a corrected field must never re-surface as a fresh
        `pendiente` proposal on the next triage run."""
        ticket = _make_ticket(db, rol_ventas, "corregida_retriage")
        db.add(
            PropuestaIA(
                ticket_id=ticket.id,
                campo="severidad",
                valor_propuesto={"valor": "mayor"},
                valor_corregido="menor",
                estado="corregida",
            )
        )
        db.flush()

        provider = FakeProvider(response=json.dumps(_valid_payload_for_ticket(ticket)))
        with _patch_background_db(db):
            asyncio.run(run_triage(ticket.id, provider))

        severidad_rows = (
            db.query(PropuestaIA).filter(PropuestaIA.ticket_id == ticket.id, PropuestaIA.campo == "severidad").all()
        )
        assert len(severidad_rows) == 1  # only the original corregida row — no new pendiente sibling
        assert severidad_rows[0].estado == "corregida"


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


class TestAutoApplyTopology:
    """feat/tickets-triage-aplicar-directo: the confirm-first topology PR 4b
    shipped never scaled past a handful of tickets (164 pending proposals
    across 35 tickets in production). `TICKETS_TRIAGE_AUTO_APPLY` (default
    True) flips it: a threshold-passing field writes straight onto the
    ticket instead of sitting `pendiente`. The proposal row is STILL
    created — the audit trail — but born `estado='confirmada'` with
    `confirmado_por_id=NULL`; that NULL is the signal nobody has reviewed
    it. The flag is a real kill switch: `False` restores PR 4b's original
    behavior exactly, without a deploy."""

    def test_threshold_passing_field_writes_ticket_value_and_confirmada_ia_auto_row(self, db, rol_ventas) -> None:
        ticket = _make_ticket(db, rol_ventas, "auto-apply")
        payload = _valid_payload_for_ticket(ticket, confianza_severidad=0.9)
        provider = FakeProvider(response=json.dumps(payload))

        with _patch_background_db(db):
            asyncio.run(run_triage(ticket.id, provider))

        db.refresh(ticket)
        assert ticket.severidad == payload["severidad"]
        assert ticket.severidad_origen == "ia_auto"

        propuesta = (
            db.query(PropuestaIA).filter(PropuestaIA.ticket_id == ticket.id, PropuestaIA.campo == "severidad").first()
        )
        assert propuesta is not None
        assert propuesta.estado == "confirmada"
        assert propuesta.confirmado_por_id is None
        assert propuesta.confirmado_at is not None

    def test_gated_field_applies_nothing_column_stays_null(self, db, rol_ventas) -> None:
        """A field that fails the confidence gate never even becomes a
        proposal row (unchanged from PR 4b) — auto-apply has nothing to
        apply, so the ticket column stays untouched."""
        ticket = _make_ticket(db, rol_ventas, "auto-apply-gated")
        payload = _valid_payload_for_ticket(ticket, confianza_severidad=0.3)
        provider = FakeProvider(response=json.dumps(payload))

        with _patch_background_db(db):
            asyncio.run(run_triage(ticket.id, provider))

        db.refresh(ticket)
        assert ticket.severidad is None
        assert ticket.severidad_origen is None
        assert (
            db.query(PropuestaIA).filter(PropuestaIA.ticket_id == ticket.id, PropuestaIA.campo == "severidad").first()
            is None
        )

    def test_auto_apply_false_restores_old_behavior_exactly(self, db, rol_ventas, monkeypatch) -> None:
        """The kill switch: value stays NULL, proposal stays `pendiente`,
        `confirmado_por_id`/`confirmado_at` stay unset — exactly PR 4b's
        original shape, without a deploy."""
        monkeypatch.setattr(settings, "TICKETS_TRIAGE_AUTO_APPLY", False)
        ticket = _make_ticket(db, rol_ventas, "auto-apply-off")
        payload = _valid_payload_for_ticket(ticket, confianza_severidad=0.9)
        provider = FakeProvider(response=json.dumps(payload))

        with _patch_background_db(db):
            asyncio.run(run_triage(ticket.id, provider))

        db.refresh(ticket)
        assert ticket.severidad is None
        assert ticket.severidad_origen is None

        propuesta = (
            db.query(PropuestaIA).filter(PropuestaIA.ticket_id == ticket.id, PropuestaIA.campo == "severidad").first()
        )
        assert propuesta is not None
        assert propuesta.estado == "pendiente"
        assert propuesta.confirmado_por_id is None
        assert propuesta.confirmado_at is None

    def test_sector_and_tipo_ticket_auto_apply_together_moves_estado(self, db, rol_ventas) -> None:
        """Sector is a DOMAIN OPERATION (obs #1409), not a column write —
        auto-apply must go through the SAME `_aplicar_confirmacion` dispatch
        a human confirm uses, moving `estado_id` to the destination
        workflow's initial state in the same transaction."""
        ticket = _make_ticket(db, rol_ventas, "auto-apply-sector")
        estado_origen_id = ticket.estado_id
        destino = _make_sector(db, codigo=f"AUTO_APPLY_DESTINO_{ticket.id}")
        tipo_destino, estado_inicial_destino = _make_tipo_y_estado(db, destino)
        db.flush()

        payload = _valid_payload(sector_codigo=destino.codigo, tipo_ticket_codigo=tipo_destino.codigo)
        provider = FakeProvider(response=json.dumps(payload))

        with _patch_background_db(db):
            asyncio.run(run_triage(ticket.id, provider))

        db.refresh(ticket)
        assert ticket.sector_id == destino.id
        assert ticket.tipo_ticket_id == tipo_destino.id
        assert ticket.estado_id == estado_inicial_destino.id
        assert ticket.estado_id != estado_origen_id

        sector_prop = (
            db.query(PropuestaIA).filter(PropuestaIA.ticket_id == ticket.id, PropuestaIA.campo == "sector").first()
        )
        tipo_prop = (
            db.query(PropuestaIA).filter(PropuestaIA.ticket_id == ticket.id, PropuestaIA.campo == "tipo_ticket").first()
        )
        assert sector_prop.estado == "confirmada"
        assert sector_prop.confirmado_por_id is None
        assert tipo_prop.estado == "confirmada"
        assert tipo_prop.confirmado_por_id is None

    def test_sector_auto_apply_domain_error_falls_back_to_pendiente_for_that_field_only(self, db, rol_ventas) -> None:
        """Confirming `sector` ALONE (no `tipo_ticket` applying alongside it
        in the SAME run) would orphan the ticket's CURRENT `tipo_ticket_id`
        — still pointing at its ORIGIN sector — the exact
        `PropuestaSectorDejaTipoHuerfanoError` shape `confirmar_batch` also
        guards against for humans. Forces "tipo_ticket NOT applying
        alongside" via a pre-existing active proposal for that field (an
        earlier triage run's un-reviewed tipo_ticket classification), which
        is what `_ya_tiene_propuesta_activa` — and therefore this test's own
        `tipo_se_aplicara_junto` precheck — actually blocks on in
        production, not merely a confidence gate (sector/tipo_ticket share
        `confianza_global`, so gating one always gates the other too).
        Sector must degrade to a `pendiente` proposal for THAT field, never
        crash the whole run nor silently drop the classification."""
        ticket = _make_ticket(db, rol_ventas, "auto-apply-sector-fail")
        destino = _make_sector(db, codigo=f"AUTO_APPLY_FAIL_{ticket.id}")
        tipo_destino, _estado_destino = _make_tipo_y_estado(db, destino)
        db.add(
            PropuestaIA(
                ticket_id=ticket.id,
                campo="tipo_ticket",
                valor_propuesto={"valor": "algun_tipo_previo"},
                estado="pendiente",
            )
        )
        db.flush()

        payload = _valid_payload(sector_codigo=destino.codigo, tipo_ticket_codigo=tipo_destino.codigo)
        provider = FakeProvider(response=json.dumps(payload))

        with _patch_background_db(db):
            asyncio.run(run_triage(ticket.id, provider))

        db.refresh(ticket)
        # Sector write failed domain validation — ticket never moved.
        assert ticket.sector_id != destino.id
        assert ticket.tipo_ticket_id != tipo_destino.id

        sector_prop = (
            db.query(PropuestaIA).filter(PropuestaIA.ticket_id == ticket.id, PropuestaIA.campo == "sector").first()
        )
        assert sector_prop is not None
        assert sector_prop.estado == "pendiente"  # degraded, not lost
        assert sector_prop.valor_propuesto == {"valor": destino.codigo}

        # `_ya_tiene_propuesta_activa` blocked a NEW tipo_ticket proposal
        # this run — only the pre-existing one exists, untouched.
        tipo_props = (
            db.query(PropuestaIA).filter(PropuestaIA.ticket_id == ticket.id, PropuestaIA.campo == "tipo_ticket").all()
        )
        assert len(tipo_props) == 1
        assert tipo_props[0].valor_propuesto == {"valor": "algun_tipo_previo"}

    def test_auto_apply_never_overwrites_a_humano_origen_value(self, db, rol_ventas) -> None:
        """Real pre-push review finding: a human can set this field through
        an entirely DIFFERENT path (`actualizar_ticket`'s PATCH, e.g. the
        board's urgency-column drag) that never touches
        `tickets_propuestas_ia` — so `_ya_tiene_propuesta_activa` cannot see
        it and would otherwise let a later triage run clobber it. 'Nunca
        pisar lo que puso una persona' — the same invariant the data
        migration's own `WHERE tickets.{campo} IS NULL` guard enforces,
        checked here against `_origen` because `run_triage` (unlike the
        migration's one-time backfill) can be RE-TRIGGERED after a human
        has already classified the field by hand."""
        ticket = _make_ticket(db, rol_ventas, "auto-apply-humano-guard")
        ticket.urgencia = "inmediata"
        ticket.urgencia_origen = "humano"
        db.commit()
        payload = _valid_payload_for_ticket(ticket, urgencia="baja", confianza_urgencia=0.95)
        provider = FakeProvider(response=json.dumps(payload))

        with _patch_background_db(db):
            asyncio.run(run_triage(ticket.id, provider))

        db.refresh(ticket)
        assert ticket.urgencia == "inmediata"  # untouched
        assert ticket.urgencia_origen == "humano"  # untouched

        propuesta = (
            db.query(PropuestaIA).filter(PropuestaIA.ticket_id == ticket.id, PropuestaIA.campo == "urgencia").first()
        )
        assert propuesta is not None  # not lost — a human can still review the AI's disagreement
        assert propuesta.estado == "pendiente"
        assert propuesta.valor_propuesto == {"valor": "baja"}

    def test_sector_and_tipo_ticket_apply_atomically_neither_or_both(self, db, rol_ventas, monkeypatch) -> None:
        """Real pre-push review finding: `sector` succeeding while
        `tipo_ticket` then fails its OWN domain check must NOT leave the
        ticket with a NEW sector and its OLD `tipo_ticket_id` — the exact
        orphaned pair `PropuestaSectorDejaTipoHuerfanoError` exists to
        prevent, reached through a different door when the two writes
        aren't atomic WITH EACH OTHER. Forces `tipo_ticket`'s OWN domain
        validation to fail (independent of sector's) to prove the
        SAVEPOINT rolls back sector's mutation too, not just tipo_ticket's."""
        ticket = _make_ticket(db, rol_ventas, "auto-apply-pair-atomic")
        sector_origen_id = ticket.sector_id
        destino = _make_sector(db, codigo=f"AUTO_APPLY_ATOMIC_{ticket.id}")
        tipo_destino, _estado_destino = _make_tipo_y_estado(db, destino)
        db.flush()

        payload = _valid_payload(sector_codigo=destino.codigo, tipo_ticket_codigo=tipo_destino.codigo)
        provider = FakeProvider(response=json.dumps(payload))

        import app.tickets.services.confirmacion_service as confirmacion_service_module

        def _falla_siempre(*args, **kwargs):
            raise confirmacion_service_module.PropuestaTipoSectorInvalidoError(tipo_destino.codigo, destino.id)

        monkeypatch.setattr(confirmacion_service_module, "_confirmar_tipo_ticket", _falla_siempre)

        with _patch_background_db(db):
            asyncio.run(run_triage(ticket.id, provider))

        db.refresh(ticket)
        # `_confirmar_sector` itself would have succeeded — the SAVEPOINT
        # around the pair must have rolled it back anyway.
        assert ticket.sector_id == sector_origen_id
        assert ticket.sector_id != destino.id

        sector_prop = (
            db.query(PropuestaIA).filter(PropuestaIA.ticket_id == ticket.id, PropuestaIA.campo == "sector").first()
        )
        tipo_prop = (
            db.query(PropuestaIA).filter(PropuestaIA.ticket_id == ticket.id, PropuestaIA.campo == "tipo_ticket").first()
        )
        assert sector_prop.estado == "pendiente"  # degraded TOGETHER with tipo_ticket, not applied alone
        assert tipo_prop.estado == "pendiente"
