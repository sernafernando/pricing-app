#!/usr/bin/env python3
"""
Setup certificado AFIP de producción via automatizaciones de afipsdk.com.

Uso:
    cd backend
    python scripts/setup_afip_cert.py

Qué hace:
    1. Pide CUIT y clave fiscal de ARCA (interactivo, no se guarda)
    2. Crea certificado de producción via API de afipsdk.com
    3. Autoriza el web service ws_sr_padron_a4 (Padrón Alcance 4)
    4. Guarda AFIP_CERT y AFIP_KEY en el .env

NOTA: la clave fiscal NO se guarda en ningún lado. Solo se usa
para las automatizaciones de afipsdk.com que interactúan con ARCA.
"""

import getpass
import os
import sys
import time

import requests

# ── Config ────────────────────────────────────────────────────────
API_BASE = "https://app.afipsdk.com/api/v1"
ENV_FILE = os.path.join(os.path.dirname(__file__), "..", ".env")
POLL_INTERVAL = 5  # segundos entre polls
MAX_POLLS = 60  # máximo ~5 minutos de espera
CERT_ALIAS = "pricing-app"
WEB_SERVICES = ["ws_sr_padron_a4"]


def get_access_token() -> str:
    """Lee AFIP_ACCESS_TOKEN del .env."""
    env_path = os.path.abspath(ENV_FILE)
    if not os.path.exists(env_path):
        print(f"ERROR: No se encontró {env_path}")
        sys.exit(1)

    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line.startswith("AFIP_ACCESS_TOKEN="):
                return line.split("=", 1)[1].strip()

    print("ERROR: AFIP_ACCESS_TOKEN no encontrado en .env")
    sys.exit(1)


def headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def run_automation(token: str, automation: str, params: dict) -> dict:
    """
    Ejecuta una automatización y pollea hasta que termine.
    Retorna el resultado final.
    """
    print(f"\n  Ejecutando automatización: {automation}...")

    resp = requests.post(
        f"{API_BASE}/automations",
        json={"automation": automation, "params": params},
        headers=headers(token),
        timeout=30,
    )

    if resp.status_code != 200:
        print(f"  ERROR HTTP {resp.status_code}: {resp.text}")
        sys.exit(1)

    data = resp.json()
    automation_id = data.get("id")

    if not automation_id:
        # Respuesta directa (sin polling)
        if data.get("status") == "complete":
            return data
        print(f"  ERROR: respuesta inesperada: {data}")
        sys.exit(1)

    # Pollear hasta completar
    for i in range(MAX_POLLS):
        time.sleep(POLL_INTERVAL)
        elapsed = (i + 1) * POLL_INTERVAL

        resp = requests.get(
            f"{API_BASE}/automations/{automation_id}",
            headers=headers(token),
            timeout=30,
        )
        result = resp.json()
        status = result.get("status", "unknown")

        if status == "complete":
            print(f"  Completado en ~{elapsed}s")
            return result
        elif status == "error":
            error_msg = result.get("data", {}).get("message", result.get("error", "Error desconocido"))
            print(f"  ERROR: {error_msg}")
            sys.exit(1)
        else:
            print(f"  [{elapsed}s] Estado: {status}...", end="\r")

    print(f"\n  TIMEOUT: la automatización no terminó en {MAX_POLLS * POLL_INTERVAL}s")
    sys.exit(1)


def update_env(key: str, value: str) -> None:
    """Actualiza o agrega una variable en el .env."""
    env_path = os.path.abspath(ENV_FILE)
    lines = []
    found = False

    with open(env_path) as f:
        lines = f.readlines()

    # Escapar newlines en cert/key para que quede en una línea del .env
    escaped_value = value.replace("\n", "\\n").replace("\r", "")

    for i, line in enumerate(lines):
        if line.strip().startswith(f"{key}="):
            lines[i] = f"{key}={escaped_value}\n"
            found = True
            break

    if not found:
        # Agregar al final
        if lines and not lines[-1].endswith("\n"):
            lines.append("\n")
        lines.append(f"{key}={escaped_value}\n")

    with open(env_path, "w") as f:
        f.writelines(lines)

    print(f"  .env actualizado: {key} ({'actualizado' if found else 'agregado'})")


def main() -> None:
    print("=" * 60)
    print("  AFIP SDK — Setup Certificado de Producción")
    print("=" * 60)
    print()
    print("Este script va a:")
    print("  1. Habilitar Administración de Certificados Digitales en ARCA")
    print("  2. Crear un certificado digital de producción")
    print("  3. Autorizar el web service ws_sr_padron_a4")
    print("  4. Guardar cert + key en el .env")
    print()
    print("IMPORTANTE: la clave fiscal NO se guarda.")
    print("Solo se usa para las automatizaciones de afipsdk.com.")
    print()

    # Leer access token
    access_token = get_access_token()
    print(f"  Access token de afipsdk.com: ...{access_token[-8:]}")

    # Pedir datos
    cuit = input("\n  CUIT de la empresa (ej: 30718627792): ").strip()
    if not cuit:
        print("ERROR: CUIT vacío")
        sys.exit(1)

    username = input(f"  CUIT para login en ARCA [{cuit}]: ").strip() or cuit
    password = getpass.getpass("  Clave fiscal de ARCA: ")
    if not password:
        print("ERROR: Clave fiscal vacía")
        sys.exit(1)

    alias = input(f"  Alias del certificado [{CERT_ALIAS}]: ").strip() or CERT_ALIAS

    print("\n" + "-" * 60)
    print(f"  CUIT empresa:    {cuit}")
    print(f"  CUIT login:      {username}")
    print(f"  Alias cert:      {alias}")
    print(f"  Web services:    {', '.join(WEB_SERVICES)}")
    print("-" * 60)

    confirm = input("\n  ¿Continuar? (s/N): ").strip().lower()
    if confirm != "s":
        print("  Cancelado.")
        sys.exit(0)

    # ── Paso 1: Habilitar Administración de Certificados Digitales ─
    print("\n[1/4] Habilitando Administración de Certificados Digitales...")
    result = run_automation(
        access_token,
        "add-relation",
        {
            "cuit": cuit,
            "username": username,
            "password": password,
            "service": "web://arfe_certificado",
            "delegate_to": username,
        },
    )
    status = result.get("data", {}).get("status", "")
    print(f"  Administración de Certificados: {status or 'OK'}")

    # ── Paso 2: Crear certificado ─────────────────────────────────
    print("\n[2/4] Creando certificado de producción...")
    result = run_automation(
        access_token,
        "create-cert-prod",
        {
            "cuit": cuit,
            "username": username,
            "password": password,
            "alias": alias,
        },
    )

    cert = result.get("data", {}).get("cert")
    key = result.get("data", {}).get("key")

    if not cert or not key:
        print(f"  ERROR: no se recibió cert/key. Respuesta: {result}")
        sys.exit(1)

    print("  Certificado creado OK")

    # ── Paso 3: Autorizar web services ────────────────────────────
    for ws in WEB_SERVICES:
        print(f"\n[3/4] Autorizando web service: {ws}...")
        run_automation(
            access_token,
            "auth-web-service-prod",
            {
                "cuit": cuit,
                "username": username,
                "password": password,
                "alias": alias,
                "service": ws,
            },
        )
        print(f"  {ws} autorizado OK")

    # ── Paso 4: Guardar en .env ───────────────────────────────────
    print("\n[4/4] Guardando en .env...")
    update_env("AFIP_CERT", cert)
    update_env("AFIP_KEY", key)
    update_env("AFIP_ENVIRONMENT", "prod")

    print("\n" + "=" * 60)
    print("  SETUP COMPLETADO")
    print("=" * 60)
    print()
    print("  El certificado y la key quedaron en el .env.")
    print("  Reiniciá el backend para que tome los cambios:")
    print("    systemctl restart pricing-api")
    print()
    print("  El certificado expira en ~2 años.")
    print("  Cuando expire, volvé a correr este script.")


if __name__ == "__main__":
    main()
