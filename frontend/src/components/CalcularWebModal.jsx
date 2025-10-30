import { useState } from 'react';
import axios from 'axios';

export default function CalcularWebModal({ onClose, onSuccess, filtrosActivos }) {
  const [porcentajeConPrecio, setPorcentajeConPrecio] = useState(6.0);
  const [porcentajeSinPrecio, setPorcentajeSinPrecio] = useState(10.0);
  const [calculando, setCalculando] = useState(false);
  const [aplicarFiltros, setAplicarFiltros] = useState(false);

  // Verificar si hay filtros activos
  const hayFiltros =
    !!filtrosActivos?.search ||
    filtrosActivos?.con_stock !== null ||
    filtrosActivos?.con_precio !== null ||
    (filtrosActivos?.marcas?.length > 0) ||
    (filtrosActivos?.subcategorias?.length > 0);

  const calcularMasivo = async () => {
    const mensaje = aplicarFiltros 
      ? '¿Confirmar cálculo de precios web transferencia para los productos FILTRADOS?'
      : '¿Confirmar cálculo masivo de precios web transferencia para TODOS los productos?';
    
    if (!confirm(mensaje)) return;

    setCalculando(true);
    try {
      const token = localStorage.getItem('token');
      
      // Construir body con filtros si aplica
      const body = {
        porcentaje_con_precio: porcentajeConPrecio,
        porcentaje_sin_precio: porcentajeSinPrecio
      };

      if (aplicarFiltros) {
        body.filtros = {
          search: filtrosActivos.search || null,
          con_stock: filtrosActivos.con_stock || null,
          con_precio: filtrosActivos.con_precio || null,
          marcas: filtrosActivos.marcas?.length > 0 ? filtrosActivos.marcas.join(',') : null,
          subcategorias: filtrosActivos.subcategorias?.length > 0 ? filtrosActivos.subcategorias.join(',') : null
        };
      }

      const response = await axios.post(
        'https://pricing.gaussonline.com.ar/api/productos/calcular-web-masivo',
        body,
        { headers: { Authorization: `Bearer ${token}` } }
      );

      alert(`Precios calculados: ${response.data.procesados} productos`);
      onSuccess();
      onClose();
    } catch (error) {
      console.error('Error:', error);
      alert('Error al calcular precios masivos');
    } finally {
      setCalculando(false);
    }
  };

  return (
    <div style={{
      position: 'fixed',
      top: 0,
      left: 0,
      right: 0,
      bottom: 0,
      background: 'rgba(0,0,0,0.5)',
      display: 'flex',
      justifyContent: 'center',
      alignItems: 'center',
      zIndex: 1000
    }}>
      <div style={{
        background: 'white',
        borderRadius: '12px',
        padding: '24px',
        maxWidth: '500px',
        width: '90%'
      }}>
        <h2 style={{ marginBottom: '20px' }}>🧮 Calcular Precio Web Transferencia</h2>

        {/* Selector de ámbito */}
        {hayFiltros && (
          <div style={{
            marginBottom: '20px',
            padding: '12px',
            background: '#f0fdf4',
            border: '1px solid #86efac',
            borderRadius: '8px'
          }}>
            <label style={{
              display: 'flex',
              alignItems: 'center',
              cursor: 'pointer',
              fontWeight: '500'
            }}>
              <input
                type="checkbox"
                checked={aplicarFiltros}
                onChange={(e) => setAplicarFiltros(e.target.checked)}
                style={{ marginRight: '8px' }}
              />
              Aplicar solo a productos filtrados
            </label>
            {aplicarFiltros && (
              <div style={{ marginTop: '8px', fontSize: '13px', color: '#059669' }}>
                {filtrosActivos.search && <div>• Búsqueda: "{filtrosActivos.search}"</div>}
                {filtrosActivos.con_stock === true && <div>• Con stock</div>}
                {filtrosActivos.con_stock === false && <div>• Sin stock</div>}
                {filtrosActivos.con_precio === true && <div>• Con precio</div>}
                {filtrosActivos.con_precio === false && <div>• Sin precio</div>}
                {filtrosActivos.marcas?.length > 0 && <div>• {filtrosActivos.marcas.length} marca(s)</div>}
                {filtrosActivos.subcategorias?.length > 0 && <div>• {filtrosActivos.subcategorias.length} subcategoría(s)</div>}
              </div>
            )}
          </div>
        )}

        <div style={{ display: 'grid', gap: '20px', marginBottom: '24px' }}>
          <div>
            <label style={{ display: 'block', marginBottom: '8px', fontWeight: '500' }}>
              Si el producto tiene precio, sumar:
            </label>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <input
                type="number"
                step="0.1"
                value={porcentajeConPrecio}
                onChange={(e) => setPorcentajeConPrecio(parseFloat(e.target.value))}
                style={{
                  width: '100px',
                  padding: '10px',
                  borderRadius: '6px',
                  border: '1px solid #d1d5db',
                  fontSize: '16px'
                }}
              />
              <span style={{ fontSize: '16px', fontWeight: '500' }}>%</span>
            </div>
            <p style={{ fontSize: '12px', color: '#6b7280', marginTop: '4px' }}>
              Se sumará este % al markup actual
            </p>
          </div>

          <div>
            <label style={{ display: 'block', marginBottom: '8px', fontWeight: '500' }}>
              Si el producto NO tiene precio, calcular a:
            </label>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <input
                type="number"
                step="0.1"
                value={porcentajeSinPrecio}
                onChange={(e) => setPorcentajeSinPrecio(parseFloat(e.target.value))}
                style={{
                  width: '100px',
                  padding: '10px',
                  borderRadius: '6px',
                  border: '1px solid #d1d5db',
                  fontSize: '16px'
                }}
              />
              <span style={{ fontSize: '16px', fontWeight: '500' }}>%</span>
            </div>
            <p style={{ fontSize: '12px', color: '#6b7280', marginTop: '4px' }}>
              Markup base para productos sin precio
            </p>
          </div>
        </div>

        <div style={{ display: 'flex', gap: '12px', justifyContent: 'flex-end' }}>
          <button
            onClick={onClose}
            disabled={calculando}
            style={{
              padding: '10px 20px',
              borderRadius: '6px',
              border: '1px solid #d1d5db',
              background: 'white',
              cursor: 'pointer'
            }}
          >
            Cancelar
          </button>
          <button
            onClick={calcularMasivo}
            disabled={calculando}
            style={{
              padding: '10px 20px',
              borderRadius: '6px',
              border: 'none',
              background: '#3b82f6',
              color: 'white',
              cursor: 'pointer',
              fontWeight: '600'
            }}
          >
            {calculando ? '⏳ Calculando...' : aplicarFiltros ? '✓ Calcular Filtrados' : '✓ Calcular Todos'}
          </button>
        </div>
      </div>
    </div>
  );
}
