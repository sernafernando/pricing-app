from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models.ml_catalog_status import MLCatalogStatus
from app.models.publicacion_ml import PublicacionML
from app.services.ml_webhook_client import ml_webhook_client
from app.api.deps import get_current_user
from app.models.usuario import Usuario
from datetime import datetime
import logging

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/sync-catalog-status")
async def sync_catalog_status(
    mla_id: str = Query(None, description="Sincronizar solo este MLA"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """
    Sincroniza el estado de competencia en catálogos para publicaciones de ML

    Si se proporciona mla_id, sincroniza solo ese item.
    Si no, sincroniza todas las publicaciones que tienen catalog_product_id.
    """

    # Obtener publicaciones a sincronizar
    query = db.query(PublicacionML)

    if mla_id:
        query = query.filter(PublicacionML.mla == mla_id)

    publicaciones = query.all()

    sincronizadas = 0
    errores = []

    for pub in publicaciones:
        try:
            # Obtener preview básico primero para ver si tiene catálogo
            preview = await ml_webhook_client.get_item_preview(pub.mla)

            if not preview or not preview.get("catalog_product_id"):
                continue

            # Tiene catálogo, obtener price_to_win
            ptw_data = await ml_webhook_client.get_item_preview(pub.mla, include_price_to_win=True)

            if not ptw_data:
                continue

            # Guardar en base de datos
            catalog_status = MLCatalogStatus(
                mla=pub.mla,
                catalog_product_id=ptw_data.get("catalog_product_id"),
                status=ptw_data.get("status"),
                current_price=float(ptw_data.get("price", 0)) if ptw_data.get("price") else None,
                price_to_win=float(ptw_data.get("price_to_win", 0)) if ptw_data.get("price_to_win") else None,
                visit_share=ptw_data.get("visit_share"),
                consistent=ptw_data.get("consistent"),
                competitors_sharing_first_place=ptw_data.get("competitors_sharing_first_place"),
                winner_mla=ptw_data.get("winner"),
                winner_price=float(ptw_data.get("winner_price", 0)) if ptw_data.get("winner_price") else None,
                fecha_consulta=datetime.now(),
            )

            db.add(catalog_status)
            sincronizadas += 1

        except Exception as e:
            logger.error(f"Error sincronizando {pub.mla}: {e}")
            errores.append(f"{pub.mla}: {str(e)}")

    db.commit()

    return {
        "sincronizadas": sincronizadas,
        "errores": errores[:10],  # Limitar a 10 errores
        "total_publicaciones": len(publicaciones),
    }


@router.get("/catalog-status/{mla_id}")
async def get_catalog_status(
    mla_id: str, db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)
):
    """Obtiene el último estado de catálogo de un MLA"""

    status = (
        db.query(MLCatalogStatus)
        .filter(MLCatalogStatus.mla == mla_id)
        .order_by(MLCatalogStatus.fecha_consulta.desc())
        .first()
    )

    if not status:
        raise HTTPException(status_code=404, detail="No hay datos de catálogo para este MLA")

    return {
        "mla": status.mla,
        "catalog_product_id": status.catalog_product_id,
        "status": status.status,
        "current_price": float(status.current_price) if status.current_price else None,
        "price_to_win": float(status.price_to_win) if status.price_to_win else None,
        "winner_mla": status.winner_mla,
        "winner_price": float(status.winner_price) if status.winner_price else None,
        "fecha_consulta": status.fecha_consulta.isoformat() if status.fecha_consulta else None,
    }


@router.get("/catalog-status")
async def get_all_catalog_status(db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    """Obtiene el último estado de catálogo de todos los MLAs"""

    # Usar la vista para obtener el último estado de cada MLA
    from sqlalchemy import text

    results = db.execute(
        text("""
        SELECT mla, catalog_product_id, status, current_price, price_to_win,
               winner_mla, winner_price, fecha_consulta
        FROM v_ml_catalog_status_latest
        ORDER BY fecha_consulta DESC
    """)
    ).fetchall()

    return [
        {
            "mla": row[0],
            "catalog_product_id": row[1],
            "status": row[2],
            "current_price": float(row[3]) if row[3] else None,
            "price_to_win": float(row[4]) if row[4] else None,
            "winner_mla": row[5],
            "winner_price": float(row[6]) if row[6] else None,
            "fecha_consulta": row[7].isoformat() if row[7] else None,
        }
        for row in results
    ]
