import logging

import requests
from sqlalchemy.orm import Session
from datetime import date
from app.models.tipo_cambio import TipoCambio
from app.services.sell_out import queue as sell_out_queue

logger = logging.getLogger(__name__)


def actualizar_tipo_cambio_bna(db: Session) -> dict:
    """Obtiene tipo de cambio USD BILLETE (venta) desde BNA.

    Fuente: tabla "Billetes" de https://www.bna.com.ar/Personas (tab id=billetes).
    NO usar la tabla "Divisas / Mercado Libre de Cambios" de la misma página:
    esa es otra cotización (menor, con fecha de último cierre) y no es la que
    alimenta el pricing. Se ancla la fila por el texto "Dolar U.S.A" tomando la
    primera coincidencia en orden de documento (= tabla Billetes del día).
    """
    try:
        from lxml import html  # imported here: not in requirements, and only the scrape needs it

        # El BNA carga las cotizaciones vía POST al tab de billetes y exige
        # User-Agent (un GET plano devuelve un HTML sin las tablas).
        url = "https://www.bna.com.ar/Personas?id=billetes"
        headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}
        response = requests.post(url, timeout=10, headers=headers)
        tree = html.fromstring(response.content)

        # Primera fila "Dolar U.S.A" en el documento = tabla Billetes (compra, venta).
        filas = tree.xpath("//tr[td[contains(normalize-space(.), 'Dolar U.S.A')]]")
        if not filas:
            return {"status": "error", "message": "No se encontraron valores en BNA"}

        celdas = [c.strip() for c in filas[0].xpath("./td//text()") if c.strip()]
        if len(celdas) < 3:
            return {"status": "error", "message": "Fila de dólar incompleta en BNA"}

        # Limpiar y convertir: 1450,00 -> 1450.0
        compra = float(celdas[1].replace(".", "").replace(",", "."))
        venta = float(celdas[2].replace(".", "").replace(",", "."))

        if compra == 0 or venta == 0:
            return {"status": "error", "message": "Valores inválidos"}

        guardar_cotizacion_bna(db, compra, venta)
        return {"status": "success", "compra": compra, "venta": venta, "fuente": "BNA"}
    except Exception as e:
        # Session contract: callers pass a dedicated session with nothing pending (sync endpoint, sync scripts),
        # so rolling back discards only this update and never leaves the session in a failed transaction.
        db.rollback()
        return {"status": "error", "message": str(e)}


def guardar_cotizacion_bna(db: Session, compra: float, venta: float) -> None:
    """Guarda la cotización USD de hoy y, si `venta` cambió, encola en la misma transacción las
    campañas de sell out que se mueven con el BNA (`sell_out.queue.enqueue_por_bna`), en un savepoint:
    si encolar falla se loguea y la cotización se guarda igual. Commitea."""
    hoy = date.today()
    tc = db.query(TipoCambio).filter(TipoCambio.moneda == "USD", TipoCambio.fecha == hoy).first()
    cambio = tc is None or float(tc.venta or 0) != venta
    if tc:
        tc.compra = compra
        tc.venta = venta
    else:
        db.add(TipoCambio(moneda="USD", fecha=hoy, compra=compra, venta=venta))
    if cambio:
        db.flush()
        try:
            with db.begin_nested():  # the rate is stored even if queueing fails
                sell_out_queue.enqueue_por_bna(db, hoy)
        except Exception:
            logger.exception("BNA: no se pudieron encolar las campañas de sell-out; el tipo de cambio se guarda igual")
    db.commit()
