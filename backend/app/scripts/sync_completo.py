#!/usr/bin/env python3
import sys
import requests
from datetime import datetime

sys.path.append('/var/www/html/pricing-app/backend')

BASE_URL = "http://localhost:8002/api"

def log(msg):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}")

def sync_all():
    log("=== INICIO SINCRONIZACIÓN COMPLETA ===")
    
    # 1. Tipo de cambio
    log("Sincronizando tipo de cambio...")
    try:
        r = requests.post(f"{BASE_URL}/sync-tipo-cambio", timeout=60)
        log(f"Tipo cambio: {r.json()}")
    except Exception as e:
        log(f"Error tipo cambio: {e}")
    
    # 2. ERP
    log("Sincronizando productos ERP...")
    try:
        r = requests.post(f"{BASE_URL}/sync", timeout=300)
        log(f"ERP: {r.json()}")
    except Exception as e:
        log(f"Error ERP: {e}")
    
    # 3. Publicaciones ML
    log("Sincronizando publicaciones ML...")
    try:
        r = requests.post(f"{BASE_URL}/sync-ml", timeout=300)
        log(f"ML: {r.json()}")
    except Exception as e:
        log(f"Error ML: {e}")
    
    # 4. Ofertas Sheets
    log("Sincronizando ofertas...")
    try:
        r = requests.post(f"{BASE_URL}/sync-sheets", timeout=180)
        log(f"Sheets: {r.json()}")
    except Exception as e:
        log(f"Error Sheets: {e}")
    
    # 5. Recalcular markups
    log("Recalculando markups...")
    try:
        r = requests.post(f"{BASE_URL}/recalcular-markups", timeout=600)
        log(f"Markups: {r.json()}")
    except Exception as e:
        log(f"Error markups: {e}")
    
    log("=== FIN SINCRONIZACIÓN COMPLETA ===")

if __name__ == "__main__":
    sync_all()
