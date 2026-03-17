import { useState, useEffect, useCallback } from 'react';
import { sectoresAPI, workflowsAPI } from '../services/api';
import { Plus, X, Save, GitBranch } from 'lucide-react';
import EstadosList from './workflow/EstadosList';
import TransicionesList from './workflow/TransicionesList';
import styles from './WorkflowEditor.module.css';

export default function WorkflowEditor() {
  const [sectores, setSectores] = useState([]);
  const [sectorId, setSectorId] = useState('');
  const [workflows, setWorkflows] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);

  // Create workflow form
  const [creatingWorkflow, setCreatingWorkflow] = useState(false);
  const [newWorkflow, setNewWorkflow] = useState({ nombre: '', descripcion: '', es_default: false });

  useEffect(() => {
    const fetchSectores = async () => {
      setLoading(true);
      try {
        const { data } = await sectoresAPI.listar({ activos_solo: false });
        setSectores(Array.isArray(data) ? data : []);
      } catch {
        setError('Error al cargar sectores');
        setSectores([]);
      } finally {
        setLoading(false);
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
      setNewWorkflow({ nombre: '', descripcion: '', es_default: false });
      cargarWorkflows();
    } catch (err) {
      const detail = err.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : 'Error al crear workflow');
    }
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
            clearMessages();
          }}
        >
          <option value="">Seleccionar sector...</option>
          {sectores.map((s) => (
            <option key={s.id} value={s.id}>{s.nombre}</option>
          ))}
        </select>
        {sectorId && (
          <button
            className={styles.btnCreate}
            onClick={() => setCreatingWorkflow(true)}
            disabled={creatingWorkflow}
          >
            <Plus size={16} /> Crear Workflow
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
                setNewWorkflow({ nombre: '', descripcion: '', es_default: false });
              }}
            >
              <X size={14} /> Cancelar
            </button>
            <button
              className={styles.btnSave}
              onClick={handleCreateWorkflow}
              disabled={!newWorkflow.nombre}
            >
              <Save size={14} /> Crear
            </button>
          </div>
        </div>
      )}

      {/* Workflow Cards */}
      {!sectorId ? (
        <div className={styles.emptyState}>Seleccioná un sector para ver sus workflows</div>
      ) : loading ? (
        <div className={styles.loadingState}>Cargando workflows...</div>
      ) : workflows.length === 0 ? (
        <div className={styles.emptyState}>No hay workflows para este sector</div>
      ) : (
        workflows.map((wf) => (
          <div key={wf.id} className={styles.workflowCard}>
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

            <EstadosList
              workflowId={wf.id}
              estados={wf.estados}
              onRefresh={cargarWorkflows}
              onError={setError}
              onSuccess={setSuccess}
            />

            <TransicionesList
              workflowId={wf.id}
              estados={wf.estados}
              transiciones={wf.transiciones}
              onRefresh={cargarWorkflows}
              onError={setError}
              onSuccess={setSuccess}
            />
          </div>
        ))
      )}
    </div>
  );
}
