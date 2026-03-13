import { useState, useEffect, useCallback } from 'react';
import { usePermisos } from '../contexts/PermisosContext';
import { rrhhAPI } from '../services/api';
import {
  Plus,
  Search,
  RotateCcw,
  ChevronLeft,
  ChevronRight,
  Users,
  Edit3,
  Trash2,
  User,
} from 'lucide-react';
import styles from './Empleados.module.css';

const ESTADOS = [
  { value: '', label: 'Todos' },
  { value: 'activo', label: 'Activo' },
  { value: 'licencia', label: 'Licencia' },
  { value: 'baja', label: 'Baja' },
];

const ESTADO_COLORS = {
  activo: 'statusActive',
  licencia: 'statusLicencia',
  baja: 'statusBaja',
};

export default function Empleados() {
  const { tienePermiso } = usePermisos();
  const puedeGestionar = tienePermiso('rrhh.gestionar');

  // --- State ---
  const [empleados, setEmpleados] = useState([]);
  const [loading, setLoading] = useState(true);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState('');
  const [estado, setEstado] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');

  // Modal state
  const [modalOpen, setModalOpen] = useState(false);
  const [editando, setEditando] = useState(null);
  const [formData, setFormData] = useState({});
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState(null);

  const PAGE_SIZE = 50;

  // --- Debounce search ---
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedSearch(search), 400);
    return () => clearTimeout(timer);
  }, [search]);

  // --- Fetch empleados ---
  const cargarEmpleados = useCallback(async () => {
    setLoading(true);
    try {
      const params = { page, page_size: PAGE_SIZE };
      if (debouncedSearch) params.search = debouncedSearch;
      if (estado) params.estado = estado;
      const { data } = await rrhhAPI.listarEmpleados(params);
      setEmpleados(data.items);
      setTotal(data.total);
    } catch {
      setEmpleados([]);
      setTotal(0);
    } finally {
      setLoading(false);
    }
  }, [page, debouncedSearch, estado]);

  useEffect(() => {
    cargarEmpleados();
  }, [cargarEmpleados]);

  // Reset page when filters change
  useEffect(() => {
    setPage(1);
  }, [debouncedSearch, estado]);

  const totalPages = Math.ceil(total / PAGE_SIZE);

  // --- Handlers ---
  const handleNuevo = () => {
    setEditando(null);
    setFormData({
      nombre: '',
      apellido: '',
      dni: '',
      cuil: '',
      legajo: '',
      fecha_ingreso: new Date().toISOString().split('T')[0],
      puesto: '',
      area: '',
      estado: 'activo',
      telefono: '',
      email_personal: '',
      domicilio: '',
      observaciones: '',
    });
    setFormError(null);
    setModalOpen(true);
  };

  const handleEditar = (emp) => {
    setEditando(emp);
    setFormData({
      nombre: emp.nombre || '',
      apellido: emp.apellido || '',
      dni: emp.dni || '',
      cuil: emp.cuil || '',
      legajo: emp.legajo || '',
      fecha_ingreso: emp.fecha_ingreso || '',
      fecha_egreso: emp.fecha_egreso || '',
      puesto: emp.puesto || '',
      area: emp.area || '',
      estado: emp.estado || 'activo',
      telefono: emp.telefono || '',
      email_personal: emp.email_personal || '',
      domicilio: emp.domicilio || '',
      observaciones: emp.observaciones || '',
    });
    setFormError(null);
    setModalOpen(true);
  };

  const handleGuardar = async () => {
    setSaving(true);
    setFormError(null);
    try {
      if (editando) {
        await rrhhAPI.actualizarEmpleado(editando.id, formData);
      } else {
        await rrhhAPI.crearEmpleado(formData);
      }
      setModalOpen(false);
      cargarEmpleados();
    } catch (err) {
      const msg = err.response?.data?.detail || 'Error al guardar';
      setFormError(msg);
    } finally {
      setSaving(false);
    }
  };

  const handleEliminar = async (emp) => {
    if (!puedeGestionar) return;
    try {
      await rrhhAPI.eliminarEmpleado(emp.id);
      cargarEmpleados();
    } catch {
      // silently handled
    }
  };

  const handleField = (field, value) => {
    setFormData((prev) => ({ ...prev, [field]: value }));
  };

  return (
    <div className={styles.container}>
      {/* Header */}
      <div className={styles.header}>
        <div className={styles.headerTitle}>
          <Users size={24} />
          <h1>Empleados</h1>
          <span className={styles.badge}>{total}</span>
        </div>
        {puedeGestionar && (
          <button className={styles.btnCreate} onClick={handleNuevo}>
            <Plus size={16} />
            Nuevo Empleado
          </button>
        )}
      </div>

      {/* Filters */}
      <div className={styles.filters}>
        <div className={styles.searchBox}>
          <Search size={16} />
          <input
            type="text"
            placeholder="Buscar por nombre, DNI, legajo..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className={styles.input}
          />
        </div>
        <select
          value={estado}
          onChange={(e) => setEstado(e.target.value)}
          className={styles.select}
        >
          {ESTADOS.map((e) => (
            <option key={e.value} value={e.value}>
              {e.label}
            </option>
          ))}
        </select>
        <button
          className={styles.btnRefresh}
          onClick={() => { setSearch(''); setEstado(''); setPage(1); }}
          title="Limpiar filtros"
        >
          <RotateCcw size={16} />
        </button>
      </div>

      {/* Table */}
      <div className={styles.tableWrapper}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th>Legajo</th>
              <th>Nombre</th>
              <th>DNI</th>
              <th>Puesto</th>
              <th>Area</th>
              <th>Estado</th>
              <th>Ingreso</th>
              {puedeGestionar && <th>Acciones</th>}
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={puedeGestionar ? 8 : 7} className={styles.loadingCell}>
                  Cargando...
                </td>
              </tr>
            ) : empleados.length === 0 ? (
              <tr>
                <td colSpan={puedeGestionar ? 8 : 7} className={styles.emptyCell}>
                  No se encontraron empleados
                </td>
              </tr>
            ) : (
              empleados.map((emp) => (
                <tr key={emp.id} className={styles.row}>
                  <td className={styles.legajo}>{emp.legajo}</td>
                  <td>
                    <div className={styles.nameCell}>
                      <User size={14} />
                      {emp.apellido}, {emp.nombre}
                    </div>
                  </td>
                  <td>{emp.dni}</td>
                  <td>{emp.puesto || '-'}</td>
                  <td>{emp.area || '-'}</td>
                  <td>
                    <span className={`${styles.statusBadge} ${styles[ESTADO_COLORS[emp.estado]] || ''}`}>
                      {emp.estado}
                    </span>
                  </td>
                  <td>{emp.fecha_ingreso}</td>
                  {puedeGestionar && (
                    <td className={styles.actions}>
                      <button
                        onClick={() => handleEditar(emp)}
                        className={styles.btnEdit}
                        title="Editar"
                      >
                        <Edit3 size={14} />
                      </button>
                      <button
                        onClick={() => handleEliminar(emp)}
                        className={styles.btnDanger}
                        title="Desactivar"
                      >
                        <Trash2 size={14} />
                      </button>
                    </td>
                  )}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className={styles.pagination}>
          <button
            disabled={page <= 1}
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            className={styles.btnPage}
          >
            <ChevronLeft size={16} />
          </button>
          <span className={styles.pageInfo}>
            {page} / {totalPages}
          </span>
          <button
            disabled={page >= totalPages}
            onClick={() => setPage((p) => p + 1)}
            className={styles.btnPage}
          >
            <ChevronRight size={16} />
          </button>
        </div>
      )}

      {/* Modal */}
      {modalOpen && (
        <div className="modal-overlay-tesla" onClick={() => setModalOpen(false)}>
          <div className="modal-tesla lg" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header-tesla">
              <h2 className="modal-title-tesla">{editando ? 'Editar Empleado' : 'Nuevo Empleado'}</h2>
              <button className="btn-close-tesla" onClick={() => setModalOpen(false)}>✕</button>
            </div>

            <div className="modal-body-tesla">
              {formError && <div className={styles.formError}>{formError}</div>}

              <div className={styles.formGrid}>
                <div className={styles.formGroup}>
                  <label>Nombre *</label>
                  <input
                    className={styles.input}
                    value={formData.nombre}
                    onChange={(e) => handleField('nombre', e.target.value)}
                  />
                </div>
                <div className={styles.formGroup}>
                  <label>Apellido *</label>
                  <input
                    className={styles.input}
                    value={formData.apellido}
                    onChange={(e) => handleField('apellido', e.target.value)}
                  />
                </div>
                <div className={styles.formGroup}>
                  <label>DNI *</label>
                  <input
                    className={styles.input}
                    value={formData.dni}
                    onChange={(e) => handleField('dni', e.target.value)}
                  />
                </div>
                <div className={styles.formGroup}>
                  <label>CUIL</label>
                  <input
                    className={styles.input}
                    value={formData.cuil}
                    onChange={(e) => handleField('cuil', e.target.value)}
                  />
                </div>
                <div className={styles.formGroup}>
                  <label>Legajo *</label>
                  <input
                    className={styles.input}
                    value={formData.legajo}
                    onChange={(e) => handleField('legajo', e.target.value)}
                  />
                </div>
                <div className={styles.formGroup}>
                  <label>Fecha Ingreso *</label>
                  <input
                    type="date"
                    className={styles.input}
                    value={formData.fecha_ingreso}
                    onChange={(e) => handleField('fecha_ingreso', e.target.value)}
                  />
                </div>
                {editando && (
                  <div className={styles.formGroup}>
                    <label>Fecha Egreso</label>
                    <input
                      type="date"
                      className={styles.input}
                      value={formData.fecha_egreso || ''}
                      onChange={(e) => handleField('fecha_egreso', e.target.value || null)}
                    />
                  </div>
                )}
                <div className={styles.formGroup}>
                  <label>Puesto</label>
                  <input
                    className={styles.input}
                    value={formData.puesto}
                    onChange={(e) => handleField('puesto', e.target.value)}
                  />
                </div>
                <div className={styles.formGroup}>
                  <label>Area</label>
                  <input
                    className={styles.input}
                    value={formData.area}
                    onChange={(e) => handleField('area', e.target.value)}
                  />
                </div>
                <div className={styles.formGroup}>
                  <label>Estado</label>
                  <select
                    className={styles.select}
                    value={formData.estado}
                    onChange={(e) => handleField('estado', e.target.value)}
                  >
                    <option value="activo">Activo</option>
                    <option value="licencia">Licencia</option>
                    <option value="baja">Baja</option>
                  </select>
                </div>
                <div className={styles.formGroup}>
                  <label>Teléfono</label>
                  <input
                    className={styles.input}
                    value={formData.telefono}
                    onChange={(e) => handleField('telefono', e.target.value)}
                  />
                </div>
                <div className={styles.formGroup}>
                  <label>Email Personal</label>
                  <input
                    type="email"
                    className={styles.input}
                    value={formData.email_personal}
                    onChange={(e) => handleField('email_personal', e.target.value)}
                  />
                </div>
                <div className={`${styles.formGroup} ${styles.formGroupFull}`}>
                  <label>Domicilio</label>
                  <input
                    className={styles.input}
                    value={formData.domicilio}
                    onChange={(e) => handleField('domicilio', e.target.value)}
                  />
                </div>
                <div className={`${styles.formGroup} ${styles.formGroupFull}`}>
                  <label>Observaciones</label>
                  <textarea
                    className={styles.textarea}
                    value={formData.observaciones}
                    onChange={(e) => handleField('observaciones', e.target.value)}
                    rows={3}
                  />
                </div>
              </div>
            </div>

            <div className="modal-footer-tesla">
              <button
                className={styles.btnCancel}
                onClick={() => setModalOpen(false)}
              >
                Cancelar
              </button>
              <button
                className={styles.btnSave}
                onClick={handleGuardar}
                disabled={saving}
              >
                {saving ? 'Guardando...' : 'Guardar'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
