from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel, ConfigDict
from typing import List, Optional
from datetime import datetime
from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.usuario import Usuario, RolUsuario
from app.models.producto_banlist import ProductoBanlist
from app.models.producto import ProductoERP
import re

router = APIRouter()

class ProductoBanlistCreate(BaseModel):
    item_ids: Optional[str] = None  # IDs separados por comas/espacios/saltos
    eans: Optional[str] = None  # EANs separados por comas/espacios/saltos
    motivo: Optional[str] = None

class ProductoBanlistResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    item_id: Optional[int]
    ean: Optional[str]
    codigo: Optional[str]
    descripcion: Optional[str]
    motivo: Optional[str]
    fecha_creacion: datetime
    activo: bool
    usuario_nombre: Optional[str]

@router.get("/producto-banlist", response_model=List[ProductoBanlistResponse])
async def listar_banlist(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Lista todos los productos baneados"""
    productos = db.query(ProductoBanlist).filter(ProductoBanlist.activo == True).all()

    resultado = []
    for prod in productos:
        # Buscar info del producto en ERP
        producto_erp = None
        if prod.item_id:
            producto_erp = db.query(ProductoERP).filter(ProductoERP.item_id == prod.item_id).first()
        elif prod.ean:
            producto_erp = db.query(ProductoERP).filter(ProductoERP.ean == prod.ean).first()

        # Buscar usuario que baneó
        usuario_nombre = None
        if prod.usuario_id:
            usuario = db.query(Usuario).filter(Usuario.id == prod.usuario_id).first()
            if usuario:
                usuario_nombre = usuario.nombre

        resultado.append({
            "id": prod.id,
            "item_id": prod.item_id,
            "ean": prod.ean,
            "codigo": producto_erp.codigo if producto_erp else None,
            "descripcion": producto_erp.descripcion if producto_erp else None,
            "motivo": prod.motivo,
            "fecha_creacion": prod.fecha_creacion,
            "activo": prod.activo,
            "usuario_nombre": usuario_nombre
        })

    return resultado

@router.post("/producto-banlist")
async def agregar_a_banlist(
    datos: ProductoBanlistCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Agrega uno o múltiples productos a la banlist por item_id o EAN"""

    agregados = []
    duplicados = []
    no_encontrados = []

    # Procesar item_ids
    if datos.item_ids:
        ids_input = re.split(r'[,\s\n]+', datos.item_ids)

        for id_input in ids_input:
            if not id_input.strip():
                continue

            try:
                item_id = int(id_input.strip())
            except ValueError:
                no_encontrados.append(f"ID inválido: {id_input}")
                continue

            # Verificar que el producto existe en ERP
            producto_erp = db.query(ProductoERP).filter(ProductoERP.item_id == item_id).first()
            if not producto_erp:
                no_encontrados.append(f"Item ID {item_id} no encontrado en ERP")
                continue

            # Verificar si ya existe en banlist (activo o inactivo)
            existe = db.query(ProductoBanlist).filter(
                ProductoBanlist.item_id == item_id
            ).first()

            if existe:
                if existe.activo:
                    duplicados.append(f"Item ID {item_id}")
                    continue
                else:
                    # Reactivar registro existente
                    existe.activo = True
                    existe.motivo = datos.motivo
                    existe.usuario_id = current_user.id
                    agregados.append(f"Item ID {item_id} - {producto_erp.descripcion[:50] if producto_erp.descripcion else ''} (reactivado)")
            else:
                # Crear nuevo registro
                nuevo_prod = ProductoBanlist(
                    item_id=item_id,
                    motivo=datos.motivo,
                    activo=True,
                    usuario_id=current_user.id
                )
                db.add(nuevo_prod)
                agregados.append(f"Item ID {item_id} - {producto_erp.descripcion[:50] if producto_erp.descripcion else ''}")

    # Procesar EANs
    if datos.eans:
        eans_input = re.split(r'[,\s\n]+', datos.eans)

        for ean_input in eans_input:
            ean = ean_input.strip()
            if not ean:
                continue

            # Verificar que el producto existe en ERP
            producto_erp = db.query(ProductoERP).filter(ProductoERP.ean == ean).first()
            if not producto_erp:
                no_encontrados.append(f"EAN {ean} no encontrado en ERP")
                continue

            # Verificar si ya existe en banlist (activo o inactivo)
            existe = db.query(ProductoBanlist).filter(
                ProductoBanlist.ean == ean
            ).first()

            if existe:
                if existe.activo:
                    duplicados.append(f"EAN {ean}")
                    continue
                else:
                    # Reactivar registro existente
                    existe.activo = True
                    existe.motivo = datos.motivo
                    existe.usuario_id = current_user.id
                    agregados.append(f"EAN {ean} - {producto_erp.descripcion[:50] if producto_erp.descripcion else ''} (reactivado)")
            else:
                # Crear nuevo registro
                nuevo_prod = ProductoBanlist(
                    ean=ean,
                    motivo=datos.motivo,
                    activo=True,
                    usuario_id=current_user.id
                )
                db.add(nuevo_prod)
                agregados.append(f"EAN {ean} - {producto_erp.descripcion[:50] if producto_erp.descripcion else ''}")

    db.commit()

    return {
        "mensaje": "Productos procesados",
        "agregados": agregados,
        "duplicados": duplicados,
        "no_encontrados": no_encontrados,
        "total_agregados": len(agregados)
    }

@router.delete("/producto-banlist/{producto_id}")
async def eliminar_de_banlist(
    producto_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Elimina un producto de la banlist (solo admin/superadmin)"""
    if current_user.rol not in [RolUsuario.ADMIN, RolUsuario.SUPERADMIN]:
        raise HTTPException(403, "Solo administradores pueden eliminar de la banlist")

    producto = db.query(ProductoBanlist).filter(ProductoBanlist.id == producto_id).first()
    if not producto:
        raise HTTPException(404, "Producto no encontrado en banlist")

    identificador = f"Item ID {producto.item_id}" if producto.item_id else f"EAN {producto.ean}"

    # Eliminar físicamente de la base de datos
    db.delete(producto)
    db.commit()

    return {"mensaje": f"Producto {identificador} eliminado de la banlist"}
