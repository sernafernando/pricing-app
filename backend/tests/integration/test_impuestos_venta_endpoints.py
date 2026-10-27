"""The tax treatment endpoints of Ventas ML (ventas-ml-impuestos-informativos S1-S3), through the real HTTP stack.

`GET /api/impuestos-venta` lists every ML tax withholding seen on a seller charge, with its built-in treatment,
the one in force today and its versions. `POST /api/impuestos-venta` adds a version and closes the open one of the
same name, like `% de varios`. Reads need `ml_ops.ver`, writes `ml_ops.varios_editar`.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from app.models.ml_orders_ops import MlOrdersOps
from app.models.ml_payments import MlPaymentCharge, MlPaymentOps
from app.models.ml_venta_impuesto_tratamiento import ImpuestoTratamientoVenta
from app.models.permiso import Permiso, RolPermisoBase
from app.services.ml_ventas_desglose.breakdown_service import tax_label

URL = "/api/impuestos-venta"
SOBRETASA = "tax_withholding_sirtac_sobretasa-jujuy"
SIRTAC = "tax_withholding_sirtac-caba"


def _grant(db, rol, codigo: str) -> None:
    permiso = db.query(Permiso).filter(Permiso.codigo == codigo).first()
    if not permiso:
        permiso = Permiso(codigo=codigo, nombre=codigo, descripcion="", categoria="ml_ops", orden=999)
        db.add(permiso)
        db.flush()
    db.add(RolPermisoBase(rol_id=rol.id, permiso_id=permiso.id))
    db.flush()


def _sale(db, order_id: int, sold_on: date, *charges: tuple) -> None:
    db.add(
        MlOrdersOps(
            order_id=order_id,
            status="paid",
            seller_id=999,
            ml_last_updated=datetime(2026, 8, 20, tzinfo=timezone.utc),
            date_created=datetime(sold_on.year, sold_on.month, sold_on.day, 15, tzinfo=timezone.utc),
        )
    )
    db.add(MlPaymentOps(payment_id=order_id * 10, order_id=order_id, status="approved"))
    for name, type_ in charges:
        db.add(MlPaymentCharge(payment_id=order_id * 10, name=name, type=type_, amount=Decimal("10")))
    db.commit()


class TestTheList:
    def test_it_lists_each_withholding_seen_once_with_its_treatment(self, db, client, admin_auth_headers, rol_admin):
        _grant(db, rol_admin, "ml_ops.ver")
        _sale(db, 1, date(2026, 9, 10), (SOBRETASA, "tax"), (SIRTAC, "tax"), ("meli_percentage_fee", "fee"))
        _sale(db, 2, date(2026, 9, 11), (SOBRETASA, "tax"), ("tax_withholding_payer-debitos_creditos", "tax"))
        db.add(ImpuestoTratamientoVenta(charge_name=SOBRETASA, informativo=True, fecha_desde=date(2026, 9, 1)))
        db.commit()

        resp = client.get(URL, headers=admin_auth_headers)

        assert resp.status_code == 200
        by_name = {row["charge_name"]: row for row in resp.json()}
        # The payer's débitos y créditos is the buyer's tax, never ours; a fee is not a withholding.
        assert set(by_name) == {SOBRETASA, SIRTAC}
        assert by_name[SOBRETASA] == {
            "charge_name": SOBRETASA,
            "etiqueta": tax_label(SOBRETASA),
            "informativo_por_defecto": False,
            "informativo_hoy": True,
            "versiones": [
                {
                    "id": by_name[SOBRETASA]["versiones"][0]["id"],
                    "informativo": True,
                    "fecha_desde": "2026-09-01",
                    "fecha_hasta": None,
                }
            ],
        }
        assert by_name[SIRTAC]["informativo_por_defecto"] is True
        assert by_name[SIRTAC]["informativo_hoy"] is True
        assert by_name[SIRTAC]["versiones"] == []

    def test_a_version_that_starts_later_does_not_apply_today(self, db, client, admin_auth_headers, rol_admin):
        _grant(db, rol_admin, "ml_ops.ver")
        _sale(db, 3, date(2026, 9, 10), (SOBRETASA, "tax"))
        db.add(
            ImpuestoTratamientoVenta(
                charge_name=SOBRETASA, informativo=True, fecha_desde=date.today() + timedelta(days=30)
            )
        )
        db.commit()

        row = client.get(URL, headers=admin_auth_headers).json()[0]

        assert row["informativo_hoy"] is False

    def test_reading_needs_ml_ops_ver(self, db, client, admin_auth_headers):
        assert client.get(URL, headers=admin_auth_headers).status_code == 403


class TestAddingAVersion:
    def test_it_closes_the_open_version_of_that_tax_and_reports_the_sales_to_recompute(
        self, db, client, admin_auth_headers, rol_admin
    ):
        _grant(db, rol_admin, "ml_ops.varios_editar")
        _sale(db, 4, date(2026, 9, 10), (SOBRETASA, "tax"))
        _sale(db, 5, date(2026, 10, 10), (SOBRETASA, "tax"))
        _sale(db, 6, date(2026, 10, 10), (SIRTAC, "tax"))
        db.add(ImpuestoTratamientoVenta(charge_name=SOBRETASA, informativo=True, fecha_desde=date(2026, 9, 1)))
        db.add(ImpuestoTratamientoVenta(charge_name=SIRTAC, informativo=False, fecha_desde=date(2026, 9, 1)))
        db.commit()

        resp = client.post(
            URL,
            json={"charge_name": SOBRETASA, "informativo": False, "fecha_desde": "2026-10-01"},
            headers=admin_auth_headers,
        )

        assert resp.status_code == 200
        # The closed version (from 2026-09-01) now ends on the new start: its sales and the new ones recompute.
        assert resp.json()["recalculando"] == 2
        versions = {
            (v.charge_name, v.fecha_desde): (v.informativo, v.fecha_hasta)
            for v in db.query(ImpuestoTratamientoVenta).all()
        }
        assert versions == {
            (SOBRETASA, date(2026, 9, 1)): (True, date(2026, 10, 1)),
            (SOBRETASA, date(2026, 10, 1)): (False, None),
            (SIRTAC, date(2026, 9, 1)): (False, None),
        }

    def test_the_same_start_twice_is_rejected(self, db, client, admin_auth_headers, rol_admin):
        _grant(db, rol_admin, "ml_ops.varios_editar")
        db.add(ImpuestoTratamientoVenta(charge_name=SOBRETASA, informativo=True, fecha_desde=date(2026, 9, 1)))
        db.commit()

        resp = client.post(
            URL,
            json={"charge_name": SOBRETASA, "informativo": False, "fecha_desde": "2026-09-01"},
            headers=admin_auth_headers,
        )

        assert resp.status_code == 400
        assert db.query(ImpuestoTratamientoVenta).count() == 1

    def test_a_name_that_is_not_an_ml_withholding_is_rejected(self, db, client, admin_auth_headers, rol_admin):
        _grant(db, rol_admin, "ml_ops.varios_editar")

        resp = client.post(
            URL,
            json={"charge_name": "meli_percentage_fee", "informativo": True, "fecha_desde": "2026-09-01"},
            headers=admin_auth_headers,
        )

        assert resp.status_code == 422
        assert db.query(ImpuestoTratamientoVenta).count() == 0

    def test_ml_ops_ver_alone_cannot_write(self, db, client, admin_auth_headers, rol_admin):
        _grant(db, rol_admin, "ml_ops.ver")

        resp = client.post(
            URL,
            json={"charge_name": SOBRETASA, "informativo": True, "fecha_desde": "2026-09-01"},
            headers=admin_auth_headers,
        )

        assert resp.status_code == 403
