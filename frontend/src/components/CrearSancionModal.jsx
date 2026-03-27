import { useState } from 'react';
import { rrhhAPI } from '../services/api';
import { HelpCircle, X } from 'lucide-react';
import { extractPlaceholders, interpolateText } from '../hooks/usePlaceholders';
import styles from '../pages/RRHHSanciones.module.css';

const INITIAL_FORM = {
  empleado_id: '',
  tipo_sancion_id: '',
  fecha: new Date().toISOString().slice(0, 10),
  motivo: '',
  descripcion: '',
  texto_sancion: '',
  fecha_desde: '',
  fecha_hasta: '',
};

/**
 * Modal para crear una nueva sanción.
 * Incluye selector de empleado, tipo, texto predefinido con placeholders dinámicos.
 */
export default function CrearSancionModal({
  empleados,
  tiposActivos,
  textosActivos,
  placeholders,
  onClose,
  onCreated,
}) {
  const {
    knownPlaceholders,
    placeholderValues,
    setPlaceholderValues,
    currentPlaceholders,
    setCurrentPlaceholders,
    refreshPlaceholderValues,
    setShowPlaceholderHelp,
  } = placeholders;

  const [form, setForm] = useState({ ...INITIAL_FORM, fecha: new Date().toISOString().slice(0, 10) });
  const [empleadoSearch, setEmpleadoSearch] = useState('');
  const [selectedTextoPredefinidoId, setSelectedTextoPredefinidoId] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  const handleSelectTextoPredefinido = (textoId) => {
    setSelectedTextoPredefinidoId(textoId);
    if (!textoId) {
      setForm((prev) => ({ ...prev, texto_sancion: '' }));
      setCurrentPlaceholders([]);
      setPlaceholderValues({});
      return;
    }
    const texto = textosActivos.find((t) => t.id === Number(textoId));
    if (!texto) return;
    const template = texto.texto;
    const phs = extractPlaceholders(template);
    const newForm = { ...form, texto_sancion: template };
    setForm(newForm);
    setCurrentPlaceholders(phs);
    refreshPlaceholderValues(newForm, phs);
  };

  const handleSubmit = async () => {
    if (!form.empleado_id || !form.tipo_sancion_id) {
      setError('Empleado y tipo de sancion son obligatorios');
      return;
    }
    if (!form.motivo.trim()) {
      setError('El motivo es obligatorio');
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const payload = {
        empleado_id: Number(form.empleado_id),
        tipo_sancion_id: Number(form.tipo_sancion_id),
        fecha: form.fecha,
        motivo: form.motivo.trim(),
      };
      if (form.descripcion.trim()) {
        payload.descripcion = form.descripcion.trim();
      }
      const textoFinal = currentPlaceholders.length > 0
        ? interpolateText(form.texto_sancion, placeholderValues)
        : form.texto_sancion;
      if (textoFinal.trim()) {
        payload.texto_sancion = textoFinal.trim();
      }
      if (form.fecha_desde) payload.fecha_desde = form.fecha_desde;
      if (form.fecha_hasta) payload.fecha_hasta = form.fecha_hasta;
      if (selectedTextoPredefinidoId) payload.texto_predefinido_id = Number(selectedTextoPredefinidoId);

      await rrhhAPI.crearSancion(payload);
      onCreated();
    } catch (err) {
      setError(err.response?.data?.detail || 'Error al crear la sancion');
    } finally {
      setSaving(false);
    }
  };

  const updateFormAndRefresh = (updates) => {
    const newForm = { ...form, ...updates };
    setForm(newForm);
    refreshPlaceholderValues(newForm);
  };

  return (
    <div className="modal-overlay-tesla">
      <div className="modal-tesla lg" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header-tesla">
          <h2 className="modal-title-tesla">Nueva sancion</h2>
          <button className="btn-close-tesla" onClick={onClose} aria-label="Cerrar modal"><X size={14} /></button>
        </div>
        <div className="modal-body-tesla">
          <div className={styles.formRow}>
            <div className={styles.formGroup}>
              <label>Empleado (Legajo)</label>
              <input
                type="text"
                className={styles.input}
                placeholder="Buscar por legajo o nombre..."
                value={empleadoSearch}
                onChange={(e) => setEmpleadoSearch(e.target.value)}
              />
              <select
                className={`${styles.select} ${styles.empleadoSelect}`}
                value={form.empleado_id}
                onChange={(e) => updateFormAndRefresh({ empleado_id: e.target.value })}
                required
                size={5}
              >
                <option value="">Seleccionar empleado...</option>
                {empleados
                  .filter((emp) => {
                    if (!empleadoSearch) return true;
                    const q = empleadoSearch.toLowerCase();
                    return (
                      (emp.legajo || '').toLowerCase().includes(q) ||
                      (emp.nombre || '').toLowerCase().includes(q) ||
                      (emp.apellido || '').toLowerCase().includes(q) ||
                      (`${emp.apellido} ${emp.nombre}`).toLowerCase().includes(q)
                    );
                  })
                  .map((emp) => (
                    <option key={emp.id} value={emp.id}>
                      {emp.legajo} - {emp.apellido}, {emp.nombre}
                    </option>
                  ))}
              </select>
            </div>
            <div className={styles.formGroup}>
              <label>Tipo de sancion</label>
              <select
                className={styles.select}
                value={form.tipo_sancion_id}
                onChange={(e) => setForm({ ...form, tipo_sancion_id: e.target.value })}
                required
              >
                <option value="">Seleccionar...</option>
                {tiposActivos.map((t) => (
                  <option key={t.id} value={t.id}>{t.nombre}</option>
                ))}
              </select>
            </div>
          </div>
          <div className={styles.formGroup}>
            <div className={styles.labelRow}>
              <label>Texto predefinido (opcional)</label>
              <button
                type="button"
                className={styles.btnHelp}
                onClick={() => setShowPlaceholderHelp(true)}
                title="Ver placeholders disponibles"
              >
                <HelpCircle size={14} />
              </button>
            </div>
            <select
              className={styles.select}
              value={selectedTextoPredefinidoId}
              onChange={(e) => handleSelectTextoPredefinido(e.target.value)}
            >
              <option value="">Seleccionar texto predefinido...</option>
              {textosActivos.map((t) => (
                <option key={t.id} value={t.id}>{t.nombre}</option>
              ))}
            </select>
          </div>
          <div className={styles.formGroup}>
            <label>Fecha</label>
            <input
              type="date"
              className={styles.input}
              value={form.fecha}
              onChange={(e) => updateFormAndRefresh({ fecha: e.target.value })}
              required
            />
          </div>
          <div className={styles.formGroup}>
            <label>Motivo (obligatorio)</label>
            <textarea
              className={styles.textarea}
              value={form.motivo}
              onChange={(e) => setForm({ ...form, motivo: e.target.value })}
              required
            />
          </div>
          <div className={styles.formGroup}>
            <label>Descripcion adicional</label>
            <textarea
              className={styles.textarea}
              value={form.descripcion}
              onChange={(e) => setForm({ ...form, descripcion: e.target.value })}
            />
          </div>
          {/* Texto de sanción: si hay placeholders → form dinámico, sino → textarea libre */}
          {currentPlaceholders.length > 0 ? (
            <>
              <div className={styles.formGroup}>
                <div className={styles.labelRow}>
                  <label>Campos del documento</label>
                  <button
                    type="button"
                    className={styles.btnHelp}
                    onClick={() => setShowPlaceholderHelp(true)}
                    title="Ver placeholders disponibles"
                  >
                    <HelpCircle size={14} />
                  </button>
                </div>
                <div className={styles.placeholderGrid}>
                  {currentPlaceholders.map((ph) => {
                    const isKnown = ph in knownPlaceholders;
                    return (
                      <div key={ph} className={styles.placeholderField}>
                        <label>
                          {ph.replace(/_/g, ' ')}
                          {isKnown && <span className={styles.autoTag}>auto</span>}
                        </label>
                        <input
                          type="text"
                          className={styles.input}
                          value={placeholderValues[ph] || ''}
                          onChange={(e) => {
                            setPlaceholderValues((prev) => ({ ...prev, [ph]: e.target.value }));
                          }}
                          placeholder={knownPlaceholders[ph] || `Valor para {${ph}}`}
                        />
                      </div>
                    );
                  })}
                </div>
              </div>
              <div className={styles.formGroup}>
                <label>Vista previa del texto</label>
                <div className={styles.textPreview}>
                  {interpolateText(form.texto_sancion, placeholderValues)}
                </div>
              </div>
            </>
          ) : (
            <div className={styles.formGroup}>
              <label>Texto de la sancion (cuerpo del documento)</label>
              <textarea
                className={styles.textarea}
                value={form.texto_sancion}
                onChange={(e) => setForm({ ...form, texto_sancion: e.target.value })}
                rows={6}
                placeholder="Texto completo que aparecera en el documento de sancion..."
              />
            </div>
          )}
          <div className={styles.formRow}>
            <div className={styles.formGroup}>
              <label>Suspension desde</label>
              <input
                type="date"
                className={styles.input}
                value={form.fecha_desde}
                onChange={(e) => updateFormAndRefresh({ fecha_desde: e.target.value })}
              />
            </div>
            <div className={styles.formGroup}>
              <label>Suspension hasta</label>
              <input
                type="date"
                className={styles.input}
                value={form.fecha_hasta}
                onChange={(e) => updateFormAndRefresh({ fecha_hasta: e.target.value })}
              />
            </div>
          </div>
          {error && <div className={styles.formError}>{error}</div>}
        </div>
        <div className="modal-footer-tesla">
          <button className={styles.btnCancel} onClick={onClose}>Cancelar</button>
          <button className={styles.btnSave} onClick={handleSubmit} disabled={saving}>
            {saving ? 'Guardando...' : 'Crear sancion'}
          </button>
        </div>
      </div>
    </div>
  );
}
