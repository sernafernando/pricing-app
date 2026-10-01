import CopyButton from './CopyButton';
import styles from './SaleDetailPanel.module.css';
import { MODO_LOGISTICO_LABELS, formatDay, paymentMethodLabel } from '../../utils/ventasMlFormat';

function formatMoney(value) {
  return `$ ${new Intl.NumberFormat('es-AR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(Number(value))}`;
}

function hasValue(value) {
  return value !== null && value !== undefined && value !== '';
}

function Row({ label, children }) {
  return (
    <div className={styles.contextRow}>
      <dt>{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

/**
 * Comprador / Pago / Envío of the sale panel (Stitch `detalle`). Everything
 * comes from the order detail response; a field we do not have is left out,
 * never printed as a blank or a zero. Out of scope on purpose: CUIT, card
 * brand/last 4 (ML does not send them), invoice.
 */
export default function SaleContextSections({ order, shipment }) {
  if (!order) return null;

  const fullName = [order.buyer_first_name, order.buyer_last_name].filter(Boolean).join(' ');
  const where = shipment ? [shipment.city, shipment.province].filter(Boolean).join(', ') : '';
  const method = paymentMethodLabel(order.payment_method_id);
  const installments = Number(order.installments) > 1 ? `${order.installments} cuotas` : null;
  const coupon = Number(order.coupon_amount);

  return (
    <div className={styles.contextGrid}>
      <section className={styles.contextCard} aria-label="Comprador">
        <h3 className={styles.contextTitle}>Comprador</h3>
        {order.buyer_nickname && <p className={styles.buyerNick}>{order.buyer_nickname}</p>}
        {fullName && <p className={styles.contextText}>{fullName}</p>}
        {where && <p className={styles.contextMuted}>{where}</p>}
      </section>

      <section className={styles.contextCard} aria-label="Pago">
        <h3 className={styles.contextTitle}>Pago</h3>
        <dl className={styles.contextList}>
          {(method || installments) && (
            <Row label="Método">{[method, installments].filter(Boolean).join(' · ')}</Row>
          )}
          {order.payment_date_approved && <Row label="Aprobación">{formatDay(order.payment_date_approved)}</Row>}
          {hasValue(order.paid_amount) && <Row label="Total pagado">{formatMoney(order.paid_amount)}</Row>}
          {coupon > 0 && <Row label="Cupón ML">{formatMoney(coupon)}</Row>}
        </dl>
      </section>

      {shipment && (
        <section className={styles.contextCard} aria-label="Envío">
          <h3 className={styles.contextTitle}>Envío</h3>
          <dl className={styles.contextList}>
            {shipment.modo_logistico && (
              <Row label="Modo">{MODO_LOGISTICO_LABELS[shipment.modo_logistico] || shipment.modo_logistico}</Row>
            )}
            {(shipment.substatus || shipment.status) && (
              <Row label="Estado">{shipment.substatus || shipment.status}</Row>
            )}
            {shipment.tracking_number && (
              <Row label="Seguimiento">
                <span className={styles.mono}>{shipment.tracking_number}</span>
                <CopyButton value={shipment.tracking_number} label="Copiar número de seguimiento" />
              </Row>
            )}
            {shipment.estimated_delivery && (
              <Row label="Llega">{formatDay(shipment.estimated_delivery)}</Row>
            )}
          </dl>
        </section>
      )}
    </div>
  );
}
