import { Megaphone } from 'lucide-react';
import { adsCoverageNote } from '../../utils/metricasMlAds';
import { formatPct, formatUnits } from '../../utils/metricasMlFormat';
import { formatSignedMoney } from '../../utils/ventasMlTone';
import styles from './AdsKpiBlock.module.css';

const TWO_DECIMALS = new Intl.NumberFormat('es-AR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const ratio = (value) => (value === null || value === undefined ? '—' : TWO_DECIMALS.format(value));

function Metric({ label, value, hint, money }) {
  return (
    <div className={styles.metric}>
      <span className={styles.label}>{label}</span>
      <span className={styles.value} data-money={money ? '' : undefined}>
        {value}
      </span>
      {hint && <span className={styles.hint}>{hint}</span>}
    </div>
  );
}

/**
 * The ads of the period (`kpis.ads`): what was invested, what the ads sold and the ratios. Context only: the
 * ratios use the API cost basis and are never tied to specific sales. Nothing while the toggle is off.
 */
export default function AdsKpiBlock({ ads }) {
  if (!ads) return null;
  const note = adsCoverageNote(ads.coverage);
  const attributed = ads.direct_amount + ads.indirect_amount;
  return (
    <section className={styles.block} aria-label="Publicidad (ML Ads)">
      <header className={styles.header}>
        <h2 className={styles.title}>
          <Megaphone size={14} aria-hidden="true" /> Publicidad (ML Ads)
        </h2>
        {note && (
          <span className={styles.coverage} data-tone={note.tone}>
            {note.text}
          </span>
        )}
      </header>
      <div className={styles.grid}>
        <Metric label="Inversión" value={formatSignedMoney(ads.cost_total)} hint="sin IVA" money />
        {/* Brand contributions (ml-ads-brand-contribution S9): the part of the cost the brands pay, not subtracted. */}
        {Boolean(ads.contribution) && (
          <Metric label="Aporte de marcas" value={formatSignedMoney(ads.contribution)} hint="no se descuenta" money />
        )}
        <Metric
          label="Ventas por publicidad"
          value={formatSignedMoney(attributed)}
          hint={`Directas ${formatSignedMoney(ads.direct_amount)} · Ind. ${formatSignedMoney(ads.indirect_amount)}`}
          money
        />
        <Metric label="ACOS" value={formatPct(ads.acos_pct)} />
        <Metric label="ROAS" value={ratio(ads.roas)} />
        <Metric label="TACOS" value={formatPct(ads.tacos_pct)} hint="sobre ventas totales" />
        <Metric label="Ventas orgánicas" value={formatSignedMoney(ads.organic_amount)} hint="contexto general" money />
        <Metric label="CPC" value={formatSignedMoney(ads.cpc)} money />
        <Metric label="CTR" value={formatPct(ads.ctr_pct)} />
        <Metric label="Impresiones" value={formatUnits(ads.impressions)} />
        <Metric label="Clics" value={formatUnits(ads.clicks)} />
      </div>
    </section>
  );
}
