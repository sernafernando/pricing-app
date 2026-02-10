/**
 * PRICING MODAL - Migrado a ModalTesla
 * 
 * Cambios principales:
 * - Usa ModalTesla como base
 * - Botones estandarizados (btn-tesla)
 * - ModalAlert para ofertas vigentes
 * - ModalSection para organización
 * - Footer con ModalFooterButtons
 * - Eliminados estilos inline
 */

import { useState, useEffect, useCallback } from 'react';
import api from '../services/api';
import ModalTesla, { ModalSection, ModalAlert, ModalFooterButtons } from './ModalTesla';
import './PricingModalTesla.css';

export default function PricingModalTesla({ producto, onClose, onSave, isOpen }) {
  const [modo, setModo] = useState('markup');
  const [markupObjetivo, setMarkupObjetivo] = useState('42.98');
  const [precioManual, setPrecioManual] = useState('');
  const [calculando, setCalculando] = useState(false);
  const [guardando, setGuardando] = useState(false);
  const [resultado, setResultado] = useState(null);
  const [error, setError] = useState('');

  const [participaRebate, setParticipaRebate] = useState(false);
  const [porcentajeRebate, setPorcentajeRebate] = useState(3.8);

  const [ofertas, setOfertas] = useState(null);
  const [loadingOfertas, setLoadingOfertas] = useState(true);

  const cargarOfertas = useCallback(async () => {
    if (!producto) return;
    
    setLoadingOfertas(true);
    try {
      const response = await api.get(
        `/productos/${producto.item_id}/ofertas-vigentes`
      );
      setOfertas(response.data);
    } catch (error) {
      console.error('Error cargando ofertas:', error);
    } finally {
      setLoadingOfertas(false);
    }
  }, [producto]);

  useEffect(() => {
    if (isOpen) {
      cargarOfertas();
    }
  }, [isOpen, cargarOfertas]);

  // Resetear estado cuando cambia el producto o se abre el modal
  useEffect(() => {
    if (isOpen && producto) {
      setResultado(null);
      setError('');
      setMarkupObjetivo('42.98');
      setPrecioManual('');
      setModo('markup');
      setParticipaRebate(false);
      setPorcentajeRebate(3.8);
    }
  }, [isOpen, producto?.item_id]);

  // Early return DESPUÉS de los hooks
  if (!producto) {
    return null;
  }

  const cambiarModo = (nuevoModo) => {
    setModo(nuevoModo);
    setResultado(null);
    setError('');
  };

  const calcular = async () => {
    setCalculando(true);
    setError('');

    try {
      if (modo === 'markup') {
        const response = await api.post(
          '/precios/calcular-completo',
          {
            item_id: producto.item_id,
            markup_objetivo: parseFloat(markupObjetivo),
            adicional_cuotas: 4.0,
          }
        );
        setResultado(response.data);
      } else {
        const responsePrecio = await api.post(
          '/precios/calcular-por-precio',
          {
            item_id: producto.item_id,
            pricelist_id: 4,
            precio_manual: parseFloat(precioManual),
          }
        );

        const markupResultante = responsePrecio.data.markup_resultante;
        const responseCuotas = await api.post(
          '/precios/calcular-completo',
          {
            item_id: producto.item_id,
            markup_objetivo: markupResultante,
            adicional_cuotas: 4.0,
          }
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

    if (!precio || precio <= 0) {
      setError('El precio debe ser mayor a 0');
      return;
    }

    if (precio > 999999999.99) {
      setError('El precio no puede ser mayor a $999.999.999,99');
      return;
    }

    setGuardando(true);

    try {
      const cuotas = resultado.cuotas || {};

      await api.post(
        '/precios/set',
        {
          item_id: producto.item_id,
          precio_lista_ml: precio,
          motivo: `Seteo ${modo === 'markup' ? 'por markup' : 'manual'}`,
          participa_rebate: participaRebate,
          porcentaje_rebate: porcentajeRebate,
          precio_3_cuotas: cuotas['3_cuotas']?.precio || null,
          precio_6_cuotas: cuotas['6_cuotas']?.precio || null,
          precio_9_cuotas: cuotas['9_cuotas']?.precio || null,
          precio_12_cuotas: cuotas['12_cuotas']?.precio || null
        }
      );

      alert('Precio guardado exitosamente');
      onSave();
      onClose();
    } catch (err) {
      console.error('Error al guardar precio:', err);
      setError(err.response?.data?.detail || 'Error al guardar precio');
    } finally {
      setGuardando(false);
    }
  };

  const subtitle = `${producto.marca} | ${producto.categoria} | Stock: ${producto.stock} | Costo: ${producto.moneda_costo} $${producto.costo?.toFixed(2)}`;

  return (
    <ModalTesla
      isOpen={isOpen}
      onClose={onClose}
      title={producto.descripcion}
      subtitle={subtitle}
      size="lg"
      footer={
        resultado && (
          <ModalFooterButtons
            onCancel={onClose}
            onConfirm={guardar}
            confirmText="Guardar Precio"
            confirmLoading={guardando}
            confirmVariant="success"
          />
        )
      }
    >
      {/* Ofertas vigentes */}
      {!loadingOfertas && ofertas && ofertas.con_oferta > 0 && (
        <ModalAlert type="warning">
          <strong>📢 Ofertas Vigentes ({ofertas.con_oferta} de {ofertas.total_publicaciones} publicaciones)</strong>
          <div className="ofertas-list">
            {ofertas.publicaciones
              .filter(p => p.tiene_oferta)
              .map((pub) => (
                <div key={pub.mla} className="oferta-item">
                  <div className="oferta-mla">{pub.mla}</div>
                  <div className="oferta-lista">{pub.lista_nombre}</div>
                  <div className="oferta-precio">
                    Precio de oferta: <strong>${pub.oferta.precio_final.toLocaleString('es-AR')}</strong>
                  </div>
                  <div className="oferta-aporte">
                    Aporte Meli: ${pub.oferta.aporte_meli_pesos.toLocaleString('es-AR')}
                    {pub.oferta.aporte_meli_porcentaje && ` (${pub.oferta.aporte_meli_porcentaje}%)`}
                  </div>
                  <div className="oferta-vigencia">
                    Vigente hasta: {new Date(pub.oferta.fecha_hasta).toLocaleDateString('es-AR')}
                  </div>
                </div>
              ))}
          </div>
        </ModalAlert>
      )}

      {/* Error */}
      {error && (
        <ModalAlert type="error">
          {error}
        </ModalAlert>
      )}

      {/* Selector de modo */}
      <ModalSection title="Modo de cálculo">
        <div className="modo-selector">
          <button
            className={`btn-tesla ${modo === 'markup' ? 'primary' : 'secondary'}`}
            onClick={() => cambiarModo('markup')}
          >
            Por Markup
          </button>
          <button
            className={`btn-tesla ${modo === 'precio' ? 'primary' : 'secondary'}`}
            onClick={() => cambiarModo('precio')}
          >
            Precio Manual
          </button>
        </div>
      </ModalSection>

      {/* Inputs según modo */}
      <ModalSection title={modo === 'markup' ? 'Markup Objetivo (%)' : 'Precio Manual ($)'}>
        {modo === 'markup' ? (
          <input
            type="number"
            className="input"
            value={markupObjetivo}
            onChange={(e) => setMarkupObjetivo(e.target.value)}
            step="0.01"
            placeholder="Ej: 42.98"
          />
        ) : (
          <input
            type="number"
            className="input"
            value={precioManual}
            onChange={(e) => setPrecioManual(e.target.value)}
            step="0.01"
            placeholder="Ej: 150000"
          />
        )}

        <button
          className={`btn-tesla outline-subtle-primary full ${calculando ? 'loading' : ''}`}
          onClick={calcular}
          disabled={calculando}
          style={{ marginTop: 'var(--spacing-md)' }}
        >
          {calculando ? 'Calculando...' : 'Calcular'}
        </button>
      </ModalSection>

      {/* Rebate */}
      <ModalSection title="Rebate">
        <div className="rebate-controls">
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={participaRebate}
              onChange={(e) => setParticipaRebate(e.target.checked)}
            />
            Participa en Rebate
          </label>
          {participaRebate && (
            <div className="rebate-percentage">
              <label>Porcentaje:</label>
              <input
                type="number"
                className="input"
                value={porcentajeRebate}
                onChange={(e) => setPorcentajeRebate(parseFloat(e.target.value))}
                step="0.1"
                min="0"
                max="100"
              />
              <span>%</span>
            </div>
          )}
        </div>
      </ModalSection>

      {/* Resultados */}
      {resultado && (
        <>
          <ModalSection title="Precio Clásica">
            <div className="resultado-card">
              <div className="resultado-item">
                <span>Precio:</span>
                <strong>${resultado.clasica?.precio?.toLocaleString('es-AR')}</strong>
              </div>
              <div className="resultado-item">
                <span>Markup:</span>
                <strong>{resultado.clasica?.markup_real?.toFixed(2)}%</strong>
              </div>
            </div>
          </ModalSection>

          {resultado.cuotas && (
            <ModalSection title="Precios con Cuotas">
              <div className="cuotas-grid">
                {['3_cuotas', '6_cuotas', '9_cuotas', '12_cuotas'].map((key) => {
                  const cuota = resultado.cuotas[key];
                  if (!cuota) return null;
                  
                  return (
                    <div key={key} className="cuota-card">
                      <div className="cuota-title">{key.replace('_', ' ')}</div>
                      <div className="cuota-precio">${cuota.precio?.toLocaleString('es-AR')}</div>
                      <div className="cuota-markup">{cuota.markup_real?.toFixed(2)}%</div>
                    </div>
                  );
                })}
              </div>
            </ModalSection>
          )}
        </>
      )}
    </ModalTesla>
  );
}
