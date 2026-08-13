"""Tests for GET /tickets/board (tickets-ai-triage PR 5a).

Two board queries regardless of column count: one GROUP BY for per-column
totals, one ROW_NUMBER() OVER (PARTITION BY <group> ORDER BY <rank>) capped
at items_por_columna for items. `_rank_case()` builds an explicit rank for
severidad/urgencia (VARCHAR columns) since a plain ORDER BY sorts them
alphabetically — wrong order.

Written FIRST (RED phase) per strict TDD.

Run:
    cd backend && source venv/bin/activate
    pytest tests/tickets/test_board_endpoint.py -v
"""

import re

from app.core.security import create_access_token, get_password_hash
from app.models.permiso import Permiso, UsuarioPermisoOverride
from app.models.usuario import AuthProvider, RolUsuario, Usuario
from app.tickets.api.endpoints.tickets import SEVERIDAD_VOCAB, URGENCIA_VOCAB, _rank_case
from app.tickets.models.propuesta_ia import PropuestaIA
from app.tickets.models.sector import Sector
from app.tickets.models.ticket import PrioridadTicket, Ticket
from app.tickets.models.tipo_ticket import TipoTicket
from app.tickets.models.workflow import EstadoTicket, Workflow

BOARD_ENDPOINT = "/api/tickets/tickets/board"
INBOX_SECTOR_CODIGO = "INBOX"
_seq = [0]


def _make_workflow(db, *, n_estados: int = 3):
    """Seeds a sector + workflow with `n_estados` states (orden 1..n)."""
    _seq[0] += 1
    sector = Sector(codigo=f"BOARD_SECT_{_seq[0]}", nombre="Sector Tablero", activo=True, configuracion={})
    db.add(sector)
    db.flush()
    workflow = Workflow(sector_id=sector.id, nombre="WF Tablero", es_default=True, activo=True)
    db.add(workflow)
    db.flush()
    estados = []
    for i in range(1, n_estados + 1):
        estado = EstadoTicket(
            workflow_id=workflow.id,
            codigo=f"estado_{i}",
            nombre=f"Estado {i}",
            orden=i,
            color=f"#00000{i}",
            es_inicial=(i == 1),
            es_final=(i == n_estados),
        )
        db.add(estado)
        db.flush()
        estados.append(estado)
    tipo = TipoTicket(sector_id=sector.id, codigo="consulta", nombre="Consulta", workflow_id=workflow.id)
    db.add(tipo)
    db.flush()
    creador = Usuario(
        username=f"board_creador_{_seq[0]}",
        email=f"board_creador_{_seq[0]}@test.com",
        nombre="Creador Tablero",
        password_hash=get_password_hash("pass"),
        rol=RolUsuario.VENTAS,
        rol_id=None,
        auth_provider=AuthProvider.LOCAL,
        activo=True,
    )
    db.add(creador)
    db.flush()
    return sector, workflow, estados, tipo, creador


def _make_inbox_sector(db):
    """Mirrors production's real Inbox pair (Sector INBOX / workflow
    "Bandeja de entrada" with Nuevo→Cerrado) in the SAME shape
    `_make_workflow` returns, so `_make_ticket` works unmodified."""
    _seq[0] += 1
    sector = Sector(codigo=INBOX_SECTOR_CODIGO, nombre="Bandeja de entrada", activo=True, configuracion={})
    db.add(sector)
    db.flush()
    workflow = Workflow(sector_id=sector.id, nombre="Bandeja de entrada", es_default=True, activo=True)
    db.add(workflow)
    db.flush()
    nuevo = EstadoTicket(workflow_id=workflow.id, codigo="nuevo", nombre="Nuevo", orden=1, es_inicial=True)
    cerrado = EstadoTicket(workflow_id=workflow.id, codigo="cerrado", nombre="Cerrado", orden=2, es_final=True)
    db.add_all([nuevo, cerrado])
    db.flush()
    tipo = TipoTicket(sector_id=sector.id, codigo="SIN_CLASIFICAR", nombre="Sin clasificar", workflow_id=workflow.id)
    db.add(tipo)
    db.flush()
    creador = Usuario(
        username=f"board_inbox_creador_{_seq[0]}",
        email=f"board_inbox_creador_{_seq[0]}@test.com",
        nombre="Creador Inbox",
        password_hash=get_password_hash("pass"),
        rol=RolUsuario.VENTAS,
        rol_id=None,
        auth_provider=AuthProvider.LOCAL,
        activo=True,
    )
    db.add(creador)
    db.flush()
    return sector, workflow, [nuevo, cerrado], tipo, creador


def _make_ticket(db, sector, tipo, estado, creador, *, urgencia=None, severidad=None, titulo=None):
    _seq[0] += 1
    ticket = Ticket(
        titulo=titulo or f"Ticket tablero {_seq[0]}",
        prioridad=PrioridadTicket.MEDIA,
        sector_id=sector.id,
        tipo_ticket_id=tipo.id,
        estado_id=estado.id,
        creador_id=creador.id,
        campos_metadata={},
        urgencia=urgencia,
        severidad=severidad,
    )
    db.add(ticket)
    db.flush()
    return ticket


def _make_admin(db) -> Usuario:
    """A `tickets.admin` user — sees every ticket, no sector scoping needed."""
    _seq[0] += 1
    usuario = Usuario(
        username=f"board_admin_{_seq[0]}",
        email=f"board_admin_{_seq[0]}@test.com",
        nombre="Admin Tablero",
        password_hash=get_password_hash("pass"),
        rol=RolUsuario.VENTAS,
        rol_id=None,
        auth_provider=AuthProvider.LOCAL,
        activo=True,
    )
    db.add(usuario)
    db.flush()
    permiso = db.query(Permiso).filter(Permiso.codigo == "tickets.admin").first()
    if not permiso:
        permiso = Permiso(codigo="tickets.admin", nombre="tickets.admin", categoria="tickets")
        db.add(permiso)
        db.flush()
    db.add(UsuarioPermisoOverride(usuario_id=usuario.id, permiso_id=permiso.id, concedido=True))
    db.flush()
    return usuario


def _make_usuario_ver_sin_sector(db) -> Usuario:
    """`tickets.ver` but NO `SectorUsuario` membership and no
    `tickets.admin` — sees tickets in sectors they belong to (none) plus
    what they created. Used to prove the default-sector fallback does not
    leak a foreign sector's workflow structure to a non-admin viewer."""
    _seq[0] += 1
    usuario = Usuario(
        username=f"board_ver_sin_sector_{_seq[0]}",
        email=f"board_ver_sin_sector_{_seq[0]}@test.com",
        nombre="Ver Sin Sector",
        password_hash=get_password_hash("pass"),
        rol=RolUsuario.VENTAS,
        rol_id=None,
        auth_provider=AuthProvider.LOCAL,
        activo=True,
    )
    db.add(usuario)
    db.flush()
    permiso = db.query(Permiso).filter(Permiso.codigo == "tickets.ver").first()
    if not permiso:
        permiso = Permiso(codigo="tickets.ver", nombre="tickets.ver", categoria="tickets")
        db.add(permiso)
        db.flush()
    db.add(UsuarioPermisoOverride(usuario_id=usuario.id, permiso_id=permiso.id, concedido=True))
    db.flush()
    return usuario


def _headers(user: Usuario) -> dict:
    token = create_access_token(data={"sub": user.username})
    return {"Authorization": f"Bearer {token}"}


class TestRankCaseIsNotAlphabetical:
    """Pure-function unit test — no DB, no client, no fixtures beyond the
    plain SQLAlchemy expression compiler."""

    @staticmethod
    def _ranks(expr, vocabulario: list[str]) -> dict[str, int]:
        sql = str(expr.compile(compile_kwargs={"literal_binds": True}))
        ranks = {}
        for valor in vocabulario:
            match = re.search(rf"= '{valor}'\) THEN (-?\d+)", sql)
            assert match, f"'{valor}' rank not found in compiled CASE: {sql}"
            ranks[valor] = int(match.group(1))
        return ranks

    def test_severidad_descending_is_critica_mayor_menor_trivial_not_alphabetical(self):
        ranks = self._ranks(_rank_case(Ticket.severidad, SEVERIDAD_VOCAB), SEVERIDAD_VOCAB)

        descendente = sorted(SEVERIDAD_VOCAB, key=lambda v: ranks[v], reverse=True)

        assert descendente == ["critica", "mayor", "menor", "trivial"]
        # This is the bug the rank exists to prevent: a plain alphabetical
        # DESC sort produces a DIFFERENT (wrong) order for this vocabulary.
        assert descendente != sorted(SEVERIDAD_VOCAB, reverse=True)
        assert sorted(SEVERIDAD_VOCAB, reverse=True) == ["trivial", "menor", "mayor", "critica"]

    def test_urgencia_ascending_is_baja_normal_alta_inmediata(self):
        ranks = self._ranks(_rank_case(Ticket.urgencia, URGENCIA_VOCAB), URGENCIA_VOCAB)

        ascendente = sorted(URGENCIA_VOCAB, key=lambda v: ranks[v])

        assert ascendente == ["baja", "normal", "alta", "inmediata"]
        assert ascendente == sorted(URGENCIA_VOCAB, key=lambda v: ranks[v])  # deterministic, re-derived


class TestBoardGroupedByEstado:
    def test_one_column_per_estado_with_matching_totals_and_capped_items(self, client, db):
        sector, workflow, estados, tipo, creador = _make_workflow(db, n_estados=3)
        admin = _make_admin(db)

        # 3 tickets in estado[0], 1 in estado[1], 0 in estado[2].
        for _ in range(3):
            _make_ticket(db, sector, tipo, estados[0], creador)
        _make_ticket(db, sector, tipo, estados[1], creador)
        db.commit()

        resp = client.get(
            BOARD_ENDPOINT, params={"agrupacion": "estado", "items_por_columna": 2}, headers=_headers(admin)
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["agrupacion"] == "estado"
        claves = {c["clave"]: c for c in body["columnas"]}
        assert {str(e.id) for e in estados} <= set(claves.keys())

        col0 = claves[str(estados[0].id)]
        assert col0["total"] == 3
        assert len(col0["items"]) == 2  # capped at items_por_columna

        col1 = claves[str(estados[1].id)]
        assert col1["total"] == 1
        assert len(col1["items"]) == 1

        col2 = claves[str(estados[2].id)]
        assert col2["total"] == 0
        assert col2["items"] == []

    def test_card_shape_carries_provenance_and_pending_proposal_count(self, client, db):
        sector, workflow, estados, tipo, creador = _make_workflow(db, n_estados=1)
        admin = _make_admin(db)
        ticket = _make_ticket(
            db, sector, tipo, estados[0], creador, urgencia="alta", severidad="critica", titulo="Falla facturación"
        )
        ticket.severidad_origen = "ia_confirmada"
        ticket.urgencia_origen = "humano"
        ticket.resumen = "No puede facturar"
        db.add(PropuestaIA(ticket_id=ticket.id, campo="titulo", valor_propuesto={"valor": "x"}, estado="pendiente"))
        # Human-confirmed (`confirmado_por_id` set) — a decision a person
        # already ratified, excluded from the badge just like from
        # GET /tickets/{id}/propuestas (feat/tickets-triage-aplicar-directo:
        # an UNREVIEWED ia_auto row — confirmado_por_id NULL — DOES count,
        # see the sibling test below).
        db.add(
            PropuestaIA(
                ticket_id=ticket.id,
                campo="severidad",
                valor_propuesto={"valor": "critica"},
                estado="confirmada",
                confirmado_por_id=admin.id,
            )
        )
        db.commit()

        resp = client.get(BOARD_ENDPOINT, params={"agrupacion": "estado"}, headers=_headers(admin))

        assert resp.status_code == 200
        columnas = {c["clave"]: c for c in resp.json()["columnas"]}
        card = columnas[str(estados[0].id)]["items"][0]
        assert card["id"] == ticket.id
        assert card["titulo"] == "Falla facturación"
        assert card["resumen"] == "No puede facturar"
        assert card["severidad"] == "critica"
        assert card["urgencia"] == "alta"
        assert card["severidad_origen"] == "ia_confirmada"
        assert card["urgencia_origen"] == "humano"
        assert card["estado"]["id"] == estados[0].id
        assert card["sector"]["id"] == sector.id
        assert card["propuestas_pendientes"] == 1  # only the 'titulo' proposal is pendiente

    def test_propuestas_pendientes_counts_unreviewed_ia_auto_alongside_pendiente(self, client, db):
        """feat/tickets-triage-aplicar-directo: a `confirmada` proposal with
        `confirmado_por_id IS NULL` is the AI having already applied it —
        still a human's job to review, so it must count toward this badge
        the same way `GET /tickets/{id}/propuestas` lists it. Without this,
        the badge reads 0 exactly when there IS something to review."""
        sector, workflow, estados, tipo, creador = _make_workflow(db, n_estados=1)
        admin = _make_admin(db)
        ticket = _make_ticket(db, sector, tipo, estados[0], creador, titulo="Ticket auto-clasificado")
        db.add(PropuestaIA(ticket_id=ticket.id, campo="titulo", valor_propuesto={"valor": "x"}, estado="pendiente"))
        db.add(
            PropuestaIA(
                ticket_id=ticket.id,
                campo="severidad",
                valor_propuesto={"valor": "critica"},
                estado="confirmada",
                confirmado_por_id=None,
            )
        )
        db.commit()

        resp = client.get(BOARD_ENDPOINT, params={"agrupacion": "estado"}, headers=_headers(admin))

        assert resp.status_code == 200
        columnas = {c["clave"]: c for c in resp.json()["columnas"]}
        card = columnas[str(estados[0].id)]["items"][0]
        assert card["propuestas_pendientes"] == 2


class TestBoardScopedToOneWorkflow:
    """fix/tickets-board-scope-y-legacy — the estado board must scope to
    ONE workflow (selected by sector), with the Inbox column always
    prepended, always separate from that scope."""

    def test_two_workflows_with_same_named_estado_produce_one_column_not_two(self, client, db):
        """Production shape: workflow 'Soporte' (sector sistema) and
        workflow 'Bandeja de entrada' (INBOX) each own a 'Cerrado' state
        (#5 with 11 tickets, #9 with 1). The OLD board rendered BOTH as
        separate, interleaved columns. Scoped to sector_a, only sector_a's
        'Cerrado' appears — sector_b's is not on the board at all."""
        sector_a, _, estados_a, tipo_a, creador_a = _make_workflow(db, n_estados=2)
        estados_a[-1].nombre = "Cerrado"
        sector_b, _, estados_b, tipo_b, creador_b = _make_workflow(db, n_estados=2)
        estados_b[-1].nombre = "Cerrado"
        admin = _make_admin(db)

        for _ in range(3):
            _make_ticket(db, sector_a, tipo_a, estados_a[-1], creador_a)
        _make_ticket(db, sector_b, tipo_b, estados_b[-1], creador_b)
        db.commit()

        resp = client.get(
            BOARD_ENDPOINT, params={"agrupacion": "estado", "sector_id": sector_a.id}, headers=_headers(admin)
        )

        assert resp.status_code == 200
        columnas = resp.json()["columnas"]
        cerrado_columnas = [c for c in columnas if c["etiqueta"] == "Cerrado"]
        assert len(cerrado_columnas) == 1
        assert cerrado_columnas[0]["clave"] == str(estados_a[-1].id)
        assert cerrado_columnas[0]["total"] == 3  # only sector_a's tickets
        assert str(estados_b[-1].id) not in {c["clave"] for c in columnas}

    def test_column_order_is_inbox_first_then_selected_workflow_orden(self, client, db):
        inbox_sector, _, inbox_estados, inbox_tipo, inbox_creador = _make_inbox_sector(db)
        sector, _, estados, tipo, creador = _make_workflow(db, n_estados=3)
        admin = _make_admin(db)
        _make_ticket(db, inbox_sector, inbox_tipo, inbox_estados[0], inbox_creador)
        db.commit()

        resp = client.get(
            BOARD_ENDPOINT, params={"agrupacion": "estado", "sector_id": sector.id}, headers=_headers(admin)
        )

        assert resp.status_code == 200
        claves = [c["clave"] for c in resp.json()["columnas"]]
        assert claves == ["inbox", str(estados[0].id), str(estados[1].id), str(estados[2].id)]

    def test_inbox_column_always_shown_and_counts_regardless_of_own_estado(self, client, db):
        inbox_sector, _, inbox_estados, inbox_tipo, inbox_creador = _make_inbox_sector(db)
        sector, _, estados, tipo, creador = _make_workflow(db, n_estados=1)
        admin = _make_admin(db)
        _make_ticket(db, inbox_sector, inbox_tipo, inbox_estados[0], inbox_creador)  # Nuevo
        _make_ticket(db, inbox_sector, inbox_tipo, inbox_estados[1], inbox_creador)  # Cerrado
        db.commit()

        resp = client.get(
            BOARD_ENDPOINT, params={"agrupacion": "estado", "sector_id": sector.id}, headers=_headers(admin)
        )

        assert resp.status_code == 200
        columnas = {c["clave"]: c for c in resp.json()["columnas"]}
        assert columnas["inbox"]["total"] == 2  # both Inbox tickets, across both its own estados
        assert columnas["inbox"]["sector_id"] == inbox_sector.id

    def test_non_admin_with_no_sector_membership_gets_only_inbox_not_a_foreign_sector(self, client, db):
        """Real pre-push review finding: the default-sector fallback was
        "first active non-Inbox sector system-wide" for EVERYONE with no
        membership, which leaked a foreign sector's workflow structure
        (state names/colors) to a non-admin viewer who cannot see any of
        its tickets. Only `tickets.admin` gets that global fallback."""
        sector, _, estados, tipo, creador = _make_workflow(db, n_estados=2)
        viewer = _make_usuario_ver_sin_sector(db)
        db.commit()

        resp = client.get(BOARD_ENDPOINT, params={"agrupacion": "estado"}, headers=_headers(viewer))

        assert resp.status_code == 200
        claves = {c["clave"] for c in resp.json()["columnas"]}
        assert claves == {"inbox"}  # never the foreign sector's own states

    def test_explicit_sector_id_the_viewer_cannot_access_is_rejected(self, client, db):
        """Real pre-push review finding: `_default_sector_id_para_board`'s
        access check only guarded the DEFAULT path — a non-admin viewer
        could still request an explicit `sector_id` for a sector they
        have no membership in and read its workflow structure anyway."""
        sector, _, estados, tipo, creador = _make_workflow(db, n_estados=2)
        viewer = _make_usuario_ver_sin_sector(db)
        db.commit()

        resp = client.get(
            BOARD_ENDPOINT, params={"agrupacion": "estado", "sector_id": sector.id}, headers=_headers(viewer)
        )

        assert resp.status_code == 403

    def test_explicit_inbox_sector_id_is_rejected(self, client, db):
        inbox_sector, _, _, _, _ = _make_inbox_sector(db)
        admin = _make_admin(db)
        db.commit()

        resp = client.get(
            BOARD_ENDPOINT,
            params={"agrupacion": "estado", "sector_id": inbox_sector.id},
            headers=_headers(admin),
        )

        assert resp.status_code == 400


class TestBoardGroupedByUrgencia:
    def test_four_values_plus_sin_clasificar_with_correct_totals(self, client, db):
        sector, workflow, estados, tipo, creador = _make_workflow(db, n_estados=1)
        admin = _make_admin(db)

        _make_ticket(db, sector, tipo, estados[0], creador, urgencia="alta")
        _make_ticket(db, sector, tipo, estados[0], creador, urgencia="alta")
        _make_ticket(db, sector, tipo, estados[0], creador, urgencia="baja")
        _make_ticket(db, sector, tipo, estados[0], creador, urgencia=None)
        db.commit()

        resp = client.get(BOARD_ENDPOINT, params={"agrupacion": "urgencia"}, headers=_headers(admin))

        assert resp.status_code == 200
        body = resp.json()
        claves = {c["clave"]: c for c in body["columnas"]}
        assert set(claves.keys()) == {"baja", "normal", "alta", "inmediata", "sin_clasificar"}

        assert claves["alta"]["total"] == 2
        assert claves["baja"]["total"] == 1
        assert claves["normal"]["total"] == 0
        assert claves["inmediata"]["total"] == 0
        assert claves["sin_clasificar"]["total"] == 1
        assert claves["sin_clasificar"]["etiqueta"] == "Sin clasificar"


class TestBoardOverflowHasNoOwnPagination:
    def test_board_response_exposes_no_pagination_metadata_beyond_total(self, client, db):
        sector, workflow, estados, tipo, creador = _make_workflow(db, n_estados=1)
        admin = _make_admin(db)
        for _ in range(5):
            _make_ticket(db, sector, tipo, estados[0], creador)
        db.commit()

        resp = client.get(
            BOARD_ENDPOINT, params={"agrupacion": "estado", "items_por_columna": 2}, headers=_headers(admin)
        )

        assert resp.status_code == 200
        columnas = {c["clave"]: c for c in resp.json()["columnas"]}
        columna = columnas[str(estados[0].id)]
        assert columna["total"] == 5
        assert len(columna["items"]) == 2
        # No page/page_size/pages/next_page/has_more — the ONLY count metadata
        # is `total`. A "load more" client goes through GET /tickets instead.
        pagination_keys = {"page", "page_size", "pages", "next_page", "has_more", "offset"}
        assert pagination_keys.isdisjoint(columna.keys())
        assert pagination_keys.isdisjoint(resp.json().keys())


class TestBoardUnknownOrderByRejected:
    def test_unknown_order_by_value_returns_422_not_500(self, client, db):
        sector, workflow, estados, tipo, creador = _make_workflow(db, n_estados=1)
        admin = _make_admin(db)
        _make_ticket(db, sector, tipo, estados[0], creador)
        db.commit()

        resp = client.get(
            "/api/tickets/tickets", params={"order_by": "'; DROP TABLE tickets;--"}, headers=_headers(admin)
        )

        assert resp.status_code == 422

    def test_unknown_order_dir_value_returns_422(self, client, db):
        sector, workflow, estados, tipo, creador = _make_workflow(db, n_estados=1)
        admin = _make_admin(db)
        _make_ticket(db, sector, tipo, estados[0], creador)
        db.commit()

        resp = client.get("/api/tickets/tickets", params={"order_dir": "sideways"}, headers=_headers(admin))

        assert resp.status_code == 422

    def test_severidad_order_by_uses_explicit_rank_not_alphabetical(self, client, db):
        sector, workflow, estados, tipo, creador = _make_workflow(db, n_estados=1)
        admin = _make_admin(db)
        for valor in ["trivial", "critica", "menor", "mayor"]:
            _make_ticket(db, sector, tipo, estados[0], creador, severidad=valor, titulo=f"Ticket {valor}")
        db.commit()

        resp = client.get(
            "/api/tickets/tickets",
            params={"order_by": "severidad", "order_dir": "desc", "sector_id": sector.id, "page_size": 10},
            headers=_headers(admin),
        )

        assert resp.status_code == 200
        severidades = [item["titulo"] for item in resp.json()["items"]]
        assert severidades == ["Ticket critica", "Ticket mayor", "Ticket menor", "Ticket trivial"]


class TestListTicketsUrgenciaFilter:
    """`GET /tickets`'s `urgencia` filter — added in PR 5b so the board's
    "load more" (which reuses this endpoint, per design's single-pagination
    rule) can request a matching filter for an urgencia-grouped column."""

    def test_filters_to_matching_urgencia_only(self, client, db):
        sector, workflow, estados, tipo, creador = _make_workflow(db, n_estados=1)
        admin = _make_admin(db)
        _make_ticket(db, sector, tipo, estados[0], creador, urgencia="alta", titulo="Alta 1")
        _make_ticket(db, sector, tipo, estados[0], creador, urgencia="alta", titulo="Alta 2")
        _make_ticket(db, sector, tipo, estados[0], creador, urgencia="baja", titulo="Baja 1")
        db.commit()

        resp = client.get("/api/tickets/tickets", params={"urgencia": "alta"}, headers=_headers(admin))

        assert resp.status_code == 200
        titulos = {item["titulo"] for item in resp.json()["items"]}
        assert titulos == {"Alta 1", "Alta 2"}

    def test_sin_clasificar_matches_null_urgencia(self, client, db):
        sector, workflow, estados, tipo, creador = _make_workflow(db, n_estados=1)
        admin = _make_admin(db)
        _make_ticket(db, sector, tipo, estados[0], creador, urgencia=None, titulo="Sin urgencia")
        _make_ticket(db, sector, tipo, estados[0], creador, urgencia="baja", titulo="Con urgencia")
        db.commit()

        resp = client.get("/api/tickets/tickets", params={"urgencia": "sin_clasificar"}, headers=_headers(admin))

        assert resp.status_code == 200
        titulos = [item["titulo"] for item in resp.json()["items"]]
        assert titulos == ["Sin urgencia"]

    def test_unknown_urgencia_value_returns_422_not_500(self, client, db):
        admin = _make_admin(db)

        resp = client.get(
            "/api/tickets/tickets", params={"urgencia": "'; DROP TABLE tickets;--"}, headers=_headers(admin)
        )

        assert resp.status_code == 422


class TestTicketListResponseCarriesTriageFields:
    """`TicketListResponse` (GET /tickets) — gap found in PR 5b: TicketCard
    needs severidad/urgencia/resumen/provenance to render the same for a
    "load more" item as it does for a board item, and these were only ever
    serialized on `TicketResponse` (single-ticket detail, PR 4c)."""

    def test_severity_urgency_provenance_and_resumen_are_serialized(self, client, db):
        sector, workflow, estados, tipo, creador = _make_workflow(db, n_estados=1)
        admin = _make_admin(db)
        ticket = _make_ticket(
            db, sector, tipo, estados[0], creador, urgencia="alta", severidad="critica", titulo="Falla facturación"
        )
        ticket.severidad_origen = "ia_confirmada"
        ticket.urgencia_origen = "humano"
        ticket.resumen = "No puede facturar"
        db.commit()

        resp = client.get("/api/tickets/tickets", headers=_headers(admin))

        assert resp.status_code == 200
        item = next(i for i in resp.json()["items"] if i["id"] == ticket.id)
        assert item["severidad"] == "critica"
        assert item["urgencia"] == "alta"
        assert item["severidad_origen"] == "ia_confirmada"
        assert item["urgencia_origen"] == "humano"
        assert item["resumen"] == "No puede facturar"


class TestBoardQueryCount:
    def test_exactly_two_tickets_table_queries_regardless_of_column_count(self, client, db, query_counter):
        sector, workflow, estados, tipo, creador = _make_workflow(db, n_estados=5)
        admin = _make_admin(db)
        for estado in estados:
            _make_ticket(db, sector, tipo, estado, creador)
        db.commit()

        with query_counter() as counter:
            resp = client.get(BOARD_ENDPOINT, params={"agrupacion": "estado"}, headers=_headers(admin))

        assert resp.status_code == 200
        # `.matching()` uses a word-bounded `FROM|JOIN tickets` regex, so it
        # does NOT count `tickets_estados`/`tickets_propuestas_ia`/etc, nor
        # the permission-check queries (they touch `permisos`, not
        # `tickets`). This isolates exactly the board's own two queries
        # (GROUP BY totals + ROW_NUMBER items) from auth/permission overhead
        # — a bare `counter.total` assertion would be broken by any future
        # unrelated auth-layer query and prove nothing about N+1 here.
        assert counter.matching("tickets") == 2, counter.statements
