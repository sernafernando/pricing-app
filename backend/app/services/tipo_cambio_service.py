import requests
from lxml import html
from sqlalchemy.orm import Session
from datetime import date
from app.models.tipo_cambio import TipoCambio

def actualizar_tipo_cambio_bna(db: Session):
    """Obtiene tipo de cambio USD BILLETE desde BNA con XPATH"""
    try:
        url = "https://www.bna.com.ar/Personas"
        response = requests.get(url, timeout=10)
        tree = html.fromstring(response.content)
        
        # XPATH para compra y venta del dólar (primera fila de la tabla)
        compra_str = tree.xpath('/html/body/main/div/div/div[4]/div[1]/div/div/div[1]/table/tbody/tr[1]/td[2]/text()')
        venta_str = tree.xpath('/html/body/main/div/div/div[4]/div[1]/div/div/div[1]/table/tbody/tr[1]/td[3]/text()')
        
        if not compra_str or not venta_str:
            return {"status": "error", "message": "No se encontraron valores en BNA"}
        
        # Limpiar y convertir: 1435,00 -> 1435.0
        compra = float(compra_str[0].strip().replace('.', '').replace(',', '.'))
        venta = float(venta_str[0].strip().replace('.', '').replace(',', '.'))
        
        if compra == 0 or venta == 0:
            return {"status": "error", "message": "Valores inválidos"}
        
        hoy = date.today()
        tc = db.query(TipoCambio).filter(
            TipoCambio.moneda == "USD",
            TipoCambio.fecha == hoy
        ).first()
        
        if tc:
            tc.compra = compra
            tc.venta = venta
        else:
            tc = TipoCambio(
                moneda="USD",
                fecha=hoy,
                compra=compra,
                venta=venta
            )
            db.add(tc)
        
        db.commit()
        return {"status": "success", "compra": compra, "venta": venta, "fuente": "BNA"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
