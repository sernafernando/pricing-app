import { useCallback, useState } from 'react';
import api from '../services/api';

/**
 * useComprasOP — CRUD de órdenes de pago.
 *
 * IMPORTANTE: `crear(...)` NO envuelve el error en setError. Devuelve
 * el error crudo al caller para que pueda discriminar el 409
 * POSIBLE_DUPLICADO_OP_ERP y abrir el flujo de confirmación
 * (design §7.3). Los otros métodos sí usan wrap con setError.
 */
export default function useComprasOP() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const wrap = useCallback(async (fn) => {
    setLoading(true);
    setError(null);
    try {
      return await fn();
    } catch (err) {
      const msg = err.response?.data?.detail || err.message || 'Error en órdenes de pago';
      setError(typeof msg === 'string' ? msg : 'Error en órdenes de pago');
      throw err;
    } finally {
      setLoading(false);
    }
  }, []);

  const listar = useCallback(
    (params = {}) =>
      wrap(async () => {
        const { data } = await api.get('/administracion/compras/ordenes-pago', { params });
        return data;
      }),
    [wrap]
  );

  const obtener = useCallback(
    (id) =>
      wrap(async () => {
        const { data } = await api.get(`/administracion/compras/ordenes-pago/${id}`);
        return data;
      }),
    [wrap]
  );

  // NO usa wrap: deja el error raw para que ModalOrdenPagoNueva pueda
  // leer response.status === 409 y abrir el modal de confirmación.
  const crear = useCallback(async (payload) => {
    setLoading(true);
    try {
      const { data } = await api.post('/administracion/compras/ordenes-pago', payload);
      setError(null);
      return data;
    } finally {
      setLoading(false);
    }
  }, []);

  const pagar = useCallback(
    (id, cajaId, fechaPagoReal) =>
      wrap(async () => {
        const { data } = await api.post(`/administracion/compras/ordenes-pago/${id}/pagar`, {
          caja_id: cajaId,
          fecha_pago_real: fechaPagoReal,
        });
        return data;
      }),
    [wrap]
  );

  const anular = useCallback(
    (id, motivo) =>
      wrap(async () => {
        const { data } = await api.post(`/administracion/compras/ordenes-pago/${id}/anular`, {
          motivo,
        });
        return data;
      }),
    [wrap]
  );

  const distribuirAutomatico = useCallback(
    (id) =>
      wrap(async () => {
        const { data } = await api.post(
          `/administracion/compras/ordenes-pago/${id}/distribuir-automatico`
        );
        return data;
      }),
    [wrap]
  );

  return {
    loading,
    error,
    listar,
    obtener,
    crear,
    pagar,
    anular,
    distribuirAutomatico,
  };
}
