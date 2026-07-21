import requests
from lxml import html
from sqlalchemy.orm import Session
from datetime import date
from app.models.tipo_cambio import TipoCambio


def actualizar_tipo_cambio_bna(db: Session) -> dict:
    """Obtiene tipo de cambio USD BILLETE (venta) desde BNA.

    Fuente: tabla "Billetes" de https://www.bna.com.ar/Personas (tab id=billetes).
    NO usar la tabla "Divisas / Mercado Libre de Cambios" de la misma página:
    esa es otra cotización (menor, con fecha de último cierre) y no es la que
    alimenta el pricing. Se ancla la fila por el texto "Dolar U.S.A" tomando la
    primera coincidencia en orden de documento (= tabla Billetes del día).
    """
    try:
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

        hoy = date.today()
        tc = db.query(TipoCambio).filter(TipoCambio.moneda == "USD", TipoCambio.fecha == hoy).first()

        if tc:
            tc.compra = compra
            tc.venta = venta
        else:
            tc = TipoCambio(moneda="USD", fecha=hoy, compra=compra, venta=venta)
            db.add(tc)

        db.commit()
        return {"status": "success", "compra": compra, "venta": venta, "fuente": "BNA"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
