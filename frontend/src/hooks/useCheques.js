import { useCallback, useState } from 'react';
import api from '../services/api';

/**
 * useCheques — CRUD de chequeras y cheques (Slice 1).
 *
 * Sigue el mismo patrón que useComprasOP: wrap() centraliza
 * loading/error; los métodos retornan la data directamente.
 *
 * Endpoints:
 *   GET  /administracion/cheques/chequeras?banco_empresa_id=
 *   POST /administracion/cheques/chequeras
 *   GET  /administracion/cheques/cheques  (filtros paginados)
 *   POST /administracion/cheques/cheques/propio
 *   POST /administracion/cheques/cheques/{id}/anular
 *   GET  /administracion/cheques/cheques/{id}
 */
export default function useCheques() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const wrap = useCallback(async (fn) => {
    setLoading(true);
    setError(null);
    try {
      return await fn();
    } catch (err) {
      const d = err.response?.data;
      const msg =
        (typeof d?.detail === 'string' && d.detail) ||
        (Array.isArray(d?.detail) &&
          d.detail.map((e) => e?.msg || JSON.stringify(e)).join('; ')) ||
        d?.mensaje ||
        err.message ||
        'Error en módulo de cheques';
      setError(typeof msg === 'string' ? msg : 'Error en módulo de cheques');
      throw err;
    } finally {
      setLoading(false);
    }
  }, []);

  /** Listar cheques con filtros opcionales (paginado). */
  const listar = useCallback(
    (params = {}) =>
      wrap(async () => {
        const { data } = await api.get('/administracion/cheques/cheques', { params });
        return data;
      }),
    [wrap],
  );

  /** Listar chequeras de un banco empresa. */
  const listarChequeras = useCallback(
    (params = {}) =>
      wrap(async () => {
        const { data } = await api.get('/administracion/cheques/chequeras', { params });
        return data;
      }),
    [wrap],
  );

  /** Crear chequera. */
  const crearChequera = useCallback(
    (payload) =>
      wrap(async () => {
        const { data } = await api.post('/administracion/cheques/chequeras', payload);
        return data;
      }),
    [wrap],
  );

  /**
   * Emitir cheque propio (standalone o desde OP).
   * body: { banco_empresa_id, chequera_id, instrumento, numero, monto, moneda,
   *          fecha_emision, fecha_pago, proveedor_id, pedido_id? }
   */
  const emitirPropio = useCallback(
    (payload) =>
      wrap(async () => {
        const { data } = await api.post('/administracion/cheques/cheques/propio', payload);
        return data;
      }),
    [wrap],
  );

  /** Anular cheque (motivo requerido). */
  const anular = useCallback(
    (id, motivo) =>
      wrap(async () => {
        const { data } = await api.post(`/administracion/cheques/cheques/${id}/anular`, {
          motivo,
        });
        return data;
      }),
    [wrap],
  );

  /** Obtener detalle de un cheque (+ eventos). */
  const obtener = useCallback(
    (id) =>
      wrap(async () => {
        const { data } = await api.get(`/administracion/cheques/cheques/${id}`);
        return data;
      }),
    [wrap],
  );

  /**
   * Recibir cheque de tercero (alta a cartera).
   * body: { banco_nombre, cuit_librador, librador_nombre?, numero, monto, moneda,
   *          fecha_emision, fecha_pago, instrumento? }
   * Estado resultante: en_cartera.
   */
  const recibirTercero = useCallback(
    (payload) =>
      wrap(async () => {
        const { data } = await api.post('/administracion/cheques/cheques/tercero', payload);
        return data;
      }),
    [wrap],
  );

  /**
   * Aplicar transición manual de e-cheq (Slice 3).
   * accion: 'aceptar' | 'rechazar_emision' | 'poner_en_custodia'
   * motivo: string opcional (requerido por el backend solo para rechazar_emision).
   *
   * NOTE: estas transiciones son manuales — sin integración bancaria automática (Slice 4).
   */
  const transicionarEcheq = useCallback(
    (id, accion, motivo = null) =>
      wrap(async () => {
        const body = { accion };
        if (motivo) body.motivo = motivo;
        const { data } = await api.post(`/administracion/cheques/cheques/${id}/echeq`, body);
        return data;
      }),
    [wrap],
  );

  return {
    loading,
    error,
    listar,
    listarChequeras,
    crearChequera,
    emitirPropio,
    recibirTercero,
    anular,
    obtener,
    transicionarEcheq,
  };
}
