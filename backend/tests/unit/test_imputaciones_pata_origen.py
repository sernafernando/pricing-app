"""
Tests de la pata origen de `imputaciones` (compras_038, etapa 1).

Una imputación vincula un documento ORIGEN con uno DESTINO. En cross-moneda
los dos lados NO son el mismo número, así que la fila registra ambos:

  - `monto_origen` / `moneda_origen`     → consumido del ORIGEN.
  - `monto_imputado` / `moneda_imputada` → aplicado al DESTINO.

Acá se cubre el chokepoint de escritura (`crear_imputacion`) y la propagación
correcta a los reversals. Las lecturas origin-side viven en
`test_imputaciones_saldo_origen.py`.
"""

from __future__ import annotations

import inspect
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.models.empresa import Empresa
from app.models.imputacion import Imputacion
from app.models.proveedor import OrigenProveedor, Proveedor
from app.services import imputaciones_service
from app.services.imputaciones_service import crear_imputacion

# ──────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────


@pytest.fixture
def empresa(db) -> Empresa:
    """`desimputar`/`reimputar` proyectan a CC, que exige una empresa real."""
    e = Empresa(id=1, nombre="EmpresaTest", activo=True, orden=0)
    db.add(e)
    db.flush()
    return e


@pytest.fixture
def proveedor(db, empresa) -> Proveedor:
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


def _crear(db, proveedor: Proveedor, user_id: int, **overrides) -> Imputacion:
    kwargs = {
        "origen_tipo": "orden_pago",
        "origen_id": 100,
        "destino_tipo": "pedido_compra",
        "destino_id": 200,
        "monto_imputado": Decimal("1500.00"),
        "moneda_imputada": "ARS",
        "monto_origen": Decimal("1500.00"),
        "moneda_origen": "ARS",
        "proveedor_id": proveedor.id,
        "creado_por_id": user_id,
    }
    kwargs.update(overrides)
    return crear_imputacion(db, **kwargs)


# ──────────────────────────────────────────────────────────────────────────
# La pata origen es obligatoria
# ──────────────────────────────────────────────────────────────────────────


class TestPataOrigenObligatoria:
    """El punto entero del cambio: ningún call site puede olvidarse la pata
    origen en silencio. Por eso son parámetros REQUERIDOS, no opcionales con
    default a la pata destino."""

    def test_monto_origen_no_tiene_default(self) -> None:
        param = inspect.signature(crear_imputacion).parameters["monto_origen"]
        assert param.default is inspect.Parameter.empty

    def test_moneda_origen_no_tiene_default(self) -> None:
        param = inspect.signature(crear_imputacion).parameters["moneda_origen"]
        assert param.default is inspect.Parameter.empty

    def test_omitir_la_pata_origen_es_typeerror(self, db, proveedor, user_id) -> None:
        with pytest.raises(TypeError):
            crear_imputacion(
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


# ──────────────────────────────────────────────────────────────────────────
# Persistencia de ambas patas
# ──────────────────────────────────────────────────────────────────────────


class TestAmbasPatasSePersisten:
    def test_same_moneda_persiste_las_dos_patas(self, db, proveedor, user_id) -> None:
        imp = _crear(db, proveedor, user_id)

        assert imp.monto_origen == Decimal("1500.00")
        assert imp.moneda_origen == "ARS"
        assert imp.monto_imputado == Decimal("1500.00")
        assert imp.moneda_imputada == "ARS"

    def test_cross_moneda_persiste_dos_importes_distintos(self, db, proveedor, user_id) -> None:
        """OP de 1.500.000 ARS paga un pedido de 1.000 USD a TC 1500.
        La fila tiene que recordar LOS DOS números, no uno solo."""
        imp = _crear(
            db,
            proveedor,
            user_id,
            monto_origen=Decimal("1500000.00"),
            moneda_origen="ARS",
            monto_imputado=Decimal("1000.00"),
            moneda_imputada="USD",
            tipo_cambio=Decimal("1500"),
        )

        assert imp.monto_origen == Decimal("1500000.00")
        assert imp.moneda_origen == "ARS"
        assert imp.monto_imputado == Decimal("1000.00")
        assert imp.moneda_imputada == "USD"

    def test_la_pata_origen_sobrevive_al_roundtrip_de_db(self, db, proveedor, user_id) -> None:
        imp = _crear(
            db,
            proveedor,
            user_id,
            monto_origen=Decimal("1500000.00"),
            moneda_origen="ARS",
            monto_imputado=Decimal("1000.00"),
            moneda_imputada="USD",
            tipo_cambio=Decimal("1500"),
        )
        imp_id = imp.id
        db.expire_all()

        recargada = db.get(Imputacion, imp_id)
        assert recargada.monto_origen == Decimal("1500000.00")
        assert recargada.moneda_origen == "ARS"


# ──────────────────────────────────────────────────────────────────────────
# Validaciones
# ──────────────────────────────────────────────────────────────────────────


class TestValidacionesPataOrigen:
    @pytest.mark.parametrize("monto_invalido", [Decimal("0"), Decimal("-10.00")])
    def test_monto_origen_no_positivo_raise_400(self, db, proveedor, user_id, monto_invalido) -> None:
        with pytest.raises(HTTPException) as exc:
            _crear(db, proveedor, user_id, monto_origen=monto_invalido)
        assert exc.value.status_code == 400
        assert "monto_origen" in exc.value.detail

    def test_cross_moneda_sin_tipo_cambio_raise_400(self, db, proveedor, user_id) -> None:
        """Sin TC no hay forma de auditar la relación entre las dos patas."""
        with pytest.raises(HTTPException) as exc:
            _crear(
                db,
                proveedor,
                user_id,
                monto_origen=Decimal("1500000.00"),
                moneda_origen="ARS",
                monto_imputado=Decimal("1000.00"),
                moneda_imputada="USD",
                tipo_cambio=None,
            )
        assert exc.value.status_code == 400
        assert "tipo_cambio" in exc.value.detail

    @pytest.mark.parametrize("tc_invalido", [Decimal("0"), Decimal("-1500")])
    def test_cross_moneda_con_tipo_cambio_no_positivo_raise_400(self, db, proveedor, user_id, tc_invalido) -> None:
        with pytest.raises(HTTPException) as exc:
            _crear(
                db,
                proveedor,
                user_id,
                monto_origen=Decimal("1500000.00"),
                moneda_origen="ARS",
                monto_imputado=Decimal("1000.00"),
                moneda_imputada="USD",
                tipo_cambio=tc_invalido,
            )
        assert exc.value.status_code == 400
        assert "tipo_cambio" in exc.value.detail

    def test_same_moneda_con_montos_distintos_raise_400(self, db, proveedor, user_id) -> None:
        """Invariante: si origen y destino comparten moneda, los importes son
        el MISMO número. Si difieren, alguien se equivocó de pata."""
        with pytest.raises(HTTPException) as exc:
            _crear(
                db,
                proveedor,
                user_id,
                monto_origen=Decimal("1400.00"),
                moneda_origen="ARS",
                monto_imputado=Decimal("1500.00"),
                moneda_imputada="ARS",
            )
        assert exc.value.status_code == 400
        assert "monto_origen" in exc.value.detail

    def test_same_moneda_con_montos_iguales_pasa(self, db, proveedor, user_id) -> None:
        imp = _crear(db, proveedor, user_id, monto_origen=Decimal("1500.00"))
        assert imp.id is not None

    def test_same_moneda_no_exige_tipo_cambio(self, db, proveedor, user_id) -> None:
        imp = _crear(db, proveedor, user_id, tipo_cambio=None)
        assert imp.id is not None


# ──────────────────────────────────────────────────────────────────────────
# Reversals — el lugar más fácil de romper
# ──────────────────────────────────────────────────────────────────────────


class TestReversalsPataOrigen:
    """Un reversal tiene que devolver el importe ORIGEN al origen y el
    importe DESTINO al destino. Copiar una sola pata rompe una de las dos."""

    def test_desimputar_copia_la_pata_origen_same_moneda(self, db, proveedor, user_id) -> None:
        original = _crear(db, proveedor, user_id)

        reversal = imputaciones_service.desimputar(db, imputacion_id=original.id, user_id=user_id)

        assert reversal.es_reversal is True
        assert reversal.monto_origen == original.monto_origen
        assert reversal.moneda_origen == original.moneda_origen

    def test_desimputar_copia_la_pata_origen_cross_moneda(self, db, proveedor, user_id) -> None:
        original = _crear(
            db,
            proveedor,
            user_id,
            monto_origen=Decimal("1500000.00"),
            moneda_origen="ARS",
            monto_imputado=Decimal("1000.00"),
            moneda_imputada="USD",
            tipo_cambio=Decimal("1500"),
        )

        reversal = imputaciones_service.desimputar(db, imputacion_id=original.id, user_id=user_id)

        # Pata origen: devuelve los ARS al origen.
        assert reversal.monto_origen == Decimal("1500000.00")
        assert reversal.moneda_origen == "ARS"
        # Pata destino: devuelve los USD al pedido.
        assert reversal.monto_imputado == Decimal("1000.00")
        assert reversal.moneda_imputada == "USD"

    def test_reimputar_propaga_la_pata_origen_a_las_dos_filas(self, db, proveedor, user_id) -> None:
        original = _crear(
            db,
            proveedor,
            user_id,
            monto_origen=Decimal("1500000.00"),
            moneda_origen="ARS",
            monto_imputado=Decimal("1000.00"),
            moneda_imputada="USD",
            tipo_cambio=Decimal("1500"),
        )

        reversal, nueva = imputaciones_service.reimputar(
            db,
            imputacion_id=original.id,
            nuevo_destino_tipo="saldo",
            nuevo_destino_id=None,
            user_id=user_id,
        )

        for fila in (reversal, nueva):
            assert fila.monto_origen == Decimal("1500000.00")
            assert fila.moneda_origen == "ARS"

    def test_reversal_de_fila_legacy_sin_pata_origen_cae_a_la_pata_destino(self, db, proveedor, user_id) -> None:
        """Filas escritas por una instancia pre-compras_038 durante un deploy
        rolling quedan con la pata origen en NULL. El reversal no puede
        explotar: cae a la pata destino (que para esas filas es lo mejor
        disponible)."""
        legacy = Imputacion(
            origen_tipo="orden_pago",
            origen_id=100,
            destino_tipo="pedido_compra",
            destino_id=200,
            monto_imputado=Decimal("1500.00"),
            moneda_imputada="ARS",
            monto_origen=None,
            moneda_origen=None,
            proveedor_id=proveedor.id,
            creado_por_id=user_id,
        )
        db.add(legacy)
        db.flush()

        reversal = imputaciones_service.desimputar(db, imputacion_id=legacy.id, user_id=user_id)

        assert reversal.monto_origen == Decimal("1500.00")
        assert reversal.moneda_origen == "ARS"
