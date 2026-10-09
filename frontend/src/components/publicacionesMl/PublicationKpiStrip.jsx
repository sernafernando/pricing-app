import { AlertTriangle, Boxes, Hourglass, PieChart, ReceiptText, ShoppingBag, Wallet } from 'lucide-react';
import { SegmentedControl } from '../kit';
import Sparkline from '../kit/Sparkline';
import { formatSignedMoney, markupTone, moneyTone } from '../../utils/ventasMlTone';
import { deltaTone, formatDeltaPct, formatDeltaPp, formatPct, formatUnits } from '../../utils/metricasMlFormat';
import styles from './PublicationKpiStrip.module.css';

/**
 * The strip over the filtered publications (publicaciones-ml-vista P12b): the same figures as Métricas ML's
 * ticker, for a period of its own. Total Gauss and markup are rendered only when the backend sent them
 * (`ver_ganancia`). A failed request is an error INSIDE the strip; the table below is not its business.
 */
export const PERIOD_OPTIONS = [7, 15, 30, 60, 90].map((days) => ({ value: days, label: `${days} días` }));

function Delta({ value, format }) {
  const tone = deltaTone(value);
  return tone ? (
    <span className={styles.delta} data-tone={tone}>
      {format(value)}
    </span>
  ) : null;
}

function Tile({ label, icon, value, valueClass = '', delta, series, tone, children }) {
  const Icon = icon;
  return (
    <div className={styles.card}>
      <div className={styles.label}>
        <span>{label}</span>
        <Icon size={14} aria-hidden="true" />
      </div>
      <div className={styles.valueRow}>
        <span className={`${styles.value} ${valueClass}`} data-kpi-value>{value}</span>
        {delta}
      </div>
      {series ? <Sparkline values={series} width={200} height={22} tone={tone} className={styles.spark} label={`${label} por día`} /> : children}
    </div>
  );
}

const pctOf = (part, whole) => (whole ? (part / whole) * 100 : null);

function Tiles({ kpis }) {
  const { units, gross, total_gauss: gauss, markup, rows_with_sales: withSales, ageing } = kpis;
  const activePct = pctOf(withSales.value, withSales.of_total);
  return (
    <div className={styles.cards}>
      <Tile
        label="Unidades vendidas"
        icon={ShoppingBag}
        value={formatUnits(units.value)}
        delta={<Delta value={units.delta_pct} format={formatDeltaPct} />}
        series={units.series}
        tone={deltaTone(units.delta_pct)}
      />
      <Tile
        label="Facturado bruto"
        icon={ReceiptText}
        value={formatSignedMoney(gross.value)}
        delta={<Delta value={gross.delta_pct} format={formatDeltaPct} />}
        series={gross.series}
        tone={deltaTone(gross.delta_pct)}
      />
      {gauss && (
        <Tile
          label="Total Gauss"
          icon={Wallet}
          value={formatSignedMoney(gauss.value)}
          valueClass={styles[`money_${moneyTone(gauss.value)}`]}
          delta={<Delta value={gauss.delta_pct} format={formatDeltaPct} />}
          series={gauss.series}
          tone={deltaTone(gauss.delta_pct)}
        />
      )}
      {markup && (
        <Tile
          label="Markup promedio"
          icon={PieChart}
          value={formatPct(markup.value)}
          valueClass={styles[`markup_${markupTone(markup.value)}`]}
          delta={<Delta value={markup.delta_pp} format={formatDeltaPp} />}
          series={markup.series}
          tone={deltaTone(markup.delta_pp)}
        />
      )}
      <Tile
        label="Publicaciones con ventas"
        icon={Boxes}
        value={`${formatUnits(withSales.value)} / ${formatUnits(withSales.of_total)}`}
        delta={activePct === null ? null : <span className={styles.note}>{formatPct(activePct)} activo</span>}
      >
        <div className={styles.bar} aria-hidden="true">
          <span className={styles.barFill} style={{ width: `${activePct ?? 0}%` }} />
        </div>
      </Tile>
      <Tile
        label="Ageing promedio"
        icon={Hourglass}
        value={ageing.avg_days === null ? '—' : `${formatUnits(Math.round(ageing.avg_days))} días`}
        delta={
          ageing.over_60 > 0 ? (
            <span className={styles.warn}>
              <AlertTriangle size={12} aria-hidden="true" />
              {formatUnits(ageing.over_60)} pub &gt; 60d
            </span>
          ) : null
        }
      />
    </div>
  );
}

function errorMessage(error) {
  const status = error?.response?.status;
  if (status === 503) return 'Los KPIs tardaron demasiado. Probá con filtros más acotados o reintentá.';
  if (status === 403) return 'No tenés permiso para ver los KPIs.';
  return 'No se pudieron cargar los KPIs.';
}

export default function PublicationKpiStrip({ state, periodo, onPeriodChange, markupNotice }) {
  const { data, loading, error } = state;
  return (
    <section className={styles.strip} aria-label="Indicadores de las publicaciones" aria-busy={loading}>
      <div className={styles.toolbar}>
        <SegmentedControl label="Período" options={PERIOD_OPTIONS} value={periodo} onChange={onPeriodChange} />
        {markupNotice && (
          <span className={styles.notice} role="note">
            <AlertTriangle size={14} aria-hidden="true" />
            Los KPIs no aplican el filtro de markup
          </span>
        )}
      </div>
      {error && (
        <div className={styles.error} role="alert">
          <span>{errorMessage(error)}</span>
          <button type="button" className="btn-tesla outline sm" onClick={state.reload}>
            Reintentar KPIs
          </button>
        </div>
      )}
      {!error && data && <Tiles kpis={data.kpis} />}
      {!error && !data && <div className={styles.cards} />}
    </section>
  );
}
