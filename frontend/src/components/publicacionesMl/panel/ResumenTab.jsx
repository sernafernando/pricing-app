import { formatPct } from '../../../utils/metricasMlFormat';
import PublicationStatusPill from '../PublicationStatusPill';
import { MARKUP_REASONS, UNKNOWN_REASON } from '../markupReasons';
import cellStyles from '../cells.module.css';
import { amount, count, date, orNull } from './format';
import { BodySection, MercadoLibreSection } from './ResumenMl';
import { Field, Fields, Section } from './PanelParts';
import {
  CONDITION_LABELS,
  LINK_STATE_LABELS,
  LISTING_TYPE_LABELS,
  LOGISTIC_TYPE_LABELS,
  PRICE_SOURCE_LABELS,
  SHIPPING_SOURCE_LABELS,
  STOCK_LOCATION_LABELS,
  label,
} from './labels';
import styles from './panel.module.css';

function PublicationSection({ detail }) {
  const { row } = detail;
  const store = row.store_label ?? (row.official_store_id == null ? null : `Tienda ${row.official_store_id}`);
  return (
    <Section title="Publicación">
      <Fields>
        <Field label="Estado">
          {row.status || row.gone ? <PublicationStatusPill status={row.status} gone={row.gone} subStatus={detail.subStatus} /> : null}
        </Field>
        <Field label="Subestado">{detail.subStatus.length > 0 ? detail.subStatus.join(', ') : null}</Field>
        {row.gone && <Field label="Eliminada el">{date(row.gone_at)}</Field>}
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

function PriceSection({ price }) {
  const promotion = [price?.promotion_type, price?.campaign].filter(Boolean).join(' · ');
  const hasRegular = price?.regular_amount != null && Number(price.regular_amount) !== Number(price.amount);
  return (
    <Section title="Precio">
      <Fields>
        <Field label="Precio">{amount(price?.amount)}</Field>
        <Field label="Origen">{price?.amount == null ? null : label(PRICE_SOURCE_LABELS, price.source)}</Field>
        <Field label="Precio regular">{hasRegular ? amount(price.regular_amount) : null}</Field>
        <Field label="Promoción">{promotion || null}</Field>
      </Fields>
    </Section>
  );
}

function StockSection({ detail }) {
  const stock = detail.row.stock ?? {};
  return (
    <Section title="Stock ML">
      <Fields>
        <Field label="Disponible">{count(stock.available)}</Field>
        <Field label="Full">{count(stock.full)}</Field>
        <Field label="Propio">{count(stock.own)}</Field>
        {(detail.stockLocations ?? []).map((place) => (
          <Field key={place.type} label={label(STOCK_LOCATION_LABELS, place.type)}>
            {count(place.quantity)}
          </Field>
        ))}
        <Field label="Actualizado">{date(detail.stockAsOf ?? stock.as_of)}</Field>
      </Fields>
    </Section>
  );
}

function LinkSection({ link }) {
  return (
    <Section title="Vínculo">
      <Fields>
        <Field label="Estado">{label(LINK_STATE_LABELS, link?.state)}</Field>
        <Field label="Código">{orNull(link?.codigo)}</Field>
        <Field label="Producto">{orNull(link?.descripcion)}</Field>
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
  // A % of cost bonus (T25c) has no purchase lot: it names the bonus instead of the units left.
  const origen = sellIn.unidades_restantes == null
    ? `Bono #${sellIn.bono_id} sobre el costo`
    : `Unidades restantes del lote: ${sellIn.unidades_restantes}`;
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

function MarkupSection({ breakdown, reason, sellInOut }) {
  if (breakdown == null) {
    return (
      <Section title="Markup">
        <p className={styles.note}>{MARKUP_REASONS[reason] ?? UNKNOWN_REASON}</p>
      </Section>
    );
  }
  const negative = breakdown.markup != null && breakdown.markup < 0;
  return (
    <Section title="Markup">
      <Fields>
        <Field label="Precio">{amount(breakdown.price)}</Field>
        <Field label="Origen del precio">{label(PRICE_SOURCE_LABELS, breakdown.price_source)}</Field>
        <Field label="Unidad calculada">
          {breakdown.variation_id == null ? 'La publicación' : `Variación ${breakdown.variation_id}`}
        </Field>
        <Field label="Cuotas">{count(breakdown.installments)}</Field>
        <Field label="Lista de precios">{count(breakdown.pricelist_id)}</Field>
        <Field label="Comisión">{breakdown.comision_pct == null ? null : formatPct(breakdown.comision_pct)}</Field>
        <Field label="Comisión total">{amount(breakdown.comision_total)}</Field>
        <Field label="Costo de envío">{amount(breakdown.costo_envio)}</Field>
        <Field label="Origen del envío">{label(SHIPPING_SOURCE_LABELS, breakdown.envio_source)}</Field>
        <Field label="Precio limpio">{amount(breakdown.limpio)}</Field>
        <Field label="Costo">{amount(breakdown.costo_ars)}</Field>
        {sellInOut && (
          <Field label="Costo c/ sell in">
            <SellInCost sellIn={sellInOut.sell_in} />
          </Field>
        )}
        <Field label="Markup">
          {breakdown.markup == null ? null : (
            <span className={cellStyles.markup} data-negative={negative ? '' : undefined}>
              {formatPct(breakdown.markup)}
            </span>
          )}
        </Field>
        {sellInOut && (
          <Field label="Markup c/ sell in/out">
            <SellInOutMarkup sellInOut={sellInOut} />
          </Field>
        )}
      </Fields>
    </Section>
  );
}

/** Resumen: everything the publication is, in the order an operator reads it. */
export default function ResumenTab({ detail, canSeeMargin }) {
  const { row } = detail;
  return (
    <>
      <PublicationSection detail={detail} />
      <PriceSection price={row.price} />
      <StockSection detail={detail} />
      <LinkSection link={row.link} />
      <MercadoLibreSection item={detail.item} />
      <BodySection extra={detail.extra} />
      {canSeeMargin && (
        <MarkupSection breakdown={detail.markupBreakdown} reason={row.markup?.reason} sellInOut={detail.sellInOut} />
      )}
    </>
  );
}
