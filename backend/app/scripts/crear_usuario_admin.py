import sys
sys.path.append('/var/www/html/pricing-app/backend')

from app.core.database import SessionLocal
from app.models.usuario import Usuario, RolUsuario, AuthProvider
from app.core.security import get_password_hash

def crear_admin():
    db = SessionLocal()
    
    try:
        # Verificar si ya existe
        existing = db.query(Usuario).filter(Usuario.email == "fserna@gaussonline.com.ar").first()
        
        if existing:
            print("❌ Usuario admin ya existe")
            return
        
        # Crear admin
        admin = Usuario(
            email="fserna@gaussonline.com.ar",
            nombre="Administrador",
            password_hash=get_password_hash("nKiller233"),  # Cambiar en producción
            rol=RolUsuario.ADMIN,
            auth_provider=AuthProvider.LOCAL,
            activo=True
        )
        
        db.add(admin)
        db.commit()
        
        print("✅ Usuario admin creado")
        print("   Email: fserna@gaussonline.com.ar")
        print("   Password: ********")
        print("   ⚠️  CAMBIAR PASSWORD EN PRODUCCIÓN")
        
    except Exception as e:
        db.rollback()
        print(f"❌ Error: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    crear_admin()
