import { useState, useEffect } from 'react';
import axios from 'axios';
import styles from './Admin.module.css';

export default function Admin() {
  const [sincronizando, setSincronizando] = useState(false);
  const [logSync, setLogSync] = useState([]);
  const [comisiones, setComisiones] = useState([]);
  const [tipoCambio, setTipoCambio] = useState(null);
  const [usuarios, setUsuarios] = useState([]);
  const [mostrarFormUsuario, setMostrarFormUsuario] = useState(false);
  const [nuevoUsuario, setNuevoUsuario] = useState({
    email: '',
    nombre: '',
    password: '',
    rol: 'user'
  });
  const [editandoUsuario, setEditandoUsuario] = useState(null);
  const [datosEdicion, setDatosEdicion] = useState({});

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

      // Cargar usuarios
      const usuariosRes = await axios.get('https://pricing.gaussonline.com.ar/api/usuarios', 
        { headers: { Authorization: `Bearer ${token}` }});
      setUsuarios(usuariosRes.data);
      
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
      if (erpRes.data.erp) {
        const totalErp = (erpRes.data.erp.productos_nuevos || 0) + (erpRes.data.erp.productos_actualizados || 0);
        agregarLog(`✓ ERP: ${totalErp} productos sincronizados (${erpRes.data.erp.productos_nuevos || 0} nuevos, ${erpRes.data.erp.productos_actualizados || 0} actualizados)`);
      }
      
      agregarLog('Sincronizando publicaciones ML...');
      const mlRes = await axios.post('https://pricing.gaussonline.com.ar/api/sync-ml', {}, 
        { headers: { Authorization: `Bearer ${token}` }});
      if (erpRes.data.precios_ml) {
        agregarLog(`✓ Precios ML: ${erpRes.data.precios_ml.exitosos} precios actualizados en ${erpRes.data.precios_ml.listas_procesadas?.length || 0} listas`);
        erpRes.data.precios_ml.listas_procesadas?.forEach(lista => {
          agregarLog(`  → ${lista.nombre}: ${lista.items} items`);
        });
      }
      
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

  return (
    <div className={styles.container}>
      <h1 className={styles.title}>Panel de Administración</h1>

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

      {/* Sección Comisiones */}
      <div className={styles.section}>
        <h2 className={styles.sectionTitle}>Comisiones y Tiers</h2>
        <p className={styles.description}>
          Configuración de comisiones por lista y grupo de productos (próximamente).
        </p>
        <button className={styles.secondaryButton} disabled>
          Gestionar Comisiones
        </button>
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
                value={nuevoUsuario.rol}
                onChange={(e) => setNuevoUsuario({...nuevoUsuario, rol: e.target.value})}
                style={{ padding: '10px', borderRadius: '6px', border: '1px solid #d1d5db' }}
              >
                <option value="user">Usuario</option>
                <option value="admin">Administrador</option>
                <option value="superadmin">Super Administrador</option>
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
                      <option value="AUDITOR">Auditor</option>
                      <option value="ANALISTA">Analista</option>
                      <option value="PRICING_MANAGER">Pricing Manager</option>
                      <option value="ADMIN">Administrador</option>
                      <option value="SUPERADMIN">Super Administrador</option>
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
                        user.rol === 'PRICING_MANAGER' ? '#e0e7ff' :
                        user.rol === 'ANALISTA' ? '#fce7f3' : '#f3f4f6',
                      color: 
                        user.rol === 'SUPERADMIN' ? '#92400e' : 
                        user.rol === 'ADMIN' ? '#1e40af' : 
                        user.rol === 'PRICING_MANAGER' ? '#4338ca' :
                        user.rol === 'ANALISTA' ? '#be185d' : '#374151'
                    }}>
                      {user.rol === 'SUPERADMIN' ? '⭐ Super Admin' : 
                       user.rol === 'ADMIN' ? '👑 Admin' : 
                       user.rol === 'PRICING_MANAGER' ? '💰 Pricing Manager' :
                       user.rol === 'ANALISTA' ? '📊 Analista' : '👁️ Auditor'}
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
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
