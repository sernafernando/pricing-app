import { amount, count, date, orNull, yesNo } from './format';
import { Field, Fields, Section } from './PanelParts';
import styles from './panel.module.css';

/** A list as lines; an empty or missing one is `null` (not an element), so the field reads "—". */
function lines(entries) {
  if (!Array.isArray(entries) || entries.length === 0) return null;
  return (
    <ul className={styles.lines}>
      {entries.map((entry, index) => (
        <li key={`${entry}-${index}`}>{entry}</li>
      ))}
    </ul>
  );
}

const named = (entries) =>
  Array.isArray(entries) ? entries.map((entry) => [entry.name ?? entry.id, entry.value_name].filter((part) => part != null).join(': ')) : null;

const relations = (entries) =>
  Array.isArray(entries)
    ? entries.map((relation) => [relation.id, relation.variation_id != null && `variación ${relation.variation_id}`].filter(Boolean).join(' · '))
    : null;

const plain = (value) => (value == null || value === '' ? null : typeof value === 'object' ? JSON.stringify(value) : String(value));

function pictureLinks(pictures) {
  if (!Array.isArray(pictures) || pictures.length === 0) return null;
  // A picture's address comes from the body of the item: only https is linked.
  const safe = pictures.filter((picture) => typeof picture.secure_url === 'string' && picture.secure_url.startsWith('https://'));
  return (
    <>
      <span>
        {safe.length === 1 ? '1 imagen' : `${safe.length} imágenes`}
        {safe.length < pictures.length && ` (${pictures.length - safe.length} sin enlace)`}
      </span>
      <ul className={styles.lines}>
        {safe.map((picture, index) => (
          <li key={picture.id ?? index}>
            <a href={picture.secure_url} target="_blank" rel="noopener noreferrer">
              Imagen {index + 1}
            </a>
          </li>
        ))}
      </ul>
    </>
  );
}

/** What `ml_items` holds about the publication that the other sections do not already say. */
export function MercadoLibreSection({ item }) {
  return (
    <Section title="Datos de Mercado Libre">
      <Fields>
        <Field label="Categoría">{orNull(item.category_id)}</Field>
        <Field label="Dominio">{orNull(item.domain_id)}</Field>
        <Field label="Vendedor">{count(item.seller_id)}</Field>
        <Field label="Producto de catálogo">{orNull(item.catalog_product_id)}</Field>
        <Field label="Modo de compra">{orNull(item.buying_mode)}</Field>
        <Field label="Moneda">{orNull(item.currency_id)}</Field>
        <Field label="SKU del vendedor">{orNull(item.seller_sku)}</Field>
        <Field label="Campo personalizado">{orNull(item.seller_custom_field)}</Field>
        <Field label="Precio base">{amount(item.base_price)}</Field>
        <Field label="Precio original">{amount(item.original_price)}</Field>
        <Field label="Cantidad inicial">{count(item.initial_quantity)}</Field>
        <Field label="Vendidas">{count(item.sold_quantity)}</Field>
        <Field label="Inventario">{orNull(item.inventory_id)}</Field>
        <Field label="Publicación padre">{orNull(item.parent_item_id)}</Field>
        <Field label="Modo de envío">{orNull(item.shipping_mode)}</Field>
        <Field label="Envío gratis">{yesNo(item.free_shipping)}</Field>
        <Field label="Inicio">{date(item.start_time)}</Field>
        <Field label="Fin">{date(item.stop_time)}</Field>
        <Field label="Finalizada">{date(item.end_time)}</Field>
        <Field label="Vencimiento">{date(item.expiration_time)}</Field>
        {item.last_error && <Field label="Último error">{item.last_error}</Field>}
      </Fields>
    </Section>
  );
}

/** The whitelisted part of the item body (`extra`): warranty, shipping, terms, attributes, pictures. */
export function BodySection({ extra }) {
  const shipping = extra.shipping ?? {};
  const address = extra.seller_address ?? {};
  return (
    <Section title="Características">
      <Fields>
        <Field label="Garantía">{plain(extra.warranty)}</Field>
        <Field label="Origen">{plain(extra.listing_source)}</Field>
        <Field label="Republicación automática">{yesNo(extra.automatic_relist)}</Field>
        <Field label="Acepta Mercado Pago">{yesNo(extra.accepts_mercadopago)}</Field>
        <Field label="Entrega internacional">{plain(extra.international_delivery_mode)}</Field>
        <Field label="Video">{plain(extra.video_id)}</Field>
        <Field label="Miniatura">{plain(extra.thumbnail_id)}</Field>
        <Field label="Precio diferencial">{plain(extra.differential_pricing)}</Field>
        <Field label="Canales">{lines(extra.channels)}</Field>
        <Field label="Ofertas">{lines(extra.deal_ids)}</Field>
        <Field label="Retiro en persona">{yesNo(shipping.local_pick_up)}</Field>
        <Field label="Retiro en tienda">{yesNo(shipping.store_pick_up)}</Field>
        <Field label="Etiquetas de envío">{lines(shipping.tags)}</Field>
        <Field label="Ciudad">{plain(address.city)}</Field>
        <Field label="Provincia">{plain(address.state)}</Field>
        <Field label="Condiciones de venta">{lines(named(extra.sale_terms))}</Field>
        <Field label="Atributos">{lines(named(extra.attributes))}</Field>
        <Field label="Relaciones">{lines(relations(extra.item_relations))}</Field>
        <Field label="Imágenes">{pictureLinks(extra.pictures)}</Field>
      </Fields>
    </Section>
  );
}
