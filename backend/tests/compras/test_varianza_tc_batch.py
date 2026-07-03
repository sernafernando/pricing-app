"""
REQ-FX-001 / REQ-FX-002 / REQ-FX-003 — Unit + integration tests for the
calcular_varianza_tc_batch function and the listar_pedidos filter.

TDD strict — these tests are written BEFORE the implementation.

Coverage:
  - AC1: batch result matches single-order calcular_varianza_tc for same pedido
  - AC2: filter ?diferencial_cambio_pendiente=true returns correct items + total
  - AC6: query count is bounded (≤5) regardless of N
  - AC8: edge cases — NULL tipo_cambio_original, ARS pedido, threshold boundary
  - REQ-FX-EDGE-003: threshold is exclusive (abs <= 1.00 → not pending)
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pytest

from app.models.caja import Caja, CajaTipoDocumento
from app.models.empresa import Empresa
from app.models.imputacion import Imputacion
from app.models.orden_pago import OrdenPago
from app.models.pedido_compra import PedidoCompra
from app.models.proveedor import OrigenProveedor, Proveedor
from app.models.tipo_cambio import TipoCambio
from app.models.usuario import AuthProvider, RolUsuario, Usuario
from app.services.pedidos_service import (
    calcular_varianza_tc,
    calcular_varianza_tc_batch,
)

BASE = "/api/administracion/compras"

# ---------------------------------------------------------------------------
# Permission helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def con_permisos():
    with (
        patch("app.services.permisos_service.PermisosService.tiene_permiso", return_value=True),
        patch("app.services.permisos_service.PermisosService.obtener_permisos_usuario", return_value=set()),
    ):
        yield


# ---------------------------------------------------------------------------
# Common data fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def empresa(db) -> Empresa:
    e = Empresa(nombre="Empresa Varianza Batch", activo=True, orden=0)
    db.add(e)
    db.flush()
    return e


@pytest.fixture
def proveedor(db) -> Proveedor:
    p = Proveedor(
        nombre="Prov Varianza Batch",
        activo=True,
        origen=OrigenProveedor.ERP.value,
        supp_id=9901,
    )
    db.add(p)
    db.flush()
    return p


@pytest.fixture
def user(db) -> Usuario:
    u = Usuario(
        username="batch_varianza_user",
        email="bvuser@test.com",
        nombre="BV User",
        password_hash="hashed",
        rol=RolUsuario.ADMIN,
        auth_provider=AuthProvider.LOCAL,
        activo=True,
    )
    db.add(u)
    db.flush()
    return u


@pytest.fixture
def caja_ars(db, empresa) -> Caja:
    c = Caja(
        nombre="Caja ARS BV",
        empresa_id=empresa.id,
        moneda="ARS",
        saldo_inicial=Decimal("999999999"),
        saldo_actual=Decimal("999999999"),
        activo=True,
    )
    db.add(c)
    db.flush()
    return c


@pytest.fixture
def tipos_doc(db) -> None:
    db.add(CajaTipoDocumento(nombre="Orden de Pago BV", descripcion="OP", activo=True))
    db.flush()


@pytest.fixture
def tc_usd(db) -> None:
    db.add(TipoCambio(fecha=date(2026, 1, 1), moneda="USD", compra=Decimal("1000"), venta=Decimal("1010")))
    db.add(TipoCambio(fecha=date(2026, 1, 2), moneda="USD", compra=Decimal("1400"), venta=Decimal("1410")))
    db.flush()


_pedido_seq = 0


def _make_pedido(
    db,
    *,
    empresa,
    proveedor,
    user,
    moneda="USD",
    monto=Decimal("100"),
    tc=None,
    tc_orig=None,
    tc_manual=None,
    estado="pagado",
) -> PedidoCompra:
    global _pedido_seq
    _pedido_seq += 1
    p = PedidoCompra(
        numero=f"PC-BVT-{_pedido_seq:04d}",
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda=moneda,
        monto=monto,
        tipo_cambio=tc,
        tipo_cambio_original=tc_orig,
        tipo_cambio_manual=tc_manual,
        estado=estado,
        creado_por_id=user.id,
    )
    db.add(p)
    db.flush()
    return p


def _make_caso_b_imp(
    db, *, pedido: PedidoCompra, op: OrdenPago, monto_usd: Decimal, tc: Decimal, es_reversal: bool = False
) -> Imputacion:
    """Create a raw Caso-B imputacion directly (bypasses service for unit test speed)."""
    imp = Imputacion(
        origen_tipo="orden_pago",
        origen_id=op.id,
        destino_tipo="pedido_compra",
        destino_id=pedido.id,
        monto_imputado=monto_usd,
        moneda_imputada="USD",
        tipo_cambio=tc,
        proveedor_id=pedido.proveedor_id,
        creado_por_id=pedido.creado_por_id,
        es_reversal=es_reversal,
    )
    db.add(imp)
    db.flush()
    return imp


_op_seq = 0


def _make_op(db, *, empresa, proveedor, user, monto_ars: Decimal, tc: Decimal, actualizar: bool = False) -> OrdenPago:
    global _op_seq
    _op_seq += 1
    op = OrdenPago(
        numero=f"OP-BVT-{_op_seq:05d}",
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda="ARS",
        monto_total=monto_ars,
        tipo_cambio=tc,
        modo_imputacion="especifica",
        actualizar_tc_pedido=actualizar,
        estado="pagado",
        creado_por_id=user.id,
    )
    db.add(op)
    db.flush()
    return op


# ---------------------------------------------------------------------------
# AC1 — Batch matches single-order calcular_varianza_tc
# ---------------------------------------------------------------------------


class TestBatchParidadSingleOrder:
    """AC1: calcular_varianza_tc_batch[id] == calcular_varianza_tc(pedido) for Caso-B orders."""

    def test_caso_b_simple_match(self, db, empresa, proveedor, user, tc_usd):
        """
        Pedido USD TC_orig=1000, TC_manual=1400 (tc_efectivo=1400), 1 USD Caso-B.
        varianza_bruta = (1400 - 1000) * 1 = 400. No NC compensation → neta = 400.
        (Sign: TC rose → buyer underpaid → ND needed → positive.)
        """
        pedido = _make_pedido(
            db,
            empresa=empresa,
            proveedor=proveedor,
            user=user,
            monto=Decimal("1"),
            tc=Decimal("1000"),
            tc_orig=Decimal("1000"),
            tc_manual=Decimal("1400"),
        )
        op = _make_op(
            db,
            empresa=empresa,
            proveedor=proveedor,
            user=user,
            monto_ars=Decimal("1000"),
            tc=Decimal("1000"),
            actualizar=False,
        )
        _make_caso_b_imp(db, pedido=pedido, op=op, monto_usd=Decimal("1"), tc=Decimal("1000"))

        single = calcular_varianza_tc(db, pedido)
        batch_map = calcular_varianza_tc_batch(db, [pedido.id])
        assert batch_map[pedido.id] == single
        assert batch_map[pedido.id] == Decimal("400.00")

    def test_multiple_pedidos_match(self, db, empresa, proveedor, user, tc_usd):
        """Pedido A: varianza 400 (tc_ef=1400 > tc_orig=1000); Pedido B: varianza 0 (no tc diff)."""
        # Pedido A: tc_orig=1000, tc_manual=1400 → tc_ef=1400 → bruta=400
        pa = _make_pedido(
            db,
            empresa=empresa,
            proveedor=proveedor,
            user=user,
            monto=Decimal("1"),
            tc=Decimal("1000"),
            tc_orig=Decimal("1000"),
            tc_manual=Decimal("1400"),
        )
        op_a = _make_op(
            db,
            empresa=empresa,
            proveedor=proveedor,
            user=user,
            monto_ars=Decimal("1000"),
            tc=Decimal("1000"),
            actualizar=False,
        )
        _make_caso_b_imp(db, pedido=pa, op=op_a, monto_usd=Decimal("1"), tc=Decimal("1000"))

        # Pedido B: no manual override, tc_orig=1000, no Caso-A → tc_ef=tc_orig=1000 → bruta=0
        pb = _make_pedido(
            db,
            empresa=empresa,
            proveedor=proveedor,
            user=user,
            monto=Decimal("1"),
            tc=Decimal("1000"),
            tc_orig=Decimal("1000"),
        )
        op_b = _make_op(
            db,
            empresa=empresa,
            proveedor=proveedor,
            user=user,
            monto_ars=Decimal("1000"),
            tc=Decimal("1000"),
            actualizar=False,
        )
        _make_caso_b_imp(db, pedido=pb, op=op_b, monto_usd=Decimal("1"), tc=Decimal("1000"))

        batch = calcular_varianza_tc_batch(db, [pa.id, pb.id])
        assert batch[pa.id] == calcular_varianza_tc(db, pa)
        assert batch[pb.id] == calcular_varianza_tc(db, pb)
        assert batch[pa.id] == Decimal("400.00")
        assert batch[pb.id] == Decimal("0.00")

    def test_ars_pedido_returns_zero(self, db, empresa, proveedor, user):
        """REQ-FX-EDGE-002: ARS pedido → batch returns 0, no error."""
        pedido_ars = _make_pedido(
            db,
            empresa=empresa,
            proveedor=proveedor,
            user=user,
            moneda="ARS",
            monto=Decimal("5000"),
            tc=None,
            tc_orig=None,
        )
        batch = calcular_varianza_tc_batch(db, [pedido_ars.id])
        assert batch[pedido_ars.id] == Decimal("0")

    def test_null_tipo_cambio_original_returns_zero(self, db, empresa, proveedor, user):
        """REQ-FX-EDGE-001: NULL tipo_cambio_original → no error, result 0."""
        pedido = _make_pedido(
            db, empresa=empresa, proveedor=proveedor, user=user, monto=Decimal("10"), tc=Decimal("1000"), tc_orig=None
        )
        op = _make_op(
            db,
            empresa=empresa,
            proveedor=proveedor,
            user=user,
            monto_ars=Decimal("14000"),
            tc=Decimal("1400"),
            actualizar=False,
        )
        _make_caso_b_imp(db, pedido=pedido, op=op, monto_usd=Decimal("10"), tc=Decimal("1400"))
        # tc_orig is NULL → batch falls back to tc_efectivo → bruta = 0
        batch = calcular_varianza_tc_batch(db, [pedido.id])
        assert batch[pedido.id] == Decimal("0.00")


# ---------------------------------------------------------------------------
# AC8 — Threshold edge case
# ---------------------------------------------------------------------------


class TestThresholdEdge:
    """REQ-FX-EDGE-003: abs ≤ 1.00 → not pending; abs > 1.00 → pending."""

    def test_exactly_one_ars_not_pending(self, db, empresa, proveedor, user, tc_usd):
        """Variance of exactly 1.00 ARS → abs <= 1.00, not pending (exclusive threshold)."""
        # tc_orig=1000, tc_manual=1001 → tc_ef=1001 → bruta = (1001-1000)*1 = 1.00
        pedido = _make_pedido(
            db,
            empresa=empresa,
            proveedor=proveedor,
            user=user,
            monto=Decimal("1"),
            tc=Decimal("1000"),
            tc_orig=Decimal("1000"),
            tc_manual=Decimal("1001"),
        )
        op = _make_op(
            db,
            empresa=empresa,
            proveedor=proveedor,
            user=user,
            monto_ars=Decimal("1000"),
            tc=Decimal("1000"),
            actualizar=False,
        )
        _make_caso_b_imp(db, pedido=pedido, op=op, monto_usd=Decimal("1"), tc=Decimal("1000"))

        batch = calcular_varianza_tc_batch(db, [pedido.id])
        neta = abs(batch[pedido.id])
        assert neta <= Decimal("1.00")

    def test_above_threshold_is_pending(self, db, empresa, proveedor, user, tc_usd):
        """Variance of 2.00 ARS → abs > 1.00 → pending."""
        # tc_orig=1000, tc_manual=1002, 1 USD → bruta = 2.00
        pedido = _make_pedido(
            db,
            empresa=empresa,
            proveedor=proveedor,
            user=user,
            monto=Decimal("1"),
            tc=Decimal("1000"),
            tc_orig=Decimal("1000"),
            tc_manual=Decimal("1002"),
        )
        op = _make_op(
            db,
            empresa=empresa,
            proveedor=proveedor,
            user=user,
            monto_ars=Decimal("1000"),
            tc=Decimal("1000"),
            actualizar=False,
        )
        _make_caso_b_imp(db, pedido=pedido, op=op, monto_usd=Decimal("1"), tc=Decimal("1000"))
        batch = calcular_varianza_tc_batch(db, [pedido.id])
        neta = abs(batch[pedido.id])
        assert neta > Decimal("1.00")


# ---------------------------------------------------------------------------
# AC6 — Query count ≤ 5
# ---------------------------------------------------------------------------


class TestQueryCount:
    """AC6: batch issues at most 5 queries regardless of N."""

    def test_bounded_queries_for_50_pedidos(self, db, empresa, proveedor, user, query_counter):
        """For 50 pedido ids, query count must be <= 5."""
        import sqlalchemy as sa

        for i in range(50):
            p = PedidoCompra(
                numero=f"PC-QC-{i:04d}",
                empresa_id=empresa.id,
                proveedor_id=proveedor.id,
                moneda="ARS",
                monto=Decimal("100"),
                estado="pagado",
                creado_por_id=user.id,
            )
            db.add(p)
        db.flush()
        pedido_ids = [
            row[0]
            for row in db.execute(
                sa.text("SELECT id FROM pedidos_compra WHERE empresa_id = :eid ORDER BY id DESC LIMIT 50"),
                {"eid": empresa.id},
            ).all()
        ]

        with query_counter() as counter:
            calcular_varianza_tc_batch(db, pedido_ids)

        assert counter.total <= 5, f"Expected ≤5 queries, got {counter.total}"


# ---------------------------------------------------------------------------
# REQ-FX-002 — List endpoint populates varianza_tc_neta
# ---------------------------------------------------------------------------


class TestListEndpointVarianzaFields:
    """GET /pedidos returns varianza_tc_neta, varianza_tc_pendiente, moneda_varianza."""

    def test_list_includes_varianza_fields(
        self, db, client, con_permisos, empresa, proveedor, active_user, auth_headers, caja_ars, tipos_doc, tc_usd
    ):
        """List response item includes varianza_tc_neta, varianza_tc_pendiente=true, moneda_varianza='ARS'."""
        uid = active_user.id
        pedido = PedidoCompra(
            numero="PC-LIST-VAR-001",
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="USD",
            monto=Decimal("1"),
            tipo_cambio=Decimal("1000"),
            tipo_cambio_original=Decimal("1000"),
            tipo_cambio_manual=Decimal("1400"),  # tc_ef=1400 → bruta = (1400-1000)*1 = 400
            estado="pagado",
            creado_por_id=uid,
        )
        db.add(pedido)
        db.flush()

        op = _make_op(
            db,
            empresa=empresa,
            proveedor=proveedor,
            user=active_user,
            monto_ars=Decimal("1000"),
            tc=Decimal("1000"),
            actualizar=False,
        )
        _make_caso_b_imp(db, pedido=pedido, op=op, monto_usd=Decimal("1"), tc=Decimal("1000"))

        resp = client.get(f"{BASE}/pedidos", headers=auth_headers)
        assert resp.status_code == 200
        items = resp.json()["items"]
        match = next((i for i in items if i["id"] == pedido.id), None)
        assert match is not None
        assert match["varianza_tc_pendiente"] is True
        assert Decimal(str(match["varianza_tc_neta"])) == Decimal("400.00")
        assert match.get("moneda_varianza") == "ARS"

    def test_fully_absorbed_shows_not_pending(
        self, db, client, con_permisos, empresa, proveedor, active_user, auth_headers
    ):
        """Pedido with varianza 0 → varianza_tc_pendiente=false in list."""
        uid = active_user.id
        pedido = PedidoCompra(
            numero="PC-LIST-ZERO-002",
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="USD",
            monto=Decimal("1"),
            tipo_cambio=Decimal("1000"),
            tipo_cambio_original=Decimal("1000"),
            estado="pagado",
            creado_por_id=uid,
        )
        db.add(pedido)
        db.flush()
        # No Caso-B imputaciones → varianza = 0
        resp = client.get(f"{BASE}/pedidos", headers=auth_headers)
        assert resp.status_code == 200
        items = resp.json()["items"]
        match = next((i for i in items if i["id"] == pedido.id), None)
        assert match is not None
        assert match["varianza_tc_pendiente"] is False


# ---------------------------------------------------------------------------
# REQ-FX-003 — Filter ?diferencial_cambio_pendiente=true
# ---------------------------------------------------------------------------


class TestFilterDiferencialCambioPendiente:
    """Server-side filter returns correct items with correct total (not page-scoped)."""

    def _make_pedido_con_varianza(self, db, *, empresa, proveedor, user, numero_suffix: str) -> PedidoCompra:
        global _pedido_seq
        _pedido_seq += 1
        pedido = PedidoCompra(
            numero=f"PC-FILT-{numero_suffix}",
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="USD",
            monto=Decimal("1"),
            tipo_cambio=Decimal("1000"),
            tipo_cambio_original=Decimal("1000"),
            tipo_cambio_manual=Decimal("1500"),  # tc_ef=1500 → bruta=500 > threshold
            estado="pagado",
            creado_por_id=user.id,
        )
        db.add(pedido)
        db.flush()
        op = _make_op(
            db,
            empresa=empresa,
            proveedor=proveedor,
            user=user,
            monto_ars=Decimal("1000"),
            tc=Decimal("1000"),
            actualizar=False,
        )
        _make_caso_b_imp(db, pedido=pedido, op=op, monto_usd=Decimal("1"), tc=Decimal("1000"))
        return pedido

    def test_filter_returns_only_pending(
        self, db, client, con_permisos, empresa, proveedor, active_user, auth_headers, caja_ars, tipos_doc, tc_usd
    ):
        """P1 (varianza pendiente), P2 (varianza 0, no Caso-B) → filter returns only P1."""
        uid = active_user.id
        p1 = self._make_pedido_con_varianza(
            db, empresa=empresa, proveedor=proveedor, user=active_user, numero_suffix="F001"
        )
        p2 = PedidoCompra(
            numero="PC-FILT-F002",
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="USD",
            monto=Decimal("1"),
            tipo_cambio=Decimal("1000"),
            tipo_cambio_original=Decimal("1000"),
            estado="pagado",
            creado_por_id=uid,
        )
        db.add(p2)
        db.flush()

        resp = client.get(f"{BASE}/pedidos?diferencial_cambio_pendiente=true", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        ids = [i["id"] for i in data["items"]]
        assert p1.id in ids
        assert p2.id not in ids

    def test_filter_total_reflects_all_matching_not_just_page(
        self, db, client, con_permisos, empresa, proveedor, active_user, auth_headers, caja_ars, tipos_doc, tc_usd
    ):
        """total returned equals number of survivors, not size of unconstrained table."""
        uid = active_user.id
        # Create 3 pedidos with varianza + 2 without
        p_with = [
            self._make_pedido_con_varianza(
                db, empresa=empresa, proveedor=proveedor, user=active_user, numero_suffix=f"TOTAL-{i:03d}"
            )
            for i in range(3)
        ]
        for j in range(2):
            p_no = PedidoCompra(
                numero=f"PC-FILT-NOTOTAL-{j:03d}",
                empresa_id=empresa.id,
                proveedor_id=proveedor.id,
                moneda="USD",
                monto=Decimal("1"),
                tipo_cambio=Decimal("1000"),
                tipo_cambio_original=Decimal("1000"),
                estado="pagado",
                creado_por_id=uid,
            )
            db.add(p_no)
        db.flush()

        resp = client.get(f"{BASE}/pedidos?diferencial_cambio_pendiente=true&page=1&page_size=50", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= len(p_with)
        result_ids = {i["id"] for i in data["items"]}
        for p in p_with:
            assert p.id in result_ids

    def test_filter_pagination_multipage(
        self, db, client, con_permisos, empresa, proveedor, active_user, auth_headers, caja_ars, tipos_doc, tc_usd
    ):
        """REQ-FX-003 scenario 2: con varios survivors y page_size chico, total cuenta todos
        y el slicing de la segunda página funciona (sin solapamiento entre páginas)."""
        for i in range(3):
            self._make_pedido_con_varianza(
                db, empresa=empresa, proveedor=proveedor, user=active_user, numero_suffix=f"MP-{i:03d}"
            )
        db.flush()

        r1 = client.get(f"{BASE}/pedidos?diferencial_cambio_pendiente=true&page=1&page_size=2", headers=auth_headers)
        assert r1.status_code == 200
        d1 = r1.json()
        # total cuenta TODOS los survivors (no solo la página) → hay más de una página
        assert d1["total"] >= 3
        assert d1["total"] > 2
        assert len(d1["items"]) == 2  # página llena
        ids1 = [i["id"] for i in d1["items"]]

        r2 = client.get(f"{BASE}/pedidos?diferencial_cambio_pendiente=true&page=2&page_size=2", headers=auth_headers)
        assert r2.status_code == 200
        d2 = r2.json()
        assert d2["total"] == d1["total"]  # total consistente entre páginas
        ids2 = [i["id"] for i in d2["items"]]
        assert set(ids1).isdisjoint(ids2)  # sin solapamiento entre páginas

    def test_filter_ignores_non_settled_estados(
        self, db, client, con_permisos, empresa, proveedor, active_user, auth_headers, tc_usd
    ):
        """Pedido in estado='aprobado' with large TC variance is excluded from filter."""
        uid = active_user.id
        pedido = PedidoCompra(
            numero="PC-FILT-APROBADO-001",
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="USD",
            monto=Decimal("1"),
            tipo_cambio=Decimal("1000"),
            tipo_cambio_original=Decimal("1000"),
            tipo_cambio_manual=Decimal("1500"),
            estado="aprobado",  # NOT pagado/pagado_parcial
            creado_por_id=uid,
        )
        db.add(pedido)
        db.flush()
        op = _make_op(
            db,
            empresa=empresa,
            proveedor=proveedor,
            user=active_user,
            monto_ars=Decimal("1000"),
            tc=Decimal("1000"),
            actualizar=False,
        )
        _make_caso_b_imp(db, pedido=pedido, op=op, monto_usd=Decimal("1"), tc=Decimal("1000"))

        resp = client.get(f"{BASE}/pedidos?diferencial_cambio_pendiente=true", headers=auth_headers)
        assert resp.status_code == 200
        ids = [i["id"] for i in resp.json()["items"]]
        assert pedido.id not in ids

    def test_filter_absent_returns_all_no_regression(
        self, db, client, con_permisos, empresa, proveedor, active_user, auth_headers
    ):
        """Without filter, all pedidos are returned (no regression)."""
        uid = active_user.id
        pedido = PedidoCompra(
            numero="PC-NOFILT-001",
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="ARS",
            monto=Decimal("500"),
            estado="pagado",
            creado_por_id=uid,
        )
        db.add(pedido)
        db.flush()

        resp = client.get(f"{BASE}/pedidos", headers=auth_headers)
        assert resp.status_code == 200
        ids = [i["id"] for i in resp.json()["items"]]
        assert pedido.id in ids
