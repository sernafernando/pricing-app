import { useState, useEffect } from 'react';
import { useDebounce } from '../hooks/useDebounce';
import { useQueryFilters } from '../hooks/useQueryFilters';
import { usePermisos } from '../contexts/PermisosContext';
import api from '../services/api';
import ModalRma from '../components/ModalRma';
import RmaAdminOpciones from '../components/RmaAdminOpciones';
import { Plus, Search, RotateCcw, ChevronLeft, ChevronRight, Settings } from 'lucide-react';
import styles from './Rma.module.css';

export default function Rma() {
  const { tienePermiso } = usePermisos();
  const puedeGestionar = tienePermiso('rma.gestionar');
  const puedeAdminOpciones = tienePermiso('rma.admin_opciones');

  const [casos, setCasos] = useState([]);
  const [loading, setLoading] = useState(true);
  const [totalItems, setTotalItems] = useState(0);
  const [totalPages, setTotalPages] = useState(0);
  const [stats, setStats] = useState(null);

  const { getFilter, updateFilters } = useQueryFilters(
    { search: '', page: 1, page_size: 50, estado: '' },
    { page: 'number', page_size: 'number' }
  );

  const search = getFilter('search');
  const page = getFilter('page');
  const estado = getFilter('estado');
  const debouncedSearch = useDebounce(search, 500);

  const [modalOpen, setModalOpen] = useState(false);
  const [casoSeleccionado, setCasoSeleccionado] = useState(null);
  const [showAdmin, setShowAdmin] = useState(false);

  useEffect(() => {
    cargarCasos();
  }, [page, debouncedSearch, estado]);

  useEffect(() => {
    cargarStats();
  }, []);

  const cargarCasos = async () => {
    setLoading(true);
    try {
      const params = { page, page_size: 50 };
      if (debouncedSearch) params.search = debouncedSearch;
      if (estado) params.estado = estado;
      const { data } = await api.get('/rma-seguimiento', { params });
      setCasos(data.items);
      setTotalItems(data.total);
      setTotalPages(data.total_pages);
    } catch {
      setCasos([]);
    } finally {
      setLoading(false);
    }
  };

  const cargarStats = async () => {
    try {
      const { data } = await api.get('/rma-seguimiento/stats/resumen');
      setStats(data);
    } catch {
      // stats opcionales
    }
  };

  const handleNuevo = () => {
    setCasoSeleccionado(null);
    setModalOpen(true);
  };

  const handleEditar = (caso) => {
    setCasoSeleccionado(caso);
    setModalOpen(true);
  };

  const handleModalClose = (updated) => {
    setModalOpen(false);
    setCasoSeleccionado(null);
    if (updated) {
      cargarCasos();
      cargarStats();
    }
  };

  return (
    <div className={styles.container}>
      {/* Header */}
      <div className={styles.header}>
        <div className={styles.headerLeft}>
          <RotateCcw size={24} />
          <h1>RMA Seguimiento</h1>
          {stats && (
            <div className={styles.statsChips}>
              <span className={styles.chipAbiertos}>{stats.abiertos} abiertos</span>
              <span className={styles.chipTotal}>{stats.total} total</span>
            </div>
          )}
        </div>
        <div style={{ display: 'flex', gap: '8px' }}>
          {puedeAdminOpciones && (
            <button
              className={`btn-tesla ${showAdmin ? 'primary' : 'ghost'} sm`}
              onClick={() => setShowAdmin(!showAdmin)}
              title="Gestionar opciones de dropdowns"
              aria-label="Gestionar opciones de dropdowns"
            >
              <Settings size={16} />
            </button>
          )}
          {puedeGestionar && (
            <button className="btn-tesla outline-subtle-primary" onClick={handleNuevo}>
              <Plus size={16} /> Nuevo Caso
            </button>
          )}
        </div>
      </div>

      {/* Filtros */}
      <div className={styles.filtros}>
        <div className={styles.searchBox}>
          <Search size={16} />
          <input
            type="text"
            placeholder="Buscar por caso, cliente, ML ID, serie..."
            value={search}
            onChange={(e) => updateFilters({ search: e.target.value, page: 1 })}
          />
        </div>
        <select
          value={estado}
          onChange={(e) => updateFilters({ estado: e.target.value, page: 1 })}
          className={styles.selectFiltro}
        >
          <option value="">Todos los estados</option>
          <option value="abierto">Abiertos</option>
          <option value="cerrado">Cerrados</option>
          <option value="en_espera">En espera</option>
        </select>
      </div>

      {/* Admin Panel */}
      {showAdmin && puedeAdminOpciones && (
        <div className={styles.adminPanel}>
          <RmaAdminOpciones />
        </div>
      )}

      {/* Tabla */}
      <div className="table-container-tesla">
        <table className="table-tesla striped">
          <thead className="table-tesla-head">
            <tr>
              <th>Caso</th>
              <th>Fecha</th>
              <th>Cliente</th>
              <th>ML ID</th>
              <th>Items</th>
              <th>Estado</th>
              <th>Reclamo ML</th>
              <th>Observaciones</th>
            </tr>
          </thead>
          <tbody className="table-tesla-body">
            {loading ? (
              <tr><td colSpan={8} className={styles.loadingCell}>Cargando...</td></tr>
            ) : casos.length === 0 ? (
              <tr><td colSpan={8} className={styles.emptyCell}>No se encontraron casos RMA</td></tr>
            ) : (
              casos.map((caso) => (
                <tr key={caso.id} onClick={() => handleEditar(caso)} className={styles.clickableRow}>
                  <td className={styles.cellCaso}>{caso.numero_caso}</td>
                  <td>{caso.fecha_caso || '—'}</td>
                  <td>
                    <div className={styles.clienteCell}>
                      <span className={styles.clienteNombre}>{caso.cliente_nombre || '—'}</span>
                      {caso.cliente_numero && (
                        <span className={styles.clienteNumero}>#{caso.cliente_numero}</span>
                      )}
                    </div>
                  </td>
                  <td className={styles.cellMono}>{caso.ml_id || '—'}</td>
                  <td className={styles.cellCenter}>{caso.total_items}</td>
                  <td>
                    <span className={`${styles.badge} ${styles[`badge_${caso.estado}`] || ''}`}>
                      {caso.estado}
                    </span>
                  </td>
                  <td>
                    {caso.estado_reclamo_ml_valor ? (
                      <span
                        className={styles.badgeOpcion}
                        style={{ '--badge-color': `var(--color-${caso.estado_reclamo_ml_color || 'gray'})` }}
                      >
                        {caso.estado_reclamo_ml_valor}
                      </span>
                    ) : '—'}
                  </td>
                  <td className={styles.cellObs}>
                    {caso.observaciones ? caso.observaciones.substring(0, 60) + (caso.observaciones.length > 60 ? '...' : '') : '—'}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Paginación */}
      {totalPages > 1 && (
        <div className={styles.pagination}>
          <button
            className="btn-tesla ghost sm"
            disabled={page <= 1}
            onClick={() => updateFilters({ page: page - 1 })}
          >
            <ChevronLeft size={16} />
          </button>
          <span className={styles.pageInfo}>
            Página {page} de {totalPages} ({totalItems} casos)
          </span>
          <button
            className="btn-tesla ghost sm"
            disabled={page >= totalPages}
            onClick={() => updateFilters({ page: page + 1 })}
          >
            <ChevronRight size={16} />
          </button>
        </div>
      )}

      {/* Modal */}
      {modalOpen && (
        <ModalRma
          caso={casoSeleccionado}
          onClose={handleModalClose}
        />
      )}
    </div>
  );
}
