from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from datetime import UTC, datetime
import asyncio
from app.api.endpoints import (
    sync,
    productos,
    pricing,
    admin,
    auth,
    usuarios,
    auditoria,
    sync_ml,
    marcas_pm,
    mla_banlist,
    producto_banlist,
    ventas_ml,
    ventas_fuera_ml,
    commercial_transactions,
    comisiones,
    calculos,
    configuracion,
    items_sin_mla,
    dashboard_ml,
    dashboard_tplink,
    erp_sync,
    ml_catalog,
    tienda_nube,
    gbp_parser,
    notificaciones,
    offsets_ganancia,
    rentabilidad,
    rentabilidad_fuera,
    vendedores_excluidos,
    ventas_tienda_nube,
    rentabilidad_tienda_nube,
    permisos,
    markups_tienda,
    roles,
    pedidos_preparacion,
    clientes,
    pedidos_export,
    usuarios_erp,
    pedidos_export_v2,
    pedidos_export_simple,
    produccion_banlist,
    turbo_routing,
    pedidos_export_local,
    sale_order_status,
    asignaciones,
    cuentas_corrientes,
    codigos_postales,
    logisticas,
    etiquetas_envio,
    config_operaciones,
    sounds,
    transportes,
    etiquetas_colecta,
    colectas,
    etiquetas_zpl_tools,
)
from app.routers import (
    consultas,
    administracion_bancos,
    administracion_caja,
    administracion_cheques,
    administracion_compras,
    administracion_impuestos,
    administracion_proveedores,
    alertas,
    claims_dashboard,
    document_templates,
    empresas,
    free_shipping_alerts,
    prearmado,
    prearmado_stats,
    rrhh_empleados,
    rrhh_fichaje_mobile,
    rrhh_presentismo,
    rrhh_sanciones,
    rrhh_vacaciones,
    rrhh_cuenta_corriente,
    rrhh_horarios,
    rrhh_horas_extras,
    rrhh_cumpleanos,
    rrhh_reportes,
    seriales,
    sse,
    rma_seguimiento,
    rma_control_deposito,
    rma_proveedores,
    weather,
)
from app.tickets.api.endpoints import (
    tickets as tickets_ep,
    sectores as sectores_ep,
    workflows as workflows_ep,
)
from app.core.config import settings
from app.core.exceptions import http_exception_handler
from app.core.logging import get_logger

# Importar `app.events.rrhh_he_hooks` dispara los `@event.listens_for` que
# detectan modificaciones de fichadas / cambios de turno y generan alertas
# o recálculos de Horas Extras. DEBE ocurrir ANTES de `include_router(...)`
# para que los listeners estén activos cuando empiece a aceptar requests.
from app.events import rrhh_he_hooks  # noqa: F401  (side-effect: registra listeners)

logger = get_logger(__name__)

# ── Worker-level lock for background tasks ───────────────────────
# With multiple uvicorn workers, lifespan() runs on EACH worker.
# Without a lock, background tasks run N times (once per worker),
# causing duplicated DB writes, TRUNCATE races, and wasted resources.
# Only one worker acquires the lock; the rest skip background tasks.

_BG_LOCK_PATH = "/tmp/pricing-bg-tasks.lock"


def _try_acquire_bg_lock():
    """Try to acquire exclusive lock for background tasks. Returns fd or None."""
    import fcntl
    import os

    try:
        lock_fd = open(_BG_LOCK_PATH, "w")
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        lock_fd.write(str(os.getpid()))
        lock_fd.flush()
        return lock_fd  # Keep fd open — lock releases when process exits
    except OSError:
        return None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown lifecycle manager."""
    from redis.asyncio import Redis as AsyncRedis

    from app.core.sse import SSEConnectionManager, set_redis

    logger.info("Pricing API started (version=%s, env=%s)", app.version, settings.ENVIRONMENT)
    logger.info("CORS allowed origins: %s", settings.cors_origins)

    # ── Redis for SSE pub/sub (best-effort — app works without it) ─
    redis = None
    sse_manager = None
    try:
        redis = AsyncRedis.from_url(settings.REDIS_URL, decode_responses=False)
        await redis.ping()
        set_redis(redis, loop=asyncio.get_running_loop())
        app.state.redis = redis

        sse_manager = SSEConnectionManager(redis, max_connections=settings.SSE_MAX_CONNECTIONS)
        await sse_manager.start()
        app.state.sse_manager = sse_manager
        app.state.sse_heartbeat_seconds = settings.SSE_HEARTBEAT_SECONDS
        logger.info("SSE enabled (Redis connected)")
    except Exception:
        logger.warning("Redis unavailable — SSE disabled, polling fallback active")
        app.state.redis = None
        app.state.sse_manager = None
        app.state.sse_heartbeat_seconds = 30

    # ── Background tasks (only on ONE worker) ─────────────────────
    bg_lock_fd = _try_acquire_bg_lock()
    bg_tasks = []

    if bg_lock_fd:
        import os

        logger.info("This worker (pid=%d) owns background tasks", os.getpid())
        bg_tasks = [
            asyncio.create_task(sync_pedidos_preparacion_task()),
            asyncio.create_task(free_shipping_auto_fix_task()),
            asyncio.create_task(sync_sale_orders_task()),
        ]
    else:
        import os

        logger.info("This worker (pid=%d) skips background tasks (another worker owns them)", os.getpid())

    yield

    # Shutdown
    logger.info("Pricing API shutting down")
    for task in bg_tasks:
        task.cancel()
    for task in bg_tasks:
        try:
            await task
        except asyncio.CancelledError:
            pass

    if sse_manager:
        await sse_manager.stop()
    if redis:
        await redis.close()
    if bg_lock_fd:
        import fcntl

        fcntl.flock(bg_lock_fd, fcntl.LOCK_UN)
        bg_lock_fd.close()


app = FastAPI(
    title="Pricing API",
    description="API para gestión de precios de productos",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

# Global error handler — ensures all errors follow the standard envelope
app.add_exception_handler(HTTPException, http_exception_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=[
        "X-Etiquetas-Detectadas",
        "X-LH-Modificados",
        "X-LH-Heterogeneo",
        "X-LL-Warning",
        "Content-Disposition",
    ],
)

# Incluir routers
app.include_router(auth.router, prefix="/api", tags=["Autenticación"])
app.include_router(sync.router, prefix="/api", tags=["Sincronización"])
app.include_router(productos.router, prefix="/api", tags=["Productos"])
app.include_router(pricing.router, prefix="/api", tags=["Pricing"])
app.include_router(admin.router, prefix="/api", tags=["Admin"])
app.include_router(usuarios.router, prefix="/api", tags=["usuarios"])
app.include_router(auditoria.router, prefix="/api", tags=["auditoria"])
app.include_router(sync_ml.router, prefix="/api", tags=["sync-ml"])
app.include_router(marcas_pm.router, prefix="/api", tags=["marcas-pm"])
app.include_router(mla_banlist.router, prefix="/api", tags=["mla-banlist"])
app.include_router(producto_banlist.router, prefix="/api", tags=["producto-banlist"])
app.include_router(ventas_ml.router, prefix="/api", tags=["ventas-ml"])
app.include_router(ventas_fuera_ml.router, prefix="/api", tags=["ventas-fuera-ml"])
app.include_router(commercial_transactions.router, prefix="/api", tags=["commercial-transactions"])
app.include_router(comisiones.router, prefix="/api", tags=["comisiones"])
app.include_router(calculos.router, prefix="/api", tags=["calculos"])
app.include_router(configuracion.router, prefix="/api", tags=["configuracion"])
app.include_router(items_sin_mla.router, prefix="/api/items-sin-mla", tags=["items-sin-mla"])
app.include_router(dashboard_ml.router, prefix="/api", tags=["dashboard-ml"])
app.include_router(dashboard_tplink.router, prefix="/api", tags=["dashboard-tplink"])
app.include_router(erp_sync.router, prefix="/api", tags=["erp-sync"])
app.include_router(ml_catalog.router, prefix="/api/ml-catalog", tags=["ml-catalog"])
app.include_router(tienda_nube.router, prefix="/api/tienda-nube", tags=["tienda-nube"])
app.include_router(gbp_parser.router, prefix="/api", tags=["gbp-parser"])
app.include_router(notificaciones.router, prefix="/api", tags=["notificaciones"])
app.include_router(offsets_ganancia.router, prefix="/api", tags=["offsets-ganancia"])
app.include_router(rentabilidad.router, prefix="/api", tags=["rentabilidad"])
app.include_router(rentabilidad_fuera.router, prefix="/api", tags=["rentabilidad-fuera"])
app.include_router(vendedores_excluidos.router, prefix="/api", tags=["vendedores-excluidos"])
app.include_router(ventas_tienda_nube.router, prefix="/api", tags=["ventas-tienda-nube"])
app.include_router(rentabilidad_tienda_nube.router, prefix="/api", tags=["rentabilidad-tienda-nube"])
app.include_router(permisos.router, prefix="/api", tags=["permisos"])
app.include_router(markups_tienda.router, prefix="/api", tags=["markups-tienda"])
app.include_router(roles.router, prefix="/api", tags=["roles"])
app.include_router(pedidos_preparacion.router, prefix="/api", tags=["pedidos-preparacion"])
app.include_router(clientes.router, prefix="/api", tags=["clientes"])
app.include_router(pedidos_export.router, prefix="/api", tags=["pedidos-export"])
app.include_router(pedidos_export_v2.router, prefix="/api", tags=["pedidos-export-v2"])
app.include_router(pedidos_export_simple.router, prefix="/api", tags=["pedidos-export-simple"])
app.include_router(pedidos_export_local.router, prefix="/api", tags=["pedidos-export-local"])
app.include_router(sale_order_status.router, prefix="/api", tags=["sale-order-status"])
app.include_router(usuarios_erp.router, prefix="/api", tags=["usuarios-erp"])
app.include_router(produccion_banlist.router, prefix="/api", tags=["produccion-banlist"])
app.include_router(prearmado.router, prefix="/api", tags=["prearmado"])
app.include_router(prearmado_stats.router, prefix="/api", tags=["prearmados-stats"])
app.include_router(turbo_routing.router, prefix="/api", tags=["turbo-routing"])
app.include_router(alertas.router, prefix="/api", tags=["alertas"])
app.include_router(asignaciones.router, prefix="/api/asignaciones", tags=["asignaciones"])
app.include_router(cuentas_corrientes.router, prefix="/api", tags=["cuentas-corrientes"])
app.include_router(codigos_postales.router, prefix="/api", tags=["codigos-postales"])
app.include_router(logisticas.router, prefix="/api", tags=["logisticas"])
app.include_router(etiquetas_envio.router, prefix="/api", tags=["etiquetas-envio"])
app.include_router(config_operaciones.router, prefix="/api", tags=["config-operaciones"])
app.include_router(sounds.router, prefix="/api", tags=["sounds"])
app.include_router(transportes.router, prefix="/api", tags=["transportes"])
app.include_router(seriales.router, prefix="/api", tags=["seriales"])
app.include_router(rma_seguimiento.router, prefix="/api", tags=["rma-seguimiento"])
app.include_router(rma_control_deposito.router, prefix="/api", tags=["rma-control-deposito"])
app.include_router(rma_proveedores.router, prefix="/api", tags=["RMA Proveedores"])
app.include_router(claims_dashboard.router, prefix="/api", tags=["Claims Dashboard"])
app.include_router(etiquetas_colecta.router, prefix="/api", tags=["etiquetas-colecta"])
app.include_router(colectas.router, prefix="/api", tags=["colectas"])
app.include_router(etiquetas_zpl_tools.router, prefix="/api", tags=["etiquetas-zpl-tools"])
app.include_router(weather.router, prefix="/api", tags=["weather"])
app.include_router(free_shipping_alerts.router, prefix="/api", tags=["free-shipping-alerts"])
app.include_router(document_templates.router, prefix="/api", tags=["document-templates"])
app.include_router(rrhh_empleados.router, prefix="/api", tags=["rrhh"])
app.include_router(rrhh_presentismo.router, prefix="/api", tags=["rrhh-presentismo"])
app.include_router(rrhh_sanciones.router, prefix="/api", tags=["rrhh-sanciones"])
app.include_router(rrhh_vacaciones.router, prefix="/api", tags=["rrhh-vacaciones"])
app.include_router(rrhh_cuenta_corriente.router, prefix="/api", tags=["rrhh-cuenta-corriente"])
app.include_router(rrhh_horarios.router, prefix="/api", tags=["rrhh-horarios"])
app.include_router(rrhh_horas_extras.router, prefix="/api", tags=["rrhh-horas-extras"])
app.include_router(rrhh_fichaje_mobile.router, prefix="/api", tags=["rrhh-fichaje-mobile"])
app.include_router(rrhh_cumpleanos.router, prefix="/api", tags=["rrhh-cumpleanos"])
app.include_router(rrhh_reportes.router, prefix="/api", tags=["rrhh-reportes"])
app.include_router(sse.router, prefix="/api", tags=["SSE"])

# ── Módulo Consultas ───────────────────────────────────────────────
app.include_router(consultas.router, prefix="/api")

# ── Módulo Administración (sector empresa) ────────────────────────
app.include_router(empresas.router, prefix="/api", tags=["admin-empresas"])
app.include_router(administracion_proveedores.router, prefix="/api", tags=["Administración - Proveedores"])
app.include_router(administracion_bancos.router, prefix="/api", tags=["Administración - Bancos"])
app.include_router(administracion_impuestos.router, prefix="/api", tags=["Administración - Impuestos"])
app.include_router(administracion_caja.router, prefix="/api", tags=["Administración - Caja"])
app.include_router(administracion_compras.router, prefix="/api", tags=["Administración - Compras"])
app.include_router(administracion_cheques.router, prefix="/api", tags=["Administración - Cheques"])

# ── Tickets module ────────────────────────────────────────────────
app.include_router(tickets_ep.router, prefix="/api/tickets", tags=["tickets"])
app.include_router(sectores_ep.router, prefix="/api/tickets", tags=["tickets-sectores"])
app.include_router(workflows_ep.router, prefix="/api/tickets", tags=["tickets-workflows"])


@app.get("/")
async def root():
    return {"message": "Pricing API", "version": "1.0.0", "status": "running"}


@app.get("/health")
async def health():
    return {"status": "ok", "timestamp": datetime.now(UTC).isoformat()}


async def sync_pedidos_preparacion_task():
    """
    Tarea de background que sincroniza pedidos en preparación cada 5 minutos.
    """
    from app.scripts.sync_pedidos_preparacion import sync_pedidos_preparacion

    # Esperar 30 segundos después del inicio para que todo esté listo
    await asyncio.sleep(30)
    logger.info("Background task started: sync pedidos preparacion (interval=300s)")

    while True:
        try:
            await sync_pedidos_preparacion()
        except Exception as e:
            logger.error("Sync pedidos preparacion failed: %s", e, exc_info=True)

        # Esperar 5 minutos
        await asyncio.sleep(300)


async def sync_sale_orders_task():
    """
    Tarea de background que sincroniza sale orders del ERP cada 10 minutos.
    Trae headers + details actualizados de los últimos 7 días.
    """
    from app.scripts.sync_sale_orders_all import main_async

    # Esperar 60 segundos para no competir con el startup
    await asyncio.sleep(60)
    logger.info("Background task started: sync sale orders (interval=600s)")

    while True:
        try:
            await main_async(days=7)
        except Exception as e:
            logger.error("Sync sale orders failed: %s", e, exc_info=True)

        # Esperar 10 minutos
        await asyncio.sleep(600)


async def free_shipping_auto_fix_task():
    """
    Tarea de background que desactiva envío gratis en publicaciones
    con free_shipping_error=true (no mandatory) cada 5 minutos.
    """
    from app.services.free_shipping_auto_fix import run_free_shipping_auto_fix

    # Esperar 60 segundos para que todo esté listo (DB, ML client, etc.)
    await asyncio.sleep(60)
    logger.info("Background task started: free_shipping_auto_fix (interval=300s)")

    while True:
        try:
            stats = await run_free_shipping_auto_fix()
            if stats["fixed"] > 0 or stats["failed"] > 0:
                logger.info("Free shipping auto-fix stats: %s", stats)
        except Exception as e:
            logger.error("Free shipping auto-fix failed: %s", e, exc_info=True)

        # Esperar 5 minutos
        await asyncio.sleep(300)
