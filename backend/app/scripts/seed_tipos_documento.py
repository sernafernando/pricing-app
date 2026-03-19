"""
Seed de tipos de documento para legajos de empleados.

Uso:
  cd backend
  source venv/bin/activate
  python -m app.scripts.seed_tipos_documento
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from app.core.database import SessionLocal
from app.models.rrhh_tipo_documento import RRHHTipoDocumento

TIPOS = [
    # ── Documentación personal ──
    {"nombre": "DNI Frente", "descripcion": "Foto/scan del frente del DNI", "requiere_vencimiento": False, "orden": 1},
    {"nombre": "DNI Dorso", "descripcion": "Foto/scan del dorso del DNI", "requiere_vencimiento": False, "orden": 2},
    {"nombre": "CUIL", "descripcion": "Constancia de CUIL (ANSES)", "requiere_vencimiento": False, "orden": 3},
    {
        "nombre": "Certificado de Domicilio",
        "descripcion": "Certificado de domicilio actualizado",
        "requiere_vencimiento": True,
        "orden": 4,
    },
    {
        "nombre": "Partida de Nacimiento",
        "descripcion": "Partida/acta de nacimiento",
        "requiere_vencimiento": False,
        "orden": 5,
    },
    # ── Documentación laboral - ingreso ──
    {
        "nombre": "Contrato de Trabajo",
        "descripcion": "Contrato laboral firmado",
        "requiere_vencimiento": False,
        "orden": 10,
    },
    {
        "nombre": "Alta Temprana AFIP",
        "descripcion": "Comprobante de alta temprana en AFIP",
        "requiere_vencimiento": False,
        "orden": 11,
    },
    {
        "nombre": "Declaración Jurada de Domicilio",
        "descripcion": "DDJJ de domicilio firmada por el empleado",
        "requiere_vencimiento": False,
        "orden": 12,
    },
    {
        "nombre": "Ficha de Ingreso",
        "descripcion": "Ficha de ingreso completa y firmada",
        "requiere_vencimiento": False,
        "orden": 13,
    },
    {
        "nombre": "Apto Médico",
        "descripcion": "Certificado de aptitud médica preocupacional",
        "requiere_vencimiento": True,
        "orden": 14,
    },
    {
        "nombre": "Examen Preocupacional",
        "descripcion": "Resultado del examen preocupacional",
        "requiere_vencimiento": False,
        "orden": 15,
    },
    # ── Documentación laboral - durante la relación ──
    {
        "nombre": "Recibo de Sueldo",
        "descripcion": "Recibo de haberes firmado",
        "requiere_vencimiento": False,
        "orden": 20,
    },
    {
        "nombre": "Certificado de Capacitación",
        "descripcion": "Certificado de capacitación/curso realizado",
        "requiere_vencimiento": True,
        "orden": 21,
    },
    {
        "nombre": "Acuerdo de Confidencialidad",
        "descripcion": "NDA firmado por el empleado",
        "requiere_vencimiento": False,
        "orden": 22,
    },
    {
        "nombre": "Entrega de Indumentaria",
        "descripcion": "Constancia de entrega de ropa de trabajo/EPP",
        "requiere_vencimiento": False,
        "orden": 23,
    },
    {
        "nombre": "Entrega de Herramientas",
        "descripcion": "Constancia de entrega de herramientas/equipos",
        "requiere_vencimiento": False,
        "orden": 24,
    },
    # ── Documentación de baja ──
    {
        "nombre": "Telegrama de Renuncia",
        "descripcion": "Telegrama de renuncia del empleado",
        "requiere_vencimiento": False,
        "orden": 30,
    },
    {
        "nombre": "Telegrama de Despido",
        "descripcion": "Telegrama de despido enviado al empleado",
        "requiere_vencimiento": False,
        "orden": 31,
    },
    {
        "nombre": "Acta de Desvinculación",
        "descripcion": "Acta de desvinculación firmada por ambas partes",
        "requiere_vencimiento": False,
        "orden": 32,
    },
    {
        "nombre": "Acuerdo de Desvinculación",
        "descripcion": "Acuerdo de desvinculación con condiciones pactadas",
        "requiere_vencimiento": False,
        "orden": 33,
    },
    {
        "nombre": "Certificación de Servicios",
        "descripcion": "Certificación de servicios y remuneraciones (art. 80 LCT)",
        "requiere_vencimiento": False,
        "orden": 34,
    },
    {
        "nombre": "Liquidación Final",
        "descripcion": "Liquidación final firmada por el empleado",
        "requiere_vencimiento": False,
        "orden": 35,
    },
    {
        "nombre": "Libre Deuda",
        "descripcion": "Constancia de libre deuda del empleado",
        "requiere_vencimiento": False,
        "orden": 36,
    },
    {
        "nombre": "Devolución de Materiales",
        "descripcion": "Constancia de devolución de equipos/herramientas",
        "requiere_vencimiento": False,
        "orden": 37,
    },
    # ── Sanciones ──
    {
        "nombre": "Sanción - Apercibimiento",
        "descripcion": "Notificación de apercibimiento firmada",
        "requiere_vencimiento": False,
        "orden": 40,
    },
    {
        "nombre": "Sanción - Severo Apercibimiento",
        "descripcion": "Notificación de severo apercibimiento firmada",
        "requiere_vencimiento": False,
        "orden": 41,
    },
    {
        "nombre": "Sanción - Suspensión",
        "descripcion": "Notificación de suspensión firmada",
        "requiere_vencimiento": False,
        "orden": 42,
    },
    # ── ART / Médico ──
    {
        "nombre": "Certificado Médico",
        "descripcion": "Certificado médico de licencia/reposo",
        "requiere_vencimiento": True,
        "orden": 50,
    },
    {
        "nombre": "Denuncia ART",
        "descripcion": "Formulario de denuncia ante la ART",
        "requiere_vencimiento": False,
        "orden": 51,
    },
    {
        "nombre": "Alta Médica ART",
        "descripcion": "Alta médica emitida por la ART",
        "requiere_vencimiento": False,
        "orden": 52,
    },
    # ── Otros ──
    {
        "nombre": "Foto Carnet",
        "descripcion": "Foto carnet 4x4 del empleado",
        "requiere_vencimiento": False,
        "orden": 60,
    },
    {
        "nombre": "CV / Currículum",
        "descripcion": "Currículum vitae del empleado",
        "requiere_vencimiento": False,
        "orden": 61,
    },
    {
        "nombre": "Otro",
        "descripcion": "Documento que no encaja en las categorías anteriores",
        "requiere_vencimiento": False,
        "orden": 99,
    },
]


def main() -> None:
    db = SessionLocal()
    try:
        created = 0
        skipped = 0

        for tipo_data in TIPOS:
            existing = db.query(RRHHTipoDocumento).filter(RRHHTipoDocumento.nombre == tipo_data["nombre"]).first()
            if existing:
                skipped += 1
                continue

            tipo = RRHHTipoDocumento(**tipo_data)
            db.add(tipo)
            created += 1

        db.commit()
        print(f"Tipos de documento: {created} creados, {skipped} ya existían")

    except Exception as e:
        db.rollback()
        print(f"ERROR: {e}")
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
