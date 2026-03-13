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
  obtenerEmpleado: (id) => api.get(`/rrhh/empleados/${id}`),
  crearEmpleado: (data) => api.post('/rrhh/empleados', data),
  actualizarEmpleado: (id, data) => api.put(`/rrhh/empleados/${id}`, data),
  eliminarEmpleado: (id) => api.delete(`/rrhh/empleados/${id}`),

  // Documentos
  listarDocumentos: (empleadoId) => api.get(`/rrhh/empleados/${empleadoId}/documentos`),
  subirDocumento: (empleadoId, formData, params) =>
    api.post(`/rrhh/empleados/${empleadoId}/documentos`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      params,
    }),
  descargarDocumento: (docId) =>
    api.get(`/rrhh/documentos/${docId}/descargar`, { responseType: 'blob' }),
  eliminarDocumento: (docId) => api.delete(`/rrhh/documentos/${docId}`),

  // Tipos de documento
  listarTiposDocumento: (params) => api.get('/rrhh/tipos-documento', { params }),
  crearTipoDocumento: (data) => api.post('/rrhh/tipos-documento', data),
  actualizarTipoDocumento: (id, data) => api.put(`/rrhh/tipos-documento/${id}`, data),

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
  listarTiposSancion: () => api.get('/rrhh/tipos-sancion'),
  crearTipoSancion: (data) => api.post('/rrhh/tipos-sancion', data),
  actualizarTipoSancion: (id, data) => api.put(`/rrhh/tipos-sancion/${id}`, data),

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

  // ── Hikvision Users & Mapping ──────────────
  listarUsuariosHikvision: () => api.get('/rrhh/hikvision/usuarios'),
  mapearEmpleadoHikvision: (data) => api.post('/rrhh/hikvision/mapear', data),
  desmapearEmpleadoHikvision: (empleadoId) =>
    api.delete(`/rrhh/hikvision/mapear/${empleadoId}`),

  // ── Horarios Config ─────────────────────────
  listarHorarios: (params) => api.get('/rrhh/horarios', { params }),
  crearHorario: (data) => api.post('/rrhh/horarios', data),
  actualizarHorario: (id, data) => api.put(`/rrhh/horarios/${id}`, data),
  eliminarHorario: (id) => api.delete(`/rrhh/horarios/${id}`),

  // ── Excepciones (feriados) ──────────────────
  listarExcepciones: (params) => api.get('/rrhh/horarios/excepciones', { params }),
  crearExcepcion: (data) => api.post('/rrhh/horarios/excepciones', data),
  actualizarExcepcion: (id, data) => api.put(`/rrhh/horarios/excepciones/${id}`, data),
  eliminarExcepcion: (id) => api.delete(`/rrhh/horarios/excepciones/${id}`),

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
  exportarReporte: (tipo, params) =>
    api.get(`/rrhh/reportes/exportar/${tipo}`, { params, responseType: 'blob' }),
};

export default api;
