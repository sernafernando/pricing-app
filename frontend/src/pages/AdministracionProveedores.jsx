import { useState, useEffect, useCallback } from 'react';
import { usePermisos } from '../contexts/PermisosContext';
import api from '../services/api';
import styles from './AdministracionProveedores.module.css';
import { registrarPagina } from '../registry/tabRegistry';
import {
  Building2,
  Search,
  Plus,
  RefreshCw,
  FileSearch,
  ChevronLeft,
  AlertCircle,
  CheckCircle,
  XCircle,
  Loader2,
  ExternalLink,
  X,
} from 'lucide-react';

registrarPagina({
  pagePath: '/administracion/proveedores',
  pageLabel: 'Administración - Proveedores',
  tabs: [],
});

export default function AdministracionProveedores() {
  const { tienePermiso } = usePermisos();

  // ── Estado lista ───────────────────────────────────────────────
  const [proveedores, setProveedores] = useState([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState('');
  const [searchInput, setSearchInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [soloActivos, setSoloActivos] = useState(true);

  // ── Estado detalle ─────────────────────────────────────────────
  const [selectedId, setSelectedId] = useState(null);
  const [detalle, setDetalle] = useState(null);
  const [loadingDetalle, setLoadingDetalle] = useState(false);

  // ── Estado AFIP ────────────────────────────────────────────────
  const [consultandoAfip, setConsultandoAfip] = useState(false);
  const [afipResult, setAfipResult] = useState(null);
  const [afipError, setAfipError] = useState(null);

  // ── Estado sync ────────────────────────────────────────────────
  const [syncing, setSyncing] = useState(false);
  const [syncResult, setSyncResult] = useState(null);

  // ── Estado modal crear ─────────────────────────────────────────
  const [showCrear, setShowCrear] = useState(false);
  const [crearForm, setCrearForm] = useState({ nombre: '', cuit: '', telefono: '', email: '' });
  const [creando, setCreando] = useState(false);
  const [crearError, setCrearError] = useState(null);

  const PAGE_SIZE = 50;

  // ── Fetch lista ────────────────────────────────────────────────
  const fetchProveedores = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({
        page: String(page),
        page_size: String(PAGE_SIZE),
        solo_activos: String(soloActivos),
      });
      if (search) params.set('search', search);

      const { data } = await api.get(`/administracion/proveedores?${params}`);
      setProveedores(data.proveedores);
      setTotal(data.total);
    } catch {
      setProveedores([]);
      setTotal(0);
    } finally {
      setLoading(false);
    }
  }, [page, search, soloActivos]);

  useEffect(() => {
    fetchProveedores();
  }, [fetchProveedores]);

  // ── Fetch detalle ──────────────────────────────────────────────
  const fetchDetalle = useCallback(async (id) => {
    setLoadingDetalle(true);
    setAfipResult(null);
    setAfipError(null);
    try {
      const { data } = await api.get(`/administracion/proveedores/${id}`);
      setDetalle(data);
    } catch {
      setDetalle(null);
    } finally {
      setLoadingDetalle(false);
    }
  }, []);

  useEffect(() => {
    if (selectedId) fetchDetalle(selectedId);
  }, [selectedId, fetchDetalle]);

  // ── Handlers ───────────────────────────────────────────────────
  const handleSearch = (e) => {
    e.preventDefault();
    setPage(1);
    setSearch(searchInput);
  };

  const handleConsultarAfip = async () => {
    if (!selectedId) return;
    setConsultandoAfip(true);
    setAfipResult(null);
    setAfipError(null);
    try {
      const { data } = await api.post(`/administracion/proveedores/${selectedId}/consultar-afip`);
      setAfipResult(data);
      // Refrescar detalle para ver datos actualizados
      fetchDetalle(selectedId);
    } catch (err) {
      const detail = err.response?.data?.detail;
      setAfipError(typeof detail === 'object' ? detail.message : (detail || 'Error consultando AFIP'));
    } finally {
      setConsultandoAfip(false);
    }
  };

  const handleSyncErp = async () => {
    setSyncing(true);
    setSyncResult(null);
    try {
      const { data } = await api.post('/administracion/proveedores/sync-erp');
      setSyncResult(data);
      fetchProveedores();
    } catch {
      setSyncResult({ success: false, error: 'Error sincronizando' });
    } finally {
      setSyncing(false);
    }
  };

  const handleCrear = async (e) => {
    e.preventDefault();
    if (!crearForm.nombre.trim()) return;
    setCreando(true);
    setCrearError(null);
    try {
      await api.post('/administracion/proveedores', crearForm);
      setShowCrear(false);
      setCrearForm({ nombre: '', cuit: '', telefono: '', email: '' });
      fetchProveedores();
    } catch (err) {
      setCrearError(err.response?.data?.detail || 'Error creando proveedor');
    } finally {
      setCreando(false);
    }
  };

  const totalPages = Math.ceil(total / PAGE_SIZE);

  // ── Render ─────────────────────────────────────────────────────
  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <div className={styles.headerLeft}>
          <Building2 size={28} />
          <h1 className={styles.title}>Proveedores</h1>
          <span className={styles.badge}>{total}</span>
        </div>
        <div className={styles.headerActions}>
          {tienePermiso('administracion.gestionar_proveedores') && (
            <>
              <button
                className={styles.btnSecondary}
                onClick={handleSyncErp}
                disabled={syncing}
              >
                <RefreshCw size={16} className={syncing ? styles.spinning : ''} />
                {syncing ? 'Sincronizando...' : 'Sync ERP'}
              </button>
              <button
                className={styles.btnPrimary}
                onClick={() => setShowCrear(true)}
              >
                <Plus size={16} />
                Nuevo Proveedor
              </button>
            </>
          )}
        </div>
      </div>

      {/* Sync result */}
      {syncResult && (
        <div className={syncResult.success ? styles.alertSuccess : styles.alertError}>
          {syncResult.success ? (
            <>
              <CheckCircle size={16} />
              Sync completado: {syncResult.insertados} nuevos, {syncResult.actualizados} actualizados,
              {' '}{syncResult.vinculados_rma} vinculados RMA
            </>
          ) : (
            <><AlertCircle size={16} /> {syncResult.error}</>
          )}
          <button className={styles.alertClose} onClick={() => setSyncResult(null)}>
            <X size={14} />
          </button>
        </div>
      )}

      {/* Search bar */}
      <div className={styles.searchBar}>
        <form onSubmit={handleSearch} className={styles.searchForm}>
          <Search size={18} className={styles.searchIcon} />
          <input
            type="text"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            placeholder="Buscar por nombre, CUIT o ciudad..."
            className={styles.searchInput}
          />
        </form>
        <label className={styles.checkLabel}>
          <input
            type="checkbox"
            checked={soloActivos}
            onChange={(e) => { setSoloActivos(e.target.checked); setPage(1); }}
          />
          Solo activos
        </label>
      </div>

      <div className={styles.layout}>
        {/* ── LISTA ──────────────────────────────────────── */}
        <div className={styles.listPanel}>
          {loading ? (
            <div className={styles.loadingState}>
              <Loader2 size={24} className={styles.spinning} />
              Cargando proveedores...
            </div>
          ) : proveedores.length === 0 ? (
            <div className={styles.emptyState}>
              No se encontraron proveedores
            </div>
          ) : (
            <>
              <div className={styles.listItems}>
                {proveedores.map((p) => (
                  <div
                    key={p.id}
                    className={`${styles.listItem} ${selectedId === p.id ? styles.listItemActive : ''}`}
                    onClick={() => setSelectedId(p.id)}
                  >
                    <div className={styles.listItemMain}>
                      <span className={styles.listItemName}>{p.nombre}</span>
                      {p.condicion_iva && (
                        <span className={`${styles.tag} ${styles[`tag${p.condicion_iva.replace(/\s/g, '')}`] || ''}`}>
                          {p.condicion_iva}
                        </span>
                      )}
                    </div>
                    <div className={styles.listItemSub}>
                      {p.cuit && <span>CUIT: {p.cuit}</span>}
                      {p.estado_clave && (
                        <span className={p.estado_clave === 'ACTIVO' ? styles.textSuccess : styles.textDanger}>
                          {p.estado_clave}
                        </span>
                      )}
                      <span className={styles.textMuted}>{p.origen}</span>
                    </div>
                  </div>
                ))}
              </div>

              {/* Paginación */}
              {totalPages > 1 && (
                <div className={styles.pagination}>
                  <button
                    disabled={page <= 1}
                    onClick={() => setPage(page - 1)}
                    className={styles.pageBtn}
                  >
                    Anterior
                  </button>
                  <span className={styles.pageInfo}>
                    Página {page} de {totalPages}
                  </span>
                  <button
                    disabled={page >= totalPages}
                    onClick={() => setPage(page + 1)}
                    className={styles.pageBtn}
                  >
                    Siguiente
                  </button>
                </div>
              )}
            </>
          )}
        </div>

        {/* ── DETALLE ────────────────────────────────────── */}
        <div className={styles.detailPanel}>
          {!selectedId ? (
            <div className={styles.emptyDetail}>
              <FileSearch size={48} />
              <p>Seleccioná un proveedor para ver sus datos</p>
            </div>
          ) : loadingDetalle ? (
            <div className={styles.loadingState}>
              <Loader2 size={24} className={styles.spinning} />
              Cargando detalle...
            </div>
          ) : detalle ? (
            <div className={styles.detail}>
              {/* Header detalle */}
              <div className={styles.detailHeader}>
                <button className={styles.btnBack} onClick={() => setSelectedId(null)}>
                  <ChevronLeft size={16} /> Volver
                </button>
                <h2 className={styles.detailTitle}>{detalle.nombre}</h2>
                {detalle.estado_clave && (
                  <span className={detalle.estado_clave === 'ACTIVO' ? styles.badgeSuccess : styles.badgeDanger}>
                    {detalle.estado_clave}
                  </span>
                )}
              </div>

              {/* Datos generales */}
              <div className={styles.detailSection}>
                <h3 className={styles.sectionTitle}>Datos Generales</h3>
                <div className={styles.fieldGrid}>
                  <Field label="CUIT" value={detalle.cuit} />
                  <Field label="Origen" value={detalle.origen === 'erp' ? 'ERP (GBP)' : 'Manual'} />
                  {detalle.telefono && <Field label="Teléfono" value={detalle.telefono} />}
                  {detalle.email && <Field label="Email" value={detalle.email} />}
                  {detalle.direccion && <Field label="Dirección" value={detalle.direccion} />}
                  {detalle.ciudad && <Field label="Ciudad" value={detalle.ciudad} />}
                  {detalle.provincia && <Field label="Provincia" value={detalle.provincia} />}
                  {detalle.cp && <Field label="CP" value={detalle.cp} />}
                  {detalle.representante && <Field label="Representante" value={detalle.representante} />}
                </div>
                {detalle.notas && (
                  <div className={styles.fieldFull}>
                    <span className={styles.fieldLabel}>Notas</span>
                    <span className={styles.fieldValue}>{detalle.notas}</span>
                  </div>
                )}
              </div>

              {/* Datos fiscales AFIP */}
              <div className={styles.detailSection}>
                <div className={styles.sectionHeader}>
                  <h3 className={styles.sectionTitle}>Datos Fiscales (AFIP)</h3>
                  {tienePermiso('administracion.consultar_afip') && detalle.cuit && (
                    <button
                      className={styles.btnAfip}
                      onClick={handleConsultarAfip}
                      disabled={consultandoAfip}
                    >
                      {consultandoAfip ? (
                        <><Loader2 size={14} className={styles.spinning} /> Consultando...</>
                      ) : (
                        <><ExternalLink size={14} /> Consultar AFIP</>
                      )}
                    </button>
                  )}
                </div>

                {/* AFIP result/error */}
                {afipResult && (
                  <div className={styles.alertSuccess}>
                    <CheckCircle size={16} />
                    Consulta exitosa — {afipResult.condicion_iva} | Ganancias: {afipResult.inscripto_ganancias ? 'Sí' : 'No'}
                  </div>
                )}
                {afipError && (
                  <div className={styles.alertError}>
                    <AlertCircle size={16} />
                    {afipError}
                  </div>
                )}

                {detalle.datos_fiscales ? (
                  <DatosFiscalesView datos={detalle.datos_fiscales} />
                ) : (
                  <div className={styles.emptyFiscal}>
                    {detalle.cuit
                      ? 'No hay datos fiscales cargados. Hacé clic en "Consultar AFIP" para obtenerlos.'
                      : 'Este proveedor no tiene CUIT cargado. Cargá el CUIT primero para poder consultar AFIP.'}
                  </div>
                )}
              </div>
            </div>
          ) : null}
        </div>
      </div>

      {/* ── MODAL CREAR ──────────────────────────────────── */}
      {showCrear && (
        <div className={styles.modalOverlay} onClick={() => setShowCrear(false)}>
          <div className={styles.modalContent} onClick={(e) => e.stopPropagation()}>
            <div className={styles.modalHeader}>
              <h2>Nuevo Proveedor</h2>
              <button className={styles.modalClose} onClick={() => setShowCrear(false)}>
                <X size={20} />
              </button>
            </div>
            <form onSubmit={handleCrear} className={styles.modalBody}>
              {crearError && (
                <div className={styles.alertError}>
                  <AlertCircle size={16} /> {crearError}
                </div>
              )}
              <div className={styles.formGroup}>
                <label className={styles.formLabel}>Nombre *</label>
                <input
                  className={styles.formInput}
                  value={crearForm.nombre}
                  onChange={(e) => setCrearForm({ ...crearForm, nombre: e.target.value })}
                  required
                  autoFocus
                />
              </div>
              <div className={styles.formGroup}>
                <label className={styles.formLabel}>CUIT</label>
                <input
                  className={styles.formInput}
                  value={crearForm.cuit}
                  onChange={(e) => setCrearForm({ ...crearForm, cuit: e.target.value })}
                  placeholder="30-12345678-9"
                />
              </div>
              <div className={styles.formRow}>
                <div className={styles.formGroup}>
                  <label className={styles.formLabel}>Teléfono</label>
                  <input
                    className={styles.formInput}
                    value={crearForm.telefono}
                    onChange={(e) => setCrearForm({ ...crearForm, telefono: e.target.value })}
                  />
                </div>
                <div className={styles.formGroup}>
                  <label className={styles.formLabel}>Email</label>
                  <input
                    className={styles.formInput}
                    type="email"
                    value={crearForm.email}
                    onChange={(e) => setCrearForm({ ...crearForm, email: e.target.value })}
                  />
                </div>
              </div>
              <div className={styles.modalActions}>
                <button type="button" className={styles.btnSecondary} onClick={() => setShowCrear(false)}>
                  Cancelar
                </button>
                <button type="submit" className={styles.btnPrimary} disabled={creando}>
                  {creando ? 'Creando...' : 'Crear Proveedor'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Componentes internos ─────────────────────────────────────────

function Field({ label, value }) {
  return (
    <div className={styles.field}>
      <span className={styles.fieldLabel}>{label}</span>
      <span className={styles.fieldValue}>{value || '—'}</span>
    </div>
  );
}

function DatosFiscalesView({ datos }) {
  const impuestosActivos = (datos.impuestos || []).filter(
    (i) => (i.estado || '').toUpperCase() === 'ACTIVO'
  );
  const regimenesActivos = (datos.regimenes || []).filter(
    (r) => (r.estado || '').toUpperCase() === 'ACTIVO'
  );

  return (
    <div className={styles.fiscalData}>
      {datos.wsid_consultado === 'ws_sr_padron_a13' && (
        <div className={styles.alertWarning}>
          <AlertCircle size={16} />
          Datos parciales (Padrón A13). Condición IVA y Ganancias requieren Padrón A4 (pendiente de habilitación en ARCA).
        </div>
      )}
      <div className={styles.fieldGrid}>
        {datos.condicion_iva !== null && datos.condicion_iva !== undefined && (
          <Field label="Condición IVA" value={datos.condicion_iva} />
        )}
        {datos.inscripto_ganancias !== null && datos.inscripto_ganancias !== undefined && (
          <Field label="Inscripto Ganancias" value={datos.inscripto_ganancias ? 'Sí' : 'No'} />
        )}
        <Field label="Estado Clave" value={datos.estado_clave} />
        <Field label="Tipo Persona" value={datos.tipo_persona} />
        <Field label="Forma Jurídica" value={datos.forma_juridica} />
        <Field label="Razón Social (AFIP)" value={datos.razon_social_afip} />
        <Field label="Actividad Principal" value={datos.actividad_principal} />
        <Field label="Domicilio Fiscal" value={datos.domicilio_fiscal} />
        <Field label="CP Fiscal" value={datos.domicilio_fiscal_cp} />
        <Field label="Provincia Fiscal" value={datos.domicilio_fiscal_provincia} />
        <Field
          label="Última Consulta"
          value={datos.ultima_consulta_afip
            ? new Date(datos.ultima_consulta_afip).toLocaleString('es-AR')
            : null}
        />
      </div>

      {datos.ultimo_error_afip && (
        <div className={styles.alertError} style={{ marginTop: '12px' }}>
          <AlertCircle size={16} />
          Último error: {datos.ultimo_error_afip}
        </div>
      )}

      {/* Impuestos activos */}
      {impuestosActivos.length > 0 && (
        <div className={styles.subSection}>
          <h4 className={styles.subSectionTitle}>Impuestos Inscriptos (Activos)</h4>
          <div className={styles.tagList}>
            {impuestosActivos.map((imp, i) => (
              <span key={i} className={styles.tagImpuesto}>
                {imp.descripcionImpuesto || `ID ${imp.idImpuesto}`}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Regímenes activos */}
      {regimenesActivos.length > 0 && (
        <div className={styles.subSection}>
          <h4 className={styles.subSectionTitle}>Regímenes Retención/Percepción (Activos)</h4>
          <table className={styles.miniTable}>
            <thead>
              <tr>
                <th>Régimen</th>
                <th>Tipo</th>
                <th>Impuesto</th>
              </tr>
            </thead>
            <tbody>
              {regimenesActivos.map((reg, i) => (
                <tr key={i}>
                  <td>{reg.descripcionRegimen || `ID ${reg.idRegimen}`}</td>
                  <td>{reg.tipoRegimen || '—'}</td>
                  <td>{reg.idImpuesto}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
