import { useEffect, useState } from 'react';
import api from '../../services/api';
import styles from '../../pages/GestionFull.module.css';

function cell(value) {
  if (value === null || value === undefined || value === '') return '—';
  return value;
}

async function downloadBlob(path, filename) {
  const { data } = await api.get(path, { responseType: 'blob' });
  const url = URL.createObjectURL(data);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
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
      setError(err?.response?.data?.detail || `No se pudo exportar (${kind})`);
    } finally {
      setBusy(false);
    }
  };

  const addReadyFromList = async () => {
    setBusy(true);
    setMsg(null);
    setError(null);
    try {
      const { data } = await api.get('/gestion-full', {
        params: { full_mode: 'todos', include_zero_stock: true, limit: 500, offset: 0 },
      });
      const ready = (data.items || []).filter((r) => r.pm_ready);
      if (ready.length === 0) {
        setError('No hay filas con Listo para agregar al paquete');
        return;
      }
      let added = 0;
      for (const row of ready) {
        try {
          await api.post('/gestion-full/package/lines', {
            producto_item_id: row.producto_item_id,
            user_product_id: row.user_product_id,
          });
          added += 1;
        } catch {
          // skip rows that already fail (e.g. duplicate / not ready race)
        }
      }
      setMsg(`Agregadas/actualizadas ${added} línea(s) al paquete`);
      setNonce((n) => n + 1);
    } catch {
      setError('No se pudieron agregar líneas Listo al paquete');
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
          disabled={busy || pkg?.status === 'locked'}
        />
        <button
          type="button"
          className={styles.readyBtn}
          disabled={busy || selected.size === 0 || !inboundId.trim() || pkg?.status === 'locked'}
          onClick={assign}
        >
          Asignar a selección ({selected.size})
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
                    disabled={pkg.status === 'locked'}
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
                      disabled={pkg.status === 'locked'}
                    />
                  </td>
                  <td className={styles.mono}>{cell(ln.inventory_id)}</td>
                  <td className={styles.mono}>{cell(ln.user_product_id)}</td>
                  <td className={styles.num}>{cell(ln.qty_pm)}</td>
                  <td className={styles.num}>{cell(ln.qty_export)}</td>
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
