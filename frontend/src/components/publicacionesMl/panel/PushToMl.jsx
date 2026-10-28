import { useEffect, useId, useRef, useState } from 'react';
import { Upload } from 'lucide-react';
import { mlItemOverridesAPI } from '../../../services/api';
import styles from './panel.module.css';

const CAMPO_LABELS = { titulo: 'Título', descripcion: 'Descripción', fotos: 'Fotos', atributos: 'Atributos' };

// How each field went, as the push answers it (`ml_item_override_push_service`).
const ESTADO_LABELS = {
  submitted: 'enviado a Mercado Libre',
  rejected: 'Mercado Libre lo rechazó',
  ambiguous: 'sin confirmar',
  not_sent: 'no se envió',
  omitted: 'no se puede cambiar en Mercado Libre',
};

// The tone of each state: sent, refused, unknown; a field never sent or left out stays neutral.
const ESTADO_TONES = { submitted: styles.pushSubmitted, rejected: styles.pushRejected, ambiguous: styles.pushAmbiguous };

const UNANSWERED = 'No se sabe si llegó a Mercado Libre. Revisá la publicación antes de volver a enviar.';

/** A field that reached ML, or may have. */
const landed = (parte) => parte.estado === 'submitted' || parte.estado === 'ambiguous';

/** The push's own body (`{ status, message, partes }`), as opposed to a gateway's page or the app's error envelope. */
const isPushBody = (data) => Boolean(data) && typeof data.status === 'string' && Array.isArray(data.partes);

/**
 * What the push answered, as `{ ok, message, partes, mayHaveLanded }`. The push answers its own body on every status
 * (404, 409, 503 included); a 403 is the app's error envelope. No answer at all, or a 5xx without the push's body (a
 * gateway, a crash after the proxy forwarded the write), may have reached ML: it is unknown, never "retry".
 */
function outcomeOf(response, error) {
  if (response) {
    if (!isPushBody(response.data)) return { ok: false, message: UNANSWERED, partes: [], mayHaveLanded: true };
    const { status, message, partes } = response.data;
    return { ok: true, message, partes, mayHaveLanded: status === 'sent' || partes.some(landed) };
  }
  const failed = error?.response;
  if (!failed) return { ok: false, message: UNANSWERED, partes: [], mayHaveLanded: true };
  if (failed.status === 403) return { ok: false, message: 'No tenés permiso para actualizar la publicación en Mercado Libre.', partes: [] };
  if (isPushBody(failed.data)) {
    return { ok: false, message: failed.data.message, partes: failed.data.partes, mayHaveLanded: failed.data.partes.some(landed) };
  }
  if (failed.status >= 500) return { ok: false, message: UNANSWERED, partes: [], mayHaveLanded: true };
  return { ok: false, message: 'No se pudo enviar a Mercado Libre. Probá de nuevo.', partes: [] };
}

function Parte({ parte }) {
  const campo = CAMPO_LABELS[parte.campo] ?? parte.campo;
  const estado = ESTADO_LABELS[parte.estado] ?? parte.estado;
  return <li className={ESTADO_TONES[parte.estado]} data-estado={parte.estado}>{`${campo}: ${estado}.${parte.motivo ? ` ${parte.motivo}` : ''}`}</li>;
}

/**
 * "Actualizar en ML" (T8c): after a confirmation, send the publication's override to Mercado Libre through the
 * ml-webhook proxy (`POST /ml-item-overrides/{mla}/ml`). The server sends only what differs from ML and what ML lets
 * change, once, never retried; every field then says how it went. Nothing reached ML (the proxy not forwarding, the
 * kill switch off) is a failure that can be retried; no answer at all may have reached ML, so it says to check first.
 *
 * @param {object} props
 * @param {string} props.itemId The MLA.
 * @param {() => void} props.onPushed Something may have landed in ML: the caller reads the publication again.
 * @param {boolean} [props.canPush] Offers the button (an override to send); the last result stays without it.
 * @param {boolean} [props.replacesPictures] The override has pictures: ML takes the saved list as a whole.
 * @param {(sending: boolean) => void} [props.onSendingChange] A push went out (true) or answered (false): the caller
 *   keeps what would unmount this (the edit form) away meanwhile, or the answer is lost.
 */
export default function PushToMl({ itemId, onPushed, canPush = true, replacesPictures = false, onSendingChange }) {
  const [phase, setPhase] = useState('idle'); // idle | confirming | sending
  const [outcome, setOutcome] = useState(null);
  const resultId = useId();
  // A push still out when the panel moves on answers into nothing: it must not re-read another publication.
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const send = async () => {
    if (phase === 'sending') return; // a second click before the re-render
    setPhase('sending');
    setOutcome(null);
    onSendingChange?.(true);
    let next;
    try {
      next = outcomeOf(await mlItemOverridesAPI.pushToMl(itemId));
    } catch (error) {
      next = outcomeOf(null, error);
    }
    onSendingChange?.(false); // the caller outlives this (it keeps the tab when the MLA changes)
    if (!mounted.current) return;
    setOutcome(next);
    setPhase('idle');
    if (next.mayHaveLanded) onPushed();
  };

  return (
    <>
      {phase === 'idle' && canPush && (
        <div className={styles.statusConfirm}>
          <button type="button" className="btn-tesla outline sm" onClick={() => setPhase('confirming')}>
            <Upload size={14} aria-hidden="true" />
            Actualizar en ML
          </button>
        </div>
      )}
      {phase === 'confirming' && (
        <div className={styles.statusConfirm}>
          <span>{`Se envían a Mercado Libre los datos sobrescritos que difieren del original. ¿Actualizar ${itemId}?`}</span>
          {replacesPictures && (
            <span>
              Las fotos se reemplazan por la lista guardada: las que se agregaron o quitaron directo en Mercado Libre desde entonces se
              pierden.
            </span>
          )}
          <button type="button" className="btn-tesla primary sm" onClick={send}>
            Confirmar
          </button>
          <button type="button" className="btn-tesla outline sm" onClick={() => setPhase('idle')}>
            Cancelar
          </button>
        </div>
      )}
      {phase === 'sending' && <p className={styles.note}>Enviando a Mercado Libre…</p>}

      {outcome && (
        <section className={styles.pushResult} aria-labelledby={resultId}>
          <h4 id={resultId} className={styles.subTitle}>
            Resultado en Mercado Libre
          </h4>
          {outcome.message && (
            <p className={styles.feedback} role={outcome.ok ? 'status' : 'alert'}>
              {outcome.message}
            </p>
          )}
          {outcome.partes.length > 0 && (
            <ul className={styles.pushParts}>
              {outcome.partes.map((parte) => (
                <Parte key={parte.campo} parte={parte} />
              ))}
            </ul>
          )}
        </section>
      )}
    </>
  );
}
