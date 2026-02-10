import { useState, useEffect } from 'react';
import api from '../services/api';
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
      // Cargar tipo de cambio actual
      const tcRes = await api.get('/tipo-cambio/actual');
      setTipoCambio(tcRes.data);
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
      agregarLog('Sincronizando tipo de cambio...');
      await api.post('/sync-tipo-cambio', {});
      agregarLog('✓ Tipo de cambio sincronizado');
      
      agregarLog('Sincronizando productos ERP...');
      const erpRes = await api.post('/sync', {});
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
      const mlRes = await api.post('/sync-ml', {});
      agregarLog(`✓ ML: ${mlRes.data.total_publicaciones || 0} publicaciones`);
      
      agregarLog('Sincronizando ofertas...');
      const sheetsRes = await api.post('/sync-sheets', {});
      agregarLog(`✓ Ofertas: ${sheetsRes.data.total} sincronizadas`);
      
      agregarLog('Recalculando markups...');
      const markupRes = await api.post('/recalcular-markups', {});
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
      const response = await api.post('/sync-ml/precios', {});
      alert('Sincronización iniciada: ' + JSON.stringify(response.data));
    } catch (error) {
      alert('Error al sincronizar: ' + error.message);
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
      const endpoint = tipoLimpieza === 'rebate'
        ? '/productos/limpiar-rebate'
        : '/productos/limpiar-web-transferencia';

      const response = await api.post(endpoint, {});

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
          Usuarios
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
	  	      className="btn-tesla outline-subtle-danger sm"
	  	    >
	  	      🧹 Limpiar Rebate
	  	    </button>

	  	    <button
	  	      onClick={() => abrirModalLimpieza('web-transferencia')}
	  	      className="btn-tesla outline-subtle-warning sm"
	  	    >
	  	      🧹 Limpiar Web Transferencia
	  	    </button>
	  	  </div>
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
            <h2 className={styles.modalTitle}>Confirmar Limpieza Masiva</h2>

            <div className={styles.modalInfo}>
              <p><strong>Accion:</strong> {tipoLimpieza === 'rebate' ? 'Limpiar Rebate' : 'Limpiar Web Transferencia'}</p>
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
