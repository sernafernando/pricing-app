import { formatPct } from '../../../utils/metricasMlFormat';
import { MARKUP_REASONS, UNKNOWN_REASON } from '../markupReasons';
import cellStyles from '../cells.module.css';
import { amount, count, date, orNull, units } from './format';
import { BodySection, MercadoLibreSection } from './ResumenMl';
import { Field, Fields, Section } from './PanelParts';
import {
  CONDITION_LABELS,
  LINK_STATE_LABELS,
  LISTING_TYPE_LABELS,
  LOGISTIC_TYPE_LABELS,
  PRICE_SOURCE_LABELS,
  SHIPPING_SOURCE_LABELS,
  label,
} from './labels';
import styles from './panel.module.css';
import { sellInOrigen } from '../../../utils/sellInOrigen';

/**
 * What needs the operator now, only from real signals (orchestrator 2026-11-02): ML took the
 * publication down or flags it, the last write failed, the link is broken, or it sells at a loss.
 * No thresholds of our own. Absent when there is nothing to say.
 */
function AttentionSection({ detail, canSeeMargin }) {
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
    <Section title="Atención">
      <ul className={styles.attention}>
        {signals.map((text) => (
          <li key={text}>{text}</li>
        ))}
      </ul>
    </Section>
  );
}

/**
 * The parts of the stock, as the table's Stock group: ERP and Full; their total is in the panel header. The published
 * quantity (and where ML places it) is not a stock (owner, 2026-11-10) and is not shown.
 */
function StockSection({ detail }) {
  const stock = detail.row.stock ?? {};
  return (
    <Section title="Stock">
      <Fields shortValues>
        <Field label="Stock ERP">{units(detail.row.erp_stock?.quantity)}</Field>
        <Field label="Full">{units(stock.full)}</Field>
        <Field label="Actualizado">{date(detail.stockAsOf ?? stock.as_of)}</Field>
      </Fields>
    </Section>
  );
}

function LinkSection({ link }) {
  return (
    <Section title="Producto vinculado">
      <Fields>
        <Field label="Estado">{label(LINK_STATE_LABELS, link?.state)}</Field>
        <Field label="Código">{orNull(link?.codigo)}</Field>
        <Field label="Producto">{orNull(link?.descripcion)}</Field>
      </Fields>
    </Section>
  );
}

/**
 * What the publication is, read once and seldom: quiet, in two columns when the panel is wide. The promotion is the
 * Promos tab's ("Activa ahora") for whoever has that tab (`canViewPromos`), so only the others read it here.
 */
function PublicationDataSection({ detail, canViewPromos }) {
  const { row } = detail;
  const price = row.price;
  const store = row.store_label ?? (row.official_store_id == null ? null : `Tienda ${row.official_store_id}`);
  const promotion = [price?.promotion_type, price?.campaign].filter(Boolean).join(' · ');
  const hasRegular = price?.regular_amount != null && Number(price.regular_amount) !== Number(price.amount);
  return (
    <Section title="Datos de la publicación">
      <Fields columns quiet>
        <Field label="Condición">{label(CONDITION_LABELS, detail.condition)}</Field>
        <Field label="Tipo">{label(LISTING_TYPE_LABELS, row.listing_type_id)}</Field>
        <Field label="Catálogo">{row.catalog_listing == null ? null : row.catalog_listing ? 'Sí' : 'No'}</Field>
        <Field label="Logística">{label(LOGISTIC_TYPE_LABELS, row.logistic_type)}</Field>
        <Field label="Tienda">{store}</Field>
        <Field label="Marca">{orNull(row.ml_brand)}</Field>
        <Field label="Familia">{row.family_name ?? count(row.family_id)}</Field>
        <Field label="Producto de usuario">{orNull(row.user_product_id)}</Field>
        <Field label="Variaciones">{row.variations_count > 0 ? row.variations_count : null}</Field>
        <Field label="Salud">{detail.health == null ? null : formatPct(detail.health * 100)}</Field>
        <Field label="Origen del precio">{price?.amount == null ? null : label(PRICE_SOURCE_LABELS, price.source)}</Field>
        <Field label="Precio regular">{hasRegular ? amount(price.regular_amount) : null}</Field>
        {!canViewPromos && <Field label="Promoción">{promotion || null}</Field>}
        <Field label="Etiquetas">
          {detail.tags.length > 0 ? (
            <span className={styles.tags}>
              {detail.tags.map((tag) => (
                <span key={tag} className={cellStyles.badge}>
                  {tag}
                </span>
              ))}
            </span>
          ) : null}
        </Field>
        <Field label="Creada">{date(detail.dateCreated)}</Field>
        <Field label="Modificada en ML">{date(detail.mlLastUpdated)}</Field>
        <Field label="Sincronizada">{date(detail.fetchedAt)}</Field>
      </Fields>
    </Section>
  );
}

/** The key of this publication's markup in `sell_in_out.markups_sell_in[_out]` (backend `detail.SELL_IN_OUT_KEY`). */
const SELL_IN_OUT_KEY = 'publicacion';

const isBlank = (value) => value === null || value === undefined;

/** A marked-down figure: an unknown amount, or no sell in at all, with what it means in the tooltip. */
const Muted = ({ title, children }) => (
  <span className={cellStyles.empty} title={title}>
    {children}
  </span>
);

const MarkupValue = ({ value }) => (
  <span className={cellStyles.markup} data-negative={value < 0 ? '' : undefined}>
    {formatPct(value)}
  </span>
);

/** The cost of the purchase lot the next sale takes its sell in from, with its discount and units left. */
function SellInCost({ sellIn }) {
  if (!sellIn) return <Muted title="Sin sell in vigente">-</Muted>;
  const origen = sellInOrigen(sellIn); // a purchase lot or the % of cost bonuses (T25c)
  const detalle = `Descuento por unidad: $ ${amount(sellIn.descuento_unit)}\n${origen}`;
  if (isBlank(sellIn.costo)) return <Muted title={detalle}>Sin tipo de cambio</Muted>;
  return <span title={detalle}>{amount(sellIn.costo)}</span>;
}

/**
 * The publication's markup with sell in and sell out when there is sell out, else with sell in only.
 * "Pendiente" when an amount is unknown (a lot without a cost in pesos, a sell out without its rate
 * or base): never a made-up figure.
 */
function SellInOutMarkup({ sellInOut }) {
  const { sell_in: sellIn, sell_out: sellOut } = sellInOut;
  const conSellOut = sellInOut.markups_sell_in_out?.[SELL_IN_OUT_KEY];
  if (!isBlank(conSellOut)) {
    return (
      <span title={`Con sell in y sell out (sell out: $ ${amount(sellOut.monto_unit)} por unidad, sin IVA)`}>
        <MarkupValue value={conSellOut} />
      </span>
    );
  }
  const sellOutPendiente = Boolean(sellOut) && isBlank(sellOut.monto_unit);
  const conSellIn = sellInOut.markups_sell_in?.[SELL_IN_OUT_KEY];
  if (isBlank(conSellIn)) {
    const costoPendiente = Boolean(sellIn) && isBlank(sellIn.costo);
    if (costoPendiente || sellOutPendiente) {
      return <Muted title="Falta el tipo de cambio o la base para calcular el markup">Pendiente</Muted>;
    }
    return null;
  }
  return (
    <span title={sellOutPendiente ? 'Con sell in; el sell out está pendiente' : 'Con sell in'}>
      <MarkupValue value={conSellIn} />
    </span>
  );
}

/**
 * An amount with a quieter fact after it; either may be missing. Both missing is null, so `Field` draws "—"
 * (a plain function, not a component: `Field` must see the null).
 */
function withAside(value, aside) {
  if (value == null && !aside) return null;
  return (
    <>
      {value}
      {aside && <span className={styles.aside}>{value == null ? aside : ` · ${aside}`}</span>}
    </>
  );
}

/**
 * Rentabilidad: the sum from the price down to the markup (Precio on top, Markup last: the one repeat
 * of the header, allowed because they are the ends of the sum), then what it was computed on, quieter.
 */
function RentabilidadSection({ breakdown, reason, sellInOut, publicationPriceSource }) {
  if (breakdown == null) {
    return (
      <Section title="Rentabilidad">
        <p className={styles.note}>{MARKUP_REASONS[reason] ?? UNKNOWN_REASON}</p>
      </Section>
    );
  }
  // The origin of the price the sum starts from, only when Datos de la publicación does not already say it (a
  // variation's price, say): never repeated, never lost.
  const priceOrigin = breakdown.price_source === publicationPriceSource ? null : label(PRICE_SOURCE_LABELS, breakdown.price_source);
  return (
    <Section title="Rentabilidad">
      <Fields>
        <Field label="Precio">
          {withAside(amount(breakdown.price), priceOrigin)}
        </Field>
        <Field label="Comisión">
          {withAside(amount(breakdown.comision_total), breakdown.comision_pct == null ? null : formatPct(breakdown.comision_pct))}
        </Field>
        <Field label="Costo de envío">
          {withAside(amount(breakdown.costo_envio), label(SHIPPING_SOURCE_LABELS, breakdown.envio_source))}
        </Field>
        <Field label="Precio limpio">{amount(breakdown.limpio)}</Field>
        <Field label="Costo">{amount(breakdown.costo_ars)}</Field>
        {sellInOut && (
          <Field label="Costo c/ sell in">
            <SellInCost sellIn={sellInOut.sell_in} />
          </Field>
        )}
        <Field label="Markup">{breakdown.markup == null ? null : <MarkupValue value={breakdown.markup} />}</Field>
        {sellInOut && (
          <Field label="Markup c/ sell in/out">
            <SellInOutMarkup sellInOut={sellInOut} />
          </Field>
        )}
      </Fields>
      <Fields quiet>
        <Field label="Unidad calculada">
          {breakdown.variation_id == null ? 'La publicación' : `Variación ${breakdown.variation_id}`}
        </Field>
        <Field label="Cuotas">{count(breakdown.installments)}</Field>
        <Field label="Lista de precios">{count(breakdown.pricelist_id)}</Field>
      </Fields>
    </Section>
  );
}

/**
 * Resumen (S4): what needs attention, the Rentabilidad sum, Stock beside the linked product, then
 * the quiet data. Total stock, sales and the status live in the panel header, not here; price and markup
 * only come back as the two ends of the Rentabilidad sum. The promotion is left to the Promos tab when the viewer has
 * it (`canViewPromos`).
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
        <StockSection detail={detail} />
        <LinkSection link={row.link} />
      </div>
      <PublicationDataSection detail={detail} canViewPromos={canViewPromos} />
      <MercadoLibreSection item={detail.item} shownPrices={[row.price?.amount, row.price?.regular_amount]} />
      <BodySection extra={detail.extra} />
    </>
  );
}
