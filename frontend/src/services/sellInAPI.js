import api from './api';

const BASE = '/sell-in/compras';

/**
 * Sell-in purchases API (`backend/app/routers/sell_in_compras.py`). Reads need
 * `sell_in.ver`; the operation search and void need `sell_in.gestionar`. Creating is `POST /tacticals` (tacticalsAPI).
 */
export const sellInAPI = {
  listar: (params) => api.get(BASE, { params }),
  // Same filters as `listar`; `conteo` ignores `aplica` so the chips keep all three counts.
  resumen: (params) => api.get(`${BASE}/resumen`, { params }),
  detalle: (id) => api.get(`${BASE}/${id}`),
  // The operation picker: `q`, optional `proveedor_id`/`moneda`, and `excluir` (ids already linked).
  operaciones: (params) => api.get(`${BASE}/operaciones`, { params, paramsSerializer: { indexes: null } }),
  // One operation's products (ordered and received units), for the picker's hover card; needs `sell_in.gestionar`.
  operacionProductos: (id) => api.get(`${BASE}/operaciones/${id}/productos`),
  anular: (id, motivo) => api.post(`${BASE}/${id}/anular`, { motivo: motivo?.trim() || null }),
  // All or nothing; a refused set (409, or 422 for unknown ids) names each one (`{ mensaje, rechazadas: [{ id, motivo }] }`).
  anularMasivo: (ids, motivo) => api.post(`${BASE}/anular-masivo`, { ids, motivo: motivo?.trim() || null }),
  // The supplier picker (`GET /administracion/proveedores`, active ones by default).
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
  anularMasivo: (ids, motivo) => api.post(`${BONOS}/anular-masivo`, { ids, motivo: motivo?.trim() || null }),
};

const PRODUCTOS = '/sell-in/productos';

/**
 * Sell-in lot viewer per product (`backend/app/routers/sell_in_lotes.py`), read only, behind the permission of the
 * product panel: a product's lots in FIFO order with their status, and each lot's consumptions, paginated.
 */
export const sellInLotesAPI = {
  // Sell in's Productos list (`sell_in.ver`): every product with units left in its lots, its cost mode, units, the
  // next sale's sell in per unit and latest purchase, in one request.
  productos: () => api.get(`${PRODUCTOS}/costos`),
  lotes: (itemId) => api.get(`${PRODUCTOS}/${itemId}/lotes`),
  consumos: (itemId, compraItemId, params) => api.get(`${PRODUCTOS}/${itemId}/lotes/${compraItemId}/consumos`, { params }),
  // The product's cost modes (`sell_in.ver`): the history and the one governing today; a change is always previewed
  // first (`{ modo, desde }`) and confirmed with the preview's `huella` (409: the product moved, preview again).
  modos: (itemId) => api.get(`${PRODUCTOS}/${itemId}/modos`),
  vistaPrevia: (itemId, body) => api.post(`${PRODUCTOS}/${itemId}/modos/vista-previa`, body),
  confirmarModo: (itemId, body) => api.post(`${PRODUCTOS}/${itemId}/modos`, body),
  // The mode the selector opens preselected with (global); only an admin changes it. It never changes costing.
  modoPorDefecto: () => api.get(`${PRODUCTOS}/modo-por-defecto`),
  fijarModoPorDefecto: (modo) => api.put(`${PRODUCTOS}/modo-por-defecto`, { modo }),
};
