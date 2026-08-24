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
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app.core.config import settings
from app.core.security import create_access_token
from app.models.permiso import Permiso, UsuarioPermisoOverride
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


def _dar_permiso(db, user, codigo: str) -> None:
    permiso = db.query(Permiso).filter_by(codigo=codigo).first()
    if permiso is None:
        permiso = Permiso(codigo=codigo, nombre=codigo, categoria="tickets")
        db.add(permiso)
        db.flush()
    db.add(UsuarioPermisoOverride(usuario_id=user.id, permiso_id=permiso.id, concedido=True))
    db.commit()


def _auth(user) -> dict:
    return {"Authorization": f"Bearer {create_access_token(data={'sub': user.username})}"}


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

        asyncio.run(push_attachment(999999))


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
        _make_adjunto(db, ticket, creador)
        db.commit()

        fake_client = AsyncMock()

        with _patch_background_db(db), patch.object(vikunja_sync_service, "_client", return_value=fake_client):
            asyncio.run(push_attachment(ticket.id))

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


class TestAttachmentUploadedBeforeTicketSynced:
    """The most common real sequence, and the one the original drain lost
    silently: the user uploads the screenshot seconds after creating the
    ticket, so the attachment's `created_at` is EARLIER than the moment the
    ticket finished syncing. A drain filtering `created_at > synced_at`
    finds nothing, declares itself fully drained, and clears the flag -- the
    file never reaches Vikunja and nothing logs it.

    The pre-existing drain test missed this because it inserted the ledger
    row by hand with `synced_at` left NULL, which is the one state
    production never produces."""

    def test_attachment_older_than_synced_at_is_still_uploaded(
        self, db, rol, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        _enable_flag(monkeypatch)
        monkeypatch.setattr(settings, "TICKETS_UPLOADS_DIR", str(tmp_path))
        ticket = _make_ticket(db, rol)
        creador = db.query(Usuario).filter_by(id=ticket.creador_id).one()
        adjunto = _make_adjunto(db, ticket, creador)
        db.commit()

        # The ticket finishes syncing AFTER the attachment was uploaded.
        db.add(
            TicketVikunjaSync(
                ticket_id=ticket.id,
                estado="sincronizado",
                vikunja_task_id=321,
                adjuntos_pendientes=True,
                synced_at=datetime.now(timezone.utc) + timedelta(seconds=5),
            )
        )
        db.commit()

        upload_dir = tmp_path / str(ticket.id)
        upload_dir.mkdir(parents=True, exist_ok=True)
        (upload_dir / adjunto.path_archivo.split("/")[-1]).write_bytes(b"contenido")

        fake_client = AsyncMock()
        fake_client.list_tasks.return_value = []
        fake_client.list_attachments.return_value = []

        with _patch_background_db(db), patch.object(vikunja_sync_service, "_client", return_value=fake_client):
            asyncio.run(run_vikunja_reconcile_cycle())

        fake_client.upload_attachment.assert_called_once()

    def test_attachment_already_in_vikunja_is_not_uploaded_twice(
        self, db, rol, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        """The other half: `upload_attachment` is `idempotent=False`, so a
        second drain must not attach the same file again. Vikunja's own
        attachment list is the source of truth, not a local watermark."""
        _enable_flag(monkeypatch)
        monkeypatch.setattr(settings, "TICKETS_UPLOADS_DIR", str(tmp_path))
        ticket = _make_ticket(db, rol)
        creador = db.query(Usuario).filter_by(id=ticket.creador_id).one()
        adjunto = _make_adjunto(db, ticket, creador)
        db.add(
            TicketVikunjaSync(ticket_id=ticket.id, estado="sincronizado", vikunja_task_id=321, adjuntos_pendientes=True)
        )
        db.commit()

        upload_dir = tmp_path / str(ticket.id)
        upload_dir.mkdir(parents=True, exist_ok=True)
        (upload_dir / adjunto.path_archivo.split("/")[-1]).write_bytes(b"contenido")

        fake_client = AsyncMock()
        fake_client.list_tasks.return_value = []
        fake_client.list_attachments.return_value = [
            {"id": 1, "file": {"name": adjunto.nombre_archivo, "size": adjunto.tamano_bytes}}
        ]

        with _patch_background_db(db), patch.object(vikunja_sync_service, "_client", return_value=fake_client):
            asyncio.run(run_vikunja_reconcile_cycle())

        fake_client.upload_attachment.assert_not_called()
        row = db.query(TicketVikunjaSync).filter_by(ticket_id=ticket.id).one()
        assert row.adjuntos_pendientes is False


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
        _make_adjunto(db, ticket, creador)
        db.commit()

        fake_client = AsyncMock()

        with _patch_background_db(db), patch.object(vikunja_sync_service, "_client", return_value=fake_client):
            asyncio.run(push_attachment(ticket.id))

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


class TestAttachmentArrivingDuringDrainIsNotLost:
    """Lost-update guard: a file uploaded WHILE the loop is draining must not
    have its pending flag wiped by that drain.

    The drain reads the ticket's attachments, uploads them, then clears
    `adjuntos_pendientes`. If a user uploads in between, `push_attachment`
    sets the flag to True and the clear would immediately overwrite it with
    False -- the newcomer would never be uploaded, and nothing would look at
    that ticket again until some other attachment happened to arrive."""

    def test_flag_survives_when_a_newer_attachment_arrives_mid_drain(
        self, db, rol, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        _enable_flag(monkeypatch)
        monkeypatch.setattr(settings, "TICKETS_UPLOADS_DIR", str(tmp_path))
        ticket = _make_ticket(db, rol)
        creador = db.query(Usuario).filter_by(id=ticket.creador_id).one()
        db.add(
            TicketVikunjaSync(ticket_id=ticket.id, estado="sincronizado", vikunja_task_id=55, adjuntos_pendientes=True)
        )
        db.commit()

        upload_dir = tmp_path / str(ticket.id)
        upload_dir.mkdir(parents=True, exist_ok=True)
        primero = _make_adjunto(db, ticket, creador, nombre="primero.png")
        db.commit()
        (upload_dir / primero.path_archivo.split("/")[-1]).write_bytes(b"1")

        fake_client = AsyncMock()
        fake_client.list_tasks.return_value = []
        fake_client.list_attachments.return_value = []

        # Simulate the race: a second attachment lands while the first one
        # is being uploaded.
        segundo_id: dict = {}

        async def upload_y_llega_otro(**kwargs):
            if not segundo_id:
                segundo = _make_adjunto(db, ticket, creador, nombre="segundo.png")
                db.commit()
                (upload_dir / segundo.path_archivo.split("/")[-1]).write_bytes(b"2")
                segundo_id["id"] = segundo.id
            return {"id": 1}

        fake_client.upload_attachment.side_effect = upload_y_llega_otro

        with _patch_background_db(db), patch.object(vikunja_sync_service, "_client", return_value=fake_client):
            asyncio.run(run_vikunja_reconcile_cycle())

        row = db.query(TicketVikunjaSync).filter_by(ticket_id=ticket.id).one()
        assert row.adjuntos_pendientes is True, "the newcomer must keep the ticket flagged for the next cycle"


class TestTerminalFailureNotifiesOncePerCycle:
    """A terminal failure has to reach a person, not just a table -- but if
    Vikunja is down, twenty tickets go ambiguous in the same cycle. Notifying
    per ticket would put twenty rows in everyone's bell at once, which is how
    people learn to ignore the bell.

    `notificado_at` alone does not solve it: it stops the SECOND cycle, not
    the first burst. So the cycle aggregates: one notification naming how
    many, whoever is affected."""

    def test_many_failures_produce_a_single_aggregated_notification(
        self, db, rol, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _enable_flag(monkeypatch)
        tickets = [_make_ticket(db, rol) for _ in range(3)]
        for t in tickets:
            db.add(TicketVikunjaSync(ticket_id=t.id, estado="ambiguo"))
        db.commit()

        fake_client = AsyncMock()
        # No task matches any marker, so all three stay ambiguous and flag.
        fake_client.list_tasks.return_value = []

        creadas = []

        def _fake_notificar(session, **kwargs):
            creadas.append(kwargs)
            return []

        with (
            _patch_background_db(db),
            patch.object(vikunja_sync_service, "_client", return_value=fake_client),
            patch.object(vikunja_sync_service, "crear_notificaciones_para_permisos", _fake_notificar),
        ):
            asyncio.run(run_vikunja_reconcile_cycle())

        assert len(creadas) == 1, "three failures must not mean three notifications"
        assert "3" in creadas[0]["mensaje"], "the single notification must say how many failed"

    def test_rows_already_notified_do_not_notify_again(self, db, rol, monkeypatch: pytest.MonkeyPatch) -> None:
        """Ambiguous rows that ALREADY carry `notificado_at` must produce zero
        notifications: once a row is handed to a human, the bell stops.

        Verified by sabotage, which turned up something worth writing down:
        TWO independent guards enforce this — the loop's fetch filters on
        `notificado_at IS NULL`, and `_flag_for_notification`'s own UPDATE
        carries the same condition. Removing either one alone still passes,
        because the other catches it. This test protects the PROPERTY, not
        one mechanism, and only fails when both are gone.

        (It replaced a smoke test that asserted on a cycle with nothing to
        flag — that one passed even with no guard at all, because the cycle
        never reached the notification in the first place.)"""
        _enable_flag(monkeypatch)
        tickets = [_make_ticket(db, rol) for _ in range(2)]
        for t in tickets:
            db.add(TicketVikunjaSync(ticket_id=t.id, estado="ambiguo", notificado_at=datetime.now(timezone.utc)))
        db.commit()

        fake_client = AsyncMock()
        fake_client.list_tasks.return_value = []

        creadas = []

        def _fake_notificar(session, **kwargs):
            creadas.append(kwargs)
            return []

        with (
            _patch_background_db(db),
            patch.object(vikunja_sync_service, "_client", return_value=fake_client),
            patch.object(vikunja_sync_service, "crear_notificaciones_para_permisos", _fake_notificar),
        ):
            asyncio.run(run_vikunja_reconcile_cycle())

        assert creadas == [], "a row already handed to a human must not keep ringing the bell"


class TestImmediatePathAlsoNotifies:
    """The immediate push is the MOST common terminal-failure path, and it was
    the only one that never notified.

    Two changes that are each right on their own combined into a hole: the
    loop excludes already-notified rows (so zombie rows stop hammering
    Vikunja every 300s), and the loop notifies about what it flags. But
    `_resolve_ambiguous_create` also flags -- setting `notificado_at` --
    without notifying. That row was then excluded from the sweep forever, so
    it never entered the loop's batch and no one was ever told."""

    def test_ambiguous_create_on_the_immediate_path_notifies(self, db, rol, monkeypatch: pytest.MonkeyPatch) -> None:
        _enable_flag(monkeypatch)
        monkeypatch.setattr(vikunja_sync_service, "_AMBIGUOUS_CHECK_DELAY_SECONDS", 0)
        ticket = _make_ticket(db, rol)

        fake_client = AsyncMock()
        # The create is ambiguous, and the check then finds two candidates:
        # unsafe either way, so it must route to a human.
        fake_client.create_task.side_effect = VikunjaTransientError("PUT", "/x", None, "timeout")
        marcador = vikunja_sync_service._marker(ticket.id)
        ahora = datetime.now(timezone.utc).isoformat()
        fake_client.list_tasks.return_value = [
            {"id": 1, "description": marcador + "a", "created": ahora},
            {"id": 2, "description": marcador + "b", "created": ahora},
        ]

        creadas = []

        def _fake_notificar(session, **kwargs):
            creadas.append(kwargs)
            return []

        with (
            _patch_background_db(db),
            patch.object(vikunja_sync_service, "_client", return_value=fake_client),
            patch.object(vikunja_sync_service, "crear_notificaciones_para_permisos", _fake_notificar),
        ):
            asyncio.run(push_ticket(ticket.id))

        row = db.query(TicketVikunjaSync).filter_by(ticket_id=ticket.id).one()
        assert row.estado == "ambiguo"
        assert len(creadas) == 1, "the immediate path must tell someone, not just set notificado_at"


class TestPendienteIsNotAnOrphanState:
    """`pendiente` must be swept by the loop, or rows land there and are
    never touched again. Two real paths get you there:

    1. The flag was OFF when the ticket was created (so `push_ticket` never
       made a row), then turned ON, and an attachment upload creates the row
       in `pendiente`. Nothing calls `push_ticket` for that ticket ever
       again -- the hook only runs on the creation POST.
    2. The process dies between the row INSERT and the CAS claim, or a
       deploy restarts the app between the ticket's commit and its
       BackgroundTask. The row sits in `pendiente`, and the 300s "crash
       backstop" -- which exists precisely for this -- does not look at it.

    Either way the ticket never syncs and the attachment never uploads, with
    no error and no warning."""

    def test_loop_recovers_a_pendiente_row_nobody_will_hook_again(
        self, db, rol, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _enable_flag(monkeypatch)
        ticket = _make_ticket(db, rol)
        # Exactly what `push_attachment` leaves behind when the ticket was
        # created while the flag was off.
        db.add(TicketVikunjaSync(ticket_id=ticket.id, estado="pendiente", adjuntos_pendientes=True))
        db.commit()

        fake_client = AsyncMock()
        fake_client.list_tasks.return_value = []
        fake_client.list_attachments.return_value = []
        fake_client.create_task.return_value = {"id": 777}

        with _patch_background_db(db), patch.object(vikunja_sync_service, "_client", return_value=fake_client):
            asyncio.run(run_vikunja_reconcile_cycle())

        fake_client.create_task.assert_called_once()
        row = db.query(TicketVikunjaSync).filter_by(ticket_id=ticket.id).one()
        assert row.estado == "sincronizado"
        assert row.vikunja_task_id == 777


class TestSecondAttachmentAfterFirstDrainDoesNotReupload:
    """The exact regression the second review pass demanded: a ticket that
    already drained one attachment must NOT re-upload it when a second
    attachment arrives later and triggers another drain cycle. Dedup is by
    asking Vikunja what it already has (`list_attachments`), not by a local
    watermark — the second `list_attachments` call reflects A already being
    on the task, exactly like the real API would report after the first
    drain actually uploaded it."""

    def test_second_attachment_drain_does_not_reupload_the_first(
        self, db, rol, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        _enable_flag(monkeypatch)
        monkeypatch.setattr(settings, "TICKETS_UPLOADS_DIR", str(tmp_path))
        ticket = _make_ticket(db, rol)
        creador = db.query(Usuario).filter_by(id=ticket.creador_id).one()
        db.add(
            TicketVikunjaSync(ticket_id=ticket.id, estado="sincronizado", vikunja_task_id=42, adjuntos_pendientes=True)
        )
        db.commit()

        upload_dir = tmp_path / str(ticket.id)
        upload_dir.mkdir(parents=True, exist_ok=True)

        adjunto_a = _make_adjunto(db, ticket, creador, nombre="a.png")
        db.commit()
        (upload_dir / adjunto_a.path_archivo.split("/")[-1]).write_bytes(b"a")

        fake_client = AsyncMock()
        fake_client.list_tasks.return_value = []
        fake_client.list_attachments.return_value = []

        # First drain cycle: uploads A (nothing on the task yet).
        with _patch_background_db(db), patch.object(vikunja_sync_service, "_client", return_value=fake_client):
            asyncio.run(run_vikunja_reconcile_cycle())

        assert fake_client.upload_attachment.call_count == 1
        row = db.query(TicketVikunjaSync).filter_by(ticket_id=ticket.id).one()
        assert row.adjuntos_pendientes is False

        # A second attachment arrives later and re-flags the ticket. Vikunja
        # now reports A as already present (that is what the real API would
        # say after the first drain's upload actually succeeded).
        fake_client.list_attachments.return_value = [
            {"id": 1, "file": {"name": "a.png", "size": adjunto_a.tamano_bytes}}
        ]
        adjunto_b = _make_adjunto(db, ticket, creador, nombre="b.png")
        db.commit()
        (upload_dir / adjunto_b.path_archivo.split("/")[-1]).write_bytes(b"b")

        with _patch_background_db(db), patch.object(vikunja_sync_service, "_client", return_value=fake_client):
            asyncio.run(push_attachment(ticket.id))
            asyncio.run(run_vikunja_reconcile_cycle())

        # Only B was uploaded this round — A must NOT be re-uploaded.
        assert fake_client.upload_attachment.call_count == 2
        uploaded_filenames = [call.kwargs["filename"] for call in fake_client.upload_attachment.call_args_list]
        assert uploaded_filenames == ["a.png", "b.png"]


class TestEstadoSyncVikunjaEndpoint:
    """`GET /tickets/vikunja/estado` — the deliberate check-on-it surface.
    A terminal failure ALSO raises an in-app notification, because a table
    nobody opens is not visibility."""

    def test_requires_tickets_gestionar(self, db, rol, client) -> None:
        """Ticket access is not enough: this exposes operational state across
        every ticket, not only the ones this user can see."""
        usuario = _make_usuario(db, rol)
        _dar_permiso(db, usuario, "tickets.ver")

        resp = client.get("/api/tickets/tickets/vikunja/estado", headers=_auth(usuario))

        assert resp.status_code == 403

    def test_reports_counts_and_the_flag(self, db, rol, client, monkeypatch: pytest.MonkeyPatch) -> None:
        usuario = _make_usuario(db, rol)
        _dar_permiso(db, usuario, "tickets.gestionar")
        _enable_flag(monkeypatch)

        t1, t2, t3 = _make_ticket(db, rol), _make_ticket(db, rol), _make_ticket(db, rol)
        db.add(TicketVikunjaSync(ticket_id=t1.id, estado="sincronizado", vikunja_task_id=1))
        db.add(TicketVikunjaSync(ticket_id=t2.id, estado="ambiguo"))
        db.add(TicketVikunjaSync(ticket_id=t3.id, estado="error", ultimo_error="token vencido"))
        db.commit()

        resp = client.get("/api/tickets/tickets/vikunja/estado", headers=_auth(usuario))

        assert resp.status_code == 200
        cuerpo = resp.json()
        assert cuerpo["habilitado"] is True
        assert cuerpo["sincronizados"] == 1
        assert cuerpo["ambiguos"] == 1
        assert cuerpo["con_error"] == 1
        assert cuerpo["ultimo_error"] == "token vencido"

    def test_habilitado_follows_the_flag(self, db, rol, client, monkeypatch: pytest.MonkeyPatch) -> None:
        """The frontend gates the badge on this field, so it must report the
        flag rather than assume it."""
        usuario = _make_usuario(db, rol)
        _dar_permiso(db, usuario, "tickets.gestionar")
        monkeypatch.setattr(settings, "TICKETS_VIKUNJA_SYNC_ENABLED", False)

        resp = client.get("/api/tickets/tickets/vikunja/estado", headers=_auth(usuario))

        assert resp.json()["habilitado"] is False
