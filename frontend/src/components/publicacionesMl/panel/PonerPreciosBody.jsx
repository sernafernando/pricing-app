import { useState } from 'react';
import { formatAmount } from '../../../utils/ventasMlFormat';
import { parsePrecioInput } from '../../../utils/precioInput';
import { publicationListLabel } from '../../../constants/mlPublicationTypes';
import { LISTS, writePrice, errorText } from '../../pricing/priceWrites';
import { promocionesAPI } from '../../../services/api';
import { resolvePromoName } from '../../promociones/resolvePromoName';
import { promoDisplayPrice } from '../../promociones/promoDisplayPrice';
import ModalTesla, { ModalFooterButtons } from '../../ModalTesla';
import {
  enrollBodyForPromo,
  listRowForPricelist,
  pickPonerPreciosPromos,
} from './pickPonerPreciosPromos';
import styles from './panel.module.css';

const SLOT_LABELS = { smart: 'SMART', deal: 'DEAL', premium: 'Premium' };

/** MODO PONER PRECIOS: Enter writes Pricing, then PM picks exactly one promo. */
export default function PonerPreciosBody({
  detail,
  itemId,
  canEditPrice = false,
  canWritePromos = false,
  onWritten,
  onLeavePub,
}) {
  const row = detail?.row;
  const price = row?.price;
  const product = detail?.product;
  const productId = product?.item_id ?? row?.link?.producto_item_id;

  const [draft, setDraft] = useState(price?.amount != null ? String(price.amount) : '');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState(null);
  const [suggestions, setSuggestions] = useState(null);
  const [typedPrice, setTypedPrice] = useState(null);
  const [baselineMarkup, setBaselineMarkup] = useState(null);
  const [enrolling, setEnrolling] = useState(false);

  const closeSuggestions = () => {
    if (!enrolling) setSuggestions(null);
  };

  const runEnter = async () => {
    setMessage(null);
    if (!canEditPrice) {
      setMessage({ tone: 'error', text: 'No tenés permiso para editar el precio.' });
      return;
    }
    const precio = parsePrecioInput(draft);
    if (precio == null) {
      setMessage({ tone: 'error', text: 'Ingresá un precio válido.' });
      return;
    }
    if (productId == null) {
      setMessage({ tone: 'error', text: 'La publicación no tiene producto vinculado.' });
      return;
    }
    const listRow = listRowForPricelist(price?.pricelist_id, LISTS);
    if (!listRow) {
      setMessage({ tone: 'error', text: 'No se reconoce la lista ERP de esta publicación.' });
      return;
    }

    setBusy(true);
    try {
      await writePrice(listRow, productId, precio, product ?? {});
      onWritten?.();
      setTypedPrice(precio);
      try {
        const res = await promocionesAPI.getMarkupParaPrecio(itemId, precio);
        setBaselineMarkup(res?.data?.nuestro_markup ?? null);
      } catch {
        setBaselineMarkup(null);
      }
      if (!canWritePromos) {
        setMessage({ tone: 'ok', text: 'Precio guardado en Pricing. Sin permiso para activar promos.' });
        return;
      }
      const promoRes = await promocionesAPI.getPromocionesItem(itemId);
      const promotions = promoRes?.data?.promotions ?? promoRes?.data?.promociones ?? [];
      const picked = pickPonerPreciosPromos(promotions);
      if (!picked.smart && !picked.deal && !picked.premium) {
        setMessage({ tone: 'ok', text: 'Precio guardado. No hay candidatas SMART / DEAL / Premium este mes.' });
        return;
      }
      setSuggestions(picked);
    } catch (err) {
      setMessage({ tone: 'error', text: errorText(err, 'No se pudo guardar el precio.') });
    } finally {
      setBusy(false);
    }
  };

  const acceptSlot = async (slot) => {
    const promo = suggestions?.[slot];
    if (!promo || enrolling) return;
    setEnrolling(true);
    setMessage(null);
    try {
      await promocionesAPI.postPromocionItem(itemId, enrollBodyForPromo(promo));
      setSuggestions(null);
      onWritten?.();
      onLeavePub?.();
    } catch (err) {
      setMessage({
        tone: 'error',
        text: errorText(
          err,
          'El precio ya está guardado en Pricing, pero no se pudo activar la promoción.',
        ),
      });
      setEnrolling(false);
    }
  };

  const slots = suggestions
    ? [
        ['smart', suggestions.smart],
        ['deal', suggestions.deal],
        ['premium', suggestions.premium],
      ].filter(([, promo]) => promo)
    : [];

  return (
    <div className={styles.ponerPreciosBody}>
      <dl className={styles.ponerPreciosFacts}>
        <div>
          <dt>Lista</dt>
          <dd>{publicationListLabel(price) ?? '—'}</dd>
        </div>
        <div>
          <dt>Precio actual</dt>
          <dd>{price?.amount != null ? formatAmount(price.amount) : '—'}</dd>
        </div>
        {row?.link?.codigo && (
          <div>
            <dt>Código</dt>
            <dd>{row.link.codigo}</dd>
          </div>
        )}
      </dl>
      <label className={styles.ponerPreciosField}>
        <span>Nuevo precio</span>
        <input
          type="text"
          inputMode="decimal"
          className={styles.ponerPreciosInput}
          value={draft}
          disabled={!canEditPrice || busy}
          aria-label="Nuevo precio"
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key !== 'Enter' || busy) return;
            e.preventDefault();
            e.stopPropagation();
            runEnter();
          }}
        />
      </label>
      {message && (
        <p className={message.tone === 'error' ? styles.ponerPreciosError : styles.ponerPreciosOk} role="status">
          {message.text}
        </p>
      )}
      <ModalTesla
        isOpen={Boolean(suggestions)}
        onClose={closeSuggestions}
        title="Elegí una promoción"
        subtitle={
          typedPrice != null
            ? `Precio en Pricing: $ ${formatAmount(typedPrice)}${
                baselineMarkup != null ? ` · markup ${formatAmount(baselineMarkup)}%` : ''
              }`
            : undefined
        }
        size="sm"
        closeOnOverlay={false}
        closeOnEsc={!enrolling}
        showCloseButton={!enrolling}
        footer={<ModalFooterButtons onCancel={closeSuggestions} cancelText="Cancelar" cancelDisabled={enrolling} />}
      >
        <ul className={styles.ponerPreciosChoices}>
          {slots.map(([slot, promo]) => (
            <li key={slot}>
              <button type="button" className="btn-tesla outline sm" disabled={enrolling} onClick={() => acceptSlot(slot)}>
                <span className={styles.ponerPreciosChoiceLabel}>{SLOT_LABELS[slot]}</span>
                <span className={styles.ponerPreciosChoiceMeta}>
                  {resolvePromoName(promo) || promo.promotion_id}
                  {promoDisplayPrice(promo) != null ? ` · $ ${formatAmount(promoDisplayPrice(promo))}` : ''}
                  {promo.nuestro_markup != null ? ` · markup ${formatAmount(promo.nuestro_markup)}%` : ''}
                </span>
              </button>
            </li>
          ))}
        </ul>
      </ModalTesla>
    </div>
  );
}
