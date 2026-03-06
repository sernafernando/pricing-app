/**
 * ClaimsDashboard — Centralized view of all MercadoLibre claims.
 *
 * Shows stats cards, filterable table of claims from local cache,
 * sync button to fetch from ML, and links to RMA cases when they exist.
 * Uses ClaimCards for detail view of individual claims.
 */

import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useDebounce } from '../hooks/useDebounce';
import { usePermisos } from '../contexts/PermisosContext';
import api from '../services/api';
import ClaimCards from '../components/ClaimCards';
import ModalTesla from '../components/ModalTesla';
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
  mediations: 'Mediacion',
  return: 'Devolucion',
  returns: 'Devolucion',
  fulfillment: 'Fulfillment',
  ml_case: 'Caso ML',
  cancel_sale: 'Cancelacion',
  change: 'Cambio',
  service: 'Servicio',
};

const RESPONSIBLE_LABELS = {
  seller: 'Vendedor',
  buyer: 'Comprador',
  mediator: 'Mediador',
};

export default function ClaimsDashboard() {
  const { tienePermiso } = usePermisos();
  const puedeGestionar = tienePermiso('rma.gestionar');
  const navigate = useNavigate();

  // Data
  const [claims, setClaims] = useState([]);
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
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

  // Sync
  const [syncing, setSyncing] = useState(false);
  const [syncResult, setSyncResult] = useState(null);

  // Detail modal
  const [detailClaim, setDetailClaim] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const cargarClaims = useCallback(async () => {
    setLoading(true);
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

  useEffect(() => {
    cargarClaims();
  }, [cargarClaims]);

  useEffect(() => {
    cargarStats();
  }, [cargarStats]);

  // Reset page when filters change
  useEffect(() => {
    setPage(1);
  }, [statusFilter, stageFilter, typeFilter, responsibleFilter, hasRmaFilter, debouncedSearch]);

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

      {/* Stats cards */}
      {stats && (
        <div className={styles.statsGrid}>
          <div className={styles.statCard}>
            <div className={styles.statValue}>{stats.total_abiertos}</div>
            <div className={styles.statLabel}>Abiertos</div>
          </div>
          <div className={`${styles.statCard} ${stats.en_disputa > 0 ? styles.statCardDanger : ''}`}>
            <Swords size={16} />
            <div className={styles.statValue}>{stats.en_disputa}</div>
            <div className={styles.statLabel}>En disputa</div>
          </div>
          <div className={`${styles.statCard} ${stats.accion_vendedor > 0 ? styles.statCardWarning : ''}`}>
            <Clock size={16} />
            <div className={styles.statValue}>{stats.accion_vendedor}</div>
            <div className={styles.statLabel}>Accion requerida</div>
          </div>
          <div className={styles.statCard}>
            <ShieldCheck size={16} />
            <div className={styles.statValue}>{stats.con_caso_rma}</div>
            <div className={styles.statLabel}>Con caso RMA</div>
          </div>
          <div className={styles.statCard}>
            <ShieldX size={16} />
            <div className={styles.statValue}>{stats.sin_caso_rma}</div>
            <div className={styles.statLabel}>Sin caso RMA</div>
          </div>
        </div>
      )}

      {/* Filters */}
      <div className={styles.filtersBar}>
        <div className={styles.searchBox}>
          <Search size={16} />
          <input
            type="text"
            placeholder="Buscar por motivo, titulo, claim ID, order ID..."
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
          <option value="mediations">Mediacion</option>
          <option value="return">Devolucion</option>
          <option value="fulfillment">Fulfillment</option>
          <option value="change">Cambio</option>
        </select>
        <select value={responsibleFilter} onChange={(e) => setResponsibleFilter(e.target.value)} className={styles.select}>
          <option value="">Todos</option>
          <option value="seller">Accion nuestra</option>
          <option value="buyer">Accion comprador</option>
          <option value="mediator">Accion mediador</option>
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
                return (
                  <tr
                    key={claim.claim_id}
                    className={`${styles.clickableRow} ${claim.claim_stage === 'dispute' ? styles.rowDispute : ''}`}
                    onClick={() => openDetail(claim.claim_id)}
                  >
                    <td className={styles.cellClaim}>
                      <span className={styles.claimId}>{claim.claim_id}</span>
                      {claim.resource_id && (
                        <span className={styles.orderId}>OID: {claim.resource_id}</span>
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
                    <td className={styles.cellMotivo}>
                      {claim.detail_title || claim.reason_detail || '\u2014'}
                    </td>
                    <td>
                      {claim.action_responsible ? (
                        <span className={`${styles.badgeResp} ${styles[`resp_${claim.action_responsible}`] || ''}`}>
                          {RESPONSIBLE_LABELS[claim.action_responsible] || claim.action_responsible}
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
                      {claim.messages_total != null ? claim.messages_total : '\u2014'}
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
                        <span className={styles.noRma} title="Sin caso RMA">
                          \u2014
                        </span>
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
            Pagina {page} de {totalPages} ({totalItems} claims)
          </span>
          <button className="btn-tesla ghost sm" disabled={page >= totalPages} onClick={() => setPage(page + 1)}>
            <ChevronRight size={16} />
          </button>
        </div>
      )}

      {/* Detail modal */}
      {(detailClaim || detailLoading) && (
        <ModalTesla
          title={detailClaim ? `Claim #${detailClaim.claim?.claim_id || ''}` : 'Cargando...'}
          onClose={() => { setDetailClaim(null); setDetailLoading(false); }}
          closeOnOverlay={false}
          size="lg"
        >
          {detailLoading ? (
            <div className={styles.loadingCell}>Cargando detalle...</div>
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

              {/* Full claim card */}
              <ClaimCards claims={[detailClaim.claim]} />
            </div>
          ) : null}
        </ModalTesla>
      )}
    </div>
  );
}
