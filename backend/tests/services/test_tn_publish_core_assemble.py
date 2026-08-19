"""Unit tests for v1 payload assembly (PC7 visibility, PC9 inventory_levels)."""

from app.services.tn_publish_core.resolve import Resolved
from app.services.tn_publish_core.assemble import assemble_payload


def _resolved_fields():
    return {
        "weight": Resolved(1.0, "gbp"),
        "width": Resolved(13.0, "gbp"),
        "depth": Resolved(2.0, "gbp"),
        "height": Resolved(8.0, "gbp"),
    }


class TestVisibilityExclusivity:
    def test_payload_has_visibility_and_never_published(self):
        payload = assemble_payload(
            _resolved_fields(),
            name_es="Producto de prueba",
            price="1000.00",
            stock=5,
            category_id=42,
            description_html="<p>desc</p>",
        )

        assert payload["visibility"] == "visible"
        assert "published" not in payload
        assert "visibility" not in payload["variants"][0]
        assert "published" not in payload["variants"][0]


class TestInventoryLevels:
    def test_variant_carries_inventory_levels_no_top_level_stock(self):
        payload = assemble_payload(
            _resolved_fields(),
            name_es="Producto de prueba",
            price="1000.00",
            stock=7,
            category_id=42,
            description_html="<p>desc</p>",
        )

        variant = payload["variants"][0]
        assert variant["inventory_levels"] == [{"stock": 7}]
        assert "stock" not in variant

    def test_variant_carries_resolved_measurements(self):
        payload = assemble_payload(
            _resolved_fields(),
            name_es="Producto de prueba",
            price="1000.00",
            stock=0,
            category_id=42,
            description_html="<p>desc</p>",
        )

        variant = payload["variants"][0]
        assert variant["weight"] == 1.0
        assert variant["width"] == 13.0
        assert variant["depth"] == 2.0
        assert variant["height"] == 8.0


class TestAbsentStock:
    """PR-7 gap fix task A: `stock=None` must never fabricate a number — the
    key is omitted so TN applies its own create-time default, instead of
    this module inventing `0` or silently dropping a real value."""

    def test_stock_none_omits_inventory_levels_entirely(self):
        payload = assemble_payload(
            _resolved_fields(),
            name_es="Producto de prueba",
            price="1000.00",
            stock=None,
            category_id=42,
            description_html="<p>desc</p>",
        )

        assert "inventory_levels" not in payload["variants"][0]

    def test_stock_zero_still_sends_inventory_levels(self):
        """Triangulation: `0` is a legitimate value (D1/PC9 — zero stock is
        publishable) and must NOT be treated the same as `None`."""
        payload = assemble_payload(
            _resolved_fields(),
            name_es="Producto de prueba",
            price="1000.00",
            stock=0,
            category_id=42,
            description_html="<p>desc</p>",
        )

        assert payload["variants"][0]["inventory_levels"] == [{"stock": 0}]
