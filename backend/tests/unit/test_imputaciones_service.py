"""
Tests de `imputaciones_service` (COMPRAS-2.3 — base).

Cubre las operaciones base de F2:
  - Whitelist de los 6 combos válidos v1.
  - Validación de moneda consistente (cross-moneda permitido si TC > 0).
  - `crear_imputacion` básico + constraints.
  - `listar_por_origen` / `listar_por_destino`.
  - `monto_imputado_total_al_destino` (excluye reversals).

`distribuir_fifo` y `reimputar` se testean en F4 (no acá).
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.models.proveedor import OrigenProveedor, Proveedor
from app.services.imputaciones_service import (
    COMBOS_VALIDOS_V1,
    _validar_moneda_consistente,
    _validar_whitelist,
    crear_imputacion,
    listar_por_destino,
    listar_por_origen,
    monto_imputado_total_al_destino,
)


# ──────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────


@pytest.fixture
def proveedor(db) -> Proveedor:
    prov = Proveedor(
        id=1,
        nombre="Proveedor Test",
        activo=True,
        origen=OrigenProveedor.ERP.value,
    )
    db.add(prov)
    db.flush()
    return prov


@pytest.fixture
def user_id(active_user) -> int:
    return active_user.id


# ──────────────────────────────────────────────────────────────────────────
# Whitelist
# ──────────────────────────────────────────────────────────────────────────


class TestWhitelist:
    def test_whitelist_tiene_exactamente_10_combos(self) -> None:
        # Compras v1: 6 combos (orden_pago × 3 + nota_credito_erp × 3).
        # Compras v2: +3 combos para nota_credito_local × 3.
        # PR2: +1 combo (orden_pago, dinero_a_cuenta) para pago_a_cuenta.
        # PR4: +2 combos (dinero_a_cuenta → pedido_compra, dinero_a_cuenta → factura_erp).
        assert len(COMBOS_VALIDOS_V1) == 12

    def test_whitelist_contiene_los_combos_esperados(self) -> None:
        esperados = {
            ("orden_pago", "pedido_compra"),
            ("orden_pago", "factura_erp"),
            ("orden_pago", "saldo"),
            ("nota_credito_erp", "pedido_compra"),
            ("nota_credito_erp", "factura_erp"),
            ("nota_credito_erp", "saldo"),
            # Compras v2 — NCs locales como origen
            ("nota_credito_local", "pedido_compra"),
            ("nota_credito_local", "factura_erp"),
            ("nota_credito_local", "saldo"),
            # PR2 — dinero a cuenta como destino (pago_a_cuenta crea DAC)
            ("orden_pago", "dinero_a_cuenta"),
            # PR4 — dinero a cuenta como ORIGEN (consumo como medio de pago)
            ("dinero_a_cuenta", "pedido_compra"),
            ("dinero_a_cuenta", "factura_erp"),
        }
        assert COMBOS_VALIDOS_V1 == frozenset(esperados)

    @pytest.mark.parametrize("origen,destino", list(COMBOS_VALIDOS_V1))
    def test_todos_los_combos_validos_pasan(self, origen: str, destino: str) -> None:
        # No raise
        _validar_whitelist(origen, destino)

    def test_combo_invalido_raise_400(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            _validar_whitelist("orden_pago", "otro_destino")
        assert exc_info.value.status_code == 400
        assert "no soportada" in exc_info.value.detail

    def test_combo_invalido_origen_desconocido(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            _validar_whitelist("factura_propia", "pedido_compra")
        assert exc_info.value.status_code == 400


class TestMonedaConsistente:
    def test_monedas_iguales_pasan(self) -> None:
        _validar_moneda_consistente("ARS", "ARS")
        _validar_moneda_consistente("USD", "USD")

    def test_monedas_iguales_ignoran_tc(self) -> None:
        _validar_moneda_consistente("ARS", "ARS", tipo_cambio=None)
        _validar_moneda_consistente("ARS", "ARS", tipo_cambio=Decimal("1500"))
        _validar_moneda_consistente("USD", "USD", tipo_cambio=Decimal("0"))

    def test_cross_moneda_sin_tc_raise_400(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            _validar_moneda_consistente("ARS", "USD")
        assert exc_info.value.status_code == 400
        assert "Cross-moneda" in exc_info.value.detail

    def test_cross_moneda_tc_cero_raise_400(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            _validar_moneda_consistente("ARS", "USD", tipo_cambio=Decimal("0"))
        assert exc_info.value.status_code == 400
        assert "tipo_cambio > 0" in exc_info.value.detail

    def test_cross_moneda_tc_negativo_raise_400(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            _validar_moneda_consistente("USD", "ARS", tipo_cambio=Decimal("-100"))
        assert exc_info.value.status_code == 400

    def test_cross_moneda_con_tc_ok(self) -> None:
        _validar_moneda_consistente("ARS", "USD", tipo_cambio=Decimal("1500"))
        _validar_moneda_consistente("USD", "ARS", tipo_cambio=Decimal("0.000667"))

    # ── B.1 — REQ-MM-004 / design §2: cross-moneda unblock ────────────────

    def test_cross_moneda_con_tc_procede(self) -> None:
        """B.1 — cross-moneda con TC válido (OP ARS + pedido USD + TC) → OK.
        El bloqueo duro de v1 fue removido; ahora cross-moneda con TC procede.
        Spec: REQ-MM-004, design §2.
        """
        # Should not raise — cross-moneda is allowed when TC > 0.
        _validar_moneda_consistente("ARS", "USD", tipo_cambio=Decimal("1410"))
        _validar_moneda_consistente("USD", "ARS", tipo_cambio=Decimal("1450"))

    def test_cross_moneda_sin_tc_devuelve_422(self) -> None:
        """B.1 — cross-moneda sin tipo_cambio → HTTP 400 (guard correcto: TC requerido).
        Spec: REQ-MM-004, design §2.
        """
        with pytest.raises(HTTPException) as exc:
            _validar_moneda_consistente("ARS", "USD")
        assert exc.value.status_code == 400
        assert "Cross-moneda" in exc.value.detail
        assert "tipo_cambio > 0" in exc.value.detail

    def test_same_moneda_ars_sin_tc_procede(self) -> None:
        """B.1 — same-moneda ARS sin tipo_cambio → OK (no requiere TC).
        Spec: REQ-MM-004, design §2.
        """
        # No raise expected — same-moneda ignores TC.
        _validar_moneda_consistente("ARS", "ARS")
        _validar_moneda_consistente("ARS", "ARS", tipo_cambio=None)


# ──────────────────────────────────────────────────────────────────────────
# crear_imputacion
# ──────────────────────────────────────────────────────────────────────────


class TestCrearImputacion:
    def test_crear_imputacion_basica_ok(self, db, proveedor, user_id) -> None:
        imp = crear_imputacion(
            db,
            origen_tipo="orden_pago",
            origen_id=100,
            destino_tipo="pedido_compra",
            destino_id=200,
            monto_imputado=Decimal("1500.00"),
            moneda_imputada="ARS",
            proveedor_id=proveedor.id,
            creado_por_id=user_id,
        )
        assert imp.id is not None
        assert imp.origen_tipo == "orden_pago"
        assert imp.destino_tipo == "pedido_compra"
        assert imp.monto_imputado == Decimal("1500.00")
        assert imp.es_reversal is False

    def test_crear_imputacion_destino_saldo_con_destino_id_null(self, db, proveedor, user_id) -> None:
        imp = crear_imputacion(
            db,
            origen_tipo="orden_pago",
            origen_id=100,
            destino_tipo="saldo",
            destino_id=None,
            monto_imputado=Decimal("500.00"),
            moneda_imputada="ARS",
            proveedor_id=proveedor.id,
            creado_por_id=user_id,
        )
        assert imp.destino_tipo == "saldo"
        assert imp.destino_id is None

    def test_crear_imputacion_monto_cero_raise_400(self, db, proveedor, user_id) -> None:
        with pytest.raises(HTTPException) as exc_info:
            crear_imputacion(
                db,
                origen_tipo="orden_pago",
                origen_id=100,
                destino_tipo="pedido_compra",
                destino_id=200,
                monto_imputado=Decimal("0"),
                moneda_imputada="ARS",
                proveedor_id=proveedor.id,
                creado_por_id=user_id,
            )
        assert exc_info.value.status_code == 400
        assert "monto_imputado" in exc_info.value.detail

    def test_crear_imputacion_combo_invalido_raise_400(self, db, proveedor, user_id) -> None:
        with pytest.raises(HTTPException) as exc_info:
            crear_imputacion(
                db,
                origen_tipo="orden_pago",
                origen_id=100,
                destino_tipo="otro_tipo_raro",
                destino_id=200,
                monto_imputado=Decimal("100"),
                moneda_imputada="ARS",
                proveedor_id=proveedor.id,
                creado_por_id=user_id,
            )
        assert exc_info.value.status_code == 400

    def test_crear_imputacion_saldo_con_destino_id_raise_400(self, db, proveedor, user_id) -> None:
        """destino='saldo' obliga destino_id=None."""
        with pytest.raises(HTTPException) as exc_info:
            crear_imputacion(
                db,
                origen_tipo="orden_pago",
                origen_id=100,
                destino_tipo="saldo",
                destino_id=999,  # inválido
                monto_imputado=Decimal("100"),
                moneda_imputada="ARS",
                proveedor_id=proveedor.id,
                creado_por_id=user_id,
            )
        assert exc_info.value.status_code == 400
        assert "saldo" in exc_info.value.detail

    def test_crear_imputacion_no_saldo_sin_destino_id_raise_400(self, db, proveedor, user_id) -> None:
        """destino != 'saldo' obliga destino_id no null."""
        with pytest.raises(HTTPException) as exc_info:
            crear_imputacion(
                db,
                origen_tipo="orden_pago",
                origen_id=100,
                destino_tipo="pedido_compra",
                destino_id=None,
                monto_imputado=Decimal("100"),
                moneda_imputada="ARS",
                proveedor_id=proveedor.id,
                creado_por_id=user_id,
            )
        assert exc_info.value.status_code == 400


# ──────────────────────────────────────────────────────────────────────────
# Listados
# ──────────────────────────────────────────────────────────────────────────


class TestListados:
    def test_listar_por_origen_retorna_todas_las_imputaciones(self, db, proveedor, user_id) -> None:
        # 2 imputaciones con mismo origen, 1 con otro origen
        _ = crear_imputacion(
            db,
            origen_tipo="orden_pago",
            origen_id=100,
            destino_tipo="pedido_compra",
            destino_id=201,
            monto_imputado=Decimal("100"),
            moneda_imputada="ARS",
            proveedor_id=proveedor.id,
            creado_por_id=user_id,
        )
        _ = crear_imputacion(
            db,
            origen_tipo="orden_pago",
            origen_id=100,
            destino_tipo="pedido_compra",
            destino_id=202,
            monto_imputado=Decimal("200"),
            moneda_imputada="ARS",
            proveedor_id=proveedor.id,
            creado_por_id=user_id,
        )
        _ = crear_imputacion(
            db,
            origen_tipo="orden_pago",
            origen_id=999,
            destino_tipo="pedido_compra",
            destino_id=300,
            monto_imputado=Decimal("300"),
            moneda_imputada="ARS",
            proveedor_id=proveedor.id,
            creado_por_id=user_id,
        )

        resultado = listar_por_origen(db, origen_tipo="orden_pago", origen_id=100)
        assert len(resultado) == 2
        assert {i.destino_id for i in resultado} == {201, 202}

    def test_listar_por_destino(self, db, proveedor, user_id) -> None:
        _ = crear_imputacion(
            db,
            origen_tipo="orden_pago",
            origen_id=100,
            destino_tipo="factura_erp",
            destino_id=500,
            monto_imputado=Decimal("1000"),
            moneda_imputada="ARS",
            proveedor_id=proveedor.id,
            creado_por_id=user_id,
        )
        _ = crear_imputacion(
            db,
            origen_tipo="nota_credito_erp",
            origen_id=77,
            destino_tipo="factura_erp",
            destino_id=500,
            monto_imputado=Decimal("250"),
            moneda_imputada="ARS",
            proveedor_id=proveedor.id,
            creado_por_id=user_id,
        )

        resultado = listar_por_destino(db, destino_tipo="factura_erp", destino_id=500)
        assert len(resultado) == 2
        assert {i.origen_tipo for i in resultado} == {"orden_pago", "nota_credito_erp"}


# ──────────────────────────────────────────────────────────────────────────
# Sumatoria excluyendo reversals
# ──────────────────────────────────────────────────────────────────────────


class TestMontoImputadoTotal:
    def test_suma_excluye_reversals(self, db, proveedor, user_id) -> None:
        _ = crear_imputacion(
            db,
            origen_tipo="orden_pago",
            origen_id=100,
            destino_tipo="pedido_compra",
            destino_id=201,
            monto_imputado=Decimal("1000"),
            moneda_imputada="ARS",
            proveedor_id=proveedor.id,
            creado_por_id=user_id,
        )
        # Reversal (append-only): misma imputación pero es_reversal=True — NO suma.
        _ = crear_imputacion(
            db,
            origen_tipo="orden_pago",
            origen_id=100,
            destino_tipo="pedido_compra",
            destino_id=201,
            monto_imputado=Decimal("1000"),
            moneda_imputada="ARS",
            proveedor_id=proveedor.id,
            creado_por_id=user_id,
            es_reversal=True,
        )

        total = monto_imputado_total_al_destino(db, destino_tipo="pedido_compra", destino_id=201, moneda="ARS")
        assert total == Decimal("1000")

    def test_suma_dos_imputaciones_mismo_destino(self, db, proveedor, user_id) -> None:
        _ = crear_imputacion(
            db,
            origen_tipo="orden_pago",
            origen_id=100,
            destino_tipo="factura_erp",
            destino_id=500,
            monto_imputado=Decimal("300"),
            moneda_imputada="ARS",
            proveedor_id=proveedor.id,
            creado_por_id=user_id,
        )
        _ = crear_imputacion(
            db,
            origen_tipo="nota_credito_erp",
            origen_id=77,
            destino_tipo="factura_erp",
            destino_id=500,
            monto_imputado=Decimal("700"),
            moneda_imputada="ARS",
            proveedor_id=proveedor.id,
            creado_por_id=user_id,
        )

        total = monto_imputado_total_al_destino(db, destino_tipo="factura_erp", destino_id=500, moneda="ARS")
        assert total == Decimal("1000")

    def test_suma_filtra_por_moneda(self, db, proveedor, user_id) -> None:
        _ = crear_imputacion(
            db,
            origen_tipo="orden_pago",
            origen_id=100,
            destino_tipo="factura_erp",
            destino_id=500,
            monto_imputado=Decimal("1000"),
            moneda_imputada="ARS",
            proveedor_id=proveedor.id,
            creado_por_id=user_id,
        )
        _ = crear_imputacion(
            db,
            origen_tipo="orden_pago",
            origen_id=101,
            destino_tipo="factura_erp",
            destino_id=500,
            monto_imputado=Decimal("50"),
            moneda_imputada="USD",
            proveedor_id=proveedor.id,
            creado_por_id=user_id,
        )

        total_ars = monto_imputado_total_al_destino(db, destino_tipo="factura_erp", destino_id=500, moneda="ARS")
        total_usd = monto_imputado_total_al_destino(db, destino_tipo="factura_erp", destino_id=500, moneda="USD")
        assert total_ars == Decimal("1000")
        assert total_usd == Decimal("50")

    def test_suma_sin_imputaciones_retorna_cero(self, db, proveedor, user_id) -> None:
        total = monto_imputado_total_al_destino(db, destino_tipo="factura_erp", destino_id=9999, moneda="ARS")
        assert total == Decimal("0")


# ──────────────────────────────────────────────────────────────────────────
# F4 — distribuir_fifo / desimputar / reimputar (COMPRAS-4.3/4.4/4.5)
# ──────────────────────────────────────────────────────────────────────────


@pytest.fixture
def empresa_fifo(db):
    from app.models.empresa import Empresa  # noqa: PLC0415

    emp = Empresa(id=1, nombre="Emp FIFO", activo=True, orden=0)
    db.add(emp)
    db.flush()
    return emp


class TestDesimputar:
    def test_desimputar_happy_path(self, db, proveedor, user_id, empresa_fifo) -> None:
        from app.services.imputaciones_service import desimputar  # noqa: PLC0415

        imp = crear_imputacion(
            db,
            origen_tipo="orden_pago",
            origen_id=100,
            destino_tipo="pedido_compra",
            destino_id=200,
            monto_imputado=Decimal("500"),
            moneda_imputada="ARS",
            proveedor_id=proveedor.id,
            creado_por_id=user_id,
        )

        # aplicar_imputacion (que ocurre en el flow real antes de desimputar)
        from app.services import cc_proveedor_service  # noqa: PLC0415

        cc_proveedor_service.aplicar_imputacion(db, imputacion_id=imp.id)

        reversal = desimputar(db, imputacion_id=imp.id, user_id=user_id, motivo="test")
        assert reversal.id != imp.id
        assert reversal.es_reversal is True
        assert reversal.reimputada_desde_id == imp.id
        assert reversal.destino_tipo == imp.destino_tipo
        assert reversal.destino_id == imp.destino_id
        assert reversal.monto_imputado == imp.monto_imputado

    def test_desimputar_un_reversal_raise_400(self, db, proveedor, user_id, empresa_fifo) -> None:
        from app.services.imputaciones_service import desimputar  # noqa: PLC0415

        imp = crear_imputacion(
            db,
            origen_tipo="orden_pago",
            origen_id=100,
            destino_tipo="pedido_compra",
            destino_id=200,
            monto_imputado=Decimal("500"),
            moneda_imputada="ARS",
            proveedor_id=proveedor.id,
            creado_por_id=user_id,
            es_reversal=True,
        )
        with pytest.raises(HTTPException) as exc:
            desimputar(db, imputacion_id=imp.id, user_id=user_id)
        assert exc.value.status_code == 400

    def test_reversal_cross_moneda_genera_debe_en_moneda_destino(self, db, proveedor, user_id, empresa_fifo) -> None:
        """
        Reversal de una imputación cross-moneda (OP ARS → pedido USD con TC):
        el reversal copia `moneda_imputada=USD` + `monto_imputado` USD +
        `tipo_cambio` original. La proyección al CC genera un DEBE en USD
        (compensando el HABER USD que generó la imp original).

        Append-only sagrado: el reversal es un INSERT nuevo con `es_reversal=True`
        y `reimputada_desde_id` apuntando a la original.
        """
        from app.services import cc_proveedor_service  # noqa: PLC0415
        from app.models.cc_proveedor_movimiento import CCProveedorMovimiento  # noqa: PLC0415
        from app.services.imputaciones_service import desimputar  # noqa: PLC0415

        # Imp original cross-moneda: OP ARS paga pedido USD por 666.67 USD con TC=1500.
        imp_original = crear_imputacion(
            db,
            origen_tipo="orden_pago",
            origen_id=100,
            destino_tipo="pedido_compra",
            destino_id=200,
            monto_imputado=Decimal("666.67"),
            moneda_imputada="USD",
            proveedor_id=proveedor.id,
            creado_por_id=user_id,
            tipo_cambio=Decimal("1500"),
        )
        cc_proveedor_service.aplicar_imputacion(db, imputacion_id=imp_original.id)

        # Verificar HABER USD original en CC.
        movs_original = (
            db.query(CCProveedorMovimiento)
            .filter(
                CCProveedorMovimiento.origen_tipo == "imputacion",
                CCProveedorMovimiento.origen_id == imp_original.id,
            )
            .all()
        )
        assert len(movs_original) == 1
        assert movs_original[0].tipo == "haber"
        assert movs_original[0].monto == Decimal("666.67")
        assert movs_original[0].moneda == "USD"

        # Desimputar — el reversal copia moneda, monto y TC originales.
        reversal = desimputar(db, imputacion_id=imp_original.id, user_id=user_id, motivo="test cross")
        assert reversal.es_reversal is True
        assert reversal.reimputada_desde_id == imp_original.id
        assert reversal.moneda_imputada == "USD"
        assert reversal.monto_imputado == Decimal("666.67")
        assert reversal.tipo_cambio == Decimal("1500")

        # CC mov del reversal: DEBE en USD (compensación del HABER original).
        # NOTE: cc_proveedor_service usa origen_tipo='reimputacion' (no 'imputacion')
        # cuando la imp fuente es es_reversal=True.
        movs_reversal = (
            db.query(CCProveedorMovimiento)
            .filter(
                CCProveedorMovimiento.origen_tipo == "reimputacion",
                CCProveedorMovimiento.origen_id == reversal.id,
            )
            .all()
        )
        assert len(movs_reversal) == 1
        assert movs_reversal[0].tipo == "debe"
        assert movs_reversal[0].monto == Decimal("666.67")
        assert movs_reversal[0].moneda == "USD"


class TestReimputar:
    def test_reimputar_crea_2_filas(self, db, proveedor, user_id, empresa_fifo) -> None:
        from app.services.imputaciones_service import reimputar  # noqa: PLC0415

        imp = crear_imputacion(
            db,
            origen_tipo="orden_pago",
            origen_id=100,
            destino_tipo="pedido_compra",
            destino_id=200,
            monto_imputado=Decimal("500"),
            moneda_imputada="ARS",
            proveedor_id=proveedor.id,
            creado_por_id=user_id,
        )

        reversal, nueva = reimputar(
            db,
            imputacion_id=imp.id,
            nuevo_destino_tipo="factura_erp",
            nuevo_destino_id=300,
            user_id=user_id,
        )
        assert reversal.es_reversal is True
        assert reversal.destino_tipo == "pedido_compra"
        assert reversal.destino_id == 200
        assert reversal.reimputada_desde_id == imp.id

        assert nueva.es_reversal is False
        assert nueva.destino_tipo == "factura_erp"
        assert nueva.destino_id == 300
        assert nueva.reimputada_desde_id == imp.id

    def test_reimputar_ya_reimputada_raise_400(self, db, proveedor, user_id, empresa_fifo) -> None:
        """D13: no se puede reimputar en cadena."""
        from app.services.imputaciones_service import reimputar  # noqa: PLC0415

        imp = crear_imputacion(
            db,
            origen_tipo="orden_pago",
            origen_id=100,
            destino_tipo="pedido_compra",
            destino_id=200,
            monto_imputado=Decimal("500"),
            moneda_imputada="ARS",
            proveedor_id=proveedor.id,
            creado_por_id=user_id,
        )

        reimputar(
            db,
            imputacion_id=imp.id,
            nuevo_destino_tipo="factura_erp",
            nuevo_destino_id=300,
            user_id=user_id,
        )
        # Reimputar de nuevo la original → 400
        with pytest.raises(HTTPException) as exc:
            reimputar(
                db,
                imputacion_id=imp.id,
                nuevo_destino_tipo="saldo",
                nuevo_destino_id=None,
                user_id=user_id,
            )
        assert exc.value.status_code == 400

    def test_reimputar_combo_invalido_raise_400(self, db, proveedor, user_id, empresa_fifo) -> None:
        from app.services.imputaciones_service import reimputar  # noqa: PLC0415

        imp = crear_imputacion(
            db,
            origen_tipo="orden_pago",
            origen_id=100,
            destino_tipo="pedido_compra",
            destino_id=200,
            monto_imputado=Decimal("500"),
            moneda_imputada="ARS",
            proveedor_id=proveedor.id,
            creado_por_id=user_id,
        )
        with pytest.raises(HTTPException) as exc:
            reimputar(
                db,
                imputacion_id=imp.id,
                nuevo_destino_tipo="combo_invalido",
                nuevo_destino_id=999,
                user_id=user_id,
            )
        assert exc.value.status_code == 400


class TestDistribuirFifo:
    def test_distribuir_fifo_remanente_va_a_saldo(self, db, proveedor, user_id, empresa_fifo) -> None:
        """OP a_cuenta sin pedidos previos → toda la plata va a saldo."""
        from app.models.orden_pago import OrdenPago  # noqa: PLC0415
        from app.services.imputaciones_service import distribuir_fifo  # noqa: PLC0415

        op = OrdenPago(
            numero="OP-01-2026-00001",
            empresa_id=empresa_fifo.id,
            proveedor_id=proveedor.id,
            moneda="ARS",
            monto_total=Decimal("1500"),
            modo_imputacion="a_cuenta",
            estado="pendiente",
            creado_por_id=user_id,
        )
        db.add(op)
        db.flush()

        imps = distribuir_fifo(db, orden_pago_id=op.id, user_id=user_id)
        assert len(imps) == 1
        assert imps[0].destino_tipo == "saldo"
        assert imps[0].monto_imputado == Decimal("1500")

    def test_distribuir_fifo_con_pedido_pendiente(self, db, proveedor, user_id, empresa_fifo) -> None:
        from app.models.orden_pago import OrdenPago  # noqa: PLC0415
        from app.models.pedido_compra import PedidoCompra  # noqa: PLC0415
        from app.services.imputaciones_service import distribuir_fifo  # noqa: PLC0415

        # Pedido aprobado con saldo
        pedido = PedidoCompra(
            numero="P-01-2026-00001",
            empresa_id=empresa_fifo.id,
            proveedor_id=proveedor.id,
            moneda="ARS",
            monto=Decimal("800"),
            estado="aprobado",
            creado_por_id=user_id,
        )
        db.add(pedido)
        db.flush()

        op = OrdenPago(
            numero="OP-01-2026-00001",
            empresa_id=empresa_fifo.id,
            proveedor_id=proveedor.id,
            moneda="ARS",
            monto_total=Decimal("1500"),
            modo_imputacion="a_cuenta",
            estado="pendiente",
            creado_por_id=user_id,
        )
        db.add(op)
        db.flush()

        imps = distribuir_fifo(db, orden_pago_id=op.id, user_id=user_id)
        # 1 imputación al pedido + 1 a saldo del remanente
        assert len(imps) == 2
        assert imps[0].destino_tipo == "pedido_compra"
        assert imps[0].destino_id == pedido.id
        assert imps[0].monto_imputado == Decimal("800")
        assert imps[1].destino_tipo == "saldo"
        assert imps[1].monto_imputado == Decimal("700")


# ──────────────────────────────────────────────────────────────────────────
# Fix: `desimputar` debe recalcular el estado del pedido destino cuando
# la imputación revertida apuntaba a un `pedido_compra`. Antes del fix,
# desimputar aisladamente una NC/OP aplicada dejaba el pedido en
# `pagado_parcial` o `pagado` inconsistente con su saldo real.
# ──────────────────────────────────────────────────────────────────────────


class TestDesimputarRecalculaEstadoPedido:
    """
    Covers la orquestación agregada en `desimputar`:
    `pedidos_service.recalcular_estado_por_imputaciones` se invoca
    cuando el destino de la imputación revertida es `pedido_compra`.
    """

    def test_desimputar_nc_a_pedido_recalcula_estado_pedido(self, db, proveedor, user_id, empresa_fifo) -> None:
        """
        Escenario:
          1. NC aprobada de $1000 + pedido aprobado de $1500.
          2. Aplicar NC al pedido → pedido pasa a `pagado_parcial` (saldo $500).
          3. Desimputar aisladamente → pedido vuelve a `aprobado` y NC a `aprobado`.
        """
        from datetime import date  # noqa: PLC0415

        from app.models.nota_credito_local import NotaCreditoLocal  # noqa: PLC0415
        from app.models.pedido_compra import PedidoCompra  # noqa: PLC0415
        from app.services import cc_proveedor_service  # noqa: PLC0415
        from app.services.imputaciones_service import desimputar  # noqa: PLC0415

        pedido = PedidoCompra(
            numero="P-FX3-00001",
            empresa_id=empresa_fifo.id,
            proveedor_id=proveedor.id,
            moneda="ARS",
            monto=Decimal("1500"),
            estado="aprobado",
            creado_por_id=user_id,
        )
        db.add(pedido)
        db.flush()

        nc = NotaCreditoLocal(
            numero="NCL-FX3-0001",
            proveedor_id=proveedor.id,
            empresa_id=empresa_fifo.id,
            moneda="ARS",
            monto=Decimal("1000"),
            motivo="test",
            fecha_emision=date.today(),
            estado="aprobado",
            aprobado_por_id=user_id,
            creado_por_id=user_id,
        )
        db.add(nc)
        db.flush()

        imp = crear_imputacion(
            db,
            origen_tipo="nota_credito_local",
            origen_id=nc.id,
            destino_tipo="pedido_compra",
            destino_id=pedido.id,
            monto_imputado=Decimal("1000"),
            moneda_imputada="ARS",
            proveedor_id=proveedor.id,
            creado_por_id=user_id,
        )
        cc_proveedor_service.aplicar_imputacion(db, imputacion_id=imp.id)

        # Disparar transición pedido por la imputación creada
        from app.services import pedidos_service  # noqa: PLC0415

        pedidos_service.aplicar_imputacion_a_pedido(db, pedido_id=pedido.id, monto_imputado=Decimal("1000"))
        db.refresh(pedido)
        db.refresh(nc)
        assert pedido.estado == "pagado_parcial"
        assert nc.estado == "aplicada"

        # --- Acto bajo test: desimputar aisladamente ---
        desimputar(db, imputacion_id=imp.id, user_id=user_id, motivo="ajuste manual")

        db.refresh(pedido)
        db.refresh(nc)
        assert pedido.estado == "aprobado", (
            f"desimputar NC sobre pedido debería devolver el pedido a 'aprobado' pero quedó en '{pedido.estado}'"
        )
        assert nc.estado == "aprobado"

    def test_desimputar_op_a_pedido_recalcula_estado_pedido(self, db, proveedor, user_id, empresa_fifo) -> None:
        """
        Escenario simétrico al anterior pero con OP como origen:
          1. Pedido aprobado de $1500 + OP pagada de $1500 imputada al pedido.
          2. Pedido queda en `pagado`.
          3. Desimputar aisladamente (no anular OP) → pedido vuelve a `aprobado`.
        """
        from app.models.orden_pago import OrdenPago  # noqa: PLC0415
        from app.models.pedido_compra import PedidoCompra  # noqa: PLC0415
        from app.services import cc_proveedor_service, pedidos_service  # noqa: PLC0415
        from app.services.imputaciones_service import desimputar  # noqa: PLC0415

        pedido = PedidoCompra(
            numero="P-FX3-00002",
            empresa_id=empresa_fifo.id,
            proveedor_id=proveedor.id,
            moneda="ARS",
            monto=Decimal("1500"),
            estado="aprobado",
            creado_por_id=user_id,
        )
        db.add(pedido)
        db.flush()

        op = OrdenPago(
            numero="OP-FX3-00001",
            empresa_id=empresa_fifo.id,
            proveedor_id=proveedor.id,
            moneda="ARS",
            monto_total=Decimal("1500"),
            modo_imputacion="especifica",
            estado="pagado",
            creado_por_id=user_id,
        )
        db.add(op)
        db.flush()

        imp = crear_imputacion(
            db,
            origen_tipo="orden_pago",
            origen_id=op.id,
            destino_tipo="pedido_compra",
            destino_id=pedido.id,
            monto_imputado=Decimal("1500"),
            moneda_imputada="ARS",
            proveedor_id=proveedor.id,
            creado_por_id=user_id,
        )
        cc_proveedor_service.aplicar_imputacion(db, imputacion_id=imp.id)
        pedidos_service.aplicar_imputacion_a_pedido(db, pedido_id=pedido.id, monto_imputado=Decimal("1500"))
        db.refresh(pedido)
        assert pedido.estado == "pagado"

        # --- Acto bajo test: desimputar aisladamente ---
        desimputar(db, imputacion_id=imp.id, user_id=user_id, motivo="ajuste manual")

        db.refresh(pedido)
        assert pedido.estado == "aprobado", (
            f"desimputar OP sobre pedido (sin anular la OP) debería devolver el "
            f"pedido a 'aprobado' pero quedó en '{pedido.estado}'"
        )
