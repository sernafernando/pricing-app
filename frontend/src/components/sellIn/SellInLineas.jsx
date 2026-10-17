import { FORMULA_LABELS, formatEntero, formatMonto } from './sellInFormat';
import styles from './SellInLineas.module.css';

/** The purchase's lines: what each one got and its unit cost before and after the sell in. */
export default function SellInLineas({ compra }) {
  const { moneda } = compra;
  return (
    <div className={styles.lines}>
      <table className={styles.linesTable}>
        <thead>
          <tr>
            <th>Producto</th>
            <th className={styles.num}>Unid.</th>
            <th className={styles.num}>Monto asignado</th>
            <th className={styles.num}>Costo antes</th>
            <th className={styles.num}>Costo después</th>
            <th className={styles.num}>Consumidas</th>
          </tr>
        </thead>
        <tbody>
          {compra.items.map((linea) => (
            <tr key={linea.id}>
              <td>
                <span>{linea.descripcion}</span> <span className={styles.mono}>{linea.codigo}</span>
              </td>
              <td className={styles.num}>{formatEntero(linea.cantidad)}</td>
              <td className={styles.num}>{formatMonto(linea.monto_asignado, moneda)}</td>
              <td className={`${styles.num} ${styles.before}`}>{formatMonto(linea.costo_base_unit, moneda)}</td>
              <td className={`${styles.num} ${styles.after}`}>{formatMonto(linea.costo_con_sell_in_unit, moneda)}</td>
              <td className={styles.num}>{formatEntero(linea.unidades_consumidas)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className={styles.note}>
        {FORMULA_LABELS[compra.formula] ?? compra.formula} · al consumirse las unidades el costo vuelve al normal.
      </p>
    </div>
  );
}
