import { useState } from 'react';
import axios from 'axios';

export default function ExportModal({ onClose }) {
  const [tab, setTab] = useState('rebate'); // 'rebate' o 'web_transf'
  const [exportando, setExportando] = useState(false);
  
  // Estados para rebate
  const [fechaDesde, setFechaDesde] = useState(() => {
    const hoy = new Date();
    return hoy.toLocaleDateString('es-AR', { day: '2-digit', month: '2-digit', year: 'numeric' });
  });
  const [fechaHasta, setFechaHasta] = useState(() => {
    const hoy = new Date();
    const ultimoDia = new Date(hoy.getFullYear(), hoy.getMonth() + 1, 0);
    return ultimoDia.toLocaleDateString('es-AR', { day: '2-digit', month: '2-digit', year: 'numeric' });
  });

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
      const timestamp = ahora.toISOString().replace(/[:.]/g, '-').slice(0, -5);
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

  const exportarWebTransf = async () => {
    setExportando(true);
    try {
      const token = localStorage.getItem('token');
      const response = await axios.get(
        'https://pricing.gaussonline.com.ar/api/exportar-web-transferencia',
        {
          headers: { Authorization: `Bearer ${token}` },
          responseType: 'blob'
        }
      );
      const url = window.URL.createObjectURL(new Blob([response.data]));
      const link = document.createElement('a');
      link.href = url;
      const ahora = new Date();
      const timestamp = ahora.toISOString().replace(/[:.]/g, '-').slice(0, -5);
      const nombreArchivo = `web_transferencia_${timestamp}.xlsx`;
      link.setAttribute('download', nombreArchivo);
      document.body.appendChild(link);
      link.click();
      link.remove();
      alert('Exportación completada');
      onClose();
    } catch (error) {
      console.error('Error exportando:', error);
      alert('Error al exportar Web Transferencia');
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
        maxWidth: '500px',
        width: '90%',
        overflow: 'hidden'
      }}>
        {/* Header */}
        <div style={{
          padding: '20px 24px',
          borderBottom: '1px solid #e5e7eb',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center'
        }}>
          <h2 style={{ margin: 0, fontSize: '18px', fontWeight: '600' }}>
            📊 Exportar Precios
          </h2>
          <button
            onClick={onClose}
            style={{
              background: 'none',
              border: 'none',
              fontSize: '24px',
              cursor: 'pointer',
              color: '#6b7280',
              padding: 0
            }}
          >
            ×
          </button>
        </div>

        {/* Pestañas */}
        <div style={{
          display: 'flex',
          borderBottom: '1px solid #e5e7eb'
        }}>
          <button
            onClick={() => setTab('rebate')}
            style={{
              flex: 1,
              padding: '12px 20px',
              background: 'none',
              border: 'none',
              borderBottom: tab === 'rebate' ? '3px solid #10b981' : '3px solid transparent',
              color: tab === 'rebate' ? '#10b981' : '#6b7280',
              fontWeight: tab === 'rebate' ? '600' : '400',
              cursor: 'pointer',
              fontSize: '14px',
              transition: 'all 0.2s'
            }}
          >
            Rebate ML
          </button>
          <button
            onClick={() => setTab('web_transf')}
            style={{
              flex: 1,
              padding: '12px 20px',
              background: 'none',
              border: 'none',
              borderBottom: tab === 'web_transf' ? '3px solid #10b981' : '3px solid transparent',
              color: tab === 'web_transf' ? '#10b981' : '#6b7280',
              fontWeight: tab === 'web_transf' ? '600' : '400',
              cursor: 'pointer',
              fontSize: '14px',
              transition: 'all 0.2s'
            }}
          >
            Web Transferencia
          </button>
        </div>

        {/* Contenido */}
        <div style={{ padding: '24px' }}>
          {tab === 'rebate' ? (
            <div>
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
                    cursor: exportando ? 'not-allowed' : 'pointer'
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
                    background: exportando ? '#9ca3af' : '#10b981',
                    color: 'white',
                    cursor: exportando ? 'not-allowed' : 'pointer',
                    fontWeight: '600'
                  }}
                >
                  {exportando ? '⏳ Exportando...' : '📥 Exportar Rebate'}
                </button>
              </div>
            </div>
          ) : (
            <div>
              <p style={{ color: '#6b7280', marginBottom: '20px', fontSize: '14px' }}>
                Exporta los precios de Web Transferencia activos en formato XLS.
                <br />
                <strong>Formato:</strong> Código/EAN | Precio | ID Moneda (1=ARS)
              </p>
              <div style={{ display: 'flex', gap: '12px', justifyContent: 'flex-end' }}>
                <button
                  onClick={onClose}
                  disabled={exportando}
                  style={{
                    padding: '10px 20px',
                    borderRadius: '6px',
                    border: '1px solid #d1d5db',
                    background: 'white',
                    cursor: exportando ? 'not-allowed' : 'pointer'
                  }}
                >
                  Cancelar
                </button>
                <button
                  onClick={exportarWebTransf}
                  disabled={exportando}
                  style={{
                    padding: '10px 20px',
                    borderRadius: '6px',
                    border: 'none',
                    background: exportando ? '#9ca3af' : '#10b981',
                    color: 'white',
                    cursor: exportando ? 'not-allowed' : 'pointer',
                    fontWeight: '600'
                  }}
                >
                  {exportando ? '⏳ Exportando...' : '📥 Exportar Web'}
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
