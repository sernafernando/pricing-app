import { useState } from 'react';
import { Lock, Pencil } from 'lucide-react';
import { preciosAPI } from '../../services/api';
import { formatAmount } from '../../utils/ventasMlFormat';
import { Empty, MarkupChip } from './PriceParts';
import { formatRate, isBlank } from './priceFormat';
import styles from './ProductPrices.module.css';

/**
 * Rebate, best offer, web transferencia and "fuera de tarjetas" of ONE
 * product, shown and edited as Productos does (useProductosToggles: same
 * endpoints, payloads, defaults and validation; no confirmation and no
 * negative-markup check, as there). The figures are what
 * `GET /productos/{item_id}` computes, the same as the Productos listing.
 */

// Productos' defaults for a product that never had them.
const REBATE_DEFAULT = 3.8;
const WEB_TRANSF_DEFAULT = 6.0;

/** Productos' parse: the first comma is the decimal separator. */
const parsePercent = (text) => parseFloat(String(text).replace(',', '.'));

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

/** The editor's keys: Enter saves, Escape cancels the edit (not the side panel around it). */
const editorKeys = (onSave, onCancel) => (event) => {
  // Enter on a button is that button's click (Cancelar must not save).
  if (event.key === 'Enter' && event.target.tagName !== 'BUTTON') {
    event.preventDefault();
    onSave();
  } else if (event.key === 'Escape') {
    event.stopPropagation();
    onCancel();
  }
};

function EditorActions({ saving, onCancel }) {
  return (
    <div className={styles.warningActions}>
      <button type="button" className="btn-tesla outline sm" onClick={onCancel} disabled={saving}>
        Cancelar
      </button>
      <button type="submit" className="btn-tesla primary sm" disabled={saving}>
        Guardar
      </button>
    </div>
  );
}

function RebateEditor({ initial, saving, onSave, onCancel }) {
  const [draft, setDraft] = useState(initial);
  const save = () => onSave(draft);
  return (
    <form
      className={styles.editor}
      role="group"
      aria-label="Rebate"
      onKeyDown={editorKeys(save, onCancel)}
      onSubmit={(event) => {
        event.preventDefault();
        save();
      }}
    >
      <label className={styles.check}>
        <input type="checkbox" checked={draft.participa} onChange={(event) => setDraft({ ...draft, participa: event.target.checked })} autoFocus={!draft.participa} disabled={saving} />
        Participa
      </label>
      {draft.participa && (
        <input
          className={styles.input}
          type="text"
          inputMode="decimal"
          aria-label="% de rebate"
          placeholder="%"
          value={draft.porcentaje}
          onChange={(event) => setDraft({ ...draft, porcentaje: event.target.value })}
          onFocus={(event) => event.target.select()}
          disabled={saving}
          autoFocus
        />
      )}
      <EditorActions saving={saving} onCancel={onCancel} />
    </form>
  );
}

function WebTransfEditor({ initial, saving, onSave, onCancel }) {
  const [draft, setDraft] = useState(initial);
  const save = () => onSave(draft);
  return (
    <form
      className={styles.editor}
      role="group"
      aria-label="Web transferencia"
      onKeyDown={editorKeys(save, onCancel)}
      onSubmit={(event) => {
        event.preventDefault();
        save();
      }}
    >
      <label className={styles.check}>
        <input type="checkbox" checked={draft.participa} onChange={(event) => setDraft({ ...draft, participa: event.target.checked })} disabled={saving} autoFocus />
        Participa
      </label>
      <input
        className={styles.input}
        type="text"
        inputMode="decimal"
        aria-label="% sobre la clásica"
        placeholder="%"
        value={draft.porcentaje}
        onChange={(event) => setDraft({ ...draft, porcentaje: event.target.value })}
        onFocus={(event) => event.target.select()}
        disabled={saving}
      />
      <label className={styles.check}>
        <input type="checkbox" checked={draft.preservar} onChange={(event) => setDraft({ ...draft, preservar: event.target.checked })} disabled={saving} />
        Conservar el % en cambios masivos
      </label>
      <EditorActions saving={saving} onCancel={onCancel} />
    </form>
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

  const storedRebate = isBlank(product.porcentaje_rebate) ? REBATE_DEFAULT : product.porcentaje_rebate;

  const saveRebate = async ({ participa, porcentaje }) => {
    // Turning it off sends the stored percentage, as Productos' quick toggle
    // does: the field is hidden then, so whatever it holds is not read.
    const value = participa ? parsePercent(porcentaje) : storedRebate;
    if (!Number.isFinite(value) || value < 0 || value > 100) {
      onInvalid('El porcentaje de rebate debe ser un número entre 0 y 100.');
      return;
    }
    const saved = await onSave((itemId) => preciosAPI.setRebate(itemId, { participa_rebate: participa, porcentaje_rebate: value }), {
      saved: 'Rebate guardado',
      fallback: 'No se pudo guardar el rebate.',
    });
    if (saved) setEditing(null);
  };

  const saveWebTransf = async ({ participa, porcentaje, preservar }) => {
    // As Productos: an unreadable percentage is sent as 0.
    const value = parsePercent(porcentaje) || 0;
    const saved = await onSave(
      (itemId) => preciosAPI.setWebTransferencia(itemId, { participa, porcentaje_markup: value, preservar_porcentaje: preservar }),
      { saved: 'Web transferencia guardada', fallback: 'No se pudo guardar web transferencia.' },
    );
    if (saved) setEditing(null);
  };

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
          initial={{
            participa: Boolean(product.participa_rebate),
            porcentaje: formatRate(storedRebate),
          }}
          saving={saving}
          onSave={saveRebate}
          onCancel={cancel}
        />
      )}
      {editing === 'web' && (
        <WebTransfEditor
          initial={{
            participa: Boolean(product.participa_web_transferencia),
            porcentaje: formatRate(isBlank(product.porcentaje_markup_web) ? WEB_TRANSF_DEFAULT : product.porcentaje_markup_web),
            preservar: Boolean(product.preservar_porcentaje_web),
          }}
          saving={saving}
          onSave={saveWebTransf}
          onCancel={cancel}
        />
      )}
    </section>
  );
}
