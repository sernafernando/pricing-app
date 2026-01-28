import axios from 'axios';

const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL,
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

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

export default api;
