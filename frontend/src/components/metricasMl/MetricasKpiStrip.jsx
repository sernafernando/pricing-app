import {
  AlertTriangle,
  Boxes,
  Hourglass,
  PieChart,
  ReceiptText,
  ShoppingBag,
  Wallet,
} from 'lucide-react';
import Sparkline from './Sparkline';
import { formatSignedMoney, markupTone, moneyTone } from '../../utils/ventasMlTone';
import { deltaTone, formatDeltaPct, formatDeltaPp, formatPct, formatUnits } from '../../utils/metricasMlFormat';
import styles from './MetricasKpiStrip.module.css';

/**
 * The board's six "ticker" cards (tablero.png): units, gross, Total Gauss,
 * markup, rows with sales and ageing -- each with its change against the
 * comparison period and a sparkline of the period, all over the WHOLE
 * filtered set (never the page). Without the margin permission the two
 * margin cards say so instead of showing a number.
 */
function DeltaChip({ value, format }) {
  const tone = deltaTone(value);
  if (!tone) return null;
  return (
    <span className={styles.delta} data-tone={tone}>
      {format(value)}
    </span>
  );
}

function Card({ label, icon, children }) {
  const Icon = icon;
  return (
    <div className={styles.card}>
      <div className={styles.label}>
        <span>{label}</span>
        <Icon size={14} aria-hidden="true" />
      </div>
      {children}
    </div>
  );
}

const pctOf = (part, whole) => (whole ? (part / whole) * 100 : null);

export default function MetricasKpiStrip({ kpis, canSeeMargin, groupBy, loading }) {
  if (!kpis) return <div className={styles.cards} aria-busy={loading} />;
  const noun = { publication: 'Publicaciones', group: 'Grupos' }[groupBy] ?? 'Productos';
  // The ageing buckets count PRODUCTS (or publications) even in the grouped view.
  const short = groupBy === 'publication' ? 'pub' : 'prod';
  const { units, gross, total_gauss: tg, markup, rows_with_sales: withSales, ageing } = kpis;
  const ageingTotal = ageing.up_to_30 + ageing.from_31_to_60 + ageing.over_60;
  const activePct = pctOf(withSales.value, withSales.of_total);

  return (
    <section className={styles.cards} aria-label="Indicadores del período" aria-busy={loading}>
      <Card label="Unidades vendidas" icon={ShoppingBag}>
        <div className={styles.valueRow}>
          <span className={styles.value} data-kpi-value>
            {formatUnits(units.value)}
          </span>
          <DeltaChip value={units.delta_pct} format={formatDeltaPct} />
        </div>
        <Sparkline values={units.series} width={200} height={22} tone={deltaTone(units.delta_pct)} className={styles.spark} label="Unidades por día" />
      </Card>

      <Card label="Facturado bruto" icon={ReceiptText}>
        <div className={styles.valueRow}>
          <span className={styles.value} data-money data-kpi-value>{formatSignedMoney(gross.value)}</span>
          <DeltaChip value={gross.delta_pct} format={formatDeltaPct} />
        </div>
        <Sparkline values={gross.series} width={200} height={22} tone={deltaTone(gross.delta_pct)} className={styles.spark} label="Facturado por día" />
      </Card>

      <Card label="Total Gauss" icon={Wallet}>
        {canSeeMargin ? (
          <>
            <div className={styles.valueRow}>
              <span className={`${styles.value} ${styles[`money_${moneyTone(tg.value)}`] || ''}`} data-money data-kpi-value>
                {formatSignedMoney(tg.value)}
              </span>
              <DeltaChip value={tg.delta_pct} format={formatDeltaPct} />
            </div>
            <Sparkline values={tg.series} width={200} height={22} tone={deltaTone(tg.delta_pct)} className={styles.spark} label="Total Gauss por día" />
          </>
        ) : (
          <span className={styles.locked}>Sin permiso para ver ganancia</span>
        )}
      </Card>

      <Card label="Markup promedio" icon={PieChart}>
        {canSeeMargin ? (
          <>
            <div className={styles.valueRow}>
              <span className={`${styles.value} ${styles[`markup_${markupTone(markup.value)}`] || ''}`} data-kpi-value>
                {formatPct(markup.value)}
              </span>
              <DeltaChip value={markup.delta_pp} format={formatDeltaPp} />
            </div>
            <Sparkline values={markup.series} width={200} height={22} tone={deltaTone(markup.delta_pp)} className={styles.spark} label="Markup por día" />
          </>
        ) : (
          <span className={styles.locked}>Sin permiso para ver ganancia</span>
        )}
      </Card>

      <Card label={`${noun} con ventas`} icon={Boxes}>
        <div className={styles.valueRow}>
          <span className={styles.value} data-kpi-value>
            {formatUnits(withSales.value)} <span className={styles.of}>/ {formatUnits(withSales.of_total)}</span>
          </span>
          {activePct !== null && <span className={styles.note}>{formatPct(activePct)} activo</span>}
        </div>
        <div className={styles.bar} aria-hidden="true">
          <span className={styles.barFill} style={{ width: `${activePct ?? 0}%` }} />
        </div>
      </Card>

      <Card label="Ageing promedio" icon={Hourglass}>
        <div className={styles.valueRow}>
          <span className={styles.value} data-kpi-value>
            {ageing.avg_days === null ? '—' : `${formatUnits(Math.round(ageing.avg_days))} días`}
          </span>
          {ageing.over_60 > 0 && (
            <span className={styles.warn}>
              <AlertTriangle size={12} aria-hidden="true" />
              {formatUnits(ageing.over_60)} {short} &gt; 60d
            </span>
          )}
        </div>
        <div className={styles.bar} aria-hidden="true">
          {ageingTotal > 0 && (
            <>
              <span className={styles.segGood} style={{ width: `${pctOf(ageing.up_to_30, ageingTotal)}%` }} />
              <span className={styles.segLow} style={{ width: `${pctOf(ageing.from_31_to_60, ageingTotal)}%` }} />
              <span className={styles.segBad} style={{ width: `${pctOf(ageing.over_60, ageingTotal)}%` }} />
            </>
          )}
        </div>
      </Card>
    </section>
  );
}
