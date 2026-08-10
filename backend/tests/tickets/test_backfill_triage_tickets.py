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


def _make_ticket(db, rol: Rol, *, texto_original) -> Ticket:
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
    )
    db.add(t)
    db.flush()
    return t


def _make_propuesta(db, ticket: Ticket) -> PropuestaIA:
    p = PropuestaIA(
        ticket_id=ticket.id,
        campo="titulo",
        valor_propuesto={"valor": "Ya clasificado"},
        confianza=0.9,
        estado="pendiente",
    )
    db.add(p)
    db.flush()
    return p


class TestFindCandidateTickets:
    def test_ticket_without_proposals_is_selected_ticket_with_proposals_is_excluded(self, db, rol_ventas):
        """Both halves of the filter, in one test: a candidate ticket (has
        texto_original, zero proposals) IS returned; a ticket that already
        has a proposal is NOT — proving the query actually filters instead
        of returning everything."""
        candidato = _make_ticket(db, rol_ventas, texto_original="Un reclamo que nadie clasificó")
        ya_procesado = _make_ticket(db, rol_ventas, texto_original="Este ya tiene propuesta")
        _make_propuesta(db, ya_procesado)

        resultado_ids = {t.id for t in script.find_candidate_tickets(db)}

        assert candidato.id in resultado_ids
        assert ya_procesado.id not in resultado_ids

    def test_ticket_without_texto_original_is_excluded(self, db, rol_ventas):
        sin_texto = _make_ticket(db, rol_ventas, texto_original=None)

        resultado_ids = {t.id for t in script.find_candidate_tickets(db)}

        assert sin_texto.id not in resultado_ids

    def test_limit_caps_the_number_returned(self, db, rol_ventas):
        _make_ticket(db, rol_ventas, texto_original="Uno")
        _make_ticket(db, rol_ventas, texto_original="Dos")

        resultado = script.find_candidate_tickets(db, limit=1)

        assert len(resultado) == 1


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
