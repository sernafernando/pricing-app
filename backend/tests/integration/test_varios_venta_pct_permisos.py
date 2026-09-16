"""HTTP-level permission gate for the "% de varios" screen (feat/varios-
modal-ventas-ml). Product decision, verbatim: "que se pueda ver pero no
editar sin el permiso" -- so reads sit behind the EXISTING `ml_ops.ver`
(same gate as the ML sales view this modal lives in) and writes behind the
NEW, separate `ml_ops.varios_editar`.

`tests/api/endpoints/test_configuracion_varios_venta_pct.py` already
covers the business logic by calling the endpoint functions directly,
bypassing FastAPI's dependency injection entirely -- so it proves nothing
about the permission gate. These tests go through the real HTTP stack
(`client`) so `require_permiso(...)` actually runs.
"""

from __future__ import annotations

from datetime import date

from app.models.permiso import Permiso, RolPermisoBase
from app.models.varios_venta_pct import VariosVentaPct


def _grant(db, rol, codigo: str, *, categoria: str = "ml_ops") -> None:
    permiso = db.query(Permiso).filter(Permiso.codigo == codigo).first()
    if not permiso:
        permiso = Permiso(codigo=codigo, nombre=codigo, descripcion="", categoria=categoria, orden=999)
        db.add(permiso)
        db.flush()
    db.add(RolPermisoBase(rol_id=rol.id, permiso_id=permiso.id))
    db.flush()


class TestVariosVentaPctPermisos:
    def test_ver_permission_without_editar_gets_403_on_post(self, db, client, admin_auth_headers, rol_admin) -> None:
        _grant(db, rol_admin, "ml_ops.ver")

        resp = client.post(
            "/api/varios-venta-pct",
            json={"porcentaje": 2.5, "fecha_desde": "2026-01-01"},
            headers=admin_auth_headers,
        )

        assert resp.status_code == 403

    def test_ver_permission_without_editar_gets_200_on_both_gets(
        self, db, client, admin_auth_headers, rol_admin
    ) -> None:
        _grant(db, rol_admin, "ml_ops.ver")
        db.add(VariosVentaPct(porcentaje=2.5, fecha_desde=date(2020, 1, 1), fecha_hasta=None))
        db.commit()

        resp_list = client.get("/api/varios-venta-pct", headers=admin_auth_headers)
        resp_actual = client.get("/api/varios-venta-pct/actual", headers=admin_auth_headers)

        assert resp_list.status_code == 200
        assert resp_actual.status_code == 200

    def test_ver_and_editar_permission_gets_200_on_post(self, db, client, admin_auth_headers, rol_admin) -> None:
        _grant(db, rol_admin, "ml_ops.ver")
        _grant(db, rol_admin, "ml_ops.varios_editar")

        resp = client.post(
            "/api/varios-venta-pct",
            json={"porcentaje": 2.5, "fecha_desde": "2026-01-01"},
            headers=admin_auth_headers,
        )

        assert resp.status_code == 200

    def test_without_ver_permission_gets_403_on_both_gets(self, db, client, admin_auth_headers) -> None:
        resp_list = client.get("/api/varios-venta-pct", headers=admin_auth_headers)
        resp_actual = client.get("/api/varios-venta-pct/actual", headers=admin_auth_headers)

        assert resp_list.status_code == 403
        assert resp_actual.status_code == 403

    def test_editar_permission_alone_is_enough_for_post(self, db, client, admin_auth_headers, rol_admin) -> None:
        # POST is gated by `ml_ops.varios_editar` only -- not `ml_ops.ver`
        # -- so the gate is permission-scoped, not role-scoped. Not a
        # realistic grant per the seed migration (ADMIN gets both), but
        # proves the POST dependency doesn't secretly also require `ver`.
        _grant(db, rol_admin, "ml_ops.varios_editar")

        resp = client.post(
            "/api/varios-venta-pct",
            json={"porcentaje": 2.5, "fecha_desde": "2026-01-01"},
            headers=admin_auth_headers,
        )

        assert resp.status_code == 200
