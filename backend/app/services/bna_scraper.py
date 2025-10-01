import httpx
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session
from app.models.tipo_cambio import TipoCambio
from datetime import date
from typing import Dict, Optional

async def scrapear_dolar_bna() -> Optional[Dict[str, float]]:
    """
    Scrapea la tabla de cotizaciones del BNA
    Retorna dict con compra/venta o None si falla
    """
    
    url = "https://www.bna.com.ar/Personas"
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Buscar la primera tabla
        tabla = soup.find('table')
        
        if not tabla:
            print("❌ No se encontró la tabla de cotizaciones")
            return None
        
        # Buscar la fila del Dólar U.S.A
        filas = tabla.find_all('tr')
        
        for fila in filas:
            celdas = fila.find_all('td')
            if len(celdas) >= 3:
                moneda = celdas[0].get_text(strip=True)
                
                if 'Dolar U.S.A' in moneda or 'Dólar U.S.A' in moneda:
                    try:
                        # Las cotizaciones vienen sin decimales ni separadores
                        # Ej: "1350" = $1.350,00
                        compra_text = celdas[1].get_text(strip=True)
                        venta_text = celdas[2].get_text(strip=True)
                        
                        # Limpiar y convertir
                        compra = float(compra_text.replace('.', '').replace(',', '.'))
                        venta = float(venta_text.replace('.', '').replace(',', '.'))
                        
                        return {
                            "compra": compra,
                            "venta": venta
                        }
                    except (ValueError, IndexError) as e:
                        print(f"❌ Error parseando valores: {e}")
                        return None
        
        print("❌ No se encontró la fila del Dólar U.S.A")
        return None
        
    except Exception as e:
        print(f"❌ Error scrapeando BNA: {e}")
        return None

async def actualizar_tipo_cambio(db: Session) -> Dict:
    """
    Scrapea el BNA y actualiza la base de datos
    """
    
    print(f"🔄 Scrapeando tipo de cambio del BNA...")
    
    cotizacion = await scrapear_dolar_bna()
    
    if not cotizacion:
        return {
            "status": "error",
            "message": "No se pudo obtener cotización del BNA"
        }
    
    # Verificar si ya existe registro para hoy
    hoy = date.today()
    tc_existente = db.query(TipoCambio).filter(
        TipoCambio.fecha == hoy,
        TipoCambio.moneda == "USD"
    ).first()
    
    if tc_existente:
        # Actualizar
        tc_existente.compra = cotizacion["compra"]
        tc_existente.venta = cotizacion["venta"]
        mensaje = "actualizado"
    else:
        # Crear nuevo
        nuevo_tc = TipoCambio(
            fecha=hoy,
            moneda="USD",
            compra=cotizacion["compra"],
            venta=cotizacion["venta"]
        )
        db.add(nuevo_tc)
        mensaje = "creado"
    
    db.commit()
    
    print(f"✅ Tipo de cambio {mensaje}: USD Compra ${cotizacion['compra']:.2f} / Venta ${cotizacion['venta']:.2f}")
    
    return {
        "status": "success",
        "message": mensaje,
        "fecha": hoy.isoformat(),
        "compra": cotizacion["compra"],
        "venta": cotizacion["venta"]
    }
