# Deploy — modulo-compras

> **Change:** `modulo-compras` (v1) — primer release
> **Perfil de riesgo:** BAJO. Módulo 90% aditivo, sin cambios destructivos en tablas existentes.

---

## Qué podría romper (honesto)

| # | Cambio | Riesgo | Mitigación |
|---|--------|--------|------------|
| 1 | Hook en `sync_commercial_transactions_guid.py` | BAJO | Wrapped en try/except, no tumba el sync si falla |
| 2 | Handler de `app/core/exceptions.py` preserva dicts con `codigo` | BAJO | Verificado: ningún endpoint legacy usa `detail={"codigo":...}` |
| 3 | +4 columnas nullable en `etiquetas_envio` | NULO | Todas nullable con default, backward compat total |

**Lo demás es código nuevo aditivo** (8 tablas, 28 endpoints, 14 componentes frontend). No afecta nada existente.

---

## Deploy (pasos reales)

### 1. Backup DB (siempre primero)

```bash
pg_dump -h <host> -U <user> -d <dbname> -F c -f /backups/pre_deploy_compras_$(date +%Y%m%d_%H%M).dump
```

### 2. Pull + dependencias

```bash
cd /path/to/pricing-app
git checkout main
git pull origin main

# Solo si cambiaron requirements.txt o package.json
cd backend && source venv/bin/activate && pip install -r requirements.txt
cd ../frontend && npm install
```

### 3. Migraciones

```bash
cd backend && source venv/bin/activate
alembic upgrade head
alembic current  # debe imprimir: compras_014_vfactvig (head)
```

Si falla → restaurar del dump del paso 1 y revisar stacktrace.

### 4. Build frontend + restart

```bash
cd frontend && npm run build
sudo systemctl restart pricing-backend
sudo systemctl reload nginx
```

### 5. Smoke test

```bash
BASE_URL=https://pricing.miempresa.com
curl -s "$BASE_URL/api/administracion/compras/health" | jq .
# Esperado: {"status":"ok", "module":"compras", "catalogos":{"tb_sale_document":67}}
```

Ir al frontend con SUPERADMIN:
- [ ] `/administracion/compras` carga sin error 500
- [ ] Tab "Catálogo SD" muestra 67 filas

### 6. Asignar permisos (manual, desde `/admin/usuarios`)

Sin esto los tabs quedan invisibles para usuarios no-SUPERADMIN:

- **Rol aprobadores** (ej. GERENTE):
  - `administracion.aprobar_ordenes_compra`
  - `administracion.ver_ordenes_compra`
  - `administracion.ver_cuentas_corrientes`
- **Rol tesorería** (ej. ADMIN):
  - `administracion.ejecutar_pagos`
  - `administracion.gestionar_ordenes_compra`
- **Rol compradores/PMs**:
  - `administracion.ver_ordenes_compra`
  - `administracion.gestionar_ordenes_compra`
  - (**NO** aprobar — separación de funciones)

### 7. Cron de reconciliación diaria (opcional pero recomendado)

Agregar a crontab del servidor:

```
0 3 * * * cd /path/to/backend && source venv/bin/activate && python -m app.scripts.reconciliar_cc_proveedor >> /var/log/compras/reconciliacion.log 2>&1
```

Crear directorio de log:
```bash
sudo mkdir -p /var/log/compras && sudo chown <user-app>:<user-app> /var/log/compras
```

---

## Verificación post-deploy

El sync existente `sync_commercial_transactions_guid.py` (cada 10 min) ahora tiene el hook de matching. Verificar en las primeras corridas que los logs no muestren errores `[compras.matching] Hook falló`:

```bash
tail -f /var/log/cron-sync.log | grep -i compras
```

Si aparece repetidamente, revisar → NO tumba el sync pero el matching no estará funcionando.

---

## Herramienta de diagnóstico (opcional)

Si algo se ve raro post-deploy, correr:

```bash
cd backend && source venv/bin/activate
python -m app.scripts.verify_compras_pre_deploy
```

Valida: cajas USD por empresa, seeds populados, permisos existen, sync ERP al día. **NO es un gate obligatorio** — es diagnóstico para debugging.

---

## Rollback

### Opción A — Deshabilitar módulo sin tocar DB

1. Comentar el include del router en `backend/app/main.py`
2. Comentar la ruta en `frontend/src/App.jsx`
3. Restart backend + rebuild frontend
4. **DB intacta**, se puede re-habilitar sin perder datos

### Opción B — Revertir migraciones (drástico)

```bash
alembic downgrade -14   # deshace las 14 migraciones del módulo
```

Solo si la DB quedó en estado corrupto. Datos de pedidos/OPs/CC se pierden. Restaurar del dump si hace falta.

---

## Referencias

- `openspec/changes/modulo-compras/proposal.md` — qué y por qué
- `openspec/changes/modulo-compras/design.md` — decisiones técnicas
- `docs/modulos/compras-guia-usuario.md` — manual para usuarios
- `docs/modulos/compras-dev-guide.md` — guía técnica para devs
- `docs/modulos/compras-post-deploy-checklist.md` — monitoring 48h post-deploy
