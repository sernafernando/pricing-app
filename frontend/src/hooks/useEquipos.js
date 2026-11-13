import { useState, useEffect, useCallback } from 'react';
import { equiposAPI } from '../services/api';

/**
 * Fetches the color-layer teams (productos-color-teams) available to the user,
 * including the global team. Returns [{ id, nombre, es_global, por_defecto, mostrar_referencia_global }]: the last
 * two are the user's own preferences on that layer, set with `guardarPreferencias` (Publicaciones ML's selector).
 *
 * On error, keeps an empty list and logs — the Productos page must never crash
 * just because teams could not load (the global layer still works).
 */
export function useEquipos() {
  const [equipos, setEquipos] = useState([]);
  const [loading, setLoading] = useState(false);
  // True once the first request settled (even failed): an empty list then means "no team", not "not yet".
  const [loaded, setLoaded] = useState(false);

  const recargar = useCallback(async () => {
    setLoading(true);
    try {
      const response = await equiposAPI.listar();
      setEquipos(response.data || []);
    } catch (err) {
      setEquipos([]);
      console.error('Error al cargar equipos:', err);
    } finally {
      setLoading(false);
      setLoaded(true);
    }
  }, []);

  useEffect(() => {
    recargar();
  }, [recargar]);

  // Saves the user's own preferences on one layer; the answer is the whole list, already updated. Throws on failure.
  const guardarPreferencias = useCallback(async (equipoId, preferencias) => {
    const response = await equiposAPI.misPreferencias(equipoId, preferencias);
    setEquipos(response.data || []);
  }, []);

  return { equipos, loading, loaded, recargar, guardarPreferencias };
}
