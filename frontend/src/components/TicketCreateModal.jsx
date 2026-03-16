import { useState, useEffect, useRef } from 'react';
import { sectoresAPI, ticketsAPI } from '../services/api';
import ModalTesla, { ModalFooterButtons } from './ModalTesla';
import { Paperclip, X, ImagePlus } from 'lucide-react';
import styles from './TicketCreateModal.module.css';

const PRIORIDADES = [
  { value: 'baja', label: 'Baja' },
  { value: 'media', label: 'Media' },
  { value: 'alta', label: 'Alta' },
  { value: 'critica', label: 'Crítica' },
];

/**
 * Renders a dynamic form field based on the schema_campos definition.
 */
const DynamicField = ({ fieldKey, fieldDef, value, onChange }) => {
  const { tipo, label, requerido, opciones, descripcion } = fieldDef;

  const handleChange = (val) => onChange(fieldKey, val);

  switch (tipo) {
    case 'text':
      return (
        <div className={styles.formGroup}>
          <label className={requerido ? styles.required : ''}>{label || fieldKey}</label>
          <textarea
            className={styles.textarea}
            value={value || ''}
            onChange={(e) => handleChange(e.target.value)}
            placeholder={descripcion || ''}
            rows={3}
          />
        </div>
      );
    case 'string':
      return (
        <div className={styles.formGroup}>
          <label className={requerido ? styles.required : ''}>{label || fieldKey}</label>
          <input
            type="text"
            className={styles.input}
            value={value || ''}
            onChange={(e) => handleChange(e.target.value)}
            placeholder={descripcion || ''}
          />
        </div>
      );
    case 'integer':
      return (
        <div className={styles.formGroup}>
          <label className={requerido ? styles.required : ''}>{label || fieldKey}</label>
          <input
            type="number"
            className={styles.input}
            value={value ?? ''}
            onChange={(e) => handleChange(e.target.value ? parseInt(e.target.value, 10) : null)}
            placeholder={descripcion || ''}
            step="1"
          />
        </div>
      );
    case 'decimal':
      return (
        <div className={styles.formGroup}>
          <label className={requerido ? styles.required : ''}>{label || fieldKey}</label>
          <input
            type="number"
            className={styles.input}
            value={value ?? ''}
            onChange={(e) => handleChange(e.target.value ? parseFloat(e.target.value) : null)}
            placeholder={descripcion || ''}
            step="0.01"
          />
        </div>
      );
    case 'select':
      return (
        <div className={styles.formGroup}>
          <label className={requerido ? styles.required : ''}>{label || fieldKey}</label>
          <select
            className={styles.select}
            value={value || ''}
            onChange={(e) => handleChange(e.target.value)}
          >
            <option value="">Seleccionar...</option>
            {(opciones || []).map((opt) => (
              <option key={opt} value={opt}>{opt}</option>
            ))}
          </select>
        </div>
      );
    case 'boolean':
      return (
        <div className={styles.checkboxGroup}>
          <input
            type="checkbox"
            id={`field_${fieldKey}`}
            checked={!!value}
            onChange={(e) => handleChange(e.target.checked)}
          />
          <label htmlFor={`field_${fieldKey}`}>{label || fieldKey}</label>
        </div>
      );
    default:
      return (
        <div className={styles.formGroup}>
          <label className={requerido ? styles.required : ''}>{label || fieldKey}</label>
          <input
            type="text"
            className={styles.input}
            value={value || ''}
            onChange={(e) => handleChange(e.target.value)}
            placeholder={descripcion || ''}
          />
        </div>
      );
  }
};

export default function TicketCreateModal({ isOpen, onClose, onCreated }) {
  const fileInputRef = useRef(null);

  // Options
  const [sectores, setSectores] = useState([]);
  const [tiposTicket, setTiposTicket] = useState([]);
  const [loadingTipos, setLoadingTipos] = useState(false);

  // Form state
  const [sectorId, setSectorId] = useState('');
  const [tipoTicketId, setTipoTicketId] = useState('');
  const [titulo, setTitulo] = useState('');
  const [descripcion, setDescripcion] = useState('');
  const [prioridad, setPrioridad] = useState('media');
  const [metadata, setMetadata] = useState({});
  const [files, setFiles] = useState([]);

  // UI state
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  // Load sectores on mount
  useEffect(() => {
    if (!isOpen) return;
    const fetchSectores = async () => {
      try {
        const { data } = await sectoresAPI.listar();
        setSectores(Array.isArray(data) ? data : []);
      } catch {
        setSectores([]);
      }
    };
    fetchSectores();
  }, [isOpen]);

  // Load tipos_ticket when sector changes
  useEffect(() => {
    if (!sectorId) {
      setTiposTicket([]);
      setTipoTicketId('');
      setMetadata({});
      return;
    }

    const fetchTipos = async () => {
      setLoadingTipos(true);
      try {
        const { data } = await sectoresAPI.listarTiposTicket(sectorId);
        setTiposTicket(Array.isArray(data) ? data : []);
      } catch {
        setTiposTicket([]);
      } finally {
        setLoadingTipos(false);
      }
    };
    fetchTipos();
    setTipoTicketId('');
    setMetadata({});
  }, [sectorId]);

  // Reset metadata when tipo changes
  useEffect(() => {
    setMetadata({});
  }, [tipoTicketId]);

  const selectedTipo = tiposTicket.find((t) => String(t.id) === String(tipoTicketId));
  const schemaCampos = selectedTipo?.schema_campos || {};
  const hasDynamicFields = Object.keys(schemaCampos).length > 0;

  const handleMetadataChange = (key, value) => {
    setMetadata((prev) => ({ ...prev, [key]: value }));
  };

  const handleFileSelect = (e) => {
    const selected = Array.from(e.target.files || []);
    setFiles((prev) => [...prev, ...selected]);
    // Reset input so the same file can be re-selected
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  };

  const handleRemoveFile = (index) => {
    setFiles((prev) => prev.filter((_, i) => i !== index));
  };

  const validateForm = () => {
    if (!sectorId) return 'Selecciona un sector';
    if (!tipoTicketId) return 'Selecciona un tipo de ticket';
    if (!titulo || titulo.trim().length < 5) return 'El título debe tener al menos 5 caracteres';

    // Validate required dynamic fields
    for (const [key, def] of Object.entries(schemaCampos)) {
      if (def.requerido) {
        const val = metadata[key];
        if (val === undefined || val === null || val === '') {
          return `El campo "${def.label || key}" es requerido`;
        }
      }
    }
    return null;
  };

  const handleSubmit = async () => {
    const validationError = validateForm();
    if (validationError) {
      setError(validationError);
      return;
    }

    setSaving(true);
    setError(null);

    try {
      // Create ticket
      const payload = {
        sector_id: parseInt(sectorId, 10),
        tipo_ticket_id: parseInt(tipoTicketId, 10),
        titulo: titulo.trim(),
        descripcion: descripcion.trim() || null,
        prioridad,
        campos_metadata: metadata,
      };

      const { data: ticket } = await ticketsAPI.crear(payload);

      // Upload files if any
      for (const file of files) {
        try {
          await ticketsAPI.subirAdjunto(ticket.id, file);
        } catch {
          // File upload failure is non-blocking
        }
      }

      onCreated?.(ticket);
    } catch (err) {
      const msg = err.response?.data?.detail || 'Error al crear el ticket';
      setError(typeof msg === 'string' ? msg : JSON.stringify(msg));
    } finally {
      setSaving(false);
    }
  };

  const footer = (
    <ModalFooterButtons
      onCancel={onClose}
      onConfirm={handleSubmit}
      confirmText={saving ? 'Creando...' : 'Crear Ticket'}
      confirmLoading={saving}
      confirmDisabled={saving}
    />
  );

  return (
    <ModalTesla
      isOpen={isOpen}
      onClose={onClose}
      title="Nuevo Ticket"
      size="lg"
      footer={footer}
    >
      <div className={styles.formGrid}>
        {error && <div className={styles.formError}>{error}</div>}

        <div className={styles.formRow}>
          <div className={styles.formGroup}>
            <label className={styles.required}>Sector</label>
            <select
              className={styles.select}
              value={sectorId}
              onChange={(e) => setSectorId(e.target.value)}
            >
              <option value="">Seleccionar sector...</option>
              {sectores.map((s) => (
                <option key={s.id} value={s.id}>{s.nombre}</option>
              ))}
            </select>
          </div>

          <div className={styles.formGroup}>
            <label className={styles.required}>Tipo</label>
            {loadingTipos ? (
              <span className={styles.loadingHint}>Cargando tipos...</span>
            ) : (
              <select
                className={styles.select}
                value={tipoTicketId}
                onChange={(e) => setTipoTicketId(e.target.value)}
                disabled={!sectorId}
              >
                <option value="">Seleccionar tipo...</option>
                {tiposTicket.map((t) => (
                  <option key={t.id} value={t.id}>{t.nombre}</option>
                ))}
              </select>
            )}
          </div>
        </div>

        <div className={styles.formGroup}>
          <label className={styles.required}>Título</label>
          <input
            type="text"
            className={styles.input}
            value={titulo}
            onChange={(e) => setTitulo(e.target.value)}
            placeholder="Resumen breve del ticket (min. 5 caracteres)"
            maxLength={255}
          />
        </div>

        <div className={styles.formGroup}>
          <label>Descripción</label>
          <textarea
            className={styles.textarea}
            value={descripcion}
            onChange={(e) => setDescripcion(e.target.value)}
            placeholder="Detalle del problema o solicitud..."
            rows={4}
          />
        </div>

        <div className={styles.formGroup}>
          <label>Prioridad</label>
          <select
            className={styles.select}
            value={prioridad}
            onChange={(e) => setPrioridad(e.target.value)}
          >
            {PRIORIDADES.map((p) => (
              <option key={p.value} value={p.value}>{p.label}</option>
            ))}
          </select>
        </div>

        {/* Dynamic fields from tipo_ticket.schema_campos */}
        {hasDynamicFields && (
          <div className={styles.dynamicFields}>
            <div className={styles.dynamicFieldsTitle}>Campos adicionales</div>
            {Object.entries(schemaCampos).map(([key, def]) => (
              <DynamicField
                key={key}
                fieldKey={key}
                fieldDef={def}
                value={metadata[key]}
                onChange={handleMetadataChange}
              />
            ))}
          </div>
        )}

        {/* File upload */}
        <div className={styles.fileSection}>
          <input
            ref={fileInputRef}
            type="file"
            accept="image/*"
            multiple
            onChange={handleFileSelect}
            className={styles.fileInput}
          />
          <button
            type="button"
            className={styles.btnUpload}
            onClick={() => fileInputRef.current?.click()}
          >
            <ImagePlus size={14} />
            Adjuntar captura
          </button>

          {files.length > 0 && (
            <div className={styles.fileList}>
              {files.map((file, idx) => (
                <div key={idx} className={styles.fileItem}>
                  <span className={styles.fileName}>
                    <Paperclip size={12} />
                    {file.name}
                  </span>
                  <button
                    type="button"
                    className={styles.btnRemoveFile}
                    onClick={() => handleRemoveFile(idx)}
                    aria-label="Quitar archivo"
                  >
                    <X size={12} />
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </ModalTesla>
  );
}
