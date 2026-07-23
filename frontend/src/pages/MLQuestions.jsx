/**
 * MLQuestions — Panel for the MercadoLibre pre-sale questions bot.
 *
 * Shows a live list of `ml_bot_questions` (SSE-driven reload, REST refetch
 * per ADR-8), lets a human take over / edit / publish-now / hold a question,
 * toggles the bot on/off, and exposes the business-knowledge config +
 * few-shot examples editors. Every action is also enforced backend-side —
 * this page only hides/disables UI, it never trusts itself for authz.
 */

import { useState, useEffect, useCallback, useMemo, useRef, Fragment } from 'react';
import { useReactTable, getCoreRowModel, flexRender } from '@tanstack/react-table';
import { useSSEChannel } from '../hooks/useSSEChannel';
import { usePermisos } from '../contexts/PermisosContext';
import api from '../services/api';
import ModalTesla from '../components/ModalTesla';
import {
  Bot,
  RefreshCcw,
  AlertTriangle,
  Loader,
  Clock,
  UserCheck,
  Send,
  PauseCircle,
  RotateCcw,
  Settings,
  Power,
  Plus,
  Trash2,
  ShieldAlert,
  ChevronDown,
  ChevronUp,
  ExternalLink,
} from 'lucide-react';
import styles from './MLQuestions.module.css';

// 60s polling fallback (panel-v2 requirement #4b) — the panel must never
// depend solely on SSE for reload; this is a safety net regardless of the
// SSE cross-worker delivery path (backend already routes through Redis
// pub/sub, mirroring the working `claims:updated` channel).
const POLL_INTERVAL_MS = 60_000;

// Fallback link builder when a row has no `item_permalink` (rows ingested
// before panel-v2, or enrichment failed at ingest time). ML's public item
// URLs use a hyphen after the 3-letter site prefix (MLA123 -> MLA-123).
function buildFallbackItemLink(itemId) {
  if (!itemId) return null;
  const match = /^([A-Za-z]{3})(\d+)$/.exec(itemId);
  if (!match) return null;
  return `https://articulo.mercadolibre.com.ar/${match[1]}-${match[2]}`;
}

// Item #5 (PR de pulido): curated model list per provider for the
// `llm_providers` roster editor's dropdown, so operators pick a known-good
// model instead of typing free text. Kept as a frontend constant — the
// roster JSON in `ml_bot_config` remains the source of truth; a free-text
// escape hatch (`__custom__`) always covers a model not in this list.
const LLM_PROVIDER_MODELS = {
  groq: [
    'llama-3.3-70b-versatile',
    'qwen/qwen3-32b',
    'llama-3.1-8b-instant',
    'openai/gpt-oss-120b',
  ],
  cerebras: ['llama-3.3-70b', 'llama3.1-8b'],
  openrouter: ['meta-llama/llama-3.3-70b-instruct:free'],
};
const LLM_ROSTER_CONFIG_KEY = 'llm_providers';
const CUSTOM_MODEL_OPTION = '__custom__';

const STATUS_LABELS = {
  received: 'Recibida',
  drafting: 'Redactando',
  waiting: 'Esperando',
  publishing: 'Publicando',
  published: 'Publicada',
  taken_over: 'Tomada',
  pending_morning: 'Para la mañana',
  failed: 'Fallida',
};

// Phase 5 (PR3) — ML Bot postventa messages tab. Read-only MVP: no reply /
// take-over actions yet (deferred to a future drafting slice). Mirrors the
// backend's raw `moderation_status` values (design §Schema); anything not
// in this map still renders via the raw fallback so ML contract drift never
// hides a badge silently.
const MESSAGE_STATUS_LABELS = {
  clean: 'Limpio',
  pending: 'Pendiente de revisión',
  flagged: 'Marcado',
};

// Phase A, PR3 — `bot_status` lifecycle labels/badges for the Mensajes tab
// thread-header (mirrors STATUS_LABELS/STATUS_BADGE_CLASS above, but on the
// separate `bot_status` column — design "Interfaces / Contracts"). Only the
// anchor message of a thread ever carries a non-null `bot_status`.
const MESSAGE_BOT_STATUS_LABELS = {
  awaiting_human: 'Esperando humano',
  taken_over: 'Tomada',
  sent: 'Enviada',
  failed: 'Falló',
  superseded: 'Reemplazada',
  blocked_claim: 'Reclamo — el bot no responde',
};

const MESSAGE_BOT_STATUS_BADGE_CLASS = {
  awaiting_human: 'badgeWarning',
  taken_over: 'badgeInfo',
  sent: 'badgeSuccess',
  failed: 'badgeDanger',
  superseded: 'badgeNeutral',
  blocked_claim: 'badgeDanger',
};

// States a thread's anchor message may be taken over from (mirrors backend
// `_MESSAGE_TAKE_OVER_SOURCE_STATES`).
const MESSAGE_TAKE_OVER_STATES = ['awaiting_human', 'blocked_claim'];
// ML post-sale conversation link (T0.2 verified — orchestrator instruction):
// query string intentionally omitted.
function buildMlConversationLink(packId) {
  if (!packId) return null;
  return `https://www.mercadolibre.com.ar/ventas/nueva/mensajeria/${packId}`;
}

// Item #5 (PR de pulido): structured editor for the `llm_providers` roster
// key — a small picker UI over the same JSON the panel already round-trips
// through the generic config text input. Falls back gracefully to an empty
// roster on unparseable JSON (never throws — matches the backend's own
// fail-safe roster parsing in `provider_rotation.py`).
function LlmProviderRosterEditor({ value, onChange }) {
  let entries;
  try {
    const parsed = JSON.parse(value || '[]');
    entries = Array.isArray(parsed) ? parsed : [];
  } catch {
    entries = [];
  }

  const commit = (next) => onChange(JSON.stringify(next));

  const updateEntry = (index, patch) => {
    commit(entries.map((entry, i) => (i === index ? { ...entry, ...patch } : entry)));
  };

  const removeEntry = (index) => {
    commit(entries.filter((_, i) => i !== index));
  };

  const addEntry = () => {
    commit([...entries, { name: 'groq', model: LLM_PROVIDER_MODELS.groq[0], enabled: true }]);
  };

  return (
    <div className={styles.rosterEditor}>
      {entries.map((entry, index) => {
        const curated = LLM_PROVIDER_MODELS[entry.name] || [];
        const isCustomModel = !entry.model || !curated.includes(entry.model);
        return (
          <div key={index} className={styles.rosterRow}>
            <select
              className={styles.rosterSelect}
              value={entry.name || ''}
              onChange={(e) => updateEntry(index, { name: e.target.value, model: '' })}
            >
              {Object.keys(LLM_PROVIDER_MODELS).map((name) => (
                <option key={name} value={name}>{name}</option>
              ))}
              <option value="">otro (personalizado)</option>
            </select>
            <select
              className={styles.rosterSelect}
              value={isCustomModel ? CUSTOM_MODEL_OPTION : entry.model}
              onChange={(e) => {
                const next = e.target.value;
                updateEntry(index, { model: next === CUSTOM_MODEL_OPTION ? '' : next });
              }}
            >
              {curated.map((model) => (
                <option key={model} value={model}>{model}</option>
              ))}
              <option value={CUSTOM_MODEL_OPTION}>personalizado…</option>
            </select>
            {isCustomModel && (
              <input
                type="text"
                className={styles.configInput}
                placeholder="modelo personalizado"
                value={entry.model || ''}
                onChange={(e) => updateEntry(index, { model: e.target.value })}
              />
            )}
            <label className={styles.rosterEnabledLabel}>
              <input
                type="checkbox"
                checked={entry.enabled !== false}
                onChange={(e) => updateEntry(index, { enabled: e.target.checked })}
              />
              activo
            </label>
            <button
              type="button"
              className="btn-tesla outline-subtle-danger sm"
              onClick={() => removeEntry(index)}
              aria-label="Quitar proveedor"
            >
              <Trash2 size={14} />
            </button>
          </div>
        );
      })}
      <button type="button" className="btn-tesla outline-subtle-primary sm" onClick={addEntry}>
        <Plus size={14} /> Agregar variante
      </button>
    </div>
  );
}

const STATUS_BADGE_CLASS = {
  received: 'badgeNeutral',
  drafting: 'badgeInfo',
  waiting: 'badgeWarning',
  publishing: 'badgeInfo',
  published: 'badgeSuccess',
  taken_over: 'badgeInfo',
  pending_morning: 'badgeWarning',
  failed: 'badgeDanger',
};

// Soft client-side denylist warning (adjudicated nicety) — never blocks,
// only nudges a human editing a manual answer. Backend has no equivalent
// check on human-authored answers (R-502 applies to bot output only).
const PRICE_PATTERN = /\$\s?\d|\b\d+[.,]?\d*\s*(pesos|ars|usd|u\$s)\b/i;
const ADDRESS_PATTERN = /\b(calle|av\.?|avenida|ruta)\s+[a-záéíóúñ.]+\s*\d{2,}/i;

function checkSoftDenylist(text) {
  if (!text) return null;
  if (PRICE_PATTERN.test(text)) return 'contiene posible precio — revisalo antes de publicar';
  if (ADDRESS_PATTERN.test(text)) return 'contiene posible dirección — revisalo antes de publicar';
  return null;
}

// TanStack column-sizing engine adopted for the Preguntas table ONLY
// (#956 fixed — a hand-rolled resizer failed 4x on drag math/specificity).
// We consume the library purely as a column-sizing engine: `data: []`, no
// row model — the body stays the existing hand-rendered `.map()` +
// `Fragment` + `renderDetailRow`. The shared `<colgroup>` (driven by
// `getVisibleLeafColumns()`) is the single source of truth for both the
// TanStack-rendered header row and the untouched body rows under
// `table-layout: fixed`.
//
// Locked sizing (tasks.md override — notebook-fit ~1024px, supersedes the
// design doc's 1105px default): sum = 1024px on a true ~1024px notebook,
// `.table-container-tesla` already has `overflow-x:auto` as a fallback.
// Acciones is fixed at 280px — measured floor for the worst-case
// `taken_over` row (chevron + Editar + PublicarAhora + Retener ≈ 267px).
// Readable default sizes (sum ~1110px). Minor horizontal scroll on a small
// notebook is fine — the columns are resizable and persist, and the shared
// .table-container-tesla already provides overflow-x. The Acciones floor (280)
// fits up to 5 `btn-tesla sm` buttons without clipping (the #956 failure mode).
const PREGUNTAS_COLUMNS = [
  { id: 'pregunta', header: 'Pregunta', size: 200, minSize: 120, maxSize: 600, enableResizing: true },
  { id: 'item', header: 'Item', size: 120, minSize: 100, maxSize: 400, enableResizing: true },
  { id: 'estado', header: 'Estado', size: 90, enableResizing: false },
  { id: 'respuesta', header: 'Respuesta (borrador)', size: 200, minSize: 100, maxSize: 600, enableResizing: true },
  { id: 'confianza', header: 'Confianza', size: 70, enableResizing: false },
  { id: 'cuentaRegresiva', header: 'Cuenta regresiva', size: 150, enableResizing: false },
  { id: 'acciones', header: 'Acciones', size: 280, minSize: 280, maxSize: 280, enableResizing: false },
];

// Historial del comprador table (inside the expanded detail row) — same
// TanStack column-sizing engine pattern as PREGUNTAS_COLUMNS above, applied
// to the read-only 5-column buyer-history table. No action buttons here, so
// there's no #956-style clipping concern; sizes are just readable defaults.
const HISTORIAL_COLUMNS = [
  { id: 'fecha', header: 'Fecha', size: 150, enableResizing: false },
  { id: 'pregunta', header: 'Pregunta', size: 200, minSize: 100, maxSize: 600, enableResizing: true },
  { id: 'item', header: 'Item', size: 120, minSize: 80, maxSize: 400, enableResizing: true },
  { id: 'estado', header: 'Estado', size: 90, enableResizing: false },
  { id: 'respuesta', header: 'Respuesta', size: 200, minSize: 100, maxSize: 600, enableResizing: true },
];

// Mensajes tab table (thread-grouped) — same TanStack sizing-engine pattern,
// but structurally different: the buyer identity lives in a `colSpan={5}`
// thread-header row, not in a per-message cell. Column 1 ("Comprador ·
// Pack") in message rows is just a thin indent `<td>` (`threadRowIndent`),
// so it carries NO resizable content — only "Mensaje" (col 2) is resizable.
const MENSAJES_COLUMNS = [
  { id: 'comprador', header: 'Comprador · Pack', size: 150, enableResizing: false },
  { id: 'mensaje', header: 'Mensaje', size: 320, minSize: 120, maxSize: 600, enableResizing: true },
  { id: 'recibido', header: 'Recibido', size: 150, enableResizing: false },
  { id: 'leido', header: 'Leído', size: 150, enableResizing: false },
  { id: 'moderacion', header: 'Moderación', size: 120, enableResizing: false },
];

// Stable empty array reference — we never call `getRowModel()`, TanStack
// only needs `data` to satisfy its API shape.
const EMPTY_TABLE_DATA = [];

const COLUMN_SIZING_STORAGE_KEY = 'mlq:colsizing:preguntas';
const HISTORIAL_COLUMN_SIZING_STORAGE_KEY = 'mlq:colsizing:historial';
const MENSAJES_COLUMN_SIZING_STORAGE_KEY = 'mlq:colsizing:mensajes';

// Fail-safe persistence (mirrors `LlmProviderRosterEditor`'s parse pattern
// already in this file): absent/corrupt/disabled localStorage MUST never
// throw, and MUST fall back to `{}` so TanStack uses each column's default
// `size`. Unknown/stale column ids in the stored object are inert — TanStack
// only reads sizes for columns that currently exist.
// eslint-disable-next-line react-refresh/only-export-components
export function loadColumnSizing(key = COLUMN_SIZING_STORAGE_KEY) {
  try {
    const parsed = JSON.parse(localStorage.getItem(key) || '{}');
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {};
  } catch {
    return {};
  }
}

// eslint-disable-next-line react-refresh/only-export-components
export function saveColumnSizing(state, key = COLUMN_SIZING_STORAGE_KEY) {
  try {
    localStorage.setItem(key, JSON.stringify(state));
  } catch {
    // Disabled/private-mode localStorage: resizing still works in-memory,
    // it just won't persist across reload.
  }
}

function secondsRemaining(waitUntil, referenceNow) {
  if (!waitUntil) return null;
  const diff = new Date(waitUntil).getTime() - referenceNow;
  return Math.max(0, Math.round(diff / 1000));
}

function formatCountdown(seconds) {
  if (seconds == null) return '—';
  if (seconds <= 0) return 'Publicando...';
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${String(s).padStart(2, '0')}`;
}

export default function MLQuestions() {
  const { tienePermiso } = usePermisos();
  const puedeVer = tienePermiso('ml_bot.ver');
  const puedeResponder = tienePermiso('ml_bot.responder');
  const puedeConfigurar = tienePermiso('ml_bot.config');
  const puedeEncenderApagar = tienePermiso('ml_bot.on_off');
  const puedeVerMensajes = tienePermiso('ml_bot.messages.ver');
  const puedeResponderMensajes = tienePermiso('ml_bot.messages.responder');

  const [activeTab, setActiveTab] = useState('preguntas');

  // Questions list
  const [questions, setQuestions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [statusFilter, setStatusFilter] = useState('');
  const [now, setNow] = useState(Date.now());

  // Edit modal
  const [editQuestion, setEditQuestion] = useState(null);
  const [editText, setEditText] = useState('');
  const [actionLoadingId, setActionLoadingId] = useState(null);
  const [actionError, setActionError] = useState(null);

  // Config editor
  const [configItems, setConfigItems] = useState([]);
  const [configLoading, setConfigLoading] = useState(false);
  const [configError, setConfigError] = useState(null);
  const [configDrafts, setConfigDrafts] = useState({});
  const [savingClave, setSavingClave] = useState(null);

  // Few-shot examples
  const [examples, setExamples] = useState([]);
  const [examplesLoading, setExamplesLoading] = useState(false);
  const [newExample, setNewExample] = useState({ question_example: '', answer_example: '', category: '' });
  const [savingExample, setSavingExample] = useState(false);

  // Bot toggle
  const [toggling, setToggling] = useState(false);

  // Messages tab (Phase 5, PR3) — read-only list of ml_bot_messages
  const [messages, setMessages] = useState([]);
  const [messagesLoading, setMessagesLoading] = useState(true);
  const [messagesError, setMessagesError] = useState(null);

  const messageThreads = useMemo(() => {
    if (!messages || messages.length === 0) return [];
    const groups = new Map();
    for (const m of messages) {
      const key = m.pack_id ? `pack:${m.pack_id}` : `buyer:${m.buyer_id || 'unknown'}`;
      if (!groups.has(key)) {
        groups.set(key, {
          key,
          pack_id: m.pack_id ?? null,
          buyer_id: m.buyer_id ?? null,
          buyer_nickname: m.buyer_nickname ?? null,
          messages: [],
        });
      }
      const group = groups.get(key);
      group.messages.push(m);
      if (m.buyer_nickname && !group.buyer_nickname) {
        group.buyer_nickname = m.buyer_nickname;
      }
    }
    for (const g of groups.values()) {
      g.messages.sort((a, b) => {
        const ta = a.received_at ? new Date(a.received_at).getTime() : 0;
        const tb = b.received_at ? new Date(b.received_at).getTime() : 0;
        return ta - tb;
      });
      g.latest_received_at = g.messages[g.messages.length - 1]?.received_at ?? null;
      // Anchor = the most recent message carrying a non-null `bot_status`
      // (design "Draft unit = anchor" — earlier burst messages stay NULL).
      const statused = g.messages.filter((m) => m.bot_status);
      g.anchorMessage = statused.length > 0 ? statused[statused.length - 1] : null;
    }
    return Array.from(groups.values()).sort((a, b) => {
      const ta = a.latest_received_at ? new Date(a.latest_received_at).getTime() : 0;
      const tb = b.latest_received_at ? new Date(b.latest_received_at).getTime() : 0;
      return tb - ta;
    });
  }, [messages]);

  const [buyerFilter, setBuyerFilter] = useState('');
  const [packFilter, setPackFilter] = useState('');
  const [sinPack, setSinPack] = useState(false);
  const [includeModerated, setIncludeModerated] = useState(false);
  const [hasReadFilter, setHasReadFilter] = useState('');

  // Message thread actions (Phase A, PR3) — take-over/edit/send + detail
  // spoiler. Kept separate from the Preguntas action state above since the
  // two tabs act on different entities and can race independently.
  const [editMessage, setEditMessage] = useState(null);
  const [editMessageText, setEditMessageText] = useState('');
  const [msgActionLoadingId, setMsgActionLoadingId] = useState(null);
  const [msgActionError, setMsgActionError] = useState(null);
  const [expandedThreadKey, setExpandedThreadKey] = useState(null);

  // Expandable row detail (panel-v2 requirements #3 + #5) — one expanded
  // panel per row with two sections: "Detalle" (full question/answer text,
  // read-only, no take-over required) and "Historial del comprador"
  // (lazy-loaded on demand). Available to any `ml_bot.ver` holder in any
  // status.
  const [expandedId, setExpandedId] = useState(null);
  const [expandedTab, setExpandedTab] = useState('detalle');
  const [historyItems, setHistoryItems] = useState([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState(null);
  const [historyLoadedForId, setHistoryLoadedForId] = useState(null);
  // Tracks the row whose history is currently being requested, so a stale
  // in-flight response (from a row the operator already navigated away
  // from) never overwrites the history of the row that's now expanded.
  const expandedIdRef = useRef(null);

  // Preguntas table — TanStack column-sizing engine (see PREGUNTAS_COLUMNS
  // above). `columnSizing` initializes from localStorage; changes are
  // debounced (~200ms, since `onChange` resize mode fires per mouse-move
  // during a drag) before persisting.
  const [columnSizing, setColumnSizingState] = useState(() => loadColumnSizing());
  const columnSizingSaveTimerRef = useRef(null);

  const handleColumnSizingChange = useCallback((updater) => {
    setColumnSizingState((prev) => {
      const next = typeof updater === 'function' ? updater(prev) : updater;
      if (columnSizingSaveTimerRef.current) clearTimeout(columnSizingSaveTimerRef.current);
      columnSizingSaveTimerRef.current = setTimeout(() => saveColumnSizing(next), 200);
      return next;
    });
  }, []);

  const handleResetColumnSizing = useCallback(() => {
    if (columnSizingSaveTimerRef.current) clearTimeout(columnSizingSaveTimerRef.current);
    setColumnSizingState({});
    try {
      localStorage.removeItem(COLUMN_SIZING_STORAGE_KEY);
    } catch {
      // no-op — disabled/private-mode localStorage
    }
  }, []);

  const preguntasTable = useReactTable({
    columns: PREGUNTAS_COLUMNS,
    data: EMPTY_TABLE_DATA,
    columnResizeMode: 'onChange',
    getCoreRowModel: getCoreRowModel(),
    state: { columnSizing },
    onColumnSizingChange: handleColumnSizingChange,
  });

  const hasCustomColumnSizing = Object.keys(columnSizing).length > 0;

  // Historial del comprador table — same sizing-engine pattern, own
  // localStorage key and its own debounce timer. There is only ever one
  // expanded row (`expandedId`), so a single shared top-level instance is
  // correct (must NOT be instantiated inside `renderDetailRow` — that would
  // violate the Rules of Hooks by calling a hook conditionally/per-row).
  const [historialColumnSizing, setHistorialColumnSizingState] = useState(() => loadColumnSizing(HISTORIAL_COLUMN_SIZING_STORAGE_KEY));
  const historialColumnSizingSaveTimerRef = useRef(null);

  const handleHistorialColumnSizingChange = useCallback((updater) => {
    setHistorialColumnSizingState((prev) => {
      const next = typeof updater === 'function' ? updater(prev) : updater;
      if (historialColumnSizingSaveTimerRef.current) clearTimeout(historialColumnSizingSaveTimerRef.current);
      historialColumnSizingSaveTimerRef.current = setTimeout(() => saveColumnSizing(next, HISTORIAL_COLUMN_SIZING_STORAGE_KEY), 200);
      return next;
    });
  }, []);

  const handleResetHistorialColumnSizing = useCallback(() => {
    if (historialColumnSizingSaveTimerRef.current) clearTimeout(historialColumnSizingSaveTimerRef.current);
    setHistorialColumnSizingState({});
    try {
      localStorage.removeItem(HISTORIAL_COLUMN_SIZING_STORAGE_KEY);
    } catch {
      // no-op — disabled/private-mode localStorage
    }
  }, []);

  const historialTable = useReactTable({
    columns: HISTORIAL_COLUMNS,
    data: EMPTY_TABLE_DATA,
    columnResizeMode: 'onChange',
    getCoreRowModel: getCoreRowModel(),
    state: { columnSizing: historialColumnSizing },
    onColumnSizingChange: handleHistorialColumnSizingChange,
  });

  const hasCustomHistorialColumnSizing = Object.keys(historialColumnSizing).length > 0;

  // Mensajes table — same sizing-engine pattern, own localStorage key and
  // debounce timer. Only one instance needed (the table itself is not
  // duplicated per thread — threads are body rows under one shared header).
  const [mensajesColumnSizing, setMensajesColumnSizingState] = useState(() => loadColumnSizing(MENSAJES_COLUMN_SIZING_STORAGE_KEY));
  const mensajesColumnSizingSaveTimerRef = useRef(null);

  const handleMensajesColumnSizingChange = useCallback((updater) => {
    setMensajesColumnSizingState((prev) => {
      const next = typeof updater === 'function' ? updater(prev) : updater;
      if (mensajesColumnSizingSaveTimerRef.current) clearTimeout(mensajesColumnSizingSaveTimerRef.current);
      mensajesColumnSizingSaveTimerRef.current = setTimeout(() => saveColumnSizing(next, MENSAJES_COLUMN_SIZING_STORAGE_KEY), 200);
      return next;
    });
  }, []);

  const handleResetMensajesColumnSizing = useCallback(() => {
    if (mensajesColumnSizingSaveTimerRef.current) clearTimeout(mensajesColumnSizingSaveTimerRef.current);
    setMensajesColumnSizingState({});
    try {
      localStorage.removeItem(MENSAJES_COLUMN_SIZING_STORAGE_KEY);
    } catch {
      // no-op — disabled/private-mode localStorage
    }
  }, []);

  const mensajesTable = useReactTable({
    columns: MENSAJES_COLUMNS,
    data: EMPTY_TABLE_DATA,
    columnResizeMode: 'onChange',
    getCoreRowModel: getCoreRowModel(),
    state: { columnSizing: mensajesColumnSizing },
    onColumnSizingChange: handleMensajesColumnSizingChange,
  });

  const hasCustomMensajesColumnSizing = Object.keys(mensajesColumnSizing).length > 0;

  // Bot status (visible to ANY ml_bot.ver holder, not just ml_bot.config —
  // Judgment Day fix: the on/off + supervised-mode badges were previously
  // invisible to operators who only had ml_bot.ver/ml_bot.responder).
  const [status, setStatus] = useState(null);

  const cargarStatus = useCallback(async () => {
    try {
      const { data } = await api.get('/ml-bot/status');
      setStatus(data);
    } catch {
      setStatus(null);
    }
  }, []);

  const cargarPreguntas = useCallback(async ({ silent = false } = {}) => {
    if (!silent) setLoading(true);
    setError(null);
    try {
      const params = { limit: 100 };
      if (statusFilter) params.status = statusFilter;
      const { data } = await api.get('/ml-bot/questions', { params });
      setQuestions(data.questions);
    } catch {
      // Silent (background) refreshes must not wipe the currently rendered
      // rows / expanded panel on a transient error — only surface the error
      // banner and clear the table on an explicit (non-silent) load.
      if (!silent) {
        setQuestions([]);
        setError('Error al cargar preguntas');
      }
    } finally {
      if (!silent) setLoading(false);
    }
  }, [statusFilter]);

  const cargarConfig = useCallback(async () => {
    if (!puedeConfigurar) return;
    setConfigLoading(true);
    setConfigError(null);
    try {
      const { data } = await api.get('/ml-bot/config');
      setConfigItems(data.items);
      const drafts = {};
      data.items.forEach((item) => { drafts[item.clave] = item.valor; });
      setConfigDrafts(drafts);
    } catch {
      setConfigError('Error al cargar configuración');
    } finally {
      setConfigLoading(false);
    }
  }, [puedeConfigurar]);

  const cargarExamples = useCallback(async () => {
    if (!puedeConfigurar) return;
    setExamplesLoading(true);
    try {
      const { data } = await api.get('/ml-bot/examples');
      setExamples(data.examples);
    } catch {
      setExamples([]);
    } finally {
      setExamplesLoading(false);
    }
  }, [puedeConfigurar]);

  useEffect(() => {
    if (puedeVer) {
      cargarPreguntas();
      cargarStatus();
    }
  }, [cargarPreguntas, cargarStatus, puedeVer]);

  useEffect(() => {
    if (activeTab === 'config') {
      cargarConfig();
      cargarExamples();
    }
  }, [activeTab, cargarConfig, cargarExamples]);

  const cargarMensajes = useCallback(async ({ silent = false } = {}) => {
    if (!puedeVerMensajes) return;
    if (!silent) setMessagesLoading(true);
    setMessagesError(null);
    try {
      const params = { limit: 100 };
      if (buyerFilter.trim()) params.buyer_id = buyerFilter.trim();
      if (sinPack) {
        params.pack_id = 'none';
      } else if (packFilter.trim()) {
        params.pack_id = packFilter.trim();
      }
      if (hasReadFilter !== '') params.has_read = hasReadFilter === 'true';
      if (includeModerated) params.include_moderated = true;
      const { data } = await api.get('/ml-bot/messages', { params });
      setMessages(data.messages || []);
    } catch {
      if (!silent) {
        setMessages([]);
        setMessagesError('Error al cargar mensajes');
      }
    } finally {
      if (!silent) setMessagesLoading(false);
    }
  }, [puedeVerMensajes, buyerFilter, packFilter, sinPack, includeModerated, hasReadFilter]);

  useEffect(() => {
    if (activeTab === 'mensajes' && puedeVerMensajes) {
      cargarMensajes();
    }
  }, [activeTab, puedeVerMensajes, cargarMensajes]);

  // SSE reload for the messages tab — mirrors the questions tab's reload
  // pattern (mounted whenever the operator has the permission, so the tab
  // stays warm across tab switches without a re-fetch storm).
  const reloadMessagesFromSSE = useCallback(() => {
    if (puedeVerMensajes) {
      cargarMensajes({ silent: true });
    }
  }, [puedeVerMensajes, cargarMensajes]);

  useSSEChannel('ml_bot:messages', reloadMessagesFromSSE, { enabled: puedeVerMensajes });

  const runMessageAction = async (fn, messageId) => {
    setMsgActionLoadingId(messageId);
    setMsgActionError(null);
    try {
      await fn();
    } catch (err) {
      setMsgActionError(err?.response?.data?.detail || 'No se pudo completar la acción');
    } finally {
      // Always resync — mirrors runAction: an action can 409 after partially
      // mutating server state (operator race), so re-fetch regardless.
      await cargarMensajes();
      setMsgActionLoadingId(null);
    }
  };

  const handleTakeOverMessage = (message) => runMessageAction(async () => {
    await api.post(`/ml-bot/messages/${message.id}/take-over`);
  }, message.id);

  const handleSendMessage = (message) => runMessageAction(async () => {
    await api.post(`/ml-bot/messages/${message.id}/send`);
  }, message.id);

  const openMessageEdit = (message) => {
    setEditMessage(message);
    setEditMessageText(message.drafted_answer || '');
    setMsgActionError(null);
  };

  const closeMessageEdit = () => {
    setEditMessage(null);
    setEditMessageText('');
    setMsgActionError(null);
  };

  const handleSaveMessageAnswer = () => runMessageAction(async () => {
    await api.put(`/ml-bot/messages/${editMessage.id}/answer`, { drafted_answer: editMessageText });
    closeMessageEdit();
  }, editMessage.id);

  const toggleThreadDetail = (threadKey) => {
    setExpandedThreadKey((prev) => (prev === threadKey ? null : threadKey));
  };

  // SSE-driven reload: instant panel update on any bot state transition.
  const reloadFromSSE = useCallback(() => {
    if (puedeVer) {
      cargarPreguntas();
      cargarStatus();
    }
    if (activeTab === 'config') {
      cargarConfig();
      cargarExamples();
    }
  }, [puedeVer, cargarPreguntas, cargarStatus, activeTab, cargarConfig, cargarExamples]);

  useSSEChannel('ml_bot:questions', reloadFromSSE);

  // 60s polling fallback (panel-v2 requirement #4b) — the panel must never
  // depend solely on SSE reload; this refetches regardless of whether the
  // SSE event was actually delivered.
  useEffect(() => {
    if (!puedeVer) return;
    const id = setInterval(() => {
      // Silent refresh: must not toggle the table-wide loading state, which
      // would otherwise collapse the expanded detail panel (and whatever
      // tab/history the operator is reading) every 60s.
      cargarPreguntas({ silent: true });
      cargarStatus();
    }, POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [puedeVer, cargarPreguntas, cargarStatus]);

  const cargarHistorial = useCallback(async (questionId) => {
    setHistoryItems([]);
    setHistoryError(null);
    setHistoryLoading(true);
    try {
      const { data } = await api.get(`/ml-bot/questions/${questionId}/buyer-history`);
      // Stale-response guard: if the operator collapsed this row or opened
      // a different one while the request was in flight, discard the
      // response instead of overwriting the history panel of a now-current
      // (different) row with the wrong buyer's data.
      if (expandedIdRef.current !== questionId) return;
      setHistoryItems(data.questions);
      setHistoryLoadedForId(questionId);
    } catch {
      if (expandedIdRef.current !== questionId) return;
      setHistoryError('Error al cargar el historial del comprador');
    } finally {
      if (expandedIdRef.current === questionId) setHistoryLoading(false);
    }
  }, []);

  const toggleExpand = (question) => {
    if (expandedId === question.id) {
      setExpandedId(null);
      expandedIdRef.current = null;
      return;
    }
    setExpandedId(question.id);
    expandedIdRef.current = question.id;
    setExpandedTab('detalle');
  };

  const openExpandTab = (question, tab) => {
    setExpandedId(question.id);
    expandedIdRef.current = question.id;
    setExpandedTab(tab);
    if (tab === 'historial' && historyLoadedForId !== question.id) {
      cargarHistorial(question.id);
    }
  };

  // Live countdown ticker (client-side only, server remains source of truth
  // via wait_until — a page refresh always re-syncs).
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  // Bot on/off + supervised-mode booleans come straight from GET /status
  // (visible to every ml_bot.ver holder) — no more string-parsing a config
  // item's raw `valor` (Judgment Day fix: the old `valor === 'true'` check
  // didn't match the backend's real truthy convention, `_cast_bool`).
  const botEnabled = status?.bot_enabled ?? false;
  const autoPublishEnabled = status?.auto_publish_enabled ?? false;

  const handleToggle = async (enabled) => {
    setToggling(true);
    try {
      await api.post('/ml-bot/toggle', { enabled });
      cargarStatus();
      if (puedeConfigurar) cargarConfig();
    } catch {
      setError('Error al cambiar el estado del bot');
    } finally {
      setToggling(false);
    }
  };

  const openEdit = (question) => {
    setEditQuestion(question);
    setEditText(question.drafted_answer || '');
    setActionError(null);
  };

  const closeEdit = () => {
    setEditQuestion(null);
    setEditText('');
    setActionError(null);
  };

  const runAction = async (fn, questionId) => {
    setActionLoadingId(questionId);
    setActionError(null);
    try {
      await fn();
    } catch (err) {
      setActionError(err?.response?.data?.detail || 'No se pudo completar la acción');
    } finally {
      // Always resync — an action can fail with a 409 (operator race) after
      // partially mutating server state, so we re-fetch regardless of outcome.
      await cargarPreguntas();
      setActionLoadingId(null);
    }
  };

  const handleTakeOver = (question) => runAction(async () => {
    await api.post(`/ml-bot/questions/${question.id}/take-over`);
  }, question.id);

  const handleHold = (question) => runAction(async () => {
    await api.post(`/ml-bot/questions/${question.id}/hold`);
  }, question.id);

  const handleSaveAnswer = () => runAction(async () => {
    await api.put(`/ml-bot/questions/${editQuestion.id}/answer`, { drafted_answer: editText });
  }, editQuestion.id);

  const handlePublishNow = (question) => runAction(async () => {
    await api.post(`/ml-bot/questions/${question.id}/publish-now`);
    if (editQuestion?.id === question.id) closeEdit();
  }, question.id);

  const handleSaveAndPublish = () => runAction(async () => {
    await api.put(`/ml-bot/questions/${editQuestion.id}/answer`, { drafted_answer: editText });
    await api.post(`/ml-bot/questions/${editQuestion.id}/publish-now`);
    closeEdit();
  }, editQuestion.id);

  const handleConfigSave = async (clave) => {
    setSavingClave(clave);
    try {
      const original = configItems.find((item) => item.clave === clave);
      await api.put(`/ml-bot/config/${clave}`, {
        valor: configDrafts[clave],
        descripcion: original?.descripcion || null,
        tipo: original?.tipo || 'string',
      });
      await cargarConfig();
    } catch {
      setConfigError(`Error al guardar "${clave}"`);
    } finally {
      setSavingClave(null);
    }
  };

  const handleCreateExample = async () => {
    if (!newExample.question_example.trim() || !newExample.answer_example.trim()) return;
    setSavingExample(true);
    try {
      await api.post('/ml-bot/examples', newExample);
      setNewExample({ question_example: '', answer_example: '', category: '' });
      cargarExamples();
    } catch {
      setConfigError('Error al crear ejemplo');
    } finally {
      setSavingExample(false);
    }
  };

  const handleDeleteExample = async (id) => {
    try {
      await api.delete(`/ml-bot/examples/${id}`);
      cargarExamples();
    } catch {
      setConfigError('Error al eliminar ejemplo');
    }
  };

  const softWarning = checkSoftDenylist(editText);
  const messageSoftWarning = checkSoftDenylist(editMessageText);

  // Detail spoiler for a message thread (mirrors `renderDetailRow` above) —
  // full pack conversation in order, current draft + category/confidence,
  // and the ML conversation link (T0.2-verified format).
  const renderMessageDetailRow = (thread) => {
    const link = buildMlConversationLink(thread.pack_id);
    const anchor = thread.anchorMessage;
    return (
      <tr key={`${thread.key}-detail`} className={styles.detailRow}>
        <td colSpan={5}>
          <div className={styles.detailPanel}>
            <div className={styles.detailContent}>
              <div>
                <strong>Conversación completa</strong>
                {thread.messages.map((m) => (
                  <p key={m.id} className={styles.detailText}>
                    <em>Comprador{m.received_at ? ` · ${new Date(m.received_at).toLocaleString()}` : ''}:</em>{' '}
                    {m.text}
                  </p>
                ))}
              </div>
              <div>
                <strong>Respuesta (borrador)</strong>
                <p className={styles.detailText}>{anchor?.drafted_answer || '—'}</p>
              </div>
              {anchor?.intent_category && (
                <div>
                  <strong>Categoría</strong>
                  <p className={styles.detailText}>{anchor.intent_category}</p>
                </div>
              )}
              {anchor?.confidence != null && (
                <div>
                  <strong>Confianza</strong>
                  <p className={styles.detailText}>{Math.round(anchor.confidence * 100)}%</p>
                </div>
              )}
              <div>
                <strong>Conversación en ML</strong>
                <p>
                  {link ? (
                    <a href={link} target="_blank" rel="noopener noreferrer" className={styles.detailLink}>
                      Ver en MercadoLibre <ExternalLink size={12} />
                    </a>
                  ) : '—'}
                </p>
              </div>
            </div>
          </div>
        </td>
      </tr>
    );
  };

  // Expanded detail panel for a single row — rendered as the immediate
  // sibling <tr> right after its parent row (inside the map), never at the
  // end of <tbody>, so it stays visually attached to the row the operator
  // expanded regardless of how many other rows are in the table.
  const renderDetailRow = (q) => {
    const fallbackLink = buildFallbackItemLink(q.item_id);
    const itemLink = (q.item_permalink && q.item_permalink.startsWith('https://'))
      ? q.item_permalink
      : fallbackLink;
    return (
      <tr key={`${q.id}-detail`} className={styles.detailRow}>
        <td colSpan={7}>
          <div className={styles.detailPanel}>
            <div className={styles.detailTabBar}>
              <button
                type="button"
                className={`${styles.detailTab} ${expandedTab === 'detalle' ? styles.detailTabActive : ''}`}
                onClick={() => setExpandedTab('detalle')}
              >
                Detalle
              </button>
              <button
                type="button"
                className={`${styles.detailTab} ${expandedTab === 'historial' ? styles.detailTabActive : ''}`}
                onClick={() => openExpandTab(q, 'historial')}
              >
                Historial del comprador
              </button>
            </div>

            {expandedTab === 'detalle' && (
              <div className={styles.detailContent}>
                <div>
                  <strong>Pregunta completa</strong>
                  <p className={styles.detailText}>{q.question_text}</p>
                </div>
                <div>
                  <strong>Respuesta (borrador)</strong>
                  <p className={styles.detailText}>{q.drafted_answer || '—'}</p>
                </div>
                {q.llm_provider && (
                  <div>
                    <strong>Proveedor LLM</strong>
                    <p className={styles.detailText}>{q.llm_provider}</p>
                  </div>
                )}
                <div>
                  <strong>Publicación</strong>
                  <p>
                    {itemLink ? (
                      <a
                        href={itemLink}
                        target="_blank"
                        rel="noopener noreferrer"
                        className={styles.detailLink}
                      >
                        {q.item_title || q.item_id} <ExternalLink size={12} />
                      </a>
                    ) : (
                      q.item_id
                    )}
                  </p>
                </div>
              </div>
            )}

            {expandedTab === 'historial' && (
              <div className={styles.detailContent}>
                {historyLoading ? (
                  <div className={styles.loadingCell}>Cargando...</div>
                ) : historyError ? (
                  <div className={styles.errorBar}>
                    <AlertTriangle size={14} />
                    {historyError}
                  </div>
                ) : q.buyer_id == null ? (
                  <div className={styles.emptyCell}>Esta pregunta no tiene comprador identificado</div>
                ) : historyItems.length === 0 ? (
                  <div className={styles.emptyCell}>No hay preguntas anteriores de este comprador</div>
                ) : (
                  <>
                    {hasCustomHistorialColumnSizing && (
                      <div className={styles.columnSizingBar}>
                        <button
                          type="button"
                          className="btn-tesla ghost sm"
                          onClick={handleResetHistorialColumnSizing}
                        >
                          Restablecer columnas
                        </button>
                      </div>
                    )}
                    <div className="table-container-tesla">
                    <table
                      className={`table-tesla striped ${styles.resizableTable}`}
                      style={{ width: historialTable.getTotalSize() }}
                    >
                      <colgroup>
                        {historialTable.getVisibleLeafColumns().map((col) => (
                          <col key={col.id} style={{ width: col.getSize() }} />
                        ))}
                      </colgroup>
                      <thead className="table-tesla-head">
                        <tr>
                          {historialTable.getFlatHeaders().map((h) => (
                            <th key={h.id} style={{ position: 'relative' }}>
                              {flexRender(h.column.columnDef.header, h.getContext())}
                              {h.column.getCanResize() && (
                                <span
                                  className={`${styles.resizeGrip} ${h.column.getIsResizing() ? styles.resizeGripActive : ''}`}
                                  onMouseDown={h.getResizeHandler()}
                                  onTouchStart={h.getResizeHandler()}
                                  role="separator"
                                  aria-orientation="vertical"
                                  aria-label={`Redimensionar columna ${h.column.columnDef.header}`}
                                />
                              )}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody className="table-tesla-body">
                        {historyItems.map((h) => (
                          <tr key={h.id}>
                            <td>{new Date(h.question_date).toLocaleString()}</td>
                            <td className={styles.cellQuestion} title={h.question_text}>{h.question_text}</td>
                            <td className={styles.cellItem}>{h.item_title || '—'}</td>
                            <td>
                              <span className={`${styles.badge} ${styles[STATUS_BADGE_CLASS[h.status]] || ''}`}>
                                {STATUS_LABELS[h.status] || h.status}
                              </span>
                            </td>
                            <td className={styles.cellAnswer} title={h.drafted_answer || ''}>
                              {h.drafted_answer || '—'}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    </div>
                  </>
                )}
              </div>
            )}
          </div>
        </td>
      </tr>
    );
  };

  if (!puedeVer) {
    return (
      <div className={styles.container}>
        <div className={styles.errorBar}>
          <ShieldAlert size={14} />
          No tenés permiso para ver el panel del bot de preguntas.
        </div>
      </div>
    );
  }

  return (
    <div className={styles.container}>
      {/* Header */}
      <div className={styles.header}>
        <div className={styles.headerLeft}>
          <Bot size={24} />
          <h1>Bot de Preguntas ML</h1>
        </div>
        <div className={styles.headerActions}>
          {status && (
            <>
              <span className={botEnabled ? styles.botOn : styles.botOff}>
                <Power size={14} />
                {botEnabled ? 'Bot activo' : 'Bot apagado'}
              </span>
              <span className={autoPublishEnabled ? styles.botOn : styles.botOff}>
                <ShieldAlert size={14} />
                {autoPublishEnabled
                  ? 'Publicación automática: ON'
                  : 'Publicación automática: OFF — modo supervisado'}
              </span>
            </>
          )}
          {puedeEncenderApagar && (
            <>
              <button
                className="btn-tesla outline-subtle-primary sm"
                onClick={() => handleToggle(true)}
                disabled={toggling}
              >
                {toggling ? <Loader size={14} className={styles.spinning} /> : <Power size={14} />}
                Activar
              </button>
              <button
                className="btn-tesla ghost sm"
                onClick={() => handleToggle(false)}
                disabled={toggling}
              >
                <Power size={14} />
                Apagar
              </button>
            </>
          )}
          <button className="btn-tesla outline-subtle-primary sm" onClick={cargarPreguntas} disabled={loading}>
            <RefreshCcw size={14} className={loading ? styles.spinning : ''} />
            Actualizar
          </button>
        </div>
      </div>

      {/* Tabs */}
      <div className={styles.tabBar}>
        <button
          type="button"
          className={`${styles.tab} ${activeTab === 'preguntas' ? styles.tabActive : ''}`}
          onClick={() => setActiveTab('preguntas')}
        >
          <Bot size={14} />
          Preguntas
        </button>
        {puedeVerMensajes && (
          <button
            type="button"
            className={`${styles.tab} ${activeTab === 'mensajes' ? styles.tabActive : ''}`}
            onClick={() => setActiveTab('mensajes')}
          >
            <Bot size={14} />
            Mensajes
          </button>
        )}
        {puedeConfigurar && (
          <button
            type="button"
            className={`${styles.tab} ${activeTab === 'config' ? styles.tabActive : ''}`}
            onClick={() => setActiveTab('config')}
          >
            <Settings size={14} />
            Configuración
          </button>
        )}
      </div>

      {/* ====== TAB: Preguntas ====== */}
      {activeTab === 'preguntas' && (
        <>
          <div className={styles.filtersBar}>
            <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} className={styles.select}>
              <option value="">Todos los estados</option>
              {Object.entries(STATUS_LABELS).map(([value, label]) => (
                <option key={value} value={value}>{label}</option>
              ))}
            </select>
          </div>

          {error && (
            <div className={styles.errorBar}>
              <AlertTriangle size={14} />
              {error}
            </div>
          )}

          {actionError && (
            <div className={styles.errorBar}>
              <AlertTriangle size={14} />
              {actionError}
              <button
                type="button"
                className="btn-tesla ghost sm"
                onClick={() => setActionError(null)}
                aria-label="Descartar error"
              >
                ×
              </button>
            </div>
          )}

          {hasCustomColumnSizing && (
            <div className={styles.columnSizingBar}>
              <button
                type="button"
                className="btn-tesla ghost sm"
                onClick={handleResetColumnSizing}
              >
                Restablecer columnas
              </button>
            </div>
          )}

          <div className="table-container-tesla">
            <table
              className={`table-tesla striped ${styles.resizableTable}`}
              style={{ width: preguntasTable.getTotalSize() }}
            >
              <colgroup>
                {preguntasTable.getVisibleLeafColumns().map((col) => (
                  <col key={col.id} style={{ width: col.getSize() }} />
                ))}
              </colgroup>
              <thead className="table-tesla-head">
                <tr>
                  {preguntasTable.getFlatHeaders().map((h) => (
                    <th key={h.id} style={{ position: 'relative' }}>
                      {flexRender(h.column.columnDef.header, h.getContext())}
                      {h.column.getCanResize() && (
                        <span
                          className={`${styles.resizeGrip} ${h.column.getIsResizing() ? styles.resizeGripActive : ''}`}
                          onMouseDown={h.getResizeHandler()}
                          onTouchStart={h.getResizeHandler()}
                          role="separator"
                          aria-orientation="vertical"
                          aria-label={`Redimensionar columna ${h.column.columnDef.header}`}
                        />
                      )}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="table-tesla-body">
                {loading ? (
                  <tr><td colSpan={7} className={styles.loadingCell}>Cargando...</td></tr>
                ) : questions.length === 0 ? (
                  <tr><td colSpan={7} className={styles.emptyCell}>No hay preguntas para mostrar</td></tr>
                ) : (
                  questions.map((q) => {
                    const remaining = q.status === 'waiting' ? secondsRemaining(q.wait_until, now) : null;
                    return (
                      <Fragment key={q.id}>
                      <tr>
                        <td className={styles.cellQuestion} title={q.question_text}>
                          {q.question_text}
                          {q.buyer_nickname && <span className={styles.buyerNick}>{q.buyer_nickname}</span>}
                        </td>
                        <td className={styles.cellItem}>
                          {q.item_permalink && q.item_permalink.startsWith('https://') ? (
                            <a
                              href={q.item_permalink}
                              target="_blank"
                              rel="noopener noreferrer"
                              title={q.item_title || q.item_id}
                              className={styles.detailLink}
                            >
                              {q.item_title || q.item_id}
                            </a>
                          ) : (
                            (() => {
                              const fallbackLink = buildFallbackItemLink(q.item_id);
                              return fallbackLink ? (
                                <a
                                  href={fallbackLink}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  title={q.item_id}
                                  className={styles.detailLink}
                                >
                                  {q.item_id}
                                </a>
                              ) : (
                                q.item_id
                              );
                            })()
                          )}
                        </td>
                        <td>
                          <span className={`${styles.badge} ${styles[STATUS_BADGE_CLASS[q.status]] || ''}`}>
                            {STATUS_LABELS[q.status] || q.status}
                          </span>
                          {q.injection_flag && (
                            <span className={styles.injectionFlag} title="Se detectó un posible intento de manipulación en esta pregunta">
                              <ShieldAlert size={12} />
                            </span>
                          )}
                        </td>
                        <td className={styles.cellAnswer} title={q.drafted_answer || ''}>
                          {q.drafted_answer || '—'}
                        </td>
                        <td className={styles.cellCenter}>
                          {q.confidence != null ? `${Math.round(q.confidence * 100)}%` : '—'}
                        </td>
                        <td className={styles.cellCenter}>
                          {q.status === 'waiting' ? (
                            !autoPublishEnabled ? (
                              <span className={styles.countdown}>
                                <ShieldAlert size={12} />
                                esperando aprobación
                              </span>
                            ) : (
                              <span className={styles.countdown}>
                                <Clock size={12} />
                                {formatCountdown(remaining)}
                              </span>
                            )
                          ) : '—'}
                        </td>
                        <td>
                          <div className={styles.actionsCell}>
                            <button
                              className="btn-tesla ghost sm"
                              onClick={() => toggleExpand(q)}
                              title={expandedId === q.id ? 'Ocultar detalle' : 'Ver detalle completo'}
                              aria-label={expandedId === q.id ? 'Ocultar detalle' : 'Ver detalle completo'}
                              aria-expanded={expandedId === q.id}
                            >
                              {expandedId === q.id ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                            </button>
                            {puedeResponder && (
                              <>
                              {['received', 'waiting', 'pending_morning', 'failed'].includes(q.status) && (
                                <button
                                  className="btn-tesla ghost sm"
                                  onClick={() => handleTakeOver(q)}
                                  disabled={actionLoadingId === q.id}
                                  title="Tomar la pregunta"
                                  aria-label="Tomar la pregunta"
                                >
                                  <UserCheck size={14} />
                                </button>
                              )}
                              {q.status === 'taken_over' && (
                                <button
                                  className="btn-tesla outline-subtle-primary sm"
                                  onClick={() => openEdit(q)}
                                  disabled={actionLoadingId === q.id}
                                >
                                  Editar
                                </button>
                              )}
                              {['waiting', 'taken_over', 'pending_morning', 'failed'].includes(q.status) && (
                                <button
                                  className="btn-tesla outline-subtle-primary sm"
                                  onClick={() => handlePublishNow(q)}
                                  disabled={actionLoadingId === q.id || !q.drafted_answer}
                                  title={q.status === 'failed' ? 'Reintentar publicación' : 'Publicar ahora'}
                                  aria-label={q.status === 'failed' ? 'Reintentar publicación' : 'Publicar ahora'}
                                >
                                  {q.status === 'failed' ? <RotateCcw size={14} /> : <Send size={14} />}
                                </button>
                              )}
                              {['waiting', 'taken_over'].includes(q.status) && (
                                <button
                                  className="btn-tesla ghost sm"
                                  onClick={() => handleHold(q)}
                                  disabled={actionLoadingId === q.id}
                                  title="Retener para la mañana"
                                  aria-label="Retener para la mañana"
                                >
                                  <PauseCircle size={14} />
                                </button>
                              )}
                              </>
                            )}
                          </div>
                        </td>
                      </tr>
                      {expandedId === q.id && renderDetailRow(q)}
                    </Fragment>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        </>
      )}

      {/* ====== TAB: Mensajes (Phase 5, PR3 — read-only MVP) ====== */}
      {activeTab === 'mensajes' && puedeVerMensajes && (
        <>
          <div className={styles.filtersBar}>
            <input
              type="text"
              placeholder="Buscar por comprador (ID)"
              className={styles.configInput}
              value={buyerFilter}
              onChange={(e) => setBuyerFilter(e.target.value)}
            />
            <input
              type="text"
              placeholder="Pack ID"
              className={styles.configInput}
              value={packFilter}
              disabled={sinPack}
              onChange={(e) => setPackFilter(e.target.value)}
            />
            <button
              type="button"
              className={`btn-tesla sm ${sinPack ? '' : 'outline-subtle-primary'}`}
              onClick={() => setSinPack((prev) => !prev)}
              aria-pressed={sinPack}
            >
              Sin pack
            </button>
            <label className={styles.rosterEnabledLabel}>
              <input
                type="checkbox"
                checked={includeModerated}
                onChange={(e) => setIncludeModerated(e.target.checked)}
              />
              Incluir moderados
            </label>
            <label className={styles.rosterEnabledLabel}>
              <input
                type="checkbox"
                checked={hasReadFilter === 'true'}
                onChange={(e) => setHasReadFilter(e.target.checked ? 'true' : 'false')}
              />
              Leídos
            </label>
          </div>

          {messagesError && (
            <div className={styles.errorBar}>
              <AlertTriangle size={14} />
              {messagesError}
            </div>
          )}

          {msgActionError && (
            <div className={styles.errorBar}>
              <AlertTriangle size={14} />
              {msgActionError}
              <button
                type="button"
                className="btn-tesla ghost sm"
                onClick={() => setMsgActionError(null)}
                aria-label="Descartar error"
              >
                ×
              </button>
            </div>
          )}

          {hasCustomMensajesColumnSizing && (
            <div className={styles.columnSizingBar}>
              <button
                type="button"
                className="btn-tesla ghost sm"
                onClick={handleResetMensajesColumnSizing}
              >
                Restablecer columnas
              </button>
            </div>
          )}

          <div className="table-container-tesla">
            <table
              className={`table-tesla ${styles.resizableTable}`}
              style={{ width: mensajesTable.getTotalSize() }}
            >
              <colgroup>
                {mensajesTable.getVisibleLeafColumns().map((col) => (
                  <col key={col.id} style={{ width: col.getSize() }} />
                ))}
              </colgroup>
              <thead className="table-tesla-head">
                <tr>
                  {mensajesTable.getFlatHeaders().map((h) => (
                    <th key={h.id} style={{ position: 'relative' }}>
                      {flexRender(h.column.columnDef.header, h.getContext())}
                      {h.column.getCanResize() && (
                        <span
                          className={`${styles.resizeGrip} ${h.column.getIsResizing() ? styles.resizeGripActive : ''}`}
                          onMouseDown={h.getResizeHandler()}
                          onTouchStart={h.getResizeHandler()}
                          role="separator"
                          aria-orientation="vertical"
                          aria-label={`Redimensionar columna ${h.column.columnDef.header}`}
                        />
                      )}
                    </th>
                  ))}
                </tr>
              </thead>
              {messagesLoading ? (
                <tbody className="table-tesla-body">
                  <tr><td colSpan={5} className={styles.loadingCell}>Cargando...</td></tr>
                </tbody>
              ) : messageThreads.length === 0 ? (
                <tbody className="table-tesla-body">
                  <tr><td colSpan={5} className={styles.emptyCell}>No hay mensajes para mostrar</td></tr>
                </tbody>
              ) : (
                messageThreads.map((thread) => {
                  const anchor = thread.anchorMessage;
                  const canTakeOver = anchor && MESSAGE_TAKE_OVER_STATES.includes(anchor.bot_status);
                  const canRespond = anchor?.bot_status === 'taken_over';
                  return (
                  <tbody key={thread.key} className={`table-tesla-body ${styles.threadGroup}`}>
                    <tr className={styles.threadHeader}>
                      <td colSpan={5}>
                        <div className={styles.threadHeaderRow}>
                          <div className={styles.threadHeaderInfo}>
                            <button
                              type="button"
                              className="btn-tesla ghost sm"
                              onClick={() => toggleThreadDetail(thread.key)}
                              title={expandedThreadKey === thread.key ? 'Ocultar detalle' : 'Ver detalle completo'}
                              aria-label={expandedThreadKey === thread.key ? 'Ocultar detalle' : 'Ver detalle completo'}
                              aria-expanded={expandedThreadKey === thread.key}
                            >
                              {expandedThreadKey === thread.key ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                            </button>
                            <span className={styles.threadBuyer}>
                              {thread.buyer_nickname || thread.buyer_id || 'comprador desconocido'}
                            </span>
                            <span className={styles.threadSeparator}>·</span>
                            <span className={styles.threadPack}>
                              {thread.pack_id ? `pack ${thread.pack_id}` : 'sin pack'}
                            </span>
                            <span className={styles.threadSeparator}>·</span>
                            <span className={styles.threadCount}>
                              {thread.messages.length} mensaje{thread.messages.length === 1 ? '' : 's'}
                            </span>
                            {anchor?.bot_status && (
                              <span className={`${styles.badge} ${styles[MESSAGE_BOT_STATUS_BADGE_CLASS[anchor.bot_status]] || ''}`}>
                                {MESSAGE_BOT_STATUS_LABELS[anchor.bot_status] || anchor.bot_status}
                              </span>
                            )}
                            {anchor?.bot_status === 'failed' && anchor?.last_error && (
                              <span className={styles.threadErrorText} title={anchor.last_error}>
                                {anchor.last_error}
                              </span>
                            )}
                          </div>
                          {puedeResponderMensajes && (canTakeOver || canRespond) && (
                            <div className={styles.actionsCell}>
                              {canTakeOver && (
                                <button
                                  className="btn-tesla ghost sm"
                                  onClick={() => handleTakeOverMessage(anchor)}
                                  disabled={msgActionLoadingId === anchor.id}
                                  title="Tomar el mensaje"
                                  aria-label="Tomar el mensaje"
                                >
                                  <UserCheck size={14} />
                                </button>
                              )}
                              {canRespond && (
                                <>
                                  <button
                                    className="btn-tesla outline-subtle-primary sm"
                                    onClick={() => openMessageEdit(anchor)}
                                    disabled={msgActionLoadingId === anchor.id}
                                  >
                                    Editar
                                  </button>
                                  <button
                                    className="btn-tesla sm"
                                    onClick={() => handleSendMessage(anchor)}
                                    disabled={msgActionLoadingId === anchor.id || !anchor.drafted_answer}
                                    title="Enviar respuesta"
                                    aria-label="Enviar respuesta"
                                  >
                                    <Send size={14} />
                                  </button>
                                </>
                              )}
                            </div>
                          )}
                        </div>
                      </td>
                    </tr>
                    {thread.messages.map((m) => (
                      <tr key={m.id} className={styles.threadRow}>
                        <td className={styles.threadRowIndent} aria-hidden="true" />
                        <td className={styles.cellQuestion} title={m.text}>{m.text}</td>
                        <td>{m.received_at ? new Date(m.received_at).toLocaleString() : '—'}</td>
                        <td>{m.read_at ? new Date(m.read_at).toLocaleString() : '—'}</td>
                        <td>
                          {m.moderation_status && m.moderation_status !== 'clean' ? (
                            <span className={`${styles.badge} ${styles.badgeWarning}`}>
                              {MESSAGE_STATUS_LABELS[m.moderation_status] || m.moderation_status}
                            </span>
                          ) : '—'}
                        </td>
                      </tr>
                    ))}
                    {expandedThreadKey === thread.key && renderMessageDetailRow(thread)}
                  </tbody>
                  );
                })
              )}
            </table>
          </div>
        </>
      )}

      {/* ====== TAB: Configuración ====== */}
      {activeTab === 'config' && puedeConfigurar && (
        <div className={styles.configSection}>
          {configError && (
            <div className={styles.errorBar}>
              <AlertTriangle size={14} />
              {configError}
            </div>
          )}

          <h2 className={styles.sectionTitle}>Variables de negocio</h2>
          {configLoading ? (
            <div className={styles.loadingCell}>Cargando...</div>
          ) : (
            <div className="table-container-tesla">
              <table className="table-tesla striped">
                <thead className="table-tesla-head">
                  <tr>
                    <th>Clave</th>
                    <th>Valor</th>
                    <th>Descripción</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody className="table-tesla-body">
                  {configItems.map((item) => (
                    <tr key={item.clave}>
                      <td className={styles.cellClave}>{item.clave}</td>
                      <td>
                        {item.clave === LLM_ROSTER_CONFIG_KEY ? (
                          <LlmProviderRosterEditor
                            value={configDrafts[item.clave] ?? ''}
                            onChange={(next) => setConfigDrafts((prev) => ({ ...prev, [item.clave]: next }))}
                          />
                        ) : (
                          <input
                            type="text"
                            className={styles.configInput}
                            value={configDrafts[item.clave] ?? ''}
                            onChange={(e) => setConfigDrafts((prev) => ({ ...prev, [item.clave]: e.target.value }))}
                          />
                        )}
                      </td>
                      <td className={styles.cellDescripcion}>{item.descripcion || '—'}</td>
                      <td>
                        <button
                          className="btn-tesla outline-subtle-primary sm"
                          onClick={() => handleConfigSave(item.clave)}
                          disabled={savingClave === item.clave || configDrafts[item.clave] === item.valor}
                        >
                          {savingClave === item.clave ? <Loader size={14} className={styles.spinning} /> : 'Guardar'}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <h2 className={styles.sectionTitle}>Ejemplos de tono (few-shot)</h2>
          {examplesLoading ? (
            <div className={styles.loadingCell}>Cargando...</div>
          ) : (
            <>
              <div className="table-container-tesla">
                <table className="table-tesla striped">
                  <thead className="table-tesla-head">
                    <tr>
                      <th>Pregunta ejemplo</th>
                      <th>Respuesta ejemplo</th>
                      <th>Categoría</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody className="table-tesla-body">
                    {examples.map((ex) => (
                      <tr key={ex.id}>
                        <td className={styles.cellMotivo}>{ex.question_example}</td>
                        <td className={styles.cellMotivo}>{ex.answer_example}</td>
                        <td>{ex.category || '—'}</td>
                        <td>
                          <button className="btn-tesla ghost sm" onClick={() => handleDeleteExample(ex.id)} title="Eliminar" aria-label="Eliminar ejemplo">
                            <Trash2 size={14} />
                          </button>
                        </td>
                      </tr>
                    ))}
                    {examples.length === 0 && (
                      <tr><td colSpan={4} className={styles.emptyCell}>No hay ejemplos cargados</td></tr>
                    )}
                  </tbody>
                </table>
              </div>

              <div className={styles.newExampleForm}>
                <input
                  type="text"
                  placeholder="Pregunta ejemplo"
                  className={styles.configInput}
                  value={newExample.question_example}
                  onChange={(e) => setNewExample((prev) => ({ ...prev, question_example: e.target.value }))}
                />
                <input
                  type="text"
                  placeholder="Respuesta ejemplo"
                  className={styles.configInput}
                  value={newExample.answer_example}
                  onChange={(e) => setNewExample((prev) => ({ ...prev, answer_example: e.target.value }))}
                />
                <input
                  type="text"
                  placeholder="Categoría (opcional)"
                  className={styles.configInput}
                  value={newExample.category}
                  onChange={(e) => setNewExample((prev) => ({ ...prev, category: e.target.value }))}
                />
                <button className="btn-tesla outline-subtle-primary sm" onClick={handleCreateExample} disabled={savingExample}>
                  <Plus size={14} />
                  Agregar
                </button>
              </div>
            </>
          )}
        </div>
      )}

      {/* Edit / publish modal */}
      <ModalTesla
        isOpen={editQuestion !== null}
        title={editQuestion ? `Editar respuesta — pregunta #${editQuestion.id}` : ''}
        onClose={closeEdit}
        closeOnOverlay
        size="md"
      >
        {editQuestion && (
          <div className={styles.editBody}>
            <p className={styles.editQuestionText}>{editQuestion.question_text}</p>
            <textarea
              className={styles.editTextarea}
              rows={6}
              value={editText}
              onChange={(e) => setEditText(e.target.value)}
              maxLength={2000}
            />
            {softWarning && (
              <div className={styles.softWarning}>
                <AlertTriangle size={14} />
                {softWarning}
              </div>
            )}
            {actionError && (
              <div className={styles.errorBar}>
                <AlertTriangle size={14} />
                {actionError}
              </div>
            )}
            <div className={styles.editActions}>
              <button className="btn-tesla ghost sm" onClick={closeEdit} disabled={actionLoadingId === editQuestion.id}>
                Cancelar
              </button>
              <button
                className="btn-tesla outline-subtle-primary sm"
                onClick={handleSaveAnswer}
                disabled={actionLoadingId === editQuestion.id || !editText.trim()}
              >
                Guardar borrador
              </button>
              <button
                className="btn-tesla sm"
                onClick={handleSaveAndPublish}
                disabled={actionLoadingId === editQuestion.id || !editText.trim()}
              >
                <Send size={14} />
                Guardar y publicar
              </button>
            </div>
          </div>
        )}
      </ModalTesla>

      {/* Message edit modal (Mensajes tab, Phase A PR3) */}
      <ModalTesla
        isOpen={editMessage !== null}
        title={editMessage ? `Editar respuesta — mensaje #${editMessage.id}` : ''}
        onClose={closeMessageEdit}
        closeOnOverlay
        size="md"
      >
        {editMessage && (
          <div className={styles.editBody}>
            <p className={styles.editQuestionText}>{editMessage.text}</p>
            <textarea
              className={styles.editTextarea}
              rows={6}
              value={editMessageText}
              onChange={(e) => setEditMessageText(e.target.value)}
              maxLength={2000}
            />
            {messageSoftWarning && (
              <div className={styles.softWarning}>
                <AlertTriangle size={14} />
                {messageSoftWarning}
              </div>
            )}
            {msgActionError && (
              <div className={styles.errorBar}>
                <AlertTriangle size={14} />
                {msgActionError}
              </div>
            )}
            <div className={styles.editActions}>
              <button className="btn-tesla ghost sm" onClick={closeMessageEdit} disabled={msgActionLoadingId === editMessage.id}>
                Cancelar
              </button>
              <button
                className="btn-tesla outline-subtle-primary sm"
                onClick={handleSaveMessageAnswer}
                disabled={msgActionLoadingId === editMessage.id || !editMessageText.trim()}
              >
                Guardar borrador
              </button>
            </div>
          </div>
        )}
      </ModalTesla>
    </div>
  );
}
