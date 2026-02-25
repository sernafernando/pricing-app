"""
Script orquestador para sincronizar todas las tablas RMA desde el ERP.

Ejecuta los 5 syncs RMA en orden:
  1. tb_rma_header
  2. tb_rma_detail
  3. tb_rma_add_items
  4. tb_rma_detail_attrib_history
  5. tb_rma_supplier_cn_pending

Modos de uso:
    # Incremental (para cron horario)
    python -m app.scripts.sync_rma_all --incremental

    # Full (para cron nocturno)
    python -m app.scripts.sync_rma_all --full
"""

import sys
import subprocess
from datetime import datetime
from pathlib import Path

# Backend dir para ejecutar los scripts
BACKEND_DIR = Path(__file__).parent.parent.parent

SCRIPTS = [
    {"nombre": "RMA Header", "emoji": "📋", "module": "app.scripts.sync_rma_header"},
    {"nombre": "RMA Detail", "emoji": "📦", "module": "app.scripts.sync_rma_detail"},
    {"nombre": "RMA AddItems", "emoji": "➕", "module": "app.scripts.sync_rma_add_items"},
    {"nombre": "RMA Detail AttribHistory", "emoji": "📜", "module": "app.scripts.sync_rma_detail_attrib_history"},
    {"nombre": "RMA Supplier CN Pending", "emoji": "💳", "module": "app.scripts.sync_rma_supplier_cn_pending"},
]


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in ("--full", "--incremental"):
        print("Uso: python -m app.scripts.sync_rma_all [--full | --incremental]")
        sys.exit(1)

    mode = sys.argv[1]
    timestamp_inicio = datetime.now()

    print("\n" + "=" * 60)
    print(f"🔄 Sync RMA {mode.replace('--', '').upper()}: {timestamp_inicio.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    exitosos = []
    errores = []
    python_exe = sys.executable

    for i, script in enumerate(SCRIPTS, 1):
        print(f"\n{script['emoji']} [{i}/{len(SCRIPTS)}] {script['nombre']}...")

        try:
            result = subprocess.run(
                [python_exe, "-m", script["module"], mode],
                cwd=str(BACKEND_DIR),
                capture_output=True,
                text=True,
                timeout=300,
            )

            if result.stdout:
                # Imprimir solo las líneas de resumen (últimas líneas relevantes)
                lines = result.stdout.strip().split("\n")
                for line in lines:
                    if any(k in line for k in ["✅", "Total", "⚠️", "Obtenidos"]):
                        print(f"   {line.strip()}")

            if result.returncode == 0:
                exitosos.append(script["nombre"])
                print(f"   ✅ {script['nombre']} OK")
            else:
                errores.append(f"{script['nombre']}: exit code {result.returncode}")
                print(f"   ❌ {script['nombre']} FALLÓ (exit {result.returncode})")
                if result.stderr:
                    print(f"   stderr: {result.stderr[:200]}")

        except subprocess.TimeoutExpired:
            errores.append(f"{script['nombre']}: TIMEOUT (5 min)")
            print(f"   ❌ {script['nombre']} TIMEOUT")
        except Exception as e:
            errores.append(f"{script['nombre']}: {str(e)}")
            print(f"   ❌ {script['nombre']} ERROR: {str(e)}")

    # Resumen
    timestamp_fin = datetime.now()
    duracion = (timestamp_fin - timestamp_inicio).total_seconds()

    print("\n" + "=" * 60)
    print(f"✨ Sync RMA finalizado: {timestamp_fin.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"⏱️  Duración: {duracion:.1f}s")
    print(f"   ✅ Exitosos: {len(exitosos)}/{len(SCRIPTS)}")
    if errores:
        print(f"   ❌ Errores: {len(errores)}")
        for error in errores:
            print(f"      • {error}")
    print("=" * 60)

    sys.exit(1 if errores else 0)


if __name__ == "__main__":
    main()
