import api from './api';

const TACTICALS = '/tacticals';

/**
 * Tacticals (`/api/tacticals`, handoffs/tactical-tarea.md): a brand program whose lines live in the sell-in and
 * sell-out engines. `listar` takes tipo, marca, estado (`vigentes` | `vencidos` | `anulados`), desde, hasta, q, page and
 * page_size, and answers `{ items, total }`, each tactical with its lines and their usage.
 */
export const tacticalsAPI = {
  listar: (params) => api.get(TACTICALS, { params }),
};
