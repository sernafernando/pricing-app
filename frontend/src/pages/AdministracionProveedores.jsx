import { useState, useEffect, useCallback, useRef } from 'react';
import { usePermisos } from '../contexts/PermisosContext';
import api from '../services/api';
import styles from './AdministracionProveedores.module.css';
import { registrarPagina } from '../registry/tabRegistry';
import {
  Building2,
  Plus,
  RefreshCw,
  FileSearch,
  ChevronLeft,
  AlertCircle,
  CheckCircle,
  Loader2,
  ExternalLink,
  X,
  MapPin,
  Landmark,
  Users,
  Tag,
  Eye,
  EyeOff,
} from 'lucide-react';
import SearchInput from '../components/SearchInput';
import { useSSEChannel } from '../hooks/useSSEChannel';

registrarPagina({
  pagePath: '/administracion/proveedores',
  pageLabel: 'Administración - Proveedores',
  tabs: [],
});

/**
 * Cota máxima de espera del resultado del sync full por SSE.
 *
 * La entrega por SSE es best-effort por diseño: el backend traga los errores de
 * publicación y, si Redis nunca se configuró, ni siquiera publica. Sin esta cota
 * un evento perdido dejaría el botón deshabilitado hasta recargar la página.
 *
 * 90 s cubre con margen la cadena real del job: la consulta al ERP tiene un
 * timeout de 30 s en `erp_worker_client` y después se persiste toda la tabla de
 * proveedores (mirror + proyección + RMA) en un worker thread.
 */
const SYNC_SSE_TIMEOUT_MS = 90_000;

/**
 * ¿Este evento SSE pertenece a la corrida que disparó ESTA pestaña?
 *
 * `proveedores:sync` es un canal de broadcast global: publica ahí el job de
 * cualquier usuario. Sin correlación, el sync de otro operador (o un job viejo
 * que llega tarde) limpiaba el banner de esta pestaña, cancelaba su timeout y
 * renderizaba contadores ajenos como propios.
 *
 * @param {object} evento - payload del evento SSE.
 * @param {string|null} runIdEsperado - `run_id` que devolvió la 202 de esta
 *   corrida. `null` cuando no hay ninguna corrida propia esperando resultado:
 *   ahí todo evento es ajeno. La cadena vacía marca el caso degradado en que el
 *   backend no devolvió `run_id` (deploy viejo): sin identificador no hay
 *   correlación posible y se conserva el comportamiento anterior de aceptar el
 *   evento, en vez de dejar la UI colgada hasta el timeout.
 * @returns {boolean}
 */
const eventoDeEstaCorrida = (evento, runIdEsperado) => {
  if (runIdEsperado === null) return false;
  if (runIdEsperado === '') return true;
  return evento?.run_id === runIdEsperado;
};

export default function AdministracionProveedores() {
  const { tienePermiso } = usePermisos();

  // ── Estado lista ───────────────────────────────────────────────
  const [proveedores, setProveedores] = useState([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState('');
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
  // El sync full se encola en el backend (202) y publica su resultado por SSE:
  // `syncing` queda en true hasta que llega el evento, no hasta que responde
  // el POST. El sync puntual (`supp_id`) sigue siendo sincrónico.
  const [syncing, setSyncing] = useState(false);
  const [syncResult, setSyncResult] = useState(null);
  const [syncEnCurso, setSyncEnCurso] = useState(false);
  // El resultado no llegó dentro de la ventana de espera. NO significa que el
  // sync haya fallado: casi seguro terminó bien y se perdió la notificación.
  const [syncSinConfirmar, setSyncSinConfirmar] = useState(false);

  // Correlación entre el POST y el evento SSE. La suscripción SSE está siempre
  // viva, así que un job rápido puede publicar su resultado ANTES de que el POST
  // resuelva; sin esta correlación el `setSyncEnCurso(true)` posterior pisaría un
  // resultado ya recibido y dejaría la UI trabada en "en curso" para siempre.
  const syncRunIdRef = useRef(0); // corrida local actual (se incrementa en cada click)
  const syncResueltoRef = useRef(0); // última corrida local cuyo resultado ya llegó
  const syncTimeoutRef = useRef(null);

  // `run_id` que devolvió la 202: identifica la corrida del SERVIDOR y es lo
  // único que permite distinguir nuestro evento del de otro usuario. `null`
  // mientras no haya corrida propia esperando resultado.
  const syncRunIdServidorRef = useRef(null);
  // El POST sigue en vuelo: todavía NO conocemos el `run_id`, así que ningún
  // evento se puede correlacionar todavía.
  const syncPostEnVueloRef = useRef(false);
  // Eventos llegados mientras el POST estaba en vuelo. Se guardan TODOS en vez
  // de aplicarlos o descartarlos a ciegas: cuando llegue la 202 con el `run_id`
  // recién ahí se puede decidir honestamente cuál era nuestro. Es una lista y
  // no un slot único porque un evento ajeno posterior no puede pisar al propio.
  const syncEventosPendientesRef = useRef([]);

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
  const handleSearchChange = (value) => {
    setPage(1);
    setSearch(value);
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

  const limpiarTimeoutSync = useCallback(() => {
    if (syncTimeoutRef.current) {
      clearTimeout(syncTimeoutRef.current);
      syncTimeoutRef.current = null;
    }
  }, []);

  // Sin timers colgados ni setState sobre un componente ya desmontado.
  useEffect(() => limpiarTimeoutSync, [limpiarTimeoutSync]);

  /** Aplica un resultado de sync YA correlacionado con esta corrida. */
  const aplicarResultadoSync = useCallback(
    (data) => {
      // Marca la corrida en vuelo como resuelta ANTES de tocar el estado: si el
      // POST todavía no resolvió, su `setSyncEnCurso(true)` posterior se descarta.
      syncResueltoRef.current = syncRunIdRef.current;
      syncEventosPendientesRef.current = [];
      // La corrida ya no espera nada: cualquier evento posterior (una
      // re-entrega, o el sync de otro usuario) vuelve a ser ajeno.
      syncRunIdServidorRef.current = null;
      limpiarTimeoutSync();
      setSyncEnCurso(false);
      setSyncSinConfirmar(false);
      setSyncResult(data);
      if (data?.success) fetchProveedores();
    },
    [fetchProveedores, limpiarTimeoutSync],
  );

  const handleSyncErp = async () => {
    const runId = syncRunIdRef.current + 1;
    syncRunIdRef.current = runId;
    syncRunIdServidorRef.current = null;
    syncEventosPendientesRef.current = [];
    syncPostEnVueloRef.current = true;
    limpiarTimeoutSync();
    setSyncing(true);
    setSyncResult(null);
    setSyncEnCurso(false);
    setSyncSinConfirmar(false);
    try {
      const { status, data } = await api.post('/administracion/proveedores/sync-erp');
      if (status === 202) {
        // Sync full encolado: los contadores reales llegan por SSE.
        if (syncRunIdRef.current !== runId) return; // hubo otro click más nuevo
        // Cadena vacía = el backend no mandó `run_id` (deploy viejo): sin
        // identificador no hay correlación posible, ver `eventoDeEstaCorrida`.
        const runIdServidor = data?.run_id ?? '';
        syncRunIdServidorRef.current = runIdServidor;
        syncPostEnVueloRef.current = false;

        // Reconciliación de los eventos tempranos: el job puede haber publicado
        // su resultado ANTES de que la 202 llegara. Esos eventos quedaron en el
        // buffer porque no se podían correlacionar todavía; recién ahora
        // conocemos el `run_id` y se puede buscar el nuestro entre ellos.
        const pendientes = syncEventosPendientesRef.current;
        syncEventosPendientesRef.current = [];
        const propio = pendientes.find((evento) => eventoDeEstaCorrida(evento, runIdServidor));
        if (propio) {
          aplicarResultadoSync(propio);
          return;
        }

        // Si el evento ya se aplicó, esta corrida está resuelta y marcarla
        // "en curso" ahora sería un dato viejo.
        if (syncResueltoRef.current === runId) return;
        setSyncEnCurso(true);
        // La notificación puede perderse: liberamos la UI al vencer la ventana.
        syncTimeoutRef.current = setTimeout(() => {
          syncTimeoutRef.current = null;
          setSyncEnCurso(false);
          setSyncSinConfirmar(true);
        }, SYNC_SSE_TIMEOUT_MS);
        return;
      }
      setSyncResult(data);
      fetchProveedores();
    } catch (err) {
      // El backend normaliza los errores al envelope `{ error: { code, message } }`;
      // `detail` queda como fallback para las rutas legacy.
      const { error, detail } = err.response?.data ?? {};
      const mensaje = error?.message ?? (typeof detail === 'object' ? detail?.message : detail);
      setSyncResult({ success: false, error: mensaje || 'Error sincronizando con el ERP' });
    } finally {
      // El camino sincrónico y el de error no esperan ningún evento: se cierra
      // la ventana de buffering para que un evento ajeno no quede retenido.
      syncPostEnVueloRef.current = false;
      setSyncing(false);
    }
  };

  // ── Resultado del sync full (llega por SSE cuando el job termina) ──
  const handleSyncEvent = useCallback(
    ({ data }) => {
      // El POST sigue en vuelo: no conocemos el `run_id` con el que comparar.
      // Se retiene el evento y se decide al resolver la 202. Aplicarlo a ciegas
      // sería el bug original (un evento ajeno resuelve nuestra corrida) y
      // descartarlo a ciegas dejaría la UI esperando hasta el timeout un
      // resultado que YA llegó.
      if (syncPostEnVueloRef.current) {
        syncEventosPendientesRef.current.push(data);
        return;
      }

      // Evento de otra corrida (otro usuario, otra pestaña, un job tardío): no
      // limpia el banner, no cancela el timeout y no pisa `syncResult`. Pero un
      // sync ajeno exitoso dejó datos nuevos en la tabla: se refresca en
      // silencio para que esta pestaña no muestre proveedores viejos.
      if (!eventoDeEstaCorrida(data, syncRunIdServidorRef.current)) {
        if (data?.success) fetchProveedores();
        return;
      }

      aplicarResultadoSync(data);
    },
    [aplicarResultadoSync, fetchProveedores],
  );

  useSSEChannel('proveedores:sync', handleSyncEvent);

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
                disabled={syncing || syncEnCurso}
              >
                <RefreshCw size={16} className={syncing || syncEnCurso ? styles.spinning : ''} />
                {syncing || syncEnCurso ? 'Sincronizando...' : 'Sync ERP'}
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

      {/* Sync full encolado: el resultado llega por SSE */}
      {syncEnCurso && (
        <div className={styles.alertInfo} role="status">
          <Loader2 size={16} className={styles.spinning} />
          Sincronización con el ERP en curso. Los resultados aparecen al finalizar.
        </div>
      )}

      {/* El resultado no llegó a tiempo. El sync sigue corriendo en el servidor:
          no se reporta como error, solo como resultado no confirmado. */}
      {syncSinConfirmar && (
        <div className={styles.alertWarning} role="status">
          <AlertCircle size={16} />
          No se pudo confirmar el resultado de la sincronización. Es probable que siga
          ejecutándose en el servidor: actualizá la página en unos minutos para ver el resultado.
          <button
            className={styles.alertClose}
            onClick={() => setSyncSinConfirmar(false)}
            aria-label="Cerrar aviso"
          >
            <X size={14} />
          </button>
        </div>
      )}

      {/* Sync result */}
      {syncResult && (
        <div className={syncResult.success ? styles.alertSuccess : styles.alertError}>
          {syncResult.success ? (
            <>
              <CheckCircle size={16} />
              Sync completado: {syncResult.total_erp} proveedores recibidos del ERP —
              {' '}{syncResult.insertados} nuevos, {syncResult.actualizados} actualizados,
              {' '}{syncResult.rma_insertados} RMA creados, {syncResult.vinculados_rma} RMA vinculados
            </>
          ) : (
            <><AlertCircle size={16} /> {syncResult.error}</>
          )}
          <button
            className={styles.alertClose}
            onClick={() => setSyncResult(null)}
            aria-label="Cerrar resultado del sync"
          >
            <X size={14} />
          </button>
        </div>
      )}

      {/* Search bar */}
      <div className={styles.searchBar}>
        <div className={styles.searchForm}>
          <SearchInput
            value={search}
            onChange={handleSearchChange}
            placeholder="Buscar por nombre, CUIT o ciudad..."
            debounce={300}
          />
        </div>
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
                {tienePermiso('administracion.gestionar_proveedores') && (
                  <button
                    className={detalle.activo ? styles.btnDisable : styles.btnEnable}
                    onClick={async () => {
                      await api.put(`/administracion/proveedores/${detalle.id}`, { activo: !detalle.activo });
                      fetchDetalle(selectedId);
                      fetchProveedores();
                    }}
                  >
                    {detalle.activo ? <><EyeOff size={14} /> Deshabilitar</> : <><Eye size={14} /> Habilitar</>}
                  </button>
                )}
              </div>

              {/* Datos generales */}
              <div className={styles.detailSection}>
                <h3 className={styles.sectionTitle}>Datos Generales</h3>
                <div className={styles.fieldGrid}>
                  <Field label="CUIT" value={detalle.cuit} />
                  {detalle.supp_id && <Field label="ID ERP" value={detalle.supp_id} />}
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

              {/* Direcciones / Depósitos */}
              <DireccionesSection
                proveedorId={detalle.id}
                direcciones={detalle.direcciones || []}
                canEdit={tienePermiso('administracion.gestionar_proveedores')}
                onRefresh={() => fetchDetalle(selectedId)}
              />

              {/* Datos Bancarios */}
              <BancosSection
                proveedorId={detalle.id}
                bancos={detalle.bancos || []}
                canEdit={tienePermiso('administracion.gestionar_proveedores')}
                onRefresh={() => fetchDetalle(selectedId)}
              />

              {/* Contactos */}
              <ContactosSection
                proveedorId={detalle.id}
                contactos={detalle.contactos || []}
                canEdit={tienePermiso('administracion.gestionar_proveedores')}
                onRefresh={() => fetchDetalle(selectedId)}
              />

              {/* Marcas */}
              <MarcasSection proveedorId={detalle.id} />
            </div>
          ) : null}
        </div>
      </div>

      {/* ── MODAL CREAR ──────────────────────────────────── */}
      {showCrear && (
        <div className={styles.modalOverlay}>
          <div className={styles.modalContent}>
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
            ? new Date(datos.ultima_consulta_afip).toLocaleString('es-AR', { hour12: false })
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

// ── Sección Direcciones ──────────────────────────────────────────

function DireccionesSection({ proveedorId, direcciones, canEdit, onRefresh }) {
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ etiqueta: 'Depósito', direccion: '', cp: '', ciudad: '', provincia: '', horario_recepcion: '', contacto_nombre: '', contacto_telefono: '' });
  const [saving, setSaving] = useState(false);

  const handleSave = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      await api.post(`/administracion/proveedores/${proveedorId}/direcciones`, form);
      setShowForm(false);
      setForm({ etiqueta: 'Depósito', direccion: '', cp: '', ciudad: '', provincia: '', horario_recepcion: '', contacto_nombre: '', contacto_telefono: '' });
      onRefresh();
    } catch { /* */ }
    finally { setSaving(false); }
  };

  const handleToggle = async (id) => {
    await api.patch(`/administracion/proveedores/direcciones/${id}/toggle`);
    onRefresh();
  };

  return (
    <div className={styles.detailSection}>
      <div className={styles.sectionHeader}>
        <h3 className={styles.sectionTitle}><MapPin size={16} /> Direcciones / Depósitos</h3>
        {canEdit && (
          <button className={styles.btnSmall} onClick={() => setShowForm(!showForm)}>
            <Plus size={14} /> Agregar
          </button>
        )}
      </div>
      {showForm && (
        <form onSubmit={handleSave} className={styles.inlineForm}>
          <div className={styles.formRow}>
            <input className={styles.formInput} placeholder="Etiqueta (ej: Depósito)" value={form.etiqueta} onChange={(e) => setForm({ ...form, etiqueta: e.target.value })} required />
            <input className={styles.formInput} placeholder="Dirección *" value={form.direccion} onChange={(e) => setForm({ ...form, direccion: e.target.value })} required />
          </div>
          <div className={styles.formRow}>
            <input className={styles.formInput} placeholder="Ciudad" value={form.ciudad} onChange={(e) => setForm({ ...form, ciudad: e.target.value })} />
            <input className={styles.formInput} placeholder="Provincia" value={form.provincia} onChange={(e) => setForm({ ...form, provincia: e.target.value })} />
            <input className={styles.formInput} placeholder="CP" value={form.cp} onChange={(e) => setForm({ ...form, cp: e.target.value })} />
          </div>
          <div className={styles.formRow}>
            <input className={styles.formInput} placeholder="Horario recepción" value={form.horario_recepcion} onChange={(e) => setForm({ ...form, horario_recepcion: e.target.value })} />
            <input className={styles.formInput} placeholder="Contacto" value={form.contacto_nombre} onChange={(e) => setForm({ ...form, contacto_nombre: e.target.value })} />
            <input className={styles.formInput} placeholder="Tel. contacto" value={form.contacto_telefono} onChange={(e) => setForm({ ...form, contacto_telefono: e.target.value })} />
          </div>
          <div className={styles.formActions}>
            <button type="button" className={styles.btnSmall} onClick={() => setShowForm(false)}>Cancelar</button>
            <button type="submit" className={styles.btnSmallPrimary} disabled={saving}>{saving ? 'Guardando...' : 'Guardar'}</button>
          </div>
        </form>
      )}
      {direcciones.length === 0 && !showForm && (
        <div className={styles.emptyFiscal}>Sin direcciones cargadas</div>
      )}
      {direcciones.map((d) => (
        <div key={d.id} className={styles.subCard}>
          <div className={styles.subCardHeader}>
            <span className={styles.subCardTitle}>{d.etiqueta}</span>
            {d.origen === 'rma' && <span className={styles.tagSmall}>RMA</span>}
            {canEdit && (
              <button className={styles.btnIcon} onClick={() => handleToggle(d.id)} title={d.activo ? 'Deshabilitar' : 'Habilitar'}>
                {d.activo ? <EyeOff size={14} /> : <Eye size={14} />}
              </button>
            )}
          </div>
          <div className={styles.subCardBody}>
            <span>{d.direccion}</span>
            {d.ciudad && <span>{d.ciudad}{d.provincia ? `, ${d.provincia}` : ''}{d.cp ? ` (${d.cp})` : ''}</span>}
            {d.horario_recepcion && <span>Horario: {d.horario_recepcion}</span>}
            {d.contacto_nombre && <span>Contacto: {d.contacto_nombre}{d.contacto_telefono ? ` — ${d.contacto_telefono}` : ''}</span>}
          </div>
        </div>
      ))}
    </div>
  );
}

// ── Sección Bancos ───────────────────────────────────────────────

function BancosSection({ proveedorId, bancos, canEdit, onRefresh }) {
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ banco: '', tipo_cuenta: '', cbu: '', alias: '', titular: '', cuit_titular: '' });
  const [saving, setSaving] = useState(false);

  const handleSave = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      const moneda = (form.tipo_cuenta || '').includes('USD') ? 'USD' : 'ARS';
      await api.post(`/administracion/proveedores/${proveedorId}/bancos`, { ...form, moneda });
      setShowForm(false);
      setForm({ banco: '', tipo_cuenta: '', cbu: '', alias: '', titular: '', cuit_titular: '' });
      onRefresh();
    } catch { /* */ }
    finally { setSaving(false); }
  };

  return (
    <div className={styles.detailSection}>
      <div className={styles.sectionHeader}>
        <h3 className={styles.sectionTitle}><Landmark size={16} /> Datos Bancarios</h3>
        {canEdit && (
          <button className={styles.btnSmall} onClick={() => setShowForm(!showForm)}>
            <Plus size={14} /> Agregar
          </button>
        )}
      </div>
      {showForm && (
        <form onSubmit={handleSave} className={styles.inlineForm}>
          <div className={styles.formRow}>
            <input className={styles.formInput} placeholder="Banco *" value={form.banco} onChange={(e) => setForm({ ...form, banco: e.target.value })} required />
            <select className={styles.formInput} value={form.tipo_cuenta} onChange={(e) => setForm({ ...form, tipo_cuenta: e.target.value })}>
              <option value="">Tipo cuenta</option>
              <option value="CA $">CA $</option>
              <option value="CC $">CC $</option>
              <option value="CU $">CU $</option>
              <option value="CA USD">CA USD</option>
              <option value="CC USD">CC USD</option>
              <option value="CU USD">CU USD</option>
            </select>
          </div>
          <div className={styles.formRow}>
            <input className={styles.formInput} placeholder="CBU" value={form.cbu} onChange={(e) => setForm({ ...form, cbu: e.target.value })} />
            <input className={styles.formInput} placeholder="Alias" value={form.alias} onChange={(e) => setForm({ ...form, alias: e.target.value })} />
          </div>
          <div className={styles.formRow}>
            <input className={styles.formInput} placeholder="Titular" value={form.titular} onChange={(e) => setForm({ ...form, titular: e.target.value })} />
            <input className={styles.formInput} placeholder="CUIT titular" value={form.cuit_titular} onChange={(e) => setForm({ ...form, cuit_titular: e.target.value })} />
          </div>
          <div className={styles.formActions}>
            <button type="button" className={styles.btnSmall} onClick={() => setShowForm(false)}>Cancelar</button>
            <button type="submit" className={styles.btnSmallPrimary} disabled={saving}>{saving ? 'Guardando...' : 'Guardar'}</button>
          </div>
        </form>
      )}
      {bancos.length === 0 && !showForm && (
        <div className={styles.emptyFiscal}>Sin datos bancarios cargados</div>
      )}
      {bancos.map((b) => (
        <div key={b.id} className={styles.subCard}>
          <div className={styles.subCardHeader}>
            <span className={styles.subCardTitle}>{b.banco}</span>
            {b.tipo_cuenta && <span className={styles.tagSmall}>{b.tipo_cuenta}</span>}
            {b.moneda && b.moneda !== 'ARS' && <span className={styles.tagSmall}>{b.moneda}</span>}
          </div>
          <div className={styles.subCardBody}>
            {b.cbu && <span>CBU: {b.cbu}</span>}
            {b.alias && <span>Alias: {b.alias}</span>}
            {b.titular && <span>Titular: {b.titular}{b.cuit_titular ? ` (${b.cuit_titular})` : ''}</span>}
          </div>
        </div>
      ))}
    </div>
  );
}

// ── Sección Contactos ────────────────────────────────────────────

function ContactosSection({ proveedorId, contactos, canEdit, onRefresh }) {
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ nombre: '', rol: '', telefono: '', email: '', cargo: '' });
  const [saving, setSaving] = useState(false);

  const handleSave = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      await api.post(`/administracion/proveedores/${proveedorId}/contactos`, form);
      setShowForm(false);
      setForm({ nombre: '', rol: '', telefono: '', email: '', cargo: '' });
      onRefresh();
    } catch { /* */ }
    finally { setSaving(false); }
  };

  return (
    <div className={styles.detailSection}>
      <div className={styles.sectionHeader}>
        <h3 className={styles.sectionTitle}><Users size={16} /> Contactos</h3>
        {canEdit && (
          <button className={styles.btnSmall} onClick={() => setShowForm(!showForm)}>
            <Plus size={14} /> Agregar
          </button>
        )}
      </div>
      {showForm && (
        <form onSubmit={handleSave} className={styles.inlineForm}>
          <div className={styles.formRow}>
            <input className={styles.formInput} placeholder="Nombre *" value={form.nombre} onChange={(e) => setForm({ ...form, nombre: e.target.value })} required />
            <select className={styles.formInput} value={form.rol} onChange={(e) => setForm({ ...form, rol: e.target.value })}>
              <option value="">Área / Rol</option>
              <option value="Ventas">Ventas</option>
              <option value="Pagos">Pagos</option>
              <option value="Facturación">Facturación</option>
              <option value="Técnico">Técnico</option>
              <option value="Logística">Logística</option>
              <option value="Otro">Otro</option>
            </select>
          </div>
          <div className={styles.formRow}>
            <input className={styles.formInput} placeholder="Teléfono" value={form.telefono} onChange={(e) => setForm({ ...form, telefono: e.target.value })} />
            <input className={styles.formInput} placeholder="Email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
            <input className={styles.formInput} placeholder="Cargo" value={form.cargo} onChange={(e) => setForm({ ...form, cargo: e.target.value })} />
          </div>
          <div className={styles.formActions}>
            <button type="button" className={styles.btnSmall} onClick={() => setShowForm(false)}>Cancelar</button>
            <button type="submit" className={styles.btnSmallPrimary} disabled={saving}>{saving ? 'Guardando...' : 'Guardar'}</button>
          </div>
        </form>
      )}
      {contactos.length === 0 && !showForm && (
        <div className={styles.emptyFiscal}>Sin contactos cargados</div>
      )}
      {contactos.map((c) => (
        <div key={c.id} className={styles.subCard}>
          <div className={styles.subCardHeader}>
            <span className={styles.subCardTitle}>{c.nombre}</span>
            {c.rol && <span className={styles.tagSmall}>{c.rol}</span>}
          </div>
          <div className={styles.subCardBody}>
            {c.cargo && <span>{c.cargo}</span>}
            {c.telefono && <span>Tel: {c.telefono}</span>}
            {c.email && <span>{c.email}</span>}
          </div>
        </div>
      ))}
    </div>
  );
}

// ── Sección Marcas ───────────────────────────────────────────────

function MarcasSection({ proveedorId }) {
  const [marcas, setMarcas] = useState([]);
  const [loading, setLoading] = useState(false);
  const [loaded, setLoaded] = useState(false);

  const fetchMarcas = async () => {
    setLoading(true);
    try {
      const { data } = await api.get(`/administracion/proveedores/${proveedorId}/marcas`);
      setMarcas(data);
      setLoaded(true);
    } catch { setMarcas([]); }
    finally { setLoading(false); }
  };

  return (
    <div className={styles.detailSection}>
      <div className={styles.sectionHeader}>
        <h3 className={styles.sectionTitle}><Tag size={16} /> Marcas</h3>
        {!loaded && (
          <button className={styles.btnSmall} onClick={fetchMarcas} disabled={loading}>
            {loading ? <><Loader2 size={14} className={styles.spinning} /> Cargando...</> : 'Cargar marcas'}
          </button>
        )}
      </div>
      {loaded && marcas.length === 0 && (
        <div className={styles.emptyFiscal}>No se encontraron compras a este proveedor</div>
      )}
      {marcas.length > 0 && (
        <div className={styles.tagList}>
          {marcas.map((m) => (
            <span key={m.brand_id} className={styles.tagImpuesto} title={`${m.cantidad_compras} compras — Última: ${m.ultima_compra ? new Date(m.ultima_compra).toLocaleDateString('es-AR') : 'N/A'}`}>
              {m.marca} ({m.cantidad_compras})
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
