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
      <div className={styles.strip} aria-label="Métricas principales">
        <div className={styles.stateCard}>Cargando métricas…</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className={styles.strip} aria-label="Métricas principales">
        <div className={styles.stateCard}>No se pudieron cargar las métricas.</div>
      </div>
    );
  }

  if (!kpi) return null;

  const otherCurrencies = formatOtherCurrencies(kpi.gross_billed_other);

  // T2: the "unresolved" figure is a COUNT of what could not be settled,
  // never invented as a subtraction from a total — each of these fields
  // already means "not resolved yet" on its own, so summing them is safe
  // and nothing here is double-counted against a resolved amount.
  const incompleteCount =
    (kpi.neto_unknown_count || 0) +
    (kpi.total_gauss_unresolved_count || 0) +
    (kpi.recalculating_count || 0) +
    (kpi.pending_count || 0) +
    (kpi.failed_count || 0);

  return (
    <div className={styles.strip} aria-label="Métricas principales">
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
          <div className={styles.value}>{INT_FORMAT.format(incompleteCount)}</div>
          <div className={styles.sub}>
            {`${INT_FORMAT.format(kpi.neto_unknown_count || 0)} neto desconocido · ${INT_FORMAT.format(
              kpi.total_gauss_unresolved_count || 0
            )} total sin resolver · ${INT_FORMAT.format(kpi.recalculating_count || 0)} recalculando · ${INT_FORMAT.format(
              kpi.pending_count || 0
            )} pendientes · ${INT_FORMAT.format(kpi.failed_count || 0)} fallidos`}
          </div>
        </div>
      </div>
    </div>
  );
}
