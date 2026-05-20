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
  Edit3,
  History,
  TrendingUp,
} from 'lucide-react';
import { usePermisos } from '../../contexts/PermisosContext';
import useComprasPedidos from '../../hooks/useComprasPedidos';
import api from '../../services/api';
import AdjuntosPanel from './AdjuntosPanel';
import EstadoBadge from './_shared/EstadoBadge';
import ModalVincularFactura from './ModalVincularFactura';
import ModalCorregirPedido from './ModalCorregirPedido';
import styles from './ModalPedidoDetalle.module.css';

// Estados desde los que se puede corregir un pedido (feature D).
const ESTADOS_CORREGIBLES = new Set(['aprobado', 'pagado_parcial', 'pagado']);

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
  const [showCorregirModal, setShowCorregirModal] = useState(false);
  // F2 — ND/NC variance circuit.
  const [resolviendoVarianza, setResolviendoVarianza] = useState(false);
  const [errorVarianza, setErrorVarianza] = useState(null);

  const puedeCorregir =
    canGestionar && pedido && ESTADOS_CORREGIBLES.has(pedido.estado);

  // Documentos ERP imputados (sub-batch 3.1).
  const [documentos, setDocumentos] = useState([]);
  const [loadingDocs, setLoadingDocs] = useState(false);

  const fetchDocumentos = useCallback(async (id) => {
    if (!id) return;
    setLoadingDocs(true);
    try {
      const { data } = await api.get(
        `/administracion/compras/pedidos/${id}/documentos-erp-imputados`
      );
      setDocumentos(Array.isArray(data) ? data : []);
    } catch {
      setDocumentos([]);
    } finally {
      setLoadingDocs(false);
    }
  }, []);

  const fetchDetalle = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await obtenerPedido(pedidoId);
      setPedido(data);
      fetchDocumentos(data?.id);
    } catch (err) {
      setError(err.response?.data?.detail || 'Error al cargar el pedido.');
    } finally {
      setLoading(false);
    }
  }, [obtenerPedido, pedidoId, fetchDocumentos]);

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

  // Feature D — al corregir se crea un clon. Cierra este modal y propaga el
  // ID del clon al padre para que abra el modal del clon (flujo fluido).
  const handleCorregirClose = useCallback(
    (clon) => {
      setShowCorregirModal(false);
      if (clon) {
        // `onClose(clon)` le dice al padre que recargue Y navegue al clon.
        // Firma backward-compatible: el padre venía usando `bool reload`.
        // Nuevos callers pueden leer el objeto clon para navegar.
        onClose({ reload: true, clonId: clon.id });
      }
    },
    [onClose]
  );

  // F2 — Resolve TC variance by creating and applying a ND or NC.
  const handleResolverVarianza = useCallback(async () => {
    if (!pedido) return;
    setResolviendoVarianza(true);
    setErrorVarianza(null);
    try {
      await api.post(
        `/administracion/compras/pedidos/${pedido.id}/resolver-varianza-tc`
      );
      // Reload the pedido so varianza_tc_pendiente and varianza_tc_neta update.
      onClose({ reload: true });
    } catch (err) {
      const msg =
        err?.response?.data?.detail ||
        'Error al resolver la varianza TC. Intente nuevamente.';
      setErrorVarianza(msg);
    } finally {
      setResolviendoVarianza(false);
    }
  }, [pedido, onClose]);

  const handleNavegarAPedidoRelacionado = useCallback(
    (relacionadoId) => {
      if (!relacionadoId) return;
      // Cerrar este modal señalando al padre que abra el del relacionado.
      onClose({ reload: false, pedidoId: relacionadoId });
    },
    [onClose]
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
                <div className={styles.infoValue}>
                  <EstadoBadge variant="pedido" estado={pedido.estado} size="md" />
                </div>
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
                <span className={styles.infoLabel}>Total pedido</span>
                {pedido.moneda === 'USD' && pedido.tipo_cambio ? (
                  <>
                    <strong className={styles.infoValue}>
                      {formatCurrency(
                        Number(pedido.monto) * Number(pedido.tipo_cambio),
                        'ARS'
                      )}
                    </strong>
                    <div className={styles.infoSubvalue}>
                      {formatCurrency(pedido.monto, 'USD')} @{' '}
                      {Number(pedido.tipo_cambio).toLocaleString('es-AR', {
                        minimumFractionDigits: 2,
                        maximumFractionDigits: 4,
                      })}
                    </div>
                  </>
                ) : (
                  <strong className={styles.infoValue}>
                    {formatCurrency(pedido.monto, pedido.moneda)}
                  </strong>
                )}
              </div>
              {pedido.saldo_pendiente !== null && pedido.saldo_pendiente !== undefined && (
                <div>
                  <span className={styles.infoLabel}>Saldo pendiente</span>
                  {pedido.moneda === 'USD' && pedido.tipo_cambio ? (
                    <>
                      <strong className={styles.infoValue}>
                        {formatCurrency(
                          Number(pedido.saldo_pendiente) * Number(pedido.tipo_cambio),
                          'ARS'
                        )}
                      </strong>
                      <div className={styles.infoSubvalue}>
                        {formatCurrency(pedido.saldo_pendiente, 'USD')} @ TC actual
                      </div>
                    </>
                  ) : (
                    <strong className={styles.infoValue}>
                      {formatCurrency(pedido.saldo_pendiente, pedido.moneda)}
                    </strong>
                  )}
                </div>
              )}
              {pedido.moneda === 'USD' && (
                <div>
                  <span className={styles.infoLabel}>TC efectivo</span>
                  <strong className={styles.infoValue}>
                    {pedido.tipo_cambio
                      ? `$${Number(pedido.tipo_cambio).toLocaleString('es-AR', {
                          minimumFractionDigits: 2,
                          maximumFractionDigits: 4,
                        })} / USD`
                      : '—'}
                  </strong>
                  {/* F1 — Show TC original when it differs from effective TC */}
                  {pedido.tipo_cambio_original &&
                    pedido.tipo_cambio &&
                    Number(pedido.tipo_cambio_original) !== Number(pedido.tipo_cambio) && (
                      <div className={styles.infoSubvalue}>
                        TC aprobación: $
                        {Number(pedido.tipo_cambio_original).toLocaleString('es-AR', {
                          minimumFractionDigits: 2,
                          maximumFractionDigits: 4,
                        })}{' '}
                        / USD
                      </div>
                    )}
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

            {/* ── Chips de correcciones (feature D, bidireccional) ── */}
            {(pedido.corregido_desde_id || pedido.corregido_a_id) && (
              <div className={styles.correctionChips}>
                {pedido.corregido_desde_id && (
                  <button
                    type="button"
                    className={styles.chipCorrection}
                    onClick={() =>
                      handleNavegarAPedidoRelacionado(pedido.corregido_desde_id)
                    }
                    title="Ver el pedido original desde el que se corrigió este"
                  >
                    <History size={14} />
                    Corregido desde pedido #{pedido.corregido_desde_id} (ver original)
                  </button>
                )}
                {pedido.corregido_a_id && (
                  <button
                    type="button"
                    className={styles.chipCorrection}
                    onClick={() =>
                      handleNavegarAPedidoRelacionado(pedido.corregido_a_id)
                    }
                    title="Ver la versión corregida de este pedido"
                  >
                    <History size={14} />
                    Corregido en pedido #{pedido.corregido_a_id} (ver versión corregida)
                  </button>
                )}
              </div>
            )}

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

            {/* ── Documentos ERP imputados (sub-batch 3) ── */}
            <h3 className={styles.sectionTitle}>
              <FileText size={14} /> Documentos imputados ({documentos.length})
            </h3>
            {loadingDocs ? (
              <div className={styles.centered}>
                <Loader2 size={16} className={styles.spin} /> Cargando documentos...
              </div>
            ) : documentos.length === 0 ? (
              <div className={styles.emptySection}>
                Sin documentos imputados aún. Se listan acá las OPs, NCs y facturas que
                se fueron imputando al pedido.
              </div>
            ) : (
              <div className={styles.tableWrapper}>
                <table className={styles.table}>
                  <thead>
                    <tr>
                      <th>Tipo</th>
                      <th>Número</th>
                      <th>Fecha</th>
                      <th className={styles.thRight}>Monto imputado</th>
                      <th>Estado</th>
                    </tr>
                  </thead>
                  <tbody>
                    {documentos.map((d, i) => (
                      <tr key={`${d.origen_tipo}-${d.origen_id}-${i}`}>
                        <td className={styles.tdSecondary}>{d.descripcion || d.origen_tipo}</td>
                        <td className={styles.tdMono}>{d.numero || `#${d.origen_id}`}</td>
                        <td className={styles.tdSecondary}>
                          {d.fecha ? formatDate(d.fecha) : '—'}
                        </td>
                        <td className={styles.tdRight}>
                          {formatCurrency(d.monto_imputado, d.moneda_imputada)}
                        </td>
                        <td>{d.estado || '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

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
                          {i.origen_descripcion || `${i.origen_tipo} #${i.origen_id}`}
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

            {/* ── Timeline de eventos (sección entera colapsable) ── */}
            <details className={styles.timelineSection}>
              <summary className={styles.timelineSectionSummary}>
                Timeline ({pedido.eventos?.length || 0})
              </summary>
              {!pedido.eventos || pedido.eventos.length === 0 ? (
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
                            <details className={styles.timelinePayloadDetails}>
                              <summary className={styles.timelinePayloadSummary}>
                                Ver detalle
                              </summary>
                              <pre className={styles.timelinePayload}>
                                {JSON.stringify(ev.payload, null, 2)}
                              </pre>
                            </details>
                          )}
                        </div>
                      </li>
                    );
                  })}
                </ul>
              )}
            </details>
          </>
        )}

        {/* F2 — TC variance legend + resolver action */}
        {pedido && pedido.varianza_tc_pendiente && (
          <div className={styles.varianzaAlert}>
            <TrendingUp size={14} />
            <span>
              Falta aplicar ND/NC por varianza TC:{' '}
              <strong>
                {Number(pedido.varianza_tc_neta) > 0 ? '+' : ''}
                {Number(pedido.varianza_tc_neta).toLocaleString('es-AR', {
                  style: 'currency',
                  currency: 'ARS',
                  minimumFractionDigits: 2,
                })}
              </strong>
            </span>
            {errorVarianza && (
              <span className={styles.varianzaError}>{errorVarianza}</span>
            )}
          </div>
        )}

        <div className={styles.formActions}>
          {/* F2 — Show resolver button when variance is pending and user can manage */}
          {canGestionar && pedido && pedido.varianza_tc_pendiente && (
            <button
              type="button"
              className={styles.btnVarianza}
              onClick={handleResolverVarianza}
              disabled={resolviendoVarianza}
              title="Crear y aplicar automáticamente la ND o NC de varianza TC"
            >
              {resolviendoVarianza ? (
                <Loader2 size={14} className={styles.spin} />
              ) : (
                <TrendingUp size={14} />
              )}
              Resolver varianza TC
            </button>
          )}
          {puedeCorregir && (
            <button
              type="button"
              className={styles.btnCorregir}
              onClick={() => setShowCorregirModal(true)}
              title="Crear una versión corregida del pedido (cancela el actual)"
            >
              <Edit3 size={14} />
              Corregir
            </button>
          )}
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
      {showCorregirModal && pedido && (
        <ModalCorregirPedido pedido={pedido} onClose={handleCorregirClose} />
      )}
    </div>
  );
}
