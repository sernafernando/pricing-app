import { useCallback, useState } from 'react';
import api from '../services/api';

/**
 * useCCProveedor — Cuenta corriente de proveedor + reconciliación.
 *
 * Estrategia C (multi-moneda): los saldos vienen separados por moneda
 * (ARS/USD). El consolidado en ARS al TC del día se calcula opcionalmente
 * en el componente si se requiere mostrarlo.
 */
export default function useCCProveedor() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const wrap = useCallback(async (fn) => {
    setLoading(true);
    setError(null);
    try {
      return await fn();
    } catch (err) {
      const msg = err.response?.data?.detail || err.message || 'Error en CC proveedor';
      setError(typeof msg === 'string' ? msg : 'Error en CC proveedor');
      throw err;
    } finally {
      setLoading(false);
    }
  }, []);

  const obtenerDetalle = useCallback(
    (proveedorId, params = {}) =>
      wrap(async () => {
        const { data } = await api.get(
          `/administracion/compras/cc-proveedor/${proveedorId}`,
          { params }
        );
        return data;
      }),
    [wrap]
  );

  const obtenerPorPedido = useCallback(
    (proveedorId) =>
      wrap(async () => {
        const { data } = await api.get(
          `/administracion/compras/cc-proveedor/${proveedorId}/por-pedido`
        );
        return data;
      }),
    [wrap]
  );

  const listarReconciliaciones = useCallback(
    (params = {}) =>
      wrap(async () => {
        const { data } = await api.get('/administracion/compras/reconciliacion', { params });
        return data;
      }),
    [wrap]
  );

  const forzarReconciliacion = useCallback(
    (fecha = null) =>
      wrap(async () => {
        const body = fecha ? { fecha } : {};
        const { data } = await api.post('/administracion/compras/reconciliacion/forzar', body);
        return data;
      }),
    [wrap]
  );

  const obtenerMetricas = useCallback(
    () =>
      wrap(async () => {
        const { data } = await api.get('/administracion/compras/reconciliacion/metricas');
        return data;
      }),
    [wrap]
  );

  const listarImputaciones = useCallback(
    (params = {}) =>
      wrap(async () => {
        const { data } = await api.get('/administracion/compras/imputaciones', { params });
        return data;
      }),
    [wrap]
  );

  // NO memoizar con useMemo([loading, error, ...]) porque loading/error
  // cambian durante un fetch — eso crearía el mismo loop.
  // Las funciones individuales YA son estables via useCallback; los consumers
  // deben desestructurarlas en vez de depender del objeto completo.
  return {
    loading,
    error,
    obtenerDetalle,
    obtenerPorPedido,
    listarReconciliaciones,
    forzarReconciliacion,
    obtenerMetricas,
    listarImputaciones,
  };
}
