# Pedidos Export - Visualizador de Pedidos TiendaNube

Sistema para visualizar y gestionar pedidos de exportación (principalmente TiendaNube).

## 📋 Estructura

### Base de Datos

#### Tabla: `tb_sale_order_header`
**Campos agregados:**
- `codigo_envio_interno` (String 100) - Para códigos QR en etiquetas de envío
- `export_id` (Integer) - ID del export del ERP (80 = pedidos pendientes TN)
- `export_activo` (Boolean) - True = activo, False = archivado

#### Tabla: `tb_user` (NUEVA)
Usuarios del ERP sincronizados desde Export 88.

**Campos:**
- `user_id` (PK) - ID único del usuario
- `user_name` - Nombre completo (firstname + lastname o nick)
- `user_loginname` - Nick del usuario (user_nick en ERP)
- `user_email` - Email
- `user_isactive` - Activo (user_login=1 AND user_Blocked=0)
- `user_lastupdate` - Última actualización desde ERP

### Backend

#### Endpoints: `/api/pedidos-export/`

**GET `/por-export/{export_id}`**
```
Obtiene pedidos filtrados por export_id.

Query params:
  - solo_activos: bool = true
  - user_id: int (opcional, ej: 50021 para TN, 50006 para ML)
  - ssos_id: int (opcional, estado del pedido)
  - solo_ml: bool = false (filtro por user_id = 50006)
  - solo_tn: bool = false (filtro por user_id = 50021)
  - sin_codigo_envio: bool = false (sin etiqueta)
  - limit: int = 100
  - offset: int = 0
```

**POST `/sincronizar-export-80`**
```
Sincroniza pedidos desde ERP Query 87 (sin filtros).
Aplica filtros localmente y marca pedidos como export_id=80.

Filtros aplicados en sincronización:
  - user_id IN (50021, 50006) - Vendedores TiendaNube y MercadoLibre
  - ssos_id = 20 (estado pendiente)
  - Excluye pedidos que SOLO tienen items 2953/2954
```

**GET `/estadisticas-sincronizacion`**
```
Estadísticas de la sincronización:
  - total_pedidos
  - activos
  - archivados
  - porcentaje_activos
```

#### Endpoints: `/api/usuarios-erp/`

**GET `/usuarios-erp`**
```
Lista usuarios del ERP.
Query params:
  - solo_activos: bool = true
```

**GET `/usuarios-erp/{user_id}`**
```
Obtiene un usuario específico por ID.
```

### Scripts de Sincronización

#### `scripts/sync_pedidos_export.py`
Sincroniza pedidos desde ERP Query 87.
- Llama a `/api/pedidos-export/sincronizar-export-80` (localhost, sin auth)
- Se ejecuta cada 5 minutos via cron
- Log: `/var/log/pricing-sync-pedidos.log`

#### `scripts/sync_usuarios_erp.py` (NUEVO)
Sincroniza usuarios desde ERP Export 88.
- Obtiene usuarios via gbp-parser
- Crea/actualiza registros en `tb_user`
- Ejecutar manualmente o agregar a cron

**Uso:**
```bash
cd /var/www/html/pricing-app/backend
venv/bin/python scripts/sync_usuarios_erp.py
```

### Frontend

#### Componente: `TabPedidosExport.jsx`
Visualizador de pedidos export con filtros.

**Filtros disponibles:**
- ✅ Solo Activos / Ver Todos
- ✅ Selector de Usuario (con TiendaNube destacado)
- ✅ Solo ML / Solo TN
- ✅ Sin etiqueta (sin código de envío)
- ✅ Búsqueda por texto (ID, ML Order, dirección)

**Estadísticas mostradas:**
- Total pedidos
- Activos
- Archivados
- Porcentaje activos

## 🔧 Configuración

### Cron Jobs

**Sincronización de pedidos (cada 5 min):**
```cron
*/5 * * * * cd /var/www/html/pricing-app/backend && venv/bin/python scripts/sync_pedidos_export.py >> /var/log/pricing-sync-pedidos.log 2>&1
```

**Sincronización de usuarios (diaria):**
```cron
0 6 * * * cd /var/www/html/pricing-app/backend && venv/bin/python scripts/sync_usuarios_erp.py >> /var/log/pricing-sync-usuarios.log 2>&1
```

### Migraciones

**Crear tablas:**
```bash
cd /var/www/html/pricing-app/backend
venv/bin/alembic upgrade head
```

**Migración inicial de usuarios:**
```bash
venv/bin/python scripts/sync_usuarios_erp.py
```

## 📊 Query SQL Original (Referencia)

La query original del visualizador TiendaNube era:

```sql
SELECT
    tsoh.cust_id AS [IDCliente],
    tsoh.soh_id AS [IDPedido],
    tsod.item_id AS [item_id],
    ti.item_code AS [EAN],
    ti.item_desc AS [Descripción],
    tsod.sod_qty AS [Cantidad],
    tsoh.soh_observation2 AS [Tipo de Envío],
    tsoh.soh_deliveryAddress AS [Dirección de Envío],
    NULLIF(TRIM(REPLACE(tsoh.soh_observation1, 'NaN', '')), '') AS [Observaciones],
    tsoh.soh_deliveryDate AS [Fecha de envío],
    tsoh.soh_internalAnnotation AS [Orden TN],
    tc.cust_name AS [NombreCliente],
    ttno.tno_orderID [orderID],
    tsoh.user_id [userID]
FROM
    tbSaleOrderHeader tsoh
LEFT JOIN
    tbSaleOrderDetail tsod ON tsod.bra_id = tsoh.bra_id AND tsod.soh_id = tsoh.soh_id
LEFT JOIN
    tbItem ti ON ti.item_id = tsod.item_id
LEFT JOIN
    tbCustomer tc ON tc.cust_id = tsoh.cust_id
LEFT JOIN 
    tbTiendaNube_Orders ttno ON ttno.bra_id = tsoh.bra_id AND ttno.soh_id = tsoh.soh_id
WHERE
    tsoh.ssos_id = 20
    AND tsod.item_id NOT IN (2953, 2954)
ORDER BY
    tsoh.soh_id, tsod.item_id;
```

**Filtros clave:**
- `ssos_id = 20` → Estado pendiente de preparación
- `item_id NOT IN (2953, 2954)` → Excluir items de servicio/envío
- `user_id = 50021` → Vendedor TiendaNube (aplicado desde frontend)

## 🚀 Uso

### Desde el Frontend

1. **Ir a "Pedidos en Preparación"**
2. **Click en tab "Export (ERP Query 80)"**
3. **Filtrar por usuario TiendaNube:**
   - Selector: "🛒 TiendaNube (50021)"
4. **Aplicar filtros adicionales:**
   - Solo ML / Solo TN
   - Sin etiqueta (pendientes de imprimir)
   - Búsqueda por texto

### Sincronización Manual

**Desde el frontend:**
- Click en botón "🔄 Sincronizar desde ERP"

**Desde el servidor:**
```bash
cd /var/www/html/pricing-app/backend
venv/bin/python scripts/sync_pedidos_export.py
```

## 🔍 Debugging

**Ver logs de sincronización:**
```bash
tail -f /var/log/pricing-sync-pedidos.log
tail -f /var/log/pricing-sync-usuarios.log
```

**Ver pedidos activos en DB:**
```sql
SELECT count(*) 
FROM tb_sale_order_header 
WHERE export_id = 80 AND export_activo = true;
```

**Ver usuarios sincronizados:**
```sql
SELECT user_id, user_name, user_loginname, user_isactive 
FROM tb_user 
WHERE user_isactive = true
ORDER BY user_name;
```

## 📝 TODOs Futuros

- [ ] JOIN con `tb_customer` para traer nombre del cliente
- [ ] JOIN con `tb_item` para traer items del pedido
- [ ] Consulta a TiendaNube API para datos adicionales
- [ ] Generación de etiquetas ZPL para impresoras Zebra
- [ ] Asignación automática de códigos de envío
- [ ] Expandible rows para ver items del pedido
