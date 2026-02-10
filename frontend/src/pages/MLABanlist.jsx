import { useState, useEffect } from 'react';
import api from '../services/api';
import styles from './Admin.module.css';
import { useAuthStore } from '../store/authStore';

export default function MLABanlist() {
  const [mlas, setMlas] = useState([]);
  const [cargando, setCargando] = useState(true);
  const [mlasInput, setMlasInput] = useState('');
  const [motivo, setMotivo] = useState('');
  const [agregando, setAgregando] = useState(false);
  const [filtro, setFiltro] = useState('');

  const user = useAuthStore((state) => state.user);
  const esAdmin = ['SUPERADMIN', 'ADMIN'].includes(user?.rol);

  useEffect(() => {
    cargarBanlist();
  }, []);

  const cargarBanlist = async () => {
    try {
      const response = await api.get('/mla-banlist');
      setMlas(response.data);
      setCargando(false);
    } catch (error) {
      console.error('Error cargando banlist:', error);
      alert('Error al cargar banlist: ' + (error.response?.data?.detail || error.message));
      setCargando(false);
    }
  };

  const agregarMLAs = async () => {
    if (!mlasInput.trim()) {
      alert('Ingresa al menos un MLA');
      return;
    }

    setAgregando(true);
    try {
      const response = await api.post('/mla-banlist', {
        mlas: mlasInput,
        motivo: motivo || null
      });

      let mensaje = `✅ ${response.data.total_agregados} MLA(s) agregados correctamente`;

      if (response.data.duplicados.length > 0) {
        mensaje += `\n\n⚠️ ${response.data.duplicados.length} duplicados (ya estaban en la banlist):\n${response.data.duplicados.join(', ')}`;
      }

      if (response.data.invalidos.length > 0) {
        mensaje += `\n\n❌ ${response.data.invalidos.length} inválidos:\n${response.data.invalidos.join(', ')}`;
      }

      alert(mensaje);
      setMlasInput('');
      setMotivo('');
      cargarBanlist();
    } catch (error) {
      alert('Error al agregar MLAs: ' + (error.response?.data?.detail || error.message));
    } finally {
      setAgregando(false);
    }
  };

  const eliminarMLA = async (id, mla) => {
    if (!confirm(`¿Eliminar ${mla} de la banlist?`)) return;

    try {
      await api.delete(`/mla-banlist/${id}`);

      alert('✅ MLA eliminado de la banlist');
      cargarBanlist();
    } catch (error) {
      alert('Error al eliminar: ' + (error.response?.data?.detail || error.message));
    }
  };

  const mlasFiltrados = mlas.filter(m =>
    m.mla.toLowerCase().includes(filtro.toLowerCase()) ||
    (m.motivo && m.motivo.toLowerCase().includes(filtro.toLowerCase())) ||
    m.usuario_nombre.toLowerCase().includes(filtro.toLowerCase())
  );

  if (cargando) {
    return <div className={styles.container}>Cargando...</div>;
  }

  return (
    <div className={styles.container}>
      <h1 className={styles.title}>Banlist de MLAs</h1>
      <p style={{ marginBottom: '24px', color: 'var(--text-secondary)' }}>
        Los MLAs en esta lista serán excluidos automáticamente de las exportaciones de rebates
      </p>

      {/* Formulario para agregar MLAs */}
      <div className={styles.section} style={{ marginBottom: '24px' }}>
        <h2 className={styles.sectionTitle}>Agregar MLAs a la Banlist</h2>
        <p style={{ marginBottom: '12px', fontSize: '14px', color: 'var(--text-secondary)' }}>
          Puedes ingresar uno o múltiples MLAs separados por comas, espacios o saltos de línea.
          <br />
          Formatos aceptados: <code style={{ background: 'var(--bg-tertiary)', padding: '2px 6px', borderRadius: '4px' }}>MLA123456789</code> o <code style={{ background: 'var(--bg-tertiary)', padding: '2px 6px', borderRadius: '4px' }}>123456789</code>
        </p>

        <textarea
          placeholder="Ej: MLA123456789, 987654321, MLA555555555&#10;Uno por línea o separados por comas"
          value={mlasInput}
          onChange={(e) => setMlasInput(e.target.value)}
          style={{
            width: '100%',
            minHeight: '120px',
            padding: '12px',
            borderRadius: '8px',
            border: '1px solid var(--border-color)',
            fontSize: '14px',
            fontFamily: 'monospace',
            background: 'var(--bg-primary)',
            color: 'var(--text-primary)',
            marginBottom: '12px',
            resize: 'vertical'
          }}
        />

        <input
          type="text"
          placeholder="Motivo (opcional)"
          value={motivo}
          onChange={(e) => setMotivo(e.target.value)}
          style={{
            width: '100%',
            padding: '10px 12px',
            borderRadius: '8px',
            border: '1px solid var(--border-color)',
            fontSize: '14px',
            background: 'var(--bg-primary)',
            color: 'var(--text-primary)',
            marginBottom: '12px'
          }}
        />

        <button
          onClick={agregarMLAs}
          disabled={agregando || !mlasInput.trim()}
          className={styles.syncButton}
          style={{
            opacity: agregando || !mlasInput.trim() ? 0.5 : 1,
            cursor: agregando || !mlasInput.trim() ? 'not-allowed' : 'pointer'
          }}
        >
          {agregando ? '⏳ Agregando...' : '➕ Agregar a Banlist'}
        </button>
      </div>

      {/* Lista de MLAs baneados */}
      <div className={styles.section}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
          <h2 className={styles.sectionTitle}>MLAs Baneados ({mlas.length})</h2>
        </div>

        <input
          type="text"
          placeholder="Buscar por MLA, motivo o usuario..."
          value={filtro}
          onChange={(e) => setFiltro(e.target.value)}
          style={{
            width: '100%',
            padding: '10px 12px',
            borderRadius: '8px',
            border: '1px solid var(--border-color)',
            fontSize: '14px',
            background: 'var(--bg-primary)',
            color: 'var(--text-primary)',
            marginBottom: '16px'
          }}
        />

        {mlasFiltrados.length === 0 ? (
          <div style={{ padding: '40px', textAlign: 'center', color: 'var(--text-secondary)' }}>
            {filtro ? 'No se encontraron resultados' : 'No hay MLAs en la banlist'}
          </div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr style={{ borderBottom: '2px solid var(--border-color)', textAlign: 'left' }}>
                  <th style={{ padding: '12px', color: 'var(--text-primary)' }}>MLA</th>
                  <th style={{ padding: '12px', color: 'var(--text-primary)' }}>Motivo</th>
                  <th style={{ padding: '12px', color: 'var(--text-primary)' }}>Agregado por</th>
                  <th style={{ padding: '12px', color: 'var(--text-primary)' }}>Fecha</th>
                  {esAdmin && <th style={{ padding: '12px', color: 'var(--text-primary)' }}>Acciones</th>}
                </tr>
              </thead>
              <tbody>
                {mlasFiltrados.map(mla => (
                  <tr key={mla.id} style={{ borderBottom: '1px solid var(--border-color)' }}>
                    <td style={{ padding: '12px', fontFamily: 'monospace', fontWeight: '600', color: 'var(--text-primary)' }}>
                      {mla.mla}
                    </td>
                    <td style={{ padding: '12px', color: 'var(--text-secondary)' }}>
                      {mla.motivo || <em style={{ color: 'var(--text-tertiary)' }}>Sin motivo</em>}
                    </td>
                    <td style={{ padding: '12px', color: 'var(--text-secondary)' }}>
                      {mla.usuario_nombre}
                    </td>
                    <td style={{ padding: '12px', color: 'var(--text-secondary)' }}>
                      {new Date(mla.fecha_creacion).toLocaleDateString('es-AR', {
                        year: 'numeric',
                        month: 'short',
                        day: 'numeric',
                        hour: '2-digit',
                        minute: '2-digit'
                      })}
                    </td>
                    {esAdmin && (
                      <td style={{ padding: '12px' }}>
                        <button
                          onClick={() => eliminarMLA(mla.id, mla.mla)}
                          style={{
                            padding: '6px 12px',
                            borderRadius: '4px',
                            border: 'none',
                            background: '#fee2e2',
                            color: '#991b1b',
                            cursor: 'pointer',
                            fontSize: '13px'
                          }}
                        >
                          🗑️ Eliminar
                        </button>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
