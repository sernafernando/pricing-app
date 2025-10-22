import sys
sys.path.append('/var/www/html/pricing-app/backend')

from app.services.google_sheets_sync import obtener_datos_sheets

data = obtener_datos_sheets()
if data:
    print("Headers encontrados:")
    for key in data[0].keys():
        print(f"  - '{key}'")
    
    print("\nPrimera fila de ejemplo:")
    for key, value in list(data[0].items())[:10]:
        print(f"  {key}: {value}")
