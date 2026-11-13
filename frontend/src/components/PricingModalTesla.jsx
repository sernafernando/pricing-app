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
import { Megaphone } from 'lucide-react';
import api from '../services/api';
import { formatDateOnly } from '../utils/dateUtils';
import { formatMoney } from '../utils/formatMoney';
import ModalTesla, { ModalSection, ModalAlert, ModalFooterButtons } from './ModalTesla';
import './PricingModalTesla.css';

/** A figure in the Argentine format with two decimals: 95.5 -> "95,50"; a missing one is "—". */
function decimal2(value) {
  if (value === null || value === undefined || value === '') return '—';
  const num = Number(value);
  if (Number.isNaN(num)) return '—';
  return num.toLocaleString('es-AR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

/** A percentage in the Argentine format: 42.98 -> "42,98 %"; a missing one is only "—". */
function percent2(value) {
  const figure = decimal2(value);
  return figure === '—' ? figure : `${figure} %`;
}

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
    // resetear solo al abrir o cambiar de item — usar producto?.item_id evita reset por nueva referencia
    // eslint-disable-next-line react-hooks/exhaustive-deps
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

  const subtitle = `${producto.marca} · ${producto.categoria} · Stock ${producto.stock} · Costo ${producto.moneda_costo} ${decimal2(producto.costo)}`;

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
            confirmText="Guardar precio"
            confirmLoading={guardando}
            confirmVariant="outline-subtle-success"
          />
        )
      }
    >
      {/* Ofertas vigentes */}
      {!loadingOfertas && ofertas && ofertas.con_oferta > 0 && (
        <ModalAlert type="warning">
          <strong>
            <Megaphone size={14} aria-hidden="true" /> Ofertas vigentes ({ofertas.con_oferta} de {ofertas.total_publicaciones}{' '}
            publicaciones)
          </strong>
          <div className="ofertas-list">
            {ofertas.publicaciones
              .filter(p => p.tiene_oferta)
              .map((pub) => (
                <div key={pub.mla} className="oferta-item">
                  <div className="oferta-mla">{pub.mla}</div>
                  <div className="oferta-lista">{pub.lista_nombre}</div>
                  <div className="oferta-precio">
                    Precio de oferta: <strong>{formatMoney(pub.oferta.precio_final)}</strong>
                  </div>
                  <div className="oferta-aporte">
                    Aporte Meli: {formatMoney(pub.oferta.aporte_meli_pesos)}
                    {pub.oferta.aporte_meli_porcentaje && ` (${pub.oferta.aporte_meli_porcentaje}%)`}
                  </div>
                  <div className="oferta-vigencia">
                    Vigente hasta: {formatDateOnly(pub.oferta.fecha_hasta)}
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
        <div className="modo-selector" role="group" aria-label="Modo de cálculo">
          <button type="button" aria-pressed={modo === 'markup'} onClick={() => cambiarModo('markup')}>
            Por markup
          </button>
          <button type="button" aria-pressed={modo === 'precio'} onClick={() => cambiarModo('precio')}>
            Precio manual
          </button>
        </div>
      </ModalSection>

      {/* Inputs según modo */}
      <ModalSection title={modo === 'markup' ? 'Markup objetivo (%)' : 'Precio manual ($)'}>
        {/* The field and "Calcular" on one line, the button as tall as the field. */}
        <div className="calcular-row">
        {modo === 'markup' ? (
          <input
            type="number"
            className="input"
            aria-label="Markup objetivo (%)"
            value={markupObjetivo}
            onChange={(e) => setMarkupObjetivo(e.target.value)}
            step="0.01"
            placeholder="Ej: 42.98"
          />
        ) : (
          <input
            type="number"
            className="input"
            aria-label="Precio manual ($)"
            value={precioManual}
            onChange={(e) => setPrecioManual(e.target.value)}
            step="0.01"
            placeholder="Ej: 150000"
          />
        )}

        <button
          type="button"
          className={`btn-tesla outline-subtle-primary ${calculando ? 'loading' : ''}`}
          onClick={calcular}
          disabled={calculando}
        >
          {calculando ? 'Calculando…' : 'Calcular'}
        </button>
        </div>
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
            Participa en rebate
          </label>
          {participaRebate && (
            <div className="rebate-percentage">
              <label>Porcentaje</label>
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
          <ModalSection title="Precio clásica">
            <div className="resultado-card">
              <div className="resultado-item">
                <span>Precio</span>
                <strong>{formatMoney(resultado.clasica?.precio) ?? '—'}</strong>
              </div>
              <div className="resultado-item">
                <span>Markup</span>
                <strong>{percent2(resultado.clasica?.markup_real)}</strong>
              </div>
            </div>
          </ModalSection>

          {resultado.cuotas && (
            <ModalSection title="Precios con cuotas">
              <div className="cuotas-grid">
                {['3_cuotas', '6_cuotas', '9_cuotas', '12_cuotas'].map((key) => {
                  const cuota = resultado.cuotas[key];
                  if (!cuota) return null;
                  
                  return (
                    <div key={key} className="cuota-card">
                      <div className="cuota-title">{key.replace('_', ' ')}</div>
                      <div className="cuota-precio">{formatMoney(cuota.precio) ?? '—'}</div>
                      <div className="cuota-markup">{percent2(cuota.markup_real)}</div>
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
