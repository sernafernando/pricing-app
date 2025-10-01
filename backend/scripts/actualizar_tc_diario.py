#!/usr/bin/env python3
import sys
import asyncio
sys.path.append('/var/www/html/pricing-app/backend')

from app.core.database import SessionLocal
from app.services.bna_scraper import actualizar_tipo_cambio

async def main():
    db = SessionLocal()
    try:
        resultado = await actualizar_tipo_cambio(db)
        print(resultado)
    finally:
        db.close()

if __name__ == "__main__":
    asyncio.run(main())
