import { useState } from 'react';
import { promocionesAPI } from '../../services/api';
import { usePermisos } from '../../contexts/PermisosContext';
import styles from './promociones.module.css';

// Same writable-type contract as MlaPromocionesPanel's APPLICABLE_TYPES.
const WRITABLE_TYPES = new Set(['SELLER_CAMPAIGN', 'DEAL', 'SMART', 'PRE_NEGOTIATED']);

// EnrollResult/RemoveResult.status -> feedback message + tone. Eventual-
// consistency-safe: never claim a confirmed state from the immediate response.
// The success verb depends on the action (aplicada vs desaplicada).
function feedbackFor(status, isApplied) {
  const verb = isApplied ? 'desaplicada' : 'aplicada';
  const map = {
    submitted: { tone: 'info', message: 'Enviado — puede tardar en reflejarse (la tabla es la fuente de verdad).' },
    ambiguous: { tone: 'warn', message: 'Enviado, estado por confirmar — verificá en ML.' },
    reconciled_applied: { tone: 'success', message: `Promoción ${verb}.` },
    reconciled_not_applied: { tone: 'warn', message: 'Enviado pero aún no reflejado — verificá en ML.' },
    disabled: { tone: 'error', message: 'Escritura deshabilitada.' },
    rejected_out_of_range: { tone: 'error', message: 'Precio fuera de rango.' },
    rejected_unsupported_type: { tone: 'error', message: 'Tipo de promoción no soportado.' },
    rejected_price_unresolved: { tone: 'error', message: 'No se pudo resolver el precio.' },
    rejected_promotion_not_found: { tone: 'error', message: 'Promoción no encontrada.' },
    rejected_read_unavailable: { tone: 'error', message: 'Servicio de ML no disponible, reintentá.' },
    rejected_by_proxy: { tone: 'error', message: 'Rechazado por ML.' },
  };
  return map[status] || { tone: 'error', message: 'No se pudo confirmar el resultado.' };
}

function feedbackForError(err, actionLabel = 'aplicar') {
  const httpStatus = err?.response?.status;
  const detail = err?.response?.data?.detail;
  if (httpStatus === 403) {
    return { tone: 'error', message: detail || 'No autorizado o función deshabilitada.' };
  }
  if (httpStatus === 404 || httpStatus === 405 || httpStatus === 501) {
    return { tone: 'unavailable', message: `${actionLabel === 'aplicar' ? 'Aplicar' : 'Desaplicar'} no disponible.` };
  }
  if (httpStatus === 422) {
    return { tone: 'error', message: detail || 'Solicitud rechazada.' };
  }
  if (httpStatus === 503) {
    return { tone: 'error', message: 'Servicio de ML no disponible, reintentá.' };
  }
  return { tone: 'error', message: `Error al ${actionLabel} la promoción.` };
}

/**
 * Apply control for a single writable promotion row (SELLER_CAMPAIGN, DEAL, SMART, PRE_NEGOTIATED).
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
  const isApplied = promotion.status === 'started';
  const actionLabel = isApplied ? 'desaplicar' : 'aplicar';
  const actionLabelCapitalized = isApplied ? 'Desaplicar' : 'Aplicar';

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
    return <span className={styles.applySlot}>{actionLabelCapitalized} no disponible</span>;
  }

  const handleActionClick = () => {
    setFeedback(null);
    setPhase('confirming');
  };

  const handleCancel = () => {
    setPhase('idle');
  };

  const handleConfirm = async () => {
    setPhase('submitting');
    try {
      const data = isApplied
        ? await promocionesAPI
            .deletePromocionItem(mla, {
              promotion_id: promotion.promotion_id,
              promotion_type: promotion.promotion_type,
            })
            .then((res) => res.data)
        : await promocionesAPI
            .postPromocionItem(mla, {
              promotion_id: promotion.promotion_id,
              promotion_type: promotion.promotion_type,
            })
            .then((res) => res.data);
      setFeedback(feedbackFor(data?.status, isApplied));
      setPhase('done');
      if (onApplied) onApplied(data);
    } catch (err) {
      const fb = feedbackForError(err, actionLabel);
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
        <span>¿{actionLabelCapitalized} esta promoción?</span>
        <button type="button" className={styles.applyConfirmBtn} onClick={handleConfirm}>
          Sí, {actionLabel}
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
        {isApplied ? 'Desaplicando...' : 'Aplicando...'}
      </button>
    );
  }

  return (
    <span className={styles.applyWrapper}>
      <button type="button" className={styles.applyBtn} onClick={handleActionClick}>
        {actionLabelCapitalized}
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
