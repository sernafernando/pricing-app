"""Tests for the PR5a curation endpoints (tickets-triage-feedback):
`GET /tickets/triage/ejemplos` (list, filtered by `campo`, paginated) and
`PATCH /tickets/triage/ejemplos/{id}` (toggle `active`).

Both endpoints require `tickets.triage.ejemplos` — deliberately INDEPENDENT
from `tickets.triage.confirmar` (a curator reviewing few-shot examples is a
narrower judgment than confirming AI proposals; a user holding one must not
get the other for free).

Covers:
- 403 on both endpoints for a user holding only `tickets.triage.confirmar`
  (proves the two permissions are independent, not aliased).
- List filtered by `campo`, paginated.
- Toggle `active=false` and the VERY NEXT retrieval call
  (`ejemplos_service._similarity_query`) excludes it — no caching, no
  delayed propagation.
- `EjemploResponse` serialized JSON shape from the real endpoint: declares
  every field the future curation UI needs, and never exposes `embedding`.

Written FIRST (RED phase) per strict TDD.

Run:
    cd backend && source venv/bin/activate
    pytest tests/tickets/test_ejemplos_curation.py -v
"""

from __future__ import annotations

from app.core.security import create_access_token, get_password_hash
from app.models.permiso import Permiso, UsuarioPermisoOverride
from app.models.usuario import AuthProvider, RolUsuario, Usuario
from app.tickets.models.ejemplo_correccion import EjemploCorreccion, EMBEDDING_DIM
from app.tickets.services import ejemplos_service

LIST_ENDPOINT = "/api/tickets/tickets/triage/ejemplos"
TOGGLE_ENDPOINT = "/api/tickets/tickets/triage/ejemplos/{id}"
_seq = [0]


def _make_usuario(db, rol) -> Usuario:
    _seq[0] += 1
    usuario = Usuario(
        username=f"ejemplos_curador_{_seq[0]}",
        email=f"ejemplos_curador_{_seq[0]}@test.com",
        nombre="Curador Ejemplos",
        password_hash=get_password_hash("pass"),
        rol=RolUsuario.VENTAS,
        rol_id=rol.id,
        auth_provider=AuthProvider.LOCAL,
        activo=True,
    )
    db.add(usuario)
    db.flush()
    return usuario


def _give_permiso(db, user: Usuario, codigo: str) -> None:
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


def _make_ejemplo(db, campo: str, texto: str, active: bool = True) -> EjemploCorreccion:
    _seq[0] += 1
    from app.tickets.models.propuesta_ia import PropuestaIA
    from app.tickets.models.sector import Sector
    from app.tickets.models.ticket import PrioridadTicket, Ticket
    from app.tickets.models.tipo_ticket import TipoTicket
    from app.tickets.models.workflow import EstadoTicket, Workflow

    sector = Sector(codigo=f"EJ_CUR_SECT_{_seq[0]}", nombre="Sector Ejemplos", activo=True, configuracion={})
    db.add(sector)
    db.flush()
    workflow = Workflow(sector_id=sector.id, nombre="WF Ejemplos", es_default=True, activo=True)
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
    creador = Usuario(
        username=f"ej_cur_creador_{_seq[0]}",
        email=f"ej_cur_creador_{_seq[0]}@test.com",
        nombre="Creador Ejemplos",
        password_hash=get_password_hash("pass"),
        rol=RolUsuario.VENTAS,
        rol_id=1,
        auth_provider=AuthProvider.LOCAL,
        activo=True,
    )
    db.add(creador)
    db.flush()
    ticket = Ticket(
        titulo="Ticket para ejemplos de curación",
        prioridad=PrioridadTicket.MEDIA,
        sector_id=sector.id,
        tipo_ticket_id=tipo.id,
        estado_id=estado.id,
        creador_id=creador.id,
        campos_metadata={},
    )
    db.add(ticket)
    db.flush()
    propuesta = PropuestaIA(
        ticket_id=ticket.id,
        campo=campo,
        valor_propuesto={"valor": "mayor"},
        confianza=0.9,
        estado="corregida",
        valor_corregido="menor",
    )
    db.add(propuesta)
    db.flush()
    ejemplo = EjemploCorreccion(
        ticket_id=ticket.id,
        propuesta_id=propuesta.id,
        campo=campo,
        texto=texto,
        valor_ia="mayor",
        valor_corregido="menor",
        embedding=[0.1] * EMBEDDING_DIM,
        active=active,
    )
    db.add(ejemplo)
    db.flush()
    return ejemplo


class TestPermisoIndependiente:
    def test_list_requires_tickets_triage_ejemplos_not_confirmar(self, client, db, rol_ventas):
        usuario = _make_usuario(db, rol_ventas)
        _give_permiso(db, usuario, "tickets.triage.confirmar")

        resp = client.get(LIST_ENDPOINT, headers=_headers(usuario))

        assert resp.status_code == 403

    def test_toggle_requires_tickets_triage_ejemplos_not_confirmar(self, db, rol_ventas, client):
        usuario = _make_usuario(db, rol_ventas)
        _give_permiso(db, usuario, "tickets.triage.confirmar")
        ejemplo = _make_ejemplo(db, "severidad", "texto original")

        resp = client.patch(TOGGLE_ENDPOINT.format(id=ejemplo.id), json={"active": False}, headers=_headers(usuario))

        assert resp.status_code == 403


class TestListado:
    def test_filters_by_campo_and_paginates(self, client, db, rol_ventas):
        usuario = _make_usuario(db, rol_ventas)
        _give_permiso(db, usuario, "tickets.triage.ejemplos")
        sev1 = _make_ejemplo(db, "severidad", "sev uno")
        _make_ejemplo(db, "severidad", "sev dos")
        _make_ejemplo(db, "urgencia", "urg uno")

        resp = client.get(LIST_ENDPOINT, params={"campo": "severidad", "limit": 1}, headers=_headers(usuario))

        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 1
        assert body[0]["campo"] == "severidad"
        assert body[0]["id"] == sev1.id

    def test_limit_over_the_cap_is_rejected_not_silently_clamped(self, client, db, rol_ventas):
        """The 200-row cap must REJECT (422), never quietly serve a smaller
        page as if the request had been honoured — a caller asking for 500
        has to learn it cannot have them."""
        usuario = _make_usuario(db, rol_ventas)
        _give_permiso(db, usuario, "tickets.triage.ejemplos")

        resp = client.get(LIST_ENDPOINT, params={"limit": 201}, headers=_headers(usuario))

        assert resp.status_code == 422

    def test_limit_at_the_cap_is_allowed(self, client, db, rol_ventas):
        """Guards the boundary from the other side: 200 is inclusive, so a
        later tightening to `lt=200` cannot pass unnoticed."""
        usuario = _make_usuario(db, rol_ventas)
        _give_permiso(db, usuario, "tickets.triage.ejemplos")

        resp = client.get(LIST_ENDPOINT, params={"limit": 200}, headers=_headers(usuario))

        assert resp.status_code == 200


def _similarity_query_without_pgvector_order(db, campo, query_embedding, k):
    """Mirrors `_similarity_query`'s exact `active`/`campo` filter (the part
    under test here) WITHOUT the `cosine_distance` ORDER BY, which sqlite's
    test DB has no operator for (module docstring "Retrieval CI note") —
    same monkeypatch-isolation pattern `test_ejemplos_service.py` already
    uses for this function."""
    return (
        db.query(EjemploCorreccion)
        .filter(EjemploCorreccion.active.is_(True), EjemploCorreccion.campo == campo)
        .limit(k)
        .all()
    )


class TestToggle:
    def test_toggle_active_false_excludes_from_next_retrieval(self, client, db, rol_ventas, monkeypatch):
        monkeypatch.setattr(ejemplos_service, "_similarity_query", _similarity_query_without_pgvector_order)
        usuario = _make_usuario(db, rol_ventas)
        _give_permiso(db, usuario, "tickets.triage.ejemplos")
        ejemplo = _make_ejemplo(db, "severidad", "texto a desactivar")

        rows_before = ejemplos_service._similarity_query(db, "severidad", [0.1] * 384, 10)
        assert ejemplo.id in [row.id for row in rows_before]

        resp = client.patch(TOGGLE_ENDPOINT.format(id=ejemplo.id), json={"active": False}, headers=_headers(usuario))
        assert resp.status_code == 200
        assert resp.json()["active"] is False

        rows_after = ejemplos_service._similarity_query(db, "severidad", [0.1] * 384, 10)
        assert ejemplo.id not in [row.id for row in rows_after]

    def test_toggle_unknown_id_returns_404(self, client, db, rol_ventas):
        usuario = _make_usuario(db, rol_ventas)
        _give_permiso(db, usuario, "tickets.triage.ejemplos")

        resp = client.patch(TOGGLE_ENDPOINT.format(id=999999), json={"active": False}, headers=_headers(usuario))

        assert resp.status_code == 404


class TestEjemploResponseShape:
    def test_serialized_shape_excludes_embedding(self, client, db, rol_ventas):
        usuario = _make_usuario(db, rol_ventas)
        _give_permiso(db, usuario, "tickets.triage.ejemplos")
        ejemplo = _make_ejemplo(db, "severidad", "texto shape")

        resp = client.get(LIST_ENDPOINT, headers=_headers(usuario))

        assert resp.status_code == 200
        body = resp.json()
        row = next(r for r in body if r["id"] == ejemplo.id)
        assert row["campo"] == "severidad"
        assert row["texto"] == "texto shape"
        assert row["valor_ia"] == "mayor"
        assert row["valor_corregido"] == "menor"
        assert row["active"] is True
        assert "created_at" in row
        assert "embedding" not in row
