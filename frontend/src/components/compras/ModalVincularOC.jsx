import { useCallback, useEffect, useState } from 'react';
import { X, Loader2, Link2, AlertCircle } from 'lucide-react';
import { usePermisos } from '../../contexts/PermisosContext';
import api from '../../services/api';
import styles from './ModalVincularOC.module.css';

const formatDate = (isoStr) => {
  if (!isoStr) return '—';
  try {
    const d = new Date(isoStr);
    return d.toLocaleDateString('es-AR', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
    });
  } catch {
    return isoStr;
  }
};

const formatCurrency = (value) => {
  const num = Number(value) || 0;
  return `$${num.toLocaleString('es-AR', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
};

/**
 * ModalVincularOC — links a purchase order (OC) from the ERP to a pedido.
 *
 * Props:
 *   - pedido: { id, numero } — the pedido to link
 *   - onClose(): closes the modal without changes
 *   - onVinculada(updatedPedido): called on successful link with the updated pedido
 */
export default function ModalVincularOC({ pedido, onClose, onVinculada }) {
  const { tienePermiso } = usePermisos();
  const canGestionar = tienePermiso('administracion.gestionar_ordenes_compra');

  const [candidatas, setCandidatas] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [seleccionada, setSeleccionada] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  const fetchCandidatas = useCallback(async () => {
    if (!pedido?.id) return;
    setLoading(true);
    setError(null);
    try {
      const { data } = await api.get(
        `/administracion/compras/pedidos/${pedido.id}/oc-candidatas`
      );
      setCandidatas(data || []);
    } catch (err) {
      setError(
        err.response?.data?.error?.message ||
          err.response?.data?.detail ||
          'Error al cargar órdenes de compra candidatas.'
      );
    } finally {
      setLoading(false);
    }
  }, [pedido?.id]);

  useEffect(() => {
    fetchCandidatas();
  }, [fetchCandidatas]);

  const handleVincular = async () => {
    if (!seleccionada) return;
    setSubmitting(true);
    setError(null);
    try {
      const { data } = await api.post(
        `/administracion/compras/pedidos/${pedido.id}/vincular-oc`,
        {
          oc_comp_id: seleccionada.oc_comp_id,
          oc_bra_id: seleccionada.oc_bra_id,
          oc_poh_id: seleccionada.oc_poh_id,
        }
      );
      onVinculada(data);
    } catch (err) {
      setError(
        err.response?.data?.error?.message ||
          err.response?.data?.detail ||
          'Error al vincular la orden de compra.'
      );
    } finally {
      setSubmitting(false);
    }
  };

  if (!canGestionar) return null;

  return (
    <div className={styles.modalOverlay}>
      <div className={styles.modalContent}>
        <div className={styles.modalHeader}>
          <span className={styles.modalTitle}>
            <Link2 size={18} /> Vincular OC — Pedido {pedido?.numero}
          </span>
          <button
            className={styles.modalCloseBtn}
            onClick={onClose}
            aria-label="Cerrar"
            type="button"
          >
            <X size={18} />
          </button>
        </div>

        {error && (
          <div className={styles.errorBanner}>
            <AlertCircle size={14} /> {error}
          </div>
        )}

        {loading ? (
          <div className={styles.centered}>
            <Loader2 size={18} className={styles.spin} /> Cargando órdenes de compra…
          </div>
        ) : candidatas.length === 0 ? (
          <div className={styles.empty}>
            No hay órdenes de compra pendientes en el ERP para el proveedor de este
            pedido. Si la OC fue cargada recientemente, esperá a que el sync la tome.
          </div>
        ) : (
          <>
            <p className={styles.instructions}>
              Seleccioná la orden de compra del ERP que corresponde a este pedido.
              Solo se muestran OCs con al menos una línea sin procesar.
            </p>

            <div className={styles.tableWrapper}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th></th>
                    <th>Nº OC</th>
                    <th>Fecha</th>
                    <th className={styles.thRight}>Total</th>
                    <th className={styles.thRight}>Líneas pendientes</th>
                  </tr>
                </thead>
                <tbody>
                  {candidatas.map((c) => {
                    const key = `${c.oc_comp_id}-${c.oc_bra_id}-${c.oc_poh_id}`;
                    const isSelected =
                      seleccionada?.oc_poh_id === c.oc_poh_id &&
                      seleccionada?.oc_comp_id === c.oc_comp_id &&
                      seleccionada?.oc_bra_id === c.oc_bra_id;
                    return (
                      <tr
                        key={key}
                        className={isSelected ? styles.rowSelected : ''}
                        onClick={() => setSeleccionada(c)}
                      >
                        <td className={styles.tdRadio}>
                          <input
                            type="radio"
                            name="oc_candidata"
                            checked={isSelected}
                            onChange={() => setSeleccionada(c)}
                          />
                        </td>
                        <td className={styles.tdMono}>{`#${c.oc_poh_id}`}</td>
                        <td>{c.poh_cd ? formatDate(c.poh_cd) : '—'}</td>
                        <td className={styles.tdRight}>{formatCurrency(c.poh_total)}</td>
                        <td className={styles.tdRight}>{c.lineas_pendientes ?? '—'}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </>
        )}

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
            onClick={handleVincular}
            disabled={!seleccionada || submitting}
          >
            {submitting ? (
              <Loader2 size={14} className={styles.spin} />
            ) : (
              'Vincular OC'
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
