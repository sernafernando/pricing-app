import { Package } from 'lucide-react';
import CopyButton from './CopyButton';
import StatusPill from './StatusPill';
import styles from './SaleDetailPanel.module.css';
import { MODO_LOGISTICO_LABELS, formatDay, paymentMethodLabel } from '../../utils/ventasMlFormat';
import { MODO_LOGISTICO_TONE, formatSignedMoney, shipmentDotTone, shippingStatusLabel } from '../../utils/ventasMlTone';

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
 * Producto card (Stitch `detalle`): one block per item of the order, with
 * its SKU, publication, quantity and unit price. From the detail response's
 * own `items`; absent fields are left out, never printed blank.
 */
export function ProductSection({ items }) {
  const list = items || [];
  if (list.length === 0) return null;
  return (
    <section className={styles.card} aria-label="Producto">
      <h3 className={styles.cardTitle}>Producto{list.length > 1 ? 's' : ''}</h3>
      {list.map((item, index) => (
        <div key={`${index}-${item.item_id}-${item.variation_id ?? ''}`} className={styles.productBlock}>
          <div className={styles.productThumb} aria-hidden="true">
            <Package size={20} />
          </div>
          <div className={styles.productInfo}>
            <p className={styles.productTitle}>{item.title || item.item_id}</p>
            <dl className={styles.contextList}>
              {item.seller_sku && (
                <Row label="SKU">
                  <span className={styles.skuChip}>{item.seller_sku}</span>
                </Row>
              )}
              {item.item_id && (
                <Row label="Publicación">
                  <span className={styles.mono}>{item.item_id}</span>
                  <CopyButton value={item.item_id} label="Copiar publicación" compact />
                </Row>
              )}
              {hasValue(item.quantity) && <Row label="Cantidad">{item.quantity}</Row>}
              {hasValue(item.unit_price) && (
                <Row label="Precio unitario">
                  <span className={styles.figure}>{formatSignedMoney(item.unit_price)}</span>
                </Row>
              )}
            </dl>
          </div>
        </div>
      ))}
    </section>
  );
}

/**
 * Comprador | Envío side by side, then Pago (Stitch `detalle`). Everything
 * comes from the order detail response; a field we do not have is left out,
 * never printed as a blank or a zero. Out of scope on purpose: CUIT, card
 * brand/last 4 (ML does not send them), invoice.
 *
 * Envío leads with the ML shipping id -- the identifier an operator pastes
 * into ML -- copyable. The carrier's tracking number is still shown, small,
 * but it is no longer the shipment's identity on this panel.
 */
export default function SaleContextSections({ order, shipment }) {
  if (!order) return null;

  const fullName = [order.buyer_first_name, order.buyer_last_name].filter(Boolean).join(' ');
  const where = shipment ? [shipment.city, shipment.province].filter(Boolean).join(', ') : '';
  const method = paymentMethodLabel(order.payment_method_id);
  const installments = Number(order.installments) > 1 ? `${order.installments} cuotas` : null;
  const coupon = Number(order.coupon_amount);
  const shipmentStatus = shipment ? shippingStatusLabel(shipment) : null;

  return (
    <>
      <div className={styles.twoCol}>
        <section className={styles.card} aria-label="Comprador">
          <h3 className={styles.cardTitle}>Comprador</h3>
          {order.buyer_nickname && <p className={styles.buyerNick}>{order.buyer_nickname}</p>}
          {fullName && <p className={styles.contextText}>{fullName}</p>}
          {where && <p className={styles.contextMuted}>{where}</p>}
        </section>

        {shipment && (
          <section className={styles.card} aria-label="Envío">
            <div className={styles.cardTitleRow}>
              <h3 className={styles.cardTitle}>Envío</h3>
              {shipment.modo_logistico && (
                <StatusPill tone={MODO_LOGISTICO_TONE[shipment.modo_logistico]}>
                  {MODO_LOGISTICO_LABELS[shipment.modo_logistico] || shipment.modo_logistico}
                </StatusPill>
              )}
            </div>
            {shipmentStatus && (
              <p className={`${styles.shipStatus} ${styles[`dot_${shipmentDotTone(shipment.status)}`]}`}>
                <span className={styles.statusDot} aria-hidden="true" />
                {shipmentStatus}
              </p>
            )}
            {hasValue(shipment.shipment_id) && (
              <p className={styles.shipId}>
                <span className={styles.mono}>{shipment.shipment_id}</span>
                <CopyButton value={shipment.shipment_id} label="Copiar ID de envío" />
              </p>
            )}
            {shipment.estimated_delivery && (
              <p className={styles.contextMuted}>Llega el {formatDay(shipment.estimated_delivery)}</p>
            )}
            {shipment.tracking_number && (
              <p className={styles.trackingNote}>
                Seguimiento del correo: <span className={styles.mono}>{shipment.tracking_number}</span>
              </p>
            )}
          </section>
        )}
      </div>

      <section className={styles.card} aria-label="Pago">
        <h3 className={styles.cardTitle}>Pago</h3>
        <dl className={styles.contextList}>
          {(method || installments) && (
            <Row label="Método">{[method, installments].filter(Boolean).join(' · ')}</Row>
          )}
          {order.payment_date_approved && <Row label="Aprobación">{formatDay(order.payment_date_approved)}</Row>}
          {hasValue(order.paid_amount) && (
            <Row label="Total pagado por el comprador">
              <span className={styles.figure}>{formatSignedMoney(order.paid_amount)}</span>
            </Row>
          )}
          {coupon > 0 && (
            <Row label="Cupón ML">
              <span className={`${styles.figure} ${styles.figureMuted}`}>{formatSignedMoney(coupon)}</span>
            </Row>
          )}
        </dl>
      </section>
    </>
  );
}
