"""
Endpoints para gestión de markups de tienda
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func, text
from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel, ConfigDict

from app.core.database import get_db
from app.api.deps import get_current_user
from app.models.usuario import Usuario
from app.models.markup_tienda import MarkupTiendaBrand, MarkupTiendaProducto, TiendaConfig
from app.models.producto import ProductoERP, ProductoPricing
from app.services.permisos_service import verificar_permiso
from app.services.pricing_calculator import obtener_tipo_cambio_actual, convertir_a_pesos, obtener_constantes_pricing
from app.api.endpoints.productos_shared import computar_precio_sugerido

router = APIRouter(prefix="/markups-tienda", tags=["markups-tienda"])


# =============================================================================
# SCHEMAS
# =============================================================================


class MarkupBrandCreate(BaseModel):
    comp_id: int
    brand_id: int
    brand_desc: Optional[str] = None
    markup_porcentaje: float
    markup_sugerido: Optional[float] = None
    activo: bool = True
    notas: Optional[str] = None


class MarkupBrandUpdate(BaseModel):
    markup_porcentaje: Optional[float] = None
    markup_sugerido: Optional[float] = None
    activo: Optional[bool] = None
    notas: Optional[str] = None


class MarkupBrandResponse(BaseModel):
    id: int
    comp_id: int
    brand_id: int
    brand_desc: Optional[str]
    markup_porcentaje: float
    markup_sugerido: Optional[float] = None
    activo: bool
    notas: Optional[str]
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class BrandWithMarkup(BaseModel):
    """Marca con información de markup si existe"""

    comp_id: int
    brand_id: int
    brand_desc: str
    markup_id: Optional[int] = None
    markup_porcentaje: Optional[float] = None
    markup_sugerido: Optional[float] = None
    markup_activo: Optional[bool] = None
    markup_notas: Optional[str] = None


class MarkupProductoCreate(BaseModel):
    item_id: int
    codigo: Optional[str] = None
    descripcion: Optional[str] = None
    marca: Optional[str] = None
    markup_porcentaje: float
    markup_sugerido: Optional[float] = None
    activo: bool = True
    notas: Optional[str] = None


class MarkupProductoResponse(BaseModel):
    id: int
    item_id: int
    codigo: Optional[str]
    descripcion: Optional[str]
    marca: Optional[str]
    markup_porcentaje: float
    markup_sugerido: Optional[float] = None
    activo: bool
    notas: Optional[str]
    markup_id: Optional[int] = None  # Alias para compatibilidad con el frontend

    model_config = ConfigDict(from_attributes=True)


class MarkupSugeridoUpdate(BaseModel):
    """Request body for PATCH /productos/{item_id}/markup-sugerido.

    Set markup_sugerido to a float to upsert; pass null/None to clear (delete) the product row.
    """

    markup_sugerido: Optional[float] = None


class MarkupSugeridoResponse(BaseModel):
    """Response for PATCH /productos/{item_id}/markup-sugerido."""

    item_id: int
    markup_sugerido_valor: Optional[float]
    markup_sugerido_total: Optional[float]
    markup_sugerido_origen: Optional[str]
    precio_sugerido_sin_iva: Optional[float]
    precio_sugerido_con_iva: Optional[float]


# =============================================================================
# ENDPOINTS
# =============================================================================


@router.get("/brands", response_model=List[BrandWithMarkup])
def listar_brands_con_markups(
    busqueda: Optional[str] = None,
    solo_con_markup: bool = False,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """
    Lista todas las marcas con sus markups asignados (si tienen).
    Permite búsqueda por nombre de marca.
    """
    if not verificar_permiso(db, current_user, "productos.gestionar_markups_tienda"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="No tienes permiso para gestionar markups de tienda"
        )

    # Query base para obtener marcas de tb_brand
    params = {}
    where_clause = ""
    if busqueda:
        where_clause = "AND LOWER(b.brand_desc) LIKE LOWER(:busqueda)"
        params["busqueda"] = f"%{busqueda}%"

    query = db.execute(
        text(f"""
        SELECT DISTINCT
            b.comp_id,
            b.brand_id,
            b.brand_desc,
            m.id as markup_id,
            m.markup_porcentaje,
            m.markup_sugerido,
            m.activo as markup_activo,
            m.notas as markup_notas
        FROM tb_brand b
        LEFT JOIN markups_tienda_brand m ON b.comp_id = m.comp_id AND b.brand_id = m.brand_id
        WHERE 1=1
        {where_clause}
        ORDER BY b.brand_desc
    """),
        params,
    )

    results = []
    for row in query:
        # Si solo_con_markup es True, filtrar solo los que tienen markup
        if solo_con_markup and row.markup_id is None:
            continue

        results.append(
            BrandWithMarkup(
                comp_id=row.comp_id,
                brand_id=row.brand_id,
                brand_desc=row.brand_desc,
                markup_id=row.markup_id,
                markup_porcentaje=row.markup_porcentaje,
                markup_sugerido=row.markup_sugerido,
                markup_activo=row.markup_activo,
                markup_notas=row.markup_notas,
            )
        )

    return results


@router.post("/brands/{comp_id}/{brand_id}/markup", response_model=MarkupBrandResponse)
def crear_o_actualizar_markup_brand(
    comp_id: int,
    brand_id: int,
    data: MarkupBrandCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """
    Crea o actualiza el markup para una marca específica.
    """
    if not verificar_permiso(db, current_user, "productos.gestionar_markups_tienda"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="No tienes permiso para gestionar markups de tienda"
        )

    # Verificar si ya existe un markup para esta marca
    existing = (
        db.query(MarkupTiendaBrand)
        .filter(MarkupTiendaBrand.comp_id == comp_id, MarkupTiendaBrand.brand_id == brand_id)
        .first()
    )

    if existing:
        # Actualizar existente
        existing.markup_porcentaje = data.markup_porcentaje
        existing.markup_sugerido = data.markup_sugerido
        existing.activo = data.activo
        existing.notas = data.notas
        existing.brand_desc = data.brand_desc
        existing.updated_by_id = current_user.id
        db.commit()
        db.refresh(existing)
        return existing
    else:
        # Crear nuevo
        nuevo_markup = MarkupTiendaBrand(
            comp_id=data.comp_id,
            brand_id=data.brand_id,
            brand_desc=data.brand_desc,
            markup_porcentaje=data.markup_porcentaje,
            markup_sugerido=data.markup_sugerido,
            activo=data.activo,
            notas=data.notas,
            created_by_id=current_user.id,
        )
        db.add(nuevo_markup)
        db.commit()
        db.refresh(nuevo_markup)
        return nuevo_markup


@router.delete("/brands/{comp_id}/{brand_id}/markup")
def eliminar_markup_brand(
    comp_id: int, brand_id: int, db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)
):
    """
    Elimina el markup de una marca específica.
    """
    if not verificar_permiso(db, current_user, "productos.gestionar_markups_tienda"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="No tienes permiso para gestionar markups de tienda"
        )

    markup = (
        db.query(MarkupTiendaBrand)
        .filter(MarkupTiendaBrand.comp_id == comp_id, MarkupTiendaBrand.brand_id == brand_id)
        .first()
    )

    if not markup:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Markup no encontrado")

    db.delete(markup)
    db.commit()

    return {"success": True, "message": "Markup eliminado correctamente"}


@router.get("/stats")
def obtener_estadisticas_markups(db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    """
    Obtiene estadísticas de los markups configurados.
    """
    if not verificar_permiso(db, current_user, "productos.gestionar_markups_tienda"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="No tienes permiso para gestionar markups de tienda"
        )

    total_marcas = db.execute(text("SELECT COUNT(DISTINCT brand_id) FROM tb_brand")).scalar()
    total_con_markup = db.query(func.count(MarkupTiendaBrand.id)).filter(MarkupTiendaBrand.activo == True).scalar()
    total_inactivos = db.query(func.count(MarkupTiendaBrand.id)).filter(MarkupTiendaBrand.activo == False).scalar()

    markup_promedio = (
        db.query(func.avg(MarkupTiendaBrand.markup_porcentaje)).filter(MarkupTiendaBrand.activo == True).scalar()
    )

    # Estadísticas de productos
    total_productos_con_markup = (
        db.query(func.count(MarkupTiendaProducto.id)).filter(MarkupTiendaProducto.activo == True).scalar()
    )

    return {
        "total_marcas": total_marcas,
        "total_con_markup": total_con_markup,
        "total_sin_markup": total_marcas - total_con_markup - total_inactivos,
        "total_inactivos": total_inactivos,
        "markup_promedio": round(float(markup_promedio or 0), 2),
        "total_productos_con_markup": total_productos_con_markup,
    }


# =============================================================================
# ENDPOINTS PRODUCTOS INDIVIDUALES
# =============================================================================


@router.get("/productos", response_model=List[MarkupProductoResponse])
def listar_productos_con_markup(db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    """
    Lista todos los productos con markups individuales configurados.
    """
    if not verificar_permiso(db, current_user, "productos.gestionar_markups_tienda"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="No tienes permiso para gestionar markups de tienda"
        )

    productos = (
        db.query(MarkupTiendaProducto)
        .filter(MarkupTiendaProducto.activo == True)
        .order_by(MarkupTiendaProducto.codigo)
        .all()
    )

    return [
        MarkupProductoResponse(
            id=p.id,
            item_id=p.item_id,
            codigo=p.codigo,
            descripcion=p.descripcion,
            marca=p.marca,
            markup_porcentaje=p.markup_porcentaje,
            markup_sugerido=p.markup_sugerido,
            activo=p.activo,
            notas=p.notas,
            markup_id=p.id,  # Para compatibilidad con el frontend
        )
        for p in productos
    ]


@router.post("/productos/{item_id}/markup", response_model=MarkupProductoResponse)
def crear_o_actualizar_markup_producto(
    item_id: int,
    data: MarkupProductoCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """
    Crea o actualiza el markup para un producto específico.
    """
    if not verificar_permiso(db, current_user, "productos.gestionar_markups_tienda"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="No tienes permiso para gestionar markups de tienda"
        )

    # Verificar si ya existe un markup para este producto
    existing = db.query(MarkupTiendaProducto).filter(MarkupTiendaProducto.item_id == item_id).first()

    if existing:
        # Actualizar existente
        existing.markup_porcentaje = data.markup_porcentaje
        existing.markup_sugerido = data.markup_sugerido
        existing.activo = data.activo
        existing.notas = data.notas
        existing.codigo = data.codigo
        existing.descripcion = data.descripcion
        existing.marca = data.marca
        existing.updated_by_id = current_user.id
        db.commit()
        db.refresh(existing)
        return MarkupProductoResponse(
            id=existing.id,
            item_id=existing.item_id,
            codigo=existing.codigo,
            descripcion=existing.descripcion,
            marca=existing.marca,
            markup_porcentaje=existing.markup_porcentaje,
            markup_sugerido=existing.markup_sugerido,
            activo=existing.activo,
            notas=existing.notas,
            markup_id=existing.id,
        )
    else:
        # Crear nuevo
        nuevo_markup = MarkupTiendaProducto(
            item_id=data.item_id,
            codigo=data.codigo,
            descripcion=data.descripcion,
            marca=data.marca,
            markup_porcentaje=data.markup_porcentaje,
            markup_sugerido=data.markup_sugerido,
            activo=data.activo,
            notas=data.notas,
            created_by_id=current_user.id,
        )
        db.add(nuevo_markup)
        db.commit()
        db.refresh(nuevo_markup)
        return MarkupProductoResponse(
            id=nuevo_markup.id,
            item_id=nuevo_markup.item_id,
            codigo=nuevo_markup.codigo,
            descripcion=nuevo_markup.descripcion,
            marca=nuevo_markup.marca,
            markup_porcentaje=nuevo_markup.markup_porcentaje,
            markup_sugerido=nuevo_markup.markup_sugerido,
            activo=nuevo_markup.activo,
            notas=nuevo_markup.notas,
            markup_id=nuevo_markup.id,
        )


@router.delete("/productos/{item_id}/markup")
def eliminar_markup_producto(
    item_id: int, db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)
):
    """
    Elimina el markup de un producto específico.
    """
    if not verificar_permiso(db, current_user, "productos.gestionar_markups_tienda"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="No tienes permiso para gestionar markups de tienda"
        )

    markup = db.query(MarkupTiendaProducto).filter(MarkupTiendaProducto.item_id == item_id).first()

    if not markup:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Markup no encontrado")

    db.delete(markup)
    db.commit()

    return {"success": True, "message": "Markup eliminado correctamente"}


@router.patch("/productos/{item_id}/markup-sugerido", response_model=MarkupSugeridoResponse)
def actualizar_markup_sugerido(
    item_id: int,
    data: MarkupSugeridoUpdate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> MarkupSugeridoResponse:
    """
    Set or clear the individual suggested markup (markup_sugerido) for a single product.

    Business logic:
    - Requires permission `productos.gestionar_markups_tienda`.
    - The payload only touches `markup_sugerido`; `markup_porcentaje` (gremio) and all
      other fields (codigo, descripcion, marca, activo, notas) are PRESERVED on an
      existing row and are not exposed in this endpoint's request body.
    - Clear path (markup_sugerido is None): the markups_tienda_producto row is deleted,
      causing the listing to fall back to brand-level or null sugerido.
      Clearing a non-existent row is idempotent (returns 200, no error).
    - Set path: rounds the value to 2 decimal places before persisting.
      When no product row exists yet, it is created and markup_porcentaje is set to the
      currently resolved gremio value (brand override or 0.0).
      INTENTIONAL: creating a row freezes the product's gremio markup at the current
      resolved brand/default value at the time of the first sugerido edit.
    - Returns recomputed precio_sugerido and markup_sugerido_total using the same
      formula as the Tienda listing (shared helper computar_precio_sugerido).

    Returns 403 if the user lacks the required permission.
    Returns 404 if item_id is not found in productos_erp.
    """
    if not verificar_permiso(db, current_user, "productos.gestionar_markups_tienda"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para gestionar markups de tienda",
        )

    # 404 guard + fetch product data for recompute
    producto = db.query(ProductoERP).filter(ProductoERP.item_id == item_id).first()
    if not producto:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Producto no encontrado",
        )

    existing = db.query(MarkupTiendaProducto).filter(MarkupTiendaProducto.item_id == item_id).first()

    # --- Clear path ---
    if data.markup_sugerido is None:
        if existing:
            db.delete(existing)
            db.commit()
        # After clear: resolve origin and sugerido from brand (if any)
        markup_sugerido_valor, markup_sugerido_origen = _resolver_sugerido_marca(db, producto.marca)
        return _build_markup_sugerido_response(
            db=db,
            producto=producto,
            item_id=item_id,
            markup_sugerido_valor=markup_sugerido_valor,
            markup_sugerido_origen=markup_sugerido_origen,
        )

    # --- Set path ---
    valor_redondeado = round(data.markup_sugerido, 2)

    if existing:
        # Update only markup_sugerido; preserve all other fields
        existing.markup_sugerido = valor_redondeado
        existing.updated_by_id = current_user.id
    else:
        # Resolve current gremio markup for this product to use as markup_porcentaje default.
        # INTENTIONAL: creating a row freezes the gremio markup at its current resolved value.
        markup_porcentaje_default = _resolver_markup_gremio(db, producto.marca)
        existing = MarkupTiendaProducto(
            item_id=item_id,
            codigo=producto.codigo,
            descripcion=producto.descripcion,
            marca=producto.marca,
            markup_porcentaje=markup_porcentaje_default,
            markup_sugerido=valor_redondeado,
            activo=True,
            created_by_id=current_user.id,
        )
        db.add(existing)

    db.commit()
    db.refresh(existing)

    return _build_markup_sugerido_response(
        db=db,
        producto=producto,
        item_id=item_id,
        markup_sugerido_valor=valor_redondeado,
        markup_sugerido_origen="producto",
    )


def _resolver_sugerido_marca(db: Session, marca: Optional[str]) -> tuple[Optional[float], Optional[str]]:
    """Resolve the effective markup_sugerido and origin from the brand row (if any)."""
    if not marca:
        return None, None
    brand_row = (
        db.query(MarkupTiendaBrand)
        .filter(MarkupTiendaBrand.brand_desc == marca, MarkupTiendaBrand.activo == True)
        .first()
    )
    if brand_row and brand_row.markup_sugerido is not None:
        return brand_row.markup_sugerido, "marca"
    return None, None


def _resolver_markup_gremio(db: Session, marca: Optional[str]) -> float:
    """Resolve the gremio markup for the product: brand override or 0.0 as fallback."""
    if marca:
        brand_row = (
            db.query(MarkupTiendaBrand)
            .filter(MarkupTiendaBrand.brand_desc == marca, MarkupTiendaBrand.activo == True)
            .first()
        )
        if brand_row:
            return brand_row.markup_porcentaje
    return 0.0


def _build_markup_sugerido_response(
    db: Session,
    producto: ProductoERP,
    item_id: int,
    markup_sugerido_valor: Optional[float],
    markup_sugerido_origen: Optional[str],
) -> MarkupSugeridoResponse:
    """Build the MarkupSugeridoResponse by recomputing precio_sugerido."""
    tipo_cambio_usd = obtener_tipo_cambio_actual(db, "USD")
    costo_ars = convertir_a_pesos(
        producto.costo or 0.0,
        producto.moneda_costo.value if hasattr(producto.moneda_costo, "value") else (producto.moneda_costo or "ARS"),
        tipo_cambio_usd,
    )
    constantes = obtener_constantes_pricing(db)
    varios_porcentaje = constantes.get("varios", 6.5)

    # Fetch markup_clasica (same as the listing uses: producto_pricing.markup_calculado)
    producto_pricing = db.query(ProductoPricing).filter(ProductoPricing.item_id == item_id).first()
    markup_clasica = producto_pricing.markup_calculado if producto_pricing else None

    iva = producto.iva if producto.iva is not None else 21.0

    precio_sin_iva, precio_con_iva, markup_sugerido_total = computar_precio_sugerido(
        costo_ars=costo_ars,
        iva=iva,
        markup_clasica=markup_clasica,
        markup_sugerido_valor=markup_sugerido_valor,
        varios_porcentaje=varios_porcentaje,
    )

    return MarkupSugeridoResponse(
        item_id=item_id,
        markup_sugerido_valor=markup_sugerido_valor,
        markup_sugerido_total=markup_sugerido_total,
        markup_sugerido_origen=markup_sugerido_origen,
        precio_sugerido_sin_iva=precio_sin_iva,
        precio_sugerido_con_iva=precio_con_iva,
    )


# =============================================================================
# ENDPOINTS CONFIGURACIÓN TIENDA
# =============================================================================


class ConfigUpdate(BaseModel):
    valor: float


@router.get("/config")
def obtener_config_tienda(db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    """
    Obtiene toda la configuración de tienda.
    """
    if not verificar_permiso(db, current_user, "productos.gestionar_markups_tienda"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="No tienes permiso para gestionar markups de tienda"
        )

    configs = db.query(TiendaConfig).all()
    return {c.clave: c.valor for c in configs}


@router.get("/config/{clave}")
def obtener_config_valor(clave: str, db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    """
    Obtiene un valor de configuración específico.
    """
    if not verificar_permiso(db, current_user, "productos.gestionar_markups_tienda"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="No tienes permiso para gestionar markups de tienda"
        )

    config = db.query(TiendaConfig).filter(TiendaConfig.clave == clave).first()
    if not config:
        return {"clave": clave, "valor": 0}
    return {"clave": config.clave, "valor": config.valor}


@router.put("/config/{clave}")
def actualizar_config_valor(
    clave: str, data: ConfigUpdate, db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)
):
    """
    Actualiza o crea un valor de configuración.
    """
    if not verificar_permiso(db, current_user, "productos.gestionar_markups_tienda"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="No tienes permiso para gestionar markups de tienda"
        )

    config = db.query(TiendaConfig).filter(TiendaConfig.clave == clave).first()
    if config:
        config.valor = data.valor
        config.updated_by_id = current_user.id
    else:
        config = TiendaConfig(clave=clave, valor=data.valor, updated_by_id=current_user.id)
        db.add(config)

    db.commit()
    db.refresh(config)

    return {"success": True, "clave": config.clave, "valor": config.valor}
