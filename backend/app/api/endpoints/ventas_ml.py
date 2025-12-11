from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_, desc, text
from typing import List, Optional
from datetime import datetime, date, timedelta
import httpx
from app.core.database import get_db
from app.models.venta_ml import VentaML, MetricasVentasDiarias, MetricasVentasPorMarca, MetricasVentasPorCategoria
from app.models.tb_brand import TBBrand
from app.models.tb_category import TBCategory
from app.models.tb_subcategory import TBSubCategory
from app.models.tb_item import TBItem
from app.models.tb_tax_name import TBTaxName
from app.models.tb_item_taxes import TBItemTaxes
from app.models.usuario import Usuario, RolUsuario
from app.models.marca_pm import MarcaPM
from app.api.deps import get_current_user
from pydantic import BaseModel
from decimal import Decimal
from app.utils.ml_metrics_calculator import calcular_metricas_ml


def get_marcas_usuario_ventas(db: Session, usuario: Usuario) -> Optional[List[str]]:
    """
    Obtiene las marcas asignadas al usuario si no es admin/gerente.
    Retorna None si el usuario puede ver todas las marcas.
    """
    roles_completos = [RolUsuario.SUPERADMIN, RolUsuario.ADMIN, RolUsuario.GERENTE]

    if usuario.rol in roles_completos:
        return None

    marcas = db.query(MarcaPM.marca).filter(MarcaPM.usuario_id == usuario.id).all()
    return [m[0] for m in marcas] if marcas else []

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
        url = "http://localhost:8002/api/gbp-parser"
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


class VentaDetalladaResponse(BaseModel):
    codigo_item: Optional[str]
    marca: Optional[str]
    descripcion: Optional[str]
    cantidad: int
    monto_total: Decimal
    costo_sin_iva: Optional[Decimal]
    iva: Optional[Decimal]
    subcat_id: Optional[int]
    proveedor: Optional[str]
    ufc: Optional[datetime]  # Última fecha de compra
    envio: Optional[Decimal]  # Precio para envío gratis
    upv: Optional[Decimal]  # Último precio de venta

    class Config:
        from_attributes = True


@router.get("/ventas-ml/detalladas", response_model=List[VentaDetalladaResponse])
async def get_ventas_detalladas(
    from_date: Optional[str] = Query(None, description="Fecha desde (YYYY-MM-DD)"),
    to_date: Optional[str] = Query(None, description="Fecha hasta (YYYY-MM-DD)"),
    item_id: Optional[int] = Query(None, description="ID de item específico"),
    dias: Optional[int] = Query(30, description="Últimos N días (si no se especifica from_date/to_date)"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Obtiene ventas detalladas por producto con información completa del ERP.
    Replica la query SQL del dashboard de ventas.

    Incluye: cantidad vendida, monto total, costo s/IVA, IVA, proveedor,
    última fecha de compra, precio envío gratis, último precio de venta.
    """

    # Si no se especifican fechas, usar últimos N días
    if not from_date and not to_date:
        fecha_hasta = datetime.now()
        fecha_desde = fecha_hasta - timedelta(days=dias)
    else:
        fecha_desde = datetime.fromisoformat(from_date) if from_date else datetime.now() - timedelta(days=30)
        fecha_hasta = datetime.fromisoformat(to_date) if to_date else datetime.now()

    # Agregar un día a fecha_hasta para incluir todo el día
    fecha_hasta = fecha_hasta + timedelta(days=1)

    # Query principal: agrupar ventas por item_id
    query = db.query(
        VentaML.item_id,
        VentaML.codigo_item,
        VentaML.marca,
        VentaML.descripcion,
        func.sum(VentaML.cantidad).label('cantidad_total'),
        func.sum(VentaML.monto_total).label('monto_total'),
        VentaML.costo_sin_iva,
        VentaML.iva,
        VentaML.subcat_id
    ).filter(
        and_(
            VentaML.fecha >= fecha_desde,
            VentaML.fecha < fecha_hasta,
            VentaML.item_id.isnot(None),
            VentaML.item_id != 460  # Excluir item_id 460 como en la query original
        )
    )

    # Filtro por item_id específico si se proporciona
    if item_id:
        query = query.filter(VentaML.item_id == item_id)

    # Agrupar y ordenar por cantidad vendida descendente
    ventas_agrupadas = query.group_by(
        VentaML.item_id,
        VentaML.codigo_item,
        VentaML.marca,
        VentaML.descripcion,
        VentaML.costo_sin_iva,
        VentaML.iva,
        VentaML.subcat_id
    ).order_by(desc('cantidad_total')).all()

    # Construir respuesta con datos adicionales
    resultados = []
    for venta in ventas_agrupadas:
        # Obtener proveedor (última venta con ese item_id)
        # Nota: Esto requeriría acceso a tbSupplier, tbCommercialTransactions, tbItemTransactions
        # que no están en los modelos actuales. Por ahora lo dejamos en None.
        proveedor = None
        ufc = None

        # Obtener precio de envío gratis (ml_price_free_shipping)
        envio_query = db.query(VentaML.ml_price_free_shipping).filter(
            VentaML.item_id == venta.item_id
        ).order_by(desc(VentaML.fecha)).first()
        envio = envio_query[0] if envio_query else None

        # Obtener último precio de venta
        upv_query = db.query(VentaML.monto_unitario).filter(
            VentaML.item_id == venta.item_id
        ).order_by(desc(VentaML.fecha)).first()
        upv = upv_query[0] if upv_query else None

        resultados.append({
            "codigo_item": venta.codigo_item,
            "marca": venta.marca,
            "descripcion": venta.descripcion,
            "cantidad": int(venta.cantidad_total or 0),
            "monto_total": venta.monto_total or Decimal(0),
            "costo_sin_iva": venta.costo_sin_iva,
            "iva": venta.iva,
            "subcat_id": venta.subcat_id,
            "proveedor": proveedor,
            "ufc": ufc,
            "envio": envio,
            "upv": upv
        })

    return resultados


class OperacionConMetricasResponse(BaseModel):
    # Datos de la operación
    id_operacion: int
    ml_id: Optional[str]
    pack_id: Optional[int]
    fecha_venta: datetime

    # Datos del producto
    item_id: Optional[int]
    codigo: Optional[str]
    descripcion: Optional[str]
    categoria: Optional[str]
    subcategoria: Optional[str]
    marca: Optional[str]

    # Datos de la venta
    cantidad: Decimal
    monto_unitario: Decimal
    monto_total: Decimal
    iva: Decimal
    pricelist_id: Optional[int]
    tipo_publicacion: Optional[str]

    # Costos
    costo_sin_iva: Decimal
    costo_total: Decimal

    # Métricas calculadas
    comision_porcentaje: Decimal
    comision_pesos: Decimal
    costo_envio: Decimal
    monto_limpio: Decimal
    markup_porcentaje: Decimal

    class Config:
        from_attributes = True


@router.get("/ventas-ml/operaciones-con-metricas", response_model=List[OperacionConMetricasResponse])
async def get_operaciones_con_metricas(
    from_date: str = Query(..., description="Fecha desde (YYYY-MM-DD)"),
    to_date: str = Query(..., description="Fecha hasta (YYYY-MM-DD)"),
    ml_id: Optional[str] = Query(None, description="Filtrar por ML ID"),
    codigo: Optional[str] = Query(None, description="Filtrar por código de producto"),
    marca: Optional[str] = Query(None, description="Filtrar por marca"),
    limit: int = Query(1000, le=5000, description="Límite de resultados"),
    offset: int = Query(0, description="Offset para paginación"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Obtiene operaciones de ML con todas las métricas calculadas (comisión, markup, etc.)
    Si el usuario no es admin/gerente, solo ve sus marcas asignadas.
    """

    # Obtener marcas del usuario para filtrar
    marcas_usuario = get_marcas_usuario_ventas(db, current_user)

    to_date_full = to_date + ' 23:59:59'

    query_str = """
    WITH sales_data AS (
        SELECT DISTINCT ON (tmlod.mlo_id)
            tmlod.mlo_id as id_operacion,
            tmlod.item_id,
            tmloh.mlo_cd as fecha_venta,
            COALESCE(tb.brand_desc, pe.marca) as marca,
            COALESCE(tc.cat_desc, pe.categoria) as categoria,
            COALESCE(tsc.subcat_desc, (SELECT s.subcat_desc FROM tb_subcategory s WHERE s.subcat_id = pe.subcategoria_id LIMIT 1)) as subcategoria,
            COALESCE(ti.item_code, pe.codigo) as codigo,
            COALESCE(UPPER(ti.item_desc), UPPER(pe.descripcion)) as descripcion,
            tmlod.mlo_quantity as cantidad,
            tmlod.mlo_unit_price as monto_unitario,
            tmlod.mlo_unit_price * tmlod.mlo_quantity as monto_total,

            -- Costo sin IVA en PESOS (convierte USD a ARS usando tipo de cambio)
            -- TC: Primero tipo_cambio, fallback tb_cur_exch_history
            COALESCE(
                (
                    SELECT CASE
                        WHEN iclh.curr_id = 2 THEN  -- USD
                            CASE
                                WHEN iclh.iclh_price = 0 THEN ticl.coslis_price * COALESCE(
                                    (SELECT tc.venta FROM tipo_cambio tc WHERE tc.moneda = 'USD' AND tc.fecha <= tmloh.mlo_cd::date ORDER BY tc.fecha DESC LIMIT 1),
                                    (SELECT ceh.ceh_exchange FROM tb_cur_exch_history ceh WHERE ceh.ceh_cd <= tmloh.mlo_cd ORDER BY ceh.ceh_cd DESC LIMIT 1)
                                )
                                ELSE iclh.iclh_price * COALESCE(
                                    (SELECT tc.venta FROM tipo_cambio tc WHERE tc.moneda = 'USD' AND tc.fecha <= tmloh.mlo_cd::date ORDER BY tc.fecha DESC LIMIT 1),
                                    (SELECT ceh.ceh_exchange FROM tb_cur_exch_history ceh WHERE ceh.ceh_cd <= tmloh.mlo_cd ORDER BY ceh.ceh_cd DESC LIMIT 1)
                                )
                            END
                        ELSE  -- ARS
                            CASE
                                WHEN iclh.iclh_price = 0 THEN ticl.coslis_price
                                ELSE iclh.iclh_price
                            END
                    END
                    FROM tb_item_cost_list_history iclh
                    LEFT JOIN tb_item_cost_list ticl
                        ON ticl.item_id = iclh.item_id
                        AND ticl.coslis_id = 1
                    WHERE iclh.item_id = tmlod.item_id
                      AND iclh.iclh_cd <= tmloh.mlo_cd
                      AND iclh.coslis_id = 1
                    ORDER BY iclh.iclh_id DESC
                    LIMIT 1
                ),
                (
                    SELECT CASE
                        WHEN ticl.curr_id = 2 THEN  -- USD
                            ticl.coslis_price * COALESCE(
                                (SELECT tc.venta FROM tipo_cambio tc WHERE tc.moneda = 'USD' AND tc.fecha <= tmloh.mlo_cd::date ORDER BY tc.fecha DESC LIMIT 1),
                                (SELECT ceh.ceh_exchange FROM tb_cur_exch_history ceh WHERE ceh.ceh_cd <= tmloh.mlo_cd ORDER BY ceh.ceh_cd DESC LIMIT 1)
                            )
                        ELSE  -- ARS
                            ticl.coslis_price
                    END
                    FROM tb_item_cost_list ticl
                    WHERE ticl.item_id = tmlod.item_id
                      AND ticl.coslis_id = 1
                ),
                0
            ) as costo_sin_iva,

            COALESCE(ttn.tax_percentage, 21.0) as iva,

            tmloh.ml_id,
            tmloh.ml_pack_id as pack_id,

            -- Costo de envío del producto (viene con IVA)
            pe.envio as envio_producto,

            -- Comisión base porcentaje
            COALESCE(
                (
                    SELECT clg.comision_porcentaje
                    FROM subcategorias_grupos sg
                    JOIN comisiones_lista_grupo clg ON clg.grupo_id = sg.grupo_id
                    WHERE sg.subcat_id = tsc.subcat_id
                      AND clg.pricelist_id = COALESCE(
                          tsoh.prli_id,
                          CASE
                              WHEN tmloh.mlo_ismshops = TRUE THEN tmlip.prli_id4mercadoshop
                              ELSE tmlip.prli_id
                          END
                      )
                      AND clg.activo = TRUE
                    LIMIT 1
                ),
                (
                    SELECT cb.comision_base
                    FROM subcategorias_grupos sg
                    JOIN comisiones_base cb ON cb.grupo_id = sg.grupo_id
                    JOIN comisiones_versiones cv ON cv.id = cb.version_id
                    WHERE sg.subcat_id = tsc.subcat_id
                      AND tmloh.mlo_cd::date BETWEEN cv.fecha_desde AND COALESCE(cv.fecha_hasta, '9999-12-31'::date)
                      AND cv.activo = TRUE
                    LIMIT 1
                ),
                12.0
            ) as comision_base_porcentaje,

            tsc.subcat_id,

            -- Price list
            COALESCE(
                tsoh.prli_id,
                CASE
                    WHEN tmloh.mlo_ismshops = TRUE THEN tmlip.prli_id4mercadoshop
                    ELSE tmlip.prli_id
                END
            ) as pricelist_id

        FROM tb_mercadolibre_orders_detail tmlod

        LEFT JOIN tb_mercadolibre_orders_header tmloh
            ON tmloh.comp_id = tmlod.comp_id
            AND tmloh.mlo_id = tmlod.mlo_id

        LEFT JOIN tb_sale_order_header tsoh
            ON tsoh.comp_id = tmlod.comp_id
            AND tsoh.mlo_id = tmlod.mlo_id

        LEFT JOIN tb_item ti
            ON ti.comp_id = tmlod.comp_id
            AND ti.item_id = tmlod.item_id

        LEFT JOIN productos_erp pe
            ON pe.item_id = tmlod.item_id

        LEFT JOIN tb_mercadolibre_items_publicados tmlip
            ON tmlip.comp_id = tmlod.comp_id
            AND tmlip.mlp_id = tmlod.mlp_id

        LEFT JOIN tb_mercadolibre_orders_shipping tmlos
            ON tmlos.comp_id = tmlod.comp_id
            AND tmlos.mlo_id = tmlod.mlo_id

        LEFT JOIN tb_commercial_transactions tct
            ON tct.comp_id = tmlod.comp_id
            AND tct.mlo_id = tmlod.mlo_id

        LEFT JOIN tb_category tc
            ON tc.comp_id = tmlod.comp_id
            AND tc.cat_id = ti.cat_id

        LEFT JOIN tb_subcategory tsc
            ON tsc.comp_id = tmlod.comp_id
            AND tsc.cat_id = ti.cat_id
            AND tsc.subcat_id = ti.subcat_id

        LEFT JOIN tb_brand tb
            ON tb.comp_id = tmlod.comp_id
            AND tb.brand_id = ti.brand_id

        LEFT JOIN tb_item_taxes tit
            ON ti.comp_id = tit.comp_id
            AND ti.item_id = tit.item_id

        LEFT JOIN tb_tax_name ttn
            ON ttn.comp_id = ti.comp_id
            AND ttn.tax_id = tit.tax_id

        LEFT JOIN tb_item_cost_list ticl
            ON ticl.comp_id = tmlod.comp_id
            AND ticl.item_id = tmlod.item_id
            AND ticl.coslis_id = 1

        WHERE tmlod.item_id NOT IN (460, 3042)
          AND tmloh.mlo_cd BETWEEN %(from_date)s AND %(to_date)s
          AND tmloh.mlo_status <> 'cancelled'
    )
    SELECT * FROM sales_data
    ORDER BY fecha_venta DESC, id_operacion
    LIMIT %(limit)s OFFSET %(offset)s
    """

    # Ejecutar via raw connection (psycopg2) que soporta %(param)s nativo
    # Obtener la conexión raw de psycopg2
    raw_connection = db.connection().connection
    cursor = raw_connection.cursor()
    cursor.execute(query_str, {
        'from_date': from_date,
        'to_date': to_date_full,
        'limit': limit,
        'offset': offset
    })

    # Convertir resultado a formato compatible
    columns = [desc[0] for desc in cursor.description]
    from collections import namedtuple
    Row = namedtuple('Row', columns)
    rows = [Row(*row) for row in cursor.fetchall()]
    cursor.close()

    # Procesar cada fila y calcular métricas
    operaciones = []
    for row in rows:
        # Filtrar por marcas del PM si no es admin/gerente
        if marcas_usuario is not None:
            if len(marcas_usuario) == 0:
                continue  # Sin marcas asignadas, no ve nada
            if row.marca not in marcas_usuario:
                continue

        # Aplicar filtros adicionales si se especificaron
        if ml_id and row.ml_id != ml_id:
            continue
        if codigo and codigo not in (row.codigo or ''):
            continue
        if marca and marca != row.marca:
            continue

        # Usar el costo de envío del PRODUCTO (productos_erp.envio)
        # Ya viene con IVA, el helper lo multiplica por cantidad y le resta el IVA
        costo_envio_producto = None
        if row.envio_producto:
            costo_envio_producto = float(row.envio_producto)

        # Calcular métricas usando el helper
        metricas = calcular_metricas_ml(
            monto_unitario=float(row.monto_unitario or 0),
            cantidad=float(row.cantidad or 1),
            iva_porcentaje=float(row.iva or 0),
            costo_unitario_sin_iva=float(row.costo_sin_iva or 0),
            costo_envio_ml=costo_envio_producto,
            count_per_pack=1,
            subcat_id=row.subcat_id if hasattr(row, 'subcat_id') else None,
            pricelist_id=row.pricelist_id,
            fecha_venta=row.fecha_venta,
            comision_base_porcentaje=float(row.comision_base_porcentaje or 12.0),
            db_session=db
        )

        # Mapeo de pricelist_id a nombre
        pricelist_names = {
            4: "Clásica", 12: "Clásica",
            17: "3 Cuotas", 18: "3 Cuotas",
            14: "6 Cuotas", 19: "6 Cuotas",
            13: "9 Cuotas", 20: "9 Cuotas",
            23: "12 Cuotas", 21: "12 Cuotas"
        }
        tipo_publicacion = pricelist_names.get(row.pricelist_id, f"Lista {row.pricelist_id}") if row.pricelist_id else None

        # Costo total
        costo_total = float(row.costo_sin_iva or 0) * float(row.cantidad or 1)

        operaciones.append({
            "id_operacion": row.id_operacion,
            "ml_id": row.ml_id,
            "pack_id": row.pack_id,
            "fecha_venta": row.fecha_venta,
            "item_id": row.item_id,
            "codigo": row.codigo,
            "descripcion": row.descripcion,
            "categoria": row.categoria,
            "subcategoria": row.subcategoria,
            "marca": row.marca,
            "cantidad": Decimal(str(row.cantidad or 0)),
            "monto_unitario": Decimal(str(row.monto_unitario or 0)),
            "monto_total": Decimal(str(row.monto_total or 0)),
            "iva": Decimal(str(row.iva or 0)),
            "pricelist_id": row.pricelist_id,
            "tipo_publicacion": tipo_publicacion,
            "costo_sin_iva": Decimal(str(row.costo_sin_iva or 0)),
            "costo_total": Decimal(str(costo_total)),
            "comision_porcentaje": Decimal(str(row.comision_base_porcentaje or 0)),
            "comision_pesos": Decimal(str(metricas['comision_ml'])),
            "costo_envio": Decimal(str(metricas['costo_envio'])),
            "monto_limpio": Decimal(str(metricas['monto_limpio'])),
            "markup_porcentaje": Decimal(str(metricas['markup_porcentaje']))
        })

    return operaciones
