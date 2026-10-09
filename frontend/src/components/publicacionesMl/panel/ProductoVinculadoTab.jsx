import { getPublicationTypeLabel } from '../../../constants/mlPublicationTypes';
import cellStyles from '../cells.module.css';
import { amount, date, orNull } from './format';
import { Field, Fields, Section } from './PanelParts';
import { LINK_STATE_LABELS, label } from './labels';
import styles from './panel.module.css';

/** The list's name when the pricelist is one we label, else its number. */
const listName = (pricelistId) => {
  const known = getPublicationTypeLabel(Number(pricelistId));
  return known === 'Desconocido' ? `Lista ${pricelistId}` : known;
};

function ProductSection({ product }) {
  return (
    <Section title="Producto">
      <Fields>
        <Field label="Código">{orNull(product.codigo)}</Field>
        <Field label="Descripción">{orNull(product.descripcion)}</Field>
        <Field label="Marca">{orNull(product.marca)}</Field>
        <Field label="Categoría">{orNull(product.categoria)}</Field>
        <Field label="Subcategoría">{orNull(product.subcategoria)}</Field>
      </Fields>
    </Section>
  );
}

function PricesSection({ prices }) {
  const lists = Object.entries(prices);
  if (lists.length === 0) return null;
  return (
    <Section title="Precios de lista">
      <Fields>
        {lists.map(([pricelistId, price]) => (
          <Field key={pricelistId} label={listName(pricelistId)}>
            {amount(price)}
          </Field>
        ))}
      </Fields>
    </Section>
  );
}

/** Only rendered for a caller with `ml_metricas.ver_ganancia`: the model drops the cost for anybody else. */
function CostSection({ product }) {
  return (
    <Section title="Costo">
      <Fields>
        <Field label="Costo">{product.costo == null ? null : [amount(product.costo), product.moneda_costo].filter(Boolean).join(' ')}</Field>
        <Field label="IVA">{product.iva == null ? null : `${product.iva}%`}</Field>
      </Fields>
    </Section>
  );
}

function LinkUnit({ link }) {
  const linked = link.producto_item_id != null;
  return (
    <li className={styles.card}>
      <div className={styles.cardHead}>
        <span className={styles.cardTitle}>{link.variation_id === 0 ? 'Publicación' : `Variación ${link.variation_id}`}</span>
        <span className={cellStyles.badge}>{label(LINK_STATE_LABELS, link.state)}</span>
        {linked ? (
          <span className={styles.productName}>{[link.codigo, link.descripcion].filter(Boolean).join(' · ') || '—'}</span>
        ) : (
          <span className={cellStyles.empty}>Sin producto vinculado</span>
        )}
      </div>
      <Fields>
        <Field label="Marca">{linked ? orNull(link.marca) : null}</Field>
        <Field label="SKU coincidente">{orNull(link.matched_sku)}</Field>
        <Field label="Vinculado">{date(link.linked_at)}</Field>
        <Field label="Nota">{orNull(link.note)}</Field>
        {link.suggested_producto_item_id != null && <Field label="Sugerencia">{`Producto sugerido: ${link.suggested_producto_item_id}`}</Field>}
      </Fields>
    </li>
  );
}

/**
 * Producto vinculado: the product the publication is linked to (the item-level
 * one), its list prices and, with `ml_metricas.ver_ganancia`, its cost; and the
 * link of each unit (the publication and each variation). Read-only: the
 * links are edited elsewhere.
 */
export default function ProductoVinculadoTab({ detail }) {
  const { product, links } = detail;
  return (
    <>
      {product == null && <p className={styles.note}>Sin producto vinculado</p>}
      {product != null && (
        <>
          <ProductSection product={product} />
          <PricesSection prices={product.precios_lista} />
          {'costo' in product && <CostSection product={product} />}
        </>
      )}
      {links.length > 0 && (
        <Section title="Vínculos">
          <ul className={styles.cards}>
            {links.map((link) => (
              <LinkUnit key={link.variation_id} link={link} />
            ))}
          </ul>
        </Section>
      )}
    </>
  );
}
