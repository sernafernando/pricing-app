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
 * @param {string} [props.className] styles the amount itself (a struck-through cost before), never the USD line: a
 *   text decoration on the cell does not reach inside the stacked (inline-flex) amount.
 */
export default function SellInCompraMonto({ monto, moneda, tipoCambio, className }) {
  const usd = equivalenteUsd(monto, moneda, tipoCambio);
  const texto = formatMonto(monto, moneda);
  if (!usd) return className ? <span className={className}>{texto}</span> : texto;
  return (
    <span className={styles.apilado}>
      <span className={className}>{texto}</span>
      <span className={styles.secundario}>{usd}</span>
    </span>
  );
}
