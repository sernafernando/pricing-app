import { useEffect, useState } from 'react';
import api from '../../services/api';
import styles from '../../pages/GestionFull.module.css';

function cell(value) {
  if (value === null || value === undefined || value === '') return '—';
  return value;
}

/** With responseType blob, error bodies arrive as Blob — parse JSON detail. */
async function messageFromBlobError(err, genericError) {
  const data = err?.response?.data;
  if (data && typeof data.text === 'function') {
    try {
      const parsed = JSON.parse(await data.text());
      const detail = parsed?.detail;
      if (typeof detail === 'string' && detail) return detail;
      if (Array.isArray(detail) && detail.length) {
        return detail
          .map((item) => (typeof item === 'string' ? item : item?.msg))
          .filter(Boolean)
          .join('; ');
      }
    } catch {
      // not JSON — fall through
    }
  }
  if (typeof data?.detail === 'string' && data.detail) return data.detail;
  return genericError;
}

async function downloadBlob(path, filename) {
  try {
    const { data } = await api.get(path, { responseType: 'blob' });
    const url = URL.createObjectURL(data);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  } catch (err) {
    throw new Error(await messageFromBlobError(err, `No se pudo exportar`));
  }
}

export default function GestionFullGestorTab() {
  const [pkg, setPkg] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [msg, setMsg] = useState(null);
  const [filter, setFilter] = useState('todos');
  const [selected, setSelected] = useState(() => new Set());
  const [inboundId, setInboundId] = useState('');
  const [busy, setBusy] = useState(false);
  const [nonce, setNonce] = useState(0);
  const [qtyDraft, setQtyDraft] = useState(() => ({}));

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      setError(null);
      try {
        const { data } = await api.get('/gestion-full/package');
        if (!cancelled) {
          setPkg(data);
          setSelected(new Set());
          setQtyDraft({});
        }
      } catch (err) {
        if (!cancelled) {
          setPkg(null);
          const status = err?.response?.status;
          setError(
            status === 404
              ? 'No hay paquete activo. Agregá líneas cerradas (Listo) desde acá.'
              : 'No se pudo cargar el paquete',
          );
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    load();
    return () => {
      cancelled = true;
    };
  }, [nonce]);

  const lines = (pkg?.lines || []).filter((ln) => {
    if (filter === 'asignado') return Boolean(ln.inbound_id);
    if (filter === 'sin') return !ln.inbound_id;
    return true;
  });

  const locked = pkg?.status === 'locked';

  const toggle = (id) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleAll = () => {
    if (selected.size === lines.length) {
      setSelected(new Set());
      return;
    }
    setSelected(new Set(lines.map((ln) => ln.id)));
  };

  const assign = async () => {
    if (!inboundId.trim() || selected.size === 0) return;
    setBusy(true);
    setMsg(null);
    setError(null);
    try {
      await api.post('/gestion-full/package/assign-inbound', {
        inbound_id: inboundId.trim(),
        line_ids: [...selected],
      });
      setMsg(`Asignado inbound ${inboundId.trim()} a ${selected.size} línea(s)`);
      setInboundId('');
      setNonce((n) => n + 1);
    } catch (err) {
      setError(err?.response?.data?.detail || 'No se pudo asignar inbound');
    } finally {
      setBusy(false);
    }
  };

  const removeSelected = async () => {
    if (selected.size === 0 || locked) return;
    setBusy(true);
    setMsg(null);
    setError(null);
    try {
      const count = selected.size;
      await api.post('/gestion-full/package/remove-lines', {
        line_ids: [...selected],
      });
      setMsg(`Quitadas ${count} línea(s) del envío`);
      setNonce((n) => n + 1);
    } catch (err) {
      setError(err?.response?.data?.detail || 'No se pudieron quitar las líneas del envío');
    } finally {
      setBusy(false);
    }
  };

  const clearInbounds = async () => {
    setBusy(true);
    setMsg(null);
    setError(null);
    try {
      await api.post('/gestion-full/package/clear-inbounds');
      setMsg('Inbound ids borrados');
      setNonce((n) => n + 1);
    } catch (err) {
      setError(err?.response?.data?.detail || 'No se pudo limpiar inbounds');
    } finally {
      setBusy(false);
    }
  };

  const exportFile = async (kind) => {
    setBusy(true);
    setMsg(null);
    setError(null);
    try {
      const path =
        kind === 'ml'
          ? '/gestion-full/package/export/ml'
          : '/gestion-full/package/export/ops';
      const filename =
        kind === 'ml' ? 'envio-stock-full-ml.xlsx' : 'envio-stock-full-ops.xlsx';
      await downloadBlob(path, filename);
      setMsg(`Descarga ${filename} lista`);
      setNonce((n) => n + 1);
    } catch (err) {
      setError(err?.message || `No se pudo exportar (${kind})`);
    } finally {
      setBusy(false);
    }
  };

  const addReadyFromList = async () => {
    setBusy(true);
    setMsg(null);
    setError(null);
    try {
      const { data } = await api.post('/gestion-full/package/lines/from-ready');
      if (!data.touched) {
        setError('No hay filas con Listo para agregar al paquete');
        return;
      }
      setMsg(`Agregadas/actualizadas ${data.touched} línea(s) al paquete`);
      setNonce((n) => n + 1);
    } catch (err) {
      setError(err?.response?.data?.detail || 'No se pudieron agregar líneas Listo al paquete');
    } finally {
      setBusy(false);
    }
  };

  const saveQtyExport = async (line) => {
    if (locked) return;
    const raw = qtyDraft[line.id];
    const next =
      raw === undefined || raw === '' ? line.qty_export : Number.parseInt(String(raw), 10);
    if (Number.isNaN(next) || next < 0) {
      setError('Qty export debe ser un entero ≥ 0');
      return;
    }
    if (next === line.qty_export) {
      setQtyDraft((prev) => {
        const copy = { ...prev };
        delete copy[line.id];
        return copy;
      });
      return;
    }
    setBusy(true);
    setMsg(null);
    setError(null);
    try {
      await api.patch(`/gestion-full/package/lines/${line.id}/qty-export`, {
        qty_export: next,
      });
      setMsg(`Qty export línea ${line.id} → ${next}`);
      setNonce((n) => n + 1);
    } catch (err) {
      setError(err?.response?.data?.detail || 'No se pudo guardar qty export');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={styles.depositos}>
      <div className={styles.filters}>
        <span className={styles.meta}>
          Paquete {pkg ? `#${pkg.id}` : '—'} · {pkg?.week_monday || '—'} · {pkg?.status || 'sin paquete'}
        </span>
        <label className={styles.filterField}>
          <span className={styles.filterLabel}>Filtro</span>
          <select
            className={styles.select}
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            aria-label="Filtro asignación"
          >
            <option value="todos">Todos</option>
            <option value="asignado">Asignados</option>
            <option value="sin">Sin asignar</option>
          </select>
        </label>
        <button type="button" className={styles.clearBtn} disabled={busy} onClick={addReadyFromList}>
          Sumar líneas Listo
        </button>
        <button type="button" className={styles.readyBtn} disabled={busy || !pkg} onClick={() => exportFile('ml')}>
          Excel ML
        </button>
        <button type="button" className={styles.readyBtn} disabled={busy || !pkg} onClick={() => exportFile('ops')}>
          Excel ops
        </button>
        <button type="button" className={styles.unlockBtn} disabled={busy || !pkg} onClick={clearInbounds}>
          Limpiar inbounds
        </button>
      </div>

      <div className={styles.filters}>
        <input
          className={styles.input}
          type="text"
          value={inboundId}
          onChange={(e) => setInboundId(e.target.value)}
          placeholder="inbound_id (SC)"
          aria-label="inbound_id"
          disabled={busy || locked}
        />
        <button
          type="button"
          className={styles.readyBtn}
          disabled={busy || selected.size === 0 || !inboundId.trim() || locked}
          onClick={assign}
        >
          Asignar a selección ({selected.size})
        </button>
        <button
          type="button"
          className={styles.unlockBtn}
          disabled={busy || selected.size === 0 || locked}
          onClick={removeSelected}
        >
          Quitar del envío ({selected.size})
        </button>
      </div>

      {error && <div className={styles.error}>{typeof error === 'string' ? error : JSON.stringify(error)}</div>}
      {msg && <div className={styles.meta}>{msg}</div>}
      {loading && <div className={styles.loading}>Cargando paquete…</div>}

      {!loading && pkg && (
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>
                  <input
                    type="checkbox"
                    checked={lines.length > 0 && selected.size === lines.length}
                    onChange={toggleAll}
                    aria-label="Seleccionar todas"
                    disabled={locked}
                  />
                </th>
                <th>Código ML</th>
                <th>MLAU</th>
                <th>Qty PM</th>
                <th>Qty export</th>
                <th>Inbound</th>
              </tr>
            </thead>
            <tbody>
              {lines.map((ln) => (
                <tr key={ln.id}>
                  <td>
                    <input
                      type="checkbox"
                      checked={selected.has(ln.id)}
                      onChange={() => toggle(ln.id)}
                      aria-label={`Seleccionar línea ${ln.id}`}
                      disabled={locked}
                    />
                  </td>
                  <td className={styles.mono}>{cell(ln.inventory_id)}</td>
                  <td className={styles.mono}>{cell(ln.user_product_id)}</td>
                  <td className={styles.num}>{cell(ln.qty_pm)}</td>
                  <td className={styles.num}>
                    {locked ? (
                      cell(ln.qty_export)
                    ) : (
                      <input
                        className={styles.input}
                        type="number"
                        min={0}
                        step={1}
                        value={qtyDraft[ln.id] ?? ln.qty_export}
                        onChange={(e) =>
                          setQtyDraft((prev) => ({ ...prev, [ln.id]: e.target.value }))
                        }
                        onBlur={() => saveQtyExport(ln)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') {
                            e.currentTarget.blur();
                          }
                        }}
                        aria-label={`Qty export línea ${ln.id}`}
                        disabled={busy}
                      />
                    )}
                  </td>
                  <td className={styles.mono}>{cell(ln.inbound_id)}</td>
                </tr>
              ))}
              {lines.length === 0 && (
                <tr>
                  <td colSpan={6} className={styles.empty}>
                    Sin líneas en este filtro
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
