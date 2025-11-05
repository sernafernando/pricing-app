import React, { useState, useEffect } from 'react';
import axios from 'axios';
import '../styles/ModalCalculadora.css';
import { useModalClickOutside } from '../hooks/useModalClickOutside';

const ModalCalculadora = ({ isOpen, onClose }) => {
  const { overlayRef, handleOverlayMouseDown, handleOverlayClick } = useModalClickOutside(onClose);
  const [formData, setFormData] = useState({
    costo: '',
    monedaCosto: 'USD',
    iva: '21',
    comisionML: '',
    costoEnvio: '0',
    precioFinal: '',
    tipoCambio: ''
  });

  const [resultados, setResultados] = useState({
    costoARS: 0,
    comisionTotal: 0,
    limpio: 0,
    markupPorcentaje: 0
  });

  const [guardando, setGuardando] = useState(false);
  const [descripcion, setDescripcion] = useState('');
  const [ean, setEan] = useState('');

  useEffect(() => {
    if (isOpen) {
      cargarTipoCambio();
    }
  }, [isOpen]);

  const cargarTipoCambio = async () => {
    try {
      const token = localStorage.getItem('token');
      const response = await axios.get('https://pricing.gaussonline.com.ar/api/tipo-cambio/actual', {
        headers: { Authorization: `Bearer ${token}` }
      });
      setFormData(prev => ({ ...prev, tipoCambio: response.data.venta.toString() }));
    } catch (error) {
      console.error('Error cargando tipo de cambio:', error);
    }
  };

  const calcular = () => {
    const costo = parseFloat(formData.costo) || 0;
    const comisionML = parseFloat(formData.comisionML) || 0;
    const costoEnvio = parseFloat(formData.costoEnvio) || 0;
    const precioFinal = parseFloat(formData.precioFinal) || 0;
    const iva = parseFloat(formData.iva);
    const tipoCambio = parseFloat(formData.tipoCambio) || 1;

    if (costo === 0 || precioFinal === 0 || comisionML === 0) {
      return;
    }

    // Convertir costo a ARS si es necesario
    const costoARS = formData.monedaCosto === 'USD'
      ? costo * tipoCambio
      : costo;

    // Calcular precio sin IVA
    const precioSinIva = precioFinal / (1 + iva / 100);

    // Calcular comisión base ML (dividido por 1.21)
    const comisionBase = (precioFinal * (comisionML / 100)) / 1.21;

    // Calcular tier según el monto
    let tier = 0;
    if (precioFinal < 15000) {
      tier = 1095 / 1.21;
    } else if (precioFinal < 24000) {
      tier = 2190 / 1.21;
    } else if (precioFinal < 33000) {
      tier = 2628 / 1.21;
    }

    // Comisión con tier (si el precio >= 33000 no hay tier)
    const comisionConTier = precioFinal >= 33000 ? comisionBase : comisionBase + tier;

    // Calcular varios (6.5% sobre precio sin IVA)
    const comisionVarios = precioSinIva * 0.065;

    // Comisión total
    const comisionTotal = comisionConTier + comisionVarios;

    // Calcular envío sin IVA (solo si el precio es >= 33000)
    const envioSinIva = precioFinal >= 33000 ? (costoEnvio / 1.21) : 0;

    // Calcular limpio
    const limpio = precioSinIva - envioSinIva - comisionTotal;

    // Calcular markup
    const markup = ((limpio / costoARS) - 1) * 100;

    setResultados({
      costoARS: costoARS.toFixed(2),
      comisionTotal: comisionTotal.toFixed(2),
      limpio: limpio.toFixed(2),
      markupPorcentaje: markup.toFixed(2)
    });
  };

  useEffect(() => {
    calcular();
  }, [formData]);

  const handleChange = (field, value) => {
    setFormData(prev => ({ ...prev, [field]: value }));
  };

  const handleGuardar = async () => {
    if (!descripcion && !ean) {
      alert('Debe ingresar al menos una descripción o un EAN');
      return;
    }

    try {
      setGuardando(true);
      const token = localStorage.getItem('token');

      await axios.post(
        'https://pricing.gaussonline.com.ar/api/calculos',
        {
          descripcion: descripcion || 'Sin descripción',
          ean: ean || null,
          costo: parseFloat(formData.costo),
          moneda_costo: formData.monedaCosto,
          iva: parseFloat(formData.iva),
          comision_ml: parseFloat(formData.comisionML),
          costo_envio: parseFloat(formData.costoEnvio),
          precio_final: parseFloat(formData.precioFinal),
          markup_porcentaje: parseFloat(resultados.markupPorcentaje),
          limpio: parseFloat(resultados.limpio),
          comision_total: parseFloat(resultados.comisionTotal)
        },
        { headers: { Authorization: `Bearer ${token}` } }
      );

      alert('Cálculo guardado correctamente');
      setDescripcion('');
      setEan('');
      setGuardando(false);
      onClose();
    } catch (error) {
      console.error('Error guardando cálculo:', error);
      alert('Error al guardar el cálculo');
      setGuardando(false);
    }
  };

  const limpiarFormulario = () => {
    setFormData({
      costo: '',
      monedaCosto: 'USD',
      iva: '21',
      comisionML: '',
      costoEnvio: '0',
      precioFinal: '',
      tipoCambio: formData.tipoCambio // Mantener el tipo de cambio
    });
    setResultados({
      costoARS: '0.00',
      comisionTotal: '0.00',
      limpio: '0.00',
      markupPorcentaje: '0.00'
    });
    setDescripcion('');
    setEan('');
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Escape') {
      onClose();
    }
  };

  // Agregar listener global cuando el modal está abierto
  useEffect(() => {
    if (!isOpen) return;

    const handleGlobalKeyDown = (e) => {
      // ESC: cerrar modal
      if (e.key === 'Escape') {
        e.preventDefault();
        e.stopPropagation();
        onClose();
        return;
      }

      // BLOQUEAR todas las teclas para que no lleguen a la página de fondo
      // Esto previene que Enter active edición, etc.
      e.stopPropagation();
    };

    // Usar capture phase (true) para capturar ANTES que el listener de la página
    window.addEventListener('keydown', handleGlobalKeyDown, true);
    return () => window.removeEventListener('keydown', handleGlobalKeyDown, true);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  const markupColor = parseFloat(resultados.markupPorcentaje) >= 30 ? '#22c55e' :
                      parseFloat(resultados.markupPorcentaje) >= 15 ? '#f59e0b' :
                      '#ef4444';

  return (
    <div
      ref={overlayRef}
      className="modal-overlay"
      onMouseDown={handleOverlayMouseDown}
      onClick={handleOverlayClick}
      onKeyDown={handleKeyDown}
    >
      <div className="modal-calculadora" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h2>Calculadora de Pricing</h2>
          <div className="header-buttons">
            <button onClick={limpiarFormulario} className="clear-btn" title="Limpiar campos">
              🗑️ Limpiar
            </button>
            <button onClick={onClose} className="close-btn">✕</button>
          </div>
        </div>

        <div className="modal-body">
          <div className="form-grid">
            <div className="form-group">
              <label>Costo</label>
              <input
                type="number"
                step="0.01"
                value={formData.costo}
                onChange={(e) => handleChange('costo', e.target.value)}
                placeholder="0.00"
              />
            </div>

            <div className="form-group">
              <label>Moneda</label>
              <select
                value={formData.monedaCosto}
                onChange={(e) => handleChange('monedaCosto', e.target.value)}
              >
                <option value="USD">USD</option>
                <option value="ARS">ARS</option>
              </select>
            </div>

            <div className="form-group">
              <label>IVA</label>
              <select
                value={formData.iva}
                onChange={(e) => handleChange('iva', e.target.value)}
              >
                <option value="10.5">10.5%</option>
                <option value="21">21%</option>
              </select>
            </div>

            <div className="form-group">
              <label>Comisión ML (%)</label>
              <input
                type="number"
                step="0.01"
                value={formData.comisionML}
                onChange={(e) => handleChange('comisionML', e.target.value)}
                placeholder="0.00"
              />
            </div>

            <div className="form-group">
              <label>Costo Envío</label>
              <input
                type="number"
                step="0.01"
                value={formData.costoEnvio}
                onChange={(e) => handleChange('costoEnvio', e.target.value)}
                placeholder="0.00"
              />
            </div>

            <div className="form-group">
              <label>Precio Final</label>
              <input
                type="number"
                step="0.01"
                value={formData.precioFinal}
                onChange={(e) => handleChange('precioFinal', e.target.value)}
                placeholder="0.00"
              />
            </div>

            <div className="form-group">
              <label>Tipo de Cambio (USD)</label>
              <input
                type="number"
                step="0.01"
                value={formData.tipoCambio}
                onChange={(e) => handleChange('tipoCambio', e.target.value)}
                placeholder="0.00"
              />
            </div>
          </div>

          <div className="resultados-section">
            <h3>Resultados</h3>
            <div className="resultados-grid">
              <div className="resultado-item">
                <span className="resultado-label">Costo ARS:</span>
                <span className="resultado-valor">${resultados.costoARS}</span>
              </div>
              <div className="resultado-item">
                <span className="resultado-label">Comisión Total:</span>
                <span className="resultado-valor">${resultados.comisionTotal}</span>
              </div>
              <div className="resultado-item">
                <span className="resultado-label">Limpio:</span>
                <span className="resultado-valor">${resultados.limpio}</span>
              </div>
              <div className="resultado-item destacado">
                <span className="resultado-label">Markup:</span>
                <span className="resultado-valor" style={{ color: markupColor, fontWeight: 'bold', fontSize: '24px' }}>
                  {resultados.markupPorcentaje}%
                </span>
              </div>
            </div>
          </div>

          {guardando && (
            <div className="guardar-section">
              <h3>Guardar Cálculo</h3>
              <div className="form-group">
                <label>Descripción *</label>
                <input
                  type="text"
                  value={descripcion}
                  onChange={(e) => setDescripcion(e.target.value)}
                  placeholder="Descripción del producto"
                  maxLength={500}
                />
              </div>
              <div className="form-group">
                <label>EAN (opcional)</label>
                <input
                  type="text"
                  value={ean}
                  onChange={(e) => setEan(e.target.value)}
                  placeholder="EAN del producto"
                  maxLength={50}
                />
              </div>
              <p className="form-hint">* Debe completar al menos uno de los dos campos</p>
            </div>
          )}
        </div>

        <div className="modal-footer">
          {!guardando ? (
            <>
              <button onClick={onClose} className="btn-secondary">
                Cerrar
              </button>
              <button onClick={() => setGuardando(true)} className="btn-primary">
                Guardar
              </button>
            </>
          ) : (
            <>
              <button onClick={() => setGuardando(false)} className="btn-secondary">
                Cancelar
              </button>
              <button onClick={handleGuardar} className="btn-primary">
                Confirmar
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
};

export default ModalCalculadora;
