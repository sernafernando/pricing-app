import { getPublicationTypeLabel } from '../../../constants/mlPublicationTypes';
import { usePermisos } from '../../../contexts/PermisosContext';
import cellStyles from '../cells.module.css';
import { amount, count, date, orNull } from './format';
import { Field, Fields, Section } from './PanelParts';
import { LINK_STATE_LABELS, label } from './labels';
import styles from './panel.module.css';
import LinkActions from './LinkActions';
import { useProductLinks } from './useProductLinks';

const PERMISO_VINCULAR = 'ml_publicaciones.vincular';

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
        <Field label="Stock ERP (depósito 1)">{count(product.stock)}</Field>
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

/**
 * One card per unit: the detail's link rows, plus -- once the link units are
 * loaded for editing -- the live units without a row (never evaluated).
 */
const unitsOf = (links, editUnits) => {
  const byVariation = new Map(links.map((link) => [link.variation_id, { link, unit: null }]));
  for (const unit of editUnits) {
    const known = byVariation.get(unit.variation_id);
    if (known) known.unit = unit;
    else byVariation.set(unit.variation_id, { link: { variation_id: unit.variation_id, state: 'no_evaluado', producto_item_id: null }, unit });
  }
  return [...byVariation.values()].sort((a, b) => a.link.variation_id - b.link.variation_id);
};

function LinkUnit({ link, unit, itemId, canLink, onWritten }) {
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
      {canLink && (
        <LinkActions
          itemId={itemId}
          variationId={link.variation_id}
          source={unit?.link?.source ?? link.source ?? null}
          candidates={unit?.suggestion?.candidates ?? []}
          onWritten={onWritten}
        />
      )}
    </li>
  );
}

/**
 * Producto vinculado: the product the publication is linked to (the item-level
 * one), its list prices and, with `ml_metricas.ver_ganancia`, its cost; and the
 * link of each unit (the publication and each variation). With
 * `ml_publicaciones.vincular`, each unit can be linked to a product by hand,
 * marked as having no product or handed back to the automatic rule; a write
 * re-reads the link units here and the detail and list row (`onWritten`).
 */
export default function ProductoVinculadoTab({ detail, itemId, onWritten }) {
  const { product, links } = detail;
  const { tienePermiso } = usePermisos();
  const canLink = tienePermiso(PERMISO_VINCULAR);
  const editable = useProductLinks(itemId, canLink);
  const units = unitsOf(links, editable.units);
  const handleWritten = () => {
    editable.reload();
    onWritten?.();
  };
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
      {canLink && editable.status === 'error' && (
        <p className={styles.note} role="alert">
          No se pudieron cargar los vínculos para editarlos.
        </p>
      )}
      {units.length > 0 && (
        <Section title="Vínculos">
          <ul className={styles.cards}>
            {units.map(({ link, unit }) => (
              <LinkUnit key={link.variation_id} link={link} unit={unit} itemId={itemId} canLink={canLink} onWritten={handleWritten} />
            ))}
          </ul>
        </Section>
      )}
    </>
  );
}
