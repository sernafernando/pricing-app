import gspread
from google.oauth2.service_account import Credentials
from sqlalchemy.orm import Session
from typing import Dict, List
from datetime import datetime
from app.core.config import settings
from app.models.oferta_ml import OfertaML
from app.models.publicacion_ml import PublicacionML

SCOPES = ['https://www.googleapis.com/auth/spreadsheets.readonly']
WORKSHEET_GID = 1669753772

def parse_fecha(fecha_str: str):
    try:
        return datetime.strptime(fecha_str.strip(), "%d/%m/%Y").date()
    except:
        return None

def parse_numero(num_str: str):
    try:
        # Remover símbolos de moneda, espacios y %
        num_str = num_str.replace('$', '').replace(' ', '').replace('%', '')
        # Reemplazar punto como separador de miles y coma como decimal
        num_str = num_str.replace('.', '').replace(',', '.')
        return float(num_str) if num_str else None
    except:
        return None

def obtener_datos_sheets() -> List[Dict]:
    try:
        creds = Credentials.from_service_account_file(settings.GOOGLE_SERVICE_ACCOUNT_FILE, scopes=SCOPES)
        client = gspread.authorize(creds)
        spreadsheet = client.open_by_key(settings.GOOGLE_SHEETS_ID)
        
        worksheet = None
        for sheet in spreadsheet.worksheets():
            if sheet.id == WORKSHEET_GID:
                worksheet = sheet
                break
        
        if not worksheet:
            raise Exception(f"No se encontró la hoja con gid {WORKSHEET_GID}")
        
        all_values = worksheet.get_all_values()
        if not all_values or len(all_values) < 4:
            return []
        
        headers = all_values[2]
        clean_headers = []
        seen = {}
        
        for i, h in enumerate(headers):
            h = h.strip()
            if not h:
                h = f"columna_{i}"
            if h in seen:
                seen[h] += 1
                h = f"{h}_{seen[h]}"
            else:
                seen[h] = 0
            clean_headers.append(h)
        
        data = []
        for row in all_values[3:]:
            row_dict = {}
            for i, value in enumerate(row):
                if i < len(clean_headers):
                    row_dict[clean_headers[i]] = value
            data.append(row_dict)
        return data
    except Exception:
        raise

def sincronizar_ofertas_sheets(db: Session) -> Dict:
    try:
        data = obtener_datos_sheets()
        if not data:
            return {"status": "error", "message": "No se obtuvieron datos"}
        
        nuevas = 0
        actualizadas = 0
        ignoradas = 0
        errores = []
        
        for row in data:
            try:
                mla = row.get('MLA', '').strip()
                if not mla:
                    ignoradas += 1
                    continue
                
                pub = db.query(PublicacionML).filter(PublicacionML.mla == mla).first()
                if not pub:
                    ignoradas += 1
                    continue
                
                fecha_desde = parse_fecha(row.get('DESDE', ''))
                fecha_hasta = parse_fecha(row.get('HASTA', ''))
                
                if not fecha_desde or not fecha_hasta:
                    ignoradas += 1
                    continue
                
                precio_final = parse_numero(row.get('PRECIO FINAL', '0'))
                aporte_meli = parse_numero(row.get('$ APORTE MELI', '0'))
                aporte_pct = parse_numero(row.get('%', '0'))
                pvp_seller = parse_numero(row.get('PVP SELLER\n(Min 5% de dto)', '0'))
                
                oferta = db.query(OfertaML).filter(
                    OfertaML.mla == mla,
                    OfertaML.fecha_desde == fecha_desde,
                    OfertaML.fecha_hasta == fecha_hasta
                ).first()
                
                if oferta:
                    oferta.precio_final = precio_final
                    oferta.aporte_meli_pesos = aporte_meli
                    oferta.aporte_meli_porcentaje = aporte_pct
                    oferta.pvp_seller = pvp_seller
                    actualizadas += 1
                else:
                    oferta = OfertaML(
                        mla=mla,
                        fecha_desde=fecha_desde,
                        fecha_hasta=fecha_hasta,
                        precio_final=precio_final,
                        aporte_meli_pesos=aporte_meli,
                        aporte_meli_porcentaje=aporte_pct,
                        pvp_seller=pvp_seller
                    )
                    db.add(oferta)
                    nuevas += 1
            except Exception as e:
                errores.append(f"MLA {row.get('MLA')}: {str(e)}")
        
        db.commit()
        return {
            "status": "success",
            "nuevas": nuevas,
            "actualizadas": actualizadas,
            "ignoradas": ignoradas,
            "total": nuevas + actualizadas,
            "errores": errores[:10]
        }
    except Exception as e:
        db.rollback()
        return {"status": "error", "message": str(e)}
