"""
CRUD validation: negative-valued offsets (of any tipo_offset) with consumption
limits must be rejected (422). Money-path safety invariant — see design ADR-4:
this is what keeps negatives away from the max(0, ...) availability clamps in
the rentabilidad endpoints.

Covers monto (monto_fijo/monto_por_unidad) AND porcentaje (porcentaje_costo).
"""

import pytest

BASE_PAYLOAD = {
    "marca": "MarcaTest",
    "fecha_desde": "2026-01-01",
}


@pytest.fixture(autouse=True)
def _grant_editar_constantes(db, rol_admin, admin_user):
    """admin_user's rol has no permisos_base seeded in tests by default; grant
    the permission the offsets-ganancia CRUD endpoints require."""
    from app.models.permiso import Permiso, RolPermisoBase

    permiso = db.query(Permiso).filter(Permiso.codigo == "config.editar_constantes").first()
    if not permiso:
        permiso = Permiso(
            codigo="config.editar_constantes",
            nombre="Editar constantes de pricing",
            descripcion="Crear nuevas versiones de constantes",
            categoria="configuracion",
            orden=63,
        )
        db.add(permiso)
        db.flush()

    db.add(RolPermisoBase(rol_id=rol_admin.id, permiso_id=permiso.id))
    db.flush()


def _payload(**overrides):
    payload = dict(BASE_PAYLOAD)
    payload.update(overrides)
    return payload


class TestPostRejectsNegativeValueWithLimit:
    def test_post_negative_monto_with_max_unidades_is_422(self, client, admin_auth_headers):
        resp = client.post(
            "/api/offsets-ganancia",
            json=_payload(tipo_offset="monto_fijo", monto=-50, max_unidades=10),
            headers=admin_auth_headers,
        )
        assert resp.status_code == 422

    def test_post_negative_monto_with_max_monto_usd_is_422(self, client, admin_auth_headers):
        resp = client.post(
            "/api/offsets-ganancia",
            json=_payload(tipo_offset="monto_fijo", monto=-50, max_monto_usd=100),
            headers=admin_auth_headers,
        )
        assert resp.status_code == 422

    def test_post_negative_porcentaje_with_max_unidades_is_422(self, client, admin_auth_headers):
        resp = client.post(
            "/api/offsets-ganancia",
            json=_payload(tipo_offset="porcentaje_costo", porcentaje=-15, max_unidades=10),
            headers=admin_auth_headers,
        )
        assert resp.status_code == 422

    def test_post_negative_porcentaje_with_max_monto_usd_is_422(self, client, admin_auth_headers):
        resp = client.post(
            "/api/offsets-ganancia",
            json=_payload(tipo_offset="porcentaje_costo", porcentaje=-15, max_monto_usd=100),
            headers=admin_auth_headers,
        )
        assert resp.status_code == 422


class TestPostAllowsRegressionCases:
    def test_post_positive_monto_with_limit_still_2xx(self, client, admin_auth_headers):
        resp = client.post(
            "/api/offsets-ganancia",
            json=_payload(tipo_offset="monto_fijo", monto=50, max_unidades=10),
            headers=admin_auth_headers,
        )
        assert resp.status_code in (200, 201)

    def test_post_positive_porcentaje_with_limit_still_2xx(self, client, admin_auth_headers):
        resp = client.post(
            "/api/offsets-ganancia",
            json=_payload(tipo_offset="porcentaje_costo", porcentaje=15, max_monto_usd=100),
            headers=admin_auth_headers,
        )
        assert resp.status_code in (200, 201)

    def test_post_negative_monto_without_limit_is_2xx(self, client, admin_auth_headers):
        resp = client.post(
            "/api/offsets-ganancia",
            json=_payload(tipo_offset="monto_fijo", monto=-50),
            headers=admin_auth_headers,
        )
        assert resp.status_code in (200, 201)
        assert resp.json()["monto"] == -50

    def test_post_negative_porcentaje_without_limit_is_2xx(self, client, admin_auth_headers):
        resp = client.post(
            "/api/offsets-ganancia",
            json=_payload(tipo_offset="porcentaje_costo", porcentaje=-15),
            headers=admin_auth_headers,
        )
        assert resp.status_code in (200, 201)
        assert resp.json()["porcentaje"] == -15


class TestPutRejectsNegativeValueWithLimit:
    def _create(self, client, admin_auth_headers, **overrides):
        resp = client.post(
            "/api/offsets-ganancia",
            json=_payload(**overrides),
            headers=admin_auth_headers,
        )
        assert resp.status_code in (200, 201), resp.text
        return resp.json()["id"]

    def test_put_existing_monto_to_negative_with_limit_remaining_is_422(self, client, admin_auth_headers):
        offset_id = self._create(client, admin_auth_headers, tipo_offset="monto_fijo", monto=50, max_unidades=5)
        resp = client.put(
            f"/api/offsets-ganancia/{offset_id}",
            json={"monto": -50},
            headers=admin_auth_headers,
        )
        assert resp.status_code == 422

    def test_put_existing_porcentaje_to_negative_with_limit_remaining_is_422(self, client, admin_auth_headers):
        offset_id = self._create(
            client, admin_auth_headers, tipo_offset="porcentaje_costo", porcentaje=15, max_monto_usd=100
        )
        resp = client.put(
            f"/api/offsets-ganancia/{offset_id}",
            json={"porcentaje": -15},
            headers=admin_auth_headers,
        )
        assert resp.status_code == 422

    def test_put_switching_tipo_offset_onto_negative_field_with_limit_is_422(self, client, admin_auth_headers):
        # Created as monto_fijo, positive monto, negative porcentaje pre-set, with a limit.
        offset_id = self._create(
            client,
            admin_auth_headers,
            tipo_offset="monto_fijo",
            monto=50,
            porcentaje=-15,
            max_unidades=5,
        )
        resp = client.put(
            f"/api/offsets-ganancia/{offset_id}",
            json={"tipo_offset": "porcentaje_costo"},
            headers=admin_auth_headers,
        )
        assert resp.status_code == 422
