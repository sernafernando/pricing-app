import api from './api';

const CAMPANAS = '/sell-out/campanas';

/**
 * Sell-out campaigns (`app/routers/sell_out_campanas.py`): `sell_out.ver` lists and reads,
 * `sell_out.gestionar` creates, edits, voids and sets the exchange rate; `sell_out.repartir` (or `gestionar`) splits a
 * `monto_total` campaign among its products.
 */
export const sellOutAPI = {
  listar: (params) => api.get(CAMPANAS, { params }),
  // The grouped view's rows with the list's filters: the programs with campaigns under them, a page at a time,
  // and `sin_programa`, the campaigns without one (null when there are none).
  porPrograma: (params) => api.get(`${CAMPANAS}/por-programa`, { params }),
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
  // The product groups a campaign reaches: the ones Gestionar Offsets manages (`GET /offset-grupos`).
  grupos: () => api.get('/offset-grupos'),
};

const PROGRAMAS = '/sell-out/programas';

/**
 * Sell-out programs (`app/routers/sell_out_programas.py`), the level that groups campaigns: `sell_out.ver` lists them
 * and their suggestions, `sell_out.gestionar` creates, edits and archives them, assigns campaigns and renews a program (Renovar programa
 * creates campaigns; the rest is metadata only).
 */
export const sellOutProgramasAPI = {
  listar: (params) => api.get(PROGRAMAS, { params }),
  crear: (body) => api.post(PROGRAMAS, body),
  // Only the fields sent change: `nombre`, `descripcion`, or `estado` ('archivado' / 'activo'). A taken name is a 409.
  editar: (id, body) => api.patch(`${PROGRAMAS}/${id}`, body),
  // All or nothing: `{ asignadas, sin_cambio }`; an archived program or unknown campaigns are a 422.
  asignar: (campanaIds, programaId) => api.post(`${PROGRAMAS}/asignar`, { campana_ids: campanaIds, programa_id: programaId }),
  // Campaigns without a program that share their exact dates, each group with a proposed name (`base`).
  sugerencias: (params) => api.get(`${PROGRAMAS}/sugerencias`, { params }),
  // Renovar programa's preview: the source period, the target quarter, `renovar`, `omitidas` and `quedan_afuera`.
  renovacion: (id) => api.get(`${PROGRAMAS}/${id}/renovacion`),
  // Creates the copies of the ids the preview listed, all or nothing; a 409 means the preview changed (read it again).
  renovar: (id, campanaIds) => api.post(`${PROGRAMAS}/${id}/renovar`, { campana_ids: campanaIds }),
};
