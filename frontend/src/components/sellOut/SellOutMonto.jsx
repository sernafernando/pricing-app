import { formatMonto } from '../sellIn/sellInFormat';
import styles from './SellOutReparto.module.css';

/** An amount in the campaign currency; a negative one (a deduction from profit, S35) is highlighted. */
export default function SellOutMonto({ value, moneda }) {
  const negativo = Number(value) < 0;
  return (
    <span className={negativo ? styles.deduccion : undefined} data-deduccion={negativo ? 'true' : undefined}>
      {formatMonto(value, moneda)}
    </span>
  );
}
