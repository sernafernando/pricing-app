import { useCallback, useState } from 'react';
import api from '../services/api';

/**
 * useNCsLocales — CRUD + transiciones + vinculación + aplicación de NCs locales.
 *
 * Envuelve los endpoints de /administracion/compras/ncs-locales/* exponiendo
 * funciones con error handling + loading state consistentes. Los errores
 * NO se silencian: se devuelven al caller (throw) para que decida cómo
 * mostrarlos (toast, inline, modal).
 *
 * Diferencia clave con pedidos: una NC aprobada NO impacta CC inmediatamente.
 * Solo impacta al aplicarse (via POST /ncs-locales/{id}/aplicar).
 */
export default function useNCsLocales() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const wrap = useCallback(async (fn) => {
    setLoading(true);
    setError(null);
    try {
      return await fn();
    } catch (err) {
      const raw =
        err.response?.data?.error?.message ||
        err.response?.data?.detail ||
        err.message ||
        'Error en NCs locales';
      setError(typeof raw === 'string' ? raw : 'Error en NCs locales');
      throw err;
    } finally {
      setLoading(false);
    }
  }, []);

  const listar = useCallback(
    (params = {}) =>
      wrap(async () => {
        const { data } = await api.get('/administracion/compras/ncs-locales', { params });
        return data;
      }),
    [wrap]
  );

  const obtener = useCallback(
    (id) =>
      wrap(async () => {
        const { data } = await api.get(`/administracion/compras/ncs-locales/${id}`);
        return data;
      }),
    [wrap]
  );

  const crear = useCallback(
    (payload) =>
      wrap(async () => {
        const { data } = await api.post('/administracion/compras/ncs-locales', payload);
        return data;
      }),
    [wrap]
  );

  const editar = useCallback(
    (id, payload) =>
      wrap(async () => {
        const { data } = await api.put(`/administracion/compras/ncs-locales/${id}`, payload);
        return data;
      }),
    [wrap]
  );

  const enviarAprobacion = useCallback(
    (id) =>
      wrap(async () => {
        const { data } = await api.post(
          `/administracion/compras/ncs-locales/${id}/enviar-aprobacion`
        );
        return data;
      }),
    [wrap]
  );

  const aprobar = useCallback(
    (id, motivo = null) =>
      wrap(async () => {
        const body = motivo ? { motivo } : {};
        const { data } = await api.post(
          `/administracion/compras/ncs-locales/${id}/aprobar`,
          body
        );
        return data;
      }),
    [wrap]
  );

  const rechazar = useCallback(
    (id, accion, motivo) =>
      wrap(async () => {
        const { data } = await api.post(`/administracion/compras/ncs-locales/${id}/rechazar`, {
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
        const { data } = await api.post(`/administracion/compras/ncs-locales/${id}/reabrir`);
        return data;
      }),
    [wrap]
  );

  const cancelar = useCallback(
    (id, motivo) =>
      wrap(async () => {
        const body = motivo ? { motivo } : {};
        const { data } = await api.post(
          `/administracion/compras/ncs-locales/${id}/cancelar`,
          body
        );
        return data;
      }),
    [wrap]
  );

  const listarEventos = useCallback(
    (id) =>
      wrap(async () => {
        const { data } = await api.get(`/administracion/compras/ncs-locales/${id}/eventos`);
        return data;
      }),
    [wrap]
  );

  // ── Vinculación con NC del ERP ─────────────────────────────────────
  const listarCandidatasERP = useCallback(
    (id) =>
      wrap(async () => {
        const { data } = await api.get(
          `/administracion/compras/ncs-locales/${id}/candidatas-erp`
        );
        return data;
      }),
    [wrap]
  );

  const vincularFactura = useCallback(
    (id, body) =>
      wrap(async () => {
        const { data } = await api.post(
          `/administracion/compras/ncs-locales/${id}/vincular-factura`,
          body
        );
        return data;
      }),
    [wrap]
  );

  const desvincularFactura = useCallback(
    (id) =>
      wrap(async () => {
        const { data } = await api.post(
          `/administracion/compras/ncs-locales/${id}/desvincular-factura`
        );
        return data;
      }),
    [wrap]
  );

  // ── Aplicación (imputar crédito a pedido/factura/saldo) ────────────
  // body: { destino_tipo, destino_id?, monto_imputado }
  const aplicar = useCallback(
    (id, body) =>
      wrap(async () => {
        const { data } = await api.post(
          `/administracion/compras/ncs-locales/${id}/aplicar`,
          body
        );
        return data;
      }),
    [wrap]
  );

  /**
   * F4 — NCs locales con saldo > 0 disponibles para imputar a una OP.
   * GET /ncs-locales/disponibles?proveedor_id=&limit=&offset=
   * Returns NCDisponibleSummary[] (saldo_pendiente ya calculado en batch).
   */
  const listarDisponibles = useCallback(
    (params = {}) =>
      wrap(async () => {
        const { data } = await api.get('/administracion/compras/ncs-locales/disponibles', {
          params,
        });
        return data;
      }),
    [wrap]
  );

  return {
    loading,
    error,
    listar,
    listarDisponibles,
    obtener,
    crear,
    editar,
    enviarAprobacion,
    aprobar,
    rechazar,
    reabrir,
    cancelar,
    listarEventos,
    listarCandidatasERP,
    vincularFactura,
    desvincularFactura,
    aplicar,
  };
}
