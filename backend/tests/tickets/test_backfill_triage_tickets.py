"""Tests for scripts/backfill_triage_tickets.py (fix/tickets-triage-backfill).

Covers: the candidate query selects only tickets with `texto_original` and
ZERO `PropuestaIA` rows; dry-run makes zero provider calls; an unset
`GROQ_TICKETS_KEY` exits non-zero without walking the table; a per-ticket
failure does not abort the run; and — per obs #1323/#1350's lesson that a
test running inside the app's already-populated mapper registry cannot
prove standalone execution works — a subprocess test in a fresh
interpreter, mirroring `test_audit_transiciones.py`.

Written FIRST (RED phase) per strict TDD.

Run:
    cd backend && source venv/bin/activate
    pytest tests/tickets/test_backfill_triage_tickets.py -v
"""

import logging
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from app.core.database import Base
from app.core.security import get_password_hash
from app.models.rol import Rol
from app.models.usuario import AuthProvider, RolUsuario, Usuario
from app.tickets.models.propuesta_ia import PropuestaIA
from app.tickets.models.sector import Sector
from app.tickets.models.ticket import PrioridadTicket, Ticket
from app.tickets.models.tipo_ticket import TipoTicket
from app.tickets.models.workflow import EstadoTicket, Workflow
from scripts import backfill_triage_tickets as script

BACKEND_DIR = Path(__file__).resolve().parents[2]

_seq = [0]


class FakeProvider:
    """Duck-typed `LlmProvider` — never touches the network. `calls` counts
    `complete()` invocations so tests can assert zero network calls."""

    def __init__(self, configured=True):
        self._configured = configured
        self.calls = 0

    def is_configured(self) -> bool:
        return self._configured

    async def complete(self, system_prompt: str, user_payload: str) -> str:
        self.calls += 1
        return "{}"


class _NonClosingSessionWrapper:
    """Delegates to the test's own transactional `db` fixture session but
    no-ops `close()` — the script calls `.close()` on its own session, and
    closing the SHARED fixture session mid-test would break the test."""

    def __init__(self, db):
        self._db = db

    def __getattr__(self, name):
        return getattr(self._db, name)

    def close(self) -> None:
        pass


def _patch_session_local(monkeypatch, db) -> None:
    monkeypatch.setattr(script, "SessionLocal", lambda: _NonClosingSessionWrapper(db))


def _make_sector(db) -> Sector:
    _seq[0] += 1
    s = Sector(codigo=f"BACKFILL_SECT_{_seq[0]}", nombre="Sector Backfill Test", activo=True, configuracion={})
    db.add(s)
    db.flush()
    return s


def _make_tipo_y_estado(db, sector: Sector):
    wf = Workflow(sector_id=sector.id, nombre="WF Backfill Test", es_default=True, activo=True)
    db.add(wf)
    db.flush()
    estado = EstadoTicket(workflow_id=wf.id, codigo="abierto", nombre="Abierto", orden=1, es_inicial=True)
    db.add(estado)
    db.flush()
    tipo = TipoTicket(sector_id=sector.id, codigo="consulta", nombre="Consulta", workflow_id=wf.id)
    db.add(tipo)
    db.flush()
    return tipo, estado


def _make_usuario(db, rol: Rol) -> Usuario:
    _seq[0] += 1
    u = Usuario(
        username=f"backfill_user_{_seq[0]}",
        email=f"backfill_{_seq[0]}@test.com",
        nombre=f"Backfill User {_seq[0]}",
        password_hash=get_password_hash("pass"),
        rol=RolUsuario.VENTAS,
        rol_id=rol.id,
        auth_provider=AuthProvider.LOCAL,
        activo=True,
    )
    db.add(u)
    db.flush()
    return u


def _make_ticket(db, rol: Rol, *, texto_original=None, descripcion=None) -> Ticket:
    _seq[0] += 1
    sector = _make_sector(db)
    tipo, estado = _make_tipo_y_estado(db, sector)
    creador = _make_usuario(db, rol)
    t = Ticket(
        titulo="Ticket backfill test",
        prioridad=PrioridadTicket.MEDIA,
        sector_id=sector.id,
        tipo_ticket_id=tipo.id,
        estado_id=estado.id,
        creador_id=creador.id,
        campos_metadata={},
        texto_original=texto_original,
        descripcion=descripcion,
    )
    db.add(t)
    db.flush()
    return t


def _make_propuesta(db, ticket: Ticket, *, campo="titulo", estado="pendiente") -> PropuestaIA:
    p = PropuestaIA(
        ticket_id=ticket.id,
        campo=campo,
        valor_propuesto={"valor": "Ya clasificado"},
        confianza=0.9,
        estado=estado,
    )
    db.add(p)
    db.flush()
    return p


def _make_todas_las_propuestas(db, ticket: Ticket) -> None:
    """Fully classified — an active proposal for every field
    `script.CAMPOS_PROPUESTA_BASE` covers, plus `titulo` when the ticket's
    `texto_original` allows it (see `script.CAMPOS_PROPUESTA_BASE` /
    `_debe_proponer_titulo`'s production counterpart)."""
    campos = list(script.CAMPOS_PROPUESTA_BASE)
    if ticket.texto_original is not None:
        campos.append("titulo")
    for campo in campos:
        _make_propuesta(db, ticket, campo=campo)


class TestFindCandidateTickets:
    def test_ticket_without_proposals_is_selected_fully_classified_ticket_is_excluded(self, db, rol_ventas):
        """Both halves of the filter, in one test: a candidate ticket (has
        texto_original, zero proposals) IS returned; a ticket that already
        has an active proposal for EVERY applicable field is NOT — proving
        the query actually filters instead of returning everything."""
        candidato = _make_ticket(db, rol_ventas, texto_original="Un reclamo que nadie clasificó")
        ya_procesado = _make_ticket(db, rol_ventas, texto_original="Este ya está completo")
        _make_todas_las_propuestas(db, ya_procesado)

        resultado_ids = {t.id for t in script.find_candidate_tickets(db)}

        assert candidato.id in resultado_ids
        assert ya_procesado.id not in resultado_ids

    def test_ticket_missing_only_some_fields_is_picked_up(self, db, rol_ventas):
        """The core gap this fix closes: ticket #34 in production had
        `titulo`/`resumen` already proposed but not `sector`/`tipo_ticket`
        — the OLD zero-proposals query could never select it again."""
        parcial = _make_ticket(db, rol_ventas, texto_original="Ticket con algunas propuestas")
        _make_propuesta(db, parcial, campo="titulo")
        _make_propuesta(db, parcial, campo="resumen")

        resultado_ids = {t.id for t in script.find_candidate_tickets(db)}

        assert parcial.id in resultado_ids

    def test_ticket_with_neither_texto_original_nor_descripcion_is_excluded(self, db, rol_ventas):
        sin_texto = _make_ticket(db, rol_ventas, texto_original=None, descripcion=None)

        resultado_ids = {t.id for t in script.find_candidate_tickets(db)}

        assert sin_texto.id not in resultado_ids

    def test_ticket_with_only_descripcion_is_a_candidate(self, db, rol_ventas):
        """The 33/35 legacy tickets: `texto_original IS NULL` but they
        carry a human-written `descripcion` from the old two-field form."""
        legado = _make_ticket(db, rol_ventas, texto_original=None, descripcion="Reclamo del formulario viejo")

        resultado_ids = {t.id for t in script.find_candidate_tickets(db)}

        assert legado.id in resultado_ids

    def test_limit_caps_the_number_returned(self, db, rol_ventas):
        _make_ticket(db, rol_ventas, texto_original="Uno")
        _make_ticket(db, rol_ventas, texto_original="Dos")

        resultado = script.find_candidate_tickets(db, limit=1)

        assert len(resultado) == 1


class TestEstadosPropuestaActivaIncludesCorregida:
    """Design's `estado` consumer audit, item 3 of 3: this script's own
    docstring requires `_ESTADOS_PROPUESTA_ACTIVA` to stay in parity with
    `triage_service._ya_tiene_propuesta_activa` — without `corregida` here,
    a ticket whose only gap is a HUMAN-corrected field would be
    re-selected as a backfill candidate, wasting a Groq call to propose
    something a human already decided."""

    def test_constant_includes_corregida(self) -> None:
        assert "corregida" in script._ESTADOS_PROPUESTA_ACTIVA

    def test_ticket_with_only_corregida_proposals_is_not_a_candidate(self, db, rol_ventas):
        ticket = _make_ticket(db, rol_ventas, texto_original="Ya todo corregido a mano")
        campos = list(script.CAMPOS_PROPUESTA_BASE) + ["titulo"]
        for campo in campos:
            p = PropuestaIA(
                ticket_id=ticket.id,
                campo=campo,
                valor_propuesto={"valor": "x"},
                estado="corregida",
            )
            db.add(p)
        db.flush()

        resultado_ids = {t.id for t in script.find_candidate_tickets(db)}

        assert ticket.id not in resultado_ids


class TestDryRunMakesNoProviderCalls:
    def test_dry_run_never_builds_the_provider(self, db, rol_ventas, monkeypatch, capsys):
        ticket = _make_ticket(db, rol_ventas, texto_original="Reclamo sin clasificar")
        _patch_session_local(monkeypatch, db)

        def _fail_if_called():
            raise AssertionError("dry-run must not build/call the LLM provider")

        monkeypatch.setattr(script, "get_triage_provider", _fail_if_called)

        exit_code = script.main([])

        assert exit_code == 0
        out = capsys.readouterr().out
        assert f"#{ticket.id}" in out
        assert "Dry-run" in out


class TestApplyAndDryRunAreMutuallyExclusive:
    """Real pre-push review finding: `dry_run = not args.apply` silently let
    `--dry-run --apply` together run for REAL (the last-wins semantics of a
    plain boolean), while the operator believed `--dry-run` made it safe.
    For a script that burns API quota and writes to the DB, that must be a
    loud argparse error at parse time, not a footgun."""

    def test_passing_both_flags_together_is_a_hard_error(self):
        with pytest.raises(SystemExit) as exc_info:
            script._parse_args(["--dry-run", "--apply"])

        assert exc_info.value.code == 2


class TestUnsetKeyFailsLoud:
    def test_apply_without_key_exits_nonzero_and_never_walks_the_table(self, monkeypatch, capsys):
        provider = FakeProvider(configured=False)
        monkeypatch.setattr(script, "get_triage_provider", lambda: provider)

        called = {"find": False}

        def _spy_find(*args, **kwargs):
            called["find"] = True
            return []

        monkeypatch.setattr(script, "find_candidate_tickets", _spy_find)

        exit_code = script.main(["--apply"])

        assert exit_code == 1
        assert called["find"] is False
        assert "GROQ_TICKETS_KEY" in capsys.readouterr().err


class TestPerTicketFailureDoesNotAbort:
    def test_one_ticket_raising_does_not_stop_the_rest(self, db, rol_ventas, monkeypatch):
        boom_ticket = _make_ticket(db, rol_ventas, texto_original="Este va a fallar")
        ok_ticket = _make_ticket(db, rol_ventas, texto_original="Este va a andar bien")
        _patch_session_local(monkeypatch, db)
        monkeypatch.setattr(script, "_SLEEP_BETWEEN_CALLS_SECONDS", 0)

        async def _fake_run_triage(ticket_id, provider):
            if ticket_id == boom_ticket.id:
                raise RuntimeError("simulated failure")

        monkeypatch.setattr(script, "run_triage", _fake_run_triage)

        resumen = _run_async(script._procesar([boom_ticket, ok_ticket], FakeProvider()))

        assert resumen["fallidos"] == 1
        assert resumen["procesados"] == 1


class TestOutcomeBucketsDistinguishFailureModes:
    def test_write_phase_failure_counts_as_fallo_not_confianza_gateada(self, monkeypatch):
        """Real pre-push review finding: the detector originally matched
        ONLY the "failed for ticket" message, missing `run_triage`'s
        SECOND failure warning ("failed to write proposals for ticket
        #%s", the unique-index race backstop) — that write-phase failure
        fell into `sin_propuestas_por_confianza`, exactly the
        misattribution this bucket split exists to prevent."""
        triage_logger = logging.getLogger(script._TRIAGE_LOGGER_NAME)

        async def _fake_run_triage(ticket_id, provider):
            triage_logger.warning("tickets triage: failed to write proposals for ticket #%s", ticket_id)

        monkeypatch.setattr(script, "run_triage", _fake_run_triage)
        monkeypatch.setattr(script, "_contar_propuestas", lambda db, ticket_id: 0)
        monkeypatch.setattr(script, "_SLEEP_BETWEEN_CALLS_SECONDS", 0)

        ticket = type("Ticket", (), {"id": 1})()
        resumen = _run_async(script._procesar([ticket], FakeProvider()))

        assert resumen["fallo_llm_o_parseo"] == 1
        assert resumen["sin_propuestas_por_confianza"] == 0


def _run_async(coro):
    """No pytest-asyncio in this project — async code is driven with
    `asyncio.run(...)` directly (see `tests/tickets/test_triage_service.py`)."""
    import asyncio

    return asyncio.run(coro)


class TestStandaloneScriptExecution:
    """Guards that the script actually runs as a STANDALONE script — see
    `test_audit_transiciones.py::TestStandaloneScriptExecution` for the full
    rationale (obs #1323/#1350): a test running inside `conftest.py`'s
    already-populated mapper registry cannot reproduce the standalone
    failure mode. This launches a brand-new subprocess instead.
    """

    def test_runs_standalone_in_fresh_interpreter(self, tmp_path, engine):
        # `engine` (conftest.py) is requested purely for its side effect —
        # same as test_audit_transiciones.py's equivalent test: it patches
        # Postgres-only column types (JSONB, UUID on PropuestaIA/Ticket)
        # to SQLite equivalents in-place on `Base.metadata` before we call
        # `create_all` on our own tmp-file engine below. Without it, running
        # only this test in isolation (before any other fixture triggers
        # that patch) can fail to build the schema correctly.
        db_path = tmp_path / "backfill_standalone.db"
        db_url = f"sqlite:///{db_path}"
        tmp_engine = create_engine(db_url)
        Base.metadata.create_all(bind=tmp_engine)
        tmp_engine.dispose()

        # Explicit env — never `{**os.environ, ...}` (see
        # test_audit_transiciones.py for why). GROQ_TICKETS_KEY is
        # deliberately OMITTED: --dry-run must work without it.
        env = {
            "ENVIRONMENT": "testing",
            "DATABASE_URL": db_url,
            "SECRET_KEY": "ci-test-secret-key-minimum-32-bytes!",
            "ERP_BASE_URL": "http://localhost:9999",
        }

        result = subprocess.run(
            [sys.executable, "-m", "scripts.backfill_triage_tickets", "--dry-run"],
            cwd=BACKEND_DIR,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert result.returncode == 0, f"stdout:\n{result.stdout}\n\nstderr:\n{result.stderr}"
        assert "Tickets candidatos para backfill de triage IA" in result.stdout

    def test_apply_without_key_fails_loud_standalone(self, tmp_path):
        db_path = tmp_path / "backfill_standalone_noapply.db"
        db_url = f"sqlite:///{db_path}"
        tmp_engine = create_engine(db_url)
        Base.metadata.create_all(bind=tmp_engine)
        tmp_engine.dispose()

        env = {
            "ENVIRONMENT": "testing",
            "DATABASE_URL": db_url,
            "SECRET_KEY": "ci-test-secret-key-minimum-32-bytes!",
            "ERP_BASE_URL": "http://localhost:9999",
        }

        result = subprocess.run(
            [sys.executable, "-m", "scripts.backfill_triage_tickets", "--apply"],
            cwd=BACKEND_DIR,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert result.returncode == 1
        assert "GROQ_TICKETS_KEY" in result.stderr
