import { useId } from 'react';
import { AlertTriangle } from 'lucide-react';
import { formatPct } from '../../../utils/metricasMlFormat';
import { MARKUP_REASONS, UNKNOWN_REASON } from '../markupReasons';
import cellStyles from '../cells.module.css';
import { amount, count, date, units } from './format';
import { MoreMercadoLibre } from './ResumenMl';
import { Block, Card, Chip, ChipRow, Group, Line } from './ResumenParts';
import {
  CONDITION_LABELS,
  LINK_STATE_LABELS,
  LISTING_TYPE_LABELS,
  LOGISTIC_TYPE_LABELS,
  PRICE_SOURCE_LABELS,
  SHIPPING_SOURCE_LABELS,
  label,
} from './labels';
import panelStyles from './panel.module.css';
import styles from './resumen.module.css';
import { MarkupValue, SellInCost, SellInOutMarkupLine } from './sellInOutFigures';

/** Money with its sign, as the panel header writes it ("$ 98.500,50"); a missing figure stays `null`. */
const money = (value) => {
  const text = amount(value);
  return text == null ? null : `$ ${text}`;
};

/**
 * What needs the operator now, only from real signals (orchestrator 2026-11-02): ML took the
 * publication down or flags it, the last write failed, the link is broken, or it sells at a loss.
 * No thresholds of our own. Absent when there is nothing to say. An alert box on top (S5).
 */
function AttentionSection({ detail, canSeeMargin }) {
  const titleId = useId();
  const { row } = detail;
  const signals = [];
  if (row.gone) signals.push(row.gone_at ? `Eliminada de Mercado Libre el ${date(row.gone_at)}` : 'Eliminada de Mercado Libre');
  for (const code of detail.subStatus) signals.push(`Subestado de Mercado Libre: ${code}`);
  if (detail.item?.last_error) signals.push(`Último error de Mercado Libre: ${detail.item.last_error}`);
  if (row.link?.state === 'conflicto') signals.push('El vínculo con el producto está en conflicto');
  // An unknown link (none sent) is not a signal; only a link evaluated without a product is.
  if (row.link?.state === 'sin_producto') signals.push('Sin producto vinculado');
  if (canSeeMargin && row.markup?.any_negative) signals.push('Markup negativo');
  if (signals.length === 0) return null;
  return (
    <section className={styles.alert} aria-labelledby={titleId}>
      <AlertTriangle size={18} aria-hidden="true" className={styles.alertIcon} />
      <div className={styles.alertBody}>
        <h3 id={titleId} className={styles.alertTitle}>
          Atención
        </h3>
        <ul className={styles.alertList}>
          {signals.map((text) => (
            <li key={text}>{text}</li>
          ))}
        </ul>
      </div>
    </section>
  );
}

/**
 * The parts of the stock, as the table's Stock group: ERP and Full; their total is in the panel header. The published
 * quantity (and where ML places it) is not a stock (owner, 2026-11-10) and is not shown.
 */
function StockCard({ detail }) {
  const stock = detail.row.stock ?? {};
  const asOf = date(detail.stockAsOf ?? stock.as_of);
  const figure = (value) => units(value) ?? <span className={cellStyles.empty}>—</span>;
  return (
    <Card title="Stock">
      <dl className={styles.figures}>
        <div className={styles.figure}>
          <dt>ERP</dt>
          <dd>{figure(detail.row.erp_stock?.quantity)}</dd>
        </div>
        <div className={styles.figure}>
          <dt>Full</dt>
          <dd>{figure(stock.full)}</dd>
        </div>
      </dl>
      <p className={styles.caption}>{asOf ? `Actualizado ${asOf}` : 'Sin fecha de actualización'}</p>
    </Card>
  );
}

const LINK_TONES = { auto: 'success', manual: 'success', conflicto: 'danger', sin_producto: 'warning' };

function LinkCard({ link }) {
  const state = label(LINK_STATE_LABELS, link?.state);
  const hasProduct = link?.codigo != null || link?.descripcion != null;
  return (
    <Card title="Producto vinculado" badge={state && <Chip tone={LINK_TONES[link.state]}>{state}</Chip>}>
      {hasProduct ? (
        <>
          {link.codigo != null && <span className={styles.strong}>{link.codigo}</span>}
          {link.descripcion != null && <span className={styles.muted}>{link.descripcion}</span>}
        </>
      ) : (
        <span className={styles.muted}>Sin producto</span>
      )}
    </Card>
  );
}

/**
 * What the publication is, read once and seldom, in three groups (S5): the publication, its price, its dates; then
 * the tags as chips. The promotion is the Promos tab's ("Activa ahora") for whoever has that tab (`canViewPromos`), so
 * only the others read it here. The regular price only when it is not the price.
 */
function FichaSection({ detail, canViewPromos }) {
  const { row } = detail;
  const price = row.price;
  const store = row.store_label ?? (row.official_store_id == null ? null : `Tienda ${row.official_store_id}`);
  const promotion = [price?.promotion_type, price?.campaign].filter(Boolean).join(' · ');
  const hasRegular = price?.regular_amount != null && Number(price.regular_amount) !== Number(price.amount);
  return (
    <Block title="Ficha de la publicación">
      <div className={styles.groupsContainer}>
        <div className={`${styles.groups} ${styles.groupsThree}`}>
          <Group title="Publicación">
            <Line label="Condición">{label(CONDITION_LABELS, detail.condition)}</Line>
            <Line label="Tipo">{label(LISTING_TYPE_LABELS, row.listing_type_id)}</Line>
            <Line label="Catálogo">{row.catalog_listing == null ? null : row.catalog_listing ? 'Sí' : 'No'}</Line>
            <Line label="Logística">{label(LOGISTIC_TYPE_LABELS, row.logistic_type)}</Line>
            <Line label="Tienda">{store}</Line>
            <Line label="Marca">{row.ml_brand}</Line>
            <Line label="Familia">{row.family_name ?? count(row.family_id)}</Line>
            <Line label="Producto de usuario">{row.user_product_id}</Line>
            <Line label="Variaciones">{row.variations_count > 0 ? row.variations_count : null}</Line>
            <Line label="Salud">{detail.health == null ? null : formatPct(detail.health * 100)}</Line>
          </Group>
          <Group title="Precio">
            <Line label="Origen">{price?.amount == null ? null : label(PRICE_SOURCE_LABELS, price.source)}</Line>
            {hasRegular && <Line label="Regular">{money(price.regular_amount)}</Line>}
            {!canViewPromos && <Line label="Promoción">{promotion || null}</Line>}
          </Group>
          <Group title="Fechas">
            <Line short label="Creada">{date(detail.dateCreated)}</Line>
            <Line short label="Modificada en ML">{date(detail.mlLastUpdated)}</Line>
            <Line short label="Sincronizada">{date(detail.fetchedAt)}</Line>
          </Group>
        </div>
      </div>
      <ChipRow label="Etiquetas" items={detail.tags} emptyDash />
    </Block>
  );
}

/**
 * One step of the Rentabilidad sum; `op` is its sign ("−", "="), drawn before the label by its class. `aside` is a
 * quieter fact next to the label (the commission %, where the shipping cost comes from).
 */
function Step({ label: text, op, aside, className, children }) {
  const opClass = op === '−' ? styles.stepMinus : op === '=' ? styles.stepTotal : null;
  return (
    <div className={[styles.step, opClass, className].filter(Boolean).join(' ')} data-op={op}>
      <dt>
        {text}
        {aside}
      </dt>
      <dd>{children ?? <span className={cellStyles.empty}>—</span>}</dd>
    </div>
  );
}

/** "Calculado sobre la publicación · 6 cuotas · lista de precios 12", leaving out what the breakdown lacks. */
function computedOn(breakdown) {
  const unit = breakdown.variation_id == null ? 'Calculado sobre la publicación' : `Calculado sobre la variación ${breakdown.variation_id}`;
  const installments = breakdown.installments == null ? null : `${breakdown.installments} cuotas`;
  const pricelist = breakdown.pricelist_id == null ? null : `lista de precios ${breakdown.pricelist_id}`;
  return [unit, installments, pricelist].filter(Boolean).join(' · ');
}

/**
 * Rentabilidad (S5): the sum as a waterfall from the price down to the clean price and the cost, the markup as its
 * result band (the one repeat of the header, allowed because they are the ends of the sum), then what it was
 * computed on as one caption.
 */
function RentabilidadSection({ breakdown, reason, sellInOut, publicationPriceSource }) {
  if (breakdown == null) {
    return (
      <Block title="Rentabilidad">
        <p className={panelStyles.note}>{MARKUP_REASONS[reason] ?? UNKNOWN_REASON}</p>
      </Block>
    );
  }
  // The origin of the price the sum starts from, only when the Ficha does not already say it (a variation's price,
  // say): never repeated, never lost.
  const priceOrigin = breakdown.price_source === publicationPriceSource ? null : label(PRICE_SOURCE_LABELS, breakdown.price_source);
  const shippingSource = label(SHIPPING_SOURCE_LABELS, breakdown.envio_source);
  const aside = (text) => text && <span className={styles.stepAside}>{text}</span>;
  return (
    <Block title="Rentabilidad">
      <div className={styles.waterfall}>
        <dl className={styles.steps}>
          <Step label="Precio" aside={aside(priceOrigin)}>
            {money(breakdown.price)}
          </Step>
          <Step label="Comisión" op="−" aside={aside(breakdown.comision_pct == null ? null : `· ${formatPct(breakdown.comision_pct)}`)}>
            {money(breakdown.comision_total)}
          </Step>
          <Step label="Costo de envío" op="−" aside={shippingSource && <span className={styles.sourceTag}>{shippingSource}</span>}>
            {money(breakdown.costo_envio)}
          </Step>
          <Step label="Precio limpio" op="=">
            {money(breakdown.limpio)}
          </Step>
          <Step label="Costo" className={styles.stepCost}>
            {sellInOut ? (
              <>
                <span>{money(breakdown.costo_ars) ?? <span className={cellStyles.empty}>—</span>}</span>
                <span className={styles.muted}>
                  c/ sell in <SellInCost sellIn={sellInOut.sell_in} format={money} />
                </span>
              </>
            ) : (
              money(breakdown.costo_ars)
            )}
          </Step>
        </dl>
        <dl className={styles.markupBand}>
          <dt>Markup</dt>
          <dd>
            <span className={styles.markupMain}>
              {breakdown.markup == null ? <span className={cellStyles.empty}>—</span> : <MarkupValue value={breakdown.markup} />}
            </span>
            {sellInOut && <SellInOutMarkupLine sellInOut={sellInOut} className={styles.markupSecondaryLine} />}
          </dd>
        </dl>
      </div>
      <p className={styles.caption}>{computedOn(breakdown)}</p>
    </Block>
  );
}

/**
 * Resumen (S4, laid out in S5): what needs attention, the Rentabilidad sum, Stock beside the linked product, the
 * Ficha, then Mercado Libre's own data collapsed. Total stock, sales and the status live in the panel header, not
 * here; price and markup only come back as the two ends of the Rentabilidad sum. The promotion is left to the Promos
 * tab when the viewer has it (`canViewPromos`).
 */
export default function ResumenTab({ detail, canSeeMargin, canViewPromos = false }) {
  const { row } = detail;
  return (
    <>
      <AttentionSection detail={detail} canSeeMargin={canSeeMargin} />
      {canSeeMargin && (
        <RentabilidadSection
          breakdown={detail.markupBreakdown}
          reason={row.markup?.reason}
          sellInOut={detail.sellInOut}
          publicationPriceSource={row.price?.amount == null ? null : row.price.source}
        />
      )}
      <div className={styles.pair}>
        <StockCard detail={detail} />
        <LinkCard link={row.link} />
      </div>
      <FichaSection detail={detail} canViewPromos={canViewPromos} />
      <MoreMercadoLibre item={detail.item} extra={detail.extra} shownPrices={[row.price?.amount, row.price?.regular_amount]} />
    </>
  );
}
