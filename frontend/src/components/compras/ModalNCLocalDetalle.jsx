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
  CreditCard,
  AlertCircle,
  Pencil,
  Link2,
  Link2Off,
  Paperclip,
} from 'lucide-react';
import { usePermisos } from '../../contexts/PermisosContext';
import useNCsLocales from '../../hooks/useNCsLocales';
import AdjuntosPanel from './AdjuntosPanel';
import ModalVincularFacturaNC from './ModalVincularFacturaNC';
import ModalAplicarNC from './ModalAplicarNC';
import ModalNCLocal from './ModalNCLocal';
import styles from './ModalNCLocalDetalle.module.css';

const eventoIcon = (tipo) => {
  const t = (tipo || '').toLowerCase();
  if (t.includes('creada') || t.includes('crear')) return FileText;
  if (t.includes('enviada') || t.includes('enviar')) return Send;
  if (t.includes('aprobada') || t.includes('aprobar')) return Check;
  if (t.includes('rechaz')) return XCircle;
  if (t.includes('cancel')) return Ban;
  if (t.includes('reabierta') || t.includes('reabrir')) return RotateCcw;
  if (t.includes('aplicada') || t.includes('aplicar') || t.includes('imputa')) return CreditCard;
  if (t.includes('editada') || t.includes('editar')) return Pencil;
  if (t.includes('vincul') || t.includes('match')) return Link2;
  return AlertCircle;
};

const formatDateTime = (isoStr) => {
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

const formatDateOnly = (isoStr) => {
  if (!isoStr) return '—';
  try {
    const [y, m, d] = String(isoStr).split('T')[0].split('-');
    if (!y || !m || !d) return isoStr;
    return `${d}/${m}/${y}`;
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

export default function ModalNCLocalDetalle({ ncId, onClose }) {
  const { tienePermiso } = usePermisos();
  const canManage = tienePermiso('administracion.gestionar_ordenes_compra');
  const canApprove = tienePermiso('administracion.aprobar_ncs_locales');

  // Desestructurar funciones memoizadas para evitar loops.
  const {
    obtener: obtenerNC,
    enviarAprobacion,
    aprobar: aprobarNC,
    rechazar: rechazarNC,
    reabrir: reabrirNC,
    cancelar: cancelarNC,
    desvincularFactura,
  } = useNCsLocales();

  const [nc, setNc] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const [showVincularModal, setShowVincularModal] = useState(false);
  const [showAplicarModal, setShowAplicarModal] = useState(false);
  const [showEditarModal, setShowEditarModal] = useState(false);
  const [desvinculando, setDesvinculando] = useState(false);

  // Motivo modal (rechazar / cancelar con motivo).
  const [motivoModal, setMotivoModal] = useState(null); // { accion, titulo, defaultAccionRechazo? }
  const [motivoTexto, setMotivoTexto] = useState('');
  const [motivoAccionRechazo, setMotivoAccionRechazo] = useState('devolver_a_borrador');
  const [motivoLoading, setMotivoLoading] = useState(false);
  const [motivoError, setMotivoError] = useState(null);

  const [actionLoading, setActionLoading] = useState(false);

  const fetchDetalle = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await obtenerNC(ncId);
      setNc(data);
    } catch (err) {
      const msg =
        err.response?.data?.error?.message ||
        err.response?.data?.detail ||
        'Error al cargar la NC.';
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, [obtenerNC, ncId]);

  useEffect(() => {
    fetchDetalle();
  }, [fetchDetalle]);

  const handleDesvincular = useCallback(async () => {
    if (!nc?.id) return;
    try {
      setDesvinculando(true);
      setError(null);
      await desvincularFactura(nc.id);
      await fetchDetalle();
    } catch (err) {
      const msg =
        err.response?.data?.error?.message ||
        err.response?.data?.detail ||
        'Error al desvincular la NC del ERP.';
      setError(msg);
    } finally {
      setDesvinculando(false);
    }
  }, [desvincularFactura, nc?.id, fetchDetalle]);

  const handleVincularClose = useCallback(
    (reload) => {
      setShowVincularModal(false);
      if (reload) fetchDetalle();
    },
    [fetchDetalle]
  );

  const handleAplicarClose = useCallback(
    (reload) => {
      setShowAplicarModal(false);
      if (reload) fetchDetalle();
    },
    [fetchDetalle]
  );

  const handleEditarClose = useCallback(
    (reload) => {
      setShowEditarModal(false);
      if (reload) fetchDetalle();
    },
    [fetchDetalle]
  );

  // ── Transiciones simples (sin motivo) ──
  const handleEnviarAprobacion = async () => {
    if (!nc?.id) return;
    setActionLoading(true);
    try {
      await enviarAprobacion(nc.id);
      await fetchDetalle();
    } catch (err) {
      const msg =
        err.response?.data?.error?.message ||
        err.response?.data?.detail ||
        'Error al enviar a aprobación.';
      setError(msg);
    } finally {
      setActionLoading(false);
    }
  };

  const handleAprobar = async () => {
    if (!nc?.id) return;
    setActionLoading(true);
    try {
      await aprobarNC(nc.id, null);
      await fetchDetalle();
    } catch (err) {
      const msg =
        err.response?.data?.error?.message ||
        err.response?.data?.detail ||
        'Error al aprobar.';
      setError(msg);
    } finally {
      setActionLoading(false);
    }
  };

  const handleReabrir = async () => {
    if (!nc?.id) return;
    setActionLoading(true);
    try {
      await reabrirNC(nc.id);
      await fetchDetalle();
    } catch (err) {
      const msg =
        err.response?.data?.error?.message ||
        err.response?.data?.detail ||
        'Error al reabrir.';
      setError(msg);
    } finally {
      setActionLoading(false);
    }
  };

  // ── Motivo modal (rechazar / cancelar) ──
  const openMotivoModal = (accion, titulo) => {
    setMotivoModal({ accion, titulo });
    setMotivoTexto('');
    setMotivoAccionRechazo('devolver_a_borrador');
    setMotivoError(null);
  };

  const handleSubmitMotivo = async () => {
    if (!motivoModal || !nc?.id) return;
    const motivo = motivoTexto.trim();
    if (!motivo) {
      setMotivoError('El motivo es requerido.');
      return;
    }
    setMotivoLoading(true);
    setMotivoError(null);
    try {
      if (motivoModal.accion === 'rechazar') {
        await rechazarNC(nc.id, motivoAccionRechazo, motivo);
      } else if (motivoModal.accion === 'cancelar') {
        await cancelarNC(nc.id, motivo);
      }
      setMotivoModal(null);
      await fetchDetalle();
    } catch (err) {
      const msg =
        err.response?.data?.error?.message ||
        err.response?.data?.detail ||
        'Error al procesar la acción.';
      setMotivoError(msg);
    } finally {
      setMotivoLoading(false);
    }
  };

  // ── Permisos por estado ──
  const estado = nc?.estado;
  const puedeEditar = canManage && estado === 'borrador';
  const puedeEnviar = canManage && estado === 'borrador';
  const puedeAprobar = canApprove && estado === 'pendiente_aprobacion';
  const puedeRechazar = canApprove && estado === 'pendiente_aprobacion';
  const puedeReabrir = canManage && estado === 'rechazado';
  const puedeCancelarDesdeBorrador =
    canManage && ['borrador', 'pendiente_aprobacion'].includes(estado);
  const puedeCancelarAprobada =
    canManage && ['aprobado', 'aplicada_parcial'].includes(estado);
  const puedeAplicar =
    canManage && ['aprobado', 'aplicada_parcial'].includes(estado);

  const saldoPendiente =
    nc?.saldo_pendiente !== undefined && nc?.saldo_pendiente !== null
      ? Number(nc.saldo_pendiente)
      : null;
  const mostrarSaldoPendiente =
    saldoPendiente !== null &&
    (estado === 'aplicada_parcial' || estado === 'aplicada');

  return (
    <div className={styles.modalOverlay}>
      <div className={styles.modalContent}>
        <div className={styles.modalHeader}>
          <span className={styles.modalTitle}>
            {nc ? `NC ${nc.numero}` : 'Detalle de NC'}
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

        {nc && !loading && (
          <>
            {/* ── Info general ── */}
            <div className={styles.infoGrid}>
              <div>
                <span className={styles.infoLabel}>Estado</span>
                <strong className={styles.infoValue}>{nc.estado}</strong>
              </div>
              <div>
                <span className={styles.infoLabel}>Empresa</span>
                <strong className={styles.infoValue}>
                  {nc.empresa_nombre || `#${nc.empresa_id}`}
                </strong>
              </div>
              <div>
                <span className={styles.infoLabel}>Proveedor</span>
                <strong className={styles.infoValue}>
                  {nc.proveedor_nombre || `#${nc.proveedor_id}`}
                </strong>
              </div>
              <div>
                <span className={styles.infoLabel}>Fecha emisión</span>
                <strong className={styles.infoValue}>
                  {formatDateOnly(nc.fecha_emision)}
                </strong>
              </div>
              <div>
                <span className={styles.infoLabel}>Nº NC proveedor</span>
                <strong className={styles.infoValue}>
                  {nc.numero_nc_proveedor || '—'}
                </strong>
              </div>
              <div>
                <span className={styles.infoLabel}>Moneda</span>
                <strong className={styles.infoValue}>{nc.moneda}</strong>
              </div>
              {nc.moneda === 'USD' && (
                <div>
                  <span className={styles.infoLabel}>Tipo de cambio</span>
                  <strong className={styles.infoValue}>
                    {nc.tipo_cambio
                      ? `$${Number(nc.tipo_cambio).toLocaleString('es-AR', {
                          minimumFractionDigits: 2,
                          maximumFractionDigits: 4,
                        })} / USD`
                      : '—'}
                  </strong>
                </div>
              )}
            </div>

            {/* ── Montos card ── */}
            <div className={styles.montosCard}>
              <div className={styles.montoItem}>
                <span className={styles.infoLabel}>Monto total</span>
                <strong className={styles.montoValor}>
                  {formatCurrency(nc.monto, nc.moneda)}
                </strong>
              </div>
              {mostrarSaldoPendiente && (
                <div className={styles.montoItem}>
                  <span className={styles.infoLabel}>Saldo pendiente (crédito)</span>
                  <strong
                    className={
                      saldoPendiente > 0 ? styles.montoSaldo : styles.montoAplicada
                    }
                  >
                    {formatCurrency(saldoPendiente, nc.moneda)}
                  </strong>
                </div>
              )}
            </div>

            {/* ── Motivo ── */}
            <h3 className={styles.sectionTitle}>
              <FileText size={14} /> Motivo
            </h3>
            <div className={styles.motivoBox}>{nc.motivo || '—'}</div>

            {/* ── Observaciones ── */}
            {nc.observaciones && (
              <>
                <h3 className={styles.sectionTitle}>Observaciones</h3>
                <div className={styles.motivoBox}>{nc.observaciones}</div>
              </>
            )}

            {/* ── NC ERP ── */}
            <h3 className={styles.sectionTitle}>
              <Link2 size={14} /> NC del ERP
            </h3>
            <div className={styles.facturaBlock}>
              {nc.ct_transaction_id ? (
                <div className={styles.facturaVinculada}>
                  <div className={styles.facturaInfo}>
                    <span className={styles.facturaMain}>
                      Vinculada a ct_transaction{' '}
                      <strong>#{nc.ct_transaction_id}</strong>
                    </span>
                  </div>
                  {canManage && (
                    <button
                      type="button"
                      className={styles.btnGhost}
                      onClick={handleDesvincular}
                      disabled={desvinculando}
                      title="Desvincular NC ERP (no revierte ajustes previos)"
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
                    Sin NC ERP vinculada.
                  </span>
                  {canManage && (
                    <button
                      type="button"
                      className={styles.btnPrimaryInline}
                      onClick={() => setShowVincularModal(true)}
                    >
                      <Link2 size={14} /> Vincular NC del ERP
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
              entidadTipo="nota_credito_local"
              entidadId={nc.id}
              canManage={canManage && estado !== 'cancelado'}
            />

            {/* ── Imputaciones ── */}
            <h3 className={styles.sectionTitle}>
              Imputaciones ({nc.imputaciones?.length || 0})
            </h3>
            {!nc.imputaciones || nc.imputaciones.length === 0 ? (
              <div className={styles.emptySection}>
                Sin imputaciones aún. Esta NC está en estado crédito disponible.
              </div>
            ) : (
              <div className={styles.tableWrapper}>
                <table className={styles.table}>
                  <thead>
                    <tr>
                      <th>ID</th>
                      <th>Destino</th>
                      <th className={styles.thRight}>Monto</th>
                      <th>Moneda</th>
                      <th>Fecha</th>
                      <th>Reversal</th>
                    </tr>
                  </thead>
                  <tbody>
                    {nc.imputaciones.map((i) => (
                      <tr key={i.id}>
                        <td className={styles.tdMono}>#{i.id}</td>
                        <td>
                          {i.destino_descripcion ||
                            `${i.destino_tipo}${i.destino_id ? ` #${i.destino_id}` : ''}`}
                        </td>
                        <td className={styles.tdRight}>
                          {formatCurrency(i.monto_imputado, i.moneda_imputada)}
                        </td>
                        <td>{i.moneda_imputada}</td>
                        <td className={styles.tdSecondary}>
                          {formatDateTime(i.created_at)}
                        </td>
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

            {/* ── Timeline (sección entera colapsable) ── */}
            <details className={styles.timelineSection}>
              <summary className={styles.timelineSectionSummary}>
                Timeline ({nc.eventos?.length || 0})
              </summary>
              {!nc.eventos || nc.eventos.length === 0 ? (
                <div className={styles.emptySection}>Sin eventos.</div>
              ) : (
                <ul className={styles.timeline}>
                  {nc.eventos.map((ev) => {
                    const Icon = eventoIcon(ev.tipo);
                    return (
                      <li key={ev.id} className={styles.timelineItem}>
                        <div className={styles.timelineIcon}>
                          <Icon size={14} />
                        </div>
                        <div className={styles.timelineBody}>
                          <div className={styles.timelineHeader}>
                            <span className={styles.timelineType}>{ev.tipo}</span>
                            <span className={styles.timelineDate}>
                              {formatDateTime(ev.created_at)}
                            </span>
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

        {/* ── Footer actions ── */}
        <div className={styles.formActions}>
          <button
            type="button"
            className={styles.btnSecondary}
            onClick={() => onClose(false)}
          >
            Cerrar
          </button>

          {nc && !loading && (
            <>
              {puedeEditar && (
                <button
                  type="button"
                  className={styles.btnSecondary}
                  onClick={() => setShowEditarModal(true)}
                  disabled={actionLoading}
                >
                  <Pencil size={14} /> Editar
                </button>
              )}
              {puedeEnviar && (
                <button
                  type="button"
                  className={styles.btnPrimary}
                  onClick={handleEnviarAprobacion}
                  disabled={actionLoading}
                >
                  <Send size={14} /> Enviar a aprobación
                </button>
              )}
              {puedeAprobar && (
                <button
                  type="button"
                  className={styles.btnSuccess}
                  onClick={handleAprobar}
                  disabled={actionLoading}
                >
                  <Check size={14} /> Aprobar
                </button>
              )}
              {puedeRechazar && (
                <button
                  type="button"
                  className={styles.btnDanger}
                  onClick={() => openMotivoModal('rechazar', 'Rechazar NC')}
                  disabled={actionLoading}
                >
                  <XCircle size={14} /> Rechazar
                </button>
              )}
              {puedeReabrir && (
                <button
                  type="button"
                  className={styles.btnPrimary}
                  onClick={handleReabrir}
                  disabled={actionLoading}
                >
                  <RotateCcw size={14} /> Reabrir
                </button>
              )}
              {puedeAplicar && (
                <button
                  type="button"
                  className={styles.btnSuccess}
                  onClick={() => setShowAplicarModal(true)}
                  disabled={actionLoading}
                >
                  <CreditCard size={14} /> Aplicar a pedido/factura
                </button>
              )}
              {puedeCancelarDesdeBorrador && (
                <button
                  type="button"
                  className={styles.btnDanger}
                  onClick={() => openMotivoModal('cancelar', 'Cancelar NC')}
                  disabled={actionLoading}
                >
                  <Ban size={14} /> Cancelar
                </button>
              )}
              {puedeCancelarAprobada && (
                <button
                  type="button"
                  className={styles.btnDanger}
                  onClick={() =>
                    openMotivoModal('cancelar', 'Cancelar NC aprobada (con motivo)')
                  }
                  disabled={actionLoading}
                >
                  <Ban size={14} /> Cancelar NC
                </button>
              )}
            </>
          )}
        </div>
      </div>

      {/* ── Sub-modales ── */}
      {showVincularModal && nc && (
        <ModalVincularFacturaNC nc={nc} onClose={handleVincularClose} />
      )}

      {showAplicarModal && nc && (
        <ModalAplicarNC nc={nc} onClose={handleAplicarClose} />
      )}

      {showEditarModal && nc && (
        <ModalNCLocal nc={nc} empresas={[]} onClose={handleEditarClose} />
      )}

      {/* ── Motivo modal ── */}
      {motivoModal && (
        <div className={styles.motivoOverlay}>
          <div className={styles.motivoContent}>
            <div className={styles.modalHeader}>
              <span className={styles.modalTitle}>{motivoModal.titulo}</span>
              <button
                className={styles.modalCloseBtn}
                onClick={() => setMotivoModal(null)}
                aria-label="Cerrar"
                type="button"
              >
                <X size={18} />
              </button>
            </div>

            {motivoError && <div className={styles.errorBanner}>{motivoError}</div>}

            {motivoModal.accion === 'rechazar' && (
              <div className={styles.formGroup}>
                <label className={styles.formLabel}>Acción</label>
                <select
                  className={styles.select}
                  value={motivoAccionRechazo}
                  onChange={(e) => setMotivoAccionRechazo(e.target.value)}
                >
                  <option value="devolver_a_borrador">Devolver a borrador</option>
                  <option value="cancelar_definitivo">Cancelar definitivamente</option>
                </select>
              </div>
            )}

            <div className={styles.formGroup}>
              <label className={styles.formLabel}>Motivo *</label>
              <textarea
                className={styles.textarea}
                value={motivoTexto}
                onChange={(e) => setMotivoTexto(e.target.value)}
                placeholder="Describí el motivo..."
                rows={3}
              />
            </div>

            <div className={styles.formActions}>
              <button
                type="button"
                className={styles.btnSecondary}
                onClick={() => setMotivoModal(null)}
                disabled={motivoLoading}
              >
                Cancelar
              </button>
              <button
                type="button"
                className={styles.btnDanger}
                onClick={handleSubmitMotivo}
                disabled={motivoLoading}
              >
                {motivoLoading ? 'Procesando...' : 'Confirmar'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
