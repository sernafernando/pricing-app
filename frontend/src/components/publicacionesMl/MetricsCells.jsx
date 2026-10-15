import Sparkline from '../kit/Sparkline';
import { formatSignedMoney, markupTone, moneyTone } from '../../utils/ventasMlTone';
import { ageingTone, deltaTone, formatAgeing, formatLastSale, formatPct, formatUnits, weeklySums } from '../../utils/metricasMlFormat';
import styles from './MetricsCells.module.css';

/**
 * Cells of a publication's Métricas ML figures (`row.metrics`: the Board's
 * own publication row over the last 30 days, computed by the server) and of
 * its stock. They render exactly as the Métricas board renders the same
 * figures -- same formats, same tones, same sparklines -- so the two screens
 * read the same. A publication Métricas has no row for reads "—"; so do the
 * money and the real markup of one that did not sell in the 30 days.
 */
const Empty = () => <span className={styles.muted}>—</span>;

const soldIn30d = (metrics) => Number(metrics?.units_30d ?? 0) > 0;

/** Units sold in a window (`units_7d` / `units_30d`); a counted zero is 0, an unknown "—". */
export function UnitsCell({ value, strong = false }) {
  return (
    <span className={`${styles.units} ${strong ? styles.strong : ''} ${value ? '' : styles.muted}`}>{formatUnits(value)}</span>
  );
}

/** Weekly units over the 90 days, toned by the last week against the one before (Métricas' `units_trend`). */
export function UnitsTrendCell({ metrics }) {
  if (!metrics) return <Empty />;
  const weeks = weeklySums(metrics.series_units_90d ?? []);
  const tone = weeks.length > 1 ? deltaTone(weeks.at(-1) - weeks.at(-2)) : null;
  return <Sparkline values={weeks} width={96} height={28} tone={tone} label="Unidades por semana, 90 días" />;
}

/** The real (sales-weighted) markup of the 30 days (`ml_metricas.ver_ganancia`). */
export function MarkupRealCell({ metrics }) {
  if (!soldIn30d(metrics) || metrics.markup_30d == null) return <Empty />;
  return (
    <span className={styles.markup} data-tone={markupTone(metrics.markup_30d)}>
      {formatPct(metrics.markup_30d)}
    </span>
  );
}

/** Daily markup over the 90 days, toned by the change against the previous 30 days (Métricas' `markup_trend`). */
export function MarkupTrendCell({ metrics }) {
  if (!metrics?.series_markup_90d) return <Empty />;
  return (
    <Sparkline
      values={metrics.series_markup_90d}
      width={120}
      height={32}
      tone={deltaTone(metrics.markup_delta_pp)}
      label="Markup diario, 90 días"
    />
  );
}

function Money({ value, strong = false }) {
  return (
    <span className={`${styles.money} ${strong ? styles.strong : ''}`} data-tone={moneyTone(value)} data-money>
      {formatSignedMoney(value)}
    </span>
  );
}

/** Gross revenue of the 30 days. */
export function GrossCell({ metrics }) {
  return soldIn30d(metrics) ? <Money value={metrics.gross_30d} /> : <Empty />;
}

/** Total Gauss of the 30 days (`ml_metricas.ver_ganancia`). */
export function TotalGaussCell({ metrics }) {
  return soldIn30d(metrics) && metrics.total_gauss_30d != null ? <Money value={metrics.total_gauss_30d} strong /> : <Empty />;
}

/** The last sale ever and how long ago, in business days. */
export function LastSaleCell({ metrics, now = new Date() }) {
  if (!metrics) return <Empty />;
  const { when, ago } = formatLastSale(metrics.last_sale_at, now);
  return (
    <div className={styles.lastSale}>
      <span className={styles.when}>{when}</span>
      <span className={styles.ago}>{ago}</span>
    </div>
  );
}

/** Days since the last sale (or the publication's start), as Métricas' chip. */
export function AgeingCell({ metrics }) {
  if (metrics?.ageing_days == null) return <Empty />;
  return (
    <span className={styles.ageing} data-tone={ageingTone(metrics.ageing_days)}>
      {formatAgeing(metrics.ageing_days)}
    </span>
  );
}

/** One stock figure of its own source: unknown is "—", a real zero (or less) is shown and flagged. */
function StockQuantity({ value }) {
  if (value == null) return <Empty />;
  const out = value <= 0;
  return (
    <span className={`${styles.units} ${out ? styles.outOfStock : ''}`} data-out={out ? '' : undefined}>
      {formatUnits(value)}
    </span>
  );
}

/** Our own warehouse stock at ML (`stock.own`), never added to Full. */
export function OwnStockCell({ stock }) {
  return <StockQuantity value={stock?.own ?? null} />;
}

/** The Full stock (`stock.full`), never added to our own. */
export function FullStockCell({ stock }) {
  return <StockQuantity value={stock?.full ?? null} />;
}
