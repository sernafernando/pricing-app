import api from './api';

/**
 * Column layouts and presets of Publicaciones ML (pubml-columnas-presets, `app/routers/ml_publications_presets.py`).
 * `vista` is one of publicacion | precios | producto | agrupado | auditoria. Every call resolves to the response body;
 * they are `async` so that even a broken client rejects instead of throwing.
 *
 * - layout: `{ columns: { visibility: { key: bool }, order: [key] } | null, preset_activo_id: int | null }`.
 * - preset: `{ id, vista, nombre, compartido, editable, payload: { columns, params: { key: string } }, updated_at }`.
 *   A name already used answers 409; a shared preset without `ml_publicaciones.presets_compartidos`, 403.
 */
export const mlPublicationsPresetsAPI = {
  getLayout: async (vista) => (await api.get(`/ml-publications/layouts/${vista}`)).data,
  // "Restablecer" is `{ columns: null, preset_activo_id: null }`.
  saveLayout: async (vista, body) => (await api.put(`/ml-publications/layouts/${vista}`, body)).data,
  // The user's personal presets and every shared one of `vista`, shared first.
  list: async (vista) => (await api.get('/ml-publications/presets', { params: { vista } })).data,
  // `{ vista, nombre, compartido, payload }` -> 201 + the preset.
  create: async (body) => (await api.post('/ml-publications/presets', body)).data,
  // `{ nombre?, payload? }` -> the preset.
  update: async (id, body) => (await api.put(`/ml-publications/presets/${id}`, body)).data,
  remove: async (id) => {
    await api.delete(`/ml-publications/presets/${id}`);
  },
};
