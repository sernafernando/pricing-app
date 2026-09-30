import { AlertTriangle } from 'lucide-react';
import styles from './KpiStrip.module.css';

/**
 * ventas-ml-kpi-strip T1-T3/T6: six totals cards over the CURRENT filtered
 * set (`GET /ml-ventas-ops/sales/kpis`), translating the Stitch mockup's
 * "KPI Metric Strip" layout/hierarchy (uppercase label, big mono number,
 * small secondary sub-line, warning-coloured 6th card) into this project's
 * CSS Modules + design tokens — see the module's own comment header, no
 * Tailwind classes exist on this project.
 *
 * HONESTY OF NUMBERS (task doc): nothing unresolved is ever rendered as a
 * bare zero, and `markup_weighted_pct` reads "—" rather than "0%" when the
 * backend sends `null` (K1: an order missing either side of the ratio
 * contributes to NEITHER side, per `markup_skipped_count`'s own doc).
 * `gross_billed_other` currencies NEVER get added into the ARS figure —
 * they are a different unit, not "more pesos".
 */

const INT_FORMAT = new Intl.NumberFormat('es-AR');
const MONEY_FORMAT = new Intl.NumberFormat('es-AR', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});
const PCT_FORMAT = new Intl.NumberFormat('es-AR', { maximumFractionDigits: 1 });

function formatMoneyARS(value) {
  if (value === null || value === undefined) return '—';
  return `$ ${MONEY_FORMAT.format(Number(value))}`;
}

function formatOtherCurrencies(grossBilledOther) {
  const entries = Object.entries(grossBilledOther || {});
  if (entries.length === 0) return null;
  return entries.map(([currency, amount]) => `${MONEY_FORMAT.format(Number(amount))} ${currency}`).join(' · ');
}

function formatPct(value) {
  if (value === null || value === undefined) return '—';
  return `${PCT_FORMAT.format(Number(value))}%`;
}

export default function KpiStrip({ kpi, loading, error }) {
  if (loading) {
    return (
      <div className={styles.strip} role="region" aria-label="Métricas principales">
        <div className={styles.stateCard}>Cargando métricas…</div>
      </div>
    );
  }

  if (error) {
    // The caller already classified this; rendering one message for all three
    // throws that away and makes a permissions problem look like an outage.
    const message =
      error === 'forbidden'
        ? 'No tenés permiso para ver las métricas de ventas.'
        : error === 'disabled'
          ? 'Las métricas de ventas están desactivadas.'
          : 'No se pudieron cargar las métricas.';
    return (
      <div className={styles.strip} role="region" aria-label="Métricas principales">
        <div className={styles.stateCard}>{message}</div>
      </div>
    );
  }

  if (!kpi) return null;

  const otherCurrencies = formatOtherCurrencies(kpi.gross_billed_other);

  // What this card is FOR: how many sales carry no usable Total Gauss.
  //
  // It first showed only the never-computed count, and production reported a
  // big fat `0` sitting on top of "21 sin Total Gauss" -- a true number
  // answering a question nobody asked. A sale that finished computing and came
  // back `unresolved` is just as unusable as one still in the queue.
  //
  // These four ARE safe to add: `metrics_state` assigns each order exactly one
  // of recalculating/pending/failed, and such an order never reaches
  // `aggregate.py`'s stored-row block at all (it `continue`s), so it cannot
  // also be counted in `total_gauss_unresolved_count`.
  const noUsableGaussCount =
    (kpi.total_gauss_unresolved_count || 0) +
    (kpi.recalculating_count || 0) +
    (kpi.pending_count || 0) +
    (kpi.failed_count || 0);

  // NOT added into the figure above. `aggregate.py` increments
  // `neto_unknown_count` from the SAME stored row that may also be
  // `unresolved`, so one order missing both is counted once in each. Since an
  // unresolved Gauss usually means an unknown neto too, folding it in would
  // roughly DOUBLE the count -- on the one screen built so the totals stop
  // lying. There is no per-order data here to de-duplicate them, so it stays
  // on its own line.
  const netoUnknown = kpi.neto_unknown_count || 0;

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
          <div className={styles.value}>{INT_FORMAT.format(kpi.groups_count ?? 0)}</div>
          <div className={styles.sub}>{INT_FORMAT.format(kpi.orders_count ?? 0)} ventas individuales</div>
        </div>

        <div className={styles.card}>
          <span className={styles.label}>Facturado bruto</span>
          <div className={styles.value}>{formatMoneyARS(kpi.gross_billed_ars)}</div>
          <div className={styles.sub}>
            {otherCurrencies ? `Además: ${otherCurrencies}` : 'Total transaccionado'}
          </div>
        </div>

        <div className={styles.card}>
          <span className={styles.label}>Neto ML</span>
          <div className={styles.value}>{formatMoneyARS(kpi.neto_sum)}</div>
          <div className={styles.sub}>
            {kpi.neto_unknown_count > 0 ? `${INT_FORMAT.format(kpi.neto_unknown_count)} desconocidos` : 'Depositado por ML'}
          </div>
        </div>

        <div className={styles.card}>
          <span className={styles.label}>Total Gauss</span>
          <div className={styles.value}>{formatMoneyARS(kpi.total_gauss_sum)}</div>
          <div className={styles.sub}>
            {kpi.total_gauss_provisional_count > 0
              ? `${INT_FORMAT.format(kpi.total_gauss_provisional_count)} provisorios`
              : 'Costos + comisiones aplicadas'}
          </div>
        </div>

        <div className={styles.card}>
          <span className={styles.label}>Markup promedio</span>
          <div className={styles.value}>{formatPct(kpi.markup_weighted_pct)}</div>
          <div className={styles.sub}>
            {kpi.markup_skipped_count > 0
              ? `${INT_FORMAT.format(kpi.markup_skipped_count)} sin datos para calcular`
              : 'Ponderado por venta'}
          </div>
        </div>

        <div className={`${styles.card} ${styles.cardWarning}`}>
          <span className={styles.label}>Desglose incompleto</span>
          <div className={styles.value}>{INT_FORMAT.format(noUsableGaussCount)}</div>
          <div className={styles.sub}>sin Total Gauss usable</div>
          <div className={styles.sub}>
            {`${INT_FORMAT.format(kpi.total_gauss_unresolved_count || 0)} sin resolver · ${INT_FORMAT.format(
              kpi.recalculating_count || 0
            )} recalculando · ${INT_FORMAT.format(kpi.pending_count || 0)} pendientes · ${INT_FORMAT.format(
              kpi.failed_count || 0
            )} fallidos`}
          </div>
          {/* Apart, never folded in: this one can describe the SAME order as
              `sin resolver` above, so adding it would count that order twice. */}
          <div className={styles.sub}>{`además, ${INT_FORMAT.format(netoUnknown)} sin neto`}</div>
        </div>
      </div>
    </div>
  );
}
