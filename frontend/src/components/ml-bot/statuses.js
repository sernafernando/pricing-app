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
// PR6 (ml-bot-panel-operador) adds `pending`/`drafting` labels — both were
// missing and fell through to the raw string. `pending` here is the EXACT
// `bot_status == 'pending'` value only (never NULL — see
// decisions-bot-status, obs #1805): NULL is overloaded (not-yet-processed
// anchor OR non-anchor burst context that will never be processed), so it
// is deliberately excluded from both this map and the filter's option set
// below rather than lumped in with `pending`.
export const MESSAGE_BOT_STATUS_LABELS = {
  pending: 'Pendiente',
  drafting: 'Redactando',
  awaiting_human: 'Esperando humano',
  taken_over: 'Tomada',
  sending: 'Enviando…',
  sent: 'Enviada',
  failed: 'Falló',
  superseded: 'Reemplazada',
  blocked_claim: 'Reclamo — el bot no responde',
};

export const MESSAGE_BOT_STATUS_BADGE_CLASS = {
  pending: 'badgeNeutral',
  drafting: 'badgeInfo',
  awaiting_human: 'badgeWarning',
  taken_over: 'badgeInfo',
  sending: 'badgeInfo',
  sent: 'badgeSuccess',
  failed: 'badgeDanger',
  superseded: 'badgeNeutral',
  blocked_claim: 'badgeDanger',
};

// PR6 — filter option set for the Mensajes tab `bot_status` filter.
// Deliberately does NOT include a "no procesado"/NULL option: NULL is
// overloaded (see decisions-bot-status, obs #1805) and the backend filter
// is a strict equality that never matches NULL, so exposing a NULL option
// here would either be a silent no-op or require the backend to special-
// case it — both worse than just not offering it. Every value below is a
// real, filterable `bot_status`.
export const MESSAGE_BOT_STATUS_FILTER_OPTIONS = [
  { value: 'pending', label: MESSAGE_BOT_STATUS_LABELS.pending },
  { value: 'drafting', label: MESSAGE_BOT_STATUS_LABELS.drafting },
  { value: 'awaiting_human', label: MESSAGE_BOT_STATUS_LABELS.awaiting_human },
  { value: 'taken_over', label: MESSAGE_BOT_STATUS_LABELS.taken_over },
  { value: 'sent', label: MESSAGE_BOT_STATUS_LABELS.sent },
  { value: 'failed', label: MESSAGE_BOT_STATUS_LABELS.failed },
  { value: 'superseded', label: MESSAGE_BOT_STATUS_LABELS.superseded },
  { value: 'blocked_claim', label: MESSAGE_BOT_STATUS_LABELS.blocked_claim },
];

// PR5 (ml-bot-panel-operador) — absorbs the orphaned WU6 from
// ml-bot-fallback-reason-tracking: operator-facing labels for
// `ml_bot_question.fallback_reason` (backend `FALLBACK_REASONS`, see
// `app/services/ml_questions/fallback_reasons.py`). A row with
// `fallback_reason == null` renders NO badge at all (predates the
// instrumentation) — callers must never fall back to a dash here.
export const FALLBACK_REASON_LABELS = {
  injection_flagged: 'Intento de manipulación',
  provider_error: 'Error del proveedor',
  fallback_denylist: 'Bloqueada por denylist',
  deflection: 'Desvío',
  low_confidence: 'Confianza baja',
  drafted_no_answer: 'Sin respuesta redactada',
};
