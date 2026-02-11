"""
Script para sincronizar TABLAS MAESTRAS PEQUEÑAS del ERP.
Diseñado para ejecutarse 1-2 veces al día (son tablas que cambian poco).

Tablas sincronizadas:
- tbBranch (sucursales)
- tbSalesman (vendedores)
- tbState (estados/provincias)
- tbDocumentFile (tipos de documento)
- tbFiscalClass (clases fiscales)
- tbTaxNumberType (tipos de número impositivo)
- tbItemAssociation (asociaciones de items)

Ejecutar:
    python -m app.scripts.sync_master_tables_small
"""

import sys
import os
from pathlib import Path

if __name__ == "__main__":
    backend_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if backend_path not in sys.path:
        sys.path.insert(0, backend_path)

    # Cargar variables de entorno desde .env
    from dotenv import load_dotenv

    env_path = Path(backend_path) / ".env"
    load_dotenv(dotenv_path=env_path)

from datetime import datetime

# Importar funciones de sincronización
from app.scripts.sync_branches import sync_branches
from app.scripts.sync_salesmen import sync_salesmen
from app.scripts.sync_states import sync_states
from app.scripts.sync_document_files import sync_document_files
from app.scripts.sync_fiscal_classes import sync_fiscal_classes
from app.scripts.sync_tax_number_types import sync_tax_number_types
from app.scripts.sync_item_associations import sync_item_associations


def main():
    """
    Ejecuta sincronización de todas las tablas maestras pequeñas.
    """
    timestamp_inicio = datetime.now()
    print("\n" + "=" * 60)
    print(f"🔄 Inicio sincronización tablas maestras: {timestamp_inicio.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    resultados = {"exitosos": [], "errores": []}

    # Lista de sincronizaciones a ejecutar
    sincronizaciones = [
        {"nombre": "Sucursales (Branches)", "emoji": "🏢", "funcion": sync_branches, "args": {}},
        {"nombre": "Vendedores (Salesmen)", "emoji": "👔", "funcion": sync_salesmen, "args": {}},
        {"nombre": "Estados/Provincias (States)", "emoji": "🗺️", "funcion": sync_states, "args": {}},
        {"nombre": "Tipos de Documento (Document Files)", "emoji": "📄", "funcion": sync_document_files, "args": {}},
        {"nombre": "Clases Fiscales (Fiscal Classes)", "emoji": "💼", "funcion": sync_fiscal_classes, "args": {}},
        {
            "nombre": "Tipos de Número Impositivo (Tax Number Types)",
            "emoji": "🔢",
            "funcion": sync_tax_number_types,
            "args": {},
        },
        {"nombre": "Asociaciones de Items", "emoji": "🔗", "funcion": sync_item_associations, "args": {}},
    ]

    for i, sync in enumerate(sincronizaciones, 1):
        try:
            print(f"\n{sync['emoji']} [{i}/{len(sincronizaciones)}] Sincronizando {sync['nombre']}...")

            # Ejecutar la función standalone
            result = sync["funcion"](**sync["args"])

            print(f"✅ {sync['nombre']} completado")

            # Guardar resultado
            if isinstance(result, tuple):
                resultados["exitosos"].append(f"{sync['nombre']}: {result[0]} nuevos, {result[1]} actualizados")
            else:
                resultados["exitosos"].append(sync["nombre"])

        except Exception as e:
            error_msg = f"{sync['nombre']}: {str(e)}"
            print(f"❌ Error en {sync['nombre']}: {str(e)}")
            resultados["errores"].append(error_msg)

    # Resumen final
    timestamp_fin = datetime.now()
    duracion = (timestamp_fin - timestamp_inicio).total_seconds()

    print("\n" + "=" * 60)
    print(f"✨ Sincronización completada: {timestamp_fin.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"⏱️  Duración: {duracion:.2f} segundos")
    print("=" * 60)

    print("\n📊 Resumen:")
    print(f"   ✅ Exitosos: {len(resultados['exitosos'])}")
    print(f"   ❌ Errores: {len(resultados['errores'])}")

    if resultados["exitosos"]:
        print("\n✅ Completados exitosamente:")
        for msg in resultados["exitosos"]:
            print(f"   • {msg}")

    if resultados["errores"]:
        print("\n⚠️  Errores encontrados:")
        for error in resultados["errores"]:
            print(f"   • {error}")

    # Exit code
    if resultados["errores"]:
        return 1
    return 0


if __name__ == "__main__":
    print("🚀 Iniciando sincronización de tablas maestras pequeñas...")

    try:
        exit_code = main()
        sys.exit(exit_code)

    except KeyboardInterrupt:
        print("\n\n⚠️  Sincronización interrumpida por el usuario")
        sys.exit(130)
    except Exception as e:
        print(f"\n\n❌ Error crítico: {str(e)}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
