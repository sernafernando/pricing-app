# Sincronización de Tienda Nube

El catálogo de Tienda Nube (productos, variantes, precios, publicado, vínculo con el ERP por SKU, nombre y
descripción) lo sincroniza el handler del worker `tienda_nube.sync`
(`backend/app/workers/handlers/tienda_nube_sync.py`), cada 15 minutos de 6 a 21 h. Ya no hay línea de cron ni script.

- Lógica compartida con `POST /api/tienda-nube/sync`: `backend/app/services/tienda_nube_sync_shared.py`
  (`sincronizar_catalogo`).
- Los vínculos producto ↔ Tienda Nube hechos a mano (`producto_tn_vinculos`) se aplican al final de cada pasada:
  siempre ganan sobre el match por SKU.
- Estado y último resultado: tabla `worker_job_state`, fila `tienda_nube.sync`.
- Para correrlo ya: `POST /api/tienda-nube/sync` (permiso `admin.gestionar_tn_publicacion`).
