import { useState, useEffect, useCallback, useRef } from 'react';
import { usePermisos } from '../contexts/PermisosContext';
import { useSSEChannel } from '../hooks/useSSEChannel';
import { ticketsAPI, sectoresAPI } from '../services/api';
import {
  X,
  MessageSquare,
  Clock,
  Paperclip,
  Download,
  Trash2,
  Upload,
  Send,
  UserPlus,
  ArrowRightCircle,
} from 'lucide-react';
import styles from './TicketDetail.module.css';

const PRIORIDAD_CLASS = {
  baja: 'prioridadBaja',
  media: 'prioridadMedia',
  alta: 'prioridadAlta',
  critica: 'prioridadCritica',
};

const formatDate = (dateStr) => {
  if (!dateStr) return '-';
  const d = new Date(dateStr);
  return d.toLocaleDateString('es-AR', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
};

const formatFileSize = (bytes) => {
  if (!bytes) return '-';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
};

/**
 * Picks a button CSS class based on the destination state semantics.
 *
 * Priority: es_final with negative name → danger, es_final → success,
 * then maps hex color to the closest Tesla outline-subtle variant,
 * falls back to default (primary).
 */
const NEGATIVE_CODES = ['rechazado', 'cancelado', 'cerrado_sin_resolver', 'descartado'];
const COLOR_TO_VARIANT = {
  '#ef4444': 'btnTransitionDanger',
  '#f87171': 'btnTransitionDanger',
  '#dc2626': 'btnTransitionDanger',
  '#22c55e': 'btnTransitionSuccess',
  '#10b981': 'btnTransitionSuccess',
  '#16a34a': 'btnTransitionSuccess',
  '#f59e0b': 'btnTransitionWarning',
  '#eab308': 'btnTransitionWarning',
  '#f97316': 'btnTransitionWarning',
  '#3b82f6': 'btnTransitionInfo',
  '#6366f1': 'btnTransitionPurple',
  '#8b5cf6': 'btnTransitionPurple',
  '#a855f7': 'btnTransitionPurple',
};

const getTransitionBtnClass = (trans) => {
  const dest = trans.estado_destino;
  if (!dest) return styles.btnTransition;

  const codigo = (dest.codigo || '').toLowerCase();

  // Final + negative name → danger (red)
  if (dest.es_final && NEGATIVE_CODES.some((neg) => codigo.includes(neg))) {
    return styles.btnTransitionDanger;
  }

  // Final state (resolved, approved, etc.) → success (green)
  if (dest.es_final) {
    return styles.btnTransitionSuccess;
  }

  // Map by hex color if available
  if (dest.color) {
    const match = COLOR_TO_VARIANT[dest.color.toLowerCase()];
    if (match) return styles[match];
  }

  // Default → primary (blue)
  return styles.btnTransition;
};

export default function TicketDetail({ ticketId, onClose, onTicketChanged }) {
  const { tienePermiso } = usePermisos();
  const puedeGestionar = tienePermiso('tickets.gestionar');
  const fileInputRef = useRef(null);

  // Ticket data
  const [ticket, setTicket] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Workflow data (for transitions)
  const [workflows, setWorkflows] = useState([]);

  // Tabs
  const [activeTab, setActiveTab] = useState('comentarios');

  // Comments
  const [comentarios, setComentarios] = useState([]);
  const [loadingComentarios, setLoadingComentarios] = useState(false);
  const [commentText, setCommentText] = useState('');
  const [commentInternal, setCommentInternal] = useState(false);
  const [sendingComment, setSendingComment] = useState(false);
  const [commentError, setCommentError] = useState(null);

  // History
  const [historial, setHistorial] = useState([]);
  const [loadingHistorial, setLoadingHistorial] = useState(false);

  // Attachments
  const [adjuntos, setAdjuntos] = useState([]);
  const [loadingAdjuntos, setLoadingAdjuntos] = useState(false);
  const [uploadingFile, setUploadingFile] = useState(false);
  const [adjuntoError, setAdjuntoError] = useState(null);

  // Assign
  const [sectorUsuarios, setSectorUsuarios] = useState([]);
  const [assignUserId, setAssignUserId] = useState('');
  const [assigning, setAssigning] = useState(false);

  // Transition
  const [transitioning, setTransitioning] = useState(false);
  const [transitionError, setTransitionError] = useState(null);

  // Fetch ticket
  const fetchTicket = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const { data } = await ticketsAPI.obtener(ticketId);
      setTicket(data);

      // Mark as reviewed
      try {
        await ticketsAPI.marcarRevisado(ticketId);
      } catch {
        // Non-blocking
      }
    } catch {
      setError('Error al cargar el ticket');
    } finally {
      setLoading(false);
    }
  }, [ticketId]);

  useEffect(() => {
    fetchTicket();
  }, [fetchTicket]);

  // Load workflows for transitions when ticket loads
  useEffect(() => {
    if (!ticket?.sector?.id || !puedeGestionar) return;
    const fetchWorkflows = async () => {
      try {
        const { data } = await sectoresAPI.listarWorkflows(ticket.sector.id);
        setWorkflows(Array.isArray(data) ? data : []);
      } catch {
        setWorkflows([]);
      }
    };
    fetchWorkflows();
  }, [ticket?.sector?.id, puedeGestionar]);

  // Load sector users for assignment
  useEffect(() => {
    if (!ticket?.sector?.id || !puedeGestionar) return;
    const fetchUsers = async () => {
      try {
        const { data } = await sectoresAPI.listarUsuarios(ticket.sector.id);
        setSectorUsuarios(Array.isArray(data) ? data : []);
      } catch {
        setSectorUsuarios([]);
      }
    };
    fetchUsers();
  }, [ticket?.sector?.id, puedeGestionar]);

  // Load tab data
  useEffect(() => {
    if (!ticketId) return;

    if (activeTab === 'comentarios') {
      setLoadingComentarios(true);
      ticketsAPI.listarComentarios(ticketId)
        .then(({ data }) => setComentarios(Array.isArray(data) ? data : []))
        .catch(() => setComentarios([]))
        .finally(() => setLoadingComentarios(false));
    } else if (activeTab === 'historial') {
      setLoadingHistorial(true);
      ticketsAPI.obtenerHistorial(ticketId)
        .then(({ data }) => setHistorial(Array.isArray(data) ? data : []))
        .catch(() => setHistorial([]))
        .finally(() => setLoadingHistorial(false));
    } else if (activeTab === 'adjuntos') {
      setLoadingAdjuntos(true);
      ticketsAPI.listarAdjuntos(ticketId)
        .then(({ data }) => setAdjuntos(Array.isArray(data) ? data : []))
        .catch(() => setAdjuntos([]))
        .finally(() => setLoadingAdjuntos(false));
    }
  }, [ticketId, activeTab]);

  // SSE
  useSSEChannel('tickets:changed', () => {
    fetchTicket();
    if (activeTab === 'comentarios') {
      ticketsAPI.listarComentarios(ticketId)
        .then(({ data }) => setComentarios(Array.isArray(data) ? data : []))
        .catch(() => {});
    }
  });

  // Compute available transitions
  const getAvailableTransitions = () => {
    if (!ticket?.estado?.id || workflows.length === 0) return [];
    const transitions = [];
    for (const wf of workflows) {
      for (const trans of (wf.transiciones || [])) {
        if (trans.estado_origen_id === ticket.estado.id) {
          transitions.push(trans);
        }
      }
    }
    return transitions;
  };

  const availableTransitions = getAvailableTransitions();

  // Handlers
  const handleTransition = async (transicion) => {
    setTransitioning(true);
    setTransitionError(null);
    try {
      await ticketsAPI.transicion(ticketId, {
        nuevo_estado_id: transicion.estado_destino_id,
      });
      await fetchTicket();
      onTicketChanged?.();
    } catch (err) {
      setTransitionError(err.response?.data?.detail || 'Error en la transición');
    } finally {
      setTransitioning(false);
    }
  };

  const handleAssign = async () => {
    if (!assignUserId) return;
    setAssigning(true);
    try {
      await ticketsAPI.asignar(ticketId, { usuario_id: parseInt(assignUserId, 10) });
      setAssignUserId('');
      await fetchTicket();
      onTicketChanged?.();
    } catch {
      // Error handled silently
    } finally {
      setAssigning(false);
    }
  };

  const handleSendComment = async () => {
    if (!commentText.trim()) return;
    setSendingComment(true);
    setCommentError(null);
    try {
      await ticketsAPI.agregarComentario(ticketId, {
        contenido: commentText.trim(),
        es_interno: commentInternal,
      });
      setCommentText('');
      setCommentInternal(false);
      const { data } = await ticketsAPI.listarComentarios(ticketId);
      setComentarios(Array.isArray(data) ? data : []);
    } catch (err) {
      setCommentError(err.response?.data?.detail || 'Error al enviar comentario');
    } finally {
      setSendingComment(false);
    }
  };

  const handleDownload = async (adjunto) => {
    try {
      const { data } = await ticketsAPI.descargarAdjunto(ticketId, adjunto.id);
      const url = window.URL.createObjectURL(data);
      const link = document.createElement('a');
      link.href = url;
      link.download = adjunto.nombre_archivo;
      link.click();
      window.URL.revokeObjectURL(url);
    } catch {
      setAdjuntoError('Error al descargar');
    }
  };

  const handleDeleteAdjunto = async (adjuntoId) => {
    setAdjuntoError(null);
    try {
      await ticketsAPI.eliminarAdjunto(ticketId, adjuntoId);
      const { data } = await ticketsAPI.listarAdjuntos(ticketId);
      setAdjuntos(Array.isArray(data) ? data : []);
    } catch (err) {
      setAdjuntoError(err.response?.data?.detail || 'Error al eliminar');
    }
  };

  const handleUploadFile = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploadingFile(true);
    setAdjuntoError(null);
    try {
      await ticketsAPI.subirAdjunto(ticketId, file);
      const { data } = await ticketsAPI.listarAdjuntos(ticketId);
      setAdjuntos(Array.isArray(data) ? data : []);
    } catch (err) {
      setAdjuntoError(err.response?.data?.detail || 'Error al subir archivo');
    } finally {
      setUploadingFile(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  const getStatusStyle = (estado) => {
    const color = estado?.color || '#6b7280';
    return { background: `${color}20`, color };
  };

  if (loading) {
    return (
      <div className={styles.container}>
        <div className={styles.loading}>Cargando ticket...</div>
      </div>
    );
  }

  if (error || !ticket) {
    return (
      <div className={styles.container}>
        <div className={styles.error}>{error || 'Ticket no encontrado'}</div>
      </div>
    );
  }

  const metadataEntries = Object.entries(ticket.metadata || {});

  return (
    <div className={styles.container}>
      {/* Header */}
      <div className={styles.header}>
        <div className={styles.headerLeft}>
          <div className={styles.headerRow}>
            <span className={styles.ticketNumber}>#{ticket.id}</span>
            <span
              className={styles.statusBadge}
              style={getStatusStyle(ticket.estado)}
            >
              {ticket.estado?.nombre}
            </span>
            <span className={`${styles.prioridadBadge} ${styles[PRIORIDAD_CLASS[ticket.prioridad]] || ''}`}>
              {ticket.prioridad}
            </span>
          </div>
          <h3 className={styles.ticketTitle}>{ticket.titulo}</h3>
        </div>
        <button className={styles.btnClose} onClick={onClose} aria-label="Cerrar detalle">
          <X size={16} />
        </button>
      </div>

      {/* Info grid */}
      <div className={styles.infoGrid}>
        <div className={styles.infoItem}>
          <span className={styles.infoLabel}>Sector</span>
          <span className={styles.infoValue}>{ticket.sector?.nombre || '-'}</span>
        </div>
        <div className={styles.infoItem}>
          <span className={styles.infoLabel}>Tipo</span>
          <span className={styles.infoValue}>{ticket.tipo_ticket?.nombre || '-'}</span>
        </div>
        <div className={styles.infoItem}>
          <span className={styles.infoLabel}>Creador</span>
          <span className={styles.infoValue}>{ticket.creador?.nombre || '-'}</span>
        </div>
        <div className={styles.infoItem}>
          <span className={styles.infoLabel}>Asignado a</span>
          <span className={styles.infoValue}>{ticket.asignado_a?.nombre || 'Sin asignar'}</span>
        </div>
        <div className={styles.infoItem}>
          <span className={styles.infoLabel}>Creado</span>
          <span className={styles.infoValue}>{formatDate(ticket.created_at)}</span>
        </div>
        <div className={styles.infoItem}>
          <span className={styles.infoLabel}>Cerrado</span>
          <span className={styles.infoValue}>{ticket.closed_at ? formatDate(ticket.closed_at) : '-'}</span>
        </div>
      </div>

      {/* Metadata fields */}
      {metadataEntries.length > 0 && (
        <div className={styles.metadataSection}>
          <div className={styles.metadataTitle}>Campos adicionales</div>
          <div className={styles.metadataGrid}>
            {metadataEntries.map(([key, value]) => (
              <div key={key} className={styles.metadataItem}>
                <span className={styles.metadataKey}>{key}:</span>
                <span className={styles.metadataValue}>
                  {typeof value === 'boolean' ? (value ? 'Sí' : 'No') : String(value ?? '-')}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Action bar (gestionar users only) */}
      {puedeGestionar && !ticket.esta_cerrado && (
        <div className={styles.actionBar}>
          {/* Transition buttons */}
          {availableTransitions.map((trans) => (
            <button
              key={trans.id}
              className={getTransitionBtnClass(trans)}
              onClick={() => handleTransition(trans)}
              disabled={transitioning}
              title={trans.descripcion || ''}
            >
              <ArrowRightCircle size={14} />
              {trans.estado_destino?.nombre || trans.nombre || 'Transicionar'}
            </button>
          ))}

          {/* Assign dropdown */}
          <select
            className={styles.assignSelect}
            value={assignUserId}
            onChange={(e) => setAssignUserId(e.target.value)}
          >
            <option value="">Asignar a...</option>
            {sectorUsuarios.map((su) => (
              <option key={su.usuario?.id || su.id} value={su.usuario?.id || su.id}>
                {su.usuario?.nombre || '-'}
              </option>
            ))}
          </select>
          {assignUserId && (
            <button
              className={styles.btnAssign}
              onClick={handleAssign}
              disabled={assigning}
            >
              <UserPlus size={14} />
              {assigning ? '...' : 'Asignar'}
            </button>
          )}

          {transitionError && (
            <span className={styles.inlineError}>{transitionError}</span>
          )}
        </div>
      )}

      {/* Tabs */}
      <div className={styles.tabs}>
        <button
          className={`${styles.tab} ${activeTab === 'comentarios' ? styles.tabActive : ''}`}
          onClick={() => setActiveTab('comentarios')}
        >
          <MessageSquare size={14} />
          Comentarios
          {comentarios.length > 0 && (
            <span className={styles.tabBadge}>{comentarios.length}</span>
          )}
        </button>
        <button
          className={`${styles.tab} ${activeTab === 'historial' ? styles.tabActive : ''}`}
          onClick={() => setActiveTab('historial')}
        >
          <Clock size={14} />
          Historial
        </button>
        <button
          className={`${styles.tab} ${activeTab === 'adjuntos' ? styles.tabActive : ''}`}
          onClick={() => setActiveTab('adjuntos')}
        >
          <Paperclip size={14} />
          Adjuntos
          {adjuntos.length > 0 && (
            <span className={styles.tabBadge}>{adjuntos.length}</span>
          )}
        </button>
      </div>

      {/* Tab content */}
      <div className={styles.tabContent}>
        {/* Comentarios tab */}
        {activeTab === 'comentarios' && (
          <>
            {loadingComentarios ? (
              <div className={styles.empty}>Cargando comentarios...</div>
            ) : comentarios.length === 0 ? (
              <div className={styles.empty}>Sin comentarios</div>
            ) : (
              <div className={styles.commentsList}>
                {comentarios.map((c) => (
                  <div
                    key={c.id}
                    className={`${styles.comment} ${c.es_interno ? styles.commentInternal : ''}`}
                  >
                    <div className={styles.commentHeader}>
                      <span className={styles.commentAuthor}>
                        {c.usuario?.nombre || 'Sistema'}
                        {c.es_interno && (
                          <span className={styles.internalLabel}> (interno)</span>
                        )}
                      </span>
                      <span className={styles.commentDate}>
                        {formatDate(c.created_at)}
                      </span>
                    </div>
                    <div className={styles.commentBody}>{c.contenido}</div>
                  </div>
                ))}
              </div>
            )}

            {/* Comment form */}
            <div className={styles.commentForm}>
              <textarea
                className={styles.textarea}
                value={commentText}
                onChange={(e) => setCommentText(e.target.value)}
                placeholder="Escribir comentario..."
                rows={2}
              />
              <div className={styles.commentFormActions}>
                {puedeGestionar && (
                  <label className={styles.checkboxGroup}>
                    <input
                      type="checkbox"
                      checked={commentInternal}
                      onChange={(e) => setCommentInternal(e.target.checked)}
                    />
                    Interno (solo equipo)
                  </label>
                )}
                <button
                  className={styles.btnComment}
                  onClick={handleSendComment}
                  disabled={sendingComment || !commentText.trim()}
                >
                  <Send size={14} />
                  {sendingComment ? 'Enviando...' : 'Enviar'}
                </button>
              </div>
              {commentError && (
                <span className={styles.inlineError}>{commentError}</span>
              )}
            </div>
          </>
        )}

        {/* Historial tab */}
        {activeTab === 'historial' && (
          <>
            {loadingHistorial ? (
              <div className={styles.empty}>Cargando historial...</div>
            ) : historial.length === 0 ? (
              <div className={styles.empty}>Sin historial</div>
            ) : (
              <div className={styles.timeline}>
                {historial.map((h) => (
                  <div key={h.id} className={styles.historyItem}>
                    <div className={styles.historyDot} />
                    <div className={styles.historyContent}>
                      <div className={styles.historyAction}>
                        {h.descripcion || h.accion}
                      </div>
                      <div className={styles.historyMeta}>
                        <span>{h.usuario?.nombre || 'Sistema'}</span>
                        <span>{formatDate(h.fecha)}</span>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </>
        )}

        {/* Adjuntos tab */}
        {activeTab === 'adjuntos' && (
          <>
            {adjuntoError && (
              <div className={styles.inlineError}>{adjuntoError}</div>
            )}
            {loadingAdjuntos ? (
              <div className={styles.empty}>Cargando adjuntos...</div>
            ) : adjuntos.length === 0 ? (
              <div className={styles.empty}>Sin adjuntos</div>
            ) : (
              <div className={styles.attachmentsList}>
                {adjuntos.map((a) => (
                  <div key={a.id} className={styles.attachment}>
                    <div className={styles.attachmentInfo}>
                      <Paperclip size={14} />
                      <span className={styles.attachmentName}>{a.nombre_archivo}</span>
                      <span className={styles.attachmentSize}>{formatFileSize(a.tamano_bytes)}</span>
                    </div>
                    <div className={styles.attachmentActions}>
                      <button
                        className={styles.btnDownload}
                        onClick={() => handleDownload(a)}
                        aria-label="Descargar"
                      >
                        <Download size={14} />
                      </button>
                      {puedeGestionar && (
                        <button
                          className={styles.btnDelete}
                          onClick={() => handleDeleteAdjunto(a.id)}
                          aria-label="Eliminar"
                        >
                          <Trash2 size={14} />
                        </button>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}

            {/* Upload button */}
            <input
              ref={fileInputRef}
              type="file"
              accept="image/*,application/pdf"
              onChange={handleUploadFile}
              className={styles.fileInput}
            />
            <button
              className={styles.btnUpload}
              onClick={() => fileInputRef.current?.click()}
              disabled={uploadingFile}
            >
              <Upload size={14} />
              {uploadingFile ? 'Subiendo...' : 'Subir adjunto'}
            </button>
          </>
        )}
      </div>
    </div>
  );
}
