"""Sell in incident 2026-11-24, S1: a % cost bonus's generado/usado is read in the currency of the costo SI steps it
got (the product's cost currency, L18), one amount per currency, never converted to the line's stored `moneda`.

Owner, "TP loyalty 18.18M ARS must read USD 11,648"; L35: "encima están mostrando los costos en dólares en pesos además
de todo, cuando dijimos que los muestren en dólares." A % has no currency: a USD tactical's uncapped % line is stored
ARS by design (`tacticals.moneda_de_costo`), and that stays. A per-unit amount and a money cap keep counting in the
line's own currency. Built from the prod rows of bono 98 (TPLINK LOYALTY, tactical 62) read on 2026-11-24.
Postgres test database (`_pg_app`): `costo_si.generado` is Postgres-only SQL.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func

from app.models.costo_si import CostoSiFacturaTc, CostoSiPaso
from app.models.producto import ProductoERP, TipoMoneda
from app.models.sell_in import SellInBonoMarca, SellInCompra, SellInCompraItem
from tests.routers._pg_app import engine  # noqa: F401 - the fixture, by name
from tests.services._aprobacion import aprobar_siempre  # noqa: F401 - the fixture, by name

pytestmark = [pytest.mark.postgres, pytest.mark.usefixtures("aprobar_siempre")]

TACTICALS = "/api/tacticals"
BONOS = "/api/sell-in/bonos"
TPLINK = "TP-LINK"

# Every costo SI purchase step bono 98 got in prod (2026-11-24, read only): (item_id, fecha, ct_transaction, cantidad,
# costo_neto_usd, the invoice's rate). All 3.6 %, all `moneda` USD (TP-LINK products cost in USD), all on ARS invoices.
# Sum of cantidad x costo x 3.6 %: USD 11,648.078540280 over 11,954 units; at each invoice's rate ARS 18,183,306.16.
PASOS_BONO_98 = [
    (72, "2026-10-09", 915727, 60, "29.29505", "1535"),
    (1519, "2026-10-09", 917466, 10, "175.33928", "1535"),
    (1530, "2026-10-09", 915727, 80, "6.56949", "1535"),
    (1986, "2026-10-09", 915727, 120, "8.89557", "1535"),
    (2102, "2026-10-09", 915727, 30, "16.30206", "1535"),
    (2741, "2026-10-09", 915727, 30, "26.45313", "1535"),
    (2744, "2026-10-09", 915727, 50, "25.83025", "1535"),
    (4082, "2026-10-09", 917466, 50, "21.03831", "1535"),
    (4347, "2026-10-09", 915727, 10, "19.79605", "1535"),
    (4348, "2026-10-09", 917466, 100, "35.06384", "1535"),
    (4352, "2026-10-09", 917466, 70, "39.22736", "1535"),
    (4355, "2026-10-09", 917466, 80, "55.15909", "1535"),
    (4401, "2026-10-09", 917466, 20, "30.63948", "1535"),
    (4442, "2026-10-09", 917466, 12, "116.89954", "1535"),
    (2265, "2026-10-14", 917353, 30, "19.81000", "1535"),
    (23, "2026-10-15", 919426, 1000, "14.02569", "1530"),
    (32, "2026-10-15", 919426, 50, "7.94588", "1530"),
    (70, "2026-10-15", 919426, 100, "16.33320", "1530"),
    (306, "2026-10-15", 919427, 100, "8.18667", "1530"),
    (308, "2026-10-15", 919428, 20, "9.55847", "1530"),
    (619, "2026-10-15", 919427, 60, "70.13846", "1530"),
    (629, "2026-10-15", 919427, 100, "5.25712", "1530"),
    (1121, "2026-10-15", 919427, 20, "100.52745", "1530"),
    (1123, "2026-10-15", 919427, 100, "37.41186", "1530"),
    (1126, "2026-10-15", 919426, 20, "93.51461", "1530"),
    (1169, "2026-10-15", 919428, 15, "46.10496", "1530"),
    (1249, "2026-10-15", 919426, 150, "26.96784", "1530"),
    (1618, "2026-10-15", 919428, 40, "12.65209", "1530"),
    (1969, "2026-10-15", 919427, 100, "9.35046", "1530"),
    (1970, "2026-10-15", 919427, 45, "20.45663", "1530"),
    (1976, "2026-10-15", 919428, 4, "49.28208", "1530"),
    (1986, "2026-10-15", 919427, 50, "9.35046", "1530"),
    (2068, "2026-10-15", 919427, 65, "61.82338", "1530"),
    (2103, "2026-10-15", 919426, 30, "18.03580", "1530"),
    (2262, "2026-10-15", 919427, 40, "14.78980", "1530"),
    (2267, "2026-10-15", 919427, 15, "95.85222", "1530"),
    (2320, "2026-10-15", 919426, 30, "13.09265", "1530"),
    (2666, "2026-10-15", 919428, 10, "48.53164", "1530"),
    (4252, "2026-10-15", 919426, 10, "9.54072", "1530"),
    (4276, "2026-10-15", 919427, 20, "27.89085", "1530"),
    (4277, "2026-10-15", 919428, 12, "11.05939", "1530"),
    (4350, "2026-10-15", 919426, 30, "176.42369", "1530"),
    (4827, "2026-10-15", 919426, 10, "19.79448", "1530"),
    (70, "2026-10-22", 931321, 200, "17.10000", "1550"),
    (317, "2026-10-22", 931321, 30, "32.62000", "1550"),
    (455, "2026-10-22", 931321, 100, "4.66000", "1550"),
    (489, "2026-10-22", 931321, 50, "133.99000", "1550"),
    (674, "2026-10-22", 931321, 40, "69.91000", "1550"),
    (792, "2026-10-22", 931321, 10, "69.91000", "1550"),
    (1972, "2026-10-22", 931321, 20, "192.25000", "1550"),
    (1973, "2026-10-22", 931321, 10, "291.29000", "1550"),
    (1986, "2026-10-22", 931321, 150, "9.32000", "1550"),
    (2267, "2026-10-22", 931321, 30, "95.54000", "1550"),
    (3077, "2026-10-22", 931321, 20, "17.10000", "1550"),
    (3078, "2026-10-22", 931321, 20, "40.32000", "1550"),
    (4045, "2026-10-22", 931321, 120, "41.95000", "1550"),
    (4086, "2026-10-22", 931321, 10, "28.10000", "1550"),
    (4350, "2026-10-22", 931321, 12, "233.03000", "1550"),
    (4351, "2026-10-22", 931321, 9, "54.98000", "1550"),
    (4397, "2026-10-22", 931321, 6, "157.30000", "1550"),
    (4399, "2026-10-22", 931321, 4, "15.71000", "1550"),
    (4400, "2026-10-22", 931321, 4, "17.18000", "1550"),
    (4514, "2026-10-22", 931321, 30, "26.88000", "1550"),
    (4862, "2026-10-22", 931321, 10, "61.09000", "1550"),
    (22, "2026-10-27", 935025, 200, "16.96401", "1560"),
    (24, "2026-10-27", 935065, 21, "5.94904", "1560"),
    (336, "2026-10-27", 935065, 3, "7.14274", "1560"),
    (1121, "2026-10-27", 935025, 70, "97.04808", "1560"),
    (1123, "2026-10-27", 935025, 40, "36.18923", "1560"),
    (1522, "2026-10-27", 935065, 10, "57.12250", "1560"),
    (1525, "2026-10-27", 935065, 4, "214.19481", "1560"),
    (1969, "2026-10-27", 935025, 50, "9.04488", "1560"),
    (2038, "2026-10-27", 935065, 22, "19.04083", "1560"),
    (4280, "2026-10-27", 935065, 6, "30.67690", "1560"),
    (4871, "2026-10-27", 935065, 6, "30.67690", "1560"),
    (71, "2026-10-29", 937717, 40, "25.69150", "1560"),
    (455, "2026-10-29", 937717, 200, "4.66060", "1560"),
    (534, "2026-10-29", 937717, 36, "46.60600", "1560"),
    (1249, "2026-10-29", 937717, 50, "26.91500", "1560"),
    (2265, "2026-10-29", 937717, 10, "19.80760", "1560"),
    (2539, "2026-10-29", 937717, 50, "5.82580", "1560"),
    (2890, "2026-10-29", 937717, 20, "11.65150", "1560"),
    (4893, "2026-10-29", 937717, 5, "13.86530", "1560"),
    (70, "2026-11-06", 944607, 200, "16.51590", "1570"),
    (70, "2026-11-06", 944606, 250, "16.51590", "1570"),
    (454, "2026-11-06", 944606, 20, "25.63330", "1570"),
    (455, "2026-11-06", 944607, 800, "4.66060", "1570"),
    (485, "2026-11-06", 944582, 30, "31.64000", "1570"),
    (627, "2026-11-06", 944607, 30, "9.64750", "1570"),
    (674, "2026-11-06", 944582, 20, "69.91000", "1570"),
    (887, "2026-11-06", 944582, 30, "5.93000", "1570"),
    (1125, "2026-11-06", 944582, 10, "159.63000", "1570"),
    (1127, "2026-11-06", 944582, 10, "233.03000", "1570"),
    (1249, "2026-11-06", 944606, 200, "26.91500", "1570"),
    (1815, "2026-11-06", 944582, 30, "23.30000", "1570"),
    (1818, "2026-11-06", 944582, 10, "116.52000", "1570"),
    (1970, "2026-11-06", 944582, 150, "20.39000", "1570"),
    (1971, "2026-11-06", 944582, 20, "99.04000", "1570"),
    (2029, "2026-11-06", 944582, 10, "6.99000", "1570"),
    (2064, "2026-11-06", 944607, 30, "72.23940", "1570"),
    (2103, "2026-11-06", 944582, 50, "18.33000", "1570"),
    (2103, "2026-11-06", 944607, 113, "17.73930", "1570"),
    (2320, "2026-11-06", 944607, 30, "12.86330", "1570"),
    (2737, "2026-11-06", 944582, 50, "36.65000", "1570"),
    (3011, "2026-11-06", 944582, 30, "23.21000", "1570"),
    (3077, "2026-11-06", 944607, 82, "16.51590", "1570"),
    (3078, "2026-11-06", 944582, 20, "40.32000", "1570"),
    (3654, "2026-11-06", 944582, 20, "54.98000", "1570"),
    (4086, "2026-11-06", 944582, 20, "28.10000", "1570"),
    (4400, "2026-11-06", 944582, 3, "17.18000", "1570"),
    (4401, "2026-11-06", 944582, 1, "30.54000", "1570"),
    (4583, "2026-11-06", 944582, 20, "32.99000", "1570"),
    (4862, "2026-11-06", 944582, 14, "61.09000", "1570"),
    (4953, "2026-11-06", 944582, 9, "17.48000", "1570"),
    (4955, "2026-11-06", 944582, 10, "54.76000", "1570"),
    (4956, "2026-11-06", 944582, 10, "42.76000", "1570"),
    (30, "2026-11-10", 944440, 300, "12.78389", "1570"),
    (70, "2026-11-10", 943885, 300, "16.03980", "1570"),
    (71, "2026-11-10", 943885, 100, "25.66000", "1570"),
    (306, "2026-11-10", 943885, 150, "8.16000", "1570"),
    (317, "2026-11-10", 943885, 150, "32.62000", "1570"),
    (328, "2026-11-10", 944440, 100, "50.21389", "1570"),
    (454, "2026-11-10", 944440, 75, "25.62936", "1570"),
    (489, "2026-11-10", 943885, 30, "123.80900", "1570"),
    (619, "2026-11-10", 944440, 100, "71.18389", "1570"),
    (628, "2026-11-10", 943885, 150, "10.49000", "1570"),
    (792, "2026-11-10", 943885, 50, "64.62871", "1570"),
    (793, "2026-11-10", 943885, 30, "179.11911", "1570"),
    (901, "2026-11-10", 944440, 50, "23.56688", "1570"),
    (1121, "2026-11-10", 944440, 60, "101.47389", "1570"),
    (1122, "2026-11-10", 944440, 60, "72.34389", "1570"),
    (1123, "2026-11-10", 944440, 60, "38.62758", "1570"),
    (1126, "2026-11-10", 943885, 20, "93.21000", "1570"),
    (1249, "2026-11-10", 943885, 250, "26.88000", "1570"),
    (1986, "2026-11-10", 943885, 60, "9.32000", "1570"),
    (2063, "2026-11-10", 944440, 40, "55.81210", "1570"),
    (2103, "2026-11-10", 944440, 150, "19.60389", "1570"),
    (2262, "2026-11-10", 944440, 30, "15.44226", "1570"),
    (2737, "2026-11-10", 943885, 60, "36.65000", "1570"),
    (3077, "2026-11-10", 944440, 120, "17.43859", "1570"),
    (4276, "2026-11-10", 943885, 10, "30.77134", "1570"),
    (887, "2026-11-16", 944984, 11, "6.73944", "1570"),
    (4277, "2026-11-16", 944984, 6, "11.56113", "1570"),
    (22, "2026-11-18", 950137, 200, "16.99804", "1580"),
    (1121, "2026-11-18", 950137, 70, "97.68987", "1580"),
    (1123, "2026-11-18", 950137, 40, "36.14525", "1580"),
    (1969, "2026-11-18", 950137, 95, "9.08516", "1580"),
    (23, "2026-11-19", 950142, 200, "13.50175", "1585"),
    (71, "2026-11-19", 950142, 50, "25.01047", "1585"),
    (319, "2026-11-19", 950142, 50, "13.54083", "1585"),
    (792, "2026-11-19", 950142, 24, "67.89953", "1585"),
    (1249, "2026-11-19", 950141, 55, "26.08514", "1585"),
    (1249, "2026-11-19", 950142, 100, "26.08514", "1585"),
    (1513, "2026-11-19", 950142, 150, "13.57991", "1585"),
    (1986, "2026-11-19", 950142, 100, "9.10538", "1585"),
    (2297, "2026-11-19", 950142, 200, "27.35521", "1585"),
    (2539, "2026-11-19", 950141, 20, "5.69575", "1585"),
    (2539, "2026-11-19", 950142, 200, "5.64690", "1585"),
    (2739, "2026-11-19", 950142, 115, "20.31124", "1585"),
    (2740, "2026-11-19", 950142, 100, "26.08514", "1585"),
    (3077, "2026-11-19", 950142, 50, "16.49128", "1585"),
    (4202, "2026-11-19", 950144, 12, "222.39000", "1580"),
    (4348, "2026-11-19", 950142, 100, "33.85207", "1585"),
    (4726, "2026-11-19", 950144, 28, "400.91000", "1580"),
    (4956, "2026-11-19", 950144, 10, "50.11000", "1580"),
    (1249, "2026-11-20", 952991, 250, "26.88000", "1585"),
    (2029, "2026-11-20", 952991, 25, "6.99000", "1585"),
    (4094, "2026-11-20", 952025, 15, "44.86270", "1595"),
    (4098, "2026-11-20", 952991, 30, "24.47000", "1585"),
    (4353, "2026-11-20", 952991, 30, "19.14000", "1585"),
    (4482, "2026-11-20", 952991, 20, "48.87000", "1585"),
    (4563, "2026-11-20", 952991, 20, "42.76000", "1585"),
    (4584, "2026-11-20", 952991, 15, "69.91000", "1585"),
]


@pytest.fixture()
def productos(db):
    rows = [
        ProductoERP(item_id=1986, codigo="TL-1986", descripcion="Router TP", marca=TPLINK, costo=8.9),
        ProductoERP(item_id=7001, codigo="TL-ARS", descripcion="Cable TP en pesos", marca=TPLINK, costo=26856.9),
        ProductoERP(item_id=3020, codigo="XRX-3020", descripcion="Xerox 3020", marca="XEROX", costo=120.0),
    ]
    for row in rows:
        row.moneda_costo = TipoMoneda.ARS if row.item_id == 7001 else TipoMoneda.USD
    db.add_all(rows)
    db.flush()


@pytest.fixture()
def sell_in(rol_admin, admin_auth_headers, grant_permiso):
    for permiso in ("sell_in.ver", "sell_in.gestionar", "sell_out.ver"):
        grant_permiso(rol_admin, permiso)
    return admin_auth_headers


def _loyalty(client, headers, **linea) -> dict:
    """Tactical 62 as loaded in prod: USD, rate of the sale's day, TP-LINK, one uncapped 3.6 % line on the brand."""
    body = {
        "tipo": "sell_in",
        "nombre": "TPLINK LOYALTY",
        "marca": TPLINK,
        "fecha_desde": "2026-10-01",
        "fecha_hasta": "2026-12-31",
        "moneda": "USD",
        "tc_modo": "dia_venta",
        "lineas": [{"alcance": "marca", "marca": TPLINK, "modo_monto": "porcentaje", "valor": "3.6", **linea}],
    }
    resp = client.post(TACTICALS, json=body, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _bono(db, tactical_id: int) -> SellInBonoMarca:
    return db.query(SellInBonoMarca).filter(SellInBonoMarca.tactical_id == tactical_id).one()


def _pasos(db, ref: tuple[str, int], filas, pct: str = "3.6000", moneda: str = "USD") -> None:
    """Costo SI purchase steps that got the sell in `ref` at `pct`, each invoice's rate stored where costo SI and its
    caps read it (`costo_si_factura_tc`)."""
    orden = dict(db.query(CostoSiPaso.item_id, func.max(CostoSiPaso.orden)).group_by(CostoSiPaso.item_id).all())
    tasas = {t.ct_transaction for t in db.query(CostoSiFacturaTc)}
    for item_id, fecha, ct, cantidad, costo, tc in filas:
        orden[item_id] = orden.get(item_id, 0) + 1
        if ct not in tasas:
            db.add(CostoSiFacturaTc(ct_transaction=ct, tipo_cambio=Decimal(tc)))
            tasas.add(ct)
        db.add(
            CostoSiPaso(
                item_id=item_id,
                orden=orden[item_id],
                tipo="compra",
                fecha=date.fromisoformat(fecha),
                ct_transaction=ct,
                cantidad=cantidad,
                costo_neto_usd=Decimal(costo),
                sell_ins=[{"origen": ref[0], "ref": ref[1], "porcentaje": pct}],
                stock_antes=0,
                stock_base=0,
                stock_despues=cantidad,
                tipo_cambio=Decimal(tc),
                moneda=moneda,
            )
        )
    db.flush()


def _linea(client, headers, tactical_id: int) -> dict:
    [linea] = client.get(f"{TACTICALS}/{tactical_id}", headers=headers).json()["lineas"]
    return linea


def _kpis(client, headers) -> dict:
    return client.get(TACTICALS, params={"tipo": "sell_in"}, headers=headers).json()["kpis"]


def _listado(client, headers, bono_id: int) -> dict:
    [fila] = [f for f in client.get(BONOS, headers=headers).json()["items"] if f["id"] == bono_id]
    return fila


def _monto(moneda: str, monto: str) -> dict:
    return {"moneda": moneda, "monto": monto, "tope": None, "tope_parcial": False, "estimado": False}


def test_a_usd_tactical_s_percentage_line_reads_what_it_took_in_usd(client, db, productos, sell_in) -> None:
    """S1: three real bono 98 steps, USD products on ARS invoices: what it took is USD, not ARS at each rate."""
    tactical = _loyalty(client, sell_in)
    bono = _bono(db, tactical["id"])
    assert bono.moneda == "ARS"  # stored as it is (`moneda_de_costo`): no data change
    # 120 x 8.89557 x 3.6 % = 38.4288624; 60 x 29.29505 x 3.6 % = 63.276308; 10 x 175.33928 x 3.6 % = 63.1221408.
    tres = {(1986, "2026-10-09"), (72, "2026-10-09"), (1519, "2026-10-09")}
    _pasos(db, ("bono", bono.id), [r for r in PASOS_BONO_98 if (r[0], r[1]) in tres])

    linea = _linea(client, sell_in, tactical["id"])
    fila = _listado(client, sell_in, bono.id)

    assert (linea["moneda"], linea["monto_usado"], linea["unidades_usadas"]) == ("USD", "164.83", 190)
    assert linea["montos_usados"] == [{"moneda": "USD", "monto": "164.83"}]
    assert _kpis(client, sell_in)["pendientes"]["montos"] == [_monto("USD", "164.83")]
    assert (fila["unidades"], fila["montos_generados"]) == (190, [{"moneda": "USD", "monto": "164.83"}])
    assert (fila["moneda"], fila["moneda_generado"], fila["monto_generado"]) == ("ARS", "USD", "164.83")


def test_bono_98_reads_usd_11_648_08_over_its_173_steps(client, db, productos, sell_in) -> None:
    """S1 acceptance: "TP loyalty 18.18M ARS must read USD 11,648" (bono 98 = USD 11,648.08, 173 steps, 11,954 u)."""
    tactical = _loyalty(client, sell_in)
    bono = _bono(db, tactical["id"])
    _pasos(db, ("bono", bono.id), PASOS_BONO_98)

    linea = _linea(client, sell_in, tactical["id"])
    fila = _listado(client, sell_in, bono.id)

    assert (linea["moneda"], linea["monto_usado"], linea["unidades_usadas"]) == ("USD", "11648.08", 11954)
    assert linea["montos_usados"] == [{"moneda": "USD", "monto": "11648.08"}]
    assert _kpis(client, sell_in)["pendientes"]["montos"] == [_monto("USD", "11648.08")]
    assert (fila["unidades"], fila["montos_generados"]) == (11954, [{"moneda": "USD", "monto": "11648.08"}])
    assert (fila["moneda_generado"], fila["monto_generado"]) == ("USD", "11648.08")
    assert client.get(f"{BONOS}/{bono.id}", headers=sell_in).json()["monto_generado"] == "11648.08"


def test_a_percentage_over_usd_and_ars_products_reports_one_amount_per_currency(client, db, productos, sell_in) -> None:
    """S1: steps of a USD and of an ARS product are never added into one converted sum."""
    tactical = _loyalty(client, sell_in)
    bono = _bono(db, tactical["id"])
    # USD: 120 x 8.89557 x 3.6 % = 38.4288624.
    _pasos(db, ("bono", bono.id), [(1986, "2026-10-09", 915727, 120, "8.89557", "1535")])
    # ARS (an ARS-cost product): 10 x 26,856.90 x 3.6 % = 9,668.484.
    _pasos(db, ("bono", bono.id), [(7001, "2026-11-18", 950137, 10, "26856.90", "1580")], moneda="ARS")

    linea = _linea(client, sell_in, tactical["id"])
    fila = _listado(client, sell_in, bono.id)

    assert linea["unidades_usadas"] == 130
    assert linea["montos_usados"] == [{"moneda": "ARS", "monto": "9668.48"}, {"moneda": "USD", "monto": "38.43"}]
    assert _kpis(client, sell_in)["pendientes"]["montos"] == [_monto("ARS", "9668.48"), _monto("USD", "38.43")]
    assert (fila["unidades"], fila["montos_generados"]) == (
        130,
        [{"moneda": "ARS", "monto": "9668.48"}, {"moneda": "USD", "monto": "38.43"}],
    )
    # Several currencies: `monto_generado` stays in the bonus's own, the rest is only listed.
    assert (fila["moneda_generado"], fila["monto_generado"]) == ("ARS", "9668.48")
    assert (linea["moneda"], linea["monto_usado"]) == ("ARS", "9668.48")


def test_an_invoice_bonus_with_one_purchase_in_its_invoice_s_currency_reads_in_it(
    client, db, productos, sell_in, admin_user
) -> None:
    """S1/S3: compras 25/26 (USD bonos 84/85, 2.5 %, base factura) are ARS purchases on ARS invoices. What the
    bonus generated is that ARS amount, not USD 0 with the ARS listed as left over from a currency change."""
    resp = client.post(
        BONOS,
        json={"marca": TPLINK, "tipo": "porcentaje", "porcentaje": "2.5", "moneda": "USD", "fecha_desde": "2026-10-01",
              "fecha_hasta": "2026-12-31", "descripcion": "DESC AIR TP"},
        headers=sell_in,
    )  # fmt: skip
    assert resp.status_code == 201, resp.text
    bono = resp.json()
    db.add(
        SellInCompra(
            fecha_compra=date(2026, 11, 3),
            moneda="ARS",
            monto_total=Decimal("393467.14"),
            tipo_cambio=Decimal("1570"),
            formula="proporcional",
            estado="activa",
            usuario_id=admin_user.id,
            origen="bono_marca",
            bono_id=bono["id"],
        )
    )
    db.flush()
    compra = db.query(SellInCompra).filter(SellInCompra.bono_id == bono["id"]).one()
    db.add(
        SellInCompraItem(
            compra_id=compra.id, item_id=1986, cantidad=1000, costo_base_unit=Decimal("15738.69"),
            monto_asignado=Decimal("393467.14"),
        )
    )  # fmt: skip
    db.flush()

    fila = client.get(f"{BONOS}/{bono['id']}", headers=sell_in).json()

    assert (fila["moneda"], fila["moneda_generado"], fila["monto_generado"]) == ("USD", "ARS", "393467.14")
    assert (fila["compras_activas"], fila["unidades"]) == (1, 1000)
    assert fila["montos_generados"] == [{"moneda": "ARS", "monto": "393467.14"}]


def test_a_usd_per_unit_line_still_counts_in_usd_converting_an_ars_step(client, db, productos, sell_in) -> None:
    """Kept (bono 99 shape, XEROX 3020 6.50 USD/u): a per-unit amount is in its line's currency, an ARS invoice's
    step converted at that invoice's rate, so a money cap keeps counting USD."""
    resp = client.post(
        TACTICALS,
        json={
            "tipo": "sell_in",
            "nombre": "XEROX 3020 remanente",
            "marca": "XEROX",
            "fecha_desde": "2026-11-01",
            "fecha_hasta": "2026-12-31",
            "moneda": "USD",
            "tc_modo": "dia_venta",
            "lineas": [{"alcance": "productos", "item_ids": [3020], "modo_monto": "por_unidad", "valor": "6.50"}],
        },
        headers=sell_in,
    )
    assert resp.status_code == 201, resp.text
    tactical = resp.json()
    bono = _bono(db, tactical["id"])
    assert bono.moneda == "USD"
    # 10 x USD 120 x 6.50 / 120 = USD 65; 2 x ARS 195,000 x 5 % = ARS 19,500 at 1,500 = USD 13.
    _pasos(db, ("bono", bono.id), [(3020, "2026-11-20", 951001, 10, "120.00", "1580")], pct="5.4166667")
    _pasos(db, ("bono", bono.id), [(3020, "2026-11-21", 951002, 2, "195000.00", "1500")], pct="5.0000", moneda="ARS")

    linea = _linea(client, sell_in, tactical["id"])
    fila = _listado(client, sell_in, bono.id)

    assert (linea["moneda"], linea["monto_usado"], linea["unidades_usadas"]) == ("USD", "78.00", 12)
    assert _kpis(client, sell_in)["pendientes"]["montos"] == [_monto("USD", "78.00")]
    assert (fila["moneda"], fila["unidades"], fila["monto_generado"]) == ("USD", 12, "78.00")
    assert fila["montos_generados"] == [{"moneda": "USD", "monto": "78.00"}]


def test_a_compras_sell_in_still_reads_in_its_own_currency(client, db, productos, sell_in, admin_user) -> None:
    """Kept: a Compras sell in (an invoice total) is in the purchase's currency, its USD steps at each invoice's rate.
    Compra 28 / item 22 in prod: 200 u x USD 16.99804 x 1 % = USD 33.99608, at 1,580 = ARS 53,713.81."""
    tactical = _loyalty(client, sell_in)
    compra = SellInCompra(
        fecha_compra=date(2026, 11, 18),
        moneda="ARS",
        monto_total=Decimal("53713.80"),
        formula="por_unidad",
        estado="activa",
        usuario_id=admin_user.id,
        origen="manual",
        tactical_id=tactical["id"],
        tactical_linea=2,
    )
    db.add(compra)
    db.flush()
    _pasos(db, ("compra", compra.id), [(1986, "2026-11-18", 950137, 200, "16.99804", "1580")], pct="1.0000")

    lineas = client.get(f"{TACTICALS}/{tactical['id']}", headers=sell_in).json()["lineas"]
    [linea] = [x for x in lineas if x["origen"] == "sell_in_compra"]

    assert (linea["moneda"], linea["monto_usado"], linea["unidades_usadas"]) == ("ARS", "53713.81", 200)
    # The bonus line (stored ARS, nothing used) is ARS too, uncapped: the total's cap covers only part of ARS.
    assert _kpis(client, sell_in)["pendientes"]["montos"] == [
        {**_monto("ARS", "53713.81"), "tope": "53713.80", "tope_parcial": True}
    ]


def test_a_usd_invoice_percentage_line_reads_its_purchase_in_the_invoice_s_currency(
    client, db, productos, sell_in, admin_user
) -> None:
    """S1/S3 seam (tactical 47 "DESC AIR TP", bono 84, 2.5 %): S3 stores a % bonus's purchase in its invoice's
    currency, so compra 25 is ARS 393,467.14 (470 u) on an ARS invoice. The tactical line reads it in ARS, as the Sell
    in list does, not "USD 0" with the ARS left out of the totals."""
    tactical = _loyalty(client, sell_in)
    factura = SellInBonoMarca(
        alcance="marca",
        marca=TPLINK,
        tipo="porcentaje",
        porcentaje=Decimal("2.5"),
        moneda="USD",
        base="factura",
        fecha_desde=date(2026, 10, 1),
        fecha_hasta=date(2026, 12, 31),
        descripcion="DESC AIR TP",
        estado="activa",
        usuario_id=admin_user.id,
        tactical_id=tactical["id"],
        tactical_linea=2,
    )
    db.add(factura)
    db.flush()
    compra = SellInCompra(
        fecha_compra=date(2026, 11, 3),
        moneda="ARS",
        monto_total=Decimal("393467.14"),
        formula="proporcional",
        estado="activa",
        usuario_id=admin_user.id,
        origen="bono_marca",
        bono_id=factura.id,
    )
    db.add(compra)
    db.flush()
    db.add(
        SellInCompraItem(
            compra_id=compra.id, item_id=1986, cantidad=470, costo_base_unit=Decimal("33484.80"),
            monto_asignado=Decimal("393467.14"),
        )
    )  # fmt: skip
    db.flush()

    lineas = client.get(f"{TACTICALS}/{tactical['id']}", headers=sell_in).json()["lineas"]
    [linea] = [x for x in lineas if x["id"] == factura.id]

    assert (linea["moneda"], linea["monto_usado"], linea["unidades_usadas"]) == ("ARS", "393467.14", 470)
    assert linea["montos_usados"] == [{"moneda": "ARS", "monto": "393467.14"}]
    # The cost line (stored ARS, nothing used yet) adds its ARS 0.
    assert _kpis(client, sell_in)["pendientes"]["montos"] == [_monto("ARS", "393467.14")]
