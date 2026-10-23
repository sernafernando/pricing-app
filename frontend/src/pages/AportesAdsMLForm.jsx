/**
 * AportesAdsMLForm — the modal form of a brand contribution (ml-ads-brand-contribution S10).
 *
 * The page decides where the body goes through `submit(body)` (`POST /ml-ads/contributions`, which needs
 * `ml_metricas.gestionar_aportes_ads`, S7), so the same form can serve any write of a contribution. A fixed amount must say how it settles and a percentage must not (S6): the backend answers 422 otherwise, so the
 * body carries `settlement` only for a fixed amount. The backend's 422 message (overlapping range, unknown campaign)
 * is shown in the form, which stays open.
 */
import { useState } from 'react';
import { AlertTriangle } from 'lucide-react';
import ModalTesla from '../components/ModalTesla';
import styles from './AportesAdsMLForm.module.css';

/**
 * The form state from `initial`, shaped like the API's contribution: a new one passes only `advertiser_id` and
 * `campaign_id`, so every other field starts empty.
 */
function initialForm(initial) {
  return {
    advertiserId: initial.advertiser_id,
    campaignId: initial.campaign_id,
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
  const body = {
    advertiser_id: form.advertiserId,
    campaign_id: form.campaignId,
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
  if (!(Number(form.value) > 0)) return 'El valor tiene que ser mayor a cero.';
  if (form.kind === 'percentage' && Number(form.value) > 100) return 'Un porcentaje no puede superar 100.';
  if (form.kind === 'fixed_amount' && !form.settlement) return 'Elegí si se recibe todo o se devuelve la diferencia.';
  if (!form.dateFrom || !form.dateTo) return 'Completá el rango de fechas.';
  if (form.dateFrom > form.dateTo) return 'La fecha desde no puede ser posterior a la fecha hasta.';
  return null;
}

/**
 * `initial`: the contribution to start from (see `initialForm`). `submit(body)`: sends the body and resolves when
 * saved. `settlementLabels`: the page's labels of each fixed-amount settlement, so the list and the form say the same.
 */
export default function AportesAdsMLForm({ title, initial, submit, settlementLabels, onClose, onSaved }) {
  const [form, setForm] = useState(() => initialForm(initial));
  const [formError, setFormError] = useState(null);
  const [saving, setSaving] = useState(false);

  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));

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
      setFormError(err?.response?.data?.error?.message || err?.response?.data?.detail || 'No se pudo guardar el aporte');
      setSaving(false);
    }
  };

  return (
    <ModalTesla
      isOpen
      onClose={onClose}
      title={title}
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
          <div className={styles.alertError}>
            <AlertTriangle size={16} /> {formError}
          </div>
        )}
        <div className={styles.grid}>
          <label className={styles.field} htmlFor="aporte-tipo">
            <span className={styles.label}>Tipo</span>
            <select id="aporte-tipo" className={styles.input} value={form.kind} onChange={set('kind')}>
              <option value="percentage">Porcentaje</option>
              <option value="fixed_amount">Monto fijo</option>
            </select>
          </label>
          <label className={styles.field} htmlFor="aporte-valor">
            <span className={styles.label}>Valor</span>
            <input
              id="aporte-valor"
              type="number"
              min="0"
              step="0.01"
              className={styles.input}
              value={form.value}
              onChange={set('value')}
            />
          </label>
          <label className={styles.field} htmlFor="aporte-desde">
            <span className={styles.label}>Desde</span>
            <input id="aporte-desde" type="date" className={styles.input} value={form.dateFrom} onChange={set('dateFrom')} />
          </label>
          <label className={styles.field} htmlFor="aporte-hasta">
            <span className={styles.label}>Hasta</span>
            <input id="aporte-hasta" type="date" className={styles.input} value={form.dateTo} onChange={set('dateTo')} />
          </label>
        </div>

        {form.kind === 'fixed_amount' && (
          <fieldset className={styles.settlement}>
            <legend className={styles.label}>Si la campaña gasta menos que el monto</legend>
            {Object.entries(settlementLabels).map(([key, label]) => (
              <label key={key} className={styles.radio}>
                <input
                  type="radio"
                  name="settlement"
                  value={key}
                  checked={form.settlement === key}
                  onChange={set('settlement')}
                />{' '}
                {label}
              </label>
            ))}
          </fieldset>
        )}

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
          <span className={styles.label}>Nota</span>
          <textarea
            id="aporte-nota"
            maxLength={1000}
            rows={2}
            className={styles.input}
            value={form.note}
            onChange={set('note')}
          />
        </label>
      </form>
    </ModalTesla>
  );
}
