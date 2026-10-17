import api from './api';

const BASE = '/sell-in/compras';

/**
 * Sell-in purchases API (`backend/app/routers/sell_in_compras.py`). Reads need
 * `sell_in.ver`; preview, create and void need `sell_in.gestionar`.
 */
export const sellInAPI = {
  listar: (params) => api.get(BASE, { params }),
  // Same filters as `listar`; `conteo` ignores `aplica` so the chips keep all three counts.
  resumen: (params) => api.get(`${BASE}/resumen`, { params }),
  detalle: (id) => api.get(`${BASE}/${id}`),
  preview: (body) => api.post(`${BASE}/preview`, body),
  crear: (body) => api.post(BASE, body),
  anular: (id, motivo) => api.post(`${BASE}/${id}/anular`, { motivo: motivo?.trim() || null }),
  // The supplier picker of the create panel (`GET /administracion/proveedores`, active ones by default).
  proveedores: (search) => api.get('/administracion/proveedores', { params: { search, page_size: 10 } }),
};
