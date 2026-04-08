import { useState, useEffect, useCallback } from 'react';
import { usePermisos } from '../contexts/PermisosContext';
import { useDebounce } from '../hooks/useDebounce';
import api from '../services/api';
import styles from './AdministracionCaja.module.css';
import { registrarPagina } from '../registry/tabRegistry';
import {
  Wallet,
  Plus,
  ArrowLeft,
  Loader2,
  AlertCircle,
  ArrowUpCircle,
  ArrowDownCircle,
  RefreshCw,
  ChevronLeft,
  ChevronRight,
  X,
  Paperclip,
  Settings2,
  Search,
} from 'lucide-react';

registrarPagina({
  pagePath: '/administracion/caja',
  pageLabel: 'Administración - Caja',
  tabs: [],
});

// ── Helpers ──────────────────────────────────────────────────────

const formatCurrency = (value, moneda = 'ARS') => {
  const num = Number(value) || 0;
  const prefix = moneda === 'USD' ? 'US$' : '$';
  return `${prefix}${num.toLocaleString('es-AR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
};

const formatDate = (dateStr) => {
  if (!dateStr) return '';
  const d = new Date(dateStr + 'T00:00:00');
  return d.toLocaleDateString('es-AR', { day: '2-digit', month: '2-digit', year: 'numeric' });
};

const todayStr = () => new Date().toISOString().split('T')[0];

// ── Component ────────────────────────────────────────────────────

export default function AdministracionCaja() {
  const { tienePermiso } = usePermisos();
  const canManage = tienePermiso('administracion.gestionar_caja');
  const canSync = tienePermiso('administracion.sincronizar_caja');

  // ── Routing state (list / detail / categories) ──
  const [view, setView] = useState('list'); // 'list' | 'detail' | 'categories'
  const [selectedCaja, setSelectedCaja] = useState(null);

  // ── List view ──
  const [cajas, setCajas] = useState([]);
  const [loadingCajas, setLoadingCajas] = useState(false);

  // ── Detail view ──
  const [movimientos, setMovimientos] = useState([]);
  const [movTotal, setMovTotal] = useState(0);
  const [movPage, setMovPage] = useState(1);
  const [movSummary, setMovSummary] = useState({ total_ingresos: 0, total_egresos: 0, saldo_periodo: 0 });
  const [loadingMovimientos, setLoadingMovimientos] = useState(false);

  // Filters
  const [filtroFechaDesde, setFiltroFechaDesde] = useState('');
  const [filtroFechaHasta, setFiltroFechaHasta] = useState('');
  const [filtroTipo, setFiltroTipo] = useState('');
  const [filtroCategoria, setFiltroCategoria] = useState('');
  const [filtroBusqueda, setFiltroBusqueda] = useState('');
  const debouncedBusqueda = useDebounce(filtroBusqueda, 300);

  // Categories
  const [categorias, setCategorias] = useState([]);

  // ── Modals ──
  const [showMovModal, setShowMovModal] = useState(false);
  const [showSyncModal, setShowSyncModal] = useState(false);
  const [showCajaModal, setShowCajaModal] = useState(false);

  // ── Modal forms ──
  const [movForm, setMovForm] = useState({ tipo: 'ingreso', fecha: todayStr(), detalle: '', monto: '', categoria_id: '', observaciones: '' });
  const [catForm, setCatForm] = useState({ nombre: '', tipo_aplicable: 'ambos' });
  const [cajaForm, setCajaForm] = useState({ nombre: '', empresa_id: '', moneda: 'ARS', saldo_inicial: 0 });
  const [empresas, setEmpresas] = useState([]);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState(null);

  // Sync
  const [syncing, setSyncing] = useState(false);
  const [syncResult, setSyncResult] = useState(null);

  // ══════════════════════════════════════════════════════════════
  // Data fetching
  // ══════════════════════════════════════════════════════════════

  const fetchCajas = useCallback(async () => {
    setLoadingCajas(true);
    try {
      const { data } = await api.get('/administracion-caja/cajas');
      setCajas(data);
    } catch {
      setCajas([]);
    } finally {
      setLoadingCajas(false);
    }
  }, []);

  const fetchMovimientos = useCallback(async () => {
    if (!selectedCaja) return;
    setLoadingMovimientos(true);
    try {
      const params = new URLSearchParams({ page: movPage, page_size: 50 });
      if (filtroFechaDesde) params.append('fecha_desde', filtroFechaDesde);
      if (filtroFechaHasta) params.append('fecha_hasta', filtroFechaHasta);
      if (filtroTipo) params.append('tipo', filtroTipo);
      if (filtroCategoria) params.append('categoria_id', filtroCategoria);
      if (debouncedBusqueda) params.append('busqueda', debouncedBusqueda);

      const { data } = await api.get(`/administracion-caja/cajas/${selectedCaja.id}/movimientos?${params}`);
      setMovimientos(data.items);
      setMovTotal(data.total);
      setMovSummary({
        total_ingresos: data.total_ingresos,
        total_egresos: data.total_egresos,
        saldo_periodo: data.saldo_periodo,
      });
    } catch {
      setMovimientos([]);
    } finally {
      setLoadingMovimientos(false);
    }
  }, [selectedCaja, movPage, filtroFechaDesde, filtroFechaHasta, filtroTipo, filtroCategoria, debouncedBusqueda]);

  const fetchCategorias = useCallback(async () => {
    try {
      const { data } = await api.get('/administracion-caja/categorias?incluir_inactivas=true');
      setCategorias(data);
    } catch {
      setCategorias([]);
    }
  }, []);

  const fetchEmpresas = useCallback(async () => {
    try {
      const { data } = await api.get('/empresas');
      setEmpresas(data);
    } catch {
      setEmpresas([]);
    }
  }, []);

  useEffect(() => { fetchCajas(); fetchCategorias(); }, [fetchCajas, fetchCategorias]);
  useEffect(() => { if (view === 'detail') fetchMovimientos(); }, [view, fetchMovimientos]);

  // Reset page when filters change
  useEffect(() => { setMovPage(1); }, [filtroFechaDesde, filtroFechaHasta, filtroTipo, filtroCategoria, debouncedBusqueda]);

  // ══════════════════════════════════════════════════════════════
  // Actions
  // ══════════════════════════════════════════════════════════════

  const handleSelectCaja = (caja) => {
    setSelectedCaja(caja);
    setView('detail');
    setMovPage(1);
    setFiltroBusqueda('');
    setFiltroTipo('');
    setFiltroCategoria('');
    setFiltroFechaDesde('');
    setFiltroFechaHasta('');
  };

  const handleBackToList = () => {
    setView('list');
    setSelectedCaja(null);
    fetchCajas();
  };

  // ── Create Caja ──
  const handleOpenCajaModal = () => {
    setCajaForm({ nombre: '', empresa_id: '', moneda: 'ARS', saldo_inicial: 0 });
    setFormError(null);
    fetchEmpresas();
    setShowCajaModal(true);
  };

  const handleSaveCaja = async (e) => {
    e.preventDefault();
    if (!cajaForm.nombre.trim() || !cajaForm.empresa_id) {
      setFormError('Nombre y empresa son requeridos');
      return;
    }
    setSaving(true);
    setFormError(null);
    try {
      await api.post('/administracion-caja/cajas', {
        nombre: cajaForm.nombre.trim(),
        empresa_id: Number(cajaForm.empresa_id),
        moneda: cajaForm.moneda,
        saldo_inicial: Number(cajaForm.saldo_inicial) || 0,
      });
      setShowCajaModal(false);
      fetchCajas();
    } catch (err) {
      setFormError(err.response?.data?.detail || 'Error al crear caja');
    } finally {
      setSaving(false);
    }
  };

  // ── Register Movement ──
  const handleOpenMovModal = () => {
    setMovForm({ tipo: 'ingreso', fecha: todayStr(), detalle: '', monto: '', categoria_id: '', observaciones: '' });
    setFormError(null);
    setShowMovModal(true);
  };

  const handleSaveMovimiento = async (e) => {
    e.preventDefault();
    const monto = parseFloat(movForm.monto);
    if (!movForm.detalle.trim() || !monto || monto <= 0) {
      setFormError('Detalle y monto (> 0) son requeridos');
      return;
    }
    setSaving(true);
    setFormError(null);
    try {
      await api.post(`/administracion-caja/cajas/${selectedCaja.id}/movimientos`, {
        tipo: movForm.tipo,
        fecha: movForm.fecha,
        detalle: movForm.detalle.trim(),
        monto,
        categoria_id: movForm.categoria_id ? Number(movForm.categoria_id) : null,
        observaciones: movForm.observaciones || null,
      });
      setShowMovModal(false);
      fetchMovimientos();
      // Refresh caja to get updated saldo
      try {
        const { data } = await api.get(`/administracion-caja/cajas/${selectedCaja.id}`);
        setSelectedCaja(data);
      } catch { /* ignore */ }
    } catch (err) {
      setFormError(err.response?.data?.detail || 'Error al registrar movimiento');
    } finally {
      setSaving(false);
    }
  };

  // ── Category CRUD ──
  const handleSaveCategory = async (e) => {
    e.preventDefault();
    if (!catForm.nombre.trim()) {
      setFormError('Nombre es requerido');
      return;
    }
    setSaving(true);
    setFormError(null);
    try {
      await api.post('/administracion-caja/categorias', {
        nombre: catForm.nombre.trim(),
        tipo_aplicable: catForm.tipo_aplicable,
      });
      setCatForm({ nombre: '', tipo_aplicable: 'ambos' });
      fetchCategorias();
    } catch (err) {
      setFormError(err.response?.data?.detail || 'Error al crear categoría');
    } finally {
      setSaving(false);
    }
  };

  // ── Sync ──
  const handleSync = async () => {
    setSyncing(true);
    setSyncResult(null);
    try {
      const { data } = await api.post('/administracion-caja/sync');
      setSyncResult(data);
      fetchCajas();
    } catch (err) {
      setSyncResult({ error: err.response?.data?.detail || 'Error de sincronización' });
    } finally {
      setSyncing(false);
    }
  };

  // ══════════════════════════════════════════════════════════════
  // Render
  // ══════════════════════════════════════════════════════════════

  const activeCategorias = categorias.filter(c => c.activo);
  const totalPages = Math.ceil(movTotal / 50);

  // ── LIST VIEW ──
  if (view === 'list') {
    return (
      <div className={styles.container}>
        <div className={styles.header}>
          <div className={styles.headerLeft}>
            <Wallet size={24} />
            <h1 className={styles.title}>Caja</h1>
            <span className={styles.badge}>{cajas.length}</span>
          </div>
          <div className={styles.headerActions}>
            {canManage && (
              <button className={styles.btnPrimary} onClick={() => { setView('categories'); setFormError(null); }}>
                <Settings2 size={16} /> Categorías
              </button>
            )}
            {canSync && (
              <button className={styles.btnSync} onClick={() => { setSyncResult(null); setShowSyncModal(true); }} disabled={syncing}>
                <RefreshCw size={16} /> Sincronizar Sheets
              </button>
            )}
            {canManage && (
              <button className={styles.btnSuccess} onClick={handleOpenCajaModal}>
                <Plus size={16} /> Nueva Caja
              </button>
            )}
          </div>
        </div>

        {loadingCajas ? (
          <div className={styles.centered}><Loader2 size={24} className="spin" /> Cargando...</div>
        ) : cajas.length === 0 ? (
          <div className={styles.emptyState}>No hay cajas registradas</div>
        ) : (
          <div className={styles.cardsGrid}>
            {cajas.map(caja => (
              <div key={caja.id} className={styles.card} onClick={() => handleSelectCaja(caja)}>
                <div className={styles.cardHeader}>
                  <span className={styles.cardNombre}>{caja.nombre}</span>
                  <span className={caja.moneda === 'USD' ? styles.cardMonedaUSD : styles.cardMoneda}>{caja.moneda}</span>
                </div>
                <div className={styles.cardEmpresa}>{caja.empresa_nombre}</div>
                <div className={styles.cardSaldo}>{formatCurrency(caja.saldo_actual, caja.moneda)}</div>
              </div>
            ))}
          </div>
        )}

        {/* ── New Caja Modal ── */}
        {showCajaModal && (
          <div className={styles.modalOverlay}>
            <div className={styles.modalContent}>
              <div className={styles.modalHeader}>
                <span className={styles.modalTitle}>Nueva Caja</span>
                <button className={styles.modalCloseBtn} onClick={() => setShowCajaModal(false)}><X size={18} /></button>
              </div>
              {formError && <div className={styles.formError}>{formError}</div>}
              <form onSubmit={handleSaveCaja}>
                <div className={styles.formGroup}>
                  <label className={styles.formLabel}>Nombre</label>
                  <input className={styles.formInput} value={cajaForm.nombre} onChange={e => setCajaForm(f => ({ ...f, nombre: e.target.value }))} required />
                </div>
                <div className={styles.formGroup}>
                  <label className={styles.formLabel}>Empresa</label>
                  <select className={styles.formSelect} value={cajaForm.empresa_id} onChange={e => setCajaForm(f => ({ ...f, empresa_id: e.target.value }))} required>
                    <option value="">Seleccionar...</option>
                    {empresas.map(emp => <option key={emp.id} value={emp.id}>{emp.nombre}</option>)}
                  </select>
                </div>
                <div className={styles.formGroup}>
                  <label className={styles.formLabel}>Moneda</label>
                  <select className={styles.formSelect} value={cajaForm.moneda} onChange={e => setCajaForm(f => ({ ...f, moneda: e.target.value }))}>
                    <option value="ARS">ARS</option>
                    <option value="USD">USD</option>
                  </select>
                </div>
                <div className={styles.formGroup}>
                  <label className={styles.formLabel}>Saldo Inicial</label>
                  <input type="number" step="0.01" className={styles.formInput} value={cajaForm.saldo_inicial} onChange={e => setCajaForm(f => ({ ...f, saldo_inicial: e.target.value }))} />
                </div>
                <div className={styles.formActions}>
                  <button type="button" className={styles.btnPrimary} onClick={() => setShowCajaModal(false)}>Cancelar</button>
                  <button type="submit" className={styles.btnSuccess} disabled={saving}>{saving ? 'Guardando...' : 'Crear Caja'}</button>
                </div>
              </form>
            </div>
          </div>
        )}

        {/* ── Sync Modal ── */}
        {showSyncModal && (
          <div className={styles.modalOverlay}>
            <div className={styles.modalContent}>
              <div className={styles.modalHeader}>
                <span className={styles.modalTitle}>Sincronizar desde Google Sheets</span>
                <button className={styles.modalCloseBtn} onClick={() => setShowSyncModal(false)}><X size={18} /></button>
              </div>
              {!syncResult && !syncing && (
                <div>
                  <p className={styles.syncDescription}>
                    Esto importará movimientos históricos desde la hoja de Google Sheets configurada. Los duplicados serán detectados y omitidos automáticamente.
                  </p>
                  <div className={styles.formActions}>
                    <button className={styles.btnPrimary} onClick={() => setShowSyncModal(false)}>Cancelar</button>
                    <button className={styles.btnSync} onClick={handleSync}>Iniciar Sincronización</button>
                  </div>
                </div>
              )}
              {syncing && (
                <div className={styles.centered}><Loader2 size={24} className="spin" /> Sincronizando...</div>
              )}
              {syncResult && (
                <div className={styles.syncResults}>
                  {syncResult.error ? (
                    <p className={styles.syncError}>{syncResult.error}</p>
                  ) : (
                    <dl>
                      <dt>Procesadas</dt><dd>{syncResult.total_procesadas}</dd>
                      <dt>Nuevas</dt><dd className={styles.syncNuevas}>{syncResult.nuevas}</dd>
                      <dt>Duplicadas saltadas</dt><dd>{syncResult.duplicadas_saltadas}</dd>
                      <dt>Errores</dt><dd className={syncResult.errores?.length > 0 ? styles.syncErrorCount : undefined}>{syncResult.errores?.length || 0}</dd>
                    </dl>
                  )}
                  <div className={styles.formActions}>
                    <button className={styles.btnPrimary} onClick={() => setShowSyncModal(false)}>Cerrar</button>
                  </div>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    );
  }

  // ── CATEGORIES VIEW ──
  if (view === 'categories') {
    return (
      <div className={styles.container}>
        <div className={styles.header}>
          <div className={styles.headerLeft}>
            <button className={styles.backBtn} onClick={handleBackToList}><ArrowLeft size={16} /> Volver</button>
            <h1 className={styles.title}>Categorías de Caja</h1>
            <span className={styles.badge}>{categorias.length}</span>
          </div>
        </div>

        {/* New category form */}
        {canManage && (
          <form onSubmit={handleSaveCategory} className={styles.categoryForm}>
            <input className={styles.input} placeholder="Nombre de categoría..." value={catForm.nombre} onChange={e => setCatForm(f => ({ ...f, nombre: e.target.value }))} />
            <select className={styles.select} value={catForm.tipo_aplicable} onChange={e => setCatForm(f => ({ ...f, tipo_aplicable: e.target.value }))}>
              <option value="ambos">Ambos</option>
              <option value="ingreso">Ingreso</option>
              <option value="egreso">Egreso</option>
            </select>
            <button type="submit" className={styles.btnSuccess} disabled={saving}><Plus size={14} /> Crear</button>
          </form>
        )}
        {formError && <div className={styles.formError}>{formError}</div>}

        <div className={styles.tableWrapper}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Nombre</th>
                <th>Tipo Aplicable</th>
                <th>Estado</th>
              </tr>
            </thead>
            <tbody>
              {categorias.map(cat => (
                <tr key={cat.id}>
                  <td className={styles.catNombreTd}>{cat.nombre}</td>
                  <td>
                    <span className={`${styles.tipoChip} ${cat.tipo_aplicable === 'ingreso' ? styles.tipoIngreso : cat.tipo_aplicable === 'egreso' ? styles.tipoEgreso : ''}`}>
                      {cat.tipo_aplicable}
                    </span>
                  </td>
                  <td className={cat.activo ? styles.catEstadoActiva : styles.catEstadoInactiva}>
                    {cat.activo ? 'Activa' : 'Inactiva'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    );
  }

  // ── DETAIL VIEW ──
  return (
    <div className={styles.container}>
      {/* Header */}
      <div className={styles.header}>
        <div className={styles.headerLeft}>
          <button className={styles.backBtn} onClick={handleBackToList}><ArrowLeft size={16} /> Volver</button>
          <h1 className={styles.title}>{selectedCaja?.nombre}</h1>
          <span className={selectedCaja?.moneda === 'USD' ? styles.cardMonedaUSD : styles.cardMoneda}>{selectedCaja?.moneda}</span>
          <span className={styles.empresaLabel}>{selectedCaja?.empresa_nombre}</span>
        </div>
        <div className={styles.headerActions}>
          {canManage && (
            <button className={styles.btnSuccess} onClick={handleOpenMovModal}>
              <Plus size={16} /> Nuevo Movimiento
            </button>
          )}
        </div>
      </div>

      {/* Stats Bar */}
      <div className={styles.statsBar}>
        <div className={styles.statCard}>
          <div className={styles.statLabel}>Total Ingresos</div>
          <div className={`${styles.statValue} ${styles.statIngreso}`}>
            {formatCurrency(movSummary.total_ingresos, selectedCaja?.moneda)}
          </div>
        </div>
        <div className={styles.statCard}>
          <div className={styles.statLabel}>Total Egresos</div>
          <div className={`${styles.statValue} ${styles.statEgreso}`}>
            {formatCurrency(movSummary.total_egresos, selectedCaja?.moneda)}
          </div>
        </div>
        <div className={styles.statCard}>
          <div className={styles.statLabel}>Saldo Actual</div>
          <div className={`${styles.statValue} ${styles.statNeutral}`}>
            {formatCurrency(selectedCaja?.saldo_actual, selectedCaja?.moneda)}
          </div>
        </div>
      </div>

      {/* Filters */}
      <div className={styles.filters}>
        <input type="date" className={styles.dateInput} value={filtroFechaDesde} onChange={e => setFiltroFechaDesde(e.target.value)} title="Fecha desde" />
        <input type="date" className={styles.dateInput} value={filtroFechaHasta} onChange={e => setFiltroFechaHasta(e.target.value)} title="Fecha hasta" />
        <select className={styles.select} value={filtroTipo} onChange={e => setFiltroTipo(e.target.value)}>
          <option value="">Todos los tipos</option>
          <option value="ingreso">Ingreso</option>
          <option value="egreso">Egreso</option>
        </select>
        <select className={styles.select} value={filtroCategoria} onChange={e => setFiltroCategoria(e.target.value)}>
          <option value="">Todas las categorías</option>
          {activeCategorias.map(c => <option key={c.id} value={c.id}>{c.nombre}</option>)}
        </select>
        <div className={styles.searchWrapper}>
          <Search size={14} className={styles.searchIcon} />
          <input className={styles.searchInputWithIcon} placeholder="Buscar en detalle..." value={filtroBusqueda} onChange={e => setFiltroBusqueda(e.target.value)} />
        </div>
      </div>

      {/* Movements Table */}
      {loadingMovimientos ? (
        <div className={styles.centered}><Loader2 size={24} className="spin" /> Cargando movimientos...</div>
      ) : movimientos.length === 0 ? (
        <div className={styles.emptyState}>No hay movimientos{debouncedBusqueda || filtroTipo || filtroCategoria || filtroFechaDesde ? ' con los filtros aplicados' : ''}</div>
      ) : (
        <div className={styles.tableWrapper}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Fecha</th>
                <th>Detalle</th>
                <th>Tipo</th>
                <th className={styles.thRight}>Monto</th>
                <th className={styles.thRight}>Saldo</th>
                <th>Categoría</th>
                <th>Origen</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {movimientos.map(mov => (
                <tr key={mov.id}>
                  <td className={styles.tdNoWrap}>{formatDate(mov.fecha)}</td>
                  <td>{mov.detalle}</td>
                  <td>
                    <span className={`${styles.tipoChip} ${mov.tipo === 'ingreso' ? styles.tipoIngreso : styles.tipoEgreso}`}>
                      {mov.tipo === 'ingreso' ? <ArrowUpCircle size={12} /> : <ArrowDownCircle size={12} />}
                      {mov.tipo}
                    </span>
                  </td>
                  <td className={`${styles.tdRight} ${mov.tipo === 'ingreso' ? styles.montoIngreso : styles.montoEgreso}`}>
                    {mov.tipo === 'ingreso' ? '+' : '-'}{formatCurrency(mov.monto, selectedCaja?.moneda)}
                  </td>
                  <td className={styles.tdRightBold}>
                    {formatCurrency(mov.saldo_posterior, selectedCaja?.moneda)}
                  </td>
                  <td className={styles.tdSecondary}>{mov.categoria_nombre || '—'}</td>
                  <td className={styles.tdMeta}>{mov.origen}</td>
                  <td>
                    {mov.documentos_count > 0 && (
                      <span className={styles.docIndicator} title={`${mov.documentos_count} documento(s)`}>
                        <Paperclip size={12} /> {mov.documentos_count}
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          {/* Pagination */}
          {totalPages > 1 && (
            <div className={styles.pagination}>
              <span>{movTotal} movimientos — Página {movPage} de {totalPages}</span>
              <div className={styles.paginationBtns}>
                <button className={styles.pageBtn} onClick={() => setMovPage(p => Math.max(1, p - 1))} disabled={movPage === 1}>
                  <ChevronLeft size={14} />
                </button>
                <button className={styles.pageBtn} onClick={() => setMovPage(p => Math.min(totalPages, p + 1))} disabled={movPage === totalPages}>
                  <ChevronRight size={14} />
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {/* ── New Movement Modal ── */}
      {showMovModal && (
        <div className={styles.modalOverlay}>
          <div className={styles.modalContent}>
            <div className={styles.modalHeader}>
              <span className={styles.modalTitle}>Nuevo Movimiento</span>
              <button className={styles.modalCloseBtn} onClick={() => setShowMovModal(false)}><X size={18} /></button>
            </div>
            {formError && <div className={styles.formError}>{formError}</div>}
            <form onSubmit={handleSaveMovimiento}>
              {/* Tipo Toggle */}
              <div className={styles.formGroup}>
                <label className={styles.formLabel}>Tipo</label>
                <div className={styles.tipoToggle}>
                  <button type="button" className={`${styles.tipoBtn} ${movForm.tipo === 'ingreso' ? styles.tipoBtnIngreso : ''}`} onClick={() => setMovForm(f => ({ ...f, tipo: 'ingreso', categoria_id: '' }))}>
                    <ArrowUpCircle size={14} /> Ingreso
                  </button>
                  <button type="button" className={`${styles.tipoBtn} ${movForm.tipo === 'egreso' ? styles.tipoBtnEgreso : ''}`} onClick={() => setMovForm(f => ({ ...f, tipo: 'egreso', categoria_id: '' }))}>
                    <ArrowDownCircle size={14} /> Egreso
                  </button>
                </div>
              </div>

              <div className={styles.formGroup}>
                <label className={styles.formLabel}>Fecha</label>
                <input type="date" className={styles.formInput} value={movForm.fecha} onChange={e => setMovForm(f => ({ ...f, fecha: e.target.value }))} required />
              </div>

              <div className={styles.formGroup}>
                <label className={styles.formLabel}>Detalle</label>
                <input className={styles.formInput} value={movForm.detalle} onChange={e => setMovForm(f => ({ ...f, detalle: e.target.value }))} required placeholder="Descripción del movimiento" />
              </div>

              <div className={styles.formGroup}>
                <label className={styles.formLabel}>Monto</label>
                <input type="number" step="0.01" min="0.01" className={styles.formInput} value={movForm.monto} onChange={e => setMovForm(f => ({ ...f, monto: e.target.value }))} required placeholder="0.00" />
              </div>

              <div className={styles.formGroup}>
                <label className={styles.formLabel}>Categoría (opcional)</label>
                <select className={styles.formSelect} value={movForm.categoria_id} onChange={e => setMovForm(f => ({ ...f, categoria_id: e.target.value }))}>
                  <option value="">Sin categoría</option>
                  {activeCategorias
                    .filter(c => c.tipo_aplicable === 'ambos' || c.tipo_aplicable === movForm.tipo)
                    .map(c => <option key={c.id} value={c.id}>{c.nombre}</option>)
                  }
                </select>
              </div>

              <div className={styles.formGroup}>
                <label className={styles.formLabel}>Observaciones (opcional)</label>
                <textarea className={styles.formTextarea} value={movForm.observaciones} onChange={e => setMovForm(f => ({ ...f, observaciones: e.target.value }))} placeholder="Notas adicionales..." />
              </div>

              <div className={styles.formActions}>
                <button type="button" className={styles.btnPrimary} onClick={() => setShowMovModal(false)}>Cancelar</button>
                <button type="submit" className={movForm.tipo === 'ingreso' ? styles.btnSuccess : styles.btnDanger} disabled={saving}>
                  {saving ? 'Guardando...' : `Registrar ${movForm.tipo === 'ingreso' ? 'Ingreso' : 'Egreso'}`}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
