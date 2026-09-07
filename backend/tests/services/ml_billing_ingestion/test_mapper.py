"""
RED/GREEN — `map_billing_detail` (ml-ventas-desglose-costos, corte 2).

Spec coverage:
  REQ-1 — sign: `detail_type == "BONUS"` -> amount is NEGATIVE.
          `detail_type == "CHARGE"` -> amount is POSITIVE. All amounts
          arrive positive from ML (investigation §6/§5.b) -- the mapper
          is the ONLY place that applies a sign.
  REQ-2 — the sign is decided by `detail_type`, a real field, NEVER by a
          string-prefix heuristic on `detail_sub_type` (a sub_type
          starting with "B" but `detail_type == "CHARGE"` stays POSITIVE).
  REQ-3 (PII) — `sales_info[].payer_nickname` / `sales_info[].state_name`
          are discarded before `raw_detail` is built; neither key/value
          may appear anywhere in the resulting `raw_detail`.
  REQ-4 — `order_ids` is the deduped list of `items_info[].order_id`,
          coerced to `int` (BigInteger-range safe).
"""

from __future__ import annotations

from decimal import Decimal

from app.services.ml_billing_ingestion.mapper import BillingChargeDTO, MappingError, map_billing_detail


def _raw_detail(**overrides):
    base = {
        "charge_info": {
            "detail_id": "12345",
            "detail_type": "CHARGE",
            "detail_sub_type": "CVFV",
            "detail_amount": 91250,
            "transaction_detail": "Cargo por vender",
            "creation_date_time": "2026-09-01T10:00:00.000-04:00",
        },
        "items_info": [{"order_id": 2000018265495500, "item_id": "MLA123"}],
        "sales_info": [
            {
                "order_id": 2000018265495500,
                "operation_id": "OP1",
                "payer_nickname": "SECRETO123",
                "state_name": "Buenos Aires",
            }
        ],
        "shipping_info": {},
        "discount_info": {},
        "document_info": {"document_id": "DOC1"},
    }
    base.update(overrides)
    return base


class TestSign:
    def test_charge_is_positive(self) -> None:
        raw = _raw_detail()
        result = map_billing_detail(raw, period_key="2026-09-01")

        assert isinstance(result, BillingChargeDTO)
        assert result.amount == 91250.0

    def test_bonus_is_negative(self) -> None:
        raw = _raw_detail()
        raw["charge_info"]["detail_type"] = "BONUS"
        result = map_billing_detail(raw, period_key="2026-09-01")

        assert isinstance(result, BillingChargeDTO)
        assert result.amount == -91250.0

    def test_sub_type_b_prefix_with_charge_type_stays_positive(self) -> None:
        """`detail_sub_type` starting with "B" (e.g. a real ML reversal code
        like BVFV) is NOT the sign rule. Only `detail_type` decides."""
        raw = _raw_detail()
        raw["charge_info"]["detail_sub_type"] = "BVFV"
        raw["charge_info"]["detail_type"] = "CHARGE"
        result = map_billing_detail(raw, period_key="2026-09-01")

        assert isinstance(result, BillingChargeDTO)
        assert result.amount == 91250.0


class TestPii:
    def test_payer_nickname_and_state_name_are_stripped(self) -> None:
        raw = _raw_detail()
        result = map_billing_detail(raw, period_key="2026-09-01")

        assert isinstance(result, BillingChargeDTO)
        serialized = str(result.raw_detail)
        assert "SECRETO123" not in serialized
        assert "payer_nickname" not in serialized
        assert "Buenos Aires" not in serialized
        assert "state_name" not in serialized
        # everything else in sales_info survives
        assert "OP1" in serialized


class TestOrderIds:
    def test_order_ids_from_items_info_deduped(self) -> None:
        raw = _raw_detail()
        raw["items_info"] = [
            {"order_id": 2000018265495500, "item_id": "MLA1"},
            {"order_id": 2000018265495500, "item_id": "MLA2"},
            {"order_id": 2000018265495501, "item_id": "MLA3"},
        ]
        result = map_billing_detail(raw, period_key="2026-09-01")

        assert isinstance(result, BillingChargeDTO)
        assert result.order_ids == [2000018265495500, 2000018265495501]


class TestMappingError:
    def test_missing_detail_id_is_mapping_error(self) -> None:
        raw = _raw_detail()
        del raw["charge_info"]["detail_id"]
        result = map_billing_detail(raw, period_key="2026-09-01")

        assert isinstance(result, MappingError)


class TestAmountIsDecimalNotFloat:
    """La columna es `Numeric(14, 2)` y estos montos se suman de a miles
    para armar el "Neto" de una venta. Binario flotante en el camino del
    dinero introduce un error que decimal no tiene."""

    def test_amount_is_decimal(self) -> None:
        raw = _raw_detail()
        result = map_billing_detail(raw, period_key="2026-09-01")

        assert isinstance(result.amount, Decimal)
        assert not isinstance(result.amount, float)

    def test_a_float_from_ml_does_not_carry_its_binary_noise(self) -> None:
        """ML manda `detail_amount` como número JSON, que llega como float.
        Convertir con `str()` primero corta el ruido binario ahí mismo, en
        vez de arrastrarlo a la suma."""
        raw = _raw_detail()
        raw["charge_info"]["detail_amount"] = 1125.60
        result = map_billing_detail(raw, period_key="2026-09-01")

        assert result.amount == Decimal("1125.60")
        # La vía ingenua arrastra el ruido; la nuestra no.
        assert Decimal(1125.60) != Decimal("1125.60")

    def test_a_bonus_stays_decimal_when_negated(self) -> None:
        raw = _raw_detail()
        raw["charge_info"]["detail_type"] = "BONUS"
        result = map_billing_detail(raw, period_key="2026-09-01")

        assert isinstance(result.amount, Decimal)
        assert result.amount < 0


class TestNeverRaises:
    """El contrato del mapper es fail-closed: cualquier cargo raro vuelve
    como `MappingError`, nunca como excepción. Un solo detalle malo no
    puede voltear el barrido diario de 18.000 cargos."""

    def test_un_detail_amount_no_numerico_no_levanta(self) -> None:
        """`Decimal(str("N/A"))` levanta `InvalidOperation`, que hereda de
        `ArithmeticError` y NO de `ValueError`.

        Cuando el mapper usaba `float()` alcanzaba con `ValueError` en el
        `except`; al pasar a Decimal por el camino del dinero, ese contrato
        se rompió en silencio. Este test lo fija."""
        raw = _raw_detail()
        raw["charge_info"]["detail_amount"] = "N/A"

        result = map_billing_detail(raw, period_key="2026-09-01")

        assert isinstance(result, MappingError)

    def test_un_monto_con_formato_local_no_levanta(self) -> None:
        raw = _raw_detail()
        raw["charge_info"]["detail_amount"] = "1.234,56"

        result = map_billing_detail(raw, period_key="2026-09-01")

        assert isinstance(result, MappingError)

    def test_un_detalle_que_no_es_dict_no_levanta(self) -> None:
        """ML devuelve `results: [...]`; un elemento que no sea dict
        rompería en el primer `.get()` con AttributeError."""
        for basura in (["no", "soy", "dict"], "un string", 42, None):
            result = map_billing_detail(basura, period_key="2026-09-01")
            assert isinstance(result, MappingError), f"falló con {basura!r}"


class TestErrorPathAlsoStripsPii:
    """El happy path descarta `payer_nickname` y `state_name`. El camino de
    ERROR guardaba el payload crudo — y `MappingError.raw_payload` existe
    justamente para que el barrido lo loguee o lo persista."""

    def test_un_mapping_error_no_lleva_pii(self) -> None:
        raw = _raw_detail()
        raw["charge_info"]["detail_amount"] = "N/A"  # fuerza el error
        raw["sales_info"] = [{"order_id": 2000018265495500, "payer_nickname": "INU03", "state_name": "CORDOBA"}]

        result = map_billing_detail(raw, period_key="2026-09-01")

        assert isinstance(result, MappingError)
        serializado = str(result.raw_payload)
        assert "INU03" not in serializado
        assert "CORDOBA" not in serializado
        # y no se perdió lo que sí sirve para diagnosticar
        assert "2000018265495500" in serializado

    def test_las_tres_salidas_de_error_filtran_la_pii(self) -> None:
        """El mapper tiene TRES salidas de error, no una. La primera versión
        de este arreglo filtró solo la del `except` y dejó las dos salidas
        tempranas devolviendo el payload crudo — con la de
        `missing detail_id`, que es la que llega CON `sales_info` entera.

        Este test recorre las tres a propósito: arreglar una instancia de un
        patrón y dejar las hermanas es exactamente cómo vuelve el agujero.
        """
        pii = [{"order_id": 2000018265495500, "payer_nickname": "INU03", "state_name": "CORDOBA"}]

        sin_detail_id = _raw_detail()
        sin_detail_id["charge_info"].pop("detail_id", None)
        sin_detail_id["sales_info"] = pii

        monto_roto = _raw_detail()
        monto_roto["charge_info"]["detail_amount"] = "N/A"
        monto_roto["sales_info"] = pii

        for nombre, raw in (("sin detail_id", sin_detail_id), ("monto no numérico", monto_roto)):
            result = map_billing_detail(raw, period_key="2026-09-01")
            assert isinstance(result, MappingError), nombre
            serializado = str(result.raw_payload)
            assert "INU03" not in serializado, f"PII filtrada en: {nombre}"
            assert "CORDOBA" not in serializado, f"PII filtrada en: {nombre}"

        # La tercera salida (raw que no es dict) no puede llevar PII porque
        # no es un dict, pero pasa por el mismo filtro igual.
        assert isinstance(map_billing_detail(["no soy dict"], period_key="2026-09-01"), MappingError)
