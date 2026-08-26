/**
 * Status label/badge maps for the ml-bot panel — extracted in PR4
 * (ml-bot-panel-operador, design ADR-3) from `MLQuestions.jsx`.
 *
 * Kept as TWO separate maps deliberately, not merged: `STATUS_LABELS`
 * describes `ml_bot_question.status` (8 values) and
 * `MESSAGE_BOT_STATUS_LABELS` describes `ml_bot_message.bot_status`
 * (7 values) — two different lifecycles that happen to share some label
 * strings. Merging them would make an unknown value from one lifecycle
 * silently render the other's label.
 */

export const STATUS_LABELS = {
  received: 'Recibida',
  drafting: 'Redactando',
  waiting: 'Esperando',
  publishing: 'Publicando',
  published: 'Publicada',
  taken_over: 'Tomada',
  pending_morning: 'Para la mañana',
  failed: 'Fallida',
};

export const STATUS_BADGE_CLASS = {
  received: 'badgeNeutral',
  drafting: 'badgeInfo',
  waiting: 'badgeWarning',
  publishing: 'badgeInfo',
  published: 'badgeSuccess',
  taken_over: 'badgeInfo',
  pending_morning: 'badgeWarning',
  failed: 'badgeDanger',
};

// Phase A, PR3 — `bot_status` lifecycle labels/badges for the Mensajes tab
// thread-header (mirrors STATUS_LABELS/STATUS_BADGE_CLASS above, but on the
// separate `bot_status` column — design "Interfaces / Contracts"). Only the
// anchor message of a thread ever carries a non-null `bot_status`.
export const MESSAGE_BOT_STATUS_LABELS = {
  awaiting_human: 'Esperando humano',
  taken_over: 'Tomada',
  sending: 'Enviando…',
  sent: 'Enviada',
  failed: 'Falló',
  superseded: 'Reemplazada',
  blocked_claim: 'Reclamo — el bot no responde',
};

export const MESSAGE_BOT_STATUS_BADGE_CLASS = {
  awaiting_human: 'badgeWarning',
  taken_over: 'badgeInfo',
  sending: 'badgeInfo',
  sent: 'badgeSuccess',
  failed: 'badgeDanger',
  superseded: 'badgeNeutral',
  blocked_claim: 'badgeDanger',
};
