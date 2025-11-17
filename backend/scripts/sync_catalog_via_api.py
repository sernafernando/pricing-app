#!/usr/bin/env python
"""
Script para sincronizar catalog status via API HTTP
"""
import requests
import sys
import getpass

API_URL = "http://localhost:8000"


def login(username, password):
    """Hacer login y obtener token"""
    response = requests.post(
        f"{API_URL}/api/auth/login",
        json={"username": username, "password": password}
    )

    if response.status_code == 200:
        return response.json()["access_token"]
    else:
        print(f"Error en login: {response.status_code} - {response.text}")
        return None


def sync_catalog_status(token, mla_id=None):
    """Sincronizar catalog status"""
    headers = {"Authorization": f"Bearer {token}"}

    params = {}
    if mla_id:
        params["mla_id"] = mla_id

    print(f"Sincronizando catalog status{' para ' + mla_id if mla_id else ''}...")

    response = requests.post(
        f"{API_URL}/api/ml-catalog/sync-catalog-status",
        headers=headers,
        params=params
    )

    if response.status_code == 200:
        result = response.json()
        print(f"\n{'='*60}")
        print(f"Sincronización completada:")
        print(f"  - Total publicaciones: {result['total_publicaciones']}")
        print(f"  - Sincronizadas: {result['sincronizadas']}")
        print(f"  - Errores: {len(result['errores'])}")

        if result['errores']:
            print(f"\nErrores:")
            for err in result['errores']:
                print(f"  - {err}")

        print(f"{'='*60}\n")
    else:
        print(f"Error: {response.status_code} - {response.text}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Sincronizar catalog status via API')
    parser.add_argument('--username', '-u', type=str, help='Usuario para login')
    parser.add_argument('--password', '-p', type=str, help='Password (si no se proporciona, se pedirá)')
    parser.add_argument('--token', '-t', type=str, help='Token JWT (si ya lo tenés)')
    parser.add_argument('--mla', type=str, help='MLA específico a sincronizar')

    args = parser.parse_args()

    token = args.token

    if not token:
        username = args.username or input("Usuario: ")
        password = args.password or getpass.getpass("Password: ")

        token = login(username, password)

        if not token:
            print("No se pudo obtener token de autenticación")
            sys.exit(1)

    sync_catalog_status(token, args.mla)
