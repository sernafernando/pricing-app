import { formatAmount } from '../../../utils/ventasMlFormat';
import { resolvePromoName } from '../../promociones/resolvePromoName';
import { promoDisplayPrice } from '../../promociones/promoDisplayPrice';
import SellInOutMarkupExtra from '../../promociones/SellInOutMarkupExtra';
import { SLOT_BADGE, dateRange, markupTone, pct, shares } from './mejoresCandidatasHelpers';
import promoStyles from '../../promociones/promociones.module.css';
import styles from './panel.module.css';

/** A figure's runs, each on one line, separated by a space where the line may break. */
function Runs({ runs }) {
  return runs.map((run, index) => (
    <span key={index}>
      {index > 0 && ' '}
      <span className={styles.mejoresNowrap}>{run}</span>
    </span>
  ));
}

/** The figures every row shows, the applied promo and each candidate alike, so they compare like for like. */
export function PromoFigures({ price, markup, sellInOut, sharesText, dates, delta, deltaLabel }) {
  return (
    <>
      <span className={styles.mejoresFigure}>
        <span className={styles.mejoresEyebrow}>Precio</span>
        <span className={`${styles.mejoresValue} ${styles.mejoresNowrap}`}>{price != null ? `$ ${formatAmount(price)}` : '—'}</span>
      </span>
      <span className={styles.mejoresFigure}>
        <span className={styles.mejoresEyebrow}>Markup</span>
        <span className={`${styles.mejoresValue} ${styles.mejoresNowrap} ${markupTone(markup)}`}>{markup != null ? pct(markup) : '—'}</span>
        <SellInOutMarkupExtra value={sellInOut} format={pct} />
        {delta && (
          <span className={styles.mejoresDelta} aria-label={`${delta} ${deltaLabel}`}>
            <span className={styles.mejoresNowrap}>{delta}</span> {deltaLabel}
          </span>
        )}
      </span>
      <span className={styles.mejoresFigure}>
        <span className={styles.mejoresEyebrow}>Vend. / ML</span>
        <span className={styles.mejoresValue}>
          <Runs runs={sharesText} />
        </span>
      </span>
      <span className={styles.mejoresFigure}>
        <span className={styles.mejoresEyebrow}>Vigencia</span>
        <span className={styles.mejoresValue}>
          <Runs runs={dates} />
        </span>
      </span>
    </>
  );
}

export function AppliedOrSaleCard({
  applied,
  baselinePrice,
  baselineMarkup,
  baselineSellInOut,
}) {
  if (applied) {
    return (
      <li className={`${styles.mejoresCard} ${styles.mejoresCardApplied}`} role="group" aria-label="Promo aplicada">
        <span className={styles.mejoresHead}>
          <span className={`${promoStyles.badge} ${SLOT_BADGE[applied.promotion_type] || promoStyles.badgeTypeNeutral}`}>
            {applied.promotion_type}
          </span>
          <span className={styles.mejoresMain}>
            <span className={styles.mejoresEyebrow}>Promo aplicada</span>
            <span className={styles.mejoresName}>{resolvePromoName(applied) || applied.promotion_id}</span>
          </span>
        </span>
        <PromoFigures
          price={promoDisplayPrice(applied)}
          markup={applied.nuestro_markup}
          sellInOut={applied.markup_sell_in_out}
          sharesText={shares(applied)}
          dates={dateRange(applied)}
        />
      </li>
    );
  }
  return (
    <li className={`${styles.mejoresCard} ${styles.mejoresCardApplied}`} role="group" aria-label="Sin promo aplicada">
      <span className={styles.mejoresHead}>
        <span className={`${promoStyles.badge} ${promoStyles.badgeTypeNeutral}`}>Actual</span>
        <span className={styles.mejoresMain}>
          <span className={styles.mejoresEyebrow}>Sin promo aplicada</span>
          <span className={styles.mejoresName}>Precio de venta actual</span>
        </span>
      </span>
      <PromoFigures
        price={baselinePrice != null && Number.isFinite(Number(baselinePrice)) ? Number(baselinePrice) : null}
        markup={baselineMarkup}
        sellInOut={baselineSellInOut}
        sharesText={['—']}
        dates={['—']}
      />
    </li>
  );
}
