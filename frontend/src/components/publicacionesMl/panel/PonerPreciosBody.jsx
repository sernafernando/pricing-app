import { useState } from 'react';
import { formatAmount } from '../../../utils/ventasMlFormat';
import { publicationListLabel } from '../../../constants/mlPublicationTypes';
import styles from './panel.module.css';

/**
 * Minimal body for MODO PONER PRECIOS (S5): lista + current price + draft input.
 * Enter-suggest / enroll is T5 — this slice only mounts the field.
 *
 * @param {object} props
 * @param {object} props.detail Publication detail (`usePublicationDetail`).
 * @param {boolean} [props.canEditPrice]
 */
export default function PonerPreciosBody({ detail, canEditPrice = false }) {
  const row = detail?.row;
  const price = row?.price;
  const listLabel = publicationListLabel(price);
  const amount = price?.amount;
  const [draft, setDraft] = useState(amount != null ? String(amount) : '');

  return (
    <div className={styles.ponerPreciosBody}>
      <dl className={styles.ponerPreciosFacts}>
        <div>
          <dt>Lista</dt>
          <dd>{listLabel ?? '—'}</dd>
        </div>
        <div>
          <dt>Precio actual</dt>
          <dd>{amount != null ? formatAmount(amount) : '—'}</dd>
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
          disabled={!canEditPrice}
          aria-label="Nuevo precio"
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            // T5 wires Enter → suggest/enroll; keep the key from bubbling to the layout.
            if (event.key === 'Enter') event.stopPropagation();
          }}
        />
      </label>
    </div>
  );
}
