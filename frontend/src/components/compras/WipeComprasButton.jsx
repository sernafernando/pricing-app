/**
 * WipeComprasButton — botón de testing que limpia TODAS las tablas del módulo compras.
 *
 * PELIGRO: acción destructiva e irreversible. Solo visible para usuarios con el permiso
 * `administracion.wipe_compras_testing`. Requiere que el usuario escriba "WIPE" en un
 * campo de confirmación antes de habilitar el botón de ejecución.
 *
 * Spec PR1, FR-1.1..FR-1.3, AC-1.1/AC-1.2.
 */

import { useState } from 'react';
import { AlertTriangle, Trash2, X } from 'lucide-react';
import { usePermisos } from '../../contexts/PermisosContext';
import api from '../../services/api';
import styles from './WipeComprasButton.module.css';

const CONFIRMATION_WORD = 'WIPE';
const ENDPOINT = '/administracion/compras/testing/wipe-compras';

export default function WipeComprasButton({ onWipeComplete }) {
  const { tienePermiso } = usePermisos();
  const [modalOpen, setModalOpen] = useState(false);
  const [confirmacionInput, setConfirmacionInput] = useState('');
  const [incluirCajaBanco, setIncluirCajaBanco] = useState(true);
  const [loading, setLoading] = useState(false);
  const [errorMsg, setErrorMsg] = useState(null);
  const [successMsg, setSuccessMsg] = useState(null);

  if (!tienePermiso('administracion.wipe_compras_testing')) {
    return null;
  }

  const openModal = () => {
    setModalOpen(true);
    setConfirmacionInput('');
    setErrorMsg(null);
    setSuccessMsg(null);
  };

  const closeModal = () => {
    if (loading) return;
    setModalOpen(false);
    setConfirmacionInput('');
    setErrorMsg(null);
    setSuccessMsg(null);
  };

  const handleWipe = async () => {
    if (confirmacionInput !== CONFIRMATION_WORD) return;
    setLoading(true);
    setErrorMsg(null);
    setSuccessMsg(null);

    try {
      const { data } = await api.post(ENDPOINT, {
        confirmacion: CONFIRMATION_WORD,
        incluir_caja_banco: incluirCajaBanco,
      });
      setSuccessMsg(data.mensaje || 'Tablas limpiadas correctamente.');
      if (onWipeComplete) onWipeComplete();
    } catch (err) {
      const detail =
        err?.response?.data?.detail ||
        err?.response?.data?.error?.message ||
        'Error al limpiar las tablas.';
      setErrorMsg(typeof detail === 'string' ? detail : JSON.stringify(detail));
    } finally {
      setLoading(false);
    }
  };

  const canSubmit = confirmacionInput === CONFIRMATION_WORD && !loading;

  return (
    <>
      <button
        type="button"
        className={styles.triggerBtn}
        onClick={openModal}
        title="Limpiar datos de compras (solo testing)"
      >
        <Trash2 size={14} />
        <span>Limpiar datos compras</span>
      </button>

      {modalOpen && (
        <div className={styles.overlay} role="dialog" aria-modal="true" aria-label="Confirmar limpieza de compras">
          <div className={styles.modal}>
            <button
              type="button"
              className={styles.closeBtn}
              onClick={closeModal}
              aria-label="Cerrar"
              disabled={loading}
            >
              <X size={16} />
            </button>

            <div className={styles.header}>
              <AlertTriangle size={24} className={styles.warningIcon} />
              <h2 className={styles.title}>Limpiar datos de compras</h2>
            </div>

            <p className={styles.description}>
              Esta acción elimina <strong>todos</strong> los datos del módulo compras:
              pedidos, órdenes de pago, imputaciones, cuenta corriente, notas de crédito y eventos.
              Es <strong>irreversible</strong>. Solo para entornos de prueba.
            </p>

            <label className={styles.checkLabel}>
              <input
                type="checkbox"
                checked={incluirCajaBanco}
                onChange={(e) => setIncluirCajaBanco(e.target.checked)}
                disabled={loading}
              />
              <span>Incluir movimientos de caja y banco</span>
            </label>

            <div className={styles.confirmGroup}>
              <label className={styles.confirmLabel} htmlFor="wipe-confirm-input">
                Escribí <strong>WIPE</strong> para confirmar:
              </label>
              <input
                id="wipe-confirm-input"
                type="text"
                className={styles.confirmInput}
                value={confirmacionInput}
                onChange={(e) => setConfirmacionInput(e.target.value)}
                placeholder="WIPE"
                disabled={loading}
                autoComplete="off"
              />
            </div>

            {errorMsg && <p className={styles.errorMsg}>{errorMsg}</p>}
            {successMsg && <p className={styles.successMsg}>{successMsg}</p>}

            <div className={styles.actions}>
              <button
                type="button"
                className={styles.cancelBtn}
                onClick={closeModal}
                disabled={loading}
              >
                Cancelar
              </button>
              <button
                type="button"
                className={styles.wipeBtn}
                onClick={handleWipe}
                disabled={!canSubmit}
              >
                {loading ? 'Limpiando...' : 'Limpiar todo'}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
