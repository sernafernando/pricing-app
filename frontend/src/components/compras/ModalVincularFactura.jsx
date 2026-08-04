import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  X,
  Loader2,
  Link2,
  AlertTriangle,
  CheckCircle,
  AlertCircle,
  Info,
} from 'lucide-react';
import { usePermisos } from '../../contexts/PermisosContext';
import api from '../../services/api';
import {
  equivalenteEnArs,
  formatMoneda,
  formatMonedaErp,
  formatTC,
  monedaDeCurrId,
} from './_shared/formatMoneda';
import styles from './ModalVincularFactura.module.css';

/**
 * Expresses an amount in ARS, the module's functional currency (see the
 * convention documented in `_shared/formatMoneda.js`).
 *
 * ARS → itself. USD → `monto * tc`, but ONLY with a usable TC. Anything else
 * (unknown currency, USD without a TC) → `null`, meaning "no ARS equivalent
 * exists", which callers must treat as NOT comparable. Never invent a rate:
 * today's rate is not the rate this document was priced at.
 *
 * @param {number} monto
 * @param {'ARS'|'USD'|null} moneda
 * @param {number|string|null|undefined} tc
 * @returns {number|null}
 */
const montoEnArs = (monto, moneda, tc) => {
  if (moneda === 'ARS') return monto;
  return equivalenteEnArs(monto, moneda, tc);
};

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

  // The ERP invoice carries its OWN currency; it does not have to match the
  // pedido's (cross-currency linking is supported by the backend).
  const monedaPedido = pedido?.moneda ?? null;
  const monedaFactura = monedaDeCurrId(seleccionada?.curr_id_transaction);
  const tcPedido = pedido?.tipo_cambio ?? null;

  // Both sides expressed in ARS. A USD pedido carries its own `tipo_cambio`;
  // an ERP document never does, so a USD invoice has no ARS equivalent here —
  // hence the explicit null TC. No fallback, no "rate of the day".
  const montoPedidoArs = montoEnArs(montoPedido, monedaPedido, tcPedido);
  const montoFacturaArs = montoEnArs(montoFactura, monedaFactura, null);

  const monedasNativasCoinciden =
    monedaFactura !== null && monedaPedido !== null && monedaFactura === monedaPedido;

  // Cross-currency, but both sides land on ARS (in practice: pedido USD with TC
  // vs. the ARS invoice, which is 100% of the ERP purchase documents).
  const comparaEnArs =
    !monedasNativasCoinciden && montoPedidoArs !== null && montoFacturaArs !== null;

  const montosComparables =
    !!seleccionada && (monedasNativasCoinciden || comparaEnArs);
  const monedasNoComparables = !!seleccionada && !montosComparables;

  const monedaDiferencia = comparaEnArs ? 'ARS' : monedaPedido;
  const diferencia = comparaEnArs
    ? montoFacturaArs - montoPedidoArs
    : montoFactura - montoPedido;

  // ── TWO INDEPENDENT CONCEPTS. Do not fuse them again. ──────────────────
  //
  // 1) `hayDiferencia` — DISPLAY ONLY. We can show a meaningful difference,
  //    which now includes the cross-currency case resolved through the pedido's
  //    own TC.
  //
  // 2) `ajusteHabilitadoPorMoneda` — WRITE. The adjustment rewrites
  //    `pedido.monto` in the PEDIDO's own currency, so the backend requires the
  //    invoice to be in that same currency (`_validar_moneda_factura_coincide`,
  //    pedidos_service.py). It therefore depends on NATIVE currency equality and
  //    must NEVER be derived from the ARS-based comparability above: a pedido
  //    USD + factura ARS shows its difference and still offers no adjustment.
  //    Fusing these two is how pedido P-02-2026-00001 ended up with a 46M USD
  //    monto after being adjusted against an ARS invoice.
  const hayDiferencia = montosComparables && Math.abs(diferencia) >= 0.01;
  const ajusteHabilitadoPorMoneda = monedasNativasCoinciden;

  // `ajustar` is user state that survives changing the selected invoice, so it
  // must never be trusted on its own — a mismatched selection would otherwise
  // still POST ajustar_monto=true (which the backend rejects with a 400).
  const puedeAjustar = ajusteHabilitadoPorMoneda && hayDiferencia && canAdjust;
  const ajustarEfectivo = ajustar && puedeAjustar;

  // Module convention: a USD pedido is shown ARS-first with its native amount
  // as muted secondary, and the TC is always stated alongside it.
  const mostrarPedidoEnArs = monedaPedido === 'USD' && montoPedidoArs !== null;

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
                  {mostrarPedidoEnArs ? (
                    <span className={styles.compValueStack}>
                      <strong className={styles.compValue}>
                        {formatMoneda(montoPedidoArs, 'ARS')}
                      </strong>
                      <span className={styles.compValueNativo}>
                        {formatMoneda(pedido?.monto, monedaPedido)} @ TC{' '}
                        {formatTC(tcPedido)}
                      </span>
                    </span>
                  ) : (
                    <strong className={styles.compValue}>
                      {formatMoneda(pedido?.monto, pedido?.moneda)}
                    </strong>
                  )}
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
                            monedaDiferencia
                          )}`
                        : '—'}
                    </strong>
                  </div>
                )}

                {comparaEnArs && (
                  <div className={styles.equivalenciaNota}>
                    <Info size={14} /> El pedido está en {monedaPedido} y la
                    factura en {monedaFactura}. La diferencia se calcula en ARS
                    convirtiendo el pedido al TC {formatTC(tcPedido)}. Por ser
                    monedas distintas, no se puede ajustar el monto del pedido
                    contra esta factura.
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

                {hayDiferencia && ajusteHabilitadoPorMoneda && !canAdjust && (
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
