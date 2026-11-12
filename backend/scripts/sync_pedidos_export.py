#!/usr/bin/env python3
"""
Script para sincronizar pedidos desde el export 87 del ERP.
Ejecutar cada 5 minutos via cron.
"""

import requests
import sys
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

# Configuración
API_URL = "http://localhost:8002/api/pedidos-export/sincronizar-export-80"
# backend/.env resolved from this file, not from the cron's working directory.
BACKEND_ENV = Path(__file__).resolve().parent.parent / ".env"


def load_token() -> Optional[str]:
    """Internal service token: PRICING_API_TOKEN from the environment, else from backend/.env."""
    load_dotenv(BACKEND_ENV)  # override=False: a variable already set (e.g. inline in cron) wins
    return os.getenv("PRICING_API_TOKEN")


def log(message: str) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {message}", flush=True)


def sync_pedidos() -> int:
    """Sincroniza pedidos desde el ERP"""
    try:
        log("Iniciando sincronización de pedidos export...")

        token = load_token()
        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"

        response = requests.post(API_URL, headers=headers, timeout=60)

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
