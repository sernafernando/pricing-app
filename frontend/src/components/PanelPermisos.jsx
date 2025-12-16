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

  const API_URL = 'https://pricing.gaussonline.com.ar/api';

  useEffect(() => {
    cargarDatos();
  }, []);

  const cargarDatos = async () => {
    try {
      const token = localStorage.getItem('token');
      const headers = { Authorization: `Bearer ${token}` };

      console.log('Cargando usuarios y catálogo de permisos...');

      const [usuariosRes, catalogoRes] = await Promise.all([
        axios.get(`${API_URL}/usuarios`, { headers }),
        axios.get(`${API_URL}/permisos/catalogo`, { headers })
      ]);

      console.log('Usuarios recibidos:', usuariosRes.data);
      console.log('Catálogo recibido:', catalogoRes.data);

      // Filtrar usuarios activos, manejando el caso donde activo puede ser undefined
      const usuariosActivos = Array.isArray(usuariosRes.data)
        ? usuariosRes.data.filter(u => u.activo !== false)
        : [];

      setUsuarios(usuariosActivos);
      setCatalogo(catalogoRes.data || {});
    } catch (error) {
      console.error('Error cargando datos:', error);
      console.error('Error response:', error.response?.data);
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

  const togglePermiso = async (permisoCodigo, estadoActual) => {
    if (!usuarioSeleccionado) return;

    setGuardando(true);
    try {
      const token = localStorage.getItem('token');
      const headers = { Authorization: `Bearer ${token}` };

      // Si el estado actual viene del rol base y queremos quitarlo, creamos override false
      // Si el estado actual viene de un override, lo eliminamos para volver al rol base
      // Si no tiene el permiso y queremos darlo, creamos override true

      const permisoInfo = Object.values(permisosUsuario.permisos_detallados)
        .flat()
        .find(p => p.codigo === permisoCodigo);

      if (permisoInfo.override !== null) {
        // Tiene override, lo eliminamos para volver al estado base del rol
        await axios.delete(`${API_URL}/permisos/override/${usuarioSeleccionado.id}/${permisoCodigo}`, { headers });
      } else {
        // No tiene override, creamos uno
        await axios.post(`${API_URL}/permisos/override`, {
          usuario_id: usuarioSeleccionado.id,
          permiso_codigo: permisoCodigo,
          concedido: !estadoActual,
          motivo: `Modificado desde panel de permisos`
        }, { headers });
      }

      // Recargar permisos del usuario
      await seleccionarUsuario(usuarioSeleccionado);
      setMensaje({ tipo: 'success', texto: 'Permiso actualizado' });
      setTimeout(() => setMensaje(null), 2000);
    } catch (error) {
      console.error('Error actualizando permiso:', error);
      setMensaje({ tipo: 'error', texto: 'Error al actualizar permiso' });
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
        motivo: `Override forzado desde panel de permisos`
      }, { headers });

      await seleccionarUsuario(usuarioSeleccionado);
      setMensaje({ tipo: 'success', texto: `Permiso ${conceder ? 'concedido' : 'denegado'}` });
      setTimeout(() => setMensaje(null), 2000);
    } catch (error) {
      console.error('Error forzando permiso:', error);
      setMensaje({ tipo: 'error', texto: 'Error al forzar permiso' });
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

  if (loading) {
    return <div className={styles.loading}>Cargando...</div>;
  }

  return (
    <div style={{ display: 'flex', gap: '20px', height: '70vh' }}>
      {/* Lista de usuarios */}
      <div style={{
        width: '300px',
        borderRight: '1px solid var(--border-color)',
        paddingRight: '20px',
        overflowY: 'auto'
      }}>
        <h3 style={{ marginBottom: '10px', color: 'var(--text-primary)' }}>Usuarios</h3>
        <input
          type="text"
          placeholder="Buscar usuario..."
          value={filtroUsuario}
          onChange={(e) => setFiltroUsuario(e.target.value)}
          style={{
            width: '100%',
            padding: '8px',
            marginBottom: '10px',
            borderRadius: '4px',
            border: '1px solid var(--border-color)',
            backgroundColor: 'var(--bg-secondary)',
            color: 'var(--text-primary)'
          }}
        />
        {usuariosFiltrados.map(usuario => (
          <div
            key={usuario.id}
            onClick={() => seleccionarUsuario(usuario)}
            style={{
              padding: '10px',
              marginBottom: '5px',
              borderRadius: '6px',
              cursor: 'pointer',
              backgroundColor: usuarioSeleccionado?.id === usuario.id
                ? 'var(--primary)'
                : 'var(--bg-secondary)',
              color: usuarioSeleccionado?.id === usuario.id
                ? 'var(--text-inverse)'
                : 'var(--text-primary)',
              transition: 'all 0.2s'
            }}
          >
            <div style={{ fontWeight: '500' }}>{usuario.nombre}</div>
            <div style={{ fontSize: '12px', opacity: 0.8 }}>
              {usuario.email}
            </div>
            <div style={{
              fontSize: '11px',
              marginTop: '4px',
              padding: '2px 6px',
              borderRadius: '3px',
              display: 'inline-block',
              backgroundColor: usuarioSeleccionado?.id === usuario.id
                ? 'rgba(255,255,255,0.2)'
                : 'var(--bg-tertiary)'
            }}>
              {usuario.rol}
            </div>
          </div>
        ))}
      </div>

      {/* Panel de permisos */}
      <div style={{ flex: 1, overflowY: 'auto' }}>
        {mensaje && (
          <div style={{
            padding: '10px 15px',
            marginBottom: '15px',
            borderRadius: '6px',
            backgroundColor: mensaje.tipo === 'error' ? 'var(--error-bg)' : 'var(--success-bg)',
            color: mensaje.tipo === 'error' ? 'var(--error-text)' : 'var(--success-text)'
          }}>
            {mensaje.texto}
          </div>
        )}

        {!usuarioSeleccionado ? (
          <div style={{
            textAlign: 'center',
            padding: '50px',
            color: 'var(--text-secondary)'
          }}>
            Selecciona un usuario para ver y editar sus permisos
          </div>
        ) : !permisosUsuario ? (
          <div className={styles.loading}>Cargando permisos...</div>
        ) : (
          <div>
            <div style={{
              marginBottom: '20px',
              padding: '15px',
              backgroundColor: 'var(--bg-secondary)',
              borderRadius: '8px'
            }}>
              <h3 style={{ margin: 0, color: 'var(--text-primary)' }}>
                {permisosUsuario.usuario_nombre}
              </h3>
              <div style={{ color: 'var(--text-secondary)', fontSize: '14px' }}>
                Rol base: <strong>{permisosUsuario.rol}</strong>
              </div>
              <div style={{ marginTop: '10px', fontSize: '13px', color: 'var(--text-secondary)' }}>
                <span style={{ marginRight: '15px' }}>
                  <span style={{ display: 'inline-block', width: '12px', height: '12px', backgroundColor: 'var(--success)', borderRadius: '2px', marginRight: '5px' }}></span>
                  Permiso activo
                </span>
                <span style={{ marginRight: '15px' }}>
                  <span style={{ display: 'inline-block', width: '12px', height: '12px', backgroundColor: 'var(--error)', borderRadius: '2px', marginRight: '5px' }}></span>
                  Sin permiso
                </span>
                <span style={{ marginRight: '15px' }}>
                  <span style={{ display: 'inline-block', width: '12px', height: '12px', backgroundColor: 'var(--primary)', borderRadius: '2px', marginRight: '5px' }}></span>
                  Override agregado
                </span>
                <span>
                  <span style={{ display: 'inline-block', width: '12px', height: '12px', backgroundColor: 'var(--warning)', borderRadius: '2px', marginRight: '5px' }}></span>
                  Override quitado
                </span>
              </div>
            </div>

            {Object.entries(permisosUsuario.permisos_detallados).map(([categoria, permisos]) => (
              <div key={categoria} style={{ marginBottom: '25px' }}>
                <h4 style={{
                  color: 'var(--text-primary)',
                  borderBottom: '1px solid var(--border-color)',
                  paddingBottom: '8px',
                  marginBottom: '12px'
                }}>
                  {CATEGORIAS_NOMBRE[categoria] || categoria}
                </h4>
                <div style={{ display: 'grid', gap: '8px' }}>
                  {permisos.map(permiso => {
                    const tieneOverride = permiso.override !== null;
                    const esOverridePositivo = permiso.override === true;
                    const esOverrideNegativo = permiso.override === false;

                    let bgColor = 'var(--bg-secondary)';
                    let borderColor = 'transparent';

                    if (esOverridePositivo) {
                      bgColor = 'var(--info-bg)';
                      borderColor = 'var(--primary)';
                    } else if (esOverrideNegativo) {
                      bgColor = 'var(--warning-bg)';
                      borderColor = 'var(--warning)';
                    }

                    return (
                      <div
                        key={permiso.codigo}
                        style={{
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'space-between',
                          padding: '10px 12px',
                          backgroundColor: bgColor,
                          borderRadius: '6px',
                          border: `1px solid ${borderColor}`,
                          opacity: guardando ? 0.6 : 1
                        }}
                      >
                        <div style={{ flex: 1 }}>
                          <div style={{
                            fontWeight: '500',
                            color: 'var(--text-primary)',
                            display: 'flex',
                            alignItems: 'center',
                            gap: '8px'
                          }}>
                            {permiso.nombre}
                            {permiso.es_critico && (
                              <span style={{
                                fontSize: '10px',
                                padding: '2px 5px',
                                backgroundColor: 'var(--error-bg)',
                                color: 'var(--error-text)',
                                borderRadius: '3px'
                              }}>
                                CRÍTICO
                              </span>
                            )}
                            {tieneOverride && (
                              <span style={{
                                fontSize: '10px',
                                padding: '2px 5px',
                                backgroundColor: esOverridePositivo ? 'var(--info-bg)' : 'var(--warning-bg)',
                                color: esOverridePositivo ? 'var(--info-text)' : 'var(--warning-text)',
                                borderRadius: '3px'
                              }}>
                                {esOverridePositivo ? 'AGREGADO' : 'QUITADO'}
                              </span>
                            )}
                          </div>
                          <div style={{
                            fontSize: '12px',
                            color: 'var(--text-secondary)',
                            marginTop: '2px'
                          }}>
                            {permiso.descripcion}
                          </div>
                        </div>

                        <div style={{ display: 'flex', gap: '5px', alignItems: 'center' }}>
                          {/* Indicador de estado del rol base */}
                          <span style={{
                            fontSize: '11px',
                            color: 'var(--text-secondary)',
                            marginRight: '10px'
                          }}>
                            Rol: {permiso.tiene_por_rol ? '✓' : '✗'}
                          </span>

                          {/* Botones de acción */}
                          {tieneOverride ? (
                            <button
                              onClick={() => resetearOverride(permiso.codigo)}
                              disabled={guardando}
                              style={{
                                padding: '5px 10px',
                                fontSize: '12px',
                                backgroundColor: 'var(--bg-tertiary)',
                                color: 'var(--text-primary)',
                                border: '1px solid var(--border-color)',
                                borderRadius: '4px',
                                cursor: guardando ? 'not-allowed' : 'pointer'
                              }}
                              title="Volver al permiso base del rol"
                            >
                              Resetear
                            </button>
                          ) : (
                            <>
                              {permiso.tiene_por_rol ? (
                                <button
                                  onClick={() => forzarPermiso(permiso.codigo, false)}
                                  disabled={guardando}
                                  style={{
                                    padding: '5px 10px',
                                    fontSize: '12px',
                                    backgroundColor: 'var(--warning-bg)',
                                    color: 'var(--warning-text)',
                                    border: 'none',
                                    borderRadius: '4px',
                                    cursor: guardando ? 'not-allowed' : 'pointer'
                                  }}
                                  title="Quitar este permiso al usuario"
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
                                    backgroundColor: 'var(--info-bg)',
                                    color: 'var(--info-text)',
                                    border: 'none',
                                    borderRadius: '4px',
                                    cursor: guardando ? 'not-allowed' : 'pointer'
                                  }}
                                  title="Agregar este permiso al usuario"
                                >
                                  Agregar
                                </button>
                              )}
                            </>
                          )}

                          {/* Indicador de estado efectivo */}
                          <div style={{
                            width: '24px',
                            height: '24px',
                            borderRadius: '4px',
                            backgroundColor: permiso.efectivo ? 'var(--success)' : 'var(--error)',
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
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
