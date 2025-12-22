import { useState, useEffect } from 'react';
import axios from 'axios';
import styles from '../pages/Admin.module.css';

const CATEGORIAS_NOMBRE = {
  productos: 'Productos',
  ventas_ml: 'Ventas MercadoLibre',
  ventas_fuera: 'Ventas Fuera de ML',
  ventas_tn: 'Ventas Tienda Nube',
  clientes: 'Clientes',
  reportes: 'Reportes',
  administracion: 'Administración',
  configuracion: 'Configuración'
};

export default function PanelPermisos() {
  const [usuarios, setUsuarios] = useState([]);
  const [roles, setRoles] = useState([]);
  const [usuarioSeleccionado, setUsuarioSeleccionado] = useState(null);
  const [permisosUsuario, setPermisosUsuario] = useState(null);
  const [catalogo, setCatalogo] = useState({});
  const [loading, setLoading] = useState(true);
  const [guardando, setGuardando] = useState(false);
  const [mensaje, setMensaje] = useState(null);
  const [filtroUsuario, setFiltroUsuario] = useState('');
  const [busquedaPermiso, setBusquedaPermiso] = useState('');
  const [categoriasExpandidas, setCategoriasExpandidas] = useState({});
  const [usuarioActual, setUsuarioActual] = useState(null);

  // Estados para crear/editar usuario
  const [mostrarFormUsuario, setMostrarFormUsuario] = useState(false);
  const [editandoUsuario, setEditandoUsuario] = useState(null);
  const [formUsuario, setFormUsuario] = useState({
    username: '',
    email: '',
    nombre: '',
    password: '',
    rol_id: null
  });

  // Estado para cambiar password
  const [cambiandoPassword, setCambiandoPassword] = useState(false);
  const [nuevaPassword, setNuevaPassword] = useState('');

  const API_URL = 'https://pricing.gaussonline.com.ar/api';

  useEffect(() => {
    cargarDatos();
  }, []);

  const cargarDatos = async () => {
    try {
      const token = localStorage.getItem('token');
      const headers = { Authorization: `Bearer ${token}` };

      const [usuariosRes, catalogoRes, rolesRes, meRes] = await Promise.all([
        axios.get(`${API_URL}/usuarios`, { headers }),
        axios.get(`${API_URL}/permisos/catalogo`, { headers }),
        axios.get(`${API_URL}/roles`, { headers }),
        axios.get(`${API_URL}/auth/me`, { headers })
      ]);

      const currentUser = meRes.data;
      setUsuarioActual(currentUser);

      // Filtrar usuarios según rol del usuario actual
      let usuariosFiltrados = Array.isArray(usuariosRes.data) ? usuariosRes.data : [];
      if (currentUser.rol !== 'SUPERADMIN') {
        usuariosFiltrados = usuariosFiltrados.filter(u => u.rol !== 'SUPERADMIN');
      }

      setUsuarios(usuariosFiltrados);
      setCatalogo(catalogoRes.data || {});
      setRoles(rolesRes.data || []);
    } catch (error) {
      console.error('Error cargando datos:', error);
      setMensaje({ tipo: 'error', texto: `Error al cargar datos: ${error.response?.data?.detail || error.message}` });
    } finally {
      setLoading(false);
    }
  };

  const seleccionarUsuario = async (usuario) => {
    setUsuarioSeleccionado(usuario);
    setPermisosUsuario(null);
    setEditandoUsuario(null);
    setCambiandoPassword(false);

    try {
      const token = localStorage.getItem('token');
      const headers = { Authorization: `Bearer ${token}` };

      const res = await axios.get(`${API_URL}/permisos/usuario/${usuario.id}`, { headers });
      setPermisosUsuario(res.data);
    } catch (error) {
      console.error('Error cargando permisos:', error);
      setMensaje({ tipo: 'error', texto: 'Error al cargar permisos del usuario' });
    }
  };

  const crearUsuario = async () => {
    if (!formUsuario.username || !formUsuario.nombre || !formUsuario.password) {
      setMensaje({ tipo: 'error', texto: 'Username, nombre y contraseña son requeridos' });
      return;
    }

    setGuardando(true);
    try {
      const token = localStorage.getItem('token');
      const headers = { Authorization: `Bearer ${token}` };

      // Buscar el rol seleccionado para obtener el código
      const rolSeleccionado = roles.find(r => r.id === formUsuario.rol_id);

      await axios.post(`${API_URL}/usuarios`, {
        username: formUsuario.username,
        email: formUsuario.email || null,
        nombre: formUsuario.nombre,
        password: formUsuario.password,
        rol: rolSeleccionado?.codigo || 'VENTAS',
        rol_id: formUsuario.rol_id
      }, { headers });

      setMensaje({ tipo: 'success', texto: 'Usuario creado correctamente' });
      setMostrarFormUsuario(false);
      setFormUsuario({ username: '', email: '', nombre: '', password: '', rol_id: null });
      cargarDatos();
      setTimeout(() => setMensaje(null), 3000);
    } catch (error) {
      console.error('Error creando usuario:', error);
      setMensaje({ tipo: 'error', texto: error.response?.data?.detail || 'Error al crear usuario' });
    } finally {
      setGuardando(false);
    }
  };

  const actualizarUsuario = async () => {
    if (!usuarioSeleccionado) return;

    setGuardando(true);
    try {
      const token = localStorage.getItem('token');
      const headers = { Authorization: `Bearer ${token}` };

      const cambios = {};
      if (formUsuario.username) cambios.username = formUsuario.username;
      if (formUsuario.email !== undefined) cambios.email = formUsuario.email || null;
      if (formUsuario.nombre) cambios.nombre = formUsuario.nombre;
      if (formUsuario.rol_id) {
        const rolSeleccionado = roles.find(r => r.id === formUsuario.rol_id);
        cambios.rol = rolSeleccionado?.codigo;
        cambios.rol_id = formUsuario.rol_id;
      }

      await axios.patch(`${API_URL}/usuarios/${usuarioSeleccionado.id}`, cambios, { headers });

      setMensaje({ tipo: 'success', texto: 'Usuario actualizado correctamente' });
      setEditandoUsuario(null);
      cargarDatos();
      // Recargar permisos del usuario
      setTimeout(() => {
        seleccionarUsuario({ ...usuarioSeleccionado, ...cambios });
        setMensaje(null);
      }, 500);
    } catch (error) {
      console.error('Error actualizando usuario:', error);
      setMensaje({ tipo: 'error', texto: error.response?.data?.detail || 'Error al actualizar usuario' });
    } finally {
      setGuardando(false);
    }
  };

  const cambiarPassword = async () => {
    if (!usuarioSeleccionado || !nuevaPassword) {
      setMensaje({ tipo: 'error', texto: 'Ingresa la nueva contraseña' });
      return;
    }

    setGuardando(true);
    try {
      const token = localStorage.getItem('token');
      const headers = { Authorization: `Bearer ${token}` };

      await axios.patch(`${API_URL}/usuarios/${usuarioSeleccionado.id}/password`, {
        nueva_password: nuevaPassword
      }, { headers });

      setMensaje({ tipo: 'success', texto: 'Contraseña actualizada correctamente' });
      setCambiandoPassword(false);
      setNuevaPassword('');
      setTimeout(() => setMensaje(null), 3000);
    } catch (error) {
      console.error('Error cambiando password:', error);
      setMensaje({ tipo: 'error', texto: error.response?.data?.detail || 'Error al cambiar contraseña' });
    } finally {
      setGuardando(false);
    }
  };

  const toggleUsuarioActivo = async () => {
    if (!usuarioSeleccionado) return;

    setGuardando(true);
    try {
      const token = localStorage.getItem('token');
      const headers = { Authorization: `Bearer ${token}` };

      await axios.patch(`${API_URL}/usuarios/${usuarioSeleccionado.id}`, {
        activo: !usuarioSeleccionado.activo
      }, { headers });

      setMensaje({ tipo: 'success', texto: usuarioSeleccionado.activo ? 'Usuario desactivado' : 'Usuario activado' });
      cargarDatos();
      setUsuarioSeleccionado({ ...usuarioSeleccionado, activo: !usuarioSeleccionado.activo });
      setTimeout(() => setMensaje(null), 3000);
    } catch (error) {
      console.error('Error toggling usuario:', error);
      setMensaje({ tipo: 'error', texto: error.response?.data?.detail || 'Error al cambiar estado' });
    } finally {
      setGuardando(false);
    }
  };

  const forzarPermiso = async (permisoCodigo, conceder) => {
    if (!usuarioSeleccionado) return;

    setGuardando(true);
    try {
      const token = localStorage.getItem('token');
      const headers = { Authorization: `Bearer ${token}` };

      await axios.post(`${API_URL}/permisos/override`, {
        usuario_id: usuarioSeleccionado.id,
        permiso_codigo: permisoCodigo,
        concedido: conceder,
        motivo: `Override desde panel de permisos`
      }, { headers });

      await seleccionarUsuario(usuarioSeleccionado);
      setMensaje({ tipo: 'success', texto: `Permiso ${conceder ? 'concedido' : 'denegado'}` });
      setTimeout(() => setMensaje(null), 2000);
    } catch (error) {
      console.error('Error forzando permiso:', error);
      setMensaje({ tipo: 'error', texto: 'Error al modificar permiso' });
    } finally {
      setGuardando(false);
    }
  };

  const resetearOverride = async (permisoCodigo) => {
    if (!usuarioSeleccionado) return;

    setGuardando(true);
    try {
      const token = localStorage.getItem('token');
      const headers = { Authorization: `Bearer ${token}` };

      await axios.delete(`${API_URL}/permisos/override/${usuarioSeleccionado.id}/${permisoCodigo}`, { headers });

      await seleccionarUsuario(usuarioSeleccionado);
      setMensaje({ tipo: 'success', texto: 'Vuelto al permiso base del rol' });
      setTimeout(() => setMensaje(null), 2000);
    } catch (error) {
      console.error('Error reseteando override:', error);
      setMensaje({ tipo: 'error', texto: 'Error al resetear permiso' });
    } finally {
      setGuardando(false);
    }
  };

  const iniciarEdicion = () => {
    if (!usuarioSeleccionado) return;
    setEditandoUsuario(usuarioSeleccionado.id);
    setFormUsuario({
      username: usuarioSeleccionado.username,
      email: usuarioSeleccionado.email || '',
      nombre: usuarioSeleccionado.nombre,
      rol_id: usuarioSeleccionado.rol_id || roles.find(r => r.codigo === usuarioSeleccionado.rol)?.id
    });
  };

  const usuariosFiltrados = usuarios.filter(u =>
    u.nombre.toLowerCase().includes(filtroUsuario.toLowerCase()) ||
    u.username?.toLowerCase().includes(filtroUsuario.toLowerCase()) ||
    u.email?.toLowerCase().includes(filtroUsuario.toLowerCase()) ||
    u.rol.toLowerCase().includes(filtroUsuario.toLowerCase())
  );

  const toggleCategoria = (categoria) => {
    setCategoriasExpandidas(prev => ({
      ...prev,
      [categoria]: !prev[categoria]
    }));
  };

  const expandirTodas = () => {
    if (permisosUsuario) {
      const todas = {};
      Object.keys(permisosUsuario.permisos_detallados).forEach(cat => {
        todas[cat] = true;
      });
      setCategoriasExpandidas(todas);
    }
  };

  const colapsarTodas = () => {
    setCategoriasExpandidas({});
  };

  if (loading) {
    return (
      <div className={styles.section}>
        <div style={{ textAlign: 'center', padding: '40px' }}>
          Cargando usuarios y permisos...
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

      <div style={{ display: 'grid', gridTemplateColumns: '320px 1fr', gap: '20px' }}>
        {/* Panel izquierdo: Lista de usuarios */}
        <div className={styles.section}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
            <h3 style={{ margin: 0, color: 'var(--text-primary)' }}>Usuarios</h3>
            <button
              onClick={() => {
                setMostrarFormUsuario(!mostrarFormUsuario);
                setFormUsuario({ email: '', nombre: '', password: '', rol_id: roles.find(r => r.codigo === 'VENTAS')?.id });
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
              + Nuevo Usuario
            </button>
          </div>

          {/* Form crear usuario */}
          {mostrarFormUsuario && (
            <div style={{
              background: 'var(--bg-secondary)',
              padding: '16px',
              borderRadius: '8px',
              marginBottom: '16px',
              border: '1px solid var(--border-primary)'
            }}>
              <h4 style={{ margin: '0 0 12px 0', color: 'var(--text-primary)' }}>Nuevo Usuario</h4>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                <input
                  type="text"
                  placeholder="Nombre de usuario (requerido)"
                  value={formUsuario.username}
                  onChange={(e) => setFormUsuario({ ...formUsuario, username: e.target.value })}
                  style={{
                    padding: '8px',
                    borderRadius: '4px',
                    border: '1px solid var(--border-secondary)',
                    background: 'var(--bg-primary)',
                    color: 'var(--text-primary)'
                  }}
                  required
                />
                <input
                  type="email"
                  placeholder="Email (opcional)"
                  value={formUsuario.email}
                  onChange={(e) => setFormUsuario({ ...formUsuario, email: e.target.value })}
                  style={{
                    padding: '8px',
                    borderRadius: '4px',
                    border: '1px solid var(--border-secondary)',
                    background: 'var(--bg-primary)',
                    color: 'var(--text-primary)'
                  }}
                />
                <input
                  type="text"
                  placeholder="Nombre completo"
                  value={formUsuario.nombre}
                  onChange={(e) => setFormUsuario({ ...formUsuario, nombre: e.target.value })}
                  style={{
                    padding: '8px',
                    borderRadius: '4px',
                    border: '1px solid var(--border-secondary)',
                    background: 'var(--bg-primary)',
                    color: 'var(--text-primary)'
                  }}
                />
                <input
                  type="password"
                  placeholder="Contraseña"
                  value={formUsuario.password}
                  onChange={(e) => setFormUsuario({ ...formUsuario, password: e.target.value })}
                  style={{
                    padding: '8px',
                    borderRadius: '4px',
                    border: '1px solid var(--border-secondary)',
                    background: 'var(--bg-primary)',
                    color: 'var(--text-primary)'
                  }}
                />
                <select
                  value={formUsuario.rol_id || ''}
                  onChange={(e) => setFormUsuario({ ...formUsuario, rol_id: parseInt(e.target.value) })}
                  style={{
                    padding: '8px',
                    borderRadius: '4px',
                    border: '1px solid var(--border-secondary)',
                    background: 'var(--bg-primary)',
                    color: 'var(--text-primary)'
                  }}
                >
                  <option value="">Seleccionar rol...</option>
                  {roles.filter(r => usuarioActual?.rol === 'SUPERADMIN' || r.codigo !== 'SUPERADMIN').map(rol => (
                    <option key={rol.id} value={rol.id}>{rol.nombre}</option>
                  ))}
                </select>
                <div style={{ display: 'flex', gap: '8px' }}>
                  <button
                    onClick={crearUsuario}
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
                    {guardando ? 'Creando...' : 'Crear Usuario'}
                  </button>
                  <button
                    onClick={() => {
                      setMostrarFormUsuario(false);
                      setFormUsuario({ email: '', nombre: '', password: '', rol_id: null });
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

          {/* Buscador */}
          <input
            type="text"
            placeholder="Buscar usuario..."
            value={filtroUsuario}
            onChange={(e) => setFiltroUsuario(e.target.value)}
            style={{
              width: '100%',
              padding: '8px 12px',
              borderRadius: '6px',
              border: '1px solid var(--border-secondary)',
              background: 'var(--bg-primary)',
              color: 'var(--text-primary)',
              fontSize: '13px',
              marginBottom: '12px'
            }}
          />

          {/* Lista de usuarios */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', maxHeight: '60vh', overflowY: 'auto' }}>
            {usuariosFiltrados.map(usuario => (
              <div
                key={usuario.id}
                onClick={() => seleccionarUsuario(usuario)}
                style={{
                  padding: '12px',
                  borderRadius: '8px',
                  border: `2px solid ${usuarioSeleccionado?.id === usuario.id ? 'var(--primary)' : 'var(--border-primary)'}`,
                  background: usuarioSeleccionado?.id === usuario.id ? 'var(--primary-light)' : 'var(--bg-primary)',
                  cursor: 'pointer',
                  transition: 'all 0.15s',
                  opacity: usuario.activo === false ? 0.6 : 1
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontWeight: '600', color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: '6px' }}>
                      {usuario.nombre}
                      {!usuario.activo && (
                        <span style={{
                          fontSize: '10px',
                          padding: '2px 6px',
                          background: 'var(--error-bg)',
                          color: 'var(--error-text)',
                          borderRadius: '4px'
                        }}>
                          INACTIVO
                        </span>
                      )}
                    </div>
                    <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginTop: '2px' }}>
                      <strong>@{usuario.username}</strong>{usuario.email && ` • ${usuario.email}`}
                    </div>
                  </div>
                </div>
                <div style={{
                  fontSize: '11px',
                  marginTop: '6px',
                  padding: '2px 8px',
                  borderRadius: '4px',
                  display: 'inline-block',
                  background: usuario.rol === 'SUPERADMIN' ? 'var(--warning-bg)' : 'var(--bg-tertiary)',
                  color: usuario.rol === 'SUPERADMIN' ? 'var(--warning-text)' : 'var(--text-secondary)'
                }}>
                  {usuario.rol}
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Panel derecho: Detalles y permisos */}
        <div className={styles.section} style={{ display: 'flex', flexDirection: 'column', maxHeight: '75vh' }}>
          {usuarioSeleccionado ? (
            <>
              {/* Header sticky con info del usuario */}
              <div style={{
                position: 'sticky',
                top: 0,
                background: 'var(--bg-primary)',
                paddingBottom: '16px',
                marginBottom: '16px',
                borderBottom: '1px solid var(--border-primary)',
                zIndex: 10
              }}>
                {/* Info del usuario y acciones */}
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '12px' }}>
                  <div style={{ flex: 1 }}>
                    {editandoUsuario ? (
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                        <input
                          type="text"
                          value={formUsuario.username || ''}
                          onChange={(e) => setFormUsuario({ ...formUsuario, username: e.target.value })}
                          placeholder="Nombre de usuario"
                          style={{
                            padding: '8px',
                            borderRadius: '4px',
                            border: '1px solid var(--border-secondary)',
                            background: 'var(--bg-primary)',
                            color: 'var(--text-primary)',
                            fontSize: '14px'
                          }}
                        />
                        <input
                          type="email"
                          value={formUsuario.email || ''}
                          onChange={(e) => setFormUsuario({ ...formUsuario, email: e.target.value })}
                          placeholder="Email (opcional)"
                          style={{
                            padding: '8px',
                            borderRadius: '4px',
                            border: '1px solid var(--border-secondary)',
                            background: 'var(--bg-primary)',
                            color: 'var(--text-primary)',
                            fontSize: '14px'
                          }}
                        />
                        <input
                          type="text"
                          value={formUsuario.nombre || ''}
                          onChange={(e) => setFormUsuario({ ...formUsuario, nombre: e.target.value })}
                          placeholder="Nombre completo"
                          style={{
                            padding: '8px',
                            borderRadius: '4px',
                            border: '1px solid var(--border-secondary)',
                            background: 'var(--bg-primary)',
                            color: 'var(--text-primary)',
                            fontSize: '16px',
                            fontWeight: '600'
                          }}
                        />
                        <select
                          value={formUsuario.rol_id || ''}
                          onChange={(e) => setFormUsuario({ ...formUsuario, rol_id: parseInt(e.target.value) })}
                          style={{
                            padding: '8px',
                            borderRadius: '4px',
                            border: '1px solid var(--border-secondary)',
                            background: 'var(--bg-primary)',
                            color: 'var(--text-primary)'
                          }}
                        >
                          {roles.filter(r => usuarioActual?.rol === 'SUPERADMIN' || r.codigo !== 'SUPERADMIN').map(rol => (
                            <option key={rol.id} value={rol.id}>{rol.nombre}</option>
                          ))}
                        </select>
                        <div style={{ display: 'flex', gap: '8px' }}>
                          <button
                            onClick={actualizarUsuario}
                            disabled={guardando}
                            style={{
                              padding: '6px 12px',
                              background: 'var(--success)',
                              color: 'var(--text-inverse)',
                              border: 'none',
                              borderRadius: '4px',
                              cursor: 'pointer',
                              fontSize: '13px'
                            }}
                          >
                            Guardar
                          </button>
                          <button
                            onClick={() => setEditandoUsuario(null)}
                            style={{
                              padding: '6px 12px',
                              background: 'var(--bg-tertiary)',
                              color: 'var(--text-primary)',
                              border: '1px solid var(--border-primary)',
                              borderRadius: '4px',
                              cursor: 'pointer',
                              fontSize: '13px'
                            }}
                          >
                            Cancelar
                          </button>
                        </div>
                      </div>
                    ) : (
                      <>
                        <h3 style={{ margin: '0 0 4px 0', color: 'var(--text-primary)' }}>
                          {usuarioSeleccionado.nombre}
                        </h3>
                        <div style={{ color: 'var(--text-secondary)', fontSize: '14px' }}>
                          {usuarioSeleccionado.email}
                        </div>
                        <div style={{ marginTop: '8px', display: 'flex', alignItems: 'center', gap: '8px' }}>
                          <span style={{
                            padding: '4px 10px',
                            borderRadius: '4px',
                            fontSize: '12px',
                            fontWeight: '600',
                            background: permisosUsuario?.rol === 'SUPERADMIN' ? 'var(--warning-bg)' : 'var(--info-bg)',
                            color: permisosUsuario?.rol === 'SUPERADMIN' ? 'var(--warning-text)' : 'var(--info-text)'
                          }}>
                            {permisosUsuario?.rol || usuarioSeleccionado.rol}
                          </span>
                          <span style={{
                            padding: '4px 10px',
                            borderRadius: '4px',
                            fontSize: '12px',
                            fontWeight: '600',
                            background: usuarioSeleccionado.activo ? 'var(--success-bg)' : 'var(--error-bg)',
                            color: usuarioSeleccionado.activo ? 'var(--success-text)' : 'var(--error-text)'
                          }}>
                            {usuarioSeleccionado.activo ? 'Activo' : 'Inactivo'}
                          </span>
                        </div>
                      </>
                    )}
                  </div>

                  {/* Botones de acción */}
                  {!editandoUsuario && (
                    <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap', justifyContent: 'flex-end' }}>
                      <button
                        onClick={iniciarEdicion}
                        style={{
                          padding: '6px 12px',
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
                        onClick={() => setCambiandoPassword(!cambiandoPassword)}
                        style={{
                          padding: '6px 12px',
                          background: 'var(--purple)',
                          color: 'var(--text-inverse)',
                          border: 'none',
                          borderRadius: '4px',
                          cursor: 'pointer',
                          fontSize: '12px'
                        }}
                      >
                        Password
                      </button>
                      <button
                        onClick={toggleUsuarioActivo}
                        disabled={guardando}
                        style={{
                          padding: '6px 12px',
                          background: usuarioSeleccionado.activo ? 'var(--error-bg)' : 'var(--success-bg)',
                          color: usuarioSeleccionado.activo ? 'var(--error-text)' : 'var(--success-text)',
                          border: 'none',
                          borderRadius: '4px',
                          cursor: 'pointer',
                          fontSize: '12px'
                        }}
                      >
                        {usuarioSeleccionado.activo ? 'Desactivar' : 'Activar'}
                      </button>
                    </div>
                  )}
                </div>

                {/* Form cambiar password */}
                {cambiandoPassword && (
                  <div style={{
                    background: 'var(--bg-secondary)',
                    padding: '12px',
                    borderRadius: '6px',
                    marginBottom: '12px',
                    display: 'flex',
                    gap: '8px',
                    alignItems: 'center'
                  }}>
                    <input
                      type="password"
                      placeholder="Nueva contraseña"
                      value={nuevaPassword}
                      onChange={(e) => setNuevaPassword(e.target.value)}
                      style={{
                        flex: 1,
                        padding: '8px',
                        borderRadius: '4px',
                        border: '1px solid var(--border-secondary)',
                        background: 'var(--bg-primary)',
                        color: 'var(--text-primary)'
                      }}
                    />
                    <button
                      onClick={cambiarPassword}
                      disabled={guardando || !nuevaPassword}
                      style={{
                        padding: '8px 16px',
                        background: 'var(--success)',
                        color: 'var(--text-inverse)',
                        border: 'none',
                        borderRadius: '4px',
                        cursor: 'pointer'
                      }}
                    >
                      Cambiar
                    </button>
                    <button
                      onClick={() => {
                        setCambiandoPassword(false);
                        setNuevaPassword('');
                      }}
                      style={{
                        padding: '8px 12px',
                        background: 'var(--bg-tertiary)',
                        color: 'var(--text-primary)',
                        border: '1px solid var(--border-primary)',
                        borderRadius: '4px',
                        cursor: 'pointer'
                      }}
                    >
                      Cancelar
                    </button>
                  </div>
                )}

                {/* Controles de permisos */}
                {permisosUsuario && (
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <div style={{ display: 'flex', gap: '12px', fontSize: '12px', color: 'var(--text-secondary)', flexWrap: 'wrap' }}>
                      <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                        <span style={{ width: '12px', height: '12px', background: 'var(--success)', borderRadius: '3px' }}></span>
                        Activo
                      </span>
                      <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                        <span style={{ width: '12px', height: '12px', background: 'var(--error)', borderRadius: '3px' }}></span>
                        Sin permiso
                      </span>
                      <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                        <span style={{ width: '12px', height: '12px', background: 'var(--primary)', borderRadius: '3px' }}></span>
                        Override +
                      </span>
                      <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                        <span style={{ width: '12px', height: '12px', background: 'var(--warning)', borderRadius: '3px' }}></span>
                        Override -
                      </span>
                    </div>
                    <div style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
                      <input
                        type="text"
                        placeholder="🔍 Buscar permiso..."
                        value={busquedaPermiso}
                        onChange={(e) => setBusquedaPermiso(e.target.value)}
                        style={{
                          padding: '6px 10px',
                          fontSize: '12px',
                          background: 'var(--bg-primary)',
                          color: 'var(--text-primary)',
                          border: '1px solid var(--border-primary)',
                          borderRadius: '4px',
                          width: '200px'
                        }}
                      />
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
                  </div>
                )}
              </div>

              {/* Lista de permisos */}
              {!permisosUsuario ? (
                <div style={{ textAlign: 'center', padding: '40px', color: 'var(--text-secondary)' }}>
                  Cargando permisos...
                </div>
              ) : (
                <div style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  {Object.entries(permisosUsuario.permisos_detallados).map(([categoria, permisos]) => {
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
                    
                    const expandida = categoriasExpandidas[categoria] || busquedaPermiso.trim() !== '';
                    const permisosActivos = permisosFiltrados.filter(p => p.efectivo).length;

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
                          {permisosActivos}/{permisosFiltrados.length}
                          {busquedaPermiso.trim() && permisosFiltrados.length !== permisos.length && (
                            <span style={{ marginLeft: '4px', fontSize: '11px', opacity: 0.7 }}>
                              (de {permisos.length})
                            </span>
                          )}
                        </span>
                      </div>
                      {expandida && (
                      <div style={{ padding: '8px 16px', background: 'var(--bg-primary)', maxHeight: '300px', overflowY: 'auto' }}>
                        {permisosFiltrados.map(permiso => {
                          const tieneOverride = permiso.override !== null;
                          const esOverridePositivo = permiso.override === true;
                          const esOverrideNegativo = permiso.override === false;
                          const esSuperadmin = permisosUsuario.rol === 'SUPERADMIN';

                          return (
                            <div
                              key={permiso.codigo}
                              style={{
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'space-between',
                                padding: '10px 0',
                                borderBottom: '1px solid var(--bg-tertiary)',
                                opacity: guardando ? 0.6 : 1
                              }}
                            >
                              <div style={{ flex: 1 }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                  <span style={{ fontWeight: '500', color: 'var(--text-primary)' }}>
                                    {permiso.nombre}
                                  </span>
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
                                  {tieneOverride && (
                                    <span style={{
                                      fontSize: '10px',
                                      padding: '2px 6px',
                                      background: esOverridePositivo ? 'var(--info-bg)' : 'var(--warning-bg)',
                                      color: esOverridePositivo ? 'var(--info-text)' : 'var(--warning-text)',
                                      borderRadius: '4px'
                                    }}>
                                      {esOverridePositivo ? 'AGREGADO' : 'QUITADO'}
                                    </span>
                                  )}
                                </div>
                                <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginTop: '2px' }}>
                                  {permiso.codigo}
                                  {permiso.descripcion && ` - ${permiso.descripcion}`}
                                </div>
                              </div>

                              <div style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
                                <span style={{ fontSize: '11px', color: 'var(--text-tertiary)', marginRight: '8px' }}>
                                  Rol: {permiso.tiene_por_rol ? '✓' : '✗'}
                                </span>

                                {!esSuperadmin && (
                                  <>
                                    {tieneOverride ? (
                                      <button
                                        onClick={() => resetearOverride(permiso.codigo)}
                                        disabled={guardando}
                                        style={{
                                          padding: '5px 10px',
                                          fontSize: '12px',
                                          background: 'var(--bg-tertiary)',
                                          color: 'var(--text-primary)',
                                          border: '1px solid var(--border-primary)',
                                          borderRadius: '4px',
                                          cursor: guardando ? 'not-allowed' : 'pointer'
                                        }}
                                      >
                                        Resetear
                                      </button>
                                    ) : permiso.tiene_por_rol ? (
                                      <button
                                        onClick={() => forzarPermiso(permiso.codigo, false)}
                                        disabled={guardando}
                                        style={{
                                          padding: '5px 10px',
                                          fontSize: '12px',
                                          background: 'var(--warning-bg)',
                                          color: 'var(--warning-text)',
                                          border: 'none',
                                          borderRadius: '4px',
                                          cursor: guardando ? 'not-allowed' : 'pointer'
                                        }}
                                      >
                                        Quitar
                                      </button>
                                    ) : (
                                      <button
                                        onClick={() => forzarPermiso(permiso.codigo, true)}
                                        disabled={guardando}
                                        style={{
                                          padding: '5px 10px',
                                          fontSize: '12px',
                                          background: 'var(--info-bg)',
                                          color: 'var(--info-text)',
                                          border: 'none',
                                          borderRadius: '4px',
                                          cursor: guardando ? 'not-allowed' : 'pointer'
                                        }}
                                      >
                                        Agregar
                                      </button>
                                    )}
                                  </>
                                )}

                                <div style={{
                                  width: '24px',
                                  height: '24px',
                                  borderRadius: '4px',
                                  background: permiso.efectivo ? 'var(--success)' : 'var(--error)',
                                  display: 'flex',
                                  alignItems: 'center',
                                  justifyContent: 'center',
                                  color: 'var(--text-inverse)',
                                  fontSize: '14px',
                                  fontWeight: 'bold'
                                }}>
                                  {permiso.efectivo ? '✓' : '✗'}
                                </div>
                              </div>
                            </div>
                          );
                        })}
                      </div>
                      )}
                    </div>
                  );
                  })}
                </div>
              )}
            </>
          ) : (
            <div style={{ textAlign: 'center', padding: '60px 20px', color: 'var(--text-secondary)' }}>
              <p style={{ fontSize: '16px' }}>Selecciona un usuario para ver y editar sus datos y permisos</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
