import { formatUnits } from '../../../utils/metricasMlFormat';
import styles from './StockAudit.module.css';

/**
 * The Auditoría de stock KPIs (auditoria-stock S7, approved mock v2), over every row of the filtered audit, not the
 * page: stock value ERP / Full / Total (USD big, ARS under it; Total in the accent), units, products with stock and
 * no active publication (count and value), products with stock with / without an applied promotion. Each card can
 * be hidden (`isVisible`, the page's "Indicadores" picker).
 */
const MONEY = new Intl.NumberFormat('es-AR', { maximumFractionDigits: 0 });
const usd = (value) => (value == null ? '—' : `USD ${MONEY.format(value)}`);
const ars = (value) => (value == null ? '—' : `$ ${MONEY.format(value)}`);
const count = (value) => (value == null ? '—' : formatUnits(value));

function ValueCard({ label, money, accent = false }) {
  return (
    <div className={`${styles.card} ${accent ? styles.cardAccent : ''}`}>
      <span className={styles.label}>{label}</span>
      <span className={styles.bigValue}>{usd(money.usd)}</span>
      <span className={styles.subValue}>{ars(money.ars)}</span>
    </div>
  );
}

function ListCard({ label, lines }) {
  return (
    <div className={styles.card}>
      <span className={styles.label}>{label}</span>
      <dl className={styles.list}>
        {lines.map(([name, value, total]) => (
          <div key={name} className={`${styles.listLine} ${total ? styles.listTotal : ''}`}>
            <dt>{name}</dt>
            <dd>{count(value)}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

export default function StockAuditKpis({ audit, isVisible }) {
  const { data, error, reload } = audit;
  if (error) {
    return (
      <div className={styles.error} role="alert">
        <span>No se pudo cargar la auditoría de stock.</span>
        <button type="button" className="btn-tesla outline sm" onClick={reload}>
          Reintentar
        </button>
      </div>
    );
  }
  if (!data) return null;
  const { kpis } = data;
  const sinActiva = kpis.valor_sin_publicacion_activa ?? {};
  const top = [
    isVisible('valor_erp') && <ValueCard key="valor_erp" label="Valor stock ERP" money={kpis.erp} />,
    isVisible('valor_full') && <ValueCard key="valor_full" label="Valor stock Full" money={kpis.full} />,
    isVisible('valor_total') && <ValueCard key="valor_total" label="Valor stock total" money={kpis.total} accent />,
  ].filter(Boolean);
  const bottom = [
    isVisible('unidades') && (
      <ListCard
        key="unidades"
        label="Unidades"
        lines={[
          ['ERP', kpis.erp.unidades],
          ['Full', kpis.full.unidades],
          ['Total', kpis.total.unidades, true],
        ]}
      />
    ),
    isVisible('sin_publicacion_activa') && (
      <div key="sin_publicacion_activa" className={styles.card}>
        <span className={styles.label}>Con stock sin publicación activa</span>
        <span className={styles.countLine}>
          <span className={styles.bigValue}>{count(kpis.productos_sin_publicacion_activa)}</span>
          <span className={styles.countUnit}>productos</span>
        </span>
        <span className={styles.subValue}>
          {usd(sinActiva.usd)} · {ars(sinActiva.ars)}
        </span>
      </div>
    ),
    isVisible('promo') && (
      <ListCard
        key="promo"
        label="Productos con stock"
        lines={[
          ['Con promo aplicada', kpis.productos_con_promo_aplicada],
          ['Sin promo aplicada', kpis.productos_sin_promo_aplicada],
          ['Total', kpis.productos, true],
        ]}
      />
    ),
  ].filter(Boolean);
  if (top.length === 0 && bottom.length === 0) return null;
  return (
    <section className={styles.kpis} aria-label="Indicadores de la auditoría de stock">
      {top.length > 0 && <div className={styles.kpiRow}>{top}</div>}
      {bottom.length > 0 && <div className={styles.kpiRow}>{bottom}</div>}
    </section>
  );
}
