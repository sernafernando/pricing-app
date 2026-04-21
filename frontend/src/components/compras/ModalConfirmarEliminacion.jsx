import { useEffect, useMemo, useRef, useState } from 'react';
import { AlertTriangle, X } from 'lucide-react';
import styles from './ModalConfirmarEliminacion.module.css';

/**
 * ModalConfirmarEliminacion — modal de confirmación destructiva reusable.
 *
 * Patrón (inspirado en `TabEnviosFlex.jsx` ~líneas 1324-1360):
 *   1. Muestra resumen de la entidad (tipo + número + motivo hint).
 *   2. Usuario debe tipear textual:
 *      - Motivo (textarea obligatoria).
 *      - Challenge word (random, elegida desde `sourceText` del caller).
 *   3. Botón "Eliminar definitivamente" queda deshabilitado hasta que:
 *      - Motivo no vacío (.trim()).
 *      - Challenge word tipeada == palabra mostrada (case-insensitive).
 *
 * No se puede deshacer: la fila queda en papelera sin endpoint de restore.
 *
 * Props:
 *   - open: boolean
 *   - onClose(): cierra sin confirmar.
 *   - onConfirm({ motivo, challenge_palabra_usada }): caller hace el DELETE.
 *   - titulo: string header.
 *   - entidadTipo: 'Pedido' | 'Orden de pago' (usado en texto descriptivo).
 *   - entidadNumero: string visual ("P-0001", "OP-0042").
 *   - sourceText: string | string[] — fuente para extraer palabra random.
 *     Puede ser `${proveedor} ${numero}` o similar. Fallback genérico si no hay words ≥4 chars.
 *   - loading: boolean.
 *   - error: string | null.
 */
export default function ModalConfirmarEliminacion({
  open,
  onClose,
  onConfirm,
  titulo = 'Eliminar definitivamente',
  entidadTipo = 'entidad',
  entidadNumero = '',
  sourceText = '',
  loading = false,
  error = null,
}) {
  const [motivo, setMotivo] = useState('');
  const [challengeTipeada, setChallengeTipeada] = useState('');
  const motivoRef = useRef(null);

  // Extraer palabra random del sourceText (mismo algoritmo que TabEnviosFlex).
  const challengeWord = useMemo(() => {
    if (!open) return null;
    const fuentes = Array.isArray(sourceText) ? sourceText : [sourceText];
    const palabras = fuentes
      .filter(Boolean)
      .flatMap((s) => String(s).split(/\s+/))
      .filter((w) => w.length >= 4 && /^[a-záéíóúñü0-9-]+$/i.test(w));
    if (palabras.length > 0) {
      return palabras[Math.floor(Math.random() * palabras.length)];
    }
    // Fallback determinístico con 6 letras si no hay words válidas en sourceText.
    const pool = ['borrar', 'definitivo', 'papelera', 'eliminar', 'confirmar', 'purgar'];
    return pool[Math.floor(Math.random() * pool.length)];
    // `sourceText` está serializado implícitamente — no hace falta dependency adicional.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, JSON.stringify(sourceText)]);

  // Reset state cada vez que abre/cierra.
  useEffect(() => {
    if (open) {
      setMotivo('');
      setChallengeTipeada('');
      // Focus en el textarea al abrir.
      setTimeout(() => {
        motivoRef.current?.focus();
      }, 50);
    }
  }, [open]);

  if (!open) return null;

  const motivoValido = motivo.trim().length > 0;
  const challengeValida =
    challengeWord && challengeTipeada.trim().toLowerCase() === challengeWord.toLowerCase();
  const puedeConfirmar = motivoValido && challengeValida && !loading;

  const handleConfirm = (e) => {
    e?.preventDefault();
    if (!puedeConfirmar) return;
    onConfirm({
      motivo: motivo.trim(),
      challenge_palabra_usada: challengeWord,
    });
  };

  return (
    <div className={styles.modalOverlay}>
      <div className={styles.modalContent} role="dialog" aria-modal="true">
        <div className={styles.modalHeader}>
          <div className={styles.headerLeft}>
            <AlertTriangle size={18} className={styles.iconWarning} />
            <span className={styles.modalTitle}>{titulo}</span>
          </div>
          <button
            type="button"
            className={styles.modalCloseBtn}
            onClick={onClose}
            aria-label="Cerrar"
          >
            <X size={18} />
          </button>
        </div>

        <p className={styles.warning}>
          Esta acción <strong>no se puede deshacer</strong>. Se va a eliminar físicamente{' '}
          <strong>
            {entidadTipo}
            {entidadNumero ? ` ${entidadNumero}` : ''}
          </strong>
          . Los datos quedan en la papelera como auditoría pero <strong>no</strong> pueden
          restaurarse.
        </p>

        {error && <div className={styles.errorBanner}>{error}</div>}

        <form onSubmit={handleConfirm}>
          <div className={styles.formGroup}>
            <label className={styles.formLabel} htmlFor="motivoInput">
              Motivo <span className={styles.required}>*</span>
            </label>
            <textarea
              id="motivoInput"
              ref={motivoRef}
              className={styles.textarea}
              value={motivo}
              onChange={(e) => setMotivo(e.target.value)}
              placeholder="Describí por qué hay que borrar esto..."
              rows={3}
              disabled={loading}
            />
          </div>

          <div className={styles.formGroup}>
            <label className={styles.formLabel} htmlFor="challengeInput">
              Para confirmar, tipeá la palabra:{' '}
              <code className={styles.challengeWord}>{challengeWord}</code>
            </label>
            <input
              id="challengeInput"
              type="text"
              className={styles.input}
              value={challengeTipeada}
              onChange={(e) => setChallengeTipeada(e.target.value)}
              placeholder={challengeWord}
              autoComplete="off"
              spellCheck={false}
              disabled={loading}
            />
          </div>

          <div className={styles.formActions}>
            <button
              type="button"
              className={styles.btnSecondary}
              onClick={onClose}
              disabled={loading}
            >
              Cancelar
            </button>
            <button
              type="submit"
              className={styles.btnDanger}
              disabled={!puedeConfirmar}
            >
              {loading ? 'Eliminando...' : 'Eliminar definitivamente'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
