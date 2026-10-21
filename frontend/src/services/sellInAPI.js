import api from './api';

const BASE = '/sell-in/compras';

/**
 * Sell-in purchases API (`backend/app/routers/sell_in_compras.py`). Reads need
 * `sell_in.ver`; preview, prefill, the operation search, create and void need `sell_in.gestionar`.
 */
export const sellInAPI = {
  listar: (params) => api.get(BASE, { params }),
  // Same filters as `listar`; `conteo` ignores `aplica` so the chips keep all three counts.
  resumen: (params) => api.get(`${BASE}/resumen`, { params }),
  detalle: (id) => api.get(`${BASE}/${id}`),
  preview: (body) => api.post(`${BASE}/preview`, body),
  crear: (body) => api.post(BASE, body),
  // Supplier, currency, receipt date and products of Compras operations; FastAPI reads `?pedido_compra_ids=1&pedido_compra_ids=2`.
  prefill: (ids) => api.get(`${BASE}/prefill`, { params: { pedido_compra_ids: ids }, paramsSerializer: { indexes: null } }),
  // The create panel's operation picker: `q`, optional `proveedor_id`/`moneda`, and `excluir` (ids already linked).
  operaciones: (params) => api.get(`${BASE}/operaciones`, { params, paramsSerializer: { indexes: null } }),
  anular: (id, motivo) => api.post(`${BASE}/${id}/anular`, { motivo: motivo?.trim() || null }),
  // The supplier picker of the create panel (`GET /administracion/proveedores`, active ones by default).
  proveedores: (search) => api.get('/administracion/proveedores', { params: { search, page_size: 10 } }),
};

const BONOS = '/sell-in/bonos';

/**
 * Brand bonuses API (`backend/app/routers/sell_in_bonos.py`): an amount per invoiced unit of a brand over a
 * supplier-invoice date range, applied by the worker. Reads need `sell_in.ver`; create, edit and void need
 * `sell_in.gestionar`. Edit is a full replace.
 */
export const sellInBonosAPI = {
  listar: (params) => api.get(BONOS, { params }),
  detalle: (id) => api.get(`${BONOS}/${id}`),
  // Generated purchases, brand operations pending an invoice and out of range, each capped with its count.
  alcance: (id) => api.get(`${BONOS}/${id}/alcance`),
  crear: (body) => api.post(BONOS, body),
  editar: (id, body) => api.put(`${BONOS}/${id}`, body),
  anular: (id, motivo) => api.post(`${BONOS}/${id}/anular`, { motivo: motivo?.trim() || null }),
};
