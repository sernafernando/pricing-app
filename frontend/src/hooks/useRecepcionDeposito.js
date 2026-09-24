import { useCallback, useState } from 'react';
import api from '../services/api';

/** Deep-link `?focus=observaciones` (no Router required — tab tests render bare). */
export function readFocusQuery() {
  if (typeof window === 'undefined') return null;
  return new URLSearchParams(window.location.search).get('focus');
}

/** G31 / banner deep-link `?pedido={id}` (same window.search, no Router). */
export function readPedidoQuery() {
  if (typeof window === 'undefined') return null;
  return new URLSearchParams(window.location.search).get('pedido');
}

/** Optional `?eje=` to open a Depósito filter tab (e.g. faltantes_con_res). */
export function readEjeQuery() {
  if (typeof window === 'undefined') return null;
  return new URLSearchParams(window.location.search).get('eje');
}

/**
 * useRecepcionDeposito — Slice B reception endpoints for Batch K.
 *
 * Mirrors the wrap pattern from useComprasPedidos. All errors are propagated
 * to the caller (thrown) so the component decides how to display them.
 */
export default function useRecepcionDeposito() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const wrap = useCallback(async (fn) => {
    setLoading(true);
    setError(null);
    try {
      return await fn();
    } catch (err) {
      const detail = err.response?.data?.detail;
      const msg =
        typeof detail === 'string'
          ? detail
          : err.message || 'Error en recepción';
      setError(msg);
      throw err;
    } finally {
      setLoading(false);
    }
  }, []);

  /**
   * GET /pedidos/{id}/recepcion/saldos
   * @returns {Promise<SaldosResponse>}
   */
  const getSaldos = useCallback(
    (pedidoId) =>
      wrap(async () => {
        const { data } = await api.get(
          `/administracion/compras/pedidos/${pedidoId}/recepcion/saldos`
        );
        return data;
      }),
    [wrap]
  );

  /**
   * POST /pedidos/{id}/recepcion/ingresos
   * @param {number} pedidoId
   * @param {{ lineas: Array<{pod_id: number, cantidad_recibida: number}>, observaciones?: string }} payload
   * @returns {Promise<RegistrarIngresosResponse>}
   */
  const registrarIngresos = useCallback(
    (pedidoId, payload) =>
      wrap(async () => {
        const { data } = await api.post(
          `/administracion/compras/pedidos/${pedidoId}/recepcion/ingresos`,
          payload
        );
        return data;
      }),
    [wrap]
  );

  /**
   * POST /pedidos/{id}/recepcion/confirmar-pedido
   * @param {number} pedidoId
   * @param {{ completo: boolean, observaciones?: string }} payload
   * @returns {Promise<ConfirmarPedidoResponse>}
   */
  const confirmarPedido = useCallback(
    (pedidoId, payload) =>
      wrap(async () => {
        const { data } = await api.post(
          `/administracion/compras/pedidos/${pedidoId}/recepcion/confirmar-pedido`,
          payload
        );
        return data;
      }),
    [wrap]
  );

  /**
   * POST /pedidos/{id}/recepcion/deshacer-recibido
   * @returns {Promise<{pedido_id: number, estado_nuevo: string}>}
   */
  const deshacerRecibido = useCallback(
    (pedidoId) =>
      wrap(async () => {
        const { data } = await api.post(
          `/administracion/compras/pedidos/${pedidoId}/recepcion/deshacer-recibido`
        );
        return data;
      }),
    [wrap]
  );

  /**
   * GET /pedidos/{id}/recepcion/eventos
   * @returns {Promise<EventosRecepcionResponse>}
   */
  const getEventos = useCallback(
    (pedidoId) =>
      wrap(async () => {
        const { data } = await api.get(
          `/administracion/compras/pedidos/${pedidoId}/recepcion/eventos`
        );
        return data;
      }),
    [wrap]
  );

  /**
   * GET /administracion/proveedores/{proveedorId}/direcciones
   * (router de proveedores, NO bajo /compras)
   * @returns {Promise<Array>}
   */
  const getDireccionesProveedor = useCallback(
    (proveedorId) =>
      wrap(async () => {
        const { data } = await api.get(
          `/administracion/proveedores/${proveedorId}/direcciones`
        );
        return data;
      }),
    [wrap]
  );

  /**
   * POST /pedidos/{id}/recepcion/despachar-retiro
   * Endpoint de depósito (permiso deposito.despachar_retiro), NO el de compras
   * generar-etiqueta-envio. Reusa el servicio de retiro: la etiqueta cae en TabEnviosFlex.
   * @param {number} pedidoId
   * @param {{ proveedor_direccion_id: number }} payload
   * @returns {Promise<EtiquetaEnvioResponse>}
   */
  /**
   * POST /pedidos/{id}/faltantes/resolver
   * @param {number} pedidoId
   * @param {{ texto: string }} payload
   * @returns {Promise<{pedido_id: number, faltantes_resuelto_en: string}>}
   */
  const resolverFaltantes = useCallback(
    (pedidoId, payload) =>
      wrap(async () => {
        const { data } = await api.post(
          `/administracion/compras/pedidos/${pedidoId}/faltantes/resolver`,
          payload
        );
        return data;
      }),
    [wrap]
  );

  const generarRetiro = useCallback(
    (pedidoId, payload) =>
      wrap(async () => {
        const { data } = await api.post(
          `/administracion/compras/pedidos/${pedidoId}/recepcion/despachar-retiro`,
          payload
        );
        return data;
      }),
    [wrap]
  );

  return {
    loading,
    error,
    getSaldos,
    registrarIngresos,
    confirmarPedido,
    deshacerRecibido,
    getEventos,
    getDireccionesProveedor,
    generarRetiro,
    resolverFaltantes,
  };
}
