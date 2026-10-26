/**
 * AportesAdsMLForm — the modal form of a brand contribution (ml-ads-brand-contribution S10), laid out as the Stitch
 * "Agregar aporte" modal (ml-ads-contribution-redesign S4).
 *
 * The page decides where the body goes through `submit(body)` (`POST /ml-ads/contributions` or a PUT, which need
 * `ml_metricas.gestionar_aportes_ads`, S7), so the same form serves any write of a contribution. A fixed amount
 * must say how it settles and a percentage must not (S6): the backend answers 422 otherwise, so the body carries
 * `settlement` only for a fixed amount. The backend's 422 message (overlapping range, unknown campaign) is shown in
 * the form, which stays open. While the body is complete, `GET /ml-ads/contributions/preview` says what it would
 * cover; a failed preview just shows nothing.
 */
import { useState, useEffect, useRef } from 'react';
import { AlertTriangle } from 'lucide-react';
import ModalTesla from '../components/ModalTesla';
import { SegmentedControl } from '../components/kit';
import api from '../services/api';
import { formatSignedMoney } from '../utils/ventasMlTone';
import { apiErrorMessage } from '../utils/apiErrorMessage';
import styles from './AportesAdsMLForm.module.css';

const KINDS = [
  { value: 'percentage', label: 'Porcentaje del costo' },
  { value: 'fixed_amount', label: 'Monto fijo' },
];

const SETTLEMENTS = [
  { value: 'full', title: 'Se recibe todo', text: 'La marca paga el monto completo aunque la campaña gaste menos.' },
  { value: 'refund_difference', title: 'Devuelve la diferencia', text: 'Si la campaña gasta menos, solo cuenta lo gastado.' },
];

const PREVIEW_DELAY_MS = 300;

const campaignKey = (advertiserId, campaignId) => (campaignId == null ? '' : `${advertiserId}-${campaignId}`);

/**
 * The form state from `initial`, shaped like the API's contribution: a new one passes `advertiser_id` and
 * `campaign_id` (or nothing, to choose the campaign in the form), so every other field starts empty.
 */
function initialForm(initial) {
  return {
    campaign: campaignKey(initial.advertiser_id, initial.campaign_id),
    kind: initial.kind || 'percentage',
    value: initial.value == null ? '' : String(initial.value),
    settlement: initial.settlement || '',
    dateFrom: initial.date_from || '',
    dateTo: initial.date_to || '',
    brand: initial.brand || '',
    note: initial.note || '',
  };
}

function payloadOf(form) {
  const [advertiserId, campaignId] = form.campaign.split('-').map(Number);
  const body = {
    advertiser_id: advertiserId,
    campaign_id: campaignId,
    kind: form.kind,
    value: Number(form.value),
    date_from: form.dateFrom,
    date_to: form.dateTo,
    brand: form.brand.trim() || null,
    note: form.note.trim() || null,
  };
  if (form.kind === 'fixed_amount') body.settlement = form.settlement;
  return body;
}

function validate(form) {
  if (!form.campaign) return 'Elegí la campaña.';
  if (!(Number(form.value) > 0)) return 'El valor tiene que ser mayor a cero.';
  if (form.kind === 'percentage' && Number(form.value) > 100) return 'Un porcentaje no puede superar 100.';
  if (form.kind === 'fixed_amount' && !form.settlement) return 'Elegí si se recibe todo o se devuelve la diferencia.';
  if (!form.dateFrom || !form.dateTo) return 'Completá el rango de fechas.';
  if (form.dateFrom > form.dateTo) return 'La fecha desde no puede ser posterior a la fecha hasta.';
  return null;
}

/**
 * `initial`: the contribution to start from (see `initialForm`); with an `id` it is an edit, and an edit cannot
 * change campaign. `campaigns`: the page's campaigns, the choices of "Campaña". `submit(body)`: sends the body and
 * resolves when saved.
 */
export default function AportesAdsMLForm({ title, initial, campaigns, submit, onClose, onSaved }) {
  const [form, setForm] = useState(() => initialForm(initial));
  const [formError, setFormError] = useState(null);
  const [saving, setSaving] = useState(false);
  const [preview, setPreview] = useState(null);
  const latestPreview = useRef(0);

  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));
  const complete = validate(form) === null;
  const body = complete ? JSON.stringify(payloadOf(form)) : null;

  useEffect(() => {
    const request = ++latestPreview.current;
    setPreview(null);
    if (!body) return undefined;
    const timer = setTimeout(async () => {
      try {
        const { data } = await api.get('/ml-ads/contributions/preview', { params: JSON.parse(body) });
        if (request === latestPreview.current) setPreview(data);
      } catch {
        // Only the line is lost; saving still reports its own errors.
      }
    }, PREVIEW_DELAY_MS);
    return () => clearTimeout(timer);
  }, [body]);

  const handleSave = async (e) => {
    e.preventDefault();
    const invalid = validate(form);
    if (invalid) {
      setFormError(invalid);
      return;
    }
    setSaving(true);
    setFormError(null);
    try {
      await submit(payloadOf(form));
      onSaved();
    } catch (err) {
      setFormError(apiErrorMessage(err, 'No se pudo guardar el aporte'));
      setSaving(false);
    }
  };

  const percentage = form.kind === 'percentage';

  return (
    <ModalTesla
      isOpen
      onClose={onClose}
      title={title}
      subtitle="El aporte se descuenta del costo de Ads de la campaña en Métricas ML."
      size="md"
      footer={
        <div className={styles.modalFooter}>
          <button type="button" className={styles.btnSecondary} onClick={onClose}>
            Cancelar
          </button>
          <button type="submit" form="aporte-ads-form" className={styles.btnPrimary} disabled={saving}>
            {saving ? 'Guardando...' : 'Guardar aporte'}
          </button>
        </div>
      }
    >
      <form id="aporte-ads-form" className={styles.form} onSubmit={handleSave} noValidate>
        {formError && (
          <div className={styles.alertError} role="alert">
            <AlertTriangle size={16} /> {formError}
          </div>
        )}
        <label className={styles.field} htmlFor="aporte-campana">
          <span className={styles.label}>Campaña</span>
          <select
            id="aporte-campana"
            className={styles.input}
            value={form.campaign}
            onChange={set('campaign')}
            disabled={initial.id != null}
          >
            <option value="">Elegí una campaña</option>
            {campaigns.map((c) => (
              <option key={campaignKey(c.advertiser_id, c.campaign_id)} value={campaignKey(c.advertiser_id, c.campaign_id)}>
                {c.name || `Campaña ${c.campaign_id}`} · {c.campaign_id} · {c.advertiser_name || c.advertiser_id}
              </option>
            ))}
          </select>
        </label>

        <div className={styles.field}>
          <span className={styles.label}>Tipo de aporte</span>
          <SegmentedControl
            label="Tipo de aporte"
            options={KINDS}
            value={form.kind}
            onChange={(kind) => setForm((f) => ({ ...f, kind }))}
          />
        </div>

        <label className={styles.field} htmlFor="aporte-valor">
          <span className={styles.label}>{percentage ? 'Porcentaje' : 'Monto'}</span>
          <span className={styles.affixed}>
            {!percentage && <span className={styles.affix}>$</span>}
            <input
              id="aporte-valor"
              aria-label={percentage ? 'Porcentaje' : 'Monto'}
              type="number"
              min="0"
              step="0.01"
              className={styles.affixedInput}
              value={form.value}
              onChange={set('value')}
            />
            {percentage && <span className={styles.affix}>%</span>}
          </span>
        </label>

        {!percentage && (
          <fieldset className={styles.settlement}>
            <legend className={styles.label}>Cómo se liquida</legend>
            {SETTLEMENTS.map((option) => (
              <label
                key={option.value}
                className={`${styles.optionCard} ${form.settlement === option.value ? styles.optionCardActive : ''}`}
              >
                <input
                  type="radio"
                  name="settlement"
                  aria-label={option.title}
                  value={option.value}
                  checked={form.settlement === option.value}
                  onChange={set('settlement')}
                />
                <span className={styles.optionTitle}>{option.title}</span>
                <span className={styles.optionText}>{option.text}</span>
              </label>
            ))}
          </fieldset>
        )}

        <div className={styles.field}>
          <span className={styles.label}>Rango de fechas</span>
          <div className={styles.dates}>
            <label className={styles.dateField} htmlFor="aporte-desde">
              <span>Desde</span>
              <input id="aporte-desde" type="date" className={styles.input} value={form.dateFrom} onChange={set('dateFrom')} />
            </label>
            <label className={styles.dateField} htmlFor="aporte-hasta">
              <span>Hasta</span>
              <input id="aporte-hasta" type="date" className={styles.input} value={form.dateTo} onChange={set('dateTo')} />
            </label>
          </div>
        </div>

        <label className={styles.field} htmlFor="aporte-marca">
          <span className={styles.label}>Marca</span>
          <input
            id="aporte-marca"
            type="text"
            maxLength={120}
            className={styles.input}
            value={form.brand}
            onChange={set('brand')}
          />
        </label>
        <label className={styles.field} htmlFor="aporte-nota">
          <span className={styles.label}>Nota (opcional)</span>
          <textarea
            id="aporte-nota"
            maxLength={1000}
            rows={2}
            className={styles.input}
            placeholder="Ej.: acuerdo comercial Q4 con Epson"
            value={form.note}
            onChange={set('note')}
          />
        </label>

        {preview && (
          <p className={styles.preview}>
            {`Costo de la campaña en el rango: ${formatSignedMoney(preview.spend)} · Aporte que cuenta: ${formatSignedMoney(
              preview.counted,
            )} · Neto: ${formatSignedMoney(preview.net)}`}
          </p>
        )}
      </form>
    </ModalTesla>
  );
}
