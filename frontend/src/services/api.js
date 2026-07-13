import axios from 'axios';

const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL,
});

// --- Auth event system ---
// En vez de hacer window.location.href = '/login' (que recarga toda la app
// y el usuario pierde lo que estaba haciendo), usamos un callback que el
// authStore registra. Así el logout se maneja con React Router, sin reload.
let _onAuthFailure = null;

/**
 * Registra el handler que se ejecuta cuando la sesión expira irrecuperablemente.
 * Llamar desde authStore.js al inicializar.
 */
export function registerAuthFailureHandler(handler) {
  _onAuthFailure = handler;
}

function handleAuthFailure() {
  localStorage.removeItem('token');
  localStorage.removeItem('refresh_token');
  if (_onAuthFailure) {
    _onAuthFailure();
  }
}

// --- Request interceptor ---
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// --- Response interceptor: silent refresh + request queuing ---
let isRefreshing = false;
let failedQueue = [];

const processQueue = (error, token = null) => {
  failedQueue.forEach(({ resolve, reject }) => {
    if (error) {
      reject(error);
    } else {
      resolve(token);
    }
  });
  failedQueue = [];
};

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    // Normalizar detail: si el backend envía {code, message}, extraer message
    // para que los componentes siempre reciban un string en error.response.data.detail
    const detail = error.response?.data?.detail;
    if (detail && typeof detail === 'object' && detail.message) {
      error.response.data.detail = detail.message;
    }

    const originalRequest = error.config;

    // Si no es 401 o ya se reintentó, rechazar directamente
    if (error.response?.status !== 401 || originalRequest._retry) {
      return Promise.reject(error);
    }

    // Si es el endpoint de refresh el que falló → sesión irrecuperable
    if (originalRequest.url?.includes('/auth/refresh')) {
      handleAuthFailure();
      return Promise.reject(error);
    }

    // Si ya hay un refresh en curso, encolar el request
    if (isRefreshing) {
      return new Promise((resolve, reject) => {
        failedQueue.push({ resolve, reject });
      }).then((token) => {
        originalRequest.headers.Authorization = `Bearer ${token}`;
        return api(originalRequest);
      });
    }

    originalRequest._retry = true;
    isRefreshing = true;

    const refreshToken = localStorage.getItem('refresh_token');
    if (!refreshToken) {
      isRefreshing = false;
      handleAuthFailure();
      return Promise.reject(error);
    }

    try {
      const { data } = await axios.post(
        `${import.meta.env.VITE_API_URL}/auth/refresh`,
        { refresh_token: refreshToken }
      );
      const newToken = data.access_token;
      localStorage.setItem('token', newToken);
      if (data.refresh_token) {
        // Backend rota el refresh_token en cada /auth/refresh; persistir el nuevo.
        localStorage.setItem('refresh_token', data.refresh_token);
      }
      processQueue(null, newToken);
      originalRequest.headers.Authorization = `Bearer ${newToken}`;
      return api(originalRequest);
    } catch (refreshError) {
      processQueue(refreshError, null);
      handleAuthFailure();
      return Promise.reject(refreshError);
    } finally {
      isRefreshing = false;
    }
  }
);

export const authAPI = {
  login: (username, password) => api.post('/auth/login', { username, password }),
  me: () => api.get('/auth/me'),
};

export const productosAPI = {
  listar: (params) => api.get('/productos', { params }),
  listarTienda: (params) => api.get('/productos/tienda', { params }),
  stats: (params) => api.get('/stats', { params }),
  statsDinamicos: (params) => api.get('/stats-dinamicos', { params }),
  marcas: (params) => api.get('/marcas', { params }),
  subcategorias: (params) => api.get('/subcategorias', { params }),
  categorias: () => api.get('/categorias'),
  obtenerMarcasPorPMs: (pm_ids) => api.get(`/pms/marcas?pm_ids=${pm_ids}`),
  obtenerSubcategoriasPorPMs: (pm_ids) => api.get(`/pms/subcategorias?pm_ids=${pm_ids}`),
  // Nested MLA/promotions expand (productos-promociones-ui, FE-A: read-only).
  getProductoMercadolibre: (itemId) => api.get(`/productos/${itemId}/mercadolibre`),
};

export const promocionesAPI = {
  // Read-only in FE-A. The write/apply POST is added in a later PR (FE-C)
  // once the write endpoint availability probe + apply control land.
  getPromocionesItem: (mlaId) => api.get(`/promociones/item/${mlaId}`),
};

export const pricingAPI = {
  calcularCompleto: (data) => api.post('/precios/calcular-completo', data),
  setearPrecio: (data) => api.post('/precios/set', data),
};

export const rolesAPI = {
  listar: (incluirInactivos = false) => api.get('/roles', { params: { incluir_inactivos: incluirInactivos } }),
  obtener: (rolId) => api.get(`/roles/${rolId}`),
  crear: (data) => api.post('/roles', data),
  actualizar: (rolId, data) => api.patch(`/roles/${rolId}`, data),
  eliminar: (rolId) => api.delete(`/roles/${rolId}`),
  obtenerPermisos: (rolId) => api.get(`/roles/${rolId}/permisos`),
  setPermisos: (rolId, permisos) => api.put(`/roles/${rolId}/permisos`, { permisos }),
  clonar: (rolId, data) => api.post(`/roles/${rolId}/clonar`, data),
  obtenerUsuarios: (rolId) => api.get(`/roles/${rolId}/usuarios`),
};

export const permisosAPI = {
  catalogo: () => api.get('/permisos/catalogo'),
  misPermisos: () => api.get('/permisos/mis-permisos'),
  permisosPorUsuario: (usuarioId) => api.get(`/permisos/usuario/${usuarioId}`),
  verificar: (permisoCodigo) => api.get(`/permisos/verificar/${permisoCodigo}`),
  verificarMultiples: (permisos) => api.post('/permisos/verificar-multiples', permisos),
};

export const rrhhAPI = {
  // Empleados
  listarEmpleados: (params) => api.get('/rrhh/empleados', { params }),
  contadoresEmpleados: () => api.get('/rrhh/empleados/contadores'),
  obtenerFiltrosEmpleados: () => api.get('/rrhh/empleados/filtros/opciones'),
  obtenerEmpleado: (id) => api.get(`/rrhh/empleados/${id}`),
  crearEmpleado: (data) => api.post('/rrhh/empleados', data),
  actualizarEmpleado: (id, data) => api.put(`/rrhh/empleados/${id}`, data),
  eliminarEmpleado: (id) => api.delete(`/rrhh/empleados/${id}`),
  crearUsuarioFichaje: (empleadoId, data = {}) =>
    api.post(`/rrhh/empleados/${empleadoId}/crear-usuario-fichaje`, data),
  listarUsuariosSistema: () => api.get('/usuarios'),
  listarDatosBancarios: () => api.get('/rrhh/empleados/datos-bancarios'),
  exportarEmpleadosExcel: (params) =>
    api.get('/rrhh/empleados/exportar-excel', { params, responseType: 'blob' }),

  // Documentos
  listarDocumentos: (empleadoId) => api.get(`/rrhh/empleados/${empleadoId}/documentos`),
  subirDocumento: (empleadoId, formData, params) =>
    api.post(`/rrhh/empleados/${empleadoId}/documentos`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      params,
    }),
  descargarDocumento: (docId) =>
    api.get(`/rrhh/documentos/${docId}/descargar`, { responseType: 'blob' }),
  editarDocumento: (docId, data) => api.put(`/rrhh/documentos/${docId}`, data),
  eliminarDocumento: (docId) => api.delete(`/rrhh/documentos/${docId}`),

  // Tipos de documento
  listarTiposDocumento: (params) => api.get('/rrhh/tipos-documento', { params }),
  crearTipoDocumento: (data) => api.post('/rrhh/tipos-documento', data),
  actualizarTipoDocumento: (id, data) => api.put(`/rrhh/tipos-documento/${id}`, data),

  // Cumpleaños
  listarCumpleanosMes: (params) => api.get('/rrhh/cumpleanos', { params }),
  cumpleanosHoy: () => api.get('/rrhh/cumpleanos/hoy'),

  // Geocodificación empleado
  geocodificarEmpleado: (empleadoId) =>
    api.post(`/rrhh/empleados/${empleadoId}/geocodificar`),

  // Motivos de baja
  listarMotivosBaja: (params) => api.get('/rrhh/motivos-baja', { params }),
  crearMotivoBaja: (data) => api.post('/rrhh/motivos-baja', data),
  actualizarMotivoBaja: (id, data) => api.put(`/rrhh/motivos-baja/${id}`, data),

  // Schema legajo (campos custom)
  listarSchemaLegajo: (params) => api.get('/rrhh/schema-legajo', { params }),
  crearCampoLegajo: (data) => api.post('/rrhh/schema-legajo', data),
  actualizarCampoLegajo: (id, data) => api.put(`/rrhh/schema-legajo/${id}`, data),

  // Historial
  listarHistorial: (empleadoId, params) =>
    api.get(`/rrhh/empleados/${empleadoId}/historial`, { params }),

  // ── Presentismo ─────────────────────────────
  obtenerGrillaPresentismo: (params) => api.get('/rrhh/presentismo', { params }),
  marcarPresentismo: (empleadoId, fecha, data) =>
    api.put(`/rrhh/presentismo/${empleadoId}/${fecha}`, data),
  marcarPresentismoBulk: (data) => api.put('/rrhh/presentismo/bulk', data),
  marcarPresentismoRango: (data) => api.put('/rrhh/presentismo/rango', data),

  // ── Motivos de ausencia ─────────────
  listarMotivosAusencia: (params) => api.get('/rrhh/motivos-ausencia', { params }),
  crearMotivoAusencia: (data) => api.post('/rrhh/motivos-ausencia', data),
  actualizarMotivoAusencia: (id, data) => api.put(`/rrhh/motivos-ausencia/${id}`, data),

  // ── ART (Accidentes de Trabajo) ─────────────
  listarArtCasos: (params) => api.get('/rrhh/art', { params }),
  crearArtCaso: (data) => api.post('/rrhh/art', data),
  obtenerArtCaso: (id) => api.get(`/rrhh/art/${id}`),
  actualizarArtCaso: (id, data) => api.put(`/rrhh/art/${id}`, data),
  subirArtDocumento: (casoId, formData, params) =>
    api.post(`/rrhh/art/${casoId}/documentos`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      params,
    }),
  descargarArtDocumento: (casoId, docId) =>
    api.get(`/rrhh/art/${casoId}/documentos/${docId}/download`, { responseType: 'blob' }),
  eliminarArtDocumento: (casoId, docId) =>
    api.delete(`/rrhh/art/${casoId}/documentos/${docId}`),

  // ── Sanciones ───────────────────────────────
  listarSanciones: (params) => api.get('/rrhh/sanciones', { params }),
  crearSancion: (data) => api.post('/rrhh/sanciones', data),
  obtenerSancion: (id) => api.get(`/rrhh/sanciones/${id}`),
  anularSancion: (id, data) => api.patch(`/rrhh/sanciones/${id}/anular`, data),
  listarTiposSancion: (params) => api.get('/rrhh/tipos-sancion', { params }),
  obtenerPlaceholdersSancion: () => api.get('/rrhh/sanciones/placeholders'),
  crearTipoSancion: (data) => api.post('/rrhh/tipos-sancion', data),
  actualizarTipoSancion: (id, data) => api.put(`/rrhh/tipos-sancion/${id}`, data),

  // ── Textos predefinidos sanción ───────────
  listarTextosPredefinidosSancion: (params) =>
    api.get('/rrhh/textos-predefinidos-sancion', { params }),
  crearTextoPredefinidoSancion: (data) =>
    api.post('/rrhh/textos-predefinidos-sancion', data),
  actualizarTextoPredefinidoSancion: (id, data) =>
    api.put(`/rrhh/textos-predefinidos-sancion/${id}`, data),
  eliminarTextoPredefinidoSancion: (id) =>
    api.delete(`/rrhh/textos-predefinidos-sancion/${id}`),
  reordenarTextosPredefinidosSancion: (items) =>
    api.put('/rrhh/textos-predefinidos-sancion/reorder', items),

  // ── Vacaciones ──────────────────────────────
  listarVacacionesPeriodos: (params) => api.get('/rrhh/vacaciones/periodos', { params }),
  generarPeriodos: (data) => api.post('/rrhh/vacaciones/periodos/generar', data),
  listarVacacionesSolicitudes: (params) => api.get('/rrhh/vacaciones/solicitudes', { params }),
  crearSolicitudVacaciones: (data) => api.post('/rrhh/vacaciones/solicitudes', data),
  aprobarSolicitud: (id) => api.patch(`/rrhh/vacaciones/solicitudes/${id}/aprobar`),
  rechazarSolicitud: (id, data) => api.patch(`/rrhh/vacaciones/solicitudes/${id}/rechazar`, data),
  cancelarSolicitud: (id) => api.patch(`/rrhh/vacaciones/solicitudes/${id}/cancelar`),

  // ── Cuenta Corriente ────────────────────────
  listarCuentasCorrientes: (params) => api.get('/rrhh/cuenta-corriente', { params }),
  detalleCuentaCorriente: (empleadoId, params) =>
    api.get(`/rrhh/cuenta-corriente/${empleadoId}`, { params }),
  registrarCargo: (empleadoId, data) =>
    api.post(`/rrhh/cuenta-corriente/${empleadoId}/cargo`, data),
  registrarAbono: (empleadoId, data) =>
    api.post(`/rrhh/cuenta-corriente/${empleadoId}/abono`, data),
  liquidacionMensual: (data) =>
    api.post('/rrhh/cuenta-corriente/liquidacion-mensual', data),

  // ── Herramientas ────────────────────────────
  listarHerramientas: (empleadoId, params) =>
    api.get(`/rrhh/herramientas/${empleadoId}`, { params }),
  asignarHerramienta: (data) => api.post('/rrhh/herramientas', data),
  devolverHerramienta: (id, params) =>
    api.patch(`/rrhh/herramientas/${id}/devolver`, null, { params }),

  // ── Fichadas ────────────────────────────────
  listarFichadas: (params) => api.get('/rrhh/fichadas', { params }),
  registrarFichadaManual: (data) => api.post('/rrhh/fichadas/manual', data),
  syncHikvision: (data) => api.post('/rrhh/fichadas/sync-hikvision', data),
  eliminarFichada: (id) => api.delete(`/rrhh/fichadas/${id}`),
  actualizarMotivoFichada: (id, data) =>
    api.patch(`/rrhh/fichadas/${id}/motivo`, data),

  // ── Hikvision Users & Mapping ──────────────
  listarUsuariosHikvision: () => api.get('/rrhh/hikvision/usuarios'),
  listarUsuariosHikvisionCache: () => api.get('/rrhh/hikvision/users-cache'),
  syncUsuariosHikvision: () => api.post('/rrhh/hikvision/sync-users'),
  mapearEmpleadoHikvision: (data) => api.post('/rrhh/hikvision/mapear', data),
  desmapearEmpleadoHikvision: (empleadoId) =>
    api.delete(`/rrhh/hikvision/mapear/${empleadoId}`),

  // ── Horarios Config ─────────────────────────
  listarHorarios: (params) => api.get('/rrhh/horarios', { params }),
  crearHorario: (data) => api.post('/rrhh/horarios', data),
  actualizarHorario: (id, data) => api.put(`/rrhh/horarios/${id}`, data),
  eliminarHorario: (id) => api.delete(`/rrhh/horarios/${id}`),

  // ── Empleado ↔ Horario (Turnos asignados) ───
  listarHorariosEmpleado: (empleadoId) =>
    api.get(`/rrhh/empleados/${empleadoId}/horarios`),
  asignarHorarioEmpleado: (empleadoId, data) =>
    api.post(`/rrhh/empleados/${empleadoId}/horarios`, data),
  desasignarHorarioEmpleado: (asignacionId) =>
    api.delete(`/rrhh/empleado-horarios/${asignacionId}`),
  listarEmpleadosHorario: (horarioId) =>
    api.get(`/rrhh/horarios/${horarioId}/empleados`),

  // ── Excepciones (feriados) ──────────────────
  listarExcepciones: (params) => api.get('/rrhh/horarios/excepciones', { params }),
  crearExcepcion: (data) => api.post('/rrhh/horarios/excepciones', data),
  actualizarExcepcion: (id, data) => api.put(`/rrhh/horarios/excepciones/${id}`, data),
  eliminarExcepcion: (id) => api.delete(`/rrhh/horarios/excepciones/${id}`),

  // ── Fichaje Mobile ───────────────────────────
  getEstadoFichaje: () => api.get('/rrhh/fichaje-mobile/estado'),
  ficharMobile: (data) => api.post('/rrhh/fichaje-mobile/fichar', data),

  // ── Reportes ────────────────────────────────
  reportePresentismoMensual: (params) =>
    api.get('/rrhh/reportes/presentismo-mensual', { params }),
  reporteSancionesPeriodo: (params) =>
    api.get('/rrhh/reportes/sanciones-periodo', { params }),
  reporteVacacionesResumen: (params) =>
    api.get('/rrhh/reportes/vacaciones-resumen', { params }),
  reporteCuentaCorrienteResumen: () =>
    api.get('/rrhh/reportes/cuenta-corriente-resumen'),
  reporteHorasTrabajadas: (params) =>
    api.get('/rrhh/reportes/horas-trabajadas', { params }),
  reportePresentismoDiario: (params) =>
    api.get('/rrhh/reportes/presentismo-diario', { params }),
  exportarPresentismoDiario: (params) =>
    api.get('/rrhh/reportes/exportar/presentismo-diario', { params, responseType: 'blob' }),
  exportarReporte: (tipo, params) =>
    api.get(`/rrhh/reportes/exportar/${tipo}`, { params, responseType: 'blob' }),
};

// ── Tickets API ───────────────────────────────────────────
export const ticketsAPI = {
  // Tickets CRUD
  listar: (params) => api.get('/tickets/tickets', { params }),
  obtener: (id) => api.get(`/tickets/tickets/${id}`),
  crear: (data) => api.post('/tickets/tickets', data),
  actualizar: (id, data) => api.patch(`/tickets/tickets/${id}`, data),

  // Badge count
  badgeCount: () => api.get('/tickets/tickets/mis-pendientes/count'),
  marcarRevisado: (id) => api.post(`/tickets/marcar-revisado/${id}`),

  // Transiciones & asignación
  transicion: (id, data) => api.post(`/tickets/tickets/${id}/transicion`, data),
  asignar: (id, data) => api.post(`/tickets/tickets/${id}/asignar`, data),

  // Comentarios
  listarComentarios: (id, params) =>
    api.get(`/tickets/tickets/${id}/comentarios`, { params }),
  agregarComentario: (id, data) =>
    api.post(`/tickets/tickets/${id}/comentarios`, data),

  // Historial
  obtenerHistorial: (id) => api.get(`/tickets/tickets/${id}/historial`),

  // Adjuntos
  listarAdjuntos: (id) => api.get(`/tickets/tickets/${id}/adjuntos`),
  subirAdjunto: (id, file) => {
    const formData = new FormData();
    formData.append('file', file);
    return api.post(`/tickets/tickets/${id}/adjuntos`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
  },
  descargarAdjunto: (ticketId, adjuntoId) =>
    api.get(`/tickets/tickets/${ticketId}/adjuntos/${adjuntoId}/descargar`, {
      responseType: 'blob',
    }),
  eliminarAdjunto: (ticketId, adjuntoId) =>
    api.delete(`/tickets/tickets/${ticketId}/adjuntos/${adjuntoId}`),
};

export const sectoresAPI = {
  listar: (params) => api.get('/tickets/sectores', { params }),
  obtener: (id) => api.get(`/tickets/sectores/${id}`),
  crear: (data) => api.post('/tickets/sectores', data),
  actualizar: (id, data) => api.patch(`/tickets/sectores/${id}`, data),

  // Sector-usuario M2M
  listarUsuarios: (sectorId) =>
    api.get(`/tickets/sectores/${sectorId}/usuarios`),
  agregarUsuario: (sectorId, data) =>
    api.post(`/tickets/sectores/${sectorId}/usuarios`, data),
  removerUsuario: (sectorId, usuarioId) =>
    api.delete(`/tickets/sectores/${sectorId}/usuarios/${usuarioId}`),

  // Workflows de un sector
  listarWorkflows: (sectorId, params) =>
    api.get(`/tickets/sectores/${sectorId}/workflows`, { params }),

  // Tipos de ticket de un sector
  listarTiposTicket: (sectorId) =>
    api.get(`/tickets/sectores/${sectorId}/tipos-ticket`),
  crearTipoTicket: (sectorId, data) =>
    api.post(`/tickets/sectores/${sectorId}/tipos-ticket`, data),
  actualizarTipoTicket: (sectorId, tipoId, data) =>
    api.patch(`/tickets/sectores/${sectorId}/tipos-ticket/${tipoId}`, data),
  eliminarTipoTicket: (sectorId, tipoId) =>
    api.delete(`/tickets/sectores/${sectorId}/tipos-ticket/${tipoId}`),
};

export const workflowsAPI = {
  obtener: (id) => api.get(`/tickets/workflows/${id}`),
  crear: (data) => api.post('/tickets/workflows', data),
  actualizar: (id, data) => api.patch(`/tickets/workflows/${id}`, data),
  eliminar: (id) => api.delete(`/tickets/workflows/${id}`),

  // Estados
  crearEstado: (workflowId, data) =>
    api.post(`/tickets/workflows/${workflowId}/estados`, data),
  actualizarEstado: (workflowId, estadoId, data) =>
    api.patch(`/tickets/workflows/${workflowId}/estados/${estadoId}`, data),
  eliminarEstado: (workflowId, estadoId) =>
    api.delete(`/tickets/workflows/${workflowId}/estados/${estadoId}`),

  // Transiciones
  crearTransicion: (workflowId, data) =>
    api.post(`/tickets/workflows/${workflowId}/transiciones`, data),
  actualizarTransicion: (workflowId, transicionId, data) =>
    api.patch(`/tickets/workflows/${workflowId}/transiciones/${transicionId}`, data),
  eliminarTransicion: (workflowId, transicionId) =>
    api.delete(`/tickets/workflows/${workflowId}/transiciones/${transicionId}`),
};

// =============================================================================
// Document Templates API
// =============================================================================
export const documentTemplatesAPI = {
  // Consulta (documentos.imprimir)
  listar: (params) => api.get('/document-templates', { params }),
  obtener: (id) => api.get(`/document-templates/${id}`),
  contextos: () => api.get('/document-templates/contextos'),
  variables: (contexto) => api.get(`/document-templates/variables/${contexto}`),

  // Gestión (documentos.disenar)
  crear: (data) => api.post('/document-templates', data),
  actualizar: (id, data) => api.put(`/document-templates/${id}`, data),
  eliminar: (id) => api.delete(`/document-templates/${id}`),
};

// =============================================================================
// Empresas API (Admin)
// =============================================================================
export const empresasAPI = {
  listar: (params) => api.get('/admin/empresas', { params }),
  crear: (data) => api.post('/admin/empresas', data),
  actualizar: (id, data) => api.put(`/admin/empresas/${id}`, data),
};

// =============================================================================
// RRHH Horas Extras API (Batch 6 — design §10.5)
// =============================================================================
export const horasExtrasApi = {
  list: (params) => api.get('/rrhh/horas-extras', { params }),
  get: (id) => api.get(`/rrhh/horas-extras/${id}`),
  create: (data) => api.post('/rrhh/horas-extras', data),
  update: (id, data) => api.put(`/rrhh/horas-extras/${id}`, data),
  aprobar: (id, body) => api.patch(`/rrhh/horas-extras/${id}/aprobar`, body),
  rechazar: (id, body) => api.patch(`/rrhh/horas-extras/${id}/rechazar`, body),
  reabrir: (id, body) => api.patch(`/rrhh/horas-extras/${id}/reabrir`, body),
  bulkAprobar: (body) => api.post('/rrhh/horas-extras/bulk/aprobar', body),
  bulkRechazar: (body) => api.post('/rrhh/horas-extras/bulk/rechazar', body),
  bulkReabrir: (body) => api.post('/rrhh/horas-extras/bulk/reabrir', body),
  resumen: (mes) => api.get('/rrhh/horas-extras/resumen', { params: { mes } }),
  completarFichada: (id, body) =>
    api.post(`/rrhh/horas-extras/${id}/completar-fichada`, body),
  descartarDia: (id, body) =>
    api.post(`/rrhh/horas-extras/${id}/descartar-dia`, body),
  recalcular: (body) => api.post('/rrhh/horas-extras/recalcular', body),
  liquidar: (body) => api.post('/rrhh/horas-extras/liquidar', body),
  alertasList: (params) => api.get('/rrhh/horas-extras/alertas', { params }),
  alertaMarcarLeida: (id) =>
    api.patch(`/rrhh/horas-extras/alertas/${id}/leida`),
  historial: (heId) => api.get(`/rrhh/horas-extras/historial/${heId}`),
  configGet: () => api.get('/rrhh/horas-extras/config'),
  configPut: (body) => api.put('/rrhh/horas-extras/config', body),
  exportarXlsx: (params) =>
    api.get('/rrhh/horas-extras/exportar', { params, responseType: 'blob' }),
};

export default api;
