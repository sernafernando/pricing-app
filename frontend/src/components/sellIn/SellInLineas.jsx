import { FORMULA_LABELS, formatEntero } from './sellInFormat';
import SellInCompraMonto from './SellInCompraMonto';
import styles from './SellInLineas.module.css';

const COLUMNAS = ['Unid.', 'Costo antes', 'Sell in unit.', 'Costo después', 'Monto asignado (total línea)'];

/**
 * The purchase's lines. The unit columns read left to right: the unit cost before the sell in, the unit sell in and the
 * unit cost after it (before - sell in). The line's amount is its TOTAL (units x unit sell in), last and labelled so,
 * never next to a unit cost where it reads as "double" (sell in incident 2026-11-24 S5).
 *
 * Each line is its own row group: the product (whatever its description's length) heads it on a full-width row and
 * its numbers go on the row below, so the five amounts fit the side panel (~524 px at 1440 with the sidebar open)
 * without scrolling the total off-screen.
 */
export default function SellInLineas({ compra }) {
  // Every amount of an ARS line goes with its USD equivalent below, at the purchase's rate (owner L35).
  const { moneda, tipo_cambio: tipoCambio } = compra;
  return (
    <div className={styles.lines}>
      <table className={styles.linesTable}>
        <thead>
          <tr>
            {COLUMNAS.map((columna) => (
              <th key={columna} scope="col" className={styles.num}>
                {columna}
              </th>
            ))}
          </tr>
        </thead>
        {compra.items.map((linea) => (
          <tbody key={linea.id} className={styles.linea}>
            <tr>
              <th scope="rowgroup" colSpan={COLUMNAS.length} className={styles.producto}>
                <span>{linea.descripcion}</span> <span className={styles.mono}>{linea.codigo}</span>
              </th>
            </tr>
            <tr>
              <td className={styles.num}>{formatEntero(linea.cantidad)}</td>
              <td className={styles.num}>
                <SellInCompraMonto
                  monto={linea.costo_base_unit}
                  moneda={moneda}
                  tipoCambio={tipoCambio}
                  className={styles.before}
                />
              </td>
              <td className={styles.num}>
                <SellInCompraMonto monto={linea.descuento_unit} moneda={moneda} tipoCambio={tipoCambio} />
              </td>
              <td className={styles.num}>
                <SellInCompraMonto
                  monto={linea.costo_con_sell_in_unit}
                  moneda={moneda}
                  tipoCambio={tipoCambio}
                  className={styles.after}
                />
              </td>
              <td className={styles.num}>
                <SellInCompraMonto monto={linea.monto_asignado} moneda={moneda} tipoCambio={tipoCambio} />
              </td>
            </tr>
          </tbody>
        ))}
      </table>
      <p className={styles.note}>
        {FORMULA_LABELS[compra.formula] ?? compra.formula} · el costo después entra en el costo SI del producto.
      </p>
    </div>
  );
}
