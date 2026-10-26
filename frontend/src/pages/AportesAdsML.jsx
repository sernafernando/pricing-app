/**
 * AportesAdsML — brand contributions to Product Ads campaigns (ml-ads-brand-contribution S10).
 *
 * Lists every catalogued campaign with its cost in a date range (`GET /ml-ads/campaigns`, `ml_metricas.ver_ganancia`)
 * and all its contributions; with `ml_metricas.gestionar_aportes_ads` (S7) it also loads and edits them
 * (`AportesAdsMLForm`) and deletes them behind a confirmation modal. A contribution is a percentage or a fixed amount over a date range (S3/S4); a fixed amount
 * says how it settles (S6). Métricas ML stops subtracting the part of the cost a contribution covers (S9).
 *
 * Layout from the Stitch redesign (ml-ads-contribution-redesign S3): APORTE and NETO per campaign as the backend
 * computes them, one-line contribution chips and a Total row.
 */
import { useState, useEffect, useCallback, useRef } from 'react';
import { AlertTriangle, Info, Pencil, Plus, Trash2 } from 'lucide-react';
import { usePermisos } from '../contexts/PermisosContext';
import api from '../services/api';
import ModalTesla from '../components/ModalTesla';
import { StatusPill } from '../components/kit';
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

const isoDay = (d) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;

// `2026-10-01` -> `01/10/26`: a contribution may sit in any year, the chip has no room for four digits.
const formatDay = (iso) => {
  const [year, month, day] = iso.split('-');
  return `${day}/${month}/${year.slice(2)}`;
};

const advertiserLabel = (c) => c.advertiser_name || `Anunciante ${c.advertiser_id}`;
const sumOf = (rows, key) => rows.reduce((total, row) => total + (row[key] || 0), 0);

function ContributionItem({ c, canManage, onEdit, onDelete }) {
  const value = c.kind === 'percentage' ? `${c.value}%` : formatSignedMoney(c.value);
  const badge = SETTLEMENT_BADGES[c.settlement];
  return (
    <li className={styles.chip} title={[c.brand, c.note].filter(Boolean).join(' · ') || undefined}>
      <span className={styles.chipValue}>{value}</span>
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

  const totals = { cost: sumOf(campaigns, 'cost'), contribution: sumOf(campaigns, 'contribution') };

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
            {!loading && campaigns.length === 0 && !loadError && (
              <tr>
                <td colSpan={6} className={styles.muted}>Todavía no hay campañas de Product Ads sincronizadas.</td>
              </tr>
            )}
            {!loading &&
              campaigns.map((c) => {
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
                <td colSpan={2}>Total ({campaigns.length} campañas)</td>
                <td className={styles.num}>{formatSignedMoney(totals.cost)}</td>
                <td className={`${styles.num} ${styles.positive}`}>{formatSignedMoney(totals.contribution)}</td>
                <td className={styles.num}>{formatSignedMoney(totals.cost - totals.contribution)}</td>
                <td />
              </tr>
            </tfoot>
          )}
        </table>
      </div>

      <p className={styles.footnote}>
        <Info size={14} aria-hidden="true" /> El aporte de monto fijo se reparte por costo entre los días del rango.
        &apos;Devuelve diferencia&apos; cuenta como máximo lo gastado en el rango.
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
