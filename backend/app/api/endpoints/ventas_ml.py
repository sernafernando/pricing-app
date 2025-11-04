from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_, desc
from typing import List, Optional
from datetime import datetime, date, timedelta
import httpx
from app.core.database import get_db
from app.models.venta_ml import VentaML, MetricasVentasDiarias, MetricasVentasPorMarca, MetricasVentasPorCategoria
from app.api.deps import get_current_user
from pydantic import BaseModel
from decimal import Decimal

router = APIRouter()

# Schemas
class VentaMLResponse(BaseModel):
    id_venta: int
    id_operacion: int
    item_id: Optional[int]
    fecha: datetime
    marca: Optional[str]
    categoria: Optional[str]
    subcategoria: Optional[str]
    codigo_item: Optional[str]
    descripcion: Optional[str]
    cantidad: int
    monto_unitario: Optional[Decimal]
    monto_total: Decimal
    costo_sin_iva: Optional[Decimal]
    iva: Optional[Decimal]
    cambio_al_momento: Optional[Decimal]
    ml_logistic_type: Optional[str]
    ml_id: Optional[int]
    ml_shipment_cost_seller: Optional[Decimal]

    class Config:
        from_attributes = True


class MetricasDiariasResponse(BaseModel):
    fecha: date
    total_ventas: int
    total_unidades: int
    monto_total_ars: Decimal
    costo_envios_total: Decimal
    ventas_full: int
    ventas_flex: int
    ventas_dropoff: int

    class Config:
        from_attributes = True


class SyncVentasRequest(BaseModel):
    from_date: str  # YYYY-MM-DD
    to_date: str    # YYYY-MM-DD


# Endpoints

@router.post("/ventas-ml/sync")
async def sync_ventas_ml(
    request: SyncVentasRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Sincroniza ventas desde el endpoint externo e inserta en la base de datos
    """
    try:
        # Llamar al endpoint externo
        url = "https://parser-worker-js.gaussonline.workers.dev/consulta"
        params = {
            "strScriptLabel": "scriptDashboard",
            "fromDate": request.from_date,
            "toDate": request.to_date
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            ventas_data = response.json()

        if not isinstance(ventas_data, list):
            raise HTTPException(status_code=500, detail="Respuesta inválida del endpoint externo")

        # Insertar o actualizar ventas
        ventas_insertadas = 0
        ventas_actualizadas = 0
        ventas_errores = 0

        for venta_json in ventas_data:
            try:
                # Verificar si ya existe
                venta_existente = db.query(VentaML).filter(
                    VentaML.id_operacion == venta_json.get("ID_de_Operación")
                ).first()

                if venta_existente:
                    ventas_actualizadas += 1
                    continue  # Skip si ya existe

                # Crear nueva venta
                venta = VentaML(
                    id_operacion=venta_json.get("ID_de_Operación"),
                    item_id=venta_json.get("item_id"),
                    fecha=datetime.fromisoformat(venta_json.get("Fecha").replace("Z", "+00:00")),
                    marca=venta_json.get("Marca"),
                    categoria=venta_json.get("Categoría"),
                    subcategoria=venta_json.get("SubCategoría"),
                    subcat_id=venta_json.get("subcat_id"),
                    codigo_item=venta_json.get("Código_Item"),
                    descripcion=venta_json.get("Descripción"),
                    cantidad=venta_json.get("Cantidad"),
                    monto_unitario=venta_json.get("Monto_Unitario"),
                    monto_total=venta_json.get("Monto_Total"),
                    moneda_costo=venta_json.get("Moneda_Costo"),
                    costo_sin_iva=venta_json.get("Costo_sin_IVA"),
                    iva=venta_json.get("IVA"),
                    cambio_al_momento=venta_json.get("Cambio_al_Momento"),
                    ml_logistic_type=venta_json.get("ML_logistic_type"),
                    ml_id=venta_json.get("ML_id"),
                    ml_shipping_id=venta_json.get("MLShippingID"),
                    ml_shipment_cost_seller=venta_json.get("MLShippmentCost4Seller"),
                    ml_price_free_shipping=venta_json.get("mlp_price4FreeShipping"),
                    ml_base_cost=venta_json.get("ML_base_cost"),
                    ml_pack_id=venta_json.get("ML_pack_id"),
                    price_list=venta_json.get("priceList")
                )

                db.add(venta)
                ventas_insertadas += 1

            except Exception as e:
                print(f"Error procesando venta {venta_json.get('ID_de_Operación')}: {str(e)}")
                ventas_errores += 1
                continue

        db.commit()

        return {
            "success": True,
            "message": f"Sincronización completada",
            "ventas_insertadas": ventas_insertadas,
            "ventas_actualizadas": ventas_actualizadas,
            "ventas_errores": ventas_errores,
            "total_procesadas": len(ventas_data)
        }

    except httpx.HTTPError as e:
        raise HTTPException(status_code=500, detail=f"Error al consultar API externa: {str(e)}")
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error en sincronización: {str(e)}")


@router.get("/ventas-ml", response_model=List[VentaMLResponse])
async def get_ventas_ml(
    from_date: Optional[str] = Query(None, description="Fecha desde (YYYY-MM-DD)"),
    to_date: Optional[str] = Query(None, description="Fecha hasta (YYYY-MM-DD)"),
    marca: Optional[str] = Query(None, description="Filtrar por marca"),
    categoria: Optional[str] = Query(None, description="Filtrar por categoría"),
    limit: int = Query(1000, le=5000, description="Límite de resultados"),
    offset: int = Query(0, description="Offset para paginación"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Obtiene ventas de MercadoLibre con filtros opcionales
    """
    query = db.query(VentaML)

    # Aplicar filtros
    if from_date:
        fecha_desde = datetime.fromisoformat(from_date)
        query = query.filter(VentaML.fecha >= fecha_desde)

    if to_date:
        fecha_hasta = datetime.fromisoformat(to_date)
        # Agregar un día para incluir todas las ventas del día to_date
        fecha_hasta = fecha_hasta + timedelta(days=1)
        query = query.filter(VentaML.fecha < fecha_hasta)

    if marca:
        query = query.filter(VentaML.marca == marca)

    if categoria:
        query = query.filter(VentaML.categoria == categoria)

    # Ordenar por fecha descendente y aplicar paginación
    ventas = query.order_by(desc(VentaML.fecha)).limit(limit).offset(offset).all()

    return ventas


@router.get("/ventas-ml/stats")
async def get_ventas_stats(
    from_date: Optional[str] = Query(None, description="Fecha desde (YYYY-MM-DD)"),
    to_date: Optional[str] = Query(None, description="Fecha hasta (YYYY-MM-DD)"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Obtiene estadísticas agregadas de ventas
    """
    query = db.query(
        func.count(VentaML.id_venta).label('total_ventas'),
        func.sum(VentaML.cantidad).label('total_unidades'),
        func.sum(VentaML.monto_total).label('monto_total'),
        func.sum(VentaML.ml_shipment_cost_seller).label('costo_envios'),
        func.count(func.distinct(VentaML.item_id)).label('productos_unicos')
    )

    # Aplicar filtros de fecha
    if from_date:
        fecha_desde = datetime.fromisoformat(from_date)
        query = query.filter(VentaML.fecha >= fecha_desde)

    if to_date:
        fecha_hasta = datetime.fromisoformat(to_date)
        fecha_hasta = fecha_hasta + timedelta(days=1)
        query = query.filter(VentaML.fecha < fecha_hasta)

    result = query.first()

    # Estadísticas por tipo de logística
    logistica_query = db.query(
        VentaML.ml_logistic_type,
        func.count(VentaML.id_venta).label('cantidad')
    )

    if from_date:
        logistica_query = logistica_query.filter(VentaML.fecha >= datetime.fromisoformat(from_date))
    if to_date:
        logistica_query = logistica_query.filter(VentaML.fecha < datetime.fromisoformat(to_date) + timedelta(days=1))

    logistica_stats = logistica_query.group_by(VentaML.ml_logistic_type).all()

    return {
        "total_ventas": result.total_ventas or 0,
        "total_unidades": result.total_unidades or 0,
        "monto_total": float(result.monto_total or 0),
        "costo_envios": float(result.costo_envios or 0),
        "productos_unicos": result.productos_unicos or 0,
        "por_logistica": {
            item.ml_logistic_type: item.cantidad
            for item in logistica_stats if item.ml_logistic_type
        }
    }


@router.get("/ventas-ml/top-productos")
async def get_top_productos(
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None),
    limit: int = Query(10, le=100),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Obtiene los productos más vendidos
    """
    query = db.query(
        VentaML.item_id,
        VentaML.descripcion,
        VentaML.marca,
        func.count(VentaML.id_venta).label('total_ventas'),
        func.sum(VentaML.cantidad).label('unidades_vendidas'),
        func.sum(VentaML.monto_total).label('monto_total')
    ).filter(VentaML.item_id.isnot(None))

    if from_date:
        query = query.filter(VentaML.fecha >= datetime.fromisoformat(from_date))
    if to_date:
        query = query.filter(VentaML.fecha < datetime.fromisoformat(to_date) + timedelta(days=1))

    top_productos = query.group_by(
        VentaML.item_id,
        VentaML.descripcion,
        VentaML.marca
    ).order_by(
        desc('unidades_vendidas')
    ).limit(limit).all()

    return [
        {
            "item_id": p.item_id,
            "descripcion": p.descripcion,
            "marca": p.marca,
            "total_ventas": p.total_ventas,
            "unidades_vendidas": p.unidades_vendidas,
            "monto_total": float(p.monto_total or 0)
        }
        for p in top_productos
    ]


@router.get("/ventas-ml/por-marca")
async def get_ventas_por_marca(
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Obtiene ventas agrupadas por marca
    """
    query = db.query(
        VentaML.marca,
        func.count(VentaML.id_venta).label('total_ventas'),
        func.sum(VentaML.cantidad).label('unidades_vendidas'),
        func.sum(VentaML.monto_total).label('monto_total')
    ).filter(VentaML.marca.isnot(None))

    if from_date:
        query = query.filter(VentaML.fecha >= datetime.fromisoformat(from_date))
    if to_date:
        query = query.filter(VentaML.fecha < datetime.fromisoformat(to_date) + timedelta(days=1))

    por_marca = query.group_by(VentaML.marca).order_by(desc('monto_total')).all()

    return [
        {
            "marca": m.marca,
            "total_ventas": m.total_ventas,
            "unidades_vendidas": m.unidades_vendidas,
            "monto_total": float(m.monto_total or 0)
        }
        for m in por_marca
    ]
