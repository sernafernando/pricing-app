import { formatPppFecha } from '../hooks/useProductosOffsets';
import styles from './CostoCell.module.css';

const isBlank = (value) => value === null || value === undefined;

/**
 * The tooltip of a costo SI (interfaz §6): since when the step applies, or that the list cost stands in (Q1), and
 * for a cost in another currency its pesos with the rate and that rate's date. A USD cost without a rate says its
 * pesos are unknown: never 0 (interfaz §7).
 */
function costoSiTitle(costoSi, format) {
  const lines = [];
  if (costoSi.fuente === 'lista') {
    lines.push('Sin costo SI: es el costo de lista');
  } else {
    const desde = formatPppFecha(costoSi.desde);
    lines.push(desde ? `Costo SI desde ${desde}` : 'Costo SI');
  }
  if (costoSi.moneda !== 'ARS') {
    if (isBlank(costoSi.costo_ars)) {
      lines.push('Sin tipo de cambio: no se sabe en pesos');
    } else {
      const fecha = formatPppFecha(costoSi.tipo_cambio_fecha);
      const tc = isBlank(costoSi.tipo_cambio) ? '' : ` (TC ${costoSi.tipo_cambio}${fecha ? ` del ${fecha}` : ''})`;
      lines.push(`En pesos: ${format(costoSi.costo_ars, 'ARS')}${tc}`);
    }
  }
  return lines.join('\n');
}

/**
 * The costo SI column next to the list cost (S13 "two columns", T3 PR 3): the product's `costo_si` in its own
 * currency on one line, like `CostoCell`; "lista" beside it when the list cost stands in. `format(monto, moneda)` is
 * the screen's own way to write an amount. No costo SI at all reads "—".
 */
export default function CostoSiCell({ costoSi, format }) {
  if (!costoSi || isBlank(costoSi.costo)) return <span className="text-muted">—</span>;
  return (
    <span className={styles.cell} title={costoSiTitle(costoSi, format)}>
      {format(costoSi.costo, costoSi.moneda)}
      {costoSi.fuente === 'lista' && <span className={styles.sellIn}> lista</span>}
    </span>
  );
}
