import { useState, useEffect, useRef } from 'react';
import { Lock } from 'lucide-react';
import api from '../services/api';
import adminStyles from '../pages/Admin.module.css';
import PermisosPorPantalla from './permisos/PermisosPorPantalla';
import ListaUsuarios from './permisos/ListaUsuarios';
import AvatarIniciales from './permisos/AvatarIniciales';
import { StatusPill } from './kit';
import { contarOverrides } from '../registry/permisosAcceso';
import styles from './PanelPermisos.module.css';

export default function PanelPermisos() {
  const [usuarios, setUsuarios] = useState([]);
  const [roles, setRoles] = useState([]);
  const [usuarioSeleccionado, setUsuarioSeleccionado] = useState(null);
  const [permisosUsuario, setPermisosUsuario] = useState(null);
  const [, setCatalogo] = useState({});
  const [loading, setLoading] = useState(true);
  const [guardando, setGuardando] = useState(false);
  const [mensaje, setMensaje] = useState(null);
  const [usuarioActual, setUsuarioActual] = useState(null);
  // Id of the user whose permissions are on screen: a late reload for a
  // previously selected user must not overwrite the current one.
  const usuarioSeleccionadoIdRef = useRef(null);
  // Generation of the latest permissions request: only the newest response is
  // applied, so a late answer to an older request (same or another user)
  // never overwrites a newer one.
  const cargaPermisosRef = useRef(0);
  // Pending auto-clear of a success message from the permissions view: a newer
  // message cancels it, so an old timer never wipes a later error.
  const mensajeTimerRef = useRef(null);

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



  useEffect(() => {
    cargarDatos();
  }, []);

  const cargarDatos = async () => {
    try {
      const [usuariosRes, catalogoRes, rolesRes, meRes] = await Promise.all([
        api.get('/usuarios'),
        api.get('/permisos/catalogo'),
        api.get('/roles'),
        api.get('/auth/me')
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
      setMensaje({ tipo: 'error', texto: `Error al cargar datos: ${error.response?.data?.detail || error.message}` });
    } finally {
      setLoading(false);
    }
  };

  const seleccionarUsuario = async (usuario) => {
    setUsuarioSeleccionado(usuario);
    usuarioSeleccionadoIdRef.current = usuario.id;
    setPermisosUsuario(null);
    setEditandoUsuario(null);
    setCambiandoPassword(false);

    try {
      await cargarPermisos(usuario.id);
    } catch {
      setMensaje({ tipo: 'error', texto: 'Error al cargar permisos del usuario' });
    }
  };

  // Fetches a user's permissions and applies them only if no newer request
  // started meanwhile. A reload for a user who is no longer selected (it can
  // start after the admin switched users) is skipped; a switch during a
  // request always starts a newer one, so the generation check covers it.
  // Rejects on a failed request so callers report it.
  const cargarPermisos = async (usuarioId) => {
    if (usuarioSeleccionadoIdRef.current !== usuarioId) return;
    const generacion = ++cargaPermisosRef.current;
    const res = await api.get(`/permisos/usuario/${usuarioId}`);
    if (generacion === cargaPermisosRef.current) setPermisosUsuario(res.data);
  };

  const crearUsuario = async () => {
    if (!formUsuario.username || !formUsuario.nombre || !formUsuario.password) {
      setMensaje({ tipo: 'error', texto: 'Username, nombre y contraseña son requeridos' });
      return;
    }

    setGuardando(true);
    try {
      // Buscar el rol seleccionado para obtener el código
      const rolSeleccionado = roles.find(r => r.id === formUsuario.rol_id);

      await api.post('/usuarios', {
        username: formUsuario.username,
        email: formUsuario.email || null,
        nombre: formUsuario.nombre,
        password: formUsuario.password,
        rol: rolSeleccionado?.codigo || 'VENTAS',
        rol_id: formUsuario.rol_id
      });

      setMensaje({ tipo: 'success', texto: 'Usuario creado correctamente' });
      setMostrarFormUsuario(false);
      setFormUsuario({ username: '', email: '', nombre: '', password: '', rol_id: null });
      cargarDatos();
      setTimeout(() => setMensaje(null), 3000);
    } catch (error) {
      setMensaje({ tipo: 'error', texto: error.response?.data?.detail || 'Error al crear usuario' });
    } finally {
      setGuardando(false);
    }
  };

  const actualizarUsuario = async () => {
    if (!usuarioSeleccionado) return;

    setGuardando(true);
    try {
      const cambios = {};
      if (formUsuario.username) cambios.username = formUsuario.username;
      if (formUsuario.email !== undefined) cambios.email = formUsuario.email || null;
      if (formUsuario.nombre) cambios.nombre = formUsuario.nombre;
      if (formUsuario.rol_id) {
        const rolSeleccionado = roles.find(r => r.id === formUsuario.rol_id);
        cambios.rol = rolSeleccionado?.codigo;
        cambios.rol_id = formUsuario.rol_id;
      }

      await api.patch(`/usuarios/${usuarioSeleccionado.id}`, cambios);

      setMensaje({ tipo: 'success', texto: 'Usuario actualizado correctamente' });
      setEditandoUsuario(null);
      cargarDatos();
      // Recargar permisos del usuario
      setTimeout(() => {
        seleccionarUsuario({ ...usuarioSeleccionado, ...cambios });
        setMensaje(null);
      }, 500);
    } catch (error) {
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
      await api.patch(`/usuarios/${usuarioSeleccionado.id}/password`, {
        nueva_password: nuevaPassword
      });

      setMensaje({ tipo: 'success', texto: 'Contraseña actualizada correctamente' });
      setCambiandoPassword(false);
      setNuevaPassword('');
      setTimeout(() => setMensaje(null), 3000);
    } catch (error) {
      setMensaje({ tipo: 'error', texto: error.response?.data?.detail || 'Error al cambiar contraseña' });
    } finally {
      setGuardando(false);
    }
  };

  const toggleUsuarioActivo = async () => {
    if (!usuarioSeleccionado) return;

    setGuardando(true);
    try {
      await api.patch(`/usuarios/${usuarioSeleccionado.id}`, {
        activo: !usuarioSeleccionado.activo
      });

      setMensaje({ tipo: 'success', texto: usuarioSeleccionado.activo ? 'Usuario desactivado' : 'Usuario activado' });
      cargarDatos();
      setUsuarioSeleccionado({ ...usuarioSeleccionado, activo: !usuarioSeleccionado.activo });
      setTimeout(() => setMensaje(null), 3000);
    } catch (error) {
      setMensaje({ tipo: 'error', texto: error.response?.data?.detail || 'Error al cambiar estado' });
    } finally {
      setGuardando(false);
    }
  };

  // Reloads the selected user's permissions in place (no loading flash), so the
  // permissions view keeps its search, filter and expanded rows after an override.
  const recargarPermisosUsuario = (usuarioId) => cargarPermisos(usuarioId);

  const mostrarMensajeTemporal = (nuevoMensaje) => {
    clearTimeout(mensajeTimerRef.current);
    mensajeTimerRef.current = null;
    setMensaje(nuevoMensaje);
    if (nuevoMensaje.tipo === 'success') {
      mensajeTimerRef.current = setTimeout(() => {
        mensajeTimerRef.current = null;
        setMensaje(null);
      }, 2000);
    }
  };

  useEffect(() => () => clearTimeout(mensajeTimerRef.current), []);

  // Messages from the permissions view belong to the user they were raised
  // for: a success that lands after switching users is dropped so it never
  // shows over someone else's permissions. Errors still show (a failed change
  // must not go unnoticed).
  const mostrarMensajeDeUsuario = (usuarioId, nuevoMensaje) => {
    if (nuevoMensaje.tipo === 'success' && usuarioSeleccionadoIdRef.current !== usuarioId) return;
    mostrarMensajeTemporal(nuevoMensaje);
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

  // Overrides are only known for the user whose permissions are loaded.
  const overridesSeleccionado =
    permisosUsuario && permisosUsuario.usuario_id === usuarioSeleccionado?.id
      ? contarOverrides(permisosUsuario.permisos_detallados)
      : null;

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

      <div className={styles.layout}>
        {/* Panel izquierdo: Lista de usuarios */}
        <div className={`${adminStyles.section} ${styles.columnaUsuarios}`}>
          <div className={styles.columnaHeader}>
            <h3 className={styles.columnaTitulo}>Usuarios del sistema</h3>
            <button
              onClick={() => {
                setMostrarFormUsuario(!mostrarFormUsuario);
                setFormUsuario({ email: '', nombre: '', password: '', rol_id: roles.find(r => r.codigo === 'VENTAS')?.id });
              }}
              className="btn-tesla outline-subtle-primary sm"
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
                    className="btn-tesla outline-subtle-success sm"
                    style={{ flex: 1 }}
                  >
                    {guardando ? 'Creando...' : 'Crear Usuario'}
                  </button>
                  <button
                    onClick={() => {
                      setMostrarFormUsuario(false);
                      setFormUsuario({ email: '', nombre: '', password: '', rol_id: null });
                    }}
                    className="btn-tesla outline-subtle-danger sm"
                  >
                    Cancelar
                  </button>
                </div>
              </div>
            </div>
          )}

          <ListaUsuarios
            usuarios={usuarios}
            seleccionadoId={usuarioSeleccionado?.id}
            overridesSeleccionado={overridesSeleccionado}
            onSeleccionar={seleccionarUsuario}
          />
        </div>

        {/* Panel derecho: Detalles y permisos */}
        <div className={`${adminStyles.section} ${styles.columnaDetalle}`}>
          {usuarioSeleccionado ? (
            <>
              {/* Header sticky con info del usuario */}
              <div className={styles.detalleHeader}>
                {/* Info del usuario y acciones */}
                <div className={styles.detalleHeaderFila}>
                  <div className={styles.detalleHeaderInfo}>
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
                            className="btn-tesla outline-subtle-success sm"
                          >
                            Guardar
                          </button>
                          <button
                            onClick={() => setEditandoUsuario(null)}
                            className="btn-tesla ghost sm"
                          >
                            Cancelar
                          </button>
                        </div>
                      </div>
                    ) : (
                      <div className={styles.usuarioHeader}>
                        <AvatarIniciales nombre={usuarioSeleccionado.nombre} className={styles.avatar} />
                        <div className={styles.usuarioDatos}>
                          <div className={styles.usuarioLinea}>
                            <h3 className={styles.usuarioNombre}>{usuarioSeleccionado.nombre}</h3>
                            <StatusPill tone={(permisosUsuario?.rol || usuarioSeleccionado.rol) === 'SUPERADMIN' ? 'warning' : 'info'}>
                              {permisosUsuario?.rol || usuarioSeleccionado.rol}
                            </StatusPill>
                          </div>
                          <div className={styles.usuarioMeta}>
                            <span>@{usuarioSeleccionado.username}</span>
                            {usuarioSeleccionado.email && <span>{usuarioSeleccionado.email}</span>}
                            <StatusPill tone={usuarioSeleccionado.activo ? 'success' : 'danger'} variant="soft" dot>
                              {usuarioSeleccionado.activo ? 'Activo' : 'Inactivo'}
                            </StatusPill>
                          </div>
                        </div>
                      </div>
                    )}
                  </div>

                  {/* Botones de acción */}
                  {!editandoUsuario && (
                    <div className={styles.usuarioAcciones}>
                      <button onClick={iniciarEdicion} className="btn-tesla outline-subtle-primary sm">
                        Editar
                      </button>
                      <button
                        onClick={() => setCambiandoPassword(!cambiandoPassword)}
                        className="btn-tesla outline-subtle-primary sm"
                      >
                        Password
                      </button>
                      <button
                        onClick={toggleUsuarioActivo}
                        disabled={guardando}
                        className={`btn-tesla sm ${usuarioSeleccionado.activo ? 'outline-subtle-danger' : 'outline-subtle-success'}`}
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
                      className="btn-tesla outline-subtle-success"
                    >
                      Cambiar
                    </button>
                    <button
                      onClick={() => {
                        setCambiandoPassword(false);
                        setNuevaPassword('');
                      }}
                      className="btn-tesla ghost"
                    >
                      Cancelar
                    </button>
                  </div>
                )}
              </div>

              {/* Lista de permisos */}
              {!permisosUsuario ? (
                <div className={styles.emptyState}>
                  <div className={styles.emptyIcon}><Lock size={24} /></div>
                  <div className={styles.emptyMessage}>Cargando permisos...</div>
                </div>
              ) : (
                <PermisosPorPantalla
                  key={usuarioSeleccionado.id}
                  usuarioId={usuarioSeleccionado.id}
                  permisosUsuario={permisosUsuario}
                  onActualizado={() => recargarPermisosUsuario(usuarioSeleccionado.id)}
                  onMensaje={(nuevoMensaje) => mostrarMensajeDeUsuario(usuarioSeleccionado.id, nuevoMensaje)}
                />
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
