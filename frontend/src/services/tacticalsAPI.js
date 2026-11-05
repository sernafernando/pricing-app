import api from './api';
import { sellInAPI } from './sellInAPI';

const TACTICALS = '/tacticals';

/**
 * Tacticals (`/api/tacticals`, handoffs/tactical-tarea.md, "Contrato final"): a brand program whose lines live in the
 * sell-in and sell-out engines.
 * - `listar(params)`: takes tipo, marca, estado (`vigentes` | `vencidos` | `anulados`), desde, hasta, q, page and
 *   page_size, and answers `{ items, total }`, each tactical with its lines and their usage.
 * - `crear(body)`: `POST /tacticals`, a header with its lines at once, all or nothing; a 422 `{error: {message}}`
 *   names the line ("Línea 3: …").
 * - `buscarProductos(q)`: the catalog search Offset uses (`GET /buscar-productos-catalogo`, 2+ characters).
 * - `buscarFacturas(q)`: the Compras operations Sell in links (`GET /sell-in/compras/operaciones`, newest first).
 */
export const tacticalsAPI = {
  listar: (params) => api.get(TACTICALS, { params }),
  crear: (body) => api.post(TACTICALS, body),
  buscarProductos: (q) => api.get('/buscar-productos-catalogo', { params: { q } }).then((r) => r.data ?? []),
  buscarFacturas: (q) => sellInAPI.operaciones(q ? { q } : {}).then((r) => r.data?.items ?? []),
};
