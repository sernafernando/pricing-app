import { Fragment } from 'react';
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
import { deltaTone, formatDeltaPct, formatDeltaPp, formatPct, formatRatio, formatUnits } from '../../utils/metricasMlFormat';
import { originalAmount } from '../../utils/metricasMlAds';
import { TP_MARKUP_HINT, tpCellState, tpIncompleteTitle } from '../../utils/metricasMlTp';
import { sellOutEstimatedTitle, sellOutPendingTitle } from '../../utils/metricasMlSell';
import { COSTO_LABELS, formatPorTipo } from '../../utils/metricasMlCanal';
import { metricasKpiOptions, nounOf } from './metricasKpiOptions';
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

/** canal=todo: one figure per channel under the card's total (`kpis.por_canal`, mockup 1). */
function Split({ lines }) {
  return (
    <div className={styles.split}>
      {lines.map(([label, value]) => (
        <div key={label} className={styles.splitLine} data-split>
          <span>{label}</span>
          <strong data-money>{value}</strong>
        </div>
      ))}
    </div>
  );
}

/** A labelled figure on one line ("con Costo: $ X"), kept whole like "Ticket promedio". */
function FigureLine({ label, children }) {
  return (
    <span className={`${styles.subtitle} ${styles.sellLine}`}>
      <span>{label}</span>{' '}
      <span className={styles.sellValue}>
        <strong data-money>{children}</strong>
      </span>
    </span>
  );
}

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

/** A figure WITH the sell out added to the profit ("c/ SO", Costo SI T3 D1), under the same figure without it. */
function WithSellInOut({ children, pendientes = 0, estimados = 0 }) {
  return (
    // The figure (and its flags) wraps as a whole under the label in a narrow card, never mid-amount.
    <span className={`${styles.subtitle} ${styles.sellLine}`} data-testid="kpi-sell-in-out">
      <span>C/ SO:</span>{' '}
      <span className={styles.sellValue}>
        <strong data-money>{children}</strong>
        {(pendientes > 0 || estimados > 0) && (
          <span className={styles.sellFlags}>
            <SellOutFlags pendientes={pendientes} estimados={estimados} />
          </span>
        )}
      </span>
    </span>
  );
}

/** One figure of the sell out card; a figure that does not apply (null) leaves no line at all. */
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

/** The period's sell out and the cost it is added over (sell-in-sell-out T20, Costo SI T3 D1: the cost is costo SI,
 * no sell in): only while some sale in the period has a sell out. */
function SellInOutCard({ sell }) {
  return (
    <Card label="Sell out" icon={ArrowLeftRight}>
      <div className={styles.sellFigures}>
        <SellFigure label="Sell out" value={sell.sell_out} testId="kpi-sell-out" pendientes={sell.sell_out_pendientes} estimados={sell.sell_out_estimados} />
        <SellFigure label="Costo" value={sell.costo} testId="kpi-costo" />
      </div>
    </Card>
  );
}

/** `tpSolo`: a `tplink.solo` user's board, which has no Total Gauss (the key is absent) and carries Markup TP.
 * `isVisible(id)` leaves out the cards the viewer hid; with none left there is no row at all. */
/**
 * `canal` (vpf-metricas-canal-fe): `todo` splits units, gross, Total Gauss and markup into ML and Por fuera
 * (`kpis.por_canal`); `fuera` reads the PDF's documents, the Venta with VAT (S10), the other cost (`costo` is the
 * chosen one) and the sin producto lines (`kpis.fuera`). Neither draws the daily sparklines (approved mockups).
 */
export default function MetricasKpiStrip({
  kpis,
  canSeeMargin,
  groupBy,
  loading,
  tpSolo = false,
  isVisible = () => true,
  canal = 'ml',
  costo = 'costo_d',
}) {
  if (!kpis) return <div className={styles.cards} aria-busy={loading} />;
  const noun = nounOf(groupBy);
  // The ageing buckets count PRODUCTS (or publications) even in the grouped view.
  const short = groupBy === 'publication' ? 'pub' : 'prod';
  const { units, gross, total_gauss: tg, markup, rows_with_sales: withSales, ageing, ads } = kpis;
  // Operations (audit B1a): packs or lone orders with a sale; no profit permission needed.
  const { operations, ticket, units_per_sale: perSale } = kpis;
  // `kpis.total_tp` exists only while the board shows the TP costs (and only with the profit view).
  const tp = canSeeMargin ? (kpis.total_tp ?? null) : null;
  // `kpis.sell_in_out` exists only with the profit view (never for `tplink.solo`).
  const sell = canSeeMargin ? (kpis.sell_in_out ?? null) : null;
  const ageingTotal = ageing.up_to_30 + ageing.from_31_to_60 + ageing.over_60;
  const activePct = pctOf(withSales.value, withSales.of_total);
  const todo = canal === 'todo';
  const fuera = canal === 'fuera' ? (kpis.fuera ?? null) : null;
  const porCanal = todo ? (kpis.por_canal ?? null) : null;
  const sparks = canal === 'ml';
  const costoLabel = COSTO_LABELS[costo] ?? COSTO_LABELS.costo_d;
  const otro = fuera?.otro_costo ?? null;
  const otroLabel = `con ${COSTO_LABELS[otro?.costo] ?? ''}:`;
  const sinProducto = fuera?.sin_producto ?? null;

  const cards = {
    units: () => (
      <Card label="Unidades vendidas" icon={ShoppingBag}>
        <div className={styles.valueRow}>
          <span className={styles.value} data-kpi-value>
            {formatUnits(units.value)}
          </span>
          <DeltaChip value={units.delta_pct} format={formatDeltaPct} />
        </div>
        {porCanal && (
          <Split
            lines={[
              ['ML', formatUnits(porCanal.ml?.units)],
              ['Por fuera', formatUnits(porCanal.fuera?.units)],
            ]}
          />
        )}
        {fuera && (
          <>
            <span className={styles.subtitle}>{formatUnits(fuera.comprobantes)} comprobantes</span>
            {fuera.por_tipo?.length > 0 && <span className={styles.subtitle}>{formatPorTipo(fuera.por_tipo)}</span>}
          </>
        )}
        {operations && !fuera && (
          <span className={styles.subtitle}>
            {formatUnits(operations.value)} operaciones{perSale?.value != null && ` · ${formatRatio(perSale.value)} por venta`}
          </span>
        )}
        {sparks && <Sparkline values={units.series} width={200} height={22} tone={deltaTone(units.delta_pct)} className={styles.spark} label="Unidades por día" />}
      </Card>
    ),
    gross: () => (
      <Card label={fuera ? 'Facturado' : 'Facturado bruto'} icon={ReceiptText}>
        <div className={styles.valueRow}>
          <span className={styles.value} data-money data-kpi-value>{formatSignedMoney(gross.value)}</span>
          <DeltaChip value={gross.delta_pct} format={formatDeltaPct} />
        </div>
        {porCanal && (
          <Split
            lines={[
              ['ML', formatSignedMoney(porCanal.ml?.gross)],
              ['Por fuera', formatSignedMoney(porCanal.fuera?.gross)],
            ]}
          />
        )}
        {/* The Venta of the PDF carries VAT, like ML's (L17 / S10); the cheque surcharge never enters it. */}
        {fuera && <span className={styles.subtitle}>con IVA · sin recargo cheque</span>}
        {ticket && !porCanal && (
          // Same line layout as "C/ SO": label, then the amount kept whole on one line.
          <span className={`${styles.subtitle} ${styles.sellLine}`}>
            <span>Ticket promedio:</span>{' '}
            <span className={styles.sellValue}>
              <strong data-money>{ticket.value == null ? '—' : formatSignedMoney(ticket.value)}</strong>
            </span>
          </span>
        )}
        {sparks && <Sparkline values={gross.series} width={200} height={22} tone={deltaTone(gross.delta_pct)} className={styles.spark} label="Facturado por día" />}
      </Card>
    ),
    total_gauss: () => (
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
            {porCanal && (
              <>
                <Split
                  lines={[
                    ['ML', formatSignedMoney(porCanal.ml?.margin)],
                    ['Por fuera', formatSignedMoney(porCanal.fuera?.margin)],
                  ]}
                />
                <span className={styles.subtitle}>ML neto de comisión y envío</span>
              </>
            )}
            {fuera && (
              <>
                <span className={styles.subtitle}>venta − {costoLabel}</span>
                {otro?.margin != null && <FigureLine label={otroLabel}>{formatSignedMoney(otro.margin)}</FigureLine>}
              </>
            )}
            {sell && sell.total_gauss != null && <WithSellInOut pendientes={sell.sell_out_pendientes} estimados={sell.sell_out_estimados}>{formatSignedMoney(sell.total_gauss)}</WithSellInOut>}
            {sparks && <Sparkline values={tg.series} width={200} height={22} tone={deltaTone(tg.delta_pct)} className={styles.spark} label="Total Gauss por día" />}
          </>
        ) : (
          <span className={styles.locked}>Sin permiso para ver ganancia</span>
        )}
      </Card>
    ),
    total_tp: () => <TotalTpCard tp={tp} />,
    markup: () => (
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
            {porCanal && (
              <Split
                lines={[
                  ['ML', formatPct(porCanal.ml?.markup_pct)],
                  [`Por fuera (${costoLabel})`, formatPct(porCanal.fuera?.markup_pct)],
                ]}
              />
            )}
            {fuera && (
              <>
                <span className={styles.subtitle}>con {costoLabel}</span>
                {otro?.markup_pct != null && <FigureLine label={otroLabel}>{formatPct(otro.markup_pct)}</FigureLine>}
              </>
            )}
            {sell && sell.total_gauss != null && <WithSellInOut>{formatPct(sell.markup_pct)}</WithSellInOut>}
            {sparks && <Sparkline values={markup.series} width={200} height={22} tone={deltaTone(markup.delta_pp)} className={styles.spark} label="Markup por día" />}
          </>
        ) : (
          <span className={styles.locked}>Sin permiso para ver ganancia</span>
        )}
      </Card>
    ),
    sell_in_out: () => <SellInOutCard sell={sell} />,
    rows_with_sales: () => (
      <Card label={`${noun} con ventas`} icon={Boxes}>
        <div className={styles.valueRow}>
          <span className={styles.value} data-kpi-value>
            {formatUnits(withSales.value)} <span className={styles.of}>/ {formatUnits(withSales.of_total)}</span>
          </span>
          {activePct !== null && <span className={styles.note}>{formatPct(activePct)} activo</span>}
        </div>
        {sinProducto?.lineas > 0 && (
          <FigureLine label={`+ ${formatUnits(sinProducto.lineas)} líneas sin producto:`}>{formatSignedMoney(sinProducto.monto)}</FigureLine>
        )}
        <div className={styles.bar} aria-hidden="true">
          <span className={styles.barFill} style={{ width: `${activePct ?? 0}%` }} />
        </div>
      </Card>
    ),
    ageing: () => (
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
    ),
  };
  // The ads block is not a card of this row (`AdsKpiBlock`); the page asks `isVisible('ads')` itself.
  const shown = metricasKpiOptions(kpis, { canSeeMargin, groupBy, tpSolo }).filter(({ id }) => cards[id] && isVisible(id));
  if (shown.length === 0) return null;

  return (
    <section
      className={styles.cards}
      aria-label="Indicadores del período"
      aria-busy={loading}
      data-canal={canal === 'ml' ? undefined : canal}
      style={{ '--kpi-count': shown.length }}
    >
      {shown.map(({ id }) => (
        <Fragment key={id}>{cards[id]()}</Fragment>
      ))}
    </section>
  );
}
