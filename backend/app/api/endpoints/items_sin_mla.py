"""
Endpoints para gestión de items sin MLA asociado
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, func
from typing import List, Optional
from pydantic import BaseModel, ConfigDict

from app.core.database import get_db
from app.api.deps import get_current_user
from app.models.producto import ProductoERP
from app.models.mercadolibre_item_publicado import MercadoLibreItemPublicado
from app.models.item_sin_mla_banlist import ItemSinMLABanlist
from app.models.comparacion_listas_banlist import ComparacionListasBanlist
from app.models.usuario import Usuario
from app.models.ml_publication_snapshot import MLPublicationSnapshot

router = APIRouter()

# Mapeo de IDs de listas a nombres
LISTAS_PRECIOS = {
    4: "Clásica",
    12: "Clásica",  # PVP pero se muestra igual
    17: "3 Cuotas",
    18: "3 Cuotas",  # PVP pero se muestra igual
    14: "6 Cuotas",
    19: "6 Cuotas",  # PVP pero se muestra igual
    13: "9 Cuotas",
    20: "9 Cuotas",  # PVP pero se muestra igual
    23: "12 Cuotas",
    21: "12 Cuotas"  # PVP pero se muestra igual
}

# Mapeo de listas Web a sus pares PVP
LISTAS_WEB_A_PVP = {
    4: 12,   # Clásica -> Clásica PVP
    17: 18,  # 3C -> 3C PVP
    14: 19,  # 6C -> 6C PVP
    13: 20,  # 9C -> 9C PVP
    23: 21   # 12C -> 12C PVP
}

# Mapeo inverso: PVP a Web
LISTAS_PVP_A_WEB = {v: k for k, v in LISTAS_WEB_A_PVP.items()}

# Orden de las listas para ordenamiento correcto
ORDEN_LISTAS = {
    4: 1,   # Clásica
    12: 1,  # Clásica PVP
    17: 2,  # 3 Cuotas
    18: 2,  # 3 Cuotas PVP
    14: 3,  # 6 Cuotas
    19: 3,  # 6 Cuotas PVP
    13: 4,  # 9 Cuotas
    20: 4,  # 9 Cuotas PVP
    23: 5,  # 12 Cuotas
    21: 5   # 12 Cuotas PVP
}

# Schemas
class ItemSinMLAResponse(BaseModel):
    item_id: int
    codigo: str
    descripcion: str
    marca: str
    categoria: Optional[str]
    stock: int
    listas_sin_mla: List[str]  # Lista de nombres de listas donde NO tiene MLA
    listas_con_mla: List[str]  # Lista de nombres de listas donde SÍ tiene MLA

    model_config = ConfigDict(from_attributes=True)

class ItemBaneadoResponse(BaseModel):
    id: int
    item_id: int
    codigo: str
    descripcion: str
    marca: str
    motivo: Optional[str]
    usuario_nombre: str
    fecha_creacion: str

    model_config = ConfigDict(from_attributes=True)

class BanItemRequest(BaseModel):
    item_id: int
    motivo: Optional[str] = None

class UnbanItemRequest(BaseModel):
    banlist_id: int

class ComparacionListaResponse(BaseModel):
    item_id: int
    codigo: str
    descripcion: str
    marca: str
    mla_id: str
    lista_sistema: str  # Lista que tiene en nuestro sistema
    campana_ml: str  # Campaña que tiene en MercadoLibre
    precio_sistema: Optional[float]
    precio_ml: Optional[float]
    permalink: Optional[str]

    model_config = ConfigDict(from_attributes=True)

class ComparacionBaneadoResponse(BaseModel):
    id: int
    mla_id: str
    item_id: Optional[int]
    codigo: str
    descripcion: str
    marca: str
    lista_sistema: str
    motivo: Optional[str]
    usuario_nombre: str
    fecha_creacion: str

    model_config = ConfigDict(from_attributes=True)

class BanComparacionRequest(BaseModel):
    mla_id: str
    motivo: Optional[str] = None

class UnbanComparacionRequest(BaseModel):
    banlist_id: int


@router.get("/items-sin-mla", response_model=List[ItemSinMLAResponse])
async def get_items_sin_mla(
    prli_id: Optional[int] = Query(None, description="Filtrar por lista de precios específica"),
    marca: Optional[str] = Query(None, description="Filtrar por marca"),
    categoria: Optional[str] = Query(None, description="Filtrar por categoría"),
    buscar: Optional[str] = Query(None, description="Buscar en código o descripción"),
    con_stock: Optional[bool] = Query(None, description="Filtrar solo items con stock"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Obtiene todos los productos que NO tienen MLA en las listas relevantes (Clásica, Web 3, 6, 9, 12),
    excluyendo los que están en la banlist.
    """
    from app.services.permisos_service import verificar_permiso
    
    if not verificar_permiso(db, current_user, "admin.ver_items_sin_mla"):
        raise HTTPException(status_code=403, detail="No tienes permiso para ver items sin MLA")

    # IDs de las listas relevantes
    listas_relevantes = list(LISTAS_PRECIOS.keys())

    # Subquery: items en banlist
    items_baneados_subq = db.query(
        ItemSinMLABanlist.item_id
    ).subquery()

    # Query principal: productos activos y no baneados
    query = db.query(ProductoERP).filter(
        and_(
            ProductoERP.activo == True,
            ProductoERP.item_id.notin_(items_baneados_subq)
        )
    )

    # Aplicar filtros opcionales
    if marca:
        query = query.filter(ProductoERP.marca == marca)

    if categoria:
        query = query.filter(ProductoERP.categoria == categoria)

    if buscar:
        search_term = f"%{buscar}%"
        query = query.filter(
            or_(
                ProductoERP.codigo.ilike(search_term),
                ProductoERP.descripcion.ilike(search_term)
            )
        )

    if con_stock is not None:
        if con_stock:
            query = query.filter(ProductoERP.stock > 0)
        else:
            query = query.filter(ProductoERP.stock == 0)

    productos = query.order_by(ProductoERP.descripcion).limit(500).all()

    # Para cada producto, determinar en qué listas NO tiene MLA
    resultados = []
    for producto in productos:
        # Obtener todas las listas RELEVANTES donde este item tiene publicación
        listas_con_mla = db.query(MercadoLibreItemPublicado.prli_id).distinct().filter(
            and_(
                MercadoLibreItemPublicado.item_id == producto.item_id,
                MercadoLibreItemPublicado.prli_id.in_(listas_relevantes)
            )
        ).all()

        listas_con_mla_ids = set([l[0] for l in listas_con_mla if l[0] is not None])

        # Determinar qué pares están presentes
        # Si tiene Web O PVP, se considera que tiene el par completo
        pares_presentes = set()  # Solo usamos las listas Web para representar el par
        pares_faltantes = set()  # Las listas Web que no tienen ni Web ni PVP

        for web_id, pvp_id in LISTAS_WEB_A_PVP.items():
            tiene_web = web_id in listas_con_mla_ids
            tiene_pvp = pvp_id in listas_con_mla_ids

            if tiene_web or tiene_pvp:
                # Tiene al menos una del par, se considera presente
                pares_presentes.add(web_id)
            else:
                # No tiene ninguna del par
                pares_faltantes.add(web_id)

        # Si no le falta ningún par, no lo incluimos en los resultados
        if not pares_faltantes:
            continue

        # Si se filtra por prli_id específico, verificar que le falte ese par
        if prli_id:
            # Obtener el ID Web del par (si es PVP, obtener su Web)
            web_del_filtro = LISTAS_PVP_A_WEB.get(prli_id, prli_id)
            if web_del_filtro not in pares_faltantes:
                continue

        # Convertir IDs a nombres (solo mostramos las listas Web, no duplicar con PVP)
        # Ordenar por el orden definido
        listas_sin_mla_nombres = [LISTAS_PRECIOS[lid] for lid in sorted(pares_faltantes, key=lambda x: ORDEN_LISTAS[x])]
        listas_con_mla_nombres = [LISTAS_PRECIOS[lid] for lid in sorted(pares_presentes, key=lambda x: ORDEN_LISTAS[x])]

        resultados.append(ItemSinMLAResponse(
            item_id=producto.item_id,
            codigo=producto.codigo or "",
            descripcion=producto.descripcion or "",
            marca=producto.marca or "",
            categoria=producto.categoria,
            stock=producto.stock or 0,
            listas_sin_mla=listas_sin_mla_nombres,
            listas_con_mla=listas_con_mla_nombres
        ))

    return resultados


@router.get("/items-baneados", response_model=List[ItemBaneadoResponse])
async def get_items_baneados(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Obtiene todos los items en la banlist (que no deben aparecer en el reporte de sin MLA)
    """
    from app.services.permisos_service import verificar_permiso
    
    if not verificar_permiso(db, current_user, "admin.gestionar_items_sin_mla_banlist"):
        raise HTTPException(status_code=403, detail="No tienes permiso para gestionar la banlist de items sin MLA")

    baneados = db.query(
        ItemSinMLABanlist,
        ProductoERP,
        Usuario
    ).join(
        ProductoERP, ProductoERP.item_id == ItemSinMLABanlist.item_id
    ).join(
        Usuario, Usuario.id == ItemSinMLABanlist.usuario_id
    ).order_by(ItemSinMLABanlist.fecha_creacion.desc()).all()

    resultados = []
    for banlist_entry, producto, usuario in baneados:
        resultados.append(ItemBaneadoResponse(
            id=banlist_entry.id,
            item_id=producto.item_id,
            codigo=producto.codigo or "",
            descripcion=producto.descripcion or "",
            marca=producto.marca or "",
            motivo=banlist_entry.motivo,
            usuario_nombre=usuario.nombre,
            fecha_creacion=banlist_entry.fecha_creacion.isoformat()
        ))

    return resultados


@router.post("/banear-item")
async def banear_item(
    request: BanItemRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Agrega un item a la banlist para que no aparezca en el reporte de items sin MLA
    """
    from app.services.permisos_service import verificar_permiso
    
    if not verificar_permiso(db, current_user, "admin.gestionar_items_sin_mla_banlist"):
        raise HTTPException(status_code=403, detail="No tienes permiso para gestionar la banlist de items sin MLA")

    # Verificar que el item existe
    producto = db.query(ProductoERP).filter(ProductoERP.item_id == request.item_id).first()
    if not producto:
        raise HTTPException(status_code=404, detail="Producto no encontrado")

    # Verificar que no esté ya baneado
    existente = db.query(ItemSinMLABanlist).filter(
        ItemSinMLABanlist.item_id == request.item_id
    ).first()

    if existente:
        raise HTTPException(status_code=400, detail="El item ya está en la banlist")

    # Crear entrada en banlist
    nuevo_ban = ItemSinMLABanlist(
        item_id=request.item_id,
        motivo=request.motivo,
        usuario_id=current_user.id
    )

    db.add(nuevo_ban)
    db.commit()
    db.refresh(nuevo_ban)

    return {
        "success": True,
        "message": f"Item {request.item_id} agregado a la banlist",
        "banlist_id": nuevo_ban.id
    }


@router.post("/desbanear-item")
async def desbanear_item(
    request: UnbanItemRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Quita un item de la banlist
    """
    from app.services.permisos_service import verificar_permiso
    
    if not verificar_permiso(db, current_user, "admin.gestionar_items_sin_mla_banlist"):
        raise HTTPException(status_code=403, detail="No tienes permiso para gestionar la banlist de items sin MLA")

    # Buscar la entrada en banlist
    ban_entry = db.query(ItemSinMLABanlist).filter(
        ItemSinMLABanlist.id == request.banlist_id
    ).first()

    if not ban_entry:
        raise HTTPException(status_code=404, detail="Entrada de banlist no encontrada")

    item_id = ban_entry.item_id

    # Eliminar de banlist
    db.delete(ban_entry)
    db.commit()

    return {
        "success": True,
        "message": f"Item {item_id} removido de la banlist"
    }


@router.get("/listas-precios")
async def get_listas_precios(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Obtiene las listas de precios relevantes (solo Web, sin PVP duplicado)
    """

    # Solo devolver las listas Web (las claves de LISTAS_WEB_A_PVP)
    return [
        {"prli_id": web_id, "nombre": LISTAS_PRECIOS[web_id]}
        for web_id in sorted(LISTAS_WEB_A_PVP.keys())
    ]


@router.get("/marcas")
async def get_marcas_sin_mla(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Obtiene las marcas de productos sin MLA (para filtros)
    """

    # Items con MLA
    items_con_mla_subq = db.query(
        MercadoLibreItemPublicado.item_id
    ).distinct().filter(
        MercadoLibreItemPublicado.item_id.isnot(None)
    ).subquery()

    # Items baneados
    items_baneados_subq = db.query(
        ItemSinMLABanlist.item_id
    ).subquery()

    # Marcas de productos sin MLA y no baneados
    marcas = db.query(
        ProductoERP.marca
    ).distinct().filter(
        and_(
            ProductoERP.activo == True,
            ProductoERP.marca.isnot(None),
            ProductoERP.item_id.notin_(items_con_mla_subq),
            ProductoERP.item_id.notin_(items_baneados_subq)
        )
    ).order_by(ProductoERP.marca).all()

    return [{"marca": m[0]} for m in marcas if m[0]]


# Mapeo de campañas ML a listas del sistema
CAMPANA_ML_A_LISTA_SISTEMA = {
    "Clásica": ["Clásica"],
    "6x_campaign": ["6 Cuotas"],
    "3x_campaign": ["3 Cuotas"],
    "9x_campaign": ["9 Cuotas"],
    "12x_campaign": ["12 Cuotas"],
    "-": []  # Sin campaña
}

# Mapeo de listas del sistema a campañas ML esperadas
LISTA_SISTEMA_A_CAMPANA_ML = {
    "Clásica": "Clásica",
    "3 Cuotas": "3x_campaign",
    "6 Cuotas": "6x_campaign",
    "9 Cuotas": "9x_campaign",
    "12 Cuotas": "12x_campaign"
}


@router.get("/comparacion-listas", response_model=List[ComparacionListaResponse])
async def get_comparacion_listas(
    buscar: Optional[str] = Query(None, description="Buscar en código o descripción"),
    marca: Optional[str] = Query(None, description="Filtrar por marca"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Compara las listas/campañas del sistema con las campañas de MercadoLibre
    Devuelve solo los items donde HAY DIFERENCIAS (no coinciden)
    """
    from app.services.permisos_service import verificar_permiso
    
    if not verificar_permiso(db, current_user, "admin.ver_comparacion_listas_ml"):
        raise HTTPException(status_code=403, detail="No tienes permiso para ver la comparación de listas")

    # Subquery: mla_ids baneados en la banlist de comparación
    mla_baneados_subq = db.query(
        ComparacionListasBanlist.mla_id
    ).subquery()
    
    # Subquery para obtener el snapshot más reciente de cada publicación (sin filtrar por fecha)
    latest_snapshots = db.query(
        MLPublicationSnapshot.mla_id,
        func.max(MLPublicationSnapshot.snapshot_date).label('max_date')
    ).group_by(MLPublicationSnapshot.mla_id).subquery()

    # Query principal: obtener snapshots con sus publicaciones
    query = db.query(
        MLPublicationSnapshot,
        MercadoLibreItemPublicado,
        ProductoERP
    ).join(
        latest_snapshots,
        and_(
            MLPublicationSnapshot.mla_id == latest_snapshots.c.mla_id,
            MLPublicationSnapshot.snapshot_date == latest_snapshots.c.max_date
        )
    ).join(
        MercadoLibreItemPublicado,
        MercadoLibreItemPublicado.mlp_publicationID == MLPublicationSnapshot.mla_id
    ).join(
        ProductoERP,
        ProductoERP.item_id == MercadoLibreItemPublicado.item_id
    ).filter(
        MLPublicationSnapshot.mla_id.notin_(mla_baneados_subq)
    )

    # Aplicar filtros opcionales
    if buscar:
        search_term = f"%{buscar}%"
        query = query.filter(
            or_(
                ProductoERP.codigo.ilike(search_term),
                ProductoERP.descripcion.ilike(search_term)
            )
        )

    if marca:
        query = query.filter(ProductoERP.marca == marca)

    resultados_query = query.all()

    # Filtrar solo las diferencias
    diferencias = []
    for snapshot, publicacion, producto in resultados_query:
        # Obtener la lista del sistema
        prli_id = publicacion.prli_id
        lista_sistema = LISTAS_PRECIOS.get(prli_id)

        # Si no está en las listas relevantes, saltar
        if not lista_sistema:
            continue

        # Obtener la campaña de ML
        campana_ml_raw = snapshot.installments_campaign or "-"

        # Limpiar la campaña ML:
        # 1. Si tiene pipe (|), dividir y filtrar
        # 2. Omitir cualquier campaña que sea de mshops_ (ya no existen)
        # 3. Tomar la primera campaña válida
        if '|' in campana_ml_raw:
            campanas = campana_ml_raw.split('|')
            # Filtrar las que NO son mshops_
            campanas_validas = [c for c in campanas if not c.startswith('mshops_')]
            campana_ml = campanas_validas[0] if campanas_validas else "-"
        elif campana_ml_raw.startswith('mshops_'):
            # Si es solo mshops_, omitirla (no comparar)
            continue
        else:
            campana_ml = campana_ml_raw

        # Verificar si coinciden
        campana_esperada = LISTA_SISTEMA_A_CAMPANA_ML.get(lista_sistema)

        # Si NO coinciden, agregar a diferencias
        if campana_esperada != campana_ml:
            diferencias.append(ComparacionListaResponse(
                item_id=producto.item_id,
                codigo=producto.codigo or "",
                descripcion=producto.descripcion or "",
                marca=producto.marca or "",
                mla_id=snapshot.mla_id,
                lista_sistema=lista_sistema,
                campana_ml=campana_ml,
                precio_sistema=float(publicacion.mlp_price) if publicacion.mlp_price else None,
                precio_ml=float(snapshot.price) if snapshot.price else None,
                permalink=snapshot.permalink
            ))

    return diferencias


@router.get("/comparacion-baneados", response_model=List[ComparacionBaneadoResponse])
async def get_comparacion_baneados(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Obtiene todos los items en la banlist de comparación de listas
    """
    from app.services.permisos_service import verificar_permiso

    if not verificar_permiso(db, current_user, "admin.gestionar_comparacion_banlist"):
        raise HTTPException(status_code=403, detail="No tienes permiso para gestionar la banlist de comparación")

    baneados = db.query(
        ComparacionListasBanlist,
        Usuario
    ).join(
        Usuario, Usuario.id == ComparacionListasBanlist.usuario_id
    ).order_by(ComparacionListasBanlist.fecha_creacion.desc()).all()

    resultados = []
    for banlist_entry, usuario in baneados:
        # Buscar info del producto a través de la publicación
        publicacion = db.query(
            MercadoLibreItemPublicado,
            ProductoERP
        ).join(
            ProductoERP, ProductoERP.item_id == MercadoLibreItemPublicado.item_id
        ).filter(
            MercadoLibreItemPublicado.mlp_publicationID == banlist_entry.mla_id
        ).first()

        if publicacion:
            pub, producto = publicacion
            lista_sistema = LISTAS_PRECIOS.get(pub.prli_id, "Desconocida")
            resultados.append(ComparacionBaneadoResponse(
                id=banlist_entry.id,
                mla_id=banlist_entry.mla_id,
                item_id=producto.item_id,
                codigo=producto.codigo or "",
                descripcion=producto.descripcion or "",
                marca=producto.marca or "",
                lista_sistema=lista_sistema,
                motivo=banlist_entry.motivo,
                usuario_nombre=usuario.nombre,
                fecha_creacion=banlist_entry.fecha_creacion.isoformat()
            ))
        else:
            # La publicación ya no existe, pero el ban sí
            resultados.append(ComparacionBaneadoResponse(
                id=banlist_entry.id,
                mla_id=banlist_entry.mla_id,
                item_id=None,
                codigo="",
                descripcion="(publicación no encontrada)",
                marca="",
                lista_sistema="",
                motivo=banlist_entry.motivo,
                usuario_nombre=usuario.nombre,
                fecha_creacion=banlist_entry.fecha_creacion.isoformat()
            ))

    return resultados


@router.post("/banear-comparacion")
async def banear_comparacion(
    request: BanComparacionRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Agrega una publicación MLA a la banlist de comparación de listas
    """
    from app.services.permisos_service import verificar_permiso

    if not verificar_permiso(db, current_user, "admin.gestionar_comparacion_banlist"):
        raise HTTPException(status_code=403, detail="No tienes permiso para gestionar la banlist de comparación")

    # Verificar que no esté ya baneado
    existente = db.query(ComparacionListasBanlist).filter(
        ComparacionListasBanlist.mla_id == request.mla_id
    ).first()

    if existente:
        raise HTTPException(status_code=400, detail="La publicación ya está en la banlist de comparación")

    nuevo_ban = ComparacionListasBanlist(
        mla_id=request.mla_id,
        motivo=request.motivo,
        usuario_id=current_user.id
    )

    db.add(nuevo_ban)
    db.commit()
    db.refresh(nuevo_ban)

    return {
        "success": True,
        "message": f"Publicación {request.mla_id} agregada a la banlist de comparación",
        "banlist_id": nuevo_ban.id
    }


@router.post("/desbanear-comparacion")
async def desbanear_comparacion(
    request: UnbanComparacionRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Quita una publicación MLA de la banlist de comparación de listas
    """
    from app.services.permisos_service import verificar_permiso

    if not verificar_permiso(db, current_user, "admin.gestionar_comparacion_banlist"):
        raise HTTPException(status_code=403, detail="No tienes permiso para gestionar la banlist de comparación")

    ban_entry = db.query(ComparacionListasBanlist).filter(
        ComparacionListasBanlist.id == request.banlist_id
    ).first()

    if not ban_entry:
        raise HTTPException(status_code=404, detail="Entrada de banlist no encontrada")

    mla_id = ban_entry.mla_id

    db.delete(ban_entry)
    db.commit()

    return {
        "success": True,
        "message": f"Publicación {mla_id} removida de la banlist de comparación"
    }
