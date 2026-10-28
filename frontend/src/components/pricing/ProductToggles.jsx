import { useState } from 'react';
import { Lock, Pencil } from 'lucide-react';
import { preciosAPI } from '../../services/api';
import { formatAmount } from '../../utils/ventasMlFormat';
import { Empty, MarkupChip } from './PriceParts';
import { formatRate, isBlank } from './priceFormat';
import { RebateEditor, WebTransfEditor } from './toggleEditors';
import { rebateDraft, rebateWrite, webTransfDraft, webTransfWrite } from './toggleWrites';
import styles from './ProductPrices.module.css';

/**
 * Rebate, best offer, web transferencia and "fuera de tarjetas" of ONE
 * product, shown and edited as Productos does (useProductosToggles: same
 * endpoints, payloads, defaults and validation; no confirmation and no
 * negative-markup check, as there). The figures are what
 * `GET /productos/{item_id}` computes, the same as the Productos listing.
 */

/** "2099-12-31" as "31/12", read as a calendar date (no time-zone shift). */
function dayMonth(isoDate) {
  const [, month, day] = String(isoDate).split('-');
  return day && month ? `${day.slice(0, 2)}/${month}` : isoDate;
}

/** The best offer's details, in Productos' order (price and markup have their own cells). */
function offerDetails(product) {
  const details = [];
  if (product.mejor_oferta_porcentaje_rebate) details.push(`Aporte ${formatAmount(product.mejor_oferta_porcentaje_rebate)}%`);
  if (product.mejor_oferta_monto_rebate) details.push(`Rebate $ ${formatAmount(product.mejor_oferta_monto_rebate)}`);
  if (product.mejor_oferta_fecha_hasta) details.push(`Hasta ${dayMonth(product.mejor_oferta_fecha_hasta)}`);
  if (product.mejor_oferta_pvp_seller) details.push(`PVP $ ${formatAmount(product.mejor_oferta_pvp_seller)}`);
  return details;
}

const Money = ({ value }) => (isBlank(value) ? <Empty /> : `$ ${formatAmount(value)}`);

function EditButton({ label, onClick, disabled }) {
  return (
    <button type="button" className="btn-tesla ghost icon-only xs" aria-label={`Editar ${label}`} title={`Editar ${label}`} onClick={onClick} disabled={disabled}>
      <Pencil size={14} aria-hidden="true" />
    </button>
  );
}

/**
 * @param {object} props
 * @param {object} props.product The `ProductoResponse` on screen.
 * @param {ReturnType<typeof import('./productPricePermissions').pricePermissions>} [props.permissions]
 * @param {boolean} props.saving A write of the tab is in flight.
 * @param {(write: (itemId: number) => Promise<unknown>, texts: { saved: string, fallback: string }) => Promise<boolean>} props.onSave
 *   Runs the write for the product on screen, re-reads it and reports; resolves true when it was saved.
 * @param {(text: string) => void} props.onInvalid Reports a value that is not sent.
 */
export default function ProductToggles({ product, permissions, saving, onSave, onInvalid }) {
  const [editing, setEditing] = useState(null);
  const canRebate = Boolean(permissions?.canToggleRebate);
  const canWebTransf = Boolean(permissions?.canToggleWebTransf);
  const canOutOfCards = Boolean(permissions?.canToggleOutOfCards);
  const editable = canRebate || canWebTransf;

  const hasRebate = Boolean(product.participa_rebate && product.precio_rebate);
  const offer = product.mejor_oferta_precio ? offerDetails(product) : [];
  const webTransf = Boolean(product.participa_web_transferencia);

  // A value that is not sent is reported; a saved one closes the editor.
  const saveWith = async (built) => {
    if (built.error) {
      onInvalid(built.error);
      return;
    }
    const saved = await onSave(built.write, { saved: built.saved, fallback: built.fallback });
    if (saved) setEditing(null);
  };
  const saveRebate = (draft) => saveWith(rebateWrite(product, draft));
  const saveWebTransf = (draft) => saveWith(webTransfWrite(product, draft));

  // A written "fuera de tarjetas" whose re-read failed: shown until the next
  // successful read replaces the product (the override belongs to the product
  // object it was written over), so the box never snaps back to a stale value.
  const [writtenOutOfCards, setWrittenOutOfCards] = useState(null);
  const outOfCards = writtenOutOfCards?.over === product ? writtenOutOfCards.value : Boolean(product.out_of_cards);

  const saveOutOfCards = async (checked) => {
    const over = product;
    const saved = await onSave((itemId) => preciosAPI.setOutOfCards(itemId, checked), {
      saved: 'Fuera de tarjetas guardado',
      fallback: 'No se pudo guardar fuera de tarjetas.',
    });
    if (saved) setWrittenOutOfCards({ over, value: checked });
  };

  const cancel = () => setEditing(null);

  return (
    <section className={styles.group} data-list="extras">
      <table className={styles.table}>
        <caption className={styles.caption}>
          <span className={styles.captionTitle}>Rebate, oferta y transferencia</span>
          <span className={styles.captionSub}>Lo que Productos muestra junto a la lista ML</span>
        </caption>
        <thead>
          <tr>
            <th scope="col">Concepto</th>
            <th scope="col">Precio</th>
            <th scope="col">Markup</th>
            {editable && (
              <th scope="col">
                <span className={styles.srOnly}>Acciones</span>
              </th>
            )}
          </tr>
        </thead>
        <tbody>
          <tr className={styles.row} data-editing={editing === 'rebate' ? '' : undefined}>
            <th scope="row" className={styles.label}>
              Rebate
              {hasRebate && <div className={styles.sub}>{formatRate(product.porcentaje_rebate)}% de rebate</div>}
            </th>
            <td className={styles.price}>{hasRebate ? <Money value={product.precio_rebate} /> : <span className={styles.muted}>Sin rebate</span>}</td>
            <td className={styles.markup}>{hasRebate ? <MarkupChip value={product.markup_rebate} /> : <Empty />}</td>
            {editable && (
              <td className={styles.actions}>
                {canRebate && <EditButton label="rebate" onClick={() => setEditing('rebate')} disabled={saving} />}
              </td>
            )}
          </tr>
          {hasRebate && (
            <tr className={styles.row}>
              <th scope="row" className={styles.label}>
                Fuera de tarjetas
              </th>
              <td className={styles.price}>
                <input
                  type="checkbox"
                  aria-label="Fuera de tarjetas"
                  title={canOutOfCards ? undefined : 'Sin permiso para cambiarlo'}
                  checked={outOfCards}
                  onChange={(event) => saveOutOfCards(event.target.checked)}
                  disabled={!canOutOfCards || saving}
                />
              </td>
              <td className={styles.markup} />
              {editable && <td className={styles.actions} />}
            </tr>
          )}
          <tr className={styles.row}>
            <th scope="row" className={styles.label}>
              Mejor oferta
              {offer.map((detail) => (
                <div key={detail} className={styles.sub}>
                  {detail}
                </div>
              ))}
            </th>
            <td className={styles.price}>{product.mejor_oferta_precio ? <Money value={product.mejor_oferta_precio} /> : <Empty />}</td>
            <td className={styles.markup}>
              {product.mejor_oferta_precio && !isBlank(product.mejor_oferta_markup) ? <MarkupChip value={product.mejor_oferta_markup * 100} /> : <Empty />}
            </td>
            {editable && <td className={styles.actions} />}
          </tr>
          <tr className={styles.row} data-editing={editing === 'web' ? '' : undefined}>
            <th scope="row" className={styles.label}>
              Web transferencia
              {webTransf && (
                <div className={styles.sub}>
                  +{formatRate(product.porcentaje_markup_web)}% sobre la clásica
                  {product.preservar_porcentaje_web && (
                    <span className={styles.lock} title="Se conserva en cambios masivos">
                      <Lock size={12} aria-hidden="true" />
                      % fijo
                    </span>
                  )}
                </div>
              )}
            </th>
            <td className={styles.price}>{webTransf ? <Money value={product.precio_web_transferencia} /> : <Empty />}</td>
            <td className={styles.markup}>{webTransf ? <MarkupChip value={product.markup_web_real} /> : <Empty />}</td>
            {editable && (
              <td className={styles.actions}>
                {canWebTransf && <EditButton label="web transferencia" onClick={() => setEditing('web')} disabled={saving} />}
              </td>
            )}
          </tr>
        </tbody>
      </table>

      {editing === 'rebate' && (
        <RebateEditor
          initial={rebateDraft(product)}
          saving={saving}
          onSave={saveRebate}
          onCancel={cancel}
        />
      )}
      {editing === 'web' && (
        <WebTransfEditor
          initial={webTransfDraft(product)}
          saving={saving}
          onSave={saveWebTransf}
          onCancel={cancel}
        />
      )}
    </section>
  );
}
