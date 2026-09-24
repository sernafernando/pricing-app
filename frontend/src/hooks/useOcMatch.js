import { useEffect, useState } from 'react';
import api from '../services/api';

export const OC_MATCH_BASE = '/administracion/compras/oc-match/jobs';
export const OC_MATCH_POLL_MS = 3000;
export const OC_MATCH_ACTIVE = new Set(['queued', 'running']);

export function needsOcMatchPoll(jobs, selected) {
  if (selected && OC_MATCH_ACTIVE.has(selected.status)) return true;
  return (jobs || []).some((job) => OC_MATCH_ACTIVE.has(job.status));
}

function errorMessage(err, fallback) {
  const raw =
    err.response?.data?.detail || err.response?.data?.error?.message || err.message;
  return typeof raw === 'string' ? raw : fallback;
}

function listParams(status, page, pageSize) {
  const params = { page, page_size: pageSize };
  if (status) params.status = status;
  return params;
}

/**
 * useOcMatch — list/detail/retry/refresh-doc-refs/excel + poll 3s while queued|running.
 * Stops when selected and list jobs are done|error|skipped, and on unmount.
 */
export default function useOcMatch({ status = '', page = 1, pageSize = 50 } = {}) {
  const [jobs, setJobs] = useState([]);
  const [total, setTotal] = useState(0);
  const [selectedId, setSelectedId] = useState(null);
  const [selected, setSelected] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [reloadToken, setReloadToken] = useState(0);

  const refresh = () => setReloadToken((n) => n + 1);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      setError(null);
      try {
        const { data } = await api.get(OC_MATCH_BASE, {
          params: listParams(status, page, pageSize),
        });
        if (cancelled) return;
        setJobs(data.items || []);
        setTotal(data.total || 0);
      } catch (err) {
        if (cancelled) return;
        setError(errorMessage(err, 'Error al listar jobs de OC Match'));
        setJobs([]);
        setTotal(0);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    load();
    return () => {
      cancelled = true;
    };
  }, [status, page, pageSize, reloadToken]);

  useEffect(() => {
    if (!selectedId) {
      setSelected(null);
      return undefined;
    }
    let cancelled = false;
    const load = async () => {
      try {
        const { data } = await api.get(`${OC_MATCH_BASE}/${selectedId}`);
        if (!cancelled) setSelected(data);
      } catch (err) {
        if (!cancelled) setError(errorMessage(err, 'Error al cargar el job'));
      }
    };
    load();
    return () => {
      cancelled = true;
    };
  }, [selectedId, reloadToken]);

  const shouldPoll = needsOcMatchPoll(jobs, selected);

  useEffect(() => {
    if (!shouldPoll) return undefined;
    const timer = setInterval(() => {
      api
        .get(OC_MATCH_BASE, { params: listParams(status, page, pageSize) })
        .then(({ data }) => {
          setJobs(data.items || []);
          setTotal(data.total || 0);
        })
        .catch(() => {});
      if (selectedId) {
        api
          .get(`${OC_MATCH_BASE}/${selectedId}`)
          .then(({ data }) => setSelected(data))
          .catch(() => {});
      }
    }, OC_MATCH_POLL_MS);
    return () => clearInterval(timer);
  }, [shouldPoll, selectedId, status, page, pageSize]);

  const refreshDocRefs = async (id) => {
    setError(null);
    try {
      const { data } = await api.post(`${OC_MATCH_BASE}/${id}/refresh-doc-refs`);
      setJobs((prev) => prev.map((job) => (job.id === id ? { ...job, ...data } : job)));
      if (selectedId === id) {
        setSelected((prev) => ({ ...(prev || {}), ...data }));
      }
      return data;
    } catch (err) {
      setError(errorMessage(err, 'Error al actualizar Factura/s y Pedido/s'));
      throw err;
    }
  };

  const retry = async (id, { refrescar_doc_refs = false } = {}) => {
    setError(null);
    try {
      const { data } = await api.post(`${OC_MATCH_BASE}/${id}/retry`, { refrescar_doc_refs });
      setJobs((prev) => prev.map((job) => (job.id === id ? { ...job, ...data } : job)));
      if (selectedId === id) {
        setSelected((prev) => ({ ...(prev || {}), ...data }));
      }
      return data;
    } catch (err) {
      setError(errorMessage(err, 'Error al reintentar el job'));
      throw err;
    }
  };

  const downloadExcel = async (id) => {
    setError(null);
    try {
      const { data } = await api.get(`${OC_MATCH_BASE}/${id}/excel`, {
        responseType: 'blob',
      });
      const blobUrl = URL.createObjectURL(data);
      const a = document.createElement('a');
      a.href = blobUrl;
      a.download = `oc-match-${id}.xlsx`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(blobUrl);
      return data;
    } catch (err) {
      setError(errorMessage(err, 'Error al descargar el Excel'));
      throw err;
    }
  };

  return {
    jobs,
    total,
    selected,
    selectedId,
    setSelectedId,
    loading,
    error,
    refresh,
    retry,
    refreshDocRefs,
    downloadExcel,
  };
}
