import { useState, useEffect } from 'react';
import axios from 'axios';
import styles from './Admin.module.css';

export default function Admin() {
  const [sincronizando, setSincronizando] = useState(false);
  const [logSync, setLogSync] = useState([]);
  const [comisiones, setComisiones] = useState([]);
  const [tipoCambio, setTipoCambio] = useState(null);

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
      agregarLog(`✓ ERP: ${erpRes.data.total_sincronizados} productos`);
      
      agregarLog('Sincronizando publicaciones ML...');
      const mlRes = await axios.post('https://pricing.gaussonline.com.ar/api/sync-ml', {}, 
        { headers: { Authorization: `Bearer ${token}` }});
      agregarLog(`✓ ML: ${mlRes.data.total_publicaciones} publicaciones`);
      
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
        <h2 className={styles.sectionTitle}>Gestión de Usuarios</h2>
        <p className={styles.description}>
          Administrar usuarios y permisos del sistema (próximamente).
        </p>
        <button className={styles.secondaryButton} disabled>
          Gestionar Usuarios
        </button>
      </div>
    </div>
  );
}
