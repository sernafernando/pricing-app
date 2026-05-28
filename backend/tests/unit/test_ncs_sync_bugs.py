"""
Regression tests para bugs del sync de NCs del ERP (fix/compras-ncs-sync-erp).

Bug 1 — NCs duplicadas:
  - match_ncs_backward llamado dos veces con el mismo ct_transaction NO vincula
    la misma NC local dos veces.
  - El modelo rechaza dos NC locales con el mismo (proveedor_id, numero_nc_proveedor)
    cuando numero_nc_proveedor IS NOT NULL (Unique constraint parcial).

Bug 2 — NCs canceladas siguen disponibles:
  - Cuando el ERP cancela una NC (ct_iscancelled=TRUE), el próximo sync
    transiciona la NC local vinculada al estado 'cancelado'.
  - La NC local cancelada NO aparece en /ncs-locales/disponibles.

Adversarial review fixes:
  C1 — state-machine action mismatch: acción correcta por estado origen.
  C2 — NC cancelled BEFORE first sync: propagación via (proveedor, numero_nc_proveedor).
  C3 — dedup migration: pre-flight guard cuando hay múltiples duplicados con imputaciones.
  W1 — narrow except: HTTPException se maneja explícitamente, re-raise para inesperados.
  W5 — migration dedup tests.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest
import sqlalchemy as sa
from app.models.commercial_transaction import CommercialTransaction
from app.models.empresa import Empresa
from app.models.imputacion import Imputacion
from app.models.nota_credito_local import NotaCreditoLocal
from app.models.proveedor import OrigenProveedor, Proveedor
from app.models.tb_sale_document import SaleDocument
from app.services import ncs_locales_service
from app.services.erp_matching_service import match_ncs_backward


# ──────────────────────────────────────────────────────────────────────────
# Fixtures compartidas
# ──────────────────────────────────────────────────────────────────────────


@pytest.fixture
def empresa(db) -> Empresa:
    e = Empresa(nombre="EmpresaNCSyncTest", activo=True, orden=99)
    db.add(e)
    db.flush()
    return e


@pytest.fixture
def proveedor(db) -> Proveedor:
    p = Proveedor(
        nombre="ProveedorNCSyncTest",
        activo=True,
        origen=OrigenProveedor.ERP.value,
        supp_id=777,
    )
    db.add(p)
    db.flush()
    return p


@pytest.fixture
def sd_nc(db) -> SaleDocument:
    """SaleDocument que clasifica como NC de compra."""
    sd = SaleDocument(
        sd_id=9901,
        sd_desc="NC de compra test",
        sd_ispurchase=True,
        sd_iscreditnote=True,
        sd_plusorminus=-1,
        hacc_group=10001,
    )
    db.add(sd)
    db.flush()
    return sd


def _ct_nc(
    db,
    *,
    ct_transaction: int,
    supp_id: int,
    ct_docnumber: str,
    sd_id: int,
    ct_iscancelled: bool = False,
    ct_total: Decimal = Decimal("1000.00"),
) -> CommercialTransaction:
    """Crea una CommercialTransaction que representa una NC del ERP."""
    ct = CommercialTransaction(
        ct_transaction=ct_transaction,
        comp_id=1,
        bra_id=1,
        supp_id=supp_id,
        ct_docNumber=ct_docnumber,
        sd_id=sd_id,
        ct_total=float(ct_total),
        ct_date=datetime(2026, 4, 1, 10, 0, 0),
        ct_isCancelled=ct_iscancelled,
    )
    db.add(ct)
    db.flush()
    return ct


def _nc_local_aprobada(
    db,
    *,
    empresa_id: int,
    proveedor_id: int,
    numero_nc_proveedor: str | None,
    creado_por_id: int,
    monto: Decimal = Decimal("1000.00"),
) -> NotaCreditoLocal:
    """Crea una NC local en estado 'aprobado' con numero_nc_proveedor dado."""
    nc = ncs_locales_service.crear(
        db,
        empresa_id=empresa_id,
        proveedor_id=proveedor_id,
        moneda="ARS",
        monto=monto,
        fecha_emision=date.today(),
        motivo="NC test sync",
        creado_por_id=creado_por_id,
        numero_nc_proveedor=numero_nc_proveedor,
    )
    ncs_locales_service.transicionar(db, nc_id=nc.id, accion="enviar_aprobacion", user_id=creado_por_id)
    ncs_locales_service.transicionar(db, nc_id=nc.id, accion="aprobar", user_id=creado_por_id)
    db.flush()
    return nc


# ──────────────────────────────────────────────────────────────────────────
# Bug 1 — Dedup: llamar sync dos veces no duplica el vínculo
# ──────────────────────────────────────────────────────────────────────────


class TestNcSyncDedup:
    def test_match_ncs_backward_dos_veces_no_duplica(self, db, empresa, proveedor, sd_nc, active_user) -> None:
        """
        match_ncs_backward llamado dos veces con el mismo ct_transaction
        no crea un segundo vínculo ni afecta la NC local ya vinculada.

        Simula lo que pasa cuando el sync corre en días consecutivos y el
        mismo ct aparece en ambas ventanas de sync (como UPDATE).
        """
        nc = _nc_local_aprobada(
            db,
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            numero_nc_proveedor="NC-A-0001-00000099",
            creado_por_id=active_user.id,
        )
        assert nc.ct_transaction_id is None

        _ct_nc(
            db,
            ct_transaction=88001,
            supp_id=proveedor.supp_id,
            ct_docnumber="NC-A-0001-00000099",
            sd_id=sd_nc.sd_id,
        )

        # Primera llamada: vincula la NC local.
        resumen1 = match_ncs_backward(db, cts_synced=[88001])
        db.flush()
        db.refresh(nc)
        assert nc.ct_transaction_id == 88001
        assert resumen1["ncs_asociadas"] == 1

        # Segunda llamada: misma ct, no debe cambiar nada.
        resumen2 = match_ncs_backward(db, cts_synced=[88001])
        db.flush()
        db.refresh(nc)
        assert nc.ct_transaction_id == 88001  # sin cambio
        assert resumen2["ncs_asociadas"] == 0  # no re-asocia
        assert resumen2["errores"] == 0

    def test_unique_constraint_previene_ncs_con_mismo_numero_proveedor(
        self, db, empresa, proveedor, active_user
    ) -> None:
        """
        Regression bug 1: el modelo ahora tiene un índice UNIQUE parcial sobre
        (proveedor_id, numero_nc_proveedor) WHERE numero_nc_proveedor IS NOT NULL.

        Intentar insertar dos NC locales con el mismo (proveedor_id,
        numero_nc_proveedor) debe fallar con IntegrityError, previniendo
        el escenario de duplicados que causaba el bug.
        """
        import sqlalchemy.exc

        ncs_locales_service.crear(
            db,
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="ARS",
            monto=Decimal("1000"),
            fecha_emision=date.today(),
            motivo="NC original",
            creado_por_id=active_user.id,
            numero_nc_proveedor="NC-UNIQUE-TEST",
        )
        db.flush()

        with pytest.raises(sqlalchemy.exc.IntegrityError):
            ncs_locales_service.crear(
                db,
                empresa_id=empresa.id,
                proveedor_id=proveedor.id,
                moneda="ARS",
                monto=Decimal("2000"),
                fecha_emision=date.today(),
                motivo="NC duplicada — debe fallar",
                creado_por_id=active_user.id,
                numero_nc_proveedor="NC-UNIQUE-TEST",
            )
            db.flush()

    def test_ncs_sin_numero_proveedor_no_limita_creacion(self, db, empresa, proveedor, active_user) -> None:
        """
        El UNIQUE es parcial (WHERE IS NOT NULL): NCs sin numero_nc_proveedor
        pueden crearse múltiples sin violar la constraint.
        """
        nc1 = ncs_locales_service.crear(
            db,
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="ARS",
            monto=Decimal("100"),
            fecha_emision=date.today(),
            motivo="NC sin numero prov 1",
            creado_por_id=active_user.id,
            numero_nc_proveedor=None,
        )
        nc2 = ncs_locales_service.crear(
            db,
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="ARS",
            monto=Decimal("200"),
            fecha_emision=date.today(),
            motivo="NC sin numero prov 2",
            creado_por_id=active_user.id,
            numero_nc_proveedor=None,
        )
        db.flush()
        assert nc1.id != nc2.id


# ──────────────────────────────────────────────────────────────────────────
# Bug 2 — NCs canceladas en ERP deben reflejarse en NC local
# ──────────────────────────────────────────────────────────────────────────


class TestNcCancelacionErp:
    def test_nc_erp_cancelada_cancela_nc_local_aprobada(self, db, empresa, proveedor, sd_nc, active_user) -> None:
        """
        Cuando el ERP cancela una NC (ct_iscancelled=TRUE), el sync actualiza
        la NC local vinculada al estado 'cancelado'.
        """
        nc = _nc_local_aprobada(
            db,
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            numero_nc_proveedor="NC-A-CANCEL-01",
            creado_por_id=active_user.id,
        )

        # Simular que la NC ya estaba vinculada (como si hubiera corrido un
        # sync previo que la vinculó).
        ct = _ct_nc(
            db,
            ct_transaction=88010,
            supp_id=proveedor.supp_id,
            ct_docnumber="NC-A-CANCEL-01",
            sd_id=sd_nc.sd_id,
            ct_iscancelled=False,
        )
        nc.ct_transaction_id = ct.ct_transaction
        db.flush()

        assert nc.estado == "aprobado"

        # Simular que el ERP cancela la NC: actualizamos ct_iscancelled.
        ct.ct_isCancelled = True
        db.flush()

        # El sync corre y ve esta ct como UPDATE (está en cts_synced).
        resumen = match_ncs_backward(db, cts_synced=[88010])
        db.flush()
        db.refresh(nc)

        assert nc.estado == "cancelado", f"NC local debería estar cancelada, estado actual: {nc.estado}"
        assert resumen.get("ncs_canceladas_por_erp", 0) >= 1
        assert resumen["errores"] == 0

    def test_nc_erp_cancelada_nc_local_borrador_cancela(self, db, empresa, proveedor, sd_nc, active_user) -> None:
        """NC local en borrador vinculada a CT cancelada → se cancela."""
        nc = ncs_locales_service.crear(
            db,
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="ARS",
            monto=Decimal("500"),
            fecha_emision=date.today(),
            motivo="NC borrador sync test",
            creado_por_id=active_user.id,
            numero_nc_proveedor="NC-BORRA-CANCEL",
        )
        ct = _ct_nc(
            db,
            ct_transaction=88011,
            supp_id=proveedor.supp_id,
            ct_docnumber="NC-BORRA-CANCEL",
            sd_id=sd_nc.sd_id,
            ct_iscancelled=True,  # ya cancelada desde el inicio
        )
        nc.ct_transaction_id = ct.ct_transaction
        db.flush()

        assert nc.estado == "borrador"

        resumen = match_ncs_backward(db, cts_synced=[88011])
        db.flush()
        db.refresh(nc)

        assert nc.estado == "cancelado"
        assert resumen.get("ncs_canceladas_por_erp", 0) >= 1

    def test_nc_erp_cancelada_nc_local_ya_cancelada_no_reintenta(
        self, db, empresa, proveedor, sd_nc, active_user
    ) -> None:
        """NC local ya cancelada no genera error si el ERP la cancela de nuevo."""
        nc = ncs_locales_service.crear(
            db,
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="ARS",
            monto=Decimal("200"),
            fecha_emision=date.today(),
            motivo="NC ya cancelada",
            creado_por_id=active_user.id,
            numero_nc_proveedor="NC-YA-CANCELADA",
        )
        # Cancelar manualmente vía servicio.
        ncs_locales_service.transicionar(db, nc_id=nc.id, accion="cancelar", user_id=active_user.id)

        ct = _ct_nc(
            db,
            ct_transaction=88012,
            supp_id=proveedor.supp_id,
            ct_docnumber="NC-YA-CANCELADA",
            sd_id=sd_nc.sd_id,
            ct_iscancelled=True,
        )
        nc.ct_transaction_id = ct.ct_transaction
        db.flush()

        assert nc.estado == "cancelado"

        resumen = match_ncs_backward(db, cts_synced=[88012])
        db.flush()
        db.refresh(nc)

        # Estado no cambia, no hay errores.
        assert nc.estado == "cancelado"
        assert resumen["errores"] == 0

    def test_nc_cancelada_no_aparece_en_disponibles(self, db, empresa, proveedor, sd_nc, active_user) -> None:
        """
        Una NC local en estado 'cancelado' NO debe aparecer en el conjunto
        de NCs disponibles para imputar (estado IN aprobado/aplicada_parcial).
        """
        nc_aprobada = _nc_local_aprobada(
            db,
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            numero_nc_proveedor="NC-VISIBLE",
            creado_por_id=active_user.id,
        )
        nc_cancelada = _nc_local_aprobada(
            db,
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            numero_nc_proveedor="NC-OCULTA",
            creado_por_id=active_user.id,
        )

        # Cancelar la segunda NC.
        ncs_locales_service.transicionar(
            db,
            nc_id=nc_cancelada.id,
            accion="cancelar_aprobado",
            user_id=active_user.id,
            motivo="Cancelación ERP test",
        )
        db.flush()

        # Consultar disponibles directamente en la DB (misma lógica del endpoint).
        disponibles = (
            db.query(NotaCreditoLocal)
            .filter(
                NotaCreditoLocal.proveedor_id == proveedor.id,
                NotaCreditoLocal.estado.in_(("aprobado", "aplicada_parcial")),
            )
            .all()
        )

        ids_disponibles = {nc.id for nc in disponibles}
        assert nc_aprobada.id in ids_disponibles, "NC aprobada debe estar disponible"
        assert nc_cancelada.id not in ids_disponibles, "NC cancelada NO debe estar disponible"

    def test_nc_vigente_erp_no_cancela_nc_local(self, db, empresa, proveedor, sd_nc, active_user) -> None:
        """
        Una NC ERP que NO está cancelada (ct_iscancelled=FALSE) NO debe
        cancelar la NC local vinculada.
        """
        nc = _nc_local_aprobada(
            db,
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            numero_nc_proveedor="NC-VIGENTE",
            creado_por_id=active_user.id,
        )
        ct = _ct_nc(
            db,
            ct_transaction=88020,
            supp_id=proveedor.supp_id,
            ct_docnumber="NC-VIGENTE",
            sd_id=sd_nc.sd_id,
            ct_iscancelled=False,  # NO cancelada
        )
        nc.ct_transaction_id = ct.ct_transaction
        db.flush()

        resumen = match_ncs_backward(db, cts_synced=[88020])
        db.flush()
        db.refresh(nc)

        assert nc.estado == "aprobado", f"NC local vigente NO debe cancelarse, estado: {nc.estado}"
        assert resumen.get("ncs_canceladas_por_erp", 0) == 0


# ──────────────────────────────────────────────────────────────────────────
# C1 — Acción correcta de cancelación por estado origen
# ──────────────────────────────────────────────────────────────────────────


class TestNcCancelacionAccionPorEstado:
    """C1: La acción de cancelación debe corresponder a TRANSICIONES_VALIDAS."""

    def test_pendiente_aprobacion_usa_rechazar_cancelar(self, db, empresa, proveedor, sd_nc, active_user) -> None:
        """
        NC en 'pendiente_aprobacion' vinculada a CT cancelada.
        La acción correcta es 'rechazar_cancelar', NO 'cancelar' (que no existe
        en TRANSICIONES_VALIDAS para ese estado).
        """
        nc = ncs_locales_service.crear(
            db,
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="ARS",
            monto=Decimal("500"),
            fecha_emision=date.today(),
            motivo="NC pendiente aprobacion C1 test",
            creado_por_id=active_user.id,
            numero_nc_proveedor="NC-C1-PENDIENTE",
        )
        ncs_locales_service.transicionar(db, nc_id=nc.id, accion="enviar_aprobacion", user_id=active_user.id)
        ct = _ct_nc(
            db,
            ct_transaction=88030,
            supp_id=proveedor.supp_id,
            ct_docnumber="NC-C1-PENDIENTE",
            sd_id=sd_nc.sd_id,
            ct_iscancelled=True,
        )
        nc.ct_transaction_id = ct.ct_transaction
        db.flush()

        assert nc.estado == "pendiente_aprobacion"

        resumen = match_ncs_backward(db, cts_synced=[88030])
        db.flush()
        db.refresh(nc)

        assert nc.estado == "cancelado", (
            f"NC en pendiente_aprobacion debe cancelarse via rechazar_cancelar, estado={nc.estado}"
        )
        assert resumen.get("ncs_canceladas_por_erp", 0) >= 1
        assert resumen["errores"] == 0

    def test_rechazado_usa_cancelar_definitivo(self, db, empresa, proveedor, sd_nc, active_user) -> None:
        """
        NC en 'rechazado' vinculada a CT cancelada.
        La acción correcta es 'cancelar_definitivo', NO 'cancelar'.
        Además 'rechazado' debe ser tratado como estado activo (no terminal
        a efectos de cancelación ERP).
        """
        nc = ncs_locales_service.crear(
            db,
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="ARS",
            monto=Decimal("400"),
            fecha_emision=date.today(),
            motivo="NC rechazada C1 test",
            creado_por_id=active_user.id,
            numero_nc_proveedor="NC-C1-RECHAZADA",
        )
        ncs_locales_service.transicionar(db, nc_id=nc.id, accion="enviar_aprobacion", user_id=active_user.id)
        ncs_locales_service.transicionar(db, nc_id=nc.id, accion="rechazar_devolver", user_id=active_user.id)
        ct = _ct_nc(
            db,
            ct_transaction=88031,
            supp_id=proveedor.supp_id,
            ct_docnumber="NC-C1-RECHAZADA",
            sd_id=sd_nc.sd_id,
            ct_iscancelled=True,
        )
        nc.ct_transaction_id = ct.ct_transaction
        db.flush()

        assert nc.estado == "rechazado"

        resumen = match_ncs_backward(db, cts_synced=[88031])
        db.flush()
        db.refresh(nc)

        assert nc.estado == "cancelado", f"NC rechazada debe cancelarse via cancelar_definitivo, estado={nc.estado}"
        assert resumen.get("ncs_canceladas_por_erp", 0) >= 1
        assert resumen["errores"] == 0


# ──────────────────────────────────────────────────────────────────────────
# C2 — NC cancelada ANTES del primer sync (nunca vinculada)
# ──────────────────────────────────────────────────────────────────────────


class TestNcCancelacionAntesDelPrimerSync:
    """
    C2: La CT ya era cancelada cuando se sincronizó por primera vez.
    El matcher usa COALESCE(ct_iscancelled, FALSE) = FALSE → nunca vincula la NC.
    La propagación de cancelación debe encontrar la NC por
    (proveedor.supp_id, numero_nc_proveedor) y cancelarla igual.
    """

    def test_nc_nunca_vinculada_ct_cancelada_desde_inicio(self, db, empresa, proveedor, sd_nc, active_user) -> None:
        """
        Regression exacta del C2: NC local aprobada, CT ya cancelada al llegar
        al primer sync. La NC debe quedar cancelada y vinculada al ct.
        """
        nc = _nc_local_aprobada(
            db,
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            numero_nc_proveedor="NC-C2-NUNCA-VINCULADA",
            creado_por_id=active_user.id,
        )
        assert nc.ct_transaction_id is None

        # CT cancelada desde el primer instante — el matcher la ignora en el forward pass.
        _ct_nc(
            db,
            ct_transaction=88040,
            supp_id=proveedor.supp_id,
            ct_docnumber="NC-C2-NUNCA-VINCULADA",
            sd_id=sd_nc.sd_id,
            ct_iscancelled=True,  # ya cancelada
        )

        resumen = match_ncs_backward(db, cts_synced=[88040])
        db.flush()
        db.refresh(nc)

        assert nc.estado == "cancelado", f"NC nunca vinculada debe cancelarse si CT llegó cancelada, estado={nc.estado}"
        # El vínculo debe quedar registrado también (trazabilidad).
        assert nc.ct_transaction_id == 88040
        assert resumen.get("ncs_canceladas_por_erp", 0) >= 1
        assert resumen["errores"] == 0

    def test_nc_en_borrador_nunca_vinculada_ct_cancelada(self, db, empresa, proveedor, sd_nc, active_user) -> None:
        """NC en borrador, CT ya cancelada al primer sync → se cancela via 'cancelar'."""
        nc = ncs_locales_service.crear(
            db,
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            moneda="ARS",
            monto=Decimal("300"),
            fecha_emision=date.today(),
            motivo="NC borrador C2",
            creado_por_id=active_user.id,
            numero_nc_proveedor="NC-C2-BORRADOR",
        )
        assert nc.ct_transaction_id is None
        assert nc.estado == "borrador"

        _ct_nc(
            db,
            ct_transaction=88041,
            supp_id=proveedor.supp_id,
            ct_docnumber="NC-C2-BORRADOR",
            sd_id=sd_nc.sd_id,
            ct_iscancelled=True,
        )

        resumen = match_ncs_backward(db, cts_synced=[88041])
        db.flush()
        db.refresh(nc)

        assert nc.estado == "cancelado"
        assert nc.ct_transaction_id == 88041
        assert resumen["errores"] == 0


# ──────────────────────────────────────────────────────────────────────────
# W5 — Tests de la lógica de dedup de la migración compras_036
# ──────────────────────────────────────────────────────────────────────────


class TestMigracionDedupC3:
    """
    W5: Tests para la lógica de dedup + pre-flight guard de compras_036.

    Se ejercita la query SQL directamente (sin correr la migración en sí)
    para mantener los tests rápidos y sin dependencias del entorno de Alembic.
    """

    def _crear_nc_raw(
        self,
        db,
        *,
        empresa_id: int,
        proveedor_id: int,
        numero_nc_proveedor: str,
        creado_por_id: int,
        monto: Decimal = Decimal("1000"),
    ) -> NotaCreditoLocal:
        nc = ncs_locales_service.crear(
            db,
            empresa_id=empresa_id,
            proveedor_id=proveedor_id,
            moneda="ARS",
            monto=monto,
            fecha_emision=date.today(),
            motivo="NC dedup test",
            creado_por_id=creado_por_id,
            numero_nc_proveedor=numero_nc_proveedor,
        )
        db.flush()
        return nc

    def _agregar_imputacion(self, db, *, nc: NotaCreditoLocal, proveedor_id: int, creado_por_id: int) -> Imputacion:
        imp = Imputacion(
            origen_tipo="nota_credito_local",
            origen_id=nc.id,
            destino_tipo="saldo",
            destino_id=None,
            monto_imputado=Decimal("100"),
            moneda_imputada="ARS",
            proveedor_id=proveedor_id,
            es_reversal=False,
            creado_por_id=creado_por_id,
        )
        db.add(imp)
        db.flush()
        return imp

    def _run_preflight(self, db) -> list:
        """
        Ejecuta la lógica de pre-flight de la migración y devuelve los conflictos.

        Usa una query SQLite-compatible (group_concat en lugar de array_agg).
        En producción (PostgreSQL) la migración usa array_agg — esta query
        verifica la MISMA condición lógica: grupos con COUNT > 1.
        """
        rows = db.execute(
            sa.text(
                """
                SELECT ncl.proveedor_id, ncl.numero_nc_proveedor,
                       COUNT(*) AS cantidad,
                       group_concat(ncl.id) AS ids_afectados
                FROM notas_credito_local ncl
                WHERE ncl.numero_nc_proveedor IS NOT NULL
                  AND EXISTS (
                      SELECT 1 FROM imputaciones i
                      WHERE i.origen_tipo = 'nota_credito_local'
                        AND i.origen_id = ncl.id
                        AND i.es_reversal = FALSE
                  )
                GROUP BY ncl.proveedor_id, ncl.numero_nc_proveedor
                HAVING COUNT(*) > 1
                """
            )
        ).all()
        # Normalizar: devolver list of (proveedor_id, numero_nc_proveedor, ids_list)
        # ids_afectados en SQLite es una string "id1,id2" — convertir a lista de ints.
        result = []
        for row in rows:
            ids_str = row[3]  # group_concat result
            ids = [int(x) for x in ids_str.split(",")]
            result.append((row[0], row[1], ids))
        return result

    def _run_dedup_query(self, db) -> None:
        """
        Ejecuta la lógica de dedup de la migración (borra duplicados según ranking).

        Usa una query SQLite-compatible (LEFT JOIN subquery en lugar de LATERAL).
        La semántica es idéntica a la migración real en PostgreSQL.
        """
        db.execute(
            sa.text(
                """
                DELETE FROM notas_credito_local
                WHERE id IN (
                    SELECT id FROM (
                        SELECT
                            ncl.id,
                            ROW_NUMBER() OVER (
                                PARTITION BY ncl.proveedor_id, ncl.numero_nc_proveedor
                                ORDER BY
                                    CASE WHEN EXISTS (
                                        SELECT 1 FROM imputaciones i
                                        WHERE i.origen_tipo = 'nota_credito_local'
                                          AND i.origen_id = ncl.id
                                          AND i.es_reversal = 0
                                    ) THEN 0 ELSE 1 END,
                                    ncl.id DESC
                            ) AS rn
                        FROM notas_credito_local ncl
                        WHERE ncl.numero_nc_proveedor IS NOT NULL
                    ) ranked
                    WHERE rn > 1
                )
                """
            )
        )

    def _seed_duplicate_ncs_raw(
        self,
        db,
        *,
        empresa_id: int,
        proveedor_id: int,
        numero_nc_proveedor: str,
        creado_por_id: int,
        monto1: Decimal = Decimal("1000"),
        monto2: Decimal = Decimal("2000"),
    ) -> tuple[int, int]:
        """
        Inserta dos filas de notas_credito_local con el mismo numero_nc_proveedor
        simulando un estado PRE-migración donde el índice UNIQUE aún no existía.

        Estrategia:
          1. Crear dos NCs con numero_nc_proveedor distintos (respetando la constraint).
          2. Dropear el índice UNIQUE de la sesión actual.
          3. Actualizar una de las NCs para tener el mismo numero_nc_proveedor.
          4. Restaurar el índice.
        Devuelve (id_menor, id_mayor).
        """
        nc1 = ncs_locales_service.crear(
            db,
            empresa_id=empresa_id,
            proveedor_id=proveedor_id,
            moneda="ARS",
            monto=monto1,
            fecha_emision=date.today(),
            motivo="NC dedup C3 test A",
            creado_por_id=creado_por_id,
            numero_nc_proveedor=f"{numero_nc_proveedor}-A",
        )
        nc2 = ncs_locales_service.crear(
            db,
            empresa_id=empresa_id,
            proveedor_id=proveedor_id,
            moneda="ARS",
            monto=monto2,
            fecha_emision=date.today(),
            motivo="NC dedup C3 test B",
            creado_por_id=creado_por_id,
            numero_nc_proveedor=f"{numero_nc_proveedor}-B",
        )
        db.flush()

        # Dropear el índice UNIQUE temporalmente para poder tener duplicados.
        # Esto simula el estado pre-migración de la BD de producción.
        conn = db.connection()
        conn.execute(sa.text("DROP INDEX IF EXISTS uq_ncs_local_proveedor_numero_nc_prov"))

        # Igualar los numero_nc_proveedor de ambas NCs (crear el duplicado).
        conn.execute(
            sa.text("UPDATE notas_credito_local SET numero_nc_proveedor = :n WHERE id IN (:id1, :id2)"),
            {"n": numero_nc_proveedor, "id1": nc1.id, "id2": nc2.id},
        )

        id1, id2 = sorted([nc1.id, nc2.id])
        return id1, id2

    def test_preflight_detecta_multiples_con_imputaciones(self, db, empresa, proveedor, active_user) -> None:
        """
        C3/W5: Si hay dos NCs duplicadas con imputaciones activas en AMBAS,
        el pre-flight debe detectarlas y el operador debe ser alertado.
        """
        id1, id2 = self._seed_duplicate_ncs_raw(
            db,
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            numero_nc_proveedor="NC-C3-CONFLICT",
            creado_por_id=active_user.id,
        )

        # Agregar imputación activa a AMBAS.
        for nc_id in (id1, id2):
            db.add(
                Imputacion(
                    origen_tipo="nota_credito_local",
                    origen_id=nc_id,
                    destino_tipo="saldo",
                    destino_id=None,
                    monto_imputado=Decimal("100"),
                    moneda_imputada="ARS",
                    proveedor_id=proveedor.id,
                    es_reversal=False,
                    creado_por_id=active_user.id,
                )
            )
        db.flush()

        conflictos = self._run_preflight(db)

        assert len(conflictos) >= 1, "Pre-flight debe detectar el grupo con múltiples imputaciones"
        ids_en_conflicto = list(conflictos[0][2])
        assert id1 in ids_en_conflicto
        assert id2 in ids_en_conflicto

    def test_dedup_preserva_nc_con_imputaciones_borra_la_otra(self, db, empresa, proveedor, active_user) -> None:
        """
        W5 (caso positivo): Dos NCs duplicadas donde solo UNA tiene imputaciones.
        El dedup conserva la que tiene imputaciones y borra la otra.
        No hay conflicto: pre-flight pasa limpio.
        """
        id_con_imp, id_sin_imp = self._seed_duplicate_ncs_raw(
            db,
            empresa_id=empresa.id,
            proveedor_id=proveedor.id,
            numero_nc_proveedor="NC-W5-DEDUP",
            creado_por_id=active_user.id,
        )

        # Agregar imputación solo a id_con_imp (el de menor id).
        db.add(
            Imputacion(
                origen_tipo="nota_credito_local",
                origen_id=id_con_imp,
                destino_tipo="saldo",
                destino_id=None,
                monto_imputado=Decimal("100"),
                moneda_imputada="ARS",
                proveedor_id=proveedor.id,
                es_reversal=False,
                creado_por_id=active_user.id,
            )
        )
        db.flush()

        # Pre-flight debe pasar sin conflictos.
        conflictos = self._run_preflight(db)
        assert len(conflictos) == 0, f"Pre-flight no debe reportar conflicto, pero reportó: {conflictos}"

        # Ejecutar dedup.
        self._run_dedup_query(db)
        db.flush()

        # id_con_imp debe existir, id_sin_imp debe haber sido borrada.
        nc_con_imp_reloaded = db.query(NotaCreditoLocal).filter_by(id=id_con_imp).first()
        nc_sin_imp_reloaded = db.query(NotaCreditoLocal).filter_by(id=id_sin_imp).first()

        assert nc_con_imp_reloaded is not None, "La NC con imputaciones debe sobrevivir el dedup"
        assert nc_sin_imp_reloaded is None, "La NC sin imputaciones debe ser eliminada por el dedup"
