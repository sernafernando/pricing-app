import { useState } from 'react';
import { formatAmount } from '../../../utils/ventasMlFormat';
import { parsePrecioInput } from '../../../utils/precioInput';
import { publicationListLabel } from '../../../constants/mlPublicationTypes';
import { LISTS, writePrice, errorText } from '../../pricing/priceWrites';
import { promocionesAPI } from '../../../services/api';
import { LIGHTNING_IRREVERSIBLE_WARNING } from '../../promociones/applicablePromoTypes';
import { resolvePromoName } from '../../promociones/resolvePromoName';
import { promoDisplayPrice } from '../../promociones/promoDisplayPrice';
import { sellInOutText } from '../../promociones/sellInOutMarkup';
import ModalTesla, { ModalFooterButtons } from '../../ModalTesla';
import MejoresCandidatasBlock from './MejoresCandidatasBlock';
import {
  CHOOSER_SLOT_LABELS,
  enrollBodyForPromo,
  hasPickedSlot,
  listRowForPricelist,
  pickPonerPreciosPromos,
  slotEntries,
} from './pickPonerPreciosPromos';
import styles from './panel.module.css';

const pct = (value) => `${formatAmount(value)}%`;

/** MODO PONER PRECIOS: price write + MeLi-type promo pick after Enter. */
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
  const flaggedOnOpen = Boolean(row?.hay_mejores_ofertas);
  // Without promos.escribir discard/apply 403 — never gate Nuevo precio on the chooser.
  const canAwaitMejores = flaggedOnOpen && canWritePromos;

  const [draft, setDraft] = useState(price?.amount != null ? String(price.amount) : '');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState(null);
  const [suggestions, setSuggestions] = useState(null);
  const [typedPrice, setTypedPrice] = useState(null);
  const [baselineMarkup, setBaselineMarkup] = useState(null);
  const [baselineSellInOut, setBaselineSellInOut] = useState(null);
  const [enrolling, setEnrolling] = useState(false);
  const [awaitingMejores, setAwaitingMejores] = useState(canAwaitMejores);
  const [pendingLightningSlot, setPendingLightningSlot] = useState(null);

  const closeSuggestions = () => {
    if (enrolling) return;
    setPendingLightningSlot(null);
    setSuggestions(null);
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
    } catch (err) {
      setMessage({ tone: 'error', text: errorText(err, 'No se pudo guardar el precio.') });
      setBusy(false);
      return;
    }

    onWritten?.();
    setTypedPrice(precio);
    try {
      try {
        const res = await promocionesAPI.getMarkupParaPrecio(itemId, precio);
        setBaselineMarkup(res?.data?.nuestro_markup ?? null);
        setBaselineSellInOut(res?.data?.markup_sell_in_out ?? null);
      } catch {
        setBaselineMarkup(null);
        setBaselineSellInOut(null);
      }
      if (!canWritePromos) {
        setMessage({ tone: 'ok', text: 'Precio guardado en Pricing. Sin permiso para activar promos.' });
        return;
      }
      const promoRes = await promocionesAPI.getPromocionesItem(itemId);
      const promotions = promoRes?.data?.promotions ?? promoRes?.data?.promociones ?? [];
      const picked = pickPonerPreciosPromos(promotions);
      if (!hasPickedSlot(picked)) {
        setMessage({
          tone: 'ok',
          text: 'Precio guardado. No hay candidatas aplicables (SMART, DEAL, PRE_NEGOTIATED, PRICE_MATCHING, LIGHTNING, SELLER_CAMPAIGN Premium del mes).',
        });
        return;
      }
      setPendingLightningSlot(null);
      setSuggestions(picked);
    } catch (err) {
      setMessage({
        tone: 'error',
        text: `Precio guardado en Pricing. ${errorText(err, 'No se pudieron cargar las candidatas.')}`,
      });
    } finally {
      setBusy(false);
    }
  };

  const enrollSlot = async (slot) => {
    const promo = suggestions?.[slot];
    if (!promo || enrolling) return;
    setEnrolling(true);
    setMessage(null);
    setPendingLightningSlot(null);
    try {
      await promocionesAPI.postPromocionItem(itemId, enrollBodyForPromo(promo));
      setSuggestions(null);
      onWritten?.();
      onLeavePub?.();
    } catch (err) {
      const detailText = errorText(err, 'No se pudo activar la promoción.');
      setMessage({
        tone: 'error',
        text: `El precio ya está guardado en Pricing. ${detailText}`,
      });
      setEnrolling(false);
    }
  };

  const requestAcceptSlot = (slot) => {
    const promo = suggestions?.[slot];
    if (!promo || enrolling) return;
    if (promo.promotion_type === 'LIGHTNING') {
      setPendingLightningSlot(slot);
      return;
    }
    enrollSlot(slot);
  };

  const enterSlots = slotEntries(suggestions);
  const showPriceField = !awaitingMejores;

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

      {awaitingMejores && (
        <MejoresCandidatasBlock
          itemId={itemId}
          baselinePrice={price?.amount}
          onWritten={onWritten}
          onLeavePub={onLeavePub}
          onDismissed={() => setAwaitingMejores(false)}
        />
      )}

      {showPriceField && (
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
      )}
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
                baselineMarkup != null
                  ? ` · markup ${formatAmount(baselineMarkup)}%${sellInOutText(baselineSellInOut, pct)}`
                  : ''
              }`
            : undefined
        }
        size="sm"
        closeOnOverlay={false}
        closeOnEsc={!enrolling}
        showCloseButton={!enrolling}
        footer={<ModalFooterButtons onCancel={closeSuggestions} cancelText="Cancelar" cancelDisabled={enrolling} />}
      >
        {pendingLightningSlot ? (
          <div role="group" aria-label="Confirmar LIGHTNING">
            <p className={styles.ponerPreciosOk}>{LIGHTNING_IRREVERSIBLE_WARNING}</p>
            <p className={styles.ponerPreciosOk}>
              Se reservará el stock mínimo que informa MeLi (
              {suggestions?.[pendingLightningSlot]?.payload?.stock?.min ?? '—'} uds).
            </p>
            <ul className={styles.ponerPreciosChoices}>
              <li>
                <button
                  type="button"
                  className="btn-tesla sm"
                  disabled={enrolling}
                  onClick={() => enrollSlot(pendingLightningSlot)}
                >
                  {enrolling ? 'Aplicando…' : 'Sí, aplicar LIGHTNING'}
                </button>
              </li>
              <li>
                <button
                  type="button"
                  className="btn-tesla ghost sm"
                  disabled={enrolling}
                  onClick={() => setPendingLightningSlot(null)}
                >
                  Volver
                </button>
              </li>
            </ul>
          </div>
        ) : (
          <ul className={styles.ponerPreciosChoices}>
            {enterSlots.map(([slot, promo]) => (
              <li key={slot}>
                <button
                  type="button"
                  className="btn-tesla outline sm"
                  disabled={enrolling}
                  onClick={() => requestAcceptSlot(slot)}
                >
                  <span className={styles.ponerPreciosChoiceLabel}>{CHOOSER_SLOT_LABELS[slot] || slot}</span>
                  <span className={styles.ponerPreciosChoiceMeta}>
                    {resolvePromoName(promo) || promo.promotion_id}
                    {promoDisplayPrice(promo) != null ? ` · $ ${formatAmount(promoDisplayPrice(promo))}` : ''}
                    {promo.nuestro_markup != null
                      ? ` · markup ${formatAmount(promo.nuestro_markup)}%${sellInOutText(promo.markup_sell_in_out, pct)}`
                      : ''}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </ModalTesla>
    </div>
  );
}
