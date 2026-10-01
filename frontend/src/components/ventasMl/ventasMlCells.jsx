import styles from '../../pages/VentasML.module.css';
import CopyButton from './CopyButton';
import { formatListMoney, formatMarkup, markupTone } from '../../utils/ventasMlTone';

/**
 * Small cell pieces of the Ventas ML table (`ventasMlColumns.jsx`), in their
 * own module so that one keeps exporting only its column list
 * (react-refresh/only-export-components).
 */

export function ShippingId({ value }) {
  return (
    // The row itself opens the panel on click; copying must not. (Only a
    // click guard: the copy control inside is the real, focusable button.)
    <span className={styles.shippingId} onClick={(e) => e.stopPropagation()}>
      <span className={styles.mono} title="ID de envío de Mercado Libre">
        {value}
      </span>
      <CopyButton value={value} label="Copiar ID de envío" compact />
    </span>
  );
}

export function Money({ value, currencyId, tone }) {
  const toneClass = tone ? styles[`money_${tone}`] : '';
  return (
    <span className={`${styles.amount} ${toneClass || ''}`.trim()} data-money>
      {formatListMoney(value, currencyId)}
    </span>
  );
}

export function MarkupChip({ value }) {
  const tone = markupTone(value);
  if (tone === null) return null;
  return (
    <span className={`${styles.markupChip} ${styles[`markup_${tone}`]}`} title="Markup real de la venta">
      {formatMarkup(value)}
    </span>
  );
}

export function ProvisionalPill({ falta }) {
  return (
    <span
      className={styles.provisionalPill}
      data-provisional
      title={`Calculado sin ${(falta || 'Envío Flex').toLowerCase()}: todavía no se cargó la etiqueta de envío.`}
    >
      Provisorio
    </span>
  );
}
