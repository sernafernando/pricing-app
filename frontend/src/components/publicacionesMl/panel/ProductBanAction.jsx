import { useState } from 'react';
import { Ban } from 'lucide-react';
import { usePermisos } from '../../../contexts/PermisosContext';
import { productoBanlistAPI } from '../../../services/api';
import { Section } from './PanelParts';
import styles from './panel.module.css';

const BAN_ROLES = ['SUPERADMIN', 'ADMIN'];
const BAN_PERMISSION = 'admin.gestionar_mla_banlist';
const DEFAULT_REASON = 'Sin motivo especificado';

/** A word of the description to type back (longer than 3 characters, like Productos), else the product id. */
function pickWord(description, productItemId) {
  const words = (description ?? '')
    .split(/\s+/)
    .map((word) => word.replace(/[^a-zA-Z0-9áéíóúñÁÉÍÓÚÑ]/g, ''))
    .filter((word) => word.length > 3);
  return words.length > 0 ? words[Math.floor(Math.random() * words.length)] : String(productItemId);
}

/** What to tell the operator when the ban did not go through. */
function describeError(error) {
  if (error?.response?.status === 403) return 'No tenés permiso para agregar productos a la banlist.';
  const data = error?.response?.data;
  return data?.error?.message ?? data?.detail ?? 'No se pudo agregar a la banlist. Probá de nuevo.';
}

/**
 * "Agregar a la banlist" for one product, as Productos does it: the operator types back a word of the product's
 * description and may give a reason. Shown to ADMIN / SUPERADMIN or with `admin.gestionar_mla_banlist`, the same
 * the server accepts. Self-contained so the panel can place it anywhere; mount it with `key={productItemId}`.
 *
 * @param {object} props
 * @param {number} props.productItemId The ERP product.
 * @param {string} [props.description] The product's description, where the word to type back comes from.
 */
export default function ProductBanAction({ productItemId, description }) {
  const { rol, tienePermiso } = usePermisos();
  const [state, setState] = useState({ status: 'idle', message: null });
  const [word, setWord] = useState('');
  const [typed, setTyped] = useState('');
  const [reason, setReason] = useState('');
  if (!BAN_ROLES.includes(rol) && !tienePermiso(BAN_PERMISSION)) return null;

  const open = () => {
    setWord(pickWord(description, productItemId));
    setTyped('');
    setReason('');
    setState({ status: 'confirming', message: null });
  };

  const matches = typed.trim().toLowerCase() === word.toLowerCase();

  const send = async () => {
    if (state.status === 'sending' || !matches) return;
    setState({ status: 'sending', message: null });
    try {
      const { data } = await productoBanlistAPI.add(productItemId, reason.trim() || DEFAULT_REASON);
      if (data?.total_agregados > 0) setState({ status: 'done', message: 'Producto agregado a la banlist.' });
      else if (data?.duplicados?.length > 0) setState({ status: 'done', message: 'El producto ya estaba en la banlist.' });
      else setState({ status: 'error', message: data?.no_encontrados?.[0] ?? 'No se pudo agregar a la banlist.' });
    } catch (error) {
      setState({ status: 'error', message: describeError(error) });
    }
  };

  if (state.status === 'done') {
    return (
      <Section title="Banlist">
        <div className={styles.feedback} role="status">
          {state.message}
        </div>
      </Section>
    );
  }

  const confirming = state.status !== 'idle';
  return (
    <Section title="Banlist">
      <div className={styles.resync}>
        {confirming ? (
          <div className={styles.banConfirm}>
            <span>
              Para confirmar, escribí: <strong data-testid="ban-word">{word}</strong>
            </span>
            <label className={styles.banField}>
              Palabra de verificación
              <input
                type="text"
                className={`${styles.identityInput} ${styles.wideInput}`}
                value={typed}
                onChange={(event) => setTyped(event.target.value)}
                autoFocus
              />
            </label>
            <label className={styles.banField}>
              Motivo (opcional)
              <textarea
                className={`${styles.identityInput} ${styles.wideInput}`}
                rows={2}
                value={reason}
                onChange={(event) => setReason(event.target.value)}
              />
            </label>
            <div className={styles.statusConfirm}>
              <button
                type="button"
                className="btn-tesla danger sm"
                onClick={send}
                disabled={!matches || state.status === 'sending'}
              >
                Confirmar
              </button>
              <button
                type="button"
                className="btn-tesla outline sm"
                onClick={() => setState({ status: 'idle', message: null })}
                disabled={state.status === 'sending'}
              >
                Cancelar
              </button>
            </div>
          </div>
        ) : (
          <button type="button" className="btn-tesla outline-subtle-danger sm" onClick={open}>
            <Ban size={14} aria-hidden="true" />
            Agregar a la banlist
          </button>
        )}
        {state.status === 'error' && (
          <div className={styles.feedback} role="alert">
            {state.message}
          </div>
        )}
      </div>
    </Section>
  );
}
