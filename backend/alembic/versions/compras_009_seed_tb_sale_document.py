"""compras 009 — seed estático tb_sale_document (67 registros)

Revision ID: compras_009_seed_sd
Revises: compras_008_cc
Create Date: 2026-04-17

Seed estático del catálogo tb_sale_document con 67 tipos de documento
conocidos del ERP:
  - Tabla 1 (ventas, sd_id 1-80): 20 registros
  - Tabla 2 (compras/bancos/otros, sd_id 101-500): 47 registros

Nota sobre el conteo: el prompt original decía "~43 registros". Al parsear
las dos tablas pasadas por el usuario, el total real es 67 — se siguió el
contenido de las tablas (levantado en contract result).

Fuente: Engram obs #106 + conversación con el usuario (dos tablas).
Flags booleanos INFERIDOS siguiendo reglas explícitas del prompt (NO inventados):
  - Por descripción: Factura → ispurchase/issales + istaxable + isinbalance
  - Por descripción: NC → iscreditnote + isinbalance
  - Por descripción: ND → isdebitnote + isinbalance
  - Por descripción: Remito → ispackinglist + NO isinbalance + NO istaxable
  - Por descripción: Recibo u Orden de Pago → isreceipt + isinbalance
  - Por descripción: Presupuesto → isquotation + NO isinbalance
  - Por descripción: Saldo/Saldos Iniciales → isinbalance
  - Por descripción: Anulada/Anulación → isannulment (mantiene tipo base)
  - Por descripción: Contraparte → asiento cruzado, isinbalance
  - Por descripción: Banc/Deposito/Cheque/Extracto → isbanking, NO isinbalance
  - Por descripción: Diferencia de Cambio → iscreditnote/isdebitnote + isinbalance
  - Por descripción: Stock/RMA/Producción/Carga inicial → NO isinbalance (no CC)
Por rango sd_id:
  - 1-80     → sd_issales=true  (excepto banking/stock/RMA)
  - 101-199  → sd_ispurchase=true  (excepto bancarios 140-144)
  - 140-144, 200-251 → sd_isbanking=true (ambos sales/purchase false)
  - 300+     → ambos false (stock/RMA/producción)

sd_plusorminus: copiado literal de la columna del usuario. Para los 3 casos
"no pasados" (sd_id 80, 205, 500) se usa fallback 1 con TODO.

Casos AMBIGUOS marcados en comentarios inline: 7, 15, 31, 33, 80, 125, 131,
145, 205, 301, 302, 350, 500.

IMPORTANTE: esta migración popula el catálogo que usa `sale_document_classifier`
(pendiente en Fase 2). Si cambia el ERP con nuevos tipos, se agrega vía nueva
migración Alembic — NO hay sync automático (refinement 2026-04-17, obs #121).
"""

from datetime import datetime
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "compras_009_seed_sd"
down_revision: Union[str, None] = "compras_008_cc"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Todos los sd_id insertados por este seed (usado en downgrade).
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
    sd_desc: str,
    sd_plusorminus: int,
    *,
    sd_iscredit: bool = False,
    sd_isquotation: bool = False,
    sd_isreceipt: bool = False,
    sd_istaxable: bool = False,
    sd_isinbalance: bool = False,
    sd_issales: bool = False,
    sd_ispurchase: bool = False,
    sd_isbanking: bool = False,
    sd_ispackinglist: bool = False,
    sd_iscreditnote: bool = False,
    sd_isdebitnote: bool = False,
    sd_isannulment: bool = False,
    hacc_group: int | None = None,
) -> dict:
    """Helper para armar dicts de fila con todos los flags por defecto False."""
    return {
        "sd_id": sd_id,
        "sd_desc": sd_desc,
        "sd_iscredit": sd_iscredit,
        "sd_isquotation": sd_isquotation,
        "sd_isreceipt": sd_isreceipt,
        "sd_istaxable": sd_istaxable,
        "sd_isinbalance": sd_isinbalance,
        "sd_issales": sd_issales,
        "sd_ispurchase": sd_ispurchase,
        "sd_isbanking": sd_isbanking,
        "sd_ispackinglist": sd_ispackinglist,
        "sd_iscreditnote": sd_iscreditnote,
        "sd_isdebitnote": sd_isdebitnote,
        "sd_isannulment": sd_isannulment,
        "sd_plusorminus": sd_plusorminus,
        "hacc_group": hacc_group,
    }


def upgrade() -> None:
    tb_sale_document = sa.table(
        "tb_sale_document",
        sa.column("sd_id", sa.Integer()),
        sa.column("sd_desc", sa.String()),
        sa.column("sd_iscredit", sa.Boolean()),
        sa.column("sd_isquotation", sa.Boolean()),
        sa.column("sd_isreceipt", sa.Boolean()),
        sa.column("sd_istaxable", sa.Boolean()),
        sa.column("sd_isinbalance", sa.Boolean()),
        sa.column("sd_issales", sa.Boolean()),
        sa.column("sd_ispurchase", sa.Boolean()),
        sa.column("sd_isbanking", sa.Boolean()),
        sa.column("sd_ispackinglist", sa.Boolean()),
        sa.column("sd_iscreditnote", sa.Boolean()),
        sa.column("sd_isdebitnote", sa.Boolean()),
        sa.column("sd_isannulment", sa.Boolean()),
        sa.column("sd_plusorminus", sa.SmallInteger()),
        sa.column("hacc_group", sa.Integer()),
    )

    rows: list[dict] = [
        # ─────────────────────────────────────────────────────────────────
        # VENTAS (sd_id 1-80) — sd_issales=true (excepto stock/prod)
        # ─────────────────────────────────────────────────────────────────
        _row(
            1,
            "Factura",
            1,
            sd_issales=True,
            sd_istaxable=True,
            sd_isinbalance=True,
            hacc_group=10001,
        ),
        _row(
            2,
            "Remito / Guía de Despacho",
            1,
            sd_issales=True,
            sd_ispackinglist=True,
        ),
        _row(
            3,
            "Nota de Crédito",
            -1,
            sd_issales=True,
            sd_iscreditnote=True,
            sd_istaxable=True,
            sd_isinbalance=True,
            hacc_group=10001,
        ),
        _row(
            4,
            "Nota de Débito",
            1,
            sd_issales=True,
            sd_isdebitnote=True,
            sd_istaxable=True,
            sd_isinbalance=True,
        ),
        _row(
            5,
            "Presupuesto",
            1,
            sd_issales=True,
            sd_isquotation=True,
        ),
        _row(
            6,
            "Recibo de Cobranza Emitido por Sistema",
            -1,
            sd_issales=True,
            sd_isreceipt=True,
            sd_isinbalance=True,
        ),
        # AMBIGUO: revisar — Recibo "NO USAR COMO RECIBO DE COBRANZA". Se trata
        # como receipt de ventas siguiendo la regla genérica "Recibo → isreceipt".
        _row(
            7,
            "Recibo de Ingreso de Valores ( NO USAR COMO RECIBO DE COBRANZA )",
            -1,
            sd_issales=True,
            sd_isreceipt=True,
            sd_isinbalance=True,
        ),
        # Remito de entrada: semánticamente inverso pero sigue siendo packing list
        # del lado ventas (opuesto a remito, descuenta stock saliente).
        _row(
            12,
            "Remito / Guía de Despacho de ENTRADA (Opuesto a REMITO)",
            -1,
            sd_issales=True,
            sd_ispackinglist=True,
        ),
        _row(
            13,
            "Recibo de Cobranza en Talonario Manual",
            -1,
            sd_issales=True,
            sd_isreceipt=True,
            sd_isinbalance=True,
        ),
        # AMBIGUO: revisar — "Abono Mensual - Máscara para Generación de Pedidos".
        # No es factura, ni NC, ni recibo. Es una máscara/template. Se deja
        # como NO-isinbalance (no mueve CC) y sin flags específicos.
        _row(
            15,
            "Abono Mensual - Máscara para Generación de Pedidos para la Venta",
            1,
            sd_issales=True,
        ),
        _row(
            21,
            "Saldos Iniciales (Deuda)",
            1,
            sd_issales=True,
            sd_isinbalance=True,
            hacc_group=20001,
        ),
        _row(
            23,
            "Saldos Iniciales (a Favor del Cliente)",
            -1,
            sd_issales=True,
            sd_isinbalance=True,
            hacc_group=20001,
        ),
        # AMBIGUO: revisar — "Líquido Producto - Débito" (agro/comisionista).
        # Afecta CC (débito del productor) pero no encaja limpio en factura/NC/ND.
        # Se marca como isdebitnote por semántica contable cercana + isinbalance.
        _row(
            31,
            "Líquido Producto - Débito",
            1,
            sd_issales=True,
            sd_isdebitnote=True,
            sd_isinbalance=True,
        ),
        # AMBIGUO: revisar — "Líquido Producto - Crédito" (agro/comisionista).
        # Mismo criterio que sd_id=31 pero en lado crédito.
        _row(
            33,
            "Líquido Producto - Crédito",
            -1,
            sd_issales=True,
            sd_iscreditnote=True,
            sd_isinbalance=True,
        ),
        # Diferencia de cambio en clientes en USD → NC con impacto en CC
        _row(
            43,
            "Nota de Crédito x Diferencia de Cambio (Clientes en USD)",
            -1,
            sd_issales=True,
            sd_iscreditnote=True,
            sd_isinbalance=True,
        ),
        _row(
            44,
            "Nota de Débito x Diferencia de Cambio (Clientes en USD)",
            1,
            sd_issales=True,
            sd_isdebitnote=True,
            sd_isinbalance=True,
        ),
        # Anulación de remito: mantiene flag packinglist (sigue siendo remito anulado)
        _row(
            52,
            "Anulación de Remito x Ventas",
            -1,
            sd_issales=True,
            sd_ispackinglist=True,
            sd_isannulment=True,
        ),
        # Recibo anulado: flag isannulment=true + isreceipt=true (sigue siendo recibo)
        _row(
            56,
            "Recibo - Anulado",
            1,
            sd_issales=True,
            sd_isreceipt=True,
            sd_isannulment=True,
            sd_isinbalance=True,
        ),
        # Contraparte — asiento contable cruzado del sd_id 6/7/13 (Recibo)
        _row(
            66,
            "Recibo - Contraparte",
            -1,
            sd_issales=True,
            sd_isreceipt=True,
            sd_isinbalance=True,
        ),
        # AMBIGUO: revisar — "Pedido de Producción" (no pasado plusOrminus, fallback=1).
        # Es semánticamente stock/producción, no CC. NO afecta balance.
        # TODO: verificar con ERP — plusOrminus no pasado por usuario
        _row(
            80,
            "Pedido de Producción",
            1,
            sd_issales=True,
        ),
        # ─────────────────────────────────────────────────────────────────
        # COMPRAS (sd_id 101-133) — sd_ispurchase=true
        # ─────────────────────────────────────────────────────────────────
        _row(
            101,
            "01.Factura",
            1,
            sd_ispurchase=True,
            sd_istaxable=True,
            sd_isinbalance=True,
            hacc_group=10011,
        ),
        _row(
            102,
            "02.Remito / Guía de Despacho",
            1,
            sd_ispurchase=True,
            sd_ispackinglist=True,
        ),
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
            104,
            "04.Nota de Débito",
            1,
            sd_ispurchase=True,
            sd_isdebitnote=True,
            sd_istaxable=True,
            sd_isinbalance=True,
        ),
        _row(
            105,
            "05.Presupuesto Compra",
            1,
            sd_ispurchase=True,
            sd_isquotation=True,
        ),
        # Orden de Pago: en compras funciona como "recibo" — isreceipt=true + isinbalance=true
        _row(
            106,
            "06.Orden de Pago",
            -1,
            sd_ispurchase=True,
            sd_isreceipt=True,
            sd_isinbalance=True,
            hacc_group=10012,
        ),
        _row(
            121,
            "21.Saldo - Deuda - ( Sin Asiento Contable )",
            1,
            sd_ispurchase=True,
            sd_isinbalance=True,
            hacc_group=20101,
        ),
        _row(
            123,
            "23.Saldo - Crédito ( Sin Asiento Contable )",
            -1,
            sd_ispurchase=True,
            sd_isinbalance=True,
            hacc_group=20101,
        ),
        # "Carga inicial de Stock": es stock — NO afecta CC.
        _row(
            124,
            "24.Carga inicial de Stock",
            1,
            sd_ispurchase=True,
        ),
        # AMBIGUO: revisar — "Crédito por Cheque en OP - Rechazado": reverso de OP.
        # Afecta CC (vuelve a incrementar deuda al rebotar el cheque). Se trata
        # como debitnote (vuelve a agregar al saldo) + isinbalance.
        _row(
            125,
            "25.Crédito por Cheque en OP - Rechazado",
            1,
            sd_ispurchase=True,
            sd_isdebitnote=True,
            sd_isinbalance=True,
        ),
        _row(
            128,
            "28.Saldo - Deuda - ( Con Asiento Contable )",
            1,
            sd_ispurchase=True,
            sd_isinbalance=True,
            hacc_group=20101,
        ),
        _row(
            129,
            "29.Saldo - Crédito ( Con Asiento Contable )",
            -1,
            sd_ispurchase=True,
            sd_isinbalance=True,
            hacc_group=20101,
        ),
        _row(
            130,
            "30.Despacho Importación / Exportación",
            1,
            sd_ispurchase=True,
            sd_isinbalance=True,
        ),
        # AMBIGUO: revisar — "Líquido Producto" en rango compras (no "Débito"/"Crédito"
        # explícito en desc). Se trata como factura de compra (aumenta saldo).
        _row(
            131,
            "31.Líquido Producto",
            1,
            sd_ispurchase=True,
            sd_isinbalance=True,
        ),
        _row(
            132,
            "32.Comprobante de Diferencia de Cambio (Débito)",
            1,
            sd_ispurchase=True,
            sd_isdebitnote=True,
            sd_isinbalance=True,
        ),
        _row(
            133,
            "33.Comprobante de Diferencia de Cambio (Crédito)",
            -1,
            sd_ispurchase=True,
            sd_iscreditnote=True,
            sd_isinbalance=True,
        ),
        # ─────────────────────────────────────────────────────────────────
        # BANCARIOS (140-144) — sd_isbanking=true, NO isinbalance (no CC prov)
        # ─────────────────────────────────────────────────────────────────
        _row(
            140,
            "40.Imputaciones Bancarias - (Entrada)",
            -1,
            sd_isbanking=True,
            hacc_group=10140,
        ),
        _row(
            141,
            "41.Imputaciones Bancarias - (Salida)",
            1,
            sd_isbanking=True,
            hacc_group=10140,
        ),
        _row(
            142,
            "42.Liquidación de Tarjetas de Crédito",
            1,
            sd_isbanking=True,
            hacc_group=10142,
        ),
        _row(
            143,
            "43.Extracto Bancario (Resumen)",
            -1,
            sd_isbanking=True,
            hacc_group=10140,
        ),
        _row(
            144,
            "44.Extracto Bancario (Resumen) No Usar !!",
            1,
            sd_isbanking=True,
            hacc_group=10140,
        ),
        # AMBIGUO: revisar — "Producción de Equipos" (145). NO es banking
        # pese al rango cercano; es producción/stock. Marcamos sin flags.
        _row(
            145,
            "Producción de Equipos",
            1,
        ),
        # ─────────────────────────────────────────────────────────────────
        # COMPRAS ANULADAS (151-156)
        # ─────────────────────────────────────────────────────────────────
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
        _row(
            152,
            "Remito Anulado",
            1,
            sd_ispurchase=True,
            sd_ispackinglist=True,
            sd_isannulment=True,
        ),
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
        # ─────────────────────────────────────────────────────────────────
        # COMPRAS CONTRAPARTES (161-166)
        # Contraparte = asiento contable cruzado del sd_id N (N = 101+60, etc.)
        # ─────────────────────────────────────────────────────────────────
        # Contraparte — asiento contable cruzado del sd_id 101 (Factura)
        _row(
            161,
            "Factura Anulada - Contraparte",
            -1,
            sd_ispurchase=True,
            sd_istaxable=True,
            sd_isinbalance=True,
            hacc_group=10011,
        ),
        # Contraparte — asiento contable cruzado del sd_id 102 (Remito)
        _row(
            162,
            "Remito Anulado - Contraparte",
            -1,
            sd_ispurchase=True,
            sd_ispackinglist=True,
            sd_isinbalance=True,
        ),
        # Contraparte — asiento contable cruzado del sd_id 103 (NC)
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
        # Contraparte — asiento contable cruzado del sd_id 104 (ND)
        _row(
            164,
            "Nota de Débito Anulada - Contraparte",
            -1,
            sd_ispurchase=True,
            sd_isdebitnote=True,
            sd_istaxable=True,
            sd_isinbalance=True,
        ),
        # Contraparte — asiento contable cruzado del sd_id 106 (OP)
        _row(
            166,
            "Orden de Pago - Contraparte",
            1,
            sd_ispurchase=True,
            sd_isreceipt=True,
            sd_isinbalance=True,
            hacc_group=10012,
        ),
        # ─────────────────────────────────────────────────────────────────
        # DESPACHOS ANULADOS / CONTRAPARTES (180, 190)
        # ─────────────────────────────────────────────────────────────────
        _row(
            180,
            "Despacho Importación/Exportación - Anulado",
            1,
            sd_ispurchase=True,
            sd_isinbalance=True,
            sd_isannulment=True,
        ),
        # Contraparte — asiento contable cruzado del sd_id 130 (Despacho)
        _row(
            190,
            "Despacho Importación/Exportación - Contraparte",
            -1,
            sd_ispurchase=True,
            sd_isinbalance=True,
        ),
        # ─────────────────────────────────────────────────────────────────
        # BANKING 200-206 — sd_isbanking=true, NO isinbalance
        # ─────────────────────────────────────────────────────────────────
        _row(
            200,
            "Deposito Bancario de Valores",
            1,
            sd_isbanking=True,
        ),
        _row(
            201,
            "Emisión de Cheques Propios",
            1,
            sd_isbanking=True,
        ),
        _row(
            202,
            "Depósito Bancario de Efectivo",
            1,
            sd_isbanking=True,
        ),
        _row(
            203,
            "Retiro de Efectivo de Caja",
            1,
            sd_isbanking=True,
        ),
        _row(
            204,
            "Retiro de Efectivo de Banco",
            1,
            sd_isbanking=True,
        ),
        # AMBIGUO: revisar — sd_id=205 "Retiro de Efectivo de Banco a Caja".
        # plusOrminus no pasado por usuario, fallback=1. Banking transfer.
        # TODO: verificar con ERP — plusOrminus no pasado por usuario
        _row(
            205,
            "Retiro de Efectivo de Banco a Caja",
            1,
            sd_isbanking=True,
        ),
        _row(
            206,
            "Control de Debito de Valores Propios",
            1,
            sd_isbanking=True,
        ),
        # ─────────────────────────────────────────────────────────────────
        # BANKING anulaciones / rechazos (250, 251)
        # ─────────────────────────────────────────────────────────────────
        _row(
            250,
            "Anulación de Depósito Bancario de Valores",
            -1,
            sd_isbanking=True,
            sd_isannulment=True,
        ),
        _row(
            251,
            "Rechazo de Valores",
            1,
            sd_isbanking=True,
        ),
        # ─────────────────────────────────────────────────────────────────
        # STOCK / RMA (300+) — NO isinbalance, ambos sales/purchase false
        # ─────────────────────────────────────────────────────────────────
        # AMBIGUO: revisar — RMA (Return Merchandise Authorization). Stock movement.
        _row(
            301,
            "RMA - Ingreso a Depósito",
            1,
        ),
        # AMBIGUO: revisar — RMA egreso.
        _row(
            302,
            "RMA - Egreso de Depósito",
            -1,
        ),
        # AMBIGUO: revisar — Ajustes manuales de stock (no CC).
        _row(
            350,
            "STOCK - Ajustes de Stock",
            1,
        ),
        # AMBIGUO: revisar — "Producción" (no pasado plusOrminus, fallback=1).
        # TODO: verificar con ERP — plusOrminus no pasado por usuario
        _row(
            500,
            "Producción",
            1,
        ),
    ]

    # Sanidad: la lista de sd_id insertados debe coincidir con _SEEDED_SD_IDS
    # (falla rápido si se agrega una fila y se olvida actualizar la tupla).
    seeded_ids = tuple(r["sd_id"] for r in rows)
    assert seeded_ids == _SEEDED_SD_IDS, (
        f"Mismatch entre filas insertadas y _SEEDED_SD_IDS. "
        f"Actualizá la tupla. Faltantes/sobrantes: "
        f"{set(seeded_ids) ^ set(_SEEDED_SD_IDS)}"
    )

    op.bulk_insert(tb_sale_document, rows)


def downgrade() -> None:
    # Borra exactamente las 43 filas insertadas en upgrade(). No toca otras
    # si alguien agregó filas manualmente (improbable — tabla es seed only).
    conn = op.get_bind()
    conn.execute(
        sa.text("DELETE FROM tb_sale_document WHERE sd_id = ANY(:ids)"),
        {"ids": list(_SEEDED_SD_IDS)},
    )


# Timestamp de generación (para debugging, no se persiste)
_GENERATED_AT: str = datetime(2026, 4, 17).isoformat()
