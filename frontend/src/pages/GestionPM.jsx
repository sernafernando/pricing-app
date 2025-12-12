import { useState, useEffect } from 'react';
import axios from 'axios';
import styles from './Admin.module.css';

export default function GestionPM() {
  const [marcas, setMarcas] = useState([]);
  const [usuarios, setUsuarios] = useState([]);
  const [cargando, setCargando] = useState(true);
  const [filtro, setFiltro] = useState('');
  const [editandoMarca, setEditandoMarca] = useState(null);

  useEffect(() => {
    cargarDatos();
  }, []);

  const cargarDatos = async () => {
    try {
      const token = localStorage.getItem('token');

      // Cargar marcas con PMs asignados
      const marcasRes = await axios.get('https://pricing.gaussonline.com.ar/api/marcas-pm',
        { headers: { Authorization: `Bearer ${token}` }});
      setMarcas(marcasRes.data);

      // Cargar usuarios disponibles
      const usuariosRes = await axios.get('https://pricing.gaussonline.com.ar/api/usuarios/pms',
        { headers: { Authorization: `Bearer ${token}` }});
      setUsuarios(usuariosRes.data);

      setCargando(false);
    } catch (error) {
      console.error('Error cargando datos:', error);
      alert('Error al cargar datos: ' + (error.response?.data?.detail || error.message));
      setCargando(false);
    }
  };

  const asignarPM = async (marcaId, usuarioId) => {
    try {
      const token = localStorage.getItem('token');
      await axios.patch(
        `https://pricing.gaussonline.com.ar/api/marcas-pm/${marcaId}`,
        { usuario_id: usuarioId === '' ? null : parseInt(usuarioId) },
        { headers: { Authorization: `Bearer ${token}` }}
      );

      setEditandoMarca(null);
      cargarDatos();
    } catch (error) {
      alert('Error al asignar PM: ' + (error.response?.data?.detail || error.message));
    }
  };

  const sincronizarMarcas = async () => {
    try {
      const token = localStorage.getItem('token');
      const response = await axios.post(
        'https://pricing.gaussonline.com.ar/api/marcas-pm/sync',
        {},
        { headers: { Authorization: `Bearer ${token}` }}
      );

      alert(`✅ Sincronización completada\nMarcas nuevas agregadas: ${response.data.marcas_nuevas}`);
      cargarDatos();
    } catch (error) {
      alert('Error al sincronizar: ' + (error.response?.data?.detail || error.message));
    }
  };

  const marcasFiltradas = marcas.filter(m =>
    m.marca.toLowerCase().includes(filtro.toLowerCase()) ||
    (m.usuario_nombre && m.usuario_nombre.toLowerCase().includes(filtro.toLowerCase()))
  );

  // Agrupar por PM
  const marcasPorPM = {};
  marcasFiltradas.forEach(marca => {
    const pmKey = marca.usuario_id || 'sin_asignar';
    if (!marcasPorPM[pmKey]) {
      marcasPorPM[pmKey] = {
        usuario: marca.usuario_id ? {
          id: marca.usuario_id,
          nombre: marca.usuario_nombre,
          email: marca.usuario_email
        } : null,
        marcas: []
      };
    }
    marcasPorPM[pmKey].marcas.push(marca);
  });

  if (cargando) {
    return <div className={styles.container}>Cargando...</div>;
  }

  return (
    <div className={styles.container}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '24px' }}>
        <h1 className={styles.title}>Gestión de Product Managers</h1>
        <button
          onClick={sincronizarMarcas}
          className={styles.syncButton}
          style={{ padding: '8px 16px', fontSize: '14px' }}
        >
          🔄 Sincronizar Marcas
        </button>
      </div>

      <div className={styles.section}>
        <div style={{ marginBottom: '20px' }}>
          <input
            type="text"
            placeholder="Buscar por marca o PM..."
            value={filtro}
            onChange={(e) => setFiltro(e.target.value)}
            style={{
              width: '100%',
              padding: '12px',
              borderRadius: '8px',
              border: '1px solid var(--border-color)',
              fontSize: '14px',
              background: 'var(--bg-primary)',
              color: 'var(--text-primary)'
            }}
          />
        </div>

        <div style={{ marginBottom: '20px', padding: '12px', background: 'var(--bg-secondary)', borderRadius: '8px', border: '1px solid var(--border-color)' }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '12px', fontSize: '14px' }}>
            <div>
              <strong>Total Marcas:</strong> {marcas.length}
            </div>
            <div>
              <strong>Asignadas:</strong> {marcas.filter(m => m.usuario_id).length}
            </div>
            <div>
              <strong>Sin asignar:</strong> {marcas.filter(m => !m.usuario_id).length}
            </div>
          </div>
        </div>

        {/* Marcas agrupadas por PM */}
        <div style={{ display: 'grid', gap: '20px' }}>
          {Object.entries(marcasPorPM).map(([key, data]) => (
            <div
              key={key}
              style={{
                border: '1px solid var(--border-color)',
                borderRadius: '8px',
                padding: '16px',
                background: key === 'sin_asignar' ? 'var(--warning-bg)' : 'var(--bg-secondary)'
              }}
            >
              <h3 style={{ marginBottom: '12px', fontSize: '16px', fontWeight: '600', color: 'var(--text-primary)' }}>
                {data.usuario ? (
                  <>
                    👤 {data.usuario.nombre} <span style={{ color: 'var(--text-secondary)', fontSize: '14px' }}>({data.usuario.email})</span>
                  </>
                ) : (
                  <>⚠️ Sin asignar</>
                )}
                <span style={{ marginLeft: '8px', color: 'var(--text-secondary)', fontSize: '14px' }}>
                  - {data.marcas.length} marca{data.marcas.length !== 1 ? 's' : ''}
                </span>
              </h3>

              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: '8px' }}>
                {data.marcas.map(marca => (
                  <div
                    key={marca.id}
                    style={{
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'center',
                      padding: '8px 12px',
                      background: 'var(--bg-tertiary)',
                      borderRadius: '6px',
                      fontSize: '14px',
                      border: '1px solid var(--border-color)'
                    }}
                  >
                    <span style={{ fontWeight: '500', color: 'var(--text-primary)' }}>{marca.marca}</span>

                    {editandoMarca === marca.id ? (
                      <div style={{ display: 'flex', gap: '4px', alignItems: 'center' }}>
                        <select
                          defaultValue={marca.usuario_id || ''}
                          onChange={(e) => asignarPM(marca.id, e.target.value)}
                          style={{
                            padding: '4px 8px',
                            borderRadius: '4px',
                            border: '1px solid var(--border-color)',
                            fontSize: '12px',
                            background: 'var(--bg-primary)',
                            color: 'var(--text-primary)'
                          }}
                        >
                          <option value="">Sin asignar</option>
                          {usuarios.map(u => (
                            <option key={u.id} value={u.id}>
                              {u.nombre}
                            </option>
                          ))}
                        </select>
                        <button
                          onClick={() => setEditandoMarca(null)}
                          style={{
                            padding: '4px 8px',
                            background: '#ef4444',
                            color: 'white',
                            border: 'none',
                            borderRadius: '4px',
                            cursor: 'pointer',
                            fontSize: '11px'
                          }}
                        >
                          ✗
                        </button>
                      </div>
                    ) : (
                      <button
                        onClick={() => setEditandoMarca(marca.id)}
                        style={{
                          padding: '4px 8px',
                          background: 'var(--accent-bg)',
                          color: 'var(--accent-text)',
                          border: 'none',
                          borderRadius: '4px',
                          cursor: 'pointer',
                          fontSize: '11px'
                        }}
                      >
                        Cambiar PM
                      </button>
                    )}
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
