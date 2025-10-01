import { createPortal } from 'react-dom';
import { useState, useEffect } from 'react';
import axios from 'axios';
import styles from './PricingModal.module.css';

export default function PricingModal({ producto, onClose, onSave }) {
  const [modo, setModo] = useState('markup');
  const [markupObjetivo, setMarkupObjetivo] = useState('42.98');
  const [precioManual, setPrecioManual] = useState('');
  const [calculando, setCalculando] = useState(false);
  const [resultado, setResultado] = useState(null);
  const [error, setError] = useState('');

  const [ofertas, setOfertas] = useState(null);
  const [loadingOfertas, setLoadingOfertas] = useState(true);

  const cambiarModo = (nuevoModo) => {
    setModo(nuevoModo);
    setResultado(null);
    setError('');
  };
  
  const calcular = async () => {
    setCalculando(true);
    setError('');
    
    try {
      const token = localStorage.getItem('token');
      
      if (modo === 'markup') {
        const response = await axios.post(
          'https://pricing.gaussonline.com.ar/api/precios/calcular-completo',
          {
            item_id: producto.item_id,
            markup_objetivo: parseFloat(markupObjetivo),
            adicional_cuotas: 4.0,
          },
          { headers: { Authorization: `Bearer ${token}` } }
        );
        setResultado(response.data);
      } else {
        const responsePrecio = await axios.post(
          'https://pricing.gaussonline.com.ar/api/precios/calcular-por-precio',
          {
            item_id: producto.item_id,
            pricelist_id: 4,
            precio_manual: parseFloat(precioManual),
          },
          { headers: { Authorization: `Bearer ${token}` } }
        );
        
        const markupResultante = responsePrecio.data.markup_resultante;
        const responseCuotas = await axios.post(
          'https://pricing.gaussonline.com.ar/api/precios/calcular-completo',
          {
            item_id: producto.item_id,
            markup_objetivo: markupResultante,
            adicional_cuotas: 4.0,
          },
          { headers: { Authorization: `Bearer ${token}` } }
        );
        
        setResultado({
          modo: 'precio',
          clasica: responsePrecio.data,
          cuotas: responseCuotas.data.cuotas,
          precioManual: parseFloat(precioManual),
        });
      }
    } catch (err) {
      setError(err.response?.data?.detail || 'Error al calcular');
    } finally {
      setCalculando(false);
    }
  };
  
  const guardar = async () => {
    if (!resultado) return;
    
    const precio = modo === 'markup' ? resultado.clasica?.precio : resultado.precioManual;
    
    if (!precio) {
      setError('No hay precio para guardar');
      return;
    }
    
    try {
      const token = localStorage.getItem('token');
      await axios.post(
        'https://pricing.gaussonline.com.ar/api/precios/set',
        {
          item_id: producto.item_id,
          precio_lista_ml: precio,
          motivo: `Seteo ${modo === 'markup' ? 'por markup' : 'manual'}`,
        },
        { headers: { Authorization: `Bearer ${token}` } }
      );
      
      alert('Precio guardado exitosamente');
      onSave();
      onClose();
    } catch (err) {
      setError('Error al guardar precio');
    }
  };
  
  useEffect(() => {
  cargarOfertas();
  }, []);

  const cargarOfertas = async () => {
    setLoadingOfertas(true);
    try {
      const response = await axios.get(
        `https://pricing.gaussonline.com.ar/api/productos/${producto.item_id}/ofertas-vigentes`
      );
      setOfertas(response.data);
    } catch (error) {
      console.error('Error cargando ofertas:', error);
    } finally {
      setLoadingOfertas(false);
    }
  };

  const modalContent = (
    <div className={styles.overlay} onClick={onClose}>
      <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className={styles.header}>
          <div className={styles.headerInfo}>
            <h2>{producto.descripcion}</h2>
            <p>{producto.marca} | {producto.categoria} | Stock: {producto.stock}</p>
            <p className={styles.costInfo}>
              Costo: {producto.moneda_costo} ${producto.costo?.toFixed(2)}
            </p>
          </div>
          <button onClick={onClose} className={styles.closeBtn}>×</button>
        </div>
        
	{/* Ofertas vigentes */}
        {!loadingOfertas && ofertas && ofertas.con_oferta > 0 && (
          <div className={styles.section}>
            <h3 className={styles.label}>
              📢 Ofertas Vigentes ({ofertas.con_oferta} de {ofertas.total_publicaciones} publicaciones)
            </h3>
            <div style={{ maxHeight: '200px', overflowY: 'auto', border: '1px solid #e5e7eb', borderRadius: '6px', padding: '8px' }}>
              {ofertas.publicaciones
                .filter(p => p.tiene_oferta)
                .map((pub) => (
                  <div key={pub.mla} style={{ 
                    padding: '8px', 
                    marginBottom: '8px', 
                    backgroundColor: '#fef3c7',
                    borderRadius: '4px',
                    borderLeft: '3px solid #f59e0b'
                  }}>
                    <div style={{ fontSize: '11px', fontFamily: 'monospace', color: '#6b7280', marginBottom: '4px' }}>
                      {pub.mla}
                    </div>
                    <div style={{ fontSize: '12px', fontWeight: '600', marginBottom: '4px' }}>
                      {pub.lista_nombre}
                    </div>
                    <div style={{ fontSize: '14px', color: '#374151' }}>
                      Precio de oferta: <strong>${pub.oferta.precio_final.toLocaleString('es-AR')}</strong>
                    </div>
                    <div style={{ fontSize: '12px', color: '#6b7280' }}>
                      Aporte Meli: ${pub.oferta.aporte_meli_pesos.toLocaleString('es-AR')} 
                      {pub.oferta.aporte_meli_porcentaje && ` (${pub.oferta.aporte_meli_porcentaje}%)`}
                    </div>
                    <div style={{ fontSize: '11px', color: '#9ca3af', marginTop: '4px' }}>
                      Vigente hasta: {new Date(pub.oferta.fecha_hasta).toLocaleDateString('es-AR')}
                    </div>
                  </div>
                ))}
            </div>
          </div>
        )}
	
        {/* Selector de modo */}
        <div className={styles.section}>
          <label className={styles.label}>Modo de cálculo</label>
          <div className={styles.modeButtons}>
            <button
              onClick={() => cambiarModo('markup')}
              className={`${styles.modeBtn} ${modo === 'markup' ? styles.active : styles.inactive}`}
            >
              Por Markup Objetivo
            </button>
            <button
              onClick={() => cambiarModo('precio')}
              className={`${styles.modeBtn} ${modo === 'precio' ? styles.active : styles.inactive}`}
            >
              Por Precio Manual
            </button>
          </div>
        </div>
        
        {/* Inputs */}
        {modo === 'markup' ? (
          <div className={styles.section}>
            <label className={styles.label}>Markup Objetivo (%)</label>
            <input
              type="number"
              step="0.01"
              value={markupObjetivo}
              onChange={(e) => setMarkupObjetivo(e.target.value)}
              className={styles.input}
            />
            <p className={styles.hint}>Las cuotas tendrán +4% adicional</p>
          </div>
        ) : (
          <div className={styles.section}>
            <label className={styles.label}>Precio Manual ($)</label>
            <input
              type="number"
              step="0.01"
              value={precioManual}
              onChange={(e) => setPrecioManual(e.target.value)}
              placeholder="Ingrese el precio"
              className={styles.input}
            />
            <p className={styles.hint}>Se calcularán automáticamente los precios en cuotas</p>
          </div>
        )}
        
        <button
          onClick={calcular}
          disabled={calculando || (modo === 'precio' && !precioManual)}
          className={styles.calculateBtn}
        >
          {calculando ? 'Calculando...' : 'Calcular Precios'}
        </button>
        
        {error && <div className={styles.error}>{error}</div>}
        
        {/* Resultados modo markup */}
        {resultado && modo === 'markup' && resultado.clasica && (
          <div className={styles.results}>
            <h3 className={styles.resultsTitle}>Resultados</h3>
            
            <div className={styles.clasicaCard}>
              <div className={styles.clasicaHeader}>
                <h4 className={styles.clasicaTitle}>Clásica</h4>
                <span className={styles.clasicaPrice}>
                  ${resultado.clasica.precio.toLocaleString('es-AR')}
                </span>
              </div>
              <div className={styles.statsGrid}>
                <div>
                  <div className={styles.statLabel}>Comisión</div>
                  <div className={styles.statValue}>${resultado.clasica.comision_total.toLocaleString('es-AR')}</div>
                </div>
                <div>
                  <div className={styles.statLabel}>Limpio</div>
                  <div className={styles.statValue}>${resultado.clasica.limpio.toLocaleString('es-AR')}</div>
                </div>
                <div>
                  <div className={styles.statLabel}>Markup</div>
                  <div className={styles.statValueGreen}>{resultado.clasica.markup_real}%</div>
                </div>
              </div>
            </div>
            
            {resultado.cuotas && (
              <div className={styles.cuotasGrid}>
                {Object.entries(resultado.cuotas).map(([nombre, datos]) => (
                  <div key={nombre} className={styles.cuotaCard}>
                    <div className={styles.cuotaHeader}>
                      <h4 className={styles.cuotaTitle}>{nombre.replace('_', ' ')}</h4>
                      <span className={styles.cuotaPrice}>${datos.precio.toLocaleString('es-AR')}</span>
                    </div>
                    <div className={styles.cuotaMarkup}>
                      Markup: <strong>{datos.markup_real}%</strong>
                    </div>
                  </div>
                ))}
              </div>
            )}
            
            <button onClick={guardar} className={styles.saveBtn}>
              💾 Guardar Precio Clásica: ${resultado.clasica.precio.toLocaleString('es-AR')}
            </button>
          </div>
        )}
        
        {/* Resultados modo precio manual */}
        {resultado && modo === 'precio' && resultado.clasica && (
          <div className={styles.results}>
            <h3 className={styles.resultsTitle}>Resultados</h3>
            
            <div className={styles.clasicaCard}>
              <div className={styles.clasicaHeader}>
                <h4 className={styles.clasicaTitle}>Clásica (Precio Ingresado)</h4>
                <span className={styles.clasicaPrice}>
                  ${resultado.precioManual.toLocaleString('es-AR')}
                </span>
              </div>
              <div className={styles.statsGrid}>
                <div>
                  <div className={styles.statLabel}>Comisión</div>
                  <div className={styles.statValue}>${resultado.clasica.comision_total.toLocaleString('es-AR')}</div>
                </div>
                <div>
                  <div className={styles.statLabel}>Limpio</div>
                  <div className={styles.statValue}>${resultado.clasica.limpio.toLocaleString('es-AR')}</div>
                </div>
                <div>
                  <div className={styles.statLabel}>Markup</div>
                  <div className={styles.statValueGreen}>{resultado.clasica.markup_resultante}%</div>
                </div>
              </div>
            </div>
            
            {resultado.cuotas && (
              <>
                <p className={styles.hint}>
                  Precios en cuotas con markup {resultado.clasica.markup_resultante}% + 4%:
                </p>
                <div className={styles.cuotasGrid}>
                  {Object.entries(resultado.cuotas).map(([nombre, datos]) => (
                    <div key={nombre} className={styles.cuotaCard}>
                      <div className={styles.cuotaHeader}>
                        <h4 className={styles.cuotaTitle}>{nombre.replace('_', ' ')}</h4>
                        <span className={styles.cuotaPrice}>${datos.precio.toLocaleString('es-AR')}</span>
                      </div>
                      <div className={styles.cuotaMarkup}>
                        Markup: <strong>{datos.markup_real}%</strong>
                      </div>
                    </div>
                  ))}
                </div>
              </>
            )}
            
            <button onClick={guardar} className={styles.saveBtn}>
              💾 Guardar Precio Clásica: ${resultado.precioManual.toLocaleString('es-AR')}
            </button>
          </div>
        )}
      </div>
    </div>
  );
  
  return createPortal(modalContent, document.body);
}
