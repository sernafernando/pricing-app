import { useCallback, useState } from 'react';
import api from '../services/api';

/**
 * useComprasPapelera — CRUD de la papelera auditable (read-only desde el UI).
 *
 * Envuelve los endpoints:
 *   - GET /administracion/compras/papelera
 *   - GET /administracion/compras/papelera/:id
 *
 * La eliminación se hace desde los hooks de pedidos/OPs (llaman a
 * `api.delete(...)` porque el endpoint DELETE vive en su propio recurso).
 */
export default function useComprasPapelera() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const wrap = useCallback(async (fn) => {
    setLoading(true);
    setError(null);
    try {
      return await fn();
    } catch (err) {
      const msg = err.response?.data?.detail || err.message || 'Error en papelera';
      setError(typeof msg === 'string' ? msg : 'Error en papelera');
      throw err;
    } finally {
      setLoading(false);
    }
  }, []);

  const listar = useCallback(
    (params = {}) =>
      wrap(async () => {
        const { data } = await api.get('/administracion/compras/papelera', { params });
        return data;
      }),
    [wrap]
  );

  const obtener = useCallback(
    (id) =>
      wrap(async () => {
        const { data } = await api.get(`/administracion/compras/papelera/${id}`);
        return data;
      }),
    [wrap]
  );

  return {
    loading,
    error,
    listar,
    obtener,
  };
}
