/**
 * AportesAdsML — brand contributions to Product Ads campaigns (ml-ads-brand-contribution S10).
 *
 * Lists every catalogued campaign with its cost in a date range (`GET /ml-ads/campaigns`, `ml_metricas.ver_ganancia`)
 * and all its contributions; with `ml_metricas.gestionar_aportes_ads` (S7) it also loads and edits them
 * (`AportesAdsMLForm`) and deletes them behind a confirmation modal. A contribution is a percentage or a fixed amount over a date range (S3/S4); a fixed amount
 * says how it settles (S6). Métricas ML stops subtracting the part of the cost a contribution covers (S9).
 *
 * Layout from the Stitch redesign (ml-ads-contribution-redesign S3): KPI tiles over the range, a toolbar that filters
 * the loaded rows (no new request), APORTE and NETO per campaign as the backend computes them, and a Total row.
 */
import { useState, useEffect, useCallback, useRef } from 'react';
import { AlertTriangle, Info, Pencil, Plus, Search, Trash2 } from 'lucide-react';
import { usePermisos } from '../contexts/PermisosContext';
import api from '../services/api';
import ModalTesla from '../components/ModalTesla';
import { SegmentedControl, StatusPill } from '../components/kit';
import AportesAdsMLForm from './AportesAdsMLForm';
import { registrarPagina } from '../registry/tabRegistry';
import { apiErrorMessage } from '../utils/apiErrorMessage';
import { formatSignedMoney } from '../utils/ventasMlTone';
import styles from './AportesAdsML.module.css';

registrarPagina({ pagePath: '/ml-ads-aportes', pageLabel: 'Aportes de marcas (Ads ML)', tabs: [] });

const SETTLEMENT_LABELS = { full: 'Se recibe todo', refund_difference: 'Se devuelve la diferencia' };
// The chip's short badge; the full label is its title.
const SETTLEMENT_BADGES = {
  full: { text: 'Todo', tone: 'info' },
  refund_difference: { text: 'Diferencia', tone: 'warning' },
};
const STATUS_PILLS = { active: { text: 'Activa', tone: 'success' }, paused: { text: 'Pausada', tone: 'neutral' } };
const SEGMENTS = [
  { value: 'all', label: 'Todas' },
  { value: 'with', label: 'Con aporte' },
  { value: 'without', label: 'Sin aporte' },
];

const isoDay = (d) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;

// `2026-10-01` -> `01/10/26`: a contribution may sit in any year, the chip has no room for four digits.
const formatDay = (iso) => {
  const [year, month, day] = iso.split('-');
  return `${day}/${month}/${year.slice(2)}`;
};

const touchesRange = (c, range) => c.date_from <= range.to && c.date_to >= range.from;
const advertiserLabel = (c) => c.advertiser_name || `Anunciante ${c.advertiser_id}`;
const sumOf = (rows, key) => rows.reduce((total, row) => total + (row[key] || 0), 0);
const formatPercent = (value) => `${value.toLocaleString('es-AR', { maximumFractionDigits: 1 })} %`;

function ContributionItem({ c, canManage, onEdit, onDelete }) {
  const value = c.kind === 'percentage' ? `${c.value}%` : formatSignedMoney(c.value);
  const badge = SETTLEMENT_BADGES[c.settlement];
  // Shown on hover; the hidden copy reads it to keyboard and screen-reader users too.
  const details = [c.brand, c.note].filter(Boolean).join(' · ');
  return (
    <li className={styles.chip} title={details || undefined}>
      <span className={styles.chipValue}>{value}</span>
      {details && <span className={styles.srOnly}>{details}</span>}
      {badge && (
        <StatusPill tone={badge.tone} title={SETTLEMENT_LABELS[c.settlement]}>
          {badge.text}
        </StatusPill>
      )}
      <span className={styles.chipRange}>
        {formatDay(c.date_from)} → {formatDay(c.date_to)}
      </span>
      {canManage && (
        <span className={styles.actions}>
          <button type="button" className={styles.btnIcon} aria-label="Editar aporte" onClick={() => onEdit(c)}>
            <Pencil size={14} />
          </button>
          <button type="button" className={styles.btnIconDanger} aria-label="Borrar aporte" onClick={() => onDelete(c)}>
            <Trash2 size={14} />
          </button>
        </span>
      )}
    </li>
  );
}

export default function AportesAdsML() {
  // The page opens with `ml_metricas.ver` (like Métricas ML); the campaign costs need `ver_ganancia`, as the API does.
  const { tienePermiso } = usePermisos();
  const puedeVerGanancia = tienePermiso('ml_metricas.ver_ganancia');
  const canManage = tienePermiso('ml_metricas.gestionar_aportes_ads');
  const today = new Date();
  const [range, setRange] = useState({
    from: isoDay(new Date(today.getFullYear(), today.getMonth(), 1)),
    to: isoDay(today),
  });
  const [campaigns, setCampaigns] = useState([]);
  const [search, setSearch] = useState('');
  const [segment, setSegment] = useState('all');
  const [advertiser, setAdvertiser] = useState('');
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState(null);

  // Only the newest request may write the list: a range changed quickly must not be overwritten by a slower,
  // older response.
  const latestRequest = useRef(0);

  // The campaign whose new contribution is being loaded, while the form is open.
  const [creatingFor, setCreatingFor] = useState(null);
  // The contribution being edited, while the form is open.
  const [editing, setEditing] = useState(null);
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [deleteError, setDeleteError] = useState(null);
  const [deleting, setDeleting] = useState(false);

  const fetchCampaigns = useCallback(async () => {
    const request = ++latestRequest.current;
    setLoading(true);
    setLoadError(null);
    try {
      const { data } = await api.get('/ml-ads/campaigns', { params: { date_from: range.from, date_to: range.to } });
      if (request === latestRequest.current) setCampaigns(data?.campaigns ?? []);
    } catch (err) {
      if (request !== latestRequest.current) return;
      setCampaigns([]);
      setLoadError(apiErrorMessage(err, 'No se pudieron cargar las campañas'));
    } finally {
      if (request === latestRequest.current) setLoading(false);
    }
  }, [range.from, range.to]);

  // ISO dates compare as text; an empty or inverted range waits for the user instead of asking for a 422.
  const rangoValido = Boolean(range.from && range.to && range.from <= range.to);

  useEffect(() => {
    if (puedeVerGanancia && rangoValido) fetchCampaigns();
  }, [fetchCampaigns, puedeVerGanancia, rangoValido]);

  if (!puedeVerGanancia) {
    return (
      <div className={styles.container}>
        <h1 className={styles.title}>Aportes de marcas (Ads ML)</h1>
        <div className={styles.alertError} role="alert">
          <AlertTriangle size={16} /> Necesitás el permiso para ver la ganancia de Métricas ML para ver los aportes.
        </div>
      </div>
    );
  }

  const handleSaved = () => {
    setCreatingFor(null);
    setEditing(null);
    fetchCampaigns();
  };

  const closeDelete = () => {
    setDeleteTarget(null);
    setDeleteError(null);
  };

  const handleConfirmDelete = async () => {
    setDeleting(true);
    setDeleteError(null);
    try {
      await api.delete(`/ml-ads/contributions/${deleteTarget.id}`);
      closeDelete();
      fetchCampaigns();
    } catch (err) {
      setDeleteError(apiErrorMessage(err, 'No se pudo borrar el aporte'));
    } finally {
      setDeleting(false);
    }
  };

  const withContribution = (c) => c.contributions.some((k) => touchesRange(k, range));
  const advertisers = [...new Set(campaigns.map(advertiserLabel))].sort();
  const needle = search.trim().toLowerCase();
  const visible = campaigns.filter(
    (c) =>
      (!needle || (c.name || '').toLowerCase().includes(needle) || String(c.campaign_id).includes(needle)) &&
      (segment === 'all' || withContribution(c) === (segment === 'with')) &&
      (!advertiser || advertiserLabel(c) === advertiser),
  );
  const totals = { cost: sumOf(visible, 'cost'), contribution: sumOf(visible, 'contribution') };

  return (
    <div className={styles.container}>
      <header className={styles.header}>
        <div>
          <h1 className={styles.title}>Aportes de marcas (Ads ML)</h1>
          <p className={styles.description}>
            Lo que una marca paga de una campaña de Product Ads deja de restarse en Métricas ML.
          </p>
        </div>
        <div className={styles.range}>
          <label className={styles.rangeField}>
            <span>Desde</span>
            <input
              type="date"
              className={styles.rangeInput}
              value={range.from}
              onChange={(e) => setRange((r) => ({ ...r, from: e.target.value }))}
            />
          </label>
          <label className={styles.rangeField}>
            <span>Hasta</span>
            <input
              type="date"
              className={styles.rangeInput}
              value={range.to}
              onChange={(e) => setRange((r) => ({ ...r, to: e.target.value }))}
            />
          </label>
        </div>
      </header>

      <section className={styles.kpis} aria-label="Resumen de aportes">
        <div className={styles.kpi}>
          <span className={styles.kpiLabel}>Costo Ads del período</span>
          <span className={styles.kpiValue}>{formatSignedMoney(totals.cost)}</span>
          <span className={styles.kpiSub}>
            {visible.length} {visible.length === 1 ? 'campaña' : 'campañas'}
          </span>
        </div>
        <div className={styles.kpi}>
          <span className={styles.kpiLabel}>Aporte de marcas</span>
          <span className={`${styles.kpiValue} ${styles.positive}`}>{formatSignedMoney(totals.contribution)}</span>
          <span className={styles.kpiSub}>
            {totals.cost > 0 ? `${formatPercent((totals.contribution / totals.cost) * 100)} del costo` : '—'}
          </span>
        </div>
        <div className={styles.kpi}>
          <span className={styles.kpiLabel}>Costo neto</span>
          <span className={styles.kpiValue}>{formatSignedMoney(totals.cost - totals.contribution)}</span>
          <span className={styles.kpiSub}>Lo que se resta en Métricas ML</span>
        </div>
        <div className={styles.kpi}>
          <span className={styles.kpiLabel}>Campañas con aporte</span>
          <span className={styles.kpiValue}>
            {visible.filter(withContribution).length} <span className={styles.kpiOf}>de {visible.length}</span>
          </span>
          <span className={styles.kpiSub}>Con un aporte que toca el rango</span>
        </div>
      </section>

      <div className={styles.toolbar}>
        <label className={styles.search}>
          <Search size={14} aria-hidden="true" />
          <input
            type="search"
            className={styles.searchInput}
            aria-label="Buscar campaña"
            placeholder="Buscar campaña…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </label>
        <SegmentedControl label="Aportes" options={SEGMENTS} value={segment} onChange={setSegment} />
        <label className={styles.advertiser}>
          <span>Anunciante</span>
          <select className={styles.advertiserSelect} value={advertiser} onChange={(e) => setAdvertiser(e.target.value)}>
            <option value="">Todos</option>
            {advertisers.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        </label>
      </div>

      {loadError && (
        <div className={styles.alertError} role="alert">
          <AlertTriangle size={16} /> {loadError}
        </div>
      )}

      <div className={styles.tableCard}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th>Campaña</th>
              <th>Estado</th>
              <th className={styles.num}>Costo del período</th>
              <th className={styles.num}>Aporte</th>
              <th className={styles.num}>Neto</th>
              <th>Aportes cargados</th>
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr>
                <td colSpan={6} className={styles.muted}>Cargando...</td>
              </tr>
            )}
            {!loading && campaigns.length > 0 && visible.length === 0 && (
              <tr>
                <td colSpan={6} className={styles.muted}>Ninguna campaña coincide con los filtros.</td>
              </tr>
            )}
            {!loading && campaigns.length === 0 && !loadError && (
              <tr>
                <td colSpan={6} className={styles.muted}>Todavía no hay campañas de Product Ads sincronizadas.</td>
              </tr>
            )}
            {!loading &&
              visible.map((c) => {
                const status = STATUS_PILLS[c.status];
                return (
                  <tr key={`${c.advertiser_id}-${c.campaign_id}`}>
                    <td>
                      <div className={styles.campaign}>
                        <span className={styles.campaignName}>{c.name || `Campaña ${c.campaign_id}`}</span>
                        <StatusPill tone="info">{advertiserLabel(c)}</StatusPill>
                      </div>
                      <span className={styles.campaignId}>{c.campaign_id}</span>
                    </td>
                    <td>
                      {status ? (
                        <StatusPill tone={status.tone} dot>{status.text}</StatusPill>
                      ) : (
                        <span className={styles.muted}>{c.status || '—'}</span>
                      )}
                    </td>
                    <td className={styles.num}>{formatSignedMoney(c.cost)}</td>
                    <td className={`${styles.num} ${c.contribution > 0 ? styles.positive : styles.muted}`}>
                      {formatSignedMoney(c.contribution)}
                    </td>
                    <td className={styles.num}>{formatSignedMoney(c.cost - c.contribution)}</td>
                    <td>
                      <div className={styles.chips}>
                        {c.contributions.length === 0 ? (
                          <span className={styles.none}>Sin aportes</span>
                        ) : (
                          <ul className={styles.chipList}>
                            {c.contributions.map((k) => (
                              <ContributionItem
                                key={k.id}
                                c={k}
                                canManage={canManage}
                                onEdit={setEditing}
                                onDelete={setDeleteTarget}
                              />
                            ))}
                          </ul>
                        )}
                        {canManage && (
                          <button
                            type="button"
                            className={styles.addLink}
                            aria-label="Agregar aporte"
                            onClick={() => setCreatingFor(c)}
                          >
                            <Plus size={14} /> Aporte
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
          </tbody>
          {!loading && campaigns.length > 0 && (
            <tfoot>
              <tr>
                <td colSpan={2}>
                  Total ({visible.length} de {campaigns.length} {campaigns.length === 1 ? 'campaña' : 'campañas'})
                </td>
                <td className={styles.num}>{formatSignedMoney(totals.cost)}</td>
                <td className={`${styles.num} ${totals.contribution > 0 ? styles.positive : styles.muted}`}>
                  {formatSignedMoney(totals.contribution)}
                </td>
                <td className={styles.num}>{formatSignedMoney(totals.cost - totals.contribution)}</td>
                <td />
              </tr>
            </tfoot>
          )}
        </table>
      </div>

      <p className={styles.footnote}>
        <Info size={14} aria-hidden="true" /> El aporte de monto fijo se reparte por costo entre los días del rango.
        Un aporte «Diferencia» cuenta como máximo lo gastado en el rango.
      </p>

      {creatingFor && (
        <AportesAdsMLForm
          title="Nuevo aporte"
          initial={{ advertiser_id: creatingFor.advertiser_id, campaign_id: creatingFor.campaign_id }}
          submit={(body) => api.post('/ml-ads/contributions', body)}
          settlementLabels={SETTLEMENT_LABELS}
          onClose={() => setCreatingFor(null)}
          onSaved={handleSaved}
        />
      )}

      {editing && (
        <AportesAdsMLForm
          title="Editar aporte"
          initial={editing}
          submit={(body) => api.put(`/ml-ads/contributions/${editing.id}`, body)}
          settlementLabels={SETTLEMENT_LABELS}
          onClose={() => setEditing(null)}
          onSaved={handleSaved}
        />
      )}

      <ModalTesla
        isOpen={deleteTarget != null}
        onClose={closeDelete}
        title="Borrar aporte"
        size="sm"
        footer={
          <div className={styles.modalFooter}>
            <button type="button" className={styles.btnSecondary} onClick={closeDelete}>
              Cancelar
            </button>
            <button type="button" className={styles.btnDanger} onClick={handleConfirmDelete} disabled={deleting}>
              <Trash2 size={14} /> Borrar
            </button>
          </div>
        }
      >
        <p className={styles.description}>El costo que cubría este aporte vuelve a descontarse en Métricas ML.</p>
        {deleteError && (
          <div className={styles.alertError} role="alert">
            <AlertTriangle size={16} /> {deleteError}
          </div>
        )}
      </ModalTesla>
    </div>
  );
}
