from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import List, Dict
from pydantic import BaseModel
from app.core.database import get_db
from app.core.security import get_current_user, require_role
from app.models.usuario import Usuario

router = APIRouter()

class ConfiguracionItem(BaseModel):
    clave: str
    valor: str
    descripcion: str
    tipo: str

class ConfiguracionUpdate(BaseModel):
    valor: str

@router.get("/configuracion", response_model=List[ConfiguracionItem])
async def listar_configuracion(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(lambda: require_role(["admin"]))
):
    """Lista todas las configuraciones del sistema"""
    result = db.execute(
        text("SELECT clave, valor, descripcion, tipo FROM configuracion ORDER BY clave")
    ).fetchall()

    return [
        {
            "clave": row[0],
            "valor": row[1],
            "descripcion": row[2],
            "tipo": row[3]
        }
        for row in result
    ]

@router.get("/configuracion/{clave}")
async def obtener_configuracion(
    clave: str,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Obtiene una configuración específica"""
    result = db.execute(
        text("SELECT clave, valor, descripcion, tipo FROM configuracion WHERE clave = :clave"),
        {"clave": clave}
    ).fetchone()

    if not result:
        raise HTTPException(status_code=404, detail="Configuración no encontrada")

    return {
        "clave": result[0],
        "valor": result[1],
        "descripcion": result[2],
        "tipo": result[3]
    }

@router.put("/configuracion/{clave}")
async def actualizar_configuracion(
    clave: str,
    config: ConfiguracionUpdate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(lambda: require_role(["admin"]))
):
    """Actualiza el valor de una configuración"""
    # Verificar que la configuración existe
    result = db.execute(
        text("SELECT clave FROM configuracion WHERE clave = :clave"),
        {"clave": clave}
    ).fetchone()

    if not result:
        raise HTTPException(status_code=404, detail="Configuración no encontrada")

    # Actualizar el valor
    db.execute(
        text("""
            UPDATE configuracion
            SET valor = :valor, fecha_modificacion = CURRENT_TIMESTAMP
            WHERE clave = :clave
        """),
        {"clave": clave, "valor": config.valor}
    )
    db.commit()

    return {"mensaje": "Configuración actualizada correctamente"}

@router.get("/configuracion/grupo/pricing")
async def obtener_configuracion_pricing(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Obtiene todas las configuraciones de pricing en un solo objeto"""
    result = db.execute(
        text("""
            SELECT clave, valor
            FROM configuracion
            WHERE clave IN (
                'monto_tier1', 'monto_tier2', 'monto_tier3',
                'comision_tier1', 'comision_tier2', 'comision_tier3',
                'varios_porcentaje', 'grupo_comision_default',
                'markup_adicional_cuotas'
            )
        """)
    ).fetchall()

    config = {}
    for row in result:
        config[row[0]] = float(row[1]) if row[1] else None

    return config
