import { useEffect, useMemo, useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import api from '../../services/api';
import { MODO_LOGISTICO_LABELS } from '../../utils/ventasMlFormat';
import { formatSignedMoney } from '../../utils/ventasMlTone';
import { formatPct, formatUnits } from '../../utils/metricasMlFormat';
import styles from './MetricasEnviosPanel.module.css';

const URL = '/ml-metricas/board/envios';

/**
 * "Por tipo de envío" (audit B8): the period's sales split by each sale's shipping type, under the board's
 * filters. Closed by default and read only once opened, so the board never pays for it. An ML type with no label
 * shows verbatim, like Ventas ML.
 */
export default function MetricasEnviosPanel({ params }) {
  const [open, setOpen] = useState(false);
  const [state, setState] = useState({ rows: null, error: false });
  // Read again when the filters change, not when the page hands over an equal object.
  const key = JSON.stringify(params);
  const request = useMemo(() => JSON.parse(key), [key]);

  useEffect(() => {
    if (!open) return undefined;
    let current = true;
    setState({ rows: null, error: false });
    api
      .get(URL, { params: request })
      .then(({ data }) => current && setState({ rows: data.rows, error: false }))
      .catch(() => current && setState({ rows: null, error: true }));
    return () => {
      current = false;
    };
  }, [open, request]);

  const total = (state.rows ?? []).reduce((sum, row) => sum + row.gross, 0);

  return (
    <section className={styles.panel} aria-label="Por tipo de envío">
      <button type="button" className={styles.toggle} aria-expanded={open} onClick={() => setOpen(!open)}>
        {open ? <ChevronDown size={16} aria-hidden="true" /> : <ChevronRight size={16} aria-hidden="true" />}
        Por tipo de envío
      </button>
      {open && state.error && <p className={styles.note}>No se pudo cargar el desglose por tipo de envío</p>}
      {open && !state.error && state.rows === null && <p className={styles.note}>Cargando…</p>}
      {open && state.rows?.length === 0 && <p className={styles.note}>Sin ventas en el período</p>}
      {open && state.rows?.length > 0 && (
        <table className={styles.table}>
          <thead>
            <tr>
              <th scope="col">Tipo de envío</th>
              <th scope="col" className={styles.num}>Facturado</th>
              <th scope="col" className={styles.num}>% del facturado</th>
              <th scope="col" className={styles.num}>Operaciones</th>
              <th scope="col" className={styles.num}>Unidades</th>
            </tr>
          </thead>
          <tbody>
            {state.rows.map((row) => (
              <tr key={row.modo}>
                <th scope="row">{MODO_LOGISTICO_LABELS[row.modo] ?? row.modo}</th>
                <td className={styles.num} data-money>{formatSignedMoney(row.gross)}</td>
                <td className={styles.num}>{formatPct(total ? (row.gross / total) * 100 : null)}</td>
                <td className={styles.num}>{formatUnits(row.operations)}</td>
                <td className={styles.num}>{formatUnits(row.units)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
