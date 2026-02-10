import React, { useState, useEffect } from 'react';
import api from '../services/api';
import './Productos.css';

const TestStatsDinamicos = () => {
  const [statsGlobales, setStatsGlobales] = useState(null);
  const [statsDinamicos, setStatsDinamicos] = useState(null);
  const [filtros, setFiltros] = useState({});
  const [loading, setLoading] = useState(false);

  // Cargar stats globales al inicio
  useEffect(() => {
    cargarStatsGlobales();
  }, []);

  const cargarStatsGlobales = async () => {
    try {
      const res = await api.get('/stats');
      setStatsGlobales(res.data);
    } catch (error) {
      console.error('Error cargando stats globales:', error);
    }
  };

  const cargarStatsDinamicos = async () => {
    setLoading(true);
    try {
      const res = await api.get('/stats-dinamicos', { params: filtros });
      setStatsDinamicos(res.data);
    } catch (error) {
      console.error('Error cargando stats dinámicos:', error);
    } finally {
      setLoading(false);
    }
  };

  const agregarFiltro = (key, value) => {
    const nuevosFiltros = { ...filtros, [key]: value };
    setFiltros(nuevosFiltros);
  };

  const limpiarFiltros = () => {
    setFiltros({});
    setStatsDinamicos(null);
  };

  return (
    <div style={{ padding: '20px', maxWidth: '1400px', margin: '0 auto', color: 'var(--text-primary)' }}>
      <h1 style={{ color: 'var(--text-primary)' }}>🧪 Test: Estadísticas Dinámicas</h1>

      <div style={{ marginBottom: '30px', padding: '20px', background: 'var(--bg-secondary)', borderRadius: '8px', border: '1px solid var(--border-color)' }}>
        <h3 style={{ color: 'var(--text-primary)' }}>Filtros Rápidos</h3>
        <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
          <button onClick={() => agregarFiltro('con_stock', true)} className="btn-filtro">
            Con Stock
          </button>
          <button onClick={() => agregarFiltro('con_precio', true)} className="btn-filtro">
            Con Precio
          </button>
          <button onClick={() => agregarFiltro('con_rebate', true)} className="btn-filtro">
            Con Rebate
          </button>
          <button onClick={() => agregarFiltro('con_oferta', true)} className="btn-filtro">
            Con Oferta
          </button>
          <button
            onClick={() => {
              setFiltros({ con_oferta: true, con_rebate: false });
            }}
            className="btn-filtro"
            style={{ background: '#ff6b6b', color: 'white' }}
          >
            Con Oferta SIN Rebate
          </button>
          <button onClick={() => agregarFiltro('markup_clasica_positivo', false)} className="btn-filtro">
            Markup Negativo Clásica
          </button>
          <button onClick={() => agregarFiltro('markup_rebate_positivo', false)} className="btn-filtro">
            Markup Negativo Rebate
          </button>
          <button onClick={() => agregarFiltro('markup_oferta_positivo', false)} className="btn-filtro">
            Markup Negativo Oferta
          </button>
          <button onClick={() => agregarFiltro('con_mla', false)} className="btn-filtro">
            Sin MLA
          </button>
          <button onClick={limpiarFiltros} className="btn-filtro" style={{ background: '#dc3545', color: 'white' }}>
            Limpiar Filtros
          </button>
        </div>

        <div style={{ marginTop: '15px', color: 'var(--text-primary)' }}>
          <strong>Filtros Activos:</strong> {Object.keys(filtros).length === 0 ? 'Ninguno' : JSON.stringify(filtros)}
        </div>

        <button
          onClick={cargarStatsDinamicos}
          disabled={loading}
          style={{
            marginTop: '15px',
            padding: '10px 20px',
            background: '#007bff',
            color: 'white',
            border: 'none',
            borderRadius: '4px',
            cursor: 'pointer',
            fontSize: '16px'
          }}
        >
          {loading ? 'Cargando...' : 'Calcular Stats Dinámicos'}
        </button>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '20px' }}>
        {/* Stats Globales */}
        <div style={{ padding: '20px', background: 'var(--bg-primary)', border: '2px solid #007bff', borderRadius: '8px' }}>
          <h2 style={{ color: '#007bff' }}>📊 Stats Globales (Sin Filtros)</h2>
          {statsGlobales ? (
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <tbody>
                <tr><td style={{ padding: '8px', borderBottom: '1px solid var(--border-color)', color: 'var(--text-primary)' }}><strong>Total Productos:</strong></td><td style={{ padding: '8px', borderBottom: '1px solid var(--border-color)', color: 'var(--text-primary)' }}>{statsGlobales.total_productos}</td></tr>
                <tr><td style={{ padding: '8px', borderBottom: '1px solid var(--border-color)', color: 'var(--text-primary)' }}><strong>Con Stock:</strong></td><td style={{ padding: '8px', borderBottom: '1px solid var(--border-color)', color: 'var(--text-primary)' }}>{statsGlobales.con_stock}</td></tr>
                <tr><td style={{ padding: '8px', borderBottom: '1px solid var(--border-color)', color: 'var(--text-primary)' }}><strong>Con Precio:</strong></td><td style={{ padding: '8px', borderBottom: '1px solid var(--border-color)', color: 'var(--text-primary)' }}>{statsGlobales.con_precio}</td></tr>
                <tr><td style={{ padding: '8px', borderBottom: '1px solid var(--border-color)', color: 'var(--text-primary)' }}><strong>Nuevos (7 días):</strong></td><td style={{ padding: '8px', borderBottom: '1px solid var(--border-color)', color: 'var(--text-primary)' }}>{statsGlobales.nuevos_ultimos_7_dias}</td></tr>
                <tr><td style={{ padding: '8px', borderBottom: '1px solid var(--border-color)', color: 'var(--text-primary)' }}><strong>Sin MLA:</strong></td><td style={{ padding: '8px', borderBottom: '1px solid var(--border-color)', color: 'var(--text-primary)' }}>{statsGlobales.sin_mla_no_banlist}</td></tr>
                <tr><td style={{ padding: '8px', borderBottom: '1px solid var(--border-color)', color: 'var(--text-primary)' }}><strong>Markup Neg. Clásica:</strong></td><td style={{ padding: '8px', borderBottom: '1px solid var(--border-color)', color: 'var(--text-primary)' }}>{statsGlobales.markup_negativo_clasica}</td></tr>
                <tr><td style={{ padding: '8px', borderBottom: '1px solid var(--border-color)', color: 'var(--text-primary)' }}><strong>Markup Neg. Rebate:</strong></td><td style={{ padding: '8px', borderBottom: '1px solid var(--border-color)', color: 'var(--text-primary)' }}>{statsGlobales.markup_negativo_rebate}</td></tr>
                <tr><td style={{ padding: '8px', borderBottom: '1px solid var(--border-color)', color: 'var(--text-primary)' }}><strong>Markup Neg. Oferta:</strong></td><td style={{ padding: '8px', borderBottom: '1px solid var(--border-color)', color: 'var(--text-primary)' }}>{statsGlobales.markup_negativo_oferta}</td></tr>
                <tr><td style={{ padding: '8px', borderBottom: '1px solid var(--border-color)', color: 'var(--text-primary)' }}><strong>Markup Neg. Web:</strong></td><td style={{ padding: '8px', borderBottom: '1px solid var(--border-color)', color: 'var(--text-primary)' }}>{statsGlobales.markup_negativo_web}</td></tr>
              </tbody>
            </table>
          ) : (
            <p style={{ color: 'var(--text-secondary)' }}>Cargando...</p>
          )}
        </div>

        {/* Stats Dinámicos */}
        <div style={{ padding: '20px', background: 'var(--bg-primary)', border: '2px solid #28a745', borderRadius: '8px' }}>
          <h2 style={{ color: '#28a745' }}>🎯 Stats Dinámicos (Con Filtros)</h2>
          {statsDinamicos ? (
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <tbody>
                <tr><td style={{ padding: '8px', borderBottom: '1px solid var(--border-color)', color: 'var(--text-primary)' }}><strong>Total Productos:</strong></td><td style={{ padding: '8px', borderBottom: '1px solid var(--border-color)', color: 'var(--text-primary)' }}>{statsDinamicos.total_productos}</td></tr>
                <tr><td style={{ padding: '8px', borderBottom: '1px solid var(--border-color)', color: 'var(--text-primary)' }}><strong>Con Stock:</strong></td><td style={{ padding: '8px', borderBottom: '1px solid var(--border-color)', color: 'var(--text-primary)' }}>{statsDinamicos.con_stock}</td></tr>
                <tr><td style={{ padding: '8px', borderBottom: '1px solid var(--border-color)', color: 'var(--text-primary)' }}><strong>Con Precio:</strong></td><td style={{ padding: '8px', borderBottom: '1px solid var(--border-color)', color: 'var(--text-primary)' }}>{statsDinamicos.con_precio}</td></tr>
                <tr><td style={{ padding: '8px', borderBottom: '1px solid var(--border-color)', color: 'var(--text-primary)' }}><strong>Nuevos (7 días):</strong></td><td style={{ padding: '8px', borderBottom: '1px solid var(--border-color)', color: 'var(--text-primary)' }}>{statsDinamicos.nuevos_ultimos_7_dias}</td></tr>
                <tr><td style={{ padding: '8px', borderBottom: '1px solid var(--border-color)', color: 'var(--text-primary)' }}><strong>Sin MLA:</strong></td><td style={{ padding: '8px', borderBottom: '1px solid var(--border-color)', color: 'var(--text-primary)' }}>{statsDinamicos.sin_mla_no_banlist}</td></tr>
                <tr><td style={{ padding: '8px', borderBottom: '1px solid var(--border-color)', color: 'var(--text-primary)' }}><strong>Markup Neg. Clásica:</strong></td><td style={{ padding: '8px', borderBottom: '1px solid var(--border-color)', color: 'var(--text-primary)' }}>{statsDinamicos.markup_negativo_clasica}</td></tr>
                <tr><td style={{ padding: '8px', borderBottom: '1px solid var(--border-color)', color: 'var(--text-primary)' }}><strong>Markup Neg. Rebate:</strong></td><td style={{ padding: '8px', borderBottom: '1px solid var(--border-color)', color: 'var(--text-primary)' }}>{statsDinamicos.markup_negativo_rebate}</td></tr>
                <tr><td style={{ padding: '8px', borderBottom: '1px solid var(--border-color)', color: 'var(--text-primary)' }}><strong>Markup Neg. Oferta:</strong></td><td style={{ padding: '8px', borderBottom: '1px solid var(--border-color)', color: 'var(--text-primary)' }}>{statsDinamicos.markup_negativo_oferta}</td></tr>
                <tr><td style={{ padding: '8px', borderBottom: '1px solid var(--border-color)', color: 'var(--text-primary)' }}><strong>Markup Neg. Web:</strong></td><td style={{ padding: '8px', borderBottom: '1px solid var(--border-color)', color: 'var(--text-primary)' }}>{statsDinamicos.markup_negativo_web}</td></tr>
              </tbody>
            </table>
          ) : (
            <p style={{ color: 'var(--text-secondary)' }}>Aplica filtros y haz clic en "Calcular Stats Dinámicos"</p>
          )}
        </div>
      </div>

      <div style={{ marginTop: '30px', padding: '20px', background: 'var(--bg-secondary)', borderRadius: '8px', border: '1px solid var(--border-color)' }}>
        <h3 style={{ color: 'var(--text-primary)' }}>📝 Notas</h3>
        <ul style={{ color: 'var(--text-primary)' }}>
          <li><strong>Stats Globales:</strong> Se calculan sobre TODOS los productos sin filtros (endpoint <code>/stats</code>)</li>
          <li><strong>Stats Dinámicos:</strong> Se calculan SOLO sobre productos que cumplen con los filtros aplicados (endpoint <code>/stats-dinamicos</code>)</li>
          <li>Esta es una página de prueba para comparar ambos enfoques</li>
          <li>Los stats dinámicos usan SQL COUNT para mejor rendimiento</li>
        </ul>
      </div>
    </div>
  );
};

export default TestStatsDinamicos;
