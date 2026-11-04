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
 *
 * ml-ads-aportes-robust: the brand is picked from `GET /marcas` and is mandatory (S1); a fixed amount can be typed
 * with IVA, which the backend stores without it (S2); a `full` amount above the range cost is saved only after
 * confirming it (S3); and the form says when the range ends after the last day with Ads data (S4).
 */
import { useState, useEffect, useRef } from 'react';
import { AlertTriangle } from 'lucide-react';
import ModalTesla from '../components/ModalTesla';
import { SegmentedControl } from '../components/kit';
import api from '../services/api';
import { formatSignedMoney } from '../utils/ventasMlTone';
import { formatDate } from '../utils/displayAds';
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
    ivaIncluded: false,
    confirmOverSpend: false,
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
  if (form.kind === 'fixed_amount') {
    body.settlement = form.settlement;
    if (form.ivaIncluded) body.iva_included = true;
  }
  return body;
}

/** What blocks saving; `previewing` skips the brand, which changes nothing the preview counts. */
function validate(form, { previewing = false } = {}) {
  if (!previewing && !form.brand.trim()) return 'Elegí la marca.';
  if (!form.campaign) return 'Elegí la campaña.';
  if (!(Number(form.value) > 0)) return 'El valor tiene que ser mayor a cero.';
  if (form.kind === 'percentage' && Number(form.value) > 100) return 'Un porcentaje no puede superar 100.';
  if (form.kind === 'fixed_amount' && !form.settlement) return 'Elegí si se recibe todo o se devuelve la diferencia.';
  if (!form.dateFrom || !form.dateTo) return 'Completá el rango de fechas.';
  if (form.dateFrom > form.dateTo) return 'La fecha desde no puede ser posterior a la fecha hasta.';
  return null;
}

const OVER_SPEND_ERROR = 'Confirmá que el aporte supera el costo de la campaña en el rango.';
// The over-spend is measured on one campaign, kind, amount (with or without IVA), range and settlement: changing any
// of them asks again.
const RESETS_OVER_SPEND = new Set(['campaign', 'kind', 'value', 'ivaIncluded', 'dateFrom', 'dateTo', 'settlement']);

/** A `full` amount the backend flags above the range spend (S3): by the preview, or by a save it rejected on `value`. */
const fullAmount = (form) => form.kind === 'fixed_amount' && form.settlement === 'full';

/**
 * The brand list (`GET /marcas`), keeping an edited aporte's brand visible even when the list lacks it. `failed`
 * says the list could not load, so the form can say why no brand can be picked.
 */
function useMarcas(current) {
  const [state, setState] = useState({ marcas: [], failed: false });
  useEffect(() => {
    let active = true;
    api
      .get('/marcas')
      .then((response) => active && setState({ marcas: response.data?.marcas ?? [], failed: false }))
      .catch(() => active && setState({ marcas: [], failed: true }));
    return () => {
      active = false;
    };
  }, []);
  const marcas = current && !state.marcas.includes(current) ? [current, ...state.marcas] : state.marcas;
  return { marcas, failed: state.failed };
}

const AMOUNT = new Intl.NumberFormat('es-AR', { maximumFractionDigits: 2 });

/**
 * The typed amount -> the form's value ("500000.5"). With a comma it is es-AR ("1.500.000,5": dots group thousands);
 * without one, a single dot followed by at most two digits is a decimal point ("1500.50", "12.5"), and any other dot
 * groups thousands ("1.500", "1.500.000"). A decimal point is never dropped, so an amount never grows by 100.
 */
function amountOf(typed) {
  const text = typed.trim();
  if (text.includes(',')) return text.replace(/\./g, '').replace(',', '.');
  if (/^\d*\.\d{0,2}$/.test(text)) return text;
  return text.replace(/\./g, '');
}

/** The value as es-AR shows it ("500.000,5") while the field is not being edited. */
const shownAmount = (value) => (value !== '' && Number.isFinite(Number(value)) ? AMOUNT.format(Number(value)) : value);

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
  const { marcas, failed: marcasFailed } = useMarcas(initial.brand || '');
  // The amount as typed while the field has focus (null otherwise, when it shows es-AR grouping).
  const [amountText, setAmountText] = useState(null);
  // The backend rejected a save on `value`: it is the over-spend rule, even if the preview never answered.
  const [rejectedOverSpend, setRejectedOverSpend] = useState(false);

  // A confirmation (or a backend rejection) holds only for the inputs it was given on (`RESETS_OVER_SPEND`).
  const update = (key, value) => {
    const resets = RESETS_OVER_SPEND.has(key);
    setForm((f) => ({ ...f, [key]: value, ...(resets ? { confirmOverSpend: false } : {}) }));
    if (resets) setRejectedOverSpend(false);
  };
  const set = (key) => (e) => update(key, e.target.value);
  const toggle = (key) => (e) => update(key, e.target.checked);
  const body = validate(form, { previewing: true }) === null ? JSON.stringify(payloadOf(form)) : null;
  const overSpend = fullAmount(form) && (preview?.over_spend === true || rejectedOverSpend);
  const pastData = preview?.data_through && form.dateTo > preview.data_through ? preview.data_through : null;

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
    const invalid = validate(form) || (overSpend && !form.confirmOverSpend ? OVER_SPEND_ERROR : null);
    if (invalid) {
      setFormError(invalid);
      return;
    }
    setSaving(true);
    setFormError(null);
    try {
      const confirmed = overSpend && form.confirmOverSpend;
      await submit(confirmed ? { ...payloadOf(form), confirm_over_spend: true } : payloadOf(form));
      onSaved();
    } catch (err) {
      const rejectedOnValue = err?.response?.status === 422 && err.response.data?.error?.field === 'value';
      if (rejectedOnValue && fullAmount(form)) setRejectedOverSpend(true);
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
        <label className={styles.field} htmlFor="aporte-marca">
          <span className={styles.label}>Marca</span>
          <select id="aporte-marca" className={styles.input} value={form.brand} onChange={set('brand')}>
            <option value="">Elegí una marca</option>
            {marcas.map((marca) => (
              <option key={marca} value={marca}>
                {marca}
              </option>
            ))}
          </select>
          {marcasFailed && (
            <span className={styles.fieldError} role="alert">
              No se pudo cargar la lista de marcas. Cerrá el formulario y volvé a abrirlo.
            </span>
          )}
        </label>
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
            onChange={(kind) => update('kind', kind)}
          />
        </div>

        <label className={styles.field} htmlFor="aporte-valor">
          <span className={styles.label}>{percentage ? 'Porcentaje' : 'Monto'}</span>
          <span className={styles.amountBox}>
            {!percentage && <span className={styles.affix}>$</span>}
            <input
              id="aporte-valor"
              aria-label={percentage ? 'Porcentaje' : 'Monto'}
              type="text"
              inputMode="decimal"
              autoComplete="off"
              className={styles.amountBare}
              value={amountText ?? shownAmount(form.value)}
              onFocus={() => setAmountText(form.value.replace('.', ','))}
              onBlur={() => setAmountText(null)}
              onChange={(e) => {
                setAmountText(e.target.value);
                update('value', amountOf(e.target.value));
              }}
            />
            {percentage && <span className={styles.affix}>%</span>}
          </span>
        </label>

        {!percentage && (
          <div className={styles.check}>
            <input
              id="aporte-iva"
              type="checkbox"
              aria-describedby="aporte-iva-hint"
              checked={form.ivaIncluded}
              onChange={toggle('ivaIncluded')}
            />
            <label htmlFor="aporte-iva">El monto incluye IVA</label>
            <span id="aporte-iva-hint" className={styles.checkHint}>
              Se guarda sin IVA, como el costo de Ads.
            </span>
          </div>
        )}

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

        {preview && (
          <dl className={styles.preview} aria-label="Lo que cubre el aporte">
            <dt>Costo de la campaña en el rango</dt>
            <dd>{formatSignedMoney(preview.spend)}</dd>
            <dt>Aporte que cuenta</dt>
            <dd>{formatSignedMoney(preview.counted)}</dd>
            <dt>Neto</dt>
            <dd>{formatSignedMoney(preview.net)}</dd>
          </dl>
        )}

        {pastData && (
          <p className={styles.warning} role="status">
            {`Hay datos de Ads hasta el ${formatDate(pastData)}: lo que cae después todavía no se cargó y el aporte va a cambiar cuando llegue.`}
          </p>
        )}

        {overSpend && (
          <div className={`${styles.check} ${styles.warning}`}>
            <input
              id="aporte-confirmar"
              type="checkbox"
              aria-describedby="aporte-confirmar-hint"
              checked={form.confirmOverSpend}
              onChange={toggle('confirmOverSpend')}
            />
            <label htmlFor="aporte-confirmar">Confirmo que el aporte supera el costo de la campaña en el rango</label>
            <span id="aporte-confirmar-hint" className={styles.checkHint}>
              El neto queda negativo: Métricas ML suma la diferencia.
            </span>
          </div>
        )}

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
      </form>
    </ModalTesla>
  );
}
