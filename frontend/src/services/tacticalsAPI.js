import api from './api';
import { sellInAPI } from './sellInAPI';

const TACTICALS = '/tacticals';

/**
 * Tacticals (`/api/tacticals`, handoffs/tactical-tarea.md, "Contrato final"): a brand program whose lines live in the
 * sell-in and sell-out engines.
 * - `listar(params)`: takes tipo, marca, moneda (`ARS` | `USD`), estado (`vigentes` | `vencidos` | `anulados`), desde,
 *   hasta, q, page and page_size, and answers `{ items, total }`, each tactical with its lines and their usage.
 * - `detalle(id)`: `GET /tacticals/{id}`, one tactical with its lines (Renovar prefills Nuevo tactical from it).
 * - `crear(body)`: `POST /tacticals`, a header with its lines at once, all or nothing; a 422 `{error: {message}}`
 *   names the line ("Línea 3: …").
 * - `editar(id, body)`: `PATCH /tacticals/{id}`, only nombre, nota, fecha_hasta and each line's caps
 *   (`lineas: [{linea, tope_unidades?, tope_monto?}]`, a null cap removes it); a 422 names the line.
 * - `reemplazar(id, body)`: `PUT /tacticals/{id}`, the create's body: the whole definition is loaded again under the
 *   same id and what it applied is recomputed (S8); a 409 when it is voided or collected, a 422 names the line.
 * - `anular(id, motivo)`: `POST /tacticals/{id}/anular`, voids the tactical and every child (the reason, or null,
 *   goes to the audit rows); a 409 when it is already voided.
 * - `cobrar(id, body)`: `PUT /tacticals/{id}/cobranza`, saves its one collection record (`fecha_cobro` required; medio
 *   nota_credito | fondo_distribuidor | otro with nc_numero / distribuidor / otro_detalle; observaciones): "Cobrado".
 * - `deshacerCobro(id)`: `DELETE /tacticals/{id}/cobranza`, back to "Pendiente" (a 204 when there was none).
 * - `listar` also takes `cobranza` (`cobrados` | `pendientes`) and answers `kpis` (Pendientes / Cobrados over the
 *   other filters: `{ cantidad, montos: [{ moneda, monto }] }`).
 * - `buscarProductos(q)`: the catalog search Offset uses (`GET /buscar-productos-catalogo`, 2+ characters).
 * - `buscarFacturas(q)`: the Compras operations Sell in links (`GET /sell-in/compras/operaciones`, newest first).
 */
export const tacticalsAPI = {
  listar: (params) => api.get(TACTICALS, { params }),
  detalle: (id) => api.get(`${TACTICALS}/${id}`),
  crear: (body) => api.post(TACTICALS, body),
  editar: (id, body) => api.patch(`${TACTICALS}/${id}`, body),
  reemplazar: (id, body) => api.put(`${TACTICALS}/${id}`, body),
  anular: (id, motivo) => api.post(`${TACTICALS}/${id}/anular`, { motivo }),
  cobrar: (id, body) => api.put(`${TACTICALS}/${id}/cobranza`, body),
  deshacerCobro: (id) => api.delete(`${TACTICALS}/${id}/cobranza`),
  buscarProductos: (q) => api.get('/buscar-productos-catalogo', { params: { q } }).then((r) => r.data ?? []),
  buscarFacturas: (q) => sellInAPI.operaciones(q ? { q } : {}).then((r) => r.data?.items ?? []),
};
