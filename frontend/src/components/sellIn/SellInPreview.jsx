import { formatEntero, formatMonto, formatNumero } from './sellInFormat';
import styles from './SellInLineas.module.css';

/** The server's split (`POST /sell-in/compras/preview`): each line's share and its unit cost without and with the sell in. */
export default function SellInPreview({ preview }) {
  const { moneda, lineas, totales } = preview;
  const pct = (value) => (value === null || value === undefined ? '—' : `${formatNumero(value)} %`);
  // A % purchase (`tipo: 'porcentaje'`) shows each line's invoiced net, the base of its amount.
  const conBase = lineas.some((linea) => linea.base_facturada != null);
  return (
    <div className={styles.lines}>
      <table className={styles.linesTable} aria-label="Vista previa por ítem">
        <thead>
          <tr>
            <th>Producto</th>
            <th className={styles.num}>Unid.</th>
            {conBase && <th className={styles.num}>Base facturada</th>}
            <th className={styles.num}>Monto asignado</th>
            <th className={styles.num}>Costo antes</th>
            <th className={styles.num}>Costo después</th>
            <th className={styles.num}>%</th>
          </tr>
        </thead>
        <tbody>
          {lineas.map((linea) => (
            <tr key={linea.item_id}>
              <td>
                <span>{linea.descripcion}</span> <span className={styles.mono}>{linea.codigo}</span>
              </td>
              <td className={styles.num}>{formatEntero(linea.cantidad)}</td>
              {conBase && <td className={styles.num}>{formatMonto(linea.base_facturada, moneda)}</td>}
              <td className={styles.num}>{formatMonto(linea.monto_asignado, moneda)}</td>
              <td className={`${styles.num} ${styles.before}`}>{formatMonto(linea.costo_base_unit, moneda)}</td>
              <td className={`${styles.num} ${styles.after}`}>{formatMonto(linea.costo_con_sell_in_unit, moneda)}</td>
              <td className={styles.num}>{pct(linea.porcentaje)}</td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr>
            <th scope="row">Total</th>
            <td className={styles.num}>{formatEntero(totales.cantidad)}</td>
            {conBase && <td />}
            <td className={styles.num}>{formatMonto(totales.monto_asignado_total, moneda)}</td>
            <td className={`${styles.num} ${styles.before}`}>{formatMonto(totales.costo_base_total, moneda)}</td>
            <td className={`${styles.num} ${styles.after}`}>{formatMonto(totales.costo_con_sell_in_total, moneda)}</td>
            <td className={styles.num}>{pct(totales.porcentaje)}</td>
          </tr>
        </tfoot>
      </table>
    </div>
  );
}
