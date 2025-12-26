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
  const [constantes, setConstantes] = useState(null);
  const [preciosCuotas, setPreciosCuotas] = useState([]);
  const [calculandoCuotas, setCalculandoCuotas] = useState(false);
  const [adicionalMarkup, setAdicionalMarkup] = useState(0); // Se carga desde BD al abrir modal
  const [gruposComision, setGruposComision] = useState([]);
  const [grupoSeleccionado, setGrupoSeleccionado] = useState(1); // Default: Grupo 1

  useEffect(() => {
    if (isOpen) {
      cargarTipoCambio();
      cargarConstantes();
      cargarGruposComision();
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

  const cargarConstantes = async () => {
    try {
      const token = localStorage.getItem('token');
      const response = await axios.get('https://pricing.gaussonline.com.ar/api/pricing-constants/actual', {
        headers: { Authorization: `Bearer ${token}` }
      });
      setConstantes(response.data);
      
      // Setear adicional de markup desde la BD
      if (response.data.markup_adicional_cuotas !== undefined) {
        setAdicionalMarkup(response.data.markup_adicional_cuotas);
      }
    } catch (error) {
      console.error('Error cargando constantes:', error);
      alert('Error cargando constantes de pricing. No se pueden realizar cálculos.');
      setConstantes(null);
    }
  };

  const cargarGruposComision = async () => {
    try {
      const token = localStorage.getItem('token');
      const response = await axios.get('https://pricing.gaussonline.com.ar/api/comisiones/calculadas', {
        headers: { Authorization: `Bearer ${token}` }
      });
      setGruposComision(response.data); // Array de {grupo_id, lista_4, lista_3_cuotas, ...}
    } catch (error) {
      console.error('Error cargando grupos de comisión:', error);
    }
  };

  const calcular = () => {
    const costo = parseFloat(formData.costo) || 0;
    const costoEnvio = parseFloat(formData.costoEnvio) || 0;
    const precioFinal = parseFloat(formData.precioFinal) || 0;
    const iva = parseFloat(formData.iva);
    const tipoCambio = parseFloat(formData.tipoCambio) || 1;

    // Obtener comisión base del grupo seleccionado (lista 4 = clásica)
    const grupoData = gruposComision.find(g => g.grupo_id === grupoSeleccionado);
    const comisionML = grupoData ? grupoData.lista_4 : 0;

    if (costo === 0 || precioFinal === 0 || comisionML === 0 || !constantes) {
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

    // Calcular tier según el monto (usando valores de la BD)
    let tier = 0;
    if (precioFinal < constantes.monto_tier1) {
      tier = constantes.comision_tier1 / 1.21;
    } else if (precioFinal < constantes.monto_tier2) {
      tier = constantes.comision_tier2 / 1.21;
    } else if (precioFinal < constantes.monto_tier3) {
      tier = constantes.comision_tier3 / 1.21;
    }

    // Comisión con tier (si el precio >= MONTOT3 no hay tier)
    const comisionConTier = precioFinal >= constantes.monto_tier3 ? comisionBase : comisionBase + tier;

    // Calcular varios (usando porcentaje de la BD sobre precio sin IVA)
    const comisionVarios = precioSinIva * (constantes.varios_porcentaje / 100);

    // Comisión total
    const comisionTotal = comisionConTier + comisionVarios;

    // Calcular envío sin IVA (solo si el precio es >= MONTOT3)
    const envioSinIva = precioFinal >= constantes.monto_tier3 ? (costoEnvio / 1.21) : 0;

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
  }, [formData, grupoSeleccionado, gruposComision]);

  // Calcular cuotas automáticamente cuando cambia el markup o el adicional
  useEffect(() => {
    const markup = parseFloat(resultados.markupPorcentaje);
    const costo = parseFloat(formData.costo);
    const precioFinal = parseFloat(formData.precioFinal);
    const tipoCambio = parseFloat(formData.tipoCambio);
    
    console.log('🔍 Verificando condiciones para calcular cuotas:', {
      markup,
      costo,
      precioFinal,
      tipoCambio,
      formData
    });
    
    if (markup && !isNaN(markup) && markup > 0 && costo > 0 && precioFinal > 0 && tipoCambio > 0) {
      console.log('✅ Calculando cuotas...');
      calcularCuotas();
    } else {
      console.log('❌ No se cumplen condiciones para calcular cuotas');
      setPreciosCuotas([]);
    }
  }, [resultados.markupPorcentaje, adicionalMarkup, formData.costo, formData.precioFinal, formData.tipoCambio]);

  const calcularCuotas = async () => {
    try {
      setCalculandoCuotas(true);
      const token = localStorage.getItem('token');
      
      const requestData = {
        costo: parseFloat(formData.costo),
        moneda_costo: formData.monedaCosto,
        iva: parseFloat(formData.iva),
        envio: parseFloat(formData.costoEnvio) || 0,
        markup_objetivo: parseFloat(resultados.markupPorcentaje),
        tipo_cambio: parseFloat(formData.tipoCambio),
        grupo_id: grupoSeleccionado, // Usar grupo seleccionado del dropdown
        adicional_markup: adicionalMarkup
      };
      
      console.log('📤 Enviando request calcular cuotas:', requestData);
      
      const response = await axios.post(
        'https://pricing.gaussonline.com.ar/api/calculos/calcular-cuotas',
        requestData,
        { headers: { Authorization: `Bearer ${token}` } }
      );
      
      console.log('📥 Respuesta cuotas:', response.data);
      setPreciosCuotas(response.data);
    } catch (error) {
      console.error('❌ Error calculando cuotas:', error);
      console.error('Error response:', error.response?.data);
      setPreciosCuotas([]);
    } finally {
      setCalculandoCuotas(false);
    }
  };

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

      // Preparar datos de cuotas para JSONB
      const cuotasData = preciosCuotas.length > 0 ? {
        adicional_markup: adicionalMarkup,
        cuotas: preciosCuotas.map(c => ({
          cuotas: c.cuotas,
          pricelist_id: c.pricelist_id,
          precio: c.precio,
          comision_base_pct: c.comision_base_pct,
          comision_total: c.comision_total,
          limpio: c.limpio,
          markup_real: c.markup_real
        }))
      } : null;

      // Obtener comisión ML del grupo seleccionado
      const grupoData = gruposComision.find(g => g.grupo_id === grupoSeleccionado);
      const comisionML = grupoData ? grupoData.lista_4 : 0;

      await axios.post(
        'https://pricing.gaussonline.com.ar/api/calculos',
        {
          descripcion: descripcion || 'Sin descripción',
          ean: ean || null,
          costo: parseFloat(formData.costo),
          moneda_costo: formData.monedaCosto,
          iva: parseFloat(formData.iva),
          comision_ml: comisionML,  // ← Usar comisión del grupo
          costo_envio: parseFloat(formData.costoEnvio),
          precio_final: parseFloat(formData.precioFinal),
          markup_porcentaje: parseFloat(resultados.markupPorcentaje),
          limpio: parseFloat(resultados.limpio),
          comision_total: parseFloat(resultados.comisionTotal),
          tipo_cambio_usado: parseFloat(formData.tipoCambio),
          precios_cuotas: cuotasData  // ← Guardar cuotas en JSONB
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
              <label>Grupo Comisión</label>
              <select
                value={grupoSeleccionado}
                onChange={(e) => setGrupoSeleccionado(parseInt(e.target.value))}
                title="Grupo de comisión para cálculos"
              >
                {gruposComision.length === 0 ? (
                  <option value="1">Cargando grupos...</option>
                ) : (
                  gruposComision.map(grupo => (
                    <option key={grupo.grupo_id} value={grupo.grupo_id}>
                      Grupo {grupo.grupo_id} - Base {grupo.lista_4.toFixed(2)}%
                    </option>
                  ))
                )}
              </select>
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

          {/* Precios de Cuotas */}
          {preciosCuotas.length > 0 && (
            <div className="cuotas-section">
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
                <h3>Precios de Cuotas (Markup Convergente)</h3>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <label style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>
                    Adicional:
                  </label>
                  <input
                    type="number"
                    step="0.1"
                    min="0"
                    value={adicionalMarkup}
                    onChange={(e) => {
                      const val = e.target.value;
                      // Permitir vacío temporalmente, pero al perder foco volverá a 0
                      if (val === '' || val === null) {
                        setAdicionalMarkup(0);
                      } else {
                        const num = parseFloat(val);
                        setAdicionalMarkup(isNaN(num) ? 0 : num);
                      }
                    }}
                    style={{ width: '60px', padding: '4px 8px', fontSize: '13px' }}
                  />
                  <span style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>%</span>
                </div>
              </div>
              
              {calculandoCuotas ? (
                <div style={{ textAlign: 'center', padding: '20px', color: 'var(--text-secondary)' }}>
                  Calculando cuotas...
                </div>
              ) : (
                <div className="cuotas-grid">
                  {preciosCuotas.map((cuota) => (
                    <div key={cuota.cuotas} className="cuota-item">
                      <div className="cuota-header">
                        <span className="cuota-numero">{cuota.cuotas} Cuotas</span>
                        <span className="cuota-precio">${cuota.precio.toFixed(2)}</span>
                      </div>
                      <div className="cuota-details">
                        <div className="cuota-detail-row">
                          <span>Comisión:</span>
                          <span>{cuota.comision_base_pct.toFixed(2)}%</span>
                        </div>
                        <div className="cuota-detail-row">
                          <span>Limpio:</span>
                          <span>${cuota.limpio.toFixed(2)}</span>
                        </div>
                        <div className="cuota-detail-row">
                          <span>Markup:</span>
                          <span style={{ color: markupColor, fontWeight: 'bold' }}>
                            {cuota.markup_real.toFixed(2)}%
                          </span>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

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
