/**
 * MLQuestions — Panel for the MercadoLibre pre-sale questions bot.
 *
 * Shows a live list of `ml_bot_questions` (SSE-driven reload, REST refetch
 * per ADR-8), lets a human take over / edit / publish-now / hold a question,
 * toggles the bot on/off, and exposes the business-knowledge config +
 * few-shot examples editors. Every action is also enforced backend-side —
 * this page only hides/disables UI, it never trusts itself for authz.
 */

import { useState, useEffect, useCallback, useRef, Fragment } from 'react';
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
                <div>
                  <strong>Publicación</strong>
                  <p>
                    {itemLink ? (
                      <a href={itemLink} target="_blank" rel="noopener noreferrer">
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
                  <div className="table-container-tesla">
                    <table className="table-tesla striped">
                      <thead className="table-tesla-head">
                        <tr>
                          <th>Fecha</th>
                          <th>Pregunta</th>
                          <th>Item</th>
                          <th>Estado</th>
                          <th>Respuesta</th>
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

          <div className="table-container-tesla">
            <table className="table-tesla striped">
              <thead className="table-tesla-head">
                <tr>
                  <th>Pregunta</th>
                  <th>Item</th>
                  <th>Estado</th>
                  <th>Respuesta (borrador)</th>
                  <th>Confianza</th>
                  <th>Cuenta regresiva</th>
                  <th>Acciones</th>
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
                            >
                              {q.item_title || q.item_id}
                            </a>
                          ) : (
                            (() => {
                              const fallbackLink = buildFallbackItemLink(q.item_id);
                              return fallbackLink ? (
                                <a href={fallbackLink} target="_blank" rel="noopener noreferrer" title={q.item_id}>
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
                        <input
                          type="text"
                          className={styles.configInput}
                          value={configDrafts[item.clave] ?? ''}
                          onChange={(e) => setConfigDrafts((prev) => ({ ...prev, [item.clave]: e.target.value }))}
                        />
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
    </div>
  );
}
