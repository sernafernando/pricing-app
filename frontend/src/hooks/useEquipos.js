import { useState, useEffect, useCallback } from 'react';
import { equiposAPI } from '../services/api';

/**
 * Fetches the color-layer teams (productos-color-teams) available to the user,
 * including the global team. Returns [{ id, nombre, es_global }].
 *
 * On error, keeps an empty list and logs — the Productos page must never crash
 * just because teams could not load (the global layer still works).
 */
export function useEquipos() {
  const [equipos, setEquipos] = useState([]);
  const [loading, setLoading] = useState(false);

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
    }
  }, []);

  useEffect(() => {
    recargar();
  }, [recargar]);

  return { equipos, loading, recargar };
}
