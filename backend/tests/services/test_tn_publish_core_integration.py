"""Backend-only integration test (task 5.17, PC11/D7): the full publish
pipeline — extract -> resolve -> validate -> assemble -> batch — invoked
end-to-end with NO FastAPI request object and NO React code anywhere on the
call path. Proves the "one server-side resolver" claim structurally, not by
convention: this test constructs a GBP row, a stored override, and a
measurement profile directly in Python and asserts a complete, valid TN
payload comes out the other end.
"""

from app.services.tn_publish_core.assemble import assemble_payload
from app.services.tn_publish_core.batch import execute_batch
from app.services.tn_publish_core.extract import extract_report_row
from app.services.tn_publish_core.resolve import resolve_field, resolve_gbp_fields
from app.services.tn_publish_core.validate import validate_measurements


def _gbp_row(**overrides: object) -> dict:
    """A complete, well-formed report-78 row — every `REQUIRED_REPORT_FIELDS`
    key present, exactly like a real GBP export. Overridable per test."""
    row = {
        "weight": "1500",  # grams -> 1.500 kg
        "wide": "10",  # -> TN depth (U2, not a typo)
        "large": "20",  # -> TN width (U2, not a typo)
        "height": "5",
        "Marca": "ACME",
        "Stock_Disponible": "12",
        "coslis_price": "1000.00",
        "iclh_price": "1500.00",
        "Moneda_Costo": "ARS",
        "Código": "7791234567890",
        "tnr_lastPromotionalPrice": "1400.00",
    }
    row.update(overrides)
    return row


class TestFullPipelineNoFastapiNoReact:
    """No `fastapi.Request`, no pydantic request/response model, no
    frontend/React object appears anywhere below — every stage is called
    with plain Python values only (dicts, dataclasses, primitives)."""

    def test_gbp_only_row_assembles_a_complete_tn_payload(self):
        extracted = extract_report_row(_gbp_row())
        resolved_gbp = resolve_gbp_fields(extracted)

        resolved_fields = {
            "weight": resolve_field(gbp_value=resolved_gbp.weight_kg),
            "width": resolve_field(gbp_value=resolved_gbp.width_cm),
            "depth": resolve_field(gbp_value=resolved_gbp.depth_cm),
            "height": resolve_field(gbp_value=resolved_gbp.height_cm),
        }

        validation = validate_measurements(resolved_fields)
        assert validation.blocked is False
        assert validation.blocked_reasons == []

        payload = assemble_payload(
            resolved_fields,
            name_es="ACME Widget",
            price="1999.00",
            stock=12,
            category_id=42,
            sku=resolved_gbp.codigo,
        )

        # PC9/D1: inventory_levels, never a top-level `stock`.
        variant = payload["variants"][0]
        assert variant["inventory_levels"] == [{"stock": 12}]
        assert "stock" not in variant
        # U1: grams -> kg conversion landed.
        assert variant["weight"] == 1.5
        # U2: GBP `large` -> TN `width`, GBP `wide` -> TN `depth`.
        assert variant["width"] == 20.0
        assert variant["depth"] == 10.0
        assert variant["height"] == 5.0
        # PC7/D4: visibility, never `published`.
        assert payload["visibility"] == "visible"
        assert "published" not in payload
        assert payload["categories"] == [42]

    def test_stored_override_outranks_gbp_and_is_not_re_divided(self):
        """PC4 precedence + Decision 1 ordering constraint: an override
        already stored in canonical kg (1.2) must win over the fresh GBP
        value AND must never be divided by 1000 again."""
        extracted = extract_report_row(_gbp_row(weight="3000"))  # would be 3.0 kg from GBP
        resolved_gbp = resolve_gbp_fields(extracted)

        weight_field = resolve_field(gbp_value=resolved_gbp.weight_kg, override_value=1.2)
        assert weight_field.value == 1.2
        assert weight_field.source == "override"

    def test_profile_fills_a_gap_gbp_leaves_empty(self):
        """A measurement profile (built directly in Python — no ORM model
        needed for this pure-function proof) fills weight when GBP reports
        no data for it (blank convention -> `Absent`)."""
        extracted = extract_report_row(_gbp_row(weight="0"))  # GBP "no data" convention
        resolved_gbp = resolve_gbp_fields(extracted)

        profile = {"weight": 0.9, "width": 30.0, "depth": 20.0, "height": 20.0}
        resolved_fields = {
            "weight": resolve_field(gbp_value=resolved_gbp.weight_kg, profile_value=profile["weight"]),
            "width": resolve_field(gbp_value=resolved_gbp.width_cm, profile_value=profile["width"]),
            "depth": resolve_field(gbp_value=resolved_gbp.depth_cm, profile_value=profile["depth"]),
            "height": resolve_field(gbp_value=resolved_gbp.height_cm, profile_value=profile["height"]),
        }
        validation = validate_measurements(resolved_fields)
        assert validation.blocked is False
        assert resolved_fields["weight"].value == 0.9
        assert resolved_fields["weight"].source == "profile"

    def test_missing_measurement_with_no_fallback_blocks_and_names_the_field(self):
        extracted = extract_report_row(_gbp_row(weight="0"))  # absent, no override/profile
        resolved_gbp = resolve_gbp_fields(extracted)

        resolved_fields = {
            "weight": resolve_field(gbp_value=resolved_gbp.weight_kg),
            "width": resolve_field(gbp_value=resolved_gbp.width_cm),
            "depth": resolve_field(gbp_value=resolved_gbp.depth_cm),
            "height": resolve_field(gbp_value=resolved_gbp.height_cm),
        }
        validation = validate_measurements(resolved_fields)
        assert validation.blocked is True
        assert any("weight" in reason for reason in validation.blocked_reasons)

    def test_single_item_publish_runs_through_execute_batch_end_to_end(self):
        """PC10/R1 (Decision 6): even the "no FastAPI/React" integration
        path runs its final TN submission through `execute_batch` — a
        single item is a batch of one, no second code path exists."""
        extracted = extract_report_row(_gbp_row())
        resolved_gbp = resolve_gbp_fields(extracted)
        resolved_fields = {
            "weight": resolve_field(gbp_value=resolved_gbp.weight_kg),
            "width": resolve_field(gbp_value=resolved_gbp.width_cm),
            "depth": resolve_field(gbp_value=resolved_gbp.depth_cm),
            "height": resolve_field(gbp_value=resolved_gbp.height_cm),
        }
        payload = assemble_payload(
            resolved_fields,
            name_es="ACME Widget",
            price="1999.00",
            stock=12,
            category_id=42,
            sku=resolved_gbp.codigo,
        )

        submitted_payloads = []

        def _fake_publish(item: dict) -> dict:
            submitted_payloads.append(item["payload"])
            return {"status": "submitted", "product_id": 555}

        outcomes = execute_batch([{"ean": resolved_gbp.codigo, "payload": payload}], _fake_publish)
        assert len(outcomes) == 1
        assert outcomes[0].status == "submitted"
        assert outcomes[0].product_id == 555
        assert submitted_payloads == [payload]
