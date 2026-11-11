"""S4-S7: the shipping cost a PM chooses for a product, applied inside the resolvers (real Postgres).

The mlwebhook table (`_query_list_cost_by_mla`) and the units sold (`unidades_vendidas_por_mla`, Métricas ML's own
base, pinned by `test_units_sold_postgres.py`) are stubbed; the publications, the products and the stored choices are
real tables read through a session with `autoflush=False`, as in production.

Costs: the RE200 production figures (L9, item_id 22): MLA1173065146 = 7290, MLA2517958828 = 10890; `MLA_A` stands
for one of its 41 publications at 8290 (its id is unknown: the id is synthetic, the cost is real). The units sold are
SYNTHETIC weights: no production sales figures were captured for these publications.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import CheckConstraint, event, text
from sqlalchemy.orm import sessionmaker

from app.models.producto_envio_eleccion import ProductoEnvioEleccion
from app.services import envio_real_service
from app.services.envio_real_service import (
    MODOS_ENVIO,
    CostosEnvio,
    resolver_costo_envio,
    resolver_costos_envio_batch,
    resolver_costos_envio_publicaciones,
)
from app.services import envio_producto_eleccion as envio_producto
from tests.services.ml_publications.conftest import env, mlpub_pg  # noqa: F401
from tests.services.ml_publications.view import seed

pytestmark = pytest.mark.postgres

OWN = "MLA1173065146"  # 7290
OUTLIER = "MLA2517958828"  # 10890
MID = "MLA_A"  # synthetic id, real cost 8290
RE200 = 22
COSTS = {OWN: 7290.0, OUTLIER: 10890.0, MID: 8290.0}

# The choices table as the migration builds it, minus the `usuarios` foreign key (these schemas have no `usuarios`).
CHOICE_DDL = (
    "CREATE TABLE producto_envio_eleccion (item_id integer PRIMARY KEY REFERENCES productos_erp (item_id), "
    "modo varchar(16) NOT NULL CONSTRAINT ck_producto_envio_eleccion_modo "
    "CHECK (modo IN ('max', 'mla', 'promedio', 'ponderado')), mla varchar(32), usuario_id integer, "
    "updated_at timestamptz NOT NULL DEFAULT now())"
)


@pytest.fixture()
def conn(env):  # noqa: F811  (`env` builds `publicaciones_ml` beside `productos_erp`)
    with env.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        connection.execute(text(seed.PRICING_DDL))
        connection.execute(text(CHOICE_DDL))
        for statement in seed.AUDIT_DDL:  # `auditoria` (and the `usuarios` it references), production's shape
            connection.execute(text(statement))
        connection.execute(
            text("INSERT INTO usuarios (id, nombre, username) VALUES (7, 'PM', 'pm'), (8, 'PM2', 'pm2')")
        )
        yield connection


@pytest.fixture()
def db(env, conn):  # noqa: F811
    session = sessionmaker(bind=env, autocommit=False, autoflush=False)()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture()
def costs(monkeypatch) -> list[list[str]]:
    """The mlwebhook read, stubbed with `COSTS`; records the MLAs asked for."""
    asked: list[list[str]] = []

    def query(mla_ids):
        asked.append(sorted(mla_ids))
        return {mla: COSTS[mla] for mla in mla_ids if mla in COSTS}

    monkeypatch.setattr(envio_real_service, "_query_list_cost_by_mla", query)
    return asked


@pytest.fixture()
def units(monkeypatch):
    """The units sold per MLA, stubbed: `units.sold` answers every period; each call is recorded."""

    class Units:
        sold: dict[str, int] = {}
        calls: list[tuple[list[str], date, date]] = []

    Units.sold, Units.calls = {}, []

    def read(db, mlas, date_from, date_to):
        Units.calls.append((sorted(mlas), date_from, date_to))
        return {mla: Units.sold[mla] for mla in mlas if Units.sold.get(mla)}

    monkeypatch.setattr(envio_real_service, "unidades_vendidas_por_mla", read)
    return Units


def add_publication(conn, mla: str, product: int, activo: bool = True) -> None:
    conn.execute(
        text(
            "INSERT INTO publicaciones_ml (mla, item_id, codigo, item_title, pricelist_id, activo) "
            "VALUES (:mla, :item, 'C', 't', 4, :activo)"
        ),
        {"mla": mla, "item": product, "activo": activo},
    )


def seed_re200(conn, *, mid: bool = False) -> None:
    seed.add_product(conn, RE200, "C22", "RE200")
    seed.add_cost(conn, RE200, 1000.0, envio=555.0)  # the ERP envio, used only when no MLA has a cost
    add_publication(conn, OWN, RE200)
    add_publication(conn, OUTLIER, RE200)
    if mid:
        add_publication(conn, MID, RE200)


def choose(conn, item_id: int, modo: str, mla: str | None = None) -> None:
    conn.execute(
        text("INSERT INTO producto_envio_eleccion (item_id, modo, mla, usuario_id) VALUES (:i, :m, :mla, 1)"),
        {"i": item_id, "m": modo, "mla": mla},
    )


def product(db, item_id: int = RE200):
    from app.models.producto import ProductoERP

    return db.get(ProductoERP, item_id)


class TestTheModel:
    def test_the_check_lists_the_four_modes(self) -> None:
        (check,) = [c for c in ProductoEnvioEleccion.__table__.constraints if isinstance(c, CheckConstraint)]
        assert MODOS_ENVIO == ("max", "mla", "promedio", "ponderado")
        assert all(f"'{modo}'" in str(check.sqltext) for modo in MODOS_ENVIO)

    def test_the_table_shape(self) -> None:
        table = ProductoEnvioEleccion.__table__
        assert table.name == "producto_envio_eleccion"
        assert [c.name for c in table.primary_key] == ["item_id"]
        assert {fk.target_fullname for fk in table.foreign_keys} == {"productos_erp.item_id", "usuarios.id"}
        assert table.c.modo.type.length == 16 and table.c.mla.type.length == 32 and table.c.mla.nullable
        assert table.c.updated_at.type.timezone is True
        assert any(ix.columns.keys() == ["usuario_id"] for ix in table.indexes)


class TestNoChoiceIsTodaysMax:
    """S4: without a stored choice the product resolves exactly as before, MAX of its active MLAs' costs."""

    def test_single(self, conn, db, costs, units) -> None:
        seed_re200(conn)
        assert resolver_costo_envio(db, product(db)) == 10890.0
        assert units.calls == []  # no sales read without a ponderado choice

    def test_batch(self, conn, db, costs, units) -> None:
        seed_re200(conn)
        assert resolver_costos_envio_batch(db, [RE200]) == {RE200: 10890.0}

    def test_publicaciones(self, conn, db, costs, units) -> None:
        seed_re200(conn)
        assert resolver_costos_envio_publicaciones(db, [RE200], [OWN]) == CostosEnvio(
            por_producto={RE200: 10890.0}, por_mla={OWN: 7290.0}
        )

    def test_a_product_without_any_cost_still_falls_back_to_the_erp_envio(self, conn, db, costs, units) -> None:
        seed.add_product(conn, 90, "C90", "Sin costo")
        seed.add_cost(conn, 90, 1000.0, envio=555.0)
        add_publication(conn, "MLA_NOCOST", 90)
        choose(conn, 90, "promedio")
        assert resolver_costo_envio(db, product(db, 90)) == 555.0
        assert resolver_costos_envio_batch(db, [90]) == {}


class TestEachMode:
    def test_max_stored_is_the_max(self, conn, db, costs, units) -> None:
        seed_re200(conn)
        choose(conn, RE200, "max")
        assert resolver_costo_envio(db, product(db)) == 10890.0
        assert resolver_costos_envio_batch(db, [RE200]) == {RE200: 10890.0}

    def test_mla_is_that_publications_own_cost(self, conn, db, costs, units) -> None:
        seed_re200(conn)
        choose(conn, RE200, "mla", OWN)
        assert resolver_costo_envio(db, product(db)) == 7290.0
        assert resolver_costos_envio_batch(db, [RE200]) == {RE200: 7290.0}
        assert resolver_costos_envio_publicaciones(db, [RE200], [OUTLIER]) == CostosEnvio(
            por_producto={RE200: 7290.0},
            por_mla={OUTLIER: 10890.0},  # each publication keeps its own cost
        )

    def test_promedio_is_the_simple_mean_of_the_active_mlas_costs(self, conn, db, costs, units) -> None:
        seed_re200(conn, mid=True)
        choose(conn, RE200, "promedio")
        expected = round((7290.0 + 10890.0 + 8290.0) / 3, 2)
        assert resolver_costo_envio(db, product(db)) == expected
        assert resolver_costos_envio_batch(db, [RE200]) == {RE200: expected}

    def test_promedio_leaves_out_inactive_and_costless_mlas(self, conn, db, costs, units) -> None:
        seed_re200(conn)
        add_publication(conn, MID, RE200, activo=False)
        add_publication(conn, "MLA_NOCOST", RE200)
        choose(conn, RE200, "promedio")
        assert resolver_costos_envio_batch(db, [RE200]) == {RE200: 9090.0}  # (7290 + 10890) / 2

    def test_ponderado_weights_each_cost_by_its_units_of_the_last_30_days(self, conn, db, costs, units) -> None:
        seed_re200(conn)
        choose(conn, RE200, "ponderado")
        units.sold = {OWN: 3, OUTLIER: 1}
        assert resolver_costo_envio(db, product(db)) == 8190.0  # (7290*3 + 10890*1) / 4
        assert resolver_costos_envio_batch(db, [RE200]) == {RE200: 8190.0}
        today = envio_real_service.hoy()
        assert {(first, last) for _, first, last in units.calls} == {(today - timedelta(days=29), today)}

    def test_ponderado_without_sales_in_30_days_is_promedio(self, conn, db, costs, units) -> None:
        seed_re200(conn)
        choose(conn, RE200, "ponderado")
        units.sold = {}
        assert resolver_costo_envio(db, product(db)) == 9090.0
        assert resolver_costos_envio_batch(db, [RE200]) == {RE200: 9090.0}

    def test_a_failed_sales_read_is_promedio_and_the_session_stays_usable(self, conn, db, costs, monkeypatch) -> None:
        """A real database error in the sales read must not take Productos down: the product falls back to promedio
        (the same rule as no sales) and the caller's session keeps working."""
        seed_re200(conn)
        choose(conn, RE200, "ponderado")

        def failing(session, mlas, date_from, date_to):
            session.execute(text("SELECT 1 / 0"))  # a real error from Postgres, not a mock

        monkeypatch.setattr(envio_real_service, "unidades_vendidas_por_mla", failing)
        assert resolver_costos_envio_batch(db, [RE200]) == {RE200: 9090.0}
        assert resolver_costo_envio(db, product(db)) == 9090.0
        assert db.execute(text("SELECT 1")).scalar() == 1

    def test_a_ponderado_read_does_not_flush_the_callers_pending_objects(self, conn, db, costs, units) -> None:
        """A read-only lookup never flushes what the caller has pending (the resolvers' rule), on the `ponderado`
        path too: its savepoint must not flush on entry."""
        from app.models.producto import ProductoERP

        seed_re200(conn)
        choose(conn, RE200, "ponderado")
        units.sold = {OWN: 3, OUTLIER: 1}
        db.add(ProductoERP(item_id=9999, codigo="PEND", descripcion="pendiente"))
        assert resolver_costos_envio_batch(db, [RE200]) == {RE200: 8190.0}
        assert conn.execute(text("SELECT count(*) FROM productos_erp WHERE item_id = 9999")).scalar() == 0
        assert len(db.new) == 1


class TestChosenMlaFallsBackToMax:
    """S6: a chosen MLA that is inactive or has no cost resolves to the MAX."""

    def test_inactive(self, conn, db, costs, units) -> None:
        seed_re200(conn)
        add_publication(conn, MID, RE200, activo=False)
        choose(conn, RE200, "mla", MID)
        assert resolver_costo_envio(db, product(db)) == 10890.0
        assert resolver_costos_envio_batch(db, [RE200]) == {RE200: 10890.0}

    def test_without_cost(self, conn, db, costs, units) -> None:
        seed_re200(conn)
        add_publication(conn, "MLA_NOCOST", RE200)
        choose(conn, RE200, "mla", "MLA_NOCOST")
        assert resolver_costo_envio(db, product(db)) == 10890.0
        assert resolver_costos_envio_batch(db, [RE200]) == {RE200: 10890.0}


def statements_of(db, run) -> list[str]:
    recorded: list[str] = []

    def record(connection, cursor, statement, *rest) -> None:
        recorded.append(statement)

    event.listen(db.get_bind(), "before_cursor_execute", record)
    try:
        run()
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", record)
    return recorded


class TestTheBatchStaysConstant:
    """One read of the choices for every asked product and one sales read for the ponderado ones, whatever their
    number."""

    def seed_many(self, conn, products: int) -> list[int]:
        ids = list(range(100, 100 + products))
        for n, item_id in enumerate(ids):
            seed.add_product(conn, item_id, f"C{item_id}", f"P{item_id}")
            add_publication(conn, f"MLA_{item_id}_X", item_id)
            add_publication(conn, f"MLA_{item_id}_Y", item_id)
            choose(conn, item_id, ("ponderado", "promedio", "mla", "max")[n % 4], f"MLA_{item_id}_X")
        return ids

    @pytest.mark.parametrize("products", [4, 40])
    def test_statements_and_sales_reads_do_not_grow(self, conn, db, units, monkeypatch, products) -> None:
        ids = self.seed_many(conn, products)
        monkeypatch.setattr(
            envio_real_service, "_query_list_cost_by_mla", lambda mlas: {m: 7290.0 for m in mlas if m.endswith("X")}
        )
        recorded = statements_of(db, lambda: resolver_costos_envio_batch(db, ids))
        # The sales read is stubbed; around it, its savepoint (transaction control, the same two whatever the count).
        assert [s for s in recorded if "SAVEPOINT" in s] == [
            "SAVEPOINT sa_savepoint_1",
            "RELEASE SAVEPOINT sa_savepoint_1",
        ]
        recorded = [s for s in recorded if "SAVEPOINT" not in s]
        assert len(recorded) == 2  # the active MLAs and the choices
        assert "producto_envio_eleccion" in recorded[1] and "ANY" in recorded[1].upper()
        assert len(units.calls) == 1  # one sales read, only for the ponderado products' MLAs
        ponderados = [item_id for n, item_id in enumerate(ids) if n % 4 == 0]
        assert units.calls[0][0] == sorted(m for i in ponderados for m in (f"MLA_{i}_X", f"MLA_{i}_Y"))

    def test_without_a_ponderado_choice_there_is_no_sales_read(self, conn, db, costs, units) -> None:
        seed_re200(conn)
        choose(conn, RE200, "promedio")
        resolver_costos_envio_batch(db, [RE200])
        assert units.calls == []

    def test_the_mlwebhook_read_still_never_raises(self, conn, db, units, monkeypatch) -> None:
        seed_re200(conn)
        choose(conn, RE200, "mla", OWN)

        def down(mla_ids):
            raise RuntimeError("mlwebhook unreachable")

        monkeypatch.setattr(envio_real_service, "_query_list_cost_by_mla", down)
        assert resolver_costos_envio_batch(db, [RE200]) == {}
        assert resolver_costo_envio(db, product(db)) == 555.0


class TestOptions:
    """S1, S2, S5, S6: what the PM chooses from, for a period."""

    PERIOD = (date(2026, 10, 1), date(2026, 10, 30))

    def test_every_active_mla_with_its_cost_and_units_and_the_most_sold_flagged(self, conn, db, costs, units) -> None:
        seed_re200(conn, mid=True)
        add_publication(conn, "MLA_INACTIVE", RE200, activo=False)
        units.sold = {OWN: 3, OUTLIER: 1}
        found = envio_producto.opciones_envio(db, RE200, *self.PERIOD)
        assert found is not None
        assert found["publicaciones"] == [
            {"mla": OWN, "costo": 7290.0, "unidades": 3, "mas_vendida": True},
            {"mla": OUTLIER, "costo": 10890.0, "unidades": 1, "mas_vendida": False},
            {"mla": MID, "costo": 8290.0, "unidades": 0, "mas_vendida": False},
        ]
        assert found["promedio"] == round((7290.0 + 10890.0 + 8290.0) / 3, 2)
        assert found["ponderado"] == 8190.0
        assert found["max"] == 10890.0
        assert (found["date_from"], found["date_to"]) == self.PERIOD
        assert units.calls[0][1:] == self.PERIOD

    def test_no_sales_in_the_period_has_no_ponderado_and_no_most_sold(self, conn, db, costs, units) -> None:
        seed_re200(conn)
        found = envio_producto.opciones_envio(db, RE200, *self.PERIOD)
        assert found["ponderado"] is None
        assert not any(row["mas_vendida"] for row in found["publicaciones"])

    def test_without_a_choice_it_is_max_and_resolves_to_the_max(self, conn, db, costs, units) -> None:
        seed_re200(conn)
        found = envio_producto.opciones_envio(db, RE200, *self.PERIOD)
        assert found["eleccion"] == {
            "modo": "max",
            "mla": None,
            "costo": 10890.0,
            "warning": None,
            "usuario_id": None,
            "updated_at": None,
        }

    def test_a_stored_ponderado_resolves_with_the_last_30_days_not_the_period(self, conn, db, costs, units) -> None:
        seed_re200(conn)
        choose(conn, RE200, "ponderado")
        units.sold = {OWN: 3, OUTLIER: 1}
        found = envio_producto.opciones_envio(db, RE200, *self.PERIOD)
        assert found["eleccion"]["modo"] == "ponderado" and found["eleccion"]["costo"] == 8190.0
        today = envio_real_service.hoy()
        assert (today - timedelta(days=29), today) in {(first, last) for _, first, last in units.calls}

    def test_a_stored_mla_resolves_to_its_cost(self, conn, db, costs, units) -> None:
        seed_re200(conn)
        choose(conn, RE200, "mla", OWN)
        eleccion = envio_producto.opciones_envio(db, RE200, *self.PERIOD)["eleccion"]
        assert (eleccion["modo"], eleccion["mla"], eleccion["costo"], eleccion["warning"]) == ("mla", OWN, 7290.0, None)
        assert eleccion["usuario_id"] == 1 and eleccion["updated_at"] is not None

    @pytest.mark.parametrize("activo", [False, True])
    def test_a_stored_mla_that_fell_back_to_max_warns(self, conn, db, costs, units, activo) -> None:
        seed_re200(conn)
        chosen = MID if not activo else "MLA_NOCOST"  # inactive with a cost / active without one
        add_publication(conn, chosen, RE200, activo=activo)
        choose(conn, RE200, "mla", chosen)
        eleccion = envio_producto.opciones_envio(db, RE200, *self.PERIOD)["eleccion"]
        assert eleccion["costo"] == 10890.0
        assert chosen in eleccion["warning"] and "máximo" in eleccion["warning"]

    def test_an_unknown_product_is_none(self, conn, db, costs, units) -> None:
        assert envio_producto.opciones_envio(db, 404, *self.PERIOD) is None


class TestSaveChoice:
    def test_it_stores_the_mode_the_mla_and_who(self, conn, db, costs, units) -> None:
        seed_re200(conn)
        saved = envio_producto.guardar_eleccion(db, RE200, "mla", OWN, usuario_id=7)
        db.commit()
        assert (saved["modo"], saved["mla"], saved["usuario_id"]) == ("mla", OWN, 7)
        assert saved["updated_at"] is not None
        assert resolver_costo_envio(db, product(db)) == 7290.0

    def test_every_change_is_audited_with_who_and_from_to(self, conn, db, costs, units) -> None:
        """L12: each change of the choice writes one `auditoria` row (who, when, before -> after), in the same
        transaction as the choice."""
        seed_re200(conn)
        envio_producto.guardar_eleccion(db, RE200, "mla", OWN, usuario_id=7)
        db.commit()
        envio_producto.guardar_eleccion(db, RE200, "promedio", None, usuario_id=7)
        db.commit()
        rows = conn.execute(
            text(
                "SELECT item_id, usuario_id, tipo_accion, valores_anteriores, valores_nuevos, fecha "
                "FROM auditoria ORDER BY id"
            )
        ).all()
        assert [(r.item_id, r.usuario_id, r.tipo_accion) for r in rows] == [
            (RE200, 7, "ENVIO_PRODUCTO_ELECCION"),
            (RE200, 7, "ENVIO_PRODUCTO_ELECCION"),
        ]
        assert rows[0].valores_anteriores == {"modo": "max", "mla": None}  # no stored choice reads as the MAX
        assert rows[0].valores_nuevos == {"modo": "mla", "mla": OWN}
        assert rows[1].valores_anteriores == {"modo": "mla", "mla": OWN}
        assert rows[1].valores_nuevos == {"modo": "promedio", "mla": None}
        assert all(r.fecha is not None for r in rows)

    def test_saving_the_same_choice_again_is_not_a_change(self, conn, db, costs, units) -> None:
        seed_re200(conn)
        envio_producto.guardar_eleccion(db, RE200, "promedio", None, usuario_id=7)
        db.commit()
        envio_producto.guardar_eleccion(db, RE200, "promedio", None, usuario_id=7)
        db.commit()
        assert conn.execute(text("SELECT count(*) FROM auditoria")).scalar() == 1

    def test_the_audit_row_rolls_back_with_the_choice(self, conn, db, costs, units) -> None:
        seed_re200(conn)
        envio_producto.guardar_eleccion(db, RE200, "promedio", None, usuario_id=7)
        db.rollback()
        assert conn.execute(text("SELECT count(*) FROM auditoria")).scalar() == 0
        assert conn.execute(text("SELECT count(*) FROM producto_envio_eleccion")).scalar() == 0

    def test_it_replaces_the_previous_choice(self, conn, db, costs, units) -> None:
        seed_re200(conn)
        envio_producto.guardar_eleccion(db, RE200, "mla", OWN, usuario_id=7)
        db.commit()
        envio_producto.guardar_eleccion(db, RE200, "promedio", None, usuario_id=8)
        db.commit()
        rows = conn.execute(text("SELECT modo, mla, usuario_id FROM producto_envio_eleccion")).all()
        assert [tuple(r) for r in rows] == [("promedio", None, 8)]

    def test_max_is_stored_as_a_row(self, conn, db, costs, units) -> None:
        seed_re200(conn)
        envio_producto.guardar_eleccion(db, RE200, "max", None, usuario_id=7)
        db.commit()
        rows = conn.execute(text("SELECT modo, mla, usuario_id FROM producto_envio_eleccion")).all()
        assert [tuple(r) for r in rows] == [("max", None, 7)]  # who chose MAX, and when, stays recorded

    def test_an_mla_of_another_product_is_refused(self, conn, db, costs, units) -> None:
        seed_re200(conn)
        seed.add_product(conn, 90, "C90", "Otro")
        add_publication(conn, "MLA_OTHER", 90)
        with pytest.raises(envio_producto.EleccionInvalida) as refused:
            envio_producto.guardar_eleccion(db, RE200, "mla", "MLA_OTHER", usuario_id=7)
        assert refused.value.field == "mla"
        assert conn.execute(text("SELECT count(*) FROM producto_envio_eleccion")).scalar() == 0

    def test_an_unknown_product_is_none(self, conn, db, costs, units) -> None:
        assert envio_producto.guardar_eleccion(db, 404, "max", None, usuario_id=7) is None
