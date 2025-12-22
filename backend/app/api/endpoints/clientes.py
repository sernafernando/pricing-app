"""
Endpoints para consulta de clientes
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import func, or_, and_
from pydantic import BaseModel, EmailStr
from typing import List, Optional
from datetime import datetime, date
import csv
import io

from app.core.database import get_db
from app.models.tb_customer import TBCustomer
from app.models.tb_state import TBState
from app.models.tb_fiscal_class import TBFiscalClass
from app.models.tb_branch import TBBranch
from app.models.tb_salesman import TBSalesman


router = APIRouter(prefix="/clientes", tags=["Clientes"])


# Schemas
class ClienteResponse(BaseModel):
    comp_id: int
    cust_id: int
    cust_name: Optional[str] = None
    cust_name1: Optional[str] = None
    cust_taxnumber: Optional[str] = None
    cust_address: Optional[str] = None
    cust_city: Optional[str] = None
    cust_zip: Optional[str] = None
    cust_phone1: Optional[str] = None
    cust_cellphone: Optional[str] = None
    cust_email: Optional[str] = None
    cust_inactive: Optional[bool] = None
    cust_mercadolibrenickname: Optional[str] = None
    cust_mercadolibreid: Optional[str] = None
    cust_cd: Optional[datetime] = None
    cust_lastupdate: Optional[datetime] = None
    
    # Datos relacionados
    state_id: Optional[int] = None
    state_desc: Optional[str] = None
    fc_id: Optional[int] = None
    fc_desc: Optional[str] = None
    bra_id: Optional[int] = None
    bra_desc: Optional[str] = None
    sm_id: Optional[int] = None
    sm_name: Optional[str] = None
    sm_id_2: Optional[int] = None
    tnt_id: Optional[int] = None
    country_id: Optional[int] = None
    prli_id: Optional[int] = None
    
    class Config:
        from_attributes = True


class ClienteUpdateRequest(BaseModel):
    """Request para actualizar campos editables de un cliente"""
    cust_name: Optional[str] = None
    cust_email: Optional[str] = None
    cust_phone1: Optional[str] = None
    cust_cellphone: Optional[str] = None
    cust_address: Optional[str] = None
    cust_city: Optional[str] = None
    cust_zip: Optional[str] = None


class ClienteListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    total_pages: int
    clientes: List[ClienteResponse]


class ExportClientesRequest(BaseModel):
    """Request para exportar clientes con campos seleccionados"""
    campos: List[str]  # Lista de campos a exportar
    # Filtros (mismos que el GET)
    search: Optional[str] = None
    state_id: Optional[int] = None
    fc_id: Optional[int] = None
    bra_id: Optional[int] = None
    sm_id: Optional[int] = None
    solo_activos: Optional[bool] = None
    con_ml: Optional[bool] = None
    fecha_desde: Optional[date] = None
    fecha_hasta: Optional[date] = None
    cust_id_desde: Optional[int] = None
    cust_id_hasta: Optional[int] = None


# Mapeo de campos disponibles para exportación
CAMPOS_DISPONIBLES = {
    'cust_id': 'ID Cliente',
    'cust_name': 'Nombre',
    'cust_name1': 'Razón Social',
    'cust_taxnumber': 'CUIT/DNI',
    'cust_address': 'Dirección',
    'cust_city': 'Ciudad',
    'cust_zip': 'Código Postal',
    'state_desc': 'Provincia',
    'cust_phone1': 'Teléfono',
    'cust_cellphone': 'Celular',
    'cust_email': 'Email',
    'fc_desc': 'Condición Fiscal',
    'bra_desc': 'Sucursal',
    'sm_name': 'Vendedor',
    'cust_mercadolibrenickname': 'Usuario ML',
    'cust_mercadolibreid': 'ID ML',
    'cust_inactive': 'Inactivo'
}


@router.get("/campos-disponibles")
async def obtener_campos_disponibles():
    """
    Retorna la lista de campos disponibles para exportación
    """
    return {
        "campos": [
            {"key": key, "label": label}
            for key, label in CAMPOS_DISPONIBLES.items()
        ]
    }


@router.get("", response_model=ClienteListResponse)
async def listar_clientes(
    page: int = Query(1, ge=1, description="Número de página"),
    page_size: int = Query(50, ge=1, le=1000, description="Cantidad de registros por página"),
    search: Optional[str] = Query(None, description="Buscar por nombre, CUIT, email o ciudad"),
    state_id: Optional[int] = Query(None, description="Filtrar por provincia"),
    fc_id: Optional[int] = Query(None, description="Filtrar por condición fiscal"),
    bra_id: Optional[int] = Query(None, description="Filtrar por sucursal"),
    sm_id: Optional[int] = Query(None, description="Filtrar por vendedor"),
    solo_activos: Optional[bool] = Query(None, description="Solo clientes activos"),
    con_ml: Optional[bool] = Query(None, description="Solo clientes con MercadoLibre"),
    fecha_desde: Optional[date] = Query(None, description="Filtrar por fecha de alta desde"),
    fecha_hasta: Optional[date] = Query(None, description="Filtrar por fecha de alta hasta"),
    cust_id_desde: Optional[int] = Query(None, description="ID de cliente desde (rango)"),
    cust_id_hasta: Optional[int] = Query(None, description="ID de cliente hasta (rango)"),
    db: Session = Depends(get_db)
):
    """
    Lista clientes con filtros y paginación
    """
    # Query base con joins
    query = db.query(
        TBCustomer.comp_id,
        TBCustomer.cust_id,
        TBCustomer.cust_name,
        TBCustomer.cust_name1,
        TBCustomer.cust_taxnumber,
        TBCustomer.cust_address,
        TBCustomer.cust_city,
        TBCustomer.cust_zip,
        TBCustomer.cust_phone1,
        TBCustomer.cust_cellphone,
        TBCustomer.cust_email,
        TBCustomer.cust_inactive,
        TBCustomer.cust_mercadolibrenickname,
        TBCustomer.cust_mercadolibreid,
        TBCustomer.state_id,
        TBState.state_desc,
        TBCustomer.fc_id,
        TBFiscalClass.fc_desc,
        TBCustomer.bra_id,
        TBBranch.bra_desc,
        TBCustomer.sm_id,
        TBSalesman.sm_name
    ).outerjoin(
        TBState,
        and_(
            TBCustomer.state_id == TBState.state_id,
            TBState.country_id == 54  # Argentina
        )
    ).outerjoin(
        TBFiscalClass,
        TBCustomer.fc_id == TBFiscalClass.fc_id
    ).outerjoin(
        TBBranch,
        and_(
            TBCustomer.bra_id == TBBranch.bra_id,
            TBCustomer.comp_id == TBBranch.comp_id
        )
    ).outerjoin(
        TBSalesman,
        and_(
            TBCustomer.sm_id == TBSalesman.sm_id,
            TBCustomer.comp_id == TBSalesman.comp_id
        )
    )

    # Aplicar filtros
    if search:
        search_filter = or_(
            TBCustomer.cust_name.ilike(f"%{search}%"),
            TBCustomer.cust_name1.ilike(f"%{search}%"),
            TBCustomer.cust_taxnumber.ilike(f"%{search}%"),
            TBCustomer.cust_email.ilike(f"%{search}%"),
            TBCustomer.cust_city.ilike(f"%{search}%")
        )
        query = query.filter(search_filter)

    if state_id is not None:
        query = query.filter(TBCustomer.state_id == state_id)

    if fc_id is not None:
        query = query.filter(TBCustomer.fc_id == fc_id)

    if bra_id is not None:
        query = query.filter(TBCustomer.bra_id == bra_id)

    if sm_id is not None:
        query = query.filter(TBCustomer.sm_id == sm_id)

    if solo_activos is not None:
        query = query.filter(TBCustomer.cust_inactive == (not solo_activos))

    if con_ml is not None:
        if con_ml:
            query = query.filter(TBCustomer.cust_mercadolibreid.isnot(None))
        else:
            query = query.filter(TBCustomer.cust_mercadolibreid.is_(None))

    if fecha_desde is not None:
        query = query.filter(func.date(TBCustomer.cust_cd) >= fecha_desde)

    if fecha_hasta is not None:
        query = query.filter(func.date(TBCustomer.cust_cd) <= fecha_hasta)

    if cust_id_desde is not None:
        query = query.filter(TBCustomer.cust_id >= cust_id_desde)

    if cust_id_hasta is not None:
        query = query.filter(TBCustomer.cust_id <= cust_id_hasta)

    # Contar total
    total = query.count()

    # Aplicar paginación
    offset = (page - 1) * page_size
    clientes_raw = query.order_by(TBCustomer.cust_name).offset(offset).limit(page_size).all()

    # Convertir a ClienteResponse
    clientes = [
        ClienteResponse(
            comp_id=c.comp_id,
            cust_id=c.cust_id,
            cust_name=c.cust_name,
            cust_name1=c.cust_name1,
            cust_taxnumber=c.cust_taxnumber,
            cust_address=c.cust_address,
            cust_city=c.cust_city,
            cust_zip=c.cust_zip,
            cust_phone1=c.cust_phone1,
            cust_cellphone=c.cust_cellphone,
            cust_email=c.cust_email,
            cust_inactive=c.cust_inactive,
            cust_mercadolibrenickname=c.cust_mercadolibrenickname,
            cust_mercadolibreid=c.cust_mercadolibreid,
            state_id=c.state_id,
            state_desc=c.state_desc,
            fc_id=c.fc_id,
            fc_desc=c.fc_desc,
            bra_id=c.bra_id,
            bra_desc=c.bra_desc,
            sm_id=c.sm_id,
            sm_name=c.sm_name
        )
        for c in clientes_raw
    ]

    total_pages = (total + page_size - 1) // page_size

    return ClienteListResponse(
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
        clientes=clientes
    )


@router.get("/{cust_id}", response_model=ClienteResponse)
async def obtener_cliente(
    cust_id: int,
    comp_id: int = Query(1, description="ID de compañía"),
    db: Session = Depends(get_db)
):
    """
    Obtiene un cliente específico por ID
    """
    result = db.query(
        TBCustomer.comp_id,
        TBCustomer.cust_id,
        TBCustomer.cust_name,
        TBCustomer.cust_name1,
        TBCustomer.cust_taxnumber,
        TBCustomer.cust_address,
        TBCustomer.cust_city,
        TBCustomer.cust_zip,
        TBCustomer.cust_phone1,
        TBCustomer.cust_cellphone,
        TBCustomer.cust_email,
        TBCustomer.cust_inactive,
        TBCustomer.cust_mercadolibrenickname,
        TBCustomer.cust_mercadolibreid,
        TBCustomer.cust_cd,
        TBCustomer.cust_lastupdate,
        TBCustomer.state_id,
        TBState.state_desc,
        TBCustomer.fc_id,
        TBFiscalClass.fc_desc,
        TBCustomer.bra_id,
        TBBranch.bra_desc,
        TBCustomer.sm_id,
        TBSalesman.sm_name,
        TBCustomer.sm_id_2,
        TBCustomer.tnt_id,
        TBCustomer.country_id,
        TBCustomer.prli_id
    ).outerjoin(
        TBState,
        and_(
            TBCustomer.state_id == TBState.state_id,
            TBState.country_id == 54
        )
    ).outerjoin(
        TBFiscalClass,
        TBCustomer.fc_id == TBFiscalClass.fc_id
    ).outerjoin(
        TBBranch,
        and_(
            TBCustomer.bra_id == TBBranch.bra_id,
            TBCustomer.comp_id == TBBranch.comp_id
        )
    ).outerjoin(
        TBSalesman,
        and_(
            TBCustomer.sm_id == TBSalesman.sm_id,
            TBCustomer.comp_id == TBSalesman.comp_id
        )
    ).filter(
        TBCustomer.comp_id == comp_id,
        TBCustomer.cust_id == cust_id
    ).first()

    if not result:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")

    return ClienteResponse(
        comp_id=result.comp_id,
        cust_id=result.cust_id,
        cust_name=result.cust_name,
        cust_name1=result.cust_name1,
        cust_taxnumber=result.cust_taxnumber,
        cust_address=result.cust_address,
        cust_city=result.cust_city,
        cust_zip=result.cust_zip,
        cust_phone1=result.cust_phone1,
        cust_cellphone=result.cust_cellphone,
        cust_email=result.cust_email,
        cust_inactive=result.cust_inactive,
        cust_mercadolibrenickname=result.cust_mercadolibrenickname,
        cust_mercadolibreid=result.cust_mercadolibreid,
        cust_cd=result.cust_cd,
        cust_lastupdate=result.cust_lastupdate,
        state_id=result.state_id,
        state_desc=result.state_desc,
        fc_id=result.fc_id,
        fc_desc=result.fc_desc,
        bra_id=result.bra_id,
        bra_desc=result.bra_desc,
        sm_id=result.sm_id,
        sm_name=result.sm_name,
        sm_id_2=result.sm_id_2,
        tnt_id=result.tnt_id,
        country_id=result.country_id,
        prli_id=result.prli_id
    )


@router.post("/exportar")
async def exportar_clientes(
    export_request: ExportClientesRequest,
    db: Session = Depends(get_db)
):
    """
    Exporta clientes a CSV con campos seleccionados y filtros aplicados
    """
    # Validar campos solicitados
    campos_invalidos = [c for c in export_request.campos if c not in CAMPOS_DISPONIBLES]
    if campos_invalidos:
        raise HTTPException(
            status_code=400,
            detail=f"Campos inválidos: {', '.join(campos_invalidos)}"
        )

    # Query base con joins (mismo que listar_clientes)
    query = db.query(
        TBCustomer.comp_id,
        TBCustomer.cust_id,
        TBCustomer.cust_name,
        TBCustomer.cust_name1,
        TBCustomer.cust_taxnumber,
        TBCustomer.cust_address,
        TBCustomer.cust_city,
        TBCustomer.cust_zip,
        TBCustomer.cust_phone1,
        TBCustomer.cust_cellphone,
        TBCustomer.cust_email,
        TBCustomer.cust_inactive,
        TBCustomer.cust_mercadolibrenickname,
        TBCustomer.cust_mercadolibreid,
        TBCustomer.state_id,
        TBState.state_desc,
        TBCustomer.fc_id,
        TBFiscalClass.fc_desc,
        TBCustomer.bra_id,
        TBBranch.bra_desc,
        TBCustomer.sm_id,
        TBSalesman.sm_name
    ).outerjoin(
        TBState,
        and_(
            TBCustomer.state_id == TBState.state_id,
            TBState.country_id == 54
        )
    ).outerjoin(
        TBFiscalClass,
        TBCustomer.fc_id == TBFiscalClass.fc_id
    ).outerjoin(
        TBBranch,
        and_(
            TBCustomer.bra_id == TBBranch.bra_id,
            TBCustomer.comp_id == TBBranch.comp_id
        )
    ).outerjoin(
        TBSalesman,
        and_(
            TBCustomer.sm_id == TBSalesman.sm_id,
            TBCustomer.comp_id == TBSalesman.comp_id
        )
    )

    # Aplicar los mismos filtros que en listar_clientes
    if export_request.search:
        search_filter = or_(
            TBCustomer.cust_name.ilike(f"%{export_request.search}%"),
            TBCustomer.cust_name1.ilike(f"%{export_request.search}%"),
            TBCustomer.cust_taxnumber.ilike(f"%{export_request.search}%"),
            TBCustomer.cust_email.ilike(f"%{export_request.search}%"),
            TBCustomer.cust_city.ilike(f"%{export_request.search}%")
        )
        query = query.filter(search_filter)

    if export_request.state_id is not None:
        query = query.filter(TBCustomer.state_id == export_request.state_id)

    if export_request.fc_id is not None:
        query = query.filter(TBCustomer.fc_id == export_request.fc_id)

    if export_request.bra_id is not None:
        query = query.filter(TBCustomer.bra_id == export_request.bra_id)

    if export_request.sm_id is not None:
        query = query.filter(TBCustomer.sm_id == export_request.sm_id)

    if export_request.solo_activos is not None:
        query = query.filter(TBCustomer.cust_inactive == (not export_request.solo_activos))

    if export_request.con_ml is not None:
        if export_request.con_ml:
            query = query.filter(TBCustomer.cust_mercadolibreid.isnot(None))
        else:
            query = query.filter(TBCustomer.cust_mercadolibreid.is_(None))

    if export_request.fecha_desde is not None:
        query = query.filter(func.date(TBCustomer.cust_cd) >= export_request.fecha_desde)

    if export_request.fecha_hasta is not None:
        query = query.filter(func.date(TBCustomer.cust_cd) <= export_request.fecha_hasta)

    if export_request.cust_id_desde is not None:
        query = query.filter(TBCustomer.cust_id >= export_request.cust_id_desde)

    if export_request.cust_id_hasta is not None:
        query = query.filter(TBCustomer.cust_id <= export_request.cust_id_hasta)

    # Obtener todos los resultados
    clientes_raw = query.order_by(TBCustomer.cust_name).all()

    # Crear CSV en memoria
    output = io.StringIO()
    writer = csv.writer(output)

    # Escribir encabezados (solo los campos seleccionados)
    headers = [CAMPOS_DISPONIBLES[campo] for campo in export_request.campos]
    writer.writerow(headers)

    # Mapeo de campos a índices en la tupla del resultado
    campo_a_indice = {
        'cust_id': 1,
        'cust_name': 2,
        'cust_name1': 3,
        'cust_taxnumber': 4,
        'cust_address': 5,
        'cust_city': 6,
        'cust_zip': 7,
        'cust_phone1': 8,
        'cust_cellphone': 9,
        'cust_email': 10,
        'cust_inactive': 11,
        'cust_mercadolibrenickname': 12,
        'cust_mercadolibreid': 13,
        'state_desc': 15,
        'fc_desc': 17,
        'bra_desc': 19,
        'sm_name': 21
    }

    # Escribir filas
    for cliente in clientes_raw:
        row = []
        for campo in export_request.campos:
            if campo in campo_a_indice:
                valor = cliente[campo_a_indice[campo]]
                # Formatear valores especiales
                if campo == 'cust_inactive' and valor is not None:
                    valor = 'Sí' if valor else 'No'
                row.append(valor if valor is not None else '')
            else:
                row.append('')
        writer.writerow(row)

    # Preparar respuesta
    output.seek(0)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"clientes_{timestamp}.csv"

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename={filename}"
        }
    )


@router.get("/filtros/provincias")
async def obtener_provincias(
    db: Session = Depends(get_db)
):
    """
    Retorna lista de provincias para el filtro
    """
    provincias = db.query(
        TBState.state_id,
        TBState.state_desc
    ).filter(
        TBState.country_id == 54  # Argentina
    ).order_by(TBState.state_desc).all()

    return [
        {"state_id": p.state_id, "state_desc": p.state_desc}
        for p in provincias
    ]


@router.get("/filtros/condiciones-fiscales")
async def obtener_condiciones_fiscales(
    db: Session = Depends(get_db)
):
    """
    Retorna lista de condiciones fiscales para el filtro
    """
    condiciones = db.query(
        TBFiscalClass.fc_id,
        TBFiscalClass.fc_desc
    ).order_by(TBFiscalClass.fc_desc).all()

    return [
        {"fc_id": c.fc_id, "fc_desc": c.fc_desc}
        for c in condiciones
    ]


@router.get("/filtros/sucursales")
async def obtener_sucursales(
    db: Session = Depends(get_db)
):
    """
    Retorna lista de sucursales para el filtro
    """
    sucursales = db.query(
        TBBranch.bra_id,
        TBBranch.bra_desc
    ).filter(
        TBBranch.bra_disabled == False
    ).order_by(TBBranch.bra_desc).all()

    return [
        {"bra_id": s.bra_id, "bra_desc": s.bra_desc}
        for s in sucursales
    ]


@router.get("/filtros/vendedores")
async def obtener_vendedores(
    db: Session = Depends(get_db)
):
    """
    Retorna lista de vendedores para el filtro
    """
    vendedores = db.query(
        TBSalesman.sm_id,
        TBSalesman.sm_name
    ).filter(
        TBSalesman.sm_disabled == False
    ).order_by(TBSalesman.sm_name).all()

    return [
        {"sm_id": v.sm_id, "sm_name": v.sm_name}
        for v in vendedores
    ]


@router.patch("/{cust_id}", response_model=ClienteResponse)
async def actualizar_cliente(
    cust_id: int,
    datos: ClienteUpdateRequest,
    comp_id: int = Query(1, description="ID de compañía"),
    db: Session = Depends(get_db)
):
    """
    Actualiza campos editables de un cliente
    Solo permite editar: nombre, email, teléfonos, dirección, ciudad, código postal
    """
    cliente = db.query(TBCustomer).filter(
        TBCustomer.comp_id == comp_id,
        TBCustomer.cust_id == cust_id
    ).first()

    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")

    # Actualizar solo los campos que vienen en el request
    update_data = datos.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(cliente, field, value)

    db.commit()
    db.refresh(cliente)

    # Retornar cliente actualizado con joins
    result = db.query(
        TBCustomer.comp_id,
        TBCustomer.cust_id,
        TBCustomer.cust_name,
        TBCustomer.cust_name1,
        TBCustomer.cust_taxnumber,
        TBCustomer.cust_address,
        TBCustomer.cust_city,
        TBCustomer.cust_zip,
        TBCustomer.cust_phone1,
        TBCustomer.cust_cellphone,
        TBCustomer.cust_email,
        TBCustomer.cust_inactive,
        TBCustomer.cust_mercadolibrenickname,
        TBCustomer.cust_mercadolibreid,
        TBCustomer.cust_cd,
        TBCustomer.cust_lastupdate,
        TBCustomer.state_id,
        TBState.state_desc,
        TBCustomer.fc_id,
        TBFiscalClass.fc_desc,
        TBCustomer.bra_id,
        TBBranch.bra_desc,
        TBCustomer.sm_id,
        TBSalesman.sm_name
    ).outerjoin(
        TBState,
        and_(
            TBCustomer.state_id == TBState.state_id,
            TBState.country_id == 54
        )
    ).outerjoin(
        TBFiscalClass,
        TBCustomer.fc_id == TBFiscalClass.fc_id
    ).outerjoin(
        TBBranch,
        and_(
            TBCustomer.bra_id == TBBranch.bra_id,
            TBCustomer.comp_id == TBBranch.comp_id
        )
    ).outerjoin(
        TBSalesman,
        and_(
            TBCustomer.sm_id == TBSalesman.sm_id,
            TBCustomer.comp_id == TBSalesman.comp_id
        )
    ).filter(
        TBCustomer.comp_id == comp_id,
        TBCustomer.cust_id == cust_id
    ).first()

    return ClienteResponse(
        comp_id=result.comp_id,
        cust_id=result.cust_id,
        cust_name=result.cust_name,
        cust_name1=result.cust_name1,
        cust_taxnumber=result.cust_taxnumber,
        cust_address=result.cust_address,
        cust_city=result.cust_city,
        cust_zip=result.cust_zip,
        cust_phone1=result.cust_phone1,
        cust_cellphone=result.cust_cellphone,
        cust_email=result.cust_email,
        cust_inactive=result.cust_inactive,
        cust_mercadolibrenickname=result.cust_mercadolibrenickname,
        cust_mercadolibreid=result.cust_mercadolibreid,
        cust_cd=result.cust_cd,
        cust_lastupdate=result.cust_lastupdate,
        state_id=result.state_id,
        state_desc=result.state_desc,
        fc_id=result.fc_id,
        fc_desc=result.fc_desc,
        bra_id=result.bra_id,
        bra_desc=result.bra_desc,
        sm_id=result.sm_id,
        sm_name=result.sm_name
    )
