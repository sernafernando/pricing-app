#!/usr/bin/env python3
"""
Script para sincronizar usuarios del ERP (tbUser) via gbp-parser.
Usa Export Group 88 del ERP.
"""
import sys
import os
from pathlib import Path

# Agregar el directorio raíz al path
sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx
from datetime import datetime
from sqlalchemy.orm import Session
from app.core.database import SessionLocal
from app.models.tb_user import TBUser

GBP_PARSER_URL = "http://localhost:8002/api/gbp-parser"
EXPORT_ID = 88  # tbUser en el ERP


def sync_usuarios():
    """
    Sincroniza usuarios desde el ERP Export 88
    """
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Iniciando sincronización de usuarios ERP...")
    
    db: Session = SessionLocal()
    
    try:
        # 1. Obtener datos del Export 88
        print(f"Consultando Export {EXPORT_ID} (tbUser)...")
        
        response = httpx.post(
            GBP_PARSER_URL,
            json={"intExpgr_id": EXPORT_ID},
            timeout=60.0
        )
        
        if response.status_code != 200:
            print(f"❌ Error HTTP {response.status_code}: {response.text}")
            return
        
        data = response.json()
        
        if not data or not isinstance(data, list):
            print("❌ No se obtuvieron datos del ERP")
            return
        
        print(f"✓ Obtenidos {len(data)} usuarios del ERP")
        
        # 2. Procesar usuarios
        usuarios_nuevos = 0
        usuarios_actualizados = 0
        
        for row in data:
            user_id = row.get("user_id")
            if not user_id:
                continue
            
            # Buscar si existe
            usuario = db.query(TBUser).filter(TBUser.user_id == user_id).first()
            
            # Preparar datos
            user_data = {
                "user_id": user_id,
                "user_name": f"{row.get('user_firstname', '')} {row.get('user_lastname', '')}".strip() or row.get('user_nick'),
                "user_loginname": row.get("user_nick"),
                "user_email": row.get("user_email"),
                "user_isactive": bool(row.get("user_login")) and not bool(row.get("user_Blocked")),
                "user_lastupdate": row.get("user_LastUpdate"),
            }
            
            if usuario:
                # Actualizar
                for key, value in user_data.items():
                    if key != "user_id":  # No actualizar la PK
                        setattr(usuario, key, value)
                usuarios_actualizados += 1
            else:
                # Crear nuevo
                usuario = TBUser(**user_data)
                db.add(usuario)
                usuarios_nuevos += 1
        
        # 3. Commit
        db.commit()
        
        print(f"✅ Sincronización completada:")
        print(f"   - Nuevos: {usuarios_nuevos}")
        print(f"   - Actualizados: {usuarios_actualizados}")
        print(f"   - Total en DB: {db.query(TBUser).count()}")
        
    except httpx.HTTPError as e:
        print(f"❌ Error de conexión: {e}")
        db.rollback()
    except Exception as e:
        print(f"❌ Error: {e}")
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    sync_usuarios()
