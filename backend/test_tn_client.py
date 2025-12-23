#!/usr/bin/env python3
"""
Script de prueba para verificar TiendaNube Order Client
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.services.tienda_nube_order_client import TiendaNubeOrderClient


async def test_tn_client():
    """Prueba el cliente de TiendaNube"""
    print("🧪 Probando TiendaNube Order Client...")
    
    client = TiendaNubeOrderClient()
    
    if not client.base_url:
        print("❌ TN_STORE_ID o TN_ACCESS_TOKEN no configurados en .env")
        print("   Configurá las variables de entorno primero:")
        print("   TN_STORE_ID=XXXXX")
        print("   TN_ACCESS_TOKEN=your_token")
        return
    
    print(f"✅ Cliente inicializado: {client.base_url}")
    
    # Obtener un order_id de prueba desde la DB
    from app.core.database import SessionLocal
    from app.models.sale_order_header import SaleOrderHeader
    from sqlalchemy import and_
    
    db = SessionLocal()
    
    pedido_test = db.query(SaleOrderHeader).filter(
        and_(
            SaleOrderHeader.user_id == 50021,
            SaleOrderHeader.ws_internalid.isnot(None)
        )
    ).first()
    
    if not pedido_test:
        print("❌ No hay pedidos TN en la DB para probar")
        db.close()
        return
    
    print(f"\n📦 Pedido de prueba:")
    print(f"   - soh_id: {pedido_test.soh_id}")
    print(f"   - ws_internalid (TN order ID): {pedido_test.ws_internalid}")
    
    try:
        tn_order_id = int(pedido_test.ws_internalid)
        print(f"\n🔍 Consultando TN API para orden {tn_order_id}...")
        
        tn_data = await client.get_order_details(tn_order_id)
        
        if tn_data:
            print(f"\n✅ Datos obtenidos de TiendaNube:")
            print(f"   - Order Number: {tn_data.get('number')}")
            print(f"   - Order ID: {tn_data.get('id')}")
            
            shipping = tn_data.get('shipping_address', {})
            if shipping:
                print(f"\n📬 Dirección de envío:")
                print(f"   - Nombre: {shipping.get('name')}")
                print(f"   - Teléfono: {shipping.get('phone')}")
                print(f"   - Dirección: {client.build_shipping_address(shipping)}")
                print(f"   - Ciudad: {shipping.get('city')}")
                print(f"   - Provincia: {shipping.get('province')}")
                print(f"   - CP: {shipping.get('zipcode')}")
        else:
            print("❌ No se obtuvieron datos de TN (verificar API key o rate limit)")
            
    except ValueError as e:
        print(f"❌ Error: ws_internalid no es un número válido: {e}")
    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(test_tn_client())
