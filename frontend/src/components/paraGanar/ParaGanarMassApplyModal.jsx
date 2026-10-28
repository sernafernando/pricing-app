import { useEffect, useState } from 'react';
import ModalTesla from '../ModalTesla';
import api from '../../services/api';
import { usePermisos } from '../../contexts/PermisosContext';
import {
  CRITERIA_FLAG_FIELDS,
  EMPTY_CRITERIA_FORM,
  MASS_CRITERIA_NUMBER_FIELDS,
  formToMassPayload,
} from './criteriaFields';
import styles from '../../pages/ParaGanarAdvisor.module.css';

export default function ParaGanarMassApplyModal({
  isOpen,
  onClose,
  scopeTotal,
  scopeQueryParams,
  onApplied,
}) {
  const { tienePermiso } = usePermisos();
  const canWrite = tienePermiso('productos.editar_precios');
  const [form, setForm] = useState(EMPTY_CRITERIA_FORM);
  const [applying, setApplying] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!isOpen) return;
    setForm(EMPTY_CRITERIA_FORM);
    setError(null);
    setApplying(false);
  }, [isOpen]);

  const setField = (key, value) => {
    setError(null);
    setForm((prev) => ({ ...prev, [key]: value }));
  };

  const onConfirm = async () => {
    if (!canWrite || applying || scopeTotal <= 0) return;
    setApplying(true);
    setError(null);
    try {
      const payload = formToMassPayload(form);
      const { data } = await api.post('/para-ganar/criterios/aplicar-masivo', payload, {
        params: scopeQueryParams,
      });
      onApplied?.(data);
      onClose();
    } catch (err) {
      const detail = err.response?.data?.detail;
      if (typeof detail === 'string') {
        setError(detail);
      } else if (err.response?.status === 403) {
        setError('No tenés permiso para aplicar criterios (productos.editar_precios).');
      } else if (err.response?.status === 422) {
        setError('Revisá los valores o el alcance: no se pudo aplicar.');
      } else {
        setError('No se pudieron aplicar los criterios al filtro.');
      }
    } finally {
      setApplying(false);
    }
  };

  return (
    <ModalTesla
      isOpen={isOpen}
      onClose={onClose}
      title="Aplicar criterios al filtro"
      subtitle={`${scopeTotal.toLocaleString('es-AR')} MLAs en alcance · sobreescribe con y sin criterio`}
      size="md"
      closeOnOverlay={false}
      footer={
        <div className={styles.massModalFooter}>
          <button type="button" className={styles.massModalCancel} onClick={onClose} disabled={applying}>
            Cancelar
          </button>
          <button
            type="button"
            className={styles.bulkBtn}
            onClick={onConfirm}
            disabled={applying || !canWrite || scopeTotal <= 0}
            title={canWrite ? undefined : 'Requiere productos.editar_precios'}
          >
            {applying ? 'Aplicando…' : `Aplicar a ${scopeTotal.toLocaleString('es-AR')} MLAs`}
          </button>
        </div>
      }
    >
      <p className={styles.massModalLead}>
        Solo markup, TOP y flags (sin topes de precio). Las filas que ya tenían criterio se pisan.
      </p>
      <div className={styles.massModalForm}>
        {MASS_CRITERIA_NUMBER_FIELDS.map((field) => (
          <label key={field.key} className={styles.criteriaField}>
            <span>{field.label}</span>
            <input
              className={styles.criteriaInput}
              type="text"
              inputMode="decimal"
              placeholder={field.placeholder}
              value={form[field.key]}
              disabled={applying || !canWrite}
              title={field.hint}
              onChange={(e) => setField(field.key, e.target.value)}
            />
          </label>
        ))}
        {CRITERIA_FLAG_FIELDS.map((field) => (
          <label key={field.key} className={styles.criteriaCheck}>
            <input
              type="checkbox"
              checked={Boolean(form[field.key])}
              disabled={applying || !canWrite}
              onChange={(e) => setField(field.key, e.target.checked)}
            />
            {field.label}
          </label>
        ))}
      </div>
      {error && (
        <p className={styles.criteriaFeedbackError} role="alert">
          {error}
        </p>
      )}
    </ModalTesla>
  );
}
