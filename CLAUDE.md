# Pricing App - Contexto del Proyecto

## Descripción General
Sistema de gestión de precios para Gauss Online. Backend en FastAPI + PostgreSQL, frontend en React (Vite).

## Stack Técnico
- **Backend**: FastAPI, SQLAlchemy, PostgreSQL, Alembic (migraciones)
- **Frontend**: React 18, Vite, CSS Modules
- **Integraciones**: MercadoLibre API, Tienda Nube, ERP via gbp-parser (SOAP)

## Estructura de Directorios
```
backend/
  app/
    api/endpoints/     # Endpoints FastAPI
    models/            # Modelos SQLAlchemy
    services/          # Lógica de negocio
    scripts/           # Scripts de sincronización
  alembic/             # Migraciones de BD

frontend/
  src/
    pages/             # Páginas React
    components/        # Componentes reutilizables
    services/          # Llamadas API
```

## URLs y Ambientes
- **Producción**: https://pricing.gaussonline.com.ar
- **API**: https://pricing.gaussonline.com.ar/api
- **Docs**: https://pricing.gaussonline.com.ar/api/docs

## Modelos Importantes

### ProductoERP
- `item_id`: ID único del ERP (PK)
- `codigo`: Código/EAN del producto
- `descripcion`, `marca`, `categoria`
- `costo`, `moneda_costo` (ARS/USD), `iva`, `envio`
- `subcategoria_id`: Para determinar comisiones

### TipoCambio
- `fecha`, `moneda`, `compra`, `venta`
- `timestamp_actualizacion`: Datetime de última actualización

### PedidoPreparacionCache
- Cache de la query 67 del ERP (pedidos en preparación)
- Se sincroniza cada 5 minutos automáticamente
- Campos: `item_id`, `item_code`, `item_desc`, `cantidad`, `ml_logistic_type`, `prepara_paquete`

## Endpoints Clave

### Pricing
- `GET /api/precios/calcular-markup?item_code=XXX&precio=YYY` - Calcula markup dado un precio
- `POST /api/precios/calcular` - Cálculo completo de pricing

### Admin
- `GET /api/admin/tipo-cambio-actual` - TC actual con timestamp
- `POST /api/admin/sync-tipo-cambio` - Actualiza TC desde BNA

### Pedidos Preparación
- `GET /api/pedidos-preparacion/resumen` - Lista productos a preparar
- `POST /api/pedidos-preparacion/sync` - Fuerza sincronización con ERP
- Parámetros: `vista_produccion=true` filtra por EAN con "-" + Notebooks/NB/PC ARMADA/AIO

## Servicios Externos

### gbp-parser
- URL: `http://localhost:8002/api/gbp-parser`
- Wrapper para consultas SOAP al ERP
- Parámetro: `intExpgr_id` = ID de query del ERP (ej: 67 para pedidos preparación)

### MercadoLibre
- Sincronización de publicaciones y ventas
- Endpoints en `sync_ml.py`, `ventas_ml.py`

## Tareas de Background
- Sincronización de pedidos en preparación cada 5 minutos (main.py startup)

## Migraciones
```bash
cd backend
alembic revision --autogenerate -m "descripcion"
alembic upgrade head
```

## Notas Importantes
- El deploy lo maneja el usuario directamente (no usar SSH)
- Los commits llevan el footer de Claude Code
- Usar `codigo` (no `ean`) para buscar productos por código en ProductoERP
- Vista Producción: filtra EAN con guión + descripciones que empiezan con Notebook/NB/PC ARMADA/AIO
