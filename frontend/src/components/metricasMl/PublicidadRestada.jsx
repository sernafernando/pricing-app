import { ArrowRight, Info, WalletCards } from 'lucide-react';
import { Link } from 'react-router-dom';
import { adsModeNotice, waterfallLines } from '../../utils/metricasMlAds';
import { formatSignedMoney } from '../../utils/ventasMlTone';
import styles from './PublicidadRestada.module.css';

const CHIPS = {
  restado: 'Restado',
  aporte: 'Aporte',
  'no-restado': 'No restado',
};

/**
 * "Publicidad restada" (Stitch 5736acfc, owner-approved): what the board subtracted from Total Gauss and the markup,
 * line by line, from `kpis.ads.waterfall` -- the API computes every line on the basis it subtracts, so they add up
 * to the total. Above it, the notice when filters made "Restar toda" apply as "Restar Ads". Nothing with the toggle
 * off.
 */
export default function PublicidadRestada({ ads }) {
  if (!ads?.waterfall) return null;
  const w = ads.waterfall;
  const notice = adsModeNotice(ads);
  const lines = waterfallLines(w);
  const scale = Math.max(...lines.filter((l) => !l.subtotal).map((l) => Math.abs(l.amount)), 0);
  return (
    <div className={styles.stack}>
      {notice && (
        <div className={styles.notice} role="note">
          <Info size={14} aria-hidden="true" />
          <span>{notice.message}</span>
          <span className={styles.noticeChip}>{notice.chip}</span>
        </div>
      )}
      <section className={styles.card} aria-label="Publicidad restada">
        <header className={styles.header}>
          <h2 className={styles.title}>
            <WalletCards size={16} aria-hidden="true" /> Publicidad restada
          </h2>
          <Link className={styles.link} to="/ml-ads-aportes">
            Ver aportes <ArrowRight size={14} aria-hidden="true" />
          </Link>
        </header>
        <ul className={styles.lines}>
          {lines.map((line) => (
            <li key={line.key} className={styles.line} data-kind={line.subtotal ? 'subtotal' : line.chip}>
              <span className={styles.label}>{line.label}</span>
              <span className={styles.amount} data-money>
                {line.amount < 0 ? `- ${formatSignedMoney(-line.amount)}` : formatSignedMoney(line.amount)}
              </span>
              {line.chip ? <span className={styles.chip}>{CHIPS[line.chip]}</span> : <span />}
              {!line.subtotal && (
                <span className={styles.track} aria-hidden="true">
                  <span
                    className={styles.bar}
                    style={{ width: `${scale ? (Math.abs(line.amount) / scale) * 100 : 0}%` }}
                  />
                </span>
              )}
            </li>
          ))}
        </ul>
        <div className={styles.total}>
          <div>
            <span className={styles.totalLabel}>= Publicidad restada</span>
            <span className={styles.caption}>Se resta del Total Gauss y del markup</span>
          </div>
          <span className={styles.totalAmount} data-money>
            {formatSignedMoney(w.total)}
          </span>
        </div>
        <div className={styles.notes}>
          {w.no_campaign > 0 && (
            <p className={styles.note}>
              <Info size={14} aria-hidden="true" />
              <span>
                De Product Ads, <span data-money>{formatSignedMoney(w.no_campaign)}</span> son de anuncios sin campaña:
                ningún aporte puede cubrirlos.
              </span>
            </p>
          )}
          {/* As in Stitch 5736acfc: explains the OTHER position too, so it shows wherever the account lines do. */}
          {w.display_gross !== null && w.display_gross !== undefined && (
            <p className={styles.subnote}>
              En &quot;Restar Ads&quot; solo se restan las líneas de Product Ads; Display y Brand Ads quedan como &quot;No
              restado&quot;.
            </p>
          )}
        </div>
      </section>
    </div>
  );
}
