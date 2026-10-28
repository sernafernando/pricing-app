"""
GET /productos/{id}/mercadolibre/tree requires any of PERMISOS_PUBLICACIONES_ML
(productos.ver or ml_ops.ver): the permission of each screen that reads it.
Productos' expandable publication rows and the Publicaciones ML product panel
both mount ProductoMLAsPanel, which loads this tree.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.models.permiso import Permiso, UsuarioPermisoOverride
from app.models.producto import ProductoERP
from app.models.publicacion_ml import PublicacionML
from tests.conftest import make_access_token

VER = "productos.ver"
ML_OPS_VER = "ml_ops.ver"


@pytest.fixture()
def publicacion(db) -> None:
    db.add(ProductoERP(item_id=9301, codigo="TREE-001", descripcion="Producto árbol"))
    db.flush()
    db.add(PublicacionML(mla="MLA9301", item_id=9301, pricelist_id=4, activo=True))
    db.commit()


def _get(client, user):
    with patch("app.api.endpoints.productos_detail.sync_links_from_store"):
        return client.get(
            "/api/productos/9301/mercadolibre/tree",
            headers={"Authorization": f"Bearer {make_access_token(user)}"},
        )


def _assert_tree(response) -> None:
    assert response.status_code == 200, response.text
    assert [child["mla"] for child in response.json()["tree"]["children"]] == ["MLA9301"]


def _assert_forbidden(response) -> None:
    assert response.status_code == 403, response.text
    assert "MLA9301" not in response.text


def test_without_either_permission_is_forbidden(client, active_user, publicacion) -> None:
    _assert_forbidden(_get(client, active_user))


def test_role_with_ml_ops_ver_only_gets_the_tree(client, active_user, rol_ventas, grant_permiso, publicacion) -> None:
    # Publicaciones ML's product panel shows the tree to whoever opens that screen, ml_ops.ver included.
    grant_permiso(rol_ventas, ML_OPS_VER)

    _assert_tree(_get(client, active_user))


def test_role_with_productos_ver_only_gets_the_tree(
    client, active_user, rol_ventas, grant_permiso, publicacion
) -> None:
    grant_permiso(rol_ventas, VER)

    _assert_tree(_get(client, active_user))


def test_superadmin_gets_the_tree(client, rma_superadmin_user, publicacion) -> None:
    _assert_tree(_get(client, rma_superadmin_user))


def test_user_override_grants_productos_ver(client, db, active_user, publicacion) -> None:
    permiso = Permiso(codigo=VER, nombre=VER, descripcion="", categoria="productos", orden=999)
    db.add(permiso)
    db.flush()
    db.add(UsuarioPermisoOverride(usuario_id=active_user.id, permiso_id=permiso.id, concedido=True))
    db.commit()

    _assert_tree(_get(client, active_user))


def test_user_override_revokes_productos_ver(client, db, active_user, rol_ventas, grant_permiso, publicacion) -> None:
    grant_permiso(rol_ventas, VER)
    permiso = db.query(Permiso).filter(Permiso.codigo == VER).one()
    db.add(UsuarioPermisoOverride(usuario_id=active_user.id, permiso_id=permiso.id, concedido=False))
    db.commit()

    _assert_forbidden(_get(client, active_user))


def test_without_session_is_unauthorized(client, publicacion) -> None:
    response = client.get("/api/productos/9301/mercadolibre/tree")

    assert response.status_code == 401
    assert "MLA9301" not in response.text
