"""RED/GREEN — ProductoPrecioOrigen model + upsert_origen_manual helper.

Slice 2 of promo-price-propagation: provenance table tracking which
mechanism (manual edit vs promo) last wrote each price column.
"""

from datetime import UTC, datetime

from app.models.producto import ProductoERP, TipoMoneda
from app.models.producto_precio_origen import ProductoPrecioOrigen, upsert_origen_manual


def _make_producto(db, item_id: int = 1001) -> ProductoERP:
    producto = ProductoERP(
        item_id=item_id,
        codigo=f"COD{item_id}",
        descripcion="Producto de prueba",
        subcategoria_id=1,
        costo=1000.0,
        moneda_costo=TipoMoneda.ARS,
        iva=21.0,
    )
    db.add(producto)
    db.commit()
    return producto


class TestProductoPrecioOrigenModel:
    def test_insert_and_read_row(self, db):
        _make_producto(db)
        origen = ProductoPrecioOrigen(
            item_id=1001,
            column_key="precio_lista_ml",
            origen="manual",
            fecha=datetime.now(UTC),
        )
        db.add(origen)
        db.commit()

        row = db.query(ProductoPrecioOrigen).filter_by(item_id=1001).first()
        assert row is not None
        assert row.column_key == "precio_lista_ml"
        assert row.origen == "manual"
        assert row.promo_id is None
        assert row.mla is None

    def test_unique_constraint_item_column(self, db):
        """A second row for the same (item_id, column_key) must be rejected —
        this is what makes upsert_origen_manual's update-in-place path required."""
        _make_producto(db)
        db.add(ProductoPrecioOrigen(item_id=1001, column_key="precio_lista_ml", origen="manual"))
        db.commit()

        db.add(ProductoPrecioOrigen(item_id=1001, column_key="precio_lista_ml", origen="promo"))
        try:
            db.commit()
            raised = False
        except Exception:
            db.rollback()
            raised = True
        assert raised, "Expected a uniqueness violation on duplicate (item_id, column_key)"


class TestUpsertOrigenManual:
    def test_inserts_new_rows_for_each_column(self, db):
        _make_producto(db)
        upsert_origen_manual(db, 1001, ["precio_lista_ml", "precio_3_cuotas"])
        db.commit()

        rows = db.query(ProductoPrecioOrigen).filter_by(item_id=1001).all()
        assert {r.column_key for r in rows} == {"precio_lista_ml", "precio_3_cuotas"}
        assert all(r.origen == "manual" for r in rows)

    def test_upsert_flips_existing_promo_row_back_to_manual(self, db):
        _make_producto(db)
        db.add(
            ProductoPrecioOrigen(
                item_id=1001,
                column_key="precio_lista_ml",
                origen="promo",
                promo_id="PROMO-1",
                mla="MLA123",
            )
        )
        db.commit()

        upsert_origen_manual(db, 1001, ["precio_lista_ml"])
        db.commit()

        rows = db.query(ProductoPrecioOrigen).filter_by(item_id=1001, column_key="precio_lista_ml").all()
        assert len(rows) == 1
        row = rows[0]
        assert row.origen == "manual"
        assert row.promo_id is None
        assert row.mla is None

    def test_upsert_does_not_duplicate_row_on_repeated_manual_writes(self, db):
        _make_producto(db)
        upsert_origen_manual(db, 1001, ["precio_lista_ml"])
        db.commit()
        upsert_origen_manual(db, 1001, ["precio_lista_ml"])
        db.commit()

        rows = db.query(ProductoPrecioOrigen).filter_by(item_id=1001, column_key="precio_lista_ml").all()
        assert len(rows) == 1

    def test_uses_explicit_fecha_when_provided(self, db):
        _make_producto(db)
        fixed = datetime(2026, 1, 1, tzinfo=UTC)
        upsert_origen_manual(db, 1001, ["precio_lista_ml"], fecha=fixed)
        db.commit()

        row = db.query(ProductoPrecioOrigen).filter_by(item_id=1001, column_key="precio_lista_ml").first()
        assert row.fecha.replace(tzinfo=UTC) == fixed
