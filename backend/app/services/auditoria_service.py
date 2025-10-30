from sqlalchemy.orm import Session
from app.models.auditoria import Auditoria, TipoAccion
from app.models.usuario import Usuario
from typing import Optional, Dict, Any

def registrar_auditoria(
    db: Session,
    usuario_id: int,
    tipo_accion: TipoAccion,
    item_id: Optional[int] = None,
    valores_anteriores: Optional[Dict[str, Any]] = None,
    valores_nuevos: Optional[Dict[str, Any]] = None,
    es_masivo: bool = False,
    productos_afectados: Optional[int] = None,
    comentario: Optional[str] = None
):
    """Registra una acción en la auditoría"""
    auditoria = Auditoria(
        item_id=item_id,
        usuario_id=usuario_id,
        tipo_accion=tipo_accion,
        valores_anteriores=valores_anteriores,
        valores_nuevos=valores_nuevos,
        es_masivo=es_masivo,
        productos_afectados=productos_afectados,
        comentario=comentario
    )
    db.add(auditoria)
    db.commit()
    return auditoria
