import { useState } from 'react';
import { Plus, Edit3, Check, X } from 'lucide-react';
import api from '../services/api';
import { useTiendasOficiales } from '../hooks/useTiendasOficiales';
import styles from './PanelTiendasOficiales.module.css';

const EMPTY_FORM = { store_id: '', nombre: '', clave: '', orden: 0, activa: true };

const errorMessage = (err) =>
  err?.response?.data?.detail || err?.response?.data?.error?.message || 'Error al guardar';

/**
 * Admin panel: names (and order / state) of the MercadoLibre official stores,
 * keyed by `official_store_id`. A `clave` ties code to a store (e.g. `tplink`
 * for the TP-Link dashboard); several ids may share one when ML changes it.
 */
export default function PanelTiendasOficiales() {
  const { tiendas, loading, reload } = useTiendasOficiales();
  const [form, setForm] = useState({ ...EMPTY_FORM });
  const [editando, setEditando] = useState(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  const resetForm = () => {
    setForm({ ...EMPTY_FORM });
    setEditando(null);
  };

  const handleSubmit = async () => {
    setSaving(true);
    setError(null);
    const clave = form.clave.trim() || null;
    const orden = Number(form.orden) || 0;
    try {
      if (editando) {
        await api.put(`/tiendas-oficiales/${editando.store_id}`, {
          nombre: form.nombre,
          clave,
          orden,
          activa: form.activa,
        });
      } else {
        await api.post('/tiendas-oficiales', {
          store_id: Number(form.store_id),
          nombre: form.nombre,
          clave,
          orden,
          activa: form.activa,
        });
      }
      resetForm();
      await reload();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  const handleEdit = (tienda) => {
    setEditando(tienda);
    setForm({
      store_id: String(tienda.store_id),
      nombre: tienda.nombre,
      clave: tienda.clave || '',
      orden: tienda.orden,
      activa: tienda.activa,
    });
    setError(null);
  };

  const handleToggle = async (tienda) => {
    setError(null);
    try {
      await api.put(`/tiendas-oficiales/${tienda.store_id}`, { activa: !tienda.activa });
      await reload();
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const canSubmit = !saving && form.nombre.trim() !== '' && (editando || Number(form.store_id) > 0);

  return (
    <div className={styles.container}>
      <h2 className={styles.title}>Tiendas Oficiales</h2>
      <p className={styles.desc}>
        Definí el nombre con el que se muestra cada tienda oficial de MercadoLibre según su ID. La clave
        (opcional) vincula una tienda con funciones del sistema, por ejemplo <code>tplink</code> para el
        dashboard de TP-Link; varios IDs pueden compartir la misma clave. Una tienda inactiva deja de
        ofrecerse en los filtros pero sus ventas siguen mostrando su nombre.
      </p>

      {error && <div className={styles.error}>{error}</div>}

      <div className={styles.form}>
        <div className={styles.formRow}>
          <div className={styles.formGroup}>
            <label htmlFor="tienda-store-id">ID de tienda (ML)</label>
            <input
              id="tienda-store-id"
              type="number"
              min="1"
              className={styles.input}
              value={form.store_id}
              onChange={(e) => setForm({ ...form, store_id: e.target.value })}
              disabled={Boolean(editando)}
            />
          </div>
          <div className={styles.formGroup}>
            <label htmlFor="tienda-nombre">Nombre</label>
            <input
              id="tienda-nombre"
              className={styles.input}
              value={form.nombre}
              onChange={(e) => setForm({ ...form, nombre: e.target.value })}
              maxLength={100}
            />
          </div>
          <div className={styles.formGroup}>
            <label htmlFor="tienda-clave">Clave</label>
            <input
              id="tienda-clave"
              className={styles.input}
              value={form.clave}
              onChange={(e) => setForm({ ...form, clave: e.target.value })}
              placeholder="Ej: tplink"
              maxLength={50}
            />
          </div>
          <div className={styles.formGroup}>
            <label htmlFor="tienda-orden">Orden</label>
            <input
              id="tienda-orden"
              type="number"
              className={styles.input}
              value={form.orden}
              onChange={(e) => setForm({ ...form, orden: e.target.value })}
            />
          </div>
          <label className={styles.checkRow}>
            <input
              type="checkbox"
              checked={form.activa}
              onChange={(e) => setForm({ ...form, activa: e.target.checked })}
            />
            Activa
          </label>
        </div>
        <div className={styles.formActions}>
          <button className={styles.btnSave} onClick={handleSubmit} disabled={!canSubmit}>
            {saving ? '...' : editando ? 'Actualizar' : (<><Plus size={14} /> Crear</>)}
          </button>
          {editando && (
            <button className={styles.btnCancel} onClick={resetForm}>
              <X size={14} /> Cancelar
            </button>
          )}
        </div>
      </div>

      {loading && tiendas.length === 0 ? (
        <div className={styles.loading}>Cargando tiendas...</div>
      ) : tiendas.length === 0 ? (
        <div className={styles.empty}>No hay tiendas configuradas</div>
      ) : (
        <div className={styles.tableWrapper}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>ID</th>
                <th>Nombre</th>
                <th>Clave</th>
                <th>Orden</th>
                <th>Estado</th>
                <th>Acciones</th>
              </tr>
            </thead>
            <tbody>
              {tiendas.map((tienda) => (
                <tr key={tienda.store_id}>
                  <td>{tienda.store_id}</td>
                  <td><strong>{tienda.nombre}</strong></td>
                  <td>{tienda.clave || '-'}</td>
                  <td>{tienda.orden}</td>
                  <td>
                    <span className={tienda.activa ? styles.statusActive : styles.statusInactive}>
                      {tienda.activa ? 'Activa' : 'Inactiva'}
                    </span>
                  </td>
                  <td className={styles.actions}>
                    <button
                      className={styles.btnEdit}
                      onClick={() => handleEdit(tienda)}
                      title="Editar"
                      aria-label="Editar tienda"
                    >
                      <Edit3 size={14} />
                    </button>
                    <button
                      className={tienda.activa ? styles.btnDeactivate : styles.btnEdit}
                      onClick={() => handleToggle(tienda)}
                      title={tienda.activa ? 'Desactivar' : 'Activar'}
                      aria-label={tienda.activa ? 'Desactivar tienda' : 'Activar tienda'}
                    >
                      {tienda.activa ? <X size={14} /> : <Check size={14} />}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
