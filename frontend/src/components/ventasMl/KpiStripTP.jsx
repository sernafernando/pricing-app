import { AlertTriangle } from 'lucide-react';
import KpiStrip from './KpiStrip';
import { formatSignedMoney, markupTone, moneyTone } from '../../utils/ventasMlTone';
import styles from '../kit/KpiStrip.module.css';

/**
 * The KPI strip of a `tplink.solo` user (`tpMode.js`): the sale cards stay,
 * Total TP and Markup TP replace the Gauss ones, and the incomplete card
 * counts the sales without a usable Total TP. Loading, error and empty
 * states are the shared strip's own.
 */

const INT_FORMAT = new Intl.NumberFormat('es-AR');
const PCT_FORMAT = new Intl.NumberFormat('es-AR', { maximumFractionDigits: 1 });
const MONEY_FORMAT = new Intl.NumberFormat('es-AR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

const formatInt = (value) => INT_FORMAT.format(value || 0);

function formatOtherCurrencies(grossBilledOther) {
  const entries = Object.entries(grossBilledOther || {});
  if (entries.length === 0) return null;
  return entries.map(([currency, amount]) => `${MONEY_FORMAT.format(Number(amount))} ${currency}`).join(' · ');
}

export default function KpiStripTP({ kpi, loading, error }) {
  if (loading || error || !kpi) return <KpiStrip kpi={kpi} loading={loading} error={error} />;

  const otherCurrencies = formatOtherCurrencies(kpi.gross_billed_other);
  // Same arithmetic as the Gauss card: an unsettled order never reaches the
  // TP incomplete count (the backend skips it), so the four add up safely.
  const noUsableTpCount =
    (kpi.tp_incompleto_count || 0) + (kpi.recalculating_count || 0) + (kpi.pending_count || 0) + (kpi.failed_count || 0);
  const markup = kpi.markup_tp_weighted_pct;
  const markupKnown = markupTone(markup) !== null;
  const excludedNonMoneyCount = kpi.excluded_non_money_orders_count || 0;

  return (
    <div className={styles.strip} role="region" aria-label="Métricas principales">
      {!kpi.worker_alive && (
        <div className={styles.workerWarning}>
          <AlertTriangle size={14} aria-hidden="true" />
          Recálculo detenido: el worker de métricas no está corriendo. Estos totales pueden quedar desactualizados.
        </div>
      )}

      <div className={styles.cards}>
        <div className={styles.card}>
          <span className={styles.label}>Ventas</span>
          <div className={styles.value}>{formatInt(kpi.groups_count)}</div>
          <div className={styles.sub}>{formatInt(kpi.orders_count)} ventas individuales</div>
        </div>

        <div className={styles.card}>
          <span className={styles.label}>Facturado bruto</span>
          <div className={styles.value}>{formatSignedMoney(kpi.gross_billed_ars)}</div>
          <div className={styles.sub}>{otherCurrencies ? `Además: ${otherCurrencies}` : 'Total transaccionado'}</div>
        </div>

        <div className={styles.card}>
          <span className={styles.label}>Neto ML</span>
          <div className={`${styles.value} ${styles.valueHeadline}`}>{formatSignedMoney(kpi.neto_sum)}</div>
          <div className={styles.sub}>
            {kpi.neto_unknown_count > 0 ? `${formatInt(kpi.neto_unknown_count)} desconocidos` : 'Depositado por ML'}
          </div>
        </div>

        <div className={styles.card}>
          <span className={styles.label}>Total TP</span>
          <div className={`${styles.value} ${styles[`money_${moneyTone(kpi.total_tp_sum)}`] || ''}`.trim()}>
            {formatSignedMoney(kpi.total_tp_sum)}
          </div>
          <div className={styles.sub}>Al costo TP, sin las ventas incompletas</div>
        </div>

        <div className={styles.card}>
          <span className={styles.label}>Markup TP</span>
          <div className={styles.value} data-testid="markup-tp">
            {markupKnown ? (
              <span className={`${styles.markupChip} ${styles[`markup_${markupTone(markup)}`]}`}>
                {`${PCT_FORMAT.format(Number(markup))}%`}
              </span>
            ) : (
              '—'
            )}
          </div>
          <div className={styles.sub}>Ponderado por venta</div>
        </div>

        <div className={`${styles.card} ${styles.cardWarning}`}>
          <span className={styles.label}>
            TP incompleto
            <AlertTriangle size={14} aria-hidden="true" />
          </span>
          <div className={styles.value} data-testid="tp-incompleto-count">
            {formatInt(noUsableTpCount)}
          </div>
          <div className={styles.sub}>sin Total TP usable</div>
          <div className={styles.sub}>
            {`${formatInt(kpi.tp_incompleto_count)} incompletos · ${formatInt(kpi.recalculating_count)} recalculando · ${formatInt(
              kpi.pending_count,
            )} pendientes · ${formatInt(kpi.failed_count)} fallidos`}
          </div>
          <div className={styles.sub}>{`además, ${formatInt(kpi.neto_unknown_count)} sin neto`}</div>
        </div>

        {excludedNonMoneyCount > 0 && (
          <div className={`${styles.card} ${styles.cardWarning}`}>
            <span className={styles.label}>Ventas sin cobro efectivo</span>
            <div className={styles.value}>{formatSignedMoney(kpi.excluded_non_money_ars)}</div>
            <div className={styles.sub}>{`${formatInt(excludedNonMoneyCount)} ventas con pago rechazado o no completado`}</div>
            <div className={styles.sub}>excluidas de Facturado bruto: no es dinero cobrado</div>
          </div>
        )}
      </div>
    </div>
  );
}
