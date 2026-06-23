"""
Tests for the etiquetas_zpl_tools endpoint (thin HTTP layer).

TDD: These tests were written BEFORE the endpoint implementation (strict TDD mode).

Uses TestClient with mocked permissions to avoid real DB dependency.
"""

import io
import zipfile
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.database import get_db
from app.api.deps import get_current_user


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_txt_upload(content: bytes, filename: str = "Envio-12345-Etiquetas.txt") -> dict:
    """Build multipart upload files dict for a .txt file."""
    return {"file": (filename, io.BytesIO(content), "text/plain")}


def _make_zip_upload(inner_filename: str, inner_content: bytes, zip_name: str = "batch.zip") -> dict:
    """Build multipart upload files dict for a .zip file."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(inner_filename, inner_content)
    buf.seek(0)
    return {"file": (zip_name, buf, "application/zip")}


VALID_ZPL = b"^XA\n^LH5,15\n^FDTest^FS\n^XZ\n"
NO_LH_ZPL = b"^XA\n^FO10,10^ADN,18,10^FDTest^FS\n^XZ\n"


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def client_with_permiso(active_user, db):
    """TestClient where the user HAS etiquetas.reescribir_lh."""

    def _override_get_db():
        yield db

    def _override_get_current_user():
        return active_user

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_user] = _override_get_current_user

    with patch(
        "app.api.endpoints.etiquetas_zpl_tools.verificar_permiso",
        return_value=True,
    ):
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c

    app.dependency_overrides.clear()


@pytest.fixture()
def client_without_permiso(active_user, db):
    """TestClient where the user does NOT have etiquetas.reescribir_lh."""

    def _override_get_db():
        yield db

    def _override_get_current_user():
        return active_user

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_user] = _override_get_current_user

    with patch(
        "app.api.endpoints.etiquetas_zpl_tools.verificar_permiso",
        return_value=False,
    ):
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c

    app.dependency_overrides.clear()


@pytest.fixture()
def client_unauthenticated():
    """TestClient with no auth override (unauthenticated request)."""
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


# ── Auth / permission tests ───────────────────────────────────────────────────


class TestAuth:
    def test_t61a_no_permiso_returns_403(self, client_without_permiso):
        """T6.1a: User without permiso etiquetas.reescribir_lh → 403."""
        response = client_without_permiso.post(
            "/api/etiquetas-envio/reescribir-lh",
            files=_make_txt_upload(VALID_ZPL),
            data={"target_y": "450"},
        )
        assert response.status_code == 403

    def test_t61b_unauthenticated_returns_4xx(self, client_unauthenticated):
        """T6.1b: Unauthenticated → 401/403 (app's global handler may remap to 403)."""
        response = client_unauthenticated.post(
            "/api/etiquetas-envio/reescribir-lh",
            files=_make_txt_upload(VALID_ZPL),
            data={"target_y": "450"},
        )
        # The app's global exception handler remaps 401 to 403 in some paths
        assert response.status_code in (401, 403)


# ── Validation errors ─────────────────────────────────────────────────────────


class TestValidation:
    def test_t61c_no_lh_returns_400(self, client_with_permiso):
        """T6.1c: Valid auth + no ^LH file → 400."""
        response = client_with_permiso.post(
            "/api/etiquetas-envio/reescribir-lh",
            files=_make_txt_upload(NO_LH_ZPL),
            data={"target_y": "450"},
        )
        assert response.status_code == 400

    def test_t61d_negative_y_returns_400(self, client_with_permiso):
        """T6.1d: target_y = -1 → 400."""
        response = client_with_permiso.post(
            "/api/etiquetas-envio/reescribir-lh",
            files=_make_txt_upload(VALID_ZPL),
            data={"target_y": "-1"},
        )
        assert response.status_code == 400


# ── Success responses ─────────────────────────────────────────────────────────


class TestSuccess:
    def test_t61e_valid_txt_returns_200_with_headers(self, client_with_permiso):
        """T6.1e: Valid .txt + Y=450 → 200, bytes body, X-LH-Modificados header present,
        Content-Disposition contains _corregido.txt."""
        response = client_with_permiso.post(
            "/api/etiquetas-envio/reescribir-lh",
            files=_make_txt_upload(VALID_ZPL, "Envio-12345-Etiquetas.txt"),
            data={"target_y": "450"},
        )
        assert response.status_code == 200
        assert response.headers.get("x-lh-modificados") is not None
        assert "_corregido.txt" in response.headers.get("content-disposition", "")
        # Body should contain the rewritten bytes
        assert b"^LH5,450" in response.content

    def test_t61f_valid_zip_returns_200(self, client_with_permiso):
        """T6.1f: Valid .zip + Y=450 → 200, Content-Disposition references inner .txt stem."""
        zip_files = _make_zip_upload("Envio-12345-Etiquetas.txt", VALID_ZPL, "batch.zip")
        response = client_with_permiso.post(
            "/api/etiquetas-envio/reescribir-lh",
            files=zip_files,
            data={"target_y": "450"},
        )
        assert response.status_code == 200
        content_disposition = response.headers.get("content-disposition", "")
        assert "Envio-12345-Etiquetas_corregido.txt" in content_disposition

    def test_response_headers_all_present(self, client_with_permiso):
        """All four X-* feedback headers should be present on success."""
        response = client_with_permiso.post(
            "/api/etiquetas-envio/reescribir-lh",
            files=_make_txt_upload(VALID_ZPL),
            data={"target_y": "450"},
        )
        assert response.status_code == 200
        assert "x-etiquetas-detectadas" in response.headers
        assert "x-lh-modificados" in response.headers
        assert "x-lh-heterogeneo" in response.headers
        assert "x-ll-warning" in response.headers
