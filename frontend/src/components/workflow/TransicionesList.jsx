import { useState } from 'react';
import { workflowsAPI } from '../../services/api';
import {
  Plus,
  X,
  Save,
  ArrowRight,
  Lock,
  Pencil,
  Trash2,
} from 'lucide-react';
import styles from '../WorkflowEditor.module.css';

const INITIAL_TRANSICION = {
  estado_origen_id: '',
  estado_destino_id: '',
  nombre: '',
  descripcion: '',
  requiere_permiso: '',
  solo_asignado: false,
  solo_creador: false,
};

export default function TransicionesList({ workflowId, estados, transiciones, onRefresh, onError, onSuccess }) {
  const [adding, setAdding] = useState(false);
  const [newTr, setNewTr] = useState({ ...INITIAL_TRANSICION });
  const [editingId, setEditingId] = useState(null);
  const [editData, setEditData] = useState({ ...INITIAL_TRANSICION });
  const [confirmDelete, setConfirmDelete] = useState(null);

  const clearForm = () => {
    setAdding(false);
    setNewTr({ ...INITIAL_TRANSICION });
  };

  const getEstadoNombre = (estadoId) => {
    const e = (estados || []).find((s) => s.id === estadoId);
    return e?.nombre || `#${estadoId}`;
  };

  const handleCreate = async () => {
    try {
      await workflowsAPI.crearTransicion(workflowId, {
        workflow_id: workflowId,
        estado_origen_id: Number(newTr.estado_origen_id),
        estado_destino_id: Number(newTr.estado_destino_id),
        nombre: newTr.nombre || null,
        descripcion: newTr.descripcion || null,
        requiere_permiso: newTr.requiere_permiso || null,
        solo_asignado: newTr.solo_asignado,
        solo_creador: newTr.solo_creador,
      });
      onSuccess('Transición creada');
      clearForm();
      onRefresh();
    } catch (err) {
      const detail = err.response?.data?.detail;
      onError(typeof detail === 'string' ? detail : 'Error al crear transición');
    }
  };

  const startEdit = (tr) => {
    setEditingId(tr.id);
    setEditData({
      nombre: tr.nombre || '',
      descripcion: tr.descripcion || '',
      requiere_permiso: tr.requiere_permiso || '',
      solo_asignado: tr.solo_asignado,
      solo_creador: tr.solo_creador,
    });
    setAdding(false);
  };

  const handleUpdate = async () => {
    try {
      await workflowsAPI.actualizarTransicion(workflowId, editingId, {
        nombre: editData.nombre || null,
        descripcion: editData.descripcion || null,
        requiere_permiso: editData.requiere_permiso || null,
        solo_asignado: editData.solo_asignado,
        solo_creador: editData.solo_creador,
      });
      onSuccess('Transición actualizada');
      setEditingId(null);
      onRefresh();
    } catch (err) {
      const detail = err.response?.data?.detail;
      onError(typeof detail === 'string' ? detail : 'Error al actualizar transición');
    }
  };

  const handleDelete = (trId, trNombre) => {
    setConfirmDelete({
      message: `¿Eliminar la transición "${trNombre || 'sin nombre'}"?`,
      onConfirm: async () => {
        setConfirmDelete(null);
        try {
          await workflowsAPI.eliminarTransicion(workflowId, trId);
          onSuccess('Transición eliminada');
          onRefresh();
        } catch (err) {
          const detail = err.response?.data?.detail;
          onError(typeof detail === 'string' ? detail : 'Error al eliminar transición');
        }
      },
    });
  };

  const list = transiciones || [];

  return (
    <div className={styles.subSection}>
      <div className={styles.subSectionHeader}>
        <span className={styles.subSectionTitle}>Transiciones ({list.length})</span>
        {estados && estados.length >= 2 && (
          <button
            className={styles.btnCreate}
            onClick={() => { setAdding(!adding); setNewTr({ ...INITIAL_TRANSICION }); }}
          >
            <Plus size={14} /> Agregar Transición
          </button>
        )}
      </div>

      {confirmDelete && (
        <div className={styles.confirmBar}>
          <span>{confirmDelete.message}</span>
          <div className={styles.confirmActions}>
            <button className={styles.btnCancel} onClick={() => setConfirmDelete(null)}>
              <X size={14} /> No
            </button>
            <button className={styles.btnDangerSolid} onClick={confirmDelete.onConfirm}>
              <Trash2 size={14} /> Sí, eliminar
            </button>
          </div>
        </div>
      )}

      {/* Create form */}
      {adding && (
        <div className={styles.formCard}>
          <div className={styles.formHint}>
            Una transición define un <strong>movimiento permitido</strong> entre dos estados.
            Por ejemplo: de &quot;Abierto&quot; a &quot;En revisión&quot;.
            Sin transiciones, el ticket queda trabado en su estado inicial.
          </div>
          <div className={styles.formGrid}>
            <div className={styles.formField}>
              <label>Estado origen</label>
              <select
                className={styles.select}
                value={newTr.estado_origen_id}
                onChange={(e) => setNewTr({ ...newTr, estado_origen_id: e.target.value })}
              >
                <option value="">Desde qué estado...</option>
                {estados?.map((e) => (
                  <option key={e.id} value={e.id}>{e.nombre}</option>
                ))}
              </select>
            </div>
            <div className={styles.formField}>
              <label>Estado destino</label>
              <select
                className={styles.select}
                value={newTr.estado_destino_id}
                onChange={(e) => setNewTr({ ...newTr, estado_destino_id: e.target.value })}
              >
                <option value="">Hacia qué estado...</option>
                {estados?.map((e) => (
                  <option key={e.id} value={e.id}>{e.nombre}</option>
                ))}
              </select>
            </div>
            <div className={styles.formField}>
              <label>Nombre de la acción</label>
              <input
                className={styles.input}
                value={newTr.nombre}
                onChange={(e) => setNewTr({ ...newTr, nombre: e.target.value })}
                placeholder="Ej: Tomar, Resolver, Rechazar, Reabrir"
              />
              <span className={styles.fieldHint}>
                El texto del botón que verá el usuario para mover el ticket
              </span>
            </div>
            <div className={styles.formField}>
              <label>Permiso requerido</label>
              <input
                className={styles.input}
                value={newTr.requiere_permiso}
                onChange={(e) => setNewTr({ ...newTr, requiere_permiso: e.target.value })}
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
                  checked={newTr.solo_asignado}
                  onChange={(e) => setNewTr({ ...newTr, solo_asignado: e.target.checked })}
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
                  checked={newTr.solo_creador}
                  onChange={(e) => setNewTr({ ...newTr, solo_creador: e.target.checked })}
                />
                <span className={styles.toggleTrack} />
              </label>
              <span className={styles.fieldHint}>
                Solo quien creó el ticket puede ejecutar esta acción
              </span>
            </div>
          </div>
          <div className={styles.formActions}>
            <button className={styles.btnCancel} onClick={clearForm}>
              <X size={14} /> Cancelar
            </button>
            <button
              className={styles.btnSave}
              onClick={handleCreate}
              disabled={!newTr.estado_origen_id || !newTr.estado_destino_id}
            >
              <Save size={14} /> Crear Transición
            </button>
          </div>
        </div>
      )}

      {/* List */}
      {list.length > 0 ? (
        <div className={styles.statesList}>
          {list.map((tr) => (
            <div key={tr.id}>
              <div className={styles.transitionItem}>
                <span>{getEstadoNombre(tr.estado_origen_id)}</span>
                <ArrowRight size={14} className={styles.transitionArrow} />
                <span>{getEstadoNombre(tr.estado_destino_id)}</span>
                {tr.nombre && <span className={styles.transitionName}>({tr.nombre})</span>}
                {tr.requiere_permiso && (
                  <span className={styles.transitionPermiso}>
                    <Lock size={10} /> {tr.requiere_permiso}
                  </span>
                )}
                <div className={styles.itemActions}>
                  <button
                    className={styles.btnIcon}
                    onClick={() => startEdit(tr)}
                    aria-label="Editar transición"
                  >
                    <Pencil size={13} />
                  </button>
                  <button
                    className={`${styles.btnIcon} ${styles.btnDanger}`}
                    onClick={() => handleDelete(tr.id, tr.nombre)}
                    aria-label="Eliminar transición"
                  >
                    <Trash2 size={13} />
                  </button>
                </div>
              </div>

              {/* Inline edit */}
              {editingId === tr.id && (
                <div className={styles.editFormInline}>
                  <div className={styles.formGrid}>
                    <div className={styles.formField}>
                      <label>Nombre de la acción</label>
                      <input
                        className={styles.input}
                        value={editData.nombre}
                        onChange={(e) => setEditData({ ...editData, nombre: e.target.value })}
                        placeholder="Ej: Tomar, Resolver, Rechazar"
                      />
                    </div>
                    <div className={styles.formField}>
                      <label>Permiso requerido</label>
                      <input
                        className={styles.input}
                        value={editData.requiere_permiso}
                        onChange={(e) => setEditData({ ...editData, requiere_permiso: e.target.value })}
                        placeholder="Ej: tickets.gestionar"
                      />
                    </div>
                    <div className={styles.formField}>
                      <label>Solo asignado</label>
                      <label className={styles.toggle}>
                        <input
                          type="checkbox"
                          checked={editData.solo_asignado}
                          onChange={(e) => setEditData({ ...editData, solo_asignado: e.target.checked })}
                        />
                        <span className={styles.toggleTrack} />
                      </label>
                    </div>
                    <div className={styles.formField}>
                      <label>Solo creador</label>
                      <label className={styles.toggle}>
                        <input
                          type="checkbox"
                          checked={editData.solo_creador}
                          onChange={(e) => setEditData({ ...editData, solo_creador: e.target.checked })}
                        />
                        <span className={styles.toggleTrack} />
                      </label>
                    </div>
                  </div>
                  <div className={styles.formActions}>
                    <button className={styles.btnCancel} onClick={() => setEditingId(null)}>
                      <X size={14} /> Cancelar
                    </button>
                    <button className={styles.btnSave} onClick={handleUpdate}>
                      <Save size={14} /> Guardar
                    </button>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      ) : (
        <div className={styles.emptyState}>Sin transiciones definidas</div>
      )}
    </div>
  );
}
