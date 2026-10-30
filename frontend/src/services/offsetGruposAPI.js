import api from './api';

/**
 * The product groups sell-out campaigns reach (`app/api/endpoints/offsets_ganancia/_grupos.py`, `_filtros.py`).
 * A group is an OR of filter rows; a row is an AND of the fields it sets (marca, categoria, subcategoria_id,
 * item_id). Every write and `alcance` need `config.editar_constantes`; changing filters re-queues the campaigns.
 */
export const offsetGruposAPI = {
  listar: () => api.get('/offset-grupos'),
  // Per group: `{ grupo_id, productos, campanas: [{ id, nombre, estado }] }`.
  alcance: () => api.get('/offset-grupos-alcance'),
  // The brands, categories and subcategories products have (`{ marcas, categorias, subcategorias: [{ id, nombre }] }`).
  opciones: () => api.get('/offset-filtros-opciones'),
  crear: (body) => api.post('/offset-grupos', body),
  editar: (id, body) => api.patch(`/offset-grupos/${id}`, body),
  // Refused (400, the message names the active campaigns) while a sell-out campaign or a legacy offset uses it.
  eliminar: (id) => api.delete(`/offset-grupos/${id}`),
  agregarFiltro: (id, filtro) => api.post(`/offset-grupos/${id}/filtros`, filtro),
  eliminarFiltro: (id, filtroId) => api.delete(`/offset-grupos/${id}/filtros/${filtroId}`),
};
