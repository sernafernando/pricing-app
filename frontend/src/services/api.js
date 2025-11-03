import axios from 'axios';

const api = axios.create({
  baseURL: 'https://pricing.gaussonline.com.ar/api',  // API directa
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

export const authAPI = {
  login: (email, password) => api.post('/auth/login', { email, password }),
  me: () => api.get('/auth/me'),
};

export const productosAPI = {
  listar: (params) => api.get('/productos', { params }),
  stats: () => api.get('/stats'),
  marcas: (params) => api.get('/marcas', { params }),
  subcategorias: (params) => api.get('/subcategorias', { params }),
  categorias: () => api.get('/categorias'),
};

export const pricingAPI = {
  calcularCompleto: (data) => api.post('/precios/calcular-completo', data),
  setearPrecio: (data) => api.post('/precios/set', data),
};

export default api;
