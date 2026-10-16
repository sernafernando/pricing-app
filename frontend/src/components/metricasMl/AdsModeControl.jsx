import SegmentedControl from './SegmentedControl';
import { ADS_MODE_HINTS, ADS_MODE_OPTIONS } from '../../utils/metricasMlAds';
import styles from './AdsModeControl.module.css';

/**
 * "Publicidad: Sin publicidad | Restar Ads de publicaciones | Restar toda la
 * publicidad" -- the three positions of the ads toggle, with a line on what
 * the chosen one subtracts. Rendered only for `ml_metricas.ver_ganancia`.
 */
export default function AdsModeControl({ value, onChange }) {
  return (
    <div className={styles.wrapper}>
      <div className={styles.row}>
        <span className={styles.label}>Publicidad:</span>
        <SegmentedControl label="Publicidad" options={ADS_MODE_OPTIONS} value={value} onChange={onChange} />
      </div>
      <p className={styles.hint}>{ADS_MODE_HINTS[value]}</p>
    </div>
  );
}
