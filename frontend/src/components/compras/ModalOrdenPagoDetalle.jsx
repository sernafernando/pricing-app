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
  Link2,
  Paperclip,
} from 'lucide-react';
import { usePermisos } from '../../contexts/PermisosContext';
import useComprasOP from '../../hooks/useComprasOP';
import AdjuntosPanel from './AdjuntosPanel';
import styles from './ModalOrdenPagoDetalle.module.css';

const eventoIcon = (tipo) => {
  const t = (tipo || '').toLowerCase();
  if (t.includes('creado') || t.includes('creada')) return FileText;
  if (t.includes('enviado') || t.includes('enviar')) return Send;
  if (t.includes('aprobado')) return Check;
  if (t.includes('rechaz')) return XCircle;
  if (t.includes('anul')) return Ban;
  if (t.includes('reabier')) return RotateCcw;
  if (t.includes('pago') || t.includes('pagad')) return Wallet;
  if (t.includes('imputa') || t.includes('distribuida')) return CreditCard;
  if (t.includes('editado') || t.includes('editar')) return Pencil;
  if (t.includes('match')) return Link2;
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

// dd/mm/yyyy sin bug UTC off-by-one.
const formatDate = (isoDate) => {
  if (!isoDate) return '—';
  try {
    const [year, month, day] = String(isoDate).split('T')[0].split('-');
    if (!year || !month || !day) return isoDate;
    return `${day}/${month}/${year}`;
  } catch {
    return isoDate;
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

const estadoBadgeClass = (estado, styles) => {
  switch (estado) {
    case 'pendiente':
      return styles.badgePendiente;
    case 'pagado':
      return styles.badgePagado;
    case 'anulado':
      return styles.badgeAnulado;
    default:
      return styles.badgeNeutral;
  }
};

const descripcionModo = (modo) => {
  switch (modo) {
    case 'especifica':
      return 'Imputación específica a uno o más pedidos/facturas.';
    case 'a_cuenta':
      return 'Pago a cuenta — queda como saldo del proveedor, sin pedido específico.';
    case 'mixta':
      return 'Mixta — parte imputada a pedidos/facturas, parte como saldo.';
    default:
      return '';
  }
};

const nombreDestino = (imp) => {
  if (imp.destino_tipo === 'saldo') return 'Saldo general';
  return `${imp.destino_tipo} #${imp.destino_id ?? '—'}`;
};

/**
 * ModalOrdenPagoDetalle — detalle completo de una OP.
 *
 * Consume GET /administracion/compras/ordenes-pago/{id} que incluye
 * imputaciones, eventos y (si está pagada) resumen del caja_movimiento.
 *
 * Props:
 *   - op: objeto OP con al menos { id, numero, estado }
 *   - onClose(reload): cierra modal; reload=true fuerza refresh en tab padre
 *   - onEjecutarPago(op): callback cuando el usuario clickea "Ejecutar pago"
 *   - onAnular(op): callback cuando el usuario clickea "Anular"
 */
export default function ModalOrdenPagoDetalle({ op, onClose, onEjecutarPago, onAnular }) {
  const { tienePermiso } = usePermisos();
  const canPay = tienePermiso('administracion.ejecutar_pagos');
  const canGestionarAdj = tienePermiso('administracion.gestionar_ordenes_compra');

  const { obtener: obtenerOP } = useComprasOP();

  const [detalle, setDetalle] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [historialAbierto, setHistorialAbierto] = useState(false);

  const fetchDetalle = useCallback(async () => {
    if (!op?.id) return;
    setLoading(true);
    setError(null);
    try {
      const data = await obtenerOP(op.id);
      setDetalle(data);
    } catch (err) {
      setError(err.response?.data?.detail || 'Error al cargar la orden de pago.');
    } finally {
      setLoading(false);
    }
  }, [obtenerOP, op?.id]);

  useEffect(() => {
    fetchDetalle();
  }, [fetchDetalle]);

  const handleEjecutarPago = () => {
    if (!detalle) return;
    onClose(false);
    if (onEjecutarPago) onEjecutarPago(detalle);
  };

  const handleAnular = () => {
    if (!detalle) return;
    onClose(false);
    if (onAnular) onAnular(detalle);
  };

  const estadoActual = detalle?.estado || op?.estado;
  const puedePagar = canPay && estadoActual === 'pendiente';
  const puedeAnular = canPay && estadoActual === 'pagado';

  return (
    <div className={styles.modalOverlay}>
      <div className={styles.modalContent}>
        <div className={styles.modalHeader}>
          <div className={styles.modalTitleGroup}>
            <span className={styles.modalTitle}>
              {detalle ? `OP ${detalle.numero}` : `OP ${op?.numero || ''}`}
            </span>
            {estadoActual && (
              <span className={`${styles.badge} ${estadoBadgeClass(estadoActual, styles)}`}>
                {estadoActual}
              </span>
            )}
          </div>
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

        {detalle && !loading && (
          <>
            {/* ── Info general ── */}
            <div className={styles.infoGrid}>
              <div>
                <span className={styles.infoLabel}>Empresa</span>
                <strong className={styles.infoValue}>
                  {detalle.empresa_nombre || `#${detalle.empresa_id}`}
                </strong>
              </div>
              <div>
                <span className={styles.infoLabel}>Proveedor</span>
                <strong className={styles.infoValue}>
                  {detalle.proveedor_nombre || `#${detalle.proveedor_id}`}
                </strong>
              </div>
              <div>
                <span className={styles.infoLabel}>Fecha emisión</span>
                <strong className={styles.infoValue}>{formatDate(detalle.created_at)}</strong>
              </div>
              <div>
                <span className={styles.infoLabel}>Fecha pago real</span>
                <strong className={styles.infoValue}>
                  {detalle.fecha_pago_real ? formatDate(detalle.fecha_pago_real) : '—'}
                </strong>
              </div>
              <div>
                <span className={styles.infoLabel}>Moneda</span>
                <strong className={styles.infoValue}>{detalle.moneda}</strong>
              </div>
              {detalle.moneda === 'USD' && (
                <div>
                  <span className={styles.infoLabel}>Tipo de cambio</span>
                  <strong className={styles.infoValue}>
                    {detalle.tipo_cambio
                      ? `$${Number(detalle.tipo_cambio).toLocaleString('es-AR', {
                          minimumFractionDigits: 2,
                          maximumFractionDigits: 4,
                        })} / USD`
                      : '—'}
                  </strong>
                </div>
              )}
            </div>

            {/* ── Monto destacado ── */}
            <div className={styles.montoCard}>
              <span className={styles.montoLabel}>Monto total</span>
              <strong className={styles.montoValor}>
                {formatCurrency(detalle.monto_total, detalle.moneda)}
              </strong>
            </div>

            {/* ── Modo de imputación ── */}
            <div className={styles.modoSection}>
              <div className={styles.modoHeader}>
                <span className={styles.modoLabel}>Modo de imputación</span>
                <span className={`${styles.badge} ${styles.badgeNeutral}`}>
                  {detalle.modo_imputacion}
                </span>
              </div>
              <p className={styles.modoDescripcion}>{descripcionModo(detalle.modo_imputacion)}</p>
            </div>

            {/* ── Imputaciones ── */}
            <h3 className={styles.sectionTitle}>
              Imputaciones ({detalle.imputaciones?.length || 0})
            </h3>
            {!detalle.imputaciones || detalle.imputaciones.length === 0 ? (
              <div className={styles.emptySection}>Sin imputaciones aún.</div>
            ) : (
              <div className={styles.tableWrapper}>
                <table className={styles.table}>
                  <thead>
                    <tr>
                      <th>Tipo</th>
                      <th>Destino</th>
                      <th className={styles.thRight}>Monto</th>
                      <th>Reversal</th>
                    </tr>
                  </thead>
                  <tbody>
                    {detalle.imputaciones.map((i) => (
                      <tr key={i.id}>
                        <td className={styles.tdSecondary}>{i.destino_tipo}</td>
                        <td>{nombreDestino(i)}</td>
                        <td className={styles.tdRight}>
                          {formatCurrency(i.monto_imputado, i.moneda_imputada)}
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

            {/* ── Adjuntos ── */}
            <h3 className={styles.sectionTitle}>
              <Paperclip size={14} /> Adjuntos
            </h3>
            <AdjuntosPanel
              entidadTipo="orden_pago"
              entidadId={detalle.id}
              canManage={canGestionarAdj}
            />

            {/* ── Pago ejecutado ── */}
            {estadoActual === 'pagado' && detalle.caja_movimiento_resumen && (
              <>
                <h3 className={styles.sectionTitle}>Pago ejecutado</h3>
                <div className={styles.pagoCard}>
                  <div className={styles.pagoRow}>
                    <span className={styles.infoLabel}>Caja</span>
                    <strong className={styles.infoValue}>
                      {detalle.caja_movimiento_resumen.caja_nombre ||
                        `#${detalle.caja_movimiento_resumen.caja_id}`}
                    </strong>
                  </div>
                  <div className={styles.pagoRow}>
                    <span className={styles.infoLabel}>Fecha pago</span>
                    <strong className={styles.infoValue}>
                      {formatDate(detalle.caja_movimiento_resumen.fecha)}
                    </strong>
                  </div>
                  <div className={styles.pagoRow}>
                    <span className={styles.infoLabel}>Monto</span>
                    <strong className={styles.infoValue}>
                      {formatCurrency(detalle.caja_movimiento_resumen.monto, detalle.moneda)}
                    </strong>
                  </div>
                  <div className={styles.pagoRow}>
                    <span className={styles.infoLabel}>Tipo</span>
                    <strong className={styles.infoValue}>
                      {detalle.caja_movimiento_resumen.tipo}
                    </strong>
                  </div>
                </div>
              </>
            )}

            {/* ── Historial (collapsible) ── */}
            <button
              type="button"
              className={styles.historialToggle}
              onClick={() => setHistorialAbierto((v) => !v)}
              aria-expanded={historialAbierto}
            >
              Historial ({detalle.eventos?.length || 0}){' '}
              <span className={styles.historialArrow}>{historialAbierto ? '▲' : '▼'}</span>
            </button>
            {historialAbierto && (
              <>
                {!detalle.eventos || detalle.eventos.length === 0 ? (
                  <div className={styles.emptySection}>Sin eventos.</div>
                ) : (
                  <ul className={styles.timeline}>
                    {detalle.eventos.map((ev) => {
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
                            <div className={styles.timelineMeta}>Usuario #{ev.usuario_id}</div>
                          </div>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </>
            )}
          </>
        )}

        <div className={styles.formActions}>
          <button type="button" className={styles.btnSecondary} onClick={() => onClose(false)}>
            Cerrar
          </button>
          {puedePagar && (
            <button
              type="button"
              className={styles.btnSuccess}
              onClick={handleEjecutarPago}
              disabled={!detalle}
            >
              <Wallet size={14} /> Ejecutar pago
            </button>
          )}
          {puedeAnular && (
            <button
              type="button"
              className={styles.btnDanger}
              onClick={handleAnular}
              disabled={!detalle}
            >
              <Ban size={14} /> Anular
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
