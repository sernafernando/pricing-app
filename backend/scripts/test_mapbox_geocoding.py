"""
Script de prueba para verificar que Mapbox Geocoding funciona.
"""
import asyncio
import sys
from pathlib import Path

# Agregar el directorio backend al path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.geocoding_service import geocode_address
from app.core.config import settings

async def test_geocoding():
    """Testear geocoding con Mapbox"""
    
    print("=" * 60)
    print("TEST: Mapbox Geocoding API")
    print("=" * 60)
    
    # Verificar token
    if not settings.MAPBOX_ACCESS_TOKEN:
        print("❌ ERROR: MAPBOX_ACCESS_TOKEN no está configurado en .env")
        return
    
    print(f"✅ Token configurado: {settings.MAPBOX_ACCESS_TOKEN[:20]}...")
    print()
    
    # Direcciones de prueba en Buenos Aires
    direcciones_test = [
        "Av. Corrientes 1234",
        "Av. Santa Fe 2500",
        "Av. 9 de Julio 500",
        "Calle Florida 100",
    ]
    
    print("Geocodificando direcciones de prueba:")
    print("-" * 60)
    
    for direccion in direcciones_test:
        print(f"\n📍 Dirección: {direccion}, Buenos Aires, Argentina")
        
        # Geocodificar sin cache (db=None)
        coords = await geocode_address(
            direccion=direccion,
            ciudad="Buenos Aires",
            pais="Argentina",
            db=None,
            usar_cache=False
        )
        
        if coords:
            lat, lng = coords
            print(f"   ✅ Resultado: lat={lat:.6f}, lng={lng:.6f}")
            print(f"   🗺️  Google Maps: https://www.google.com/maps?q={lat},{lng}")
        else:
            print(f"   ❌ No se pudo geocodificar")
    
    print("\n" + "=" * 60)
    print("TEST COMPLETADO")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(test_geocoding())
