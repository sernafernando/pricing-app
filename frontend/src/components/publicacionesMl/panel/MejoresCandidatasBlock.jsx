import { Sparkles } from 'lucide-react';
import { formatAmount } from '../../../utils/ventasMlFormat';
import { resolvePromoName } from '../../promociones/resolvePromoName';
import { promoDisplayPrice } from '../../promociones/promoDisplayPrice';
import PromoApplyControl from '../../promociones/PromoApplyControl';
import { sellInOutText } from '../../promociones/sellInOutMarkup';
import { CHOOSER_SLOT_LABELS, slotEntries } from './pickPonerPreciosPromos';
import { AppliedOrSaleCard, PromoFigures } from './MejoresCandidatasFigures';
import {
  SLOT_BADGE,
  appliedCleanly,
  dateRange,
  markupDelta,
  markupTone,
  pct,
  shares,
} from './mejoresCandidatasHelpers';
import { useMejoresCandidatas } from './useMejoresCandidatas';
import { useMonopolioC6 } from './useMonopolioC6';
import MonopolioC6Block from './MonopolioC6Block';
import promoStyles from '../../promociones/promociones.module.css';
import styles from './panel.module.css';

/**
 * The best candidate per writable MeLi type for a pub already flagged hay_mejores, as cards.
 * Mount only when the operator can write promos (discard/apply need it).
 * "Aplicar sugerencia" is the row's PromoApplyControl (same confirmation, guards and body; a
 * LIGHTNING opens its irreversible-offer card with the stock prefilled at ML's minimum);
 * `onLeavePub` runs only after a clean apply; without it, a clean apply reloads the candidates
 * so the applied promo drops out. `onSuggested(ids)` reports the suggested promotion ids so the
 * Promos tab can mark them. Calls onUnavailable only when baseline markup cannot be computed
 * (optional parent signal). A hard load failure stays mounted with the error and
 * "Descartar sugerencia" and does not call onUnavailable. MODO unlocks Nuevo precio only via
 * onDismissed (Descartar), so neither path can hide the failure by unmounting early.
 */
export default function MejoresCandidatasBlock({
  itemId,
  baselinePrice,
  onWritten,
  onLeavePub,
  onDismissed,
  onUnavailable,
  onSuggested,
}) {
  const {
    loading,
    slots,
    baselineMarkup,
    baselineSellInOut,
    applied,
    unavailable,
    message,
    descartando,
    discard,
    bumpReload,
  } = useMejoresCandidatas({
    itemId,
    baselinePrice,
    onWritten,
    onDismissed,
    onUnavailable,
    onSuggested,
  });
  const { loading: monopolioLoading, oportunidad: monopolio, error: monopolioError } = useMonopolioC6(itemId);

  const entries = slotEntries(slots);
  const showClassic = entries.length > 0;
  const showMonopolio = Boolean(monopolio);
  const showEmptyClassic = !showClassic && !showMonopolio && !monopolioLoading;
  const lead = (extra) => (
    <p className={styles.ponerPreciosMejoresLead}>
      <Sparkles size={14} aria-hidden="true" className={styles.mejoresIcon} />
      <span>
        Hay candidatas mejores que el precio vigente en MeLi.
        {extra}
      </span>
    </p>
  );
  const vigente =
    baselineMarkup != null ? (
      <>
        {' '}
        Markup vigente ~ <span className={markupTone(baselineMarkup)}>{formatAmount(baselineMarkup)}%</span>
        {sellInOutText(baselineSellInOut, pct)}.
      </>
    ) : null;
  // What each candidate is compared against: the applied promo, else today's sale price with its markup.
  const statusQuo = applied
    ? { nuestro_markup: applied.nuestro_markup, markup_sell_in_out: applied.markup_sell_in_out }
    : { nuestro_markup: baselineMarkup, markup_sell_in_out: baselineSellInOut };
  const deltaLabel = applied ? 'vs aplicada' : 'vs actual';

  const discardButton = (
    <button type="button" className="btn-tesla ghost sm" disabled={descartando} onClick={discard}>
      {descartando ? 'Descartando…' : 'Descartar sugerencia'}
    </button>
  );

  return (
    <div className={styles.ponerPreciosMejores} role="region" aria-label="Candidatas mejores">
      {loading ? (
        <p className={styles.ponerPreciosOk} role="status">
          Cargando candidatas…
        </p>
      ) : unavailable ? (
        <>
          {lead(null)}
          <span>{discardButton}</span>
        </>
      ) : (
        <>
          {showClassic && (
            <>
              {lead(vigente)}
              <ul className={styles.ponerPreciosChoices}>
                <AppliedOrSaleCard
                  applied={applied}
                  baselinePrice={baselinePrice}
                  baselineMarkup={baselineMarkup}
                  baselineSellInOut={baselineSellInOut}
                />
                {entries.map(([slot, promo], index) => {
                  const price = promoDisplayPrice(promo);
                  return (
                    <li
                      key={slot}
                      className={styles.mejoresCard}
                      role="group"
                      aria-label={`Promo sugerida ${CHOOSER_SLOT_LABELS[slot] || slot}`}
                    >
                      <span className={styles.mejoresHead}>
                        <span className={`${promoStyles.badge} ${SLOT_BADGE[slot] || promoStyles.badgeTypeNeutral}`}>
                          {CHOOSER_SLOT_LABELS[slot] || slot}
                        </span>
                        <span className={styles.mejoresMain}>
                          <span className={styles.mejoresEyebrow}>Promo sugerida</span>
                          <span className={styles.mejoresName}>{resolvePromoName(promo) || promo.promotion_id}</span>
                        </span>
                      </span>
                      <PromoFigures
                        price={price}
                        markup={promo.nuestro_markup}
                        sellInOut={promo.markup_sell_in_out}
                        sharesText={shares(promo)}
                        dates={dateRange(promo)}
                        delta={markupDelta(promo, statusQuo)}
                        deltaLabel={deltaLabel}
                      />
                      <span className={styles.mejoresActions}>
                        {index === 0 && discardButton}
                        <PromoApplyControl
                          mla={itemId}
                          promotion={promo}
                          label="Aplicar sugerencia"
                          initialStock={slot === 'LIGHTNING' ? promo.payload?.stock?.min : undefined}
                          onApplied={(data) => {
                            onWritten?.();
                            if (!appliedCleanly(promo, data)) return;
                            if (onLeavePub) onLeavePub();
                            else bumpReload();
                          }}
                          onReloadNeeded={onWritten}
                        />
                      </span>
                    </li>
                  );
                })}
              </ul>
            </>
          )}
          {showMonopolio && <MonopolioC6Block oportunidad={monopolio} />}
          {showEmptyClassic && (
            <>
              <p className={styles.ponerPreciosOk} role="status">
                No hay candidatas aplicables (SMART, DEAL, PRE_NEGOTIATED, PRICE_MATCHING, LIGHTNING, SELLER_CAMPAIGN
                Premium del mes) que superen el precio vigente
                {baselineMarkup != null
                  ? ` (markup vigente ~ ${formatAmount(baselineMarkup)}%${sellInOutText(baselineSellInOut, pct)})`
                  : ''}
                . Podés descartar el aviso si quedó desactualizado.
              </p>
              <span>{discardButton}</span>
            </>
          )}
          {showMonopolio && !showClassic && <span>{discardButton}</span>}
        </>
      )}
      {monopolioError && (
        <p className={styles.ponerPreciosError} role="status">
          {monopolioError}
        </p>
      )}
      {message && (
        <p className={message.tone === 'error' ? styles.ponerPreciosError : styles.ponerPreciosOk} role="status">
          {message.text}
        </p>
      )}
    </div>
  );
}
