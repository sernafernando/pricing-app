import api from './api';

const CAMPANAS = '/sell-out/campanas';

/**
 * Sell-out campaigns (`app/routers/sell_out_campanas.py`): `sell_out.ver` lists and reads,
 * `sell_out.gestionar` creates, edits, voids and sets the exchange rate.
 */
export const sellOutAPI = {
  listar: (params) => api.get(CAMPANAS, { params }),
  detalle: (id) => api.get(`${CAMPANAS}/${id}`),
};
