"""
Tests de `ProveedoresService.sync_desde_erp()` — cadena canónica
GBP → tb_supplier → proveedores → rma_proveedores.

Cubre el contrato fail-loud (`ErpSyncError` en vez de contadores en cero) y
las tres regresiones que introdujo el fix del cron + botón:

  - Una fila sin `supp_name` abortaba la transacción completa (las tres
    tablas destino tienen la columna NOT NULL) y dejaba el sync en cero.
  - `comp_id`/`supp_id` en string desde el ERP no matcheaban contra la clave
    tipada del ORM, así que se insertaba un proveedor duplicado.
  - La persistencia bloqueante corría dentro del event loop.

No hay pytest-asyncio en este proyecto (ver
`tests/services/test_fetch_gbp_report_78.py`): las corrutinas se manejan con
`asyncio.run(...)`. El ERP (gbp-parser) SIEMPRE va mockeado: solo existe en
producción.
"""

import asyncio
import threading
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.models.proveedor import OrigenProveedor, Proveedor
from app.models.rma_proveedor import RmaProveedor
from app.models.tb_supplier import TBSupplier
from app.services.erp_worker_client import erp_worker_client
from app.services.proveedores_service import (
    SUPPLIER_VALID_FIELDS,
    ErpSyncError,
    ProveedoresService,
    normalize_supplier_row,
)


def _sync(db, filas):
    """Corre `sync_desde_erp()` con el ERP mockeado devolviendo `filas`."""
    with patch.object(erp_worker_client, "get_suppliers", new=AsyncMock(return_value=filas)):
        return asyncio.run(ProveedoresService(db).sync_desde_erp())


def _fila(supp_id: int, nombre: str = "Proveedor ERP", **extra):
    """Fila del ERP con la forma que devuelve el gbp-parser."""
    return {"comp_id": 1, "supp_id": supp_id, "supp_name": nombre, **extra}


def _crear_proveedor(db, *, supp_id: int, comp_id: int = 1, nombre: str = "Existente", cuit=None) -> Proveedor:
    prov = Proveedor(
        supp_id=supp_id,
        comp_id=comp_id,
        nombre=nombre,
        cuit=cuit,
        origen=OrigenProveedor.ERP,
    )
    db.add(prov)
    db.flush()
    return prov


# =============================================================================
# Contrato fail-loud: el ERP no devolvió datos utilizables
# =============================================================================


class TestFailLoud:
    def test_erp_vacio_levanta_erp_sync_error(self, db) -> None:
        """Caso 1: respuesta vacía. Es el bug original: devolvía ceros como éxito."""
        with pytest.raises(ErpSyncError, match="no devolvió proveedores"):
            _sync(db, [])

        assert db.query(Proveedor).count() == 0

    def test_respuesta_de_error_del_erp_levanta_erp_sync_error(self, db) -> None:
        """Caso 2: el gbp-parser responde HTTP 200 con [{"Column1": "-9"}]."""
        with pytest.raises(ErpSyncError, match="respuesta de error"):
            _sync(db, [{"Column1": "-9"}])

        assert db.query(Proveedor).count() == 0

    def test_fallo_de_transporte_levanta_erp_sync_error(self, db) -> None:
        """Caso 3: el gbp-parser no es alcanzable (httpx.HTTPError)."""
        with patch.object(
            erp_worker_client,
            "get_suppliers",
            new=AsyncMock(side_effect=httpx.ConnectError("connection refused")),
        ):
            with pytest.raises(ErpSyncError, match="No se pudo consultar el ERP"):
                asyncio.run(ProveedoresService(db).sync_desde_erp())

        assert db.query(Proveedor).count() == 0

    def test_todas_las_filas_descartadas_levanta_erp_sync_error(self, db) -> None:
        """Si ninguna fila sobrevive la normalización tampoco se retorna éxito."""
        with pytest.raises(ErpSyncError, match="ninguna tiene comp_id/supp_id/supp_name"):
            _sync(db, [{"comp_id": 1, "supp_id": 10}, {"comp_id": 1, "supp_name": "Sin ID"}])

        assert db.query(Proveedor).count() == 0


# =============================================================================
# Invariante del executemany: todas las filas con las MISMAS claves
# =============================================================================


class TestClavesHomogeneas:
    def test_filas_heterogeneas_normalizan_al_mismo_set_de_claves(self, db) -> None:
        """
        Caso 4: el ERP omite `supp_taxNumber` en algunas filas. `execute(stmt, lista)`
        compila el executemany con el primer dict, así que los dicts heterogéneos
        revientan el insert completo.
        """
        con_cuit = normalize_supplier_row(_fila(11, "Con CUIT", supp_taxNumber="30-11111111-1"))
        sin_cuit = normalize_supplier_row(_fila(12, "Sin CUIT"))

        assert set(con_cuit) == set(sin_cuit) == set(SUPPLIER_VALID_FIELDS)
        assert sin_cuit["supp_tax_number"] is None

    def test_sync_con_filas_heterogeneas_completa(self, db) -> None:
        """La cadena entera corre con filas de claves distintas."""
        result = _sync(
            db,
            [
                _fila(11, "Con CUIT", supp_taxNumber="30-11111111-1"),
                _fila(12, "Sin CUIT"),
            ],
        )

        assert result["insertados"] == 2
        assert db.query(TBSupplier).count() == 2
        assert db.query(Proveedor).count() == 2
        assert db.query(Proveedor).filter(Proveedor.supp_id == 11).one().cuit == "30-11111111-1"
        assert db.query(Proveedor).filter(Proveedor.supp_id == 12).one().cuit is None


# =============================================================================
# DEFECTO 1 — supp_name faltante/vacío no debe abortar la transacción
# =============================================================================


class TestSuppNameInvalido:
    @pytest.mark.parametrize(
        "fila_invalida",
        [
            pytest.param({"comp_id": 1, "supp_id": 99}, id="clave-ausente"),
            pytest.param({"comp_id": 1, "supp_id": 99, "supp_name": None}, id="none"),
            pytest.param({"comp_id": 1, "supp_id": 99, "supp_name": ""}, id="vacio"),
            pytest.param({"comp_id": 1, "supp_id": 99, "supp_name": "   \t "}, id="solo-espacios"),
        ],
    )
    def test_fila_sin_nombre_se_descarta_y_el_resto_sincroniza(self, db, fila_invalida) -> None:
        """
        Caso 5: `tb_supplier.supp_name`, `proveedores.nombre` y
        `rma_proveedores.nombre` son NOT NULL. Sin este guard, la fila mala
        levanta IntegrityError dentro de la única transacción → rollback de
        TODO → cero proveedores sincronizados.
        """
        result = _sync(db, [_fila(11, "Válido"), fila_invalida])

        assert result["insertados"] == 1
        assert result["total_erp"] == 2
        assert [p.supp_id for p in db.query(Proveedor).all()] == [11]
        assert db.query(Proveedor).filter(Proveedor.supp_id == 99).count() == 0

    def test_normalize_descarta_nombre_invalido(self) -> None:
        assert normalize_supplier_row({"comp_id": 1, "supp_id": 5}) is None
        assert normalize_supplier_row({"comp_id": 1, "supp_id": 5, "supp_name": None}) is None
        assert normalize_supplier_row({"comp_id": 1, "supp_id": 5, "supp_name": "  "}) is None
        assert normalize_supplier_row({"comp_id": 1, "supp_id": 5, "supp_name": "OK"}) is not None


# =============================================================================
# Clave ERP: comp_id = 0 es válido, los strings se castean a int
# =============================================================================


class TestClaveErp:
    def test_comp_id_cero_se_preserva(self, db) -> None:
        """
        Caso 6: el guard es explícito contra None, no por falsy. comp_id = 0
        es una clave válida.
        """
        assert normalize_supplier_row(_fila(11, "Empresa cero") | {"comp_id": 0})["comp_id"] == 0

        result = _sync(db, [_fila(11, "Empresa cero") | {"comp_id": 0}])

        assert result["insertados"] == 1
        assert db.query(Proveedor).one().comp_id == 0

    def test_clave_no_casteable_se_descarta(self, db) -> None:
        """Una clave que no es un entero no puede matchear nada: se descarta."""
        assert normalize_supplier_row(_fila(11) | {"supp_id": "no-es-un-int"}) is None
        assert normalize_supplier_row(_fila(11) | {"comp_id": []}) is None

    def test_clave_en_string_actualiza_el_existente_sin_duplicar(self, db) -> None:
        """
        Caso 7 (DEFECTO 2): si el ERP manda "11" en vez de 11, la clave del
        payload (str) no matchea la del ORM (int), se toma la rama `else` y se
        inserta un Proveedor DUPLICADO más su RmaProveedor.
        """
        _crear_proveedor(db, supp_id=11, nombre="Nombre viejo")
        db.commit()

        result = _sync(db, [{"comp_id": "1", "supp_id": "11", "supp_name": "Nombre nuevo"}])

        assert result["insertados"] == 0
        assert result["actualizados"] == 1
        assert db.query(Proveedor).filter(Proveedor.supp_id == 11).count() == 1
        assert db.query(Proveedor).filter(Proveedor.supp_id == 11).one().nombre == "Nombre nuevo"
        assert db.query(RmaProveedor).filter(RmaProveedor.supp_id == 11).count() == 1


# =============================================================================
# Contadores
# =============================================================================


class TestContadores:
    def test_existente_sin_cambios_no_cuenta_como_actualizado(self, db) -> None:
        """Caso 8a: mismo nombre y mismo CUIT → actualizados == 0."""
        _crear_proveedor(db, supp_id=11, nombre="Acme SA", cuit="30-11111111-1")
        db.commit()

        result = _sync(db, [_fila(11, "Acme SA", supp_taxNumber="30-11111111-1")])

        assert result["actualizados"] == 0
        assert result["insertados"] == 0

    def test_proveedor_nuevo_cuenta_como_insertado(self, db) -> None:
        """Caso 8b: un supp_id que no está en el mirror local es alta."""
        _crear_proveedor(db, supp_id=11, nombre="Acme SA")
        db.commit()

        result = _sync(db, [_fila(77, "Proveedor Nuevo")])

        assert result["insertados"] == 1
        assert result["actualizados"] == 0
        assert db.query(Proveedor).filter(Proveedor.supp_id == 77).count() == 1

    def test_total_erp_refleja_lo_que_devolvio_el_erp(self, db) -> None:
        """
        Caso 9: `total_erp` es la cantidad de filas del ERP — incluye las
        descartadas y NO depende del tamaño del mirror local.
        """
        for supp_id in (11, 12, 13, 14, 15):
            _crear_proveedor(db, supp_id=supp_id, nombre=f"Local {supp_id}")
        db.commit()

        result = _sync(
            db,
            [
                _fila(11, "Local 11"),
                _fila(12, "Local 12 renombrado"),
                {"comp_id": 1, "supp_id": 13},  # descartada: sin supp_name
            ],
        )

        assert result["total_erp"] == 3
        assert db.query(Proveedor).count() == 5


# =============================================================================
# DEFECTO 3 — la persistencia bloqueante no debe correr en el event loop
# =============================================================================


class TestPersistenciaFueraDelEventLoop:
    def test_persistir_sync_corre_en_un_worker_thread(self, db) -> None:
        """
        `get_async_db` entrega una Session SINCRÓNICA (ver
        `app/core/database.py`): el upsert masivo, los dos `query(...).all()`,
        los `flush()` por proveedor nuevo y el commit bloquean. Si corren en la
        corrutina, congelan la API entera para todos los usuarios mientras dura
        el sync.
        """
        hilos: dict[str, int] = {}
        original = ProveedoresService._persistir_sync

        def espia(self, normalized, total_erp):
            hilos["persistencia"] = threading.get_ident()
            return original(self, normalized, total_erp)

        async def correr():
            hilos["event_loop"] = threading.get_ident()
            with (
                patch.object(ProveedoresService, "_persistir_sync", espia),
                patch.object(erp_worker_client, "get_suppliers", new=AsyncMock(return_value=[_fila(11)])),
            ):
                return await ProveedoresService(db).sync_desde_erp()

        result = asyncio.run(correr())

        assert result["insertados"] == 1
        assert hilos["persistencia"] != hilos["event_loop"]
