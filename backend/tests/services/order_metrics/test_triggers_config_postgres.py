"""RED/GREEN -- config/statement-level enqueue triggers (ventas-ml-rediseno
PR5.T1-T6, design D3 statement-level scope, D11). Real Postgres only:
transition tables (`REFERENCING OLD TABLE / NEW TABLE`) have no SQLite
equivalent.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from sqlalchemy import text


def _dirty_row(session, order_id: int):
    return session.execute(
        text("SELECT version, reason FROM ml_order_metrics_dirty WHERE order_id = :order_id"),
        {"order_id": order_id},
    ).fetchone()


def _clear_dirty(session) -> None:
    session.execute(text("DELETE FROM ml_order_metrics_dirty"))
    session.commit()


def _insert_order(session, order_id: int, **overrides) -> None:
    row = {
        "order_id": order_id,
        "seller_id": 999,
        "status": "paid",
        "ml_last_updated": datetime(2026, 8, 20, tzinfo=timezone.utc),
        "date_created": datetime(2026, 8, 15, tzinfo=timezone.utc),
        "shipping_id": None,
    }
    row.update(overrides)
    session.execute(
        text(
            "INSERT INTO ml_orders_ops (order_id, seller_id, status, ml_last_updated, date_created, shipping_id) "
            "VALUES (:order_id, :seller_id, :status, :ml_last_updated, :date_created, :shipping_id)"
        ),
        row,
    )


def _insert_shipment(session, shipment_id: int, logistic_type: str = "self_service", receiver_address=None) -> None:
    session.execute(
        text(
            "INSERT INTO ml_shipments_ops (shipment_id, logistic_type, receiver_address) "
            "VALUES (:shipment_id, :logistic_type, CAST(:receiver_address AS jsonb))"
        ),
        {
            "shipment_id": shipment_id,
            "logistic_type": logistic_type,
            "receiver_address": receiver_address,
        },
    )


def _insert_etiqueta(session, shipping_id: int, **overrides) -> int:
    row = {
        "shipping_id": str(shipping_id),
        "fecha_envio": date(2026, 8, 20),
        "logistica_id": None,
        "transporte_id": None,
        "costo_override": None,
        "es_turbo": False,
        "es_lluvia": False,
        "manual_zip_code": None,
    }
    row.update(overrides)
    return session.execute(
        text(
            "INSERT INTO etiquetas_envio "
            "(shipping_id, fecha_envio, logistica_id, transporte_id, costo_override, es_turbo, es_lluvia, manual_zip_code) "
            "VALUES (:shipping_id, :fecha_envio, :logistica_id, :transporte_id, :costo_override, :es_turbo, "
            ":es_lluvia, :manual_zip_code) RETURNING id"
        ),
        row,
    ).scalar()


@pytest.fixture()
def clean_slate(pg_order_metrics_config_triggers_db):
    session = pg_order_metrics_config_triggers_db
    _clear_dirty(session)
    yield session
    _clear_dirty(session)


@pytest.mark.postgres
class TestEtiquetasEnvioTrigger:
    def test_insert_enqueues_matching_order(self, clean_slate) -> None:
        session = clean_slate
        order_id, shipping_id = 500001, 900001
        try:
            _insert_order(session, order_id, shipping_id=shipping_id)
            session.commit()
            _clear_dirty(session)

            _insert_etiqueta(session, shipping_id)
            session.commit()

            assert _dirty_row(session, order_id) is not None
        finally:
            session.execute(text("DELETE FROM etiquetas_envio WHERE shipping_id = :sid"), {"sid": str(shipping_id)})
            session.execute(text("DELETE FROM ml_orders_ops WHERE order_id = :oid"), {"oid": order_id})
            session.commit()

    def test_manual_zip_code_edit_enqueues(self, clean_slate) -> None:
        """Review finding R3-001: `manual_zip_code` IS a metrics input --
        the cordon a Flex order falls into resolves as
        `COALESCE(transporte.cp, etiqueta.manual_zip_code, shipment zip)`
        (`breakdown_service.py:508-509`, and the `cp_cordones` trigger
        functions in this very PR join on that same expression). Correcting
        a label's postal code by hand can therefore change the shipping
        cost -- and it was absent from the trigger's column list, so nothing
        was enqueued and the stored number silently kept the old cordon."""
        session = clean_slate
        order_id, shipping_id = 500012, 900012
        try:
            _insert_order(session, order_id, shipping_id=shipping_id)
            _insert_etiqueta(session, shipping_id, manual_zip_code=None)
            session.commit()
            _clear_dirty(session)

            session.execute(
                text("UPDATE etiquetas_envio SET manual_zip_code = :cp WHERE shipping_id = :sid"),
                {"cp": "1704", "sid": str(shipping_id)},
            )
            session.commit()

            assert _dirty_row(session, order_id) is not None, (
                "a hand-corrected postal code changes the cordon and must enqueue"
            )
        finally:
            session.execute(text("DELETE FROM etiquetas_envio WHERE shipping_id = :sid"), {"sid": str(shipping_id)})
            session.execute(text("DELETE FROM ml_orders_ops WHERE order_id = :oid"), {"oid": order_id})
            session.commit()

    def test_update_of_read_column_enqueues(self, clean_slate) -> None:
        session = clean_slate
        order_id, shipping_id = 500002, 900002
        try:
            _insert_order(session, order_id, shipping_id=shipping_id)
            _insert_etiqueta(session, shipping_id, es_turbo=False)
            session.commit()
            _clear_dirty(session)

            session.execute(
                text("UPDATE etiquetas_envio SET es_turbo = true WHERE shipping_id = :sid"),
                {"sid": str(shipping_id)},
            )
            session.commit()

            assert _dirty_row(session, order_id) is not None
        finally:
            session.execute(text("DELETE FROM etiquetas_envio WHERE shipping_id = :sid"), {"sid": str(shipping_id)})
            session.execute(text("DELETE FROM ml_orders_ops WHERE order_id = :oid"), {"oid": order_id})
            session.commit()

    def test_delete_enqueues(self, clean_slate) -> None:
        session = clean_slate
        order_id, shipping_id = 500003, 900003
        try:
            _insert_order(session, order_id, shipping_id=shipping_id)
            _insert_etiqueta(session, shipping_id)
            session.commit()
            _clear_dirty(session)

            session.execute(text("DELETE FROM etiquetas_envio WHERE shipping_id = :sid"), {"sid": str(shipping_id)})
            session.commit()

            assert _dirty_row(session, order_id) is not None
        finally:
            session.execute(text("DELETE FROM ml_orders_ops WHERE order_id = :oid"), {"oid": order_id})
            session.commit()

    def test_lat_lng_only_write_does_not_fire(self, clean_slate) -> None:
        """PR5.T1 negative scenario — lat/lng enrichment writes are outside
        the read set."""
        session = clean_slate
        order_id, shipping_id = 500004, 900004
        try:
            _insert_order(session, order_id, shipping_id=shipping_id)
            _insert_etiqueta(session, shipping_id)
            session.commit()
            _clear_dirty(session)

            session.execute(
                text("UPDATE etiquetas_envio SET latitud = -34.6, longitud = -58.4 WHERE shipping_id = :sid"),
                {"sid": str(shipping_id)},
            )
            session.commit()

            assert _dirty_row(session, order_id) is None
        finally:
            session.execute(text("DELETE FROM etiquetas_envio WHERE shipping_id = :sid"), {"sid": str(shipping_id)})
            session.execute(text("DELETE FROM ml_orders_ops WHERE order_id = :oid"), {"oid": order_id})
            session.commit()

    def test_same_value_rewrite_is_a_no_op(self, clean_slate) -> None:
        """PR5.T1a: a row-level no-op guard on the etiquetas_envio ROW
        trigger — mirrors PR4.T6a."""
        session = clean_slate
        order_id, shipping_id = 500005, 900005
        try:
            _insert_order(session, order_id, shipping_id=shipping_id)
            _insert_etiqueta(session, shipping_id, es_turbo=True)
            session.commit()
            _clear_dirty(session)

            session.execute(
                text("UPDATE etiquetas_envio SET es_turbo = true WHERE shipping_id = :sid"),
                {"sid": str(shipping_id)},
            )
            session.commit()

            assert _dirty_row(session, order_id) is None
        finally:
            session.execute(text("DELETE FROM etiquetas_envio WHERE shipping_id = :sid"), {"sid": str(shipping_id)})
            session.execute(text("DELETE FROM ml_orders_ops WHERE order_id = :oid"), {"oid": order_id})
            session.commit()


@pytest.mark.postgres
class TestVariosVentaPctStatementTrigger:
    def test_insert_enqueues_orders_in_range_via_one_set_based_insert(self, clean_slate) -> None:
        session = clean_slate
        order_in, order_out = 510001, 510002
        try:
            _insert_order(session, order_in, date_created=datetime(2026, 6, 15, tzinfo=timezone.utc))
            _insert_order(session, order_out, date_created=datetime(2020, 1, 1, tzinfo=timezone.utc))
            session.commit()
            _clear_dirty(session)

            session.execute(
                text(
                    "INSERT INTO ml_venta_varios_pct (porcentaje, fecha_desde, fecha_hasta) "
                    "VALUES (5.0, :fecha_desde, NULL)"
                ),
                {"fecha_desde": date(2026, 6, 1)},
            )
            session.commit()

            assert _dirty_row(session, order_in) is not None
            assert _dirty_row(session, order_out) is None
        finally:
            session.execute(text("DELETE FROM ml_venta_varios_pct WHERE fecha_desde = :fd"), {"fd": date(2026, 6, 1)})
            session.execute(
                text("DELETE FROM ml_orders_ops WHERE order_id = ANY(:ids)"), {"ids": [order_in, order_out]}
            )
            session.commit()

    def test_narrowing_window_enqueues_orders_leaving_it(self, clean_slate) -> None:
        """Union of OLD and NEW ranges: closing a version's open end must
        still recompute the orders that fall out of the new (narrower)
        window, not just the ones that stay in it."""
        session = clean_slate
        order_id = 510003
        try:
            _insert_order(session, order_id, date_created=datetime(2026, 8, 15, tzinfo=timezone.utc))
            row_id = session.execute(
                text(
                    "INSERT INTO ml_venta_varios_pct (porcentaje, fecha_desde, fecha_hasta) "
                    "VALUES (5.0, :fecha_desde, NULL) RETURNING id"
                ),
                {"fecha_desde": date(2026, 1, 1)},
            ).scalar()
            session.commit()
            _clear_dirty(session)

            session.execute(
                text("UPDATE ml_venta_varios_pct SET fecha_hasta = :fecha_hasta WHERE id = :id"),
                {"fecha_hasta": date(2026, 7, 1), "id": row_id},
            )
            session.commit()

            assert _dirty_row(session, order_id) is not None
        finally:
            session.execute(text("DELETE FROM ml_venta_varios_pct WHERE id = :id"), {"id": row_id})
            session.execute(text("DELETE FROM ml_orders_ops WHERE order_id = :oid"), {"oid": order_id})
            session.commit()

    def test_bulk_update_rewriting_identical_values_enqueues_nothing(self, clean_slate) -> None:
        """PR5.T1a (generalized to statement triggers): a bulk UPDATE that
        rewrites the SAME porcentaje/fecha_desde/fecha_hasta enqueues
        nothing."""
        session = clean_slate
        order_id = 510004
        try:
            _insert_order(session, order_id, date_created=datetime(2026, 8, 15, tzinfo=timezone.utc))
            row_id = session.execute(
                text(
                    "INSERT INTO ml_venta_varios_pct (porcentaje, fecha_desde, fecha_hasta) "
                    "VALUES (5.0, :fecha_desde, NULL) RETURNING id"
                ),
                {"fecha_desde": date(2026, 1, 1)},
            ).scalar()
            session.commit()
            _clear_dirty(session)

            session.execute(
                text("UPDATE ml_venta_varios_pct SET porcentaje = 5.0 WHERE id = :id"),
                {"id": row_id},
            )
            session.commit()

            assert _dirty_row(session, order_id) is None
        finally:
            session.execute(text("DELETE FROM ml_venta_varios_pct WHERE id = :id"), {"id": row_id})
            session.execute(text("DELETE FROM ml_orders_ops WHERE order_id = :oid"), {"oid": order_id})
            session.commit()


@pytest.mark.postgres
class TestLogisticaCostoCordonStatementTrigger:
    def test_insert_enqueues_self_service_orders_with_matching_logistica(self, clean_slate) -> None:
        session = clean_slate
        order_id, shipping_id, logistica_id = 520001, 900101, 42
        try:
            _insert_order(session, order_id, shipping_id=shipping_id)
            _insert_shipment(session, shipping_id, logistic_type="self_service")
            _insert_etiqueta(session, shipping_id, logistica_id=logistica_id)
            session.commit()
            _clear_dirty(session)

            session.execute(
                text(
                    "INSERT INTO logistica_costo_cordon (logistica_id, cordon, costo, vigente_desde) "
                    "VALUES (:logistica_id, 'CABA', 100.0, :vigente_desde)"
                ),
                {"logistica_id": logistica_id, "vigente_desde": date(2026, 1, 1)},
            )
            session.commit()

            assert _dirty_row(session, order_id) is not None
        finally:
            session.execute(text("DELETE FROM logistica_costo_cordon WHERE logistica_id = :lid"), {"lid": logistica_id})
            session.execute(text("DELETE FROM etiquetas_envio WHERE shipping_id = :sid"), {"sid": str(shipping_id)})
            session.execute(text("DELETE FROM ml_shipments_ops WHERE shipment_id = :sid"), {"sid": shipping_id})
            session.execute(text("DELETE FROM ml_orders_ops WHERE order_id = :oid"), {"oid": order_id})
            session.commit()

    def test_non_self_service_shipment_is_not_enqueued(self, clean_slate) -> None:
        session = clean_slate
        order_id, shipping_id, logistica_id = 520002, 900102, 43
        try:
            _insert_order(session, order_id, shipping_id=shipping_id)
            _insert_shipment(session, shipping_id, logistic_type="drop_off")
            _insert_etiqueta(session, shipping_id, logistica_id=logistica_id)
            session.commit()
            _clear_dirty(session)

            session.execute(
                text(
                    "INSERT INTO logistica_costo_cordon (logistica_id, cordon, costo, vigente_desde) "
                    "VALUES (:logistica_id, 'CABA', 100.0, :vigente_desde)"
                ),
                {"logistica_id": logistica_id, "vigente_desde": date(2026, 1, 1)},
            )
            session.commit()

            assert _dirty_row(session, order_id) is None
        finally:
            session.execute(text("DELETE FROM logistica_costo_cordon WHERE logistica_id = :lid"), {"lid": logistica_id})
            session.execute(text("DELETE FROM etiquetas_envio WHERE shipping_id = :sid"), {"sid": str(shipping_id)})
            session.execute(text("DELETE FROM ml_shipments_ops WHERE shipment_id = :sid"), {"sid": shipping_id})
            session.execute(text("DELETE FROM ml_orders_ops WHERE order_id = :oid"), {"oid": order_id})
            session.commit()


@pytest.mark.postgres
class TestCodigosPostalesStatementTrigger:
    def test_cordon_update_enqueues_matching_self_service_order(self, clean_slate) -> None:
        session = clean_slate
        order_id, shipping_id, cp = 530001, 900201, "1900"
        try:
            _insert_order(session, order_id, shipping_id=shipping_id)
            _insert_shipment(
                session, shipping_id, logistic_type="self_service", receiver_address='{"zip_code": "1900"}'
            )
            _insert_etiqueta(session, shipping_id)
            session.execute(
                text("INSERT INTO cp_cordones (codigo_postal, cordon) VALUES (:cp, 'Cordon 1')"), {"cp": cp}
            )
            session.commit()
            _clear_dirty(session)

            session.execute(text("UPDATE cp_cordones SET cordon = 'Cordon 2' WHERE codigo_postal = :cp"), {"cp": cp})
            session.commit()

            assert _dirty_row(session, order_id) is not None
        finally:
            session.execute(text("DELETE FROM cp_cordones WHERE codigo_postal = :cp"), {"cp": cp})
            session.execute(text("DELETE FROM etiquetas_envio WHERE shipping_id = :sid"), {"sid": str(shipping_id)})
            session.execute(text("DELETE FROM ml_shipments_ops WHERE shipment_id = :sid"), {"sid": shipping_id})
            session.execute(text("DELETE FROM ml_orders_ops WHERE order_id = :oid"), {"oid": order_id})
            session.commit()

    def test_same_cordon_rewrite_is_a_no_op(self, clean_slate) -> None:
        session = clean_slate
        order_id, shipping_id, cp = 530002, 900202, "1901"
        try:
            _insert_order(session, order_id, shipping_id=shipping_id)
            _insert_shipment(
                session, shipping_id, logistic_type="self_service", receiver_address='{"zip_code": "1901"}'
            )
            _insert_etiqueta(session, shipping_id)
            session.execute(
                text("INSERT INTO cp_cordones (codigo_postal, cordon) VALUES (:cp, 'Cordon 1')"), {"cp": cp}
            )
            session.commit()
            _clear_dirty(session)

            session.execute(text("UPDATE cp_cordones SET cordon = 'Cordon 1' WHERE codigo_postal = :cp"), {"cp": cp})
            session.commit()

            assert _dirty_row(session, order_id) is None
        finally:
            session.execute(text("DELETE FROM cp_cordones WHERE codigo_postal = :cp"), {"cp": cp})
            session.execute(text("DELETE FROM etiquetas_envio WHERE shipping_id = :sid"), {"sid": str(shipping_id)})
            session.execute(text("DELETE FROM ml_shipments_ops WHERE shipment_id = :sid"), {"sid": shipping_id})
            session.execute(text("DELETE FROM ml_orders_ops WHERE order_id = :oid"), {"oid": order_id})
            session.commit()


@pytest.mark.postgres
class TestConfiguracionStatementTrigger:
    def test_lluvia_key_change_enqueues_es_lluvia_orders(self, clean_slate) -> None:
        session = clean_slate
        order_id, shipping_id = 540001, 900301
        try:
            _insert_order(session, order_id, shipping_id=shipping_id)
            _insert_etiqueta(session, shipping_id, es_lluvia=True)
            session.execute(text("INSERT INTO configuracion (clave, valor) VALUES ('lluvia_offset_valor', '10')"))
            session.commit()
            _clear_dirty(session)

            session.execute(text("UPDATE configuracion SET valor = '20' WHERE clave = 'lluvia_offset_valor'"))
            session.commit()

            assert _dirty_row(session, order_id) is not None
        finally:
            session.execute(text("DELETE FROM configuracion WHERE clave = 'lluvia_offset_valor'"))
            session.execute(text("DELETE FROM etiquetas_envio WHERE shipping_id = :sid"), {"sid": str(shipping_id)})
            session.execute(text("DELETE FROM ml_orders_ops WHERE order_id = :oid"), {"oid": order_id})
            session.commit()

    def test_non_lluvia_key_change_does_not_fire(self, clean_slate) -> None:
        session = clean_slate
        order_id, shipping_id = 540002, 900302
        try:
            _insert_order(session, order_id, shipping_id=shipping_id)
            _insert_etiqueta(session, shipping_id, es_lluvia=True)
            session.execute(text("INSERT INTO configuracion (clave, valor) VALUES ('otra_clave', '10')"))
            session.commit()
            _clear_dirty(session)

            session.execute(text("UPDATE configuracion SET valor = '20' WHERE clave = 'otra_clave'"))
            session.commit()

            assert _dirty_row(session, order_id) is None
        finally:
            session.execute(text("DELETE FROM configuracion WHERE clave = 'otra_clave'"))
            session.execute(text("DELETE FROM etiquetas_envio WHERE shipping_id = :sid"), {"sid": str(shipping_id)})
            session.execute(text("DELETE FROM ml_orders_ops WHERE order_id = :oid"), {"oid": order_id})
            session.commit()

    def test_non_es_lluvia_order_is_not_enqueued(self, clean_slate) -> None:
        session = clean_slate
        order_id, shipping_id = 540003, 900303
        try:
            _insert_order(session, order_id, shipping_id=shipping_id)
            _insert_etiqueta(session, shipping_id, es_lluvia=False)
            session.execute(text("INSERT INTO configuracion (clave, valor) VALUES ('lluvia_offset_tipo', 'fijo')"))
            session.commit()
            _clear_dirty(session)

            session.execute(text("UPDATE configuracion SET valor = 'porcentual' WHERE clave = 'lluvia_offset_tipo'"))
            session.commit()

            assert _dirty_row(session, order_id) is None
        finally:
            session.execute(text("DELETE FROM configuracion WHERE clave = 'lluvia_offset_tipo'"))
            session.execute(text("DELETE FROM etiquetas_envio WHERE shipping_id = :sid"), {"sid": str(shipping_id)})
            session.execute(text("DELETE FROM ml_orders_ops WHERE order_id = :oid"), {"oid": order_id})
            session.commit()


@pytest.mark.postgres
class TestTransportesStatementTrigger:
    def test_cp_update_enqueues_orders_whose_label_uses_that_transporte(self, clean_slate) -> None:
        session = clean_slate
        order_id, shipping_id = 550001, 900401
        transporte_id = None
        try:
            transporte_id = session.execute(
                text("INSERT INTO transportes (nombre, cp, activa) VALUES ('Cruz del Sur', '1000', true) RETURNING id")
            ).scalar()
            _insert_order(session, order_id, shipping_id=shipping_id)
            _insert_etiqueta(session, shipping_id, transporte_id=transporte_id)
            session.commit()
            _clear_dirty(session)

            session.execute(text("UPDATE transportes SET cp = '2000' WHERE id = :id"), {"id": transporte_id})
            session.commit()

            assert _dirty_row(session, order_id) is not None
        finally:
            session.execute(text("DELETE FROM etiquetas_envio WHERE shipping_id = :sid"), {"sid": str(shipping_id)})
            session.execute(text("DELETE FROM ml_orders_ops WHERE order_id = :oid"), {"oid": order_id})
            if transporte_id is not None:
                session.execute(text("DELETE FROM transportes WHERE id = :id"), {"id": transporte_id})
            session.commit()

    def test_non_cp_update_does_not_fire(self, clean_slate) -> None:
        session = clean_slate
        order_id, shipping_id = 550002, 900402
        transporte_id = None
        try:
            transporte_id = session.execute(
                text("INSERT INTO transportes (nombre, cp, activa) VALUES ('Via Cargo', '1000', true) RETURNING id")
            ).scalar()
            _insert_order(session, order_id, shipping_id=shipping_id)
            _insert_etiqueta(session, shipping_id, transporte_id=transporte_id)
            session.commit()
            _clear_dirty(session)

            session.execute(text("UPDATE transportes SET telefono = '123' WHERE id = :id"), {"id": transporte_id})
            session.commit()

            assert _dirty_row(session, order_id) is None
        finally:
            session.execute(text("DELETE FROM etiquetas_envio WHERE shipping_id = :sid"), {"sid": str(shipping_id)})
            session.execute(text("DELETE FROM ml_orders_ops WHERE order_id = :oid"), {"oid": order_id})
            if transporte_id is not None:
                session.execute(text("DELETE FROM transportes WHERE id = :id"), {"id": transporte_id})
            session.commit()

    def test_rolled_back_write_enqueues_nothing(self, pg_order_metrics_config_triggers_engine, clean_slate) -> None:
        session = clean_slate
        transporte_id = session.execute(
            text("INSERT INTO transportes (nombre, cp, activa) VALUES ('Chevallier', '1000', true) RETURNING id")
        ).scalar()
        session.commit()
        order_id, shipping_id = 550003, 900403
        try:
            _insert_order(session, order_id, shipping_id=shipping_id)
            _insert_etiqueta(session, shipping_id, transporte_id=transporte_id)
            session.commit()
            _clear_dirty(session)

            conn = pg_order_metrics_config_triggers_engine.connect()
            trans = conn.begin()
            conn.execute(text("UPDATE transportes SET cp = '3000' WHERE id = :id"), {"id": transporte_id})
            trans.rollback()
            conn.close()

            assert _dirty_row(session, order_id) is None
        finally:
            session.execute(text("DELETE FROM etiquetas_envio WHERE shipping_id = :sid"), {"sid": str(shipping_id)})
            session.execute(text("DELETE FROM ml_orders_ops WHERE order_id = :oid"), {"oid": order_id})
            session.execute(text("DELETE FROM transportes WHERE id = :id"), {"id": transporte_id})
            session.commit()
