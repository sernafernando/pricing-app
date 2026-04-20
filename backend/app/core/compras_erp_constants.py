"""
Constantes ERP para el módulo de compras.

Este módulo concentra las ÚNICAS excepciones al principio "no números mágicos
de sd_id en código" — valores explícitos del ERP que deben buscarse por su ID
para alguna lógica específica (no clasificable vía flags booleanos).

Regla: si aparece un nuevo valor del ERP que se quiere "hardcodear", debe
moverse a este archivo con justificación documentada o — preferentemente —
clasificarse vía flags de `tb_sale_document` en `sale_document_classifier.py`.
"""

from typing import Final

# sd_id del ERP para documento "Orden de Pago" — ÚNICA excepción al
# "no números mágicos".
#
# Justificación: se necesita buscar específicamente este tipo en
# `tb_commercial_transactions` para la lógica anti-doble-contabilización
# (design §7.1 / REQ-OP-005). Al crear una OP propia, chequeamos si ya
# existe una OP con sd_id=106 en el ERP para esa factura/proveedor en los
# últimos 7 días — si hay match → HTTP 409 POSIBLE_DUPLICADO_OP_ERP.
#
# No se puede clasificar vía flags porque `sd_isreceipt=true` matchea
# otros tipos (recibos de cobranza de ventas), y queremos filtrar SOLO
# la OP de compras específicamente.
ERP_SD_ID_ORDEN_PAGO: Final[int] = 106
