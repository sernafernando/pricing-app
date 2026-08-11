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

/**
 * Un ERROR DE APLICACIÓN TIPADO es un payload que el backend construyó a
 * propósito para que el frontend lo LEA POR CAMPOS, no para mostrarlo tal cual.
 * El discriminador en esta API es un `status` string, y lo emiten hoy
 * `backend/app/routers/pxq.py` (`_error_detail_from_outcome`, que conserva
 * `divergences`) y `backend/app/services/ml_pxq_adopt_service.py`
 * (`adopt_conflict` con `conflicts`, `adopt_read_unavailable`).
 *
 * El predicado es a propósito MÁS ANGOSTO que "cualquier objeto". Los otros
 * detalles-dict del backend son `{code, message}` (`core/exceptions.py`),
 * `{codigo, mensaje, ...}` (ordenes_pago), `{message, errores}` (prearmado) o
 * `{motivo, item_id_real, ...}`, y hay más de cien componentes que hacen
 * `<div>{data.detail || 'fallback'}</div>`. Dejar pasar cualquier objeto los
 * haría explotar con React #31, que es exactamente lo que este interceptor
 * existe para evitar. `status` string y nada más.
 */
function isTypedAppError(value) {
  return (
    !!value && typeof value === 'object' && !Array.isArray(value) && typeof value.status === 'string'
  );
}

/**
 * El ENVELOPE ESTÁNDAR de error: `{error: {code, message}}`, la forma que
 * `backend/app/core/exceptions.py` (`http_exception_handler`) le pone al body
 * cuando el `detail` es un string, o un dict que trae `code`. Es el camino que
 * toma la enorme mayoría de los errores de la API.
 *
 * Lo contrario de `isTypedAppError`: acá el payload NO se lee por campos, es
 * un mensaje para mostrarle a la persona. Por eso se desenvuelve a string.
 *
 * El predicado exige `error.message` STRING y no solo la presencia de `error`.
 * Hay bodies que usan esa clave para otra cosa (`{error: "texto plano"}`), y
 * confiar en la clave sola terminaría poniendo un número o un objeto donde el
 * contrato con los componentes es "string o nada".
 */
function isStandardErrorEnvelope(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const { error } = value;
  return (
    !!error && typeof error === 'object' && !Array.isArray(error) && typeof error.message === 'string'
  );
}

/**
 * Deja `response.data.detail` en un estado que los componentes puedan usar:
 * un string renderizable, o el payload tipado INTACTO.
 *
 * Las dos primeras ramas son la razón original de existir de esto:
 *   - [{msg, ...}] (422 de validación FastAPI/Pydantic) → msgs unidos
 *   - {code, message} / {message} / {msg} / {mensaje}    → el texto
 * Sin eso, un 422 deja detail como array de objetos y los componentes que lo
 * renderizan directo (`<div>{error}</div>`) tiran React #31.
 *
 * Aplanar TAMBIÉN los errores tipados los mataba: `{status, reason, conflicts}`
 * no tiene `message`/`msg`/`mensaje`, así que terminaba en `JSON.stringify` —
 * un string — y `detail.status` quedaba `undefined` para siempre.
 *
 * La PRIMERA rama es la menos obvia y la más importante:
 * `backend/app/core/exceptions.py` (`http_exception_handler`, registrado en
 * `main.py` sobre `StarletteHTTPException`) devuelve el dict de `detail` COMO
 * RAÍZ del body cuando no trae `code`. O sea que el 409 de adopt-live llega
 * como `{status, reason, conflicts}` y NO como `{detail: {...}}`: sin esa rama
 * `data.detail` es `undefined` y las ramas `adopt_conflict` / `divergence` de
 * PxqPanel no se ejecutan NUNCA, que es como se enviaron muertas a producción.
 */
function normalizeErrorDetail(response) {
  const data = response?.data;
  if (!data || typeof data !== 'object') return;

  if (isTypedAppError(data)) {
    // La RAÍZ es el payload tipado. Que además traiga su propia clave `detail`
    // no cambia nada: los outcomes de `ml_pxq_write_service` la usan como UN
    // CAMPO MÁS del payload ("Writes are disabled...", el body crudo del proxy),
    // no como el canal de mensaje renderizable del frontend. Tratar ese string
    // como la respuesta es lo que dejaba `detail.status` en `undefined` para
    // los siete estados de sync que sí traen `detail`.
    //
    // Copia superficial, NO `data` mismo: `data.detail = data` sería una
    // referencia circular y rompería cualquier `JSON.stringify` del payload.
    // La copia conserva el `detail` original como `detail.detail`.
    data.detail = { ...data };
    return;
  }

  // El envelope estándar NO trae `detail`: `http_exception_handler` mueve el
  // mensaje a `error.message` y nunca escribe esa clave. Como los 287
  // `data.detail || 'fallback'` repartidos en 106 archivos leen justamente
  // `detail`, todos tomaban SIEMPRE el fallback genérico y el mensaje real del
  // backend no llegaba a ninguna de esas pantallas. Dieciocho archivos ya se
  // habían comido el bug y lo esquivaban a mano con
  // `data?.error?.message || data?.detail || '...'`.
  //
  // Se AGREGA `detail` como string; `data.error` queda intacto, así que esos
  // dieciocho siguen andando igual. String y no el objeto `error`, porque el
  // destino es `<div>{data.detail || 'fallback'}</div>`: un objeto ahí es
  // React #31, que es la razón de existir de todo este normalizador.
  //
  // Va DESPUÉS de la rama tipada a propósito: un payload que sea las dos cosas
  // se lee por campos, y aplanarlo dejaría `detail.status` en `undefined`.
  if (data.detail === undefined && isStandardErrorEnvelope(data)) {
    data.detail = data.error.message;
    return;
  }

  const { detail } = data;

  if (Array.isArray(detail)) {
    data.detail = detail
      .map((e) => (typeof e === 'string' ? e : e?.msg || e?.mensaje || JSON.stringify(e)))
      .join('; ');
    return;
  }

  if (isTypedAppError(detail)) {
    // Intacto. El consumidor lo lee por campos (`status`, `conflicts`,
    // `divergences`); un string no le sirve para nada.
    return;
  }

  if (detail && typeof detail === 'object') {
    data.detail = detail.message || detail.msg || detail.mensaje || JSON.stringify(detail);
  }
}

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
    // Ver `normalizeErrorDetail`: aplana lo que hay que aplanar y deja pasar
    // intactos los contratos de error tipados del backend.
    normalizeErrorDetail(error.response);

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
  // `filterParams` (optional) forwards the active promo filter — `{ promo_tipos, promo_estado }`
  // (or the legacy no-type booleans `con_promo_aplicada`/`con_promo_sin_aplicar`) — so the
  // backend can compute per-pub `matches_filter` (productos-promo-filter-per-mla).
  getProductoMercadolibreLite: (itemId, filterParams = {}) =>
    api.get(`/productos/${itemId}/mercadolibre`, { params: { lite: true, ...filterParams } }),
  // Recursive catalog/family publication tree (productos-catalog-family-tree
  // PR3). Mirrors `getProductoMercadolibreLite`'s param-forwarding pattern —
  // `filterParams` is the same `{ promo_tipos, promo_estado }` (or legacy
  // `con_promo_aplicada`/`con_promo_sin_aplicar`) shape, forwarded as-is so the
  // backend computes per-node `matches_filter` at any depth.
  getProductoTree: (itemId, filterParams = {}) =>
    api.get(`/productos/${itemId}/mercadolibre/tree`, { params: { ...filterParams } }),
};

// Color-layer teams (productos-color-teams). `listar` returns the user's teams
// plus the global team: [{ id, nombre, es_global }]. Only `listar` is used in
// the current tanda; the CRUD + membership methods are for the team-management
// modal (later task).
export const equiposAPI = {
  listar: () => api.get('/equipos'),
  // Lightweight user picker (id + display name only) any authenticated user can
  // read — unlike the admin-only `/usuarios`, which leaks emails and roles.
  usuariosDisponibles: () => api.get('/equipos/usuarios-disponibles'),
  crear: (data) => api.post('/equipos', data),
  actualizar: (id, data) => api.patch(`/equipos/${id}`, data),
  eliminar: (id) => api.delete(`/equipos/${id}`),
  listarMiembros: (id) => api.get(`/equipos/${id}/miembros`),
  agregarMiembro: (id, data) => api.post(`/equipos/${id}/miembros`, data),
  actualizarMiembro: (id, uid, data) => api.patch(`/equipos/${id}/miembros/${uid}`, data),
  eliminarMiembro: (id, uid) => api.delete(`/equipos/${id}/miembros/${uid}`),
};

export const promocionesAPI = {
  getPromocionesItem: (mlaId) => api.get(`/promociones/item/${mlaId}`),
  // Enroll a promotion for a given MLA (real ML price write). `body` shape:
  // - SELLER_CAMPAIGN/DEAL: { promotion_id, promotion_type, deal_price? }
  // - SMART: { promotion_id, promotion_type } — backend derives offer_id/price.
  postPromocionItem: (mlaId, body) => api.post(`/promociones/item/${mlaId}`, body),
  // Remove/desapply a promotion from a given MLA (real ML write). `params`
  // shape: { promotion_type, promotion_id } - backend re-derives offer_id
  // for SMART itself, so the FE never sends offer_id here either.
  deletePromocionItem: (mlaId, params) => api.delete(`/promociones/item/${mlaId}`, { params }),
  // Seller markup for a candidate price (used by the manual price input on
  // SELLER_CAMPAIGN/DEAL apply controls). Returns { price, nuestro_markup }.
  getMarkupParaPrecio: (mlaId, price) => api.get(`/promociones/item/${mlaId}/markup`, { params: { price } }),
  // Manual per-MLA promo-refresh button: triggers a read-reconcile of the
  // promo mirror via the ml-webhook proxy (PROMOS ONLY — never touches the
  // publication/tree structure, never writes prices/promos). Returns
  // { ok: boolean }; fail-soft (HTTP 200 even on proxy failure).
  refreshItemPromociones: (mlaId) => api.post(`/promociones/item/${mlaId}/refresh`),
  // Catalog-competition (promos-catalog-prices-and-official-store, slice C2).
  // READ is cheap (our own DB, latest snapshot only) — safe to call on
  // panel open. It NEVER hits the throttled ML proxy itself; only the
  // explicit refresh below does, and only for the ONE given MLA (no
  // refresh-all, no per-product refresh — the ML throttle (~6.6 req/s) is
  // shared with sales-webhook processing).
  getCompetenciaCatalogo: (mlaId) => api.get(`/promociones/catalogo-competencia/${mlaId}`),
  refreshCompetenciaCatalogo: (mlaId) => api.post(`/promociones/catalogo-competencia/${mlaId}/refresh`),
};

// PxQ (wholesale, price-by-quantity) tiers.
// `getLive` always re-hits the ML proxy server-side (never server-cached);
// `live_tiers: null` (vs `[]`) means the live read failed, not "no tiers".
// The CRUD calls below (PR 4c) only ever touch our own DB — no ML traffic —
// matching the shapes in `backend/app/routers/pxq.py`'s
// `PxqCreateTierRequest`/`PxqUpdateTierRequest`.
export const pxqAPI = {
  getLive: (itemId) => api.get(`/pxq/${itemId}/live`),
  createTier: (itemId, body) => api.post(`/pxq/${itemId}/tiers`, body),
  updateTier: (itemId, tierId, body) => api.patch(`/pxq/${itemId}/tiers/${tierId}`, body),
  deleteTier: (itemId, tierId) => api.delete(`/pxq/${itemId}/tiers/${tierId}`),
  // Write path (PR 4d): `sync` pushes the local mirror to ML and can NEVER
  // clear the live array. The backend still accepts `allow_clear` (see
  // `backend/app/routers/pxq.py`'s `PxqSyncRequest`), but a full-array wipe is
  // a destructive operation that needs its own explicitly-labelled verb — not
  // a default argument on a verb the UI calls "sincronizar". Taking the
  // parameter away removes the syntactic path that let a caller ask for a
  // wipe by accident.
  sync: (itemId) => api.post(`/pxq/${itemId}/sync`, { allow_clear: false }),
  // Import path (PR 4e): pulls ML's LIVE tiers into an EMPTY local mirror.
  // The opposite direction from `sync` and the only non-destructive way out of
  // "ML holds tiers we never mirrored".
  //
  // Takes the item id and NOTHING else, for the same reason `sync` no longer
  // takes `allow_clear`: `POST /pxq/{item_id}/adopt-live` accepts no request
  // body at all (see `backend/app/routers/pxq.py`), so there is no option to
  // express here. An optional flag on an import verb is exactly the shape that
  // let "sincronizar" be asked to wipe four publications — the parameter that
  // does not exist cannot be passed by accident.
  adoptLive: (itemId) => api.post(`/pxq/${itemId}/adopt-live`),
};

export const pricingAPI = {
  calcularCompleto: (data) => api.post('/precios/calcular-completo', data),
  setearPrecio: (data) => api.post('/precios/set', data),
};

// Sub-PM scope delegation (sub-pm-scope-marcas PR3). Non-admin titular-only
// surface: a titular of a (marca, categoria) pair can grant/revoke sub-PMs on
// their own pairs. `listarUsuariosPM` intentionally hits `/usuarios/pms` (NOT
// the admin-only `/usuarios`) — it has no role gate, so it works for any
// authenticated titular as the grant-target picker source.
export const marcasPmAPI = {
  misTitularidades: () => api.get('/marcas-pm/mis-titularidades'),
  // Admin-only (ADMIN/SUPERADMIN): every (marca, categoria) pair, including
  // pairs with no titular. Same source GestionPM.jsx uses.
  listarTodosLosPares: () => api.get('/marcas-pm'),
  listarSubPMs: (marca, categoria) => api.get('/marcas-pm/sub-pms', { params: { marca, categoria } }),
  crearSubPM: (data) => api.post('/marcas-pm/sub-pms', data),
  eliminarSubPM: (id) => api.delete(`/marcas-pm/sub-pms/${id}`),
  listarUsuariosPM: () => api.get('/usuarios/pms'),
  // Bulk assignment reads (sub-pm-bulk-assignment Slice 1): grants for a
  // target user, scoped to the caller's writable pairs — used to pre-check
  // the pair table when a user is picked.
  obtenerGrantsUsuario: (usuarioId) => api.get(`/marcas-pm/sub-pms/usuario/${usuarioId}`),
  // Aggregate grant counts by usuario_id, scoped to the caller's writable
  // pairs — feeds the "Juan Pérez (12)" picker counter without an N+1.
  obtenerConteosSubPMs: () => api.get('/marcas-pm/sub-pms/conteos'),
  // Bulk assignment write (sub-pm-bulk-assignment Slice 2): replaces the
  // FULL desired set of (marca, categoria) pairs for `usuarioId`, confined
  // to the caller's writable scope. Fail-closed: any out-of-scope pair
  // rejects the whole request (403 with `pares_rechazados`), nothing applied.
  asignarSubPMsBulk: (usuarioId, pares) => api.put(`/marcas-pm/sub-pms/usuario/${usuarioId}`, { pares }),
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

/**
 * Serializa params emitiendo un parámetro REPETIDO por cada elemento de un
 * array: `{ empleado_ids: [1, 2] }` → `empleado_ids=1&empleado_ids=2`.
 *
 * El serializador por defecto de axios emite `empleado_ids[]=1&empleado_ids[]=2`,
 * y FastAPI —que declara estos filtros como `list[int] = Query(default=None)`—
 * NO lee esa forma: recibe la lista vacía y devuelve todos los empleados. Es un
 * fallo silencioso (200 con datos de más), así que hay que serializar a mano.
 *
 * `null`/`undefined` se omiten en vez de mandarse como el string "null".
 */
export function serializeRepeatedParams(params) {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params || {})) {
    if (value === null || value === undefined) continue;
    if (Array.isArray(value)) {
      for (const item of value) {
        if (item === null || item === undefined) continue;
        search.append(key, String(item));
      }
    } else {
      search.append(key, String(value));
    }
  }
  return search.toString();
}

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
  // Registro de horarios imprimible. `empleado_ids` es un array y DEBE viajar
  // como parámetro repetido — ver `serializeRepeatedParams`.
  reporteHorariosDocumento: (params) =>
    api.get('/rrhh/reportes/horarios-documento', {
      params,
      paramsSerializer: serializeRepeatedParams,
    }),
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
  marcarRevisado: (id) => api.post(`/tickets/tickets/marcar-revisado/${id}`),

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

  // Triage IA (tickets-ai-triage)
  listarPropuestas: (id) => api.get(`/tickets/tickets/${id}/propuestas`),
  triage: (id, forzar = false) =>
    api.post(`/tickets/tickets/${id}/triage`, null, { params: { forzar } }),

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

// ── Propuestas IA (tickets-ai-triage) ────────────────────────
export const propuestasAPI = {
  confirmar: (id) => api.post(`/tickets/propuestas/${id}/confirmar`),
  descartar: (id) => api.post(`/tickets/propuestas/${id}/descartar`),
  confirmarBatch: (propuestaIds) =>
    api.post('/tickets/propuestas/confirmar-batch', { propuesta_ids: propuestaIds }),
};

// ── Tablero (tickets-ai-triage PR 5b) ────────────────────────
export const boardAPI = {
  obtener: (agrupacion, itemsPorColumna) =>
    api.get('/tickets/tickets/board', {
      params: { agrupacion, items_por_columna: itemsPorColumna },
    }),
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
