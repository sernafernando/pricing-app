import { useState, useEffect, useCallback } from 'react';
import { ChevronRight, ChevronDown, Maximize2, Minimize2, MinusCircle } from 'lucide-react';
import api from '../services/api';
import SearchInput from '../components/SearchInput';
import { ProductoCard } from './PedidosPreparacion';
import sharedStyles from './PedidosPreparacion.module.css';
import styles from './Produccion.module.css';

export default function Produccion() {
  const [resumen, setResumen] = useState([]);
  const [tiposEnvio, setTiposEnvio] = useState([]);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [syncError, setSyncError] = useState(null);
  const [tipoEnvio, setTipoEnvio] = useState('');
  const [search, setSearch] = useState('');
  const [modoVista, setModoVista] = useState('lista');
  const [componentes, setComponentes] = useState({});
  const [expandidos, setExpandidos] = useState(new Set());
  const [cargandoTodos, setCargandoTodos] = useState(false);

  const cargarTiposEnvio = useCallback(async () => {
    try {
      const response = await api.get('/pedidos-preparacion/tipos-envio');
      setTiposEnvio(response.data);
    } catch (error) {
      console.error('Error cargando tipos de envío:', error);
    }
  }, []);

  const cargarDatos = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (tipoEnvio) params.append('logistic_type', tipoEnvio);
      if (search) params.append('search', search);
      // vista_produccion siempre activa en esta página — es el sentido de existir
      params.append('vista_produccion', 'true');

      const response = await api.get(`/pedidos-preparacion/resumen?${params}`);
      setResumen(response.data);
      // Cuando cambia el dataset, los items expandidos pueden ya no estar — limpiamos
      setExpandidos(new Set());
    } catch (error) {
      console.error('Error cargando datos:', error);
    } finally {
      setLoading(false);
    }
  }, [tipoEnvio, search]);

  const cargarComponentes = useCallback(async (itemId) => {
    try {
      const response = await api.get(`/pedidos-preparacion/componentes/${itemId}`);
      setComponentes(prev => ({ ...prev, [itemId]: response.data }));
      return response.data;
    } catch (error) {
      console.error('Error cargando componentes:', error);
      setComponentes(prev => ({ ...prev, [itemId]: [] }));
      return [];
    }
  }, []);

  useEffect(() => {
    cargarTiposEnvio();
  }, [cargarTiposEnvio]);

  useEffect(() => {
    cargarDatos();
  }, [cargarDatos]);

  const sincronizarDatos = async () => {
    setSyncing(true);
    setSyncError(null);
    try {
      await api.post('/pedidos-preparacion/sync', {});
      await Promise.all([cargarDatos(), cargarTiposEnvio()]);
    } catch (error) {
      console.error('Error sincronizando:', error);
      setSyncError(error.response?.data?.detail || error.message || 'Error desconocido');
    } finally {
      setSyncing(false);
    }
  };

  const toggleExpandido = async (itemId) => {
    if (!componentes[itemId]) {
      await cargarComponentes(itemId);
    }
    setExpandidos(prev => {
      const next = new Set(prev);
      if (next.has(itemId)) next.delete(itemId);
      else next.add(itemId);
      return next;
    });
  };

  const desplegarTodos = async () => {
    if (resumen.length === 0) return;
    setCargandoTodos(true);
    try {
      const itemsSinCache = resumen.filter(r => !componentes[r.item_id]);
      await Promise.all(itemsSinCache.map(r => cargarComponentes(r.item_id)));
      setExpandidos(new Set(resumen.map(r => r.item_id)));
    } finally {
      setCargandoTodos(false);
    }
  };

  const colapsarTodos = () => setExpandidos(new Set());

  const todosExpandidos = resumen.length > 0 && expandidos.size === resumen.length;

  const getBadgeClass = (tipo) => {
    switch (tipo?.toLowerCase()) {
      case 'turbo': return sharedStyles.badgeTurbo;
      case 'self_service': return sharedStyles.badgeSelfService;
      case 'cross_docking': return sharedStyles.badgeCrossDocking;
      case 'drop_off': return sharedStyles.badgeDropOff;
      case 'xd_drop_off': return sharedStyles.badgeXdDropOff;
      default: return sharedStyles.badgeDefault;
    }
  };

  const renderComponentes = (itemId) => {
    const lista = componentes[itemId];
    if (lista === undefined) {
      return <div className={sharedStyles.componentesLoading}>Cargando...</div>;
    }
    if (lista.length === 0) {
      return <div className={sharedStyles.componentesEmpty}>Sin componentes asociados</div>;
    }
    return (
      <div className={sharedStyles.componentesList}>
        {lista.map((comp) => {
          const esNegativo = comp.cantidad < 0;
          return (
            <div
              key={comp.item_id}
              className={`${sharedStyles.componenteItem} ${esNegativo ? sharedStyles.componenteItemNegativo : ''}`}
            >
              {esNegativo && (
                <MinusCircle
                  size={14}
                  className={sharedStyles.componenteIconoNegativo}
                  aria-label="Se reemplaza del producto original"
                />
              )}
              <div className={sharedStyles.componenteInfo}>
                <strong>{comp.item_code}</strong>
                <span>{comp.item_desc}</span>
                {esNegativo && (
                  <small className={sharedStyles.componenteReemplaza}>se reemplaza</small>
                )}
              </div>
              <div className={`${sharedStyles.componenteCantidad} ${esNegativo ? sharedStyles.componenteCantidadNegativa : ''}`}>
                x {comp.cantidad}
              </div>
            </div>
          );
        })}
      </div>
    );
  };

  return (
    <div className={sharedStyles.container}>
      <div className={sharedStyles.header}>
        <h1 className={sharedStyles.title}>Producción</h1>
      </div>

      {syncError && (
        <div className={styles.syncErrorBanner} role="alert">
          <span>Error al sincronizar con el ERP: {syncError}</span>
          <button
            type="button"
            onClick={() => setSyncError(null)}
            className={styles.syncErrorDismiss}
            aria-label="Cerrar mensaje de error"
          >
            ×
          </button>
        </div>
      )}

      <div className={sharedStyles.tabControls}>
        <button onClick={cargarDatos} className={styles.actionBtn} disabled={loading || syncing}>
          Actualizar
        </button>
        <button
          onClick={sincronizarDatos}
          className={`${styles.actionBtn} ${styles.actionBtnAccent}`}
          disabled={syncing || loading}
        >
          {syncing ? 'Sincronizando...' : 'Sincronizar ERP'}
        </button>
        {modoVista === 'lista' && resumen.length > 0 && (
          <button
            onClick={todosExpandidos ? colapsarTodos : desplegarTodos}
            className={styles.actionBtn}
            disabled={cargandoTodos}
          >
            {todosExpandidos
              ? <><Minimize2 size={16} /> Colapsar todos</>
              : <><Maximize2 size={16} /> {cargandoTodos ? 'Cargando...' : 'Desplegar todos'}</>}
          </button>
        )}
      </div>

      <div className={sharedStyles.filtrosContainer}>
        <div className={sharedStyles.filtrosRow}>
          <div className={sharedStyles.modoVistaButtons}>
            <button
              className={`${sharedStyles.modoVistaBtn} ${modoVista === 'lista' ? sharedStyles.modoVistaActivo : ''}`}
              onClick={() => setModoVista('lista')}
              title="Vista Lista"
              aria-label="Vista Lista"
            >
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <line x1="3" y1="6" x2="21" y2="6" />
                <line x1="3" y1="12" x2="21" y2="12" />
                <line x1="3" y1="18" x2="21" y2="18" />
              </svg>
            </button>
            <button
              className={`${sharedStyles.modoVistaBtn} ${modoVista === 'cards' ? sharedStyles.modoVistaActivo : ''}`}
              onClick={() => setModoVista('cards')}
              title="Vista Cards"
              aria-label="Vista Cards"
            >
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <rect x="3" y="3" width="7" height="7" />
                <rect x="14" y="3" width="7" height="7" />
                <rect x="3" y="14" width="7" height="7" />
                <rect x="14" y="14" width="7" height="7" />
              </svg>
            </button>
          </div>

          <select
            value={tipoEnvio}
            onChange={(e) => setTipoEnvio(e.target.value)}
            className={sharedStyles.select}
          >
            <option value="">Todos los envios</option>
            {tiposEnvio.map((t) => (
              <option key={t} value={t}>{t}</option>
            ))}
          </select>

          <SearchInput
            value={search}
            onChange={setSearch}
            placeholder="Buscar codigo o descripcion..."
            className={sharedStyles.searchInput}
            size="sm"
          />
        </div>
        <div className={sharedStyles.vistaInfo}>
          Filtrando: EAN con guion + Notebooks, NB, PC ARMADA, AIO
        </div>
      </div>

      {loading ? (
        <div className={sharedStyles.loading}>Cargando pedidos...</div>
      ) : modoVista === 'lista' ? (
        <div className={sharedStyles.tableContainer}>
          <table className={sharedStyles.table}>
            <thead>
              <tr>
                <th aria-label="Expandir" />
                <th>Producto</th>
                <th>Cantidad</th>
                <th>Paquetes</th>
                <th>Tipo Envio</th>
              </tr>
            </thead>
            <tbody>
              {resumen.length === 0 ? (
                <tr>
                  <td colSpan={5} className={sharedStyles.empty}>No hay datos para mostrar</td>
                </tr>
              ) : (
                resumen.flatMap((r) => {
                  const isOpen = expandidos.has(r.item_id);
                  const filas = [
                    <tr key={r.id}>
                      <td className={styles.spoilerToggleCell}>
                        <button
                          className={styles.spoilerToggle}
                          onClick={() => toggleExpandido(r.item_id)}
                          aria-label={isOpen ? 'Colapsar componentes' : 'Expandir componentes'}
                          aria-expanded={isOpen}
                        >
                          {isOpen ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                        </button>
                      </td>
                      <td>
                        <div className={sharedStyles.producto}>
                          <strong>{r.item_code || '-'}</strong>
                          <span className={sharedStyles.descripcion}>{r.item_desc || '-'}</span>
                        </div>
                      </td>
                      <td className={sharedStyles.cantidadGrande}>{r.cantidad}</td>
                      <td className={sharedStyles.cantidad}>{r.prepara_paquete}</td>
                      <td>
                        <span className={`${sharedStyles.badge} ${getBadgeClass(r.ml_logistic_type)}`}>
                          {r.ml_logistic_type || 'N/A'}
                        </span>
                      </td>
                    </tr>,
                  ];
                  if (isOpen) {
                    filas.push(
                      <tr key={`${r.id}-detalle`} className={styles.filaDetalle}>
                        <td colSpan={5}>
                          <div className={styles.filaDetalleContent}>
                            {renderComponentes(r.item_id)}
                          </div>
                        </td>
                      </tr>,
                    );
                  }
                  return filas;
                })
              )}
            </tbody>
          </table>
        </div>
      ) : (
        <div className={sharedStyles.cardsContainer}>
          {resumen.length === 0 ? (
            <div className={sharedStyles.empty}>No hay datos para mostrar</div>
          ) : (
            resumen.map((r) => (
              <ProductoCard
                key={r.id}
                producto={r}
                componentes={componentes[r.item_id]}
                onLoadComponentes={() => cargarComponentes(r.item_id)}
                getBadgeClass={getBadgeClass}
              />
            ))
          )}
        </div>
      )}

      <div className={sharedStyles.footer}>
        <span>Mostrando {resumen.length} productos</span>
      </div>
    </div>
  );
}
