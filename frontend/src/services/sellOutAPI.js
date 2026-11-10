import api from './api';

const CAMPANAS = '/sell-out/campanas';

/**
 * Sell-out campaigns (`app/routers/sell_out_campanas.py`): `sell_out.ver` lists and reads,
 * `sell_out.gestionar` creates, edits, voids and sets the exchange rate; `sell_out.repartir` (or `gestionar`) splits a
 * `monto_total` campaign among its products.
 */
export const sellOutAPI = {
  listar: (params) => api.get(CAMPANAS, { params }),
  detalle: (id) => api.get(`${CAMPANAS}/${id}`),
  // What a campaign credited, sale line by sale line, page by page.
  consumos: (id, params) => api.get(`${CAMPANAS}/${id}/consumos`, { params }),
  crear: (body) => api.post(CAMPANAS, body),
  editar: (id, body) => api.put(`${CAMPANAS}/${id}`, body),
  // The renewal draft of a campaign, active or voided: a NEW campaign in the shape `crear` takes. It writes nothing.
  renovacion: (id) => api.get(`${CAMPANAS}/${id}/renovacion`),
  anular: (id, motivo) => api.post(`${CAMPANAS}/${id}/anular`, { motivo: motivo?.trim() || null }),
  // Bulk void, all or nothing: `{ anuladas, omitidas }`; a refusal is a 422 with `error.rechazadas: [{ id, motivo }]`.
  anularVarias: (ids, motivo) => api.post(`${CAMPANAS}/anular`, { ids, motivo: motivo?.trim() || null }),
  // The rate the brand paid at, for an `al_cobro` campaign; also after it ended, and it can be changed.
  definirTipoCambio: (id, tipoCambio) => api.post(`${CAMPANAS}/${id}/tipo-cambio`, { tipo_cambio: tipoCambio }),
  // The shares of a `monto_total` campaign: `[{ item_id, reparto_porcentaje | reparto_monto }]`. A brand-scoped PM
  // sends and gets back only their brands' shares; the others are kept by the server.
  repartir: (id, repartos) => api.put(`${CAMPANAS}/${id}/reparto`, { repartos }),
  // A `monto_total` campaign split by a criterion (`iguales` | `unidades` | `costo`), for a user without brand
  // restriction: the per-product result before saving, then the same PUT with no shares and the criterion.
  vistaPreviaReparto: (id, criterio) => api.get(`${CAMPANAS}/${id}/reparto/vista-previa`, { params: { criterio } }),
  repartirPorCriterio: (id, criterio) => api.put(`${CAMPANAS}/${id}/reparto`, { repartos: [], criterio }),
  // The product groups a campaign reaches: the ones Gestionar Offsets manages (`GET /offset-grupos`).
  grupos: () => api.get('/offset-grupos'),
};
