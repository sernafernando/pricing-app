import { formatPppFecha } from '../hooks/useProductosOffsets';
import { sellInOrigen } from '../utils/sellInOrigen';
import styles from './CostoCell.module.css';

const isBlank = (value) => value === null || value === undefined;

function pppText(ppp) {
  if (!ppp) return 'sin PPP';
  const fecha = formatPppFecha(ppp.fecha);
  return `ppp: ${ppp.moneda ?? 'ARS'} $${ppp.costo?.toFixed(2)}${fecha ? ` (${fecha})` : ''}`;
}

/** The sell in figures in the cost's currency (backend `en_moneda_costo`); an older payload has only the ARS ones. */
function enMoneda(sellIn) {
  if (sellIn.moneda_costo === undefined) {
    return { moneda: 'ARS', costo: sellIn.costo, descuento: sellIn.descuento_unit };
  }
  return { moneda: sellIn.moneda_costo, costo: sellIn.costo_moneda, descuento: sellIn.descuento_unit_moneda };
}

function sellInTitle(sellIn, figures, format) {
  const lines = [];
  const enPesos = figures.moneda !== 'ARS';
  if (enPesos && !isBlank(sellIn.costo)) lines.push(`c/ sell in en pesos: ${format(sellIn.costo, 'ARS')}`);
  const descuento = isBlank(figures.descuento) ? 'pendiente' : format(figures.descuento, figures.moneda);
  const pesos = enPesos ? ` (${format(sellIn.descuento_unit, 'ARS')})` : '';
  lines.push(`Descuento de sell in por unidad: ${descuento}${pesos} · ${sellInOrigen(sellIn)}`);
  return lines;
}

/**
 * A product's unit cost in a list row (S10, S10b), on ONE line like the other cells: the cost in its own currency
 * (`moneda`) and, inline and small, the cost with sell in in that same currency, never in pesos for a USD cost (the
 * backend converts it back at the rate it converted the cost with). The PPP, the pesos figures, the discount and the
 * origin of the sell in go in the tooltip. `format(monto, moneda)` is the screen's own way to write an amount.
 * `ppp` undefined (not sent) leaves the PPP out of the tooltip; null reads "sin PPP".
 */
export default function CostoCell({ monto, moneda, ppp, sellInOut, format }) {
  const sellIn = sellInOut?.sell_in ?? null;
  const figures = sellIn ? enMoneda(sellIn) : null;
  const title = [];
  if (ppp !== undefined) title.push(pppText(ppp));
  if (sellIn) title.push(...sellInTitle(sellIn, figures, format));
  return (
    <span className={styles.cell} title={title.join('\n') || undefined}>
      {format(monto, moneda)}
      {sellIn && (
        <span className={styles.sellIn}>
          {` c/ sell in ${isBlank(figures.costo) ? 'pendiente' : format(figures.costo, figures.moneda)}`}
        </span>
      )}
    </span>
  );
}
