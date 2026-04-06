import { useState, useEffect, useCallback } from 'react';
import { empresasAPI } from '../services/api';
import { Plus, Edit3, Check, X } from 'lucide-react';
import styles from './PanelEmpresas.module.css';

const EMPTY_FORM = {
  nombre: '', razon_social: '', cuit: '', direccion: '',
  telefono: '', email: '', notas: '', activo: true, orden: 0,
};

export default function PanelEmpresas() {
  const [empresas, setEmpresas] = useState([]);
  const [loading, setLoading] = useState(false);
  const [form, setForm] = useState({ ...EMPTY_FORM });
  const [editando, setEditando] = useState(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  const cargar = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await empresasAPI.listar();
      setEmpresas(Array.isArray(data) ? data : []);
    } catch {
      setEmpresas([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    cargar();
  }, [cargar]);

  const handleSubmit = async () => {
    if (!form.nombre.trim()) return;
    setSaving(true);
    setError(null);
    try {
      if (editando) {
        await empresasAPI.actualizar(editando.id, form);
      } else {
        await empresasAPI.crear(form);
      }
      setForm({ ...EMPTY_FORM });
      setEditando(null);
      cargar();
    } catch (err) {
      setError(err.response?.data?.detail || 'Error al guardar');
    } finally {
      setSaving(false);
    }
  };

  const handleEdit = (emp) => {
    setEditando(emp);
    setForm({
      nombre: emp.nombre || '',
      razon_social: emp.razon_social || '',
      cuit: emp.cuit || '',
      direccion: emp.direccion || '',
      telefono: emp.telefono || '',
      email: emp.email || '',
      notas: emp.notas || '',
      activo: emp.activo,
      orden: emp.orden || 0,
    });
    setError(null);
  };

  const handleCancel = () => {
    setEditando(null);
    setForm({ ...EMPTY_FORM });
    setError(null);
  };

  const handleToggle = async (emp) => {
    try {
      await empresasAPI.actualizar(emp.id, { ...emp, activo: !emp.activo });
      cargar();
    } catch {
      setError('Error al cambiar estado');
    }
  };

  return (
    <div className={styles.container}>
      <h2 className={styles.title}>Empresas del Grupo</h2>
      <p className={styles.desc}>
        Configurá las empresas propias. Los empleados se asignan a una empresa para diferenciar sueldos, cuentas bancarias y datos fiscales.
      </p>

      {error && <div className={styles.error}>{error}</div>}

      {/* Form */}
      <div className={styles.form}>
        <div className={styles.formRow}>
          <div className={styles.formGroup}>
            <label>Nombre *</label>
            <input
              className={styles.input}
              value={form.nombre}
              onChange={(e) => setForm({ ...form, nombre: e.target.value })}
              placeholder="Ej: Pastoriza"
              maxLength={100}
            />
          </div>
          <div className={styles.formGroup}>
            <label>Razón Social</label>
            <input
              className={styles.input}
              value={form.razon_social}
              onChange={(e) => setForm({ ...form, razon_social: e.target.value })}
              placeholder="Ej: Pastoriza S.A."
              maxLength={255}
            />
          </div>
          <div className={styles.formGroup}>
            <label>CUIT</label>
            <input
              className={styles.input}
              value={form.cuit}
              onChange={(e) => setForm({ ...form, cuit: e.target.value })}
              placeholder="30-12345678-9"
              maxLength={20}
            />
          </div>
        </div>
        <div className={styles.formRow}>
          <div className={styles.formGroup}>
            <label>Dirección</label>
            <input
              className={styles.input}
              value={form.direccion}
              onChange={(e) => setForm({ ...form, direccion: e.target.value })}
              maxLength={500}
            />
          </div>
          <div className={styles.formGroup}>
            <label>Teléfono</label>
            <input
              className={styles.input}
              value={form.telefono}
              onChange={(e) => setForm({ ...form, telefono: e.target.value })}
              maxLength={50}
            />
          </div>
          <div className={styles.formGroup}>
            <label>Email</label>
            <input
              className={styles.input}
              value={form.email}
              onChange={(e) => setForm({ ...form, email: e.target.value })}
              maxLength={255}
            />
          </div>
        </div>
        <div className={styles.formActions}>
          <button
            className={styles.btnSave}
            onClick={handleSubmit}
            disabled={saving || !form.nombre.trim()}
          >
            {saving ? '...' : editando ? 'Actualizar' : <><Plus size={14} /> Crear</>}
          </button>
          {editando && (
            <button className={styles.btnCancel} onClick={handleCancel}>
              <X size={14} /> Cancelar
            </button>
          )}
        </div>
      </div>

      {/* Table */}
      {loading ? (
        <div className={styles.loading}>Cargando empresas...</div>
      ) : empresas.length === 0 ? (
        <div className={styles.empty}>No hay empresas configuradas</div>
      ) : (
        <div className={styles.tableWrapper}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Nombre</th>
                <th>Razón Social</th>
                <th>CUIT</th>
                <th>Dirección</th>
                <th>Estado</th>
                <th>Acciones</th>
              </tr>
            </thead>
            <tbody>
              {empresas.map((emp) => (
                <tr key={emp.id}>
                  <td><strong>{emp.nombre}</strong></td>
                  <td>{emp.razon_social || '-'}</td>
                  <td>{emp.cuit || '-'}</td>
                  <td>{emp.direccion || '-'}</td>
                  <td>
                    <span className={emp.activo ? styles.statusActive : styles.statusInactive}>
                      {emp.activo ? 'Activo' : 'Inactivo'}
                    </span>
                  </td>
                  <td className={styles.actions}>
                    <button className={styles.btnEdit} onClick={() => handleEdit(emp)} title="Editar" aria-label="Editar empresa">
                      <Edit3 size={14} />
                    </button>
                    <button
                      className={emp.activo ? styles.btnDeactivate : styles.btnEdit}
                      onClick={() => handleToggle(emp)}
                      title={emp.activo ? 'Desactivar' : 'Activar'}
                      aria-label={emp.activo ? 'Desactivar empresa' : 'Activar empresa'}
                    >
                      {emp.activo ? <X size={14} /> : <Check size={14} />}
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
