/**
 * ClaimsDashboard — Centralized view of all MercadoLibre claims.
 *
 * Two tabs:
 * 1. "Reclamos" — filterable table of all claims from local cache
 * 2. "Devoluciones al Local" — filtered view of returns heading to seller_address
 *
 * Shows stats cards, sync button to fetch from ML, and links to RMA cases.
 * Uses ClaimCards for detail view of individual claims.
 */

import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useDebounce } from '../hooks/useDebounce';
import { usePermisos } from '../contexts/PermisosContext';
import api from '../services/api';
import ClaimCards from '../components/ClaimCards';
import ModalTesla from '../components/ModalTesla';
import { PLAYER_ROLE_ES } from '../components/claimTranslations';
import {
  ShieldAlert,
  RefreshCcw,
  Search,
  ChevronLeft,
  ChevronRight,
  AlertTriangle,
  Loader,
  ExternalLink,
  FileText,
  Swords,
  Clock,
  ShieldCheck,
  ShieldX,
  Filter,
  X,
  MessageSquare,
  PackageCheck,
  Truck,
  PackageX,
  MapPin,
} from 'lucide-react';
import styles from './ClaimsDashboard.module.css';

const STAGE_LABELS = {
  claim: 'Reclamo',
  dispute: 'Disputa',
  recontact: 'Recontacto',
  stale: 'Inactivo',
  none: 'Sin etapa',
  sin_etapa: 'Sin etapa',
};

const TYPE_LABELS = {
  mediations: 'Mediación',
  return: 'Devolución',
  returns: 'Devolución',
  fulfillment: 'Fulfillment',
  ml_case: 'Caso ML',
  cancel_sale: 'Cancelación',
  change: 'Cambio',
  service: 'Servicio',
};

const RESPONSIBLE_LABELS = {
  seller: 'Vendedor',
  buyer: 'Comprador',
  mediator: 'Mediador',
  // ML uses respondent/complainant in players — backend now maps them,
  // but just in case old cached data slips through:
  respondent: 'Vendedor',
  complainant: 'Comprador',
};

// Map reason_id prefixes to readable categories
const REASON_CATEGORY_LABELS = {
  PDD: 'Prod. diferente/defectuoso',
  PNR: 'Prod. no recibido',
  CS: 'Cancelación',
};

const RETURN_SHIPMENT_STATUS_LABELS = {
  pending: 'Pendiente',
  ready_to_ship: 'Listo para envío',
  shipped: 'En camino',
  delivered: 'Entregado',
  cancelled: 'Cancelado',
};

export default function ClaimsDashboard() {
  const { tienePermiso } = usePermisos();
  const puedeGestionar = tienePermiso('rma.gestionar');
  const puedeVerRma = tienePermiso('rma.ver');
  const navigate = useNavigate();

  // Tab
  const [activeTab, setActiveTab] = useState('claims');

  // Data
  const [claims, setClaims] = useState([]);
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [totalItems, setTotalItems] = useState(0);
  const [totalPages, setTotalPages] = useState(0);

  // Filters
  const [statusFilter, setStatusFilter] = useState('opened');
  const [stageFilter, setStageFilter] = useState('');
  const [typeFilter, setTypeFilter] = useState('');
  const [responsibleFilter, setResponsibleFilter] = useState('');
  const [hasRmaFilter, setHasRmaFilter] = useState('');
  const [searchText, setSearchText] = useState('');
  const [page, setPage] = useState(1);
  const debouncedSearch = useDebounce(searchText, 500);

  // Returns tab specific filters
  const [returnShipmentFilter, setReturnShipmentFilter] = useState('');
  const [returnSearchText, setReturnSearchText] = useState('');
  const [returnPage, setReturnPage] = useState(1);
  const debouncedReturnSearch = useDebounce(returnSearchText, 500);

  // Returns tab data
  const [returns, setReturns] = useState([]);
  const [returnsLoading, setReturnsLoading] = useState(false);
  const [returnsError, setReturnsError] = useState(null);
  const [returnsTotalItems, setReturnsTotalItems] = useState(0);
  const [returnsTotalPages, setReturnsTotalPages] = useState(0);

  // Sync
  const [syncing, setSyncing] = useState(false);
  const [syncResult, setSyncResult] = useState(null);

  // Detail modal
  const [detailClaim, setDetailClaim] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const cargarClaims = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = { page, page_size: 50 };
      if (statusFilter) params.status = statusFilter;
      if (stageFilter) params.stage = stageFilter;
      if (typeFilter) params.claim_type = typeFilter;
      if (responsibleFilter) params.action_responsible = responsibleFilter;
      if (hasRmaFilter === 'true') params.has_rma = true;
      else if (hasRmaFilter === 'false') params.has_rma = false;
      if (debouncedSearch) params.search = debouncedSearch;

      const { data } = await api.get('/claims-dashboard', { params });
      setClaims(data.items);
      setTotalItems(data.total);
      setTotalPages(data.total_pages);
    } catch {
      setClaims([]);
      setError('Error al cargar reclamos');
    } finally {
      setLoading(false);
    }
  }, [page, statusFilter, stageFilter, typeFilter, responsibleFilter, hasRmaFilter, debouncedSearch]);

  const cargarStats = useCallback(async () => {
    try {
      const { data } = await api.get('/claims-dashboard/stats');
      setStats(data);
    } catch {
      // stats optional
    }
  }, []);

  const cargarReturns = useCallback(async () => {
    setReturnsLoading(true);
    setReturnsError(null);
    try {
      const params = {
        page: returnPage,
        page_size: 50,
        status: 'opened',
        return_destination: 'seller_address',
      };
      if (returnShipmentFilter) params.return_shipment_status = returnShipmentFilter;
      if (debouncedReturnSearch) params.search = debouncedReturnSearch;

      const { data } = await api.get('/claims-dashboard', { params });
      setReturns(data.items);
      setReturnsTotalItems(data.total);
      setReturnsTotalPages(data.total_pages);
    } catch {
      setReturns([]);
      setReturnsError('Error al cargar devoluciones');
    } finally {
      setReturnsLoading(false);
    }
  }, [returnPage, returnShipmentFilter, debouncedReturnSearch]);

  useEffect(() => {
    if (activeTab === 'claims') {
      cargarClaims();
    }
  }, [cargarClaims, activeTab]);

  useEffect(() => {
    if (activeTab === 'returns') {
      cargarReturns();
    }
  }, [cargarReturns, activeTab]);

  useEffect(() => {
    cargarStats();
  }, [cargarStats]);

  // Reset page when filters change
  useEffect(() => {
    setPage(1);
  }, [statusFilter, stageFilter, typeFilter, responsibleFilter, hasRmaFilter, debouncedSearch]);

  // Reset return page when return filters change
  useEffect(() => {
    setReturnPage(1);
  }, [returnShipmentFilter, debouncedReturnSearch]);

  const handleSync = async () => {
    setSyncing(true);
    setSyncResult(null);
    try {
      const { data } = await api.post('/claims-dashboard/sync');
      setSyncResult(data);
      cargarClaims();
      cargarStats();
    } catch {
      setSyncResult({ ok: false, mensaje: 'Error al sincronizar con MercadoLibre' });
    } finally {
      setSyncing(false);
    }
  };

  const openDetail = async (claimId) => {
    setDetailLoading(true);
    setDetailClaim(null);
    try {
      const { data } = await api.get(`/claims-dashboard/${claimId}`);
      setDetailClaim(data);
    } catch {
      setDetailClaim(null);
    } finally {
      setDetailLoading(false);
    }
  };

  const clearFilters = () => {
    setStatusFilter('opened');
    setStageFilter('');
    setTypeFilter('');
    setResponsibleFilter('');
    setHasRmaFilter('');
    setSearchText('');
    setPage(1);
  };

  const hasActiveFilters = stageFilter || typeFilter || responsibleFilter || hasRmaFilter || debouncedSearch || statusFilter !== 'opened';

  const formatDate = (dateStr) => {
    if (!dateStr) return '\u2014';
    try {
      const d = new Date(dateStr);
      return d.toLocaleDateString('es-AR', { day: '2-digit', month: '2-digit', year: '2-digit' });
    } catch {
      return dateStr;
    }
  };

  const formatDueDate = (dateStr) => {
    if (!dateStr) return null;
    try {
      const d = new Date(dateStr);
      const now = new Date();
      const diffMs = d - now;
      const diffHours = Math.floor(diffMs / (1000 * 60 * 60));

      if (diffHours < 0) return { text: 'Vencido', urgent: true };
      if (diffHours < 24) return { text: `${diffHours}h`, urgent: true };
      const diffDays = Math.floor(diffHours / 24);
      return { text: `${diffDays}d`, urgent: diffDays <= 2 };
    } catch {
      return null;
    }
  };

  /** Build a readable motivo from whatever data we have */
  const getMotivo = (claim) => {
    // Prefer detail_title (from enrichment), then reason_detail, then a translated reason_category
    if (claim.detail_title) return claim.detail_title;
    if (claim.reason_detail) return claim.reason_detail;
    if (claim.reason_category) {
      return REASON_CATEGORY_LABELS[claim.reason_category] || claim.reason_category;
    }
    if (claim.reason_id) return claim.reason_id;
    return null;
  };

  return (
    <div className={styles.container}>
      {/* Header */}
      <div className={styles.header}>
        <div className={styles.headerLeft}>
          <ShieldAlert size={24} />
          <h1>Reclamos ML</h1>
        </div>
        <div className={styles.headerActions}>
          {syncResult && (
            <span className={syncResult.ok !== false ? styles.syncSuccess : styles.syncError}>
              {syncResult.mensaje}
            </span>
          )}
          {puedeGestionar && (
            <button
              className="btn-tesla outline-subtle-primary sm"
              onClick={handleSync}
              disabled={syncing}
            >
              {syncing
                ? <><Loader size={14} className={styles.spinning} /> Sincronizando...</>
                : <><RefreshCcw size={14} /> Sincronizar ML</>}
            </button>
          )}
        </div>
      </div>

      {/* Tabs */}
      {puedeVerRma && (
        <div className={styles.tabBar}>
          <button
            type="button"
            className={`${styles.tab} ${activeTab === 'claims' ? styles.tabActive : ''}`}
            onClick={() => setActiveTab('claims')}
          >
            <ShieldAlert size={14} />
            Reclamos
          </button>
          <button
            type="button"
            className={`${styles.tab} ${activeTab === 'returns' ? styles.tabActive : ''}`}
            onClick={() => setActiveTab('returns')}
          >
            <Truck size={14} />
            Devoluciones al Local
            {stats && (stats.devoluciones_pendientes + stats.devoluciones_en_camino) > 0 && (
              <span className={styles.tabBadge}>{stats.devoluciones_pendientes + stats.devoluciones_en_camino}</span>
            )}
          </button>
        </div>
      )}

      {/* ====== TAB: Claims ====== */}
      {activeTab === 'claims' && (
        <>
      {/* Stats cards — clickable as filter shortcuts */}
      {stats && (
        <div className={styles.statsGrid}>
          <button
            type="button"
            className={`${styles.statCard} ${styles.statClickable} ${statusFilter === 'opened' && !stageFilter && !responsibleFilter && !hasRmaFilter ? styles.statActive : ''}`}
            onClick={() => { clearFilters(); setStatusFilter('opened'); }}
          >
            <div className={styles.statValue}>{stats.total_abiertos}</div>
            <div className={styles.statLabel}>Abiertos</div>
          </button>
          <button
            type="button"
            className={`${styles.statCard} ${styles.statClickable} ${stats.en_disputa > 0 ? styles.statCardDanger : ''} ${stageFilter === 'dispute' ? styles.statActive : ''}`}
            onClick={() => { clearFilters(); setStatusFilter('opened'); setStageFilter('dispute'); }}
          >
            <Swords size={16} />
            <div className={styles.statValue}>{stats.en_disputa}</div>
            <div className={styles.statLabel}>En disputa</div>
          </button>
          <button
            type="button"
            className={`${styles.statCard} ${styles.statClickable} ${stats.accion_vendedor > 0 ? styles.statCardWarning : ''} ${responsibleFilter === 'seller' ? styles.statActive : ''}`}
            onClick={() => { clearFilters(); setStatusFilter('opened'); setResponsibleFilter('seller'); }}
          >
            <Clock size={16} />
            <div className={styles.statValue}>{stats.accion_vendedor}</div>
            <div className={styles.statLabel}>Acción requerida</div>
          </button>
          <button
            type="button"
            className={`${styles.statCard} ${styles.statClickable} ${hasRmaFilter === 'true' ? styles.statActive : ''}`}
            onClick={() => { clearFilters(); setStatusFilter('opened'); setHasRmaFilter('true'); }}
          >
            <ShieldCheck size={16} />
            <div className={styles.statValue}>{stats.con_caso_rma}</div>
            <div className={styles.statLabel}>Con caso RMA</div>
          </button>
          <button
            type="button"
            className={`${styles.statCard} ${styles.statClickable} ${hasRmaFilter === 'false' ? styles.statActive : ''}`}
            onClick={() => { clearFilters(); setStatusFilter('opened'); setHasRmaFilter('false'); }}
          >
            <ShieldX size={16} />
            <div className={styles.statValue}>{stats.sin_caso_rma}</div>
            <div className={styles.statLabel}>Sin caso RMA</div>
          </button>
        </div>
      )}

      {/* Filters */}
      <div className={styles.filtersBar}>
        <div className={styles.searchBox}>
          <Search size={16} />
          <input
            type="text"
            placeholder="Buscar por motivo, título, claim ID, order ID..."
            value={searchText}
            onChange={(e) => setSearchText(e.target.value)}
          />
        </div>
        <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} className={styles.select}>
          <option value="">Todos</option>
          <option value="opened">Abiertos</option>
          <option value="closed">Cerrados</option>
        </select>
        <select value={stageFilter} onChange={(e) => setStageFilter(e.target.value)} className={styles.select}>
          <option value="">Todas las etapas</option>
          <option value="claim">Reclamo</option>
          <option value="dispute">Disputa</option>
          <option value="recontact">Recontacto</option>
          <option value="stale">Inactivo</option>
        </select>
        <select value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)} className={styles.select}>
          <option value="">Todos los tipos</option>
          <option value="mediations">Mediación</option>
          <option value="return">Devolución</option>
          <option value="fulfillment">Fulfillment</option>
          <option value="change">Cambio</option>
        </select>
        <select value={responsibleFilter} onChange={(e) => setResponsibleFilter(e.target.value)} className={styles.select}>
          <option value="">Todos</option>
          <option value="seller">Acción nuestra</option>
          <option value="buyer">Acción comprador</option>
          <option value="mediator">Acción mediador</option>
        </select>
        <select value={hasRmaFilter} onChange={(e) => setHasRmaFilter(e.target.value)} className={styles.select}>
          <option value="">RMA: todos</option>
          <option value="true">Con caso RMA</option>
          <option value="false">Sin caso RMA</option>
        </select>
        {hasActiveFilters && (
          <button className="btn-tesla ghost sm" onClick={clearFilters} title="Limpiar filtros">
            <Filter size={14} />
            <X size={12} />
          </button>
        )}
      </div>

      {/* Error message */}
      {error && (
        <div className={styles.errorBar}>
          <AlertTriangle size={14} />
          {error}
        </div>
      )}

      {/* Table */}
      <div className="table-container-tesla">
        <table className="table-tesla striped">
          <thead className="table-tesla-head">
            <tr>
              <th>Claim</th>
              <th>Fecha</th>
              <th>Tipo</th>
              <th>Etapa</th>
              <th>Motivo</th>
              <th>Responsable</th>
              <th>Vence</th>
              <th>Msgs</th>
              <th>RMA</th>
            </tr>
          </thead>
          <tbody className="table-tesla-body">
            {loading ? (
              <tr><td colSpan={9} className={styles.loadingCell}>Cargando...</td></tr>
            ) : claims.length === 0 ? (
              <tr><td colSpan={9} className={styles.emptyCell}>No se encontraron claims</td></tr>
            ) : (
              claims.map((claim) => {
                const due = formatDueDate(claim.nearest_due_date);
                const motivo = getMotivo(claim);
                return (
                  <tr
                    key={claim.claim_id}
                    className={`${styles.clickableRow} ${claim.claim_stage === 'dispute' ? styles.rowDispute : ''}`}
                    onClick={() => openDetail(claim.claim_id)}
                  >
                    <td className={styles.cellClaim}>
                      <span className={styles.claimId}>{claim.claim_id}</span>
                      {claim.resource_id && (
                        <span className={styles.orderId}>Venta: {claim.resource_id}</span>
                      )}
                    </td>
                    <td className={styles.cellDate}>{formatDate(claim.ml_date_created)}</td>
                    <td>
                      <span className={`${styles.badge} ${styles[`badge_${claim.claim_type}`] || ''}`}>
                        {TYPE_LABELS[claim.claim_type] || claim.claim_type || '\u2014'}
                      </span>
                    </td>
                    <td>
                      <span className={`${styles.badge} ${styles[`badge_${claim.claim_stage}`] || ''}`}>
                        {STAGE_LABELS[claim.claim_stage] || claim.claim_stage || '\u2014'}
                      </span>
                    </td>
                    <td className={styles.cellMotivo} title={motivo || ''}>
                      {motivo || '\u2014'}
                    </td>
                    <td>
                      {claim.action_responsible ? (
                        <span className={`${styles.badgeResp} ${styles[`resp_${claim.action_responsible}`] || ''}`}>
                          {RESPONSIBLE_LABELS[claim.action_responsible] || PLAYER_ROLE_ES[claim.action_responsible] || claim.action_responsible}
                        </span>
                      ) : '\u2014'}
                    </td>
                    <td>
                      {due ? (
                        <span className={due.urgent ? styles.dueUrgent : styles.dueNormal}>
                          {due.urgent && <AlertTriangle size={12} />}
                          {due.text}
                        </span>
                      ) : '\u2014'}
                    </td>
                    <td className={styles.cellCenter}>
                      {claim.messages_total != null && claim.messages_total > 0 ? (
                        <span className={styles.msgCount}>
                          <MessageSquare size={12} />
                          {claim.messages_total}
                        </span>
                      ) : '\u2014'}
                    </td>
                    <td>
                      {claim.rma_numero_caso ? (
                        <button
                          className={styles.rmaBadge}
                          onClick={(e) => { e.stopPropagation(); navigate('/rma'); }}
                          title={`Ir a RMA ${claim.rma_numero_caso}`}
                        >
                          <FileText size={12} />
                          {claim.rma_numero_caso}
                        </button>
                      ) : (
                        <span className={styles.noRma}>{'\u2014'}</span>
                      )}
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className={styles.pagination}>
          <button className="btn-tesla ghost sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>
            <ChevronLeft size={16} />
          </button>
          <span className={styles.pageInfo}>
            Página {page} de {totalPages} ({totalItems} claims)
          </span>
          <button className="btn-tesla ghost sm" disabled={page >= totalPages} onClick={() => setPage(page + 1)}>
            <ChevronRight size={16} />
          </button>
        </div>
      )}
        </>
      )}

      {/* ====== TAB: Returns to Local ====== */}
      {activeTab === 'returns' && (
        <>
          {/* Returns stats */}
          {stats && (
            <div className={styles.statsGrid}>
              <button
                type="button"
                className={`${styles.statCard} ${styles.statClickable} ${!returnShipmentFilter ? styles.statActive : ''}`}
                onClick={() => setReturnShipmentFilter('')}
              >
                <MapPin size={16} />
                <div className={styles.statValue}>{stats.devoluciones_al_local}</div>
                <div className={styles.statLabel}>Total al local</div>
              </button>
              <button
                type="button"
                className={`${styles.statCard} ${styles.statClickable} ${stats.devoluciones_pendientes > 0 ? styles.statCardWarning : ''} ${returnShipmentFilter === 'pending' ? styles.statActive : ''}`}
                onClick={() => setReturnShipmentFilter('pending')}
              >
                <Clock size={16} />
                <div className={styles.statValue}>{stats.devoluciones_pendientes}</div>
                <div className={styles.statLabel}>Pendientes</div>
              </button>
              <button
                type="button"
                className={`${styles.statCard} ${styles.statClickable} ${stats.devoluciones_en_camino > 0 ? styles.statCardWarning : ''} ${returnShipmentFilter === 'shipped' ? styles.statActive : ''}`}
                onClick={() => setReturnShipmentFilter('shipped')}
              >
                <Truck size={16} />
                <div className={styles.statValue}>{stats.devoluciones_en_camino}</div>
                <div className={styles.statLabel}>En camino</div>
              </button>
              <button
                type="button"
                className={`${styles.statCard} ${styles.statClickable} ${returnShipmentFilter === 'delivered' ? styles.statActive : ''}`}
                onClick={() => setReturnShipmentFilter('delivered')}
              >
                <PackageCheck size={16} />
                <div className={styles.statValue}>{stats.devoluciones_entregadas}</div>
                <div className={styles.statLabel}>Entregadas</div>
              </button>
            </div>
          )}

          {/* Returns filters */}
          <div className={styles.filtersBar}>
            <div className={styles.searchBox}>
              <Search size={16} />
              <input
                type="text"
                placeholder="Buscar por motivo, claim ID, order ID..."
                value={returnSearchText}
                onChange={(e) => setReturnSearchText(e.target.value)}
              />
            </div>
            <select value={returnShipmentFilter} onChange={(e) => setReturnShipmentFilter(e.target.value)} className={styles.select}>
              <option value="">Todos los estados</option>
              <option value="pending">Pendientes (sin despachar)</option>
              <option value="shipped">En camino</option>
              <option value="delivered">Entregado</option>
            </select>
            {(returnShipmentFilter || debouncedReturnSearch) && (
              <button className="btn-tesla ghost sm" onClick={() => { setReturnShipmentFilter(''); setReturnSearchText(''); }} title="Limpiar filtros">
                <Filter size={14} />
                <X size={12} />
              </button>
            )}
          </div>

          {/* Returns error */}
          {returnsError && (
            <div className={styles.errorBar}>
              <AlertTriangle size={14} />
              {returnsError}
            </div>
          )}

          {/* Returns table */}
          <div className="table-container-tesla">
            <table className="table-tesla striped">
              <thead className="table-tesla-head">
                <tr>
                  <th>Claim</th>
                  <th>Fecha</th>
                  <th>Motivo</th>
                  <th>Estado envío</th>
                  <th>Tracking</th>
                  <th>Tipo envío</th>
                  <th>Etapa</th>
                  <th>RMA</th>
                </tr>
              </thead>
              <tbody className="table-tesla-body">
                {returnsLoading ? (
                  <tr><td colSpan={8} className={styles.loadingCell}>Cargando...</td></tr>
                ) : returns.length === 0 ? (
                  <tr><td colSpan={8} className={styles.emptyCell}>
                    <PackageX size={20} />
                    No hay devoluciones al local{returnShipmentFilter ? ` con estado "${RETURN_SHIPMENT_STATUS_LABELS[returnShipmentFilter] || returnShipmentFilter}"` : ''}
                  </td></tr>
                ) : (
                  returns.map((claim) => {
                    const motivo = getMotivo(claim);
                    const shipStatus = claim.return_shipment_status;
                    const isDelivered = shipStatus === 'delivered';
                    const isInTransit = shipStatus === 'shipped';
                    return (
                      <tr
                        key={claim.claim_id}
                        className={styles.clickableRow}
                        onClick={() => openDetail(claim.claim_id)}
                      >
                        <td className={styles.cellClaim}>
                          <span className={styles.claimId}>{claim.claim_id}</span>
                          {claim.resource_id && (
                            <span className={styles.orderId}>Venta: {claim.resource_id}</span>
                          )}
                        </td>
                        <td className={styles.cellDate}>{formatDate(claim.ml_date_created)}</td>
                        <td className={styles.cellMotivo} title={motivo || ''}>
                          {motivo || '\u2014'}
                        </td>
                        <td>
                          <span className={`${styles.returnBadge} ${isDelivered ? styles.returnDelivered : ''} ${isInTransit ? styles.returnShipped : ''}`}>
                            {isDelivered && <PackageCheck size={12} />}
                            {isInTransit && <Truck size={12} />}
                            {!isDelivered && !isInTransit && shipStatus === 'ready_to_ship' && <PackageCheck size={12} />}
                            {RETURN_SHIPMENT_STATUS_LABELS[shipStatus] || shipStatus || '\u2014'}
                          </span>
                        </td>
                        <td className={styles.cellTracking}>
                          {claim.return_tracking || '\u2014'}
                        </td>
                        <td>
                          <span className={styles.badge}>
                            {claim.return_shipment_type === 'return_from_triage' ? 'Desde triage' : 'Devolución'}
                          </span>
                        </td>
                        <td>
                          <span className={`${styles.badge} ${styles[`badge_${claim.claim_stage}`] || ''}`}>
                            {STAGE_LABELS[claim.claim_stage] || claim.claim_stage || '\u2014'}
                          </span>
                        </td>
                        <td>
                          {claim.rma_numero_caso ? (
                            <button
                              className={styles.rmaBadge}
                              onClick={(e) => { e.stopPropagation(); navigate('/rma'); }}
                              title={`Ir a RMA ${claim.rma_numero_caso}`}
                            >
                              <FileText size={12} />
                              {claim.rma_numero_caso}
                            </button>
                          ) : (
                            <span className={styles.noRma}>{'\u2014'}</span>
                          )}
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>

          {/* Returns pagination */}
          {returnsTotalPages > 1 && (
            <div className={styles.pagination}>
              <button className="btn-tesla ghost sm" disabled={returnPage <= 1} onClick={() => setReturnPage(returnPage - 1)}>
                <ChevronLeft size={16} />
              </button>
              <span className={styles.pageInfo}>
                Página {returnPage} de {returnsTotalPages} ({returnsTotalItems} devoluciones)
              </span>
              <button className="btn-tesla ghost sm" disabled={returnPage >= returnsTotalPages} onClick={() => setReturnPage(returnPage + 1)}>
                <ChevronRight size={16} />
              </button>
            </div>
          )}
        </>
      )}

      {/* Detail modal — full enriched claim with ClaimCards */}
      <ModalTesla
        isOpen={detailLoading || detailClaim !== null}
        title={detailClaim ? `Claim #${detailClaim.claim?.claim_id || ''}` : 'Cargando detalle...'}
        onClose={() => { setDetailClaim(null); setDetailLoading(false); }}
        closeOnOverlay={false}
        size="lg"
      >
          {detailLoading ? (
            <div className={styles.loadingCell}>
              <Loader size={20} className={styles.spinning} />
              <span>Enriqueciendo claim desde MercadoLibre...</span>
            </div>
          ) : detailClaim ? (
            <div className={styles.detailBody}>
              {/* RMA link */}
              {detailClaim.rma ? (
                <div className={styles.detailRma}>
                  <FileText size={16} />
                  <span>Caso RMA: <strong>{detailClaim.rma.numero_caso}</strong></span>
                  <button
                    className="btn-tesla outline-subtle-primary sm"
                    onClick={() => { setDetailClaim(null); navigate('/rma'); }}
                  >
                    <ExternalLink size={14} /> Ir al caso
                  </button>
                </div>
              ) : (
                <div className={styles.detailNoRma}>
                  <ShieldX size={16} />
                  <span>Este claim no tiene caso RMA asociado</span>
                  {puedeGestionar && (
                    <button
                      className="btn-tesla outline-subtle-primary sm"
                      onClick={() => { setDetailClaim(null); navigate('/rma'); }}
                    >
                      Crear caso RMA
                    </button>
                  )}
                </div>
              )}

              {/* Full claim card — includes messages button, return, change, etc. */}
              <ClaimCards claims={[detailClaim.claim]} />
            </div>
          ) : null}
      </ModalTesla>
    </div>
  );
}
