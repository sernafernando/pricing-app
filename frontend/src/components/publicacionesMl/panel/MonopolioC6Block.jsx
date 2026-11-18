import { TrendingUp } from 'lucide-react';
import { formatAmount } from '../../../utils/ventasMlFormat';
import PromoApplyControl from '../../promociones/PromoApplyControl';
import styles from './panel.module.css';

/**
 * C6 raise-price suggestion block (below classic candidatas when both apply).
 * When not solo_via_promo and a Premium candidate is available, offers editable apply at precio_objetivo.
 */
export default function MonopolioC6Block({
  oportunidad,
  markupPct = null,
  premiumPromo = null,
  itemId = null,
  applyFailMessage = null,
  onWritten,
  onLeavePub,
}) {
  if (!oportunidad) return null;
  const raiseBy = Math.max(0, oportunidad.precio_objetivo - oportunidad.our_price);
  const markupLabel =
    markupPct != null && Number.isFinite(Number(markupPct))
      ? ` con ${Number(markupPct).toFixed(1)}% de markup`
      : '';
  if (oportunidad.solo_via_promo) {
    return (
      <div className={styles.ponerPreciosMejores} role="region" aria-label="Oportunidad de monopolio">
        {applyFailMessage && (
          <p className={styles.ponerPreciosWarn} role="status">
            {applyFailMessage}
          </p>
        )}
        <p className={styles.ponerPreciosMejoresLead}>
          <TrendingUp size={14} aria-hidden="true" className={styles.mejoresIcon} />
          <span>
            C6 (solo vía promo): hay gap para subir ~${formatAmount(raiseBy)}
            {markupLabel}, pero hace falta una promo que asista. Sin esa promo no se sugiere Premium
            editable.
          </span>
        </p>
      </div>
    );
  }
  const premiumForApply =
    premiumPromo && Number.isFinite(Number(oportunidad.precio_objetivo))
      ? {
          ...premiumPromo,
          // Prefill the range input at the monopoly target (PM can still edit).
          price: oportunidad.precio_objetivo,
          suggested_discounted_price: oportunidad.precio_objetivo,
          deal_price: oportunidad.precio_objetivo,
        }
      : null;
  return (
    <div className={styles.ponerPreciosMejores} role="region" aria-label="Oportunidad de monopolio">
      {applyFailMessage && (
        <p className={styles.ponerPreciosWarn} role="status">
          {applyFailMessage}
        </p>
      )}
      <p className={styles.ponerPreciosMejoresLead}>
        <TrendingUp size={14} aria-hidden="true" className={styles.mejoresIcon} />
        <span>
          Tenés oportunidad de aumentar el precio en ${formatAmount(raiseBy)}
          {markupLabel} y mantener tu posición en el catálogo (2º a $
          {formatAmount(oportunidad.segundo_precio)}; objetivo $
          {formatAmount(oportunidad.precio_objetivo)}).
        </span>
      </p>
      {premiumForApply && itemId ? (
        <span className={styles.mejoresActions}>
          <PromoApplyControl
            mla={itemId}
            promotion={premiumForApply}
            label="Aplicar Premium al objetivo"
            onApplied={() => {
              onWritten?.();
              onLeavePub?.();
            }}
            onReloadNeeded={onWritten}
          />
        </span>
      ) : (
        <p className={styles.ponerPreciosOk} role="status">
          Gap actual ~ ${formatAmount(oportunidad.gap)}.
          {premiumPromo
            ? ' Podés apuntar Premium cerca del objetivo (editable) y aplicar.'
            : ' No hay Premium del mes disponible para aplicar desde acá; podés subir el precio desde Promos.'}
        </p>
      )}
    </div>
  );
}
