import { useEffect, useState } from 'react';
import api from '../../services/api';
import styles from '../../pages/GestionFull.module.css';

function cell(value) {
  if (value === null || value === undefined || value === '') return '—';
  return value;
}

export default function GestionFullEnviosTab() {
  const [items, setItems] = useState([]);
  const [detail, setDetail] = useState(null);
  const [includeClosed, setIncludeClosed] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

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
    try {
      const { data } = await api.get(`/gestion-full/envios/${encodeURIComponent(inboundId)}`);
      setDetail(data);
    } catch {
      setError(`No se pudo cargar detalle ${inboundId}`);
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
