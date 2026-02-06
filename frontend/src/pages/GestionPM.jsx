import { useState, useEffect } from 'react';
import axios from 'axios';
import styles from './Admin.module.css';

const API_URL = import.meta.env.VITE_API_URL;

export default function GestionPM() {
  const [registros, setRegistros] = useState([]);
  const [usuarios, setUsuarios] = useState([]);
  const [cargando, setCargando] = useState(true);
  const [filtro, setFiltro] = useState('');
  const [vistaAgrupada, setVistaAgrupada] = useState('pm'); // 'pm' | 'marca'

  useEffect(() => {
    cargarDatos();
  }, []);

  const cargarDatos = async () => {
    try {
      const token = localStorage.getItem('token');
      const headers = { Authorization: `Bearer ${token}` };

      const [registrosRes, usuariosRes] = await Promise.all([
        axios.get(`${API_URL}/marcas-pm`, { headers }),
        axios.get(`${API_URL}/usuarios/pms`, { headers }),
      ]);

      setRegistros(registrosRes.data);
      setUsuarios(usuariosRes.data);
      setCargando(false);
    } catch (error) {
      console.error('Error cargando datos:', error);
      alert('Error al cargar datos: ' + (error.response?.data?.detail || error.message));
      setCargando(false);
    }
  };

  const asignarPM = async (registroId, usuarioId) => {
    try {
      const token = localStorage.getItem('token');
      await axios.patch(
        `${API_URL}/marcas-pm/${registroId}`,
        { usuario_id: usuarioId === '' ? null : parseInt(usuarioId) },
        { headers: { Authorization: `Bearer ${token}` } }
      );
      cargarDatos();
    } catch (error) {
      alert('Error al asignar PM: ' + (error.response?.data?.detail || error.message));
    }
  };

  const asignarPMMasivo = async (marca, categorias, usuarioId) => {
    try {
      const token = localStorage.getItem('token');
      await axios.put(
        `${API_URL}/marcas-pm/asignar`,
        {
          marca,
          categorias,
          usuario_id: usuarioId === '' ? null : parseInt(usuarioId),
        },
        { headers: { Authorization: `Bearer ${token}` } }
      );
      cargarDatos();
    } catch (error) {
      alert('Error al asignar PM: ' + (error.response?.data?.detail || error.message));
    }
  };

  const sincronizarMarcas = async () => {
    try {
      const token = localStorage.getItem('token');
      const response = await axios.post(
        `${API_URL}/marcas-pm/sync`,
        {},
        { headers: { Authorization: `Bearer ${token}` } }
      );
      alert(`Sincronizacion completada\nPares marca-categoria nuevos: ${response.data.pares_nuevos}`);
      cargarDatos();
    } catch (error) {
      alert('Error al sincronizar: ' + (error.response?.data?.detail || error.message));
    }
  };

  // Filtrar registros
  const registrosFiltrados = registros.filter((r) =>
    r.marca.toLowerCase().includes(filtro.toLowerCase()) ||
    r.categoria.toLowerCase().includes(filtro.toLowerCase()) ||
    (r.usuario_nombre && r.usuario_nombre.toLowerCase().includes(filtro.toLowerCase()))
  );

  // Stats
  const totalPares = registros.length;
  const asignados = registros.filter((r) => r.usuario_id).length;
  const sinAsignar = registros.filter((r) => !r.usuario_id).length;
  const marcasUnicas = new Set(registros.map((r) => r.marca)).size;

  if (cargando) {
    return <div className={styles.container}>Cargando...</div>;
  }

  return (
    <div className={styles.container}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '24px' }}>
        <h1 className={styles.title} style={{ marginBottom: 0 }}>Gestion de Product Managers</h1>
        <button
          onClick={sincronizarMarcas}
          className={styles.syncButton}
          style={{ padding: '8px 16px', fontSize: '14px' }}
        >
          Sincronizar Marcas
        </button>
      </div>

      <div className={styles.section}>
        {/* Search + View Toggle */}
        <div style={{ display: 'flex', gap: '12px', marginBottom: '20px' }}>
          <input
            type="text"
            placeholder="Buscar por marca, categoria o PM..."
            value={filtro}
            onChange={(e) => setFiltro(e.target.value)}
            style={{
              flex: 1,
              padding: '12px',
              borderRadius: '8px',
              border: '1px solid var(--border-color)',
              fontSize: '14px',
              background: 'var(--bg-primary)',
              color: 'var(--text-primary)',
            }}
          />
          <div style={{ display: 'flex', gap: '4px' }}>
            <button
              onClick={() => setVistaAgrupada('pm')}
              style={{
                padding: '8px 16px',
                borderRadius: '8px',
                border: '1px solid var(--border-color)',
                background: vistaAgrupada === 'pm' ? 'var(--accent-bg, rgba(59,130,246,0.1))' : 'var(--bg-primary)',
                color: vistaAgrupada === 'pm' ? 'var(--accent-text, #60a5fa)' : 'var(--text-secondary)',
                cursor: 'pointer',
                fontSize: '13px',
                fontWeight: vistaAgrupada === 'pm' ? '600' : '400',
              }}
            >
              Por PM
            </button>
            <button
              onClick={() => setVistaAgrupada('marca')}
              style={{
                padding: '8px 16px',
                borderRadius: '8px',
                border: '1px solid var(--border-color)',
                background: vistaAgrupada === 'marca' ? 'var(--accent-bg, rgba(59,130,246,0.1))' : 'var(--bg-primary)',
                color: vistaAgrupada === 'marca' ? 'var(--accent-text, #60a5fa)' : 'var(--text-secondary)',
                cursor: 'pointer',
                fontSize: '13px',
                fontWeight: vistaAgrupada === 'marca' ? '600' : '400',
              }}
            >
              Por Marca
            </button>
          </div>
        </div>

        {/* Stats */}
        <div style={{ marginBottom: '20px', padding: '12px', background: 'var(--bg-secondary)', borderRadius: '8px', border: '1px solid var(--border-color)' }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '12px', fontSize: '14px' }}>
            <div><strong>Marcas:</strong> {marcasUnicas}</div>
            <div><strong>Pares (marca+cat):</strong> {totalPares}</div>
            <div><strong>Asignados:</strong> {asignados}</div>
            <div><strong>Sin asignar:</strong> {sinAsignar}</div>
          </div>
        </div>

        {/* Content */}
        {vistaAgrupada === 'pm' ? (
          <VistaPorPM
            registros={registrosFiltrados}
            usuarios={usuarios}
            onAsignar={asignarPM}
          />
        ) : (
          <VistaPorMarca
            registros={registrosFiltrados}
            usuarios={usuarios}
            onAsignar={asignarPM}
            onAsignarMasivo={asignarPMMasivo}
          />
        )}
      </div>
    </div>
  );
}


// ── Vista Por PM ──────────────────────────────────────────────────────────────

function VistaPorPM({ registros, usuarios, onAsignar }) {
  const [editandoId, setEditandoId] = useState(null);

  // Agrupar por PM
  const porPM = {};
  registros.forEach((reg) => {
    const key = reg.usuario_id || 'sin_asignar';
    if (!porPM[key]) {
      porPM[key] = {
        usuario: reg.usuario_id
          ? { id: reg.usuario_id, nombre: reg.usuario_nombre, email: reg.usuario_email }
          : null,
        registros: [],
      };
    }
    porPM[key].registros.push(reg);
  });

  // Dentro de cada PM, agrupar por marca
  const renderMarcaGroup = (regs) => {
    const porMarca = {};
    regs.forEach((r) => {
      if (!porMarca[r.marca]) porMarca[r.marca] = [];
      porMarca[r.marca].push(r);
    });

    return Object.entries(porMarca)
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([marca, cats]) => (
        <div
          key={marca}
          style={{
            padding: '8px 12px',
            background: 'var(--bg-tertiary)',
            borderRadius: '6px',
            fontSize: '14px',
            border: '1px solid var(--border-color)',
          }}
        >
          <div style={{ fontWeight: '600', color: 'var(--text-primary)', marginBottom: cats.length > 1 ? '4px' : 0 }}>
            {marca}
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px' }}>
            {cats.map((reg) => (
              <span
                key={reg.id}
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '4px',
                  padding: '2px 8px',
                  background: 'var(--bg-secondary)',
                  borderRadius: '4px',
                  fontSize: '12px',
                  color: 'var(--text-secondary)',
                  border: '1px solid var(--border-color)',
                }}
              >
                {reg.categoria}
                {editandoId === reg.id ? (
                  <select
                    defaultValue={reg.usuario_id || ''}
                    onChange={(e) => {
                      onAsignar(reg.id, e.target.value);
                      setEditandoId(null);
                    }}
                    autoFocus
                    style={{
                      padding: '1px 4px',
                      borderRadius: '3px',
                      border: '1px solid var(--border-color)',
                      fontSize: '11px',
                      background: 'var(--bg-primary)',
                      color: 'var(--text-primary)',
                    }}
                  >
                    <option value="">Sin asignar</option>
                    {usuarios.map((u) => (
                      <option key={u.id} value={u.id}>{u.nombre}</option>
                    ))}
                  </select>
                ) : (
                  <button
                    onClick={() => setEditandoId(reg.id)}
                    style={{
                      padding: '1px 4px',
                      background: 'none',
                      color: 'var(--text-secondary)',
                      border: 'none',
                      cursor: 'pointer',
                      fontSize: '10px',
                      opacity: 0.6,
                    }}
                    title="Cambiar PM de esta categoria"
                  >
                    ✎
                  </button>
                )}
              </span>
            ))}
          </div>
        </div>
      ));
  };

  return (
    <div style={{ display: 'grid', gap: '20px' }}>
      {Object.entries(porPM).map(([key, data]) => (
        <div
          key={key}
          style={{
            border: '1px solid var(--border-color)',
            borderRadius: '8px',
            padding: '16px',
            background: key === 'sin_asignar' ? 'var(--warning-bg, rgba(234,179,8,0.05))' : 'var(--bg-secondary)',
          }}
        >
          <h3 style={{ marginBottom: '12px', fontSize: '16px', fontWeight: '600', color: 'var(--text-primary)' }}>
            {data.usuario ? (
              <>
                {data.usuario.nombre}{' '}
                <span style={{ color: 'var(--text-secondary)', fontSize: '14px' }}>({data.usuario.email})</span>
              </>
            ) : (
              <>Sin asignar</>
            )}
            <span style={{ marginLeft: '8px', color: 'var(--text-secondary)', fontSize: '14px' }}>
              - {new Set(data.registros.map((r) => r.marca)).size} marca{new Set(data.registros.map((r) => r.marca)).size !== 1 ? 's' : ''},{' '}
              {data.registros.length} categoria{data.registros.length !== 1 ? 's' : ''}
            </span>
          </h3>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: '8px' }}>
            {renderMarcaGroup(data.registros)}
          </div>
        </div>
      ))}
    </div>
  );
}


// ── Vista Por Marca ───────────────────────────────────────────────────────────

function VistaPorMarca({ registros, usuarios, onAsignar, onAsignarMasivo }) {
  const [expandida, setExpandida] = useState(null);
  const [pmSeleccionado, setPmSeleccionado] = useState({});
  const [catsSeleccionadas, setCatsSeleccionadas] = useState({});

  // Agrupar por marca
  const porMarca = {};
  registros.forEach((reg) => {
    if (!porMarca[reg.marca]) porMarca[reg.marca] = [];
    porMarca[reg.marca].push(reg);
  });

  const marcasOrdenadas = Object.entries(porMarca).sort(([a], [b]) => a.localeCompare(b));

  const toggleExpand = (marca) => {
    if (expandida === marca) {
      setExpandida(null);
    } else {
      setExpandida(marca);
      // Pre-seleccionar todas las categorías sin PM asignado
      const cats = porMarca[marca];
      const sinAsignar = cats.filter((c) => !c.usuario_id).map((c) => c.categoria);
      setCatsSeleccionadas((prev) => ({ ...prev, [marca]: sinAsignar }));
    }
  };

  const toggleCategoria = (marca, categoria) => {
    setCatsSeleccionadas((prev) => {
      const current = prev[marca] || [];
      const next = current.includes(categoria)
        ? current.filter((c) => c !== categoria)
        : [...current, categoria];
      return { ...prev, [marca]: next };
    });
  };

  const toggleTodasCategorias = (marca) => {
    const cats = porMarca[marca];
    const allCats = cats.map((c) => c.categoria);
    const selected = catsSeleccionadas[marca] || [];
    const allSelected = allCats.length === selected.length;

    setCatsSeleccionadas((prev) => ({
      ...prev,
      [marca]: allSelected ? [] : allCats,
    }));
  };

  const handleAsignarMasivo = (marca) => {
    const cats = catsSeleccionadas[marca] || [];
    const pm = pmSeleccionado[marca];
    if (cats.length === 0) {
      alert('Selecciona al menos una categoria');
      return;
    }
    if (pm === undefined) {
      alert('Selecciona un PM');
      return;
    }
    onAsignarMasivo(marca, cats, pm);
    setExpandida(null);
  };

  // Obtener el PM asignado a una marca (o "Mixto" si hay varios)
  const getPMResumen = (cats) => {
    const pmIds = [...new Set(cats.map((c) => c.usuario_id))];
    if (pmIds.length === 1) {
      if (pmIds[0] === null) return { texto: 'Sin asignar', color: 'var(--text-secondary)' };
      return { texto: cats[0].usuario_nombre, color: 'var(--text-primary)' };
    }
    return { texto: 'Mixto', color: '#f59e0b' };
  };

  return (
    <div style={{ display: 'grid', gap: '4px' }}>
      {marcasOrdenadas.map(([marca, cats]) => {
        const isExpanded = expandida === marca;
        const pm = getPMResumen(cats);

        return (
          <div
            key={marca}
            style={{
              border: '1px solid var(--border-color)',
              borderRadius: '8px',
              overflow: 'hidden',
              background: 'var(--bg-secondary)',
            }}
          >
            {/* Marca Header - clickable */}
            <div
              onClick={() => toggleExpand(marca)}
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                padding: '12px 16px',
                cursor: 'pointer',
                userSelect: 'none',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                <span style={{ fontSize: '12px', color: 'var(--text-secondary)', transition: 'transform 0.2s', transform: isExpanded ? 'rotate(90deg)' : 'none' }}>
                  ▶
                </span>
                <span style={{ fontWeight: '600', fontSize: '15px', color: 'var(--text-primary)' }}>
                  {marca}
                </span>
                <span style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
                  ({cats.length} cat{cats.length !== 1 ? 's' : ''})
                </span>
              </div>
              <span style={{ fontSize: '13px', color: pm.color, fontWeight: '500' }}>
                {pm.texto}
              </span>
            </div>

            {/* Expanded: categorías con checkboxes */}
            {isExpanded && (
              <div style={{ padding: '0 16px 16px', borderTop: '1px solid var(--border-color)' }}>
                {/* Asignación masiva */}
                <div style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '12px',
                  padding: '12px 0',
                  borderBottom: '1px solid var(--border-color)',
                  marginBottom: '8px',
                }}>
                  <button
                    onClick={() => toggleTodasCategorias(marca)}
                    style={{
                      padding: '4px 10px',
                      borderRadius: '4px',
                      border: '1px solid var(--border-color)',
                      background: 'var(--bg-primary)',
                      color: 'var(--text-secondary)',
                      cursor: 'pointer',
                      fontSize: '12px',
                    }}
                  >
                    {(catsSeleccionadas[marca] || []).length === cats.length ? 'Deseleccionar todas' : 'Seleccionar todas'}
                  </button>
                  <select
                    value={pmSeleccionado[marca] ?? ''}
                    onChange={(e) => setPmSeleccionado((prev) => ({ ...prev, [marca]: e.target.value }))}
                    style={{
                      padding: '4px 8px',
                      borderRadius: '4px',
                      border: '1px solid var(--border-color)',
                      fontSize: '13px',
                      background: 'var(--bg-primary)',
                      color: 'var(--text-primary)',
                    }}
                  >
                    <option value="">Sin asignar</option>
                    {usuarios.map((u) => (
                      <option key={u.id} value={u.id}>{u.nombre}</option>
                    ))}
                  </select>
                  <button
                    onClick={() => handleAsignarMasivo(marca)}
                    disabled={(catsSeleccionadas[marca] || []).length === 0}
                    style={{
                      padding: '4px 12px',
                      borderRadius: '4px',
                      border: 'none',
                      background: (catsSeleccionadas[marca] || []).length > 0 ? 'rgba(59,130,246,0.15)' : 'var(--bg-tertiary)',
                      color: (catsSeleccionadas[marca] || []).length > 0 ? '#60a5fa' : 'var(--text-secondary)',
                      cursor: (catsSeleccionadas[marca] || []).length > 0 ? 'pointer' : 'not-allowed',
                      fontSize: '13px',
                      fontWeight: '600',
                    }}
                  >
                    Asignar ({(catsSeleccionadas[marca] || []).length})
                  </button>
                </div>

                {/* Lista de categorías */}
                <div style={{ display: 'grid', gap: '4px' }}>
                  {cats
                    .sort((a, b) => a.categoria.localeCompare(b.categoria))
                    .map((reg) => (
                      <div
                        key={reg.id}
                        style={{
                          display: 'flex',
                          alignItems: 'center',
                          gap: '10px',
                          padding: '6px 8px',
                          borderRadius: '4px',
                          background: (catsSeleccionadas[marca] || []).includes(reg.categoria)
                            ? 'rgba(59,130,246,0.05)'
                            : 'transparent',
                        }}
                      >
                        <input
                          type="checkbox"
                          checked={(catsSeleccionadas[marca] || []).includes(reg.categoria)}
                          onChange={() => toggleCategoria(marca, reg.categoria)}
                          style={{ cursor: 'pointer', accentColor: '#3b82f6' }}
                        />
                        <span style={{ flex: 1, fontSize: '14px', color: 'var(--text-primary)' }}>
                          {reg.categoria}
                        </span>
                        <span style={{ fontSize: '12px', color: reg.usuario_nombre ? 'var(--text-secondary)' : '#f59e0b' }}>
                          {reg.usuario_nombre || 'Sin asignar'}
                        </span>
                        <CambiarPMInline reg={reg} usuarios={usuarios} onAsignar={onAsignar} />
                      </div>
                    ))}
                </div>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}


// ── Componente inline para cambiar PM individual ──────────────────────────────

function CambiarPMInline({ reg, usuarios, onAsignar }) {
  const [editando, setEditando] = useState(false);

  if (editando) {
    return (
      <div style={{ display: 'flex', gap: '4px' }}>
        <select
          defaultValue={reg.usuario_id || ''}
          onChange={(e) => {
            onAsignar(reg.id, e.target.value);
            setEditando(false);
          }}
          autoFocus
          style={{
            padding: '2px 6px',
            borderRadius: '4px',
            border: '1px solid var(--border-color)',
            fontSize: '11px',
            background: 'var(--bg-primary)',
            color: 'var(--text-primary)',
          }}
        >
          <option value="">Sin asignar</option>
          {usuarios.map((u) => (
            <option key={u.id} value={u.id}>{u.nombre}</option>
          ))}
        </select>
        <button
          onClick={() => setEditando(false)}
          style={{
            padding: '2px 6px',
            background: '#ef4444',
            color: 'white',
            border: 'none',
            borderRadius: '4px',
            cursor: 'pointer',
            fontSize: '10px',
          }}
        >
          X
        </button>
      </div>
    );
  }

  return (
    <button
      onClick={() => setEditando(true)}
      style={{
        padding: '2px 8px',
        background: 'var(--bg-tertiary)',
        color: 'var(--text-secondary)',
        border: '1px solid var(--border-color)',
        borderRadius: '4px',
        cursor: 'pointer',
        fontSize: '11px',
      }}
    >
      Cambiar
    </button>
  );
}
