import { useState, useEffect } from 'react';
import axios from 'axios';
import styles from '../pages/Admin.module.css';

const CATEGORIAS_NOMBRE = {
  productos: 'Productos',
  ventas_ml: 'Ventas MercadoLibre',
  ventas_fuera: 'Ventas Fuera de ML',
  ventas_tn: 'Ventas Tienda Nube',
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

  // Estado para categorías colapsables
  const [categoriasExpandidas, setCategoriasExpandidas] = useState({});

  const API_URL = 'https://pricing.gaussonline.com.ar/api';

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

  const toggleCategoria = (categoria) => {
    setCategoriasExpandidas(prev => ({
      ...prev,
      [categoria]: !prev[categoria]
    }));
  };

  const expandirTodas = () => {
    const todas = {};
    Object.keys(catalogo).forEach(cat => {
      todas[cat] = true;
    });
    setCategoriasExpandidas(todas);
  };

  const colapsarTodas = () => {
    setCategoriasExpandidas({});
  };

  if (loading) {
    return (
      <div className={styles.section}>
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
        <div className={styles.section}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
            <h3 style={{ margin: 0 }}>Roles</h3>
            <button
              onClick={() => {
                setMostrarFormRol(!mostrarFormRol);
                setEditandoRol(null);
                setFormRol({ codigo: '', nombre: '', descripcion: '', orden: roles.length });
              }}
              style={{
                padding: '6px 12px',
                background: 'var(--primary)',
                color: 'var(--text-inverse)',
                border: 'none',
                borderRadius: '4px',
                cursor: 'pointer',
                fontSize: '13px'
              }}
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
                    style={{
                      flex: 1,
                      padding: '8px',
                      background: 'var(--success)',
                      color: 'var(--text-inverse)',
                      border: 'none',
                      borderRadius: '4px',
                      cursor: 'pointer'
                    }}
                  >
                    {guardando ? 'Guardando...' : (editandoRol ? 'Actualizar' : 'Crear')}
                  </button>
                  <button
                    onClick={() => {
                      setMostrarFormRol(false);
                      setEditandoRol(null);
                      setFormRol({ codigo: '', nombre: '', descripcion: '', orden: 0 });
                    }}
                    style={{
                      padding: '8px 16px',
                      background: 'var(--danger)',
                      color: 'var(--text-inverse)',
                      border: 'none',
                      borderRadius: '4px',
                      cursor: 'pointer'
                    }}
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
        <div className={styles.section} style={{ display: 'flex', flexDirection: 'column', maxHeight: '75vh' }}>
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
                  <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                    <div style={{ display: 'flex', gap: '4px', marginRight: '8px' }}>
                      <button
                        onClick={expandirTodas}
                        style={{
                          padding: '4px 8px',
                          fontSize: '11px',
                          background: 'var(--bg-tertiary)',
                          color: 'var(--text-secondary)',
                          border: '1px solid var(--border-primary)',
                          borderRadius: '4px',
                          cursor: 'pointer'
                        }}
                      >
                        Expandir
                      </button>
                      <button
                        onClick={colapsarTodas}
                        style={{
                          padding: '4px 8px',
                          fontSize: '11px',
                          background: 'var(--bg-tertiary)',
                          color: 'var(--text-secondary)',
                          border: '1px solid var(--border-primary)',
                          borderRadius: '4px',
                          cursor: 'pointer'
                        }}
                      >
                        Colapsar
                      </button>
                    </div>
                    {rolSeleccionado.codigo !== 'SUPERADMIN' && (
                      <>
                        <button
                          onClick={() => setMostrarClonar(true)}
                          style={{
                            padding: '8px 16px',
                            background: 'var(--purple)',
                            color: 'var(--text-inverse)',
                            border: 'none',
                            borderRadius: '6px',
                            cursor: 'pointer',
                            fontSize: '13px'
                          }}
                        >
                          Clonar Rol
                        </button>
                        <button
                          onClick={guardarPermisosRol}
                          disabled={guardando}
                          style={{
                            padding: '8px 16px',
                            background: 'var(--success)',
                            color: 'var(--text-inverse)',
                            border: 'none',
                            borderRadius: '6px',
                            cursor: 'pointer',
                            fontSize: '13px'
                          }}
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
                          style={{
                            flex: 1,
                            padding: '10px',
                            background: 'var(--purple)',
                            color: 'var(--text-inverse)',
                            border: 'none',
                            borderRadius: '6px',
                            cursor: 'pointer'
                          }}
                        >
                          {guardando ? 'Clonando...' : 'Clonar'}
                        </button>
                        <button
                          onClick={() => {
                            setMostrarClonar(false);
                            setClonarData({ nuevo_codigo: '', nuevo_nombre: '', descripcion: '' });
                          }}
                          style={{
                            padding: '10px 20px',
                            background: 'var(--text-secondary)',
                            color: 'var(--text-inverse)',
                            border: 'none',
                            borderRadius: '6px',
                            cursor: 'pointer'
                          }}
                        >
                          Cancelar
                        </button>
                      </div>
                    </div>
                  </div>
                </div>
              )}

              {/* Lista de permisos por categoria */}
              <div style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '8px' }}>
                {Object.entries(catalogo).map(([categoria, permisos]) => {
                  const expandida = categoriasExpandidas[categoria] || false;
                  const permisosActivos = permisos.filter(p => permisosRol.includes(p.codigo)).length;

                  return (
                  <div key={categoria} style={{
                    border: '1px solid var(--border-primary)',
                    borderRadius: '8px',
                    overflow: 'hidden'
                  }}>
                    <div
                      onClick={() => toggleCategoria(categoria)}
                      style={{
                        padding: '10px 16px',
                        background: 'var(--bg-secondary)',
                        fontWeight: '600',
                        borderBottom: expandida ? '1px solid var(--border-primary)' : 'none',
                        color: 'var(--text-primary)',
                        cursor: 'pointer',
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'center',
                        userSelect: 'none'
                      }}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <span style={{
                          display: 'inline-block',
                          transition: 'transform 0.2s',
                          transform: expandida ? 'rotate(90deg)' : 'rotate(0deg)'
                        }}>
                          ▶
                        </span>
                        {CATEGORIAS_NOMBRE[categoria] || categoria}
                      </div>
                      <span style={{
                        fontSize: '12px',
                        color: 'var(--text-secondary)',
                        fontWeight: 'normal'
                      }}>
                        {permisosActivos}/{permisos.length}
                      </span>
                    </div>
                    {expandida && (
                    <div style={{ padding: '8px 16px', background: 'var(--bg-primary)', maxHeight: '300px', overflowY: 'auto' }}>
                      {permisos.map(permiso => {
                        const tienePermiso = permisosRol.includes(permiso.codigo);
                        const esSuperadmin = rolSeleccionado.codigo === 'SUPERADMIN';

                        return (
                          <div
                            key={permiso.codigo}
                            style={{
                              display: 'flex',
                              alignItems: 'center',
                              justifyContent: 'space-between',
                              padding: '8px 0',
                              borderBottom: '1px solid var(--bg-tertiary)'
                            }}
                          >
                            <div style={{ flex: 1 }}>
                              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                <span style={{ fontWeight: '500', color: 'var(--text-primary)' }}>{permiso.nombre}</span>
                                {permiso.es_critico && (
                                  <span style={{
                                    fontSize: '10px',
                                    padding: '2px 6px',
                                    background: 'var(--error-bg)',
                                    color: 'var(--error-text)',
                                    borderRadius: '4px'
                                  }}>
                                    CRITICO
                                  </span>
                                )}
                              </div>
                              <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
                                {permiso.codigo}
                                {permiso.descripcion && ` - ${permiso.descripcion}`}
                              </div>
                            </div>
                            <label style={{
                              display: 'flex',
                              alignItems: 'center',
                              cursor: esSuperadmin ? 'not-allowed' : 'pointer'
                            }}>
                              <input
                                type="checkbox"
                                checked={tienePermiso}
                                onChange={() => togglePermisoRol(permiso.codigo)}
                                disabled={esSuperadmin}
                                style={{
                                  width: '18px',
                                  height: '18px',
                                  cursor: esSuperadmin ? 'not-allowed' : 'pointer'
                                }}
                              />
                            </label>
                          </div>
                        );
                      })}
                    </div>
                    )}
                  </div>
                  );
                })}
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
