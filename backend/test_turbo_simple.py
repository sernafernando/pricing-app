#!/usr/bin/env python3
"""
Script simple para testear endpoints de Turbo Routing.
Uso: python test_turbo_simple.py
"""
import requests
import json
import os
from getpass import getpass

# Configuración
API_URL = os.getenv("API_URL", "http://localhost:8000")
TOKEN = os.getenv("TOKEN", "")

# Obtener token si no existe
if not TOKEN:
    print("🔐 No se encontró TOKEN en variables de entorno")
    print(f"   Para obtener el token, ir a: {API_URL}/api/docs")
    print("   Hacer login con POST /api/auth/login")
    print()
    TOKEN = input("Ingresá tu token JWT: ").strip()

HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json"
}

def print_section(title):
    print("\n" + "="*60)
    print(f"  {title}")
    print("="*60)

def print_response(response):
    """Pretty print de respuesta JSON"""
    try:
        data = response.json()
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return data
    except:
        print(f"Response text: {response.text}")
        return None

def test_estadisticas():
    print_section("📊 Estadísticas Generales")
    response = requests.get(f"{API_URL}/api/turbo/estadisticas", headers=HEADERS)
    print(f"Status: {response.status_code}")
    return print_response(response)

def test_crear_motoquero():
    print_section("🏍️ Crear Motoquero")
    data = {
        "nombre": "Carlos Test",
        "telefono": "+5491112345678",
        "activo": True,
        "zona_preferida_id": None
    }
    response = requests.post(f"{API_URL}/api/turbo/motoqueros", headers=HEADERS, json=data)
    print(f"Status: {response.status_code}")
    return print_response(response)

def test_listar_motoqueros():
    print_section("📋 Listar Motoqueros")
    response = requests.get(f"{API_URL}/api/turbo/motoqueros", headers=HEADERS)
    print(f"Status: {response.status_code}")
    return print_response(response)

def test_crear_zona():
    print_section("🗺️ Crear Zona")
    data = {
        "nombre": "Zona Test",
        "poligono": {
            "type": "Polygon",
            "coordinates": [
                [
                    [-58.4173, -34.5816],
                    [-58.4173, -34.6016],
                    [-58.3973, -34.6016],
                    [-58.3973, -34.5816],
                    [-58.4173, -34.5816]
                ]
            ]
        },
        "color": "#00FF00",
        "activa": True
    }
    response = requests.post(f"{API_URL}/api/turbo/zonas", headers=HEADERS, json=data)
    print(f"Status: {response.status_code}")
    return print_response(response)

def test_listar_zonas():
    print_section("📋 Listar Zonas")
    response = requests.get(f"{API_URL}/api/turbo/zonas", headers=HEADERS)
    print(f"Status: {response.status_code}")
    return print_response(response)

def test_envios_pendientes():
    print_section("📦 Envíos Turbo Pendientes")
    response = requests.get(f"{API_URL}/api/turbo/envios/pendientes?limit=5", headers=HEADERS)
    print(f"Status: {response.status_code}")
    return print_response(response)

def test_asignar_envio(mlshippingid, motoquero_id, zona_id=None):
    print_section("✅ Asignar Envío")
    data = {
        "mlshippingids": [mlshippingid],
        "motoquero_id": motoquero_id,
        "zona_id": zona_id,
        "asignado_por": "manual"
    }
    response = requests.post(f"{API_URL}/api/turbo/asignacion/manual", headers=HEADERS, json=data)
    print(f"Status: {response.status_code}")
    return print_response(response)

def test_resumen_asignaciones():
    print_section("📊 Resumen de Asignaciones")
    response = requests.get(f"{API_URL}/api/turbo/asignaciones/resumen", headers=HEADERS)
    print(f"Status: {response.status_code}")
    return print_response(response)

def main():
    print("\n🚀 TESTING TURBO ROUTING API")
    print(f"   API URL: {API_URL}")
    print()
    
    try:
        # Test 1: Estadísticas
        stats = test_estadisticas()
        
        # Test 2: Crear motoquero
        motoquero = test_crear_motoquero()
        motoquero_id = motoquero.get('id') if motoquero else None
        
        # Test 3: Listar motoqueros
        test_listar_motoqueros()
        
        # Test 4: Crear zona
        zona = test_crear_zona()
        zona_id = zona.get('id') if zona else None
        
        # Test 5: Listar zonas
        test_listar_zonas()
        
        # Test 6: Envíos pendientes
        envios = test_envios_pendientes()
        
        # Test 7: Asignar envío (si hay)
        if envios and len(envios) > 0 and motoquero_id:
            first_envio = envios[0]
            mlshippingid = first_envio.get('mlshippingid')
            if mlshippingid:
                test_asignar_envio(mlshippingid, motoquero_id, zona_id)
        
        # Test 8: Resumen
        test_resumen_asignaciones()
        
        # Resumen final
        print_section("✅ TESTS COMPLETADOS")
        print(f"\n📝 Recursos creados:")
        if motoquero_id:
            print(f"   - Motoquero ID: {motoquero_id}")
        if zona_id:
            print(f"   - Zona ID: {zona_id}")
        
        print(f"\n📖 Documentación: {API_URL}/api/docs#tag/turbo-routing")
        
    except requests.exceptions.ConnectionError:
        print(f"\n❌ ERROR: No se pudo conectar a {API_URL}")
        print("   ¿Está corriendo el backend?")
    except requests.exceptions.HTTPError as e:
        print(f"\n❌ ERROR HTTP: {e}")
    except Exception as e:
        print(f"\n❌ ERROR: {e}")

if __name__ == "__main__":
    main()
