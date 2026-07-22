"""
Integration tests — GET /api/items-sin-mla/anomalias-vinculadas
(productos-catalog-family-tree closing slice: anomaly-review tab).

Surfaces the ML publication-link anomalies that PR2's tree assembly SKIPS —
stock-synced vinculada edges that are cross-item (related MLA lives under a
different ERP item_id) or unresolvable (related MLA absent from
publicaciones_ml) — so the team can review and correct the underlying
mispublication.

TDD order: gate + happy-path (RED) -> endpoint (GREEN).
"""

from __future__ import annotations

import pytest

from app.core.security import create_access_token, get_password_hash
from app.models.ml_item_relation import MlItemRelation
from app.models.permiso import Permiso
from app.models.producto import ProductoERP
from app.models.publicacion_ml import PublicacionML
from app.models.rol import Rol
from app.models.usuario import AuthProvider, RolUsuario, Usuario

ENDPOINT = "/api/items-sin-mla/anomalias-vinculadas"


def _bearer(user: Usuario) -> dict[str, str]:
    token = create_access_token(data={"sub": user.username})
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def admin_rol(db) -> Rol:
    rol = Rol(codigo="ADMIN_ANOM", nombre="Admin Anomalias", es_sistema=False, orden=98, activo=True)
    db.add(rol)
    db.flush()
    return rol


@pytest.fixture()
def perm_ver_anomalias(db) -> Permiso:
    p = Permiso(
        codigo="admin.ver_anomalias_vinculadas",
        nombre="Ver anomalías vinculadas",
        descripcion="Ver publicaciones vinculadas con item_id cruzado o irresolubles",
        categoria="administracion",
        orden=62,
        es_critico=False,
    )
    db.add(p)
    db.flush()
    return p


@pytest.fixture()
def user_no_perm(db, admin_rol) -> Usuario:
    user = Usuario(
        username="anom_no_perm",
        email="anom_no_perm@test.com",
        nombre="No Perm",
        password_hash=get_password_hash("Pass123!"),
        rol=RolUsuario.VENTAS,
        rol_id=admin_rol.id,
        auth_provider=AuthProvider.LOCAL,
        activo=True,
    )
    db.add(user)
    db.flush()
    return user


@pytest.fixture()
def user_with_perm(db, admin_rol, perm_ver_anomalias) -> Usuario:
    from app.models.permiso import UsuarioPermisoOverride

    user = Usuario(
        username="anom_with_perm",
        email="anom_with_perm@test.com",
        nombre="With Perm",
        password_hash=get_password_hash("Pass123!"),
        rol=RolUsuario.VENTAS,
        rol_id=admin_rol.id,
        auth_provider=AuthProvider.LOCAL,
        activo=True,
    )
    db.add(user)
    db.flush()

    override = UsuarioPermisoOverride(usuario_id=user.id, permiso_id=perm_ver_anomalias.id, concedido=True)
    db.add(override)
    db.flush()
    return user


def _seed_producto(db, item_id: int, codigo: str, descripcion: str, marca: str) -> None:
    db.add(ProductoERP(item_id=item_id, codigo=codigo, descripcion=descripcion, marca=marca, activo=True))
    db.flush()


class TestPermissionGate:
    def test_unauthenticated_returns_401_or_403(self, client) -> None:
        response = client.get(ENDPOINT)
        assert response.status_code in (401, 403)

    def test_no_permission_returns_403(self, client, user_no_perm) -> None:
        response = client.get(ENDPOINT, headers=_bearer(user_no_perm))
        assert response.status_code == 403

    def test_with_permission_returns_200(self, client, user_with_perm) -> None:
        response = client.get(ENDPOINT, headers=_bearer(user_with_perm))
        assert response.status_code == 200


class TestAnomaliesPayload:
    def test_cross_item_anomaly_enriched_with_source_product(self, db, client, user_with_perm) -> None:
        _seed_producto(db, 2905, "COD2905", "Producto fuente", "MarcaX")
        _seed_producto(db, 3271, "COD3271", "Producto relacionado", "MarcaY")
        db.add(PublicacionML(mla="MLA2068711536", item_id=2905))
        db.add(PublicacionML(mla="MLA1493337181", item_id=3271))
        db.add(MlItemRelation(mla="MLA2068711536", related_mla="MLA1493337181", stock_relation=1))
        db.commit()

        response = client.get(ENDPOINT, headers=_bearer(user_with_perm))
        assert response.status_code == 200
        body = response.json()
        assert len(body) == 1
        row = body[0]
        assert row["mla"] == "MLA2068711536"
        assert row["item_id"] == 2905
        assert row["codigo"] == "COD2905"
        assert row["descripcion"] == "Producto fuente"
        assert row["marca"] == "MarcaX"
        assert row["related_mla"] == "MLA1493337181"
        assert row["related_item_id"] == 3271
        assert row["reason"] == "cross_item"
        assert row["stock_relation"] == 1

    def test_unresolvable_source_mla_item_id_none_does_not_500(self, db, client, user_with_perm) -> None:
        # The SOURCE mla itself is absent from publicaciones_ml (orphaned edge),
        # so its item_id resolves to None. The whole endpoint must NOT 500 on
        # serialization — item_id is Optional and the row is returned with null.
        db.add(MlItemRelation(mla="MLA_ORPHAN_SRC", related_mla="MLA_SOMEWHERE", stock_relation=1))
        db.commit()

        response = client.get(ENDPOINT, headers=_bearer(user_with_perm))
        assert response.status_code == 200
        body = response.json()
        assert len(body) == 1
        assert body[0]["mla"] == "MLA_ORPHAN_SRC"
        assert body[0]["item_id"] is None
        assert body[0]["reason"] == "unresolvable"

    def test_unresolvable_anomaly_has_related_item_id_none(self, db, client, user_with_perm) -> None:
        _seed_producto(db, 100, "COD100", "Producto", "Marca")
        db.add(PublicacionML(mla="MLA2374249178", item_id=100))
        db.add(MlItemRelation(mla="MLA2374249178", related_mla="MLA3100873948", stock_relation=1))
        db.commit()

        response = client.get(ENDPOINT, headers=_bearer(user_with_perm))
        assert response.status_code == 200
        body = response.json()
        assert len(body) == 1
        assert body[0]["reason"] == "unresolvable"
        assert body[0]["related_item_id"] is None

    def test_same_item_edge_not_returned(self, db, client, user_with_perm) -> None:
        _seed_producto(db, 100, "COD100", "Producto", "Marca")
        db.add(PublicacionML(mla="MLA_A", item_id=100))
        db.add(PublicacionML(mla="MLA_B", item_id=100))
        db.add(MlItemRelation(mla="MLA_A", related_mla="MLA_B", stock_relation=1))
        db.commit()

        response = client.get(ENDPOINT, headers=_bearer(user_with_perm))
        assert response.status_code == 200
        assert response.json() == []

    def test_no_edges_returns_empty_list(self, client, user_with_perm) -> None:
        response = client.get(ENDPOINT, headers=_bearer(user_with_perm))
        assert response.status_code == 200
        assert response.json() == []
