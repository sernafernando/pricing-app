#!/usr/bin/env python3
"""
Script para crear envíos Turbo de prueba en distintas zonas de CABA.

Uso:
    python scripts/seed_envios_turbo_test.py

Crea 30 envíos distribuidos en:
- 10 envíos en Zona Norte (Palermo, Belgrano, Núñez)
- 10 envíos en Zona Sur (Constitución, Barracas, San Telmo)
- 10 envíos en Zona Oeste (Caballito, Flores, Almagro)

Todos con:
- shipping_mode = 'me2' (Turbo)
- status = 'ready_to_ship'
- substatus = 'ready_to_print'
- Coordenadas reales de CABA
"""
import sys
import os
from datetime import datetime

# Agregar parent directory al path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from sqlalchemy.orm import Session
from app.core.database import SessionLocal
from app.models.mercadolibre_order_shipping import MercadoLibreOrderShipping
from app.models.geocoding_cache import GeocodingCache

# Envíos de prueba por zona (con coordenadas reales de CABA)
ENVIOS_TEST = [
    # ========== ZONA NORTE (Palermo, Belgrano, Núñez) ==========
    {
        'mlshippingid': 'TEST_NORTE_001',
        'mlo_id': 9000001,
        'mlm_id': 8000001,
        'comp_id': 1,
        'mlshipping_mode': 'me2',
        'mlstatus': 'ready_to_ship',
        'mlstreet_name': 'Av. Santa Fe',
        'mlstreet_number': '3100',
        'mlcity_name': 'Palermo',
        'mlstate_name': 'CABA',
        'mlreceiver_name': 'Juan Pérez',
        'mlreceiver_phone': '1156781234',
        'lat': -34.5889,
        'lng': -58.4036
    },
    {
        'mlshippingid': 'TEST_NORTE_002',
        'mlo_id': 9000002,
        'mlm_id': 8000002,
        'comp_id': 1,
        'mlshipping_mode': 'me2',
        'mlstatus': 'ready_to_ship',
        'mlstreet_name': 'Av. Libertador',
        'mlstreet_number': '4500',
        'mlcity_name': 'Palermo',
        'mlstate_name': 'CABA',
        'mlreceiver_name': 'María González',
        'mlreceiver_phone': '1156782345',
        'lat': -34.5702,
        'lng': -58.4234
    },
    {
        'mlshippingid': 'TEST_NORTE_003',
        'mlo_id': 9000003,
        'mlm_id': 8000003,
        'comp_id': 1,
        'mlshipping_mode': 'me2',
        'mlstatus': 'ready_to_ship',
        'mlstreet_name': 'Cabildo',
        'mlstreet_number': '2500',
        'mlcity_name': 'Belgrano',
        'mlstate_name': 'CABA',
        'mlreceiver_name': 'Carlos Rodríguez',
        'mlreceiver_phone': '1156783456',
        'lat': -34.5641,
        'lng': -58.4545
    },
    {
        'mlshippingid': 'TEST_NORTE_004',
        'mlo_id': 9000004,
        'mlm_id': 8000004,
        'comp_id': 1,
        'mlshipping_mode': 'me2',
        'mlstatus': 'ready_to_ship',
        'mlstreet_name': 'Virrey del Pino',
        'mlstreet_number': '3500',
        'mlcity_name': 'Belgrano',
        'mlstate_name': 'CABA',
        'mlreceiver_name': 'Ana Martínez',
        'mlreceiver_phone': '1156784567',
        'lat': -34.5589,
        'lng': -58.4612
    },
    {
        'mlshippingid': 'TEST_NORTE_005',
        'mlo_id': 9000005,
        'mlm_id': 8000005,
        'comp_id': 1,
        'mlshipping_mode': 'me2',
        'mlstatus': 'ready_to_ship',
        'mlstreet_name': 'Av. del Libertador',
        'mlstreet_number': '7500',
        'mlcity_name': 'Núñez',
        'mlstate_name': 'CABA',
        'mlreceiver_name': 'Luis Fernández',
        'mlreceiver_phone': '1156785678',
        'lat': -34.5456,
        'lng': -58.4567
    },
    {
        'mlshippingid': 'TEST_NORTE_006',
        'mlo_id': 9000006,
        'mlm_id': 8000006,
        'comp_id': 1,
        'mlshipping_mode': 'me2',
        'mlstatus': 'ready_to_ship',
        'mlstreet_name': 'Thames',
        'mlstreet_number': '1500',
        'mlcity_name': 'Palermo',
        'mlstate_name': 'CABA',
        'mlreceiver_name': 'Sofía López',
        'mlreceiver_phone': '1156786789',
        'lat': -34.5890,
        'lng': -58.4250
    },
    {
        'mlshippingid': 'TEST_NORTE_007',
        'mlo_id': 9000007,
        'mlm_id': 8000007,
        'comp_id': 1,
        'mlshipping_mode': 'me2',
        'mlstatus': 'ready_to_ship',
        'mlstreet_name': 'Fitz Roy',
        'mlstreet_number': '1800',
        'mlcity_name': 'Palermo',
        'mlstate_name': 'CABA',
        'mlreceiver_name': 'Diego Sánchez',
        'mlreceiver_phone': '1156787890',
        'lat': -34.5875,
        'lng': -58.4310
    },
    {
        'mlshippingid': 'TEST_NORTE_008',
        'mlo_id': 9000008,
        'mlm_id': 8000008,
        'comp_id': 1,
        'mlshipping_mode': 'me2',
        'mlstatus': 'ready_to_ship',
        'mlstreet_name': 'Juramento',
        'mlstreet_number': '3000',
        'mlcity_name': 'Belgrano',
        'mlstate_name': 'CABA',
        'mlreceiver_phone': '1156788901',
        'mlreceiver_name': 'Laura Romero',
        'lat': -34.5623,
        'lng': -58.4590
    },
    {
        'mlshippingid': 'TEST_NORTE_009',
        'mlo_id': 9000009,
        'mlm_id': 8000009,
        'comp_id': 1,
        'mlshipping_mode': 'me2',
        'mlstatus': 'ready_to_ship',
        'mlstreet_name': 'Av. Las Heras',
        'mlstreet_number': '3800',
        'mlcity_name': 'Palermo',
        'mlstate_name': 'CABA',
        'mlreceiver_name': 'Martín Torres',
        'mlreceiver_phone': '1156789012',
        'lat': -34.5867,
        'lng': -58.4089
    },
    {
        'mlshippingid': 'TEST_NORTE_010',
        'mlo_id': 9000010,
        'mlm_id': 8000010,
        'comp_id': 1,
        'mlshipping_mode': 'me2',
        'mlstatus': 'ready_to_ship',
        'mlstreet_name': 'Olleros',
        'mlstreet_number': '2500',
        'mlcity_name': 'Belgrano',
        'mlstate_name': 'CABA',
        'mlreceiver_name': 'Valeria Castro',
        'mlreceiver_phone': '1156790123',
        'lat': -34.5678,
        'lng': -58.4534
    },
    
    # ========== ZONA SUR (Constitución, Barracas, San Telmo) ==========
    {
        'mlshippingid': 'TEST_SUR_001',
        'mlo_id': 9000011,
        'mlm_id': 8000011,
        'comp_id': 1,
        'mlshipping_mode': 'me2',
        'mlstatus': 'ready_to_ship',
        'mlstreet_name': 'Av. Juan de Garay',
        'mlstreet_number': '500',
        'mlcity_name': 'Constitución',
        'mlstate_name': 'CABA',
        'mlreceiver_name': 'Roberto Díaz',
        'mlreceiver_phone': '1156791234',
        'lat': -34.6289,
        'lng': -58.3812
    },
    {
        'mlshippingid': 'TEST_SUR_002',
        'mlo_id': 9000012,
        'mlm_id': 8000012,
        'comp_id': 1,
        'mlshipping_mode': 'me2',
        'mlstatus': 'ready_to_ship',
        'mlstreet_name': 'Brasil',
        'mlstreet_number': '800',
        'mlcity_name': 'Constitución',
        'mlstate_name': 'CABA',
        'mlreceiver_name': 'Claudia Ruiz',
        'mlreceiver_phone': '1156792345',
        'lat': -34.6301,
        'lng': -58.3756
    },
    {
        'mlshippingid': 'TEST_SUR_003',
        'mlo_id': 9000013,
        'mlm_id': 8000013,
        'comp_id': 1,
        'mlshipping_mode': 'me2',
        'mlstatus': 'ready_to_ship',
        'mlstreet_name': 'Av. Montes de Oca',
        'mlstreet_number': '1200',
        'mlcity_name': 'Barracas',
        'mlstate_name': 'CABA',
        'mlreceiver_name': 'Fernando Morales',
        'mlreceiver_phone': '1156793456',
        'lat': -34.6378,
        'lng': -58.3689
    },
    {
        'mlshippingid': 'TEST_SUR_004',
        'mlo_id': 9000014,
        'mlm_id': 8000014,
        'comp_id': 1,
        'mlshipping_mode': 'me2',
        'mlstatus': 'ready_to_ship',
        'mlstreet_name': 'Defensa',
        'mlstreet_number': '950',
        'mlcity_name': 'San Telmo',
        'mlstate_name': 'CABA',
        'mlreceiver_name': 'Gabriela Herrera',
        'mlreceiver_phone': '1156794567',
        'lat': -34.6223,
        'lng': -58.3734
    },
    {
        'mlshippingid': 'TEST_SUR_005',
        'mlo_id': 9000015,
        'mlm_id': 8000015,
        'comp_id': 1,
        'mlshipping_mode': 'me2',
        'mlstatus': 'ready_to_ship',
        'mlstreet_name': 'Av. Caseros',
        'mlstreet_number': '2500',
        'mlcity_name': 'Parque Patricios',
        'mlstate_name': 'CABA',
        'mlreceiver_name': 'Andrés Silva',
        'mlreceiver_phone': '1156795678',
        'lat': -34.6389,
        'lng': -58.3978
    },
    {
        'mlshippingid': 'TEST_SUR_006',
        'mlo_id': 9000016,
        'mlm_id': 8000016,
        'comp_id': 1,
        'mlshipping_mode': 'me2',
        'mlstatus': 'ready_to_ship',
        'mlstreet_name': 'Paseo Colón',
        'mlstreet_number': '1500',
        'mlcity_name': 'San Telmo',
        'mlstate_name': 'CABA',
        'mlreceiver_name': 'Patricia Vargas',
        'mlreceiver_phone': '1156796789',
        'lat': -34.6245,
        'lng': -58.3689
    },
    {
        'mlshippingid': 'TEST_SUR_007',
        'mlo_id': 9000017,
        'mlm_id': 8000017,
        'comp_id': 1,
        'mlshipping_mode': 'me2',
        'mlstatus': 'ready_to_ship',
        'mlstreet_name': 'Av. Almirante Brown',
        'mlstreet_number': '800',
        'mlcity_name': 'La Boca',
        'mlstate_name': 'CABA',
        'mlreceiver_name': 'Ricardo Méndez',
        'mlreceiver_phone': '1156797890',
        'lat': -34.6356,
        'lng': -58.3623
    },
    {
        'mlshippingid': 'TEST_SUR_008',
        'mlo_id': 9000018,
        'mlm_id': 8000018,
        'comp_id': 1,
        'mlshipping_mode': 'me2',
        'mlstatus': 'ready_to_ship',
        'mlstreet_name': 'Estados Unidos',
        'mlstreet_number': '1200',
        'mlcity_name': 'Constitución',
        'mlstate_name': 'CABA',
        'mlreceiver_name': 'Silvia Ramírez',
        'mlreceiver_phone': '1156798901',
        'lat': -34.6289,
        'lng': -58.3890
    },
    {
        'mlshippingid': 'TEST_SUR_009',
        'mlo_id': 9000019,
        'mlm_id': 8000019,
        'comp_id': 1,
        'mlshipping_mode': 'me2',
        'mlstatus': 'ready_to_ship',
        'mlstreet_name': 'Suárez',
        'mlstreet_number': '1500',
        'mlcity_name': 'Barracas',
        'mlstate_name': 'CABA',
        'mlreceiver_name': 'Gustavo Ortiz',
        'mlreceiver_phone': '1156799012',
        'lat': -34.6423,
        'lng': -58.3712
    },
    {
        'mlshippingid': 'TEST_SUR_010',
        'mlo_id': 9000020,
        'mlm_id': 8000020,
        'comp_id': 1,
        'mlshipping_mode': 'me2',
        'mlstatus': 'ready_to_ship',
        'mlstreet_name': 'Humberto 1º',
        'mlstreet_number': '700',
        'mlcity_name': 'San Telmo',
        'mlstate_name': 'CABA',
        'mlreceiver_name': 'Mónica Giménez',
        'mlreceiver_phone': '1156800123',
        'lat': -34.6198,
        'lng': -58.3745
    },
    
    # ========== ZONA OESTE (Caballito, Flores, Almagro) ==========
    {
        'mlshippingid': 'TEST_OESTE_001',
        'mlo_id': 9000021,
        'mlm_id': 8000021,
        'comp_id': 1,
        'mlshipping_mode': 'me2',
        'mlstatus': 'ready_to_ship',
        'mlstreet_name': 'Av. Rivadavia',
        'mlstreet_number': '5500',
        'mlcity_name': 'Caballito',
        'mlstate_name': 'CABA',
        'mlreceiver_name': 'Hernán Benítez',
        'mlreceiver_phone': '1156801234',
        'lat': -34.6189,
        'lng': -58.4356
    },
    {
        'mlshippingid': 'TEST_OESTE_002',
        'mlo_id': 9000022,
        'mlm_id': 8000022,
        'comp_id': 1,
        'mlshipping_mode': 'me2',
        'mlstatus': 'ready_to_ship',
        'mlstreet_name': 'Av. Acoyte',
        'mlstreet_number': '500',
        'mlcity_name': 'Caballito',
        'mlstate_name': 'CABA',
        'mlreceiver_name': 'Cecilia Domínguez',
        'mlreceiver_phone': '1156802345',
        'lat': -34.6123,
        'lng': -58.4401
    },
    {
        'mlshippingid': 'TEST_OESTE_003',
        'mlo_id': 9000023,
        'mlm_id': 8000023,
        'comp_id': 1,
        'mlshipping_mode': 'me2',
        'mlstatus': 'ready_to_ship',
        'mlstreet_name': 'Av. Directorio',
        'mlstreet_number': '2000',
        'mlcity_name': 'Flores',
        'mlstate_name': 'CABA',
        'mlreceiver_name': 'Pablo Navarro',
        'mlreceiver_phone': '1156803456',
        'lat': -34.6312,
        'lng': -58.4567
    },
    {
        'mlshippingid': 'TEST_OESTE_004',
        'mlo_id': 9000024,
        'mlm_id': 8000024,
        'comp_id': 1,
        'mlshipping_mode': 'me2',
        'mlstatus': 'ready_to_ship',
        'mlstreet_name': 'Av. Corrientes',
        'mlstreet_number': '4500',
        'mlcity_name': 'Almagro',
        'mlstate_name': 'CABA',
        'mlreceiver_name': 'Daniela Iglesias',
        'mlreceiver_phone': '1156804567',
        'lat': -34.6023,
        'lng': -58.4234
    },
    {
        'mlshippingid': 'TEST_OESTE_005',
        'mlo_id': 9000025,
        'mlm_id': 8000025,
        'comp_id': 1,
        'mlshipping_mode': 'me2',
        'mlstatus': 'ready_to_ship',
        'mlstreet_name': 'Av. San Martín',
        'mlstreet_number': '3500',
        'mlcity_name': 'Flores',
        'mlstate_name': 'CABA',
        'mlreceiver_name': 'Ramiro Cabrera',
        'mlreceiver_phone': '1156805678',
        'lat': -34.6267,
        'lng': -58.4623
    },
    {
        'mlshippingid': 'TEST_OESTE_006',
        'mlo_id': 9000026,
        'mlm_id': 8000026,
        'comp_id': 1,
        'mlshipping_mode': 'me2',
        'mlstatus': 'ready_to_ship',
        'mlstreet_name': 'Av. Boedo',
        'mlstreet_number': '1200',
        'mlcity_name': 'Boedo',
        'mlstate_name': 'CABA',
        'mlreceiver_name': 'Lorena Acosta',
        'mlreceiver_phone': '1156806789',
        'lat': -34.6256,
        'lng': -58.4178
    },
    {
        'mlshippingid': 'TEST_OESTE_007',
        'mlo_id': 9000027,
        'mlm_id': 8000027,
        'comp_id': 1,
        'mlshipping_mode': 'me2',
        'mlstatus': 'ready_to_ship',
        'mlstreet_name': 'Primera Junta',
        'mlstreet_number': '800',
        'mlcity_name': 'Caballito',
        'mlstate_name': 'CABA',
        'mlreceiver_name': 'Javier Molina',
        'mlreceiver_phone': '1156807890',
        'lat': -34.6089,
        'lng': -58.4489
    },
    {
        'mlshippingid': 'TEST_OESTE_008',
        'mlo_id': 9000028,
        'mlm_id': 8000028,
        'comp_id': 1,
        'mlshipping_mode': 'me2',
        'mlstatus': 'ready_to_ship',
        'mlstreet_name': 'Av. La Plata',
        'mlstreet_number': '1500',
        'mlcity_name': 'Flores',
        'mlstate_name': 'CABA',
        'mlreceiver_name': 'Carolina Pereyra',
        'mlreceiver_phone': '1156808901',
        'lat': -34.6378,
        'lng': -58.4534
    },
    {
        'mlshippingid': 'TEST_OESTE_009',
        'mlo_id': 9000029,
        'mlm_id': 8000029,
        'comp_id': 1,
        'mlshipping_mode': 'me2',
        'mlstatus': 'ready_to_ship',
        'mlstreet_name': 'Av. Medrano',
        'mlstreet_number': '600',
        'mlcity_name': 'Almagro',
        'mlstate_name': 'CABA',
        'mlreceiver_name': 'Federico Vega',
        'mlreceiver_phone': '1156809012',
        'lat': -34.6045,
        'lng': -58.4289
    },
    {
        'mlshippingid': 'TEST_OESTE_010',
        'mlo_id': 9000030,
        'mlm_id': 8000030,
        'comp_id': 1,
        'mlshipping_mode': 'me2',
        'mlstatus': 'ready_to_ship',
        'mlstreet_name': 'Av. Nazca',
        'mlstreet_number': '2500',
        'mlcity_name': 'Flores',
        'mlstate_name': 'CABA',
        'mlreceiver_name': 'Verónica Luna',
        'mlreceiver_phone': '1156810123',
        'lat': -34.6234,
        'lng': -58.4701
    },
]


def seed_envios_test(db: Session):
    """Inserta envíos Turbo de prueba en la BD."""
    
    print("🚀 Iniciando seed de envíos Turbo de prueba...")
    print(f"📦 Total envíos a crear: {len(ENVIOS_TEST)}")
    
    creados = 0
    ya_existentes = 0
    
    for envio_data in ENVIOS_TEST:
        # Verificar si ya existe
        existing = db.query(MercadoLibreOrderShipping).filter(
            MercadoLibreOrderShipping.mlshippingid == envio_data['mlshippingid']
        ).first()
        
        if existing:
            ya_existentes += 1
            continue
        
        # Extraer lat/lng para geocoding_cache
        lat = envio_data.pop('lat')
        lng = envio_data.pop('lng')
        
        # Crear envío
        envio = MercadoLibreOrderShipping(**envio_data)
        db.add(envio)
        
        # Crear entrada en geocoding_cache
        direccion = f"{envio_data['mlstreet_name']} {envio_data['mlstreet_number']}, {envio_data['mlcity_name']}"
        
        # Verificar si ya existe en cache
        direccion_hash = GeocodingCache.hash_direccion(direccion)
        existing_cache = db.query(GeocodingCache).filter(
            GeocodingCache.direccion_hash == direccion_hash
        ).first()
        
        if not existing_cache:
            cache_entry = GeocodingCache(
                direccion_hash=direccion_hash,
                direccion_normalizada=direccion,
                latitud=lat,
                longitud=lng,
                provider='seed_test'
            )
            db.add(cache_entry)
        
        creados += 1
        
        # Log cada 10 envíos
        if creados % 10 == 0:
            print(f"  ✅ {creados} envíos creados...")
    
    # Commit
    db.commit()
    
    print("\n" + "="*60)
    print(f"✅ SEED COMPLETADO")
    print(f"  • Envíos creados: {creados}")
    print(f"  • Ya existentes (skipped): {ya_existentes}")
    print(f"  • Total: {len(ENVIOS_TEST)}")
    print("="*60)
    
    # Mostrar distribución
    print("\n📊 DISTRIBUCIÓN POR ZONA:")
    print(f"  • Zona Norte (Palermo, Belgrano, Núñez): 10 envíos")
    print(f"  • Zona Sur (Constitución, Barracas, San Telmo): 10 envíos")
    print(f"  • Zona Oeste (Caballito, Flores, Almagro): 10 envíos")
    print("\n💡 PRÓXIMO PASO:")
    print("  1. Andá a TurboRouting → Tab 'Motoqueros'")
    print("  2. Creá 3 motoqueros activos")
    print("  3. Andá a Tab 'Zonas'")
    print("  4. Hacé click en '🤖 Auto-generar 3 Zonas'")
    print("  5. Verificá que se creen 3 zonas balanceadas\n")


if __name__ == '__main__':
    db = SessionLocal()
    try:
        seed_envios_test(db)
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        db.rollback()
        raise
    finally:
        db.close()
