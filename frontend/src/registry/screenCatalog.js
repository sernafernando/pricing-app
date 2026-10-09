/**
 * Declarative catalog of the app's screens, for the Admin permission panels.
 *
 * Each entry: { path, label, section, permisos, scope, fullViewPermisos?, nota? }
 *   - permisos: any-of, exactly like App.jsx `protectedRoutes` (`permiso` or
 *     `permisos`). Empty = no per-route permission (any logged-in user).
 *   - scope:
 *       'permiso' -> the permission alone decides what the user sees.
 *       'data'    -> the backend also filters rows by the user's marca/categoría
 *                    pairs (backend/app/services/pm_scope.py): with the
 *                    permission but zero pairs the screen opens empty.
 *       'public'  -> no permission needed.
 *   - fullViewPermisos: for a 'data' screen whose bypass is NOT pm_scope's
 *     is_full_view (the ranking bypasses with consultas.ver_ranking only).
 *
 * Labels and sections mirror Sidebar.jsx `menuSections`; routes outside the
 * sidebar live under "Otras". `screenCatalog.test.js` reads App.jsx and
 * Sidebar.jsx sources and fails on any drift.
 */

const OTRAS = 'Otras';

// Routes intentionally left out of the catalog (each must still exist in App.jsx).
// /test-stats-dinamicos: developer test page (TestStatsDinamicos.jsx), no sidebar
// entry; its permission (admin.sincronizar) still shows under "Permisos sin pantalla"
// if no other screen references it.
export const EXCLUDED_ROUTES = ['/test-stats-dinamicos'];

export const SCREENS = [
  // ── Productos ─────────────────────────────────────────────
  { path: '/productos', label: 'Productos', section: 'Productos', permisos: ['productos.ver'], scope: 'permiso' },
  { path: '/tienda', label: 'Tienda', section: 'Productos', permisos: ['productos.ver_tienda'], scope: 'permiso' },
  { path: '/precios-listas', label: 'Precios por Lista', section: 'Productos', permisos: ['productos.ver'], scope: 'permiso' },
  { path: '/mla-banlist', label: 'Banlist MLAs', section: 'Productos', permisos: ['admin.gestionar_mla_banlist'], scope: 'permiso' },
  { path: '/items-sin-mla', label: 'Items sin MLA', section: 'Productos', permisos: ['admin.ver_items_sin_mla'], scope: 'permiso' },
  { path: '/prearmadas-disponibles', label: 'Prearmadas disponibles', section: 'Productos', permisos: ['produccion.ver_prearmadas_stats'], scope: 'permiso' },

  // ── Operaciones ───────────────────────────────────────────
  { path: '/pedidos-preparacion', label: 'Preparación', section: 'Operaciones', permisos: ['ordenes.ver_preparacion'], scope: 'permiso' },
  { path: '/produccion', label: 'Producción', section: 'Operaciones', permisos: ['produccion.ver_combos'], scope: 'permiso' },
  { path: '/prearmado', label: 'Prearmado', section: 'Operaciones', permisos: ['produccion.prearmar_combos'], scope: 'permiso' },
  { path: '/turbo-routing', label: 'Turbo', section: 'Operaciones', permisos: ['ordenes.gestionar_turbo_routing'], scope: 'permiso' },
  { path: '/clientes', label: 'Clientes', section: 'Operaciones', permisos: ['clientes.ver'], scope: 'permiso' },
  { path: '/config-operaciones', label: 'Configuración', section: 'Operaciones', permisos: ['envios_flex.config'], scope: 'permiso' },
  { path: '/etiquetas/reescribir-lh', label: 'Reescribir ^LH', section: 'Operaciones', permisos: ['etiquetas.reescribir_lh'], scope: 'permiso' },

  // ── Consultas ─────────────────────────────────────────────
  { path: '/traza', label: 'Traza', section: 'Consultas', permisos: ['traza.ver'], scope: 'permiso' },
  { path: '/seguimiento-envios', label: 'Seguimiento Envíos', section: 'Consultas', permisos: ['seguimiento_envios.ver'], scope: 'permiso' },
  { path: '/cumpleanos', label: 'Cumpleaños', section: 'Consultas', permisos: [], scope: 'public' },

  // ── Soporte ───────────────────────────────────────────────
  { path: '/rma', label: 'RMA Seguimiento', section: 'Soporte', permisos: ['rma.ver'], scope: 'permiso' },
  { path: '/control-deposito', label: 'Control Depósito', section: 'Soporte', permisos: ['rma.control_deposito'], scope: 'permiso' },
  { path: '/claims', label: 'Reclamos ML', section: 'Soporte', permisos: ['rma.ver'], scope: 'permiso' },
  { path: '/ml-preguntas', label: 'Bot de Preguntas ML', section: 'Soporte', permisos: ['ml_bot.ver'], scope: 'permiso' },

  // ── Reportes ──────────────────────────────────────────────
  {
    path: '/consultas/ranking',
    label: 'Ranking productos',
    section: 'Reportes',
    permisos: ['consultas.ver_ranking', 'consultas.ver_mi_ranking'],
    scope: 'data',
    // backend/app/routers/consultas.py `_scope_user_id`: only ver_ranking (or
    // SUPERADMIN) lifts the pair filter; a full-view role does not.
    fullViewPermisos: ['consultas.ver_ranking'],
  },
  // ml_metricas router + ml_daily_metrics/board.py -> pm_scope.
  { path: '/metricas-ml', label: 'Métricas ML', section: 'Reportes', permisos: ['ml_metricas.ver'], scope: 'data' },
  // dashboard_ml.py, ventas_ml.py operaciones and /rentabilidad (TabRentabilidad) -> pm_scope.
  { path: '/dashboard-metricas-ml', label: 'Métricas ML (anterior)', section: 'Reportes', permisos: ['ventas_ml.ver_dashboard'], scope: 'data' },
  { path: '/ml-ventas-listado', label: 'Ventas ML', section: 'Reportes', permisos: ['ml_ops.ver'], scope: 'permiso' },
  { path: '/ml-ventas-divergencias', label: 'Divergencias ML Ventas', section: 'Reportes', permisos: ['ml_ops.ver'], scope: 'permiso' },
  { path: '/dashboard-tplink', label: 'Dashboard TP-Link', section: 'Reportes', permisos: ['dashboard_tplink.ver'], scope: 'permiso' },
  { path: '/dashboard-ventas-fuera', label: 'Ventas por Fuera', section: 'Reportes', permisos: ['ventas_fuera.ver_dashboard'], scope: 'permiso' },
  { path: '/dashboard-tienda-nube', label: 'Tienda Nube', section: 'Reportes', permisos: ['ventas_tn.ver_dashboard'], scope: 'permiso' },
  { path: '/calculos', label: 'Cálculos', section: 'Reportes', permisos: ['reportes.ver_calculadora'], scope: 'permiso' },
  { path: '/ultimos-cambios', label: 'Últimos Cambios', section: 'Reportes', permisos: ['productos.ver_auditoria'], scope: 'permiso' },
  { path: '/novedades', label: 'Novedades', section: 'Reportes', permisos: [], scope: 'public' },
  { path: '/cuentas-corrientes', label: 'Cuentas Corrientes', section: 'Reportes', permisos: ['reportes.ver_cuentas_corrientes'], scope: 'permiso' },

  // ── RRHH ──────────────────────────────────────────────────
  { path: '/rrhh/empleados', label: 'Empleados', section: 'RRHH', permisos: ['rrhh.ver'], scope: 'permiso' },
  { path: '/rrhh/presentismo', label: 'Presentismo', section: 'RRHH', permisos: ['rrhh.ver'], scope: 'permiso' },
  { path: '/rrhh/sanciones', label: 'Sanciones', section: 'RRHH', permisos: ['rrhh.ver'], scope: 'permiso' },
  { path: '/rrhh/vacaciones', label: 'Vacaciones', section: 'RRHH', permisos: ['rrhh.ver'], scope: 'permiso' },
  { path: '/rrhh/cuenta-corriente', label: 'Materiales a Cargo', section: 'RRHH', permisos: ['rrhh.ver'], scope: 'permiso' },
  { path: '/rrhh/horarios', label: 'Horarios', section: 'RRHH', permisos: ['rrhh.ver'], scope: 'permiso' },
  { path: '/rrhh/horas-extras', label: 'Horas Extras', section: 'RRHH', permisos: ['rrhh.ver_horas_extras'], scope: 'permiso' },
  { path: '/rrhh/sueldos', label: 'Sueldos', section: 'RRHH', permisos: ['rrhh.ver'], scope: 'permiso' },
  { path: '/rrhh/reportes', label: 'Reportes', section: 'RRHH', permisos: ['rrhh.ver'], scope: 'permiso' },

  // ── Administración ────────────────────────────────────────
  { path: '/administracion/proveedores', label: 'Proveedores', section: 'Administración', permisos: ['administracion.ver_proveedores'], scope: 'permiso' },
  {
    path: '/administracion/compras',
    label: 'Compras',
    section: 'Administración',
    permisos: [
      'administracion.ver_ordenes_compra',
      'administracion.ver_cuentas_corrientes',
      'deposito.recibir_mercaderia',
      'tesoreria.gestionar_cheques',
      'administracion.eliminar_compras_basura',
    ],
    scope: 'permiso',
    nota: 'Cualquiera de estos permisos abre la página; cada pestaña pide el suyo.',
  },
  { path: '/administracion/bancos', label: 'Bancos', section: 'Administración', permisos: ['administracion.ver_caja'], scope: 'permiso' },
  { path: '/administracion/impuestos', label: 'Impuestos', section: 'Administración', permisos: ['administracion.ver_proveedores'], scope: 'permiso' },
  { path: '/administracion/caja', label: 'Caja', section: 'Administración', permisos: ['administracion.ver_caja'], scope: 'permiso' },

  // ── Tickets ───────────────────────────────────────────────
  { path: '/tickets', label: 'Tickets', section: 'Tickets', permisos: ['tickets.ver'], scope: 'permiso' },
  { path: '/tickets/admin', label: 'Configuración Tickets', section: 'Tickets', permisos: ['tickets.admin'], scope: 'permiso' },
  { path: '/tickets/triage/ejemplos', label: 'Ejemplos de Corrección', section: 'Tickets', permisos: ['tickets.triage.ejemplos'], scope: 'permiso' },

  // ── Documentos ────────────────────────────────────────────
  { path: '/document-designer', label: 'Designer', section: 'Documentos', permisos: ['documentos.disenar'], scope: 'permiso' },

  // ── Gestión ───────────────────────────────────────────────
  { path: '/gestion-pm', label: 'Gestión PMs', section: 'Gestión', permisos: ['admin.gestionar_pms'], scope: 'permiso' },
  {
    path: '/mis-sub-pms',
    label: 'Mis Sub-PMs',
    section: 'Gestión',
    permisos: [],
    scope: 'public',
    nota: 'En el menú solo aparece para titulares de pares marca/categoría o con admin.gestionar_pms.',
  },
  { path: '/admin', label: 'Admin', section: 'Gestión', permisos: ['admin.ver_panel'], scope: 'permiso' },
  { path: '/gestion/alertas', label: 'Alertas', section: 'Gestión', permisos: ['alertas.gestionar'], scope: 'permiso' },
  { path: '/free-shipping-alerts', label: 'Envío Gratis', section: 'Gestión', permisos: ['alertas.ver_free_shipping'], scope: 'permiso' },

  // ── Otras (routes without a sidebar entry) ────────────────
  { path: '/notificaciones', label: 'Notificaciones', section: OTRAS, permisos: ['reportes.ver_notificaciones'], scope: 'permiso' },
  { path: '/perfiles-medidas', label: 'Perfiles de medidas', section: OTRAS, permisos: ['admin.gestionar_tn_perfiles'], scope: 'permiso' },
  { path: '/ml-publicaciones', label: 'Publicaciones ML (oculta)', section: OTRAS, permisos: ['ml_ops.ver'], scope: 'permiso' },
];

/** Every permission category the backend uses (CategoriaPermiso enum + migrations). */
export const CATEGORIAS_PERMISO = {
  productos: 'Productos',
  ventas_ml: 'Ventas MercadoLibre',
  ventas_fuera: 'Ventas fuera de ML',
  ventas_tn: 'Ventas Tienda Nube',
  clientes: 'Clientes',
  administracion: 'Administración del sistema',
  administracion_sector: 'Administración (sector)',
  reportes: 'Reportes',
  configuracion: 'Configuración',
  alertas: 'Alertas',
  envios_flex: 'Envíos y Flex',
  rrhh: 'RRHH',
  tickets: 'Tickets',
  documentos: 'Documentos',
  rma: 'RMA',
  ml_ops: 'Operaciones ML',
  consultas: 'Consultas',
  promos: 'Promociones ML',
  pxq: 'Precios por cantidad (PxQ)',
  deposito_sector: 'Depósito',
  tesoreria: 'Tesorería',
  etiquetas: 'Etiquetas',
};

/** Label for a category key, humanizing keys this file does not know yet. */
export function nombreCategoria(categoria) {
  if (!categoria) return 'Sin categoría';
  if (CATEGORIAS_PERMISO[categoria]) return CATEGORIAS_PERMISO[categoria];
  const texto = categoria.replace(/[_.-]+/g, ' ').trim();
  return texto.charAt(0).toUpperCase() + texto.slice(1);
}
