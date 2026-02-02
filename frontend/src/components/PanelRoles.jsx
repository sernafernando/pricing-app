import { useState, useEffect } from 'react';
import axios from 'axios';
import adminStyles from '../pages/Admin.module.css';
import styles from './PanelPermisos.module.css';

const CATEGORIAS_NOMBRE = {
  productos: 'Productos',
  ventas_ml: 'Ventas MercadoLibre',
  ventas_fuera: 'Ventas Fuera de ML',
  ventas_tn: 'Ventas Tienda Nube',
  clientes: 'Clientes',
  reportes: 'Reportes',
  administracion: 'Administracion',
  configuracion: 'Configuracion'
};

export default function PanelRoles() {
  const [roles, setRoles] = useState([]);
  const [rolSeleccionado, setRolSeleccionado] = useState(null);
  const [permisosRol, setPermisosRol] = useState([]);
  const [catalogo, setCatalogo] = useState({});
  const [loading, setLoading] = useState(true);
  const [guardando, setGuardando] = useState(false);
  const [mensaje, setMensaje] = useState(null);

  // Estados para crear/editar rol
  const [mostrarFormRol, setMostrarFormRol] = useState(false);
  const [editandoRol, setEditandoRol] = useState(null);
  const [formRol, setFormRol] = useState({
    codigo: '',
    nombre: '',
    descripcion: '',
    orden: 0
  });

  // Estado para clonar rol
  const [mostrarClonar, setMostrarClonar] = useState(false);
  const [clonarData, setClonarData] = useState({
    nuevo_codigo: '',
    nuevo_nombre: '',
    descripcion: ''
  });

  const [busquedaPermiso, setBusquedaPermiso] = useState('');

  const API_URL = import.meta.env.VITE_API_URL;

  useEffect(() => {
    cargarDatos();
  }, []);

  const cargarDatos = async () => {
    try {
      const token = localStorage.getItem('token');
      const headers = { Authorization: `Bearer ${token}` };

      const [rolesRes, catalogoRes] = await Promise.all([
        axios.get(`${API_URL}/roles`, { headers }),
        axios.get(`${API_URL}/permisos/catalogo`, { headers })
      ]);

      setRoles(rolesRes.data);
      setCatalogo(catalogoRes.data || {});
    } catch (error) {
      console.error('Error cargando datos:', error);
      setMensaje({ tipo: 'error', texto: `Error al cargar datos: ${error.response?.data?.detail || error.message}` });
    } finally {
      setLoading(false);
    }
  };

  const seleccionarRol = async (rol) => {
    setRolSeleccionado(rol);
    setPermisosRol([]);

    if (rol.codigo === 'SUPERADMIN') {
      // SUPERADMIN tiene todos los permisos
      const todosPermisos = Object.values(catalogo).flat().map(p => p.codigo);
      setPermisosRol(todosPermisos);
      return;
    }

    try {
      const token = localStorage.getItem('token');
      const headers = { Authorization: `Bearer ${token}` };

      const res = await axios.get(`${API_URL}/roles/${rol.id}/permisos`, { headers });
      setPermisosRol(res.data.permisos.map(p => p.codigo));
    } catch (error) {
      console.error('Error cargando permisos del rol:', error);
      setMensaje({ tipo: 'error', texto: 'Error al cargar permisos del rol' });
    }
  };

  const togglePermisoRol = async (permisoCodigo) => {
    if (!rolSeleccionado || rolSeleccionado.codigo === 'SUPERADMIN') return;

    const tienePermiso = permisosRol.includes(permisoCodigo);
    const nuevosPermisos = tienePermiso
      ? permisosRol.filter(p => p !== permisoCodigo)
      : [...permisosRol, permisoCodigo];

    setPermisosRol(nuevosPermisos);
  };

  const guardarPermisosRol = async () => {
    if (!rolSeleccionado || rolSeleccionado.codigo === 'SUPERADMIN') return;

    setGuardando(true);
    try {
      const token = localStorage.getItem('token');
      const headers = { Authorization: `Bearer ${token}` };

      await axios.put(`${API_URL}/roles/${rolSeleccionado.id}/permisos`, {
        permisos: permisosRol
      }, { headers });

      setMensaje({ tipo: 'success', texto: 'Permisos guardados correctamente' });
      setTimeout(() => setMensaje(null), 3000);
    } catch (error) {
      console.error('Error guardando permisos:', error);
      setMensaje({ tipo: 'error', texto: error.response?.data?.detail || 'Error al guardar permisos' });
    } finally {
      setGuardando(false);
    }
  };

  const crearRol = async () => {
    if (!formRol.codigo || !formRol.nombre) {
      setMensaje({ tipo: 'error', texto: 'Codigo y nombre son requeridos' });
      return;
    }

    setGuardando(true);
    try {
      const token = localStorage.getItem('token');
      const headers = { Authorization: `Bearer ${token}` };

      await axios.post(`${API_URL}/roles`, formRol, { headers });

      setMensaje({ tipo: 'success', texto: 'Rol creado correctamente' });
      setMostrarFormRol(false);
      setFormRol({ codigo: '', nombre: '', descripcion: '', orden: 0 });
      cargarDatos();
      setTimeout(() => setMensaje(null), 3000);
    } catch (error) {
      console.error('Error creando rol:', error);
      setMensaje({ tipo: 'error', texto: error.response?.data?.detail || 'Error al crear rol' });
    } finally {
      setGuardando(false);
    }
  };

  const actualizarRol = async () => {
    if (!editandoRol) return;

    setGuardando(true);
    try {
      const token = localStorage.getItem('token');
      const headers = { Authorization: `Bearer ${token}` };

      await axios.patch(`${API_URL}/roles/${editandoRol.id}`, {
        nombre: formRol.nombre,
        descripcion: formRol.descripcion,
        orden: formRol.orden
      }, { headers });

      setMensaje({ tipo: 'success', texto: 'Rol actualizado correctamente' });
      setEditandoRol(null);
      setFormRol({ codigo: '', nombre: '', descripcion: '', orden: 0 });
      cargarDatos();
      setTimeout(() => setMensaje(null), 3000);
    } catch (error) {
      console.error('Error actualizando rol:', error);
      setMensaje({ tipo: 'error', texto: error.response?.data?.detail || 'Error al actualizar rol' });
    } finally {
      setGuardando(false);
    }
  };

  const eliminarRol = async (rol) => {
    if (rol.es_sistema) {
      setMensaje({ tipo: 'error', texto: 'No se pueden eliminar roles de sistema' });
      return;
    }

    if (!confirm(`¿Eliminar el rol "${rol.nombre}"? Esta accion no se puede deshacer.`)) {
      return;
    }

    try {
      const token = localStorage.getItem('token');
      const headers = { Authorization: `Bearer ${token}` };

      await axios.delete(`${API_URL}/roles/${rol.id}`, { headers });

      setMensaje({ tipo: 'success', texto: 'Rol eliminado correctamente' });
      if (rolSeleccionado?.id === rol.id) {
        setRolSeleccionado(null);
        setPermisosRol([]);
      }
      cargarDatos();
      setTimeout(() => setMensaje(null), 3000);
    } catch (error) {
      console.error('Error eliminando rol:', error);
      setMensaje({ tipo: 'error', texto: error.response?.data?.detail || 'Error al eliminar rol' });
    }
  };

  const clonarRol = async () => {
    if (!rolSeleccionado || !clonarData.nuevo_codigo || !clonarData.nuevo_nombre) {
      setMensaje({ tipo: 'error', texto: 'Codigo y nombre son requeridos' });
      return;
    }

    setGuardando(true);
    try {
      const token = localStorage.getItem('token');
      const headers = { Authorization: `Bearer ${token}` };

      await axios.post(`${API_URL}/roles/${rolSeleccionado.id}/clonar`, clonarData, { headers });

      setMensaje({ tipo: 'success', texto: 'Rol clonado correctamente' });
      setMostrarClonar(false);
      setClonarData({ nuevo_codigo: '', nuevo_nombre: '', descripcion: '' });
      cargarDatos();
      setTimeout(() => setMensaje(null), 3000);
    } catch (error) {
      console.error('Error clonando rol:', error);
      setMensaje({ tipo: 'error', texto: error.response?.data?.detail || 'Error al clonar rol' });
    } finally {
      setGuardando(false);
    }
  };

  const iniciarEdicion = (rol) => {
    setEditandoRol(rol);
    setFormRol({
      codigo: rol.codigo,
      nombre: rol.nombre,
      descripcion: rol.descripcion || '',
      orden: rol.orden
    });
    setMostrarFormRol(true);
  };

  if (loading) {
    return (
      <div className={adminStyles.section}>
        <div style={{ textAlign: 'center', padding: '40px' }}>
          Cargando roles y permisos...
        </div>
      </div>
    );
  }

  return (
    <div>
      {mensaje && (
        <div style={{
          padding: '12px 16px',
          marginBottom: '16px',
          borderRadius: '8px',
          background: mensaje.tipo === 'success' ? 'var(--success-bg)' : 'var(--error-bg)',
          color: mensaje.tipo === 'success' ? 'var(--success-text)' : 'var(--error-text)',
          fontWeight: '500'
        }}>
          {mensaje.texto}
        </div>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: '300px 1fr', gap: '20px' }}>
        {/* Panel izquierdo: Lista de roles */}
        <div className={adminStyles.section}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
            <h3 style={{ margin: 0 }}>Roles</h3>
            <button
              onClick={() => {
                setMostrarFormRol(true);
                setEditandoRol(null);
                setFormRol({ codigo: '', nombre: '', descripcion: '', orden: roles.length });
              }}
              className="btn-tesla outline-subtle-primary sm"
            >
              + Nuevo Rol
            </button>
          </div>

          {/* Form crear/editar rol */}
          {mostrarFormRol && (
            <div style={{
              background: 'var(--bg-secondary)',
              padding: '16px',
              borderRadius: '8px',
              marginBottom: '16px',
              border: '1px solid var(--border-primary)'
            }}>
              <h4 style={{ margin: '0 0 12px 0', color: 'var(--text-primary)' }}>
                {editandoRol ? 'Editar Rol' : 'Nuevo Rol'}
              </h4>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                <input
                  type="text"
                  placeholder="Codigo (ej: VENDEDOR)"
                  value={formRol.codigo}
                  onChange={(e) => setFormRol({ ...formRol, codigo: e.target.value.toUpperCase() })}
                  disabled={!!editandoRol}
                  style={{
                    padding: '8px',
                    borderRadius: '4px',
                    border: '1px solid var(--border-secondary)',
                    background: editandoRol ? 'var(--bg-tertiary)' : 'var(--bg-primary)',
                    color: 'var(--text-primary)'
                  }}
                />
                <input
                  type="text"
                  placeholder="Nombre"
                  value={formRol.nombre}
                  onChange={(e) => setFormRol({ ...formRol, nombre: e.target.value })}
                  style={{ padding: '8px', borderRadius: '4px', border: '1px solid var(--border-secondary)', background: 'var(--bg-primary)', color: 'var(--text-primary)' }}
                />
                <textarea
                  placeholder="Descripcion (opcional)"
                  value={formRol.descripcion}
                  onChange={(e) => setFormRol({ ...formRol, descripcion: e.target.value })}
                  rows={2}
                  style={{ padding: '8px', borderRadius: '4px', border: '1px solid var(--border-secondary)', background: 'var(--bg-primary)', color: 'var(--text-primary)', resize: 'vertical' }}
                />
                <div style={{ display: 'flex', gap: '8px' }}>
                  <button
                    onClick={editandoRol ? actualizarRol : crearRol}
                    disabled={guardando}
                    className="btn-tesla outline-subtle-success"
                    style={{ flex: 1 }}
                  >
                    {guardando ? 'Guardando...' : (editandoRol ? 'Actualizar' : 'Crear')}
                  </button>
                  <button
                    onClick={() => {
                      setMostrarFormRol(false);
                      setEditandoRol(null);
                      setFormRol({ codigo: '', nombre: '', descripcion: '', orden: 0 });
                    }}
                    className="btn-tesla outline-subtle-danger"
                  >
                    Cancelar
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* Lista de roles */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            {roles.map(rol => (
              <div
                key={rol.id}
                onClick={() => seleccionarRol(rol)}
                style={{
                  padding: '12px',
                  borderRadius: '8px',
                  border: `2px solid ${rolSeleccionado?.id === rol.id ? 'var(--primary)' : 'var(--border-primary)'}`,
                  background: rolSeleccionado?.id === rol.id ? 'var(--primary-light)' : 'var(--bg-primary)',
                  cursor: 'pointer',
                  transition: 'all 0.15s'
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                  <div>
                    <div style={{ fontWeight: '600', display: 'flex', alignItems: 'center', gap: '6px', color: 'var(--text-primary)' }}>
                      {rol.nombre}
                      {rol.es_sistema && (
                        <span style={{
                          fontSize: '10px',
                          padding: '2px 6px',
                          background: 'var(--warning-bg)',
                          color: 'var(--warning-text)',
                          borderRadius: '4px'
                        }}>
                          SISTEMA
                        </span>
                      )}
                    </div>
                    <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginTop: '2px' }}>
                      {rol.codigo} - {rol.usuarios_count || 0} usuarios
                    </div>
                  </div>
                  {!rol.es_sistema && (
                    <div style={{ display: 'flex', gap: '4px' }} onClick={(e) => e.stopPropagation()}>
                      <button
                        onClick={() => iniciarEdicion(rol)}
                        title="Editar"
                        style={{
                          padding: '4px 8px',
                          background: 'var(--info-bg)',
                          color: 'var(--info-text)',
                          border: 'none',
                          borderRadius: '4px',
                          cursor: 'pointer',
                          fontSize: '12px'
                        }}
                      >
                        Editar
                      </button>
                      <button
                        onClick={() => eliminarRol(rol)}
                        title="Eliminar"
                        style={{
                          padding: '4px 8px',
                          background: 'var(--error-bg)',
                          color: 'var(--error-text)',
                          border: 'none',
                          borderRadius: '4px',
                          cursor: 'pointer',
                          fontSize: '12px'
                        }}
                      >
                        X
                      </button>
                    </div>
                  )}
                </div>
                {rol.descripcion && (
                  <div style={{ fontSize: '11px', color: 'var(--text-tertiary)', marginTop: '4px' }}>
                    {rol.descripcion}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>

        {/* Panel derecho: Permisos del rol seleccionado */}
        <div className={`${adminStyles.section} ${styles.permisosSection}`}>
          {rolSeleccionado ? (
            <>
              <div style={{
                position: 'sticky',
                top: 0,
                background: 'var(--bg-primary)',
                paddingBottom: '16px',
                marginBottom: '16px',
                borderBottom: '1px solid var(--border-primary)',
                zIndex: 10
              }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '8px' }}>
                  <div>
                    <h3 style={{ margin: 0, color: 'var(--text-primary)' }}>Permisos de: {rolSeleccionado.nombre}</h3>
                    {rolSeleccionado.codigo === 'SUPERADMIN' && (
                      <p style={{ margin: '4px 0 0', fontSize: '13px', color: 'var(--text-secondary)' }}>
                        SUPERADMIN tiene todos los permisos por defecto
                      </p>
                    )}
                  </div>
                  <div style={{ display: 'flex', gap: 'var(--spacing-sm)', alignItems: 'center' }}>
                    {rolSeleccionado.codigo !== 'SUPERADMIN' && (
                      <>
                        <button
                          onClick={() => setMostrarClonar(true)}
                          className="btn-tesla outline-subtle-primary"
                        >
                          Clonar Rol
                        </button>
                        <button
                          onClick={guardarPermisosRol}
                          disabled={guardando}
                          className="btn-tesla outline-subtle-success"
                        >
                          {guardando ? 'Guardando...' : 'Guardar Permisos'}
                        </button>
                      </>
                    )}
                  </div>
                </div>
              </div>

              {/* Modal Clonar */}
              {mostrarClonar && (
                <div style={{
                  position: 'fixed',
                  top: 0,
                  left: 0,
                  right: 0,
                  bottom: 0,
                  background: 'rgba(0,0,0,0.5)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  zIndex: 1000
                }}>
                  <div style={{
                    background: 'var(--bg-primary)',
                    padding: '24px',
                    borderRadius: '12px',
                    width: '400px',
                    maxWidth: '90%',
                    border: '1px solid var(--border-primary)'
                  }}>
                    <h3 style={{ margin: '0 0 16px', color: 'var(--text-primary)' }}>Clonar Rol: {rolSeleccionado.nombre}</h3>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                      <input
                        type="text"
                        placeholder="Codigo del nuevo rol"
                        value={clonarData.nuevo_codigo}
                        onChange={(e) => setClonarData({ ...clonarData, nuevo_codigo: e.target.value.toUpperCase() })}
                        style={{ padding: '10px', borderRadius: '6px', border: '1px solid var(--border-secondary)', background: 'var(--bg-primary)', color: 'var(--text-primary)' }}
                      />
                      <input
                        type="text"
                        placeholder="Nombre del nuevo rol"
                        value={clonarData.nuevo_nombre}
                        onChange={(e) => setClonarData({ ...clonarData, nuevo_nombre: e.target.value })}
                        style={{ padding: '10px', borderRadius: '6px', border: '1px solid var(--border-secondary)', background: 'var(--bg-primary)', color: 'var(--text-primary)' }}
                      />
                      <textarea
                        placeholder="Descripcion (opcional)"
                        value={clonarData.descripcion}
                        onChange={(e) => setClonarData({ ...clonarData, descripcion: e.target.value })}
                        rows={2}
                        style={{ padding: '10px', borderRadius: '6px', border: '1px solid var(--border-secondary)', background: 'var(--bg-primary)', color: 'var(--text-primary)', resize: 'vertical' }}
                      />
                      <div style={{ display: 'flex', gap: '8px', marginTop: '8px' }}>
                        <button
                          onClick={clonarRol}
                          disabled={guardando}
                          className="btn-tesla outline-subtle-primary"
                          style={{ flex: 1 }}
                        >
                          {guardando ? 'Clonando...' : 'Clonar'}
                        </button>
                        <button
                          onClick={() => {
                            setMostrarClonar(false);
                            setClonarData({ nuevo_codigo: '', nuevo_nombre: '', descripcion: '' });
                          }}
                          className="btn-tesla ghost"
                        >
                          Cancelar
                        </button>
                      </div>
                    </div>
                  </div>
                </div>
              )}

              {/* Lista de permisos por categoria */}
              <div className={styles.permisosWrapper}>
                {/* Header con buscador */}
                <div className={styles.permisosHeader}>
                  <div className={styles.headerRow}>
                    <div className={styles.searchBox}>
                      <input
                        type="text"
                        placeholder="🔍 Buscar permiso por nombre, código o descripción..."
                        value={busquedaPermiso}
                        onChange={(e) => setBusquedaPermiso(e.target.value)}
                        className={styles.searchInput}
                      />
                    </div>
                  </div>
                </div>

                {/* Scroll de permisos */}
                <div className={styles.permisosScroll}>
                  {Object.entries(catalogo).map(([categoria, permisos]) => {
                    // Filtrar permisos según búsqueda
                    const permisosFiltrados = busquedaPermiso.trim()
                      ? permisos.filter(p => 
                          p.nombre.toLowerCase().includes(busquedaPermiso.toLowerCase()) ||
                          p.descripcion?.toLowerCase().includes(busquedaPermiso.toLowerCase()) ||
                          p.codigo.toLowerCase().includes(busquedaPermiso.toLowerCase())
                        )
                      : permisos;
                    
                    // Si no hay permisos que coincidan, no mostrar la categoría
                    if (permisosFiltrados.length === 0) return null;
                    
                    const permisosActivos = permisosFiltrados.filter(p => permisosRol.includes(p.codigo)).length;
                    const esSuperadmin = rolSeleccionado.codigo === 'SUPERADMIN';

                    return (
                      <div key={categoria} className={styles.categoria}>
                        <div className={styles.categoriaHeader}>
                          <h3 className={styles.categoriaTitulo}>
                            {CATEGORIAS_NOMBRE[categoria] || categoria}
                          </h3>
                          <div className={styles.categoriaStats}>
                            {permisosActivos} de {permisosFiltrados.length} activos
                          </div>
                        </div>

                        <div className={styles.permisosList}>
                          {permisosFiltrados.map(permiso => {
                            const tienePermiso = permisosRol.includes(permiso.codigo);

                            return (
                              <div 
                                key={permiso.codigo} 
                                className={styles.permisoItem}
                              >
                                {/* Lado izquierdo: Info */}
                                <div className={styles.permisoInfo}>
                                  <div className={styles.permisoNombre}>
                                    {permiso.nombre}
                                    {permiso.es_critico && (
                                      <span className={`${styles.badge} ${styles.badgeCritico}`}>
                                        Crítico
                                      </span>
                                    )}
                                  </div>
                                  <code className={styles.permisoCodigo}>{permiso.codigo}</code>
                                  {permiso.descripcion && (
                                    <div className={styles.permisoDescripcion}>
                                      {permiso.descripcion}
                                    </div>
                                  )}
                                </div>

                                {/* Lado derecho: Checkbox */}
                                <div className={styles.permisoControls}>
                                  <label style={{
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: 'var(--spacing-sm)',
                                    cursor: esSuperadmin ? 'not-allowed' : 'pointer',
                                    fontSize: 'var(--font-sm)',
                                    color: 'var(--text-secondary)'
                                  }}>
                                    <input
                                      type="checkbox"
                                      checked={tienePermiso}
                                      onChange={() => togglePermisoRol(permiso.codigo)}
                                      disabled={esSuperadmin}
                                      style={{
                                        width: '20px',
                                        height: '20px',
                                        cursor: esSuperadmin ? 'not-allowed' : 'pointer'
                                      }}
                                    />
                                    {tienePermiso ? 'Activo' : 'Inactivo'}
                                  </label>
                                </div>
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            </>
          ) : (
            <div style={{ textAlign: 'center', padding: '60px 20px', color: 'var(--text-secondary)' }}>
              <p style={{ fontSize: '16px' }}>Selecciona un rol para ver y editar sus permisos</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
