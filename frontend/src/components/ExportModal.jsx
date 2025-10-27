import { useState } from 'react';
import axios from 'axios';

export default function ExportModal({ onClose }) {
  const [fechaDesde, setFechaDesde] = useState(() => {
    const hoy = new Date();
    return hoy.toLocaleDateString('es-AR', { day: '2-digit', month: '2-digit', year: 'numeric' });
  });
  
  const [fechaHasta, setFechaHasta] = useState(() => {
    const hoy = new Date();
    const ultimoDia = new Date(hoy.getFullYear(), hoy.getMonth() + 1, 0);
    return ultimoDia.toLocaleDateString('es-AR', { day: '2-digit', month: '2-digit', year: 'numeric' });
  });
  
  const [exportando, setExportando] = useState(false);
  
  const convertirFechaParaAPI = (fechaDD_MM_YYYY) => {
    const [d, m, y] = fechaDD_MM_YYYY.split('/');
    return `${y}-${m}-${d}`;
  };
  
  const exportarRebate = async () => {
    setExportando(true);
    try {
      const token = localStorage.getItem('token');
      const response = await axios.post(
        'https://pricing.gaussonline.com.ar/api/productos/exportar-rebate',
        { 
          fecha_desde: convertirFechaParaAPI(fechaDesde), 
          fecha_hasta: convertirFechaParaAPI(fechaHasta) 
        },
        {
          headers: { Authorization: `Bearer ${token}` },
          responseType: 'blob'
        }
      );
      
      const url = window.URL.createObjectURL(new Blob([response.data]));
      const link = document.createElement('a');
      link.href = url;
      const ahora = new Date();
      const timestamp = ahora.toISOString().replace(/[:.]/g, '-').slice(0, -5); // YYYY-MM-DDTHH-MM-SS
      const nombreArchivo = `rebate_export_${timestamp}.xlsx`;
      link.setAttribute('download', nombreArchivo);
      document.body.appendChild(link);
      link.click();
      link.remove();
      
      alert('Exportación completada');
      onClose();
    } catch (error) {
      console.error('Error exportando:', error);
      alert('Error al exportar');
    } finally {
      setExportando(false);
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
        <h2 style={{ marginBottom: '20px' }}>📊 Exportar Rebate</h2>
        
        <div style={{ display: 'grid', gap: '16px', marginBottom: '20px' }}>
          <div>
            <label style={{ display: 'block', marginBottom: '8px', fontWeight: '500' }}>
              Fecha Desde:
            </label>
            <input
              type="text"
              placeholder="DD/MM/YYYY"
              value={fechaDesde}
              onChange={(e) => setFechaDesde(e.target.value)}
              style={{
                width: '100%',
                padding: '10px',
                borderRadius: '6px',
                border: '1px solid #d1d5db',
                fontSize: '14px',
                boxSizing: 'border-box'
              }}
            />
          </div>
          
          <div>
            <label style={{ display: 'block', marginBottom: '8px', fontWeight: '500' }}>
              Fecha Hasta:
            </label>
            <input
              type="text"
              placeholder="DD/MM/YYYY"
              value={fechaHasta}
              onChange={(e) => setFechaHasta(e.target.value)}
              style={{
                width: '100%',
                padding: '10px',
                borderRadius: '6px',
                border: '1px solid #d1d5db',
                fontSize: '14px',
                boxSizing: 'border-box'
              }}
            />
          </div>
        </div>
        
        <div style={{ display: 'flex', gap: '12px', justifyContent: 'flex-end' }}>
          <button
            onClick={onClose}
            disabled={exportando}
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
            onClick={exportarRebate}
            disabled={exportando}
            style={{
              padding: '10px 20px',
              borderRadius: '6px',
              border: 'none',
              background: '#10b981',
              color: 'white',
              cursor: 'pointer',
              fontWeight: '600'
            }}
          >
            {exportando ? '⏳ Exportando...' : '📥 Exportar'}
          </button>
        </div>
      </div>
    </div>
  );
}
