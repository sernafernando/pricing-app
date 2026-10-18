import StatusPill from '../kit/StatusPill';
import { SKU_DIVERGENCE_KINDS } from './skuDivergence';
import styles from './cells.module.css';

const productText = (product) => [product?.codigo, product?.descripcion].filter(Boolean).join(' ');

function Line({ name, value, code }) {
  const label = `${name}: ${value}`;
  return (
    <span className={styles.divergenceLine} aria-label={label} title={label}>
      <span className={styles.divergenceName}>{name}:</span> {code ? <span className={styles.code}>{value}</span> : value}
    </span>
  );
}

/**
 * Why the publication's SKU disagrees with its linked product, so the team can fix the SKU in Mercado Libre:
 * the kind, the SKU as Mercado Libre has it, the product that SKU names and the product the publication is
 * linked to. "—" when the SKU agrees.
 */
export default function SkuDivergenceCell({ item }) {
  const divergence = item.sku_divergence;
  const kind = SKU_DIVERGENCE_KINDS[divergence?.kind];
  if (!kind) return <span className={styles.empty}>—</span>;
  return (
    <div className={styles.stack}>
      <StatusPill tone={kind.tone}>{kind.label}</StatusPill>
      <Line name="SKU en Mercado Libre" value={item.seller_sku || 'Sin SKU'} code={Boolean(item.seller_sku)} />
      <Line name="Producto por SKU" value={productText(divergence) || 'ninguno'} />
      <Line name="Producto vinculado" value={productText(item.link) || 'sin datos'} />
    </div>
  );
}
