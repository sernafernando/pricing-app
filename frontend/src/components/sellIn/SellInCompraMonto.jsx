import { formatMonto } from './sellInFormat';
import { equivalenteUsd } from './sellInMoneda';
import styles from './SellInCompraMonto.module.css';

/**
 * A sell-in purchase amount as loaded, in the purchase's currency (its invoice's, sell in incident 2026-11-24 S3), with
 * its USD equivalent at the purchase's rate below when it is in ARS (#2381 precedent, owner L35).
 *
 * @param {object} props
 * @param {string|number|null} props.monto
 * @param {string} props.moneda
 * @param {string|number|null} [props.tipoCambio]
 */
export default function SellInCompraMonto({ monto, moneda, tipoCambio }) {
  const usd = equivalenteUsd(monto, moneda, tipoCambio);
  if (!usd) return formatMonto(monto, moneda);
  return (
    <span className={styles.apilado}>
      <span>{formatMonto(monto, moneda)}</span>
      <span className={styles.secundario}>{usd}</span>
    </span>
  );
}
