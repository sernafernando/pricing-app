import { useId, useState } from 'react';
import { Check, X } from 'lucide-react';
import { amount, count, date, isBlank, yesNo } from './format';
import { Chip, ChipRow, Group, Line } from './ResumenParts';
import styles from './resumen.module.css';

/*
 * "Más datos de Mercado Libre" (S5): what `ml_items` and the whitelisted item body (`extra`) hold that the other
 * blocks do not already say, collapsed by default (technical, read seldom). Inside: the quantities as tiles, four
 * groups of lines, the yes/no options as chips, the attributes as a table and the pictures as a strip. A field the
 * store does not have is left out, not drawn as "—".
 */

/** A list as lines; an empty or missing one is `null`, so its line is left out. */
function lines(entries) {
  if (!Array.isArray(entries) || entries.length === 0) return null;
  return (
    <ul className={styles.lineList}>
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

/**
 * An option as a yes/no chip. A boolean is ✓ or ✕; a value ML spells out (the international delivery mode, the
 * differential pricing) is ✓ with that value, "none" is ✕. Unknown (`null`) is left out.
 */
function OptionChip({ label, value }) {
  if (value == null || value === '') return null;
  const on = typeof value === 'boolean' ? value : value !== 'none';
  const shown = typeof value === 'boolean' || !on ? label : `${label}: ${plain(value)}`;
  return (
    <Chip tone={on ? 'success' : undefined}>
      {on ? <Check size={12} aria-label="Sí" /> : <X size={12} aria-label="No" />}
      {shown}
    </Chip>
  );
}

function Pictures({ pictures }) {
  if (!Array.isArray(pictures) || pictures.length === 0) return null;
  // A picture's address comes from the body of the item: only https is linked.
  const safe = pictures.filter((picture) => typeof picture.secure_url === 'string' && picture.secure_url.startsWith('https://'));
  return (
    <div className={styles.group}>
      <h4 className={styles.groupTitle}>Imágenes</h4>
      <p className={styles.caption}>
        {safe.length === 1 ? '1 imagen' : `${safe.length} imágenes`}
        {safe.length < pictures.length && ` (${pictures.length - safe.length} sin enlace)`}
      </p>
      {safe.length > 0 && (
        <ul className={styles.images}>
          {safe.map((picture, index) => (
            <li key={picture.id ?? index}>
              <a className={styles.thumb} href={picture.secure_url} target="_blank" rel="noopener noreferrer">
                <img src={picture.secure_url} alt={`Imagen ${index + 1}`} loading="lazy" />
              </a>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Attributes({ attributes }) {
  const rows = Array.isArray(attributes) ? attributes.filter((entry) => (entry.name ?? entry.id) != null) : [];
  if (rows.length === 0) return null;
  return (
    <div className={styles.group}>
      <h4 className={styles.groupTitle}>Atributos</h4>
      <dl className={styles.attributes}>
        {rows.map((entry, index) => (
          <div key={`${entry.id ?? entry.name}-${index}`} className={styles.attribute}>
            <dt>{entry.name ?? entry.id}</dt>
            <dd>{entry.value_name ?? '—'}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

/** A tile only when its value is known. */
const tile = (label, value) =>
  isBlank(value) ? null : (
    <div key={label} className={styles.tile}>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );

/** The expanded content. Its base and original prices only when they are not an amount the panel already shows. */
function Body({ item, extra, shownPrices }) {
  const shown = new Set(shownPrices.filter((value) => value != null).map(Number));
  const isNew = (value) => value == null || !shown.has(Number(value));
  const shipping = extra.shipping ?? {};
  const tiles = [tile('Cantidad inicial', count(item.initial_quantity)), tile('Vendidas', count(item.sold_quantity)), tile('Moneda', item.currency_id)];
  const options = [
    ['Acepta Mercado Pago', extra.accepts_mercadopago],
    ['Republicación automática', extra.automatic_relist],
    ['Entrega internacional', extra.international_delivery_mode],
    ['Precio diferencial', extra.differential_pricing],
  ];
  const knownOptions = options.filter(([, value]) => value != null && value !== '');
  const hasOptions = knownOptions.length > 0;
  return (
    <>
      {tiles.some(Boolean) && <dl className={styles.tiles}>{tiles}</dl>}
      <div className={styles.groupsContainer}>
        <div className={`${styles.groups} ${styles.groupsTwo}`}>
          <Group title="Categoría y catálogo">
            <Line hideEmpty label="Categoría">{item.category_id}</Line>
            <Line hideEmpty label="Dominio">{item.domain_id}</Line>
            <Line hideEmpty label="Producto de catálogo">{item.catalog_product_id}</Line>
            <Line hideEmpty label="Publicación padre">{item.parent_item_id}</Line>
            <Line hideEmpty label="Relaciones">{lines(relations(extra.item_relations))}</Line>
          </Group>
          <Group title="Venta">
            <Line hideEmpty label="Modo de compra">{item.buying_mode}</Line>
            <Line hideEmpty label="Vendedor">{count(item.seller_id)}</Line>
            <Line hideEmpty label="SKU del vendedor">{item.seller_sku}</Line>
            <Line hideEmpty label="Campo personalizado">{item.seller_custom_field}</Line>
            <Line hideEmpty label="Inventario">{item.inventory_id}</Line>
            {isNew(item.base_price) && <Line hideEmpty label="Precio base">{amount(item.base_price)}</Line>}
            {isNew(item.original_price) && <Line hideEmpty label="Precio original">{amount(item.original_price)}</Line>}
            <Line hideEmpty label="Garantía">{plain(extra.warranty)}</Line>
            <Line hideEmpty label="Origen">{plain(extra.listing_source)}</Line>
            <Line hideEmpty label="Condiciones de venta">{lines(named(extra.sale_terms))}</Line>
            <Line hideEmpty label="Ofertas">{lines(extra.deal_ids)}</Line>
          </Group>
          <Group title="Envío">
            <Line hideEmpty label="Modo de envío">{item.shipping_mode}</Line>
            <Line hideEmpty label="Envío gratis">{yesNo(item.free_shipping)}</Line>
            <Line hideEmpty label="Retiro en persona">{yesNo(shipping.local_pick_up)}</Line>
            <Line hideEmpty label="Retiro en tienda">{yesNo(shipping.store_pick_up)}</Line>
          </Group>
          <Group title="Fechas en ML">
            <Line hideEmpty label="Inicio">{date(item.start_time)}</Line>
            <Line hideEmpty label="Fin">{date(item.stop_time)}</Line>
            <Line hideEmpty label="Finalizada">{date(item.end_time)}</Line>
            <Line hideEmpty label="Vencimiento">{date(item.expiration_time)}</Line>
          </Group>
        </div>
      </div>
      {(hasOptions || extra.channels?.length > 0 || shipping.tags?.length > 0) && (
        <div className={styles.group}>
          <h4 className={styles.groupTitle}>Opciones</h4>
          {hasOptions && (
            <div className={styles.chips} role="list" aria-label="Opciones">
              {knownOptions.map(([label, value]) => (
                <span key={label} role="listitem">
                  <OptionChip label={label} value={value} />
                </span>
              ))}
            </div>
          )}
          <ChipRow label="Canales" items={extra.channels} />
          <ChipRow label="Etiquetas de envío" items={shipping.tags} />
        </div>
      )}
      <Attributes attributes={extra.attributes} />
      <Pictures pictures={extra.pictures} />
      {(plain(extra.video_id) || plain(extra.thumbnail_id)) && (
        <dl className={styles.lines}>
          <Line hideEmpty label="Video">{plain(extra.video_id)}</Line>
          <Line hideEmpty label="Miniatura">{plain(extra.thumbnail_id)}</Line>
        </dl>
      )}
    </>
  );
}

export function MoreMercadoLibre({ item, extra, shownPrices = [] }) {
  const [open, setOpen] = useState(false);
  const titleId = useId();
  const bodyId = useId();
  return (
    <section className={styles.disclosure} aria-labelledby={titleId}>
      <button type="button" className={styles.disclosureToggle} aria-expanded={open} aria-controls={bodyId} onClick={() => setOpen(!open)}>
        <span className={styles.disclosureText}>
          <span id={titleId} className={styles.disclosureTitle}>
            Más datos de Mercado Libre
          </span>
          <span className={styles.caption}>Categoría, venta, envío, fechas de ML y características. Oculta los campos vacíos.</span>
        </span>
        <span className={styles.disclosureAction} aria-hidden="true">
          {open ? 'Ocultar' : 'Mostrar'}
        </span>
      </button>
      {open && (
        <div id={bodyId} className={styles.disclosureBody}>
          <Body item={item ?? {}} extra={extra ?? {}} shownPrices={shownPrices} />
        </div>
      )}
    </section>
  );
}
