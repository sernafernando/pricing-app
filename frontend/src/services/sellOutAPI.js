import api from './api';

const CAMPANAS = '/sell-out/campanas';

/**
 * Sell-out campaigns (`app/routers/sell_out_campanas.py`): `sell_out.ver` lists and reads,
 * `sell_out.gestionar` creates, edits, voids and sets the exchange rate.
 */
export const sellOutAPI = {
  listar: (params) => api.get(CAMPANAS, { params }),
  detalle: (id) => api.get(`${CAMPANAS}/${id}`),
  crear: (body) => api.post(CAMPANAS, body),
  editar: (id, body) => api.put(`${CAMPANAS}/${id}`, body),
  // The product groups a campaign reaches: the ones Gestionar Offsets manages (`GET /offset-grupos`).
  grupos: () => api.get('/offset-grupos'),
};
