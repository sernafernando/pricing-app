"""
Integration tests for GET /markups-tienda/config/{clave} — public key whitelist.

The endpoint is generic over the `tienda_config` table, so access is gated by a
closed whitelist (`CLAVES_CONFIG_PUBLICAS`) instead of being open to every
authenticated user:

- W-1: a public key is readable WITHOUT productos.gestionar_markups_tienda
- W-2: a NON-public key returns 403 without the permission
- W-3: the same non-public key is readable WITH the permission
- W-4: the missing-row fallback ({"clave": ..., "valor": 0}) still applies to a
       public key read without the permission
- W-5: the whitelist contains exactly the two pricing percentages the grids need
- W-6: the full dump (GET /config) stays gated even for a caller that can read a
       public key — the whitelist must not leak into the dump
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.api.endpoints.markups_tienda import CLAVES_CONFIG_PUBLICAS
from app.models.markup_tienda import TiendaConfig


# ==========================================================================
# Permission fixtures (same pattern as test_markup_sugerido_endpoint.py)
# ==========================================================================


PERM_MARKUPS = "productos.gestionar_markups_tienda"

CLAVE_PUBLICA = "markup_web_tarjeta"
CLAVE_PRIVADA = "clave_no_publica_de_prueba"

ENDPOINT = "/api/markups-tienda/config/{clave}"
ENDPOINT_DUMP = "/api/markups-tienda/config"


@pytest.fixture
def con_permiso_markups():
    """Forces both the cache and the service to grant gestionar_markups_tienda."""
    with (
        patch(
            "app.services.permisos_service.PermisosService.tiene_permiso",
            return_value=True,
        ),
        patch(
            "app.services.permisos_service.PermisosService.obtener_permisos_usuario",
            return_value={PERM_MARKUPS},
        ),
    ):
        yield


@pytest.fixture
def sin_permiso_markups():
    """Forces both the cache and the service to deny all permissions."""
    with (
        patch(
            "app.services.permisos_service.PermisosService.tiene_permiso",
            return_value=False,
        ),
        patch(
            "app.services.permisos_service.PermisosService.obtener_permisos_usuario",
            return_value=set(),
        ),
    ):
        yield


# ==========================================================================
# Data fixtures
# ==========================================================================


@pytest.fixture
def config_publica(db) -> TiendaConfig:
    """A stored row for a whitelisted key."""
    c = TiendaConfig(clave=CLAVE_PUBLICA, valor=18.5)
    db.add(c)
    db.flush()
    return c


@pytest.fixture
def config_privada(db) -> TiendaConfig:
    """A stored row for a key that is NOT whitelisted."""
    c = TiendaConfig(clave=CLAVE_PRIVADA, valor=42.0)
    db.add(c)
    db.flush()
    return c


# ==========================================================================
# W-5 — The whitelist itself
# ==========================================================================


class TestWhitelistContents:
    """W-5: the whitelist is a closed, immutable set with exactly two keys."""

    def test_w5_whitelist_is_exact(self):
        assert CLAVES_CONFIG_PUBLICAS == {"markup_web_tarjeta", "porcentaje_tarjeta_tn"}

    def test_w5_whitelist_is_immutable(self):
        assert isinstance(CLAVES_CONFIG_PUBLICAS, frozenset)


# ==========================================================================
# W-1 / W-2 / W-3 — Access control
# ==========================================================================


class TestPublicKeyAccess:
    """W-1: whitelisted keys need auth only."""

    @pytest.mark.parametrize("clave", sorted(CLAVES_CONFIG_PUBLICAS))
    def test_w1_public_key_readable_without_permission(self, client, auth_headers, db, clave, sin_permiso_markups):
        db.add(TiendaConfig(clave=clave, valor=18.5))
        db.flush()

        response = client.get(ENDPOINT.format(clave=clave), headers=auth_headers)

        assert response.status_code == 200
        assert response.json() == {"clave": clave, "valor": 18.5}

    def test_w1_public_key_still_readable_with_permission(
        self, client, auth_headers, config_publica, con_permiso_markups
    ):
        """Granting the permission must not change the result for a public key."""
        response = client.get(ENDPOINT.format(clave=CLAVE_PUBLICA), headers=auth_headers)

        assert response.status_code == 200
        assert response.json() == {"clave": CLAVE_PUBLICA, "valor": 18.5}

    def test_w1_public_key_still_requires_authentication(self, client, config_publica):
        """The whitelist relaxes the PERMISSION, never the auth guard."""
        response = client.get(ENDPOINT.format(clave=CLAVE_PUBLICA))

        assert response.status_code in (401, 403)


class TestNonPublicKeyAccess:
    """W-2 and W-3: everything outside the whitelist keeps the old gate."""

    def test_w2_403_without_permission(self, client, auth_headers, config_privada, sin_permiso_markups):
        response = client.get(ENDPOINT.format(clave=CLAVE_PRIVADA), headers=auth_headers)

        assert response.status_code == 403
        # `http_exception_handler` normalizes a string `detail` into this envelope.
        assert response.json()["error"]["message"] == "No tienes permiso para gestionar markups de tienda"

    def test_w2_403_hides_value_of_unknown_key(self, client, auth_headers, sin_permiso_markups):
        """A non-public key that has no row must 403, not leak the 0 fallback.

        Otherwise the fallback becomes an oracle for which keys exist.
        """
        response = client.get(ENDPOINT.format(clave="clave_inexistente"), headers=auth_headers)

        assert response.status_code == 403

    def test_w3_readable_with_permission(self, client, auth_headers, config_privada, con_permiso_markups):
        response = client.get(ENDPOINT.format(clave=CLAVE_PRIVADA), headers=auth_headers)

        assert response.status_code == 200
        assert response.json() == {"clave": CLAVE_PRIVADA, "valor": 42.0}


# ==========================================================================
# W-4 — Missing-row fallback
# ==========================================================================


class TestMissingRowFallback:
    """W-4: a public key with no stored row degrades to 0, it does not 404."""

    def test_w4_public_key_without_row_returns_zero(self, client, auth_headers, db, sin_permiso_markups):
        assert db.query(TiendaConfig).filter_by(clave=CLAVE_PUBLICA).first() is None

        response = client.get(ENDPOINT.format(clave=CLAVE_PUBLICA), headers=auth_headers)

        assert response.status_code == 200
        assert response.json() == {"clave": CLAVE_PUBLICA, "valor": 0}


# ==========================================================================
# W-6 — The dump endpoint is unaffected
# ==========================================================================


class TestDumpStaysGated:
    """W-6: GET /config still requires the permission, whitelist or not."""

    def test_w6_dump_403_without_permission(self, client, auth_headers, config_publica, sin_permiso_markups):
        response = client.get(ENDPOINT_DUMP, headers=auth_headers)

        assert response.status_code == 403

    def test_w6_dump_200_with_permission(self, client, auth_headers, config_publica, con_permiso_markups):
        response = client.get(ENDPOINT_DUMP, headers=auth_headers)

        assert response.status_code == 200
        assert response.json()[CLAVE_PUBLICA] == 18.5
