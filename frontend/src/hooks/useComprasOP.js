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
    (id, cajaId, fechaPagoReal, tipoCambioOverride = null) =>
      wrap(async () => {
        const body = {
          caja_id: cajaId,
          fecha_pago_real: fechaPagoReal,
        };
        if (tipoCambioOverride !== null && tipoCambioOverride !== undefined && tipoCambioOverride !== '') {
          body.tipo_cambio_override = tipoCambioOverride;
        }
        const { data } = await api.post(
          `/administracion/compras/ordenes-pago/${id}/pagar`,
          body
        );
        return data;
      }),
    [wrap]
  );

  /**
   * Editar OP en estado 'pendiente' (sub-batch 1.1).
   * 409 si la OP ya fue pagada/anulada/cancelada.
   */
  const editar = useCallback(
    (id, payload) =>
      wrap(async () => {
        const { data } = await api.put(
          `/administracion/compras/ordenes-pago/${id}`,
          payload
        );
        return data;
      }),
    [wrap]
  );

  /**
   * Cancelar OP pendiente (sub-batch 1.2). Transición terminal sin
   * efectos colaterales: no hay imputaciones, caja ni CC que revertir.
   */
  const cancelarPendiente = useCallback(
    (id, motivo) =>
      wrap(async () => {
        const { data } = await api.post(
          `/administracion/compras/ordenes-pago/${id}/cancelar-pendiente`,
          { motivo }
        );
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

  /**
   * Hard-delete auditable de OP anulada sin movimiento.
   */
  const eliminar = useCallback(
    (id, motivo, challengePalabraUsada = null) =>
      wrap(async () => {
        const { data } = await api.delete(`/administracion/compras/ordenes-pago/${id}`, {
          data: {
            motivo,
            challenge_palabra_usada: challengePalabraUsada,
          },
        });
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
    editar,
    cancelarPendiente,
    pagar,
    anular,
    distribuirAutomatico,
    eliminar,
  };
}
