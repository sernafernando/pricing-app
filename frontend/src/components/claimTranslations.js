/**
 * Traducciones y helpers compartidos para claims de MercadoLibre.
 * Usado por ModalRma y TrazaViewer/ClaimCards.
 */

// ── Traducciones de campos de claims ML ──────────────────────────────────────
export const TRIAGE_TAGS_ES = {
  repentant: 'Arrepentimiento',
  defective: 'Defectuoso',
  not_working: 'No funciona',
  different: 'Producto diferente',
  incomplete: 'Incompleto',
};

export const EXPECTED_RESOLUTIONS_ES = {
  return_product: 'Devolución',
  change_product: 'Cambio',
  refund: 'Reembolso',
  product: 'Producto',
  other: 'Otro',
};

export const CLAIM_STAGE_ES = {
  claim: 'Reclamo',
  dispute: 'Mediación',
  recontact: 'Recontacto',
  stale: 'Estancado',
  none: 'N/A',
};

export const CLAIM_ACTIONS_ES = {
  refund: 'Reembolso',
  allow_return: 'Autorizar devolución',
  allow_return_label: 'Generar etiqueta de devolución',
  allow_partial_refund: 'Reembolso parcial',
  open_dispute: 'Abrir mediación',
  send_message_to_complainant: 'Enviar mensaje al comprador',
  send_message_to_mediator: 'Enviar mensaje al mediador',
  send_potential_shipping: 'Promesa de envío',
  add_shipping_evidence: 'Evidencia de envío',
  send_tracking_number: 'Enviar tracking',
  send_attachments: 'Enviar adjuntos',
  return_review: 'Revisar devolución',
};

export const RESOLUTION_REASON_ES = {
  payment_refunded: 'Pago devuelto',
  item_returned: 'Producto devuelto',
  prefered_to_keep_product: 'Prefirió quedarse el producto',
  partial_refunded: 'Reembolso parcial',
  opened_claim_by_mistake: 'Reclamo por error',
  worked_out_with_seller: 'Arregló con el vendedor',
  seller_sent_product: 'Vendedor envió el producto',
  seller_explained_functions: 'Vendedor explicó funcionamiento',
  respondent_timeout: 'Vendedor no respondió',
  coverage_decision: 'Cobertura de ML',
  item_changed: 'Producto cambiado',
  change_expired: 'Cambio expirado',
  low_cost: 'Bajo costo (envío > producto)',
  already_shipped: 'Ya fue enviado',
  not_delivered: 'No entregado',
  return_expired: 'Devolución vencida',
  return_canceled: 'Devolución cancelada',
};

export const CLOSED_BY_ES = {
  seller: 'vendedor',
  buyer: 'comprador',
  mediator: 'mediador',
};

// ── Traducciones de devolución (return) ──────────────────────────────────────
export const RETURN_STATUS_ES = {
  pending: 'Pendiente',
  label_generated: 'Etiqueta generada',
  ready_to_ship: 'Listo para enviar',
  shipped: 'Enviado',
  delivered: 'Entregado',
  expired: 'Vencido',
  cancelled: 'Cancelado',
  not_returned: 'No devuelto',
  waiting_for_return: 'Esperando devolución',
};

export const RETURN_SUBTYPE_ES = {
  low_cost: 'Bajo costo',
  return_partial: 'Devolución parcial',
  return_total: 'Devolución total',
};

export const RETURN_MONEY_STATUS_ES = {
  retained: 'Retenido',
  refunded: 'Reembolsado',
  available: 'Disponible',
  pending: 'Pendiente',
};

export const SHIPMENT_STATUS_ES = {
  pending: 'Pendiente',
  ready_to_ship: 'Listo para enviar',
  shipped: 'En tránsito',
  delivered: 'Entregado',
  cancelled: 'Cancelado',
  not_delivered: 'No entregado',
};

export const REFUND_AT_ES = {
  shipped: 'Al despachar devolución',
  delivered: 'Al recibir devolución',
};

// ── Traducciones de cambio (change) ──────────────────────────────────────────
export const CHANGE_TYPE_ES = {
  change: 'Cambio',
  replace: 'Reemplazo',
};

export const CHANGE_STATUS_ES = {
  pending: 'Pendiente',
  processing: 'En proceso',
  completed: 'Completado',
  cancelled: 'Cancelado',
  expired: 'Vencido',
};

// ── Traducciones de resoluciones esperadas ───────────────────────────────────
export const EXPECTED_RES_STATUS_ES = {
  pending: 'Pendiente',
  accepted: 'Aceptada',
  rejected: 'Rechazada',
};

export const PLAYER_ROLE_ES = {
  complainant: 'Comprador',
  respondent: 'Vendedor',
  mediator: 'Mediador',
};

// ── Helpers ──────────────────────────────────────────────────────────────────

/**
 * Sanitiza HTML permitiendo solo tags seguros para mensajes de ML.
 * Remueve scripts, event handlers y tags peligrosos.
 */
export const sanitizeMessageHtml = (html) => {
  if (!html) return '';
  const ALLOWED_TAGS = ['strong', 'b', 'em', 'i', 'u', 'br', 'p', 'ul', 'ol', 'li', 'a'];
  const div = document.createElement('div');
  div.innerHTML = html;
  for (const el of div.querySelectorAll('script, style, iframe, object, embed')) {
    el.remove();
  }
  for (const el of div.querySelectorAll('*')) {
    for (const attr of [...el.attributes]) {
      if (attr.name.startsWith('on') || attr.name === 'style') {
        el.removeAttribute(attr.name);
      }
    }
    if (!ALLOWED_TAGS.includes(el.tagName.toLowerCase())) {
      el.replaceWith(...el.childNodes);
    }
  }
  for (const a of div.querySelectorAll('a')) {
    const href = a.getAttribute('href') || '';
    if (!href.startsWith('http')) {
      a.replaceWith(...a.childNodes);
    } else {
      a.setAttribute('target', '_blank');
      a.setAttribute('rel', 'noopener noreferrer');
    }
  }
  return div.innerHTML;
};

const IMG_EXTENSIONS = ['.jpg', '.jpeg', '.png', '.gif', '.webp'];

export const isImageAttachment = (key) => {
  if (!key) return false;
  const lower = typeof key === 'string' ? key.toLowerCase() : '';
  return IMG_EXTENSIONS.some((ext) => lower.endsWith(ext));
};

export const attachmentProxyUrl = (key) => `/api/seriales/ml-attachment?id=${encodeURIComponent(key)}`;

/** Proxy URL for claim message attachments (different ML API than order messages) */
export const claimAttachmentProxyUrl = (claimId, filename) =>
  `/api/seriales/ml-claim-attachment?claim_id=${encodeURIComponent(claimId)}&filename=${encodeURIComponent(filename)}`;
