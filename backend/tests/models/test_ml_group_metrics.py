"""ventas-ml-rediseno PR20.T1 — `MlGroupMetrics` model shape.

One row per GROUP (pack or a standalone order treated as a group of one,
spec `ml-order-stored-metrics` R9): `group_key` is the primary key, TEXT,
in the exact `"p:<pack_id>"` / `"o:<order_id>"` format
`_group_key_expr()` produces (`app/services/ml_sales_query/filters.py`).
Same field set and NULL/status discipline as `MlOrderMetrics` (R9), applied
at group level: `gauss_status='unresolved'` forces `total_gauss` and
`markup_pct` NULL, mirroring the per-order rule (R1/R2).
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.models.ml_group_metrics import MlGroupMetrics


def _row(**overrides):
    defaults = dict(
        group_key="p:123",
        neto=None,
        neto_sin_iva=None,
        costo_mercaderia=None,
        total_gauss=None,
        markup_pct=None,
        gauss_status="unresolved",
        member_order_ids=[1, 2],
        group_date=None,
        formula_version=1,
        computed_at=datetime.now(timezone.utc),
    )
    defaults.update(overrides)
    return MlGroupMetrics(**defaults)


class TestModelShape:
    def test_group_key_is_the_primary_key(self):
        mapper = MlGroupMetrics.__mapper__
        pk_columns = [c.name for c in mapper.primary_key]
        assert pk_columns == ["group_key"]

    def test_has_the_same_field_set_as_ml_order_metrics(self):
        columns = {c.name for c in MlGroupMetrics.__table__.columns}
        expected = {
            "group_key",
            "neto",
            "neto_sin_iva",
            "costo_mercaderia",
            "total_gauss",
            "markup_pct",
            "gauss_status",
            "member_order_ids",
            "group_date",
            "formula_version",
            "computed_at",
        }
        assert expected <= columns

    def test_gauss_status_check_constraint_matches_ml_order_metrics(self):
        check_names = {
            c.sqltext.text if hasattr(c, "sqltext") else str(c)
            for c in MlGroupMetrics.__table__.constraints
            if c.__class__.__name__ == "CheckConstraint"
        }
        assert any("gauss_status IN" in text for text in check_names)

    def test_insert_and_roundtrip_ok_row(self, db):
        row = _row(
            group_key="p:555",
            neto="100.00",
            neto_sin_iva="82.64",
            costo_mercaderia="50.00",
            total_gauss="50.00",
            markup_pct="100.00",
            gauss_status="ok",
        )
        db.add(row)
        db.commit()

        fetched = db.query(MlGroupMetrics).filter_by(group_key="p:555").one()
        assert fetched.member_order_ids == [1, 2]
        assert str(fetched.total_gauss) == "50.00"

    def test_unresolved_status_allows_null_total_gauss_and_markup(self, db):
        row = _row(group_key="p:777", gauss_status="unresolved")
        db.add(row)
        db.commit()

        fetched = db.query(MlGroupMetrics).filter_by(group_key="p:777").one()
        assert fetched.total_gauss is None
        assert fetched.markup_pct is None
        assert fetched.gauss_status == "unresolved"

    def test_standalone_order_group_key_format(self, db):
        row = _row(group_key="o:42", member_order_ids=[42])
        db.add(row)
        db.commit()

        fetched = db.query(MlGroupMetrics).filter_by(group_key="o:42").one()
        assert fetched.member_order_ids == [42]
