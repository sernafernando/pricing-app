import { useState, useEffect, useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';

import { useSSEChannel } from '../hooks/useSSEChannel';
import { ticketsAPI, sectoresAPI } from '../services/api';
import {
  Ticket,
  Plus,
  RotateCcw,
  ChevronLeft,
  ChevronRight,
  Table2,
  Columns3,
  AlarmClock,
} from 'lucide-react';
import SearchInput from '../components/SearchInput';
import TicketCreateModal from '../components/TicketCreateModal';
import TicketDetail from '../components/TicketDetail';
import TicketsBoard from '../components/TicketsBoard';
import styles from './Tickets.module.css';

// One flat segmented control — Tabla | Tablero por estado | Tablero por
// urgencia. Deliberately NOT nested (a table/board toggle with a second
// grouping selector inside): the inner selector only ever had two values,
// so nesting bought nothing and cost a mode (see design's rationale).
const VISTAS = ['tabla', 'estado', 'urgencia'];
const VISTA_STORAGE_KEY = 'tickets:vista';
const VISTA_OPTIONS = [
  { value: 'tabla', label: 'Tabla', Icon: Table2 },
  { value: 'estado', label: 'Tablero por estado', Icon: Columns3 },
  { value: 'urgencia', label: 'Tablero por urgencia', Icon: AlarmClock },
];

const PRIORIDADES = [
  { value: '', label: 'Todas' },
  { value: 'baja', label: 'Baja' },
  { value: 'media', label: 'Media' },
  { value: 'alta', label: 'Alta' },
  { value: 'critica', label: 'Crítica' },
];

const ESTADOS_CERRADO = [
  { value: '', label: 'Todos' },
  { value: 'false', label: 'Abiertos' },
  { value: 'true', label: 'Cerrados' },
];

const PRIORIDAD_CLASS = {
  baja: 'prioridadBaja',
  media: 'prioridadMedia',
  alta: 'prioridadAlta',
  critica: 'prioridadCritica',
};

const PAGE_SIZE = 50;

const formatDate = (dateStr) => {
  if (!dateStr) return '-';
  const d = new Date(dateStr);
  return d.toLocaleDateString('es-AR', {
    day: '2-digit',
    month: '2-digit',
    year: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
};

export default function Tickets() {
  // Cualquier usuario logueado puede crear tickets
  const puedeCrear = true;

  // Data
  const [tickets, setTickets] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [sectores, setSectores] = useState([]);

  // Filters
  const [page, setPage] = useState(1);
  const [sectorId, setSectorId] = useState('');
  const [prioridad, setPrioridad] = useState('');
  const [estaCerrado, setEstaCerrado] = useState('');
  const [search, setSearch] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');

  // Detail & create modal
  const [selectedTicketId, setSelectedTicketId] = useState(null);
  const [createModalOpen, setCreateModalOpen] = useState(false);

  // View state — URL (?vista=) is the source of truth, linkable and
  // reload-safe; localStorage is only the fresh-visit fallback default.
  const [searchParams, setSearchParams] = useSearchParams();
  const vistaParam = searchParams.get('vista');
  const vistaGuardada = localStorage.getItem(VISTA_STORAGE_KEY);
  const vista = VISTAS.includes(vistaParam)
    ? vistaParam
    : VISTAS.includes(vistaGuardada)
      ? vistaGuardada
      : 'tabla';

  const handleVistaChange = (nuevaVista) => {
    localStorage.setItem(VISTA_STORAGE_KEY, nuevaVista);
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      next.set('vista', nuevaVista);
      return next;
    });
  };

  // Debounce search
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedSearch(search), 400);
    return () => clearTimeout(timer);
  }, [search]);

  // Reset page on filter change
  useEffect(() => {
    setPage(1);
  }, [debouncedSearch, sectorId, prioridad, estaCerrado]);

  // Load sectores for filter dropdown
  useEffect(() => {
    const fetchSectores = async () => {
      try {
        const { data } = await sectoresAPI.listar();
        setSectores(Array.isArray(data) ? data : []);
      } catch {
        setSectores([]);
      }
    };
    fetchSectores();
  }, []);

  // Load tickets
  const cargarTickets = useCallback(async () => {
    setLoading(true);
    try {
      const params = { page, page_size: PAGE_SIZE };
      if (sectorId) params.sector_id = sectorId;
      if (prioridad) params.prioridad = prioridad;
      if (estaCerrado !== '') params.esta_cerrado = estaCerrado;
      if (debouncedSearch) params.busqueda = debouncedSearch;
      const { data } = await ticketsAPI.listar(params);
      setTickets(data.items || []);
      setTotal(data.total || 0);
    } catch {
      setTickets([]);
      setTotal(0);
    } finally {
      setLoading(false);
    }
  }, [page, sectorId, prioridad, estaCerrado, debouncedSearch]);

  useEffect(() => {
    cargarTickets();
  }, [cargarTickets]);

  // SSE subscription
  useSSEChannel('tickets:changed', () => cargarTickets());

  const totalPages = Math.ceil(total / PAGE_SIZE);

  const handleClearFilters = () => {
    setSearch('');
    setSectorId('');
    setPrioridad('');
    setEstaCerrado('');
    setPage(1);
  };

  const handleRowClick = (ticketId) => {
    setSelectedTicketId(ticketId);
  };

  const handleTicketCreated = () => {
    setCreateModalOpen(false);
    cargarTickets();
  };

  const handleTicketChanged = () => {
    cargarTickets();
  };

  const getStatusStyle = (estado) => {
    const color = estado?.color || '#6b7280';
    return {
      background: `${color}20`,
      color,
    };
  };

  const getSectorStyle = (sector) => {
    const color = sector?.color || '#3b82f6';
    return {
      background: `${color}15`,
      color,
    };
  };

  return (
    <div className={styles.container}>
      {/* Header */}
      <div className={styles.header}>
        <div className={styles.headerTitle}>
          <Ticket size={24} />
          <h1>Tickets</h1>
          <span className={styles.badge}>{total}</span>
        </div>
        <div className={styles.headerActions}>
          <div className={styles.viewSwitch} role="tablist">
            {VISTA_OPTIONS.map((opt) => {
              const Icon = opt.Icon;
              return (
                <button
                  key={opt.value}
                  type="button"
                  role="tab"
                  aria-selected={vista === opt.value}
                  className={`${styles.viewSwitchBtn} ${vista === opt.value ? styles.viewSwitchBtnActive : ''}`}
                  onClick={() => handleVistaChange(opt.value)}
                >
                  <Icon size={14} />
                  {opt.label}
                </button>
              );
            })}
          </div>
          {puedeCrear && (
            <button
              className={styles.btnCreate}
              onClick={() => setCreateModalOpen(true)}
            >
              <Plus size={16} />
              Nuevo Ticket
            </button>
          )}
        </div>
      </div>

      {/* Filters — table view only; the board endpoint has no matching
          filter params (agrupacion + items_por_columna only). */}
      {vista === 'tabla' && (
      <div className={styles.filters}>
        <SearchInput
          value={search}
          onChange={setSearch}
          placeholder="Buscar por título..."
          className={styles.searchBox}
        />
        <select
          value={sectorId}
          onChange={(e) => setSectorId(e.target.value)}
          className={styles.filterSelect}
        >
          <option value="">Todos los sectores</option>
          {sectores.map((s) => (
            <option key={s.id} value={s.id}>
              {s.nombre}
            </option>
          ))}
        </select>
        <select
          value={estaCerrado}
          onChange={(e) => setEstaCerrado(e.target.value)}
          className={styles.filterSelect}
        >
          {ESTADOS_CERRADO.map((e) => (
            <option key={e.value} value={e.value}>
              {e.label}
            </option>
          ))}
        </select>
        <select
          value={prioridad}
          onChange={(e) => setPrioridad(e.target.value)}
          className={styles.filterSelect}
        >
          {PRIORIDADES.map((p) => (
            <option key={p.value} value={p.value}>
              {p.label}
            </option>
          ))}
        </select>
        <button
          className={styles.btnRefresh}
          onClick={handleClearFilters}
          title="Limpiar filtros"
        >
          <RotateCcw size={16} />
        </button>
      </div>
      )}

      {/* Layout: list + detail */}
      <div className={styles.layout}>
        <div className={styles.listPanel}>
          {vista !== 'tabla' ? (
            <TicketsBoard agrupacion={vista} onCardClick={handleRowClick} />
          ) : (
            <>
          {/* Table */}
          <div className={styles.tableWrapper}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Título</th>
                  <th>Sector</th>
                  <th>Estado</th>
                  <th>Prioridad</th>
                  <th>Asignado</th>
                  <th>Creador</th>
                  <th>Fecha</th>
                </tr>
              </thead>
              <tbody>
                {loading ? (
                  <tr>
                    <td colSpan={8} className={styles.loadingCell}>
                      Cargando...
                    </td>
                  </tr>
                ) : tickets.length === 0 ? (
                  <tr>
                    <td colSpan={8} className={styles.emptyCell}>
                      No se encontraron tickets
                    </td>
                  </tr>
                ) : (
                  tickets.map((t) => (
                    <tr
                      key={t.id}
                      className={`${styles.row} ${selectedTicketId === t.id ? styles.rowSelected : ''}`}
                      onClick={() => handleRowClick(t.id)}
                    >
                      <td className={styles.ticketId}>#{t.id}</td>
                      <td className={styles.titleCell}>{t.titulo}</td>
                      <td>
                        <span
                          className={styles.sectorBadge}
                          style={getSectorStyle(t.sector)}
                        >
                          {t.sector?.nombre || '-'}
                        </span>
                      </td>
                      <td>
                        <span
                          className={styles.statusBadge}
                          style={getStatusStyle(t.estado)}
                        >
                          {t.estado?.nombre || '-'}
                        </span>
                      </td>
                      <td>
                        <span className={styles[PRIORIDAD_CLASS[t.prioridad]] || ''}>
                          {t.prioridad}
                        </span>
                      </td>
                      <td className={styles.userCell}>
                        {t.asignado_a?.nombre || '-'}
                      </td>
                      <td className={styles.userCell}>
                        {t.creador?.nombre || '-'}
                      </td>
                      <td className={styles.dateCell}>
                        {formatDate(t.created_at)}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          {totalPages > 1 && (
            <div className={styles.pagination}>
              <button
                disabled={page <= 1}
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                className={styles.btnPage}
              >
                <ChevronLeft size={16} />
              </button>
              <span className={styles.pageInfo}>
                {page} / {totalPages}
              </span>
              <button
                disabled={page >= totalPages}
                onClick={() => setPage((p) => p + 1)}
                className={styles.btnPage}
              >
                <ChevronRight size={16} />
              </button>
            </div>
          )}
            </>
          )}
        </div>

        {/* Detail Panel */}
        {selectedTicketId && (
          <div className={styles.detailPanel}>
            <TicketDetail
              ticketId={selectedTicketId}
              onClose={() => setSelectedTicketId(null)}
              onTicketChanged={handleTicketChanged}
            />
          </div>
        )}
      </div>

      {/* Create Modal */}
      {createModalOpen && (
        <TicketCreateModal
          isOpen={createModalOpen}
          onClose={() => setCreateModalOpen(false)}
          onCreated={handleTicketCreated}
        />
      )}
    </div>
  );
}
