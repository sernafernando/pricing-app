/**
 * MLQuestions — Panel for the MercadoLibre pre-sale questions bot.
 *
 * Shows a live list of `ml_bot_questions` (SSE-driven reload, REST refetch
 * per ADR-8), lets a human take over / edit / publish-now / hold a question,
 * toggles the bot on/off, and exposes the business-knowledge config +
 * few-shot examples editors. Every action is also enforced backend-side —
 * this page only hides/disables UI, it never trusts itself for authz.
 */

import { useState, useEffect, useCallback, useMemo } from 'react';
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
} from 'lucide-react';
import styles from './MLQuestions.module.css';

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

  const cargarPreguntas = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = { limit: 100 };
      if (statusFilter) params.status = statusFilter;
      const { data } = await api.get('/ml-bot/questions', { params });
      setQuestions(data.questions);
    } catch {
      setQuestions([]);
      setError('Error al cargar preguntas');
    } finally {
      setLoading(false);
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
    if (puedeVer) cargarPreguntas();
  }, [cargarPreguntas, puedeVer]);

  useEffect(() => {
    if (activeTab === 'config') {
      cargarConfig();
      cargarExamples();
    }
  }, [activeTab, cargarConfig, cargarExamples]);

  // SSE-driven reload: instant panel update on any bot state transition.
  const reloadFromSSE = useCallback(() => {
    if (puedeVer) cargarPreguntas();
    if (activeTab === 'config') {
      cargarConfig();
      cargarExamples();
    }
  }, [puedeVer, cargarPreguntas, activeTab, cargarConfig, cargarExamples]);

  useSSEChannel('ml_bot:questions', reloadFromSSE);

  // Live countdown ticker (client-side only, server remains source of truth
  // via wait_until — a page refresh always re-syncs).
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  const botEnabledItem = useMemo(
    () => configItems.find((item) => item.clave === 'bot_enabled'),
    [configItems],
  );

  // Supervised-mode indicator (trial period): `auto_publish_enabled` is
  // absent/empty/malformed => supervised (fail-safe default), mirroring the
  // backend's fail-safe read. Same visibility limitation as botEnabledItem
  // above — only ml_bot.config holders get the config list at all.
  const autoPublishItem = useMemo(
    () => configItems.find((item) => item.clave === 'auto_publish_enabled'),
    [configItems],
  );
  const autoPublishEnabled = autoPublishItem?.valor === 'true';

  const handleToggle = async (enabled) => {
    setToggling(true);
    try {
      await api.post('/ml-bot/toggle', { enabled });
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
          {puedeEncenderApagar && (
            <>
              {puedeConfigurar && botEnabledItem && (
                <span className={botEnabledItem.valor === 'true' ? styles.botOn : styles.botOff}>
                  <Power size={14} />
                  {botEnabledItem.valor === 'true' ? 'Bot activo' : 'Bot apagado'}
                </span>
              )}
              {puedeConfigurar && (
                <span className={autoPublishEnabled ? styles.botOn : styles.botOff}>
                  <ShieldAlert size={14} />
                  {autoPublishEnabled
                    ? 'Publicación automática: ON'
                    : 'Publicación automática: OFF — modo supervisado'}
                </span>
              )}
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
                      <tr key={q.id}>
                        <td className={styles.cellQuestion} title={q.question_text}>
                          {q.question_text}
                          {q.buyer_nickname && <span className={styles.buyerNick}>{q.buyer_nickname}</span>}
                        </td>
                        <td className={styles.cellItem}>{q.item_id}</td>
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
                            puedeConfigurar && !autoPublishEnabled ? (
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
                          {puedeResponder && (
                            <div className={styles.actionsCell}>
                              {['waiting', 'pending_morning', 'failed'].includes(q.status) && (
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
                            </div>
                          )}
                        </td>
                      </tr>
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
