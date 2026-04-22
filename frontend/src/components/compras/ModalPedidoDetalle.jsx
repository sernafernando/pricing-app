import { useCallback, useEffect, useState } from 'react';
import {
  X,
  Loader2,
  FileText,
  Send,
  Check,
  XCircle,
  Ban,
  RotateCcw,
  Wallet,
  CreditCard,
  AlertCircle,
  Pencil,
  Truck,
  Link2,
  Link2Off,
  Paperclip,
} from 'lucide-react';
import { usePermisos } from '../../contexts/PermisosContext';
import useComprasPedidos from '../../hooks/useComprasPedidos';
import AdjuntosPanel from './AdjuntosPanel';
import ModalVincularFactura from './ModalVincularFactura';
import styles from './ModalPedidoDetalle.module.css';

const eventoIcon = (tipo) => {
  const t = (tipo || '').toLowerCase();
  if (t.includes('creado')) return FileText;
  if (t.includes('enviado') || t.includes('enviar')) return Send;
  if (t.includes('aprobado')) return Check;
  if (t.includes('rechaz')) return XCircle;
  if (t.includes('cancel')) return Ban;
  if (t.includes('reabier')) return RotateCcw;
  if (t.includes('pago') || t.includes('pagad')) return Wallet;
  if (t.includes('imputa')) return CreditCard;
  if (t.includes('editado') || t.includes('editar')) return Pencil;
  if (t.includes('etiqueta') || t.includes('envio')) return Truck;
  if (t.includes('match')) return Link2;
  return AlertCircle;
};

const formatDate = (isoStr) => {
  if (!isoStr) return '';
  try {
    const d = new Date(isoStr);
    return d.toLocaleString('es-AR', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return isoStr;
  }
};

const formatCurrency = (value, moneda = 'ARS') => {
  const num = Number(value) || 0;
  const prefix = moneda === 'USD' ? 'US$' : '$';
  return `${prefix}${num.toLocaleString('es-AR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
};

export default function ModalPedidoDetalle({ pedidoId, onClose }) {
  // Desestructurar función memoizada para evitar loop en useEffect.
  const { obtener: obtenerPedido, desvincularFactura } = useComprasPedidos();
  const { tienePermiso } = usePermisos();

  const canGestionar = tienePermiso('administracion.gestionar_ordenes_compra');

  const [pedido, setPedido] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [showVincularModal, setShowVincularModal] = useState(false);
  const [desvinculando, setDesvinculando] = useState(false);

  const fetchDetalle = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await obtenerPedido(pedidoId);
      setPedido(data);
    } catch (err) {
      setError(err.response?.data?.detail || 'Error al cargar el pedido.');
    } finally {
      setLoading(false);
    }
  }, [obtenerPedido, pedidoId]);

  useEffect(() => {
    fetchDetalle();
  }, [fetchDetalle]);

  const handleDesvincular = useCallback(async () => {
    if (!pedido?.id) return;
    try {
      setDesvinculando(true);
      setError(null);
      await desvincularFactura(pedido.id);
      await fetchDetalle();
    } catch (err) {
      setError(err.response?.data?.detail || 'Error al desvincular la factura.');
    } finally {
      setDesvinculando(false);
    }
  }, [desvincularFactura, pedido?.id, fetchDetalle]);

  const handleVincularClose = useCallback(
    (reload) => {
      setShowVincularModal(false);
      if (reload) fetchDetalle();
    },
    [fetchDetalle]
  );

  return (
    <div className={styles.modalOverlay}>
      <div className={styles.modalContent}>
        <div className={styles.modalHeader}>
          <span className={styles.modalTitle}>
            {pedido ? `Pedido ${pedido.numero}` : 'Detalle del pedido'}
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

        {loading && (
          <div className={styles.centered}>
            <Loader2 size={20} className={styles.spin} /> Cargando...
          </div>
        )}
        {error && <div className={styles.errorBanner}>{error}</div>}

        {pedido && !loading && (
          <>
            {/* ── Info block ── */}
            <div className={styles.infoGrid}>
              <div>
                <span className={styles.infoLabel}>Estado</span>
                <strong className={styles.infoValue}>{pedido.estado}</strong>
              </div>
              <div>
                <span className={styles.infoLabel}>Empresa</span>
                <strong className={styles.infoValue}>
                  {pedido.empresa_nombre || `#${pedido.empresa_id}`}
                </strong>
              </div>
              <div>
                <span className={styles.infoLabel}>Proveedor</span>
                <strong className={styles.infoValue}>
                  {pedido.proveedor_nombre || `#${pedido.proveedor_id}`}
                </strong>
              </div>
              <div>
                <span className={styles.infoLabel}>Moneda</span>
                <strong className={styles.infoValue}>{pedido.moneda}</strong>
              </div>
              <div>
                <span className={styles.infoLabel}>Monto</span>
                <strong className={styles.infoValue}>
                  {formatCurrency(pedido.monto, pedido.moneda)}
                </strong>
              </div>
              {pedido.moneda === 'USD' && (
                <div>
                  <span className={styles.infoLabel}>Tipo de cambio</span>
                  <strong className={styles.infoValue}>
                    {pedido.tipo_cambio
                      ? `$${Number(pedido.tipo_cambio).toLocaleString('es-AR', {
                          minimumFractionDigits: 2,
                          maximumFractionDigits: 4,
                        })} / USD`
                      : '—'}
                  </strong>
                </div>
              )}
              <div>
                <span className={styles.infoLabel}>Plazo (PM)</span>
                <strong className={styles.infoValue}>{pedido.fecha_pago_texto || '—'}</strong>
              </div>
              <div>
                <span className={styles.infoLabel}>Fecha pago estimada</span>
                <strong className={styles.infoValue}>
                  {pedido.fecha_pago_estimada
                    ? (() => {
                        const [y, m, d] = String(pedido.fecha_pago_estimada)
                          .split('T')[0]
                          .split('-');
                        return y && m && d ? `${d}/${m}/${y}` : pedido.fecha_pago_estimada;
                      })()
                    : '—'}
                </strong>
              </div>
              <div>
                <span className={styles.infoLabel}>Requiere envío</span>
                <strong className={styles.infoValue}>
                  {pedido.requiere_envio ? 'Sí' : 'No'}
                </strong>
              </div>
              <div>
                <span className={styles.infoLabel}>N° Factura</span>
                <strong className={styles.infoValue}>{pedido.numero_factura || '—'}</strong>
              </div>
              {pedido.ct_transaction_id && (
                <div>
                  <span className={styles.infoLabel}>ERP ct_transaction</span>
                  <strong className={styles.infoValue}>#{pedido.ct_transaction_id}</strong>
                </div>
              )}
            </div>

            {/* ── Factura del ERP ── */}
            <h3 className={styles.sectionTitle}>
              <Link2 size={14} /> Factura del ERP
            </h3>
            <div className={styles.facturaBlock}>
              {pedido.ct_transaction_id ? (
                <div className={styles.facturaVinculada}>
                  <div className={styles.facturaInfo}>
                    <span className={styles.facturaMain}>
                      Vinculada a ct_transaction <strong>#{pedido.ct_transaction_id}</strong>
                    </span>
                    {pedido.numero_factura && (
                      <span className={styles.facturaSub}>
                        Nº factura: {pedido.numero_factura}
                      </span>
                    )}
                  </div>
                  {canGestionar && (
                    <button
                      type="button"
                      className={styles.btnGhost}
                      onClick={handleDesvincular}
                      disabled={desvinculando}
                      title="Desvincular factura (no revierte ajustes previos)"
                    >
                      {desvinculando ? (
                        <Loader2 size={14} className={styles.spin} />
                      ) : (
                        <Link2Off size={14} />
                      )}
                      Desvincular
                    </button>
                  )}
                </div>
              ) : (
                <div className={styles.facturaNoVinculada}>
                  <span className={styles.emptyHint}>
                    Sin factura ERP vinculada.
                  </span>
                  {canGestionar && (
                    <button
                      type="button"
                      className={styles.btnPrimaryInline}
                      onClick={() => setShowVincularModal(true)}
                    >
                      <Link2 size={14} /> Vincular factura
                    </button>
                  )}
                </div>
              )}
            </div>

            {/* ── Adjuntos ── */}
            <h3 className={styles.sectionTitle}>
              <Paperclip size={14} /> Adjuntos
            </h3>
            <AdjuntosPanel
              entidadTipo="pedido_compra"
              entidadId={pedido.id}
              canManage={canGestionar}
            />

            {/* ── Imputaciones ── */}
            <h3 className={styles.sectionTitle}>
              Imputaciones ({pedido.imputaciones?.length || 0})
            </h3>
            {(!pedido.imputaciones || pedido.imputaciones.length === 0) ? (
              <div className={styles.emptySection}>Sin imputaciones aún.</div>
            ) : (
              <div className={styles.tableWrapper}>
                <table className={styles.table}>
                  <thead>
                    <tr>
                      <th>ID</th>
                      <th>Origen</th>
                      <th className={styles.thRight}>Monto</th>
                      <th>Moneda</th>
                      <th>Fecha</th>
                      <th>Reversal</th>
                    </tr>
                  </thead>
                  <tbody>
                    {pedido.imputaciones.map((i) => (
                      <tr key={i.id}>
                        <td className={styles.tdMono}>#{i.id}</td>
                        <td>
                          {i.origen_tipo} #{i.origen_id}
                        </td>
                        <td className={styles.tdRight}>
                          {formatCurrency(i.monto_imputado, i.moneda_imputada)}
                        </td>
                        <td>{i.moneda_imputada}</td>
                        <td className={styles.tdSecondary}>{formatDate(i.created_at)}</td>
                        <td>
                          {i.es_reversal ? (
                            <span className={styles.badgeReversal}>Reversal</span>
                          ) : (
                            '—'
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {/* ── Timeline de eventos ── */}
            <h3 className={styles.sectionTitle}>
              Timeline ({pedido.eventos?.length || 0})
            </h3>
            {(!pedido.eventos || pedido.eventos.length === 0) ? (
              <div className={styles.emptySection}>Sin eventos.</div>
            ) : (
              <ul className={styles.timeline}>
                {pedido.eventos.map((ev) => {
                  const Icon = eventoIcon(ev.tipo);
                  return (
                    <li key={ev.id} className={styles.timelineItem}>
                      <div className={styles.timelineIcon}>
                        <Icon size={14} />
                      </div>
                      <div className={styles.timelineBody}>
                        <div className={styles.timelineHeader}>
                          <span className={styles.timelineType}>{ev.tipo}</span>
                          <span className={styles.timelineDate}>{formatDate(ev.created_at)}</span>
                        </div>
                        <div className={styles.timelineMeta}>
                          Usuario #{ev.usuario_id}
                        </div>
                        {ev.payload && Object.keys(ev.payload).length > 0 && (
                          <pre className={styles.timelinePayload}>
                            {JSON.stringify(ev.payload, null, 2)}
                          </pre>
                        )}
                      </div>
                    </li>
                  );
                })}
              </ul>
            )}
          </>
        )}

        <div className={styles.formActions}>
          <button
            type="button"
            className={styles.btnSecondary}
            onClick={() => onClose(false)}
          >
            Cerrar
          </button>
        </div>
      </div>

      {showVincularModal && pedido && (
        <ModalVincularFactura pedido={pedido} onClose={handleVincularClose} />
      )}
    </div>
  );
}
