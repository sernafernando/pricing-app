import { Check } from 'lucide-react';
import { unattributedLines } from '../../utils/metricasMlAds';
import { formatSignedMoney } from '../../utils/ventasMlTone';
import styles from './AdsUnattributedPanel.module.css';

/**
 * The ads no board row owns (`kpis.ads.unattributed`, sent only for the unfiltered view): Display, Brand Ads
 * and Product Ads of MLAs with no product. Shown apart, never spread across products, each marked with
 * whether it came off Total Gauss and markup.
 */
export default function AdsUnattributedPanel({ unattributed }) {
  if (!unattributed) return null;
  return (
    <section className={styles.panel} aria-label="Publicidad sin producto">
      <h2 className={styles.title}>Publicidad sin producto</h2>
      <p className={styles.subtitle}>Gasto sin publicación o producto asignado: se muestra aparte y nunca se reparte entre productos.</p>
      <table className={styles.table}>
        <thead>
          <tr>
            <th scope="col">Concepto</th>
            <th scope="col" className={styles.num}>Monto (sin IVA)</th>
            <th scope="col" className={styles.state}>Estado</th>
          </tr>
        </thead>
        <tbody>
          {unattributedLines(unattributed).map((line) => (
            <tr key={line.key}>
              <td>
                <strong>{line.label}</strong>
                <span className={styles.detail}>{line.detail}</span>
              </td>
              <td className={styles.num} data-money>
                {formatSignedMoney(line.amount)}
              </td>
              <td className={styles.state}>
                <span className={styles.chip} data-subtracted={line.subtracted}>
                  {line.subtracted && <Check size={12} aria-hidden="true" />}
                  {line.subtracted ? 'Restado' : 'No restado'}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
