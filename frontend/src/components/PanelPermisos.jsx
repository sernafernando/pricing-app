import { useState, useEffect } from 'react';
import axios from 'axios';
import styles from '../pages/Admin.module.css';

const CATEGORIAS_NOMBRE = {
  productos: 'Productos',
  ventas_ml: 'Ventas MercadoLibre',
  ventas_fuera: 'Ventas Fuera de ML',
  ventas_tn: 'Ventas Tienda Nube',
  reportes: 'Reportes',
  administracion: 'Administración',
  configuracion: 'Configuración'
};

export default function PanelPermisos() {
  const [usuarios, setUsuarios] = useState([]);
  const [usuarioSeleccionado, setUsuarioSeleccionado] = useState(null);
  const [permisosUsuario, setPermisosUsuario] = useState(null);
  const [catalogo, setCatalogo] = useState({});
  const [loading, setLoading] = useState(true);
  const [guardando, setGuardando] = useState(false);
  const [mensaje, setMensaje] = useState(null);
  const [filtroUsuario, setFiltroUsuario] = useState('');
  const [categoriasExpandidas, setCategoriasExpandidas] = useState({});

  const API_URL = 'https://pricing.gaussonline.com.ar/api';

  useEffect(() => {
    cargarDatos();
  }, []);

  const cargarDatos = async () => {
    try {
      const token = localStorage.getItem('token');
      const headers = { Authorization: `Bearer ${token}` };

      const [usuariosRes, catalogoRes] = await Promise.all([
        axios.get(`${API_URL}/usuarios`, { headers }),
        axios.get(`${API_URL}/permisos/catalogo`, { headers })
      ]);

      const usuariosActivos = Array.isArray(usuariosRes.data)
        ? usuariosRes.data.filter(u => u.activo !== false)
        : [];

      setUsuarios(usuariosActivos);
      setCatalogo(catalogoRes.data || {});
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

  const usuariosFiltrados = usuarios.filter(u =>
    u.nombre.toLowerCase().includes(filtroUsuario.toLowerCase()) ||
    u.email.toLowerCase().includes(filtroUsuario.toLowerCase()) ||
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

      <div style={{ display: 'grid', gridTemplateColumns: '300px 1fr', gap: '20px' }}>
        {/* Panel izquierdo: Lista de usuarios */}
        <div className={styles.section}>
          <div style={{ marginBottom: '16px' }}>
            <h3 style={{ margin: '0 0 12px 0', color: 'var(--text-primary)' }}>Usuarios</h3>
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
                fontSize: '13px'
              }}
            />
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
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
                  transition: 'all 0.15s'
                }}
              >
                <div style={{ fontWeight: '600', color: 'var(--text-primary)' }}>
                  {usuario.nombre}
                </div>
                <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginTop: '2px' }}>
                  {usuario.email}
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

        {/* Panel derecho: Permisos del usuario */}
        <div className={styles.section} style={{ display: 'flex', flexDirection: 'column', maxHeight: '75vh' }}>
          {usuarioSeleccionado ? (
            <>
              {/* Header sticky */}
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
                    <h3 style={{ margin: '0 0 8px 0', color: 'var(--text-primary)' }}>
                      Permisos de: {permisosUsuario?.usuario_nombre || usuarioSeleccionado.nombre}
                    </h3>
                    <div style={{ color: 'var(--text-secondary)', fontSize: '14px' }}>
                      Rol base: <strong style={{ color: 'var(--text-primary)' }}>{permisosUsuario?.rol || usuarioSeleccionado.rol}</strong>
                      {permisosUsuario?.rol === 'SUPERADMIN' && (
                        <span style={{
                          marginLeft: '10px',
                          padding: '2px 8px',
                          background: 'var(--warning-bg)',
                          color: 'var(--warning-text)',
                          borderRadius: '4px',
                          fontSize: '11px'
                        }}>
                          Todos los permisos
                        </span>
                      )}
                    </div>
                  </div>
                  {permisosUsuario && (
                    <div style={{ display: 'flex', gap: '6px' }}>
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
                  )}
                </div>
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
              </div>

              {!permisosUsuario ? (
                <div style={{ textAlign: 'center', padding: '40px', color: 'var(--text-secondary)' }}>
                  Cargando permisos...
                </div>
              ) : (
                <div style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  {Object.entries(permisosUsuario.permisos_detallados).map(([categoria, permisos]) => {
                    const expandida = categoriasExpandidas[categoria] || false;
                    const permisosActivos = permisos.filter(p => p.efectivo).length;

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
              <p style={{ fontSize: '16px' }}>Selecciona un usuario para ver y editar sus permisos</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
