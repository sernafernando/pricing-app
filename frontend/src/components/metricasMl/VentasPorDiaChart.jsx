import { Calendar } from 'lucide-react';
import { formatMoney } from '../../utils/formatMoney';
import styles from './VentasPorDiaChart.module.css';

const DIAS = 14;
// Por fuera shows the whole period, a month at most (approved mockup 2).
const DIAS_FUERA = 31;
const MILLONES = new Intl.NumberFormat('es-AR', { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const millones = (valor) => MILLONES.format(valor / 1_000_000);
// The amount over a bar, in whole pesos so it fits the bar's width; the tooltip keeps the cents.
const montoCorto = (valor) => Math.round(valor).toLocaleString('es-AR', { maximumFractionDigits: 0 });

// `YYYY-MM-DD` + n days as `dd/mm`, on the calendar (no time zone can shift the day).
function fechaCorta(desde, n) {
  const [y, m, d] = desde.split('-').map(Number);
  const dia = new Date(Date.UTC(y, m - 1, d + n));
  return `${String(dia.getUTCDate()).padStart(2, '0')}/${String(dia.getUTCMonth() + 1).padStart(2, '0')}`;
}

// `YYYY-MM-DD` + n days as the day of the month, `dd`.
const diaDelMes = (desde, n) => fechaCorta(desde, n).slice(0, 2);

/** canal=todo: the last 14 days, ML under Por fuera in one bar, the day's total over it (mockup 1). */
function ApiladoPorCanal({ period, porCanal }) {
  const ml = porCanal.ml ?? [];
  const fuera = porCanal.fuera ?? [];
  const largo = Math.max(ml.length, fuera.length);
  const inicio = Math.max(0, largo - DIAS);
  const dias = Array.from({ length: largo - inicio }, (_, i) => {
    const deMl = Number(ml[inicio + i]) || 0;
    const deFuera = Number(fuera[inicio + i]) || 0;
    return { fecha: fechaCorta(period.date_from, inicio + i), ml: deMl, fuera: deFuera, total: deMl + deFuera };
  });
  const max = Math.max(...dias.map((d) => d.total));
  return (
    <Marco subtitulo={`Últimos ${dias.length} días del período`} leyenda="canal">
      {dias.map((d) => {
        const detalle = `${formatMoney(d.total)} - ML ${formatMoney(d.ml)} · Por fuera ${formatMoney(d.fuera)}`;
        return (
          <li key={d.fecha} className={styles.day} title={detalle} aria-label={`${d.fecha}: ${detalle}`}>
            <span className={styles.track}>
              <span className={`${styles.value} ${styles.valueShown}`}>{d.total > 0 ? `${millones(d.total)} M` : ''}</span>
              <span className={styles.stack} style={{ height: `${max > 0 ? (d.total / max) * 100 : 0}%` }}>
                <span className={styles.segment} data-canal="fuera" style={{ flexGrow: d.fuera }} />
                <span className={styles.segment} data-canal="ml" style={{ flexGrow: d.ml }} />
              </span>
            </span>
            <span className={styles.date}>{d.fecha}</span>
          </li>
        );
      })}
    </Marco>
  );
}

/** canal=fuera: every day of the period (a month at most) in millions, the highest and lowest day marked; a day
 * without sales has no bar nor amount (mockup 2). */
function PorFuera({ period, montos, vendedor }) {
  const inicio = Math.max(0, montos.length - DIAS_FUERA);
  const dias = montos.slice(inicio).map((monto, i) => ({
    fecha: fechaCorta(period.date_from, inicio + i),
    dia: diaDelMes(period.date_from, inicio + i),
    monto: Number(monto) || 0,
  }));
  const conVentas = dias.map((d) => d.monto).filter((monto) => monto > 0);
  const max = Math.max(0, ...conVentas);
  const min = Math.min(...conVentas);
  const hayExtremos = conVentas.length > 1 && max !== min;
  const subtitulo = [`Últimos ${dias.length} días del período`, vendedor, 'millones'].filter(Boolean).join(' · ');
  return (
    <Marco subtitulo={subtitulo} leyenda={hayExtremos ? 'extremos' : null}>
      {dias.map((d) => {
        const vacio = d.monto <= 0;
        const extremo = !hayExtremos || vacio ? undefined : d.monto === max ? 'max' : d.monto === min ? 'min' : undefined;
        const detalle = formatMoney(d.monto);
        return (
          <li
            key={d.fecha}
            className={styles.day}
            data-extremo={extremo}
            data-vacio={vacio ? '' : undefined}
            title={detalle}
            aria-label={`${d.fecha}: ${detalle}`}
          >
            <span className={styles.track}>
              {!vacio && <span className={`${styles.value} ${styles.valueShown}`}>{millones(d.monto)}</span>}
              <span className={styles.bar} style={{ height: `${max > 0 && !vacio ? (d.monto / max) * 100 : 0}%` }} />
            </span>
            <span className={styles.date}>{d.dia}</span>
          </li>
        );
      })}
    </Marco>
  );
}

function Marco({ subtitulo, leyenda, children }) {
  return (
    <section className={styles.card} aria-labelledby="ventas-por-dia-titulo">
      <header className={styles.header}>
        <h2 id="ventas-por-dia-titulo" className={styles.title}>
          <Calendar size={16} aria-hidden="true" />
          Ventas por día
        </h2>
        <span className={styles.subtitle}>{subtitulo}</span>
        {leyenda === 'extremos' && (
          <span className={styles.legend}>
            <span className={styles.legendItem} data-extremo="max">Día más alto</span>
            <span className={styles.legendItem} data-extremo="min">Día más bajo</span>
          </span>
        )}
        {leyenda === 'canal' && (
          <span className={styles.legend} data-testid="ventas-por-dia-leyenda">
            <span className={`${styles.legendItem} ${styles.legendSquare}`} data-canal="ml">ML</span>
            <span className={`${styles.legendItem} ${styles.legendSquare}`} data-canal="fuera">Por fuera</span>
          </span>
        )}
      </header>
      <ol className={styles.bars} aria-label="Ventas por día">
        {children}
      </ol>
    </section>
  );
}

/**
 * "Ventas por día", as the old Métricas ML dashboard had it: the last 14 days of the period as bars of the gross
 * amount, the highest day green and the lowest red with their amounts always shown, the date and the operations
 * under each bar, and "$X - N ops" on hover. Same filters as the board: it reads the board's daily series
 * (`kpis.gross.series`, `kpis.operations.series`), one entry per day from `period.date_from`.
 *
 * `canal` (vpf-metricas-canal-fe): `todo` stacks ML and Por fuera (`kpis.gross.series_por_canal`), `fuera` shows
 * the whole period in millions; ML is the chart it always was.
 */
export default function VentasPorDiaChart({ period, kpis, canal = 'ml', vendedor = null }) {
  const montos = kpis?.gross?.series ?? [];
  if (!period?.date_from || montos.length === 0) return null;
  const porCanal = kpis?.gross?.series_por_canal;
  if (canal === 'todo' && porCanal) return <ApiladoPorCanal period={period} porCanal={porCanal} />;
  if (canal === 'fuera') return <PorFuera period={period} montos={montos} vendedor={vendedor} />;
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
