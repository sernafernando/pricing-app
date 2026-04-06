from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.api.deps import get_current_user, get_admin_or_localhost
from app.models.usuario import Usuario
from app.services.erp_sync import sincronizar_erp
from app.services.ml_sync import sincronizar_publicaciones_ml
from app.services.google_sheets_sync import sincronizar_ofertas_sheets

router = APIRouter()


@router.post("/sync")
async def sync_erp(db: Session = Depends(get_db), current_user: Usuario = Depends(get_admin_or_localhost)):
    """Sincroniza productos desde el ERP y precios de ML"""
    try:
        # Sincronizar ERP
        print("=== Iniciando sincronización ERP ===")
        resultado_erp = await sincronizar_erp(db)

        # Sincronizar precios de MercadoLibre
        print("=== Iniciando sincronización de precios ML ===")
        from app.services.sync_precios_ml import sincronizar_precios_ml

        resultado_ml = sincronizar_precios_ml(db)

        return {"status": "success", "erp": resultado_erp, "precios_ml": resultado_ml}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.post("/sync-ml")
async def sincronizar_ml(db: Session = Depends(get_db), current_user: Usuario = Depends(get_admin_or_localhost)):
    """Sincroniza publicaciones de Mercado Libre"""
    try:
        resultado = await sincronizar_publicaciones_ml(db)
        return resultado
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.post("/sync-sheets")
async def sincronizar_sheets(db: Session = Depends(get_db), current_user: Usuario = Depends(get_admin_or_localhost)):
    """Sincroniza ofertas desde Google Sheets"""
    try:
        resultado = sincronizar_ofertas_sheets(db)
        return resultado
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.post("/sync-tipo-cambio")
async def sincronizar_tipo_cambio(
    db: Session = Depends(get_db), current_user: Usuario = Depends(get_admin_or_localhost)
):
    """Sincroniza tipo de cambio desde BNA"""
    try:
        from app.services.tipo_cambio_service import actualizar_tipo_cambio_bna

        resultado = actualizar_tipo_cambio_bna(db)
        return resultado
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/tipo-cambio/actual")
async def obtener_tipo_cambio_actual_endpoint(
    db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)
):
    """Obtiene el tipo de cambio más reciente"""
    from app.models.tipo_cambio import TipoCambio

    tc = db.query(TipoCambio).filter(TipoCambio.moneda == "USD").order_by(TipoCambio.fecha.desc()).first()

    if not tc:
        return {"error": "No hay tipo de cambio disponible"}

    return {"moneda": tc.moneda, "compra": tc.compra, "venta": tc.venta, "fecha": tc.fecha.isoformat()}


@router.get("/tipo-cambio/fecha/{fecha}")
async def obtener_tipo_cambio_por_fecha(
    fecha: str, db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)
):
    """
    Obtiene el tipo de cambio para una fecha específica.
    Si no hay TC para esa fecha exacta, busca el más cercano anterior.
    """
    from app.models.tipo_cambio import TipoCambio
    from datetime import datetime

    try:
        fecha_obj = datetime.strptime(fecha, "%Y-%m-%d").date()
    except ValueError:
        return {"error": "Formato de fecha inválido. Use YYYY-MM-DD"}

    # Primero buscar TC exacto para la fecha
    tc = db.query(TipoCambio).filter(TipoCambio.moneda == "USD", TipoCambio.fecha == fecha_obj).first()

    # Si no existe, buscar el más cercano anterior
    if not tc:
        tc = (
            db.query(TipoCambio)
            .filter(TipoCambio.moneda == "USD", TipoCambio.fecha <= fecha_obj)
            .order_by(TipoCambio.fecha.desc())
            .first()
        )

    if not tc:
        return {"error": "No hay tipo de cambio disponible para esa fecha"}

    return {
        "moneda": tc.moneda,
        "compra": float(tc.compra) if tc.compra else None,
        "venta": float(tc.venta) if tc.venta else None,
        "fecha": tc.fecha.isoformat(),
        "fecha_solicitada": fecha,
    }


@router.post("/recalcular-markups")
async def recalcular_markups_endpoint(
    db: Session = Depends(get_db), current_user: Usuario = Depends(get_admin_or_localhost)
):
    """Recalcula markups de todos los productos con precio"""
    from app.services.recalcular_markups_service import recalcular_markups

    try:
        return recalcular_markups(db)
    except Exception as e:
        db.rollback()
        return {"status": "error", "message": str(e)}
