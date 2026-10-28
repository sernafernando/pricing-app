import { Calendar } from 'lucide-react';
import { formatMoney } from '../../utils/formatMoney';
import styles from './VentasPorDiaChart.module.css';

const DIAS = 14;
// The amount over a bar, in whole pesos so it fits the bar's width; the tooltip keeps the cents.
const montoCorto = (valor) => Math.round(valor).toLocaleString('es-AR', { maximumFractionDigits: 0 });

// `YYYY-MM-DD` + n days as `dd/mm`, on the calendar (no time zone can shift the day).
function fechaCorta(desde, n) {
  const [y, m, d] = desde.split('-').map(Number);
  const dia = new Date(Date.UTC(y, m - 1, d + n));
  return `${String(dia.getUTCDate()).padStart(2, '0')}/${String(dia.getUTCMonth() + 1).padStart(2, '0')}`;
}

/**
 * "Ventas por día", as the old Métricas ML dashboard had it: the last 14 days of the period as bars of the gross
 * amount, the highest day green and the lowest red with their amounts always shown, the date and the operations
 * under each bar, and "$X - N ops" on hover. Same filters as the board: it reads the board's daily series
 * (`kpis.gross.series`, `kpis.operations.series`), one entry per day from `period.date_from`.
 */
export default function VentasPorDiaChart({ period, kpis }) {
  const montos = kpis?.gross?.series ?? [];
  if (!period?.date_from || montos.length === 0) return null;
  const operaciones = kpis?.operations?.series;
  const inicio = Math.max(0, montos.length - DIAS);
  const dias = montos.slice(inicio).map((monto, i) => ({
    fecha: fechaCorta(period.date_from, inicio + i),
    monto: Number(monto) || 0,
    ops: operaciones ? operaciones[inicio + i] : null,
  }));
  const valores = dias.map((d) => d.monto);
  const max = Math.max(...valores);
  const min = Math.min(...valores);
  const hayExtremos = max !== min;

  return (
    <section className={styles.card} aria-labelledby="ventas-por-dia-titulo">
      <header className={styles.header}>
        <h2 id="ventas-por-dia-titulo" className={styles.title}>
          <Calendar size={16} aria-hidden="true" />
          Ventas por día
        </h2>
        <span className={styles.subtitle}>Últimos {dias.length} días del período</span>
        {hayExtremos && (
          <span className={styles.legend}>
            <span className={styles.legendItem} data-extremo="max">Día más alto</span>
            <span className={styles.legendItem} data-extremo="min">Día más bajo</span>
          </span>
        )}
      </header>
      <ol className={styles.bars} aria-label="Ventas por día">
        {dias.map((d) => {
          const extremo = !hayExtremos ? undefined : d.monto === max ? 'max' : d.monto === min ? 'min' : undefined;
          const conOps = d.ops !== null && d.ops !== undefined;
          const detalle = `${formatMoney(d.monto)}${conOps ? ` - ${d.ops} ops` : ''}`;
          return (
            <li
              key={d.fecha}
              className={styles.day}
              data-extremo={extremo}
              title={detalle}
              aria-label={`${d.fecha}: ${detalle}`}
            >
              <span className={styles.track}>
                <span className={styles.value}>{montoCorto(d.monto)}</span>
                <span className={styles.bar} style={{ height: `${max > 0 ? (d.monto / max) * 100 : 0}%` }} />
              </span>
              <span className={styles.date}>{d.fecha}</span>
              {conOps && <span className={styles.ops}>{d.ops} ops</span>}
            </li>
          );
        })}
      </ol>
    </section>
  );
}
