import { useState } from 'react';
import { workflowsAPI } from '../../services/api';
import {
  Plus,
  X,
  Save,
  CircleDot,
  Flag,
  Pencil,
  Trash2,
} from 'lucide-react';
import styles from '../WorkflowEditor.module.css';

const INITIAL_ESTADO = {
  codigo: '',
  nombre: '',
  descripcion: '',
  orden: 0,
  color: '#6b7280',
  es_inicial: false,
  es_final: false,
};

export default function EstadosList({ workflowId, estados, onRefresh, onError, onSuccess }) {
  const [adding, setAdding] = useState(false);
  const [newEstado, setNewEstado] = useState({ ...INITIAL_ESTADO });
  const [editingId, setEditingId] = useState(null);
  const [editData, setEditData] = useState({ ...INITIAL_ESTADO });
  const [confirmDelete, setConfirmDelete] = useState(null);

  const clearForm = () => {
    setAdding(false);
    setNewEstado({ ...INITIAL_ESTADO });
  };

  const handleCreate = async () => {
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
      onSuccess('Estado creado');
      clearForm();
      onRefresh();
    } catch (err) {
      const detail = err.response?.data?.detail;
      onError(typeof detail === 'string' ? detail : 'Error al crear estado');
    }
  };

  const startEdit = (estado) => {
    setEditingId(estado.id);
    setEditData({
      nombre: estado.nombre,
      descripcion: estado.descripcion || '',
      orden: estado.orden,
      color: estado.color || '#6b7280',
      es_inicial: estado.es_inicial,
      es_final: estado.es_final,
    });
    setAdding(false);
  };

  const handleUpdate = async () => {
    try {
      await workflowsAPI.actualizarEstado(workflowId, editingId, {
        nombre: editData.nombre,
        descripcion: editData.descripcion || null,
        orden: Number(editData.orden),
        color: editData.color || null,
        es_inicial: editData.es_inicial,
        es_final: editData.es_final,
      });
      onSuccess('Estado actualizado');
      setEditingId(null);
      onRefresh();
    } catch (err) {
      const detail = err.response?.data?.detail;
      onError(typeof detail === 'string' ? detail : 'Error al actualizar estado');
    }
  };

  const handleDelete = (estadoId, estadoNombre) => {
    setConfirmDelete({
      message: `¿Eliminar el estado "${estadoNombre}"? También se borrarán sus transiciones asociadas.`,
      onConfirm: async () => {
        setConfirmDelete(null);
        try {
          await workflowsAPI.eliminarEstado(workflowId, estadoId);
          onSuccess(`Estado "${estadoNombre}" eliminado`);
          onRefresh();
        } catch (err) {
          const detail = err.response?.data?.detail;
          onError(typeof detail === 'string' ? detail : 'Error al eliminar estado');
        }
      },
    });
  };

  const sorted = estados ? [...estados].sort((a, b) => a.orden - b.orden) : [];

  return (
    <div className={styles.subSection}>
      <div className={styles.subSectionHeader}>
        <span className={styles.subSectionTitle}>Estados ({sorted.length})</span>
        <button
          className={styles.btnCreate}
          onClick={() => { setAdding(!adding); setNewEstado({ ...INITIAL_ESTADO }); }}
        >
          <Plus size={14} /> Agregar Estado
        </button>
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
            Cada estado representa una <strong>etapa</strong> del ticket.
            Marcá uno como &quot;Inicial&quot; (donde arranca el ticket) y al menos uno como
            &quot;Final&quot; (donde se cierra).
          </div>
          <div className={styles.formGrid}>
            <div className={styles.formField}>
              <label>Nombre del estado</label>
              <input
                className={styles.input}
                value={newEstado.nombre}
                onChange={(e) => setNewEstado({ ...newEstado, nombre: e.target.value })}
                placeholder="Ej: Abierto, En revisión, Resuelto"
              />
            </div>
            <div className={styles.formField}>
              <label>Código interno</label>
              <input
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
              <label>Orden</label>
              <input
                type="number"
                className={styles.input}
                value={newEstado.orden}
                onChange={(e) => setNewEstado({ ...newEstado, orden: e.target.value })}
                min="0"
              />
              <span className={styles.fieldHint}>Posición en la lista (0, 1, 2...)</span>
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
                  onChange={(e) => setNewEstado({ ...newEstado, es_inicial: e.target.checked })}
                />
                <span className={styles.toggleTrack} />
              </label>
              <span className={styles.fieldHint}>El ticket arranca en este estado al crearse</span>
            </div>
            <div className={styles.formField}>
              <label>Estado final</label>
              <label className={styles.toggle}>
                <input
                  type="checkbox"
                  checked={newEstado.es_final}
                  onChange={(e) => setNewEstado({ ...newEstado, es_final: e.target.checked })}
                />
                <span className={styles.toggleTrack} />
              </label>
              <span className={styles.fieldHint}>El ticket se considera cerrado en este estado</span>
            </div>
          </div>
          <div className={styles.formActions}>
            <button className={styles.btnCancel} onClick={clearForm}>
              <X size={14} /> Cancelar
            </button>
            <button
              className={styles.btnSave}
              onClick={handleCreate}
              disabled={!newEstado.nombre || !newEstado.codigo}
            >
              <Save size={14} /> Crear Estado
            </button>
          </div>
        </div>
      )}

      {/* List */}
      {sorted.length > 0 ? (
        <div className={styles.statesList}>
          {sorted.map((estado) => (
            <div key={estado.id}>
              <div className={styles.stateItem}>
                <span className={styles.colorDot} style={{ backgroundColor: estado.color || '#6b7280' }} />
                <span className={styles.stateName}>{estado.nombre}</span>
                <span className={styles.stateCode}>{estado.codigo}</span>
                <div className={styles.stateBadges}>
                  {estado.es_inicial && (
                    <span className={styles.badgeInicial}><CircleDot size={10} /> Inicial</span>
                  )}
                  {estado.es_final && (
                    <span className={styles.badgeFinal}><Flag size={10} /> Final</span>
                  )}
                </div>
                <span className={styles.stateOrder}>#{estado.orden}</span>
                <div className={styles.itemActions}>
                  <button
                    className={styles.btnIcon}
                    onClick={() => startEdit(estado)}
                    aria-label={`Editar estado ${estado.nombre}`}
                  >
                    <Pencil size={13} />
                  </button>
                  <button
                    className={`${styles.btnIcon} ${styles.btnDanger}`}
                    onClick={() => handleDelete(estado.id, estado.nombre)}
                    aria-label={`Eliminar estado ${estado.nombre}`}
                  >
                    <Trash2 size={13} />
                  </button>
                </div>
              </div>

              {/* Inline edit */}
              {editingId === estado.id && (
                <div className={styles.editFormInline}>
                  <div className={styles.formGrid}>
                    <div className={styles.formField}>
                      <label>Nombre</label>
                      <input
                        className={styles.input}
                        value={editData.nombre}
                        onChange={(e) => setEditData({ ...editData, nombre: e.target.value })}
                      />
                    </div>
                    <div className={styles.formField}>
                      <label>Orden</label>
                      <input
                        type="number"
                        className={styles.input}
                        value={editData.orden}
                        onChange={(e) => setEditData({ ...editData, orden: e.target.value })}
                        min="0"
                      />
                    </div>
                    <div className={styles.formField}>
                      <label>Color</label>
                      <input
                        type="color"
                        className={styles.colorPicker}
                        value={editData.color}
                        onChange={(e) => setEditData({ ...editData, color: e.target.value })}
                      />
                    </div>
                    <div className={styles.formField}>
                      <label>Inicial</label>
                      <label className={styles.toggle}>
                        <input
                          type="checkbox"
                          checked={editData.es_inicial}
                          onChange={(e) => setEditData({ ...editData, es_inicial: e.target.checked })}
                        />
                        <span className={styles.toggleTrack} />
                      </label>
                    </div>
                    <div className={styles.formField}>
                      <label>Final</label>
                      <label className={styles.toggle}>
                        <input
                          type="checkbox"
                          checked={editData.es_final}
                          onChange={(e) => setEditData({ ...editData, es_final: e.target.checked })}
                        />
                        <span className={styles.toggleTrack} />
                      </label>
                    </div>
                  </div>
                  <div className={styles.formActions}>
                    <button className={styles.btnCancel} onClick={() => setEditingId(null)}>
                      <X size={14} /> Cancelar
                    </button>
                    <button className={styles.btnSave} onClick={handleUpdate} disabled={!editData.nombre}>
                      <Save size={14} /> Guardar
                    </button>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      ) : (
        <div className={styles.emptyState}>Sin estados definidos</div>
      )}
    </div>
  );
}
