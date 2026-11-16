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
    throw new Error(await messageFromBlobError(err, 'No se pudo exportar'));
  }
}

export default function GestionFullEnviosTab({ puedeGestor = false }) {
  const [items, setItems] = useState([]);
  const [detail, setDetail] = useState(null);
  const [includeClosed, setIncludeClosed] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      setError(null);
      try {
        const { data } = await api.get('/gestion-full/envios', {
          params: { include_closed: includeClosed },
        });
        if (!cancelled) setItems(data || []);
      } catch {
        if (!cancelled) setError('No se pudieron cargar envíos');
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    load();
    return () => {
      cancelled = true;
    };
  }, [includeClosed]);

  const openDetail = async (inboundId) => {
    setError(null);
    setMsg(null);
    try {
      const { data } = await api.get(`/gestion-full/envios/${encodeURIComponent(inboundId)}`);
      setDetail(data);
    } catch {
      setError(`No se pudo cargar detalle ${inboundId}`);
    }
  };

  const exportOps = async () => {
    if (!detail?.inbound_id) return;
    setBusy(true);
    setError(null);
    setMsg(null);
    const inbound = detail.inbound_id;
    const safe = String(inbound).replace(/[^a-zA-Z0-9_-]/g, '_').slice(0, 48) || 'inbound';
    try {
      await downloadBlob(
        `/gestion-full/envios/${encodeURIComponent(inbound)}/export/ops`,
        `envio-stock-full-ops-${safe}.xlsx`,
      );
      setMsg(`Descarga ops de ${detail.human_id || inbound} lista`);
    } catch (err) {
      setError(err?.message || 'No se pudo exportar Excel ops');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={styles.depositos}>
      <div className={styles.filters}>
        <label className={styles.check}>
          <input
            type="checkbox"
            checked={includeClosed}
            onChange={(e) => setIncludeClosed(e.target.checked)}
          />
          Incluir recepción cerrada
        </label>
        <span className={styles.meta}>{items.length} envíos</span>
      </div>

      {error && <div className={styles.error}>{error}</div>}
      {msg && <div className={styles.meta}>{msg}</div>}
      {loading && <div className={styles.loading}>Cargando envíos…</div>}

      {!loading && (
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Human id</th>
                <th>Inbound</th>
                <th>Semana</th>
                <th>Última recepción</th>
                <th>Cerrado</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {items.map((row) => (
                <tr key={row.inbound_id}>
                  <td className={styles.mono}>{cell(row.human_id)}</td>
                  <td className={styles.mono}>{cell(row.inbound_id)}</td>
                  <td className={styles.mono}>{cell(row.week_monday)}</td>
                  <td className={styles.mono}>{cell(row.last_reception_at)}</td>
                  <td>{row.reception_closed ? 'Sí' : 'No'}</td>
                  <td>
                    <button
                      type="button"
                      className={styles.readyBtn}
                      onClick={() => openDetail(row.inbound_id)}
                    >
                      Detalle
                    </button>
                  </td>
                </tr>
              ))}
              {items.length === 0 && (
                <tr>
                  <td colSpan={6} className={styles.empty}>
                    Sin envíos locales
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {detail && (
        <div className={styles.tableWrap}>
          <h2 className={styles.subtitle}>
            Detalle {detail.human_id}{' '}
            <button type="button" className={styles.clearBtn} onClick={() => setDetail(null)}>
              Cerrar
            </button>
            {puedeGestor ? (
              <button
                type="button"
                className={styles.readyBtn}
                disabled={busy}
                onClick={exportOps}
              >
                Excel ops
              </button>
            ) : null}
          </h2>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Código ML</th>
                <th>MLAU</th>
                <th>Declarado</th>
                <th>Recibido</th>
                <th>Diff</th>
              </tr>
            </thead>
            <tbody>
              {(detail.lines || []).map((ln) => (
                <tr key={ln.inventory_id}>
                  <td className={styles.mono}>{cell(ln.inventory_id)}</td>
                  <td className={styles.mono}>{cell(ln.user_product_id)}</td>
                  <td className={styles.num}>{cell(ln.declared)}</td>
                  <td className={styles.num}>{cell(ln.received)}</td>
                  <td className={styles.num}>{cell(ln.diff)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
