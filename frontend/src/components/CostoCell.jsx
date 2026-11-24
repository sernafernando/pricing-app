import { formatPppFecha } from '../hooks/useProductosOffsets';
import styles from './CostoCell.module.css';

function pppText(ppp) {
  if (!ppp) return 'sin PPP';
  const fecha = formatPppFecha(ppp.fecha);
  return `ppp: ${ppp.moneda ?? 'ARS'} $${ppp.costo?.toFixed(2)}${fecha ? ` (${fecha})` : ''}`;
}

/**
 * A product's unit cost in a list row (S10, S10b), on ONE line like the other cells: the cost in its own currency
 * (`moneda`), the PPP in the tooltip. No cost with sell in (costo SI T5 PR B: costo SI already holds the sell in).
 * `format(monto, moneda)` is the screen's own way to write an amount. `ppp` undefined (not sent) leaves the tooltip
 * out; null reads "sin PPP".
 */
export default function CostoCell({ monto, moneda, ppp, format }) {
  return (
    <span className={styles.cell} title={ppp === undefined ? undefined : pppText(ppp)}>
      {format(monto, moneda)}
    </span>
  );
}
