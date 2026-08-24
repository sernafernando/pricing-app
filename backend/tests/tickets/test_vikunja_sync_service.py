"""RED/GREEN for `vikunja_sync_service` (sdd/tickets-sync-vikunja, PR 2).

No pytest-asyncio in this project — async code is driven with
asyncio.run() (canon: test_ml_api_client_post_answer.py,
test_vikunja_client.py). Uses httpx.MockTransport monkeypatched into
`httpx.AsyncClient.__init__` for the Vikunja client's HTTP layer, and a
SAVEPOINT-free `_FakeBackgroundDb` wrapper (mirrors
`test_ejemplos_service.py`) so `get_background_db()` reuses the test's own
transactional `db` session instead of a second real connection.

Covers (design "the ordering that makes duplicates impossible"):
- Flag off: `push_ticket`/`push_attachment` never touch `get_background_db`
  — the flag check must be the FIRST statement, before any session opens.
- The duplicate test (most important in the change): create_task raises an
  ambiguous transient error after the task was actually created
  server-side -> row goes 'ambiguo' -> the immediate check adopts the
  matching task -> 'sincronizado', with the create-call counter still at 1.
  Mirror: marker absent in the window -> exactly one create.
- The reconcile loop NEVER creates on ambiguity: an unmatched 'ambiguo' row
  stays 'ambiguo', create-call counter 0.
- Attachment deferral: uploaded while parent is 'pendiente' -> pending
  flag True, no upload attempted; drains once the ticket syncs.

Run:
    cd backend && source venv/bin/activate
    ENVIRONMENT=testing DATABASE_URL=sqlite:///./test.db \
        pytest tests/tickets/test_vikunja_sync_service.py -v --tb=short
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app.core.config import settings
from app.models.rol import Rol
from app.models.usuario import AuthProvider, RolUsuario, Usuario
from app.services.vikunja_client import VikunjaPermanentError, VikunjaTransientError
from app.tickets.models.adjunto_ticket import AdjuntoTicket
from app.tickets.models.sector import Sector
from app.tickets.models.ticket import PrioridadTicket, Ticket
from app.tickets.models.ticket_vikunja_sync import TicketVikunjaSync
from app.tickets.models.tipo_ticket import TipoTicket
from app.tickets.models.workflow import EstadoTicket, Workflow
from app.tickets.services import vikunja_sync_service
from app.tickets.services.vikunja_sync_service import (
    push_attachment,
    push_ticket,
    run_vikunja_reconcile_cycle,
)

_seq = [0]


class _FakeBackgroundDb:
    """Mirrors `test_ejemplos_service.py`'s own fixture — reuses the test's
    transactional `db` session for every `get_background_db()` call the
    service under test makes, instead of a second real connection."""

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
    return patch("app.tickets.services.vikunja_sync_service.get_background_db", return_value=_FakeBackgroundDb(db))


def _enable_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "TICKETS_VIKUNJA_SYNC_ENABLED", True)
    monkeypatch.setattr(settings, "VIKUNJA_BASE_URL", "http://vikunja.local")
    monkeypatch.setattr(settings, "VIKUNJA_TOKEN", "secret-token")
    monkeypatch.setattr(settings, "VIKUNJA_PROJECT_ID", 7)


def _make_sector(db) -> Sector:
    _seq[0] += 1
    s = Sector(codigo=f"VIKUNJA_SECT_{_seq[0]}", nombre="Sector Vikunja Test", activo=True, configuracion={})
    db.add(s)
    db.flush()
    return s


def _make_tipo_y_estado(db, sector: Sector) -> tuple[TipoTicket, EstadoTicket]:
    workflow = Workflow(sector_id=sector.id, nombre="WF Vikunja Test", es_default=True, activo=True)
    db.add(workflow)
    db.flush()

    estado = EstadoTicket(
        workflow_id=workflow.id, codigo="abierto", nombre="Abierto", orden=1, es_inicial=True, es_final=False
    )
    db.add(estado)
    db.flush()

    tipo = TipoTicket(sector_id=sector.id, codigo="bug", nombre="Bug", workflow_id=workflow.id)
    db.add(tipo)
    db.flush()
    return tipo, estado


def _make_usuario(db, rol: Rol) -> Usuario:
    _seq[0] += 1
    usuario = Usuario(
        username=f"vikunja_user_{_seq[0]}",
        email=f"vikunja_{_seq[0]}@test.com",
        nombre="Vikunja Test User",
        password_hash="x",
        rol=RolUsuario.VENTAS,
        rol_id=rol.id,
        auth_provider=AuthProvider.LOCAL,
        activo=True,
    )
    db.add(usuario)
    db.flush()
    return usuario


def _make_ticket(db, rol: Rol, titulo: str = "Ticket Vikunja test", descripcion: str = "Cuerpo del ticket") -> Ticket:
    sector = _make_sector(db)
    tipo, estado = _make_tipo_y_estado(db, sector)
    creador = _make_usuario(db, rol)
    ticket = Ticket(
        titulo=titulo,
        descripcion=descripcion,
        prioridad=PrioridadTicket.MEDIA,
        sector_id=sector.id,
        tipo_ticket_id=tipo.id,
        estado_id=estado.id,
        creador_id=creador.id,
        campos_metadata={},
        texto_original=descripcion,
    )
    db.add(ticket)
    db.flush()
    return ticket


@pytest.fixture
def rol(db):
    _seq[0] += 1
    r = Rol(codigo=f"VENTAS_VK_{_seq[0]}", nombre="Ventas", es_sistema=False, orden=10, activo=True)
    db.add(r)
    db.flush()
    return r


def _make_adjunto(db, ticket: Ticket, usuario: Usuario, nombre: str = "foto.png") -> AdjuntoTicket:
    adjunto = AdjuntoTicket(
        ticket_id=ticket.id,
        nombre_archivo=nombre,
        path_archivo=f"{ticket.id}/some_{nombre}",
        mime_type="image/png",
        tamano_bytes=10,
        subido_por_id=usuario.id,
    )
    db.add(adjunto)
    db.flush()
    return adjunto


def _instant_sleep():
    async def _sleep(_seconds: float) -> None:
        return None

    return _sleep


class TestFlagOffNeverTouchesDb:
    """Bug that shipped once already: a prior feature checked its flag
    AFTER opening a session. The fix is that the flag check must be the
    very first statement — this test raises from `get_background_db`
    itself if it is ever called."""

    def test_push_ticket_flag_off_never_opens_a_session(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "TICKETS_VIKUNJA_SYNC_ENABLED", False)

        def _boom():
            raise AssertionError("get_background_db must not be called when the flag is off")

        monkeypatch.setattr(vikunja_sync_service, "get_background_db", _boom)

        asyncio.run(push_ticket(999999))

    def test_push_attachment_flag_off_never_opens_a_session(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "TICKETS_VIKUNJA_SYNC_ENABLED", False)

        def _boom():
            raise AssertionError("get_background_db must not be called when the flag is off")

        monkeypatch.setattr(vikunja_sync_service, "get_background_db", _boom)

        asyncio.run(push_attachment(999999, 1))


class TestPushTicketHappyPath:
    def test_create_task_success_marks_sincronizado(self, db, rol, monkeypatch: pytest.MonkeyPatch) -> None:
        _enable_flag(monkeypatch)
        ticket = _make_ticket(db, rol)
        db.commit()

        fake_client = AsyncMock()
        fake_client.create_task.return_value = {"id": 555}

        with _patch_background_db(db), patch.object(vikunja_sync_service, "_client", return_value=fake_client):
            asyncio.run(push_ticket(ticket.id))

        row = db.query(TicketVikunjaSync).filter_by(ticket_id=ticket.id).one()
        assert row.estado == "sincronizado"
        assert row.vikunja_task_id == 555
        assert fake_client.create_task.call_count == 1


class TestDuplicateAvoidance:
    """The heart of the change: an ambiguous create (task actually created,
    acknowledgement lost) must resolve to exactly ONE task, never two."""

    def test_ambiguous_create_adopted_by_immediate_check_no_duplicate(
        self, db, rol, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _enable_flag(monkeypatch)
        monkeypatch.setattr(asyncio, "sleep", _instant_sleep())
        ticket = _make_ticket(db, rol, titulo="Ticket ambiguo", descripcion="cuerpo")
        db.commit()

        fake_client = AsyncMock()
        fake_client.create_task.side_effect = VikunjaTransientError("PUT", "/x", None, "ReadTimeout")
        fake_client.list_tasks.return_value = [
            {
                "id": 4242,
                "description": f"Ticket original #{ticket.id} \n\ncuerpo",
                "created": "2026-08-24T12:00:00Z",
            }
        ]

        with (
            _patch_background_db(db),
            patch.object(vikunja_sync_service, "_client", return_value=fake_client),
            patch("app.tickets.services.vikunja_sync_service.datetime") as fake_datetime_module,
        ):
            # Freeze "now" close to the fake task's `created` so it falls
            # inside the ~120s immediate-check window.
            from datetime import UTC, datetime as real_datetime

            fake_now = real_datetime(2026, 8, 24, 12, 0, 5, tzinfo=UTC)
            fake_datetime_module.now.return_value = fake_now
            fake_datetime_module.fromisoformat = real_datetime.fromisoformat
            fake_datetime_module.UTC = UTC

            asyncio.run(push_ticket(ticket.id))

        row = db.query(TicketVikunjaSync).filter_by(ticket_id=ticket.id).one()
        assert row.estado == "sincronizado"
        assert row.vikunja_task_id == 4242
        # Exactly ONE create attempt ever reached Vikunja — the adoption
        # path must not create a second task.
        assert fake_client.create_task.call_count == 1

    def test_marker_absent_in_window_creates_exactly_once(self, db, rol, monkeypatch: pytest.MonkeyPatch) -> None:
        _enable_flag(monkeypatch)
        monkeypatch.setattr(asyncio, "sleep", _instant_sleep())
        ticket = _make_ticket(db, rol, titulo="Ticket sin match", descripcion="cuerpo")
        db.commit()

        fake_client = AsyncMock()
        fake_client.create_task.side_effect = [
            VikunjaTransientError("PUT", "/x", None, "ReadTimeout"),
            {"id": 9001},
        ]
        fake_client.list_tasks.return_value = []  # nothing matches the marker

        with _patch_background_db(db), patch.object(vikunja_sync_service, "_client", return_value=fake_client):
            asyncio.run(push_ticket(ticket.id))

        row = db.query(TicketVikunjaSync).filter_by(ticket_id=ticket.id).one()
        assert row.estado == "sincronizado"
        assert row.vikunja_task_id == 9001
        assert fake_client.create_task.call_count == 2

    def test_permanent_error_marks_error_state(self, db, rol, monkeypatch: pytest.MonkeyPatch) -> None:
        _enable_flag(monkeypatch)
        ticket = _make_ticket(db, rol)
        db.commit()

        fake_client = AsyncMock()
        fake_client.create_task.side_effect = VikunjaPermanentError("PUT", "/x", 422, "invalid")

        with _patch_background_db(db), patch.object(vikunja_sync_service, "_client", return_value=fake_client):
            asyncio.run(push_ticket(ticket.id))

        row = db.query(TicketVikunjaSync).filter_by(ticket_id=ticket.id).one()
        assert row.estado == "error"
        assert row.intentos == 1
        assert "422" in row.ultimo_error

    def test_second_call_does_not_reclaim_an_already_owned_row(self, db, rol, monkeypatch: pytest.MonkeyPatch) -> None:
        """CAS claim: a row already 'enviando'/'sincronizado' must not be
        claimed again — guards a concurrent duplicate hook invocation."""
        _enable_flag(monkeypatch)
        ticket = _make_ticket(db, rol)
        db.add(TicketVikunjaSync(ticket_id=ticket.id, estado="sincronizado", vikunja_task_id=1))
        db.commit()

        fake_client = AsyncMock()

        with _patch_background_db(db), patch.object(vikunja_sync_service, "_client", return_value=fake_client):
            asyncio.run(push_ticket(ticket.id))

        assert fake_client.create_task.call_count == 0
        row = db.query(TicketVikunjaSync).filter_by(ticket_id=ticket.id).one()
        assert row.vikunja_task_id == 1


class TestReconcileLoopNeverCreatesOnAmbiguity:
    def test_unmatched_ambiguous_row_stays_ambiguous_never_creates(
        self, db, rol, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _enable_flag(monkeypatch)
        ticket = _make_ticket(db, rol)
        db.add(TicketVikunjaSync(ticket_id=ticket.id, estado="ambiguo"))
        db.commit()

        fake_client = AsyncMock()
        fake_client.list_tasks.return_value = []  # no match anywhere

        with _patch_background_db(db), patch.object(vikunja_sync_service, "_client", return_value=fake_client):
            stats = asyncio.run(run_vikunja_reconcile_cycle())

        assert fake_client.create_task.call_count == 0
        row = db.query(TicketVikunjaSync).filter_by(ticket_id=ticket.id).one()
        assert row.estado == "ambiguo"
        assert row.notificado_at is not None
        assert stats["still_ambiguous"] == 1

    def test_multiple_matches_stays_ambiguous_never_creates(self, db, rol, monkeypatch: pytest.MonkeyPatch) -> None:
        _enable_flag(monkeypatch)
        ticket = _make_ticket(db, rol)
        db.add(TicketVikunjaSync(ticket_id=ticket.id, estado="ambiguo"))
        db.commit()

        marker = f"Ticket original #{ticket.id} "
        fake_client = AsyncMock()
        fake_client.list_tasks.return_value = [
            {"id": 1, "description": marker + "a"},
            {"id": 2, "description": marker + "b"},
        ]

        with _patch_background_db(db), patch.object(vikunja_sync_service, "_client", return_value=fake_client):
            asyncio.run(run_vikunja_reconcile_cycle())

        assert fake_client.create_task.call_count == 0
        row = db.query(TicketVikunjaSync).filter_by(ticket_id=ticket.id).one()
        assert row.estado == "ambiguo"

    def test_exactly_one_match_adopts(self, db, rol, monkeypatch: pytest.MonkeyPatch) -> None:
        _enable_flag(monkeypatch)
        ticket = _make_ticket(db, rol)
        db.add(TicketVikunjaSync(ticket_id=ticket.id, estado="ambiguo"))
        db.commit()

        marker = f"Ticket original #{ticket.id} "
        fake_client = AsyncMock()
        fake_client.list_tasks.return_value = [{"id": 77, "description": marker}]

        with _patch_background_db(db), patch.object(vikunja_sync_service, "_client", return_value=fake_client):
            stats = asyncio.run(run_vikunja_reconcile_cycle())

        assert fake_client.create_task.call_count == 0
        row = db.query(TicketVikunjaSync).filter_by(ticket_id=ticket.id).one()
        assert row.estado == "sincronizado"
        assert row.vikunja_task_id == 77
        assert stats["adopted"] == 1

    def test_stale_enviando_reclaimed_to_ambiguous(self, db, rol, monkeypatch: pytest.MonkeyPatch) -> None:
        from datetime import UTC, datetime, timedelta

        _enable_flag(monkeypatch)
        ticket = _make_ticket(db, rol)
        old = datetime.now(UTC) - timedelta(minutes=20)
        db.add(TicketVikunjaSync(ticket_id=ticket.id, estado="enviando", claimed_at=old))
        db.commit()

        fake_client = AsyncMock()
        fake_client.list_tasks.return_value = []

        with _patch_background_db(db), patch.object(vikunja_sync_service, "_client", return_value=fake_client):
            stats = asyncio.run(run_vikunja_reconcile_cycle())

        assert stats["reclaimed"] == 1
        row = db.query(TicketVikunjaSync).filter_by(ticket_id=ticket.id).one()
        assert row.estado == "ambiguo"


class TestAttachmentDeferral:
    def test_upload_while_parent_pending_defers_and_does_not_upload(
        self, db, rol, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _enable_flag(monkeypatch)
        ticket = _make_ticket(db, rol)
        creador = db.query(Usuario).filter_by(id=ticket.creador_id).one()
        db.add(TicketVikunjaSync(ticket_id=ticket.id, estado="pendiente"))
        db.commit()
        adjunto = _make_adjunto(db, ticket, creador)
        db.commit()

        fake_client = AsyncMock()

        with _patch_background_db(db), patch.object(vikunja_sync_service, "_client", return_value=fake_client):
            asyncio.run(push_attachment(ticket.id, adjunto.id))

        fake_client.upload_attachment.assert_not_called()
        row = db.query(TicketVikunjaSync).filter_by(ticket_id=ticket.id).one()
        assert row.adjuntos_pendientes is True

    def test_reconcile_loop_drains_pending_attachments_once_synced(
        self, db, rol, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        _enable_flag(monkeypatch)
        monkeypatch.setattr(settings, "TICKETS_UPLOADS_DIR", str(tmp_path))
        ticket = _make_ticket(db, rol)
        creador = db.query(Usuario).filter_by(id=ticket.creador_id).one()
        db.add(
            TicketVikunjaSync(ticket_id=ticket.id, estado="sincronizado", vikunja_task_id=321, adjuntos_pendientes=True)
        )
        db.commit()
        adjunto = _make_adjunto(db, ticket, creador)
        db.commit()

        upload_dir = tmp_path / str(ticket.id)
        upload_dir.mkdir(parents=True, exist_ok=True)
        (upload_dir / adjunto.path_archivo.split("/")[-1]).write_bytes(b"contenido")

        fake_client = AsyncMock()
        fake_client.list_tasks.return_value = []

        with _patch_background_db(db), patch.object(vikunja_sync_service, "_client", return_value=fake_client):
            stats = asyncio.run(run_vikunja_reconcile_cycle())

        fake_client.upload_attachment.assert_called_once()
        row = db.query(TicketVikunjaSync).filter_by(ticket_id=ticket.id).one()
        assert row.adjuntos_pendientes is False
        assert stats["drained"] == 1


class TestAttachmentSinglePathAndPartialFailure:
    """Review findings fixed after the first review pass: (1) `push_attachment`
    must NEVER upload directly, even on an already-synced ticket — only the
    loop uploads, so there is exactly one writer and no two-path duplicate
    race; (2) a partial-failure drain must NOT clear `adjuntos_pendientes`,
    or the failed attachment is lost forever."""

    def test_push_attachment_never_uploads_directly_even_when_synced(
        self, db, rol, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _enable_flag(monkeypatch)
        ticket = _make_ticket(db, rol)
        creador = db.query(Usuario).filter_by(id=ticket.creador_id).one()
        db.add(TicketVikunjaSync(ticket_id=ticket.id, estado="sincronizado", vikunja_task_id=999))
        db.commit()
        adjunto = _make_adjunto(db, ticket, creador)
        db.commit()

        fake_client = AsyncMock()

        with _patch_background_db(db), patch.object(vikunja_sync_service, "_client", return_value=fake_client):
            asyncio.run(push_attachment(ticket.id, adjunto.id))

        fake_client.upload_attachment.assert_not_called()
        row = db.query(TicketVikunjaSync).filter_by(ticket_id=ticket.id).one()
        assert row.adjuntos_pendientes is True

    def test_partial_drain_failure_keeps_flag_true_for_retry(
        self, db, rol, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        _enable_flag(monkeypatch)
        monkeypatch.setattr(settings, "TICKETS_UPLOADS_DIR", str(tmp_path))
        ticket = _make_ticket(db, rol)
        creador = db.query(Usuario).filter_by(id=ticket.creador_id).one()
        db.add(
            TicketVikunjaSync(ticket_id=ticket.id, estado="sincronizado", vikunja_task_id=321, adjuntos_pendientes=True)
        )
        db.commit()
        adjunto = _make_adjunto(db, ticket, creador)
        db.commit()

        upload_dir = tmp_path / str(ticket.id)
        upload_dir.mkdir(parents=True, exist_ok=True)
        (upload_dir / adjunto.path_archivo.split("/")[-1]).write_bytes(b"contenido")

        fake_client = AsyncMock()
        fake_client.list_tasks.return_value = []
        fake_client.upload_attachment.side_effect = VikunjaTransientError("PUT", "/x", 500, "boom")

        with _patch_background_db(db), patch.object(vikunja_sync_service, "_client", return_value=fake_client):
            asyncio.run(run_vikunja_reconcile_cycle())

        row = db.query(TicketVikunjaSync).filter_by(ticket_id=ticket.id).one()
        assert row.adjuntos_pendientes is True, "a failed upload must stay pending for the next cycle to retry"


class TestErrorStateBoundedRetry:
    def test_reconcile_loop_retries_error_rows_under_budget(self, db, rol, monkeypatch: pytest.MonkeyPatch) -> None:
        _enable_flag(monkeypatch)
        ticket = _make_ticket(db, rol)
        db.add(TicketVikunjaSync(ticket_id=ticket.id, estado="error", intentos=1, ultimo_error="boom"))
        db.commit()

        fake_client = AsyncMock()
        fake_client.create_task.return_value = {"id": 111}

        with _patch_background_db(db), patch.object(vikunja_sync_service, "_client", return_value=fake_client):
            stats = asyncio.run(run_vikunja_reconcile_cycle())

        assert fake_client.create_task.call_count == 1
        row = db.query(TicketVikunjaSync).filter_by(ticket_id=ticket.id).one()
        assert row.estado == "sincronizado"
        assert row.vikunja_task_id == 111
        assert stats["error_retried"] == 1

    def test_reconcile_loop_does_not_retry_error_rows_past_budget(
        self, db, rol, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _enable_flag(monkeypatch)
        ticket = _make_ticket(db, rol)
        db.add(
            TicketVikunjaSync(
                ticket_id=ticket.id,
                estado="error",
                intentos=vikunja_sync_service._MAX_ERROR_RETRY_INTENTOS,
                ultimo_error="boom",
            )
        )
        db.commit()

        fake_client = AsyncMock()

        with _patch_background_db(db), patch.object(vikunja_sync_service, "_client", return_value=fake_client):
            stats = asyncio.run(run_vikunja_reconcile_cycle())

        assert fake_client.create_task.call_count == 0
        assert stats["error_retried"] == 0
        row = db.query(TicketVikunjaSync).filter_by(ticket_id=ticket.id).one()
        assert row.estado == "error"
