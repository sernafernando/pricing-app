"""
Tests de `etiqueta_retiro_service` (COMPRAS-4.2).

Cubre:
  - Generación de etiqueta para pedido con `requiere_envio=True`.
  - Error si `requiere_envio=False` (400).
  - Error si ya existe etiqueta para el pedido (409 — D16).
  - Error si la dirección pertenece a otro proveedor (400).
  - Auto-selección de dirección cuando `proveedor_direccion_id=None`.
  - Evento `etiqueta_envio_generada` insertado.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.models.compra_evento import CompraEvento
from app.models.empresa import Empresa
from app.models.etiqueta_envio import EtiquetaEnvio
from app.models.pedido_compra import PedidoCompra
from app.models.proveedor import OrigenProveedor, Proveedor
from app.models.proveedor_direccion import ProveedorDireccion
from app.services.etiqueta_retiro_service import generar_etiqueta_retiro


@pytest.fixture
def empresa(db) -> Empresa:
    emp = Empresa(id=1, nombre="Empresa 1", activo=True, orden=0)
    db.add(emp)
    db.flush()
    return emp


@pytest.fixture
def proveedor(db) -> Proveedor:
    prov = Proveedor(id=1, nombre="Proveedor Retiro", activo=True, origen=OrigenProveedor.ERP.value)
    db.add(prov)
    db.flush()
    return prov


@pytest.fixture
def otro_proveedor(db) -> Proveedor:
    prov = Proveedor(id=2, nombre="Otro Proveedor", activo=True, origen=OrigenProveedor.ERP.value)
    db.add(prov)
    db.flush()
    return prov


@pytest.fixture
def direccion_retiro(db, proveedor) -> ProveedorDireccion:
    d = ProveedorDireccion(
        proveedor_id=proveedor.id,
        etiqueta="Depósito Retiro",
        direccion="Av. Siempreviva 742",
        cp="1407",
        ciudad="CABA",
        provincia="Buenos Aires",
        contacto_nombre="Juan Retiro",
        contacto_telefono="011-4567-8910",
        activo=True,
    )
    db.add(d)
    db.flush()
    return d


@pytest.fixture
def direccion_otra(db, otro_proveedor) -> ProveedorDireccion:
    d = ProveedorDireccion(
        proveedor_id=otro_proveedor.id,
        etiqueta="Retiro",
        direccion="Otra 123",
        activo=True,
    )
    db.add(d)
    db.flush()
    return d


def _crear_pedido(db, empresa, proveedor, user, requiere_envio: bool = True) -> PedidoCompra:
    p = PedidoCompra(
        numero="P-01-2026-00001",
        empresa_id=empresa.id,
        proveedor_id=proveedor.id,
        moneda="ARS",
        monto=Decimal("1000.00"),
        requiere_envio=requiere_envio,
        estado="aprobado",
        creado_por_id=user.id,
    )
    db.add(p)
    db.flush()
    return p


class TestGenerarEtiquetaRetiro:
    def test_happy_path_sin_direccion_explicita(self, db, empresa, proveedor, direccion_retiro, active_user) -> None:
        pedido = _crear_pedido(db, empresa, proveedor, active_user)

        etiqueta = generar_etiqueta_retiro(
            db,
            pedido_id=pedido.id,
            user_id=active_user.id,
        )

        assert etiqueta.id is not None
        assert etiqueta.tipo_envio == "retiro_proveedor"
        assert etiqueta.proveedor_id == proveedor.id
        assert etiqueta.proveedor_direccion_id == direccion_retiro.id
        assert etiqueta.pedido_compra_id == pedido.id
        assert etiqueta.es_manual is True
        assert etiqueta.shipping_id.startswith(f"RETIRO-{pedido.numero}-")
        # Datos copiados
        assert etiqueta.manual_street_name == "Av. Siempreviva 742"
        assert etiqueta.manual_zip_code == "1407"
        assert etiqueta.manual_city_name == "CABA"
        assert etiqueta.manual_phone == "011-4567-8910"

    def test_happy_path_con_direccion_explicita(self, db, empresa, proveedor, direccion_retiro, active_user) -> None:
        pedido = _crear_pedido(db, empresa, proveedor, active_user)

        etiqueta = generar_etiqueta_retiro(
            db,
            pedido_id=pedido.id,
            proveedor_direccion_id=direccion_retiro.id,
            user_id=active_user.id,
        )

        assert etiqueta.proveedor_direccion_id == direccion_retiro.id

    def test_registra_evento_etiqueta_envio_generada(
        self, db, empresa, proveedor, direccion_retiro, active_user
    ) -> None:
        pedido = _crear_pedido(db, empresa, proveedor, active_user)

        generar_etiqueta_retiro(db, pedido_id=pedido.id, user_id=active_user.id)

        eventos = (
            db.query(CompraEvento)
            .filter(
                CompraEvento.entidad_tipo == CompraEvento.ENTIDAD_TIPO_PEDIDO,
                CompraEvento.entidad_id == pedido.id,
                CompraEvento.tipo == "etiqueta_envio_generada",
            )
            .all()
        )
        assert len(eventos) == 1
        assert "etiqueta_id" in eventos[0].payload
        assert "shipping_id" in eventos[0].payload

    def test_pedido_sin_requiere_envio_raise_400(self, db, empresa, proveedor, direccion_retiro, active_user) -> None:
        pedido = _crear_pedido(db, empresa, proveedor, active_user, requiere_envio=False)

        with pytest.raises(HTTPException) as exc:
            generar_etiqueta_retiro(db, pedido_id=pedido.id, user_id=active_user.id)
        assert exc.value.status_code == 400
        assert "requiere_envio" in exc.value.detail.lower() or "no requiere" in exc.value.detail.lower()

    def test_etiqueta_ya_existente_raise_409(self, db, empresa, proveedor, direccion_retiro, active_user) -> None:
        pedido = _crear_pedido(db, empresa, proveedor, active_user)

        # Primera llamada: OK
        generar_etiqueta_retiro(db, pedido_id=pedido.id, user_id=active_user.id)

        # Segunda llamada: 409
        with pytest.raises(HTTPException) as exc:
            generar_etiqueta_retiro(db, pedido_id=pedido.id, user_id=active_user.id)
        assert exc.value.status_code == 409
        assert "ya existe" in exc.value.detail.lower()

    def test_direccion_de_otro_proveedor_raise_400(
        self, db, empresa, proveedor, direccion_retiro, direccion_otra, active_user
    ) -> None:
        pedido = _crear_pedido(db, empresa, proveedor, active_user)

        with pytest.raises(HTTPException) as exc:
            generar_etiqueta_retiro(
                db,
                pedido_id=pedido.id,
                proveedor_direccion_id=direccion_otra.id,
                user_id=active_user.id,
            )
        assert exc.value.status_code == 400
        assert "no pertenece" in exc.value.detail.lower()

    def test_sin_direcciones_configuradas_raise_400(self, db, empresa, proveedor, active_user) -> None:
        pedido = _crear_pedido(db, empresa, proveedor, active_user)

        with pytest.raises(HTTPException) as exc:
            generar_etiqueta_retiro(db, pedido_id=pedido.id, user_id=active_user.id)
        assert exc.value.status_code == 400
        assert "no tiene direcciones" in exc.value.detail.lower()

    def test_pedido_inexistente_raise_404(self, db, active_user) -> None:
        with pytest.raises(HTTPException) as exc:
            generar_etiqueta_retiro(db, pedido_id=9999, user_id=active_user.id)
        assert exc.value.status_code == 404

    def test_fecha_envio_es_hoy(self, db, empresa, proveedor, direccion_retiro, active_user) -> None:
        from datetime import date

        pedido = _crear_pedido(db, empresa, proveedor, active_user)
        et = generar_etiqueta_retiro(db, pedido_id=pedido.id, user_id=active_user.id)
        assert et.fecha_envio == date.today()

    def test_verifica_etiqueta_persistida_en_db(self, db, empresa, proveedor, direccion_retiro, active_user) -> None:
        pedido = _crear_pedido(db, empresa, proveedor, active_user)
        et = generar_etiqueta_retiro(db, pedido_id=pedido.id, user_id=active_user.id)

        leida = db.query(EtiquetaEnvio).filter(EtiquetaEnvio.id == et.id).one()
        assert leida.pedido_compra_id == pedido.id
        assert leida.tipo_envio == "retiro_proveedor"
