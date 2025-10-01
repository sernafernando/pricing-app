import { createPortal } from 'react-dom';
import { useState } from 'react';
import axios from 'axios';
import styles from './PricingModal.module.css';

export default function PricingModal({ producto, onClose, onSave }) {
  const [modo, setModo] = useState('markup');
  const [markupObjetivo, setMarkupObjetivo] = useState('42.98');
  const [precioManual, setPrecioManual] = useState('');
  const [calculando, setCalculando] = useState(false);
  const [resultado, setResultado] = useState(null);
  const [error, setError] = useState('');
  
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
