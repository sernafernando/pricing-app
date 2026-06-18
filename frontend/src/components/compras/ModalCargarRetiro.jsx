import { useCallback, useEffect, useState } from 'react';
import { X, Loader2, Truck, AlertCircle, CheckCircle2 } from 'lucide-react';
import useRecepcionDeposito from '../../hooks/useRecepcionDeposito';
import styles from './ModalCargarRetiro.module.css';

/**
 * ModalCargarRetiro — triggers a carrier pickup (retiro_proveedor) for a pedido.
 *
 * Props:
 *   pedidoId      {number}   — the pedido to generate the pickup label for
 *   pedidoNumero  {string}   — display number
 *   proveedorId   {number}   — used to fetch the supplier's address list
 *   isOpen        {boolean}
 *   onClose       {Function} — close without action
 *   onSuccess     {Function} — called after successful label creation
 */
export default function ModalCargarRetiro({
  pedidoId,
  pedidoNumero,
  proveedorId,
  isOpen,
  onClose,
  onSuccess,
}) {
  const { getDireccionesProveedor, generarRetiro } = useRecepcionDeposito();

  const [direcciones, setDirecciones] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [seleccionada, setSeleccionada] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState(null);
  const [submitSuccess, setSubmitSuccess] = useState(null);

  const fetchDirecciones = useCallback(async () => {
    if (!proveedorId) return;
    setLoading(true);
    setError(null);
    try {
      const data = await getDireccionesProveedor(proveedorId);
      const list = Array.isArray(data) ? data : data.direcciones ?? [];
      setDirecciones(list);
      // Auto-select when there is only one option
      if (list.length === 1) {
        setSeleccionada(list[0].id ?? list[0].proveedor_direccion_id);
      }
    } catch (err) {
      setError(
        err.response?.data?.detail ||
          err.message ||
          'Error al cargar direcciones del proveedor.'
      );
    } finally {
      setLoading(false);
    }
  }, [getDireccionesProveedor, proveedorId]);

  useEffect(() => {
    if (isOpen) {
      fetchDirecciones();
    }
  }, [isOpen, fetchDirecciones]);

  const handleGenerarRetiro = async () => {
    if (!seleccionada) return;
    setSubmitting(true);
    setSubmitError(null);
    setSubmitSuccess(null);
    try {
      await generarRetiro(pedidoId, { proveedor_direccion_id: seleccionada });
      setSubmitSuccess('Retiro generado correctamente.');
      setTimeout(() => {
        onSuccess();
      }, 800);
    } catch (err) {
      const detail = err.response?.data?.detail;
      setSubmitError(
        typeof detail === 'string' ? detail : 'Error al generar el retiro.'
      );
    } finally {
      setSubmitting(false);
    }
  };

  if (!isOpen) return null;

  const direcId = (d) => d.id ?? d.proveedor_direccion_id;
  const direcLabel = (d) =>
    d.direccion ?? d.label ?? d.descripcion ?? `Dirección #${direcId(d)}`;

  return (
    <div className={styles.modalOverlay} role="dialog" aria-modal="true" aria-labelledby="modal-retiro-title">
      <div className={styles.modalContent}>
        {/* Header */}
        <div className={styles.modalHeader}>
          <span className={styles.modalTitle} id="modal-retiro-title">
            <Truck size={18} aria-hidden="true" />
            Despachar retiro — Pedido #{pedidoNumero}
          </span>
          <button
            type="button"
            className={styles.modalCloseBtn}
            onClick={onClose}
            aria-label="Cerrar"
          >
            <X size={18} />
          </button>
        </div>

        {/* Error fetching addresses */}
        {error && (
          <div className={styles.errorBanner} role="alert">
            <AlertCircle size={14} /> {error}
          </div>
        )}

        {/* Submit error */}
        {submitError && (
          <div className={styles.errorBanner} role="alert">
            <AlertCircle size={14} /> {submitError}
          </div>
        )}

        {/* Submit success */}
        {submitSuccess && (
          <div className={styles.successBanner} role="status">
            <CheckCircle2 size={14} /> {submitSuccess}
          </div>
        )}

        {/* Body */}
        {loading ? (
          <div className={styles.centered}>
            <Loader2 size={18} className={styles.spin} /> Cargando direcciones…
          </div>
        ) : direcciones.length === 0 && !error ? (
          <div className={styles.empty}>
            El proveedor no tiene direcciones registradas. Agregá una antes de generar el retiro.
          </div>
        ) : (
          <>
            <p className={styles.instructions}>
              Seleccioná la dirección del proveedor desde donde se realizará el retiro.
            </p>

            <div className={styles.addressList}>
              {direcciones.map((d) => {
                const id = direcId(d);
                const isSelected = seleccionada === id;
                return (
                  <label
                    key={id}
                    className={`${styles.addressRow} ${isSelected ? styles.addressRowSelected : ''}`}
                  >
                    <input
                      type="radio"
                      name="proveedor_direccion"
                      value={id}
                      checked={isSelected}
                      onChange={() => setSeleccionada(id)}
                    />
                    <span className={styles.addressLabel}>{direcLabel(d)}</span>
                  </label>
                );
              })}
            </div>
          </>
        )}

        {/* Footer */}
        <div className={styles.formActions}>
          <button
            type="button"
            className={styles.btnSecondary}
            onClick={onClose}
            disabled={submitting}
          >
            Cancelar
          </button>
          <button
            type="button"
            className={styles.btnPrimary}
            onClick={handleGenerarRetiro}
            disabled={!seleccionada || submitting}
          >
            {submitting ? (
              <Loader2 size={14} className={styles.spin} aria-hidden="true" />
            ) : null}
            Generar retiro
          </button>
        </div>
      </div>
    </div>
  );
}
