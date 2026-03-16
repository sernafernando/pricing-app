import { useState, useEffect, useCallback } from 'react';
import { usePermisos } from '../contexts/PermisosContext';
import { sectoresAPI } from '../services/api';
import api from '../services/api';
import {
  Settings,
  Plus,
  Pencil,
  X,
  Save,
  Users,
  Layers,
  GitBranch,
  FileText,
  UserPlus,
  Trash2,
  Lock,
} from 'lucide-react';
import WorkflowEditor from '../components/WorkflowEditor';
import { registrarPagina } from '../registry/tabRegistry';
import styles from './TicketsAdmin.module.css';

registrarPagina({
  pagePath: '/tickets/admin',
  pageLabel: 'Tickets Admin',
  tabs: [
    { tabKey: 'sectores', label: 'Sectores' },
    { tabKey: 'usuarios', label: 'Usuarios por Sector' },
    { tabKey: 'tipos', label: 'Tipos de Ticket' },
    { tabKey: 'workflows', label: 'Workflows' },
  ],
});

const formatDate = (dateStr) => {
  if (!dateStr) return '-';
  const d = new Date(dateStr);
  return d.toLocaleDateString('es-AR', {
    day: '2-digit',
    month: '2-digit',
    year: '2-digit',
  });
};

// ── Tab: Sectores ───────────────────────────────────────────────
function TabSectores() {
  const [sectores, setSectores] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);
  const [formOpen, setFormOpen] = useState(false);
  const [editingId, setEditingId] = useState(null);
  const [form, setForm] = useState({
    nombre: '',
    codigo: '',
    descripcion: '',
    color: '#3b82f6',
    activo: true,
  });

  const cargar = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await sectoresAPI.listar({ activos_solo: false });
      setSectores(Array.isArray(data) ? data : []);
    } catch {
      setError('Error al cargar sectores');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    cargar();
  }, [cargar]);

  const resetForm = () => {
    setForm({
      nombre: '',
      codigo: '',
      descripcion: '',
      color: '#3b82f6',
      activo: true,
    });
    setEditingId(null);
    setFormOpen(false);
  };

  const handleEdit = (sector) => {
    setForm({
      nombre: sector.nombre,
      codigo: sector.codigo,
      descripcion: sector.descripcion || '',
      color: sector.color || '#3b82f6',
      activo: sector.activo,
    });
    setEditingId(sector.id);
    setFormOpen(true);
  };

  const handleSubmit = async () => {
    setError(null);
    setSuccess(null);
    try {
      if (editingId) {
        await sectoresAPI.actualizar(editingId, {
          nombre: form.nombre,
          descripcion: form.descripcion || null,
          color: form.color,
          activo: form.activo,
        });
        setSuccess('Sector actualizado');
      } else {
        await sectoresAPI.crear({
          nombre: form.nombre,
          codigo: form.codigo,
          descripcion: form.descripcion || null,
          color: form.color,
          activo: form.activo,
          configuracion: {},
        });
        setSuccess('Sector creado');
      }
      resetForm();
      cargar();
    } catch (err) {
      const detail = err.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : 'Error al guardar sector');
    }
  };

  return (
    <div className={styles.section}>
      <div className={styles.sectionHeader}>
        <h2 className={styles.sectionTitle}>Sectores</h2>
        {!formOpen && (
          <button className={styles.btnCreate} onClick={() => setFormOpen(true)}>
            <Plus size={16} />
            Crear Sector
          </button>
        )}
      </div>

      {error && <div className={`${styles.message} ${styles.messageError}`}>{error}</div>}
      {success && <div className={`${styles.message} ${styles.messageSuccess}`}>{success}</div>}

      {formOpen && (
        <div className={styles.formCard}>
          <div className={styles.formGrid}>
            <div className={styles.formField}>
              <label htmlFor="sector-nombre">Nombre</label>
              <input
                id="sector-nombre"
                className={styles.input}
                value={form.nombre}
                onChange={(e) => setForm({ ...form, nombre: e.target.value })}
                placeholder="Ej: Pricing"
              />
            </div>
            {!editingId && (
              <div className={styles.formField}>
                <label htmlFor="sector-codigo">Código</label>
                <input
                  id="sector-codigo"
                  className={styles.input}
                  value={form.codigo}
                  onChange={(e) => setForm({ ...form, codigo: e.target.value })}
                  placeholder="Ej: pricing"
                />
              </div>
            )}
            <div className={styles.formField}>
              <label htmlFor="sector-desc">Descripción</label>
              <input
                id="sector-desc"
                className={styles.input}
                value={form.descripcion}
                onChange={(e) => setForm({ ...form, descripcion: e.target.value })}
                placeholder="Descripción breve"
              />
            </div>
            <div className={styles.formField}>
              <label>Color</label>
              <div className={styles.colorField}>
                <input
                  type="color"
                  className={styles.colorPicker}
                  value={form.color}
                  onChange={(e) => setForm({ ...form, color: e.target.value })}
                />
                <span style={{ fontSize: 'var(--font-xs)', color: 'var(--cf-text-tertiary)' }}>
                  {form.color}
                </span>
              </div>
            </div>
            <div className={styles.formField}>
              <label>Activo</label>
              <label className={styles.toggle}>
                <input
                  type="checkbox"
                  checked={form.activo}
                  onChange={(e) => setForm({ ...form, activo: e.target.checked })}
                />
                <span className={styles.toggleTrack} />
              </label>
            </div>
          </div>
          <div className={styles.formActions}>
            <button className={styles.btnCancel} onClick={resetForm}>
              <X size={14} />
              Cancelar
            </button>
            <button
              className={styles.btnSave}
              onClick={handleSubmit}
              disabled={!form.nombre || (!editingId && !form.codigo)}
            >
              <Save size={14} />
              {editingId ? 'Guardar' : 'Crear'}
            </button>
          </div>
        </div>
      )}

      {loading ? (
        <div className={styles.loadingState}>Cargando sectores...</div>
      ) : sectores.length === 0 ? (
        <div className={styles.emptyState}>No hay sectores configurados</div>
      ) : (
        <div className={styles.tableWrapper}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Nombre</th>
                <th>Código</th>
                <th>Color</th>
                <th>Activo</th>
                <th>Acciones</th>
              </tr>
            </thead>
            <tbody>
              {sectores.map((s) => (
                <tr key={s.id}>
                  <td>{s.nombre}</td>
                  <td>
                    <code>{s.codigo}</code>
                  </td>
                  <td>
                    <span
                      className={styles.colorDot}
                      style={{ backgroundColor: s.color || '#6b7280' }}
                    />
                  </td>
                  <td>
                    <span className={s.activo ? styles.badgeActivo : styles.badgeInactivo}>
                      {s.activo ? 'Activo' : 'Inactivo'}
                    </span>
                  </td>
                  <td>
                    <div className={styles.actions}>
                      <button
                        className={styles.btnEdit}
                        onClick={() => handleEdit(s)}
                        aria-label={`Editar ${s.nombre}`}
                      >
                        <Pencil size={14} />
                      </button>
                    </div>
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

// ── Tab: Usuarios por Sector ────────────────────────────────────
function TabUsuarios() {
  const [sectores, setSectores] = useState([]);
  const [sectorId, setSectorId] = useState('');
  const [usuarios, setUsuarios] = useState([]);
  const [allUsers, setAllUsers] = useState([]);
  const [loading, setLoading] = useState(false);
  const [loadingUsers, setLoadingUsers] = useState(false);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);
  const [addingUser, setAddingUser] = useState(false);
  const [selectedUserId, setSelectedUserId] = useState('');

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

  useEffect(() => {
    if (!sectorId) {
      setUsuarios([]);
      return;
    }
    const fetchUsuarios = async () => {
      setLoading(true);
      setError(null);
      try {
        const { data } = await sectoresAPI.listarUsuarios(sectorId);
        setUsuarios(Array.isArray(data) ? data : []);
      } catch {
        setError('Error al cargar usuarios del sector');
        setUsuarios([]);
      } finally {
        setLoading(false);
      }
    };
    fetchUsuarios();
  }, [sectorId]);

  const loadAllUsers = async () => {
    if (allUsers.length > 0) {
      setAddingUser(true);
      return;
    }
    setLoadingUsers(true);
    try {
      const { data } = await api.get('/usuarios');
      setAllUsers(Array.isArray(data) ? data : []);
      setAddingUser(true);
    } catch {
      setError('Error al cargar lista de usuarios');
    } finally {
      setLoadingUsers(false);
    }
  };

  const handleAddUser = async () => {
    if (!selectedUserId || !sectorId) return;
    setError(null);
    setSuccess(null);
    try {
      await sectoresAPI.agregarUsuario(sectorId, { usuario_id: Number(selectedUserId) });
      setSuccess('Usuario agregado al sector');
      setAddingUser(false);
      setSelectedUserId('');
      // Reload
      const { data } = await sectoresAPI.listarUsuarios(sectorId);
      setUsuarios(Array.isArray(data) ? data : []);
    } catch (err) {
      const detail = err.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : 'Error al agregar usuario');
    }
  };

  const handleRemoveUser = async (usuarioId) => {
    setError(null);
    setSuccess(null);
    try {
      await sectoresAPI.removerUsuario(sectorId, usuarioId);
      setSuccess('Usuario removido del sector');
      const { data } = await sectoresAPI.listarUsuarios(sectorId);
      setUsuarios(Array.isArray(data) ? data : []);
    } catch {
      setError('Error al remover usuario');
    }
  };

  // Filter out users already in sector
  const assignedUserIds = new Set(usuarios.map((u) => u.usuario?.id));
  const availableUsers = allUsers.filter((u) => !assignedUserIds.has(u.id));

  return (
    <div className={styles.section}>
      <div className={styles.sectionHeader}>
        <h2 className={styles.sectionTitle}>Usuarios por Sector</h2>
      </div>

      {error && <div className={`${styles.message} ${styles.messageError}`}>{error}</div>}
      {success && <div className={`${styles.message} ${styles.messageSuccess}`}>{success}</div>}

      <div className={styles.selectorRow}>
        <label htmlFor="sector-usuario-sel">Sector</label>
        <select
          id="sector-usuario-sel"
          className={styles.select}
          value={sectorId}
          onChange={(e) => {
            setSectorId(e.target.value);
            setAddingUser(false);
            setSuccess(null);
            setError(null);
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
            onClick={loadAllUsers}
            disabled={loadingUsers}
          >
            <UserPlus size={16} />
            {loadingUsers ? 'Cargando...' : 'Agregar Usuario'}
          </button>
        )}
      </div>

      {addingUser && (
        <div className={styles.formCard}>
          <div className={styles.selectorRow}>
            <label htmlFor="user-pick">Usuario</label>
            <select
              id="user-pick"
              className={styles.select}
              value={selectedUserId}
              onChange={(e) => setSelectedUserId(e.target.value)}
            >
              <option value="">Seleccionar usuario...</option>
              {availableUsers.map((u) => (
                <option key={u.id} value={u.id}>
                  {u.nombre} ({u.username})
                </option>
              ))}
            </select>
            <button
              className={styles.btnSave}
              onClick={handleAddUser}
              disabled={!selectedUserId}
            >
              <Plus size={14} />
              Agregar
            </button>
            <button className={styles.btnCancel} onClick={() => setAddingUser(false)}>
              <X size={14} />
              Cancelar
            </button>
          </div>
        </div>
      )}

      {!sectorId ? (
        <div className={styles.emptyState}>Seleccioná un sector para ver sus usuarios</div>
      ) : loading ? (
        <div className={styles.loadingState}>Cargando usuarios...</div>
      ) : usuarios.length === 0 ? (
        <div className={styles.emptyState}>No hay usuarios asignados a este sector</div>
      ) : (
        <div>
          {usuarios.map((su) => (
            <div key={su.id} className={styles.userCard}>
              <div className={styles.userInfo}>
                <span className={styles.userName}>
                  {su.usuario?.nombre || `Usuario #${su.usuario_id || su.id}`}
                </span>
                <span className={styles.userMeta}>
                  Asignado: {formatDate(su.created_at)}
                  {su.usuario?.email ? ` | ${su.usuario.email}` : ''}
                </span>
              </div>
              <button
                className={styles.btnRemove}
                onClick={() => handleRemoveUser(su.usuario?.id || su.usuario_id)}
                aria-label={`Remover ${su.usuario?.nombre || 'usuario'}`}
              >
                <Trash2 size={14} />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Tab: Tipos de Ticket ────────────────────────────────────────
function TabTiposTicket() {
  const [sectores, setSectores] = useState([]);
  const [sectorId, setSectorId] = useState('');
  const [tipos, setTipos] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

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

  useEffect(() => {
    if (!sectorId) {
      setTipos([]);
      return;
    }
    const fetchTipos = async () => {
      setLoading(true);
      setError(null);
      try {
        const { data } = await sectoresAPI.listarTiposTicket(sectorId);
        setTipos(Array.isArray(data) ? data : []);
      } catch {
        setError('Error al cargar tipos de ticket');
        setTipos([]);
      } finally {
        setLoading(false);
      }
    };
    fetchTipos();
  }, [sectorId]);

  const countFields = (schema) => {
    if (!schema || typeof schema !== 'object') return 0;
    return Object.keys(schema).length;
  };

  return (
    <div className={styles.section}>
      <div className={styles.sectionHeader}>
        <h2 className={styles.sectionTitle}>Tipos de Ticket</h2>
      </div>

      {error && <div className={`${styles.message} ${styles.messageError}`}>{error}</div>}

      <div className={styles.selectorRow}>
        <label htmlFor="sector-tipo-sel">Sector</label>
        <select
          id="sector-tipo-sel"
          className={styles.select}
          value={sectorId}
          onChange={(e) => setSectorId(e.target.value)}
        >
          <option value="">Seleccionar sector...</option>
          {sectores.map((s) => (
            <option key={s.id} value={s.id}>
              {s.nombre}
            </option>
          ))}
        </select>
      </div>

      {!sectorId ? (
        <div className={styles.emptyState}>Seleccioná un sector para ver sus tipos de ticket</div>
      ) : loading ? (
        <div className={styles.loadingState}>Cargando tipos...</div>
      ) : tipos.length === 0 ? (
        <div className={styles.emptyState}>
          No hay tipos de ticket para este sector
        </div>
      ) : (
        <div className={styles.tableWrapper}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Nombre</th>
                <th>Código</th>
                <th>Color</th>
                <th>Workflow</th>
                <th>Campos</th>
              </tr>
            </thead>
            <tbody>
              {tipos.map((t) => (
                <tr key={t.id}>
                  <td>{t.nombre}</td>
                  <td>
                    <code>{t.codigo}</code>
                  </td>
                  <td>
                    {t.color ? (
                      <span
                        className={styles.colorDot}
                        style={{ backgroundColor: t.color }}
                      />
                    ) : (
                      '-'
                    )}
                  </td>
                  <td>
                    {t.workflow_id ? (
                      <span className={styles.fieldCount}>#{t.workflow_id}</span>
                    ) : (
                      <span className={styles.fieldCount}>Default</span>
                    )}
                  </td>
                  <td>
                    <span className={styles.fieldCount}>
                      {countFields(t.schema_campos)} campos
                    </span>
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

// ── Main Component ──────────────────────────────────────────────
export default function TicketsAdmin() {
  const { tienePermiso, loading: permLoading } = usePermisos();
  const [tabActiva, setTabActiva] = useState('sectores');

  if (permLoading) {
    return (
      <div className={styles.container}>
        <div className={styles.loadingState}>Cargando permisos...</div>
      </div>
    );
  }

  if (!tienePermiso('tickets.admin')) {
    return (
      <div className={styles.container}>
        <div className={styles.denied}>
          <Lock size={32} />
          <p>No tenés permisos para acceder a la configuración de tickets.</p>
        </div>
      </div>
    );
  }

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <Settings size={24} />
        <h1>Configuración de Tickets</h1>
      </div>

      <div className={styles.tabs}>
        {tienePermiso('tickets.admin') && (
          <button
            className={`${styles.tab} ${tabActiva === 'sectores' ? styles.tabActive : ''}`}
            onClick={() => setTabActiva('sectores')}
          >
            <Layers size={14} />
            Sectores
          </button>
        )}
        {tienePermiso('tickets.admin') && (
          <button
            className={`${styles.tab} ${tabActiva === 'usuarios' ? styles.tabActive : ''}`}
            onClick={() => setTabActiva('usuarios')}
          >
            <Users size={14} />
            Usuarios
          </button>
        )}
        {tienePermiso('tickets.admin') && (
          <button
            className={`${styles.tab} ${tabActiva === 'tipos' ? styles.tabActive : ''}`}
            onClick={() => setTabActiva('tipos')}
          >
            <FileText size={14} />
            Tipos de Ticket
          </button>
        )}
        {tienePermiso('tickets.admin') && (
          <button
            className={`${styles.tab} ${tabActiva === 'workflows' ? styles.tabActive : ''}`}
            onClick={() => setTabActiva('workflows')}
          >
            <GitBranch size={14} />
            Workflows
          </button>
        )}
      </div>

      {tabActiva === 'sectores' && tienePermiso('tickets.admin') && <TabSectores />}
      {tabActiva === 'usuarios' && tienePermiso('tickets.admin') && <TabUsuarios />}
      {tabActiva === 'tipos' && tienePermiso('tickets.admin') && <TabTiposTicket />}
      {tabActiva === 'workflows' && tienePermiso('tickets.admin') && <WorkflowEditor />}
    </div>
  );
}
