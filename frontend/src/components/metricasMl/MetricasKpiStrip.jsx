import {
  AlertTriangle,
  ArrowLeftRight,
  Boxes,
  Coins,
  Hourglass,
  PieChart,
  ReceiptText,
  ShoppingBag,
  Wallet,
} from 'lucide-react';
import Sparkline from './Sparkline';
import { formatSignedMoney, markupTone, moneyTone } from '../../utils/ventasMlTone';
import { deltaTone, formatDeltaPct, formatDeltaPp, formatPct, formatUnits } from '../../utils/metricasMlFormat';
import { originalAmount } from '../../utils/metricasMlAds';
import { TP_MARKUP_HINT, tpCellState, tpIncompleteTitle } from '../../utils/metricasMlTp';
import { sellOutEstimatedTitle, sellOutPendingTitle } from '../../utils/metricasMlSell';
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

/** Marks a figure the ads were subtracted from, and shows what it was before. */
function Adjusted({ original }) {
  return (
    <>
      <span className={styles.adjusted}>Ajustado</span>
      {original !== null && original !== undefined && (
        <span className={styles.original}>
          Original: <s data-money>{formatSignedMoney(original)}</s>
        </span>
      )}
    </>
  );
}

const pctOf = (part, whole) => (whole ? (part / whole) * 100 : null);

/** "Costos TP" on: the known Total TP of the TP store group's operations, never 0 when unknown, and how many
 * of their lines lack a TP cost. */
function TotalTpCard({ tp }) {
  const { known, incompletos, kind } = tpCellState(tp.value, tp.incompletos);
  return (
    <Card label="Total TP" icon={Coins}>
      <div className={styles.valueRow}>
        <span
          className={`${styles.value} ${known ? styles[`money_${moneyTone(tp.value)}`] || '' : styles.unknown}`}
          data-money
          data-kpi-value
        >
          {known ? formatSignedMoney(tp.value) : '—'}
        </span>
        {kind === 'incomplete' && <span className={styles.unknownHint}>incompleto</span>}
      </div>
      <div className={styles.adjustedRow}>
        {incompletos > 0 ? (
          <span className={styles.warn} title={tpIncompleteTitle(incompletos)}>
            <AlertTriangle size={12} aria-hidden="true" />
            {formatUnits(incompletos)} sin costo TP
          </span>
        ) : (
          <span className={styles.subtitle}>{kind === 'none' ? 'Sin ventas de la tienda TP-Link' : 'Tienda TP-Link'}</span>
        )}
      </div>
    </Card>
  );
}

/** The sell out's caveats next to a figure that adds it: the sales left out for want of a rate, and the ones
 * added on a rate that is still an estimate ("≈ n", like the rows). */
function SellOutFlags({ pendientes = 0, estimados = 0 }) {
  return (
    <>
      {pendientes > 0 && (
        <span className={styles.warn} title={sellOutPendingTitle(pendientes)}>
          <AlertTriangle size={12} aria-hidden="true" />
          {formatUnits(pendientes)}
        </span>
      )}
      {estimados > 0 && (
        <span className={styles.estimatedHint} title={sellOutEstimatedTitle(estimados)}>
          ≈ {formatUnits(estimados)}
        </span>
      )}
    </>
  );
}

/** A figure WITH sell in / sell out, under the same figure without them (sell-in-sell-out T11). */
function WithSellInOut({ children, pendientes = 0, estimados = 0 }) {
  return (
    // The figure (and its flags) wraps as a whole under the label in a narrow card, never mid-amount.
    <span className={`${styles.subtitle} ${styles.sellLine}`} data-testid="kpi-sell-in-out">
      <span>C/ sell in/out:</span>{' '}
      <span className={styles.sellValue}>
        <strong data-money>{children}</strong>
        <SellOutFlags pendientes={pendientes} estimados={estimados} />
      </span>
    </span>
  );
}

/** One figure of the sell in / sell out card; a figure that does not apply (null) leaves no line at all. */
function SellFigure({ label, value, testId, pendientes = 0, estimados = 0 }) {
  if (value == null) return null;
  return (
    <div className={styles.sellFigure} data-testid={testId}>
      <span className={styles.subtitle}>{label}</span>
      <span className={styles.sellValue}>
        <strong data-money>{formatSignedMoney(value)}</strong>
        <SellOutFlags pendientes={pendientes} estimados={estimados} />
      </span>
    </div>
  );
}

/** The period's sell in and sell out, and the cost without and with sell in (sell-in-sell-out T20): only while
 * some sale in the period has a sell in or a sell out. */
function SellInOutCard({ sell }) {
  return (
    <Card label="Sell in / Sell out" icon={ArrowLeftRight}>
      <div className={styles.sellFigures}>
        <SellFigure label="Sell in" value={sell.sell_in} testId="kpi-sell-in" />
        <SellFigure label="Sell out" value={sell.sell_out} testId="kpi-sell-out" pendientes={sell.sell_out_pendientes} estimados={sell.sell_out_estimados} />
        <SellFigure label="Costo" value={sell.costo} testId="kpi-costo" />
        <SellFigure label="Costo c/ sell in" value={sell.costo_sell_in} testId="kpi-costo-sell-in" />
      </div>
    </Card>
  );
}

/** `tpSolo`: a `tplink.solo` user's board, which has no Total Gauss (the key is absent) and carries Markup TP. */
export default function MetricasKpiStrip({ kpis, canSeeMargin, groupBy, loading, tpSolo = false }) {
  if (!kpis) return <div className={styles.cards} aria-busy={loading} />;
  const noun = { publication: 'Publicaciones', group: 'Grupos' }[groupBy] ?? 'Productos';
  // The ageing buckets count PRODUCTS (or publications) even in the grouped view.
  const short = groupBy === 'publication' ? 'pub' : 'prod';
  const { units, gross, total_gauss: tg, markup, rows_with_sales: withSales, ageing, ads } = kpis;
  // `kpis.total_tp` exists only while the board shows the TP costs (and only with the profit view).
  const tp = canSeeMargin ? (kpis.total_tp ?? null) : null;
  // `kpis.sell_in_out` exists only with the profit view (never for `tplink.solo`).
  const sell = canSeeMargin ? (kpis.sell_in_out ?? null) : null;
  const sellCard = sell && (sell.sell_in != null || sell.sell_out != null || sell.costo_sell_in != null);
  const ageingTotal = ageing.up_to_30 + ageing.from_31_to_60 + ageing.over_60;
  const activePct = pctOf(withSales.value, withSales.of_total);

  return (
    <section className={styles.cards} aria-label="Indicadores del período" aria-busy={loading} data-tp={tp ? '' : undefined} data-sell={sellCard ? '' : undefined}>
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

      {!tpSolo && (
        <Card label="Total Gauss" icon={Wallet}>
          {canSeeMargin ? (
            <>
              <div className={styles.valueRow}>
                <span className={`${styles.value} ${styles[`money_${moneyTone(tg.value)}`] || ''}`} data-money data-kpi-value>
                  {formatSignedMoney(tg.value)}
                </span>
                <DeltaChip value={tg.delta_pct} format={formatDeltaPct} />
              </div>
              {ads && (
                <div className={styles.adjustedRow}>
                  <Adjusted original={originalAmount(tg.value, ads.subtracted_total)} />
                </div>
              )}
              {sell && sell.total_gauss != null && <WithSellInOut pendientes={sell.sell_out_pendientes} estimados={sell.sell_out_estimados}>{formatSignedMoney(sell.total_gauss)}</WithSellInOut>}
              <Sparkline values={tg.series} width={200} height={22} tone={deltaTone(tg.delta_pct)} className={styles.spark} label="Total Gauss por día" />
            </>
          ) : (
            <span className={styles.locked}>Sin permiso para ver ganancia</span>
          )}
        </Card>
      )}

      {tp && <TotalTpCard tp={tp} />}

      <Card label={tpSolo ? 'Markup TP' : 'Markup promedio'} icon={PieChart}>
        {canSeeMargin ? (
          <>
            <div className={styles.valueRow}>
              <span className={`${styles.value} ${styles[`markup_${markupTone(markup.value)}`] || ''}`} data-kpi-value>
                {formatPct(markup.value)}
              </span>
              <DeltaChip value={markup.delta_pp} format={formatDeltaPp} />
            </div>
            {ads && (
              <div className={styles.adjustedRow}>
                <Adjusted />
              </div>
            )}
            {tp && <span className={styles.subtitle}>{TP_MARKUP_HINT}</span>}
            {sell && sell.total_gauss != null && <WithSellInOut>{formatPct(sell.markup_pct)}</WithSellInOut>}
            <Sparkline values={markup.series} width={200} height={22} tone={deltaTone(markup.delta_pp)} className={styles.spark} label="Markup por día" />
          </>
        ) : (
          <span className={styles.locked}>Sin permiso para ver ganancia</span>
        )}
      </Card>

      {sellCard && <SellInOutCard sell={sell} />}

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
