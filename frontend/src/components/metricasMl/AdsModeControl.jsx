import SegmentedControl from './SegmentedControl';
import { ADS_MODE_HINTS, ADS_MODE_OPTIONS } from '../../utils/metricasMlAds';
import styles from './AdsModeControl.module.css';

// A `tplink.solo` user's board has Total TP, not Total Gauss: the ads come off Total TP (backend P4).
const TP_SOLO_HINTS = {
  off: 'No se resta publicidad de Total TP ni del markup.',
  mla: 'Resta del Total TP y del markup solo los Ads atribuidos a cada publicación.',
  todo: 'Resta del Total TP y del markup los Ads de cada publicación y además Display, Brand Ads y Ads sin producto.',
};

/**
 * "Publicidad: Sin publicidad | Restar Ads de publicaciones | Restar toda la
 * publicidad" -- the three positions of the ads toggle, with a line on what
 * the chosen one subtracts. Rendered only for `ml_metricas.ver_ganancia`.
 */
export default function AdsModeControl({ value, onChange, tpSolo = false }) {
  return (
    <div className={styles.wrapper}>
      <div className={styles.row}>
        <span className={styles.label}>Publicidad:</span>
        <SegmentedControl label="Publicidad" options={ADS_MODE_OPTIONS} value={value} onChange={onChange} />
      </div>
      <p className={styles.hint}>{(tpSolo ? TP_SOLO_HINTS : ADS_MODE_HINTS)[value]}</p>
    </div>
  );
}
