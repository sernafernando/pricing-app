#!/usr/bin/env python3
"""
Script para sincronizar pedidos desde el export 87 del ERP.
Ejecutar cada 5 minutos via cron.
"""
import requests
import sys
import os
from datetime import datetime

# Configuración
API_URL = "http://localhost:8002/api/pedidos-export/sincronizar-export-80"
TOKEN = os.getenv("PRICING_API_TOKEN")  # Token de servicio interno

def log(message):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {message}", flush=True)

def sync_pedidos():
    """Sincroniza pedidos desde el ERP"""
    try:
        log("Iniciando sincronización de pedidos export...")
        
        headers = {}
        if TOKEN:
            headers["Authorization"] = f"Bearer {TOKEN}"
        
        response = requests.post(
            API_URL,
            headers=headers,
            timeout=60
        )
        
        if response.status_code == 200:
            data = response.json()
            log(f"✅ Sincronización iniciada: {data.get('registros_obtenidos', 0)} registros")
            return 0
        else:
            log(f"❌ Error HTTP {response.status_code}: {response.text}")
            return 1
            
    except requests.exceptions.Timeout:
        log("❌ Timeout: La sincronización tardó más de 60 segundos")
        return 1
    except requests.exceptions.ConnectionError as e:
        log(f"❌ Error de conexión: {e}")
        return 1
    except Exception as e:
        log(f"❌ Error inesperado: {e}")
        return 1

if __name__ == "__main__":
    exit_code = sync_pedidos()
    sys.exit(exit_code)
