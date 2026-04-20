"""
Tests del `sale_document_classifier` (COMPRAS-2.1).

Dos bloques:

1. **Regresión del seed**: los 67 `sd_id` insertados por
   `compras_009_seed_tb_sale_document.py` NO deben devolver `UNKNOWN` en
   el clasificador. Se valida parametrizadamente.

2. **Tests específicos por sd_id conocido**: factura (101), remito (102),
   NC (103), OP (106), anulación (151), contraparte (161); signo contable;
   `afecta_cc_proveedor`; warning para ambiguos (sd_id=125).

La fixture `seeded_sale_documents` siembra los 67 registros en la DB de test
(SQLite en memoria via conftest) porque Alembic no corre en tests unitarios.
Usa los MISMOS valores que el seed de Alembic para que la clasificación de
los tests coincida con producción.
"""

from __future__ import annotations

import logging
from typing import Iterator

import pytest

from app.models.tb_sale_document import SaleDocument
from app.services.sale_document_classifier import (
    ClasificacionDocCompra,
    SD_IDS_AMBIGUOS,
    afecta_cc_proveedor,
    clasificar_documento_compra,
    es_anulacion,
    es_contraparte,
    es_contraparte_de,
    signo_contable,
)


# ──────────────────────────────────────────────────────────────────────────
# Seed usado por los tests de regresión.
# Mantener en sync con backend/alembic/versions/compras_009_seed_tb_sale_document.py
# ──────────────────────────────────────────────────────────────────────────

_SEEDED_SD_IDS: tuple[int, ...] = (
    # Ventas (1-80)
    1,
    2,
    3,
    4,
    5,
    6,
    7,
    12,
    13,
    15,
    21,
    23,
    31,
    33,
    43,
    44,
    52,
    56,
    66,
    80,
    # Compras / Bancos / Otros (101-500)
    101,
    102,
    103,
    104,
    105,
    106,
    121,
    123,
    124,
    125,
    128,
    129,
    130,
    131,
    132,
    133,
    140,
    141,
    142,
    143,
    144,
    145,
    151,
    152,
    153,
    154,
    156,
    161,
    162,
    163,
    164,
    166,
    180,
    190,
    200,
    201,
    202,
    203,
    204,
    205,
    206,
    250,
    251,
    301,
    302,
    350,
    500,
)


def _row(
    sd_id: int,
    desc: str,
    plusorminus: int,
    *,
    sd_issales: bool = False,
    sd_ispurchase: bool = False,
    sd_isbanking: bool = False,
    sd_iscredit: bool = False,
    sd_isquotation: bool = False,
    sd_isreceipt: bool = False,
    sd_istaxable: bool = False,
    sd_isinbalance: bool = False,
    sd_ispackinglist: bool = False,
    sd_iscreditnote: bool = False,
    sd_isdebitnote: bool = False,
    sd_isannulment: bool = False,
    hacc_group: int | None = None,
) -> SaleDocument:
    """Helper para construir una `SaleDocument` con flags explícitos."""
    return SaleDocument(
        sd_id=sd_id,
        sd_desc=desc,
        sd_plusorminus=plusorminus,
        sd_issales=sd_issales,
        sd_ispurchase=sd_ispurchase,
        sd_isbanking=sd_isbanking,
        sd_iscredit=sd_iscredit,
        sd_isquotation=sd_isquotation,
        sd_isreceipt=sd_isreceipt,
        sd_istaxable=sd_istaxable,
        sd_isinbalance=sd_isinbalance,
        sd_ispackinglist=sd_ispackinglist,
        sd_iscreditnote=sd_iscreditnote,
        sd_isdebitnote=sd_isdebitnote,
        sd_isannulment=sd_isannulment,
        hacc_group=hacc_group,
    )


def _build_seed() -> list[SaleDocument]:
    """
    Construye las 67 filas del seed en memoria. Espejo fiel del seed
    `compras_009_seed_tb_sale_document.py` — si cambia allá, cambiar acá.

    Las reglas de flags replican las del seed real (ver docstring de
    `_row` y design §2.1).
    """
    return [
        # ═══════════════════════════════════════════════════════════════
        # VENTAS (1-80) — sd_issales=true
        # ═══════════════════════════════════════════════════════════════
        _row(1, "01.Factura (ventas)", 1, sd_issales=True, sd_istaxable=True, sd_isinbalance=True, hacc_group=10001),
        _row(2, "02.Remito (ventas)", 1, sd_issales=True, sd_ispackinglist=True),
        _row(
            3,
            "03.Nota de Crédito (ventas)",
            -1,
            sd_issales=True,
            sd_iscreditnote=True,
            sd_istaxable=True,
            sd_isinbalance=True,
            hacc_group=10001,
        ),
        _row(
            4,
            "04.Nota de Débito (ventas)",
            1,
            sd_issales=True,
            sd_isdebitnote=True,
            sd_istaxable=True,
            sd_isinbalance=True,
        ),
        _row(5, "05.Presupuesto", 1, sd_issales=True, sd_isquotation=True),
        _row(6, "06.Recibo de Cobranza", -1, sd_issales=True, sd_isreceipt=True, sd_isinbalance=True, hacc_group=10002),
        _row(7, "07.Saldo Inicial Cliente", 1, sd_issales=True, sd_isinbalance=True),  # AMBIGUO
        _row(
            12,
            "Factura Anulada (ventas)",
            1,
            sd_issales=True,
            sd_istaxable=True,
            sd_isinbalance=True,
            sd_isannulment=True,
            hacc_group=10001,
        ),
        _row(
            13,
            "Recibo Anulado (ventas)",
            -1,
            sd_issales=True,
            sd_isreceipt=True,
            sd_isinbalance=True,
            sd_isannulment=True,
        ),
        _row(
            15,
            "Factura - Contraparte (ventas)",
            -1,
            sd_issales=True,
            sd_istaxable=True,
            sd_isinbalance=True,
            hacc_group=10001,
        ),  # AMBIGUO
        _row(21, "Saldo - Deuda Inicial Cliente", 1, sd_issales=True, sd_isinbalance=True, hacc_group=20001),
        _row(23, "Saldo - Crédito Inicial Cliente", -1, sd_issales=True, sd_isinbalance=True, hacc_group=20001),
        _row(31, "Líquido Producto (ventas)", 1, sd_issales=True, sd_isinbalance=True),  # AMBIGUO
        _row(33, "Consignación (ventas)", 1, sd_issales=True, sd_isinbalance=True),  # AMBIGUO
        _row(43, "RMA - Salida (ventas)", -1, sd_issales=True),
        _row(44, "RMA - Ingreso (ventas)", 1, sd_issales=True),
        _row(52, "Remito Anulado (ventas)", 1, sd_issales=True, sd_ispackinglist=True, sd_isannulment=True),
        _row(
            56,
            "Recibo - Contraparte (ventas)",
            1,
            sd_issales=True,
            sd_isreceipt=True,
            sd_isinbalance=True,
            hacc_group=10002,
        ),
        _row(66, "Devolución Cliente", -1, sd_issales=True, sd_iscreditnote=True, sd_isinbalance=True),
        _row(80, "Pedido de Producción", 1, sd_issales=True),  # AMBIGUO
        # ═══════════════════════════════════════════════════════════════
        # COMPRAS (101-133) — sd_ispurchase=true
        # ═══════════════════════════════════════════════════════════════
        _row(101, "01.Factura", 1, sd_ispurchase=True, sd_istaxable=True, sd_isinbalance=True, hacc_group=10011),
        _row(102, "02.Remito / Guía de Despacho", 1, sd_ispurchase=True, sd_ispackinglist=True),
        _row(
            103,
            "03.Nota de Crédito",
            -1,
            sd_ispurchase=True,
            sd_iscreditnote=True,
            sd_istaxable=True,
            sd_isinbalance=True,
            hacc_group=10011,
        ),
        _row(
            104, "04.Nota de Débito", 1, sd_ispurchase=True, sd_isdebitnote=True, sd_istaxable=True, sd_isinbalance=True
        ),
        _row(105, "05.Presupuesto Compra", 1, sd_ispurchase=True, sd_isquotation=True),
        _row(106, "06.Orden de Pago", -1, sd_ispurchase=True, sd_isreceipt=True, sd_isinbalance=True, hacc_group=10012),
        _row(121, "21.Saldo - Deuda (Sin Asiento)", 1, sd_ispurchase=True, sd_isinbalance=True, hacc_group=20101),
        _row(123, "23.Saldo - Crédito (Sin Asiento)", -1, sd_ispurchase=True, sd_isinbalance=True, hacc_group=20101),
        _row(124, "24.Carga inicial de Stock", 1, sd_ispurchase=True),
        _row(
            125,
            "25.Crédito por Cheque en OP - Rechazado",
            1,
            sd_ispurchase=True,
            sd_isdebitnote=True,
            sd_isinbalance=True,
        ),  # AMBIGUO
        _row(128, "28.Saldo - Deuda (Con Asiento)", 1, sd_ispurchase=True, sd_isinbalance=True, hacc_group=20101),
        _row(129, "29.Saldo - Crédito (Con Asiento)", -1, sd_ispurchase=True, sd_isinbalance=True, hacc_group=20101),
        _row(130, "30.Despacho Importación / Exportación", 1, sd_ispurchase=True, sd_isinbalance=True),
        _row(131, "31.Líquido Producto", 1, sd_ispurchase=True, sd_isinbalance=True),  # AMBIGUO
        _row(
            132, "32.Comprobante Dif. Cambio (Débito)", 1, sd_ispurchase=True, sd_isdebitnote=True, sd_isinbalance=True
        ),
        _row(
            133,
            "33.Comprobante Dif. Cambio (Crédito)",
            -1,
            sd_ispurchase=True,
            sd_iscreditnote=True,
            sd_isinbalance=True,
        ),
        # ═══════════════════════════════════════════════════════════════
        # BANKING (140-144)
        # ═══════════════════════════════════════════════════════════════
        _row(140, "40.Imputaciones Bancarias (Entrada)", -1, sd_isbanking=True, hacc_group=10140),
        _row(141, "41.Imputaciones Bancarias (Salida)", 1, sd_isbanking=True, hacc_group=10140),
        _row(142, "42.Liquidación Tarjetas de Crédito", 1, sd_isbanking=True, hacc_group=10142),
        _row(143, "43.Extracto Bancario (Resumen)", -1, sd_isbanking=True, hacc_group=10140),
        _row(144, "44.Extracto Bancario (Resumen) No Usar", 1, sd_isbanking=True, hacc_group=10140),
        _row(145, "Producción de Equipos", 1),  # AMBIGUO — no banking pese al rango
        # ═══════════════════════════════════════════════════════════════
        # COMPRAS ANULADAS (151-156)
        # ═══════════════════════════════════════════════════════════════
        _row(
            151,
            "Factura Anulada",
            1,
            sd_ispurchase=True,
            sd_istaxable=True,
            sd_isinbalance=True,
            sd_isannulment=True,
            hacc_group=10011,
        ),
        _row(152, "Remito Anulado", 1, sd_ispurchase=True, sd_ispackinglist=True, sd_isannulment=True),
        _row(
            153,
            "Nota de Crédito Anulada",
            1,
            sd_ispurchase=True,
            sd_iscreditnote=True,
            sd_istaxable=True,
            sd_isinbalance=True,
            sd_isannulment=True,
            hacc_group=10011,
        ),
        _row(
            154,
            "Nota de Débito Anulada",
            1,
            sd_ispurchase=True,
            sd_isdebitnote=True,
            sd_istaxable=True,
            sd_isinbalance=True,
            sd_isannulment=True,
        ),
        _row(
            156,
            "Orden de Pago - Anulada",
            -1,
            sd_ispurchase=True,
            sd_isreceipt=True,
            sd_isinbalance=True,
            sd_isannulment=True,
            hacc_group=10012,
        ),
        # ═══════════════════════════════════════════════════════════════
        # COMPRAS CONTRAPARTES (161-166)
        # ═══════════════════════════════════════════════════════════════
        _row(
            161,
            "Factura Anulada - Contraparte",
            -1,
            sd_ispurchase=True,
            sd_istaxable=True,
            sd_isinbalance=True,
            hacc_group=10011,
        ),
        _row(162, "Remito Anulado - Contraparte", -1, sd_ispurchase=True, sd_ispackinglist=True, sd_isinbalance=True),
        _row(
            163,
            "Nota de Crédito Anulada - Contraparte",
            -1,
            sd_ispurchase=True,
            sd_iscreditnote=True,
            sd_istaxable=True,
            sd_isinbalance=True,
            hacc_group=10011,
        ),
        _row(
            164,
            "Nota de Débito Anulada - Contraparte",
            -1,
            sd_ispurchase=True,
            sd_isdebitnote=True,
            sd_istaxable=True,
            sd_isinbalance=True,
        ),
        _row(
            166,
            "Orden de Pago - Contraparte",
            1,
            sd_ispurchase=True,
            sd_isreceipt=True,
            sd_isinbalance=True,
            hacc_group=10012,
        ),
        # ═══════════════════════════════════════════════════════════════
        # DESPACHOS / CONTRAPARTES (180, 190)
        # ═══════════════════════════════════════════════════════════════
        _row(
            180,
            "Despacho Importación/Exportación - Anulado",
            1,
            sd_ispurchase=True,
            sd_isinbalance=True,
            sd_isannulment=True,
        ),
        _row(190, "Despacho Importación/Exportación - Contraparte", -1, sd_ispurchase=True, sd_isinbalance=True),
        # ═══════════════════════════════════════════════════════════════
        # BANKING 200-206
        # ═══════════════════════════════════════════════════════════════
        _row(200, "Deposito Bancario de Valores", 1, sd_isbanking=True),
        _row(201, "Emisión de Cheques Propios", 1, sd_isbanking=True),
        _row(202, "Depósito Bancario de Efectivo", 1, sd_isbanking=True),
        _row(203, "Retiro de Efectivo de Caja", 1, sd_isbanking=True),
        _row(204, "Retiro de Efectivo de Banco", 1, sd_isbanking=True),
        _row(205, "Retiro de Efectivo de Banco a Caja", 1, sd_isbanking=True),  # AMBIGUO
        _row(206, "Control de Debito de Valores Propios", 1, sd_isbanking=True),
        # ═══════════════════════════════════════════════════════════════
        # BANKING anulaciones / rechazos
        # ═══════════════════════════════════════════════════════════════
        _row(250, "Anulación de Depósito Bancario de Valores", -1, sd_isbanking=True, sd_isannulment=True),
        _row(251, "Rechazo de Valores", 1, sd_isbanking=True),
        # ═══════════════════════════════════════════════════════════════
        # STOCK / RMA / PRODUCCIÓN (300+)
        # ═══════════════════════════════════════════════════════════════
        _row(301, "RMA - Ingreso a Depósito", 1),  # AMBIGUO
        _row(302, "RMA - Egreso de Depósito", -1),  # AMBIGUO
        _row(350, "STOCK - Ajustes de Stock", 1),  # AMBIGUO
        _row(500, "Producción", 1),  # AMBIGUO
    ]


@pytest.fixture
def seeded_sale_documents(db) -> Iterator[None]:
    """
    Puebla la DB de test con los 67 registros del seed. Se ejecuta por test
    (matching el scope del fixture `db` de conftest que rollbackea tras
    cada test).
    """
    rows = _build_seed()
    db.add_all(rows)
    db.flush()
    yield
    # Cleanup: la transacción de `db` se rollbackea en el teardown del
    # fixture; no hace falta borrar manualmente.


# ──────────────────────────────────────────────────────────────────────────
# Guardas del tamaño y unicidad del seed (siempre activos)
# ──────────────────────────────────────────────────────────────────────────


def test_seeded_sd_ids_count_esperado() -> None:
    assert len(_SEEDED_SD_IDS) == 67, (
        f"Se esperaban 67 sd_id, hay {len(_SEEDED_SD_IDS)}. Sincronizar con "
        f"compras_009_seed_tb_sale_document.py::_SEEDED_SD_IDS."
    )


def test_seeded_sd_ids_son_unicos() -> None:
    assert len(set(_SEEDED_SD_IDS)) == len(_SEEDED_SD_IDS), "Hay duplicados en _SEEDED_SD_IDS."


def test_build_seed_genera_67_filas() -> None:
    """El helper _build_seed debe generar exactamente 67 filas con los mismos sd_id."""
    rows = _build_seed()
    assert len(rows) == 67
    assert tuple(r.sd_id for r in rows) == _SEEDED_SD_IDS


# ──────────────────────────────────────────────────────────────────────────
# Regresión parametrizada: ningún sd_id del seed retorna UNKNOWN
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("sd_id", _SEEDED_SD_IDS)
def test_clasificador_no_retorna_unknown_para_sd_id_conocido(sd_id: int, db, seeded_sale_documents) -> None:
    """
    El clasificador debe retornar una clasificación definida para los 67
    sd_id del seed. `UNKNOWN` indicaría regresión en los predicados.
    """
    sd = db.query(SaleDocument).filter(SaleDocument.sd_id == sd_id).one()
    clasificacion = clasificar_documento_compra(sd)

    assert clasificacion != ClasificacionDocCompra.UNKNOWN, (
        f"sd_id={sd_id} ('{sd.sd_desc}') quedó sin clasificar (UNKNOWN). "
        f"Revisar predicados en sale_document_classifier.py."
    )


# ──────────────────────────────────────────────────────────────────────────
# Tests específicos por sd_id conocido (COMPRAS-2.1 acceptance)
# ──────────────────────────────────────────────────────────────────────────


class TestClasificacionCompras:
    """Clasificación esperada para los tipos canónicos de compras."""

    def test_clasifica_factura_compra_101(self, db, seeded_sale_documents) -> None:
        sd = db.query(SaleDocument).filter(SaleDocument.sd_id == 101).one()
        assert clasificar_documento_compra(sd) == ClasificacionDocCompra.FACTURA

    def test_clasifica_nc_103(self, db, seeded_sale_documents) -> None:
        sd = db.query(SaleDocument).filter(SaleDocument.sd_id == 103).one()
        assert clasificar_documento_compra(sd) == ClasificacionDocCompra.NC

    def test_clasifica_remito_102(self, db, seeded_sale_documents) -> None:
        sd = db.query(SaleDocument).filter(SaleDocument.sd_id == 102).one()
        assert clasificar_documento_compra(sd) == ClasificacionDocCompra.REMITO

    def test_clasifica_op_106(self, db, seeded_sale_documents) -> None:
        sd = db.query(SaleDocument).filter(SaleDocument.sd_id == 106).one()
        assert clasificar_documento_compra(sd) == ClasificacionDocCompra.ORDEN_PAGO

    def test_clasifica_factura_anulada_151(self, db, seeded_sale_documents) -> None:
        sd = db.query(SaleDocument).filter(SaleDocument.sd_id == 151).one()
        assert clasificar_documento_compra(sd) == ClasificacionDocCompra.ANULACION

    def test_clasifica_contraparte_161(self, db, seeded_sale_documents) -> None:
        """
        sd_id=161 es "Factura Anulada - Contraparte": mismo hacc_group que
        101 (10011) pero plusOrminus invertido (-1 vs +1). El clasificador
        base devuelve FACTURA (tiene `istaxable + isinbalance`), y la
        semántica "CONTRAPARTE" se detecta vía `es_contraparte_de` /
        `es_contraparte` que consulta el par.
        """
        sd_101 = db.query(SaleDocument).filter(SaleDocument.sd_id == 101).one()
        sd_161 = db.query(SaleDocument).filter(SaleDocument.sd_id == 161).one()

        # 161 solo: se clasifica como FACTURA (flags iguales que 101 pero signo opuesto)
        assert clasificar_documento_compra(sd_161) == ClasificacionDocCompra.FACTURA

        # Pero `es_contraparte_de(161, 101)` debe ser True
        assert es_contraparte_de(sd_161, sd_101) is True
        # Y la dirección inversa también (es relación simétrica del predicado binario),
        # aunque el convenio "sd_id mayor gana" se aplica en `es_contraparte(sd, session)`.
        assert es_contraparte_de(sd_101, sd_161) is True

        # Convenio "sd_id mayor = contraparte": solo el 161 debe ser contraparte.
        assert es_contraparte(sd_161, db) is True
        assert es_contraparte(sd_101, db) is False


class TestAmbiguosEmitenWarning:
    """Los 13 sd_id ambiguos disparan logger.warning (Engram #124)."""

    def test_ambiguo_125_emite_warning(self, db, seeded_sale_documents, caplog: pytest.LogCaptureFixture) -> None:
        """Clasificar sd_id=125 debe emitir WARNING con 'AMBIGUO'."""
        target_logger = logging.getLogger("app.services.sale_document_classifier")
        target_logger.addHandler(caplog.handler)
        target_logger.setLevel(logging.WARNING)

        try:
            sd = db.query(SaleDocument).filter(SaleDocument.sd_id == 125).one()
            clasificacion = clasificar_documento_compra(sd)
        finally:
            target_logger.removeHandler(caplog.handler)

        # La clasificación sigue siendo determinista (ND por sd_isdebitnote=True).
        assert clasificacion == ClasificacionDocCompra.ND
        # Y el WARNING se emitió.
        assert any("AMBIGUO" in r.getMessage() and "sd_id=125" in r.getMessage() for r in caplog.records), (
            f"No se emitió WARNING para sd_id=125. Records: {[r.getMessage() for r in caplog.records]}"
        )

    def test_no_ambiguo_101_no_emite_warning(self, db, seeded_sale_documents, caplog: pytest.LogCaptureFixture) -> None:
        target_logger = logging.getLogger("app.services.sale_document_classifier")
        target_logger.addHandler(caplog.handler)
        target_logger.setLevel(logging.WARNING)

        try:
            sd = db.query(SaleDocument).filter(SaleDocument.sd_id == 101).one()
            clasificar_documento_compra(sd)
        finally:
            target_logger.removeHandler(caplog.handler)

        assert not any("AMBIGUO" in r.getMessage() for r in caplog.records), (
            "sd_id=101 NO debería emitir WARNING de ambiguo."
        )

    def test_sd_ids_ambiguos_son_los_esperados(self) -> None:
        """La constante SD_IDS_AMBIGUOS debe ser los 13 identificados en Engram #124."""
        esperados = frozenset({7, 15, 31, 33, 80, 125, 131, 145, 205, 301, 302, 350, 500})
        assert SD_IDS_AMBIGUOS == esperados


class TestSignoContable:
    """`signo_contable` delega en sd.sd_plusorminus sin lógica derivada."""

    def test_signo_factura_101_positivo(self, db, seeded_sale_documents) -> None:
        sd = db.query(SaleDocument).filter(SaleDocument.sd_id == 101).one()
        assert signo_contable(sd) == 1

    def test_signo_nc_103_negativo(self, db, seeded_sale_documents) -> None:
        sd = db.query(SaleDocument).filter(SaleDocument.sd_id == 103).one()
        assert signo_contable(sd) == -1

    def test_signo_op_106_negativo(self, db, seeded_sale_documents) -> None:
        sd = db.query(SaleDocument).filter(SaleDocument.sd_id == 106).one()
        assert signo_contable(sd) == -1


class TestAfectaCcProveedor:
    """Qué tipos generan movimiento en cc_proveedor_movimientos."""

    def test_afecta_cc_factura(self, db, seeded_sale_documents) -> None:
        sd = db.query(SaleDocument).filter(SaleDocument.sd_id == 101).one()
        assert afecta_cc_proveedor(sd) is True

    def test_afecta_cc_nc(self, db, seeded_sale_documents) -> None:
        sd = db.query(SaleDocument).filter(SaleDocument.sd_id == 103).one()
        assert afecta_cc_proveedor(sd) is True

    def test_afecta_cc_op(self, db, seeded_sale_documents) -> None:
        sd = db.query(SaleDocument).filter(SaleDocument.sd_id == 106).one()
        assert afecta_cc_proveedor(sd) is True

    def test_afecta_cc_ajuste_saldo(self, db, seeded_sale_documents) -> None:
        """sd_id=121 tiene hacc_group=20101 → AJUSTE_SALDO → afecta CC."""
        sd = db.query(SaleDocument).filter(SaleDocument.sd_id == 121).one()
        assert afecta_cc_proveedor(sd) is True

    def test_no_afecta_cc_remito(self, db, seeded_sale_documents) -> None:
        sd = db.query(SaleDocument).filter(SaleDocument.sd_id == 102).one()
        assert afecta_cc_proveedor(sd) is False

    def test_no_afecta_cc_presupuesto(self, db, seeded_sale_documents) -> None:
        sd = db.query(SaleDocument).filter(SaleDocument.sd_id == 105).one()
        assert afecta_cc_proveedor(sd) is False

    def test_no_afecta_cc_anulacion(self, db, seeded_sale_documents) -> None:
        sd = db.query(SaleDocument).filter(SaleDocument.sd_id == 151).one()
        assert afecta_cc_proveedor(sd) is False

    def test_no_afecta_cc_venta(self, db, seeded_sale_documents) -> None:
        """Documento de ventas (sd_ispurchase=False) → IGNORAR → no afecta CC proveedor."""
        sd = db.query(SaleDocument).filter(SaleDocument.sd_id == 1).one()
        assert afecta_cc_proveedor(sd) is False


class TestEsAnulacion:
    def test_anulacion_151_es_true(self, db, seeded_sale_documents) -> None:
        sd = db.query(SaleDocument).filter(SaleDocument.sd_id == 151).one()
        assert es_anulacion(sd) is True

    def test_factura_normal_101_no_es_anulacion(self, db, seeded_sale_documents) -> None:
        sd = db.query(SaleDocument).filter(SaleDocument.sd_id == 101).one()
        assert es_anulacion(sd) is False


class TestEsContraparteDe:
    """Predicado binario (sin consulta DB)."""

    def test_mismo_hacc_group_plusorminus_invertido_es_contraparte(self, db, seeded_sale_documents) -> None:
        sd_101 = db.query(SaleDocument).filter(SaleDocument.sd_id == 101).one()  # hacc=10011, +1
        sd_161 = db.query(SaleDocument).filter(SaleDocument.sd_id == 161).one()  # hacc=10011, -1
        assert es_contraparte_de(sd_161, sd_101) is True

    def test_mismo_sd_id_no_es_contraparte_de_si_mismo(self, db, seeded_sale_documents) -> None:
        sd = db.query(SaleDocument).filter(SaleDocument.sd_id == 101).one()
        assert es_contraparte_de(sd, sd) is False

    def test_distinto_hacc_group_no_es_contraparte(self, db, seeded_sale_documents) -> None:
        sd_101 = db.query(SaleDocument).filter(SaleDocument.sd_id == 101).one()  # hacc=10011
        sd_106 = db.query(SaleDocument).filter(SaleDocument.sd_id == 106).one()  # hacc=10012
        assert es_contraparte_de(sd_101, sd_106) is False

    def test_hacc_group_null_no_es_contraparte(self, db, seeded_sale_documents) -> None:
        sd_102 = db.query(SaleDocument).filter(SaleDocument.sd_id == 102).one()  # hacc=None
        sd_101 = db.query(SaleDocument).filter(SaleDocument.sd_id == 101).one()
        assert es_contraparte_de(sd_102, sd_101) is False


class TestClasificacionPorFlags:
    """Smoke tests de los 10 valores del enum con SaleDocument sintéticos."""

    def test_ignorar_si_no_es_purchase(self) -> None:
        sd = _row(9999, "ventas", 1, sd_issales=True, sd_istaxable=True, sd_isinbalance=True)
        assert clasificar_documento_compra(sd) == ClasificacionDocCompra.IGNORAR

    def test_anulacion_gana_sobre_factura(self) -> None:
        """Si `isannulment=True`, devuelve ANULACION sin importar los otros flags."""
        sd = _row(
            9999,
            "factura anulada sintética",
            1,
            sd_ispurchase=True,
            sd_istaxable=True,
            sd_isinbalance=True,
            sd_isannulment=True,
        )
        assert clasificar_documento_compra(sd) == ClasificacionDocCompra.ANULACION

    def test_ajuste_saldo_por_hacc_20101(self) -> None:
        sd = _row(9999, "saldo deuda", 1, sd_ispurchase=True, sd_isinbalance=True, hacc_group=20101)
        assert clasificar_documento_compra(sd) == ClasificacionDocCompra.AJUSTE_SALDO

    def test_fallback_ignorar_si_no_matchea_nada(self) -> None:
        """sd_ispurchase=True pero sin istaxable/isinbalance → IGNORAR."""
        sd = _row(9999, "compra weird", 1, sd_ispurchase=True)
        assert clasificar_documento_compra(sd) == ClasificacionDocCompra.IGNORAR


# ──────────────────────────────────────────────────────────────────────────
# COMPRAS-7.1 — Fix bug clasificador CONTRAPARTE con `session` (Engram #125)
# ──────────────────────────────────────────────────────────────────────────


class TestClasificadorDetectaContraparteConSession:
    """
    Cuando el caller pasa `session`, el clasificador detecta CONTRAPARTE vía
    lookup del par inverso en DB (convenio "sd_id mayor gana", design §2.1).

    Sin session se mantiene el comportamiento histórico (clasifica por flags
    base, ej: 161 → FACTURA).
    """

    def test_clasifica_contraparte_161_con_session(self, db, seeded_sale_documents) -> None:
        """sd_id=161 es contraparte de 101 (mismo hacc_group=10011, plusorminus invertido)."""
        sd = db.query(SaleDocument).filter(SaleDocument.sd_id == 161).one()
        assert clasificar_documento_compra(sd, session=db) == ClasificacionDocCompra.CONTRAPARTE

    def test_clasifica_contraparte_162_con_session(self, db, seeded_sale_documents) -> None:
        """
        sd_id=162 (Remito Anulado - Contraparte). hacc_group=None (remito no lo
        tiene en el seed) → `es_contraparte` devuelve False → el clasificador
        cae al paso REMITO por `sd_ispackinglist=True`.

        Documentado: los remitos contraparte no son detectables por la heurística
        de hacc_group. Se mantiene como REMITO; la vista SQL igual los filtra.
        """
        sd = db.query(SaleDocument).filter(SaleDocument.sd_id == 162).one()
        # 162 no tiene hacc_group → es_contraparte=False → matchea REMITO por sd_ispackinglist.
        assert clasificar_documento_compra(sd, session=db) == ClasificacionDocCompra.REMITO

    def test_clasifica_contraparte_163_con_session(self, db, seeded_sale_documents) -> None:
        """sd_id=163 (NC Anulada - Contraparte) es contraparte de 103 (hacc=10011)."""
        sd = db.query(SaleDocument).filter(SaleDocument.sd_id == 163).one()
        assert clasificar_documento_compra(sd, session=db) == ClasificacionDocCompra.CONTRAPARTE

    def test_clasifica_contraparte_164_con_session(self, db, seeded_sale_documents) -> None:
        """
        sd_id=164 (ND Anulada - Contraparte). Sin hacc_group (104 tampoco lo
        tiene) → no detectable por heurística → cae a ND por sd_isdebitnote.
        """
        sd = db.query(SaleDocument).filter(SaleDocument.sd_id == 164).one()
        assert clasificar_documento_compra(sd, session=db) == ClasificacionDocCompra.ND

    def test_clasifica_contraparte_166_con_session(self, db, seeded_sale_documents) -> None:
        """sd_id=166 (OP Contraparte) es contraparte de 106 (hacc=10012, signo invertido)."""
        sd = db.query(SaleDocument).filter(SaleDocument.sd_id == 166).one()
        assert clasificar_documento_compra(sd, session=db) == ClasificacionDocCompra.CONTRAPARTE

    def test_clasifica_contraparte_190_con_session(self, db, seeded_sale_documents) -> None:
        """
        sd_id=190 (Despacho Import/Export - Contraparte). Sin hacc_group →
        no detectable → fallback a IGNORAR (sd_isinbalance=True pero sin
        sd_istaxable, así que no llega a FACTURA tampoco).
        """
        sd = db.query(SaleDocument).filter(SaleDocument.sd_id == 190).one()
        # 190 no tiene hacc_group ni istaxable → cae al fallback IGNORAR.
        assert clasificar_documento_compra(sd, session=db) == ClasificacionDocCompra.IGNORAR

    def test_sin_session_161_fallback_a_factura(self, db, seeded_sale_documents) -> None:
        """
        Backward-compat: sin session, sd_id=161 se clasifica como FACTURA
        (mismos flags que 101 pero signo invertido). El test de regresión
        preexistente asume este comportamiento.
        """
        sd = db.query(SaleDocument).filter(SaleDocument.sd_id == 161).one()
        assert clasificar_documento_compra(sd) == ClasificacionDocCompra.FACTURA
        # Explícito: session=None equivale al default.
        assert clasificar_documento_compra(sd, session=None) == ClasificacionDocCompra.FACTURA
