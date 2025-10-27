import { useState } from 'react';
import axios from 'axios';

export default function CalcularWebModal({ onClose, onSuccess }) {
  const [porcentajeConPrecio, setPorcentajeConPrecio] = useState(6.0);
  const [porcentajeSinPrecio, setPorcentajeSinPrecio] = useState(10.0);
  const [calculando, setCalculando] = useState(false);
  
  const calcularMasivo = async () => {
    if (!confirm('¿Confirmar cálculo masivo de precios web transferencia?')) return;
    
    setCalculando(true);
    try {
      const token = localStorage.getItem('token');
      const response = await axios.post(
        'https://pricing.gaussonline.com.ar/api/productos/calcular-web-masivo',
        {
          porcentaje_con_precio: porcentajeConPrecio,
          porcentaje_sin_precio: porcentajeSinPrecio
        },
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
            {calculando ? '⏳ Calculando...' : '✓ Calcular Todos'}
          </button>
        </div>
      </div>
    </div>
  );
}
