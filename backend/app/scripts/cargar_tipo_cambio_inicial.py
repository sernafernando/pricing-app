import sys

sys.path.append("/var/www/html/pricing-app/backend")

from app.core.database import SessionLocal
from app.models.tipo_cambio import TipoCambio
from datetime import date


def cargar_tc():
    db = SessionLocal()

    try:
        # Tipo de cambio de hoy (ajustá estos valores según el BNA actual)
        tc = TipoCambio(fecha=date.today(), moneda="USD", compra=1350.0, venta=1400.0)

        db.add(tc)
        db.commit()

        print(f"✅ Tipo de cambio cargado: USD Compra {tc.compra} / Venta {tc.venta}")

    except Exception as e:
        db.rollback()
        print(f"❌ Error: {e}")
    finally:
        db.close()


if __name__ == "__main__":
    cargar_tc()
