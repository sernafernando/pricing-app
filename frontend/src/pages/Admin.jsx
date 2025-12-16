import { useState, useEffect } from 'react';
import axios from 'axios';
import styles from './Admin.module.css';
import PanelComisiones from '../components/PanelComisiones';
import PanelConstantesPricing from '../components/PanelConstantesPricing';
import PanelPermisos from '../components/PanelPermisos';
import PanelRoles from '../components/PanelRoles';

export default function Admin() {
  const [tabActiva, setTabActiva] = useState('general');
  const [sincronizando, setSincronizando] = useState(false);
  const [logSync, setLogSync] = useState([]);
  const [comisiones, setComisiones] = useState([]);
  const [tipoCambio, setTipoCambio] = useState(null);
  const [usuarios, setUsuarios] = useState([]);
  const [usuarioActual, setUsuarioActual] = useState(null);
  const [mostrarFormUsuario, setMostrarFormUsuario] = useState(false);
  const [nuevoUsuario, setNuevoUsuario] = useState({
    email: '',
    nombre: '',
    password: '',
    rol: 'user'
  });
  const [editandoUsuario, setEditandoUsuario] = useState(null);
  const [datosEdicion, setDatosEdicion] = useState({});
  const [cambiandoPassword, setCambiandoPassword] = useState(null);
  const [nuevaPassword, setNuevaPassword] = useState('');

  // Modal de confirmación de limpieza
  const [mostrarModalLimpieza, setMostrarModalLimpieza] = useState(false);
  const [tipoLimpieza, setTipoLimpieza] = useState(''); // 'rebate' o 'web-transferencia'
  const [palabraVerificacion, setPalabraVerificacion] = useState('');
  const [palabraObjetivo, setPalabraObjetivo] = useState('');

  useEffect(() => {
    cargarDatos();
  }, []);

  const cargarDatos = async () => {
    try {
      const token = localStorage.getItem('token');
      
      // Cargar tipo de cambio actual
      const tcRes = await axios.get('https://pricing.gaussonline.com.ar/api/tipo-cambio/actual', 
        { headers: { Authorization: `Bearer ${token}` }});
      setTipoCambio(tcRes.data);

      // Obtener usuario actual
	  const meRes = await axios.get('https://pricing.gaussonline.com.ar/api/auth/me',
	    { headers: { Authorization: `Bearer ${token}` }});
	    
	  const currentUser = meRes.data;
	    
	  // Cargar usuarios
	  const usuariosRes = await axios.get('https://pricing.gaussonline.com.ar/api/usuarios',
	    { headers: { Authorization: `Bearer ${token}` }});
	    
	  let usuariosFiltrados = usuariosRes.data;
	    
	  // Si es ADMIN, no puede ver SUPERADMIN
      if (currentUser.rol === 'ADMIN') {
	    usuariosFiltrados = usuariosFiltrados.filter(u => u.rol !== 'SUPERADMIN');
	  }
	   
	  setUsuarios(usuariosFiltrados);
	  setUsuarioActual(currentUser);

      // TODO: Cargar comisiones cuando esté el endpoint
    } catch (error) {
      console.error('Error cargando datos:', error);
    }
  };

  const agregarLog = (msg) => {
    setLogSync(prev => [...prev, `[${new Date().toLocaleTimeString()}] ${msg}`]);
  };

  const sincronizarTodo = async () => {
    if (!confirm('¿Sincronizar todos los datos? Esto puede tardar varios minutos.')) return;
    
    setSincronizando(true);
    setLogSync([]);
    
    try {
      const token = localStorage.getItem('token');
      
      agregarLog('Sincronizando tipo de cambio...');
      await axios.post('https://pricing.gaussonline.com.ar/api/sync-tipo-cambio', {}, 
        { headers: { Authorization: `Bearer ${token}` }});
      agregarLog('✓ Tipo de cambio sincronizado');
      
      agregarLog('Sincronizando productos ERP...');
      const erpRes = await axios.post('https://pricing.gaussonline.com.ar/api/sync', {}, 
        { headers: { Authorization: `Bearer ${token}` }});
      // Mostrar resultados ERP
      if (erpRes.data.erp) {
        const totalErp = (erpRes.data.erp.productos_nuevos || 0) + (erpRes.data.erp.productos_actualizados || 0);
        agregarLog(`✓ ERP: ${totalErp} productos sincronizados (${erpRes.data.erp.productos_nuevos || 0} nuevos, ${erpRes.data.erp.productos_actualizados || 0} actualizados)`);
      }
      
      // Mostrar resultados precios ML
      if (erpRes.data.precios_ml) {
        const totalPrecios = erpRes.data.precios_ml.exitosos || 0;
        agregarLog(`✓ Precios ML: ${totalPrecios} precios actualizados en ${erpRes.data.precios_ml.listas_procesadas?.length || 0} listas`);
        
        erpRes.data.precios_ml.listas_procesadas?.forEach(lista => {
          agregarLog(`  → ${lista.nombre}: ${lista.items} items`);
        });
      }
      
      agregarLog('Sincronizando publicaciones ML...');
      const mlRes = await axios.post('https://pricing.gaussonline.com.ar/api/sync-ml', {},
        { headers: { Authorization: `Bearer ${token}` }});
      agregarLog(`✓ ML: ${mlRes.data.total_publicaciones || 0} publicaciones`);
      
      agregarLog('Sincronizando ofertas...');
      const sheetsRes = await axios.post('https://pricing.gaussonline.com.ar/api/sync-sheets', {}, 
        { headers: { Authorization: `Bearer ${token}` }});
      agregarLog(`✓ Ofertas: ${sheetsRes.data.total} sincronizadas`);
      
      agregarLog('Recalculando markups...');
      const markupRes = await axios.post('https://pricing.gaussonline.com.ar/api/recalcular-markups', {}, 
        { headers: { Authorization: `Bearer ${token}` }});
      agregarLog(`✓ Markups: ${markupRes.data.actualizados} actualizados`);
      
      agregarLog('=== SINCRONIZACIÓN COMPLETADA ===');
      cargarDatos();
    } catch (error) {
      agregarLog(`❌ Error: ${error.message}`);
    } finally {
      setSincronizando(false);
    }
  };

  const sincronizarPreciosML = async () => {
    try {
      const token = localStorage.getItem('token');
      const response = await axios.post(
        'https://pricing.gaussonline.com.ar/api/sync-ml/precios',
        {},
        { headers: { Authorization: `Bearer ${token}` } }
      );
      alert('Sincronización iniciada: ' + JSON.stringify(response.data));
    } catch (error) {
      alert('Error al sincronizar: ' + error.message);
    }
  };

  const guardarEdicion = async (usuarioId) => {
    try {
      const token = localStorage.getItem('token');
      
      // Solo enviar los campos que cambiaron
      const cambios = {};
      if (datosEdicion.nombre !== undefined) cambios.nombre = datosEdicion.nombre;
      if (datosEdicion.rol !== undefined) cambios.rol = datosEdicion.rol;
      
      console.log('Guardando cambios:', cambios); // Debug
      
      await axios.patch(
        `https://pricing.gaussonline.com.ar/api/usuarios/${usuarioId}`,
        cambios,
        { headers: { Authorization: `Bearer ${token}` }}
      );
  
      alert('✅ Usuario actualizado');
      setEditandoUsuario(null);
      setDatosEdicion({});
      cargarDatos();
    } catch (error) {
      console.error('Error completo:', error.response); // Debug
      alert('❌ Error: ' + (error.response?.data?.detail || error.message));
    }
  };
  
  const crearUsuario = async () => {
    try {
      const token = localStorage.getItem('token');
      await axios.post('https://pricing.gaussonline.com.ar/api/usuarios', nuevoUsuario, 
        { headers: { Authorization: `Bearer ${token}` }});
      
      alert('✅ Usuario creado');
      setMostrarFormUsuario(false);
      setNuevoUsuario({ email: '', nombre: '', password: '', rol: 'user' });
      cargarDatos();
    } catch (error) {
      alert('❌ Error: ' + (error.response?.data?.detail || error.message));
    }
  };
  
  const toggleUsuario = async (id, activo) => {
    try {
      const token = localStorage.getItem('token');
      await axios.patch(`https://pricing.gaussonline.com.ar/api/usuarios/${id}`,
        { activo: !activo },
        { headers: { Authorization: `Bearer ${token}` }});

      cargarDatos();
    } catch (error) {
      alert('❌ Error al modificar usuario');
    }
  };

  const cambiarPassword = async (usuarioId) => {
    if (!nuevaPassword || nuevaPassword.length < 6) {
      alert('❌ La contraseña debe tener al menos 6 caracteres');
      return;
    }

    try {
      const token = localStorage.getItem('token');
      await axios.patch(
        `https://pricing.gaussonline.com.ar/api/usuarios/${usuarioId}/password`,
        { nueva_password: nuevaPassword },
        { headers: { Authorization: `Bearer ${token}` }}
      );

      alert('✅ Contraseña actualizada correctamente');
      setCambiandoPassword(null);
      setNuevaPassword('');
    } catch (error) {
      alert('❌ Error: ' + (error.response?.data?.detail || error.message));
    }
  };

  const abrirModalLimpieza = (tipo) => {
    // Palabras fijas para cada tipo de limpieza
    const palabrasPorTipo = {
      'rebate': ['LIMPIAR', 'REBATE', 'ELIMINAR', 'MASIVO', 'TODOS'],
      'web-transferencia': ['LIMPIAR', 'TRANSFERENCIA', 'ELIMINAR', 'MASIVO', 'TODOS']
    };

    const palabras = palabrasPorTipo[tipo];
    const palabraAleatoria = palabras[Math.floor(Math.random() * palabras.length)];

    setTipoLimpieza(tipo);
    setPalabraObjetivo(palabraAleatoria);
    setPalabraVerificacion('');
    setMostrarModalLimpieza(true);
  };

  const confirmarLimpieza = async () => {
    // Verificar palabra
    if (palabraVerificacion.toUpperCase() !== palabraObjetivo.toUpperCase()) {
      alert('La palabra de verificación no coincide');
      return;
    }

    try {
      const token = localStorage.getItem('token');
      const endpoint = tipoLimpieza === 'rebate'
        ? 'https://pricing.gaussonline.com.ar/api/productos/limpiar-rebate'
        : 'https://pricing.gaussonline.com.ar/api/productos/limpiar-web-transferencia';

      const response = await axios.post(
        endpoint,
        {},
        { headers: { Authorization: `Bearer ${token}` } }
      );

      alert(`✓ ${response.data.mensaje}\nProductos actualizados: ${response.data.productos_actualizados}`);

      // Cerrar modal
      setMostrarModalLimpieza(false);
      setTipoLimpieza('');
      setPalabraVerificacion('');
      setPalabraObjetivo('');
    } catch (error) {
      console.error('Error:', error);
      alert('Error al realizar la limpieza');
    }
  };


  return (
    <div className={styles.container}>
      <h1 className={styles.title}>Panel de Administración</h1>

      {/* Tabs */}
      <div className={styles.tabs}>
        <button
          className={`${styles.tab} ${tabActiva === 'general' ? styles.tabActive : ''}`}
          onClick={() => setTabActiva('general')}
        >
          General
        </button>
        <button
          className={`${styles.tab} ${tabActiva === 'comisiones' ? styles.tabActive : ''}`}
          onClick={() => setTabActiva('comisiones')}
        >
          Comisiones
        </button>
        <button
          className={`${styles.tab} ${tabActiva === 'constantes' ? styles.tabActive : ''}`}
          onClick={() => setTabActiva('constantes')}
        >
          Constantes Pricing
        </button>
        <button
          className={`${styles.tab} ${tabActiva === 'permisos' ? styles.tabActive : ''}`}
          onClick={() => setTabActiva('permisos')}
        >
          Permisos
        </button>
        <button
          className={`${styles.tab} ${tabActiva === 'roles' ? styles.tabActive : ''}`}
          onClick={() => setTabActiva('roles')}
        >
          Roles
        </button>
      </div>

      {tabActiva === 'general' && (
        <>
      {/* Sección Sincronización */}
      <div className={styles.section}>
        <h2 className={styles.sectionTitle}>Sincronización de Datos</h2>
        <p className={styles.description}>
          Sincroniza productos del ERP, publicaciones de Mercado Libre, ofertas desde Google Sheets y recalcula markups.
        </p>
        
        <button 
          onClick={sincronizarTodo} 
          disabled={sincronizando}
          className={styles.syncButton}
        >
          {sincronizando ? '⏳ Sincronizando...' : '🔄 Sincronizar Todo'}
        </button>

        {logSync.length > 0 && (
          <div className={styles.logContainer}>
            <h3>Log de Sincronización</h3>
            <div className={styles.log}>
              {logSync.map((msg, i) => (
                <div key={i} className={styles.logLine}>{msg}</div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Sección Tipo de Cambio */}
      <div className={styles.section}>
        <h2 className={styles.sectionTitle}>Tipo de Cambio</h2>
        {tipoCambio ? (
          <div className={styles.infoGrid}>
            <div className={styles.infoCard}>
              <div className={styles.infoLabel}>USD Compra</div>
              <div className={styles.infoValue}>${tipoCambio.compra}</div>
            </div>
            <div className={styles.infoCard}>
              <div className={styles.infoLabel}>USD Venta</div>
              <div className={styles.infoValue}>${tipoCambio.venta}</div>
            </div>
            <div className={styles.infoCard}>
              <div className={styles.infoLabel}>Fuente</div>
              <div className={styles.infoValue} style={{ fontSize: '16px' }}>
                BNA - {tipoCambio.fecha.split('-').reverse().join('/')}
              </div>
            </div>
          </div>
        ) : (
          <p>Cargando...</p>
        )}
      </div>

	  {/* Sección Limpieza Masiva */}
	  	<div className={styles.section}>
	  	  <h2 className={styles.sectionTitle}>Limpieza Masiva de Precios</h2>
	  	  <p className={styles.description}>
	  	    Desactiva rebate o web transferencia en todos los productos.
	  	  </p>
	  	  
	  	  <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap' }}>
	  	    <button
	  	      onClick={() => abrirModalLimpieza('rebate')}
	  	      className={styles.secondaryButton}
	  	      style={{ background: '#ef4444', color: 'white', cursor: 'pointer' }}
	  	    >
	  	      🧹 Limpiar Rebate
	  	    </button>

	  	    <button
	  	      onClick={() => abrirModalLimpieza('web-transferencia')}
	  	      className={styles.secondaryButton}
	  	      style={{ background: '#f59e0b', color: 'white', cursor: 'pointer' }}
	  	    >
	  	      🧹 Limpiar Web Transferencia
	  	    </button>
	  	  </div>
	  	</div>	
    	  

     {/* Sección Usuarios */}
      <div className={styles.section}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
          <h2 className={styles.sectionTitle}>Gestión de Usuarios</h2>
          <button 
            onClick={() => setMostrarFormUsuario(!mostrarFormUsuario)}
            className={styles.syncButton}
            style={{ padding: '8px 16px', fontSize: '14px' }}
          >
            {mostrarFormUsuario ? '❌ Cancelar' : '➕ Nuevo Usuario'}
          </button>
        </div>
      
        {mostrarFormUsuario && (
          <div style={{ 
            background: '#f9fafb', 
            padding: '20px', 
            borderRadius: '8px', 
            marginBottom: '20px',
            border: '1px solid #e5e7eb'
          }}>
            <h3 style={{ marginBottom: '16px' }}>Crear Nuevo Usuario</h3>
            <div style={{ display: 'grid', gap: '12px' }}>
              <input
                type="email"
                placeholder="Email"
                value={nuevoUsuario.email}
                onChange={(e) => setNuevoUsuario({...nuevoUsuario, email: e.target.value})}
                style={{ padding: '10px', borderRadius: '6px', border: '1px solid #d1d5db' }}
              />
              <input
                type="text"
                placeholder="Nombre completo"
                value={nuevoUsuario.nombre}
                onChange={(e) => setNuevoUsuario({...nuevoUsuario, nombre: e.target.value})}
                style={{ padding: '10px', borderRadius: '6px', border: '1px solid #d1d5db' }}
              />
              <input
                type="password"
                placeholder="Contraseña"
                value={nuevoUsuario.password}
                onChange={(e) => setNuevoUsuario({...nuevoUsuario, password: e.target.value})}
                style={{ padding: '10px', borderRadius: '6px', border: '1px solid #d1d5db' }}
              />
              <select
                value={nuevoUsuario.rol || datosEdicion.rol}
                onChange={(e) => nuevoUsuario.rol 
                  ? setNuevoUsuario({...nuevoUsuario, rol: e.target.value})
                  : setDatosEdicion({...datosEdicion, rol: e.target.value})
                }
                style={{ padding: '8px', borderRadius: '4px', border: '1px solid #d1d5db' }}
              >
                {usuarioActual?.rol === 'SUPERADMIN' && <option value="SUPERADMIN">Superadmin</option>}
                <option value="ADMIN">Admin</option>
                <option value="GERENTE">Gerente</option>
                <option value="PRICING">Pricing</option>
                <option value="VENTAS">Ventas</option>
              </select>
              <button 
                onClick={crearUsuario}
                className={styles.syncButton}
              >
                Crear Usuario
              </button>
            </div>
          </div>
        )}
      
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ borderBottom: '2px solid #e5e7eb', textAlign: 'left' }}>
              <th style={{ padding: '12px' }}>Email</th>
              <th style={{ padding: '12px' }}>Nombre</th>
              <th style={{ padding: '12px' }}>Rol</th>
              <th style={{ padding: '12px' }}>Estado</th>
              <th style={{ padding: '12px' }}>Acciones</th>
            </tr>
          </thead>
         <tbody>
            {usuarios.map(user => (
              <tr key={user.id} style={{ borderBottom: '1px solid #e5e7eb' }}>
                <td style={{ padding: '12px' }}>{user.email}</td>
                
                {/* Nombre editable */}
                <td style={{ padding: '12px' }}>
                  {editandoUsuario === user.id ? (
                    <div style={{ display: 'flex', gap: '4px', alignItems: 'center' }}>
                      <input
                        type="text"
                        value={datosEdicion.nombre ?? user.nombre}
                        onChange={(e) => setDatosEdicion({...datosEdicion, nombre: e.target.value})}
                        style={{ padding: '6px', borderRadius: '4px', border: '1px solid #d1d5db', flex: 1 }}
                      />
                      <button
                        onClick={() => guardarEdicion(user.id)}
                        style={{
                          padding: '6px 10px',
                          background: '#10b981',
                          color: 'white',
                          border: 'none',
                          borderRadius: '4px',
                          cursor: 'pointer'
                        }}
                      >
                        ✓
                      </button>
                      <button
                        onClick={() => {
                          setEditandoUsuario(null);
                          setDatosEdicion({});
                        }}
                        style={{
                          padding: '6px 10px',
                          background: '#ef4444',
                          color: 'white',
                          border: 'none',
                          borderRadius: '4px',
                          cursor: 'pointer'
                        }}
                      >
                        ✗
                      </button>
                    </div>
                  ) : (
                    <span 
                      onClick={() => setEditandoUsuario(user.id)}
                      style={{ cursor: 'pointer', borderBottom: '1px dashed #ccc' }}
                    >
                      {user.nombre}
                    </span>
                  )}
                </td>
                
                {/* Rol editable */}
                <td style={{ padding: '12px' }}>
                  {editandoUsuario === user.id ? (
                    <select
                      value={datosEdicion.rol ?? user.rol}
                      onChange={(e) => setDatosEdicion({...datosEdicion, rol: e.target.value})}
                      style={{ padding: '6px', borderRadius: '4px', border: '1px solid #d1d5db' }}
                    >
                      {usuarioActual?.rol === 'SUPERADMIN' && <option value="SUPERADMIN">Superadmin</option>}
                      <option value="ADMIN">Admin</option>
                      <option value="GERENTE">Gerente</option>
                      <option value="PRICING">Pricing</option>
                      <option value="VENTAS">Ventas</option>
                    </select>
                  ) : (
                    <span style={{
                      padding: '4px 8px',
                      borderRadius: '4px',
                      fontSize: '12px',
                      fontWeight: '600',
                      background:
                        user.rol === 'SUPERADMIN' ? '#fef3c7' :
                        user.rol === 'ADMIN' ? '#dbeafe' :
                        user.rol === 'GERENTE' ? '#e0e7ff' :
                        user.rol === 'PRICING' ? '#d1fae5' : 
                        user.rol === 'VENTAS' ? '#fce7f3' : '#f3f4f6',
                      color:
                        user.rol === 'SUPERADMIN' ? '#92400e' :
                        user.rol === 'ADMIN' ? '#1e40af' :
                        user.rol === 'GERENTE' ? '#4338ca' :
                        user.rol === 'PRICING' ? '#065f46' :
                        user.rol === 'VENTAS' ? '#be185d' : '#374151'
                    }}>
                      {user.rol === 'SUPERADMIN' ? '👑 Superadmin' :
                       user.rol === 'ADMIN' ? '⚙️ Admin' :
                       user.rol === 'GERENTE' ? '📊 Gerente' :
                       user.rol === 'PRICING' ? '💰 Pricing' : 
                       user.rol === 'VENTAS' ? '🤝 Ventas' : user.rol}
                    </span>
                  )}
                </td>
                
                {/* Estado */}
                <td style={{ padding: '12px' }}>
                  <span style={{
                    padding: '4px 8px',
                    borderRadius: '4px',
                    fontSize: '12px',
                    fontWeight: '600',
                    background: user.activo ? '#dcfce7' : '#fee2e2',
                    color: user.activo ? '#166534' : '#991b1b'
                  }}>
                    {user.activo ? '✅ Activo' : '❌ Inactivo'}
                  </span>
                </td>
                
                {/* Acciones */}
                <td style={{ padding: '12px' }}>
                  <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                    <button
                      onClick={() => toggleUsuario(user.id, user.activo)}
                      style={{
                        padding: '6px 12px',
                        borderRadius: '4px',
                        border: 'none',
                        background: user.activo ? '#fee2e2' : '#dcfce7',
                        color: user.activo ? '#991b1b' : '#166534',
                        cursor: 'pointer',
                        fontSize: '13px'
                      }}
                    >
                      {user.activo ? 'Desactivar' : 'Activar'}
                    </button>

                    {cambiandoPassword === user.id ? (
                      <div style={{ display: 'flex', gap: '4px', alignItems: 'center' }}>
                        <input
                          type="password"
                          placeholder="Nueva contraseña"
                          value={nuevaPassword}
                          onChange={(e) => setNuevaPassword(e.target.value)}
                          style={{
                            padding: '6px',
                            borderRadius: '4px',
                            border: '1px solid #d1d5db',
                            fontSize: '13px',
                            width: '150px'
                          }}
                        />
                        <button
                          onClick={() => cambiarPassword(user.id)}
                          style={{
                            padding: '6px 10px',
                            background: '#10b981',
                            color: 'white',
                            border: 'none',
                            borderRadius: '4px',
                            cursor: 'pointer'
                          }}
                        >
                          ✓
                        </button>
                        <button
                          onClick={() => {
                            setCambiandoPassword(null);
                            setNuevaPassword('');
                          }}
                          style={{
                            padding: '6px 10px',
                            background: '#ef4444',
                            color: 'white',
                            border: 'none',
                            borderRadius: '4px',
                            cursor: 'pointer'
                          }}
                        >
                          ✗
                        </button>
                      </div>
                    ) : (
                      <button
                        onClick={() => setCambiandoPassword(user.id)}
                        style={{
                          padding: '6px 12px',
                          borderRadius: '4px',
                          border: 'none',
                          background: '#dbeafe',
                          color: '#1e40af',
                          cursor: 'pointer',
                          fontSize: '13px'
                        }}
                      >
                        🔑 Cambiar Password
                      </button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      </>
      )}

      {tabActiva === 'comisiones' && (
        <PanelComisiones />
      )}

      {tabActiva === 'constantes' && (
        <PanelConstantesPricing />
      )}

      {tabActiva === 'permisos' && (
        <PanelPermisos />
      )}

      {tabActiva === 'roles' && (
        <PanelRoles />
      )}

      {/* Modal de confirmación de limpieza */}
      {mostrarModalLimpieza && (
        <div className={styles.modalOverlay}>
          <div className={styles.modalContent}>
            <h2 className={styles.modalTitle}>⚠️ Confirmar Limpieza Masiva</h2>

            <div className={styles.modalInfo}>
              <p><strong>Acción:</strong> {tipoLimpieza === 'rebate' ? 'Limpiar Rebate' : 'Limpiar Web Transferencia'}</p>
              <p><strong>Afectará:</strong> TODOS los productos</p>
              <p style={{ color: '#dc2626', fontWeight: 'bold' }}>
                Esta acción {tipoLimpieza === 'rebate' ? 'desactivará el rebate' : 'desactivará la web transferencia'} en todos los productos de la base de datos.
              </p>
            </div>

            <div className={styles.modalWarning}>
              <p>Para confirmar, escribe la siguiente palabra:</p>
              <p className={styles.modalWord}>{palabraObjetivo}</p>
            </div>

            <div className={styles.modalField}>
              <label>Palabra de verificación:</label>
              <input
                type="text"
                value={palabraVerificacion}
                onChange={(e) => setPalabraVerificacion(e.target.value)}
                placeholder="Escribe la palabra aquí"
                className={styles.modalInput}
                autoFocus
              />
            </div>

            <div className={styles.modalActions}>
              <button
                onClick={() => {
                  setMostrarModalLimpieza(false);
                  setTipoLimpieza('');
                  setPalabraVerificacion('');
                  setPalabraObjetivo('');
                }}
                className={styles.modalBtnCancel}
              >
                Cancelar
              </button>
              <button
                onClick={confirmarLimpieza}
                className={styles.modalBtnConfirm}
              >
                Confirmar Limpieza
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
