import { useState, useEffect, useCallback } from 'react';
import { sectoresAPI, workflowsAPI } from '../services/api';
import {
  Plus,
  X,
  Save,
  GitBranch,
  ArrowRight,
  CircleDot,
  Flag,
  Lock,
} from 'lucide-react';
import styles from './WorkflowEditor.module.css';

const INITIAL_ESTADO = {
  codigo: '',
  nombre: '',
  descripcion: '',
  orden: 0,
  color: '#6b7280',
  es_inicial: false,
  es_final: false,
};

const INITIAL_TRANSICION = {
  estado_origen_id: '',
  estado_destino_id: '',
  nombre: '',
  descripcion: '',
  requiere_permiso: '',
  solo_asignado: false,
  solo_creador: false,
};

const INITIAL_WORKFLOW = {
  nombre: '',
  descripcion: '',
  es_default: false,
};

export default function WorkflowEditor() {
  const [sectores, setSectores] = useState([]);
  const [sectorId, setSectorId] = useState('');
  const [workflows, setWorkflows] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);

  // Create workflow form
  const [creatingWorkflow, setCreatingWorkflow] = useState(false);
  const [newWorkflow, setNewWorkflow] = useState({ ...INITIAL_WORKFLOW });

  // Create estado form (keyed by workflow id)
  const [addingEstadoFor, setAddingEstadoFor] = useState(null);
  const [newEstado, setNewEstado] = useState({ ...INITIAL_ESTADO });

  // Create transicion form (keyed by workflow id)
  const [addingTransicionFor, setAddingTransicionFor] = useState(null);
  const [newTransicion, setNewTransicion] = useState({ ...INITIAL_TRANSICION });

  useEffect(() => {
    const fetchSectores = async () => {
      try {
        const { data } = await sectoresAPI.listar({ activos_solo: false });
        setSectores(Array.isArray(data) ? data : []);
      } catch {
        setSectores([]);
      }
    };
    fetchSectores();
  }, []);

  const cargarWorkflows = useCallback(async () => {
    if (!sectorId) {
      setWorkflows([]);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const { data } = await sectoresAPI.listarWorkflows(sectorId, { activos_solo: false });
      setWorkflows(Array.isArray(data) ? data : []);
    } catch {
      setError('Error al cargar workflows');
      setWorkflows([]);
    } finally {
      setLoading(false);
    }
  }, [sectorId]);

  useEffect(() => {
    cargarWorkflows();
  }, [cargarWorkflows]);

  const clearMessages = () => {
    setError(null);
    setSuccess(null);
  };

  // ── Create Workflow ──
  const handleCreateWorkflow = async () => {
    clearMessages();
    try {
      await workflowsAPI.crear({
        sector_id: Number(sectorId),
        nombre: newWorkflow.nombre,
        descripcion: newWorkflow.descripcion || null,
        es_default: newWorkflow.es_default,
        activo: true,
      });
      setSuccess('Workflow creado');
      setCreatingWorkflow(false);
      setNewWorkflow({ ...INITIAL_WORKFLOW });
      cargarWorkflows();
    } catch (err) {
      const detail = err.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : 'Error al crear workflow');
    }
  };

  // ── Create Estado ──
  const handleCreateEstado = async (workflowId) => {
    clearMessages();
    try {
      await workflowsAPI.crearEstado(workflowId, {
        workflow_id: workflowId,
        codigo: newEstado.codigo,
        nombre: newEstado.nombre,
        descripcion: newEstado.descripcion || null,
        orden: Number(newEstado.orden),
        color: newEstado.color || null,
        es_inicial: newEstado.es_inicial,
        es_final: newEstado.es_final,
      });
      setSuccess('Estado creado');
      setAddingEstadoFor(null);
      setNewEstado({ ...INITIAL_ESTADO });
      cargarWorkflows();
    } catch (err) {
      const detail = err.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : 'Error al crear estado');
    }
  };

  // ── Create Transicion ──
  const handleCreateTransicion = async (workflowId) => {
    clearMessages();
    try {
      await workflowsAPI.crearTransicion(workflowId, {
        workflow_id: workflowId,
        estado_origen_id: Number(newTransicion.estado_origen_id),
        estado_destino_id: Number(newTransicion.estado_destino_id),
        nombre: newTransicion.nombre || null,
        descripcion: newTransicion.descripcion || null,
        requiere_permiso: newTransicion.requiere_permiso || null,
        solo_asignado: newTransicion.solo_asignado,
        solo_creador: newTransicion.solo_creador,
      });
      setSuccess('Transición creada');
      setAddingTransicionFor(null);
      setNewTransicion({ ...INITIAL_TRANSICION });
      cargarWorkflows();
    } catch (err) {
      const detail = err.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : 'Error al crear transición');
    }
  };

  const getEstadoNombre = (estados, estadoId) => {
    const e = estados.find((s) => s.id === estadoId);
    return e?.nombre || `#${estadoId}`;
  };

  return (
    <div className={styles.container}>
      <div className={styles.sectionHeader}>
        <h2 className={styles.sectionTitle}>Workflows</h2>
      </div>

      {error && <div className={`${styles.message} ${styles.messageError}`}>{error}</div>}
      {success && <div className={`${styles.message} ${styles.messageSuccess}`}>{success}</div>}

      <div className={styles.selectorRow}>
        <label htmlFor="wf-sector-sel">Sector</label>
        <select
          id="wf-sector-sel"
          className={styles.select}
          value={sectorId}
          onChange={(e) => {
            setSectorId(e.target.value);
            setCreatingWorkflow(false);
            setAddingEstadoFor(null);
            setAddingTransicionFor(null);
            clearMessages();
          }}
        >
          <option value="">Seleccionar sector...</option>
          {sectores.map((s) => (
            <option key={s.id} value={s.id}>
              {s.nombre}
            </option>
          ))}
        </select>
        {sectorId && (
          <button
            className={styles.btnCreate}
            onClick={() => setCreatingWorkflow(true)}
            disabled={creatingWorkflow}
          >
            <Plus size={16} />
            Crear Workflow
          </button>
        )}
      </div>

      {/* Create Workflow Form */}
      {creatingWorkflow && (
        <div className={styles.formCard}>
          <div className={styles.formHint}>
            Un workflow define los <strong>estados</strong> por los que pasa un ticket
            (ej: Abierto &rarr; En revisión &rarr; Resuelto) y las <strong>transiciones</strong> permitidas entre ellos.
            Después se asigna a uno o más tipos de ticket.
          </div>
          <div className={styles.formGrid}>
            <div className={styles.formField}>
              <label htmlFor="wf-name">Nombre del flujo</label>
              <input
                id="wf-name"
                className={styles.input}
                value={newWorkflow.nombre}
                onChange={(e) => setNewWorkflow({ ...newWorkflow, nombre: e.target.value })}
                placeholder="Ej: Soporte Técnico, Aprobación Pricing"
              />
            </div>
            <div className={styles.formField}>
              <label htmlFor="wf-desc">Descripción</label>
              <input
                id="wf-desc"
                className={styles.input}
                value={newWorkflow.descripcion}
                onChange={(e) => setNewWorkflow({ ...newWorkflow, descripcion: e.target.value })}
                placeholder="Ej: Flujo para tickets de bugs y soporte"
              />
            </div>
            <div className={styles.formField}>
              <label>Default del sector</label>
              <label className={styles.toggle}>
                <input
                  type="checkbox"
                  checked={newWorkflow.es_default}
                  onChange={(e) => setNewWorkflow({ ...newWorkflow, es_default: e.target.checked })}
                />
                <span className={styles.toggleTrack} />
              </label>
              <span className={styles.fieldHint}>
                Si está activo, los tipos de ticket sin workflow propio usarán este
              </span>
            </div>
          </div>
          <div className={styles.formActions}>
            <button
              className={styles.btnCancel}
              onClick={() => {
                setCreatingWorkflow(false);
                setNewWorkflow({ ...INITIAL_WORKFLOW });
              }}
            >
              <X size={14} />
              Cancelar
            </button>
            <button
              className={styles.btnSave}
              onClick={handleCreateWorkflow}
              disabled={!newWorkflow.nombre}
            >
              <Save size={14} />
              Crear
            </button>
          </div>
        </div>
      )}

      {/* Content */}
      {!sectorId ? (
        <div className={styles.emptyState}>Seleccioná un sector para ver sus workflows</div>
      ) : loading ? (
        <div className={styles.loadingState}>Cargando workflows...</div>
      ) : workflows.length === 0 ? (
        <div className={styles.emptyState}>No hay workflows para este sector</div>
      ) : (
        workflows.map((wf) => (
          <div key={wf.id} className={styles.workflowCard}>
            {/* Workflow header */}
            <div className={styles.workflowHeader}>
              <div className={styles.workflowName}>
                <GitBranch size={18} />
                {wf.nombre}
                {wf.es_default && <span className={styles.badgeDefault}>Default</span>}
                <span className={wf.activo ? styles.badgeActivo : ''}>
                  {wf.activo ? 'Activo' : 'Inactivo'}
                </span>
              </div>
            </div>
            {wf.descripcion && <div className={styles.workflowDesc}>{wf.descripcion}</div>}

            {/* Estados */}
            <div className={styles.subSection}>
              <div className={styles.subSectionHeader}>
                <span className={styles.subSectionTitle}>
                  Estados ({wf.estados?.length || 0})
                </span>
                <button
                  className={styles.btnCreate}
                  onClick={() => {
                    setAddingEstadoFor(addingEstadoFor === wf.id ? null : wf.id);
                    setNewEstado({ ...INITIAL_ESTADO });
                    clearMessages();
                  }}
                >
                  <Plus size={14} />
                  Agregar Estado
                </button>
              </div>

              {/* Add Estado Form */}
              {addingEstadoFor === wf.id && (
                <div className={styles.formCard}>
                  <div className={styles.formHint}>
                    Cada estado representa una <strong>etapa</strong> del ticket.
                    Marcá uno como &quot;Inicial&quot; (donde arranca el ticket) y al menos uno como
                    &quot;Final&quot; (donde se cierra).
                  </div>
                  <div className={styles.formGrid}>
                    <div className={styles.formField}>
                      <label htmlFor={`est-nombre-${wf.id}`}>Nombre del estado</label>
                      <input
                        id={`est-nombre-${wf.id}`}
                        className={styles.input}
                        value={newEstado.nombre}
                        onChange={(e) => setNewEstado({ ...newEstado, nombre: e.target.value })}
                        placeholder="Ej: Abierto, En revisión, Resuelto"
                      />
                    </div>
                    <div className={styles.formField}>
                      <label htmlFor={`est-codigo-${wf.id}`}>Código interno</label>
                      <input
                        id={`est-codigo-${wf.id}`}
                        className={styles.input}
                        value={newEstado.codigo}
                        onChange={(e) => setNewEstado({ ...newEstado, codigo: e.target.value })}
                        placeholder="Ej: abierto, en_revision, resuelto"
                      />
                      <span className={styles.fieldHint}>
                        Identificador único, en minúsculas y sin espacios
                      </span>
                    </div>
                    <div className={styles.formField}>
                      <label htmlFor={`est-orden-${wf.id}`}>Orden</label>
                      <input
                        id={`est-orden-${wf.id}`}
                        type="number"
                        className={styles.input}
                        value={newEstado.orden}
                        onChange={(e) => setNewEstado({ ...newEstado, orden: e.target.value })}
                        min="0"
                      />
                      <span className={styles.fieldHint}>
                        Posición en la lista (0, 1, 2...)
                      </span>
                    </div>
                    <div className={styles.formField}>
                      <label>Color</label>
                      <div className={styles.colorField}>
                        <input
                          type="color"
                          className={styles.colorPicker}
                          value={newEstado.color}
                          onChange={(e) => setNewEstado({ ...newEstado, color: e.target.value })}
                        />
                      </div>
                    </div>
                    <div className={styles.formField}>
                      <label>Estado inicial</label>
                      <label className={styles.toggle}>
                        <input
                          type="checkbox"
                          checked={newEstado.es_inicial}
                          onChange={(e) =>
                            setNewEstado({ ...newEstado, es_inicial: e.target.checked })
                          }
                        />
                        <span className={styles.toggleTrack} />
                      </label>
                      <span className={styles.fieldHint}>
                        El ticket arranca en este estado al crearse
                      </span>
                    </div>
                    <div className={styles.formField}>
                      <label>Estado final</label>
                      <label className={styles.toggle}>
                        <input
                          type="checkbox"
                          checked={newEstado.es_final}
                          onChange={(e) =>
                            setNewEstado({ ...newEstado, es_final: e.target.checked })
                          }
                        />
                        <span className={styles.toggleTrack} />
                      </label>
                      <span className={styles.fieldHint}>
                        El ticket se considera cerrado en este estado
                      </span>
                    </div>
                  </div>
                  <div className={styles.formActions}>
                    <button
                      className={styles.btnCancel}
                      onClick={() => setAddingEstadoFor(null)}
                    >
                      <X size={14} />
                      Cancelar
                    </button>
                    <button
                      className={styles.btnSave}
                      onClick={() => handleCreateEstado(wf.id)}
                      disabled={!newEstado.nombre || !newEstado.codigo}
                    >
                      <Save size={14} />
                      Crear Estado
                    </button>
                  </div>
                </div>
              )}

              {/* States list */}
              {wf.estados && wf.estados.length > 0 ? (
                <div className={styles.statesList}>
                  {[...wf.estados]
                    .sort((a, b) => a.orden - b.orden)
                    .map((estado) => (
                      <div key={estado.id} className={styles.stateItem}>
                        <span
                          className={styles.colorDot}
                          style={{ backgroundColor: estado.color || '#6b7280' }}
                        />
                        <span className={styles.stateName}>{estado.nombre}</span>
                        <span className={styles.stateCode}>{estado.codigo}</span>
                        <div className={styles.stateBadges}>
                          {estado.es_inicial && (
                            <span className={styles.badgeInicial}>
                              <CircleDot size={10} /> Inicial
                            </span>
                          )}
                          {estado.es_final && (
                            <span className={styles.badgeFinal}>
                              <Flag size={10} /> Final
                            </span>
                          )}
                        </div>
                        <span className={styles.stateOrder}>#{estado.orden}</span>
                      </div>
                    ))}
                </div>
              ) : (
                <div className={styles.emptyState}>Sin estados definidos</div>
              )}
            </div>

            {/* Transiciones */}
            <div className={styles.subSection}>
              <div className={styles.subSectionHeader}>
                <span className={styles.subSectionTitle}>
                  Transiciones ({wf.transiciones?.length || 0})
                </span>
                {wf.estados && wf.estados.length >= 2 && (
                  <button
                    className={styles.btnCreate}
                    onClick={() => {
                      setAddingTransicionFor(
                        addingTransicionFor === wf.id ? null : wf.id
                      );
                      setNewTransicion({ ...INITIAL_TRANSICION });
                      clearMessages();
                    }}
                  >
                    <Plus size={14} />
                    Agregar Transición
                  </button>
                )}
              </div>

              {/* Add Transicion Form */}
              {addingTransicionFor === wf.id && (
                <div className={styles.formCard}>
                  <div className={styles.formHint}>
                    Una transición define un <strong>movimiento permitido</strong> entre dos estados.
                    Por ejemplo: de &quot;Abierto&quot; a &quot;En revisión&quot;.
                    Sin transiciones, el ticket queda trabado en su estado inicial.
                  </div>
                  <div className={styles.formGrid}>
                    <div className={styles.formField}>
                      <label htmlFor={`tr-origen-${wf.id}`}>Estado origen</label>
                      <select
                        id={`tr-origen-${wf.id}`}
                        className={styles.select}
                        value={newTransicion.estado_origen_id}
                        onChange={(e) =>
                          setNewTransicion({
                            ...newTransicion,
                            estado_origen_id: e.target.value,
                          })
                        }
                      >
                        <option value="">Desde qué estado...</option>
                        {wf.estados?.map((e) => (
                          <option key={e.id} value={e.id}>
                            {e.nombre}
                          </option>
                        ))}
                      </select>
                    </div>
                    <div className={styles.formField}>
                      <label htmlFor={`tr-destino-${wf.id}`}>Estado destino</label>
                      <select
                        id={`tr-destino-${wf.id}`}
                        className={styles.select}
                        value={newTransicion.estado_destino_id}
                        onChange={(e) =>
                          setNewTransicion({
                            ...newTransicion,
                            estado_destino_id: e.target.value,
                          })
                        }
                      >
                        <option value="">Hacia qué estado...</option>
                        {wf.estados?.map((e) => (
                          <option key={e.id} value={e.id}>
                            {e.nombre}
                          </option>
                        ))}
                      </select>
                    </div>
                    <div className={styles.formField}>
                      <label htmlFor={`tr-nombre-${wf.id}`}>Nombre de la acción</label>
                      <input
                        id={`tr-nombre-${wf.id}`}
                        className={styles.input}
                        value={newTransicion.nombre}
                        onChange={(e) =>
                          setNewTransicion({ ...newTransicion, nombre: e.target.value })
                        }
                        placeholder="Ej: Tomar, Resolver, Rechazar, Reabrir"
                      />
                      <span className={styles.fieldHint}>
                        El texto del botón que verá el usuario para mover el ticket
                      </span>
                    </div>
                    <div className={styles.formField}>
                      <label htmlFor={`tr-permiso-${wf.id}`}>Permiso requerido</label>
                      <input
                        id={`tr-permiso-${wf.id}`}
                        className={styles.input}
                        value={newTransicion.requiere_permiso}
                        onChange={(e) =>
                          setNewTransicion({
                            ...newTransicion,
                            requiere_permiso: e.target.value,
                          })
                        }
                        placeholder="Ej: tickets.gestionar"
                      />
                      <span className={styles.fieldHint}>
                        Dejar vacío si cualquier usuario puede hacer esta transición
                      </span>
                    </div>
                    <div className={styles.formField}>
                      <label>Solo asignado</label>
                      <label className={styles.toggle}>
                        <input
                          type="checkbox"
                          checked={newTransicion.solo_asignado}
                          onChange={(e) =>
                            setNewTransicion({
                              ...newTransicion,
                              solo_asignado: e.target.checked,
                            })
                          }
                        />
                        <span className={styles.toggleTrack} />
                      </label>
                      <span className={styles.fieldHint}>
                        Solo quien tiene el ticket asignado puede ejecutar esta acción
                      </span>
                    </div>
                    <div className={styles.formField}>
                      <label>Solo creador</label>
                      <label className={styles.toggle}>
                        <input
                          type="checkbox"
                          checked={newTransicion.solo_creador}
                          onChange={(e) =>
                            setNewTransicion({
                              ...newTransicion,
                              solo_creador: e.target.checked,
                            })
                          }
                        />
                        <span className={styles.toggleTrack} />
                      </label>
                      <span className={styles.fieldHint}>
                        Solo quien creó el ticket puede ejecutar esta acción
                      </span>
                    </div>
                  </div>
                  <div className={styles.formActions}>
                    <button
                      className={styles.btnCancel}
                      onClick={() => setAddingTransicionFor(null)}
                    >
                      <X size={14} />
                      Cancelar
                    </button>
                    <button
                      className={styles.btnSave}
                      onClick={() => handleCreateTransicion(wf.id)}
                      disabled={
                        !newTransicion.estado_origen_id || !newTransicion.estado_destino_id
                      }
                    >
                      <Save size={14} />
                      Crear Transición
                    </button>
                  </div>
                </div>
              )}

              {/* Transitions list */}
              {wf.transiciones && wf.transiciones.length > 0 ? (
                <div className={styles.statesList}>
                  {wf.transiciones.map((tr) => (
                    <div key={tr.id} className={styles.transitionItem}>
                      <span>{getEstadoNombre(wf.estados || [], tr.estado_origen_id)}</span>
                      <ArrowRight size={14} className={styles.transitionArrow} />
                      <span>{getEstadoNombre(wf.estados || [], tr.estado_destino_id)}</span>
                      {tr.nombre && (
                        <span className={styles.transitionName}>({tr.nombre})</span>
                      )}
                      {tr.requiere_permiso && (
                        <span className={styles.transitionPermiso}>
                          <Lock size={10} />
                          {tr.requiere_permiso}
                        </span>
                      )}
                    </div>
                  ))}
                </div>
              ) : (
                <div className={styles.emptyState}>Sin transiciones definidas</div>
              )}
            </div>
          </div>
        ))
      )}
    </div>
  );
}
