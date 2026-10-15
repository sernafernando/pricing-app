import { Info } from 'lucide-react';
import { ADS_APPLIED_LABELS, adsModeNotice } from '../../utils/metricasMlAds';
import { formatSignedMoney } from '../../utils/ventasMlTone';
import styles from './AdsAppliedBanner.module.css';

/**
 * What the board did about ads, from `kpis.ads`: the amount subtracted and
 * the markup formula, plus -- when the view could not apply the position that
 * was asked for -- why, with the "Aplicado" chip. Nothing with the toggle off.
 */
export default function AdsAppliedBanner({ ads }) {
  if (!ads) return null;
  const notice = adsModeNotice(ads);
  return (
    <div className={styles.stack}>
      {notice && (
        <div className={styles.notice} role="note">
          <Info size={14} aria-hidden="true" />
          <span>{notice.message}</span>
          <span className={styles.chip}>{notice.chip}</span>
        </div>
      )}
      <div className={styles.banner} role="status">
        <span>
          Publicidad restada: <strong data-money>{formatSignedMoney(ads.subtracted_total)}</strong> (
          {ADS_APPLIED_LABELS[ads.applied]})
        </span>
        <code className={styles.formula}>Markup = (margen - publicidad) / costo</code>
      </div>
    </div>
  );
}
