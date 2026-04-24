import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { usePermisos } from '../contexts/PermisosContext';
import { useDebounce } from '../hooks/useDebounce';
import api from '../services/api';
import SearchInput from '../components/SearchInput';
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
  ChevronDown,
  ChevronUp,
  X,
  Paperclip,
  Settings2,
  Upload,
  FileText,
  Trash2,
  Unlink,
  Eye,
  Pencil,
  Tag,
  ExternalLink,
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
  const navigate = useNavigate();
  const canManage = tienePermiso('administracion.gestionar_caja');
  const canSync = tienePermiso('administracion.sincronizar_caja');

  // ── Routing state (list / detail / categories / tags) ──
  const [view, setView] = useState('list'); // 'list' | 'detail' | 'categories' | 'tags'
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

  // ── Tags (T5/T6/T7) ──
  const [tags, setTags] = useState([]);
  const [filtroTag, setFiltroTag] = useState('');
  const [showClasificacionModal, setShowClasificacionModal] = useState(false);
  const [clasificacionMov, setClasificacionMov] = useState(null);
  const [clasificacionCatId, setClasificacionCatId] = useState('');
  const [clasificacionTagIds, setClasificacionTagIds] = useState([]);
  const [savingClasificacion, setSavingClasificacion] = useState(false);
  const [newTagNombre, setNewTagNombre] = useState('');
  const [newTagColor, setNewTagColor] = useState('#3b82f6');
  const [creatingTag, setCreatingTag] = useState(false);
  // Tag management form (T7)
  const [tagMgmtNombre, setTagMgmtNombre] = useState('');
  const [tagMgmtColor, setTagMgmtColor] = useState('#3b82f6');
  const [savingTagMgmt, setSavingTagMgmt] = useState(false);
  const [togglingTagId, setTogglingTagId] = useState(null);

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
      if (filtroTag) params.append('tag_id', filtroTag);

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
  }, [selectedCaja, movPage, filtroFechaDesde, filtroFechaHasta, filtroTipo, filtroCategoria, debouncedBusqueda, filtroTag]);

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
      const { data } = await api.get('/admin/empresas');
      setEmpresas(data);
    } catch {
      setEmpresas([]);
    }
  }, []);

  const fetchTags = useCallback(async () => {
    try {
      const { data } = await api.get('/administracion-caja/tags');
      setTags(data);
    } catch {
      setTags([]);
    }
  }, []);

  useEffect(() => { fetchCajas(); fetchCategorias(); fetchTags(); }, [fetchCajas, fetchCategorias, fetchTags]);
  useEffect(() => { if (view === 'detail') fetchMovimientos(); }, [view, fetchMovimientos]);

  // Reset page when filters change
  useEffect(() => { setMovPage(1); }, [filtroFechaDesde, filtroFechaHasta, filtroTipo, filtroCategoria, debouncedBusqueda, filtroTag]);

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
    setFiltroTag('');
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

  // ── Classification Modal (T6) ──
  const handleOpenClasificacion = (mov) => {
    setClasificacionMov(mov);
    setClasificacionCatId(mov.categoria_id ? String(mov.categoria_id) : '');
    setClasificacionTagIds(mov.tags ? mov.tags.map(t => t.id) : []);
    setNewTagNombre('');
    setNewTagColor('#3b82f6');
    setFormError(null);
    setShowClasificacionModal(true);
  };

  const handleToggleClasificacionTag = (tagId) => {
    setClasificacionTagIds(prev =>
      prev.includes(tagId) ? prev.filter(id => id !== tagId) : [...prev, tagId]
    );
  };

  const handleCreateTagInline = async () => {
    if (!newTagNombre.trim()) return;
    setCreatingTag(true);
    try {
      const { data } = await api.post('/administracion-caja/tags', {
        nombre: newTagNombre.trim(),
        color: newTagColor,
      });
      await fetchTags();
      setClasificacionTagIds(prev => [...prev, data.id]);
      setNewTagNombre('');
      setNewTagColor('#3b82f6');
    } catch (err) {
      setFormError(err.response?.data?.detail || 'Error al crear tag');
    } finally {
      setCreatingTag(false);
    }
  };

  const handleSaveClasificacion = async () => {
    if (!clasificacionMov) return;
    setSavingClasificacion(true);
    setFormError(null);
    try {
      const payload = {
        tag_ids: clasificacionTagIds,
      };
      if (clasificacionCatId) {
        payload.categoria_id = Number(clasificacionCatId);
      } else if (clasificacionMov.categoria_id) {
        payload.clear_categoria = true;
      }
      await api.patch(`/administracion-caja/movimientos/${clasificacionMov.id}/clasificacion`, payload);
      setShowClasificacionModal(false);
      fetchMovimientos();
    } catch (err) {
      setFormError(err.response?.data?.detail || 'Error al guardar clasificación');
    } finally {
      setSavingClasificacion(false);
    }
  };

  // ── Tag Management (T7) ──
  const handleCreateTagMgmt = async (e) => {
    e.preventDefault();
    if (!tagMgmtNombre.trim()) {
      setFormError('Nombre es requerido');
      return;
    }
    setSavingTagMgmt(true);
    setFormError(null);
    try {
      await api.post('/administracion-caja/tags', {
        nombre: tagMgmtNombre.trim(),
        color: tagMgmtColor,
      });
      setTagMgmtNombre('');
      setTagMgmtColor('#3b82f6');
      fetchTags();
    } catch (err) {
      setFormError(err.response?.data?.detail || 'Error al crear tag');
    } finally {
      setSavingTagMgmt(false);
    }
  };

  const handleToggleTagActivo = async (tag) => {
    setTogglingTagId(tag.id);
    try {
      await api.put(`/administracion-caja/tags/${tag.id}`, { activo: !tag.activo });
      fetchTags();
    } catch {
      // silently fail
    } finally {
      setTogglingTagId(null);
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
            {canManage && (
              <button className={styles.btnPrimary} onClick={() => { setView('tags'); setFormError(null); }}>
                <Tag size={16} /> Tags
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

  // ── TAGS MANAGEMENT VIEW (T7) ──
  if (view === 'tags') {
    return (
      <div className={styles.container}>
        <div className={styles.header}>
          <div className={styles.headerLeft}>
            <button className={styles.backBtn} onClick={handleBackToList}><ArrowLeft size={16} /> Volver</button>
            <h1 className={styles.title}>Tags de Caja</h1>
            <span className={styles.badge}>{tags.length}</span>
          </div>
        </div>

        {/* New tag form */}
        {canManage && (
          <form onSubmit={handleCreateTagMgmt} className={styles.tagMgmtForm}>
            <input className={styles.input} placeholder="Nombre del tag..." value={tagMgmtNombre} onChange={e => setTagMgmtNombre(e.target.value)} />
            <input type="color" className={styles.colorInput} value={tagMgmtColor} onChange={e => setTagMgmtColor(e.target.value)} title="Color del tag" />
            <button type="submit" className={styles.btnSuccess} disabled={savingTagMgmt}><Plus size={14} /> Crear</button>
          </form>
        )}
        {formError && <div className={styles.formError}>{formError}</div>}

        <div className={styles.tableWrapper}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Color</th>
                <th>Nombre</th>
                <th>Estado</th>
                {canManage && <th>Acciones</th>}
              </tr>
            </thead>
            <tbody>
              {tags.map(tag => (
                <tr key={tag.id}>
                  <td><span className={styles.tagColorPreview} style={{ backgroundColor: tag.color || 'var(--cf-bg-hover)' }} /></td>
                  <td className={styles.catNombreTd}>{tag.nombre}</td>
                  <td className={tag.activo ? styles.catEstadoActiva : styles.catEstadoInactiva}>
                    {tag.activo ? 'Activo' : 'Inactivo'}
                  </td>
                  {canManage && (
                    <td>
                      <button
                        className={styles.toggleActivoBtn}
                        onClick={() => handleToggleTagActivo(tag)}
                        disabled={togglingTagId === tag.id}
                      >
                        {togglingTagId === tag.id ? '...' : tag.activo ? 'Desactivar' : 'Activar'}
                      </button>
                    </td>
                  )}
                </tr>
              ))}
              {tags.length === 0 && (
                <tr><td colSpan={canManage ? 4 : 3} className={styles.emptyState}>No hay tags creados</td></tr>
              )}
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
        <select className={styles.select} value={filtroTag} onChange={e => setFiltroTag(e.target.value)}>
          <option value="">Todos los tags</option>
          {tags.filter(t => t.activo).map(t => <option key={t.id} value={t.id}>{t.nombre}</option>)}
        </select>
        <div className={styles.searchWrapper}>
          <SearchInput
            value={filtroBusqueda}
            onChange={setFiltroBusqueda}
            placeholder="Buscar en detalle..."
            size="sm"
          />
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
                <th>Tags</th>
                <th>Origen</th>
                <th></th>
                {canManage && <th></th>}
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
                  <td>
                    <div className={styles.tagsCell}>
                      {mov.tags && mov.tags.length > 0 ? mov.tags.map(t => (
                        <span
                          key={t.id}
                          className={t.color ? styles.tagChip : styles.tagChipNeutral}
                          style={t.color ? { backgroundColor: t.color } : undefined}
                        >
                          {t.nombre}
                        </span>
                      )) : <span className={styles.tdSecondary}>—</span>}
                    </div>
                  </td>
                  <td className={styles.tdMeta}>{mov.origen}</td>
                  <td>
                    {mov.documentos_count > 0 && (
                      <span className={styles.docIndicator} title={`${mov.documentos_count} documento(s)`}>
                        <Paperclip size={12} /> {mov.documentos_count}
                      </span>
                    )}
                    {/* COMPRAS-7.6: drill-down a OP cuando el mov está asociado a orden_pago */}
                    {mov.entidad_tipo === 'orden_pago' && mov.entidad_id && (
                      <button
                        type="button"
                        className={styles.verOpBtn}
                        onClick={() =>
                          navigate(`/administracion/compras?tab=ordenes-pago&op_id=${mov.entidad_id}`)
                        }
                        title={`Ver OP #${mov.entidad_id}`}
                      >
                        <ExternalLink size={12} /> Ver OP
                      </button>
                    )}
                  </td>
                  {canManage && (
                    <td>
                      <button className={styles.editBtn} onClick={() => handleOpenClasificacion(mov)} aria-label="Clasificar movimiento">
                        <Pencil size={14} />
                      </button>
                    </td>
                  )}
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

      {/* ── Classification Modal (T6) ── */}
      {showClasificacionModal && clasificacionMov && (
        <div className={styles.modalOverlay}>
          <div className={styles.modalContentWide}>
            <div className={styles.modalHeader}>
              <span className={styles.modalTitle}>Clasificar Movimiento</span>
              <button className={styles.modalCloseBtn} onClick={() => setShowClasificacionModal(false)}><X size={18} /></button>
            </div>

            {/* Movement info header */}
            <div className={styles.clasificacionHeader}>
              <div><span>Fecha: </span><strong>{formatDate(clasificacionMov.fecha)}</strong></div>
              <div><span>Tipo: </span><strong>{clasificacionMov.tipo}</strong></div>
              <div><span>Detalle: </span><strong>{clasificacionMov.detalle}</strong></div>
              <div><span>Monto: </span><strong>{formatCurrency(clasificacionMov.monto, selectedCaja?.moneda)}</strong></div>
            </div>

            {formError && <div className={styles.formError}>{formError}</div>}

            {/* Category dropdown */}
            <div className={styles.formGroup}>
              <label className={styles.formLabel}>Categoría</label>
              <select className={styles.formSelect} value={clasificacionCatId} onChange={e => setClasificacionCatId(e.target.value)}>
                <option value="">Sin categoría</option>
                {activeCategorias
                  .filter(c => c.tipo_aplicable === 'ambos' || c.tipo_aplicable === clasificacionMov.tipo)
                  .map(c => <option key={c.id} value={c.id}>{c.nombre}</option>)
                }
              </select>
            </div>

            {/* Tags toggle grid */}
            <div className={styles.formGroup}>
              <label className={styles.formLabel}>Tags</label>
              <div className={styles.tagToggleGrid}>
                {tags.filter(t => t.activo).map(t => {
                  const isActive = clasificacionTagIds.includes(t.id);
                  return (
                    <button
                      key={t.id}
                      type="button"
                      className={isActive ? styles.tagToggleActive : styles.tagToggle}
                      style={isActive && t.color ? { backgroundColor: t.color, borderColor: t.color } : undefined}
                      onClick={() => handleToggleClasificacionTag(t.id)}
                    >
                      {t.nombre}
                    </button>
                  );
                })}
                {tags.filter(t => t.activo).length === 0 && (
                  <span className={styles.tdSecondary}>No hay tags creados</span>
                )}
              </div>

              {/* Inline create tag */}
              <div className={styles.tagCreateRow}>
                <input
                  className={styles.input}
                  placeholder="Nuevo tag..."
                  value={newTagNombre}
                  onChange={e => setNewTagNombre(e.target.value)}
                />
                <input
                  type="color"
                  className={styles.colorInput}
                  value={newTagColor}
                  onChange={e => setNewTagColor(e.target.value)}
                  title="Color del tag"
                />
                <button
                  type="button"
                  className={styles.btnPrimary}
                  onClick={handleCreateTagInline}
                  disabled={creatingTag || !newTagNombre.trim()}
                >
                  <Plus size={14} /> {creatingTag ? '...' : 'Crear'}
                </button>
              </div>
            </div>

            <div className={styles.formActions}>
              <button type="button" className={styles.btnPrimary} onClick={() => setShowClasificacionModal(false)}>Cancelar</button>
              <button type="button" className={styles.btnSuccess} onClick={handleSaveClasificacion} disabled={savingClasificacion}>
                {savingClasificacion ? 'Guardando...' : 'Guardar'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
