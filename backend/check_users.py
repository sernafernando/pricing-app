"""
Script para ver qué usuarios existen en tb_user
"""
from app.core.database import SessionLocal
from app.models.tb_user import TBUser
from sqlalchemy import func

def main():
    db = SessionLocal()
    try:
        # Obtener todos los usuarios que tienen pedidos en export 80
        from app.models.sale_order_header import SaleOrderHeader
        
        # User IDs únicos en pedidos activos
        user_ids = db.query(SaleOrderHeader.user_id).filter(
            SaleOrderHeader.export_id == 80,
            SaleOrderHeader.export_activo == True
        ).distinct().all()
        
        print("=" * 80)
        print("USUARIOS CON PEDIDOS EN EXPORT 80:")
        print("=" * 80)
        
        for (user_id,) in sorted(user_ids, key=lambda x: x[0] if x[0] else 0):
            if user_id:
                user = db.query(TBUser).filter(TBUser.user_id == user_id).first()
                if user:
                    print(f"  {user_id:5d} → {user.user_name or '(sin nombre)'} ({user.user_loginname or '(sin login)'})")
                else:
                    print(f"  {user_id:5d} → ⚠️  NO EXISTE EN tb_user")
            else:
                print(f"  NULL  → (sin user_id)")
        
        print("\n" + "=" * 80)
        print("TODOS LOS USUARIOS EN tb_user:")
        print("=" * 80)
        
        all_users = db.query(TBUser).order_by(TBUser.user_id).all()
        for user in all_users:
            active = "✅" if user.user_isactive else "❌"
            print(f"  {active} {user.user_id:5d} → {user.user_name or '(sin nombre)'} ({user.user_loginname or '(sin login)'})")
        
    finally:
        db.close()

if __name__ == "__main__":
    main()
