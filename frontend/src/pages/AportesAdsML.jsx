/**
 * AportesAdsML — brand contributions to Product Ads campaigns (ml-ads-brand-contribution S10).
 *
 * Lists every catalogued campaign with its cost in a date range (`GET /ml-ads/campaigns`, `ml_metricas.ver_ganancia`)
 * and all its contributions; with `ml_metricas.gestionar_aportes_ads` (S7) it also loads new ones
 * (`AportesAdsMLForm`). A contribution is a percentage or a fixed amount over a date range (S3/S4); a fixed amount
 * says how it settles (S6). Métricas ML stops subtracting the part of the cost a contribution covers (S9).
 */
import { useState, useEffect, useCallback, useRef } from 'react';
import { AlertTriangle, Plus } from 'lucide-react';
import { usePermisos } from '../contexts/PermisosContext';
import api from '../services/api';
import AportesAdsMLForm from './AportesAdsMLForm';
import { registrarPagina } from '../registry/tabRegistry';
import { formatSignedMoney } from '../utils/ventasMlTone';
import styles from './AportesAdsML.module.css';

registrarPagina({ pagePath: '/ml-ads-aportes', pageLabel: 'Aportes de marcas (Ads ML)', tabs: [] });

const SETTLEMENT_LABELS = { full: 'Se recibe todo', refund_difference: 'Se devuelve la diferencia' };

const isoDay = (d) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;

const errorMessage = (err, fallback) =>
  err?.response?.data?.error?.message || err?.response?.data?.detail || fallback;

const formatDay = (iso) => iso.split('-').reverse().join('/');

function ContributionItem({ c }) {
  const value = c.kind === 'percentage' ? `${c.value}%` : formatSignedMoney(c.value);
  return (
    <li className={styles.contribution}>
      <span className={styles.contributionValue}>{value}</span>
      {c.settlement && <span className={styles.pill}>{SETTLEMENT_LABELS[c.settlement]}</span>}
      <span className={styles.muted}>
        {formatDay(c.date_from)} – {formatDay(c.date_to)}
        {c.brand ? ` · ${c.brand}` : ''}
      </span>
      {c.note && <span className={styles.note}>{c.note}</span>}
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
      setLoadError(errorMessage(err, 'No se pudieron cargar las campañas'));
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
    fetchCampaigns();
  };

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <div>
          <h1 className={styles.title}>Aportes de marcas (Ads ML)</h1>
          <p className={styles.description}>
            La parte del costo de una campaña de Product Ads que paga la marca no se descuenta en Métricas ML.
          </p>
        </div>
        <div className={styles.filters}>
          <label className={styles.field}>
            <span className={styles.label}>Desde</span>
            <input
              type="date"
              className={styles.input}
              value={range.from}
              onChange={(e) => setRange((r) => ({ ...r, from: e.target.value }))}
            />
          </label>
          <label className={styles.field}>
            <span className={styles.label}>Hasta</span>
            <input
              type="date"
              className={styles.input}
              value={range.to}
              onChange={(e) => setRange((r) => ({ ...r, to: e.target.value }))}
            />
          </label>
        </div>
      </div>

      {loadError && (
        <div className={styles.alertError} role="alert">
          <AlertTriangle size={16} /> {loadError}
        </div>
      )}

      <div className="table-container-tesla">
        <table className="table-tesla">
          <thead className="table-tesla-head">
            <tr>
              <th>Campaña</th>
              <th>Estado</th>
              <th className={styles.num}>Costo del período</th>
              <th>Aportes</th>
              {canManage && <th aria-label="Acciones" />}
            </tr>
          </thead>
          <tbody className="table-tesla-body">
            {loading && (
              <tr>
                <td colSpan={canManage ? 5 : 4} className={styles.muted}>Cargando...</td>
              </tr>
            )}
            {!loading && campaigns.length === 0 && !loadError && (
              <tr>
                <td colSpan={canManage ? 5 : 4} className={styles.muted}>Todavía no hay campañas de Product Ads sincronizadas.</td>
              </tr>
            )}
            {!loading &&
              campaigns.map((c) => (
                <tr key={`${c.advertiser_id}-${c.campaign_id}`}>
                  <td>{c.name || `Campaña ${c.campaign_id}`}</td>
                  <td className={styles.muted}>{c.status || '—'}</td>
                  <td className={styles.num}>{formatSignedMoney(c.cost)}</td>
                  <td>
                    {c.contributions.length === 0 ? (
                      <span className={styles.muted}>Sin aportes</span>
                    ) : (
                      <ul className={styles.contributions}>
                        {c.contributions.map((k) => (
                          <ContributionItem key={k.id} c={k} />
                        ))}
                      </ul>
                    )}
                  </td>
                  {canManage && (
                    <td className={styles.colActions}>
                      <button
                        type="button"
                        className={styles.btnSecondary}
                        onClick={() => setCreatingFor(c)}
                      >
                        <Plus size={14} /> Agregar aporte
                      </button>
                    </td>
                  )}
                </tr>
              ))}
          </tbody>
        </table>
      </div>

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
    </div>
  );
}
