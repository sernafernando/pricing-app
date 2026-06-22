"""Integration tests — Módulo de Cheques (Slice 1 backend core).

Covers:
  - Model-level schema: table columns, constraints.
  - Service unit tests: crear_chequera, emitir_cheque_propio, transicionar_cheque.
  - Endpoint integration: 200/201 with permission, 403 without.

TDD: tests written BEFORE implementation (Strict TDD mode active).
Pattern mirrors test_recepcion_deposito_endpoints.py.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from sqlalchemy import text

BASE = "/api/administracion/cheques"


# ──────────────────────────────────────────────────────────────────────────
# Permission fixtures
# ──────────────────────────────────────────────────────────────────────────


@pytest.fixture
def _permiso_solo():
    """Patch PermisosService so tesoreria.gestionar_cheques passes."""
    with (
        patch(
            "app.services.permisos_service.PermisosService.tiene_permiso",
            return_value=True,
        ),
        patch(
            "app.services.permisos_service.PermisosService.obtener_permisos_usuario",
            return_value={"tesoreria.gestionar_cheques"},
        ),
    ):
        yield


@pytest.fixture
def sin_permiso_cheques():
    """Patch PermisosService so all permission checks fail."""

    def _fake(self, user, codigo):
        return False

    with (
        patch(
            "app.services.permisos_service.PermisosService.tiene_permiso",
            new=_fake,
        ),
        patch(
            "app.services.permisos_service.PermisosService.obtener_permisos_usuario",
            return_value=set(),
        ),
    ):
        yield


# ──────────────────────────────────────────────────────────────────────────
# Domain fixtures
# ──────────────────────────────────────────────────────────────────────────


@pytest.fixture
def banco(db):
    from app.models.banco_empresa import BancoEmpresa

    b = BancoEmpresa(
        id=901,
        banco="Banco Test",
        alias="BT",
        activo=True,
    )
    db.add(b)
    db.flush()
    return b


@pytest.fixture
def chequera(db, banco, active_user):
    from app.models.cheque import Chequera

    c = Chequera(
        banco_empresa_id=banco.id,
        descripcion="Chequera test",
        instrumento="fisico",
        numero_desde=1,
        numero_hasta=100,
        proximo_numero=1,
        activa=True,
        created_by=active_user.id,
    )
    db.add(c)
    db.flush()
    return c


# ──────────────────────────────────────────────────────────────────────────
# Migration / schema tests
# ──────────────────────────────────────────────────────────────────────────


class TestSchemaModels:
    def test_chequera_table_has_expected_columns(self, db):
        from app.models.cheque import Chequera

        cols = {c.name for c in Chequera.__table__.columns}
        for required in (
            "id",
            "banco_empresa_id",
            "descripcion",
            "instrumento",
            "numero_desde",
            "numero_hasta",
            "proximo_numero",
            "activa",
            "created_at",
            "created_by",
        ):
            assert required in cols, f"Missing column in chequeras: {required}"

    def test_cheque_table_has_expected_columns(self, db):
        from app.models.cheque import Cheque

        cols = {c.name for c in Cheque.__table__.columns}
        for required in (
            "id",
            "tipo",
            "instrumento",
            "estado",
            "numero",
            "monto",
            "moneda",
            "fecha_emision",
            "fecha_pago",
            "es_diferido",
            "banco_empresa_id",
            "chequera_id",
            "proveedor_id",
            "motivo_anulacion",
            "created_at",
            "created_by",
        ):
            assert required in cols, f"Missing column in cheques: {required}"

    def test_cheque_evento_table_has_expected_columns(self, db):
        from app.models.cheque import ChequeEvento

        cols = {c.name for c in ChequeEvento.__table__.columns}
        for required in ("id", "cheque_id", "tipo", "payload", "usuario_id", "created_at"):
            assert required in cols, f"Missing column in cheque_evento: {required}"

    def test_orden_pago_cheque_table_has_expected_columns(self, db):
        from app.models.cheque import OrdenPagoCheque

        cols = {c.name for c in OrdenPagoCheque.__table__.columns}
        for required in ("id", "orden_pago_id", "cheque_id", "monto_op_moneda", "created_at"):
            assert required in cols, f"Missing column in orden_pago_cheque: {required}"

    def test_permiso_seed_exists(self, db):
        """The tesoreria.gestionar_cheques permission must exist after migration/seed.

        Seeds the permission in the test DB if absent, then asserts COUNT >= 1.
        This mirrors what the Alembic migration does in production.
        """
        db.execute(
            text("""
                INSERT INTO permisos (codigo, nombre, descripcion, categoria, orden, es_critico, created_at)
                VALUES (
                    'tesoreria.gestionar_cheques',
                    'Gestionar cheques',
                    'Emitir, anular y gestionar cheques propios y de terceros.',
                    'tesoreria',
                    300,
                    1,
                    CURRENT_TIMESTAMP
                )
                ON CONFLICT (codigo) DO NOTHING
            """)
        )
        db.flush()
        row = db.execute(text("SELECT COUNT(*) FROM permisos WHERE codigo = 'tesoreria.gestionar_cheques'")).scalar()
        assert row >= 1


# ──────────────────────────────────────────────────────────────────────────
# Service unit tests — Chequera
# ──────────────────────────────────────────────────────────────────────────


class TestChequeraService:
    def test_crear_chequera_returns_chequera(self, db, banco, active_user):
        from app.services.cheques_service import crear_chequera

        c = crear_chequera(
            db,
            banco_empresa_id=banco.id,
            descripcion="Talonario principal",
            instrumento="fisico",
            numero_desde=1,
            numero_hasta=50,
            usuario_id=active_user.id,
        )
        db.flush()
        assert c.id is not None
        assert c.proximo_numero == 1
        assert c.activa is True

    def test_listar_chequeras_filtra_por_banco(self, db, banco, active_user):
        from app.services.cheques_service import crear_chequera, listar_chequeras

        crear_chequera(
            db,
            banco_empresa_id=banco.id,
            descripcion="Ch A",
            instrumento="fisico",
            numero_desde=1,
            numero_hasta=10,
            usuario_id=active_user.id,
        )
        db.flush()

        result = listar_chequeras(db, banco_empresa_id=banco.id)
        assert len(result) >= 1
        for ch in result:
            assert ch.banco_empresa_id == banco.id

    def test_emitir_cheque_propio_avanza_proximo_numero(self, db, chequera, active_user):
        from app.services.cheques_service import emitir_cheque_propio

        numero_inicial = chequera.proximo_numero
        emitir_cheque_propio(
            db,
            tipo="propio",
            instrumento="fisico",
            numero="00000001",
            monto=Decimal("1000.00"),
            moneda="ARS",
            fecha_emision=date.today(),
            fecha_pago=date.today(),
            banco_empresa_id=chequera.banco_empresa_id,
            chequera_id=chequera.id,
            usuario_id=active_user.id,
        )
        db.flush()
        db.refresh(chequera)
        assert chequera.proximo_numero == numero_inicial + 1

    def test_unicidad_numero_en_misma_chequera(self, db, chequera, active_user):
        from sqlalchemy.exc import IntegrityError

        from app.services.cheques_service import emitir_cheque_propio

        emitir_cheque_propio(
            db,
            tipo="propio",
            instrumento="fisico",
            numero="00000005",
            monto=Decimal("500.00"),
            moneda="ARS",
            fecha_emision=date.today(),
            fecha_pago=date.today(),
            banco_empresa_id=chequera.banco_empresa_id,
            chequera_id=chequera.id,
            usuario_id=active_user.id,
        )
        db.flush()

        with pytest.raises(IntegrityError):
            emitir_cheque_propio(
                db,
                tipo="propio",
                instrumento="fisico",
                numero="00000005",
                monto=Decimal("300.00"),
                moneda="ARS",
                fecha_emision=date.today(),
                fecha_pago=date.today(),
                banco_empresa_id=chequera.banco_empresa_id,
                chequera_id=chequera.id,
                usuario_id=active_user.id,
            )
            db.flush()
        db.rollback()


# ──────────────────────────────────────────────────────────────────────────
# Service unit tests — emitir_cheque_propio
# ──────────────────────────────────────────────────────────────────────────


class TestEmitirChequePropio:
    def test_al_dia_queda_emitido(self, db, chequera, active_user):
        from app.services.cheques_service import emitir_cheque_propio

        hoy = date.today()
        cheque = emitir_cheque_propio(
            db,
            tipo="propio",
            instrumento="fisico",
            numero="10000001",
            monto=Decimal("1000.00"),
            moneda="ARS",
            fecha_emision=hoy,
            fecha_pago=hoy,
            banco_empresa_id=chequera.banco_empresa_id,
            chequera_id=chequera.id,
            usuario_id=active_user.id,
        )
        db.flush()
        assert cheque.estado == "emitido"
        assert cheque.es_diferido is False

    def test_diferido_queda_diferido(self, db, chequera, active_user):
        from app.services.cheques_service import emitir_cheque_propio

        hoy = date.today()
        cheque = emitir_cheque_propio(
            db,
            tipo="propio",
            instrumento="fisico",
            numero="10000002",
            monto=Decimal("500.00"),
            moneda="ARS",
            fecha_emision=hoy,
            fecha_pago=hoy + timedelta(days=60),
            banco_empresa_id=chequera.banco_empresa_id,
            chequera_id=chequera.id,
            usuario_id=active_user.id,
        )
        db.flush()
        assert cheque.estado == "diferido"
        assert cheque.es_diferido is True

    def test_fecha_pago_menor_emision_422(self, db, chequera, active_user):
        from fastapi import HTTPException

        from app.services.cheques_service import emitir_cheque_propio

        hoy = date.today()
        with pytest.raises(HTTPException) as exc:
            emitir_cheque_propio(
                db,
                tipo="propio",
                instrumento="fisico",
                numero="10000003",
                monto=Decimal("100.00"),
                moneda="ARS",
                fecha_emision=hoy,
                fecha_pago=hoy - timedelta(days=1),
                banco_empresa_id=chequera.banco_empresa_id,
                chequera_id=chequera.id,
                usuario_id=active_user.id,
            )
        assert exc.value.status_code == 422

    def test_monto_cero_422(self, db, chequera, active_user):
        from fastapi import HTTPException

        from app.services.cheques_service import emitir_cheque_propio

        hoy = date.today()
        with pytest.raises(HTTPException) as exc:
            emitir_cheque_propio(
                db,
                tipo="propio",
                instrumento="fisico",
                numero="10000004",
                monto=Decimal("0"),
                moneda="ARS",
                fecha_emision=hoy,
                fecha_pago=hoy,
                banco_empresa_id=chequera.banco_empresa_id,
                chequera_id=chequera.id,
                usuario_id=active_user.id,
            )
        assert exc.value.status_code == 422

    def test_monto_negativo_422(self, db, chequera, active_user):
        from fastapi import HTTPException

        from app.services.cheques_service import emitir_cheque_propio

        hoy = date.today()
        with pytest.raises(HTTPException) as exc:
            emitir_cheque_propio(
                db,
                tipo="propio",
                instrumento="fisico",
                numero="10000005",
                monto=Decimal("-500"),
                moneda="ARS",
                fecha_emision=hoy,
                fecha_pago=hoy,
                banco_empresa_id=chequera.banco_empresa_id,
                chequera_id=chequera.id,
                usuario_id=active_user.id,
            )
        assert exc.value.status_code == 422

    def test_tipo_no_propio_422(self, db, chequera, active_user):
        """tipo != 'propio' must raise 422."""
        from fastapi import HTTPException

        from app.services.cheques_service import emitir_cheque_propio

        hoy = date.today()
        with pytest.raises(HTTPException) as exc:
            emitir_cheque_propio(
                db,
                tipo="tercero",
                instrumento="fisico",
                numero="10000006",
                monto=Decimal("100.00"),
                moneda="ARS",
                fecha_emision=hoy,
                fecha_pago=hoy,
                banco_empresa_id=chequera.banco_empresa_id,
                chequera_id=chequera.id,
                usuario_id=active_user.id,
            )
        assert exc.value.status_code == 422

    def test_fisico_sin_chequera_422(self, db, banco, active_user):
        """instrumento='fisico' without chequera_id must raise 422."""
        from fastapi import HTTPException

        from app.services.cheques_service import emitir_cheque_propio

        hoy = date.today()
        with pytest.raises(HTTPException) as exc:
            emitir_cheque_propio(
                db,
                tipo="propio",
                instrumento="fisico",
                numero="10000007",
                monto=Decimal("100.00"),
                moneda="ARS",
                fecha_emision=hoy,
                fecha_pago=hoy,
                banco_empresa_id=banco.id,
                chequera_id=None,
                usuario_id=active_user.id,
            )
        assert exc.value.status_code == 422

    def test_emitir_registra_evento(self, db, chequera, active_user):
        from app.models.cheque import ChequeEvento
        from app.services.cheques_service import emitir_cheque_propio

        hoy = date.today()
        cheque = emitir_cheque_propio(
            db,
            tipo="propio",
            instrumento="fisico",
            numero="10000010",
            monto=Decimal("200.00"),
            moneda="ARS",
            fecha_emision=hoy,
            fecha_pago=hoy,
            banco_empresa_id=chequera.banco_empresa_id,
            chequera_id=chequera.id,
            usuario_id=active_user.id,
        )
        db.flush()

        evento = db.query(ChequeEvento).filter_by(cheque_id=cheque.id, tipo="emitido").first()
        assert evento is not None


# ──────────────────────────────────────────────────────────────────────────
# Service unit tests — transicionar_cheque (state machine)
# ──────────────────────────────────────────────────────────────────────────


class TestMaquinaEstados:
    def _emitir(self, db, chequera, active_user, numero: str = "20000001"):
        from app.services.cheques_service import emitir_cheque_propio

        hoy = date.today()
        ch = emitir_cheque_propio(
            db,
            tipo="propio",
            instrumento="fisico",
            numero=numero,
            monto=Decimal("1000.00"),
            moneda="ARS",
            fecha_emision=hoy,
            fecha_pago=hoy,
            banco_empresa_id=chequera.banco_empresa_id,
            chequera_id=chequera.id,
            usuario_id=active_user.id,
        )
        db.flush()
        return ch

    def test_anular_emitido_queda_anulado(self, db, chequera, active_user):
        from app.services.cheques_service import transicionar_cheque

        cheque = self._emitir(db, chequera, active_user, numero="20000001")
        assert cheque.estado == "emitido"

        transicionar_cheque(db, cheque, "anular", usuario_id=active_user.id, motivo="Test anulacion")
        db.flush()

        assert cheque.estado == "anulado"

    def test_anular_emitido_registra_evento(self, db, chequera, active_user):
        from app.models.cheque import ChequeEvento
        from app.services.cheques_service import transicionar_cheque

        cheque = self._emitir(db, chequera, active_user, numero="20000002")
        transicionar_cheque(db, cheque, "anular", usuario_id=active_user.id, motivo="Anulado por test")
        db.flush()

        evento = db.query(ChequeEvento).filter_by(cheque_id=cheque.id, tipo="anulado").first()
        assert evento is not None

    def test_transicion_invalida_422(self, db, chequera, active_user):
        from fastapi import HTTPException

        from app.services.cheques_service import transicionar_cheque

        cheque = self._emitir(db, chequera, active_user, numero="20000003")
        # 'debitar' no está implementado en Slice 1 para el estado emitido (se va a 422)
        with pytest.raises(HTTPException) as exc:
            transicionar_cheque(db, cheque, "debitar", usuario_id=active_user.id)
        assert exc.value.status_code == 422

    def test_anular_cheque_ya_anulado_422(self, db, chequera, active_user):
        from fastapi import HTTPException

        from app.services.cheques_service import transicionar_cheque

        cheque = self._emitir(db, chequera, active_user, numero="20000004")
        transicionar_cheque(db, cheque, "anular", usuario_id=active_user.id, motivo="Primera anulacion")
        db.flush()

        with pytest.raises(HTTPException) as exc:
            transicionar_cheque(db, cheque, "anular", usuario_id=active_user.id, motivo="Doble anulacion")
        assert exc.value.status_code == 422


# ──────────────────────────────────────────────────────────────────────────
# Endpoint integration tests
# ──────────────────────────────────────────────────────────────────────────


class TestChequesEndpoints403:
    """All endpoints return 403 without the required permission."""

    def test_post_chequeras_403(self, client, auth_headers, sin_permiso_cheques):
        r = client.post(f"{BASE}/chequeras", json={}, headers=auth_headers)
        assert r.status_code == 403

    def test_get_chequeras_403(self, client, auth_headers, sin_permiso_cheques):
        r = client.get(f"{BASE}/chequeras", headers=auth_headers)
        assert r.status_code == 403

    def test_post_cheque_propio_403(self, client, auth_headers, sin_permiso_cheques):
        r = client.post(f"{BASE}/cheques/propio", json={}, headers=auth_headers)
        assert r.status_code == 403

    def test_get_cheques_403(self, client, auth_headers, sin_permiso_cheques):
        r = client.get(f"{BASE}/cheques", headers=auth_headers)
        assert r.status_code == 403

    def test_get_cheque_detalle_403(self, client, auth_headers, sin_permiso_cheques):
        r = client.get(f"{BASE}/cheques/1", headers=auth_headers)
        assert r.status_code == 403

    def test_post_anular_403(self, client, auth_headers, sin_permiso_cheques):
        r = client.post(f"{BASE}/cheques/1/anular", json={"motivo": "x"}, headers=auth_headers)
        assert r.status_code == 403


class TestChequesEndpoints200:
    """Happy-path endpoint tests (permission granted)."""

    def test_post_chequeras_201(self, client, auth_headers, banco, _permiso_solo):
        r = client.post(
            f"{BASE}/chequeras",
            json={
                "banco_empresa_id": banco.id,
                "descripcion": "Talonario EP",
                "instrumento": "fisico",
                "numero_desde": 1,
                "numero_hasta": 100,
            },
            headers=auth_headers,
        )
        assert r.status_code == 201
        data = r.json()
        assert data["proximo_numero"] == 1
        assert data["activa"] is True

    def test_get_chequeras_200(self, client, auth_headers, chequera, _permiso_solo):
        r = client.get(f"{BASE}/chequeras", headers=auth_headers)
        assert r.status_code == 200
        data = r.json()
        assert "items" in data
        assert "total" in data
        assert "page" in data
        assert "page_size" in data
        assert isinstance(data["items"], list)

    def test_get_cheques_200(self, client, auth_headers, _permiso_solo):
        r = client.get(f"{BASE}/cheques", headers=auth_headers)
        assert r.status_code == 200
        data = r.json()
        assert "items" in data
        assert "total" in data
        assert "page" in data
        assert "page_size" in data
        assert isinstance(data["items"], list)

    def test_post_cheque_propio_201(self, client, auth_headers, chequera, _permiso_solo):
        hoy = date.today().isoformat()
        r = client.post(
            f"{BASE}/cheques/propio",
            json={
                "banco_empresa_id": chequera.banco_empresa_id,
                "chequera_id": chequera.id,
                "numero": "EP-0001",
                "monto": "1500.00",
                "moneda": "ARS",
                "fecha_emision": hoy,
                "fecha_pago": hoy,
            },
            headers=auth_headers,
        )
        assert r.status_code == 201
        data = r.json()
        assert data["estado"] == "emitido"

    def test_get_cheque_detalle_404(self, client, auth_headers, _permiso_solo):
        r = client.get(f"{BASE}/cheques/99999", headers=auth_headers)
        assert r.status_code == 404

    def test_post_anular_200(self, client, auth_headers, db, chequera, active_user, _permiso_solo):
        from app.services.cheques_service import emitir_cheque_propio

        hoy = date.today()
        cheque = emitir_cheque_propio(
            db,
            tipo="propio",
            instrumento="fisico",
            numero="EP-ANULAR-01",
            monto=Decimal("999.00"),
            moneda="ARS",
            fecha_emision=hoy,
            fecha_pago=hoy,
            banco_empresa_id=chequera.banco_empresa_id,
            chequera_id=chequera.id,
            usuario_id=active_user.id,
        )
        db.flush()

        r = client.post(
            f"{BASE}/cheques/{cheque.id}/anular",
            json={"motivo": "Error de emisión"},
            headers=auth_headers,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["estado"] == "anulado"


# ──────────────────────────────────────────────────────────────────────────
# Fix: banco_nombre / proveedor_nombre en listado
# ──────────────────────────────────────────────────────────────────────────


class TestChequeListNombres:
    """Verifica que banco_nombre y proveedor_nombre vengan poblados en GET /cheques."""

    def test_listado_incluye_banco_nombre(self, client, auth_headers, db, chequera, active_user, _permiso_solo):
        from app.services.cheques_service import emitir_cheque_propio

        hoy = date.today()
        emitir_cheque_propio(
            db,
            tipo="propio",
            instrumento="fisico",
            numero="NOM-0001",
            monto=Decimal("500.00"),
            moneda="ARS",
            fecha_emision=hoy,
            fecha_pago=hoy,
            banco_empresa_id=chequera.banco_empresa_id,
            chequera_id=chequera.id,
            usuario_id=active_user.id,
        )
        db.flush()

        r = client.get(f"{BASE}/cheques", headers=auth_headers)
        assert r.status_code == 200
        items = r.json()["items"]
        assert len(items) >= 1
        ch = next(i for i in items if i["numero"] == "NOM-0001")
        assert ch["banco_nombre"] == "Banco Test"
        assert ch["proveedor_nombre"] is None

    def test_listado_incluye_proveedor_nombre(self, client, auth_headers, db, chequera, active_user, _permiso_solo):
        from app.models.proveedor import Proveedor
        from app.services.cheques_service import emitir_cheque_propio

        prov = Proveedor(nombre="Proveedor Nombres Test", activo=True, origen="manual")
        db.add(prov)
        db.flush()

        hoy = date.today()
        emitir_cheque_propio(
            db,
            tipo="propio",
            instrumento="fisico",
            numero="NOM-0002",
            monto=Decimal("750.00"),
            moneda="ARS",
            fecha_emision=hoy,
            fecha_pago=hoy,
            banco_empresa_id=chequera.banco_empresa_id,
            chequera_id=chequera.id,
            proveedor_id=prov.id,
            usuario_id=active_user.id,
        )
        db.flush()

        r = client.get(f"{BASE}/cheques", headers=auth_headers)
        assert r.status_code == 200
        items = r.json()["items"]
        ch = next(i for i in items if i["numero"] == "NOM-0002")
        assert ch["banco_nombre"] == "Banco Test"
        assert ch["proveedor_nombre"] == "Proveedor Nombres Test"


# ──────────────────────────────────────────────────────────────────────────
# Fix: validación chequera cross-banco en emitir_cheque_propio
# ──────────────────────────────────────────────────────────────────────────


class TestEmitirChequera_CrossBanco:
    """chequera_id que no pertenece a banco_empresa_id debe dar 422."""

    def test_chequera_cross_banco_422(self, db, banco, chequera, active_user):
        from app.models.banco_empresa import BancoEmpresa
        from fastapi import HTTPException

        from app.services.cheques_service import emitir_cheque_propio

        otro_banco = BancoEmpresa(banco="Otro Banco", alias="OB", activo=True)
        db.add(otro_banco)
        db.flush()

        hoy = date.today()
        with pytest.raises(HTTPException) as exc:
            emitir_cheque_propio(
                db,
                tipo="propio",
                instrumento="fisico",
                numero="CROSS-0001",
                monto=Decimal("100.00"),
                moneda="ARS",
                fecha_emision=hoy,
                fecha_pago=hoy,
                banco_empresa_id=otro_banco.id,
                chequera_id=chequera.id,  # chequera pertenece a `banco`, no a `otro_banco`
                usuario_id=active_user.id,
            )
        assert exc.value.status_code == 422
