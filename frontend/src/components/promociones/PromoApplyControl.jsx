import { useState } from 'react';
import { promocionesAPI } from '../../services/api';
import { usePermisos } from '../../contexts/PermisosContext';
import styles from './promociones.module.css';

// Same writable-type contract as MlaPromocionesPanel's APPLICABLE_TYPES.
const WRITABLE_TYPES = new Set(['SELLER_CAMPAIGN', 'DEAL', 'SMART']);

// EnrollResult.status -> feedback message + tone. Eventual-consistency-safe:
// never claim a confirmed "aplicado" from the immediate response alone.
const STATUS_FEEDBACK = {
  submitted: { tone: 'info', message: 'Enviado — puede tardar en reflejarse (la tabla es la fuente de verdad).' },
  ambiguous: { tone: 'warn', message: 'Enviado, estado por confirmar — verificá en ML.' },
  reconciled_applied: { tone: 'success', message: 'Promoción aplicada.' },
  reconciled_not_applied: { tone: 'warn', message: 'Enviado pero aún no reflejado — verificá en ML.' },
  disabled: { tone: 'error', message: 'Escritura deshabilitada.' },
  rejected_out_of_range: { tone: 'error', message: 'Precio fuera de rango.' },
  rejected_unsupported_type: { tone: 'error', message: 'Tipo de promoción no soportado.' },
  rejected_price_unresolved: { tone: 'error', message: 'No se pudo resolver el precio.' },
  rejected_promotion_not_found: { tone: 'error', message: 'Promoción no encontrada.' },
  rejected_read_unavailable: { tone: 'error', message: 'Servicio de ML no disponible, reintentá.' },
  rejected_by_proxy: { tone: 'error', message: 'Rechazado por ML.' },
};

function feedbackFor(status) {
  return STATUS_FEEDBACK[status] || { tone: 'error', message: 'No se pudo confirmar el resultado.' };
}

function feedbackForError(err) {
  const httpStatus = err?.response?.status;
  const detail = err?.response?.data?.detail;
  if (httpStatus === 403) {
    return { tone: 'error', message: detail || 'No autorizado o función deshabilitada.' };
  }
  if (httpStatus === 404 || httpStatus === 405 || httpStatus === 501) {
    return { tone: 'unavailable', message: 'Aplicar no disponible.' };
  }
  if (httpStatus === 422) {
    return { tone: 'error', message: detail || 'Solicitud rechazada.' };
  }
  if (httpStatus === 503) {
    return { tone: 'error', message: 'Servicio de ML no disponible, reintentá.' };
  }
  return { tone: 'error', message: 'Error al aplicar la promoción.' };
}

/**
 * Apply control for a single writable promotion row (SELLER_CAMPAIGN, DEAL, SMART).
 * Renders inline inside `MlaPromocionesPanel`. Triggers a REAL ML price write:
 * requires explicit confirmation, never auto-retries, never claims a confirmed
 * "aplicado" state from the immediate response (eventual consistency).
 */
function PromoApplyControl({ mla, promotion, onApplied }) {
  const { tienePermiso } = usePermisos();
  const [phase, setPhase] = useState('idle'); // idle | confirming | submitting | done
  const [feedback, setFeedback] = useState(null); // { tone, message } | null
  const [unavailable, setUnavailable] = useState(false);

  const hasPermission = tienePermiso('promos.escribir');
  const isWritableType = WRITABLE_TYPES.has(promotion.promotion_type);

  if (!isWritableType) {
    return <span className={styles.applySlot}>Lo maneja ML</span>;
  }

  if (!hasPermission) {
    return (
      <span className={styles.applySlot} title="Sin permiso para aplicar promociones">
        Sin permiso
      </span>
    );
  }

  if (unavailable) {
    return <span className={styles.applySlot}>Aplicar no disponible</span>;
  }

  const handleApplyClick = () => {
    setFeedback(null);
    setPhase('confirming');
  };

  const handleCancel = () => {
    setPhase('idle');
  };

  const handleConfirm = async () => {
    setPhase('submitting');
    try {
      const body =
        promotion.promotion_type === 'SMART'
          ? { promotion_id: promotion.promotion_id, promotion_type: promotion.promotion_type }
          : { promotion_id: promotion.promotion_id, promotion_type: promotion.promotion_type };
      const { data } = await promocionesAPI.postPromocionItem(mla, body);
      setFeedback(feedbackFor(data?.status));
      setPhase('done');
      if (onApplied) onApplied(data);
    } catch (err) {
      const fb = feedbackForError(err);
      if (fb.tone === 'unavailable') {
        setUnavailable(true);
        setPhase('idle');
        return;
      }
      setFeedback(fb);
      setPhase('done');
    }
  };

  if (phase === 'confirming') {
    return (
      <span className={styles.applyConfirm}>
        <span>¿Aplicar esta promoción?</span>
        <button type="button" className={styles.applyConfirmBtn} onClick={handleConfirm}>
          Sí, aplicar
        </button>
        <button type="button" className={styles.applyCancelBtn} onClick={handleCancel}>
          Cancelar
        </button>
      </span>
    );
  }

  if (phase === 'submitting') {
    return (
      <button type="button" className={styles.applySlot} disabled>
        Aplicando...
      </button>
    );
  }

  return (
    <span className={styles.applyWrapper}>
      <button type="button" className={styles.applyBtn} onClick={handleApplyClick}>
        Aplicar
      </button>
      {feedback && (
        <span
          className={
            feedback.tone === 'success'
              ? styles.feedbackSuccess
              : feedback.tone === 'warn'
                ? styles.feedbackWarn
                : styles.feedbackError
          }
        >
          {feedback.message}
        </span>
      )}
    </span>
  );
}

export default PromoApplyControl;
