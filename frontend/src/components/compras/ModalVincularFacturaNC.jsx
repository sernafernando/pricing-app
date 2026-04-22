import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  X,
  Loader2,
  Link2,
  AlertTriangle,
  CheckCircle,
  AlertCircle,
} from 'lucide-react';
import { usePermisos } from '../../contexts/PermisosContext';
import useNCsLocales from '../../hooks/useNCsLocales';
import styles from './ModalVincularFacturaNC.module.css';

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

const formatCurrency = (value, moneda = 'ARS') => {
  const num = Number(value) || 0;
  const prefix = moneda === 'USD' ? 'US$' : '$';
  return `${prefix}${num.toLocaleString('es-AR', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
};

/**
 * ModalVincularFacturaNC — vincula una NC local con una NC del ERP
 * (sd_iscreditnote=TRUE). Gemelo de `ModalVincularFactura` (pedidos), pero:
 *   - Endpoint: `/ncs-locales/{id}/candidatas-erp` y `/vincular-factura`.
 *   - El destino ERP es una NC del ERP, no una factura.
 *   - Permiso para ajustar monto: `administracion.ajustar_monto_pedido` (reusado).
 *
 * Props:
 *   - nc: { id, numero, monto, moneda } (NC local destino).
 *   - onClose(reload): cierra modal; reload=true fuerza refresh del detalle.
 */
export default function ModalVincularFacturaNC({ nc, onClose }) {
  const { tienePermiso } = usePermisos();
  const canAdjust = tienePermiso('administracion.ajustar_monto_pedido');
  const { listarCandidatasERP, vincularFactura } = useNCsLocales();

  const [candidatas, setCandidatas] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [seleccionadaId, setSeleccionadaId] = useState(null);
  const [ajustar, setAjustar] = useState(false);
  const [motivo, setMotivo] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const seleccionada = useMemo(
    () => candidatas.find((c) => c.ct_transaction === seleccionadaId) || null,
    [candidatas, seleccionadaId]
  );

  const montoNC = Number(nc?.monto) || 0;
  const montoERP = Number(seleccionada?.ct_total) || 0;
  const diferencia = montoERP - montoNC;
  const hayDiferencia = Math.abs(diferencia) >= 0.01;

  const fetchCandidatas = useCallback(async () => {
    if (!nc?.id) return;
    setLoading(true);
    setError(null);
    try {
      const data = await listarCandidatasERP(nc.id);
      setCandidatas(data || []);
    } catch (err) {
      const msg =
        err.response?.data?.error?.message ||
        err.response?.data?.detail ||
        'Error al cargar NCs del ERP candidatas.';
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, [listarCandidatasERP, nc?.id]);

  useEffect(() => {
    fetchCandidatas();
  }, [fetchCandidatas]);

  const handleVincular = async () => {
    if (!seleccionada) return;
    if (ajustar && !motivo.trim()) {
      setError('Indicá un motivo para el ajuste de monto.');
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const body = {
        ct_transaction: seleccionada.ct_transaction,
        ajustar_monto: !!ajustar,
      };
      if (ajustar) {
        body.nuevo_monto = String(seleccionada.ct_total);
        body.motivo_ajuste = motivo.trim();
      }
      await vincularFactura(nc.id, body);
      onClose(true);
    } catch (err) {
      const msg =
        err.response?.data?.error?.message ||
        err.response?.data?.detail ||
        'Error al vincular la NC del ERP.';
      setError(msg);
    } finally {
      setSubmitting(false);
    }
  };

  const puedeConfirmar =
    !!seleccionada && !submitting && (!ajustar || motivo.trim().length > 0);

  return (
    <div className={styles.modalOverlay}>
      <div className={styles.modalContent}>
        <div className={styles.modalHeader}>
          <span className={styles.modalTitle}>
            <Link2 size={18} /> Vincular NC del ERP — {nc?.numero}
          </span>
          <button
            className={styles.modalCloseBtn}
            onClick={() => onClose(false)}
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
            <Loader2 size={18} className={styles.spin} /> Cargando NCs del ERP…
          </div>
        ) : candidatas.length === 0 ? (
          <div className={styles.empty}>
            No hay NCs vigentes en el ERP para el proveedor de esta NC local. Si la
            NC fue cargada al ERP recientemente, esperá al próximo sync.
          </div>
        ) : (
          <>
            <p className={styles.instructions}>
              Seleccioná la NC del ERP (sd_iscreditnote=TRUE) que corresponde a
              esta NC local. Si el monto difiere, podés ajustarlo (se registrará
              un movimiento de ajuste en cuenta corriente del proveedor).
            </p>

            <div className={styles.tableWrapper}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th></th>
                    <th>Nº NC ERP</th>
                    <th>Fecha</th>
                    <th className={styles.thRight}>Total</th>
                  </tr>
                </thead>
                <tbody>
                  {candidatas.map((c) => (
                    <tr
                      key={c.ct_transaction}
                      className={
                        seleccionadaId === c.ct_transaction ? styles.rowSelected : ''
                      }
                      onClick={() => setSeleccionadaId(c.ct_transaction)}
                    >
                      <td className={styles.tdRadio}>
                        <input
                          type="radio"
                          name="nc_candidata_erp"
                          checked={seleccionadaId === c.ct_transaction}
                          onChange={() => setSeleccionadaId(c.ct_transaction)}
                        />
                      </td>
                      <td className={styles.tdMono}>{c.ct_docnumber}</td>
                      <td>{formatDate(c.ct_date)}</td>
                      <td className={styles.tdRight}>
                        {formatCurrency(c.ct_total, nc?.moneda)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {seleccionada && (
              <div className={styles.comparisonBlock}>
                <div className={styles.compRow}>
                  <span className={styles.compLabel}>Monto de la NC local</span>
                  <strong className={styles.compValue}>
                    {formatCurrency(nc?.monto, nc?.moneda)}
                  </strong>
                </div>
                <div className={styles.compRow}>
                  <span className={styles.compLabel}>Monto de la NC ERP</span>
                  <strong className={styles.compValue}>
                    {formatCurrency(seleccionada.ct_total, nc?.moneda)}
                  </strong>
                </div>
                <div
                  className={`${styles.compRow} ${
                    hayDiferencia ? styles.diffBad : styles.diffOk
                  }`}
                >
                  <span className={styles.compLabel}>
                    {hayDiferencia ? (
                      <>
                        <AlertTriangle size={14} /> Diferencia
                      </>
                    ) : (
                      <>
                        <CheckCircle size={14} /> Coinciden
                      </>
                    )}
                  </span>
                  <strong className={styles.compValue}>
                    {hayDiferencia
                      ? `${diferencia > 0 ? '+' : ''}${formatCurrency(
                          diferencia,
                          nc?.moneda
                        )}`
                      : '—'}
                  </strong>
                </div>

                {hayDiferencia && canAdjust && (
                  <div className={styles.ajusteBlock}>
                    <label className={styles.checkboxRow}>
                      <input
                        type="checkbox"
                        checked={ajustar}
                        onChange={(e) => setAjustar(e.target.checked)}
                      />
                      <span>Ajustar el monto de la NC local al valor del ERP</span>
                    </label>

                    {ajustar && (
                      <div className={styles.motivoRow}>
                        <label className={styles.motivoLabel}>Motivo (obligatorio)</label>
                        <textarea
                          className={styles.textarea}
                          rows={3}
                          value={motivo}
                          onChange={(e) => setMotivo(e.target.value)}
                          placeholder="Ej: diferencia por redondeo, cambio de TC, ajuste impositivo…"
                          maxLength={500}
                        />
                      </div>
                    )}
                  </div>
                )}

                {hayDiferencia && !canAdjust && (
                  <div className={styles.noPermisoHint}>
                    El monto difiere, pero no tenés permiso para ajustarlo.
                    Contactá al administrador si corresponde.
                  </div>
                )}
              </div>
            )}
          </>
        )}

        <div className={styles.formActions}>
          <button
            type="button"
            className={styles.btnSecondary}
            onClick={() => onClose(false)}
            disabled={submitting}
          >
            Cancelar
          </button>
          <button
            type="button"
            className={styles.btnPrimary}
            onClick={handleVincular}
            disabled={!puedeConfirmar}
          >
            {submitting ? (
              <Loader2 size={14} className={styles.spin} />
            ) : ajustar ? (
              'Vincular y ajustar'
            ) : (
              'Vincular'
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
