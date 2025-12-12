import { useState, useEffect } from 'react';
import axios from 'axios';
import styles from './Admin.module.css';
import { useAuthStore } from '../store/authStore';

export default function Banlist() {
  const [tabActivo, setTabActivo] = useState('mla'); // 'mla' o 'productos'

  return (
    <div className={styles.container}>
      {/* Tabs */}
      <div style={{ display: 'flex', gap: '4px', marginBottom: '24px', borderBottom: '2px solid var(--border-color)' }}>
        <button
          onClick={() => setTabActivo('mla')}
          style={{
            padding: '12px 24px',
            border: 'none',
            background: tabActivo === 'mla' ? 'var(--bg-secondary)' : 'transparent',
            color: tabActivo === 'mla' ? 'var(--text-primary)' : 'var(--text-secondary)',
            borderBottom: tabActivo === 'mla' ? '2px solid #3b82f6' : 'none',
            marginBottom: '-2px',
            cursor: 'pointer',
            fontSize: '15px',
            fontWeight: tabActivo === 'mla' ? '600' : '500',
            transition: 'all 0.2s'
          }}
        >
          🚫 Banlist MLAs
        </button>
        <button
          onClick={() => setTabActivo('productos')}
          style={{
            padding: '12px 24px',
            border: 'none',
            background: tabActivo === 'productos' ? 'var(--bg-secondary)' : 'transparent',
            color: tabActivo === 'productos' ? 'var(--text-primary)' : 'var(--text-secondary)',
            borderBottom: tabActivo === 'productos' ? '2px solid #3b82f6' : 'none',
            marginBottom: '-2px',
            cursor: 'pointer',
            fontSize: '15px',
            fontWeight: tabActivo === 'productos' ? '600' : '500',
            transition: 'all 0.2s'
          }}
        >
          📦 Banlist Productos
        </button>
      </div>

      {/* Contenido según tab activo */}
      {tabActivo === 'mla' ? <MLABanlistTab /> : <ProductoBanlistTab />}
    </div>
  );
}

// Tab de MLA Banlist
function MLABanlistTab() {
  const [mlas, setMlas] = useState([]);
  const [cargando, setCargando] = useState(true);
  const [mlasInput, setMlasInput] = useState('');
  const [motivo, setMotivo] = useState('');
  const [agregando, setAgregando] = useState(false);
  const [filtro, setFiltro] = useState('');

  const user = useAuthStore((state) => state.user);
  const esAdmin = ['SUPERADMIN', 'ADMIN'].includes(user?.rol);

  const API_URL = 'https://pricing.gaussonline.com.ar/api';

  useEffect(() => {
    cargarBanlist();
  }, []);

  const cargarBanlist = async () => {
    try {
      const token = localStorage.getItem('token');
      const response = await axios.get(`${API_URL}/mla-banlist`, {
        headers: { Authorization: `Bearer ${token}` }
      });
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
      const token = localStorage.getItem('token');
      const response = await axios.post(
        `${API_URL}/mla-banlist`,
        {
          mlas: mlasInput,
          motivo: motivo || null
        },
        { headers: { Authorization: `Bearer ${token}` }}
      );

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
      const token = localStorage.getItem('token');
      await axios.delete(`${API_URL}/mla-banlist/${id}`, {
        headers: { Authorization: `Bearer ${token}` }
      });

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
    return <div>Cargando...</div>;
  }

  return (
    <>
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
    </>
  );
}

// Tab de Producto Banlist
function ProductoBanlistTab() {
  const [productos, setProductos] = useState([]);
  const [cargando, setCargando] = useState(true);
  const [itemIdsInput, setItemIdsInput] = useState('');
  const [eansInput, setEansInput] = useState('');
  const [motivo, setMotivo] = useState('');
  const [agregando, setAgregando] = useState(false);
  const [filtro, setFiltro] = useState('');

  const user = useAuthStore((state) => state.user);
  const esAdmin = ['SUPERADMIN', 'ADMIN'].includes(user?.rol);

  const API_URL = 'https://pricing.gaussonline.com.ar/api';

  useEffect(() => {
    cargarBanlist();
  }, []);

  const cargarBanlist = async () => {
    try {
      const token = localStorage.getItem('token');
      const response = await axios.get(`${API_URL}/producto-banlist`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      setProductos(response.data);
      setCargando(false);
    } catch (error) {
      console.error('Error cargando banlist:', error);
      alert('Error al cargar banlist: ' + (error.response?.data?.detail || error.message));
      setCargando(false);
    }
  };

  const agregarProductos = async () => {
    if (!itemIdsInput.trim() && !eansInput.trim()) {
      alert('Ingresa al menos un Item ID o EAN');
      return;
    }

    setAgregando(true);
    try {
      const token = localStorage.getItem('token');
      const response = await axios.post(
        `${API_URL}/producto-banlist`,
        {
          item_ids: itemIdsInput || null,
          eans: eansInput || null,
          motivo: motivo || null
        },
        { headers: { Authorization: `Bearer ${token}` }}
      );

      let mensaje = `✅ ${response.data.total_agregados} producto(s) agregados correctamente`;

      if (response.data.agregados.length > 0) {
        mensaje += `\n\n📝 Agregados:\n${response.data.agregados.join('\n')}`;
      }

      if (response.data.duplicados.length > 0) {
        mensaje += `\n\n⚠️ ${response.data.duplicados.length} duplicados (ya estaban en la banlist):\n${response.data.duplicados.join(', ')}`;
      }

      if (response.data.no_encontrados.length > 0) {
        mensaje += `\n\n❌ ${response.data.no_encontrados.length} no encontrados:\n${response.data.no_encontrados.join(', ')}`;
      }

      alert(mensaje);
      setItemIdsInput('');
      setEansInput('');
      setMotivo('');
      cargarBanlist();
    } catch (error) {
      alert('Error al agregar productos: ' + (error.response?.data?.detail || error.message));
    } finally {
      setAgregando(false);
    }
  };

  const eliminarProducto = async (id, identificador) => {
    if (!confirm(`¿Eliminar ${identificador} de la banlist?`)) return;

    try {
      const token = localStorage.getItem('token');
      await axios.delete(`${API_URL}/producto-banlist/${id}`, {
        headers: { Authorization: `Bearer ${token}` }
      });

      alert('✅ Producto eliminado de la banlist');
      cargarBanlist();
    } catch (error) {
      alert('Error al eliminar: ' + (error.response?.data?.detail || error.message));
    }
  };

  const productosFiltrados = productos.filter(p => {
    const searchTerm = filtro.toLowerCase();
    return (
      (p.item_id && p.item_id.toString().includes(searchTerm)) ||
      (p.ean && p.ean.toLowerCase().includes(searchTerm)) ||
      (p.codigo && p.codigo.toLowerCase().includes(searchTerm)) ||
      (p.descripcion && p.descripcion.toLowerCase().includes(searchTerm)) ||
      (p.motivo && p.motivo.toLowerCase().includes(searchTerm))
    );
  });

  if (cargando) {
    return <div>Cargando...</div>;
  }

  return (
    <>
      <h1 className={styles.title}>Banlist de Productos</h1>
      <p style={{ marginBottom: '24px', color: 'var(--text-secondary)' }}>
        Los productos en esta lista serán excluidos automáticamente de todas las vistas y exportaciones
      </p>

      {/* Formulario para agregar productos */}
      <div className={styles.section} style={{ marginBottom: '24px' }}>
        <h2 className={styles.sectionTitle}>Agregar Productos a la Banlist</h2>
        <p style={{ marginBottom: '12px', fontSize: '14px', color: 'var(--text-secondary)' }}>
          Puedes ingresar Item IDs o EANs separados por comas, espacios o saltos de línea.
        </p>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px', marginBottom: '12px' }}>
          <div>
            <label style={{ display: 'block', marginBottom: '8px', fontSize: '14px', fontWeight: '500', color: 'var(--text-primary)' }}>
              Item IDs
            </label>
            <textarea
              placeholder="Ej: 1234, 5678, 9012&#10;Uno por línea o separados por comas"
              value={itemIdsInput}
              onChange={(e) => setItemIdsInput(e.target.value)}
              style={{
                width: '100%',
                minHeight: '100px',
                padding: '12px',
                borderRadius: '8px',
                border: '1px solid var(--border-color)',
                fontSize: '14px',
                fontFamily: 'monospace',
                background: 'var(--bg-primary)',
                color: 'var(--text-primary)',
                resize: 'vertical'
              }}
            />
          </div>

          <div>
            <label style={{ display: 'block', marginBottom: '8px', fontSize: '14px', fontWeight: '500', color: 'var(--text-primary)' }}>
              EANs
            </label>
            <textarea
              placeholder="Ej: 7798123456789, 7798987654321&#10;Uno por línea o separados por comas"
              value={eansInput}
              onChange={(e) => setEansInput(e.target.value)}
              style={{
                width: '100%',
                minHeight: '100px',
                padding: '12px',
                borderRadius: '8px',
                border: '1px solid var(--border-color)',
                fontSize: '14px',
                fontFamily: 'monospace',
                background: 'var(--bg-primary)',
                color: 'var(--text-primary)',
                resize: 'vertical'
              }}
            />
          </div>
        </div>

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
          onClick={agregarProductos}
          disabled={agregando || (!itemIdsInput.trim() && !eansInput.trim())}
          className={styles.syncButton}
          style={{
            opacity: agregando || (!itemIdsInput.trim() && !eansInput.trim()) ? 0.5 : 1,
            cursor: agregando || (!itemIdsInput.trim() && !eansInput.trim()) ? 'not-allowed' : 'pointer'
          }}
        >
          {agregando ? '⏳ Agregando...' : '➕ Agregar a Banlist'}
        </button>
      </div>

      {/* Lista de productos baneados */}
      <div className={styles.section}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
          <h2 className={styles.sectionTitle}>Productos Baneados ({productos.length})</h2>
        </div>

        <input
          type="text"
          placeholder="Buscar por Item ID, EAN, código, descripción o motivo..."
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

        {productosFiltrados.length === 0 ? (
          <div style={{ padding: '40px', textAlign: 'center', color: 'var(--text-secondary)' }}>
            {filtro ? 'No se encontraron resultados' : 'No hay productos en la banlist'}
          </div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr style={{ borderBottom: '2px solid var(--border-color)', textAlign: 'left' }}>
                  <th style={{ padding: '12px', color: 'var(--text-primary)' }}>Item ID / EAN</th>
                  <th style={{ padding: '12px', color: 'var(--text-primary)' }}>Código</th>
                  <th style={{ padding: '12px', color: 'var(--text-primary)' }}>Descripción</th>
                  <th style={{ padding: '12px', color: 'var(--text-primary)' }}>Motivo</th>
                  <th style={{ padding: '12px', color: 'var(--text-primary)' }}>Usuario</th>
                  <th style={{ padding: '12px', color: 'var(--text-primary)' }}>Fecha</th>
                  {esAdmin && <th style={{ padding: '12px', color: 'var(--text-primary)' }}>Acciones</th>}
                </tr>
              </thead>
              <tbody>
                {productosFiltrados.map(prod => {
                  const identificador = prod.item_id ? `ID: ${prod.item_id}` : `EAN: ${prod.ean}`;
                  return (
                    <tr key={prod.id} style={{ borderBottom: '1px solid var(--border-color)' }}>
                      <td style={{ padding: '12px', fontFamily: 'monospace', fontWeight: '600', color: 'var(--text-primary)' }}>
                        {identificador}
                      </td>
                      <td style={{ padding: '12px', color: 'var(--text-secondary)', fontFamily: 'monospace' }}>
                        {prod.codigo || <em style={{ color: 'var(--text-tertiary)' }}>-</em>}
                      </td>
                      <td style={{ padding: '12px', color: 'var(--text-secondary)', maxWidth: '300px' }}>
                        {prod.descripcion || <em style={{ color: 'var(--text-tertiary)' }}>-</em>}
                      </td>
                      <td style={{ padding: '12px', color: 'var(--text-secondary)' }}>
                        {prod.motivo || <em style={{ color: 'var(--text-tertiary)' }}>Sin motivo</em>}
                      </td>
                      <td style={{ padding: '12px', color: 'var(--text-secondary)' }}>
                        {prod.usuario_nombre || <em style={{ color: 'var(--text-tertiary)' }}>-</em>}
                      </td>
                      <td style={{ padding: '12px', color: 'var(--text-secondary)' }}>
                        {new Date(prod.fecha_creacion).toLocaleDateString('es-AR', {
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
                            onClick={() => eliminarProducto(prod.id, identificador)}
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
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  );
}
