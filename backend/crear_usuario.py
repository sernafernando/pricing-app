#!/usr/bin/env python3
import sys
sys.path.insert(0, '/var/www/html/pricing-app/backend')

from app.core.database import SessionLocal
from app.models.usuario import Usuario
from passlib.context import CryptContext

def crear_usuario():
    print("=== CREAR NUEVO USUARIO ===\n")
    
    email = input("Email: ").strip()
    nombre = input("Nombre completo: ").strip()
    password = input("Contraseña: ").strip()
    es_admin = input("¿Es admin? (s/n): ").strip().lower() == 's'
    
    if not email or not nombre or not password:
        print("❌ Todos los campos son obligatorios")
        return
    
    db = SessionLocal()
    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
    
    # Verificar si ya existe
    existe = db.query(Usuario).filter(Usuario.email == email).first()
    if existe:
        print(f"❌ El email '{email}' ya existe")
        db.close()
        return
    
    # Crear usuario
    nuevo_usuario = Usuario(
        email=email,
        nombre=nombre,
        password_hash=pwd_context.hash(password),
        rol='admin' if es_admin else 'user',
        auth_provider='local',
        activo=True
    )
    
    db.add(nuevo_usuario)
    db.commit()
    
    print(f"\n✅ Usuario creado exitosamente:")
    print(f"   Email: {nuevo_usuario.email}")
    print(f"   Nombre: {nuevo_usuario.nombre}")
    print(f"   Rol: {nuevo_usuario.rol}")
    
    db.close()

if __name__ == "__main__":
    try:
        crear_usuario()
    except KeyboardInterrupt:
        print("\n\n❌ Cancelado")
    except Exception as e:
        print(f"\n❌ Error: {e}")
