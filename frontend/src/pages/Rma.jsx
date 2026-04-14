import { useState, useEffect, useCallback, useRef } from 'react';
import { useDebounce } from '../hooks/useDebounce';
import { useQueryFilters } from '../hooks/useQueryFilters';
import { usePermisos } from '../contexts/PermisosContext';
import { useToast } from '../hooks/useToast';
import api from '../services/api';
import ModalRma from '../components/ModalRma';
import RmaAdminOpciones from '../components/RmaAdminOpciones';
import RmaProveedores from '../components/RmaProveedores';
import RmaEnviosProveedor from '../components/RmaEnviosProveedor';
import RmaEnviosCliente from '../components/RmaEnviosCliente';
import Toast from '../components/Toast';
import { Plus, Search, RotateCcw, ChevronLeft, ChevronRight, Settings, Truck, PackageCheck, ClipboardList, FileDown } from 'lucide-react';
import DocumentGeneratorModal from '../components/DocumentGeneratorModal';
import styles from './Rma.module.css';

export default function Rma() {
  const { tienePermiso } = usePermisos();
  const puedeGestionar = tienePermiso('rma.gestionar');
  const puedeAdminOpciones = tienePermiso('rma.admin_opciones');
  const puedeImprimir = tienePermiso('documentos.imprimir');
  const [docGenOpen, setDocGenOpen] = useState(false);
  const [docGenCaso, setDocGenCaso] = useState(null);

  const [casos, setCasos] = useState([]);
  const [loading, setLoading] = useState(true);
  const [totalItems, setTotalItems] = useState(0);
  const [totalPages, setTotalPages] = useState(0);
  const [stats, setStats] = useState(null);
  const [estadosCaso, setEstadosCaso] = useState([]);

  const { getFilter, updateFilters } = useQueryFilters(
    { search: '', page: 1, page_size: 50, estado_caso_id: '' },
    { page: 'number', page_size: 'number' }
  );

  const search = getFilter('search');
  const page = getFilter('page');
  const estadoCasoId = getFilter('estado_caso_id');
  const debouncedSearch = useDebounce(search, 500);

  const { toast, showToast, hideToast } = useToast();
  const backgroundSaveRef = useRef(null);

  const [modalOpen, setModalOpen] = useState(false);
  const [casoSeleccionado, setCasoSeleccionado] = useState(null);
  const [showAdmin, setShowAdmin] = useState(false);
  const [showProveedores, setShowProveedores] = useState(false);
  const [activeTab, setActiveTab] = useState('casos');

  const cargarCasos = useCallback(async () => {
    setLoading(true);
    try {
      const params = { page, page_size: 50 };
      if (debouncedSearch) params.search = debouncedSearch;
      if (estadoCasoId) params.estado_caso_id = estadoCasoId;
      const { data } = await api.get('/rma-seguimiento', { params });
      setCasos(data.items);
      setTotalItems(data.total);
      setTotalPages(data.total_pages);
    } catch {
      setCasos([]);
    } finally {
      setLoading(false);
    }
  }, [page, debouncedSearch, estadoCasoId]);

  useEffect(() => {
    cargarCasos();
  }, [cargarCasos]);

  useEffect(() => {
    cargarStats();
    cargarEstadosCaso();
  }, []);

  const cargarStats = async () => {
    try {
      const { data } = await api.get('/rma-seguimiento/stats/resumen');
      setStats(data);
    } catch {
      // stats opcionales
    }
  };

  const cargarEstadosCaso = async () => {
    try {
      const { data } = await api.get('/rma-seguimiento/opciones', {
        params: { solo_activas: true },
      });
      const estados = data.filter((op) => op.categoria === 'estado_caso');
      setEstadosCaso(estados);
    } catch {
      // opciones vacías
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

  const handleModalClose = (result) => {
    setModalOpen(false);
    setCasoSeleccionado(null);

    // Background save: el modal se cerró inmediatamente y la request sigue en segundo plano
    if (result && typeof result === 'object' && result.backgroundSave) {
      showToast('Creando caso RMA...', 'info');
      const savePromise = result.backgroundSave;
      backgroundSaveRef.current = savePromise;

      savePromise
        .then(() => {
          // Solo actualizamos si esta promesa sigue siendo la vigente
          // (evita recargar si el usuario ya abrió otro modal y lanzó otro save)
          if (backgroundSaveRef.current === savePromise) {
            backgroundSaveRef.current = null;
            showToast('Caso RMA creado correctamente', 'success');
            // Recargar solo si el modal NO está abierto (no pisarle la página al usuario)
            cargarCasos();
            cargarStats();
          }
        })
        .catch(() => {
          if (backgroundSaveRef.current === savePromise) {
            backgroundSaveRef.current = null;
            showToast('Error al crear el caso RMA. Intentá de nuevo.', 'error');
          }
        });
      return;
    }

    // Guardado síncrono (edición) o cierre con cambios
    if (result === true) {
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
              {stats.por_estado ? (
                stats.por_estado
                  .filter((e) => e.cantidad > 0)
                  .map((e) => (
                    <span
                      key={e.id}
                      className={styles.chipDynamic}
                      style={{ '--chip-color': `var(--color-${e.color || 'gray'})` }}
                    >
                      {e.cantidad} {e.valor.toLowerCase()}
                    </span>
                  ))
              ) : (
                <>
                  <span className={styles.chipAbiertos}>{stats.abiertos} abiertos</span>
                  <span className={styles.chipTotal}>{stats.total} total</span>
                </>
              )}
            </div>
          )}
        </div>
        <div style={{ display: 'flex', gap: '8px' }}>
          {puedeGestionar && (
            <button
              className={`btn-tesla ${showProveedores ? 'primary' : 'ghost'} sm`}
              onClick={() => { setShowProveedores(!showProveedores); if (!showProveedores) setShowAdmin(false); }}
              title="Gestionar proveedores RMA"
              aria-label="Gestionar proveedores RMA"
            >
              <Truck size={16} />
            </button>
          )}
          {puedeAdminOpciones && (
            <button
              className={`btn-tesla ${showAdmin ? 'primary' : 'ghost'} sm`}
              onClick={() => { setShowAdmin(!showAdmin); if (!showAdmin) setShowProveedores(false); }}
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

      {/* Admin Panel */}
      {showAdmin && puedeAdminOpciones && (
        <div className={styles.adminPanel}>
          <RmaAdminOpciones />
        </div>
      )}

      {/* Proveedores Panel */}
      {showProveedores && puedeGestionar && (
        <div className={styles.adminPanel}>
          <RmaProveedores />
        </div>
      )}

      {/* Tabs */}
      <div className={styles.tabBar}>
        <button
          className={`${styles.tab} ${activeTab === 'casos' ? styles.tabActive : ''}`}
          onClick={() => setActiveTab('casos')}
        >
          <ClipboardList size={15} />
          Casos
        </button>
        {puedeGestionar && (
          <button
            className={`${styles.tab} ${activeTab === 'envios_proveedor' ? styles.tabActive : ''}`}
            onClick={() => setActiveTab('envios_proveedor')}
          >
            <Truck size={15} />
            Envios a Proveedor
          </button>
        )}
        {puedeGestionar && (
          <button
            className={`${styles.tab} ${activeTab === 'envios_cliente' ? styles.tabActive : ''}`}
            onClick={() => setActiveTab('envios_cliente')}
          >
            <PackageCheck size={15} />
            Envios a Cliente
          </button>
        )}
      </div>

      {/* Tab: Casos */}
      {activeTab === 'casos' && (
        <>
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
              value={estadoCasoId}
              onChange={(e) => updateFilters({ estado_caso_id: e.target.value, page: 1 })}
              className={styles.selectFiltro}
            >
              <option value="">Todos los estados</option>
              {estadosCaso.map((op) => (
                <option key={op.id} value={op.id}>{op.valor}</option>
              ))}
            </select>
          </div>

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
                  {puedeImprimir && <th style={{ width: '50px' }}></th>}
                </tr>
              </thead>
              <tbody className="table-tesla-body">
                {loading ? (
                  <tr><td colSpan={puedeImprimir ? 9 : 8} className={styles.loadingCell}>Cargando...</td></tr>
                ) : casos.length === 0 ? (
                  <tr><td colSpan={puedeImprimir ? 9 : 8} className={styles.emptyCell}>No se encontraron casos RMA</td></tr>
                ) : (
                  casos.map((caso) => (
                    <tr key={caso.id} onClick={() => handleEditar(caso)} className={styles.clickableRow}>
                      <td className={styles.cellCaso}>{caso.numero_caso}</td>
                      <td>{caso.fecha_caso || '\u2014'}</td>
                      <td>
                        <div className={styles.clienteCell}>
                          <span className={styles.clienteNombre}>{caso.cliente_nombre || '\u2014'}</span>
                          {caso.cliente_numero && (
                            <span className={styles.clienteNumero}>#{caso.cliente_numero}</span>
                          )}
                        </div>
                      </td>
                      <td className={styles.cellMono}>{caso.ml_id || '\u2014'}</td>
                      <td className={styles.cellCenter}>{caso.total_items}</td>
                      <td>
                        {caso.estado_caso_color ? (
                          <span
                            className={styles.badgeOpcion}
                            style={{ '--badge-color': `var(--color-${caso.estado_caso_color})` }}
                          >
                            {caso.estado}
                          </span>
                        ) : (
                          <span className={`${styles.badge} ${styles[`badge_${caso.estado}`] || ''}`}>
                            {caso.estado}
                          </span>
                        )}
                      </td>
                      <td>
                        {caso.estado_reclamo_ml_valor ? (
                          <span
                            className={styles.badgeOpcion}
                            style={{ '--badge-color': `var(--color-${caso.estado_reclamo_ml_color || 'gray'})` }}
                          >
                            {caso.estado_reclamo_ml_valor}
                          </span>
                        ) : '\u2014'}
                      </td>
                      <td className={styles.cellObs}>
                        {caso.observaciones ? caso.observaciones.substring(0, 60) + (caso.observaciones.length > 60 ? '...' : '') : '\u2014'}
                      </td>
                      {puedeImprimir && (
                        <td>
                          <button
                            onClick={(e) => { e.stopPropagation(); setDocGenCaso(caso); setDocGenOpen(true); }}
                            className={styles.btnAction}
                            title="Generar documento PDF"
                          >
                            <FileDown size={14} />
                          </button>
                        </td>
                      )}
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          {/* Paginacion */}
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
                Pagina {page} de {totalPages} ({totalItems} casos)
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
        </>
      )}

      {/* Tab: Envios a Proveedor */}
      {activeTab === 'envios_proveedor' && puedeGestionar && (
        <RmaEnviosProveedor />
      )}

      {/* Tab: Envios a Cliente */}
      {activeTab === 'envios_cliente' && puedeGestionar && (
        <RmaEnviosCliente />
      )}

      {/* Modal */}
      {modalOpen && (
        <ModalRma
          caso={casoSeleccionado}
          onClose={handleModalClose}
        />
      )}

      {/* Modal generar documento PDF */}
      <DocumentGeneratorModal
        isOpen={docGenOpen}
        onClose={() => { setDocGenOpen(false); setDocGenCaso(null); }}
        contexto="rma"
        entityData={docGenCaso}
      />

      {/* Toast para notificaciones de background save */}
      <Toast toast={toast} onClose={hideToast} />
    </div>
  );
}
