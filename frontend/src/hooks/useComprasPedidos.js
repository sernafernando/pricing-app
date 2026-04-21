import { useCallback, useState } from 'react';
import api from '../services/api';

/**
 * useComprasPedidos — CRUD + transiciones de pedidos de compra.
 *
 * Envuelve los endpoints de /administracion/compras/pedidos/* exponiendo
 * funciones con error handling + loading state consistentes. Los errores
 * NO se silencian: se devuelven al caller (throw) para que decida cómo
 * mostrarlos (toast, inline, modal).
 */
export default function useComprasPedidos() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const wrap = useCallback(async (fn) => {
    setLoading(true);
    setError(null);
    try {
      return await fn();
    } catch (err) {
      const msg = err.response?.data?.detail || err.message || 'Error en pedidos';
      setError(typeof msg === 'string' ? msg : 'Error en pedidos');
      throw err;
    } finally {
      setLoading(false);
    }
  }, []);

  const listar = useCallback(
    (params = {}) =>
      wrap(async () => {
        const { data } = await api.get('/administracion/compras/pedidos', { params });
        return data;
      }),
    [wrap]
  );

  const obtener = useCallback(
    (id) =>
      wrap(async () => {
        const { data } = await api.get(`/administracion/compras/pedidos/${id}`);
        return data;
      }),
    [wrap]
  );

  const crear = useCallback(
    (payload) =>
      wrap(async () => {
        const { data } = await api.post('/administracion/compras/pedidos', payload);
        return data;
      }),
    [wrap]
  );

  const editar = useCallback(
    (id, payload) =>
      wrap(async () => {
        const { data } = await api.put(`/administracion/compras/pedidos/${id}`, payload);
        return data;
      }),
    [wrap]
  );

  const enviarAprobacion = useCallback(
    (id) =>
      wrap(async () => {
        const { data } = await api.post(`/administracion/compras/pedidos/${id}/enviar-aprobacion`);
        return data;
      }),
    [wrap]
  );

  const aprobar = useCallback(
    (id, fechaPagoEstimada) =>
      wrap(async () => {
        const body = fechaPagoEstimada ? { fecha_pago_estimada: fechaPagoEstimada } : {};
        const { data } = await api.post(`/administracion/compras/pedidos/${id}/aprobar`, body);
        return data;
      }),
    [wrap]
  );

  const rechazar = useCallback(
    (id, accion, motivo) =>
      wrap(async () => {
        const { data } = await api.post(`/administracion/compras/pedidos/${id}/rechazar`, {
          accion,
          motivo,
        });
        return data;
      }),
    [wrap]
  );

  const reabrir = useCallback(
    (id) =>
      wrap(async () => {
        const { data } = await api.post(`/administracion/compras/pedidos/${id}/reabrir`);
        return data;
      }),
    [wrap]
  );

  const cancelar = useCallback(
    (id, motivo) =>
      wrap(async () => {
        const body = motivo ? { motivo } : {};
        const { data } = await api.post(`/administracion/compras/pedidos/${id}/cancelar`, body);
        return data;
      }),
    [wrap]
  );

  const generarEtiqueta = useCallback(
    (id, proveedorDireccionId = null) =>
      wrap(async () => {
        const body = proveedorDireccionId ? { proveedor_direccion_id: proveedorDireccionId } : {};
        const { data } = await api.post(
          `/administracion/compras/pedidos/${id}/generar-etiqueta-envio`,
          body
        );
        return data;
      }),
    [wrap]
  );

  const listarEventos = useCallback(
    (id) =>
      wrap(async () => {
        const { data } = await api.get(`/administracion/compras/pedidos/${id}/eventos`);
        return data;
      }),
    [wrap]
  );

  /**
   * Hard-delete auditable. El backend valida reglas (estado, imputaciones,
   * retención). Si falla devuelve 409 con detail explicativo.
   */
  const eliminar = useCallback(
    (id, motivo, challengePalabraUsada = null) =>
      wrap(async () => {
        const { data } = await api.delete(`/administracion/compras/pedidos/${id}`, {
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
    enviarAprobacion,
    aprobar,
    rechazar,
    reabrir,
    cancelar,
    generarEtiqueta,
    listarEventos,
    eliminar,
  };
}
