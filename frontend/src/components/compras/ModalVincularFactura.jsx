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
import api from '../../services/api';
import { formatMoneda, formatMonedaErp, monedaDeCurrId } from './_shared/formatMoneda';
import styles from './ModalVincularFactura.module.css';

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

/**
 * ModalVincularFactura — vincula manualmente un pedido a una factura del ERP,
 * con opción de ajustar el monto del pedido al valor de la factura (append-only:
 * la diferencia queda como movimiento de ajuste en CC proveedor).
 *
 * Props:
 *   - pedido: { id, numero, monto, moneda } (pedido destino, ya cargado)
 *   - onClose(reload): cierra modal; reload=true fuerza refresh del pedido
 */
export default function ModalVincularFactura({ pedido, onClose }) {
  const { tienePermiso } = usePermisos();
  const canAdjust = tienePermiso('administracion.ajustar_monto_pedido');

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

  const montoPedido = Number(pedido?.monto) || 0;
  const montoFactura = Number(seleccionada?.ct_total) || 0;
  const diferencia = montoFactura - montoPedido;

  // The ERP invoice carries its OWN currency; it does not have to match the
  // pedido's (cross-currency linking is supported by the backend). Subtracting
  // amounts in different currencies is meaningless, so the difference — and the
  // adjustment flow it gates — only exist when both currencies are known and equal.
  const monedaPedido = pedido?.moneda ?? null;
  const monedaFactura = monedaDeCurrId(seleccionada?.curr_id_transaction);
  const montosComparables =
    !!seleccionada && monedaFactura !== null && monedaFactura === monedaPedido;
  const monedasNoComparables = !!seleccionada && !montosComparables;
  const hayDiferencia = montosComparables && Math.abs(diferencia) >= 0.01;

  // `ajustar` is user state that survives changing the selected invoice, so it
  // must never be trusted on its own — a mismatched selection would otherwise
  // still POST ajustar_monto=true (which the backend rejects with a 400 via
  // `_validar_moneda_factura_coincide`).
  const puedeAjustar = hayDiferencia && canAdjust;
  const ajustarEfectivo = ajustar && puedeAjustar;

  const fetchCandidatas = useCallback(async () => {
    if (!pedido?.id) return;
    setLoading(true);
    setError(null);
    try {
      const { data } = await api.get(
        `/administracion/compras/pedidos/${pedido.id}/facturas-candidatas`
      );
      setCandidatas(data || []);
    } catch (err) {
      setError(err.response?.data?.detail || 'Error al cargar facturas candidatas.');
    } finally {
      setLoading(false);
    }
  }, [pedido?.id]);

  useEffect(() => {
    fetchCandidatas();
  }, [fetchCandidatas]);

  const handleVincular = async () => {
    if (!seleccionada) return;
    if (ajustarEfectivo && !motivo.trim()) {
      setError('Indicá un motivo para el ajuste de monto.');
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const body = {
        ct_transaction: seleccionada.ct_transaction,
        ajustar_monto: ajustarEfectivo,
      };
      if (ajustarEfectivo) {
        body.nuevo_monto = String(seleccionada.ct_total);
        body.motivo_ajuste = motivo.trim();
      }
      await api.post(
        `/administracion/compras/pedidos/${pedido.id}/vincular-factura`,
        body
      );
      onClose(true);
    } catch (err) {
      setError(err.response?.data?.detail || 'Error al vincular factura.');
    } finally {
      setSubmitting(false);
    }
  };

  const puedeConfirmar =
    !!seleccionada && !submitting && (!ajustarEfectivo || motivo.trim().length > 0);

  return (
    <div className={styles.modalOverlay}>
      <div className={styles.modalContent}>
        <div className={styles.modalHeader}>
          <span className={styles.modalTitle}>
            <Link2 size={18} /> Vincular factura — Pedido {pedido?.numero}
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
            <Loader2 size={18} className={styles.spin} /> Cargando facturas…
          </div>
        ) : candidatas.length === 0 ? (
          <div className={styles.empty}>
            No hay facturas vigentes en el ERP para el proveedor de este pedido. Si
            la factura fue cargada recientemente, esperá a que el sync la tome.
          </div>
        ) : (
          <>
            <p className={styles.instructions}>
              Seleccioná la factura del ERP que corresponde a este pedido. Si el
              monto difiere, podés ajustarlo al valor de la factura (se registrará
              un movimiento de ajuste en cuenta corriente del proveedor).
            </p>

            <div className={styles.tableWrapper}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th></th>
                    <th>Nº factura</th>
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
                          name="factura_candidata"
                          checked={seleccionadaId === c.ct_transaction}
                          onChange={() => setSeleccionadaId(c.ct_transaction)}
                        />
                      </td>
                      <td className={styles.tdMono}>{c.ct_docnumber}</td>
                      <td>{formatDate(c.ct_date)}</td>
                      <td className={styles.tdRight}>
                        {formatMonedaErp(c.ct_total, c.curr_id_transaction)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {seleccionada && (
              <div className={styles.comparisonBlock}>
                <div className={styles.compRow}>
                  <span className={styles.compLabel}>Monto del pedido</span>
                  <strong className={styles.compValue}>
                    {formatMoneda(pedido?.monto, pedido?.moneda)}
                  </strong>
                </div>
                <div className={styles.compRow}>
                  <span className={styles.compLabel}>Monto de la factura</span>
                  <strong className={styles.compValue}>
                    {formatMonedaErp(
                      seleccionada.ct_total,
                      seleccionada.curr_id_transaction
                    )}
                  </strong>
                </div>
                {monedasNoComparables ? (
                  <div className={styles.monedaMismatch} role="status">
                    <AlertTriangle size={14} /> El pedido está en{' '}
                    {monedaPedido || 'moneda desconocida'} y la factura en{' '}
                    {monedaFactura || 'moneda desconocida'}. Los montos no son
                    comparables: no se puede calcular la diferencia ni ajustar el
                    monto del pedido.
                  </div>
                ) : (
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
                        ? `${diferencia > 0 ? '+' : ''}${formatMoneda(
                            diferencia,
                            monedaPedido
                          )}`
                        : '—'}
                    </strong>
                  </div>
                )}

                {puedeAjustar && (
                  <div className={styles.ajusteBlock}>
                    <label className={styles.checkboxRow}>
                      <input
                        type="checkbox"
                        checked={ajustar}
                        onChange={(e) => setAjustar(e.target.checked)}
                      />
                      <span>Ajustar el monto del pedido al valor de la factura</span>
                    </label>

                    {ajustar && (
                      <div className={styles.motivoRow}>
                        <label className={styles.motivoLabel}>
                          Motivo (obligatorio)
                        </label>
                        <textarea
                          className={styles.textarea}
                          rows={3}
                          value={motivo}
                          onChange={(e) => setMotivo(e.target.value)}
                          placeholder="Ej: variación de TC al pagar, descuento tardío, diferencia impositiva…"
                          maxLength={500}
                        />
                      </div>
                    )}
                  </div>
                )}

                {hayDiferencia && !canAdjust && (
                  <div className={styles.noPermisoHint}>
                    El monto difiere, pero no tenés permiso para ajustarlo.
                    Contactá al administrador si corresponde hacerlo.
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
            ) : ajustarEfectivo ? (
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
