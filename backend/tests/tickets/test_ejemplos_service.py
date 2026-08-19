"""Tests for `ejemplos_service` (tickets-triage-feedback PR3 capture +
PR4a retrieval core). PR4a adds pure retrieval functions
(`recuperar_ejemplos`, block assembly, neutralisation, label
revalidation) — nothing production-wired yet (PR4b's job).

Covers (PR3, capture):
- Flag off (default): confirming a correction does not call `embed_passage`
  and writes no row.
- Flag on + embed succeeds: exactly one `EjemploCorreccion` row for that
  `(propuesta_id, campo)`.
- Ratifying confirm / discard never schedule capture at all.
- Capture never fails a confirm — flag on with embed returning `None`, or
  the capture hook raising, both still leave the confirm HTTP response and
  the committed proposal state untouched.

Covers (PR4a, retrieval core):
- Delimiter-tag neutralisation applied BEFORE truncation.
- Label revalidation drops an out-of-vocabulary corrected value entirely.
- `recuperar_ejemplos` returns `[]` on every degradation path (similarity
  query raises, zero rows, all rows below threshold, `embed_query` None).
- Prompt-block assembly is append-only and byte-identical when there are no
  blocks to append.

Written FIRST (RED phase) per strict TDD.

Run:
    cd backend && source venv/bin/activate
    pytest tests/tickets/test_ejemplos_service.py -v
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.config import settings
from app.core.security import create_access_token, get_password_hash
from app.models.permiso import Permiso, UsuarioPermisoOverride
from app.models.rol import Rol
from app.models.usuario import AuthProvider, RolUsuario, Usuario
from app.tickets.models.ejemplo_correccion import EjemploCorreccion
from app.tickets.models.propuesta_ia import PropuestaIA
from app.tickets.models.sector import Sector
from app.tickets.models.ticket import PrioridadTicket, Ticket
from app.tickets.models.tipo_ticket import TipoTicket
from app.tickets.models.workflow import EstadoTicket, Workflow
from app.tickets.services import confirmacion_service, ejemplos_service

_seq = [0]


class _FakeBackgroundDb:
    """Mirrors `test_confirmacion_service.py`'s own fixture — reuses the
    test's transactional `db` session instead of a real second connection."""

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
    return patch("app.tickets.services.ejemplos_service.get_background_db", return_value=_FakeBackgroundDb(db))


def _make_sector(db) -> Sector:
    _seq[0] += 1
    s = Sector(codigo=f"EJEMPLOS_SECT_{_seq[0]}", nombre="Sector Ejemplos Test", activo=True, configuracion={})
    db.add(s)
    db.flush()
    return s


def _make_tipo_y_estado(db, sector: Sector) -> tuple[TipoTicket, EstadoTicket]:
    workflow = Workflow(sector_id=sector.id, nombre="WF Ejemplos Test", es_default=True, activo=True)
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
        username=f"ejemplos_user_{_seq[0]}",
        email=f"ejemplos_{_seq[0]}@test.com",
        nombre="Ejemplos Test User",
        password_hash=get_password_hash("pass"),
        rol=RolUsuario.VENTAS,
        rol_id=rol.id,
        auth_provider=AuthProvider.LOCAL,
        activo=True,
    )
    db.add(usuario)
    db.flush()
    return usuario


def _make_ticket(db, rol: Rol, texto_original: str = "El login no funciona desde ayer a la tarde") -> Ticket:
    sector = _make_sector(db)
    tipo, estado = _make_tipo_y_estado(db, sector)
    creador = _make_usuario(db, rol)
    ticket = Ticket(
        titulo="Ticket para captura de ejemplos",
        prioridad=PrioridadTicket.MEDIA,
        sector_id=sector.id,
        tipo_ticket_id=tipo.id,
        estado_id=estado.id,
        creador_id=creador.id,
        campos_metadata={},
        texto_original=texto_original,
    )
    db.add(ticket)
    db.flush()
    return ticket


def _make_propuesta(
    db, ticket: Ticket, campo: str = "severidad", valor="mayor", estado: str = "pendiente"
) -> PropuestaIA:
    propuesta = PropuestaIA(
        ticket_id=ticket.id,
        campo=campo,
        valor_propuesto={"valor": valor},
        estado=estado,
    )
    db.add(propuesta)
    db.flush()
    return propuesta


@pytest.fixture
def rol(db):
    _seq[0] += 1
    r = Rol(codigo=f"VENTAS_EJ_{_seq[0]}", nombre="Ventas", es_sistema=False, orden=10, activo=True)
    db.add(r)
    db.flush()
    return r


class TestCapturarCorreccionDirect:
    """Direct unit tests of `capturar_correccion`, independent of the HTTP
    endpoint (mirrors `TestFewshotCapture`'s own AsyncMock-based style)."""

    def test_flag_off_does_not_embed_or_insert(self, db, rol, monkeypatch) -> None:
        monkeypatch.setattr(settings, "TICKETS_TRIAGE_EJEMPLOS_CAPTURE", False)
        ticket = _make_ticket(db, rol)
        usuario = _make_usuario(db, rol)
        propuesta = _make_propuesta(db, ticket, campo="severidad", valor="mayor")
        confirmacion_service.confirmar(db, propuesta.id, usuario, valor_corregido="menor")
        assert propuesta.estado == "corregida"

        embed_passage = AsyncMock(return_value=[0.1] * 384)
        with (
            _patch_background_db(db),
            patch("app.tickets.services.ejemplos_service.embed_passage", new=embed_passage),
        ):
            asyncio.run(ejemplos_service.capturar_correccion(propuesta.id))

        embed_passage.assert_not_called()
        assert db.query(EjemploCorreccion).count() == 0

    def test_flag_off_never_opens_a_db_session(self, monkeypatch) -> None:
        """Flag off must be a true no-op at the pool level too: the flag check
        runs BEFORE `get_background_db`, so a flag-off capture never checks a
        session out of the pool (PR #811 pool-exhaustion lesson)."""
        monkeypatch.setattr(settings, "TICKETS_TRIAGE_EJEMPLOS_CAPTURE", False)
        background_db = MagicMock()
        with patch("app.tickets.services.ejemplos_service.get_background_db", new=background_db):
            asyncio.run(ejemplos_service.capturar_correccion(propuesta_id=1))
        background_db.assert_not_called()

    def test_flag_on_and_embed_ok_inserts_one_row(self, db, rol, monkeypatch) -> None:
        monkeypatch.setattr(settings, "TICKETS_TRIAGE_EJEMPLOS_CAPTURE", True)
        ticket = _make_ticket(db, rol, texto_original="El sistema no permite facturar desde esta mañana")
        usuario = _make_usuario(db, rol)
        propuesta = _make_propuesta(db, ticket, campo="urgencia", valor="baja")
        confirmacion_service.confirmar(db, propuesta.id, usuario, valor_corregido="alta")
        assert propuesta.estado == "corregida"

        embed_passage = AsyncMock(return_value=[0.1] * 384)
        with (
            _patch_background_db(db),
            patch("app.tickets.services.ejemplos_service.embed_passage", new=embed_passage),
        ):
            asyncio.run(ejemplos_service.capturar_correccion(propuesta.id))

        embed_passage.assert_called_once()
        filas = db.query(EjemploCorreccion).filter_by(propuesta_id=propuesta.id, campo="urgencia").all()
        assert len(filas) == 1
        fila = filas[0]
        assert fila.ticket_id == ticket.id
        assert fila.valor_ia == "baja"
        assert fila.valor_corregido == "alta"
        assert fila.texto == "El sistema no permite facturar desde esta mañana"
        assert fila.active is True

    def test_ratifying_confirm_never_schedules_capture(self, db, rol) -> None:
        """A plain ratification (`es_ia_auto_sin_revisar`, no correction)
        resolves `estado='confirmada'`, never `'corregida'` — the endpoint's
        gate must never even schedule capture for this shape."""
        ticket = _make_ticket(db, rol)
        usuario = _make_usuario(db, rol)
        propuesta = _make_propuesta(db, ticket, campo="severidad", valor="mayor", estado="confirmada")
        propuesta.confirmado_por_id = None
        db.flush()

        resultado = confirmacion_service.confirmar(db, propuesta.id, usuario)
        assert resultado.estado == "confirmada"

    def test_discard_never_schedules_capture(self, db, rol) -> None:
        """`descartar()` never returns `estado='corregida'` — proven by
        construction (it only ever sets `descartada`), so the endpoint gate
        (`resultado.estado == 'corregida'`) can never fire for a discard."""
        ticket = _make_ticket(db, rol)
        usuario = _make_usuario(db, rol)
        propuesta = _make_propuesta(db, ticket, campo="severidad", valor="mayor")
        resultado = confirmacion_service.descartar(db, propuesta.id, usuario)
        assert resultado.estado == "descartada"


def _give_permiso(db, usuario: Usuario, codigo: str = "tickets.triage.confirmar") -> None:
    permiso = db.query(Permiso).filter(Permiso.codigo == codigo).first()
    if not permiso:
        permiso = Permiso(codigo=codigo, nombre=codigo, categoria="tickets")
        db.add(permiso)
        db.flush()
    db.add(UsuarioPermisoOverride(usuario_id=usuario.id, permiso_id=permiso.id, concedido=True))
    db.flush()


def _headers(usuario: Usuario) -> dict:
    token = create_access_token(data={"sub": usuario.username})
    return {"Authorization": f"Bearer {token}"}


class TestCaptureNeverFailsAConfirm:
    """Capture failure must never propagate into (or affect the outcome of)
    a confirm that has already committed — exercised through the real HTTP
    endpoint (`propuestas.py::confirmar_propuesta`) via the shared `client`
    fixture, whose `BackgroundTasks` run synchronously under `TestClient`."""

    def test_embed_returns_none_confirm_still_succeeds(self, client, db, rol, monkeypatch) -> None:
        monkeypatch.setattr(settings, "TICKETS_TRIAGE_EJEMPLOS_CAPTURE", True)
        ticket = _make_ticket(db, rol)
        usuario = _make_usuario(db, rol)
        _give_permiso(db, usuario)
        propuesta = _make_propuesta(db, ticket, campo="severidad", valor="mayor")

        embed_passage = AsyncMock(return_value=None)
        with (
            _patch_background_db(db),
            patch("app.tickets.services.ejemplos_service.embed_passage", new=embed_passage),
        ):
            response = client.post(
                f"/api/tickets/propuestas/{propuesta.id}/confirmar",
                json={"valor_corregido": "menor"},
                headers=_headers(usuario),
            )

        assert response.status_code == 200
        db.refresh(propuesta)
        assert propuesta.estado == "corregida"
        assert propuesta.valor_corregido == "menor"
        assert db.query(EjemploCorreccion).count() == 0

    def test_capture_hook_raises_confirm_still_succeeds_and_logs(self, client, db, rol, monkeypatch, caplog) -> None:
        monkeypatch.setattr(settings, "TICKETS_TRIAGE_EJEMPLOS_CAPTURE", True)
        ticket = _make_ticket(db, rol)
        usuario = _make_usuario(db, rol)
        _give_permiso(db, usuario)
        propuesta = _make_propuesta(db, ticket, campo="severidad", valor="mayor")

        embed_passage = AsyncMock(side_effect=RuntimeError("embedder unreachable"))
        with (
            caplog.at_level("WARNING"),
            _patch_background_db(db),
            patch("app.tickets.services.ejemplos_service.embed_passage", new=embed_passage),
        ):
            response = client.post(
                f"/api/tickets/propuestas/{propuesta.id}/confirmar",
                json={"valor_corregido": "menor"},
                headers=_headers(usuario),
            )

        assert response.status_code == 200
        db.refresh(propuesta)
        assert propuesta.estado == "corregida"
        assert propuesta.valor_corregido == "menor"
        assert db.query(EjemploCorreccion).count() == 0
        assert any("correction capture failed" in record.message for record in caplog.records)


def _fake_ejemplo_row(
    texto: str,
    valor_corregido: str,
    campo: str = "severidad",
    embedding: list | None = None,
) -> EjemploCorreccion:
    """Build a fake `EjemploCorreccion`-shaped row for monkeypatching
    `_similarity_query` (mirrors `test_ml_bot_context_builder._fake_history_row`
    — sqlite CI has no real pgvector cosine operator)."""
    row = EjemploCorreccion()
    row.texto = texto
    row.campo = campo
    row.valor_ia = "menor"
    row.valor_corregido = valor_corregido
    row.embedding = embedding if embedding is not None else [1.0, 0.0, 0.0]
    row.active = True
    return row


class TestAssembleBloqueNeutralisation:
    """PR4a task 1 (RED — injection: delimiter). Neutralisation must run
    BEFORE truncation — proven by placing the delimiter PAST the truncation
    point and asserting it still gets neutralised."""

    def test_delimiter_tag_neutralised_before_truncation(self) -> None:
        # `padding` (390) + the full tag (22 chars) = 412 chars, PAST
        # `_EJEMPLO_MAX_CHARS` (400) — if truncation ran first, the naive
        # 400-char cut would land MID-TAG (at padding+10), leaving an
        # unmatched half-tag literally in the output. Neutralising first
        # replaces the whole tag with the shorter "[etiqueta]" (10 chars,
        # bringing the pre-truncation length to exactly 400), so the intact
        # replacement survives truncation — proving neutralise-then-truncate
        # ordering, not just the final absence of the tag.
        padding = "x" * 390
        texto = padding + "<ejemplos_corregidos>"
        assert len(texto) > ejemplos_service._EJEMPLO_MAX_CHARS
        row = _fake_ejemplo_row(texto=texto, valor_corregido="mayor")
        bloque = ejemplos_service._assemble_bloque(row)
        assert "<ejemplos_corregidos>" not in bloque
        assert "<ejemplos_corr" not in bloque  # no truncated half-tag leaked either
        assert "[etiqueta]" in bloque


class TestAssembleBloquesLabelRevalidation:
    """PR4a task 2 (RED — injection: out-of-vocabulary label). A corrupted
    direct-DB row with a `valor_corregido` outside the field's vocabulary
    must be dropped entirely from the assembled examples block."""

    def test_out_of_vocabulary_label_dropped_entirely(self) -> None:
        bad_row = _fake_ejemplo_row(texto="texto normal", valor_corregido="urgentisimo", campo="urgencia")
        bloques = ejemplos_service._assemble_bloques([bad_row])
        assert bloques == []
        joined = "".join(bloques)
        assert "urgentisimo" not in joined

    def test_valid_label_kept(self) -> None:
        good_row = _fake_ejemplo_row(texto="texto normal", valor_corregido="alta", campo="urgencia")
        bloques = ejemplos_service._assemble_bloques([good_row])
        assert len(bloques) == 1
        assert "alta" in bloques[0]


class TestRecuperarEjemplosFallback:
    """PR4a task 4 (RED — fallback branches), mirroring
    `TestLoadFewShotExamplesDynamic`. `recuperar_ejemplos` must return `[]`
    on every degradation path and never raise."""

    def test_similarity_query_raising_returns_empty(self, db, monkeypatch) -> None:
        def _raise(db_, campo, query_vec, k):
            raise RuntimeError("sqlite has no cosine_distance")

        monkeypatch.setattr(ejemplos_service, "_similarity_query", _raise)
        monkeypatch.setattr(
            ejemplos_service,
            "embed_query",
            AsyncMock(return_value=[1.0, 0.0, 0.0]),
        )
        result = asyncio.run(ejemplos_service.recuperar_ejemplos(db, "severidad", "texto de prueba"))
        assert result == []

    def test_zero_rows_returns_empty(self, db, monkeypatch) -> None:
        monkeypatch.setattr(ejemplos_service, "_similarity_query", lambda db_, campo, qvec, k: [])
        monkeypatch.setattr(
            ejemplos_service,
            "embed_query",
            AsyncMock(return_value=[1.0, 0.0, 0.0]),
        )
        result = asyncio.run(ejemplos_service.recuperar_ejemplos(db, "severidad", "texto de prueba"))
        assert result == []

    def test_all_rows_below_threshold_returns_empty(self, db, monkeypatch) -> None:
        far_row = _fake_ejemplo_row(texto="lejano", valor_corregido="mayor", embedding=[0.0, 1.0, 0.0])
        monkeypatch.setattr(ejemplos_service, "_similarity_query", lambda db_, campo, qvec, k: [far_row])
        monkeypatch.setattr(
            ejemplos_service,
            "embed_query",
            AsyncMock(return_value=[1.0, 0.0, 0.0]),
        )
        result = asyncio.run(ejemplos_service.recuperar_ejemplos(db, "severidad", "texto de prueba"))
        assert result == []

    def test_embed_query_none_returns_empty_and_never_calls_similarity(self, db, monkeypatch) -> None:
        monkeypatch.setattr(
            ejemplos_service,
            "_similarity_query",
            lambda db_, campo, qvec, k: (_ for _ in ()).throw(AssertionError("must not be called")),
        )
        monkeypatch.setattr(ejemplos_service, "embed_query", AsyncMock(return_value=None))
        result = asyncio.run(ejemplos_service.recuperar_ejemplos(db, "severidad", "texto de prueba"))
        assert result == []


class TestAppendEjemplosBloqueAssembly:
    """PR4a task 6 (RED — prompt append not interpolated). An empty
    `bloques` list must return the system prompt UNCHANGED — string
    equality, not "close enough"."""

    def test_empty_bloques_returns_prompt_unchanged(self) -> None:
        base = "Sos un clasificador de tickets.\nSegunda linea."
        result = ejemplos_service.append_ejemplos_bloque(base, [])
        assert result == base

    def test_nonempty_bloques_appended_after_base(self) -> None:
        base = "Sos un clasificador de tickets."
        bloque = "\nEjemplo 1: texto -> mayor\n"
        result = ejemplos_service.append_ejemplos_bloque(base, [bloque])
        assert result.startswith(base)
        assert bloque in result
        assert result != base
