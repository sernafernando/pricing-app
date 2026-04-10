from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.core.database import get_db
from app.models.cur_exch_history import CurExchHistory
from app.models.usuario import Usuario
from app.api.deps import get_current_user

router = APIRouter()


@router.get("/tipo-cambio-hoy")
def obtener_tipo_cambio(db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    """Obtiene el tipo de cambio USD/ARS más reciente (primero tipo_cambio, fallback CurExchHistory)"""
    from app.models.tipo_cambio import TipoCambio

    # Primero intentar con tipo_cambio
    tc = db.query(TipoCambio).filter(TipoCambio.moneda == "USD").order_by(TipoCambio.fecha.desc()).first()
    if tc and tc.venta:
        return {"tipo_cambio": float(tc.venta), "fecha": tc.fecha.isoformat() if tc.fecha else None}

    # Fallback a CurExchHistory
    tipo_cambio = db.query(CurExchHistory).order_by(CurExchHistory.ceh_cd.desc()).first()

    if tipo_cambio:
        return {
            "tipo_cambio": float(tipo_cambio.ceh_exchange),
            "fecha": tipo_cambio.ceh_cd.isoformat() if tipo_cambio.ceh_cd else None,
        }

    return {"tipo_cambio": 1000.0, "fecha": None}  # Default fallback


@router.get("/buscar-productos-erp")
def buscar_productos_erp(
    q: str = Query(..., min_length=2, description="Buscar por código o descripción"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """Busca productos en productos_erp por código o descripción, con costo actual"""
    query = """
    SELECT
        p.item_id,
        p.codigo,
        p.descripcion,
        p.marca,
        p.costo,
        p.moneda_costo
    FROM productos_erp p
    WHERE (p.codigo ILIKE :buscar OR p.descripcion ILIKE :buscar)
    ORDER BY p.codigo
    LIMIT 50
    """

    result = db.execute(text(query), {"buscar": f"%{q}%"}).fetchall()

    return [
        {
            "item_id": r.item_id,
            "codigo": r.codigo or str(r.item_id),
            "descripcion": r.descripcion or "",
            "marca": r.marca,
            "costo_unitario": float(r.costo) if r.costo else None,
            "moneda_costo": r.moneda_costo,
        }
        for r in result
    ]
