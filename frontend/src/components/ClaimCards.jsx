/**
 * ClaimCards — Componente reutilizable para renderizar claims de MercadoLibre.
 *
 * Incluye:
 * - Listado de claim cards con toda la info (return, change, negociación, etc.)
 * - Modal de mensajes (conversación de la venta + mensajes del reclamo)
 * - Lightbox para imágenes adjuntas
 *
 * Props:
 *   claims — array de ClaimML objects (del backend)
 */

import { useState } from 'react';
import api from '../services/api';
import ModalTesla, { ModalLoading } from './ModalTesla';
import {
  AlertTriangle, Shield, Clock, CalendarDays, Star, Truck,
  RotateCcw, ArrowLeftRight, DollarSign, FileText, MessageSquare, Package,
} from 'lucide-react';
import {
  TRIAGE_TAGS_ES, EXPECTED_RESOLUTIONS_ES, CLAIM_STAGE_ES, CLAIM_ACTIONS_ES,
  RESOLUTION_REASON_ES, CLOSED_BY_ES, RETURN_STATUS_ES, RETURN_SUBTYPE_ES,
  RETURN_MONEY_STATUS_ES, SHIPMENT_STATUS_ES, REFUND_AT_ES, CHANGE_TYPE_ES,
  CHANGE_STATUS_ES, EXPECTED_RES_STATUS_ES, PLAYER_ROLE_ES,
  sanitizeMessageHtml, isImageAttachment, attachmentProxyUrl,
} from './claimTranslations';
import styles from './ClaimCards.module.css';

export default function ClaimCards({ claims }) {
  const [claimMsgsOpen, setClaimMsgsOpen] = useState(false);
  const [claimMsgs, setClaimMsgs] = useState([]);
  const [orderMsgs, setOrderMsgs] = useState([]);
  const [claimMsgsLoading, setClaimMsgsLoading] = useState(false);
  const [claimMsgsClaimId, setClaimMsgsClaimId] = useState(null);
  const [lightboxUrl, setLightboxUrl] = useState(null);

  if (!claims || claims.length === 0) return null;

  const abrirMensajesClaim = async (claimId, orderId) => {
    setClaimMsgsClaimId(claimId);
    setClaimMsgsOpen(true);
    setClaimMsgsLoading(true);
    setClaimMsgs([]);
    setOrderMsgs([]);
    try {
      const promises = [
        api.get(`/seriales/claims/${claimId}/messages`).catch(() => ({ data: [] })),
      ];
      if (orderId) {
        promises.push(
          api.get(`/seriales/orders/${orderId}/messages`).catch(() => ({ data: [] })),
        );
      }
      const results = await Promise.all(promises);
      setClaimMsgs(results[0].data || []);
      if (results[1]) setOrderMsgs(results[1].data || []);
    } catch {
      setClaimMsgs([]);
      setOrderMsgs([]);
    } finally {
      setClaimMsgsLoading(false);
    }
  };

  return (
    <>
      <div className={styles.claimsList}>
        {claims.map((claim) => (
          <div
            key={claim.claim_id}
            className={`${styles.claimCard} ${claim.status === 'opened' ? styles.claimOpen : styles.claimClosed}`}
          >
            <div className={styles.claimHeader}>
              <AlertTriangle size={14} />
              <span className={styles.claimTitle}>
                Reclamo #{claim.claim_id}
              </span>
              {claim.affects_reputation && (
                <span className={styles.claimRepBadge} title="Afecta reputación">
                  <Star size={10} />
                </span>
              )}
              {claim.has_incentive && claim.status === 'opened' && (
                <span className={styles.claimIncentiveBadge} title="Incentivo 48hs para resolver">
                  <Clock size={10} /> 48hs
                </span>
              )}
              <span className={`${styles.claimBadge} ${claim.status === 'opened' ? styles.claimBadgeOpen : styles.claimBadgeClosed}`}>
                {claim.status === 'opened' ? 'Abierto' : 'Cerrado'}
              </span>
            </div>

            {/* Motivo */}
            <div className={styles.claimMotivo}>
              {claim.reason_detail || claim.reason_category || 'Sin motivo'}
            </div>

            {/* Descripción del detalle (de /detail) */}
            {claim.detail_description && (
              <div className={styles.claimDescription}>
                {claim.detail_description}
              </div>
            )}

            {/* Tags y resoluciones esperadas */}
            <div className={styles.claimTags}>
              {(claim.triage_tags || []).map((tag) => (
                <span key={tag} className={styles.claimTag}>{TRIAGE_TAGS_ES[tag] || tag}</span>
              ))}
              {(claim.expected_resolutions || []).map((res) => (
                <span key={res} className={styles.claimResolution}>{EXPECTED_RESOLUTIONS_ES[res] || res.replace(/_/g, ' ')}</span>
              ))}
              {claim.messages_total != null && claim.messages_total > 0 && (
                <button
                  type="button"
                  className={styles.claimMsgBadge}
                  onClick={() => abrirMensajesClaim(claim.claim_id, claim.resource_id)}
                  aria-label={`Ver ${claim.messages_total} mensaje${claim.messages_total > 1 ? 's' : ''}`}
                >
                  <MessageSquare size={10} /> {claim.messages_total}
                </button>
              )}
            </div>

            {/* Detalles */}
            <div className={styles.claimDetails}>
              {claim.claim_stage && (
                <div className={styles.claimDetail}>
                  <Shield size={12} />
                  <span>Etapa: {CLAIM_STAGE_ES[claim.claim_stage] || claim.claim_stage}</span>
                </div>
              )}
              {claim.action_responsible === 'seller' && claim.status === 'opened' && (
                <div className={`${styles.claimDetail} ${styles.claimUrgent}`}>
                  <AlertTriangle size={12} />
                  <span>Requiere acción del vendedor</span>
                </div>
              )}
              {claim.nearest_due_date && claim.status === 'opened' && (
                <div className={`${styles.claimDetail} ${styles.claimUrgent}`}>
                  <Clock size={12} />
                  <span>Vence: {new Date(claim.nearest_due_date).toLocaleDateString('es-AR')}</span>
                </div>
              )}
              {claim.date_created && (
                <div className={styles.claimDetail}>
                  <CalendarDays size={12} />
                  <span>Creado: {new Date(claim.date_created).toLocaleDateString('es-AR')}</span>
                </div>
              )}
            </div>

            {/* Acciones obligatorias */}
            {(claim.mandatory_actions || []).length > 0 && claim.status === 'opened' && (
              <div className={styles.claimMandatory}>
                Acciones obligatorias: {claim.mandatory_actions.map((a) => CLAIM_ACTIONS_ES[a] || a.replace(/_/g, ' ')).join(', ')}
              </div>
            )}

            {/* Devolución (return) */}
            {claim.claim_return && (
              <div className={styles.claimReturnSection}>
                <div className={styles.claimSubHeader}>
                  <RotateCcw size={12} />
                  <span>Devolución</span>
                  <span className={styles.claimSubBadge}>
                    {RETURN_STATUS_ES[claim.claim_return.status] || claim.claim_return.status}
                  </span>
                </div>
                <div className={styles.claimSubDetails}>
                  {claim.claim_return.subtype && (
                    <span>{RETURN_SUBTYPE_ES[claim.claim_return.subtype] || claim.claim_return.subtype}</span>
                  )}
                  {claim.claim_return.status_money && (
                    <span>
                      <DollarSign size={10} /> {RETURN_MONEY_STATUS_ES[claim.claim_return.status_money] || claim.claim_return.status_money}
                    </span>
                  )}
                  {claim.claim_return.refund_at && claim.claim_return.refund_at !== 'n/a' && (
                    <span>Reembolso: {REFUND_AT_ES[claim.claim_return.refund_at] || claim.claim_return.refund_at}</span>
                  )}
                </div>
                {(claim.claim_return.shipments || []).length > 0 && (
                  <div className={styles.claimShipments}>
                    {claim.claim_return.shipments.map((s, idx) => (
                      <div key={s.shipment_id || idx} className={styles.claimShipment}>
                        <Truck size={10} />
                        <span>
                          {s.shipment_type === 'return' ? 'Devolución' : s.shipment_type === 'return_from_triage' ? 'Desde triage' : s.shipment_type || 'Envío'}
                          {' — '}
                          {SHIPMENT_STATUS_ES[s.status] || s.status}
                        </span>
                        {s.tracking_number && (
                          <span className={styles.claimTracking}>#{s.tracking_number}</span>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {/* Cambio/reemplazo (change) */}
            {claim.claim_change && (
              <div className={styles.claimChangeSection}>
                <div className={styles.claimSubHeader}>
                  <ArrowLeftRight size={12} />
                  <span>{CHANGE_TYPE_ES[claim.claim_change.change_type] || claim.claim_change.change_type || 'Cambio'}</span>
                  <span className={styles.claimSubBadge}>
                    {CHANGE_STATUS_ES[claim.claim_change.status] || claim.claim_change.status}
                  </span>
                </div>
                {(claim.claim_change.new_order_ids || []).length > 0 && (
                  <div className={styles.claimSubDetails}>
                    <span>Nueva orden: {claim.claim_change.new_order_ids.join(', ')}</span>
                  </div>
                )}
              </div>
            )}

            {/* Resoluciones esperadas detalladas (negociación) */}
            {(claim.expected_resolutions_detail || []).length > 0 && (
              <div className={styles.claimExpResSection}>
                <div className={styles.claimSubHeader}>
                  <FileText size={12} />
                  <span>Negociación</span>
                </div>
                {claim.expected_resolutions_detail.map((er, idx) => (
                  <div key={idx} className={styles.claimExpRes}>
                    <span className={styles.claimExpResRole}>
                      {PLAYER_ROLE_ES[er.player_role] || er.player_role}:
                    </span>
                    <span>
                      {EXPECTED_RESOLUTIONS_ES[er.expected_resolution] || er.expected_resolution?.replace(/_/g, ' ')}
                    </span>
                    <span className={`${styles.claimExpResBadge} ${er.status === 'accepted' ? styles.claimExpResAccepted : er.status === 'rejected' ? styles.claimExpResRejected : ''}`}>
                      {EXPECTED_RES_STATUS_ES[er.status] || er.status}
                    </span>
                  </div>
                ))}
              </div>
            )}

            {/* Resolución (si cerrado) */}
            {claim.status === 'closed' && claim.resolution_reason && (
              <div className={styles.claimResolved}>
                Resolución: {RESOLUTION_REASON_ES[claim.resolution_reason] || claim.resolution_reason.replace(/_/g, ' ')}
                {claim.resolution_closed_by && ` (por ${CLOSED_BY_ES[claim.resolution_closed_by] || claim.resolution_closed_by})`}
              </div>
            )}
          </div>
        ))}
      </div>

      {/* ── Sub-modal: Mensajes del reclamo ML ── */}
      <ModalTesla
        isOpen={claimMsgsOpen}
        onClose={() => setClaimMsgsOpen(false)}
        title={`Mensajes — Reclamo #${claimMsgsClaimId || ''}`}
        size="md"
        closeOnOverlay
      >
        {claimMsgsLoading ? (
          <ModalLoading message="Cargando mensajes..." />
        ) : (orderMsgs.length === 0 && claimMsgs.length === 0) ? (
          <p className={styles.claimMsgsEmpty}>Sin mensajes</p>
        ) : (
          <div className={styles.claimMsgsList}>
            {/* Mensajes de la venta (conversación posventa) */}
            {orderMsgs.length > 0 && (
              <>
                <div className={styles.claimMsgsSectionHeader}>
                  <MessageSquare size={12} />
                  Conversación de la venta ({orderMsgs.length})
                </div>
                {[...orderMsgs].reverse().map((msg) => (
                  <div
                    key={msg.message_id}
                    className={`${styles.claimMsgBubble} ${msg.is_seller ? styles.claimMsgSeller : ''}`}
                  >
                    <div className={styles.claimMsgHeader}>
                      <span className={styles.claimMsgRole}>
                        {msg.is_seller ? 'Vendedor' : 'Comprador'}
                      </span>
                      {msg.date_created && (
                        <span className={styles.claimMsgDate}>
                          {new Date(msg.date_created).toLocaleString('es-AR', {
                            day: '2-digit', month: '2-digit', year: 'numeric',
                            hour: '2-digit', minute: '2-digit',
                          })}
                        </span>
                      )}
                    </div>
                    {msg.text && (
                      <div
                        className={styles.claimMsgText}
                        dangerouslySetInnerHTML={{ __html: sanitizeMessageHtml(msg.text) }}
                      />
                    )}
                    {msg.attachments && msg.attachments.length > 0 && (
                      <div className={styles.claimMsgAttachments}>
                        {msg.attachments.map((att, i) => {
                          const key = typeof att === 'string' ? att : att?.id || att?.filename || '';
                          if (isImageAttachment(key)) {
                            return (
                              <button
                                key={i}
                                type="button"
                                className={styles.claimMsgImgThumb}
                                onClick={() => setLightboxUrl(attachmentProxyUrl(key))}
                                aria-label="Ver imagen adjunta"
                              >
                                <img
                                  src={attachmentProxyUrl(key)}
                                  alt="Adjunto"
                                  loading="lazy"
                                />
                              </button>
                            );
                          }
                          return (
                            <a
                              key={i}
                              href={attachmentProxyUrl(key)}
                              target="_blank"
                              rel="noopener noreferrer"
                              className={styles.claimMsgAttachment}
                            >
                              <Package size={10} /> {key.split('_').pop() || 'Adjunto'}
                            </a>
                          );
                        })}
                      </div>
                    )}
                  </div>
                ))}
              </>
            )}

            {/* Mensajes del reclamo */}
            {claimMsgs.length > 0 && (
              <>
                <div className={styles.claimMsgsSectionHeader}>
                  <AlertTriangle size={12} />
                  Mensajes del reclamo ({claimMsgs.length})
                </div>
                {claimMsgs.map((msg) => {
                  const isSeller = msg.sender_role === 'respondent';
                  const isMediator = msg.sender_role === 'mediator';
                  return (
                    <div
                      key={msg.id}
                      className={`${styles.claimMsgBubble} ${isSeller ? styles.claimMsgSeller : ''} ${isMediator ? styles.claimMsgMediator : ''}`}
                    >
                      <div className={styles.claimMsgHeader}>
                        <span className={styles.claimMsgRole}>
                          {PLAYER_ROLE_ES[msg.sender_role] || msg.sender_role}
                        </span>
                        {msg.ml_date_created && (
                          <span className={styles.claimMsgDate}>
                            {new Date(msg.ml_date_created).toLocaleString('es-AR', {
                              day: '2-digit', month: '2-digit', year: 'numeric',
                              hour: '2-digit', minute: '2-digit',
                            })}
                          </span>
                        )}
                      </div>
                      <div
                        className={styles.claimMsgText}
                        dangerouslySetInnerHTML={{ __html: sanitizeMessageHtml(msg.message) || '(sin texto)' }}
                      />
                      {msg.attachments && msg.attachments.length > 0 && (
                        <div className={styles.claimMsgAttachments}>
                          {msg.attachments.map((att, i) => {
                            const key = att.filename || att.original_filename || '';
                            if (isImageAttachment(key)) {
                              return (
                                <button
                                  key={i}
                                  type="button"
                                  className={styles.claimMsgImgThumb}
                                  onClick={() => setLightboxUrl(attachmentProxyUrl(key))}
                                  aria-label="Ver imagen adjunta"
                                >
                                  <img
                                    src={attachmentProxyUrl(key)}
                                    alt={att.original_filename || 'Adjunto'}
                                    loading="lazy"
                                  />
                                </button>
                              );
                            }
                            return (
                              <a
                                key={i}
                                href={attachmentProxyUrl(key)}
                                target="_blank"
                                rel="noopener noreferrer"
                                className={styles.claimMsgAttachment}
                              >
                                <Package size={10} /> {att.original_filename || att.filename || 'Adjunto'}
                              </a>
                            );
                          })}
                        </div>
                      )}
                    </div>
                  );
                })}
              </>
            )}
          </div>
        )}
      </ModalTesla>

      {/* ── Lightbox: imagen adjunta ampliada ── */}
      {lightboxUrl && (
        <div
          className={styles.lightboxOverlay}
          onClick={() => setLightboxUrl(null)}
          role="dialog"
          aria-label="Imagen adjunta ampliada"
        >
          <button
            type="button"
            className={styles.lightboxClose}
            onClick={() => setLightboxUrl(null)}
            aria-label="Cerrar imagen"
          >
            &times;
          </button>
          <img
            src={lightboxUrl}
            alt="Adjunto ampliado"
            className={styles.lightboxImg}
            onClick={(e) => e.stopPropagation()}
          />
        </div>
      )}
    </>
  );
}
