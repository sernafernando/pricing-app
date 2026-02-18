import { useState, useEffect, useMemo } from 'react';
import { Search, Plus, Check, X, Layers, Tag, EyeOff, Eye } from 'lucide-react';
import api from '../services/api';
import styles from './PanelSubcategorias.module.css';

export default function PanelSubcategorias() {
  // Data
  const [subcategorias, setSubcategorias] = useState([]);
  const [grupos, setGrupos] = useState([]);
  const [categorias, setCategorias] = useState([]);
  const [comisionesBase, setComisionesBase] = useState({});

  // Filtros
  const [busqueda, setBusqueda] = useState('');
  const [filtroCategoria, setFiltroCategoria] = useState('');
  const [filtroGrupo, setFiltroGrupo] = useState('');
  const [verOcultas, setVerOcultas] = useState(false);

  // Selección masiva
  const [seleccionadas, setSeleccionadas] = useState(new Set());

  // UI
  const [cargando, setCargando] = useState(false);
  const [mensaje, setMensaje] = useState(null);
  const [mostrarNuevoGrupo, setMostrarNuevoGrupo] = useState(false);
  const [nuevoGrupoNombre, setNuevoGrupoNombre] = useState('');
  const [nuevoGrupoDesc, setNuevoGrupoDesc] = useState('');
  const [guardandoGrupo, setGuardandoGrupo] = useState(false);

  useEffect(() => {
    cargarDatos();
  }, [verOcultas]);

  // Auto-limpiar mensajes
  useEffect(() => {
    if (mensaje) {
      const timer = setTimeout(() => setMensaje(null), 4000);
      return () => clearTimeout(timer);
    }
  }, [mensaje]);

  const cargarDatos = async () => {
    setCargando(true);
    try {
      const [subcatRes, gruposRes, catsRes, comisionesRes] = await Promise.all([
        api.get('/admin/subcategorias-grupos', { params: { incluir_ocultas: verOcultas } }),
        api.get('/admin/grupos-comision'),
        api.get('/admin/subcategorias-categorias'),
        api.get('/comisiones/vigente').catch(() => null),
      ]);
      setSubcategorias(subcatRes.data);
      setGrupos(gruposRes.data);
      setCategorias(catsRes.data.categorias);

      // Mapear grupo_id -> comision_base %
      if (comisionesRes?.data?.comisiones_base) {
        const mapa = {};
        for (const cb of comisionesRes.data.comisiones_base) {
          mapa[cb.grupo_id] = cb.comision_base;
        }
        setComisionesBase(mapa);
      }
    } catch (error) {
      console.error('Error cargando datos:', error);
      setMensaje({ tipo: 'error', texto: 'Error al cargar datos' });
    } finally {
      setCargando(false);
    }
  };

  // Filtrado
  const subcategoriasFiltradas = useMemo(() => {
    let resultado = subcategorias;

    if (busqueda) {
      const patron = busqueda.toLowerCase();
      resultado = resultado.filter(
        (s) =>
          (s.nombre_subcategoria || '').toLowerCase().includes(patron) ||
          (s.nombre_categoria || '').toLowerCase().includes(patron) ||
          String(s.subcat_id).includes(patron)
      );
    }

    if (filtroCategoria) {
      resultado = resultado.filter((s) => s.cat_id === filtroCategoria);
    }

    if (filtroGrupo === 'sin_grupo') {
      resultado = resultado.filter((s) => s.grupo_id === null);
    } else if (filtroGrupo) {
      resultado = resultado.filter((s) => s.grupo_id === Number(filtroGrupo));
    }

    return resultado;
  }, [subcategorias, busqueda, filtroCategoria, filtroGrupo]);

  // Stats
  const stats = useMemo(() => {
    const total = subcategorias.length;
    const sinGrupo = subcategorias.filter((s) => s.grupo_id === null).length;
    const conGrupo = total - sinGrupo;
    const ocultas = subcategorias.filter((s) => s.oculta).length;
    return { total, sinGrupo, conGrupo, ocultas };
  }, [subcategorias]);

  // Selección
  const toggleSeleccion = (subcatId) => {
    setSeleccionadas((prev) => {
      const next = new Set(prev);
      if (next.has(subcatId)) {
        next.delete(subcatId);
      } else {
        next.add(subcatId);
      }
      return next;
    });
  };

  const seleccionarTodas = () => {
    const ids = subcategoriasFiltradas.map((s) => s.subcat_id);
    if (seleccionadas.size === ids.length && ids.every((id) => seleccionadas.has(id))) {
      setSeleccionadas(new Set());
    } else {
      setSeleccionadas(new Set(ids));
    }
  };

  // Asignar grupo individual
  const asignarGrupoIndividual = async (subcatId, grupoId) => {
    try {
      await api.patch('/admin/subcategorias-grupos/asignar', {
        subcat_ids: [subcatId],
        grupo_id: grupoId === '' ? null : Number(grupoId),
      });

      setSubcategorias((prev) =>
        prev.map((s) =>
          s.subcat_id === subcatId
            ? { ...s, grupo_id: grupoId === '' ? null : Number(grupoId) }
            : s
        )
      );

      setMensaje({ tipo: 'exito', texto: 'Grupo asignado correctamente' });
      // Refrescar conteos de grupos
      const gruposRes = await api.get('/admin/grupos-comision');
      setGrupos(gruposRes.data);
    } catch (error) {
      console.error('Error asignando grupo:', error);
      setMensaje({
        tipo: 'error',
        texto: error.response?.data?.detail || 'Error al asignar grupo',
      });
    }
  };

  // Asignar grupo masivo
  const asignarGrupoMasivo = async (grupoId) => {
    if (seleccionadas.size === 0) return;

    try {
      const subcatIds = Array.from(seleccionadas);
      await api.patch('/admin/subcategorias-grupos/asignar', {
        subcat_ids: subcatIds,
        grupo_id: grupoId === '' ? null : Number(grupoId),
      });

      setSubcategorias((prev) =>
        prev.map((s) =>
          seleccionadas.has(s.subcat_id)
            ? { ...s, grupo_id: grupoId === '' ? null : Number(grupoId) }
            : s
        )
      );

      setMensaje({
        tipo: 'exito',
        texto: `${subcatIds.length} subcategoría(s) actualizada(s)`,
      });
      setSeleccionadas(new Set());

      const gruposRes = await api.get('/admin/grupos-comision');
      setGrupos(gruposRes.data);
    } catch (error) {
      console.error('Error asignando grupo masivo:', error);
      setMensaje({
        tipo: 'error',
        texto: error.response?.data?.detail || 'Error al asignar grupo',
      });
    }
  };

  // Ocultar/mostrar subcategorías (banlist)
  const toggleOcultar = async (subcatIds, ocultar) => {
    try {
      await api.patch('/admin/subcategorias-grupos/banlist', {
        subcat_ids: subcatIds,
        oculta: ocultar,
      });

      if (verOcultas) {
        // Si estamos viendo ocultas, actualizar el flag en el state
        setSubcategorias((prev) =>
          prev.map((s) =>
            subcatIds.includes(s.subcat_id) ? { ...s, oculta: ocultar } : s
          )
        );
      } else {
        // Si no estamos viendo ocultas, sacarlas del array
        setSubcategorias((prev) =>
          prev.filter((s) => !subcatIds.includes(s.subcat_id))
        );
      }

      setSeleccionadas(new Set());
      const accion = ocultar ? 'oculta(s)' : 'restaurada(s)';
      setMensaje({ tipo: 'exito', texto: `${subcatIds.length} subcategoría(s) ${accion}` });

      // Refrescar conteos de grupos
      const gruposRes = await api.get('/admin/grupos-comision');
      setGrupos(gruposRes.data);
    } catch (error) {
      console.error('Error en banlist:', error);
      setMensaje({
        tipo: 'error',
        texto: error.response?.data?.detail || 'Error al actualizar banlist',
      });
    }
  };

  // Crear grupo
  const crearGrupo = async () => {
    if (!nuevoGrupoNombre.trim()) return;

    setGuardandoGrupo(true);
    try {
      await api.post('/admin/grupos-comision', {
        nombre: nuevoGrupoNombre.trim(),
        descripcion: nuevoGrupoDesc.trim() || null,
      });

      setMensaje({ tipo: 'exito', texto: `Grupo "${nuevoGrupoNombre}" creado` });
      setNuevoGrupoNombre('');
      setNuevoGrupoDesc('');
      setMostrarNuevoGrupo(false);

      const gruposRes = await api.get('/admin/grupos-comision');
      setGrupos(gruposRes.data);
    } catch (error) {
      console.error('Error creando grupo:', error);
      setMensaje({
        tipo: 'error',
        texto: error.response?.data?.detail || 'Error al crear grupo',
      });
    } finally {
      setGuardandoGrupo(false);
    }
  };

  const todasSeleccionadas =
    subcategoriasFiltradas.length > 0 &&
    subcategoriasFiltradas.every((s) => seleccionadas.has(s.subcat_id));

  if (cargando && subcategorias.length === 0) {
    return <div className={styles.loading}>Cargando subcategorías...</div>;
  }

  return (
    <div className={styles.container}>
      {/* Header */}
      <div className={styles.header}>
        <h2>Subcategorías y Grupos de Comisión</h2>
        <div className={styles.headerActions}>
          <button
            className={`btn-tesla outline-subtle-warning sm ${verOcultas ? 'toggle-active-warning' : ''}`}
            onClick={() => setVerOcultas(!verOcultas)}
          >
            {verOcultas ? <Eye size={14} /> : <EyeOff size={14} />}
            {verOcultas ? 'Viendo ocultas' : 'Ver ocultas'}
          </button>
          <button
            className="btn-tesla outline-subtle-primary sm"
            onClick={() => setMostrarNuevoGrupo(!mostrarNuevoGrupo)}
          >
            <Plus size={14} /> Nuevo Grupo
          </button>
        </div>
      </div>

      {/* Mensaje */}
      {mensaje && (
        <div
          className={`${styles.mensaje} ${
            mensaje.tipo === 'exito' ? styles.mensajeExito : styles.mensajeError
          }`}
        >
          {mensaje.tipo === 'exito' ? <Check size={14} /> : <X size={14} />}{' '}
          {mensaje.texto}
        </div>
      )}

      {/* Sección Grupos */}
      <div className={styles.gruposSection}>
        <h3><Layers size={18} /> Grupos de Comisión</h3>
        <div className={styles.gruposGrid}>
          {grupos.map((g) => (
            <div
              key={g.id}
              className={`${styles.grupoCard} ${!g.activo ? styles.grupoCardInactivo : ''}`}
            >
              <div className={styles.grupoCardHeader}>
                <span className={styles.grupoCardNombre}>G{g.id} - {g.nombre}</span>
                <span className={styles.grupoCardCount}>
                  {g.cantidad_subcategorias} subcats
                </span>
              </div>
              <p className={styles.grupoCardDesc}>
                {comisionesBase[g.id] != null
                  ? `${comisionesBase[g.id].toFixed(2)}% comisión base`
                  : g.descripcion || 'Sin comisión asignada'}
              </p>
            </div>
          ))}

          {/* Form nuevo grupo inline */}
          {mostrarNuevoGrupo && (
            <div className={styles.nuevoGrupoForm}>
              <input
                type="text"
                placeholder="Nombre del grupo"
                value={nuevoGrupoNombre}
                onChange={(e) => setNuevoGrupoNombre(e.target.value)}
                className={styles.nuevoGrupoInput}
                autoFocus
                onKeyDown={(e) => {
                  if (e.key === 'Enter') crearGrupo();
                  if (e.key === 'Escape') setMostrarNuevoGrupo(false);
                }}
              />
              <input
                type="text"
                placeholder="Descripción (opcional)"
                value={nuevoGrupoDesc}
                onChange={(e) => setNuevoGrupoDesc(e.target.value)}
                className={styles.nuevoGrupoInput}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') crearGrupo();
                  if (e.key === 'Escape') setMostrarNuevoGrupo(false);
                }}
              />
              <button
                className="btn-tesla outline-subtle-success xs"
                onClick={crearGrupo}
                disabled={guardandoGrupo || !nuevoGrupoNombre.trim()}
              >
                <Check size={14} />
              </button>
              <button
                className="btn-tesla outline-subtle-danger xs"
                onClick={() => {
                  setMostrarNuevoGrupo(false);
                  setNuevoGrupoNombre('');
                  setNuevoGrupoDesc('');
                }}
              >
                <X size={14} />
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Stats */}
      <div className={styles.stats}>
        <div className={styles.stat}>
          Total: <strong>{stats.total}</strong>
        </div>
        <div className={styles.stat}>
          Asignadas: <strong>{stats.conGrupo}</strong>
        </div>
        <div className={styles.stat}>
          Sin grupo: <strong>{stats.sinGrupo}</strong>
        </div>
        <div className={styles.stat}>
          Mostrando: <strong>{subcategoriasFiltradas.length}</strong>
        </div>
      </div>

      {/* Filtros */}
      <div className={styles.filtros}>
        <div style={{ position: 'relative', flex: 1, minWidth: '200px', maxWidth: '400px' }}>
          <Search
            size={16}
            style={{
              position: 'absolute',
              left: '10px',
              top: '50%',
              transform: 'translateY(-50%)',
              color: 'var(--text-secondary)',
            }}
          />
          <input
            type="text"
            placeholder="Buscar subcategoría o categoría..."
            value={busqueda}
            onChange={(e) => setBusqueda(e.target.value)}
            className={styles.filtroInput}
            style={{ paddingLeft: '32px' }}
          />
        </div>

        <select
          value={filtroCategoria}
          onChange={(e) => setFiltroCategoria(e.target.value)}
          className={styles.filtroSelect}
        >
          <option value="">Todas las categorías</option>
          {categorias.map((c) => (
            <option key={c.cat_id} value={c.cat_id}>
              {c.nombre}
            </option>
          ))}
        </select>

        <select
          value={filtroGrupo}
          onChange={(e) => setFiltroGrupo(e.target.value)}
          className={styles.filtroSelect}
        >
          <option value="">Todos los grupos</option>
          <option value="sin_grupo">Sin grupo asignado</option>
          {grupos.map((g) => (
            <option key={g.id} value={g.id}>
              G{g.id} - {g.nombre}
            </option>
          ))}
        </select>
      </div>

      {/* Barra de acciones masivas */}
      {seleccionadas.size > 0 && (
        <div className={styles.bulkBar}>
          <span className={styles.bulkCount}>{seleccionadas.size}</span> seleccionada(s)
          <Tag size={14} />
          <span>Asignar a:</span>
          <select
            className={styles.bulkSelect}
            onChange={(e) => asignarGrupoMasivo(e.target.value)}
            defaultValue=""
          >
            <option value="" disabled>
              Seleccionar grupo...
            </option>
            <option value="">Sin grupo</option>
            {grupos.map((g) => (
              <option key={g.id} value={g.id}>
                G{g.id} - {g.nombre}
              </option>
            ))}
          </select>
          <button
            className="btn-tesla outline-subtle-warning xs"
            onClick={() => toggleOcultar(Array.from(seleccionadas), true)}
          >
            <EyeOff size={14} /> Ocultar
          </button>
          {verOcultas && (
            <button
              className="btn-tesla outline-subtle-success xs"
              onClick={() => toggleOcultar(Array.from(seleccionadas), false)}
            >
              <Eye size={14} /> Restaurar
            </button>
          )}
          <button
            className="btn-tesla outline-subtle-danger xs"
            onClick={() => setSeleccionadas(new Set())}
          >
            <X size={14} /> Limpiar
          </button>
        </div>
      )}

      {/* Tabla */}
      <div className="table-container-tesla">
        <table className="table-tesla">
          <thead className="table-tesla-head">
            <tr>
              <th className={styles.checkboxCell}>
                <input
                  type="checkbox"
                  checked={todasSeleccionadas}
                  onChange={seleccionarTodas}
                  aria-label="Seleccionar todas las subcategorías"
                />
              </th>
              <th>ID</th>
              <th>Subcategoría</th>
              <th>Categoría</th>
              <th>Grupo</th>
              <th style={{ width: '60px' }}></th>
            </tr>
          </thead>
          <tbody className="table-tesla-body">
            {subcategoriasFiltradas.map((s) => (
              <tr key={s.subcat_id} className={s.oculta ? styles.filaOculta : ''}>
                <td className={styles.checkboxCell}>
                  <input
                    type="checkbox"
                    checked={seleccionadas.has(s.subcat_id)}
                    onChange={() => toggleSeleccion(s.subcat_id)}
                    aria-label={`Seleccionar ${s.nombre_subcategoria || s.subcat_id}`}
                  />
                </td>
                <td>{s.subcat_id}</td>
                <td>{s.nombre_subcategoria || '—'}</td>
                <td>
                  <span className={styles.categoriaText}>
                    {s.nombre_categoria || '—'}
                  </span>
                </td>
                <td>
                  <select
                    value={s.grupo_id ?? ''}
                    onChange={(e) =>
                      asignarGrupoIndividual(s.subcat_id, e.target.value)
                    }
                    className={styles.grupoSelectInline}
                  >
                    <option value="">Sin grupo</option>
                    {grupos.map((g) => (
                      <option key={g.id} value={g.id}>
                        G{g.id} - {g.nombre}
                      </option>
                    ))}
                  </select>
                </td>
                <td>
                  {s.oculta ? (
                    <button
                      className="btn-tesla outline-subtle-success icon-only xs"
                      onClick={() => toggleOcultar([s.subcat_id], false)}
                      aria-label="Restaurar subcategoría"
                      title="Restaurar"
                    >
                      <Eye size={14} />
                    </button>
                  ) : (
                    <button
                      className="btn-tesla outline-subtle-warning icon-only xs"
                      onClick={() => toggleOcultar([s.subcat_id], true)}
                      aria-label="Ocultar subcategoría"
                      title="Ocultar"
                    >
                      <EyeOff size={14} />
                    </button>
                  )}
                </td>
              </tr>
            ))}
            {subcategoriasFiltradas.length === 0 && (
              <tr>
                <td colSpan={6} style={{ textAlign: 'center', padding: '32px', color: 'var(--text-secondary)' }}>
                  No se encontraron subcategorías con los filtros aplicados
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
