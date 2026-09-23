"""PR1 — factura rows (option A), tipo/responsable gates, 5-minute undo.

Covers:
  - empty / whitespace numero → HTTP 422, no row, no alert
  - seed `A-1; A-2; ;A-3` → 3 rows; raw `facturas_documento` kept
  - ERP `ct_transaction_id` alone is NOT factura cargada
  - default tipo=mercaderia; responsable_id = creado_por_id
  - PM PATCH tipo after create → 403; admin succeeds
  - POST 201; undo ≤5m → 204; >5m → 409
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from sqlalchemy import UniqueConstraint, func
from sqlalchemy.exc import IntegrityError

from app.models.empresa import Empresa
from app.models.notificacion import Notificacion
from app.models.pedido_compra import PedidoCompra
from app.models.pedido_factura_documento import PedidoFacturaDocumento
from app.models.proveedor import OrigenProveedor, Proveedor
from app.models.usuario import RolUsuario, Usuario
from app.services import pedidos_service


BASE = "/api/administracion/compras"


@pytest.fixture
def empresa(db) -> Empresa:
    emp = Empresa(id=1, nombre="Empresa Factura Docs", activo=True, orden=0)
    db.add(emp)
    db.flush()
    return emp


@pytest.fixture
def proveedor(db) -> Proveedor:
    prov = Proveedor(
        id=1,
        nombre="Proveedor Factura Docs",
        activo=True,
        origen=OrigenProveedor.ERP.value,
        supp_id=100,
    )
    db.add(prov)
    db.flush()
    return prov


def _pedido(
    db,
    empresa: Empresa,
    proveedor: Proveedor,
    user: Usuario,
    *,
    numero: str = "P-01-2026-00001",
    ct_transaction_id: int | None = None,
    facturas_documento: str | None = None,
) -> PedidoCompra:
    pedido = PedidoCompra(
        numero=numero,
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda="ARS",
        monto=Decimal("1000.00"),
        estado="borrador",
        creado_por_id=user.id,
        ct_transaction_id=ct_transaction_id,
        facturas_documento=facturas_documento,
    )
    db.add(pedido)
    db.flush()
    return pedido


@pytest.fixture
def con_permiso_gestionar_oc():
    def _fake(self, user, codigo):
        return codigo == "administracion.gestionar_ordenes_compra"

    with (
        patch(
            "app.services.permisos_service.PermisosService.tiene_permiso",
            new=_fake,
        ),
        patch(
            "app.services.permisos_service.PermisosService.obtener_permisos_usuario",
            return_value={"administracion.gestionar_ordenes_compra"},
        ),
    ):
        yield


# ──────────────────────────────────────────────────────────────────────────
# 1.1 Seed + cargada vs ERP + empty 422
# ──────────────────────────────────────────────────────────────────────────


class TestSeedFacturasDocumento:
    def test_semicolon_tokens_become_three_rows(self, db, empresa, proveedor, active_user) -> None:
        raw = "A-1; A-2; ;A-3"
        pedido = _pedido(
            db,
            empresa,
            proveedor,
            active_user,
            facturas_documento=raw,
        )
        rows = pedidos_service.seed_factura_documentos(db, pedido)
        db.flush()
        assert [row.numero for row in rows] == ["A-1", "A-2", "A-3"]
        persisted = (
            db.query(PedidoFacturaDocumento)
            .filter(PedidoFacturaDocumento.pedido_id == pedido.id)
            .order_by(PedidoFacturaDocumento.id)
            .all()
        )
        assert [row.numero for row in persisted] == ["A-1", "A-2", "A-3"]
        assert all(row.cargada is False for row in persisted)
        assert pedido.facturas_documento == raw

    def test_empty_or_separator_only_seeds_nothing(self, db, empresa, proveedor, active_user) -> None:
        pedido = _pedido(
            db,
            empresa,
            proveedor,
            active_user,
            facturas_documento=" ; ; ",
        )
        rows = pedidos_service.seed_factura_documentos(db, pedido)
        db.flush()
        assert rows == []
        assert db.query(PedidoFacturaDocumento).filter(PedidoFacturaDocumento.pedido_id == pedido.id).count() == 0

    def test_overflow_token_is_skipped_and_logged(self, db, empresa, proveedor, active_user, caplog) -> None:
        overflow = "X" * 101
        raw = f"A-1; {overflow}; A-2"
        pedido = _pedido(
            db,
            empresa,
            proveedor,
            active_user,
            facturas_documento=raw,
        )
        with caplog.at_level("WARNING"):
            rows = pedidos_service.seed_factura_documentos(db, pedido)
        db.flush()
        assert [row.numero for row in rows] == ["A-1", "A-2"]
        assert overflow not in {row.numero for row in rows}
        assert pedido.facturas_documento == raw
        assert any("overflow" in rec.message for rec in caplog.records)

    def test_casefold_duplicates_seed_one_row_first_seen_casing(self, db, empresa, proveedor, active_user) -> None:
        raw = "A-1; a-1; A-1"
        pedido = _pedido(
            db,
            empresa,
            proveedor,
            active_user,
            facturas_documento=raw,
        )
        rows = pedidos_service.seed_factura_documentos(db, pedido)
        db.flush()
        assert [row.numero for row in rows] == ["A-1"]
        assert db.query(PedidoFacturaDocumento).filter(PedidoFacturaDocumento.pedido_id == pedido.id).count() == 1
        assert pedido.facturas_documento == raw

    def test_existing_rows_are_not_reseeded(self, db, empresa, proveedor, active_user) -> None:
        pedido = _pedido(
            db,
            empresa,
            proveedor,
            active_user,
            facturas_documento="NEW-1; NEW-2",
        )
        first = PedidoFacturaDocumento(
            pedido_id=pedido.id,
            numero="KEEP-1",
            created_by_id=active_user.id,
        )
        db.add(first)
        db.flush()
        rows = pedidos_service.seed_factura_documentos(db, pedido)
        db.flush()
        assert [row.numero for row in rows] == ["KEEP-1"]
        assert db.query(PedidoFacturaDocumento).filter(PedidoFacturaDocumento.pedido_id == pedido.id).count() == 1

    def test_chips_batch_does_not_seed_text_only(self, db, empresa, proveedor, active_user) -> None:
        pedido = _pedido(
            db,
            empresa,
            proveedor,
            active_user,
            facturas_documento="FA-10",
        )
        chips = pedidos_service.chips_visibilidad_batch(db, [pedido.id])
        assert chips[pedido.id]["factura_cargada"] is False
        assert chips[pedido.id]["tiene_numero_factura"] is False
        assert db.query(PedidoFacturaDocumento).filter(PedidoFacturaDocumento.pedido_id == pedido.id).count() == 0


class TestPersistFacturaDocumento:
    def test_overflow_skip_logs_and_returns_none(self, db, empresa, proveedor, active_user, caplog) -> None:
        pedido = _pedido(db, empresa, proveedor, active_user)
        with caplog.at_level("WARNING"):
            row = pedidos_service.persist_factura_documento(
                db,
                pedido=pedido,
                numero="Y" * 101,
                created_by_id=active_user.id,
            )
        assert row is None
        assert db.query(PedidoFacturaDocumento).filter(PedidoFacturaDocumento.pedido_id == pedido.id).count() == 0
        assert any("overflow" in rec.message for rec in caplog.records)

    def test_casefold_duplicate_returns_existing(self, db, empresa, proveedor, active_user) -> None:
        pedido = _pedido(db, empresa, proveedor, active_user)
        first = pedidos_service.persist_factura_documento(
            db,
            pedido=pedido,
            numero="FA-10",
            created_by_id=active_user.id,
        )
        assert first is not None
        second = pedidos_service.persist_factura_documento(
            db,
            pedido=pedido,
            numero="fa-10",
            created_by_id=active_user.id,
        )
        assert second is not None
        assert second.id == first.id
        assert first.numero == "FA-10"
        assert first.cargada is False
        assert second.cargada is False
        assert db.query(PedidoFacturaDocumento).filter(PedidoFacturaDocumento.pedido_id == pedido.id).count() == 1


class TestPedidoFacturaUniqueConstraint:
    def test_model_declares_unique_pedido_id_numero(self) -> None:
        uniques = [c for c in PedidoFacturaDocumento.__table__.constraints if isinstance(c, UniqueConstraint)]
        cols = {tuple(col.name for col in c.columns) for c in uniques}
        assert ("pedido_id", "numero") in cols

    def test_exact_duplicate_raises_integrity_error(self, db, empresa, proveedor, active_user) -> None:
        pedido = _pedido(db, empresa, proveedor, active_user)
        db.add(
            PedidoFacturaDocumento(
                pedido_id=pedido.id,
                numero="FA-10",
                created_by_id=active_user.id,
            )
        )
        db.flush()
        db.add(
            PedidoFacturaDocumento(
                pedido_id=pedido.id,
                numero="FA-10",
                created_by_id=active_user.id,
            )
        )
        with pytest.raises(IntegrityError):
            db.flush()


class TestCompras044SeedRules:
    def test_migration_skips_overflow_casefold_and_unique(self) -> None:
        from pathlib import Path

        src = (
            Path(__file__).resolve().parents[2]
            / "alembic"
            / "versions"
            / "compras_044_pipeline_tipo_responsable_facturas.py"
        ).read_text(encoding="utf-8")
        assert "len(numero) > _FACTURA_NUMERO_MAX_LEN" in src
        assert "casefold()" in src
        assert "uq_pedido_factura_documentos_pedido_id_numero" in src
        assert "skip overflow" in src


class TestFacturaCargadaVsErp:
    def test_erp_link_without_rows_is_not_cargada(self, db, empresa, proveedor, active_user) -> None:
        pedido = _pedido(
            db,
            empresa,
            proveedor,
            active_user,
            ct_transaction_id=999001,
        )
        assert pedidos_service.es_factura_cargada(db, pedido.id) is False

    def test_row_is_constancia_not_cargada(self, db, empresa, proveedor, active_user) -> None:
        pedido = _pedido(db, empresa, proveedor, active_user, ct_transaction_id=None)
        row = pedidos_service.agregar_factura_documento(
            db,
            pedido_id=pedido.id,
            numero="FA-100",
            user_id=active_user.id,
        )
        db.flush()
        assert row.cargada is False
        assert pedidos_service.tiene_numero_factura(db, pedido.id) is True
        assert pedidos_service.es_factura_cargada(db, pedido.id) is False
        chips = pedidos_service.chips_visibilidad_batch(db, [pedido.id])
        assert chips[pedido.id]["tiene_numero_factura"] is True
        assert chips[pedido.id]["factura_cargada"] is False


class TestEmptyNumeroRejected:
    @pytest.mark.parametrize("numero", ["", "   ", "\t"])
    def test_empty_number_422_no_row_no_alert(
        self,
        db,
        empresa,
        proveedor,
        active_user,
        numero: str,
    ) -> None:
        pedido = _pedido(db, empresa, proveedor, active_user)
        with pytest.raises(HTTPException) as exc_info:
            pedidos_service.agregar_factura_documento(
                db,
                pedido_id=pedido.id,
                numero=numero,
                user_id=active_user.id,
            )
        assert exc_info.value.status_code == 422
        assert db.query(PedidoFacturaDocumento).filter(PedidoFacturaDocumento.pedido_id == pedido.id).count() == 0
        assert db.query(func.count(Notificacion.id)).scalar() == 0


# ──────────────────────────────────────────────────────────────────────────
# 1.3 tipo / responsable
# ──────────────────────────────────────────────────────────────────────────


class TestTipoYResponsable:
    def test_crear_pedido_defaults_tipo_mercaderia_and_responsable(self, db, empresa, proveedor, active_user) -> None:
        pedido = pedidos_service.crear_pedido(
            db,
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="ARS",
            monto=Decimal("2500.00"),
            creado_por_id=active_user.id,
        )
        assert pedido.tipo == "mercaderia"
        assert pedido.responsable_id == active_user.id

    def test_pm_cannot_patch_tipo_after_create(self, db, empresa, proveedor, active_user) -> None:
        pedido = pedidos_service.crear_pedido(
            db,
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="ARS",
            monto=Decimal("2500.00"),
            creado_por_id=active_user.id,
        )
        with pytest.raises(HTTPException) as exc_info:
            pedidos_service.editar_pedido(
                db,
                pedido_id=pedido.id,
                user_id=active_user.id,
                actor=active_user,
                tipo="servicio",
            )
        assert exc_info.value.status_code == 403
        db.refresh(pedido)
        assert pedido.tipo == "mercaderia"

    def test_admin_can_patch_tipo_after_create(self, db, empresa, proveedor, active_user, admin_user) -> None:
        pedido = pedidos_service.crear_pedido(
            db,
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="ARS",
            monto=Decimal("2500.00"),
            creado_por_id=active_user.id,
        )
        updated = pedidos_service.editar_pedido(
            db,
            pedido_id=pedido.id,
            user_id=admin_user.id,
            actor=admin_user,
            tipo="servicio",
        )
        assert updated.tipo == "servicio"

    def test_non_editor_cannot_change_responsable(self, db, empresa, proveedor, active_user, admin_user) -> None:
        pedido = pedidos_service.crear_pedido(
            db,
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="ARS",
            monto=Decimal("2500.00"),
            creado_por_id=admin_user.id,
        )
        assert active_user.rol == RolUsuario.VENTAS
        with pytest.raises(HTTPException) as exc_info:
            pedidos_service.editar_pedido(
                db,
                pedido_id=pedido.id,
                user_id=active_user.id,
                actor=active_user,
                responsable_id=active_user.id,
            )
        assert exc_info.value.status_code == 403


# ──────────────────────────────────────────────────────────────────────────
# 1.4 POST / DELETE routes
# ──────────────────────────────────────────────────────────────────────────


class TestFacturaDocumentoRoutes:
    def test_post_factura_201(
        self,
        client,
        db,
        empresa,
        proveedor,
        admin_user,
        admin_auth_headers,
        con_permiso_gestionar_oc,
    ) -> None:
        pedido = _pedido(db, empresa, proveedor, admin_user, numero="P-01-2026-00011")
        response = client.post(
            f"{BASE}/pedidos/{pedido.id}/factura-documentos",
            json={"numero": "FA-201"},
            headers=admin_auth_headers,
        )
        assert response.status_code == 201
        body = response.json()
        assert body["numero"] == "FA-201"
        assert body["pedido_id"] == pedido.id
        assert body["cargada"] is False
        assert pedidos_service.tiene_numero_factura(db, pedido.id) is True
        assert pedidos_service.es_factura_cargada(db, pedido.id) is False

    def test_undo_inside_five_minutes_204(
        self,
        client,
        db,
        empresa,
        proveedor,
        admin_user,
        admin_auth_headers,
        con_permiso_gestionar_oc,
    ) -> None:
        pedido = _pedido(db, empresa, proveedor, admin_user, numero="P-01-2026-00012")
        row = pedidos_service.agregar_factura_documento(
            db,
            pedido_id=pedido.id,
            numero="FA-204",
            user_id=admin_user.id,
        )
        row.created_at = datetime.now(timezone.utc) - timedelta(minutes=2)
        db.commit()
        db.refresh(row)
        response = client.delete(
            f"{BASE}/pedidos/{pedido.id}/factura-documentos/{row.id}",
            headers=admin_auth_headers,
        )
        assert response.status_code == 204
        assert db.get(PedidoFacturaDocumento, row.id) is None
        assert pedidos_service.es_factura_cargada(db, pedido.id) is False

    def test_undo_after_five_minutes_409(
        self,
        client,
        db,
        empresa,
        proveedor,
        admin_user,
        admin_auth_headers,
        con_permiso_gestionar_oc,
    ) -> None:
        pedido = _pedido(db, empresa, proveedor, admin_user, numero="P-01-2026-00013")
        row = pedidos_service.agregar_factura_documento(
            db,
            pedido_id=pedido.id,
            numero="FA-409",
            user_id=admin_user.id,
        )
        row.created_at = datetime.now(timezone.utc) - timedelta(minutes=6)
        db.commit()
        db.refresh(row)
        response = client.delete(
            f"{BASE}/pedidos/{pedido.id}/factura-documentos/{row.id}",
            headers=admin_auth_headers,
        )
        assert response.status_code == 409
        assert db.get(PedidoFacturaDocumento, row.id) is not None
        assert pedidos_service.tiene_numero_factura(db, pedido.id) is True
        assert pedidos_service.es_factura_cargada(db, pedido.id) is False

    def test_undo_uses_created_at_even_if_check_clock_differs(
        self,
        client,
        db,
        empresa,
        proveedor,
        admin_user,
        admin_auth_headers,
        con_permiso_gestionar_oc,
    ) -> None:
        t0 = datetime.now(timezone.utc)
        pedido = _pedido(db, empresa, proveedor, admin_user, numero="P-01-2026-00014")
        row = pedidos_service.agregar_factura_documento(
            db,
            pedido_id=pedido.id,
            numero="FA-CLOCK",
            user_id=admin_user.id,
        )
        row.created_at = t0 - timedelta(minutes=6)
        db.flush()
        pedidos_service.marcar_factura_cargada(
            db,
            pedido_id=pedido.id,
            row_id=row.id,
            cargada=True,
            user_id=admin_user.id,
            ahora=t0,
        )
        db.commit()
        db.refresh(row)
        assert row.cargada is True
        response = client.delete(
            f"{BASE}/pedidos/{pedido.id}/factura-documentos/{row.id}",
            headers=admin_auth_headers,
        )
        assert response.status_code == 409
        assert db.get(PedidoFacturaDocumento, row.id) is not None

    def test_uncheck_is_not_delete(
        self,
        db,
        empresa,
        proveedor,
        admin_user,
    ) -> None:
        t0 = datetime.now(timezone.utc)
        pedido = _pedido(db, empresa, proveedor, admin_user, numero="P-01-2026-00015")
        row = pedidos_service.agregar_factura_documento(
            db,
            pedido_id=pedido.id,
            numero="FA-KEEP",
            user_id=admin_user.id,
        )
        row.created_at = t0 - timedelta(minutes=2)
        db.flush()
        pedidos_service.marcar_factura_cargada(
            db,
            pedido_id=pedido.id,
            row_id=row.id,
            cargada=True,
            user_id=admin_user.id,
            ahora=t0,
        )
        db.flush()
        pedidos_service.marcar_factura_cargada(
            db,
            pedido_id=pedido.id,
            row_id=row.id,
            cargada=False,
            user_id=admin_user.id,
            ahora=t0 + timedelta(minutes=1),
        )
        db.flush()
        db.refresh(row)
        assert db.get(PedidoFacturaDocumento, row.id) is not None
        assert row.cargada is False
        pedidos_service.deshacer_factura_documento(
            db,
            pedido_id=pedido.id,
            row_id=row.id,
            ahora=t0 + timedelta(minutes=2),
        )
        db.flush()
        assert db.get(PedidoFacturaDocumento, row.id) is None


class TestMarcarFacturaCargada:
    def test_patch_check_starts_pending_window(
        self,
        client,
        db,
        empresa,
        proveedor,
        admin_user,
        admin_auth_headers,
        con_permiso_gestionar_oc,
    ) -> None:
        pedido = _pedido(db, empresa, proveedor, admin_user, numero="P-01-2026-00021")
        other = pedidos_service.agregar_factura_documento(
            db, pedido_id=pedido.id, numero="FA-11", user_id=admin_user.id
        )
        row = pedidos_service.agregar_factura_documento(db, pedido_id=pedido.id, numero="FA-10", user_id=admin_user.id)
        db.commit()
        response = client.patch(
            f"{BASE}/pedidos/{pedido.id}/factura-documentos/{row.id}",
            json={"cargada": True},
            headers=admin_auth_headers,
        )
        assert response.status_code == 200
        body = response.json()
        assert body["cargada"] is True
        assert body["cargada_marked_at"] is not None
        assert body["cargada_marked_by_id"] == admin_user.id
        db.refresh(row)
        db.refresh(other)
        assert row.cargada is True
        assert row.alerta_pendiente_hasta is not None
        assert row.alerta_pendiente_hasta == row.cargada_marked_at + pedidos_service.FACTURA_CARGADA_ALERT_DELAY
        assert other.cargada is False
        assert pedidos_service.es_factura_cargada(db, pedido.id) is True

    def test_patch_uncheck_clears_cargada_keeps_row(
        self,
        client,
        db,
        empresa,
        proveedor,
        admin_user,
        admin_auth_headers,
        con_permiso_gestionar_oc,
    ) -> None:
        pedido = _pedido(db, empresa, proveedor, admin_user, numero="P-01-2026-00022")
        row = pedidos_service.agregar_factura_documento(db, pedido_id=pedido.id, numero="FA-10", user_id=admin_user.id)
        db.commit()
        client.patch(
            f"{BASE}/pedidos/{pedido.id}/factura-documentos/{row.id}",
            json={"cargada": True},
            headers=admin_auth_headers,
        )
        response = client.patch(
            f"{BASE}/pedidos/{pedido.id}/factura-documentos/{row.id}",
            json={"cargada": False},
            headers=admin_auth_headers,
        )
        assert response.status_code == 200
        db.refresh(row)
        assert row.cargada is False
        assert row.alerta_pendiente_hasta is None
        assert db.get(PedidoFacturaDocumento, row.id) is not None
        assert pedidos_service.es_factura_cargada(db, pedido.id) is False
        assert pedidos_service.tiene_numero_factura(db, pedido.id) is True

    def test_idempotent_recheck_does_not_reset_timer(self, db, empresa, proveedor, admin_user) -> None:
        t0 = datetime(2026, 3, 10, 10, 0, tzinfo=timezone.utc)
        pedido = _pedido(db, empresa, proveedor, admin_user, numero="P-01-2026-00023")
        row = pedidos_service.agregar_factura_documento(db, pedido_id=pedido.id, numero="FA-10", user_id=admin_user.id)
        db.flush()
        first = pedidos_service.marcar_factura_cargada(
            db, pedido_id=pedido.id, row_id=row.id, cargada=True, user_id=admin_user.id, ahora=t0
        )
        marked_at = first.cargada_marked_at
        pending = first.alerta_pendiente_hasta
        second = pedidos_service.marcar_factura_cargada(
            db,
            pedido_id=pedido.id,
            row_id=row.id,
            cargada=True,
            user_id=admin_user.id,
            ahora=t0 + timedelta(minutes=1),
        )
        assert second.cargada_marked_at == marked_at
        assert second.alerta_pendiente_hasta == pending

    def test_recheck_after_uncheck_starts_new_window(self, db, empresa, proveedor, admin_user) -> None:
        t0 = datetime(2026, 3, 10, 10, 0, tzinfo=timezone.utc)
        t1 = t0 + timedelta(minutes=10)
        pedido = _pedido(db, empresa, proveedor, admin_user, numero="P-01-2026-00024")
        row = pedidos_service.agregar_factura_documento(db, pedido_id=pedido.id, numero="FA-10", user_id=admin_user.id)
        db.flush()
        pedidos_service.marcar_factura_cargada(
            db, pedido_id=pedido.id, row_id=row.id, cargada=True, user_id=admin_user.id, ahora=t0
        )
        pedidos_service.marcar_factura_cargada(
            db,
            pedido_id=pedido.id,
            row_id=row.id,
            cargada=False,
            user_id=admin_user.id,
            ahora=t0 + timedelta(minutes=2),
        )
        again = pedidos_service.marcar_factura_cargada(
            db, pedido_id=pedido.id, row_id=row.id, cargada=True, user_id=admin_user.id, ahora=t1
        )
        assert again.cargada_marked_at == t1
        assert again.alerta_pendiente_hasta == t1 + pedidos_service.FACTURA_CARGADA_ALERT_DELAY
        assert again.alerta_disparada_at is None

    def test_patch_without_permission_403(
        self,
        client,
        db,
        empresa,
        proveedor,
        admin_user,
        auth_headers,
    ) -> None:
        pedido = _pedido(db, empresa, proveedor, admin_user, numero="P-01-2026-00025")
        row = pedidos_service.agregar_factura_documento(db, pedido_id=pedido.id, numero="FA-10", user_id=admin_user.id)
        db.commit()
        response = client.patch(
            f"{BASE}/pedidos/{pedido.id}/factura-documentos/{row.id}",
            json={"cargada": True},
            headers=auth_headers,
        )
        assert response.status_code == 403
        db.refresh(row)
        assert row.cargada is False

    def test_patch_missing_row_404(
        self,
        client,
        db,
        empresa,
        proveedor,
        admin_user,
        admin_auth_headers,
        con_permiso_gestionar_oc,
    ) -> None:
        pedido = _pedido(db, empresa, proveedor, admin_user, numero="P-01-2026-00026")
        db.commit()
        response = client.patch(
            f"{BASE}/pedidos/{pedido.id}/factura-documentos/999001",
            json={"cargada": True},
            headers=admin_auth_headers,
        )
        assert response.status_code == 404
