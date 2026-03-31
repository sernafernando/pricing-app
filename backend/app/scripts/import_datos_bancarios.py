"""
Importa CBU y alias desde un Excel de empleados.

Match por DNI. Actualiza banco_cbu, banco_alias y auto-detecta banco_nombre
desde los primeros 3 dígitos del CBU (código entidad BCRA).

USO:
    cd backend
    source venv/bin/activate
    python -m app.scripts.import_datos_bancarios /path/al/archivo.xlsx
    python -m app.scripts.import_datos_bancarios /path/al/archivo.xlsx --apply
"""

import argparse
import sys
from pathlib import Path

import openpyxl

backend_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(backend_dir))

from sqlalchemy import text

from app.core.database import SessionLocal

# Código entidad BCRA (primeros 3 dígitos del CBU) → nombre del banco
# Código entidad BCRA (primeros 3 dígitos del CBU) → nombre del banco
# Fuente: BCRA / Wikipedia "Clave Bancaria Uniforme"
CBU_BANCOS = {
    "005": "The Royal Bank of Scotland",
    "007": "Banco de Galicia y Buenos Aires",
    "011": "Banco de la Nación Argentina",
    "014": "Banco de la Provincia de Buenos Aires",
    "015": "ICBC Argentina",
    "016": "Citibank",
    "017": "BBVA Banco Francés",
    "020": "Banco de la Provincia de Córdoba",
    "027": "Banco Supervielle",
    "029": "Banco de la Ciudad de Buenos Aires",
    "034": "Banco Patagonia",
    "044": "Banco Hipotecario",
    "045": "Banco de San Juan",
    "060": "Banco de Tucumán",
    "065": "Banco Municipal de Rosario",
    "072": "Banco Santander Río",
    "083": "Banco del Chubut",
    "086": "Banco de Santa Cruz",
    "093": "Banco de la Pampa",
    "094": "Banco de Corrientes",
    "097": "Banco Provincia del Neuquén",
    "143": "Brubank",
    "147": "Banco Interfinanzas",
    "150": "HSBC Bank Argentina",
    "158": "Openbank",
    "165": "JP Morgan Chase Bank",
    "191": "Banco Credicoop",
    "198": "Banco de Valores",
    "247": "Banco Roela",
    "254": "Banco Mariva",
    "259": "Banco Itaú Argentina",
    "262": "Bank of America",
    "266": "BNP Paribas",
    "268": "Banco Provincia de Tierra del Fuego",
    "277": "Banco Sáenz",
    "281": "Banco Meridian",
    "285": "Banco Macro",
    "295": "American Express Bank",
    "299": "Banco Comafi",
    "300": "Banco de Inversión y Comercio Exterior",
    "301": "Banco Piano",
    "305": "Banco Julio",
    "309": "Nuevo Banco de la Rioja",
    "310": "Banco del Sol",
    "311": "Nuevo Banco del Chaco",
    "315": "Banco de Formosa",
    "319": "Banco CMF",
    "321": "Banco de Santiago del Estero",
    "322": "Banco Industrial",
    "330": "Nuevo Banco de Santa Fe",
    "331": "Banco Cetelem Argentina",
    "336": "Banco Bradesco Argentina",
    "338": "Banco de Servicios y Transacciones",
    "340": "BACS Banco de Crédito y Securitización",
    "384": "Wilobank",
    "386": "Nuevo Banco de Entre Ríos",
    "389": "Banco Columbia",
    "405": "Ford Credit Compañía Financiera",
    "408": "Compañía Financiera Argentina",
    "431": "Banco Coinag",
    "432": "Banco de Comercio",
    "438": "Cordial Compañía Financiera",
    "440": "Fiat Crédito Compañía Financiera",
    "441": "GPAT Compañía Financiera",
    "442": "Mercedes-Benz Compañía Financiera",
    "443": "Rombo Compañía Financiera",
    "444": "John Deere Credit Compañía Financiera",
    "445": "PSA Finance Argentina",
    "446": "Toyota Compañía Financiera",
    "448": "Finandino Compañía Financiera",
    "453": "Naranja X",
}


def detect_banco(cbu: str) -> str | None:
    """Detecta el banco desde los primeros 3 dígitos del CBU."""
    if not cbu or len(cbu) < 3:
        return None
    return CBU_BANCOS.get(cbu[:3])


def import_datos_bancarios(xlsx_path: str, dry_run: bool = True) -> dict:
    """Importa CBU y alias desde Excel, matcheando por DNI."""
    wb = openpyxl.load_workbook(xlsx_path)
    ws = wb.active

    # Leer Excel
    rows = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        if not row[0]:
            continue
        nombre = str(row[0]).strip()
        dni = str(row[1]).strip() if row[1] else ""
        cbu = str(row[3]).strip() if row[3] else ""
        alias = str(row[4]).strip() if row[4] else ""
        fecha_baja = row[17]

        if cbu == "None":
            cbu = ""
        if alias == "None":
            alias = ""

        rows.append(
            {
                "nombre": nombre,
                "dni": dni,
                "cbu": cbu,
                "alias": alias,
                "baja": fecha_baja is not None,
            }
        )

    print(f"Excel: {len(rows)} filas leidas")
    rows_con_cbu = [r for r in rows if r["cbu"]]
    print(f"  Con CBU: {len(rows_con_cbu)}")

    # Cargar empleados de la DB
    db = SessionLocal()
    try:
        result = db.execute(
            text("SELECT id, dni, legajo, nombre, apellido, banco_cbu FROM rrhh_empleados WHERE activo = true")
        )
        empleados = result.fetchall()
        emp_by_dni = {str(e.dni).strip(): e for e in empleados if e.dni}
        print(f"DB: {len(emp_by_dni)} empleados activos con DNI")

        actualizados = 0
        sin_match = []
        sin_cbu = []
        ya_tiene = []

        for row in rows:
            if not row["cbu"]:
                sin_cbu.append(row["nombre"])
                continue

            emp = emp_by_dni.get(row["dni"])
            if not emp:
                if not row["baja"]:
                    sin_match.append(f"{row['nombre']} (DNI {row['dni']})")
                continue

            # Ya tiene CBU cargado?
            if emp.banco_cbu and emp.banco_cbu == row["cbu"]:
                ya_tiene.append(f"{emp.legajo} - {emp.apellido}, {emp.nombre}")
                continue

            banco = detect_banco(row["cbu"])
            print(
                f"  {'[DRY]' if dry_run else '[UPD]'} {emp.legajo} {emp.apellido}, {emp.nombre}"
                f" → CBU={row['cbu'][:8]}... Alias={row['alias'] or '-'} Banco={banco or '?'}"
            )

            if not dry_run:
                params = {
                    "cbu": row["cbu"],
                    "alias": row["alias"] or None,
                    "banco": banco,
                    "emp_id": emp.id,
                }
                db.execute(
                    text("""
                        UPDATE rrhh_empleados
                        SET banco_cbu = :cbu,
                            banco_alias = :alias,
                            banco_nombre = COALESCE(:banco, banco_nombre)
                        WHERE id = :emp_id
                    """),
                    params,
                )

            actualizados += 1

        if not dry_run:
            db.commit()

        print(f"\n{'=== DRY RUN ===' if dry_run else '=== APLICADO ==='}")
        print(f"Actualizados: {actualizados}")
        print(f"Ya tenian CBU correcto: {len(ya_tiene)}")
        print(f"Sin CBU en Excel: {len(sin_cbu)}")

        if sin_match:
            print(f"\nSin match en DB ({len(sin_match)}) — crear estos empleados:")
            for s in sin_match:
                print(f"  {s}")

        return {"actualizados": actualizados, "sin_match": len(sin_match)}

    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Importar CBU/alias desde Excel")
    parser.add_argument("xlsx", help="Path al archivo Excel")
    parser.add_argument("--apply", action="store_true", default=False, help="Aplicar cambios (default: dry-run)")
    args = parser.parse_args()

    import_datos_bancarios(args.xlsx, dry_run=not args.apply)
